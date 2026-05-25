from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


QUEUE_KIND = "stage4_backfill_followup_queue_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage4-backfill-followup-queue-v1")
DEFAULT_SCOREBOARD_JSON = Path(
    "tmp/evaluation-real-samples/stage1-6-sellable-rate-regression-live18-20260525-r2/scoreboard/stage1-6-sellable-scoreboard-v1.json"
)


def build_stage4_backfill_followup_queue(
    *,
    scoreboard_json: str | Path = DEFAULT_SCOREBOARD_JSON,
    scoreboard_comparison_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    scoreboard_path = Path(scoreboard_json)
    payload = _read_json(scoreboard_path)
    rows = payload.get("project_rows") if isinstance(payload.get("project_rows"), list) else []
    continuation_input_refs = _continuation_input_refs(payload, scoreboard_path)
    deepening_policy = _public_source_deepening_policy(
        scoreboard_path=scoreboard_path,
        comparison_json=scoreboard_comparison_json,
    )
    records = [
        _followup_record(row, scoreboard_ref=str(scoreboard_path), deepening_policy=deepening_policy)
        for row in rows
        if isinstance(row, Mapping) and _needs_backfill_followup(row)
    ]
    result = {
        "queue_kind": QUEUE_KIND,
        "queue_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "scoreboard_json": str(scoreboard_path),
            "scoreboard_comparison_json": str(scoreboard_comparison_json or ""),
        },
        "continuation_input_refs": continuation_input_refs,
        "summary": _summary(records),
        "public_source_deepening_policy": deepening_policy,
        "next_regression_execution_plan": _next_regression_execution_plan(
            records,
            deepening_policy,
            continuation_input_refs=continuation_input_refs,
        ),
        "records": records,
        "safety": {
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "live_execution_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
    }
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "stage4-backfill-followup-queue-v1.json", result)
    _write_markdown(out_dir / "stage4-backfill-followup-queue-v1.md", result)
    return result


def _needs_backfill_followup(row: Mapping[str, Any]) -> bool:
    if str(row.get("p13b_original_notice_readback_state") or "").upper() == "BLOCKED":
        return True
    if str(row.get("p13b_ygp_original_readback_state") or "").upper() == "YGP_BLOCKED":
        return True
    if str(row.get("stage5_operational_review_bucket") or "") in {
        "PUBLIC_SOURCE_BLOCKED_REVIEW",
        "ORIGINAL_NOTICE_BLOCKED_REVIEW",
        "YGP_READBACK_BLOCKED_REVIEW",
    }:
        return True
    return (
        str(row.get("stage4_project_code_backfill_state") or "")
        == "MISSING_PROJECT_CODE_BACKFILL_INPUT"
        and bool(str(row.get("stage4_project_code_backfill_gap_detail") or "").strip())
    )


def _followup_record(
    row: Mapping[str, Any],
    *,
    scoreboard_ref: str,
    deepening_policy: Mapping[str, Any],
) -> dict[str, Any]:
    project_id = str(row.get("project_id") or "").strip()
    detail = _followup_gap_detail(row)
    route = _followup_route(detail)
    deepening_recommended = bool(deepening_policy.get("public_source_deepening_recommended"))
    return {
        "followup_record_id": _stable_id("STAGE4-BACKFILL-FOLLOWUP", project_id, detail),
        "project_id": project_id,
        "project_name": str(row.get("project_name") or ""),
        "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
        "stage4_project_code_backfill_gap_detail": detail,
        "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
        "p13b_public_source_readback_state": str(row.get("p13b_public_source_readback_state") or ""),
        "p13b_original_notice_readback_state": str(row.get("p13b_original_notice_readback_state") or ""),
        "p13b_overlap_triage_state": str(row.get("p13b_overlap_triage_state") or ""),
        "followup_route": route,
        "followup_queue_state": _followup_queue_state(route),
        "worker_family": _worker_family(route),
        "public_source_fallback_sequence": _public_source_fallback_sequence(row, route),
        "required_input": _required_input(route),
        "recommended_next_action": _recommended_next_action(route),
        "execution_priority": _execution_priority(route, deepening_recommended=deepening_recommended),
        "public_source_deepening_recommended": deepening_recommended,
        "public_source_deepening_decision": str(deepening_policy.get("decision") or ""),
        "recommended_budget_focus": list(deepening_policy.get("recommended_budget_focus") or []),
        "input_artifact_refs": [scoreboard_ref],
        "controller_consumable": True,
        "customer_visible_allowed": False,
        "live_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _followup_gap_detail(row: Mapping[str, Any]) -> str:
    public_readback_state = str(row.get("p13b_public_source_readback_state") or "")
    if public_readback_state == "LOCAL_AUTHORITY_BLOCKED_REVIEW":
        return "LOCAL_AUTHORITY_BLOCKED_RETRY_OR_ALTERNATE_SOURCE_REQUIRED"
    if public_readback_state == "LOCAL_AUTHORITY_NOT_FOUND_REVIEW":
        return "LOCAL_AUTHORITY_NOT_FOUND_DEEPENING_REQUIRED"
    detail = str(row.get("stage4_project_code_backfill_gap_detail") or "").strip()
    if detail:
        return detail
    if str(row.get("p13b_ygp_original_readback_state") or "").upper() == "YGP_BLOCKED":
        return "YGP_READBACK_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"
    if str(row.get("p13b_original_notice_readback_state") or "").upper() == "BLOCKED":
        return "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED"
    bucket = str(row.get("stage5_operational_review_bucket") or "")
    if bucket == "PUBLIC_SOURCE_BLOCKED_REVIEW":
        return "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"
    if bucket == "ORIGINAL_NOTICE_BLOCKED_REVIEW":
        return "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED"
    if bucket == "YGP_READBACK_BLOCKED_REVIEW":
        return "YGP_READBACK_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"
    return ""


def _followup_route(detail: str) -> str:
    if detail == "LOCAL_AUTHORITY_BLOCKED_RETRY_OR_ALTERNATE_SOURCE_REQUIRED":
        return "local_authority_blocked_retry_or_alternate_source"
    if detail == "LOCAL_AUTHORITY_NOT_FOUND_DEEPENING_REQUIRED":
        return "local_authority_not_found_specific_endpoint_or_manual_source"
    if detail == "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED":
        return "public_source_retry_then_local_authority_fallback"
    if detail == "YGP_READBACK_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED":
        return "ygp_retry_then_local_authority_fallback"
    if detail in {
        "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
        "ORIGINAL_NOTICE_NOT_FOUND_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
        "GDCIC_IDENTIFIER_UNRESOLVED_AFTER_PUBLIC_BACKFILL_REQUIRED",
    }:
        return "local_authority_fallback_source_planning"
    if detail == "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED":
        return "original_notice_retry_then_local_authority_fallback"
    if detail == "PUBLIC_SOURCE_READBACK_NOT_RUN_REQUIRED":
        return "public_source_readback_required"
    return "operator_classify_backfill_gap"


def _followup_queue_state(route: str) -> str:
    if route == "operator_classify_backfill_gap":
        return "OPERATOR_CLASSIFICATION_REQUIRED"
    return "FOLLOWUP_SOURCE_PLAN_REQUIRED"


def _worker_family(route: str) -> str:
    if route == "operator_classify_backfill_gap":
        return "operator_action"
    return "source_adapter"


def _required_input(route: str) -> list[str]:
    if route == "local_authority_blocked_retry_or_alternate_source":
        return ["alternate_project_local_authority_source_url_or_adapter", "retry_budget_with_timeout_blocker_capture"]
    if route == "local_authority_not_found_specific_endpoint_or_manual_source":
        return ["specific_project_local_authority_search_endpoint_or_manual_source_path"]
    if route == "public_source_retry_then_local_authority_fallback":
        return ["public_source_retry_budget_or_project_local_authority_adapter"]
    if route == "ygp_retry_then_local_authority_fallback":
        return ["ygp_retry_budget_or_project_local_authority_adapter"]
    if route == "original_notice_retry_then_local_authority_fallback":
        return ["original_notice_retry_budget_or_project_local_authority_adapter"]
    if route == "public_source_readback_required":
        return ["public_source_readback_budget"]
    if route == "operator_classify_backfill_gap":
        return ["operator_classification_reason"]
    return ["data_ggzy_bid_show_or_ygp_backfill_input", "project_local_authority_source_url_or_adapter"]


def _public_source_fallback_sequence(row: Mapping[str, Any], route: str) -> list[dict[str, Any]]:
    return [
        _fallback_step(
            "data_ggzy_company_history_search",
            "search_data_ggzy_company_history_before_local_authority_fallback",
            row,
        ),
        _fallback_step("data_ggzy_bid_list_pagination", "page_bid_list_with_bounded_budget", row),
        _fallback_step("data_ggzy_bid_show_readback", "read_bid_show_text_and_original_notice_url", row),
        _fallback_step("ygp_original_notice_readback", "read_ygp_original_notice_identifiers_for_p13b_or_stage4_bridge", row),
        _fallback_step(
            "project_local_authority_public_source",
            "query_historical_project_location_housing_or_supervisory_authority",
            row,
        ),
    ] if route != "operator_classify_backfill_gap" else []


def _fallback_step(source_kind: str, action: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "action": action,
        "project_id": str(row.get("project_id") or ""),
        "input_state": _fallback_input_state(source_kind, row),
        "gdcic_project_code_route_allowed": False,
        "gdcic_project_code_route_policy": "PUBLIC_SOURCE_IDENTIFIER_NOT_SENT_TO_GDCIC_UNLESS_EXPLICIT_PROVINCIAL_CODE",
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _fallback_input_state(source_kind: str, row: Mapping[str, Any]) -> str:
    if source_kind == "data_ggzy_bid_show_readback":
        if int(row.get("p13b_bid_show_original_notice_url_count") or 0) > 0:
            return "BID_SHOW_ORIGINAL_NOTICE_URL_PRESENT"
        if int(row.get("p13b_bid_show_responsible_person_present_count") or 0) > 0:
            return "BID_SHOW_RESPONSIBLE_PERSON_PRESENT"
    if source_kind == "ygp_original_notice_readback":
        if row.get("p13b_ygp_original_readback_state") == "YGP_READBACK_READY":
            return "YGP_READBACK_READY"
        if row.get("p13b_ygp_project_code_variants"):
            return "YGP_IDENTIFIER_PRESENT"
    if source_kind == "project_local_authority_public_source":
        return "LOCAL_AUTHORITY_FALLBACK_REQUIRED"
    return "INPUT_REQUIRED_OR_RETRY_WITH_BUDGET"


def _recommended_next_action(route: str) -> str:
    actions = {
        "local_authority_blocked_retry_or_alternate_source": "retry_blocked_local_authority_source_or_choose_alternate_official_entry_without_clearance_claim",
        "local_authority_not_found_specific_endpoint_or_manual_source": "keep_not_found_as_non_clearance_and_try_specific_search_endpoint_or_manual_source_path",
        "public_source_retry_then_local_authority_fallback": "retry_public_source_or_route_to_project_local_authority_without_clearance_claim",
        "local_authority_fallback_source_planning": "plan_project_local_authority_readback_without_treating_not_found_as_clearance",
        "original_notice_retry_then_local_authority_fallback": "retry_original_notice_or_route_to_project_local_authority_without_clearance_claim",
        "ygp_retry_then_local_authority_fallback": "retry_ygp_readback_or_route_to_project_local_authority_without_clearance_claim",
        "public_source_readback_required": "run_public_source_readback_before_any_clearance_claim",
        "operator_classify_backfill_gap": "operator_classifies_backfill_gap_before_retry",
    }
    return actions.get(route, "operator_reviews_stage4_backfill_gap")


def _execution_priority(route: str, *, deepening_recommended: bool) -> str:
    if not deepening_recommended:
        return "NORMAL"
    if route in {
        "local_authority_blocked_retry_or_alternate_source",
        "public_source_retry_then_local_authority_fallback",
        "original_notice_retry_then_local_authority_fallback",
        "ygp_retry_then_local_authority_fallback",
        "public_source_readback_required",
    }:
        return "HIGH_PUBLIC_SOURCE_DEEPENING"
    if route in {
        "local_authority_fallback_source_planning",
        "local_authority_not_found_specific_endpoint_or_manual_source",
    }:
        return "MEDIUM_LOCAL_AUTHORITY_FALLBACK"
    return "NORMAL_OPERATOR_REVIEW"


def _public_source_deepening_policy(
    *,
    scoreboard_path: Path,
    comparison_json: str | Path | None,
) -> dict[str, Any]:
    run_label = _run_label(scoreboard_path)
    default = {
        "run_label": run_label,
        "public_source_deepening_recommended": False,
        "decision": "NO_COMPARISON_RECOMMENDATION",
        "recommended_budget_focus": [],
        "comparison_json": str(comparison_json or ""),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    if not comparison_json:
        return default
    comparison_path = Path(comparison_json)
    comparison = _read_json(comparison_path)
    recommendations = comparison.get("public_source_deepening_recommendations")
    if not isinstance(recommendations, list):
        return default
    for recommendation in recommendations:
        if not isinstance(recommendation, Mapping):
            continue
        if str(recommendation.get("run_label") or "") != run_label:
            continue
        if str(recommendation.get("decision") or "") != "CONTINUE_PUBLIC_SOURCE_DEEPENING":
            continue
        return {
            "run_label": run_label,
            "previous_run_label": str(recommendation.get("previous_run_label") or ""),
            "public_source_deepening_recommended": True,
            "decision": "CONTINUE_PUBLIC_SOURCE_DEEPENING",
            "reason": str(recommendation.get("reason") or ""),
            "recommended_budget_focus": list(recommendation.get("recommended_budget_focus") or []),
            "comparison_json": str(comparison_path),
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "gdcic_project_code_digit_guessing_allowed": False,
        }
    return default


def _continuation_input_refs(payload: Mapping[str, Any], scoreboard_path: Path) -> dict[str, Any]:
    input_refs = payload.get("input_refs") if isinstance(payload.get("input_refs"), Mapping) else {}
    pressure_root = _root_with_required_sibling(
        input_refs,
        keys=["pressure_summary_json", "stage1_6_readiness_json", "stage1_6_gap_summary_json"],
        required_sibling="stage4-release-adapter-bridge-plan.json",
    )
    release_field_query_root = _parent_if_file_exists(input_refs.get("release_field_query_json"))
    supplemental_release_field_query_json = input_refs.get("supplemental_release_field_query_json")
    supplemental_release_field_query_root = _parent_if_file_exists(supplemental_release_field_query_json)
    gdcic_readback_root = _parent_if_file_exists(input_refs.get("gdcic_browser_authorized_readback_json"))
    stage6_status_root = _parent_if_file_exists(input_refs.get("stage6_status_json"))
    return {
        "prior_scoreboard_json": str(scoreboard_path),
        "effective_pressure_root": pressure_root,
        "effective_release_field_query_root": release_field_query_root,
        "effective_supplemental_release_field_query_json": str(supplemental_release_field_query_json or ""),
        "effective_supplemental_release_field_query_root": supplemental_release_field_query_root,
        "effective_gdcic_browser_readback_root": gdcic_readback_root,
        "effective_stage6_status_root": stage6_status_root,
        "pressure_root_resolution_state": "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if pressure_root else "UNRESOLVED",
        "release_field_query_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if release_field_query_root else "UNRESOLVED"
        ),
        "supplemental_release_field_query_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if supplemental_release_field_query_root else "UNRESOLVED"
        ),
        "gdcic_browser_readback_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if gdcic_readback_root else "UNRESOLVED"
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _root_with_required_sibling(input_refs: Mapping[str, Any], *, keys: list[str], required_sibling: str) -> str:
    for key in keys:
        root = _parent_if_file_exists(input_refs.get(key))
        if root and (Path(root) / required_sibling).exists():
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


def _summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "followup_record_count": len(records),
        "project_count": len({str(record.get("project_id") or "") for record in records if record.get("project_id")}),
        "followup_route_counts": _counts(record.get("followup_route") for record in records),
        "followup_queue_state_counts": _counts(record.get("followup_queue_state") for record in records),
        "gap_detail_counts": _counts(record.get("stage4_project_code_backfill_gap_detail") for record in records),
        "worker_family_counts": _counts(record.get("worker_family") for record in records),
        "execution_priority_counts": _counts(record.get("execution_priority") for record in records),
        "public_source_deepening_recommended_counts": _counts(
            str(bool(record.get("public_source_deepening_recommended"))).lower() for record in records
        ),
        "customer_visible_allowed": False,
        "live_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _next_regression_execution_plan(
    records: list[Mapping[str, Any]],
    deepening_policy: Mapping[str, Any],
    *,
    continuation_input_refs: Mapping[str, Any],
) -> dict[str, Any]:
    high_count = sum(
        1 for record in records if record.get("execution_priority") == "HIGH_PUBLIC_SOURCE_DEEPENING"
    )
    medium_count = sum(
        1 for record in records if record.get("execution_priority") == "MEDIUM_LOCAL_AUTHORITY_FALLBACK"
    )
    target_project_ids = [
        str(record.get("project_id") or "")
        for record in records
        if record.get("followup_route") != "operator_classify_backfill_gap"
    ]
    if not records:
        return {
            "plan_state": "NO_FOLLOWUP_RECORDS",
            "target_project_ids": [],
            "recommended_parameter_overrides": {},
            "runner_entrypoint": "scripts/run-stage1-6-sellable-rate-regression-v1.ps1",
            "continuation_input_refs": dict(continuation_input_refs),
            "customer_visible_allowed": False,
            "live_execution_enabled_by_default": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
    plan_state = (
        "PUBLIC_SOURCE_DEEPENING_RUN_RECOMMENDED"
        if deepening_policy.get("public_source_deepening_recommended")
        else "FOLLOWUP_SOURCE_PLAN_ONLY"
    )
    p13b_company_budget = max(8, high_count * 3 + medium_count)
    original_notice_budget = max(12, high_count * 4 + medium_count * 2)
    ygp_notice_budget = max(8, high_count * 3)
    ygp_backfill_budget = max(8, high_count * 3)
    return {
        "plan_state": plan_state,
        "runner_entrypoint": "scripts/run-stage1-6-sellable-rate-regression-v1.ps1",
        "continuation_input_refs": dict(continuation_input_refs),
        "target_project_ids": target_project_ids,
        "target_project_count": len(target_project_ids),
        "public_source_fallback_sequence": [
            "data_ggzy_company_history_search",
            "data_ggzy_bid_list_pagination",
            "data_ggzy_bid_show_readback",
            "ygp_original_notice_readback",
            "project_local_authority_public_source",
        ],
        "recommended_switches": [
            "RunP13BPublicSourceChain",
            "RunYgpBackfillFieldQuery",
            "RunStage6MergedProjection",
        ],
        "recommended_parameter_overrides": {
            "MaxLiveP13BCompanies": p13b_company_budget,
            "MaxBidRecordsPerCompany": 3,
            "MaxBidListPagesPerCompany": 2,
            "MaxLongTailBidShowsPerCompany": 1,
            "MaxLiveOriginalNotices": original_notice_budget,
            "MaxLiveYgpOriginalNotices": ygp_notice_budget,
            "MaxLiveYgpBackfillTasks": ygp_backfill_budget,
        },
        "operator_live_public_query_decision_required": True,
        "default_execution_mode": "PLAN_OR_EXISTING_ARTIFACT_REPLAY",
        "live_execution_enabled_by_default": False,
        "recommended_budget_focus": list(deepening_policy.get("recommended_budget_focus") or []),
        "safety_invariants": {
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "gdcic_project_code_digit_guessing_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
        },
    }


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stable_id(prefix: str, *parts: Any) -> str:
    import hashlib

    payload = json.dumps([str(part or "") for part in parts], ensure_ascii=False, sort_keys=True)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _run_label(path: Path) -> str:
    parts = list(path.parts)
    if "tmp" in parts and "evaluation-real-samples" in parts:
        idx = parts.index("evaluation-real-samples")
        if len(parts) > idx + 1:
            return parts[idx + 1]
    if path.parent.name == "scoreboard":
        return path.parent.parent.name
    return path.parent.name


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Stage4 Backfill Follow-up Queue v1",
        "",
        f"- followup_record_count: {summary.get('followup_record_count', 0)}",
        f"- gap_detail_counts: {json.dumps(summary.get('gap_detail_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- followup_route_counts: {json.dumps(summary.get('followup_route_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- execution_priority_counts: {json.dumps(summary.get('execution_priority_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- public_source_deepening_policy: {json.dumps(payload.get('public_source_deepening_policy', {}), ensure_ascii=False, sort_keys=True)}",
        f"- next_regression_execution_plan: {json.dumps(payload.get('next_regression_execution_plan', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "customer_visible_allowed=false; live_execution_enabled=false; query_miss_is_not_clearance=true; no_legal_conclusion=true",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scoreboard-json", default=str(DEFAULT_SCOREBOARD_JSON))
    parser.add_argument("--scoreboard-comparison-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage4_backfill_followup_queue(
        scoreboard_json=args.scoreboard_json,
        scoreboard_comparison_json=args.scoreboard_comparison_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result.get("summary") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
