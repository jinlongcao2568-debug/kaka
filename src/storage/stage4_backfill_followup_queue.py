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
        "summary": _summary(records),
        "public_source_deepening_policy": deepening_policy,
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
    detail = str(row.get("stage4_project_code_backfill_gap_detail") or "").strip()
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


def _followup_route(detail: str) -> str:
    if detail == "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED":
        return "public_source_retry_then_local_authority_fallback"
    if detail in {
        "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
        "ORIGINAL_NOTICE_NOT_FOUND_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
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
    if route == "public_source_retry_then_local_authority_fallback":
        return ["public_source_retry_budget_or_project_local_authority_adapter"]
    if route == "original_notice_retry_then_local_authority_fallback":
        return ["original_notice_retry_budget_or_project_local_authority_adapter"]
    if route == "public_source_readback_required":
        return ["public_source_readback_budget"]
    if route == "operator_classify_backfill_gap":
        return ["operator_classification_reason"]
    return ["project_local_authority_source_url_or_adapter"]


def _recommended_next_action(route: str) -> str:
    actions = {
        "public_source_retry_then_local_authority_fallback": "retry_public_source_or_route_to_project_local_authority_without_clearance_claim",
        "local_authority_fallback_source_planning": "plan_project_local_authority_readback_without_treating_not_found_as_clearance",
        "original_notice_retry_then_local_authority_fallback": "retry_original_notice_or_route_to_project_local_authority_without_clearance_claim",
        "public_source_readback_required": "run_public_source_readback_before_any_clearance_claim",
        "operator_classify_backfill_gap": "operator_classifies_backfill_gap_before_retry",
    }
    return actions.get(route, "operator_reviews_stage4_backfill_gap")


def _execution_priority(route: str, *, deepening_recommended: bool) -> str:
    if not deepening_recommended:
        return "NORMAL"
    if route in {
        "public_source_retry_then_local_authority_fallback",
        "original_notice_retry_then_local_authority_fallback",
        "public_source_readback_required",
    }:
        return "HIGH_PUBLIC_SOURCE_DEEPENING"
    if route == "local_authority_fallback_source_planning":
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
