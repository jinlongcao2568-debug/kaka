from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.evaluation_rule_calibration import TAILORED_REVIEW_RULE_CODE


TAILORED_REVIEW_ADJUDICATION_MANIFEST_OBJECT_TYPE = "tailored_review_adjudication_manifest"
TAILORED_REVIEW_ADJUDICATION_MANIFEST_VERSION = 1
TAILORED_REVIEW_ADJUDICATION_ADAPTER_ID = "tailored-review-adjudication-builder"

DEFAULT_REVIEW_SAMPLE_LIMIT = 9
MIN_THRESHOLD_ADVICE_SAMPLE_COUNT = 50
TEXT_PROBE_LIMIT = 1200

CONFIRMED_CLUE = "CONFIRMED_CLUE"
LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"

FALSE_POSITIVE_REASON_MARKERS = {
    "observable_mismatch",
    "CLARIFICATION_OR_ADDENDUM_PRESENT",
    "clarification_or_addendum",
}
NON_PRIMARY_DOCUMENT_MARKERS = {
    "开标记录",
    "开标情况",
    "澄清",
    "补遗",
    "答疑",
    "变更通知",
    "更正公告",
    "中标候选人",
    "中标结果",
    "成交结果",
}
NON_PRIMARY_DOCUMENT_KINDS = {
    "candidate_notice",
    "award_result",
    "failed_bid_notice",
    "flow_or_re_tender_notice",
}
EVIDENCE_BLOCKER_STATES = {
    "DETAIL_SNAPSHOT_MISSING_REVIEW",
    "ATTACHMENTS_NOT_CAPTURED_REVIEW",
    "PARTIAL_REVIEW_REQUIRED",
}
EVIDENCE_BLOCKER_MARKERS = {
    "CAPTCHA",
    "OCR_REQUIRED",
    "OCR_ENGINE_UNAVAILABLE",
    "attachment_missing",
    "attachment_html_blocker",
    "detail_body_too_small",
    "detail_title_missing",
    "http_status:502",
    "DEGRADED",
}


def build_tailored_review_adjudication_manifest(
    *,
    rule_calibration_manifest_json: str | Path,
    real_sample_execution_manifest_json: str | Path,
    review_sample_limit: int = DEFAULT_REVIEW_SAMPLE_LIMIT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    calibration_path = Path(rule_calibration_manifest_json)
    execution_path = Path(real_sample_execution_manifest_json)
    blocking_reasons: list[str] = []

    calibration_payload = _load_json_file(calibration_path, "rule_calibration_manifest", blocking_reasons)
    execution_payload = _load_json_file(execution_path, "real_sample_execution_manifest", blocking_reasons)
    calibration_manifest = _source_manifest(calibration_payload)
    execution_manifest = _source_manifest(execution_payload)

    triggered_items = _triggered_tailored_items(calibration_manifest)
    source_index = _real_project_sample_index(execution_manifest)
    review_items = [
        _build_review_item(item, source_index)
        for item in triggered_items[: max(0, review_sample_limit)]
    ]
    manifest = _build_manifest(
        review_items=review_items,
        triggered_count=len(triggered_items),
        calibration_manifest=calibration_manifest,
        execution_manifest=execution_manifest,
        calibration_path=calibration_path,
        execution_path=execution_path,
        created_at=created,
    )
    return {
        "tailored_review_adjudication_mode": "DRY_RUN",
        "execute": False,
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": manifest["summary"],
        "execution": {
            "executed": False,
            "external_ai_review_executed": False,
            "formal_rule_threshold_mutation_enabled": False,
            "database_write_enabled": False,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "customer_visible_allowed": False,
        },
    }


def _build_manifest(
    *,
    review_items: list[dict[str, Any]],
    triggered_count: int,
    calibration_manifest: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    calibration_path: Path,
    execution_path: Path,
    created_at: str,
) -> dict[str, Any]:
    summary = _summary(review_items, triggered_count, calibration_manifest)
    fingerprint = _fingerprint(
        {
            "source_rule_calibration_manifest_id": calibration_manifest.get("manifest_id"),
            "source_real_sample_execution_manifest_id": execution_manifest.get("manifest_id"),
            "review_items": review_items,
            "triggered_count": triggered_count,
        }
    )
    manifest = {
        "manifest_version": TAILORED_REVIEW_ADJUDICATION_MANIFEST_VERSION,
        "manifest_kind": TAILORED_REVIEW_ADJUDICATION_MANIFEST_OBJECT_TYPE,
        "adapter_id": TAILORED_REVIEW_ADJUDICATION_ADAPTER_ID,
        "manifest_id": f"TAILORED-REVIEW-ADJUDICATION-{fingerprint[:16]}",
        "created_at": created_at,
        "review_rule_code": TAILORED_REVIEW_RULE_CODE,
        "source_rule_calibration_manifest_id": str(calibration_manifest.get("manifest_id") or ""),
        "source_rule_calibration_manifest_path": str(calibration_path),
        "source_real_sample_execution_manifest_id": str(execution_manifest.get("manifest_id") or ""),
        "source_real_sample_execution_manifest_path": str(execution_path),
        "items": review_items,
        "sample_items": review_items[:80],
        "summary": summary,
        "recommended_weight_policy": _recommended_weight_policy(review_items, summary),
        "allowed_internal_terms": [
            "疑似定制标",
            "限制竞争线索",
            "控标风险线索",
            "人工复核",
        ],
        "prohibited_output_policy_id": "TAILORED_NO_FORMAL_LEGAL_OR_AWARD_OUTCOME_CONCLUSION",
        "safety": {
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "formal_rule_threshold_mutation_enabled": False,
            "external_ai_review_executed": False,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "raw_html_or_blob_stored": False,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return manifest


def _build_review_item(
    calibration_item: Mapping[str, Any],
    source_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    source_item = _match_source_item(calibration_item, source_index)
    merged = {**dict(source_item), **dict(calibration_item)}
    disposition, disposition_reasons = _adjudicate_disposition(merged)
    target_id = str(calibration_item.get("target_id") or source_item.get("target_id") or "")
    review_item = {
        "review_item_id": f"TAILORED-ADJ-{_fingerprint({'target_id': target_id})[:12]}",
        "target_id": target_id,
        "parent_target_id": str(merged.get("parent_target_id") or ""),
        "candidate_key": str(merged.get("candidate_key") or ""),
        "project_id": str(merged.get("project_id") or ""),
        "project_name": str(merged.get("project_name") or ""),
        "source_url": str(merged.get("source_url") or ""),
        "document_kind": str(merged.get("document_kind") or ""),
        "jurisdiction": str(merged.get("jurisdiction") or ""),
        "source_profile_id": str(merged.get("source_profile_id") or ""),
        "target_execution_state": str(merged.get("target_execution_state") or ""),
        "review_rule_code": TAILORED_REVIEW_RULE_CODE,
        "review_disposition": disposition,
        "disposition_reasons": disposition_reasons,
        "evidence_status": _evidence_status(merged),
        "tailored_bid_index": _int_value(merged.get("tailored_bid_index"), default=0),
        "tailored_bid_risk_level": str(merged.get("tailored_bid_risk_level") or ""),
        "tailored_bid_sub_indices": dict(merged.get("tailored_bid_sub_indices") or {}),
        "tailored_bid_signal_count": _int_value(merged.get("tailored_bid_signal_count"), default=0),
        "tailored_bid_counter_reason_count": _int_value(
            merged.get("tailored_bid_counter_reason_count"),
            default=0,
        ),
        "tailored_bid_signal_families": dict(merged.get("tailored_bid_signal_families") or {}),
        "tailored_bid_ai_review_reasons": _string_list(merged.get("tailored_bid_ai_review_reasons")),
        "expected_tailored_review_reasons": _string_list(merged.get("expected_tailored_review_reasons")),
        "source_class_counts": dict(merged.get("source_class_counts") or {}),
        "source_text_probe": _safe_text_probe(source_item),
        "snapshot_refs": _safe_snapshot_refs(source_item),
        "weight_recommendation": _item_weight_recommendation(disposition, disposition_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return review_item


def _adjudicate_disposition(item: Mapping[str, Any]) -> tuple[str, list[str]]:
    false_positive_reasons = _false_positive_reasons(item)
    evidence_reasons = _evidence_blocker_reasons(item)
    if false_positive_reasons:
        return LIKELY_FALSE_POSITIVE, _dedupe_strings(false_positive_reasons + evidence_reasons)
    if evidence_reasons:
        return INSUFFICIENT_EVIDENCE, _dedupe_strings(evidence_reasons)
    if (
        _int_value(item.get("tailored_bid_index"), default=0) >= 41
        and dict(item.get("tailored_bid_signal_families") or {})
    ):
        return CONFIRMED_CLUE, ["complete_evidence_and_medium_or_higher_index"]
    return NEEDS_HUMAN_REVIEW, ["signal_hit_requires_manual_industry_context_review"]


def _false_positive_reasons(item: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    searchable_reasons = "\n".join(
        _string_list(item.get("tailored_bid_ai_review_reasons"))
        + _string_list(item.get("expected_tailored_review_reasons"))
        + _string_list(item.get("failure_taxonomy"))
    )
    if any(marker in searchable_reasons for marker in FALSE_POSITIVE_REASON_MARKERS):
        reasons.append("observable_or_version_mismatch_review")
    document_kind = str(item.get("document_kind") or "")
    if document_kind in NON_PRIMARY_DOCUMENT_KINDS and _tailored_signal_families_require_tender_context(item):
        reasons.append(f"non_primary_procurement_document_kind={document_kind}")
    text = "\n".join(
        [
            str(item.get("project_name") or ""),
            str(item.get("source_text") or ""),
            str(dict(item.get("parse_summary") or {}).get("text_probe") or ""),
        ]
    )
    if any(marker in text for marker in NON_PRIMARY_DOCUMENT_MARKERS):
        reasons.append("non_primary_procurement_document_text_marker")
    if str(item.get("notice_version_chain_state") or "") == "CLARIFICATION_OR_ADDENDUM_PRESENT":
        reasons.append("clarification_or_addendum_state")
    return _dedupe_strings(reasons)


def _evidence_blocker_reasons(item: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    parse_summary = dict(item.get("parse_summary") or {})
    document_counts = _mapping_counts(parse_summary.get("document_completeness_state_counts"))
    document_state = str(item.get("document_completeness_state") or "")
    all_document_states = set(document_counts)
    if document_state:
        all_document_states.add(document_state)
    for state in sorted(all_document_states.intersection(EVIDENCE_BLOCKER_STATES)):
        reasons.append(f"document_completeness_state={state}")
    if str(item.get("target_execution_state") or "") == "CAPTURE_PARTIAL_REVIEW":
        reasons.append("target_execution_state=CAPTURE_PARTIAL_REVIEW")
    attachment_missing_count = _int_value(
        item.get("attachment_missing_review_count"),
        default=_int_value(parse_summary.get("attachment_missing_review_count"), default=0),
    )
    if attachment_missing_count:
        reasons.append("attachment_missing_review_count>0")
    ocr_count = _int_value(parse_summary.get("ocr_required_count"), default=0) + _int_value(
        parse_summary.get("attachment_ocr_required_count"),
        default=0,
    )
    if ocr_count:
        reasons.append("ocr_required_or_attachment_ocr_required")
    failure_taxonomy = _string_list(item.get("failure_taxonomy"))
    for failure in failure_taxonomy:
        if any(marker in failure for marker in EVIDENCE_BLOCKER_MARKERS):
            reasons.append(f"failure_taxonomy={failure}")
    if str(item.get("tailored_bid_evidence_state") or "") == "INSUFFICIENT_EVIDENCE":
        reasons.append("tailored_bid_evidence_state=INSUFFICIENT_EVIDENCE")
    return _dedupe_strings(reasons)


def _tailored_signal_families_require_tender_context(item: Mapping[str, Any]) -> bool:
    families = set(dict(item.get("tailored_bid_signal_families") or {}))
    tender_context_families = {
        "qualification_customization",
        "technical_parameter_customization",
        "test_report_customization",
        "authorization_binding",
        "local_protection",
        "performance_personnel_binding",
        "scoring_customization",
        "dark_bid_format_risk",
        "fatal_rejection_complexity",
    }
    return bool(families.intersection(tender_context_families))


def _evidence_status(item: Mapping[str, Any]) -> dict[str, Any]:
    parse_summary = dict(item.get("parse_summary") or {})
    return {
        "tailored_bid_evidence_state": str(item.get("tailored_bid_evidence_state") or ""),
        "target_execution_state": str(item.get("target_execution_state") or ""),
        "document_completeness_state_counts": _mapping_counts(
            parse_summary.get("document_completeness_state_counts")
        ),
        "notice_version_chain_state_counts": _mapping_counts(
            parse_summary.get("notice_version_chain_state_counts")
        ),
        "attachment_missing_review_count": _int_value(
            item.get("attachment_missing_review_count"),
            default=_int_value(parse_summary.get("attachment_missing_review_count"), default=0),
        ),
        "ocr_required_count": _int_value(parse_summary.get("ocr_required_count"), default=0),
        "attachment_ocr_required_count": _int_value(
            parse_summary.get("attachment_ocr_required_count"),
            default=0,
        ),
        "failure_taxonomy": _string_list(item.get("failure_taxonomy")),
    }


def _item_weight_recommendation(disposition: str, reasons: list[str]) -> dict[str, Any]:
    action = "MANUAL_REVIEW_REQUIRED_BEFORE_WEIGHT_CHANGE"
    if disposition == LIKELY_FALSE_POSITIVE:
        action = "ADD_COUNTER_REASON_FOR_NON_PRIMARY_OR_MISMATCHED_DOCUMENT"
    elif disposition == INSUFFICIENT_EVIDENCE:
        action = "KEEP_AI_REVIEW_NO_INDEX_INCREASE_FOR_INSUFFICIENT_EVIDENCE"
    return {
        "formal_weight_mutation_enabled": False,
        "formal_threshold_mutation_enabled": False,
        "recommended_weight_delta": 0,
        "suggested_seed_weight_action": action,
        "reason_refs": list(reasons),
    }


def _recommended_weight_policy(review_items: list[Mapping[str, Any]], summary: Mapping[str, Any]) -> dict[str, Any]:
    false_positive_count = _int_value(
        dict(summary.get("review_disposition_counts") or {}).get(LIKELY_FALSE_POSITIVE),
        default=0,
    )
    insufficient_count = _int_value(
        dict(summary.get("review_disposition_counts") or {}).get(INSUFFICIENT_EVIDENCE),
        default=0,
    )
    recommendations = [
        "DO_NOT_MUTATE_FORMAL_THRESHOLDS_IN_THIS_RUN",
        "REQUIRE_MANUAL_ADJUDICATION_BEFORE_FORMAL_WEIGHT_CHANGE",
    ]
    if false_positive_count:
        recommendations.append("ADD_COUNTER_REASON_FOR_NON_PRIMARY_DOCUMENT_AND_OBSERVABLE_MISMATCH")
    if insufficient_count:
        recommendations.append("KEEP_AI_REVIEW_FOR_BLOCKED_EVIDENCE_WITHOUT_INDEX_INCREASE")
    if any(item.get("review_disposition") == CONFIRMED_CLUE for item in review_items):
        recommendations.append("USE_CONFIRMED_CLUES_FOR_NEXT_WEIGHT_CALIBRATION_BATCH")
    return {
        "formal_rule_threshold_mutation_enabled": False,
        "formal_seed_weight_mutation_enabled": False,
        "recommended_next_action": str(summary.get("recommended_next_action") or ""),
        "threshold_advice_state": str(summary.get("threshold_advice_state") or ""),
        "recommendations": recommendations,
    }


def _summary(
    review_items: list[Mapping[str, Any]],
    triggered_count: int,
    calibration_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    calibration_summary = dict(calibration_manifest.get("summary") or {})
    tailored_sample_count = _int_value(
        calibration_summary.get("tailored_sample_count"),
        default=len(list(calibration_manifest.get("tailored_items") or [])),
    )
    threshold_advice_state = (
        "SAMPLE_READY_MANUAL_REVIEW_REQUIRED"
        if tailored_sample_count >= MIN_THRESHOLD_ADVICE_SAMPLE_COUNT
        else "INSUFFICIENT_SAMPLE_NO_THRESHOLD_ADVICE"
    )
    return {
        "review_rule_code": TAILORED_REVIEW_RULE_CODE,
        "tailored_sample_count": tailored_sample_count,
        "tailored_sample_state": str(
            calibration_summary.get("tailored_insufficient_sample_state") or ""
        ),
        "triggered_sample_count": triggered_count,
        "review_sample_count": len(review_items),
        "review_disposition_counts": _counts(
            str(item.get("review_disposition") or "") for item in review_items
        ),
        "risk_level_counts": _counts(
            str(item.get("tailored_bid_risk_level") or "") for item in review_items
        ),
        "signal_family_counts": _aggregate_signal_families(review_items),
        "evidence_state_counts": _counts(
            str(dict(item.get("evidence_status") or {}).get("tailored_bid_evidence_state") or "")
            for item in review_items
        ),
        "threshold_advice_state": threshold_advice_state,
        "recommended_next_action": "MANUAL_REVIEW_BEFORE_WEIGHT_MUTATION",
        "formal_rule_threshold_mutation_enabled": False,
        "formal_seed_weight_mutation_enabled": False,
        "external_ai_review_executed": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _triggered_tailored_items(calibration_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(calibration_manifest.get("tailored_items") or []):
        if not isinstance(item, Mapping):
            continue
        if (
            item.get("expected_tailored_review_state") == "REVIEW_REQUIRED"
            or bool(item.get("tailored_bid_ai_review_required"))
            or bool(item.get("tailored_bid_stage5_review_required"))
        ):
            result.append(dict(item))
    return result


def _real_project_sample_index(execution_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for item in list(execution_manifest.get("project_sample_items") or []):
        if not isinstance(item, Mapping):
            continue
        target_id = str(item.get("target_id") or "")
        if target_id:
            index[target_id] = dict(item)
        parent_target_id = str(item.get("parent_target_id") or "")
        candidate_key = str(item.get("candidate_key") or "")
        if parent_target_id and candidate_key:
            index[f"{parent_target_id}::{candidate_key}"] = dict(item)
    return index


def _match_source_item(
    calibration_item: Mapping[str, Any],
    source_index: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    target_id = str(calibration_item.get("target_id") or "")
    if target_id in source_index:
        return source_index[target_id]
    parent_target_id = str(calibration_item.get("parent_target_id") or "")
    candidate_key = str(calibration_item.get("candidate_key") or "")
    if parent_target_id and candidate_key:
        return source_index.get(f"{parent_target_id}::{candidate_key}", {})
    return {}


def _safe_text_probe(source_item: Mapping[str, Any]) -> str:
    parse_summary = dict(source_item.get("parse_summary") or {})
    candidates = [
        source_item.get("source_text"),
        parse_summary.get("text_probe"),
        source_item.get("project_name"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            if len(text) > TEXT_PROBE_LIMIT:
                return text[:TEXT_PROBE_LIMIT] + "..."
            return text
    return ""


def _safe_snapshot_refs(source_item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "detail_snapshot_refs": [
            _safe_ref(ref, ("snapshot_id", "source_url", "document_completeness_state", "notice_version_chain_state"))
            for ref in list(source_item.get("detail_snapshot_refs") or [])
            if isinstance(ref, Mapping)
        ],
        "attachment_snapshot_refs": [
            _safe_ref(ref, ("snapshot_id", "attachment_url", "parse_state", "attachment_role_type"))
            for ref in list(source_item.get("attachment_snapshot_refs") or [])
            if isinstance(ref, Mapping)
        ],
    }


def _safe_ref(ref: Mapping[str, Any], allowed_keys: tuple[str, ...]) -> dict[str, str]:
    return {
        key: str(ref.get(key) or "")
        for key in allowed_keys
        if str(ref.get(key) or "")
    }


def _load_json_file(path: Path, label: str, blocking_reasons: list[str]) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(f"{label}_missing")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        blocking_reasons.append(f"{label}_load_failed:{exc}")
        return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    blocking_reasons.append(f"{label}_not_object")
    return {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _mapping_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        text = str(key or "")
        if not text:
            continue
        result[text] = _int_value(raw_count, default=0)
    return result


def _aggregate_signal_families(items: list[Mapping[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        families = dict(item.get("tailored_bid_signal_families") or {})
        for family, raw_count in families.items():
            key = str(family or "")
            if not key:
                continue
            result[key] = result.get(key, 0) + _int_value(raw_count, default=0)
    return dict(sorted(result.items()))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build internal TAILORED-REVIEW-001 sample adjudication package."
    )
    parser.add_argument("--rule-calibration-manifest-json", required=True)
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
    parser.add_argument("--review-sample-limit", type=int, default=DEFAULT_REVIEW_SAMPLE_LIMIT)
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_tailored_review_adjudication_manifest(
        rule_calibration_manifest_json=args.rule_calibration_manifest_json,
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
        review_sample_limit=args.review_sample_limit,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "tailored review adjudication "
            f"{result['tailored_review_adjudication_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONFIRMED_CLUE",
    "INSUFFICIENT_EVIDENCE",
    "LIKELY_FALSE_POSITIVE",
    "NEEDS_HUMAN_REVIEW",
    "TAILORED_REVIEW_ADJUDICATION_MANIFEST_OBJECT_TYPE",
    "build_tailored_review_adjudication_manifest",
]
