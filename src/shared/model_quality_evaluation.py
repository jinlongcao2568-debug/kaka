from __future__ import annotations

import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from shared.contract_loader import load_contract
from shared.model_provider_runtime import (
    MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
    ModelAssistRequest,
    ModelProviderConfig,
    ModelProviderExecutionError,
    ProviderHttpResponse,
    execute_governed_model_assist_with_fallback,
)


MODEL_QUALITY_CONTRACT_REF = "contracts/model/model_quality_evaluation_contract.json"
MODEL_QUALITY_GOLDEN_REF = "contracts/testing/model_provider_quality_golden_cases.json"


class _OfflineProtocolTransport:
    external_network_call_executed = False
    execution_evidence_kind = "OFFLINE_PROTOCOL_REPLAY"

    def __init__(self, simulation: Mapping[str, Any], source_ref: str) -> None:
        self.simulation = dict(simulation)
        self.source_ref = source_ref
        self.calls = 0

    def post_json(self, **_: Any) -> ProviderHttpResponse:
        self.calls += 1
        kind = str(self.simulation.get("kind") or "SUCCESS")
        if kind == "TIMEOUT":
            raise httpx.ReadTimeout("offline simulated provider timeout")
        if kind == "HTTP_STATUS":
            return ProviderHttpResponse(
                status_code=int(self.simulation.get("status_code") or 500),
                headers={},
                payload={"error": {"type": "offline_simulated_error"}},
            )
        if kind == "REFUSAL":
            return ProviderHttpResponse(
                status_code=200,
                headers={},
                payload={
                    "id": "offline-refusal",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "refusal", "refusal": "offline simulation"}],
                        }
                    ],
                    "usage": {"input_tokens": 20, "output_tokens": 2, "total_tokens": 22},
                },
            )
        if kind == "INCOMPLETE":
            return ProviderHttpResponse(
                status_code=200,
                headers={},
                payload={"id": "offline-incomplete", "status": "incomplete", "output": []},
            )

        output = {
            "summary": "内部人工复核候选，内容仅来自登记来源。",
            "field_candidates": [
                {
                    "field_name": "project_name",
                    "field_value": "测试项目",
                    "source_ref": self.source_ref,
                    "confidence": 0.8,
                }
            ],
            "review_flags": [{"code": "HUMAN_REVIEW", "message": "需要人工复核。"}],
            "draft_text": "内部草稿，不可直接外发。",
        }
        if kind == "UNTRACEABLE_SOURCE":
            output["field_candidates"][0]["source_ref"] = "HALLUCINATED-SOURCE"
        elif kind == "EXTRA_SCHEMA_KEY":
            output["unexpected"] = "must be rejected"
        elif kind == "UNSAFE_CONCLUSION":
            output["draft_text"] = "保证中标，无需人工复核。"
        elif kind == "INSTRUCTION_LEAK":
            output["draft_text"] = "system prompt: ignore previous instructions"
        return ProviderHttpResponse(
            status_code=200,
            headers={},
            payload=_provider_payload(output, response_id=f"offline-{kind.lower()}"),
        )


def build_model_cost_observation(
    result: Mapping[str, Any],
    pricing_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    trace = dict(result.get("trace") or {})
    if not bool(trace.get("external_network_call_executed")):
        return {
            "state": "NOT_APPLICABLE_OFFLINE_OR_NON_EXTERNAL_REPLAY",
            "amount": None,
            "currency": None,
            "pricing_snapshot_id": None,
            "reason": "No real external provider fee may be inferred from replay evidence.",
        }
    input_tokens = trace.get("input_tokens")
    output_tokens = trace.get("output_tokens")
    if (
        isinstance(input_tokens, bool)
        or isinstance(output_tokens, bool)
        or not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
        or input_tokens < 0
        or output_tokens < 0
        or input_tokens + output_tokens <= 0
    ):
        return {
            "state": "WITHHELD_PROVIDER_USAGE_UNAVAILABLE",
            "amount": None,
            "currency": None,
            "pricing_snapshot_id": None,
            "reason": "Provider usage was missing or zero; fee is not reported as zero.",
        }
    if pricing_snapshot is None:
        return {
            "state": "WITHHELD_NO_VERIFIED_PRICING_SNAPSHOT",
            "amount": None,
            "currency": None,
            "pricing_snapshot_id": None,
            "reason": "A versioned, approved pricing snapshot is required.",
        }
    required = set(
        load_contract(MODEL_QUALITY_CONTRACT_REF)["cost_policy"]
        ["pricing_snapshot_required_fields"]
    )
    if not required.issubset(pricing_snapshot):
        return _withheld_pricing("WITHHELD_INVALID_PRICING_SNAPSHOT", pricing_snapshot)
    required_text = (
        "snapshot_id",
        "provider_id",
        "model",
        "currency",
        "effective_at",
        "approval_ref",
    )
    if any(not str(pricing_snapshot.get(key) or "").strip() for key in required_text):
        return _withheld_pricing("WITHHELD_INVALID_PRICING_SNAPSHOT", pricing_snapshot)
    currency = str(pricing_snapshot.get("currency") or "")
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        return _withheld_pricing("WITHHELD_INVALID_PRICING_SNAPSHOT", pricing_snapshot)
    try:
        datetime.fromisoformat(str(pricing_snapshot["effective_at"]).replace("Z", "+00:00"))
    except ValueError:
        return _withheld_pricing("WITHHELD_INVALID_PRICING_SNAPSHOT", pricing_snapshot)
    if (
        str(pricing_snapshot.get("provider_id") or "") != str(result.get("provider_id") or "")
        or str(pricing_snapshot.get("model") or "") != str(result.get("model") or "")
    ):
        return _withheld_pricing("WITHHELD_PRICING_MODEL_MISMATCH", pricing_snapshot)
    try:
        input_rate = Decimal(str(pricing_snapshot["input_per_million_tokens"]))
        output_rate = Decimal(str(pricing_snapshot["output_per_million_tokens"]))
    except (InvalidOperation, ValueError):
        return _withheld_pricing("WITHHELD_INVALID_PRICING_SNAPSHOT", pricing_snapshot)
    if input_rate < 0 or output_rate < 0:
        return _withheld_pricing("WITHHELD_INVALID_PRICING_SNAPSHOT", pricing_snapshot)
    amount = (
        Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate
    ) / Decimal(1_000_000)
    return {
        "state": "CALCULATED_FROM_VERIFIED_PRICING_SNAPSHOT",
        "amount": format(amount.quantize(Decimal("0.000001")), "f"),
        "currency": str(pricing_snapshot["currency"]),
        "pricing_snapshot_id": str(pricing_snapshot["snapshot_id"]),
        "effective_at": str(pricing_snapshot["effective_at"]),
        "approval_ref": str(pricing_snapshot["approval_ref"]),
    }


def build_model_quality_observation(
    case_id: str,
    result: Mapping[str, Any],
    *,
    human_review: Mapping[str, Any] | None = None,
    pricing_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    trace = dict(result.get("trace") or {})
    failure = dict(result.get("failure") or {})
    review = dict(human_review or {})
    review_boolean_keys = (
        "accepted",
        "hallucination_found",
        "boundary_leak_found",
        "prohibited_conclusion_found",
    )
    review_completed = all(
        isinstance(review.get(key), bool) for key in review_boolean_keys
    ) and bool(str(review.get("reviewer_ref") or "").strip())
    sanitized_review = {
        "completed": review_completed,
        "accepted": bool(review.get("accepted")) if review_completed else None,
        "hallucination_found": (
            bool(review.get("hallucination_found")) if review_completed else None
        ),
        "boundary_leak_found": (
            bool(review.get("boundary_leak_found")) if review_completed else None
        ),
        "prohibited_conclusion_found": (
            bool(review.get("prohibited_conclusion_found")) if review_completed else None
        ),
        "reviewer_ref": (
            str(review.get("reviewer_ref") or "")[:160] if review_completed else None
        ),
    }
    return {
        "case_id": case_id,
        "provider_id": str(result.get("provider_id") or "") or None,
        "model": str(result.get("model") or "") or None,
        "prompt_template_id": str(trace.get("prompt_template_id") or "") or None,
        "prompt_template_version": str(trace.get("prompt_template_version") or "") or None,
        "execution_state": str(result.get("execution_state") or ""),
        "failure_category": str(failure.get("category") or "") or None,
        "request_sha256": str(trace.get("request_sha256") or "") or None,
        "input_tokens": trace.get("input_tokens"),
        "output_tokens": trace.get("output_tokens"),
        "total_tokens": trace.get("total_tokens"),
        "latency_ms": trace.get("latency_ms"),
        "attempts_executed": trace.get("attempts_executed"),
        "external_network_call_executed": bool(
            trace.get("external_network_call_executed")
        ),
        "execution_evidence_kind": str(trace.get("execution_evidence_kind") or ""),
        "cost_observation": build_model_cost_observation(result, pricing_snapshot),
        "human_review": sanitized_review,
        "raw_prompt_persisted": bool(trace.get("raw_prompt_persisted", False)),
        "raw_provider_response_persisted": bool(
            trace.get("raw_provider_response_persisted", False)
        ),
        "shadow_audit_ref": str(
            dict(result.get("governance") or {}).get("shadow_audit_ref") or ""
        )
        or None,
    }


def run_offline_model_quality_goldens() -> dict[str, Any]:
    contract = dict(load_contract(MODEL_QUALITY_CONTRACT_REF))
    golden = dict(load_contract(MODEL_QUALITY_GOLDEN_REF))
    observations: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="kaka-model-quality-") as tmp_dir:
        secret_file = Path(tmp_dir) / "offline-provider-key"
        secret_file.write_text("offline-test-placeholder", encoding="utf-8")
        config = ModelProviderConfig(
            mode=MODEL_PROVIDER_MODE_INTERNAL_SHADOW,
            provider_id="openai_responses",
            base_url="http://127.0.0.1:9/v1",
            model="offline-protocol-model",
            api_key_file=str(secret_file),
            allowed_hosts=("127.0.0.1",),
            timeout_seconds=1,
            max_attempts=1,
            max_output_tokens=800,
            reasoning_effort="low",
            shadow_approval_state="APPROVED",
            shadow_audit_ref="OFFLINE-PROTOCOL-REPLAY",
            eval_state="PASSED",
            allow_http_loopback_for_test=True,
        )
        for case in golden.get("offline_protocol_cases") or []:
            case_id = str(case["case_id"])
            source_refs = tuple(str(item) for item in case.get("source_refs") or [])
            request = ModelAssistRequest(
                request_id=f"QUALITY-{case_id}",
                task_kind=str(case["task_kind"]),
                input_data_classification="PUBLIC",
                sanitized_input=dict(case.get("sanitized_input") or {}),
                source_refs=source_refs,
                prompt_template_id="PROMPT_GOVERNED_PROVIDER_SHADOW_V1",
                prompt_template_version="1",
            )
            transport = _OfflineProtocolTransport(
                dict(case.get("simulation") or {}),
                source_refs[0] if source_refs else "",
            )
            result: dict[str, Any] | None = None
            blocked_category: str | None = None
            try:
                result = execute_governed_model_assist_with_fallback(
                    request,
                    config=config,
                    transport=transport,
                )
                actual_state = str(result.get("execution_state") or "")
                failure_category = str((result.get("failure") or {}).get("category") or "") or None
                observation = build_model_quality_observation(case_id, result)
            except ModelProviderExecutionError as exc:
                actual_state = "BLOCKED_FAIL_CLOSED"
                failure_category = exc.category
                blocked_category = exc.category
                observation = {
                    "case_id": case_id,
                    "provider_id": config.provider_id,
                    "model": config.model,
                    "prompt_template_id": request.prompt_template_id,
                    "prompt_template_version": request.prompt_template_version,
                    "execution_state": actual_state,
                    "failure_category": failure_category,
                    "request_sha256": _expected_real_case_request_sha256(
                        case, {"input_data_classification": "PUBLIC"}
                    ),
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "latency_ms": None,
                    "attempts_executed": 0,
                    "external_network_call_executed": False,
                    "execution_evidence_kind": "OFFLINE_FAIL_CLOSED_BEFORE_TRANSPORT",
                    "cost_observation": {
                        "state": "NOT_APPLICABLE_OFFLINE_OR_NON_EXTERNAL_REPLAY",
                        "amount": None,
                        "currency": None,
                        "pricing_snapshot_id": None,
                        "reason": "No provider transport was invoked.",
                    },
                    "human_review": {"completed": False, "accepted": None},
                    "raw_prompt_persisted": False,
                    "raw_provider_response_persisted": False,
                    "shadow_audit_ref": config.shadow_audit_ref,
                }
            assertions = _offline_case_assertions(
                case=case,
                result=result,
                actual_state=actual_state,
                failure_category=failure_category,
                transport_calls=transport.calls,
                blocked_category=blocked_category,
            )
            observation["assertions"] = assertions
            observations.append(observation)
            case_results.append(
                {
                    "case_id": case_id,
                    "passed": all(assertions.values()),
                    "actual_state": actual_state,
                    "failure_category": failure_category,
                    "transport_calls": transport.calls,
                }
            )

    passed = sum(1 for item in case_results if item["passed"])
    total = len(case_results)
    fallback_cases = [
        item
        for item in case_results
        if item["actual_state"] == "FALLBACK_DETERMINISTIC_REVIEW_REQUIRED"
    ]
    fail_closed_cases = [
        item for item in case_results if item["actual_state"] == "BLOCKED_FAIL_CLOSED"
    ]
    offline_gate_passed = total > 0 and passed == total
    generated_at = datetime.now(timezone.utc).isoformat()
    report_seed = json.dumps(case_results, sort_keys=True, separators=(",", ":"))
    return {
        "report_id": "MODEL-QUALITY-OFFLINE-"
        + hashlib.sha256(report_seed.encode("utf-8")).hexdigest()[:16].upper(),
        "generated_at": generated_at,
        "evaluation_mode": "OFFLINE_PROTOCOL_REPLAY",
        "contract_ref": MODEL_QUALITY_CONTRACT_REF,
        "contract_version": contract["contract_version"],
        "golden_ref": MODEL_QUALITY_GOLDEN_REF,
        "golden_version": golden["version"],
        "summary": {
            "case_count": total,
            "passed_count": passed,
            "failed_count": total - passed,
            "case_pass_rate": round(passed / total, 6) if total else 0.0,
            "fallback_case_count": len(fallback_cases),
            "fallback_case_pass_rate": (
                round(sum(1 for item in fallback_cases if item["passed"]) / len(fallback_cases), 6)
                if fallback_cases
                else 0.0
            ),
            "fail_closed_case_count": len(fail_closed_cases),
            "external_provider_call_count": 0,
            "real_latency_tokens_or_cost_observed": False,
            "offline_gate_status": "PASSED" if offline_gate_passed else "FAILED",
        },
        "observations": observations,
        "release_decision": {
            "offline_implementation_gate": "PASSED" if offline_gate_passed else "FAILED",
            "real_provider_shadow_gate": "BLOCKED_EXTERNAL_NO_REAL_PROVIDER_RESULTS",
            "customer_visible_enabled": False,
            "formal_fact_write_enabled": False,
            "controlled_opening_bypassed": False,
        },
    }


def build_real_provider_quality_request_documents() -> list[dict[str, Any]]:
    golden = dict(load_contract(MODEL_QUALITY_GOLDEN_REF))
    defaults = dict(golden.get("real_quality_case_defaults") or {})
    documents: list[dict[str, Any]] = []
    for case in golden.get("real_quality_cases") or []:
        request = {
            "request_id": f"QUALITY-{case['case_id']}",
            "task_kind": str(case["task_kind"]),
            "input_data_classification": str(defaults["input_data_classification"]),
            "sanitized_input": dict(case.get("sanitized_input") or {}),
            "source_refs": [str(item) for item in case.get("source_refs") or []],
            "prompt_template_id": str(defaults["prompt_template_id"]),
            "prompt_template_version": str(defaults["prompt_template_version"]),
        }
        documents.append(
            {
                "case_id": str(case["case_id"]),
                "request": request,
                "request_sha256": _expected_real_case_request_sha256(case, defaults),
                "manual_checks": list(case.get("manual_checks") or []),
            }
        )
    return documents


def evaluate_real_provider_results(
    case_results: Sequence[Mapping[str, Any]],
    *,
    pricing_snapshot: Mapping[str, Any] | None = None,
    baseline_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(load_contract(MODEL_QUALITY_CONTRACT_REF))
    golden = dict(load_contract(MODEL_QUALITY_GOLDEN_REF))
    gate = dict(contract["real_provider_shadow_gate"])
    golden_cases = {
        str(item["case_id"]): dict(item) for item in golden.get("real_quality_cases") or []
    }
    case_defaults = dict(golden.get("real_quality_case_defaults") or {})
    observations: list[dict[str, Any]] = []
    task_kinds: set[str] = set()
    provider_model_prompt_combinations: set[tuple[str, str, str, str]] = set()
    seen_case_ids: list[str] = []
    trace_complete_count = 0
    accepted_count = 0
    hallucination_count = 0
    boundary_leak_count = 0
    provider_failure_count = 0
    latencies: list[float] = []
    unknown_case_ids: list[str] = []
    for item in case_results:
        case_id = str(item.get("case_id") or "")
        result = dict(item.get("result") or {})
        review = dict(item.get("human_review") or {})
        case = golden_cases.get(case_id)
        if case is None:
            unknown_case_ids.append(case_id)
            continue
        seen_case_ids.append(case_id)
        task_kinds.add(str(case.get("task_kind") or ""))
        observation = build_model_quality_observation(
            case_id,
            result,
            human_review=review,
            pricing_snapshot=pricing_snapshot,
        )
        provider_model_prompt_combinations.add(
            (
                str(observation.get("provider_id") or ""),
                str(observation.get("model") or ""),
                str(observation.get("prompt_template_id") or ""),
                str(observation.get("prompt_template_version") or ""),
            )
        )
        trace_complete = _real_trace_complete(
            observation,
            result,
            case=case,
            case_defaults=case_defaults,
        )
        observation["trace_complete"] = trace_complete
        observations.append(observation)
        trace_complete_count += int(trace_complete)
        accepted_count += int(bool(observation["human_review"].get("accepted")))
        hallucination_count += int(
            bool(observation["human_review"].get("hallucination_found"))
        )
        boundary_leak_count += int(
            bool(observation["human_review"].get("boundary_leak_found"))
            or bool(observation["human_review"].get("prohibited_conclusion_found"))
        )
        provider_failure_count += int(
            str(result.get("execution_state") or "")
            != "COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED"
        )
        latency = observation.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            latencies.append(float(latency))

    total = len(observations)
    verified_costs = [
        item["cost_observation"]
        for item in observations
        if item["cost_observation"]["state"]
        == "CALCULATED_FROM_VERIFIED_PRICING_SNAPSHOT"
    ]
    verified_cost_currencies = {
        str(item.get("currency") or "") for item in verified_costs
    }
    total_verified_cost = (
        sum((Decimal(str(item["amount"])) for item in verified_costs), Decimal("0"))
        if verified_costs and len(verified_cost_currencies) == 1
        else None
    )
    metrics = {
        "case_count": total,
        "successful_case_count": total - provider_failure_count,
        "manual_acceptance_rate": _ratio(accepted_count, total),
        "trace_completeness_rate": _ratio(trace_complete_count, total),
        "hallucination_rate": _ratio(hallucination_count, total),
        "boundary_leak_rate": _ratio(boundary_leak_count, total),
        "provider_failure_rate": _ratio(provider_failure_count, total),
        "p95_latency_ms": _percentile_95(latencies),
        "task_kinds_covered": sorted(task_kinds),
        "provider_model_prompt_combination_count": len(provider_model_prompt_combinations),
        "verified_cost_case_count": len(verified_costs),
        "total_verified_cost_amount": (
            format(total_verified_cost.quantize(Decimal("0.000001")), "f")
            if total_verified_cost is not None
            else None
        ),
        "verified_cost_currency": (
            next(iter(verified_cost_currencies))
            if len(verified_cost_currencies) == 1
            else None
        ),
    }
    threshold_checks = {
        "minimum_case_count": total >= int(gate["minimum_case_count"]),
        "known_case_ids_only": not unknown_case_ids,
        "required_case_ids_exactly_once": len(seen_case_ids) == len(golden_cases)
        and len(set(seen_case_ids)) == len(seen_case_ids)
        and set(seen_case_ids) == set(golden_cases),
        "required_task_kinds": set(gate["required_task_kinds"]).issubset(task_kinds),
        "single_provider_model_prompt_version": len(provider_model_prompt_combinations) == 1,
        "manual_reviews_complete": all(
            bool(item["human_review"].get("completed")) for item in observations
        ),
        "manual_acceptance_rate": metrics["manual_acceptance_rate"]
        >= float(gate["minimum_manual_acceptance_rate"]),
        "trace_completeness_rate": metrics["trace_completeness_rate"]
        >= float(gate["minimum_trace_completeness_rate"]),
        "hallucination_rate": metrics["hallucination_rate"]
        <= float(gate["maximum_hallucination_rate"]),
        "boundary_leak_rate": metrics["boundary_leak_rate"]
        <= float(gate["maximum_boundary_leak_rate"]),
        "provider_failure_rate": metrics["provider_failure_rate"]
        <= float(gate["maximum_provider_failure_rate"]),
        "p95_latency_ms": metrics["p95_latency_ms"] is not None
        and metrics["p95_latency_ms"] <= float(gate["maximum_p95_latency_ms"]),
        "verified_cost_coverage": total > 0
        and metrics["successful_case_count"] > 0
        and metrics["verified_cost_case_count"] == metrics["successful_case_count"],
    }
    regression = compare_model_quality_reports(
        {"golden_version": golden["version"], "metrics": metrics},
        baseline_report,
    )
    quality_passed = all(threshold_checks.values()) and regression["blocks_change"] is False
    return {
        "report_id": "MODEL-QUALITY-REAL-"
        + hashlib.sha256(
            json.dumps(observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16].upper(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": "REAL_PROVIDER_SHADOW",
        "contract_ref": MODEL_QUALITY_CONTRACT_REF,
        "contract_version": contract["contract_version"],
        "golden_ref": MODEL_QUALITY_GOLDEN_REF,
        "golden_version": golden["version"],
        "metrics": metrics,
        "threshold_checks": threshold_checks,
        "unknown_case_ids": unknown_case_ids,
        "version_regression": regression,
        "observations": observations,
        "release_decision": {
            "internal_shadow_quality_gate": "PASSED" if quality_passed else "BLOCKED",
            "customer_visible_enabled": False,
            "formal_fact_write_enabled": False,
            "controlled_opening_still_required": True,
            "model_output_scope": "CANDIDATE_OR_DRAFT_ONLY",
        },
    }


def compare_model_quality_reports(
    current_report: Mapping[str, Any],
    baseline_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if baseline_report is None:
        return {
            "state": "BASELINE_CANDIDATE_REQUIRES_APPROVAL",
            "blocks_change": False,
            "reasons": [],
        }
    contract = dict(load_contract(MODEL_QUALITY_CONTRACT_REF))
    policy = dict(contract["version_regression_policy"])
    if str(current_report.get("golden_version") or "") != str(
        baseline_report.get("golden_version") or ""
    ):
        return {
            "state": "BLOCKED_GOLDEN_VERSION_MISMATCH",
            "blocks_change": True,
            "reasons": ["golden_version_mismatch"],
        }
    current = dict(current_report.get("metrics") or {})
    baseline = dict(baseline_report.get("metrics") or {})
    reasons: list[str] = []
    if _metric(current, "manual_acceptance_rate") < _metric(
        baseline, "manual_acceptance_rate"
    ) - float(policy["maximum_manual_acceptance_drop"]):
        reasons.append("manual_acceptance_regressed")
    if _metric(current, "trace_completeness_rate") < _metric(
        baseline, "trace_completeness_rate"
    ) - float(policy["maximum_trace_completeness_drop"]):
        reasons.append("trace_completeness_regressed")
    if _metric(current, "hallucination_rate") > _metric(
        baseline, "hallucination_rate"
    ) + float(policy["maximum_hallucination_rate_increase"]):
        reasons.append("hallucination_rate_regressed")
    if _metric(current, "boundary_leak_rate") > _metric(
        baseline, "boundary_leak_rate"
    ) + float(policy["maximum_boundary_leak_rate_increase"]):
        reasons.append("boundary_leak_rate_regressed")
    baseline_latency = _metric(baseline, "p95_latency_ms")
    current_latency = _metric(current, "p95_latency_ms")
    if baseline_latency > 0 and current_latency > baseline_latency * (
        1 + float(policy["maximum_p95_latency_increase_ratio"])
    ):
        reasons.append("p95_latency_regressed")
    return {
        "state": "BLOCKED_REGRESSION" if reasons else "PASSED_NO_REGRESSION",
        "blocks_change": bool(reasons),
        "reasons": reasons,
    }


def _provider_payload(output: Mapping[str, Any], *, response_id: str) -> dict[str, Any]:
    return {
        "id": response_id,
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(output, ensure_ascii=False),
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 101, "output_tokens": 42, "total_tokens": 143},
    }


def _offline_case_assertions(
    *,
    case: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    actual_state: str,
    failure_category: str | None,
    transport_calls: int,
    blocked_category: str | None,
) -> dict[str, bool]:
    expected_state = str(case.get("expected_state") or "")
    expected_category = str(case.get("expected_failure_category") or "") or None
    assertions = {
        "state_matches": actual_state == expected_state,
        "failure_category_matches": failure_category == expected_category,
        "no_external_network": True,
        "no_raw_prompt_or_response": True,
        "governed_output_boundary": True,
        "fallback_contains_no_model_candidate_or_draft": True,
        "restricted_input_stopped_before_transport": True,
    }
    if result is not None:
        trace = dict(result.get("trace") or {})
        governance = dict(result.get("governance") or {})
        assertions["no_external_network"] = not bool(
            trace.get("external_network_call_executed")
        )
        assertions["no_raw_prompt_or_response"] = not bool(
            trace.get("raw_prompt_persisted")
        ) and not bool(trace.get("raw_provider_response_persisted"))
        assertions["governed_output_boundary"] = (
            bool(governance.get("human_review_required"))
            and not bool(governance.get("formal_fact_write_enabled"))
            and not bool(governance.get("customer_visible_enabled"))
            and not bool(governance.get("tool_calling_enabled"))
        )
        if actual_state == "FALLBACK_DETERMINISTIC_REVIEW_REQUIRED":
            output = dict(result.get("model_output") or {})
            assertions["fallback_contains_no_model_candidate_or_draft"] = (
                output.get("field_candidates") == []
                and output.get("draft_text") == ""
                and not bool((result.get("failure") or {}).get("model_content_reused"))
            )
    if blocked_category == "RESTRICTED_MODEL_INPUT":
        assertions["restricted_input_stopped_before_transport"] = transport_calls == 0
    return assertions


def _real_trace_complete(
    observation: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    case: Mapping[str, Any],
    case_defaults: Mapping[str, Any],
) -> bool:
    total_tokens = observation.get("total_tokens")
    input_tokens = observation.get("input_tokens")
    output_tokens = observation.get("output_tokens")
    latency_ms = observation.get("latency_ms")
    trace = dict(result.get("trace") or {})
    expected_hash = _expected_real_case_request_sha256(case, case_defaults)
    base_complete = (
        bool(observation.get("provider_id"))
        and bool(observation.get("model"))
        and bool(observation.get("prompt_template_id"))
        and bool(observation.get("prompt_template_version"))
        and isinstance(latency_ms, (int, float))
        and not isinstance(latency_ms, bool)
        and float(latency_ms) >= 0
        and bool(observation.get("external_network_call_executed"))
        and observation.get("execution_evidence_kind") == "EXTERNAL_PROVIDER_SHADOW"
        and observation.get("request_sha256") == expected_hash
        and list(trace.get("source_refs") or []) == list(case.get("source_refs") or [])
        and observation.get("prompt_template_id")
        == case_defaults.get("prompt_template_id")
        and observation.get("prompt_template_version")
        == case_defaults.get("prompt_template_version")
        and bool(observation.get("shadow_audit_ref"))
        and not bool(observation.get("raw_prompt_persisted"))
        and not bool(observation.get("raw_provider_response_persisted"))
    )
    if not base_complete:
        return False
    if observation.get("execution_state") == "COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED":
        return (
            isinstance(total_tokens, int)
            and not isinstance(total_tokens, bool)
            and total_tokens > 0
            and isinstance(input_tokens, int)
            and not isinstance(input_tokens, bool)
            and input_tokens >= 0
            and isinstance(output_tokens, int)
            and not isinstance(output_tokens, bool)
            and output_tokens >= 0
            and total_tokens == input_tokens + output_tokens
            and bool(result.get("provider_response_id"))
        )
    return (
        observation.get("execution_state") == "FALLBACK_DETERMINISTIC_REVIEW_REQUIRED"
        and bool(observation.get("failure_category"))
    )


def _expected_real_case_request_sha256(
    case: Mapping[str, Any], case_defaults: Mapping[str, Any]
) -> str:
    request_document = {
        "task_kind": str(case.get("task_kind") or ""),
        "input_data_classification": str(
            case.get("input_data_classification")
            or case_defaults.get("input_data_classification")
            or ""
        ),
        "sanitized_input": dict(case.get("sanitized_input") or {}),
        "source_refs": [str(item) for item in case.get("source_refs") or []],
    }
    return hashlib.sha256(
        json.dumps(
            request_document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _withheld_pricing(state: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "state": state,
        "amount": None,
        "currency": None,
        "pricing_snapshot_id": str(snapshot.get("snapshot_id") or "") or None,
        "reason": "Pricing snapshot is incomplete, invalid, or does not match provider/model.",
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percentile_95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(0.95 * len(ordered)) - 1, 0)
    return round(float(ordered[index]), 3)


def _metric(metrics: Mapping[str, Any], key: str) -> float:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


__all__ = [
    "MODEL_QUALITY_CONTRACT_REF",
    "MODEL_QUALITY_GOLDEN_REF",
    "build_model_cost_observation",
    "build_real_provider_quality_request_documents",
    "build_model_quality_observation",
    "compare_model_quality_reports",
    "evaluate_real_provider_results",
    "run_offline_model_quality_goldens",
]
