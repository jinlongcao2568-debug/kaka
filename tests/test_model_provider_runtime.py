from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from shared.model_assist_governance import (
    build_model_assist_governance_summary,
    execute_model_assist_shadow,
)
from shared.model_provider_runtime import (
    MODEL_PROVIDER_MODE_EMERGENCY_OFF,
    MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
    ModelAssistRequest,
    ModelProviderConfig,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
    ProviderHttpResponse,
    execute_governed_model_assist,
    model_provider_readiness,
)


ROOT = Path(__file__).resolve().parents[1]


def _provider_payload(*, source_ref: str = "SNAP-001") -> dict[str, Any]:
    output = {
        "summary": "内部复核摘要。",
        "field_candidates": [
            {
                "field_name": "项目名称",
                "field_value": "测试工程",
                "source_ref": source_ref,
                "confidence": 0.91,
            }
        ],
        "review_flags": [{"code": "HUMAN_REVIEW", "message": "复核原文。"}],
        "draft_text": "仅供内部复核的草稿。",
    }
    return {
        "id": "resp_test_001",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(output, ensure_ascii=False)}],
            }
        ],
        "usage": {"input_tokens": 101, "output_tokens": 42, "total_tokens": 143},
    }


class _RecordingHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    response_count = 0

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("authorization"),
                "body": body,
            }
        )
        type(self).response_count += 1
        if type(self).response_count == 1:
            self.send_response(429)
            self.send_header("content-type", "application/json")
            self.send_header("retry-after", "0")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"rate limited"}}')
            return
        payload = json.dumps(_provider_payload(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


class _StaticTransport:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)
        self.calls = 0

    def post_json(self, **_: Any) -> ProviderHttpResponse:
        self.calls += 1
        return ProviderHttpResponse(status_code=200, headers={}, payload=self.payload)


class ModelProviderRuntimeTests(unittest.TestCase):
    def _request(self, **overrides: Any) -> ModelAssistRequest:
        values = {
            "request_id": "MA-REQUEST-001",
            "task_kind": "CANDIDATE_EXTRACTION",
            "input_data_classification": "PUBLIC",
            "sanitized_input": {"text": "公开来源中的测试工程"},
            "source_refs": ("SNAP-001",),
            "prompt_template_id": "PROMPT_INTERNAL_EXTRACT",
            "prompt_template_version": "1",
        }
        values.update(overrides)
        return ModelAssistRequest(**values)

    def _config(self, secret_file: str, base_url: str) -> ModelProviderConfig:
        return ModelProviderConfig(
            mode=MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
            provider_id="openai_responses",
            base_url=base_url,
            model="gpt-5.6-luna",
            api_key_file=secret_file,
            allowed_hosts=("127.0.0.1",),
            timeout_seconds=5,
            max_attempts=2,
            max_output_tokens=800,
            reasoning_effort="low",
            shadow_approval_state="APPROVED",
            shadow_audit_ref="AUDIT-MODEL-SHADOW-001",
            eval_state="PASSED",
            allow_http_loopback_for_test=True,
        )

    def test_default_and_emergency_modes_do_not_enable_provider_calls(self) -> None:
        self.assertEqual(model_provider_readiness({})["state"], "OFF")
        emergency = ModelProviderConfig.from_environ(
            {
                "KAKA_MODEL_PROVIDER_MODE": "internal-shadow",
                "KAKA_MODEL_PROVIDER_KILL_SWITCH": "true",
            }
        )
        self.assertEqual(emergency.mode, MODEL_PROVIDER_MODE_EMERGENCY_OFF)
        with self.assertRaisesRegex(ModelProviderExecutionError, "not enabled"):
            execute_governed_model_assist(self._request(), config=emergency)

    def test_from_environ_requires_explicit_shadow_gates_and_secret_file(self) -> None:
        with self.assertRaisesRegex(ModelProviderConfigurationError, "approval"):
            ModelProviderConfig.from_environ(
                {
                    "KAKA_MODEL_PROVIDER_MODE": "INTERNAL_SHADOW",
                    "KAKA_MODEL_PROVIDER_ID": "openai_responses",
                    "KAKA_MODEL_PROVIDER_BASE_URL": "https://api.openai.com/v1",
                    "KAKA_MODEL_PROVIDER_ALLOWED_HOSTS": "api.openai.com",
                    "KAKA_MODEL_PROVIDER_MODEL": "gpt-5.6-luna",
                    "KAKA_MODEL_PROVIDER_DIRECT_HTTPS_ALLOWED": "true",
                }
            )

    def test_readiness_accepts_secret_file_without_exposing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = Path(tmp_dir) / "model-api-key"
            secret_file.write_text("sk-test-not-real", encoding="utf-8")
            readiness = model_provider_readiness(
                {
                    "KAKA_MODEL_PROVIDER_MODE": "INTERNAL_SHADOW",
                    "KAKA_MODEL_PROVIDER_ID": "openai_responses",
                    "KAKA_MODEL_PROVIDER_BASE_URL": "https://api.openai.com/v1",
                    "KAKA_MODEL_PROVIDER_ALLOWED_HOSTS": "api.openai.com",
                    "KAKA_MODEL_PROVIDER_MODEL": "gpt-5.6-luna",
                    "KAKA_MODEL_PROVIDER_API_KEY_FILE": str(secret_file),
                    "KAKA_MODEL_PROVIDER_SHADOW_APPROVAL_STATE": "APPROVED",
                    "KAKA_MODEL_PROVIDER_SHADOW_AUDIT_REF": "AUDIT-001",
                    "KAKA_MODEL_PROVIDER_EVAL_STATE": "PASSED",
                    "KAKA_MODEL_PROVIDER_DIRECT_HTTPS_ALLOWED": "true",
                }
            )
        self.assertEqual(readiness["state"], "READY_INTERNAL_SHADOW")
        self.assertNotIn("sk-test-not-real", json.dumps(readiness))
        self.assertFalse(readiness["formal_fact_write_enabled"])
        self.assertFalse(readiness["customer_visible_enabled"])

    def test_secret_file_inside_repository_is_rejected(self) -> None:
        config = ModelProviderConfig(
            mode=MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
            provider_id="openai_responses",
            base_url="https://api.openai.com/v1",
            model="gpt-5.6-luna",
            api_key_file=str(ROOT / "requirements.txt"),
            allowed_hosts=("api.openai.com",),
            shadow_approval_state="APPROVED",
            shadow_audit_ref="AUDIT-001",
            eval_state="PASSED",
            direct_https_allowed=True,
        )
        with self.assertRaisesRegex(ModelProviderConfigurationError, "outside the repository"):
            config.validate()

    def test_actual_http_transport_retries_and_returns_governed_structured_output(self) -> None:
        _RecordingHandler.requests = []
        _RecordingHandler.response_count = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                secret_file = Path(tmp_dir) / "model-api-key"
                secret_file.write_text("sk-test-not-real", encoding="utf-8")
                result = execute_governed_model_assist(
                    self._request(),
                    config=self._config(
                        str(secret_file), f"http://127.0.0.1:{server.server_port}/v1"
                    ),
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(len(_RecordingHandler.requests), 2)
        sent = _RecordingHandler.requests[-1]
        self.assertEqual(sent["path"], "/v1/responses")
        self.assertEqual(sent["authorization"], "Bearer sk-test-not-real")
        self.assertFalse(sent["body"]["store"])
        self.assertNotIn("tools", sent["body"])
        self.assertTrue(sent["body"]["text"]["format"]["strict"])
        self.assertEqual(result["execution_state"], "COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED")
        self.assertEqual(result["model_output"]["field_candidates"][0]["source_ref"], "SNAP-001")
        self.assertTrue(result["governance"]["human_review_required"])
        self.assertFalse(result["governance"]["formal_fact_write_enabled"])
        self.assertFalse(result["governance"]["customer_visible_enabled"])
        self.assertEqual(result["trace"]["total_tokens"], 143)
        self.assertEqual(result["trace"]["attempts_executed"], 2)
        self.assertEqual(result["trace"]["retry_count"], 1)
        self.assertFalse(result["trace"]["external_network_call_executed"])
        self.assertTrue(result["trace"]["provider_transport_invoked"])
        self.assertEqual(result["trace"]["execution_evidence_kind"], "LOCAL_HTTP_PROTOCOL_REPLAY")
        self.assertNotIn("sk-test-not-real", json.dumps(result, ensure_ascii=False))

    def test_external_endpoint_rejects_nonstandard_port_and_unsafe_proxy_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = Path(tmp_dir) / "model-api-key"
            secret_file.write_text("sk-test-not-real", encoding="utf-8")
            base = {
                "mode": MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
                "provider_id": "openai_responses",
                "model": "gpt-5.6-luna",
                "api_key_file": str(secret_file),
                "allowed_hosts": ("api.openai.com",),
                "shadow_approval_state": "APPROVED",
                "shadow_audit_ref": "AUDIT-001",
                "eval_state": "PASSED",
            }
            with self.assertRaisesRegex(ModelProviderConfigurationError, "port 443"):
                ModelProviderConfig(
                    **base,
                    base_url="https://api.openai.com:8443/v1",
                    direct_https_allowed=True,
                ).validate()
            with self.assertRaisesRegex(ModelProviderConfigurationError, "forbidden URL parts"):
                ModelProviderConfig(
                    **base,
                    base_url="https://api.openai.com/v1",
                    proxy_url="http://user:password@egress-proxy:8080",
                ).validate()

    def test_restricted_input_is_blocked_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = Path(tmp_dir) / "model-api-key"
            secret_file.write_text("sk-test-not-real", encoding="utf-8")
            transport = _StaticTransport(_provider_payload())
            with self.assertRaisesRegex(ModelProviderExecutionError, "forbidden fields"):
                execute_governed_model_assist(
                    self._request(sanitized_input={"api_key": "must-not-send"}),
                    config=self._config(str(secret_file), "http://127.0.0.1:9999/v1"),
                    transport=transport,
                )
        self.assertEqual(transport.calls, 0)

    def test_restricted_input_key_normalization_blocks_camel_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = Path(tmp_dir) / "model-api-key"
            secret_file.write_text("sk-test-not-real", encoding="utf-8")
            transport = _StaticTransport(_provider_payload())
            with self.assertRaisesRegex(ModelProviderExecutionError, "forbidden fields"):
                execute_governed_model_assist(
                    self._request(sanitized_input={"customerPersonalData": "must-not-send"}),
                    config=self._config(str(secret_file), "http://127.0.0.1:9999/v1"),
                    transport=transport,
                )
        self.assertEqual(transport.calls, 0)

    def test_untraceable_candidate_is_rejected_after_schema_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = Path(tmp_dir) / "model-api-key"
            secret_file.write_text("sk-test-not-real", encoding="utf-8")
            with self.assertRaisesRegex(ModelProviderExecutionError, "source_ref"):
                execute_governed_model_assist(
                    self._request(),
                    config=self._config(str(secret_file), "http://127.0.0.1:9999/v1"),
                    transport=_StaticTransport(_provider_payload(source_ref="HALLUCINATED-SOURCE")),
                )

    def test_existing_governance_carrier_can_invoke_only_governed_shadow_task(self) -> None:
        carrier = build_model_assist_governance_summary(
            assist_scope="stage4_public_verification_review",
            source_refs={"snapshot_id": "SNAP-001"},
            prompt_purpose="public_evidence_summary_and_review_triage_assist",
            output_kind="llm_assisted_evidence_summary",
            evidence_refs=["SNAP-001"],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = Path(tmp_dir) / "model-api-key"
            secret_file.write_text("sk-test-not-real", encoding="utf-8")
            result = execute_model_assist_shadow(
                carrier,
                input_data_classification="PUBLIC",
                config=self._config(str(secret_file), "http://127.0.0.1:9999/v1"),
                transport=_StaticTransport(_provider_payload()),
            )
        self.assertEqual(result["execution_state"], "COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED")
        self.assertFalse(result["governance"]["formal_fact_write_enabled"])


if __name__ == "__main__":
    unittest.main()
