from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.evidence_orchestration_state_machine import build_evidence_orchestration_state
from storage.p13b_original_notice_backtrace import build_p13b_original_notice_backtrace


EVIDENCE_ORCHESTRATION_CONTINUATION_KIND = "evidence_orchestration_continuation_runner_v1_manifest"
EVIDENCE_ORCHESTRATION_CONTINUATION_VERSION = 1
EVIDENCE_ORCHESTRATION_CONTINUATION_ADAPTER_ID = "evidence-orchestration-continuation-runner-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/evidence-orchestration-continuation-run-v1")


def run_evidence_orchestration_continuation(
    *,
    stage16_storage_json: str | Path,
    company_first_stage4_inputs_json: str | Path | None = None,
    p13b_company_history_json: str | Path | None = None,
    p13b_company_history_root: str | Path | None = None,
    original_notice_backtrace_json: str | Path | None = None,
    original_notice_backtrace_root: str | Path | None = None,
    ygp_readback_root: str | Path | None = None,
    ygp_readback_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_original_notice_backtrace: bool = False,
    max_live_original_notices: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    state_before_root = out_dir / "00-evidence-state-before"
    original_out_root = out_dir / "01-original-notice-backtrace"
    state_after_root = out_dir / "02-evidence-state-after"
    out_dir.mkdir(parents=True, exist_ok=True)

    state_before = build_evidence_orchestration_state(
        stage16_storage_json=stage16_storage_json,
        company_first_stage4_inputs_json=company_first_stage4_inputs_json,
        p13b_company_history_json=p13b_company_history_json,
        p13b_company_history_root=p13b_company_history_root,
        original_notice_backtrace_json=original_notice_backtrace_json,
        original_notice_backtrace_root=original_notice_backtrace_root,
        output_root=state_before_root,
        project_ids=project_ids,
        created_at=created,
    )
    before_summary = _summary(state_before)
    backtrace_required_count = int(before_summary.get("original_backtrace_required_project_count") or 0)
    original_result: dict[str, Any] = {}
    original_source_json = original_notice_backtrace_json
    original_source_root = original_notice_backtrace_root
    original_action_state = "SKIPPED"
    original_skip_reason = ""

    if original_notice_backtrace_json or original_notice_backtrace_root:
        original_action_state = "EXISTING_ORIGINAL_BACKTRACE_CONSUMED"
        original_skip_reason = "existing_original_notice_backtrace_input_supplied"
    elif backtrace_required_count <= 0:
        original_action_state = "SKIPPED_NO_BACKTRACE_REQUIRED"
        original_skip_reason = "state_before_has_no_p13b_original_backtrace_required_project"
    elif not p13b_company_history_json and not p13b_company_history_root:
        original_action_state = "SKIPPED_P13B_INPUT_MISSING"
        original_skip_reason = "p13b_company_history_input_missing"
    else:
        original_result = build_p13b_original_notice_backtrace(
            input_json=p13b_company_history_json,
            company_history_triage_root=p13b_company_history_root,
            output_root=original_out_root,
            ygp_readback_root=ygp_readback_root,
            ygp_readback_json=ygp_readback_json,
            enable_live_public_query=enable_live_original_notice_backtrace,
            max_live_original_notices=max_live_original_notices,
            created_at=created,
        )
        original_source_root = original_out_root
        original_action_state = (
            "ORIGINAL_BACKTRACE_LIVE_ATTEMPTED"
            if enable_live_original_notice_backtrace
            else "ORIGINAL_BACKTRACE_PLAN_BUILT"
        )

    state_after = build_evidence_orchestration_state(
        stage16_storage_json=stage16_storage_json,
        company_first_stage4_inputs_json=company_first_stage4_inputs_json,
        p13b_company_history_json=p13b_company_history_json,
        p13b_company_history_root=p13b_company_history_root,
        original_notice_backtrace_json=original_source_json,
        original_notice_backtrace_root=original_source_root,
        output_root=state_after_root,
        project_ids=project_ids,
        created_at=created,
    )

    summary = _run_summary(
        state_before=state_before,
        original_result=original_result,
        state_after=state_after,
        original_action_state=original_action_state,
        original_skip_reason=original_skip_reason,
    )
    manifest = {
        "manifest_version": EVIDENCE_ORCHESTRATION_CONTINUATION_VERSION,
        "manifest_kind": EVIDENCE_ORCHESTRATION_CONTINUATION_KIND,
        "adapter_id": EVIDENCE_ORCHESTRATION_CONTINUATION_ADAPTER_ID,
        "pipeline_stage": "EvidenceOrchestrationContinuationRunnerV1",
        "manifest_id": f"EVIDENCE-ORCH-RUN-{_fingerprint({'summary': summary})[:16]}",
        "created_at": created,
        "source_stage16_storage_json": str(stage16_storage_json),
        "source_company_first_stage4_inputs_json": str(company_first_stage4_inputs_json or ""),
        "source_p13b_company_history_json": str(p13b_company_history_json or ""),
        "source_p13b_company_history_root": str(p13b_company_history_root or ""),
        "source_original_notice_backtrace_json": str(original_notice_backtrace_json or ""),
        "source_original_notice_backtrace_root": str(original_notice_backtrace_root or ""),
        "state_before_root": str(state_before_root),
        "original_notice_backtrace_root": str(original_source_root or ""),
        "state_after_root": str(state_after_root),
        "state_before_summary": _summary(state_before),
        "original_notice_backtrace_summary": _summary(original_result),
        "state_after_summary": _summary(state_after),
        "summary": summary,
        "safety": {
            "network_enabled": bool(enable_live_original_notice_backtrace),
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "stage7_to_stage9_live_execution_enabled": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "evidence_orchestration_continuation_mode": "BUILT",
        "safe_to_execute": bool(state_before.get("safe_to_execute")) and bool(state_after.get("safe_to_execute"))
        and (not original_result or bool(original_result.get("safe_to_execute"))),
        "blocking_reasons": [
            *_list(state_before.get("blocking_reasons")),
            *_list(original_result.get("blocking_reasons")),
            *_list(state_after.get("blocking_reasons")),
        ],
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "evidence-orchestration-continuation-run-v1.json", result)
    return result


def _run_summary(
    *,
    state_before: Mapping[str, Any],
    original_result: Mapping[str, Any],
    state_after: Mapping[str, Any],
    original_action_state: str,
    original_skip_reason: str,
) -> dict[str, Any]:
    before = _summary(state_before)
    original = _summary(original_result)
    after = _summary(state_after)
    return {
        "state_before_project_count": int(before.get("project_count") or 0),
        "state_before_evidence_state_counts": dict(before.get("evidence_state_counts") or {}),
        "original_action_state": original_action_state,
        "original_skip_reason": original_skip_reason,
        "original_notice_task_count": int(original.get("original_notice_task_count") or 0),
        "original_notice_live_processed_count": int(original.get("live_processed_count") or 0),
        "original_notice_overlap_signal_review_required_count": int(
            original.get("original_notice_overlap_signal_review_required_count") or 0
        ),
        "state_after_project_count": int(after.get("project_count") or 0),
        "state_after_evidence_state_counts": dict(after.get("evidence_state_counts") or {}),
        "state_after_a_strong_signal_project_count": int(after.get("a_strong_signal_project_count") or 0),
        "state_after_original_backtrace_required_project_count": int(
            after.get("original_backtrace_required_project_count") or 0
        ),
        "state_after_adapter_job_count": int(after.get("adapter_job_count") or 0),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(result: Mapping[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result, Mapping) else {}
    return dict(summary) if isinstance(summary, Mapping) else {}


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
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run evidence orchestration continuation with optional original notice backtrace.")
    parser.add_argument("--stage16-storage-json", required=True)
    parser.add_argument("--company-first-stage4-inputs-json", default="")
    parser.add_argument("--p13b-company-history-json", default="")
    parser.add_argument("--p13b-company-history-root", default="")
    parser.add_argument("--original-notice-backtrace-json", default="")
    parser.add_argument("--original-notice-backtrace-root", default="")
    parser.add_argument("--ygp-readback-root", default="")
    parser.add_argument("--ygp-readback-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-original-notice-backtrace", action="store_true")
    parser.add_argument("--max-live-original-notices", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_evidence_orchestration_continuation(
        stage16_storage_json=args.stage16_storage_json,
        company_first_stage4_inputs_json=args.company_first_stage4_inputs_json or None,
        p13b_company_history_json=args.p13b_company_history_json or None,
        p13b_company_history_root=args.p13b_company_history_root or None,
        original_notice_backtrace_json=args.original_notice_backtrace_json or None,
        original_notice_backtrace_root=args.original_notice_backtrace_root or None,
        ygp_readback_root=args.ygp_readback_root or None,
        ygp_readback_json=args.ygp_readback_json or None,
        output_root=args.output_root,
        enable_live_original_notice_backtrace=bool(args.enable_live_original_notice_backtrace),
        max_live_original_notices=args.max_live_original_notices,
        project_ids=_parse_csv(args.project_ids),
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVIDENCE_ORCHESTRATION_CONTINUATION_KIND",
    "run_evidence_orchestration_continuation",
]
