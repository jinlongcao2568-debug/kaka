from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ATTRIBUTION_KIND = "stage1_6_limited_success_attribution_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-6-limited-success-attribution-v1")


def build_stage1_6_limited_success_attribution(
    *,
    success_scoreboard_json: str | Path,
    target_scoreboard_json: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    success_path = Path(success_scoreboard_json)
    target_path = Path(target_scoreboard_json)
    success = _read_json(success_path)
    target = _read_json(target_path)
    success_rows = _rows(success)
    target_rows = _rows(target)
    success_limited_rows = [
        row for row in success_rows if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE"
    ]
    target_official_ready_not_limited = [
        row
        for row in target_rows
        if str(row.get("stage5_operational_primary_track") or "") == "official_readback_ready"
        and str(row.get("limited_sellable_review_candidate_state") or "") != "REVIEW_CANDIDATE"
    ]
    result = {
        "attribution_kind": ATTRIBUTION_KIND,
        "attribution_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "success_scoreboard_json": str(success_path),
            "target_scoreboard_json": str(target_path),
        },
        "success_run": _run_summary(success),
        "target_run": _run_summary(target),
        "success_limited_path": _success_limited_path(success_limited_rows),
        "target_not_limited_path": _target_not_limited_path(target_official_ready_not_limited),
        "attribution_summary": _attribution_summary(success_limited_rows, target_official_ready_not_limited),
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
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "stage1-6-limited-success-attribution-v1.json", result)
    _write_markdown(out_dir / "stage1-6-limited-success-attribution-v1.md", result)
    return result


def _run_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    board = _scoreboard(payload)
    return {
        "candidate_count": _int(board.get("candidate_count")),
        "limited_sellable_review_candidate_count": _int(board.get("limited_sellable_review_candidate_count")),
        "real_public_sellable_pack_rate": float(board.get("real_public_sellable_pack_rate") or 0),
        "stage5_operational_primary_track_counts": dict(board.get("stage5_operational_primary_track_counts") or {}),
        "stage5_operational_priority_bucket_counts": dict(board.get("stage5_operational_priority_bucket_counts") or {}),
        "stage4_public_readback_channel_outcome_counts": dict(
            board.get("stage4_public_readback_channel_outcome_counts") or {}
        ),
    }


def _success_limited_path(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len(rows),
        "primary_track_counts": _counts(row.get("stage5_operational_primary_track") for row in rows),
        "review_bucket_counts": _counts(row.get("stage5_operational_review_bucket") for row in rows),
        "evidence_grade_counts": _merge_count_maps(row.get("limited_sellable_review_evidence_grade_counts") for row in rows),
        "stage4_backfill_state_counts": _counts(row.get("stage4_project_code_backfill_state") for row in rows),
        "project_records": [_limited_record(row) for row in rows],
    }


def _target_not_limited_path(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len(rows),
        "review_blocker_state_counts": _counts(_target_blocker(row) for row in rows),
        "stage4_backfill_state_counts": _counts(row.get("stage4_project_code_backfill_state") for row in rows),
        "project_records": [_target_record(row) for row in rows],
    }


def _attribution_summary(
    success_limited_rows: list[Mapping[str, Any]],
    target_official_ready_not_limited: list[Mapping[str, Any]],
) -> dict[str, Any]:
    success_grades = _merge_count_maps(
        row.get("limited_sellable_review_evidence_grade_counts") for row in success_limited_rows
    )
    target_blockers = _counts(_target_blocker(row) for row in target_official_ready_not_limited)
    return {
        "success_required_b_or_c_grade_count": _int(success_grades.get("B_ENHANCEMENT_OFFICIAL_READBACK"))
        + _int(success_grades.get("C_REVERSE_EXPLANATION_OFFICIAL_READBACK")),
        "target_public_identifier_ready_not_release_evidence_count": _int(
            target_blockers.get("PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE")
        ),
        "primary_difference": _primary_difference(success_grades, target_blockers),
        "recommended_next_action": "route_target_public_identifiers_to_b_or_c_release_evidence_adapter_before_limited_review",
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _primary_difference(success_grades: Mapping[str, Any], target_blockers: Mapping[str, Any]) -> str:
    if _int(success_grades.get("B_ENHANCEMENT_OFFICIAL_READBACK")) or _int(
        success_grades.get("C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
    ):
        if _int(target_blockers.get("PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE")):
            return "SUCCESS_HAS_B_OR_C_RELEASE_EVIDENCE_TARGET_ONLY_HAS_PUBLIC_IDENTIFIER_READY"
    return "LIMITED_SUCCESS_DIFFERENCE_REQUIRES_MANUAL_REVIEW"


def _limited_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "stage5_operational_primary_track": str(row.get("stage5_operational_primary_track") or ""),
        "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
        "limited_sellable_review_evidence_grade_counts": dict(
            row.get("limited_sellable_review_evidence_grade_counts") or {}
        ),
        "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
        "stage4_public_identifier_backfill_source": str(row.get("stage4_public_identifier_backfill_source") or ""),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _target_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
        "review_blocker_state": _target_blocker(row),
        "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
        "stage4_public_identifier_backfill_source": str(row.get("stage4_public_identifier_backfill_source") or ""),
        "p13b_overlap_triage_state": str(row.get("p13b_overlap_triage_state") or ""),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
    }


def _target_blocker(row: Mapping[str, Any]) -> str:
    if str(row.get("p13b_overlap_triage_state") or "") == "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE":
        return "PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE"
    if "evidence_insufficient" in set(row.get("stage5_operational_review_families") or []):
        return "EVIDENCE_INSUFFICIENT_NOT_LIMITED_SELLABLE"
    return "B_OR_C_RELEASE_EVIDENCE_REVIEW_REQUIRED"


def _scoreboard(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    board = payload.get("scoreboard")
    return board if isinstance(board, Mapping) else {}


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = payload.get("project_rows")
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _merge_count_maps(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key, count in value.items():
            counts[str(key)] = counts.get(str(key), 0) + _int(count)
    return counts


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    lines = [
        "# Stage1-6 Limited Success Attribution v1",
        "",
        f"- success_run: {json.dumps(payload.get('success_run', {}), ensure_ascii=False, sort_keys=True)}",
        f"- target_run: {json.dumps(payload.get('target_run', {}), ensure_ascii=False, sort_keys=True)}",
        f"- attribution_summary: {json.dumps(payload.get('attribution_summary', {}), ensure_ascii=False, sort_keys=True)}",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--success-scoreboard-json", required=True)
    parser.add_argument("--target-scoreboard-json", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage1_6_limited_success_attribution(
        success_scoreboard_json=args.success_scoreboard_json,
        target_scoreboard_json=args.target_scoreboard_json,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result.get("attribution_summary") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
