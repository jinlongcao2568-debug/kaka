from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from shared.utils import utc_now_iso
from storage.evidence_stage6_fact_package import build_evidence_stage6_fact_package
from storage.stage6_review_action_dispatch import build_stage6_review_action_dispatch
from storage.stage6_review_action_dispatch_runner import run_stage6_review_action_dispatch_runner


STAGE6_REVIEW_CYCLE_RUNNER_KIND = "stage6_review_cycle_runner_v1_manifest"
STAGE6_REVIEW_CYCLE_RUNNER_VERSION = 1
STAGE6_REVIEW_CYCLE_RUNNER_ADAPTER_ID = "stage6-review-cycle-runner-v1"

DEFAULT_BATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-cycle-runner-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

CommandExecutor = Callable[[list[str], Path], Mapping[str, Any]]


def run_stage6_review_cycle_runner(
    *,
    batch_closeout_json: str | Path | None = None,
    batch_closeout_root: str | Path = DEFAULT_BATCH_CLOSEOUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute_dispatch: bool = False,
    dispatch_max_groups: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    baseline_evidence_state_json: str | Path | None = None,
    cwd: str | Path | None = None,
    created_at: str | None = None,
    command_executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    stage6_root = out_dir / "1"
    dispatch_root = out_dir / "2"
    dispatch_runner_root = out_dir / "3"
    out_dir.mkdir(parents=True, exist_ok=True)

    stage6_result = build_evidence_stage6_fact_package(
        batch_closeout_json=batch_closeout_json,
        batch_closeout_root=batch_closeout_root,
        output_root=stage6_root,
        created_at=created,
    )
    dispatch_result: dict[str, Any] = {}
    dispatch_runner_result: dict[str, Any] = {}
    blocking_reasons: list[str] = [*_list(stage6_result.get("blocking_reasons"))]

    if bool(stage6_result.get("safe_to_execute")):
        dispatch_result = build_stage6_review_action_dispatch(
            stage6_fact_package_root=stage6_root,
            output_root=dispatch_root,
            created_at=created,
        )
        blocking_reasons.extend(_list(dispatch_result.get("blocking_reasons")))
    else:
        blocking_reasons.append("stage6_fact_package_not_safe_to_dispatch")

    if dispatch_result and bool(dispatch_result.get("safe_to_execute")):
        dispatch_runner_result = run_stage6_review_action_dispatch_runner(
            dispatch_root=dispatch_root,
            baseline_evidence_state_json=baseline_evidence_state_json,
            output_root=dispatch_runner_root,
            execute_commands=execute_dispatch,
            max_groups=dispatch_max_groups,
            project_ids=project_ids,
            cwd=cwd,
            created_at=created,
            command_executor=command_executor,
        )
        blocking_reasons.extend(_list(dispatch_runner_result.get("blocking_reasons")))
    elif dispatch_result:
        blocking_reasons.append("stage6_dispatch_not_safe_to_run")

    summary = _summary(
        stage6_result=stage6_result,
        dispatch_result=dispatch_result,
        dispatch_runner_result=dispatch_runner_result,
        blocking_reasons=blocking_reasons,
        execute_dispatch=execute_dispatch,
    )
    batch_closeout_path = (
        Path(batch_closeout_json)
        if batch_closeout_json
        else Path(batch_closeout_root) / "evidence-batch-closeout-v1.json"
    )
    manifest = {
        "manifest_version": STAGE6_REVIEW_CYCLE_RUNNER_VERSION,
        "manifest_kind": STAGE6_REVIEW_CYCLE_RUNNER_KIND,
        "adapter_id": STAGE6_REVIEW_CYCLE_RUNNER_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewCycleRunnerV1",
        "manifest_id": f"STAGE6-REVIEW-CYCLE-RUNNER-{_fingerprint({'summary': summary})[:16]}",
        "created_at": created,
        "source_batch_closeout_json": str(batch_closeout_path),
        "stage6_fact_package_root": str(stage6_root),
        "stage6_fact_package_json": str(stage6_root / "stage6-fact-package-v1.json"),
        "stage6_dispatch_root": str(dispatch_root),
        "stage6_dispatch_json": str(dispatch_root / "stage6-review-action-dispatch-v1.json"),
        "stage6_dispatch_runner_root": str(dispatch_runner_root),
        "stage6_dispatch_runner_json": str(dispatch_runner_root / "stage6-review-action-dispatch-runner-v1.json"),
        "execute_dispatch": bool(execute_dispatch),
        "dispatch_max_groups": dispatch_max_groups,
        "project_ids": list(project_ids),
        "source_manifest_ids": {
            "stage6_fact_package": _manifest_id(stage6_result),
            "stage6_dispatch": _manifest_id(dispatch_result),
            "stage6_dispatch_runner": _manifest_id(dispatch_runner_result),
        },
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "stage7_to_stage9_live_execution_enabled": False,
            "dispatch_execution_enabled": bool(execute_dispatch),
            "dispatch_execution_is_internal_allowlisted": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage6_review_cycle_runner_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED_OR_PARTIAL",
        "safe_to_execute": _safe(stage6_result) and _safe(dispatch_result) and _safe(dispatch_runner_result)
        and not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result)
    return result


def _summary(
    *,
    stage6_result: Mapping[str, Any],
    dispatch_result: Mapping[str, Any],
    dispatch_runner_result: Mapping[str, Any],
    blocking_reasons: list[str],
    execute_dispatch: bool,
) -> dict[str, Any]:
    stage6_summary = _result_summary(stage6_result)
    dispatch_summary = _result_summary(dispatch_result)
    dispatch_runner_summary = _result_summary(dispatch_runner_result)
    return {
        "stage6_review_cycle_runner_state": (
            "STAGE6_REVIEW_CYCLE_READY" if not blocking_reasons else "STAGE6_REVIEW_CYCLE_PARTIAL_OR_BLOCKED"
        ),
        "execution_mode": "CONTROLLED_INTERNAL_DISPATCH_EXECUTION" if execute_dispatch else "DRY_RUN_DISPATCH_NOT_EXECUTED",
        "stage6_fact_package_safe": _safe(stage6_result),
        "stage6_dispatch_safe": _safe(dispatch_result),
        "stage6_dispatch_runner_safe": _safe(dispatch_runner_result),
        "stage6_input_closeout_project_count": int(stage6_summary.get("input_closeout_project_count") or 0),
        "stage6_project_fact_count": int(stage6_summary.get("project_fact_count") or 0),
        "stage6_review_action_plan_count": int(stage6_summary.get("review_action_plan_count") or 0),
        "stage6_review_action_family_counts": dict(stage6_summary.get("review_action_family_counts") or {}),
        "dispatch_task_count": int(dispatch_summary.get("dispatch_task_count") or 0),
        "dispatch_task_type_counts": dict(dispatch_summary.get("dispatch_task_type_counts") or {}),
        "dispatch_runner_group_count": int(dispatch_runner_summary.get("dispatch_runner_group_count") or 0),
        "dispatch_runner_group_execution_state_counts": dict(
            dispatch_runner_summary.get("group_execution_state_counts") or {}
        ),
        "dispatch_runner_dry_run_ready_group_count": int(dispatch_runner_summary.get("dry_run_ready_group_count") or 0),
        "dispatch_runner_executed_success_group_count": int(
            dispatch_runner_summary.get("executed_success_group_count") or 0
        ),
        "dispatch_runner_executed_failed_group_count": int(
            dispatch_runner_summary.get("executed_failed_group_count") or 0
        ),
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "blocking_reasons": list(blocking_reasons),
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(out_dir: Path, result: dict[str, Any]) -> None:
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
    _write_json(out_dir / "stage6-review-cycle-runner-v1.json", result)


def _result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result, Mapping) else {}
    return dict(summary) if isinstance(summary, Mapping) else {}


def _manifest_id(result: Mapping[str, Any]) -> str:
    manifest = result.get("manifest") if isinstance(result, Mapping) else {}
    return str(manifest.get("manifest_id") or "") if isinstance(manifest, Mapping) else ""


def _safe(result: Mapping[str, Any]) -> bool:
    if not result:
        return False
    return bool(result.get("safe_to_execute"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the next Stage6 review cycle from EvidenceBatchCloseout v1.")
    parser.add_argument("--batch-closeout-json", default="")
    parser.add_argument("--batch-closeout-root", default=str(DEFAULT_BATCH_CLOSEOUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute-dispatch", action="store_true")
    parser.add_argument("--dispatch-max-groups", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--baseline-evidence-state-json", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_stage6_review_cycle_runner(
        batch_closeout_json=args.batch_closeout_json or None,
        batch_closeout_root=args.batch_closeout_root,
        output_root=args.output_root,
        execute_dispatch=bool(args.execute_dispatch),
        dispatch_max_groups=args.dispatch_max_groups,
        project_ids=_parse_csv(args.project_ids),
        baseline_evidence_state_json=args.baseline_evidence_state_json or None,
        cwd=args.cwd or None,
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
    "STAGE6_REVIEW_CYCLE_RUNNER_KIND",
    "run_stage6_review_cycle_runner",
]
