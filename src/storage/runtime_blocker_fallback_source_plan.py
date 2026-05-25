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
    cycle = _unwrap_runtime_entrypoint_cycle(cycle)
    manifest = _mapping(cycle.get("manifest"))
    controller_table = _mapping(manifest.get("runtime_blocker_subqueue_controller_table"))
    nested_refs = _nested_continuation_input_refs(cycle=cycle, manifest=manifest)
    stage4_refs = _stage4_followup_continuation_input_refs(manifest)
    inferred_field_query = (
        release_field_query_json
        or manifest.get("source_release_field_query_json")
        or nested_refs.get("effective_release_field_query_json")
        or nested_refs.get("effective_supplemental_release_field_query_json")
        or stage4_refs.get("effective_release_field_query_json")
        or stage4_refs.get("effective_supplemental_release_field_query_json")
    )
    field_query_paths = _existing_paths(inferred_field_query)
    field_context = _merged_field_context(field_query_paths)
    stage4_followup_context = _stage4_followup_context(manifest)
    continuation_input_refs = _continuation_input_refs(
        cycle=cycle,
        manifest=manifest,
        field_query_paths=field_query_paths,
        stage4_refs=stage4_refs,
    )
    scoreboard_context = _scoreboard_project_context(continuation_input_refs.get("prior_scoreboard_json"))
    project_context = _merge_context_maps(field_context, scoreboard_context)

    source_records = [
        dict(record)
        for record in _records(controller_table.get("records"))
        if str(record.get("subqueue_route") or "") == "fallback_source"
    ]
    records = [
        _plan_record(
            record,
            field_context=project_context,
            stage4_followup_context=stage4_followup_context,
            cycle_ref=str(cycle_path),
            created_at=created_at,
        )
        for record in source_records
    ]
    stage4_bridge_records = _stage4_release_adapter_bridge_records(records, created_at=created_at)
    stage4_bridge_plan = _stage4_release_adapter_bridge_plan(
        records=stage4_bridge_records,
        source_cycle_json=cycle_path,
        created_at=created_at,
    )
    result = {
        "plan_kind": PLAN_KIND,
        "plan_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "stage6_review_cycle_json": str(cycle_path),
            "release_field_query_json": ";".join(str(path) for path in field_query_paths),
        },
        "continuation_input_refs": continuation_input_refs,
        "summary": _summary(records, stage4_bridge_records=stage4_bridge_records),
        "records": records,
        "stage4_release_adapter_bridge_plan": stage4_bridge_plan,
        "next_regression_execution_plan": _next_regression_execution_plan(
            records,
            stage4_bridge_records=stage4_bridge_records,
            continuation_input_refs=continuation_input_refs,
        ),
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
    _write_json(out_dir / "stage4-release-adapter-bridge-plan.json", stage4_bridge_plan)
    _write_markdown(out_dir / "runtime-blocker-fallback-source-plan-v1.md", result)
    return result


def _plan_record(
    record: Mapping[str, Any],
    *,
    field_context: Mapping[str, Mapping[str, Any]],
    stage4_followup_context: Mapping[str, Mapping[str, Any]],
    cycle_ref: str,
    created_at: str | None,
) -> dict[str, Any]:
    task_id = str(record.get("task_id") or "")
    project_id = str(record.get("project_id") or "")
    followup_context = _lookup_context(
        stage4_followup_context,
        task_id,
        project_id,
        record.get("blocker_ledger_id"),
        *_list(record.get("source_blocker_ledger_ids")),
    )
    field_record_context = field_context.get(task_id) or field_context.get(project_id) or {}
    context = _merge_context(field_record_context, followup_context)
    project_name = str(record.get("project_name") or context.get("project_name") or "")
    gap_detail = _gap_detail(record)
    route = _route(record, context)
    fallback_sequence = _merge_fallback_sequence(
        _fallback_sequence(project_id),
        _list(context.get("public_source_fallback_sequence")),
        project_id=project_id,
    )
    required_input = _dedupe(
        [
            *_list(record.get("required_input")),
            *_list(context.get("required_input")),
            "data_ggzy_company_history_or_bid_show_readback",
            "ygp_original_notice_readback_or_project_local_authority_source",
        ]
    )
    if route == "local_authority_fallback_after_ygp_not_found":
        required_input = _dedupe(
            [
                item
                for item in required_input
                if item != "ygp_original_notice_readback_or_project_local_authority_source"
            ]
            + ["project_local_authority_public_source_endpoint_or_alternate_official_source"]
        )
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
        "stage4_followup_route": str(context.get("followup_route") or ""),
        "stage4_official_readback_context": _mapping(context.get("stage4_official_readback_context")),
        "local_authority_readback_context": _mapping(context.get("local_authority_readback_context")),
        "alternate_local_authority_source_candidates": _records(context.get("alternate_local_authority_source_candidates")),
        "followup_route": route,
        "followup_queue_state": "FOLLOWUP_SOURCE_PLAN_REQUIRED",
        "worker_family": "source_adapter",
        "public_source_fallback_sequence": fallback_sequence,
        "stage4_public_source_fallback_sequence": fallback_sequence,
        "required_input": required_input,
        "recommended_next_action": _recommended_next_action_for_route(route),
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
            "stage4_official_readback_context": _stage4_official_readback_context_from_field_task(task),
        }
        if task_id:
            by_key[task_id] = context
        existing = by_key.get(project_id, {})
        by_key[project_id] = _merge_context(existing, context)
    return by_key


def _merged_field_context(paths: list[Path]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in paths:
        field_query = _read_json(path)
        field_manifest = _mapping(field_query.get("manifest") or field_query)
        for key, context in _field_context(field_manifest).items():
            out[key] = _merge_context(out.get(key, {}), context)
    return out


def _merge_context_maps(
    left: Mapping[str, Mapping[str, Any]],
    right: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for source in (left, right):
        for key, context in source.items():
            out[str(key)] = _merge_context(out.get(str(key), {}), context)
    return out


def _scoreboard_project_context(scoreboard_json: Any) -> dict[str, dict[str, Any]]:
    path_text = str(scoreboard_json or "").strip()
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        return {}
    payload = _read_json(path)
    rows = payload.get("project_rows")
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        project_id = str(row.get("project_id") or "").strip()
        if not project_id:
            continue
        context = _scoreboard_row_context(row)
        out[project_id] = _merge_context(out.get(project_id, {}), context)
    return out


def _scoreboard_row_context(row: Mapping[str, Any]) -> dict[str, Any]:
    official_context = {
        "stage4_official_readback_context_state": (
            "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED"
            if _dedupe(
                [
                    *_list(row.get("p13b_ygp_project_code_variants")),
                    *_list(row.get("p13b_overlap_ygp_project_code_variants")),
                    *_list(row.get("p13b_ygp_biz_code_variants")),
                    *_list(row.get("p13b_overlap_ygp_biz_code_variants")),
                    *_list(row.get("p13b_ygp_site_code_variants")),
                    *_list(row.get("p13b_overlap_ygp_site_code_variants")),
                    *_list(row.get("p13b_ygp_notice_id_variants")),
                    *_list(row.get("p13b_overlap_ygp_notice_id_variants")),
                ]
            )
            else ""
        ),
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "ygp_project_code_variants": _dedupe(
            [*_list(row.get("p13b_ygp_project_code_variants")), *_list(row.get("p13b_overlap_ygp_project_code_variants"))]
        ),
        "ygp_biz_code_variants": _dedupe(
            [*_list(row.get("p13b_ygp_biz_code_variants")), *_list(row.get("p13b_overlap_ygp_biz_code_variants"))]
        ),
        "ygp_site_code_variants": _dedupe(
            [*_list(row.get("p13b_ygp_site_code_variants")), *_list(row.get("p13b_overlap_ygp_site_code_variants"))]
        ),
        "ygp_notice_id_variants": _dedupe(
            [*_list(row.get("p13b_ygp_notice_id_variants")), *_list(row.get("p13b_overlap_ygp_notice_id_variants"))]
        ),
        "gdcic_project_code_route_allowed": False,
        "gdcic_project_code_route_policy": str(
            row.get("stage4_gdcic_project_code_route_policy")
            or "PUBLIC_SOURCE_IDENTIFIER_NOT_SENT_TO_GDCIC_UNLESS_EXPLICIT_PROVINCIAL_CODE"
        ),
        "must_not_extract_from_full_text_numbers": True,
    }
    return {
        "project_name": str(row.get("project_name") or ""),
        "candidate_companies": _dedupe(
            [
                *_list(row.get("candidate_companies")),
                *_list(row.get("candidate_company_names")),
                *_list(row.get("candidate_group_members")),
            ]
        ),
        "responsible_person_names": _dedupe(
            [
                *_list(row.get("responsible_person_names")),
                *_list(row.get("project_manager_names")),
                row.get("responsible_person_name"),
                row.get("project_manager_name"),
            ]
        ),
        "candidate_notice_source_urls": _dedupe(
            [
                *_list(row.get("candidate_notice_source_urls")),
                *_list(row.get("source_urls")),
                row.get("candidate_notice_source_url"),
                row.get("source_url"),
            ]
        ),
        "project_source_urls": _dedupe(
            [
                *_list(row.get("project_source_urls")),
                *_list(row.get("source_urls")),
                row.get("source_url"),
                row.get("candidate_notice_source_url"),
            ]
        ),
        "context_source": "stage1_6_scoreboard_project_rows",
        "stage4_official_readback_context": official_context,
    }


def _stage4_followup_context(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    queue_path_text = str(manifest.get("source_stage4_backfill_followup_queue_json") or "").strip()
    if not queue_path_text:
        status_json = str(manifest.get("source_stage6_review_loop_status_json") or "").strip()
        if status_json.endswith("stage4-backfill-followup-queue-v1.json"):
            queue_path_text = status_json
    if not queue_path_text:
        return {}
    queue_path = Path(queue_path_text)
    if not queue_path.exists():
        return {}
    queue = _read_json(queue_path)
    by_key: dict[str, dict[str, Any]] = {}
    for record in _records(queue.get("records") or _mapping(queue.get("manifest")).get("records")):
        official_context = _mapping(record.get("stage4_official_readback_context"))
        local_context = _mapping(record.get("local_authority_readback_context"))
        context = {
            "project_name": str(
                record.get("project_name")
                or official_context.get("project_name")
                or local_context.get("project_name")
                or ""
            ),
            "candidate_companies": _dedupe(_list(record.get("candidate_companies"))),
            "responsible_person_names": _dedupe(_list(record.get("responsible_person_names"))),
            "candidate_notice_source_urls": _dedupe(_list(record.get("candidate_notice_source_urls"))),
            "project_source_urls": _dedupe(_list(record.get("project_source_urls"))),
            "context_source": str(record.get("context_source") or "stage4_backfill_followup_queue"),
            "followup_route": str(record.get("followup_route") or ""),
            "stage4_official_readback_context": official_context,
            "local_authority_readback_context": local_context,
            "alternate_local_authority_source_candidates": _records(record.get("alternate_local_authority_source_candidates")),
            "public_source_fallback_sequence": _list(record.get("public_source_fallback_sequence")),
            "required_input": _list(record.get("required_input")),
        }
        for key in _dedupe([record.get("followup_record_id"), record.get("project_id")]):
            by_key[key] = _merge_context(by_key.get(key, {}), context)
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
        "context_source": str(left.get("context_source") or right.get("context_source") or "release_field_query_field_task_records"),
        "followup_route": str(left.get("followup_route") or right.get("followup_route") or ""),
        "stage4_official_readback_context": _merge_official_readback_context(
            left.get("stage4_official_readback_context"),
            right.get("stage4_official_readback_context"),
        ),
        "local_authority_readback_context": _merge_mapping(
            left.get("local_authority_readback_context"),
            right.get("local_authority_readback_context"),
        ),
        "alternate_local_authority_source_candidates": _dedupe_records(
            *_records(left.get("alternate_local_authority_source_candidates")),
            *_records(right.get("alternate_local_authority_source_candidates")),
        ),
        "public_source_fallback_sequence": [
            *_list(left.get("public_source_fallback_sequence")),
            *_list(right.get("public_source_fallback_sequence")),
        ],
        "required_input": _dedupe([*_list(left.get("required_input")), *_list(right.get("required_input"))]),
    }


def _stage4_official_readback_context_from_field_task(task: Mapping[str, Any]) -> Mapping[str, Any]:
    params = _mapping(task.get("query_params"))
    ygp_project_codes = _dedupe(
        [
            *_list(params.get("ygpProjectCodeVariants")),
            *_list(params.get("ygp_project_code_variants")),
            params.get("ygpProjectCode"),
            params.get("ygp_project_code"),
        ]
    )
    ygp_biz_codes = _dedupe(
        [*_list(params.get("ygpBizCodeVariants")), *_list(params.get("ygp_biz_code_variants")), params.get("ygpBizCode")]
    )
    ygp_site_codes = _dedupe(
        [*_list(params.get("ygpSiteCodeVariants")), *_list(params.get("ygp_site_code_variants")), params.get("ygpSiteCode")]
    )
    ygp_notice_ids = _dedupe(
        [*_list(params.get("ygpNoticeIdVariants")), *_list(params.get("ygp_notice_id_variants")), params.get("ygpNoticeId")]
    )
    if not any([ygp_project_codes, ygp_biz_codes, ygp_site_codes, ygp_notice_ids]):
        return {}
    return {
        "stage4_official_readback_context_state": "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED",
        "project_id": str(task.get("project_id") or params.get("projectId") or ""),
        "project_name": str(task.get("project_name") or params.get("projectName") or ""),
        "ygp_project_code_variants": ygp_project_codes,
        "ygp_biz_code_variants": ygp_biz_codes,
        "ygp_site_code_variants": ygp_site_codes,
        "ygp_notice_id_variants": ygp_notice_ids,
        "gdcic_project_code_route_allowed": False,
        "gdcic_project_code_route_policy": "PUBLIC_SOURCE_IDENTIFIER_NOT_SENT_TO_GDCIC_UNLESS_EXPLICIT_PROVINCIAL_CODE",
        "must_not_extract_from_full_text_numbers": True,
    }


def _gap_detail(record: Mapping[str, Any]) -> str:
    if str(record.get("blocker_state") or "") == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED"
    return "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"


def _route(record: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> str:
    context_route = str(_mapping(context).get("followup_route") or "")
    if context_route:
        return context_route
    task_type = str(record.get("task_type") or "")
    if (
        task_type == "ygp_original_readback_backfill"
        and str(record.get("blocker_state") or "") == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED"
    ):
        return "local_authority_fallback_after_ygp_not_found"
    if task_type:
        return task_type
    if str(record.get("blocker_state") or "") == "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED":
        return "local_authority_fallback_source_planning"
    return "public_source_retry_then_local_authority_fallback"


def _recommended_next_action_for_route(route: str) -> str:
    if route == "local_authority_fallback_after_ygp_not_found":
        return "resolve_project_local_authority_public_source_endpoint_then_run_local_authority_readback_without_clearance_claim"
    return "run_p13b_company_history_overlap_triage_with_stage4_followup_queue_then_stage6_projection"


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


def _merge_fallback_sequence(
    default_sequence: list[Mapping[str, Any]],
    source_sequence: list[Any],
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in [*default_sequence, *source_sequence]:
        mapped = dict(_mapping(step))
        source_kind = str(mapped.get("source_kind") or "").strip()
        if not source_kind or source_kind in seen:
            continue
        seen.add(source_kind)
        mapped.setdefault("project_id", project_id)
        mapped.setdefault("input_state", "INPUT_REQUIRED_OR_RETRY_WITH_BUDGET")
        mapped.setdefault("gdcic_project_code_route_allowed", False)
        mapped.setdefault(
            "gdcic_project_code_route_policy",
            "PUBLIC_SOURCE_IDENTIFIER_NOT_SENT_TO_GDCIC_UNLESS_EXPLICIT_PROVINCIAL_CODE",
        )
        mapped.setdefault("customer_visible_allowed", False)
        mapped.setdefault("query_miss_is_not_clearance", True)
        mapped.setdefault("no_legal_conclusion", True)
        merged.append(mapped)
    return merged


def _next_regression_execution_plan(
    records: list[Mapping[str, Any]],
    *,
    stage4_bridge_records: list[Mapping[str, Any]],
    continuation_input_refs: Mapping[str, Any],
) -> dict[str, Any]:
    project_ids = _dedupe(record.get("project_id") for record in records)
    stage4_bridge_project_ids = _dedupe(record.get("project_id") for record in stage4_bridge_records)
    return {
        "plan_state": "FALLBACK_SOURCE_PLAN_READY_FOR_P13B" if records else "NO_FALLBACK_SOURCE_RECORDS",
        "runner_entrypoint": "scripts/run-stage1-6-sellable-rate-regression-v1.ps1",
        "stage4_release_adapter_bridge_plan_json": "stage4-release-adapter-bridge-plan.json",
        "stage4_release_adapter_bridge_project_ids": stage4_bridge_project_ids,
        "stage4_release_adapter_bridge_project_count": len(stage4_bridge_project_ids),
        "continuation_input_refs": dict(continuation_input_refs),
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


def _continuation_input_refs(
    *,
    cycle: Mapping[str, Any],
    manifest: Mapping[str, Any],
    field_query_paths: list[Path],
    stage4_refs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    existing = _nested_continuation_input_refs(cycle=cycle, manifest=manifest)
    if stage4_refs:
        existing = {**stage4_refs, **existing}
    stage6_status_json = (
        existing.get("prior_stage6_status_json")
        or manifest.get("source_stage6_review_loop_status_json")
        or manifest.get("stage6_status_json")
    )
    stage6_status_root = existing.get("effective_stage6_status_root") or _parent_if_file_exists(stage6_status_json)
    field_query_json = ";".join(str(path) for path in field_query_paths)
    field_query_root = existing.get("effective_release_field_query_root") or _joined_parent_paths(field_query_paths)
    gdcic_json = existing.get("effective_gdcic_browser_readback_json") or manifest.get("source_gdcic_browser_readback_json")
    gdcic_root = existing.get("effective_gdcic_browser_readback_root") or _parent_if_file_exists(gdcic_json)
    scoreboard_json = (
        existing.get("prior_scoreboard_json")
        or existing.get("effective_stage1_6_scoreboard_json")
        or manifest.get("source_stage1_6_scoreboard_json")
    )
    scoreboard_path = Path(str(scoreboard_json)) if str(scoreboard_json or "").strip() else None
    pressure_root = existing.get("effective_pressure_root") or _pressure_root_from_scoreboard(scoreboard_path)
    return {
        "prior_scoreboard_json": str(scoreboard_path or ""),
        "effective_pressure_root": str(pressure_root or ""),
        "effective_release_field_query_json": str(field_query_json or existing.get("effective_release_field_query_json") or ""),
        "effective_release_field_query_root": str(field_query_root or ""),
        "effective_supplemental_release_field_query_json": str(
            existing.get("effective_supplemental_release_field_query_json") or ""
        ),
        "effective_supplemental_release_field_query_root": str(
            existing.get("effective_supplemental_release_field_query_root") or ""
        ),
        "effective_runtime_blocker_next_subqueue_json": str(
            existing.get("effective_runtime_blocker_next_subqueue_json")
            or manifest.get("source_runtime_blocker_next_subqueue_json")
            or ""
        ),
        "effective_runtime_blocker_next_subqueue_root": str(
            existing.get("effective_runtime_blocker_next_subqueue_root")
            or _parent_if_file_exists(manifest.get("source_runtime_blocker_next_subqueue_json"))
            or ""
        ),
        "effective_gdcic_browser_readback_json": str(gdcic_json or ""),
        "effective_gdcic_browser_readback_root": str(gdcic_root or ""),
        "effective_stage6_status_root": str(stage6_status_root or ""),
        "pressure_root_resolution_state": "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if pressure_root else "UNRESOLVED",
        "release_field_query_root_resolution_state": _resolution_state(field_query_root),
        "supplemental_release_field_query_root_resolution_state": _resolution_state(
            existing.get("effective_supplemental_release_field_query_root")
        ),
        "runtime_blocker_next_subqueue_root_resolution_state": _resolution_state(
            existing.get("effective_runtime_blocker_next_subqueue_root")
        ),
        "gdcic_browser_readback_root_resolution_state": _resolution_state(gdcic_root),
        "stage6_status_root_resolution_state": _resolution_state(stage6_status_root),
        "stage1_6_scoreboard_resolution_state": _resolution_state(scoreboard_path),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _nested_continuation_input_refs(*, cycle: Mapping[str, Any], manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = [
        cycle.get("continuation_input_refs"),
        manifest.get("continuation_input_refs"),
        _mapping(manifest.get("operator_projection_status_table")).get("continuation_input_refs"),
        _mapping(_mapping(manifest.get("operator_projection_status_table")).get("summary")).get("continuation_input_refs"),
        _mapping(cycle.get("summary")).get("continuation_input_refs"),
    ]
    for candidate in candidates:
        mapped = _mapping(candidate)
        if mapped:
            return mapped
    return {}


def _stage4_followup_continuation_input_refs(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    queue_path_text = str(manifest.get("source_stage4_backfill_followup_queue_json") or "").strip()
    if not queue_path_text:
        status_json = str(manifest.get("source_stage6_review_loop_status_json") or "").strip()
        if status_json.endswith("stage4-backfill-followup-queue-v1.json"):
            queue_path_text = status_json
    if not queue_path_text:
        return {}
    queue_path = Path(queue_path_text)
    if not queue_path.exists():
        return {}
    return _mapping(_read_json(queue_path).get("continuation_input_refs"))


def _pressure_root_from_scoreboard(scoreboard_path: Path | None) -> str:
    if not scoreboard_path or not scoreboard_path.exists():
        return ""
    payload = _read_json(scoreboard_path)
    input_refs = _mapping(payload.get("input_refs"))
    for key in ("pressure_summary_json", "stage1_6_readiness_json", "stage1_6_gap_summary_json"):
        root = _parent_if_file_exists(input_refs.get(key))
        if root and (Path(root) / "stage4-release-adapter-bridge-plan.json").exists():
            return root
    return ""


def _parent_if_file_exists(value: Any) -> str:
    path_text = str(value or "").strip()
    if not path_text:
        return ""
    path = Path(path_text)
    if path.exists() and path.is_file():
        return str(path.parent)
    return ""


def _existing_paths(value: Any) -> list[Path]:
    out: list[Path] = []
    for part in str(value or "").split(";"):
        text = part.strip()
        if not text:
            continue
        path = Path(text)
        if path.exists() and path.is_file():
            out.append(path)
    return out


def _joined_parent_paths(paths: list[Path]) -> str:
    return ";".join(str(path.parent) for path in paths)


def _resolution_state(value: Any) -> str:
    return "RESOLVED_FROM_STAGE6_OR_SCOREBOARD_INPUT_REFS" if str(value or "").strip() else "UNRESOLVED"


def _summary(
    records: list[Mapping[str, Any]],
    *,
    stage4_bridge_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "fallback_source_plan_record_count": len(records),
        "project_count": len(set(_dedupe(record.get("project_id") for record in records))),
        "followup_route_counts": _counts(record.get("followup_route") for record in records),
        "task_type_counts": _counts(record.get("task_type") for record in records),
        "stage4_release_adapter_bridge_task_count": len(stage4_bridge_records),
        "stage4_release_adapter_bridge_project_count": len(
            set(_dedupe(record.get("project_id") for record in stage4_bridge_records))
        ),
        "stage4_release_adapter_bridge_target_type_counts": _counts(
            record.get("release_evidence_target_type") for record in stage4_bridge_records
        ),
        "stage4_release_adapter_bridge_execution_mode_counts": _counts(
            record.get("execution_mode") for record in stage4_bridge_records
        ),
        "stage4_release_adapter_bridge_gdcic_route_allowed_count": sum(
            1 for record in stage4_bridge_records if bool(record.get("gdcic_project_code_route_allowed"))
        ),
        "candidate_company_present_count": sum(1 for record in records if _list(record.get("candidate_companies"))),
        "responsible_person_present_count": sum(1 for record in records if _list(record.get("responsible_person_names"))),
        "candidate_notice_url_present_count": sum(1 for record in records if _list(record.get("candidate_notice_source_urls"))),
        "public_identifier_present_count": sum(1 for record in records if _has_public_identifier_context(record)),
        "p13b_query_input_present_count": sum(
            1
            for record in records
            if _list(record.get("candidate_companies"))
            or _list(record.get("candidate_notice_source_urls"))
            or _has_public_identifier_context(record)
        ),
        "records_are_p13b_consumable": True,
        **_safety(),
    }


def _has_public_identifier_context(record: Mapping[str, Any]) -> bool:
    context = _mapping(record.get("stage4_official_readback_context"))
    return any(
        _list(context.get(key))
        for key in (
            "ygp_project_code_variants",
            "ygp_biz_code_variants",
            "ygp_site_code_variants",
            "ygp_notice_id_variants",
        )
    )


def _stage4_release_adapter_bridge_records(
    records: list[Mapping[str, Any]],
    *,
    created_at: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        followup_route = str(record.get("followup_route") or "")
        if followup_route not in {
            "official_readback_ready_stage4_bridge_followup",
            "ygp_retry_then_local_authority_fallback",
        }:
            continue
        context = _mapping(record.get("stage4_official_readback_context"))
        ygp_project_codes = _dedupe(context.get("ygp_project_code_variants"))
        ygp_biz_codes = _dedupe(context.get("ygp_biz_code_variants"))
        ygp_site_codes = _dedupe(context.get("ygp_site_code_variants"))
        ygp_notice_ids = _dedupe(context.get("ygp_notice_id_variants"))
        if not any([ygp_project_codes, ygp_biz_codes, ygp_site_codes, ygp_notice_ids]):
            continue
        project_id = str(record.get("project_id") or "")
        is_retry_fallback = followup_route == "ygp_retry_then_local_authority_fallback"
        ygp_project_code = str(ygp_project_codes[0] if ygp_project_codes else "")
        source_url = _first_text(
            [
                *_list(record.get("candidate_notice_source_urls")),
                *_list(record.get("project_source_urls")),
            ]
        )
        rows.append(
            {
                "release_evidence_adapter_task_id": _stable_id(
                    "REL-EVIDENCE-ADAPTER-TASK-RUNTIME-FALLBACK-YGP",
                    project_id,
                    ygp_project_code,
                    ygp_notice_ids[0] if ygp_notice_ids else "",
                ),
                "source_release_evidence_probe_task_id": str(record.get("followup_record_id") or ""),
                "source_release_evidence_probe_plan_id": "RUNTIME-BLOCKER-FALLBACK-SOURCE-PLAN",
                "input_source_kind": "runtime_blocker_fallback_source_plan",
                "project_id": project_id,
                "project_name": str(record.get("project_name") or context.get("project_name") or ""),
                "candidate_company_name": _first_text(record.get("candidate_companies")),
                "matched_person_names": _dedupe(record.get("responsible_person_names")),
                "release_evidence_target_type": "ygp_original_readback_backfill",
                "release_evidence_grade_on_match": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                "release_evidence_source_role": "source_identifier_backfill_not_release_evidence",
                "initial_release_evidence_abcd_grade": (
                    "STAGE4_YGP_RETRY_FALLBACK_READY_NOT_A_SIGNAL"
                    if is_retry_fallback
                    else "STAGE4_YGP_BACKFILL_READY_NOT_A_SIGNAL"
                ),
                "release_evidence_query_region_code": "CN-GD-YGP",
                "release_evidence_query_region_basis": (
                    "runtime_blocker_ygp_retry_public_identifier_before_local_authority_fallback"
                    if is_retry_fallback
                    else "runtime_blocker_fallback_ygp_public_identifier"
                ),
                "local_housing_authority_adapter_scope": (
                    "YGP_RETRY_THEN_LOCAL_AUTHORITY_FALLBACK"
                    if is_retry_fallback
                    else "YGP_ORIGINAL_READBACK_BACKFILL_ONLY"
                ),
                "local_housing_authority_adapter_region_code": "CN-GD-YGP",
                "non_guangdong_release_adapter_rule": "",
                "jurisdiction_local_housing_adapter": {},
                "jurisdiction_adapter_resolution_state": "YGP_BACKFILL_POINTER_ONLY",
                "no_fallback_to_guangdong_or_guangzhou": True,
                "source_entry_id": "RUNTIME-BLOCKER-YGP-STAGE4-BACKFILL",
                "subsource_id": "runtime_blocker_fallback_source_plan",
                "source_profile_id": "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
                "source_name": "运行阻断队列 YGP 原文回读回灌线索",
                "source_family": "public_original_notice_readback_backfill",
                "source_url": source_url,
                "api_url": source_url,
                "official_reference_url": source_url,
                "trigger_source_url": source_url,
                "query_params": {
                    "projectId": project_id,
                    "projectName": str(record.get("project_name") or context.get("project_name") or ""),
                    "projectCode": "",
                    "sourceProjectCode": "",
                    "projectCodeVariants": ygp_project_codes,
                    "gdcicProjectCodeVariants": [],
                    "tradeProjectCode": "",
                    "ygpProjectCodeVariants": ygp_project_codes,
                    "ygpBizCodeVariants": ygp_biz_codes,
                    "ygpSiteCodeVariants": ygp_site_codes,
                    "ygpNoticeIdVariants": ygp_notice_ids,
                    "candidateCompanyName": _first_text(record.get("candidate_companies")),
                    "sourceProfileId": "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
                    "targetSourceTypes": ["ygp_original_readback_backfill"],
                    "triggerSourceUrl": source_url,
                    "keywords": _dedupe(
                        [
                            record.get("project_name"),
                            context.get("project_name"),
                            *ygp_project_codes,
                            *ygp_biz_codes,
                            *ygp_site_codes,
                            *ygp_notice_ids,
                            *_list(record.get("candidate_companies")),
                        ]
                    ),
                },
                "next_adapter": "p13b_or_stage4_bridge_backfill",
                "runtime_status": "PLAN_ONLY_BACKFILL_READY",
                "bridge_readiness_state": (
                    "YGP_RETRY_STAGE4_BACKFILL_READY_FOR_PUBLIC_READBACK"
                    if is_retry_fallback
                    else "YGP_STAGE4_BACKFILL_READY_FOR_STAGE4_BRIDGE"
                ),
                "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
                "allowed_adapter_result_states": ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"],
                "matched_means": "ygp_backfill_can_support_followup_readback_not_legal_conclusion",
                "not_found_means": "source_query_miss_or_no_public_match_not_clearance",
                "blocked_means": "source_blocked_or_unavailable_needs_review",
                "needs_browser_means": "browser_or_authorized_runtime_required_before_field_readback",
                "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                "readback_ready": False,
                "gdcic_project_code_route_allowed": False,
                "gdcic_route_block_reason": "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
                "must_not_extract_from_full_text_numbers": True,
                "recommended_next_action": (
                    "run_ygp_retry_public_readback_then_project_local_authority_fallback_without_gdcic_project_code_route"
                    if is_retry_fallback
                    else "run_stage4_bridge_or_p13b_backfill_without_gdcic_project_code_route"
                ),
                "query_miss_is_not_clearance": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "created_at": created_at or datetime.now(timezone.utc).isoformat(),
            }
        )
    return [dict(record) for record in _dedupe_records(*rows)]


def _stage4_release_adapter_bridge_plan(
    *,
    records: list[Mapping[str, Any]],
    source_cycle_json: Path,
    created_at: str | None,
) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "manifest_kind": "runtime_blocker_stage4_release_adapter_bridge_plan_v1_manifest",
        "adapter_id": "runtime-blocker-fallback-source-stage4-bridge-plan-v1",
        "pipeline_stage": "RuntimeBlockerFallbackSourceStage4BridgePlanV1",
        "manifest_id": _stable_id("RUNTIME-BLOCKER-ST4-BRIDGE", records),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "source_stage6_review_cycle_json": str(source_cycle_json),
        "summary": {
            "bridge_plan_state": "READY" if records else "NO_STAGE4_BRIDGE_READY_RECORDS",
            "release_evidence_adapter_task_count": len(records),
            "project_count": len(set(_dedupe(record.get("project_id") for record in records))),
            "target_type_counts": _counts(record.get("release_evidence_target_type") for record in records),
            "execution_mode_counts": _counts(record.get("execution_mode") for record in records),
            "gdcic_project_code_route_allowed_count": sum(
                1 for record in records if bool(record.get("gdcic_project_code_route_allowed"))
            ),
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
        "release_evidence_adapter_task_records": [dict(record) for record in records],
        "safety": _safety(),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
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


def _unwrap_runtime_entrypoint_cycle(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = _mapping(_mapping(payload.get("controller_result")).get("stage6_cycle_result"))
    return nested if nested else payload


def _lookup_context(contexts: Mapping[str, Mapping[str, Any]], *keys: Any) -> Mapping[str, Any]:
    merged: Mapping[str, Any] = {}
    for key in _dedupe(keys):
        context = contexts.get(key)
        if context:
            merged = _merge_context(merged, context)
    return merged


def _first_mapping(*values: Any) -> Mapping[str, Any]:
    for value in values:
        mapped = _mapping(value)
        if mapped:
            return mapped
    return {}


def _merge_mapping(*values: Any) -> Mapping[str, Any]:
    out: dict[str, Any] = {}
    for value in values:
        out.update(dict(_mapping(value)))
    return out


def _merge_official_readback_context(*values: Any) -> Mapping[str, Any]:
    out = dict(_merge_mapping(*values))
    for key in (
        "ygp_project_code_variants",
        "ygp_biz_code_variants",
        "ygp_site_code_variants",
        "ygp_notice_id_variants",
    ):
        out[key] = _dedupe(item for value in values for item in _list(_mapping(value).get(key)))
    if any(out.get(key) for key in ("ygp_project_code_variants", "ygp_biz_code_variants", "ygp_site_code_variants", "ygp_notice_id_variants")):
        out["stage4_official_readback_context_state"] = (
            out.get("stage4_official_readback_context_state")
            or "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED"
        )
        out["gdcic_project_code_route_allowed"] = False
        out["must_not_extract_from_full_text_numbers"] = True
    return out


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
    if values is None:
        return out
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _dedupe_records(*records: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _first_text(values: Any) -> str:
    for value in _list(values):
        text = str(value or "").strip()
        if text:
            return text
    return ""


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
