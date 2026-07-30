from __future__ import annotations

from typing import Any, Iterable, Mapping

from stage4_verification.public_evidence_readback import (
    PUBLIC_EVIDENCE_RULE_CODES,
    evaluate_public_evidence_gate,
    normalize_public_evidence_readbacks,
)


EXECUTOR_ID = "stage5-rule-bundle-executor-v1"


class RuleBundleExecutor:
    def __init__(self, *, rule_codes: Iterable[str]) -> None:
        self.rule_codes = _unique([str(rule_code) for rule_code in rule_codes if rule_code])

    def execute(
        self,
        *,
        bundle_id: str,
        readbacks: Any,
        rule_execution_trace: Iterable[Mapping[str, Any]] | None = None,
        rule_selection_trace: Iterable[Mapping[str, Any]] | None = None,
        coverage_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if rule_execution_trace is not None or rule_selection_trace is not None:
            return self._execute_from_stage5_trace(
                bundle_id=bundle_id,
                rule_execution_trace=rule_execution_trace or [],
                rule_selection_trace=rule_selection_trace or [],
                coverage_summary=coverage_summary or {},
            )
        normalized = normalize_public_evidence_readbacks(readbacks)
        executed_rule_codes: list[str] = []
        skipped_rule_codes: list[str] = []
        missing_readback_reasons: dict[str, list[str]] = {}
        rule_results: dict[str, dict[str, Any]] = {}
        skipped_rule_details: dict[str, dict[str, Any]] = {}

        for rule_code in self.rule_codes:
            if rule_code not in PUBLIC_EVIDENCE_RULE_CODES:
                skipped_rule_codes.append(rule_code)
                reasons = [f"{rule_code}: unsupported rule code for public readback bundle"]
                missing_readback_reasons[rule_code] = reasons
                skipped_rule_details[rule_code] = {
                    "skip_reason": "unsupported_rule_code",
                    "reasons": reasons,
                }
                continue

            gate = evaluate_public_evidence_gate(rule_code, normalized)
            if not gate.get("readback_ids"):
                skipped_rule_codes.append(rule_code)
                reasons = _reasons(gate) or [f"{rule_code}: public evidence readback missing"]
                missing_readback_reasons[rule_code] = reasons
                skipped_rule_details[rule_code] = {
                    "skip_reason": "missing_relevant_readback",
                    "reasons": reasons,
                }
                continue

            executed_rule_codes.append(rule_code)
            rule_results[rule_code] = {
                **dict(gate),
                "rule_code": rule_code,
                "executed": True,
                "customer_visible": False,
                "no_legal_conclusion": True,
            }

        calibration = _calibration_summary(
            rule_codes=self.rule_codes,
            rule_results=rule_results,
            skipped_rule_details=skipped_rule_details,
            missing_readback_reasons=missing_readback_reasons,
        )
        return {
            "executor_id": EXECUTOR_ID,
            "bundle_id": str(bundle_id),
            "rule_codes": list(self.rule_codes),
            "executed_rule_codes": executed_rule_codes,
            "skipped_rule_codes": skipped_rule_codes,
            "missing_readback_reasons": missing_readback_reasons,
            "rule_results": rule_results,
            "skipped_rule_details": skipped_rule_details,
            "stage5_abcd_calibration": calibration,
            "summary": {
                "rule_count": len(self.rule_codes),
                "executed_count": len(executed_rule_codes),
                "skipped_count": len(skipped_rule_codes),
                "missing_readback_count": len(missing_readback_reasons),
                "stage5_abcd_calibration_counts": dict(calibration["calibration_bucket_counts"]),
                "truth_label_required_count": int(calibration["truth_label_required_count"]),
                "non_clearance_rule_count": int(calibration["non_clearance_rule_count"]),
            },
            "source_refs": _source_refs(rule_results),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    def _execute_from_stage5_trace(
        self,
        *,
        bundle_id: str,
        rule_execution_trace: Iterable[Mapping[str, Any]],
        rule_selection_trace: Iterable[Mapping[str, Any]],
        coverage_summary: Mapping[str, Any],
    ) -> dict[str, Any]:
        execution_entries = [dict(entry) for entry in rule_execution_trace if isinstance(entry, Mapping)]
        selection_entries = [dict(entry) for entry in rule_selection_trace if isinstance(entry, Mapping)]
        executed_rule_codes = _unique(
            [str(entry.get("rule_code")) for entry in execution_entries if entry.get("rule_code")]
        )
        skipped_rule_codes = _coverage_list(coverage_summary, "skipped_rule_codes")
        if not skipped_rule_codes:
            skipped_rule_codes = _unique(
                [
                    str(entry.get("rule_code"))
                    for entry in selection_entries
                    if entry.get("rule_code") and entry.get("selected") is not True
                ]
            )

        rule_results = {
            str(entry["rule_code"]): {
                **entry,
                "executed": True,
                "customer_visible": False,
                "no_legal_conclusion": True,
            }
            for entry in execution_entries
            if entry.get("rule_code")
        }
        missing_readback_reasons: dict[str, list[str]] = {}
        for entry in execution_entries:
            rule_code = str(entry.get("rule_code") or "")
            if not rule_code:
                continue
            readback_ids = entry.get("public_evidence_readback_ids")
            gate_status = str(entry.get("public_evidence_gate_status") or "")
            reasons = _as_str_list(entry.get("public_evidence_gate_reasons"))
            if gate_status == "REVIEW" and not _as_str_list(readback_ids) and reasons:
                missing_readback_reasons[rule_code] = reasons

        skipped_rule_details = {
            str(entry["rule_code"]): {
                "skip_reason": str(entry.get("reason") or "not_selected"),
                "selected": bool(entry.get("selected")),
                "missing_dependency_fields": _as_str_list(entry.get("missing_dependency_fields")),
                "unsupported_upstream_objects": _as_str_list(entry.get("unsupported_upstream_objects")),
            }
            for entry in selection_entries
            if entry.get("rule_code") and entry.get("selected") is not True
        }
        calibration = _calibration_summary(
            rule_codes=self.rule_codes,
            rule_results=rule_results,
            skipped_rule_details=skipped_rule_details,
            missing_readback_reasons=missing_readback_reasons,
        )
        return {
            "executor_id": EXECUTOR_ID,
            "bundle_id": str(bundle_id),
            "rule_codes": list(self.rule_codes),
            "executed_rule_codes": executed_rule_codes,
            "skipped_rule_codes": skipped_rule_codes,
            "missing_readback_reasons": missing_readback_reasons,
            "rule_results": rule_results,
            "skipped_rule_details": skipped_rule_details,
            "stage5_abcd_calibration": calibration,
            "summary": {
                "rule_count": len(self.rule_codes),
                "executed_count": len(executed_rule_codes),
                "skipped_count": _int_value(coverage_summary.get("skipped_count"), len(skipped_rule_codes)),
                "missing_readback_count": len(missing_readback_reasons),
                "pass_count": _int_value(coverage_summary.get("pass_count"), 0),
                "review_count": _int_value(coverage_summary.get("review_count"), 0),
                "block_count": _int_value(coverage_summary.get("block_count"), 0),
                "stage5_abcd_calibration_counts": dict(calibration["calibration_bucket_counts"]),
                "truth_label_required_count": int(calibration["truth_label_required_count"]),
                "non_clearance_rule_count": int(calibration["non_clearance_rule_count"]),
            },
            "source_refs": _source_refs(rule_results),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }


def _reasons(gate: Mapping[str, Any]) -> list[str]:
    raw = gate.get("reasons")
    if isinstance(raw, list):
        return [str(reason) for reason in raw if reason]
    if raw in (None, "", [], {}):
        return []
    return [str(raw)]


def _source_refs(rule_results: Mapping[str, Mapping[str, Any]]) -> list[str]:
    refs: list[str] = []
    for result in rule_results.values():
        raw = result.get("source_refs")
        if isinstance(raw, list):
            refs.extend(str(ref) for ref in raw if ref)
    return _unique(refs)


def _calibration_summary(
    *,
    rule_codes: Iterable[str],
    rule_results: Mapping[str, Mapping[str, Any]],
    skipped_rule_details: Mapping[str, Mapping[str, Any]],
    missing_readback_reasons: Mapping[str, list[str]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    bucket_counts: dict[str, int] = {}
    for rule_code in rule_codes:
        code = str(rule_code)
        if code in rule_results:
            row = _calibration_row_for_result(code, rule_results[code])
        else:
            row = _calibration_row_for_skipped(
                code,
                skipped_rule_details.get(code, {}),
                missing_readback_reasons.get(code, []),
            )
        rows.append(row)
        bucket = str(row["calibration_bucket"])
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    return {
        "calibration_schema": "STAGE5_ABCD_RULE_GATE_CALIBRATION_V1",
        "calibration_rows": rows,
        "calibration_bucket_counts": bucket_counts,
        "calibration_evidence_strength_counts": _counts(row["calibration_evidence_strength"] for row in rows),
        "calibration_review_family_counts": _counts(row["calibration_review_family"] for row in rows),
        "truth_label_required_count": sum(1 for row in rows if row["truth_label_required"]),
        "non_clearance_rule_count": sum(1 for row in rows if row["query_miss_is_not_clearance"]),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _calibration_row_for_result(rule_code: str, result: Mapping[str, Any]) -> dict[str, Any]:
    gate_status = str(result.get("gate_status") or result.get("public_evidence_gate_status") or "")
    readback_ids = _as_str_list(result.get("readback_ids") or result.get("public_evidence_readback_ids"))
    passed_readback_ids = _as_str_list(result.get("passed_readback_ids"))
    reasons = _as_str_list(result.get("reasons") or result.get("public_evidence_gate_reasons"))
    if gate_status == "PASS" and passed_readback_ids:
        bucket = "A_OFFICIAL_PUBLIC_READBACK_PASS"
        suggested_action = "allow_internal_stage6_fact_review_with_source_trace"
        truth_label_required = False
    elif _has_blocked_reason(reasons):
        bucket = "D_BLOCKED_OR_AUTHORIZATION_REQUIRED"
        suggested_action = "keep_blocked_and_collect_authorized_readback_or_operator_input"
        truth_label_required = True
    elif readback_ids:
        bucket = "B_PUBLIC_READBACK_REVIEW_REQUIRED"
        suggested_action = "manual_review_public_readback_before_rule_relaxation_or_tightening"
        truth_label_required = True
    else:
        bucket = "C_INSUFFICIENT_PUBLIC_READBACK"
        suggested_action = "collect_targeted_public_readback_before_any_clearance_claim"
        truth_label_required = True
    return _calibration_row(
        rule_code=rule_code,
        gate_status=gate_status or "REVIEW",
        calibration_bucket=bucket,
        reasons=reasons,
        readback_ids=readback_ids,
        suggested_action=suggested_action,
        truth_label_required=truth_label_required,
    )


def _calibration_row_for_skipped(
    rule_code: str,
    details: Mapping[str, Any],
    missing_reasons: list[str],
) -> dict[str, Any]:
    skip_reason = str(details.get("skip_reason") or "")
    reasons = _as_str_list(missing_reasons or details.get("reasons") or details.get("missing_dependency_fields"))
    if skip_reason == "unsupported_rule_code":
        bucket = "D_UNSUPPORTED_RULE_OR_RUNTIME_BLOCKED"
        suggested_action = "do_not_execute_or_clear_until_rule_adapter_is_supported"
    else:
        bucket = "C_MISSING_RELEVANT_PUBLIC_READBACK"
        suggested_action = "collect_targeted_public_readback_before_any_clearance_claim"
    return _calibration_row(
        rule_code=rule_code,
        gate_status="SKIPPED",
        calibration_bucket=bucket,
        reasons=reasons,
        readback_ids=[],
        suggested_action=suggested_action,
        truth_label_required=True,
    )


def _calibration_row(
    *,
    rule_code: str,
    gate_status: str,
    calibration_bucket: str,
    reasons: list[str],
    readback_ids: list[str],
    suggested_action: str,
    truth_label_required: bool,
) -> dict[str, Any]:
    return {
        "rule_code": rule_code,
        "gate_status": gate_status,
        "calibration_bucket": calibration_bucket,
        "calibration_review_bucket": calibration_bucket,
        "calibration_evidence_strength": _calibration_evidence_strength(calibration_bucket),
        "calibration_review_family": _calibration_review_family(calibration_bucket, reasons),
        "calibration_reasons": list(dict.fromkeys(reasons)),
        "readback_ids": list(dict.fromkeys(readback_ids)),
        "truth_label_required": truth_label_required,
        "suggested_calibration_action": suggested_action,
        "query_miss_is_not_clearance": calibration_bucket != "A_OFFICIAL_PUBLIC_READBACK_PASS",
        "no_clearance_without_public_readback": calibration_bucket != "A_OFFICIAL_PUBLIC_READBACK_PASS",
        "no_legal_conclusion": True,
        "customer_visible_allowed": False,
    }


def _calibration_evidence_strength(calibration_bucket: str) -> str:
    if calibration_bucket == "A_OFFICIAL_PUBLIC_READBACK_PASS":
        return "OFFICIAL_PUBLIC_READBACK_PASS"
    if calibration_bucket == "B_PUBLIC_READBACK_REVIEW_REQUIRED":
        return "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED"
    if calibration_bucket in {"C_MISSING_RELEVANT_PUBLIC_READBACK", "C_INSUFFICIENT_PUBLIC_READBACK"}:
        return "PUBLIC_READBACK_MISSING_OR_INSUFFICIENT"
    if calibration_bucket.startswith("D_"):
        return "BLOCKED_OR_UNSUPPORTED"
    return "REVIEW_REQUIRED"


def _calibration_review_family(calibration_bucket: str, reasons: Iterable[str]) -> str:
    if calibration_bucket == "A_OFFICIAL_PUBLIC_READBACK_PASS":
        return "baseline_pass"
    if calibration_bucket == "B_PUBLIC_READBACK_REVIEW_REQUIRED":
        return "manual_public_readback_review"
    if calibration_bucket == "C_MISSING_RELEVANT_PUBLIC_READBACK":
        return "missing_relevant_public_readback"
    if calibration_bucket == "C_INSUFFICIENT_PUBLIC_READBACK":
        return "insufficient_public_readback"
    if calibration_bucket == "D_UNSUPPORTED_RULE_OR_RUNTIME_BLOCKED":
        return "unsupported_rule_or_runtime_blocked"
    if calibration_bucket == "D_BLOCKED_OR_AUTHORIZATION_REQUIRED":
        return "authorization_or_source_blocked" if _has_blocked_reason(reasons) else "blocked_or_authorization_required"
    return "review_required"


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _has_blocked_reason(reasons: Iterable[str]) -> bool:
    tokens = (
        "BLOCKED",
        "LOGIN_OR_SSO_REQUIRED",
        "AUTHORIZATION",
        "NEEDS_BROWSER",
        "FAIL_CLOSED",
        "QUERY_ERROR",
        "TIMEOUT",
        "WAF",
    )
    return any(any(token in str(reason).upper() for token in tokens) for reason in reasons)


def _coverage_list(coverage_summary: Mapping[str, Any], key: str) -> list[str]:
    return _as_str_list(coverage_summary.get(key))


def _as_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, tuple):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = ["EXECUTOR_ID", "RuleBundleExecutor"]
