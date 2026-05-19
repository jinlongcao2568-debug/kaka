from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.design_survey_public_registry_fallback import build_design_survey_public_registry_fallback
from storage.design_survey_public_registry_readback import build_design_survey_public_registry_readback
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
    browser_readback_root: str | Path | None = None,
    browser_readback_json: str | Path | None = None,
    design_survey_adapter_plan_json: str | Path | None = None,
    design_survey_adapter_plan_root: str | Path | None = None,
    design_survey_stage4_execution_json: str | Path | None = None,
    design_survey_stage4_execution_root: str | Path | None = None,
    design_survey_flow08_readback_json: str | Path | None = None,
    design_survey_flow08_readback_root: str | Path | None = None,
    design_survey_flow08_attachment_parse_json: str | Path | None = None,
    design_survey_flow08_attachment_parse_root: str | Path | None = None,
    design_survey_public_registry_fallback_json: str | Path | None = None,
    design_survey_public_registry_fallback_root: str | Path | None = None,
    design_survey_public_registry_readback_json: str | Path | None = None,
    design_survey_public_registry_readback_root: str | Path | None = None,
    public_registry_snapshot_html_path: str | Path | None = None,
    public_registry_snapshot_html_root: str | Path | None = None,
    public_registry_snapshot_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_original_notice_backtrace: bool = False,
    execute_live_public_registry_entry_readback: bool = False,
    max_live_original_notices: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    state_before_root = out_dir / "00-evidence-state-before"
    original_out_root = out_dir / "01-original-notice-backtrace"
    public_registry_fallback_out_root = out_dir / "01b-design-survey-public-registry-fallback"
    public_registry_readback_out_root = out_dir / "01c-design-survey-public-registry-readback"
    state_after_root = out_dir / "02-evidence-state-after"
    out_dir.mkdir(parents=True, exist_ok=True)

    state_before = build_evidence_orchestration_state(
        stage16_storage_json=stage16_storage_json,
        company_first_stage4_inputs_json=company_first_stage4_inputs_json,
        p13b_company_history_json=p13b_company_history_json,
        p13b_company_history_root=p13b_company_history_root,
        original_notice_backtrace_json=original_notice_backtrace_json,
        original_notice_backtrace_root=original_notice_backtrace_root,
        design_survey_adapter_plan_json=design_survey_adapter_plan_json,
        design_survey_adapter_plan_root=design_survey_adapter_plan_root,
        design_survey_stage4_execution_json=design_survey_stage4_execution_json,
        design_survey_stage4_execution_root=design_survey_stage4_execution_root,
        design_survey_flow08_readback_json=design_survey_flow08_readback_json,
        design_survey_flow08_readback_root=design_survey_flow08_readback_root,
        design_survey_flow08_attachment_parse_json=design_survey_flow08_attachment_parse_json,
        design_survey_flow08_attachment_parse_root=design_survey_flow08_attachment_parse_root,
        design_survey_public_registry_fallback_json=design_survey_public_registry_fallback_json,
        design_survey_public_registry_fallback_root=design_survey_public_registry_fallback_root,
        design_survey_public_registry_readback_json=design_survey_public_registry_readback_json,
        design_survey_public_registry_readback_root=design_survey_public_registry_readback_root,
        output_root=state_before_root,
        project_ids=project_ids,
        created_at=created,
    )
    before_summary = _summary(state_before)
    original_project_ids = list(project_ids) or _project_ids_for_states(
        state_before,
        {"P13B_ORIGINAL_BACKTRACE_REQUIRED"},
    )
    public_registry_project_ids = list(project_ids) or _project_ids_for_states(
        state_before,
        {
            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
            "DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY",
        },
    )
    backtrace_required_count = int(before_summary.get("original_backtrace_required_project_count") or 0)
    original_live_notice_limit = max_live_original_notices
    if enable_live_original_notice_backtrace and original_live_notice_limit is None:
        original_live_notice_limit = 3
    original_result: dict[str, Any] = {}
    original_source_json = original_notice_backtrace_json
    original_source_root = original_notice_backtrace_root
    original_action_state = "SKIPPED"
    original_skip_reason = ""

    if backtrace_required_count <= 0:
        if original_notice_backtrace_json or original_notice_backtrace_root:
            original_action_state = "EXISTING_ORIGINAL_BACKTRACE_CONSUMED"
            original_skip_reason = "existing_original_notice_backtrace_input_supplied"
        else:
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
            browser_readback_root=browser_readback_root,
            browser_readback_json=browser_readback_json,
            enable_live_public_query=enable_live_original_notice_backtrace,
            max_live_original_notices=original_live_notice_limit,
            project_ids=original_project_ids,
            created_at=created,
        )
        original_source_json, original_source_root = _merge_original_backtrace_sources(
            existing_json=original_notice_backtrace_json,
            existing_root=original_notice_backtrace_root,
            generated_root=original_out_root,
        )
        original_action_state = (
            "ORIGINAL_BACKTRACE_LIVE_ATTEMPTED"
            if enable_live_original_notice_backtrace
            else "ORIGINAL_BACKTRACE_CONTINUED_WITH_EXISTING_INPUT"
            if original_notice_backtrace_json or original_notice_backtrace_root
            else "ORIGINAL_BACKTRACE_PLAN_BUILT"
        )

    public_registry_fallback_result: dict[str, Any] = {}
    public_registry_readback_result: dict[str, Any] = {}
    public_registry_fallback_source_json = design_survey_public_registry_fallback_json
    public_registry_fallback_source_root = design_survey_public_registry_fallback_root
    public_registry_readback_source_json = design_survey_public_registry_readback_json
    public_registry_readback_source_root = design_survey_public_registry_readback_root
    public_registry_fallback_action_state = "SKIPPED"
    public_registry_fallback_skip_reason = ""
    public_registry_readback_action_state = "SKIPPED"
    public_registry_readback_skip_reason = ""
    before_states = dict(before_summary.get("evidence_state_counts") or {})
    public_registry_fallback_required_count = int(
        before_states.get("DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED") or 0
    )
    public_registry_tasks_ready_count = int(before_states.get("DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY") or 0)

    if design_survey_public_registry_fallback_json or design_survey_public_registry_fallback_root:
        public_registry_fallback_action_state = "EXISTING_PUBLIC_REGISTRY_FALLBACK_CONSUMED"
        public_registry_fallback_skip_reason = "existing_public_registry_fallback_input_supplied"
    elif public_registry_fallback_required_count > 0:
        if design_survey_stage4_execution_json or design_survey_stage4_execution_root:
            public_registry_fallback_result = build_design_survey_public_registry_fallback(
                design_survey_stage4_execution_json=design_survey_stage4_execution_json,
                design_survey_stage4_execution_root=design_survey_stage4_execution_root,
                flow08_attachment_parse_json=design_survey_flow08_attachment_parse_json,
                flow08_attachment_parse_root=design_survey_flow08_attachment_parse_root,
                output_root=public_registry_fallback_out_root,
                project_ids=public_registry_project_ids,
                created_at=created,
            )
            public_registry_fallback_source_root = public_registry_fallback_out_root
            public_registry_fallback_action_state = "PUBLIC_REGISTRY_FALLBACK_BUILT"
            public_registry_tasks_ready_count = max(public_registry_tasks_ready_count, 1)
        else:
            public_registry_fallback_action_state = "SKIPPED_PUBLIC_REGISTRY_STAGE4_INPUT_MISSING"
            public_registry_fallback_skip_reason = "design_survey_stage4_execution_input_missing"
    else:
        public_registry_fallback_action_state = "SKIPPED_NO_PUBLIC_REGISTRY_FALLBACK_REQUIRED"
        public_registry_fallback_skip_reason = "state_before_has_no_design_survey_public_registry_fallback_required_project"

    if design_survey_public_registry_readback_json or design_survey_public_registry_readback_root:
        public_registry_readback_action_state = "EXISTING_PUBLIC_REGISTRY_READBACK_CONSUMED"
        public_registry_readback_skip_reason = "existing_public_registry_readback_input_supplied"
    elif public_registry_tasks_ready_count <= 0 and not public_registry_fallback_result:
        public_registry_readback_action_state = "SKIPPED_NO_PUBLIC_REGISTRY_TASKS_READY"
        public_registry_readback_skip_reason = "state_before_has_no_design_survey_public_registry_tasks_ready_project"
    elif not public_registry_fallback_source_json and not public_registry_fallback_source_root:
        public_registry_readback_action_state = "SKIPPED_PUBLIC_REGISTRY_FALLBACK_INPUT_MISSING"
        public_registry_readback_skip_reason = "public_registry_fallback_input_missing"
    else:
        public_registry_readback_result = build_design_survey_public_registry_readback(
            public_registry_fallback_json=public_registry_fallback_source_json,
            public_registry_fallback_root=public_registry_fallback_source_root,
            snapshot_html_path=public_registry_snapshot_html_path,
            snapshot_html_root=public_registry_snapshot_html_root,
            snapshot_json=public_registry_snapshot_json,
            execute_live_entry_readback=execute_live_public_registry_entry_readback,
            output_root=public_registry_readback_out_root,
            project_ids=public_registry_project_ids,
            created_at=created,
        )
        public_registry_readback_source_root = public_registry_readback_out_root
        public_registry_readback_action_state = (
            "PUBLIC_REGISTRY_ENTRY_LIVE_READBACK_ATTEMPTED"
            if execute_live_public_registry_entry_readback
            else "PUBLIC_REGISTRY_READBACK_EXECUTED"
        )

    state_after = build_evidence_orchestration_state(
        stage16_storage_json=stage16_storage_json,
        company_first_stage4_inputs_json=company_first_stage4_inputs_json,
        p13b_company_history_json=p13b_company_history_json,
        p13b_company_history_root=p13b_company_history_root,
        original_notice_backtrace_json=original_source_json,
        original_notice_backtrace_root=original_source_root,
        design_survey_adapter_plan_json=design_survey_adapter_plan_json,
        design_survey_adapter_plan_root=design_survey_adapter_plan_root,
        design_survey_stage4_execution_json=design_survey_stage4_execution_json,
        design_survey_stage4_execution_root=design_survey_stage4_execution_root,
        design_survey_flow08_readback_json=design_survey_flow08_readback_json,
        design_survey_flow08_readback_root=design_survey_flow08_readback_root,
        design_survey_flow08_attachment_parse_json=design_survey_flow08_attachment_parse_json,
        design_survey_flow08_attachment_parse_root=design_survey_flow08_attachment_parse_root,
        design_survey_public_registry_fallback_json=public_registry_fallback_source_json,
        design_survey_public_registry_fallback_root=public_registry_fallback_source_root,
        design_survey_public_registry_readback_json=public_registry_readback_source_json,
        design_survey_public_registry_readback_root=public_registry_readback_source_root,
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
        public_registry_fallback_result=public_registry_fallback_result,
        public_registry_readback_result=public_registry_readback_result,
        public_registry_fallback_action_state=public_registry_fallback_action_state,
        public_registry_fallback_skip_reason=public_registry_fallback_skip_reason,
        public_registry_readback_action_state=public_registry_readback_action_state,
        public_registry_readback_skip_reason=public_registry_readback_skip_reason,
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
        "source_ygp_readback_root": str(ygp_readback_root or ""),
        "source_ygp_readback_json": str(ygp_readback_json or ""),
        "source_browser_readback_root": str(browser_readback_root or ""),
        "source_browser_readback_json": str(browser_readback_json or ""),
        "source_design_survey_adapter_plan_json": str(design_survey_adapter_plan_json or ""),
        "source_design_survey_adapter_plan_root": str(design_survey_adapter_plan_root or ""),
        "source_design_survey_stage4_execution_json": str(design_survey_stage4_execution_json or ""),
        "source_design_survey_stage4_execution_root": str(design_survey_stage4_execution_root or ""),
        "source_design_survey_flow08_readback_json": str(design_survey_flow08_readback_json or ""),
        "source_design_survey_flow08_readback_root": str(design_survey_flow08_readback_root or ""),
        "source_design_survey_flow08_attachment_parse_json": str(design_survey_flow08_attachment_parse_json or ""),
        "source_design_survey_flow08_attachment_parse_root": str(design_survey_flow08_attachment_parse_root or ""),
        "source_design_survey_public_registry_fallback_json": str(design_survey_public_registry_fallback_json or ""),
        "source_design_survey_public_registry_fallback_root": str(design_survey_public_registry_fallback_root or ""),
        "source_design_survey_public_registry_readback_json": str(design_survey_public_registry_readback_json or ""),
        "source_design_survey_public_registry_readback_root": str(design_survey_public_registry_readback_root or ""),
        "source_public_registry_snapshot_html_path": str(public_registry_snapshot_html_path or ""),
        "source_public_registry_snapshot_html_root": str(public_registry_snapshot_html_root or ""),
        "source_public_registry_snapshot_json": str(public_registry_snapshot_json or ""),
        "state_before_root": str(state_before_root),
        "original_notice_backtrace_json": str(original_source_json or ""),
        "original_notice_backtrace_root": str(original_source_root or ""),
        "design_survey_public_registry_fallback_root": str(public_registry_fallback_source_root or ""),
        "design_survey_public_registry_readback_root": str(public_registry_readback_source_root or ""),
        "state_after_root": str(state_after_root),
        "state_before_summary": _summary(state_before),
        "original_notice_backtrace_summary": _summary(original_result),
        "design_survey_public_registry_fallback_summary": _summary(public_registry_fallback_result),
        "design_survey_public_registry_readback_summary": _summary(public_registry_readback_result),
        "state_after_summary": _summary(state_after),
        "summary": summary,
        "safety": {
            "network_enabled": bool(enable_live_original_notice_backtrace or execute_live_public_registry_entry_readback),
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": bool(execute_live_public_registry_entry_readback),
            "public_registry_live_entry_readback_enabled": bool(execute_live_public_registry_entry_readback),
            "default_live_original_notice_budget": original_live_notice_limit
            if enable_live_original_notice_backtrace
            else 0,
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
        and (not original_result or bool(original_result.get("safe_to_execute")))
        and (not public_registry_fallback_result or bool(public_registry_fallback_result.get("safe_to_execute")))
        and (not public_registry_readback_result or bool(public_registry_readback_result.get("safe_to_execute"))),
        "blocking_reasons": [
            *_list(state_before.get("blocking_reasons")),
            *_list(original_result.get("blocking_reasons")),
            *_list(public_registry_fallback_result.get("blocking_reasons")),
            *_list(public_registry_readback_result.get("blocking_reasons")),
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
    public_registry_fallback_result: Mapping[str, Any],
    public_registry_readback_result: Mapping[str, Any],
    state_after: Mapping[str, Any],
    original_action_state: str,
    original_skip_reason: str,
    public_registry_fallback_action_state: str,
    public_registry_fallback_skip_reason: str,
    public_registry_readback_action_state: str,
    public_registry_readback_skip_reason: str,
) -> dict[str, Any]:
    before = _summary(state_before)
    original = _summary(original_result)
    public_registry_fallback = _summary(public_registry_fallback_result)
    public_registry_readback = _summary(public_registry_readback_result)
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
        "public_registry_fallback_action_state": public_registry_fallback_action_state,
        "public_registry_fallback_skip_reason": public_registry_fallback_skip_reason,
        "public_registry_fallback_target_record_count": int(public_registry_fallback.get("target_record_count") or 0),
        "public_registry_fallback_task_count": int(public_registry_fallback.get("task_count") or 0),
        "public_registry_readback_action_state": public_registry_readback_action_state,
        "public_registry_readback_skip_reason": public_registry_readback_skip_reason,
        "public_registry_readback_record_count": int(public_registry_readback.get("readback_record_count") or 0),
        "public_registry_readback_matched_count": int(public_registry_readback.get("matched_count") or 0),
        "public_registry_readback_snapshot_supplied_count": int(
            public_registry_readback.get("snapshot_supplied_count") or 0
        ),
        "public_registry_readback_provider_result_state_counts": dict(
            public_registry_readback.get("provider_result_state_counts") or {}
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


def _project_ids_for_states(result: Mapping[str, Any], states: set[str]) -> list[str]:
    manifest = result.get("manifest") if isinstance(result.get("manifest"), Mapping) else {}
    table = manifest.get("evidence_state_table") if isinstance(manifest.get("evidence_state_table"), Mapping) else {}
    records = table.get("records") if isinstance(table.get("records"), list) else []
    project_ids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if str(record.get("evidence_state") or "") not in states:
            continue
        project_id = str(record.get("project_id") or "").strip()
        if project_id and project_id not in project_ids:
            project_ids.append(project_id)
    return project_ids


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_original_backtrace_sources(
    *,
    existing_json: str | Path | None,
    existing_root: str | Path | None,
    generated_root: Path,
) -> tuple[str | Path | None, str | Path | None]:
    generated_json = generated_root / "original-notice-backtrace-v1.json"
    if existing_json:
        return f"{existing_json};{generated_json}", None
    if existing_root:
        return None, f"{existing_root};{generated_root}"
    return None, generated_root


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
    parser.add_argument("--browser-readback-root", default="")
    parser.add_argument("--browser-readback-json", default="")
    parser.add_argument("--design-survey-adapter-plan-json", default="")
    parser.add_argument("--design-survey-adapter-plan-root", default="")
    parser.add_argument("--design-survey-stage4-execution-json", default="")
    parser.add_argument("--design-survey-stage4-execution-root", default="")
    parser.add_argument("--design-survey-flow08-readback-json", default="")
    parser.add_argument("--design-survey-flow08-readback-root", default="")
    parser.add_argument("--design-survey-flow08-attachment-parse-json", default="")
    parser.add_argument("--design-survey-flow08-attachment-parse-root", default="")
    parser.add_argument("--design-survey-public-registry-fallback-json", default="")
    parser.add_argument("--design-survey-public-registry-fallback-root", default="")
    parser.add_argument("--design-survey-public-registry-readback-json", default="")
    parser.add_argument("--design-survey-public-registry-readback-root", default="")
    parser.add_argument("--public-registry-snapshot-html-path", default="")
    parser.add_argument("--public-registry-snapshot-html-root", default="")
    parser.add_argument("--public-registry-snapshot-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-original-notice-backtrace", action="store_true")
    parser.add_argument("--execute-live-public-registry-entry-readback", action="store_true")
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
        browser_readback_root=args.browser_readback_root or None,
        browser_readback_json=args.browser_readback_json or None,
        design_survey_adapter_plan_json=args.design_survey_adapter_plan_json or None,
        design_survey_adapter_plan_root=args.design_survey_adapter_plan_root or None,
        design_survey_stage4_execution_json=args.design_survey_stage4_execution_json or None,
        design_survey_stage4_execution_root=args.design_survey_stage4_execution_root or None,
        design_survey_flow08_readback_json=args.design_survey_flow08_readback_json or None,
        design_survey_flow08_readback_root=args.design_survey_flow08_readback_root or None,
        design_survey_flow08_attachment_parse_json=args.design_survey_flow08_attachment_parse_json or None,
        design_survey_flow08_attachment_parse_root=args.design_survey_flow08_attachment_parse_root or None,
        design_survey_public_registry_fallback_json=args.design_survey_public_registry_fallback_json or None,
        design_survey_public_registry_fallback_root=args.design_survey_public_registry_fallback_root or None,
        design_survey_public_registry_readback_json=args.design_survey_public_registry_readback_json or None,
        design_survey_public_registry_readback_root=args.design_survey_public_registry_readback_root or None,
        public_registry_snapshot_html_path=args.public_registry_snapshot_html_path or None,
        public_registry_snapshot_html_root=args.public_registry_snapshot_html_root or None,
        public_registry_snapshot_json=args.public_registry_snapshot_json or None,
        output_root=args.output_root,
        enable_live_original_notice_backtrace=bool(args.enable_live_original_notice_backtrace),
        execute_live_public_registry_entry_readback=bool(args.execute_live_public_registry_entry_readback),
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
