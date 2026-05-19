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
from storage.p13b_original_backtrace_continuation_controller import (
    build_p13b_original_backtrace_continuation_controller,
)
from storage.p13b_original_notice_backtrace import build_p13b_original_notice_backtrace
from storage.p13b_targeted_person_readback import build_p13b_targeted_person_readback


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
    targeted_person_readback_json: str | Path | None = None,
    targeted_person_readback_root: str | Path | None = None,
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
    enable_live_targeted_person_readback: bool = False,
    download_targeted_person_attachments: bool = False,
    enable_targeted_person_ocr: bool = False,
    execute_live_public_registry_entry_readback: bool = False,
    max_live_original_notices: int | None = None,
    max_live_targeted_person_readbacks: int | None = None,
    max_targeted_person_attachments_per_task: int = 3,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    state_before_root = out_dir / "00-evidence-state-before"
    original_continuation_root = out_dir / "00b-original-backtrace-continuation-plan"
    original_out_root = out_dir / "01-original-notice-backtrace"
    targeted_person_continuation_root = out_dir / "01a-original-backtrace-continuation-for-targeted-person"
    targeted_person_out_root = out_dir / "01aa-p13b-targeted-person-readback"
    final_original_continuation_root = out_dir / "01ab-original-backtrace-continuation-final"
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
    original_continuation_result: dict[str, Any] = {}
    original_source_json = original_notice_backtrace_json
    original_source_root = original_notice_backtrace_root
    original_action_state = "SKIPPED"
    original_skip_reason = ""
    targeted_person_continuation_result: dict[str, Any] = {}
    targeted_person_result: dict[str, Any] = {}
    final_original_continuation_result: dict[str, Any] = {}
    targeted_person_source_json = targeted_person_readback_json
    targeted_person_source_root = targeted_person_readback_root
    targeted_person_action_state = "SKIPPED"
    targeted_person_skip_reason = ""
    final_original_continuation_source_root: Path | None = None

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
        continuation_source_json = p13b_company_history_json
        continuation_source_root = p13b_company_history_root
        continuation_from_delta_plan = False
        skip_original_backtrace_build = False
        if original_notice_backtrace_json or original_notice_backtrace_root:
            original_continuation_result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_json=original_notice_backtrace_json,
                original_notice_backtrace_root=original_notice_backtrace_root,
                output_root=original_continuation_root,
                project_ids=original_project_ids,
                created_at=created,
            )
            continuation_summary = _summary(original_continuation_result)
            continuation_plan_count = int(continuation_summary.get("continuation_plan_record_count") or 0)
            continuation_run_count = int(continuation_summary.get("continuation_run_task_count") or 0)
            if continuation_run_count > 0:
                continuation_source_json = None
                continuation_source_root = Path(
                    original_continuation_result["manifest"]["continuation_company_history_triage_root"]
                )
                continuation_from_delta_plan = True
            elif continuation_plan_count > 0:
                skip_original_backtrace_build = True
                original_action_state = "EXISTING_ORIGINAL_BACKTRACE_CONSUMED_NO_DELTA_TASKS"
                original_skip_reason = "original_backtrace_continuation_has_no_delta_task"
        if not skip_original_backtrace_build:
            original_result = build_p13b_original_notice_backtrace(
                input_json=continuation_source_json,
                company_history_triage_root=continuation_source_root,
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
                if enable_live_original_notice_backtrace and not continuation_from_delta_plan
                else "ORIGINAL_BACKTRACE_DELTA_LIVE_ATTEMPTED"
                if enable_live_original_notice_backtrace and continuation_from_delta_plan
                else "ORIGINAL_BACKTRACE_CONTINUED_FROM_DEFERRED_TASK_PLAN"
                if continuation_from_delta_plan
                else "ORIGINAL_BACKTRACE_CONTINUED_WITH_EXISTING_INPUT"
                if original_notice_backtrace_json or original_notice_backtrace_root
                else "ORIGINAL_BACKTRACE_PLAN_BUILT"
            )

    if original_source_json or original_source_root:
        targeted_person_continuation_result = build_p13b_original_backtrace_continuation_controller(
            original_notice_backtrace_json=original_source_json,
            original_notice_backtrace_root=original_source_root,
            targeted_person_readback_json=targeted_person_source_json,
            targeted_person_readback_root=targeted_person_source_root,
            output_root=targeted_person_continuation_root,
            project_ids=original_project_ids,
            created_at=created,
        )
        targeted_person_continuation_summary = _summary(targeted_person_continuation_result)
        targeted_required_count = int(
            targeted_person_continuation_summary.get("targeted_person_readback_required_count") or 0
        )
        if targeted_person_source_json or targeted_person_source_root:
            targeted_person_action_state = "EXISTING_TARGETED_PERSON_READBACK_CONSUMED"
            targeted_person_skip_reason = "existing_targeted_person_readback_input_supplied"
        elif targeted_required_count > 0:
            targeted_person_result = build_p13b_targeted_person_readback(
                continuation_root=targeted_person_continuation_root,
                output_root=targeted_person_out_root,
                project_ids=original_project_ids,
                enable_live_public_query=enable_live_targeted_person_readback,
                download_target_attachments=download_targeted_person_attachments,
                max_live_readbacks=max_live_targeted_person_readbacks,
                max_attachments_per_task=max_targeted_person_attachments_per_task,
                enable_ocr=enable_targeted_person_ocr,
                created_at=created,
            )
            targeted_person_source_root = targeted_person_out_root
            targeted_person_action_state = (
                "TARGETED_PERSON_READBACK_LIVE_ATTEMPTED"
                if enable_live_targeted_person_readback
                else "TARGETED_PERSON_READBACK_PLAN_BUILT"
            )
        else:
            targeted_person_action_state = "SKIPPED_NO_TARGETED_PERSON_READBACK_REQUIRED"
            targeted_person_skip_reason = "continuation_controller_has_no_targeted_person_readback_required_record"

        if targeted_person_source_json or targeted_person_source_root:
            final_original_continuation_result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_json=original_source_json,
                original_notice_backtrace_root=original_source_root,
                targeted_person_readback_json=targeted_person_source_json,
                targeted_person_readback_root=targeted_person_source_root,
                output_root=final_original_continuation_root,
                project_ids=original_project_ids,
                created_at=created,
            )
            final_original_continuation_source_root = final_original_continuation_root
        else:
            final_original_continuation_result = targeted_person_continuation_result
            final_original_continuation_source_root = targeted_person_continuation_root
    else:
        targeted_person_action_state = "SKIPPED_ORIGINAL_BACKTRACE_INPUT_MISSING"
        targeted_person_skip_reason = "original_notice_backtrace_input_missing"

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
        original_backtrace_continuation_root=final_original_continuation_source_root,
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
        original_continuation_result=original_continuation_result,
        original_result=original_result,
        targeted_person_continuation_result=targeted_person_continuation_result,
        targeted_person_result=targeted_person_result,
        final_original_continuation_result=final_original_continuation_result,
        state_after=state_after,
        original_action_state=original_action_state,
        original_skip_reason=original_skip_reason,
        targeted_person_action_state=targeted_person_action_state,
        targeted_person_skip_reason=targeted_person_skip_reason,
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
        "source_targeted_person_readback_json": str(targeted_person_readback_json or ""),
        "source_targeted_person_readback_root": str(targeted_person_readback_root or ""),
        "original_backtrace_continuation_root": str(original_continuation_root)
        if original_continuation_result
        else "",
        "targeted_person_backtrace_continuation_root": str(targeted_person_continuation_root)
        if targeted_person_continuation_result
        else "",
        "p13b_targeted_person_readback_root": str(targeted_person_out_root) if targeted_person_result else "",
        "final_original_backtrace_continuation_root": str(final_original_continuation_source_root or ""),
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
        "p13b_targeted_person_readback_json": str(targeted_person_source_json or ""),
        "p13b_targeted_person_readback_root": str(targeted_person_source_root or ""),
        "design_survey_public_registry_fallback_root": str(public_registry_fallback_source_root or ""),
        "design_survey_public_registry_readback_root": str(public_registry_readback_source_root or ""),
        "state_after_root": str(state_after_root),
        "state_before_summary": _summary(state_before),
        "original_backtrace_continuation_summary": _summary(original_continuation_result),
        "original_notice_backtrace_summary": _summary(original_result),
        "targeted_person_backtrace_continuation_summary": _summary(targeted_person_continuation_result),
        "p13b_targeted_person_readback_summary": _summary(targeted_person_result),
        "final_original_backtrace_continuation_summary": _summary(final_original_continuation_result),
        "design_survey_public_registry_fallback_summary": _summary(public_registry_fallback_result),
        "design_survey_public_registry_readback_summary": _summary(public_registry_readback_result),
        "state_after_summary": _summary(state_after),
        "summary": summary,
        "safety": {
            "network_enabled": bool(
                enable_live_original_notice_backtrace
                or enable_live_targeted_person_readback
                or execute_live_public_registry_entry_readback
            ),
            "download_enabled": bool(enable_live_targeted_person_readback and download_targeted_person_attachments),
            "parse_enabled": bool(enable_live_targeted_person_readback and download_targeted_person_attachments),
            "stage4_live_provider_enabled": bool(execute_live_public_registry_entry_readback),
            "public_registry_live_entry_readback_enabled": bool(execute_live_public_registry_entry_readback),
            "targeted_person_live_readback_enabled": bool(enable_live_targeted_person_readback),
            "targeted_person_attachment_download_enabled": bool(download_targeted_person_attachments),
            "targeted_person_ocr_enabled": bool(enable_targeted_person_ocr),
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
        and (not original_continuation_result or bool(original_continuation_result.get("safe_to_execute")))
        and (not original_result or bool(original_result.get("safe_to_execute")))
        and (not targeted_person_continuation_result or bool(targeted_person_continuation_result.get("safe_to_execute")))
        and (not targeted_person_result or bool(targeted_person_result.get("safe_to_execute")))
        and (not final_original_continuation_result or bool(final_original_continuation_result.get("safe_to_execute")))
        and (not public_registry_fallback_result or bool(public_registry_fallback_result.get("safe_to_execute")))
        and (not public_registry_readback_result or bool(public_registry_readback_result.get("safe_to_execute"))),
        "blocking_reasons": [
            *_list(state_before.get("blocking_reasons")),
            *_list(original_continuation_result.get("blocking_reasons")),
            *_list(original_result.get("blocking_reasons")),
            *_list(targeted_person_continuation_result.get("blocking_reasons")),
            *_list(targeted_person_result.get("blocking_reasons")),
            *_list(final_original_continuation_result.get("blocking_reasons")),
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
    original_continuation_result: Mapping[str, Any],
    original_result: Mapping[str, Any],
    targeted_person_continuation_result: Mapping[str, Any],
    targeted_person_result: Mapping[str, Any],
    final_original_continuation_result: Mapping[str, Any],
    public_registry_fallback_result: Mapping[str, Any],
    public_registry_readback_result: Mapping[str, Any],
    state_after: Mapping[str, Any],
    original_action_state: str,
    original_skip_reason: str,
    targeted_person_action_state: str,
    targeted_person_skip_reason: str,
    public_registry_fallback_action_state: str,
    public_registry_fallback_skip_reason: str,
    public_registry_readback_action_state: str,
    public_registry_readback_skip_reason: str,
) -> dict[str, Any]:
    before = _summary(state_before)
    original_continuation = _summary(original_continuation_result)
    original = _summary(original_result)
    targeted_person_continuation = _summary(targeted_person_continuation_result)
    targeted_person = _summary(targeted_person_result)
    final_original_continuation = _summary(final_original_continuation_result)
    public_registry_fallback = _summary(public_registry_fallback_result)
    public_registry_readback = _summary(public_registry_readback_result)
    after = _summary(state_after)
    return {
        "state_before_project_count": int(before.get("project_count") or 0),
        "state_before_evidence_state_counts": dict(before.get("evidence_state_counts") or {}),
        "original_action_state": original_action_state,
        "original_skip_reason": original_skip_reason,
        "original_backtrace_continuation_run_task_count": int(
            original_continuation.get("continuation_run_task_count") or 0
        ),
        "original_backtrace_continuation_state_counts": dict(
            original_continuation.get("continuation_state_counts") or {}
        ),
        "original_backtrace_continuation_recommended_next_action": str(
            original_continuation.get("recommended_next_action") or ""
        ),
        "original_notice_task_count": int(original.get("original_notice_task_count") or 0),
        "original_notice_live_processed_count": int(original.get("live_processed_count") or 0),
        "original_notice_overlap_signal_review_required_count": int(
            original.get("original_notice_overlap_signal_review_required_count") or 0
        ),
        "targeted_person_action_state": targeted_person_action_state,
        "targeted_person_skip_reason": targeted_person_skip_reason,
        "targeted_person_pre_continuation_required_count": int(
            targeted_person_continuation.get("targeted_person_readback_required_count") or 0
        ),
        "targeted_person_task_count": int(targeted_person.get("targeted_person_task_count") or 0),
        "targeted_person_readback_count": int(targeted_person.get("targeted_person_readback_count") or 0),
        "targeted_person_found_count": int(targeted_person.get("target_person_found_count") or 0),
        "targeted_person_same_signal_ready_count": int(
            targeted_person.get("same_person_company_period_signal_ready_count") or 0
        ),
        "targeted_person_final_required_count": int(
            final_original_continuation.get("targeted_person_readback_required_count") or 0
        ),
        "final_original_backtrace_release_evidence_ready_count": int(
            final_original_continuation.get("release_evidence_ready_count") or 0
        ),
        "final_original_backtrace_continuation_state_counts": dict(
            final_original_continuation.get("continuation_state_counts") or {}
        ),
        "final_original_backtrace_continuation_recommended_next_action": str(
            final_original_continuation.get("recommended_next_action") or ""
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
    parser.add_argument("--targeted-person-readback-json", default="")
    parser.add_argument("--targeted-person-readback-root", default="")
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
    parser.add_argument("--enable-live-targeted-person-readback", action="store_true")
    parser.add_argument("--download-targeted-person-attachments", action="store_true")
    parser.add_argument("--enable-targeted-person-ocr", action="store_true")
    parser.add_argument("--execute-live-public-registry-entry-readback", action="store_true")
    parser.add_argument("--max-live-original-notices", type=int, default=None)
    parser.add_argument("--max-live-targeted-person-readbacks", type=int, default=None)
    parser.add_argument("--max-targeted-person-attachments-per-task", type=int, default=3)
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
        targeted_person_readback_json=args.targeted_person_readback_json or None,
        targeted_person_readback_root=args.targeted_person_readback_root or None,
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
        enable_live_targeted_person_readback=bool(args.enable_live_targeted_person_readback),
        download_targeted_person_attachments=bool(args.download_targeted_person_attachments),
        enable_targeted_person_ocr=bool(args.enable_targeted_person_ocr),
        execute_live_public_registry_entry_readback=bool(args.execute_live_public_registry_entry_readback),
        max_live_original_notices=args.max_live_original_notices,
        max_live_targeted_person_readbacks=args.max_live_targeted_person_readbacks,
        max_targeted_person_attachments_per_task=max(0, int(args.max_targeted_person_attachments_per_task or 0)),
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
