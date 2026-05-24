from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


COMPARISON_KIND = "stage1_6_scoreboard_comparison_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-6-scoreboard-comparison-v1")
DEFAULT_SCOREBOARD_FILENAME = "stage1-6-sellable-scoreboard-v1.json"


def build_stage1_6_scoreboard_comparison(
    *,
    scoreboard_jsons: list[str | Path] | None = None,
    run_roots: list[str | Path] | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    inputs = _resolve_scoreboard_inputs(scoreboard_jsons or [], run_roots or [])
    rows = [_comparison_row(path) for path in inputs]
    baseline = rows[0] if rows else {}
    deltas = [_delta_row(row, baseline) for row in rows]
    adjacent_deltas = _adjacent_delta_rows(rows)
    result = {
        "comparison_kind": COMPARISON_KIND,
        "comparison_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": [str(path) for path in inputs],
        "comparison_rows": rows,
        "delta_from_first_row": deltas,
        "delta_from_previous_row": adjacent_deltas,
        "summary": _summary(rows),
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
    _write_json(out_dir / "stage1-6-scoreboard-comparison-v1.json", result)
    _write_markdown(out_dir / "stage1-6-scoreboard-comparison-v1.md", result)
    return result


def _resolve_scoreboard_inputs(
    scoreboard_jsons: list[str | Path],
    run_roots: list[str | Path],
) -> list[Path]:
    paths: list[Path] = []
    for value in scoreboard_jsons:
        path = Path(value)
        if path.exists() and path.is_file():
            paths.append(path)
    for value in run_roots:
        root = Path(value)
        candidates = [
            root / "scoreboard" / DEFAULT_SCOREBOARD_FILENAME,
            root / DEFAULT_SCOREBOARD_FILENAME,
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                paths.append(candidate)
                break
    deduped: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in deduped:
            deduped.append(resolved)
    return deduped


def _comparison_row(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    scoreboard = payload.get("scoreboard") if isinstance(payload.get("scoreboard"), Mapping) else {}
    blocker_summary = payload.get("blocker_summary") if isinstance(payload.get("blocker_summary"), Mapping) else {}
    run_label = _run_label(path)
    return {
        "run_label": run_label,
        "scoreboard_json": str(path),
        "candidate_count": _int(scoreboard.get("candidate_count")),
        "stage2_success_count": _int(scoreboard.get("stage2_success_count")),
        "stage3_success_count": _int(scoreboard.get("stage3_success_count")),
        "stage2_success_rate": _ratio(scoreboard.get("stage2_success_count"), scoreboard.get("candidate_count")),
        "stage3_success_rate": _ratio(scoreboard.get("stage3_success_count"), scoreboard.get("candidate_count")),
        "limited_sellable_review_candidate_count": _int(
            scoreboard.get("limited_sellable_review_candidate_count")
        ),
        "strong_lead_review_candidate_count": _int(scoreboard.get("strong_lead_review_candidate_count")),
        "real_public_sellable_pack_rate": float(scoreboard.get("real_public_sellable_pack_rate") or 0),
        "stage4_adapter_result_state_counts": dict(scoreboard.get("stage4_adapter_result_state_counts") or {}),
        "stage4_public_source_readback_state_counts": dict(
            scoreboard.get("stage4_public_source_readback_state_counts") or {}
        ),
        "stage4_original_notice_readback_state_counts": dict(
            scoreboard.get("stage4_original_notice_readback_state_counts") or {}
        ),
        "stage4_ygp_original_readback_state_counts": dict(
            scoreboard.get("stage4_ygp_original_readback_state_counts") or {}
        ),
        "stage4_public_readback_outcome_counts": dict(
            scoreboard.get("stage4_public_readback_outcome_counts") or {}
        ),
        "stage5_operational_review_bucket_counts": dict(
            scoreboard.get("stage5_operational_review_bucket_counts") or {}
        ),
        "stage5_operational_review_queue_counts": dict(
            scoreboard.get("stage5_operational_review_queue_counts") or {}
        ),
        "stage1_3_long_tail_bucket_counts": dict(scoreboard.get("stage1_3_long_tail_bucket_counts") or {}),
        "stage1_3_long_tail_signal_counts": dict(scoreboard.get("stage1_3_long_tail_signal_counts") or {}),
        "stage1_3_identity_confirmation_state_counts": dict(
            scoreboard.get("stage1_3_identity_confirmation_state_counts") or {}
        ),
        "stage4_project_code_backfill_state_counts": dict(
            scoreboard.get("stage4_project_code_backfill_state_counts") or {}
        ),
        "stage4_public_identifier_backfill_source_counts": dict(
            scoreboard.get("stage4_public_identifier_backfill_source_counts") or {}
        ),
        "stage4_gdcic_project_code_route_policy_counts": dict(
            scoreboard.get("stage4_gdcic_project_code_route_policy_counts") or {}
        ),
        "stage6_limited_sellable_review_public_source_chain_counts": dict(
            scoreboard.get("stage6_limited_sellable_review_public_source_chain_counts") or {}
        ),
        "stage6_limited_sellable_review_gdcic_project_code_route_policy_counts": dict(
            scoreboard.get("stage6_limited_sellable_review_gdcic_project_code_route_policy_counts") or {}
        ),
        "gdcic_authorized_readback_status": dict(scoreboard.get("gdcic_authorized_readback_status") or {}),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
        "active_fail_closed_reason_counts": dict(blocker_summary.get("active_fail_closed_reason_counts") or {}),
    }


def _delta_row(row: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    rate_delta = round(
        float(row.get("real_public_sellable_pack_rate") or 0)
        - float(baseline.get("real_public_sellable_pack_rate") or 0),
        4,
    )
    limited_delta = _int(row.get("limited_sellable_review_candidate_count")) - _int(
        baseline.get("limited_sellable_review_candidate_count")
    )
    matched_delta = _count_delta(row, baseline, "stage4_adapter_result_state_counts", "MATCHED")
    ygp_delta = _count_delta(
        row,
        baseline,
        "stage6_limited_sellable_review_public_source_chain_counts",
        "YGP_ORIGINAL_READBACK_BACKFILL",
    )
    return {
        "run_label": str(row.get("run_label") or ""),
        "candidate_count_delta": _int(row.get("candidate_count")) - _int(baseline.get("candidate_count")),
        "limited_sellable_review_candidate_count_delta": limited_delta,
        "real_public_sellable_pack_rate_delta": rate_delta,
        "stage4_matched_delta": matched_delta,
        "stage4_needs_browser_delta": _count_delta(
            row, baseline, "stage4_adapter_result_state_counts", "NEEDS_BROWSER"
        ),
        "stage4_not_found_delta": _count_delta(row, baseline, "stage4_adapter_result_state_counts", "NOT_FOUND"),
        "stage4_public_readback_not_found_delta": _count_delta(
            row, baseline, "stage4_public_readback_outcome_counts", "NOT_FOUND"
        ),
        "stage4_public_readback_blocked_delta": _count_delta(
            row, baseline, "stage4_public_readback_outcome_counts", "BLOCKED"
        ),
        "stage4_public_readback_ready_delta": _count_delta(
            row, baseline, "stage4_public_readback_outcome_counts", "READBACK_READY"
        ),
        "stage4_public_identifier_backfilled_delta": _count_delta(
            row,
            baseline,
            "stage4_project_code_backfill_state_counts",
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        ),
        "stage4_project_code_missing_backfill_input_delta": _count_delta(
            row, baseline, "stage4_project_code_backfill_state_counts", "MISSING_PROJECT_CODE_BACKFILL_INPUT"
        ),
        "stage6_ygp_original_readback_backfill_delta": ygp_delta,
        "regression_flags": _regression_flags(
            rate_delta=rate_delta,
            limited_delta=limited_delta,
            matched_delta=matched_delta,
            ygp_delta=ygp_delta,
        ),
    }


def _adjacent_delta_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        previous = rows[idx - 1] if idx > 0 else row
        delta = _delta_row(row, previous)
        delta["previous_run_label"] = str(previous.get("run_label") or "")
        deltas.append(delta)
    return deltas


def _regression_flags(
    *,
    rate_delta: float,
    limited_delta: int,
    matched_delta: int,
    ygp_delta: int,
) -> list[str]:
    flags: list[str] = []
    if rate_delta < 0:
        flags.append("SELLABLE_RATE_DECREASED")
    if limited_delta < 0:
        flags.append("LIMITED_SELLABLE_COUNT_DECREASED")
    if matched_delta < 0:
        flags.append("STAGE4_MATCHED_COUNT_DECREASED")
    if ygp_delta < 0:
        flags.append("YGP_BACKFILL_COUNT_DECREASED")
    return flags


def _summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    best = max(rows, key=lambda row: float(row.get("real_public_sellable_pack_rate") or 0), default={})
    latest = rows[-1] if rows else {}
    return {
        "run_count": len(rows),
        "total_candidate_count": sum(_int(row.get("candidate_count")) for row in rows),
        "total_limited_sellable_review_candidate_count": sum(
            _int(row.get("limited_sellable_review_candidate_count")) for row in rows
        ),
        "best_rate_run_label": str(best.get("run_label") or ""),
        "best_real_public_sellable_pack_rate": float(best.get("real_public_sellable_pack_rate") or 0),
        "latest_run_label": str(latest.get("run_label") or ""),
        "latest_real_public_sellable_pack_rate": float(latest.get("real_public_sellable_pack_rate") or 0),
        "latest_limited_sellable_review_candidate_count": _int(
            latest.get("limited_sellable_review_candidate_count")
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _count_delta(
    row: Mapping[str, Any],
    baseline: Mapping[str, Any],
    field: str,
    key: str,
) -> int:
    current = row.get(field) if isinstance(row.get(field), Mapping) else {}
    base = baseline.get(field) if isinstance(baseline.get(field), Mapping) else {}
    return _int(current.get(key)) - _int(base.get(key))


def _run_label(path: Path) -> str:
    parts = list(path.parts)
    if "tmp" in parts and "evaluation-real-samples" in parts:
        idx = parts.index("evaluation-real-samples")
        if len(parts) > idx + 1:
            return parts[idx + 1]
    if path.parent.name == "scoreboard":
        return path.parent.parent.name
    return path.parent.name


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    rows = payload.get("comparison_rows") if isinstance(payload.get("comparison_rows"), list) else []
    lines = [
        "# Stage1-6 Scoreboard Comparison v1",
        "",
        "| run | candidates | limited | rate | stage4 | public readback outcomes | code backfill | code route policy | stage5 queues | stage1-3 long tail | stage6 public source chain | auth state |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        auth_status = row.get("gdcic_authorized_readback_status")
        auth_state = ""
        if isinstance(auth_status, Mapping):
            auth_state = str(auth_status.get("authorization_readiness_state") or "")
        lines.append(
            "| {run} | {candidates} | {limited} | {rate} | `{stage4}` | `{readback}` | `{code_backfill}` | `{route_policy}` | `{stage5}` | `{tail}` | `{chain}` | {auth_state} |".format(
                run=str(row.get("run_label") or ""),
                candidates=_int(row.get("candidate_count")),
                limited=_int(row.get("limited_sellable_review_candidate_count")),
                rate=float(row.get("real_public_sellable_pack_rate") or 0),
                stage4=json.dumps(row.get("stage4_adapter_result_state_counts") or {}, ensure_ascii=False, sort_keys=True),
                readback=json.dumps(
                    row.get("stage4_public_readback_outcome_counts") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                code_backfill=json.dumps(
                    row.get("stage4_project_code_backfill_state_counts") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                route_policy=json.dumps(
                    row.get("stage4_gdcic_project_code_route_policy_counts") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                stage5=json.dumps(row.get("stage5_operational_review_queue_counts") or {}, ensure_ascii=False, sort_keys=True),
                tail=json.dumps(row.get("stage1_3_long_tail_bucket_counts") or {}, ensure_ascii=False, sort_keys=True),
                chain=json.dumps(
                    row.get("stage6_limited_sellable_review_public_source_chain_counts") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                auth_state=auth_state,
            )
        )
    lines.extend(
        [
            "",
            "customer_visible_allowed=false; query_miss_is_not_clearance=true; no_legal_conclusion=true",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ratio(numerator: Any, denominator: Any) -> float:
    den = _int(denominator)
    if den <= 0:
        return 0.0
    return round(_int(numerator) / den, 4)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scoreboard-json", action="append", default=[])
    parser.add_argument("--run-root", action="append", default=[])
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage1_6_scoreboard_comparison(
        scoreboard_jsons=args.scoreboard_json,
        run_roots=args.run_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
