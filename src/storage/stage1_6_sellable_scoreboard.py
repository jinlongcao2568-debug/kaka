from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


SCOREBOARD_KIND = "stage1_6_sellable_scoreboard_v1"
SCOREBOARD_VERSION = 1


DEFAULT_PRESSURE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-stage1-6-real-public-pressure-v1")
DEFAULT_FIELD_QUERY_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-field-query-probe-v1")
DEFAULT_STAGE6_STATUS_ROOT = Path("tmp/evaluation-real-samples/stage6-review-cycle-runner-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-6-sellable-scoreboard-v1")


def build_stage1_6_sellable_scoreboard(
    *,
    pressure_root: str | Path | None = None,
    pressure_summary_json: str | Path | None = None,
    readiness_json: str | Path | None = None,
    gap_summary_json: str | Path | None = None,
    field_query_root: str | Path | None = None,
    field_query_json: str | Path | None = None,
    stage6_status_root: str | Path | None = None,
    stage6_status_json: str | Path | None = None,
    output_root: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    pressure_dir = Path(pressure_root or DEFAULT_PRESSURE_ROOT)
    field_dir = Path(field_query_root or DEFAULT_FIELD_QUERY_ROOT)
    stage6_dir = Path(stage6_status_root or DEFAULT_STAGE6_STATUS_ROOT)
    out_dir = Path(output_root or DEFAULT_OUTPUT_ROOT)
    out_dir.mkdir(parents=True, exist_ok=True)

    pressure_summary_path = _resolve_path(pressure_summary_json, pressure_dir / "pressure-summary.json")
    readiness_path = _resolve_path(readiness_json, pressure_dir / "stage1-6-readiness-table.json")
    gap_summary_path = _resolve_path(gap_summary_json, pressure_dir / "stage1-6-gap-summary-table.json")
    field_query_path = _resolve_path(field_query_json, field_dir / "guangdong-local-field-query-probe-v1.json")
    stage6_status_path = _resolve_stage6_status_path(stage6_status_json, stage6_dir)

    pressure_summary = _read_json_mapping(pressure_summary_path)
    readiness = _read_json_mapping(readiness_path)
    gap_summary = _read_json_mapping(gap_summary_path)
    field_query = _read_json_mapping(field_query_path)
    stage6_status = _read_json_mapping(stage6_status_path)

    readiness_records = _records(readiness)
    gap_records = _records(gap_summary)
    field_records = _field_task_records(field_query)
    stage6_records = _records(stage6_status)

    stage6_by_project = {
        str(record.get("project_id") or "").strip(): record
        for record in stage6_records
        if str(record.get("project_id") or "").strip()
    }
    readiness_by_project = {
        str(record.get("project_id") or "").strip(): record
        for record in readiness_records
        if str(record.get("project_id") or "").strip()
    }

    project_ids = _ordered_project_ids(readiness_records, stage6_records, field_records)
    project_rows = [
        _project_scoreboard_row(
            project_id,
            readiness_by_project.get(project_id, {}),
            stage6_by_project.get(project_id, {}),
            [record for record in field_records if str(record.get("project_id") or "").strip() == project_id],
        )
        for project_id in project_ids
    ]
    counts = _scoreboard_counts(pressure_summary, readiness_records, field_query, field_records, stage6_status, stage6_records, project_rows)
    blocker_summary = _blocker_summary(readiness_records, gap_records, field_query, field_records, stage6_records, project_rows)
    recommended_next_actions = _recommended_next_actions(blocker_summary, counts)

    result = {
        "scoreboard_kind": SCOREBOARD_KIND,
        "scoreboard_version": SCOREBOARD_VERSION,
        "created_at": created,
        "input_refs": {
            "pressure_summary_json": str(pressure_summary_path),
            "stage1_6_readiness_json": str(readiness_path),
            "stage1_6_gap_summary_json": str(gap_summary_path),
            "release_field_query_json": str(field_query_path),
            "stage6_status_json": str(stage6_status_path),
        },
        "scoreboard": counts,
        "blocker_summary": blocker_summary,
        "recommended_next_actions": recommended_next_actions,
        "project_rows": project_rows,
        "safety": {
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
    }
    _write_json(out_dir / "stage1-6-sellable-scoreboard-v1.json", result)
    _write_markdown(out_dir / "stage1-6-sellable-scoreboard-v1.md", result)
    return result


def _scoreboard_counts(
    pressure_summary: Mapping[str, Any],
    readiness_records: list[Mapping[str, Any]],
    field_query: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    stage6_status: Mapping[str, Any],
    stage6_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    pressure_candidate_count = _int(pressure_summary.get("candidate_count"))
    candidate_count = pressure_candidate_count or len(readiness_records) or _distinct_count(field_records, "project_id")
    stage2_success_count = sum(
        1
        for record in readiness_records
        if str(record.get("stage2_detail_capture_state") or "").upper() in {"FETCHED", "CAPTURED", "DETAIL_CAPTURED", "READBACK_READY"}
    )
    stage3_success_count = sum(
        1
        for record in readiness_records
        if _stage3_parse_attempt_succeeded(record.get("stage3_field_parse_state"))
    )
    field_summary = _summary(field_query)
    stage6_summary = _summary(stage6_status)
    stage4_matched_count = _count_state(field_summary, field_records, "adapter_result_state", "MATCHED")
    stage4_needs_browser_count = _count_state(field_summary, field_records, "adapter_result_state", "NEEDS_BROWSER")
    stage5_review_count = _stage5_review_count(pressure_summary, readiness_records)
    stage6_fact_ready_count = sum(
        1
        for record in stage6_records
        if str(record.get("stage6_fact_package_state") or "").upper()
        in {"READY", "FACT_READY", "STAGE6_FACT_READY", "FACT_PACKAGE_READY"}
    )
    stage7_sellable_count = _int(pressure_summary.get("customer_sellable_evidence_ready_count")) or sum(
        1
        for record in stage6_records
        if bool(record.get("stage7_commercial_input_allowed"))
        and _has_grade(record, ("A_", "B_", "C_"))
    )
    limited_sellable_review_candidate_count = sum(
        1
        for row in project_rows
        if row.get("limited_sellable_review_candidate_state") == "REVIEW_CANDIDATE"
    )
    strong_lead_review_candidate_count = sum(
        1
        for row in project_rows
        if row.get("strong_lead_candidate_state") == "STRONG_LEAD_REVIEW_CANDIDATE"
    )
    denominator = candidate_count or 0
    sellable_or_limited_count = stage7_sellable_count + limited_sellable_review_candidate_count
    return {
        "candidate_count": candidate_count,
        "stage2_success_count": stage2_success_count,
        "stage3_success_count": stage3_success_count,
        "stage4_matched_task_count": stage4_matched_count,
        "stage4_needs_browser_task_count": stage4_needs_browser_count,
        "stage5_review_count": stage5_review_count,
        "stage6_fact_ready_count": stage6_fact_ready_count,
        "stage7_sellable_count": stage7_sellable_count,
        "limited_sellable_review_candidate_count": limited_sellable_review_candidate_count,
        "strong_lead_review_candidate_count": strong_lead_review_candidate_count,
        "sellable_or_limited_review_candidate_count": sellable_or_limited_count,
        "real_public_sellable_pack_rate": _ratio(sellable_or_limited_count, denominator),
        "stage4_release_field_query_project_count": _int(stage6_summary.get("release_field_query_project_count")) or _distinct_count(field_records, "project_id"),
        "stage4_release_field_query_state_counts": dict(stage6_summary.get("release_field_query_state_counts") or {})
        or _counts(record.get("release_field_query_state") for record in stage6_records),
        "stage4_adapter_result_state_counts": dict(field_summary.get("adapter_result_state_counts") or {}),
        "stage4_downstream_abcd_grade_counts": dict(field_summary.get("release_evidence_downstream_abcd_grade_counts") or {}),
        "stage6_loop_terminal_state_counts": dict(stage6_summary.get("loop_terminal_state_counts") or {})
        or _counts(record.get("loop_terminal_state") for record in stage6_records),
    }


def _project_scoreboard_row(
    project_id: str,
    readiness_record: Mapping[str, Any],
    stage6_record: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    adapter_counts = _counts(record.get("adapter_result_state") for record in field_records)
    grade_counts = _counts(
        record.get("downstream_abcd_grade") or record.get("release_evidence_downstream_abcd_grade")
        for record in field_records
    )
    stage6_grade_counts = dict(stage6_record.get("release_field_query_downstream_abcd_grade_counts") or {})
    combined_grade_counts = {**grade_counts}
    for key, value in stage6_grade_counts.items():
        combined_grade_counts[key] = max(int(combined_grade_counts.get(key) or 0), int(value or 0))
    has_official_b_or_c = any(str(key).startswith(("B_", "C_")) and int(value or 0) > 0 for key, value in combined_grade_counts.items())
    stage7_allowed = bool(stage6_record.get("stage7_commercial_input_allowed"))
    stage6_strong_lead_state = str(stage6_record.get("strong_lead_candidate_state") or "").strip()
    stage6_limited_review_state = str(stage6_record.get("limited_sellable_review_candidate_state") or "").strip()
    strong_lead_candidate_state = (
        stage6_strong_lead_state
        if stage6_strong_lead_state
        else "STRONG_LEAD_REVIEW_CANDIDATE" if has_official_b_or_c else "NOT_READY"
    )
    limited_sellable_review_candidate_state = (
        stage6_limited_review_state
        if stage6_limited_review_state
        else "REVIEW_CANDIDATE" if has_official_b_or_c and not stage7_allowed else "NOT_READY"
    )
    return {
        "project_id": project_id,
        "project_name": str(readiness_record.get("project_name") or stage6_record.get("project_name") or ""),
        "stage2_detail_capture_state": str(readiness_record.get("stage2_detail_capture_state") or ""),
        "stage3_field_parse_state": str(readiness_record.get("stage3_field_parse_state") or ""),
        "stage5_gate_state": str(readiness_record.get("stage5_gate_state") or ""),
        "stage5_rule_gate_status": str(readiness_record.get("stage5_rule_gate_status") or ""),
        "stage6_fact_package_state": str(stage6_record.get("stage6_fact_package_state") or readiness_record.get("stage6_fact_package_state") or ""),
        "stage6_ready": bool(stage6_record.get("stage6_ready")),
        "stage7_commercial_input_allowed": stage7_allowed,
        "release_field_query_state": str(stage6_record.get("release_field_query_state") or ""),
        "loop_terminal_state": str(stage6_record.get("loop_terminal_state") or ""),
        "stage4_adapter_result_state_counts": adapter_counts or dict(stage6_record.get("release_field_query_adapter_result_state_counts") or {}),
        "stage4_downstream_abcd_grade_counts": combined_grade_counts,
        "authorization_state_counts": dict(stage6_record.get("release_field_query_authorization_state_counts") or {}),
        "operator_next_actions": [str(item) for item in _as_list(stage6_record.get("release_field_query_operator_next_actions")) if str(item or "").strip()],
        "blocking_bucket": _project_blocking_bucket(readiness_record, stage6_record, field_records),
        "strong_lead_candidate_state": strong_lead_candidate_state,
        "limited_sellable_review_candidate_state": limited_sellable_review_candidate_state,
        "limited_sellable_review_reason": str(stage6_record.get("limited_sellable_review_reason") or ""),
        "commercialization_boundary_state": str(
            stage6_record.get("commercialization_boundary_state")
            or "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE"
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _blocker_summary(
    readiness_records: list[Mapping[str, Any]],
    gap_records: list[Mapping[str, Any]],
    field_query: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
    stage6_records: list[Mapping[str, Any]],
    project_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    field_summary = _summary(field_query)
    blocker_taxonomy_counts = dict(field_summary.get("blocker_taxonomy_counts") or {})
    if not blocker_taxonomy_counts:
        blocker_taxonomy_counts = _flatten_counts(field_records, "blocker_taxonomy")
    return {
        "blocking_bucket_counts": _counts(row.get("blocking_bucket") for row in project_rows),
        "field_missing_or_not_found_task_count": sum(1 for record in field_records if str(record.get("adapter_result_state") or "") == "NOT_FOUND"),
        "authorization_blocked_task_count": sum(
            1
            for record in field_records
            if str(record.get("adapter_result_state") or "") == "NEEDS_BROWSER"
            or "LOGIN_OR_SSO_REQUIRED" in str(record.get("authorization_readiness_state") or "")
        ),
        "stage4_matched_without_stage7_saleable_project_count": sum(
            1
            for row in project_rows
            if row.get("limited_sellable_review_candidate_state") == "REVIEW_CANDIDATE"
            and not bool(row.get("stage7_commercial_input_allowed"))
        ),
        "stage5_rule_review_project_count": sum(1 for record in readiness_records if str(record.get("stage5_rule_gate_status") or "").upper() == "REVIEW"),
        "stage6_projection_not_ready_project_count": sum(
            1
            for record in stage6_records
            if _has_grade(record, ("B_", "C_")) and not bool(record.get("stage7_commercial_input_allowed"))
        ),
        "gap_record_count": len(gap_records),
        "remaining_real_world_gap_counts": _flatten_counts(readiness_records, "remaining_real_world_gaps"),
        "fail_closed_reason_counts": _flatten_counts(readiness_records, "fail_closed_reasons"),
        "field_blocker_taxonomy_counts": blocker_taxonomy_counts,
        "operator_next_action_counts": dict(field_summary.get("operator_next_action_counts") or {}),
    }


def _recommended_next_actions(blocker_summary: Mapping[str, Any], counts: Mapping[str, Any]) -> list[str]:
    actions: list[str] = []
    if _int(blocker_summary.get("authorization_blocked_task_count")):
        actions.append("provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun_field_query")
    if _int(blocker_summary.get("field_missing_or_not_found_task_count")):
        actions.append("extend_stage4_project_code_and_source_readback_before_claiming_clearance")
    if _int(blocker_summary.get("stage4_matched_without_stage7_saleable_project_count")):
        actions.append("review_b_or_c_official_readback_for_limited_sellable_internal_package")
    if _int(counts.get("stage7_sellable_count")) == 0 and _int(counts.get("limited_sellable_review_candidate_count")) == 0:
        actions.append("do_not_expand_stage8_stage9_until_stage4_sellable_inventory_exists")
    return actions


def _project_blocking_bucket(
    readiness_record: Mapping[str, Any],
    stage6_record: Mapping[str, Any],
    field_records: list[Mapping[str, Any]],
) -> str:
    if _has_grade(stage6_record, ("B_", "C_")) or any(
        str(record.get("downstream_abcd_grade") or "").startswith(("B_", "C_")) for record in field_records
    ):
        return "stage4_matched_needs_manual_limited_sellable_review"
    if any(str(record.get("adapter_result_state") or "") == "NEEDS_BROWSER" for record in field_records):
        return "authorization_or_browser_blocked"
    if any(str(record.get("adapter_result_state") or "") == "NOT_FOUND" for record in field_records):
        return "official_source_not_found_or_field_missing"
    if str(readiness_record.get("stage5_rule_gate_status") or "").upper() == "REVIEW":
        return "stage5_rule_review"
    if str(readiness_record.get("stage3_field_parse_state") or "").upper() and not str(readiness_record.get("stage3_field_parse_state") or "").upper().startswith("PARSED"):
        return "stage3_parse_gap"
    return "unclassified_review_required"


def _resolve_stage6_status_path(value: str | Path | None, root: Path) -> Path:
    if value:
        return Path(value)
    candidates = (
        root / "stage6-review-loop-project-status-table.json",
        root / "stage6-review-cycle-project-status-table.json",
        root / "stage6-review-cycle-runner-v1.json",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_path(value: str | Path | None, default: Path) -> Path:
    return Path(value) if value else default


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    if isinstance(records, list):
        return [dict(record) for record in records if isinstance(record, Mapping)]
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping):
        records = manifest.get("records") or manifest.get("operator_projection_status_table")
        if isinstance(records, Mapping):
            records = records.get("records")
        if isinstance(records, list):
            return [dict(record) for record in records if isinstance(record, Mapping)]
    return []


def _field_task_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    records = manifest.get("field_task_records")
    return [dict(record) for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []


def _summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        return dict(summary)
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping) and isinstance(manifest.get("summary"), Mapping):
        return dict(manifest["summary"])
    return {}


def _ordered_project_ids(*record_groups: list[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for records in record_groups:
        for record in records:
            project_id = str(record.get("project_id") or "").strip()
            if project_id and project_id not in out:
                out.append(project_id)
    return out


def _stage5_review_count(summary: Mapping[str, Any], records: list[Mapping[str, Any]]) -> int:
    counts = summary.get("stage5_rule_gate_status_counts")
    if isinstance(counts, Mapping) and "REVIEW" in counts:
        return int(counts.get("REVIEW") or 0)
    return sum(
        1
        for record in records
        if str(record.get("stage5_rule_gate_status") or "").upper() == "REVIEW"
        or str(record.get("stage5_gate_state") or "").upper() == "REVIEW_REQUIRED"
    )


def _stage3_parse_attempt_succeeded(value: Any) -> bool:
    state = str(value or "").upper()
    if not state:
        return False
    if state.startswith("PARSED"):
        return True
    if state.endswith("_REVIEW_REQUIRED") and "STAGE2" not in state and "PENDING" not in state:
        return True
    return state in {"READBACK_READY", "FIELD_SIGNALS_READY"}


def _count_state(summary: Mapping[str, Any], records: list[Mapping[str, Any]], field: str, state: str) -> int:
    counts = summary.get(f"{field}_counts")
    if isinstance(counts, Mapping) and state in counts:
        return int(counts.get(state) or 0)
    if field == "adapter_result_state":
        counts = summary.get("adapter_result_state_counts")
        if isinstance(counts, Mapping) and state in counts:
            return int(counts.get(state) or 0)
    return sum(1 for record in records if str(record.get(field) or "") == state)


def _has_grade(record: Mapping[str, Any], prefixes: tuple[str, ...]) -> bool:
    counts = record.get("release_field_query_downstream_abcd_grade_counts")
    if isinstance(counts, Mapping):
        return any(str(key).startswith(prefixes) and int(value or 0) > 0 for key, value in counts.items())
    return False


def _flatten_counts(records: list[Mapping[str, Any]], field: str) -> dict[str, int]:
    return _counts(item for record in records for item in _as_list(record.get(field)))


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        out[text] = out.get(text, 0) + 1
    return out


def _distinct_count(records: list[Mapping[str, Any]], field: str) -> int:
    return len({str(record.get(field) or "").strip() for record in records if str(record.get(field) or "").strip()})


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    scoreboard = payload.get("scoreboard") if isinstance(payload.get("scoreboard"), Mapping) else {}
    blockers = payload.get("blocker_summary") if isinstance(payload.get("blocker_summary"), Mapping) else {}
    lines = [
        "# Stage1-6 Sellable Scoreboard v1",
        "",
        f"- candidate_count: {scoreboard.get('candidate_count', 0)}",
        f"- stage2_success_count: {scoreboard.get('stage2_success_count', 0)}",
        f"- stage3_success_count: {scoreboard.get('stage3_success_count', 0)}",
        f"- stage4_matched_task_count: {scoreboard.get('stage4_matched_task_count', 0)}",
        f"- stage4_needs_browser_task_count: {scoreboard.get('stage4_needs_browser_task_count', 0)}",
        f"- stage5_review_count: {scoreboard.get('stage5_review_count', 0)}",
        f"- stage6_fact_ready_count: {scoreboard.get('stage6_fact_ready_count', 0)}",
        f"- stage7_sellable_count: {scoreboard.get('stage7_sellable_count', 0)}",
        f"- limited_sellable_review_candidate_count: {scoreboard.get('limited_sellable_review_candidate_count', 0)}",
        f"- real_public_sellable_pack_rate: {scoreboard.get('real_public_sellable_pack_rate', 0)}",
        "",
        "## Blockers",
    ]
    for key, value in blockers.items():
        if isinstance(value, Mapping):
            lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        else:
            lines.append(f"- {key}: {value}")
    lines.extend(["", "customer_visible_allowed=false; query_miss_is_not_clearance=true; no_legal_conclusion=true"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pressure-root", default=str(DEFAULT_PRESSURE_ROOT))
    parser.add_argument("--pressure-summary-json", default="")
    parser.add_argument("--readiness-json", default="")
    parser.add_argument("--gap-summary-json", default="")
    parser.add_argument("--field-query-root", default=str(DEFAULT_FIELD_QUERY_ROOT))
    parser.add_argument("--field-query-json", default="")
    parser.add_argument("--stage6-status-root", default=str(DEFAULT_STAGE6_STATUS_ROOT))
    parser.add_argument("--stage6-status-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage1_6_sellable_scoreboard(
        pressure_root=args.pressure_root,
        pressure_summary_json=args.pressure_summary_json or None,
        readiness_json=args.readiness_json or None,
        gap_summary_json=args.gap_summary_json or None,
        field_query_root=args.field_query_root,
        field_query_json=args.field_query_json or None,
        stage6_status_root=args.stage6_status_root,
        stage6_status_json=args.stage6_status_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["scoreboard"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
