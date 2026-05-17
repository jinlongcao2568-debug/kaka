from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso
from storage.guangzhou_stage4_9_remediation_delta_report import (
    DEFAULT_BASELINE_CANDIDATE_PRESSURE_JSON,
    DEFAULT_BASELINE_RUN_RESULT_JSON,
    DEFAULT_COMPANY_FIRST_REMEDIATION_JSON,
    DEFAULT_SOURCE_GAP_PROBE_JSON,
    run_guangzhou_stage4_9_remediation_replay,
)
from storage.guangzhou_stage4_source_gap_probe import (
    build_guangzhou_stage4_source_gap_probe,
)


GUANGZHOU_STAGE4_QUERY_QUALITY_SMOKE_KIND = "guangzhou_stage4_query_quality_smoke_v1_manifest"
GUANGZHOU_STAGE4_QUERY_QUALITY_SMOKE_VERSION = 1
GUANGZHOU_STAGE4_QUERY_QUALITY_SMOKE_ADAPTER_ID = "guangzhou-stage4-query-quality-smoke-v1-builder"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-stage4-query-quality-smoke-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
JsonGetter = Callable[[str, Mapping[str, str]], Mapping[str, Any]]
SearchRunner = Callable[[Mapping[str, Any]], dict[str, Any]]


def build_guangzhou_stage4_query_quality_smoke(
    *,
    baseline_run_result_json: str | Path = DEFAULT_BASELINE_RUN_RESULT_JSON,
    baseline_candidate_pressure_json: str | Path = DEFAULT_BASELINE_CANDIDATE_PRESSURE_JSON,
    company_first_remediation_json: str | Path = DEFAULT_COMPANY_FIRST_REMEDIATION_JSON,
    before_source_gap_probe_json: str | Path = DEFAULT_SOURCE_GAP_PROBE_JSON,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    candidate_limit: int = 10,
    detail_capture_limit: int = 10,
    attachment_capture_limit: int = 20,
    stage2_detail_capture_time_budget_seconds: float = 600,
    stage1_6_time_budget_seconds: float = 600,
    http_get_json: JsonGetter | None = None,
    search_runner: SearchRunner | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    source_gap_root = out_dir / "source-gap-probe-v1"
    replay_root = out_dir / "remediation-replay-v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    before_source_gap = _load_json(Path(before_source_gap_probe_json), blocking_reasons, "before_source_gap_probe_missing")
    source_gap_result = build_guangzhou_stage4_source_gap_probe(
        run_result_json=baseline_run_result_json,
        candidate_pressure_json=baseline_candidate_pressure_json,
        output_root=source_gap_root,
        http_get_json=http_get_json,
        created_at=created,
    )
    after_source_gap_path = source_gap_root / "stage4-source-gap-probe-v1.json"
    replay_result = run_guangzhou_stage4_9_remediation_replay(
        baseline_run_result_json=baseline_run_result_json,
        baseline_candidate_pressure_json=baseline_candidate_pressure_json,
        company_first_remediation_json=company_first_remediation_json,
        source_gap_probe_json=after_source_gap_path,
        output_root=replay_root,
        candidate_limit=candidate_limit,
        detail_capture_limit=detail_capture_limit,
        attachment_capture_limit=attachment_capture_limit,
        stage2_detail_capture_time_budget_seconds=stage2_detail_capture_time_budget_seconds,
        stage1_6_time_budget_seconds=stage1_6_time_budget_seconds,
        search_runner=search_runner,
        created_at=created,
    )
    delta_report = dict(replay_result.get("delta_report") or {})
    summary = _summary(
        before_source_gap=before_source_gap,
        after_source_gap=source_gap_result,
        delta_report=delta_report,
        blocking_reasons=[
            *blocking_reasons,
            *list(source_gap_result.get("blocking_reasons") or []),
            *list(replay_result.get("blocking_reasons") or []),
        ],
    )
    manifest = {
        "manifest_version": GUANGZHOU_STAGE4_QUERY_QUALITY_SMOKE_VERSION,
        "manifest_kind": GUANGZHOU_STAGE4_QUERY_QUALITY_SMOKE_KIND,
        "adapter_id": GUANGZHOU_STAGE4_QUERY_QUALITY_SMOKE_ADAPTER_ID,
        "pipeline_stage": "GuangzhouStage4QueryQualitySmokeV1",
        "manifest_id": f"GUANGZHOU-STAGE4-QUERY-QUALITY-{_fingerprint(summary)[:16]}",
        "created_at": created,
        "source_baseline_run_result_json": str(baseline_run_result_json),
        "source_baseline_candidate_pressure_json": str(baseline_candidate_pressure_json),
        "source_company_first_remediation_json": str(company_first_remediation_json),
        "source_before_source_gap_probe_json": str(before_source_gap_probe_json),
        "source_after_source_gap_probe_json": str(after_source_gap_path),
        "source_replay_output_root": str(replay_root),
        "summary": summary,
        "safety": {
            "network_enabled": True,
            "download_enabled": False,
            "parse_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_stage4_query_quality_smoke_mode": "BUILT" if not summary["blocking_reasons"] else "INPUT_BLOCKED",
        "safe_to_execute": not summary["blocking_reasons"],
        "blocking_reasons": summary["blocking_reasons"],
        "manifest": manifest,
        "summary": summary,
    }
    _apply_forbidden_term_scan(result)
    _write_json(out_dir / "query-quality-smoke-v1.json", result)
    _write_json(out_dir / "query-quality-smoke-summary.json", summary)
    return result


def _summary(
    *,
    before_source_gap: Mapping[str, Any],
    after_source_gap: Mapping[str, Any],
    delta_report: Mapping[str, Any],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    before_source_gap_summary = dict(before_source_gap.get("summary") or {})
    after_source_gap_summary = dict(after_source_gap.get("summary") or {})
    delta_summary = dict(delta_report.get("summary") or {})
    return {
        "project_code_resolution_failure_counts_before": _project_code_resolution_failure_counts(
            before_source_gap
        ),
        "project_code_resolution_failure_counts_after": _project_code_resolution_failure_counts(
            after_source_gap
        ),
        "same_company_person_directory_found_count": _as_int(
            after_source_gap_summary.get("same_company_person_directory_found_count")
        ),
        "company_first_identity_resolution_required_count_before_after": {
            "before": _as_int(delta_summary.get("company_first_identity_resolution_required_count_before")),
            "after": _as_int(delta_summary.get("company_first_identity_resolution_required_count_after")),
        },
        "responsible_role_gap_code_count_before_after": {
            "before": _as_int(delta_summary.get("responsible_role_gap_code_count_before")),
            "after": _as_int(delta_summary.get("responsible_role_gap_code_count_after")),
        },
        "stage5_evidence_gate_status_counts_before_after": {
            "before": dict(delta_summary.get("stage5_evidence_gate_status_counts_before") or {}),
            "after": dict(delta_summary.get("stage5_evidence_gate_status_counts_after") or {}),
        },
        "empty_result_source_type_counts_before_after": {
            "before": _source_type_counts(before_source_gap, "empty_result_candidate_count"),
            "after": _source_type_counts(after_source_gap, "empty_result_candidate_count"),
        },
        "query_error_source_type_counts_before_after": {
            "before": _source_type_counts(before_source_gap, "query_error_candidate_count"),
            "after": _source_type_counts(after_source_gap, "query_error_candidate_count"),
        },
        "source_gap_responsible_role_identity_completion_state_counts_after": dict(
            after_source_gap_summary.get("responsible_role_identity_completion_state_counts") or {}
        ),
        "source_gap_stage4_responsible_role_writeback_state_counts_after": dict(
            after_source_gap_summary.get("stage4_responsible_role_writeback_state_counts") or {}
        ),
        "blocking_reasons": _dedupe_strings(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _project_code_resolution_failure_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    summary_counts = dict(dict(payload.get("summary") or {}).get("project_code_resolution_failure_counts") or {})
    if summary_counts:
        return {str(key): _as_int(value) for key, value in sorted(summary_counts.items())}
    records = _candidate_records(payload)
    counts: dict[str, int] = {}
    for record in records:
        for reason in _string_list(record.get("project_code_resolution_failure_reasons")):
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _source_type_counts(payload: Mapping[str, Any], field_name: str) -> dict[str, int]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    records = list(payload.get("source_type_summary_records") or manifest.get("source_type_summary_records") or [])
    counts: dict[str, int] = {}
    for item in records:
        if not isinstance(item, Mapping):
            continue
        source_type = str(item.get("source_type") or "")
        value = _as_int(item.get(field_name))
        if source_type and value:
            counts[source_type] = value
    return dict(sorted(counts.items()))


def _candidate_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    records = list(payload.get("records") or manifest.get("candidate_records") or [])
    return [dict(item) for item in records if isinstance(item, Mapping)]


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _as_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _apply_forbidden_term_scan(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    target = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else payload
    if forbidden_hits:
        target["forbidden_term_scan_state"] = "FAIL"
        target["forbidden_term_hits"] = forbidden_hits
        payload["safe_to_execute"] = False
        payload["blocking_reasons"] = [
            *list(payload.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
    else:
        target["forbidden_term_scan_state"] = "PASS"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou Stage4 query quality smoke.")
    parser.add_argument("--baseline-run-result-json", default=str(DEFAULT_BASELINE_RUN_RESULT_JSON))
    parser.add_argument("--baseline-candidate-pressure-json", default=str(DEFAULT_BASELINE_CANDIDATE_PRESSURE_JSON))
    parser.add_argument("--company-first-remediation-json", default=str(DEFAULT_COMPANY_FIRST_REMEDIATION_JSON))
    parser.add_argument("--before-source-gap-probe-json", default=str(DEFAULT_SOURCE_GAP_PROBE_JSON))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--detail-capture-limit", type=int, default=10)
    parser.add_argument("--attachment-capture-limit", type=int, default=20)
    parser.add_argument("--stage2-detail-capture-time-budget-seconds", type=float, default=600)
    parser.add_argument("--stage1-6-time-budget-seconds", type=float, default=600)
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_stage4_query_quality_smoke(
        baseline_run_result_json=args.baseline_run_result_json,
        baseline_candidate_pressure_json=args.baseline_candidate_pressure_json,
        company_first_remediation_json=args.company_first_remediation_json,
        before_source_gap_probe_json=args.before_source_gap_probe_json,
        output_root=args.output_root,
        candidate_limit=args.candidate_limit,
        detail_capture_limit=args.detail_capture_limit,
        attachment_capture_limit=args.attachment_capture_limit,
        stage2_detail_capture_time_budget_seconds=args.stage2_detail_capture_time_budget_seconds,
        stage1_6_time_budget_seconds=args.stage1_6_time_budget_seconds,
    )
    print(json.dumps(result if args.emit_json else result.get("summary", {}), ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
