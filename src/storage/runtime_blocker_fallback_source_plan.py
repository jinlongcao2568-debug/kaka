from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


PLAN_KIND = "runtime_blocker_fallback_source_plan_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/runtime-blocker-fallback-source-plan-v1")


def build_runtime_blocker_fallback_source_plan(
    *,
    stage6_review_cycle_json: str | Path,
    release_field_query_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    cycle_path = Path(stage6_review_cycle_json)
    cycle = _read_json(cycle_path)
    manifest = _mapping(cycle.get("manifest"))
    controller_table = _mapping(manifest.get("runtime_blocker_subqueue_controller_table"))
    inferred_field_query = release_field_query_json or manifest.get("source_release_field_query_json")
    field_query_path = Path(str(inferred_field_query)) if str(inferred_field_query or "").strip() else None
    field_query = _read_json(field_query_path) if field_query_path and field_query_path.exists() else {}
    field_manifest = _mapping(field_query.get("manifest") or field_query)
    field_context = _field_context(field_manifest)

    source_records = [
        dict(record)
        for record in _records(controller_table.get("records"))
        if str(record.get("subqueue_route") or "") == "fallback_source"
    ]
    records = [
        _plan_record(record, field_context=field_context, cycle_ref=str(cycle_path), created_at=created_at)
        for record in source_records
    ]
    result = {
        "plan_kind": PLAN_KIND,
        "plan_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "stage6_review_cycle_json": str(cycle_path),
            "release_field_query_json": str(field_query_path or ""),
        },
        "summary": _summary(records),
        "records": records,
        "next_regression_execution_plan": _next_regression_execution_plan(records),
        "stage4_backfill_followup_queue_compatibility": {
            "queue_kind": "stage4_backfill_followup_queue_v1",
            "records_are_p13b_consumable": True,
            "p13b_entrypoint": "scripts/run-stage16-p13b-continuation-v1.ps1",
            "p13b_company_history_entrypoint": "storage.p13b_company_history_overlap_triage",
        },
        "safety": _safety(),
    }
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "runtime-blocker-fallback-source-plan-v1.json", result)
    _write_markdown(out_dir / "runtime-blocker-fallback-source-plan-v1.md", result)
    return result


def _plan_record(
    record: Mapping[str, Any],
    *,
    field_context: Mapping[str, Mapping[str, Any]],
    cycle_ref: str,
    created_at: str | None,
) -> dict[str, Any]:
    task_id = str(record.get("task_id") or "")
    project_id = str(record.get("project_id") or "")
    context = field_context.get(task_id) or field_context.get(project_id) or {}
    project_name = str(record.get("project_name") or context.get("project_name") or "")
    gap_detail = _gap_detail(record)
    route = _route(record)
    return {
        "followup_record_id": _stable_id("RUNTIME-BLOCKER-FALLBACK", project_id, task_id, route),
        "source_controller_queue_record_id": str(record.get("controller_queue_record_id") or ""),
        "source_next_subqueue_record_id": str(record.get("source_next_subqueue_record_id") or ""),
        "project_id": project_id,
        "project_name": project_name,
        "task_id": task_id,
        "task_type": str(record.get("task_type") or ""),
        "stage4_project_code_backfill_state": "RUNTIME_BLOCKER_FALLBACK_SOURCE_PLAN_READY",
        "stage4_project_code_backfill_gap_detail": gap_detail,
        "stage5_operational_review_bucket": "PUBLIC_SOURCE_FALLBACK_PLAN_REVIEW",
        "p13b_public_source_readback_state": "FALLBACK_SOURCE_PLAN_READY",
        "p13b_overlap_triage_state": "P13B_COMPANY_HISTORY_TRIAGE_REQUIRED",
        "candidate_companies": _dedupe(context.get("candidate_companies")),
        "responsible_person_names": _dedupe(context.get("responsible_person_names")),
        "candidate_notice_source_urls": _dedupe(context.get("candidate_notice_source_urls")),
        "project_source_urls": _dedupe(context.get("project_source_urls")),
        "context_source": str(context.get("context_source") or "runtime_blocker_controller_and_release_field_query"),
        "followup_route": route,
        "followup_queue_state": "FOLLOWUP_SOURCE_PLAN_REQUIRED",
        "worker_family": "source_adapter",
        "public_source_fallback_sequence": _fallback_sequence(project_id),
        "required_input": [
            "data_ggzy_company_history_or_bid_show_readback",
            "ygp_original_notice_readback_or_project_local_authority_source",
        ],
        "recommended_next_action": "run_p13b_company_history_overlap_triage_with_stage4_followup_queue_then_stage6_projection",
        "execution_priority": "MEDIUM_LOCAL_AUTHORITY_FALLBACK",
        "input_artifact_refs": [cycle_ref],
        "controller_consumable": True,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        **_safety(),
    }


def _field_context(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for task in _records(manifest.get("field_task_records")):
        task_id = str(task.get("field_query_task_id") or task.get("task_id") or "")
        project_id = str(task.get("project_id") or "")
        if not project_id:
            continue
        context = {
            "project_name": str(task.get("project_name") or ""),
            "candidate_companies": _dedupe(
                [
                    *_list(task.get("candidate_group_members")),
                    *_list(task.get("matched_company_names")),
                    *_list(task.get("company_query_variants")),
                    _mapping(task.get("query_params")).get("candidateCompanyName"),
                    _mapping(task.get("query_params")).get("companyName"),
                ]
            ),
            "responsible_person_names": _dedupe(
                [
                    task.get("responsible_person_name"),
                    _mapping(task.get("query_params")).get("personName"),
                    _mapping(task.get("query_params")).get("projectManagerName"),
                ]
            ),
            "candidate_notice_source_urls": _dedupe(
                [task.get("trigger_source_url"), _mapping(task.get("query_params")).get("triggerSourceUrl")]
            ),
            "project_source_urls": _dedupe(
                [
                    task.get("trigger_source_url"),
                    _mapping(task.get("query_params")).get("triggerSourceUrl"),
                    task.get("source_url"),
                ]
            ),
            "context_source": "release_field_query_field_task_records",
        }
        if task_id:
            by_key[task_id] = context
        existing = by_key.get(project_id, {})
        by_key[project_id] = _merge_context(existing, context)
    return by_key


def _merge_context(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_name": str(left.get("project_name") or right.get("project_name") or ""),
        "candidate_companies": _dedupe([*_list(left.get("candidate_companies")), *_list(right.get("candidate_companies"))]),
        "responsible_person_names": _dedupe(
            [*_list(left.get("responsible_person_names")), *_list(right.get("responsible_person_names"))]
        ),
        "candidate_notice_source_urls": _dedupe(
            [*_list(left.get("candidate_notice_source_urls")), *_list(right.get("candidate_notice_source_urls"))]
        ),
        "project_source_urls": _dedupe([*_list(left.get("project_source_urls")), *_list(right.get("project_source_urls"))]),
        "context_source": "release_field_query_field_task_records",
    }


def _gap_detail(record: Mapping[str, Any]) -> str:
    if str(record.get("blocker_state") or "") == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED"
    return "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"


def _route(record: Mapping[str, Any]) -> str:
    if str(record.get("blocker_state") or "") == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return "local_authority_fallback_source_planning"
    return "public_source_retry_then_local_authority_fallback"


def _fallback_sequence(project_id: str) -> list[dict[str, Any]]:
    return [
        _fallback_step(project_id, "data_ggzy_company_history_search", "search_data_ggzy_company_history_before_local_authority_fallback"),
        _fallback_step(project_id, "data_ggzy_bid_list_pagination", "page_bid_list_with_bounded_budget"),
        _fallback_step(project_id, "data_ggzy_bid_show_readback", "read_bid_show_text_and_original_notice_url"),
        _fallback_step(project_id, "ygp_original_notice_readback", "read_ygp_original_notice_identifiers_for_p13b_or_stage4_bridge"),
        _fallback_step(project_id, "project_local_authority_public_source", "query_historical_project_location_housing_or_supervisory_authority"),
    ]


def _fallback_step(project_id: str, source_kind: str, action: str) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "action": action,
        "project_id": project_id,
        "input_state": "INPUT_REQUIRED_OR_RETRY_WITH_BUDGET",
        "gdcic_project_code_route_allowed": False,
        "gdcic_project_code_route_policy": "PUBLIC_SOURCE_IDENTIFIER_NOT_SENT_TO_GDCIC_UNLESS_EXPLICIT_PROVINCIAL_CODE",
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _next_regression_execution_plan(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    project_ids = _dedupe(record.get("project_id") for record in records)
    return {
        "plan_state": "FALLBACK_SOURCE_PLAN_READY_FOR_P13B" if records else "NO_FALLBACK_SOURCE_RECORDS",
        "target_project_ids": project_ids,
        "target_project_count": len(project_ids),
        "public_source_fallback_sequence": [
            "data_ggzy_company_history_search",
            "data_ggzy_bid_list_pagination",
            "data_ggzy_bid_show_readback",
            "ygp_original_notice_readback",
            "project_local_authority_public_source",
        ],
        "recommended_switches": ["RunP13BPublicSourceChain", "RunStage6MergedProjection"],
        "recommended_parameter_overrides": {
            "MaxLiveP13BCompanies": max(8, len(project_ids) * 2),
            "MaxBidRecordsPerCompany": 3,
            "MaxBidListPagesPerCompany": 2,
            "MaxLongTailBidShowsPerCompany": 1,
        },
        "default_execution_mode": "PLAN_OR_EXISTING_ARTIFACT_REPLAY",
        "live_execution_enabled_by_default": False,
        "operator_live_public_query_decision_required": True,
        "safety_invariants": _safety(),
    }


def _summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "fallback_source_plan_record_count": len(records),
        "project_count": len(set(_dedupe(record.get("project_id") for record in records))),
        "followup_route_counts": _counts(record.get("followup_route") for record in records),
        "task_type_counts": _counts(record.get("task_type") for record in records),
        "candidate_company_present_count": sum(1 for record in records if _list(record.get("candidate_companies"))),
        "candidate_notice_url_present_count": sum(1 for record in records if _list(record.get("candidate_notice_source_urls"))),
        "records_are_p13b_consumable": True,
        **_safety(),
    }


def _safety() -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "live_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
        "gdcic_project_code_digit_guessing_allowed": False,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        value = value.get("records")
    return [record for record in value if isinstance(record, Mapping)] if isinstance(value, list) else []


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps([str(part or "") for part in parts], ensure_ascii=False, sort_keys=True)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    summary = _mapping(payload.get("summary"))
    lines = [
        "# Runtime Blocker Fallback Source Plan v1",
        "",
        f"- fallback_source_plan_record_count: {summary.get('fallback_source_plan_record_count', 0)}",
        f"- project_count: {summary.get('project_count', 0)}",
        f"- followup_route_counts: {json.dumps(summary.get('followup_route_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- task_type_counts: {json.dumps(summary.get('task_type_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- next_regression_execution_plan: {json.dumps(payload.get('next_regression_execution_plan', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "customer_visible_allowed=false; live_execution_enabled=false; query_miss_is_not_clearance=true; no_legal_conclusion=true",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage6-review-cycle-json", required=True)
    parser.add_argument("--release-field-query-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_runtime_blocker_fallback_source_plan(
        stage6_review_cycle_json=args.stage6_review_cycle_json,
        release_field_query_json=args.release_field_query_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result.get("summary") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
