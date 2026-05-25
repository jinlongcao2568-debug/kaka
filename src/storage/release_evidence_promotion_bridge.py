from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


RELEASE_EVIDENCE_PROMOTION_BRIDGE_KIND = "release_evidence_promotion_bridge_v1_manifest"
RELEASE_EVIDENCE_PROMOTION_BRIDGE_VERSION = 1
RELEASE_EVIDENCE_PROMOTION_BRIDGE_ADAPTER_ID = "release-evidence-promotion-bridge-v1-builder"

DEFAULT_DIAGNOSTIC_ROOT = Path("tmp/evaluation-real-samples/stage1-6-latest-scoreboard-diagnostic-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/release-evidence-promotion-bridge-v1")
DEFAULT_DIAGNOSTIC_FILENAME = "stage1-6-latest-scoreboard-diagnostic-v1.json"

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
ALLOWED_ADAPTER_RESULT_STATES = ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"]
PROMOTION_STATE = "PUBLIC_IDENTIFIER_READY_NEEDS_B_OR_C_RELEASE_EVIDENCE_READBACK"
GDCIC_ROUTE_BLOCK_REASON = "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE"

TARGET_POLICY = {
    "construction_permit": {
        "release_evidence_grade_on_match": "B_ENHANCEMENT_OFFICIAL_READBACK",
        "release_evidence_source_role": "permit_or_license_window_enhancement",
    },
    "contract_performance": {
        "release_evidence_grade_on_match": "B_ENHANCEMENT_OFFICIAL_READBACK",
        "release_evidence_source_role": "contract_or_performance_window_enhancement",
    },
    "completion_acceptance": {
        "release_evidence_grade_on_match": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
        "release_evidence_source_role": "completion_or_acceptance_release_explanation",
    },
    "project_manager_change_notice": {
        "release_evidence_grade_on_match": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
        "release_evidence_source_role": "project_manager_change_or_responsibility_window_split",
    },
}


def build_release_evidence_promotion_bridge(
    *,
    diagnostic_json: str | Path | None = None,
    diagnostic_root: str | Path = DEFAULT_DIAGNOSTIC_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    diagnostic_path = Path(diagnostic_json) if diagnostic_json else Path(diagnostic_root) / DEFAULT_DIAGNOSTIC_FILENAME
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    diagnostic = _load_json(diagnostic_path, blocking_reasons)
    queue = diagnostic.get("release_evidence_promotion_queue") if isinstance(diagnostic, Mapping) else {}
    queue_records = [
        dict(record)
        for record in _list(queue.get("records") if isinstance(queue, Mapping) else [])
        if isinstance(record, Mapping) and str(record.get("promotion_state") or "") == PROMOTION_STATE
    ]
    task_records = [
        task
        for record in queue_records
        for task in _adapter_tasks_for_promotion_record(record, created_at=created)
    ]
    summary = _summary(
        queue_records=queue_records,
        task_records=task_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": RELEASE_EVIDENCE_PROMOTION_BRIDGE_VERSION,
        "manifest_kind": RELEASE_EVIDENCE_PROMOTION_BRIDGE_KIND,
        "adapter_id": RELEASE_EVIDENCE_PROMOTION_BRIDGE_ADAPTER_ID,
        "pipeline_stage": "ReleaseEvidencePromotionBridgeV1",
        "manifest_id": f"RELEASE-EVIDENCE-PROMOTION-BRIDGE-{_fingerprint({'records': queue_records, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_stage1_6_latest_scoreboard_diagnostic_json": str(diagnostic_path),
        "source_release_evidence_promotion_queue_record_count": len(queue_records),
        "summary": summary,
        "release_evidence_promotion_records": queue_records,
        "release_evidence_adapter_task_records": task_records,
        "project_code_backfill_records": _project_code_backfill_records(queue_records, created_at=created),
        "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "query_miss_is_not_clearance": True,
            "not_found_blocked_are_not_clearance": True,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result = {
        "release_evidence_promotion_bridge_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, task_records)
    return result


def _adapter_tasks_for_promotion_record(record: Mapping[str, Any], *, created_at: str) -> list[dict[str, Any]]:
    project_id = str(record.get("project_id") or "").strip()
    project_name = str(record.get("project_name") or "").strip()
    ygp_project_codes = _dedupe(record.get("ygp_project_code_variants"))
    ygp_biz_codes = _dedupe(record.get("ygp_biz_code_variants"))
    ygp_site_codes = _dedupe(record.get("ygp_site_code_variants"))
    ygp_notice_ids = _dedupe(record.get("ygp_notice_id_variants"))
    keywords = _dedupe([project_name, *ygp_project_codes, *ygp_biz_codes, *ygp_site_codes, *ygp_notice_ids])
    rows: list[dict[str, Any]] = []
    for target_type, policy in TARGET_POLICY.items():
        task_id = _stable_id("REL-EVIDENCE-PROMOTION-BRIDGE-TASK", project_id, target_type, ygp_project_codes, ygp_notice_ids)
        rows.append(
            {
                "release_evidence_adapter_task_id": task_id,
                "source_release_evidence_probe_task_id": _stable_id("PROMOTION-QUEUE-RECORD", project_id, ygp_project_codes, ygp_notice_ids),
                "source_release_evidence_probe_plan_id": "STAGE1-6-LATEST-SCOREBOARD-DIAGNOSTIC-PROMOTION-QUEUE",
                "input_source_kind": "stage1_6_latest_scoreboard_release_evidence_promotion_queue",
                "project_id": project_id,
                "project_name": project_name,
                "candidate_company_name": "",
                "matched_person_names": [],
                "release_evidence_target_type": target_type,
                "release_evidence_grade_on_match": policy["release_evidence_grade_on_match"],
                "release_evidence_source_role": policy["release_evidence_source_role"],
                "initial_release_evidence_abcd_grade": "PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE",
                "release_evidence_query_region_code": "CN-GD",
                "release_evidence_query_region_basis": "stage1_6_promotion_queue_public_identifier_route",
                "local_housing_authority_adapter_scope": "CN_GD_B_OR_C_OFFICIAL_READBACK_FROM_PROMOTION_QUEUE",
                "local_housing_authority_adapter_region_code": "CN-GD",
                "non_guangdong_release_adapter_rule": "",
                "jurisdiction_local_housing_adapter": {},
                "jurisdiction_adapter_resolution_state": "CN_GD_TARGET_TYPE_OVERRIDE_DEFERRED_TO_FIELD_QUERY",
                "no_fallback_to_guangdong_or_guangzhou": False,
                "source_entry_id": "",
                "subsource_id": "",
                "source_profile_id": "",
                "source_name": "",
                "source_family": "stage1_6_promotion_queue_to_b_or_c_release_evidence_readback",
                "source_url": "",
                "api_url": "",
                "official_reference_url": "",
                "trigger_source_url": "",
                "query_params": {
                    "projectId": project_id,
                    "projectName": project_name,
                    "projectCode": "",
                    "sourceProjectCode": "",
                    "projectCodeVariants": ygp_project_codes,
                    "gdcicProjectCodeVariants": [],
                    "tradeProjectCode": "",
                    "ygpProjectCodeVariants": ygp_project_codes,
                    "ygpBizCodeVariants": ygp_biz_codes,
                    "ygpSiteCodeVariants": ygp_site_codes,
                    "ygpNoticeIdVariants": ygp_notice_ids,
                    "gdcic_project_code_route_allowed": False,
                    "gdcicProjectCodeRouteAllowed": False,
                    "targetSourceTypes": [target_type],
                    "releaseEvidenceTargetType": target_type,
                    "keywords": keywords,
                },
                "next_adapter": "guangdong_local_field_query_probe",
                "runtime_status": "PLAN_ONLY_PROMOTION_BRIDGE_READY",
                "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
                "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
                "matched_means": "official_release_evidence_readback_supports_b_or_c_review_not_legal_conclusion",
                "not_found_means": "source_query_miss_or_no_public_match_not_clearance",
                "blocked_means": "source_blocked_or_unavailable_needs_review",
                "needs_browser_means": "browser_or_authorized_runtime_required_before_field_readback",
                "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                "readback_ready": False,
                "gdcic_project_code_route_allowed": False,
                "gdcic_route_block_reason": GDCIC_ROUTE_BLOCK_REASON,
                "must_not_extract_from_full_text_numbers": True,
                "recommended_next_action": "run_guangdong_local_field_query_probe_for_b_or_c_official_readback_before_limited_projection",
                "query_miss_is_not_clearance": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "created_at": created_at,
            }
        )
    return rows


def _project_code_backfill_records(records: list[Mapping[str, Any]], *, created_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        rows.append(
            {
                "project_code_backfill_record_id": _stable_id(
                    "PROMOTION-BRIDGE-PROJECT-CODE-BACKFILL",
                    project_id,
                    record.get("ygp_project_code_variants"),
                    record.get("ygp_notice_id_variants"),
                ),
                "project_id": project_id,
                "project_name": str(record.get("project_name") or ""),
                "project_code_backfill_state": "PUBLIC_IDENTIFIER_BACKFILLED_FOR_STAGE4_RELEASE_EVIDENCE_PROMOTION",
                "stage4_public_identifier_backfill_source": str(record.get("stage4_public_identifier_backfill_source") or ""),
                "ygp_project_code_variants": _dedupe(record.get("ygp_project_code_variants")),
                "ygp_biz_code_variants": _dedupe(record.get("ygp_biz_code_variants")),
                "ygp_site_code_variants": _dedupe(record.get("ygp_site_code_variants")),
                "ygp_notice_id_variants": _dedupe(record.get("ygp_notice_id_variants")),
                "gdcic_project_code_route_allowed": False,
                "gdcic_route_block_reason": GDCIC_ROUTE_BLOCK_REASON,
                "must_not_extract_from_full_text_numbers": True,
                "recommended_next_action": "run_b_or_c_release_evidence_readback_not_limited_projection_yet",
                "created_at": created_at,
                "query_miss_is_not_clearance": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _summary(
    *,
    queue_records: list[Mapping[str, Any]],
    task_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "promotion_bridge_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "source_promotion_queue_record_count": len(queue_records),
        "release_evidence_adapter_task_count": len(task_records),
        "project_count": len({str(record.get("project_id") or "") for record in queue_records if str(record.get("project_id") or "")}),
        "target_type_counts": _counts(record.get("release_evidence_target_type") for record in task_records),
        "grade_on_match_counts": _counts(record.get("release_evidence_grade_on_match") for record in task_records),
        "gdcic_project_code_route_allowed_counts": _counts(record.get("gdcic_project_code_route_allowed") for record in task_records),
        "adapter_result_state_counts": _counts(record.get("adapter_result_state") for record in task_records),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "not_found_blocked_are_not_clearance": True,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(out_dir: Path, result: dict[str, Any], task_records: list[Mapping[str, Any]]) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *list(result.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    result["manifest"]["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result["manifest"].items() if key != "manifest_sha256"}
    )
    _write_json(out_dir / "release-evidence-promotion-bridge-v1.json", result)
    _write_json(out_dir / "release-evidence-adapter-task-table.json", {"summary": result["summary"], "records": task_records})
    _write_json(out_dir / "stage4-release-adapter-bridge-plan.json", result["manifest"])
    _write_json(out_dir / "release-evidence-adapter-plan-v1.json", result)


def _load_json(path: Path, blocking_reasons: list[str]) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append("stage1_6_latest_scoreboard_diagnostic_missing")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blocking_reasons.append("stage1_6_latest_scoreboard_diagnostic_invalid_json")
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in _list(values):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value).lower() if isinstance(value, bool) else str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint(parts)[:16]}"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build release evidence promotion bridge from latest Stage1-6 diagnostic.")
    parser.add_argument("--diagnostic-json", default="")
    parser.add_argument("--diagnostic-root", default=str(DEFAULT_DIAGNOSTIC_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_release_evidence_promotion_bridge(
        diagnostic_json=args.diagnostic_json or None,
        diagnostic_root=args.diagnostic_root,
        output_root=args.output_root,
        created_at=args.created_at or None,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RELEASE_EVIDENCE_PROMOTION_BRIDGE_KIND",
    "build_release_evidence_promotion_bridge",
]
