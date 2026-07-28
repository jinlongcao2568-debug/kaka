from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import httpx

from shared.contract_loader import load_contract


MODEL_PROVIDER_RUNTIME_CONTRACT_REF = "contracts/model/model_provider_runtime_contract.json"
MODEL_PROVIDER_MODE_OFF = "OFF"
MODEL_PROVIDER_MODE_INTERNAL_SHADOW = "INTERNAL_SHADOW"
MODEL_PROVIDER_MODE_EMERGENCY_OFF = "EMERGENCY_OFF"
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_DETERMINISTIC_FALLBACK_CATEGORIES = frozenset(
    {
        "PROVIDER_TIMEOUT",
        "PROVIDER_NETWORK_ERROR",
        "PROVIDER_AUTH_ERROR",
        "PROVIDER_RATE_OR_QUOTA_LIMIT",
        "PROVIDER_TRANSIENT_ERROR",
        "PROVIDER_REQUEST_REJECTED",
        "INVALID_PROVIDER_RESPONSE",
        "INCOMPLETE_PROVIDER_RESPONSE",
        "MODEL_REFUSAL",
        "INVALID_STRUCTURED_OUTPUT",
        "UNTRACEABLE_MODEL_OUTPUT",
        "UNSAFE_MODEL_OUTPUT",
    }
)
_UNSAFE_MODEL_OUTPUT_PATTERNS = (
    re.compile(r"(?:无需|不需要)人工(?:复核|审核)"),
    re.compile(r"(?:绕过|跳过)(?:证据|审批|人工复核|规则)(?:门|流程|审核)?"),
    re.compile(r"(?:保证|确保)(?:中标|成交|无风险|合法合规)"),
    re.compile(r"(?:不存在任何|绝对没有|完全没有)(?:风险|问题|变更|违法)"),
    re.compile(r"(?:system\s+prompt|chain\s+of\s+thought|ignore\s+(?:all\s+)?previous\s+instructions)", re.I),
    re.compile(r"(?:bypass|skip)\s+(?:approval|evidence|human\s+review)", re.I),
    re.compile(r"(?:guaranteed|definitive)\s+(?:legal|compliant|safe)", re.I),
)
_SECRET_OUTPUT_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
)


class ModelProviderConfigurationError(ValueError):
    pass


class ModelProviderExecutionError(RuntimeError):
    def __init__(self, category: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code


@dataclass(frozen=True)
class ModelProviderConfig:
    mode: str = MODEL_PROVIDER_MODE_OFF
    provider_id: str = ""
    base_url: str = ""
    model: str = ""
    api_key_file: str = ""
    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    max_attempts: int = 2
    max_output_tokens: int = 1800
    reasoning_effort: str = "low"
    shadow_approval_state: str = ""
    shadow_audit_ref: str = ""
    eval_state: str = ""
    proxy_url: str | None = None
    private_edge_required: bool = False
    direct_https_allowed: bool = False
    allow_http_loopback_for_test: bool = False

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "ModelProviderConfig":
        env = dict(os.environ if environ is None else environ)
        mode = _normalized_mode(env.get("KAKA_MODEL_PROVIDER_MODE"))
        if _env_bool(env.get("KAKA_MODEL_PROVIDER_KILL_SWITCH")):
            mode = MODEL_PROVIDER_MODE_EMERGENCY_OFF
        config = cls(
            mode=mode,
            provider_id=str(env.get("KAKA_MODEL_PROVIDER_ID") or "").strip(),
            base_url=str(env.get("KAKA_MODEL_PROVIDER_BASE_URL") or "").strip(),
            model=str(env.get("KAKA_MODEL_PROVIDER_MODEL") or "").strip(),
            api_key_file=str(env.get("KAKA_MODEL_PROVIDER_API_KEY_FILE") or "").strip(),
            allowed_hosts=tuple(
                item.strip().lower().rstrip(".")
                for item in str(env.get("KAKA_MODEL_PROVIDER_ALLOWED_HOSTS") or "").split(",")
                if item.strip()
            ),
            timeout_seconds=_bounded_float(
                env.get("KAKA_MODEL_PROVIDER_TIMEOUT_SECONDS"), 30.0, 1.0, 120.0
            ),
            max_attempts=_bounded_int(env.get("KAKA_MODEL_PROVIDER_MAX_ATTEMPTS"), 2, 1, 3),
            max_output_tokens=_bounded_int(
                env.get("KAKA_MODEL_PROVIDER_MAX_OUTPUT_TOKENS"), 1800, 128, 8000
            ),
            reasoning_effort=str(
                env.get("KAKA_MODEL_PROVIDER_REASONING_EFFORT") or "low"
            ).strip().lower(),
            shadow_approval_state=str(
                env.get("KAKA_MODEL_PROVIDER_SHADOW_APPROVAL_STATE") or ""
            ).strip().upper(),
            shadow_audit_ref=str(
                env.get("KAKA_MODEL_PROVIDER_SHADOW_AUDIT_REF") or ""
            ).strip(),
            eval_state=str(env.get("KAKA_MODEL_PROVIDER_EVAL_STATE") or "").strip().upper(),
            proxy_url=str(env.get("KAKA_CONTROLLED_EGRESS_PROXY_URL") or "").strip() or None,
            private_edge_required=_env_bool(env.get("KAKA_PRIVATE_EDGE_REQUIRED")),
            direct_https_allowed=_env_bool(
                env.get("KAKA_MODEL_PROVIDER_DIRECT_HTTPS_ALLOWED")
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode in {MODEL_PROVIDER_MODE_OFF, MODEL_PROVIDER_MODE_EMERGENCY_OFF}:
            return
        if self.mode != MODEL_PROVIDER_MODE_INTERNAL_SHADOW:
            raise ModelProviderConfigurationError("unsupported model provider mode")
        if self.provider_id not in {"openai_responses", "openai_compatible_responses"}:
            raise ModelProviderConfigurationError("model provider_id is not registered")
        if not _MODEL_PATTERN.fullmatch(self.model):
            raise ModelProviderConfigurationError("model id is missing or invalid")
        if self.reasoning_effort not in {"none", "low", "medium"}:
            raise ModelProviderConfigurationError("reasoning effort must be none, low, or medium")
        if self.shadow_approval_state != "APPROVED":
            raise ModelProviderConfigurationError("internal shadow approval is required")
        if not self.shadow_audit_ref:
            raise ModelProviderConfigurationError("internal shadow audit ref is required")
        if self.eval_state != "PASSED":
            raise ModelProviderConfigurationError("model eval state must be PASSED")
        _validated_endpoint(self)
        _read_secret_file(self.api_key_file)


@dataclass(frozen=True)
class ModelAssistRequest:
    request_id: str
    task_kind: str
    input_data_classification: str
    sanitized_input: Mapping[str, Any]
    source_refs: tuple[str, ...]
    prompt_template_id: str
    prompt_template_version: str


@dataclass(frozen=True)
class ProviderHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    payload: Mapping[str, Any]


class ModelProviderTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
        proxy_url: str | None,
    ) -> ProviderHttpResponse: ...


class HttpxModelProviderTransport:
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
        proxy_url: str | None,
    ) -> ProviderHttpResponse:
        with httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            proxy=proxy_url,
            follow_redirects=False,
        ) as client:
            response = client.post(url, headers=dict(headers), json=dict(payload))
        try:
            body = response.json()
        except ValueError as exc:
            raise ModelProviderExecutionError(
                "INVALID_PROVIDER_RESPONSE",
                "model provider returned non-JSON response",
                status_code=response.status_code,
            ) from exc
        if not isinstance(body, Mapping):
            raise ModelProviderExecutionError(
                "INVALID_PROVIDER_RESPONSE",
                "model provider response must be a JSON object",
                status_code=response.status_code,
            )
        return ProviderHttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            payload=dict(body),
        )


def model_provider_readiness(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_env = dict(os.environ if environ is None else environ)
    try:
        config = ModelProviderConfig.from_environ(source_env)
    except (ModelProviderConfigurationError, OSError) as exc:
        return {
            "state": "BLOCKED_CONFIGURATION",
            "mode": _normalized_mode(source_env.get("KAKA_MODEL_PROVIDER_MODE")),
            "configured": False,
            "real_model_provider_call_enabled": False,
            "blocking_reason": str(exc),
        }
    return {
        "state": (
            "READY_INTERNAL_SHADOW"
            if config.mode == MODEL_PROVIDER_MODE_INTERNAL_SHADOW
            else config.mode
        ),
        "mode": config.mode,
        "provider_id": config.provider_id or None,
        "model": config.model or None,
        "configured": config.mode == MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
        "real_model_provider_call_enabled": config.mode == MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
        "customer_visible_enabled": False,
        "formal_fact_write_enabled": False,
        "tool_calling_enabled": False,
        "store": False,
    }


def execute_governed_model_assist(
    request: ModelAssistRequest,
    *,
    config: ModelProviderConfig | None = None,
    transport: ModelProviderTransport | None = None,
) -> dict[str, Any]:
    active_config = config or ModelProviderConfig.from_environ()
    active_config.validate()
    if active_config.mode != MODEL_PROVIDER_MODE_INTERNAL_SHADOW:
        raise ModelProviderExecutionError(
            "PROVIDER_DISABLED",
            "model provider is not enabled for internal shadow execution",
        )
    contract = _runtime_contract()
    _validate_request(request, contract)
    endpoint = _validated_endpoint(active_config)
    api_key = _read_secret_file(active_config.api_key_file)
    schema = dict(contract["output_schema"])
    request_document = {
        "task_kind": request.task_kind,
        "input_data_classification": request.input_data_classification,
        "sanitized_input": dict(request.sanitized_input),
        "source_refs": list(request.source_refs),
    }
    canonical_request = json.dumps(
        request_document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    request_sha256 = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    payload = {
        "model": active_config.model,
        "instructions": (
            "你只生成内部人工复核候选或草稿。不得把未给出的内容写成事实，"
            "不得输出法律结论，不得建议绕过证据门、审批门或人工复核。"
            "field_candidates 的 source_ref 必须来自输入 source_refs。"
        ),
        "input": canonical_request,
        "reasoning": {"effort": active_config.reasoning_effort},
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "kaka_governed_model_assist",
                "strict": True,
                "schema": schema,
            },
        },
        "max_output_tokens": active_config.max_output_tokens,
        "store": False,
        "safety_identifier": "kaka-" + hashlib.sha256(
            request.request_id.encode("utf-8")
        ).hexdigest()[:32],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Client-Request-Id": request.request_id,
    }
    runtime_transport = transport or HttpxModelProviderTransport()
    started = time.perf_counter()
    response: ProviderHttpResponse | None = None
    attempts_executed = 0
    for attempt in range(1, active_config.max_attempts + 1):
        attempts_executed = attempt
        try:
            response = runtime_transport.post_json(
                url=endpoint,
                headers=headers,
                payload=payload,
                timeout_seconds=active_config.timeout_seconds,
                proxy_url=active_config.proxy_url,
            )
        except httpx.TimeoutException as exc:
            if attempt >= active_config.max_attempts:
                raise ModelProviderExecutionError(
                    "PROVIDER_TIMEOUT", "model provider request timed out"
                ) from exc
            _retry_wait(attempt, None)
            continue
        except httpx.NetworkError as exc:
            if attempt >= active_config.max_attempts:
                raise ModelProviderExecutionError(
                    "PROVIDER_NETWORK_ERROR", "model provider network request failed"
                ) from exc
            _retry_wait(attempt, None)
            continue
        if 200 <= response.status_code < 300:
            break
        if response.status_code not in _RETRYABLE_STATUS_CODES or attempt >= active_config.max_attempts:
            raise ModelProviderExecutionError(
                _http_error_category(response.status_code),
                "model provider request failed",
                status_code=response.status_code,
            )
        _retry_wait(attempt, response.headers.get("retry-after"))
    if response is None:
        raise ModelProviderExecutionError("PROVIDER_NETWORK_ERROR", "model provider returned no response")
    model_output = _extract_structured_output(response.payload)
    _validate_model_output(model_output, set(request.source_refs))
    response_sha256 = hashlib.sha256(
        json.dumps(model_output, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()
    usage = dict(response.payload.get("usage") or {})
    external_network_call_executed, execution_evidence_kind = _transport_evidence(
        endpoint=endpoint,
        injected_transport=transport,
        runtime_transport=runtime_transport,
    )
    return {
        "execution_state": "COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED",
        "provider_id": active_config.provider_id,
        "model": active_config.model,
        "provider_response_id": str(response.payload.get("id") or ""),
        "model_output": model_output,
        "governance": {
            "internal_shadow_only": True,
            "human_review_required": True,
            "model_output_not_final_fact": True,
            "model_output_not_legal_conclusion": True,
            "formal_fact_write_enabled": False,
            "customer_visible_enabled": False,
            "tool_calling_enabled": False,
            "store": False,
            "shadow_audit_ref": active_config.shadow_audit_ref,
        },
        "trace": {
            "request_id": request.request_id,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "prompt_template_id": request.prompt_template_id,
            "prompt_template_version": request.prompt_template_version,
            "input_data_classification": request.input_data_classification,
            "source_refs": list(request.source_refs),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "attempts_executed": attempts_executed,
            "retry_count": max(attempts_executed - 1, 0),
            "provider_transport_invoked": True,
            "external_network_call_executed": external_network_call_executed,
            "execution_evidence_kind": execution_evidence_kind,
            "raw_prompt_persisted": False,
            "raw_provider_response_persisted": False,
        },
    }


def execute_governed_model_assist_with_fallback(
    request: ModelAssistRequest,
    *,
    config: ModelProviderConfig | None = None,
    transport: ModelProviderTransport | None = None,
) -> dict[str, Any]:
    """Execute internal shadow assist and safely fall back to the deterministic review chain.

    Configuration, request validation, and restricted-input failures remain fail-closed. Provider,
    schema, traceability, refusal, and unsafe-output failures return a content-free review marker;
    they never turn failed model content into a fact, citation, customer output, or formal write.
    """

    active_config = config or ModelProviderConfig.from_environ()
    started = time.perf_counter()
    try:
        return execute_governed_model_assist(
            request,
            config=active_config,
            transport=transport,
        )
    except ModelProviderExecutionError as exc:
        if exc.category not in _DETERMINISTIC_FALLBACK_CATEGORIES:
            raise
        request_document = {
            "task_kind": request.task_kind,
            "input_data_classification": request.input_data_classification,
            "sanitized_input": dict(request.sanitized_input),
            "source_refs": list(request.source_refs),
        }
        request_sha256 = hashlib.sha256(
            json.dumps(
                request_document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        endpoint = _validated_endpoint(active_config)
        external_network_call_executed, execution_evidence_kind = _transport_evidence(
            endpoint=endpoint,
            injected_transport=transport,
            runtime_transport=transport,
        )
        attempts_executed = (
            active_config.max_attempts
            if exc.category
            in {
                "PROVIDER_TIMEOUT",
                "PROVIDER_NETWORK_ERROR",
                "PROVIDER_RATE_OR_QUOTA_LIMIT",
                "PROVIDER_TRANSIENT_ERROR",
            }
            else 1
        )
        return {
            "execution_state": "FALLBACK_DETERMINISTIC_REVIEW_REQUIRED",
            "provider_id": active_config.provider_id,
            "model": active_config.model,
            "provider_response_id": "",
            "model_output": {
                "summary": (
                    "模型辅助不可用；本轮已退回确定性对象、登记来源和人工复核链。"
                    "不得根据本次失败形成事实或放行结论。"
                ),
                "field_candidates": [],
                "review_flags": [
                    {
                        "code": exc.category,
                        "message": "模型辅助失败，已执行无模型内容的确定性降级。",
                    }
                ],
                "draft_text": "",
            },
            "failure": {
                "category": exc.category,
                "status_code": exc.status_code,
                "raw_error_persisted": False,
                "model_content_reused": False,
            },
            "governance": {
                "internal_shadow_only": True,
                "human_review_required": True,
                "deterministic_fallback_executed": True,
                "model_output_not_final_fact": True,
                "model_output_not_legal_conclusion": True,
                "formal_fact_write_enabled": False,
                "customer_visible_enabled": False,
                "tool_calling_enabled": False,
                "store": False,
                "shadow_audit_ref": active_config.shadow_audit_ref,
            },
            "trace": {
                "request_id": request.request_id,
                "request_sha256": request_sha256,
                "response_sha256": None,
                "prompt_template_id": request.prompt_template_id,
                "prompt_template_version": request.prompt_template_version,
                "input_data_classification": request.input_data_classification,
                "source_refs": list(request.source_refs),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "attempts_executed": attempts_executed,
                "retry_count": max(attempts_executed - 1, 0),
                "provider_transport_invoked": True,
                "external_network_call_executed": external_network_call_executed,
                "execution_evidence_kind": execution_evidence_kind,
                "raw_prompt_persisted": False,
                "raw_provider_response_persisted": False,
            },
        }


def _runtime_contract() -> dict[str, Any]:
    return dict(load_contract(MODEL_PROVIDER_RUNTIME_CONTRACT_REF))


def _validate_request(request: ModelAssistRequest, contract: Mapping[str, Any]) -> None:
    if request.task_kind not in set(contract.get("allowed_task_kinds") or []):
        raise ModelProviderExecutionError("TASK_KIND_BLOCKED", "model assist task kind is blocked")
    if request.input_data_classification not in set(
        contract.get("allowed_input_classifications") or []
    ):
        raise ModelProviderExecutionError(
            "INPUT_CLASSIFICATION_BLOCKED", "model input classification is blocked"
        )
    if not isinstance(request.request_id, str) or not request.request_id or len(request.request_id) > 200:
        raise ModelProviderExecutionError("INVALID_REQUEST", "model request_id is invalid")
    if not isinstance(request.sanitized_input, Mapping):
        raise ModelProviderExecutionError("INVALID_REQUEST", "sanitized model input must be an object")
    if len(request.source_refs) > 100 or any(
        not isinstance(ref, str) or not ref or len(ref) > 512 for ref in request.source_refs
    ):
        raise ModelProviderExecutionError("INVALID_REQUEST", "model source_refs are invalid")
    if len(set(request.source_refs)) != len(request.source_refs):
        raise ModelProviderExecutionError("INVALID_REQUEST", "model source_refs must be unique")
    if not isinstance(request.prompt_template_id, str) or not request.prompt_template_id:
        raise ModelProviderExecutionError("INVALID_REQUEST", "prompt template id is invalid")
    if not isinstance(request.prompt_template_version, str) or not request.prompt_template_version:
        raise ModelProviderExecutionError("INVALID_REQUEST", "prompt template version is invalid")
    try:
        serialized = json.dumps(request.sanitized_input, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ModelProviderExecutionError(
            "INVALID_REQUEST", "sanitized model input must be JSON serializable"
        ) from exc
    if len(serialized.encode("utf-8")) > 64 * 1024:
        raise ModelProviderExecutionError("INPUT_TOO_LARGE", "sanitized model input exceeds 64 KiB")
    forbidden = {
        _normalized_sensitive_key(str(item))
        for item in contract.get("forbidden_input_keys") or []
    }
    violations: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key).strip()
                child = f"{path}.{key_text}" if path else key_text
                if _normalized_sensitive_key(key_text) in forbidden:
                    violations.append(child)
                visit(item, child)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(request.sanitized_input, "")
    if violations:
        raise ModelProviderExecutionError(
            "RESTRICTED_MODEL_INPUT",
            "model input contains forbidden fields: " + ", ".join(sorted(violations)),
        )


def _extract_structured_output(payload: Mapping[str, Any]) -> dict[str, Any]:
    if str(payload.get("status") or "completed") != "completed":
        raise ModelProviderExecutionError("INCOMPLETE_PROVIDER_RESPONSE", "model response is incomplete")
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or []:
            if isinstance(content, Mapping) and content.get("type") == "refusal":
                raise ModelProviderExecutionError("MODEL_REFUSAL", "model refused the request")
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, Mapping):
                continue
            if content.get("type") == "output_text":
                try:
                    parsed = json.loads(str(content.get("text") or ""))
                except json.JSONDecodeError as exc:
                    raise ModelProviderExecutionError(
                        "INVALID_STRUCTURED_OUTPUT", "model output is not valid JSON"
                    ) from exc
                if isinstance(parsed, Mapping):
                    return dict(parsed)
    raise ModelProviderExecutionError(
        "INVALID_PROVIDER_RESPONSE", "model response has no output_text message"
    )


def _validate_model_output(output: Mapping[str, Any], source_refs: set[str]) -> None:
    if set(output) != {"summary", "field_candidates", "review_flags", "draft_text"}:
        raise ModelProviderExecutionError(
            "INVALID_STRUCTURED_OUTPUT", "model output keys do not match the governed schema"
        )
    _bounded_text(output.get("summary"), 4000, "summary")
    _bounded_text(output.get("draft_text"), 8000, "draft_text")
    candidates = output.get("field_candidates")
    flags = output.get("review_flags")
    if not isinstance(candidates, list) or len(candidates) > 50:
        raise ModelProviderExecutionError("INVALID_STRUCTURED_OUTPUT", "field_candidates is invalid")
    if not isinstance(flags, list) or len(flags) > 50:
        raise ModelProviderExecutionError("INVALID_STRUCTURED_OUTPUT", "review_flags is invalid")
    for item in candidates:
        if not isinstance(item, Mapping) or set(item) != {
            "field_name",
            "field_value",
            "source_ref",
            "confidence",
        }:
            raise ModelProviderExecutionError("INVALID_STRUCTURED_OUTPUT", "field candidate is invalid")
        _bounded_text(item.get("field_name"), 160, "field_name")
        _bounded_text(item.get("field_value"), 4000, "field_value")
        source_ref = _bounded_text(item.get("source_ref"), 512, "source_ref")
        if source_ref not in source_refs:
            raise ModelProviderExecutionError(
                "UNTRACEABLE_MODEL_OUTPUT", "field candidate source_ref is not in the request"
            )
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ModelProviderExecutionError("INVALID_STRUCTURED_OUTPUT", "confidence is invalid")
        if not 0 <= float(confidence) <= 1:
            raise ModelProviderExecutionError("INVALID_STRUCTURED_OUTPUT", "confidence is out of range")
    for item in flags:
        if not isinstance(item, Mapping) or set(item) != {"code", "message"}:
            raise ModelProviderExecutionError("INVALID_STRUCTURED_OUTPUT", "review flag is invalid")
        _bounded_text(item.get("code"), 160, "review flag code")
        _bounded_text(item.get("message"), 2000, "review flag message")
    _validate_model_output_safety(output)


def _validate_model_output_safety(output: Mapping[str, Any]) -> None:
    values: list[str] = [str(output.get("summary") or ""), str(output.get("draft_text") or "")]
    for item in output.get("field_candidates") or []:
        if isinstance(item, Mapping):
            values.extend((str(item.get("field_name") or ""), str(item.get("field_value") or "")))
    for item in output.get("review_flags") or []:
        if isinstance(item, Mapping):
            values.extend((str(item.get("code") or ""), str(item.get("message") or "")))
    combined = "\n".join(values)
    if any(pattern.search(combined) for pattern in _UNSAFE_MODEL_OUTPUT_PATTERNS):
        raise ModelProviderExecutionError(
            "UNSAFE_MODEL_OUTPUT",
            "model output contains a prohibited conclusion or instruction leak",
        )
    if any(pattern.search(combined) for pattern in _SECRET_OUTPUT_PATTERNS):
        raise ModelProviderExecutionError(
            "UNSAFE_MODEL_OUTPUT",
            "model output contains credential-like material",
        )


def _transport_evidence(
    *,
    endpoint: str,
    injected_transport: ModelProviderTransport | None,
    runtime_transport: ModelProviderTransport | None,
) -> tuple[bool, str]:
    explicit_external = getattr(runtime_transport, "external_network_call_executed", None)
    explicit_kind = str(getattr(runtime_transport, "execution_evidence_kind", "") or "")
    if isinstance(explicit_external, bool):
        return explicit_external, explicit_kind or (
            "EXTERNAL_PROVIDER_SHADOW" if explicit_external else "OFFLINE_PROTOCOL_REPLAY"
        )
    host = str(urlsplit(endpoint).hostname or "").lower().rstrip(".")
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    external = injected_transport is None and not loopback
    if external:
        return True, "EXTERNAL_PROVIDER_SHADOW"
    if injected_transport is None and loopback:
        return False, "LOCAL_HTTP_PROTOCOL_REPLAY"
    return False, "INJECTED_TRANSPORT_REPLAY_UNATTESTED"


def _validated_endpoint(config: ModelProviderConfig) -> str:
    parsed = urlsplit(config.base_url)
    host = str(parsed.hostname or "").lower().rstrip(".")
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelProviderConfigurationError("model provider base_url contains forbidden URL parts")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and loopback and config.allow_http_loopback_for_test
    ):
        raise ModelProviderConfigurationError("model provider base_url must use HTTPS")
    if not host or host not in set(config.allowed_hosts) or "*" in config.allowed_hosts:
        raise ModelProviderConfigurationError("model provider host is not explicitly allowed")
    if parsed.path.rstrip("/") not in {"", "/v1"}:
        raise ModelProviderConfigurationError("model provider base_url path must be empty or /v1")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ModelProviderConfigurationError("model provider base_url port is invalid") from exc
    if not loopback and port not in {None, 443}:
        raise ModelProviderConfigurationError("external model provider must use HTTPS port 443")
    if config.proxy_url:
        _validate_proxy_url(config.proxy_url)
    if not loopback and not config.proxy_url and not config.direct_https_allowed:
        raise ModelProviderConfigurationError(
            "external model provider requires controlled egress proxy or explicit direct HTTPS approval"
        )
    return config.base_url.rstrip("/") + "/responses"


def _validate_proxy_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ModelProviderConfigurationError("controlled egress proxy URL is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelProviderConfigurationError("controlled egress proxy URL contains forbidden URL parts")
    if parsed.path not in {"", "/"}:
        raise ModelProviderConfigurationError("controlled egress proxy URL path must be empty")
    try:
        parsed.port
    except ValueError as exc:
        raise ModelProviderConfigurationError("controlled egress proxy URL port is invalid") from exc


def _read_secret_file(value: str) -> str:
    if not value:
        raise ModelProviderConfigurationError("model provider API key secret file is required")
    path = Path(value).resolve()
    repository_root = Path(__file__).resolve().parents[2]
    if path == repository_root or repository_root in path.parents:
        raise ModelProviderConfigurationError(
            "model provider API key secret file must be outside the repository"
        )
    if not path.is_file():
        raise ModelProviderConfigurationError("model provider API key secret file is missing")
    if path.stat().st_size > 8192:
        raise ModelProviderConfigurationError("model provider API key secret file exceeds 8 KiB")
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except UnicodeError as exc:
        raise ModelProviderConfigurationError(
            "model provider API key secret file must be UTF-8"
        ) from exc
    if not secret or "\n" in secret or "\r" in secret:
        raise ModelProviderConfigurationError(
            "model provider API key secret file must contain one non-empty line"
        )
    return secret


def _retry_wait(attempt: int, retry_after: str | None) -> None:
    delay = min(0.25 * (2 ** (attempt - 1)), 1.0)
    if retry_after:
        try:
            delay = min(max(float(retry_after), 0.0), 2.0)
        except ValueError:
            pass
    time.sleep(delay)


def _http_error_category(status_code: int) -> str:
    if status_code in {401, 403}:
        return "PROVIDER_AUTH_ERROR"
    if status_code == 429:
        return "PROVIDER_RATE_OR_QUOTA_LIMIT"
    if status_code >= 500:
        return "PROVIDER_TRANSIENT_ERROR"
    return "PROVIDER_REQUEST_REJECTED"


def _bounded_text(value: Any, maximum: int, label: str) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ModelProviderExecutionError("INVALID_STRUCTURED_OUTPUT", f"{label} is invalid")
    return value


def _normalized_mode(value: str | None) -> str:
    normalized = str(value or MODEL_PROVIDER_MODE_OFF).strip().upper().replace("-", "_")
    return normalized or MODEL_PROVIDER_MODE_OFF


def _env_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _normalized_sensitive_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _bounded_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value)) if value not in (None, "") else default
    except ValueError as exc:
        raise ModelProviderConfigurationError("model provider integer setting is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise ModelProviderConfigurationError("model provider integer setting is out of range")
    return parsed


def _bounded_float(value: str | None, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(str(value)) if value not in (None, "") else default
    except ValueError as exc:
        raise ModelProviderConfigurationError("model provider timeout setting is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise ModelProviderConfigurationError("model provider timeout setting is out of range")
    return parsed


__all__ = [
    "MODEL_PROVIDER_MODE_EMERGENCY_OFF",
    "MODEL_PROVIDER_MODE_INTERNAL_SHADOW",
    "MODEL_PROVIDER_MODE_OFF",
    "MODEL_PROVIDER_RUNTIME_CONTRACT_REF",
    "HttpxModelProviderTransport",
    "ModelAssistRequest",
    "ModelProviderConfig",
    "ModelProviderConfigurationError",
    "ModelProviderExecutionError",
    "ModelProviderTransport",
    "ProviderHttpResponse",
    "execute_governed_model_assist",
    "execute_governed_model_assist_with_fallback",
    "model_provider_readiness",
]
