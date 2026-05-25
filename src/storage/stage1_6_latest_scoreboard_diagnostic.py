from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DIAGNOSTIC_KIND = "stage1_6_latest_scoreboard_diagnostic_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-6-latest-scoreboard-diagnostic-v1")
DEFAULT_SCOREBOARD_FILENAME = "stage1-6-sellable-scoreboard-v1.json"
DEFAULT_COMPARISON_FILENAME = "stage1-6-scoreboard-comparison-v1.json"
DEFAULT_FOLLOWUP_QUEUE_FILENAME = "stage4-backfill-followup-queue-v1.json"


def build_stage1_6_latest_scoreboard_diagnostic(
    *,
    latest_scoreboard_json: str | Path,
    previous_scoreboard_json: str | Path | None = None,
    scoreboard_comparison_json: str | Path | None = None,
    followup_queue_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    latest_path = Path(latest_scoreboard_json)
    previous_path = Path(previous_scoreboard_json) if previous_scoreboard_json else None
    comparison_path = Path(scoreboard_comparison_json) if scoreboard_comparison_json else None
    followup_path = Path(followup_queue_json) if followup_queue_json else None
    latest = _read_json(latest_path)
    previous = _read_json(previous_path) if previous_path else {}
    comparison = _read_json(comparison_path) if comparison_path else {}
    followup = _read_json(followup_path) if followup_path else {}
    latest_board = _scoreboard(latest)
    previous_board = _scoreboard(previous)
    latest_rows = _rows(latest)
    result = {
        "diagnostic_kind": DIAGNOSTIC_KIND,
        "diagnostic_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "latest_scoreboard_json": str(latest_path),
            "previous_scoreboard_json": str(previous_path or ""),
            "scoreboard_comparison_json": str(comparison_path or ""),
            "followup_queue_json": str(followup_path or ""),
        },
        "latest_run": _run_summary(latest_board),
        "delta_from_previous": _delta_summary(latest_board, previous_board),
        "stage5_diagnosis": _stage5_diagnosis(latest_board),
        "official_readback_ready_review_queue": _official_readback_ready_review_queue(latest_rows),
        "release_evidence_promotion_queue": _release_evidence_promotion_queue(latest_rows),
        "stage4_readback_diagnosis": _stage4_readback_diagnosis(latest_board),
        "followup_queue_diagnosis": _followup_queue_diagnosis(followup),
        "comparison_diagnosis": _comparison_diagnosis(comparison),
        "p0_gap_summary": _p0_gap_summary(latest_board, latest_rows, followup, comparison),
        "recommended_next_actions": _recommended_next_actions(latest_board, followup, comparison),
        "safety": {
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "not_found_blocked_are_not_clearance": True,
        },
    }
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "stage1-6-latest-scoreboard-diagnostic-v1.json", result)
    _write_markdown(out_dir / "stage1-6-latest-scoreboard-diagnostic-v1.md", result)
    return result


def _run_summary(scoreboard: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_count": _int(scoreboard.get("candidate_count")),
        "stage2_success_count": _int(scoreboard.get("stage2_success_count")),
        "stage3_success_count": _int(scoreboard.get("stage3_success_count")),
        "limited_sellable_review_candidate_count": _int(
            scoreboard.get("limited_sellable_review_candidate_count")
        ),
        "real_public_sellable_pack_rate": float(scoreboard.get("real_public_sellable_pack_rate") or 0),
        "stage5_operational_primary_track_counts": dict(
            scoreboard.get("stage5_operational_primary_track_counts") or {}
        ),
        "stage5_operational_priority_bucket_counts": dict(
            scoreboard.get("stage5_operational_priority_bucket_counts") or {}
        ),
        "stage4_public_readback_channel_outcome_counts": dict(
            scoreboard.get("stage4_public_readback_channel_outcome_counts") or {}
        ),
        "stage4_project_code_backfill_state_counts": dict(
            scoreboard.get("stage4_project_code_backfill_state_counts") or {}
        ),
    }


def _delta_summary(latest: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    if not previous:
        return {"delta_state": "NO_PREVIOUS_SCOREBOARD"}
    return {
        "delta_state": "COMPUTED_FROM_SCOREBOARDS",
        "candidate_count_delta": _int(latest.get("candidate_count")) - _int(previous.get("candidate_count")),
        "limited_sellable_review_candidate_count_delta": _int(
            latest.get("limited_sellable_review_candidate_count")
        )
        - _int(previous.get("limited_sellable_review_candidate_count")),
        "real_public_sellable_pack_rate_delta": round(
            float(latest.get("real_public_sellable_pack_rate") or 0)
            - float(previous.get("real_public_sellable_pack_rate") or 0),
            4,
        ),
        "missing_project_code_backfill_input_delta": _count_delta(
            latest,
            previous,
            "stage4_project_code_backfill_state_counts",
            "MISSING_PROJECT_CODE_BACKFILL_INPUT",
        ),
        "public_identifier_backfilled_delta": _count_delta(
            latest,
            previous,
            "stage4_project_code_backfill_state_counts",
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        ),
    }


def _stage5_diagnosis(scoreboard: Mapping[str, Any]) -> dict[str, Any]:
    primary = dict(scoreboard.get("stage5_operational_primary_track_counts") or {})
    priority = dict(scoreboard.get("stage5_operational_priority_bucket_counts") or {})
    return {
        "primary_track_counts": primary,
        "priority_bucket_counts": priority,
        "official_readback_ready_count": _int(primary.get("official_readback_ready")),
        "public_source_blocked_count": _int(primary.get("public_source_blocked")),
        "source_not_found_count": _int(primary.get("source_not_found")),
        "limited_sellable_review_candidate_count": _int(
            scoreboard.get("limited_sellable_review_candidate_count")
        ),
        "diagnosis_state": _stage5_diagnosis_state(scoreboard),
    }


def _stage5_diagnosis_state(scoreboard: Mapping[str, Any]) -> str:
    limited = _int(scoreboard.get("limited_sellable_review_candidate_count"))
    official_ready = _int(
        dict(scoreboard.get("stage5_operational_primary_track_counts") or {}).get("official_readback_ready")
    )
    if limited > 0:
        return "LIMITED_SELLABLE_REVIEW_CANDIDATES_PRESENT"
    if official_ready > 0:
        return "OFFICIAL_READBACK_READY_NEEDS_B_OR_C_RELEASE_EVIDENCE_REVIEW"
    return "NO_LIMITED_SELLABLE_OR_OFFICIAL_READBACK_READY"


def _official_readback_ready_review_queue(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    records = []
    for row in rows:
        if str(row.get("stage5_operational_primary_track") or "") != "official_readback_ready":
            continue
        if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE":
            continue
        record = {
            "project_id": str(row.get("project_id") or ""),
            "project_name": str(row.get("project_name") or ""),
            "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
            "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
            "stage4_public_identifier_backfill_source": str(row.get("stage4_public_identifier_backfill_source") or ""),
            "p13b_public_source_readback_state": str(row.get("p13b_public_source_readback_state") or ""),
            "p13b_original_notice_readback_state": str(row.get("p13b_original_notice_readback_state") or ""),
            "p13b_ygp_original_readback_state": str(row.get("p13b_ygp_original_readback_state") or ""),
            "p13b_overlap_triage_state": str(row.get("p13b_overlap_triage_state") or ""),
            "review_blocker_state": _official_readback_ready_blocker_state(row),
            "recommended_next_action": _official_readback_ready_next_action(row),
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
        records.append(record)
    return {
        "record_count": len(records),
        "review_blocker_state_counts": _counts(record.get("review_blocker_state") for record in records),
        "records": records,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _release_evidence_promotion_queue(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    records = []
    for row in rows:
        if str(row.get("stage5_operational_primary_track") or "") != "official_readback_ready":
            continue
        if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE":
            continue
        blocker = _official_readback_ready_blocker_state(row)
        if blocker != "PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE":
            continue
        record = {
            "project_id": str(row.get("project_id") or ""),
            "project_name": str(row.get("project_name") or ""),
            "promotion_state": "PUBLIC_IDENTIFIER_READY_NEEDS_B_OR_C_RELEASE_EVIDENCE_READBACK",
            "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
            "stage4_public_identifier_backfill_source": str(row.get("stage4_public_identifier_backfill_source") or ""),
            "ygp_project_code_variants": _dedupe(
                [
                    *_as_list(row.get("p13b_ygp_project_code_variants")),
                    *_as_list(row.get("p13b_overlap_ygp_project_code_variants")),
                ]
            ),
            "ygp_biz_code_variants": _dedupe(
                [
                    *_as_list(row.get("p13b_ygp_biz_code_variants")),
                    *_as_list(row.get("p13b_overlap_ygp_biz_code_variants")),
                ]
            ),
            "ygp_site_code_variants": _dedupe(
                [
                    *_as_list(row.get("p13b_ygp_site_code_variants")),
                    *_as_list(row.get("p13b_overlap_ygp_site_code_variants")),
                ]
            ),
            "ygp_notice_id_variants": _dedupe(
                [
                    *_as_list(row.get("p13b_ygp_notice_id_variants")),
                    *_as_list(row.get("p13b_overlap_ygp_notice_id_variants")),
                ]
            ),
            "gdcic_project_code_route_allowed": False,
            "gdcic_project_code_route_policy": str(
                row.get("stage4_gdcic_project_code_route_policy")
                or "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE"
            ),
            "required_input": [
                "stage4_release_adapter_bridge_or_ygp_backfill_field_query_budget",
                "b_or_c_official_release_evidence_readback",
            ],
            "recommended_next_action": "run_stage4_release_adapter_bridge_for_b_or_c_official_readback_before_limited_projection",
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
        records.append(record)
    return {
        "record_count": len(records),
        "promotion_state_counts": _counts(record.get("promotion_state") for record in records),
        "gdcic_project_code_route_policy_counts": _counts(
            record.get("gdcic_project_code_route_policy") for record in records
        ),
        "records": records,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _official_readback_ready_blocker_state(row: Mapping[str, Any]) -> str:
    evidence_grades = dict(row.get("limited_sellable_review_evidence_grade_counts") or {})
    if _int(evidence_grades.get("B_ENHANCEMENT_OFFICIAL_READBACK")) or _int(
        evidence_grades.get("C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
    ):
        return "B_OR_C_EVIDENCE_PRESENT_BUT_NOT_PROJECTED"
    if str(row.get("p13b_overlap_triage_state") or "") == "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE":
        return "PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE"
    if "evidence_insufficient" in set(row.get("stage5_operational_review_families") or []):
        return "EVIDENCE_INSUFFICIENT_NOT_LIMITED_SELLABLE"
    return "B_OR_C_RELEASE_EVIDENCE_REVIEW_REQUIRED"


def _official_readback_ready_next_action(row: Mapping[str, Any]) -> str:
    blocker = _official_readback_ready_blocker_state(row)
    if blocker == "B_OR_C_EVIDENCE_PRESENT_BUT_NOT_PROJECTED":
        return "inspect_stage6_projection_for_missing_limited_sellable_mapping"
    if blocker == "PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE":
        return "feed_public_identifier_to_release_evidence_adapter_before_limited_review"
    if blocker == "EVIDENCE_INSUFFICIENT_NOT_LIMITED_SELLABLE":
        return "continue_b_or_c_release_evidence_readback_or_keep_internal_evidence_insufficient"
    return "review_for_b_or_c_official_release_evidence_only"


def _stage4_readback_diagnosis(scoreboard: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "channel_outcome_counts": dict(scoreboard.get("stage4_public_readback_channel_outcome_counts") or {}),
        "project_code_backfill_state_counts": dict(
            scoreboard.get("stage4_project_code_backfill_state_counts") or {}
        ),
        "gdcic_authorized_readback_status": dict(scoreboard.get("gdcic_authorized_readback_status") or {}),
        "query_miss_is_not_clearance": True,
    }


def _followup_queue_diagnosis(followup: Mapping[str, Any]) -> dict[str, Any]:
    summary = followup.get("summary") if isinstance(followup.get("summary"), Mapping) else {}
    record_count = _int(summary.get("followup_record_count")) or _int(summary.get("fallback_source_plan_record_count"))
    return {
        "followup_record_count": record_count,
        "source_plan_record_count": _int(summary.get("fallback_source_plan_record_count")),
        "followup_route_counts": dict(summary.get("followup_route_counts") or {}),
        "execution_priority_counts": dict(summary.get("execution_priority_counts") or {}),
        "public_source_deepening_recommended_counts": dict(
            summary.get("public_source_deepening_recommended_counts") or {}
        ),
        "plan_state": str(
            (followup.get("next_regression_execution_plan") or {}).get("plan_state")
            if isinstance(followup.get("next_regression_execution_plan"), Mapping)
            else ""
        ),
    }


def _comparison_diagnosis(comparison: Mapping[str, Any]) -> dict[str, Any]:
    deltas = comparison.get("delta_from_previous_row")
    latest_delta = deltas[-1] if isinstance(deltas, list) and deltas else {}
    recommendations = (
        comparison.get("public_source_deepening_recommendations")
        if isinstance(comparison.get("public_source_deepening_recommendations"), list)
        else []
    )
    return {
        "latest_effect_state": str(latest_delta.get("public_source_deepening_effect_state") or ""),
        "latest_regression_flags": list(latest_delta.get("regression_flags") or []),
        "recommendation_count": len(recommendations),
        "latest_recommendation": dict(recommendations[-1]) if recommendations else {},
    }


def _p0_gap_summary(
    scoreboard: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
    followup: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> dict[str, Any]:
    primary = dict(scoreboard.get("stage5_operational_primary_track_counts") or {})
    return {
        "local_source_blocked_or_not_found_remaining_count": _int(primary.get("public_source_blocked"))
        + _int(primary.get("source_not_found")),
        "official_readback_ready_not_limited_count": max(
            0,
            _int(primary.get("official_readback_ready"))
            - _int(scoreboard.get("limited_sellable_review_candidate_count")),
        ),
        "followup_queue_remaining_count": _followup_record_count(followup),
        "release_evidence_promotion_required_count": _release_evidence_promotion_queue(rows)["record_count"],
        "project_rows_with_customer_visible_allowed_count": sum(
            1 for row in rows if bool(row.get("customer_visible_allowed"))
        ),
        "comparison_recommends_deepening": bool(
            comparison.get("public_source_deepening_recommendations")
        ),
    }


def _recommended_next_actions(
    scoreboard: Mapping[str, Any],
    followup: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> list[str]:
    actions: list[str] = []
    queue_count = _followup_record_count(followup)
    official_ready = _int(
        dict(scoreboard.get("stage5_operational_primary_track_counts") or {}).get("official_readback_ready")
    )
    limited = _int(scoreboard.get("limited_sellable_review_candidate_count"))
    if queue_count:
        actions.append("run_stage4_followup_queue_through_controller_before_manual_triage")
    if official_ready > limited:
        actions.append("review_official_readback_ready_rows_for_b_or_c_release_evidence_only")
        actions.append("promote_public_identifiers_to_b_or_c_release_evidence_readback_before_limited_projection")
    if comparison.get("public_source_deepening_recommendations"):
        actions.append("continue_public_source_deepening_from_comparison_recommendation")
    actions.append("keep_customer_delivery_payment_refund_disabled")
    actions.append("keep_not_found_blocked_as_non_clearance")
    return actions


def _followup_record_count(followup: Mapping[str, Any]) -> int:
    summary = followup.get("summary") if isinstance(followup.get("summary"), Mapping) else {}
    return _int(summary.get("followup_record_count")) or _int(summary.get("fallback_source_plan_record_count"))


def _scoreboard(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    scoreboard = payload.get("scoreboard") if isinstance(payload, Mapping) else {}
    return scoreboard if isinstance(scoreboard, Mapping) else {}


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = payload.get("project_rows") if isinstance(payload, Mapping) else []
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _count_delta(latest: Mapping[str, Any], previous: Mapping[str, Any], key: str, count_key: str) -> int:
    return _int(dict(latest.get(key) or {}).get(count_key)) - _int(dict(previous.get(key) or {}).get(count_key))


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    lines = [
        "# Stage1-6 Latest Scoreboard Diagnostic v1",
        "",
        f"- latest_run: {json.dumps(payload.get('latest_run', {}), ensure_ascii=False, sort_keys=True)}",
        f"- delta_from_previous: {json.dumps(payload.get('delta_from_previous', {}), ensure_ascii=False, sort_keys=True)}",
        f"- stage5_diagnosis: {json.dumps(payload.get('stage5_diagnosis', {}), ensure_ascii=False, sort_keys=True)}",
        f"- official_readback_ready_review_queue: {json.dumps(payload.get('official_readback_ready_review_queue', {}), ensure_ascii=False, sort_keys=True)}",
        f"- release_evidence_promotion_queue: {json.dumps(payload.get('release_evidence_promotion_queue', {}), ensure_ascii=False, sort_keys=True)}",
        f"- followup_queue_diagnosis: {json.dumps(payload.get('followup_queue_diagnosis', {}), ensure_ascii=False, sort_keys=True)}",
        f"- p0_gap_summary: {json.dumps(payload.get('p0_gap_summary', {}), ensure_ascii=False, sort_keys=True)}",
        f"- recommended_next_actions: {json.dumps(payload.get('recommended_next_actions', []), ensure_ascii=False)}",
        "",
        "customer_visible_allowed=false; query_miss_is_not_clearance=true; no_legal_conclusion=true",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _as_list(value: Any) -> list[Any]:
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
    for value in _as_list(values):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-scoreboard-json", required=True)
    parser.add_argument("--previous-scoreboard-json", default="")
    parser.add_argument("--scoreboard-comparison-json", default="")
    parser.add_argument("--followup-queue-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage1_6_latest_scoreboard_diagnostic(
        latest_scoreboard_json=args.latest_scoreboard_json,
        previous_scoreboard_json=args.previous_scoreboard_json or None,
        scoreboard_comparison_json=args.scoreboard_comparison_json or None,
        followup_queue_json=args.followup_queue_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result.get("p0_gap_summary") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
