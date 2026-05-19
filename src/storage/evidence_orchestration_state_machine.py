from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


EVIDENCE_ORCHESTRATION_KIND = "evidence_orchestration_state_machine_v1_manifest"
EVIDENCE_ORCHESTRATION_VERSION = 1
EVIDENCE_ORCHESTRATION_ADAPTER_ID = "evidence-orchestration-state-machine-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/evidence-orchestration-state-v1")


def build_evidence_orchestration_state(
    *,
    stage16_storage_json: str | Path,
    company_first_stage4_inputs_json: str | Path | None = None,
    p13b_company_history_json: str | Path | None = None,
    p13b_company_history_root: str | Path | None = None,
    original_notice_backtrace_json: str | Path | None = None,
    original_notice_backtrace_root: str | Path | None = None,
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
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    storage_path = Path(stage16_storage_json)
    storage_payload = _load_json(storage_path, blocking_reasons, "stage16_storage_json_missing_or_invalid")
    refs = _latest_autonomous_run_refs(storage_payload)
    if storage_payload and not refs:
        blocking_reasons.append("operator_autonomous_opportunity_search_run_missing")

    candidate_options = _json_value(refs.get("candidate_options_json"), [])
    closed_loop_results = _json_value(refs.get("closed_loop_results_json"), [])
    closed_by_project = _closed_by_project(closed_loop_results)
    company_first_inputs = _company_first_inputs_by_project(company_first_stage4_inputs_json)
    p13b_manifest = _optional_manifest(
        explicit_json=p13b_company_history_json,
        root=p13b_company_history_root,
        default_file_name="company-history-overlap-triage-v1.json",
    )
    original_manifest = _optional_manifest(
        explicit_json=original_notice_backtrace_json,
        root=original_notice_backtrace_root,
        default_file_name="original-notice-backtrace-v1.json",
    )
    design_survey_plan_manifest = _optional_manifest(
        explicit_json=design_survey_adapter_plan_json,
        root=design_survey_adapter_plan_root,
        default_file_name="design-survey-responsible-adapter-plan-v1.json",
    )
    design_survey_stage4_manifest = _optional_manifest(
        explicit_json=design_survey_stage4_execution_json,
        root=design_survey_stage4_execution_root,
        default_file_name="company-first-stage4-execution.json",
    )
    design_survey_flow08_manifest = _optional_manifest(
        explicit_json=design_survey_flow08_readback_json,
        root=design_survey_flow08_readback_root,
        default_file_name="design-survey-flow08-targeted-readback-v1.json",
    )
    design_survey_flow08_parse_manifest = _optional_manifest(
        explicit_json=design_survey_flow08_attachment_parse_json,
        root=design_survey_flow08_attachment_parse_root,
        default_file_name="design-survey-flow08-target-attachment-parse-v1.json",
    )
    design_survey_public_registry_manifest = _optional_manifest(
        explicit_json=design_survey_public_registry_fallback_json,
        root=design_survey_public_registry_fallback_root,
        default_file_name="design-survey-public-registry-fallback-v1.json",
    )
    p13b_index = _p13b_index_by_project(p13b_manifest)
    original_index = _original_backtrace_index_by_project(original_manifest)
    design_survey_plan_index = _design_survey_plan_index_by_project(design_survey_plan_manifest)
    design_survey_stage4_index = _design_survey_stage4_index_by_project(design_survey_stage4_manifest)
    design_survey_flow08_index = _design_survey_flow08_index_by_project(design_survey_flow08_manifest)
    design_survey_flow08_parse_index = _design_survey_flow08_attachment_parse_index_by_project(
        design_survey_flow08_parse_manifest
    )
    design_survey_public_registry_index = _design_survey_public_registry_index_by_project(
        design_survey_public_registry_manifest
    )
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}

    evidence_records: list[dict[str, Any]] = []
    adapter_jobs: list[dict[str, Any]] = []
    fact_package_records: list[dict[str, Any]] = []

    for candidate in candidate_options if isinstance(candidate_options, list) else []:
        if not isinstance(candidate, Mapping):
            continue
        project_id = str(candidate.get("project_id") or "").strip()
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue
        closed = closed_by_project.get(project_id, {})
        supplement = company_first_inputs.get(project_id)
        record = _evidence_record(
            candidate=candidate,
            closed=closed,
            supplement=supplement,
            p13b_project=p13b_index.get(project_id, {}),
            original_project=original_index.get(project_id, {}),
            design_survey_project=design_survey_plan_index.get(project_id, {}),
            design_survey_stage4_project=design_survey_stage4_index.get(project_id, {}),
            design_survey_flow08_project=design_survey_flow08_index.get(project_id, {}),
            design_survey_flow08_parse_project=design_survey_flow08_parse_index.get(project_id, {}),
            design_survey_public_registry_project=design_survey_public_registry_index.get(project_id, {}),
            p13b_supplied=bool(p13b_manifest),
            original_supplied=bool(original_manifest),
            design_survey_plan_supplied=bool(design_survey_plan_manifest),
            design_survey_stage4_supplied=bool(design_survey_stage4_manifest),
            design_survey_flow08_supplied=bool(design_survey_flow08_manifest),
            design_survey_flow08_parse_supplied=bool(design_survey_flow08_parse_manifest),
            design_survey_public_registry_supplied=bool(design_survey_public_registry_manifest),
            created_at=created,
        )
        evidence_records.append(record)
        adapter_jobs.extend(_adapter_jobs_for_record(record, created_at=created))
        fact_package_records.append(_fact_package_record(record, created_at=created))

    evidence_table = {
        "summary": _evidence_summary(evidence_records, blocking_reasons),
        "records": evidence_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    adapter_job_table = {
        "summary": _adapter_job_summary(adapter_jobs),
        "records": adapter_jobs,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    fact_package_table = {
        "summary": _fact_package_summary(fact_package_records),
        "records": fact_package_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    batch_triage_records = _batch_triage_records(evidence_records, created_at=created)
    batch_triage_table = {
        "summary": _batch_triage_summary(batch_triage_records),
        "records": batch_triage_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = {
        **evidence_table["summary"],
        "adapter_job_count": len(adapter_jobs),
        "stage6_fact_package_record_count": len(fact_package_records),
        "batch_triage_record_count": len(batch_triage_records),
        "batch_triage_bucket_counts": batch_triage_table["summary"]["batch_triage_bucket_counts"],
        "commercial_decision_state_counts": batch_triage_table["summary"]["commercial_decision_state_counts"],
        "continue_internal_project_count": batch_triage_table["summary"]["continue_internal_project_count"],
        "stop_or_park_project_count": batch_triage_table["summary"]["stop_or_park_project_count"],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_version": EVIDENCE_ORCHESTRATION_VERSION,
        "manifest_kind": EVIDENCE_ORCHESTRATION_KIND,
        "adapter_id": EVIDENCE_ORCHESTRATION_ADAPTER_ID,
        "pipeline_stage": "EvidenceOrchestrationStateMachineV1",
        "manifest_id": f"EVIDENCE-ORCH-{_fingerprint({'summary': summary, 'records': evidence_records})[:16]}",
        "created_at": created,
        "source_stage16_storage_json": str(storage_path),
        "source_company_first_stage4_inputs_json": str(company_first_stage4_inputs_json or ""),
        "source_p13b_company_history_json": _manifest_source_path(p13b_company_history_json, p13b_company_history_root, "company-history-overlap-triage-v1.json"),
        "source_original_notice_backtrace_json": _manifest_source_path(original_notice_backtrace_json, original_notice_backtrace_root, "original-notice-backtrace-v1.json"),
        "source_design_survey_adapter_plan_json": _manifest_source_path(design_survey_adapter_plan_json, design_survey_adapter_plan_root, "design-survey-responsible-adapter-plan-v1.json"),
        "source_design_survey_stage4_execution_json": _manifest_source_path(design_survey_stage4_execution_json, design_survey_stage4_execution_root, "company-first-stage4-execution.json"),
        "source_design_survey_flow08_readback_json": _manifest_source_path(design_survey_flow08_readback_json, design_survey_flow08_readback_root, "design-survey-flow08-targeted-readback-v1.json"),
        "source_design_survey_flow08_attachment_parse_json": _manifest_source_path(design_survey_flow08_attachment_parse_json, design_survey_flow08_attachment_parse_root, "design-survey-flow08-target-attachment-parse-v1.json"),
        "source_design_survey_public_registry_fallback_json": _manifest_source_path(design_survey_public_registry_fallback_json, design_survey_public_registry_fallback_root, "design-survey-public-registry-fallback-v1.json"),
        "evidence_state_table": evidence_table,
        "adapter_job_table": adapter_job_table,
        "stage6_fact_package_readiness_table": fact_package_table,
        "batch_triage_table": batch_triage_table,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
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
        "evidence_orchestration_state_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "evidence-orchestration-state-v1.json", result)
    _write_json(out_dir / "evidence-state-table.json", evidence_table)
    _write_json(out_dir / "adapter-job-table.json", adapter_job_table)
    _write_json(out_dir / "stage6-fact-package-readiness-table.json", fact_package_table)
    _write_json(out_dir / "batch-triage-table.json", batch_triage_table)
    return result


def _evidence_record(
    *,
    candidate: Mapping[str, Any],
    closed: Mapping[str, Any],
    supplement: Mapping[str, Any] | None,
    p13b_project: Mapping[str, Any],
    original_project: Mapping[str, Any],
    design_survey_project: Mapping[str, Any],
    design_survey_stage4_project: Mapping[str, Any],
    design_survey_flow08_project: Mapping[str, Any],
    design_survey_flow08_parse_project: Mapping[str, Any],
    design_survey_public_registry_project: Mapping[str, Any],
    p13b_supplied: bool,
    original_supplied: bool,
    design_survey_plan_supplied: bool,
    design_survey_stage4_supplied: bool,
    design_survey_flow08_supplied: bool,
    design_survey_flow08_parse_supplied: bool,
    design_survey_public_registry_supplied: bool,
    created_at: str,
) -> dict[str, Any]:
    project_id = str(candidate.get("project_id") or "").strip()
    readback = closed.get("real_public_stage4_9_readback") if isinstance(closed.get("real_public_stage4_9_readback"), Mapping) else {}
    responsible_person = _responsible_person(candidate, supplement)
    certificate_no = _certificate_no(candidate, supplement)
    candidate_companies = _group_members(_split_companies(candidate.get("candidate_company")), supplement)
    base_state, base_next_action, base_reasons = _base_readiness_state(
        candidate=candidate,
        readback=readback,
        supplement=supplement,
        responsible_person=responsible_person,
        certificate_no=certificate_no,
    )
    evidence_state, evidence_grade, next_action, review_reasons, signal_source = _project_evidence_state(
        base_state=base_state,
        base_next_action=base_next_action,
        base_reasons=base_reasons,
        p13b_project=p13b_project,
        original_project=original_project,
        design_survey_project=design_survey_project,
        design_survey_stage4_project=design_survey_stage4_project,
        design_survey_flow08_project=design_survey_flow08_project,
        design_survey_flow08_parse_project=design_survey_flow08_parse_project,
        design_survey_public_registry_project=design_survey_public_registry_project,
        p13b_supplied=p13b_supplied,
        original_supplied=original_supplied,
        design_survey_plan_supplied=design_survey_plan_supplied,
        design_survey_stage4_supplied=design_survey_stage4_supplied,
        design_survey_flow08_supplied=design_survey_flow08_supplied,
        design_survey_flow08_parse_supplied=design_survey_flow08_parse_supplied,
        design_survey_public_registry_supplied=design_survey_public_registry_supplied,
    )
    signal_counts = _signal_counts(p13b_project, original_project)
    design_survey_counts = _design_survey_counts(
        design_survey_project,
        design_survey_stage4_project,
        design_survey_flow08_project,
        design_survey_flow08_parse_project,
        design_survey_public_registry_project,
    )
    release_probe_targets = _release_probe_targets(original_project)
    if not release_probe_targets and evidence_state == "A_STRONG_TIME_OVERLAP_SIGNAL_READY":
        release_probe_targets = [
            "construction_permit",
            "contract_public_info",
            "completion_filing",
            "project_manager_change_notice",
        ]
    return {
        "project_id": project_id,
        "project_name": str(candidate.get("project_name") or ""),
        "source_url": str(candidate.get("source_url") or ""),
        "candidate_company_text": str(candidate.get("candidate_company") or ""),
        "candidate_group_members": candidate_companies,
        "responsible_person_name": responsible_person,
        "project_manager_certificate_no": certificate_no,
        "person_public_id_optional": str((supplement or {}).get("person_public_id_optional") or ""),
        "engineering_work_lane": str(candidate.get("engineering_work_lane") or ""),
        "opportunity_priority_class": str(candidate.get("opportunity_priority_class") or ""),
        "stage2_detail_capture_state": str(candidate.get("stage2_detail_capture_state") or ""),
        "stage3_detail_parse_state": str(candidate.get("stage3_detail_parse_state") or ""),
        "stage4_hard_defect_gate_state": str(closed.get("real_world_hard_defect_gate_state") or ""),
        "stage5_rule_gate_status": str(readback.get("stage5_rule_gate_status") or ""),
        "stage5_evidence_gate_status": str(readback.get("stage5_evidence_gate_status") or ""),
        "jzsc_company_first_identity_resolution_required": bool(
            readback.get("jzsc_company_first_identity_resolution_required")
        ),
        "company_first_supplement_applied": bool(supplement),
        "base_readiness_state": base_state,
        "evidence_state": evidence_state,
        "evidence_grade": evidence_grade,
        "evidence_signal_source": signal_source,
        "recommended_next_action": next_action,
        "stage6_fact_package_state": _stage6_fact_package_state(evidence_state),
        "release_evidence_probe_required": evidence_state == "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
        "release_evidence_source_targets": release_probe_targets,
        "signal_counts": signal_counts,
        "design_survey_adapter_counts": design_survey_counts,
        "review_reasons": review_reasons,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _base_readiness_state(
    *,
    candidate: Mapping[str, Any],
    readback: Mapping[str, Any],
    supplement: Mapping[str, Any] | None,
    responsible_person: str,
    certificate_no: str,
) -> tuple[str, str, list[str]]:
    if str(candidate.get("stage2_detail_capture_state") or "") not in {"FETCHED", "REUSED_EXISTING"}:
        return "WAIT_STAGE2_CAPTURE", "increase_detail_capture_limit_or_retry_stage2", ["stage2_detail_not_ready"]
    priority_class = str(candidate.get("opportunity_priority_class") or "")
    lane = str(candidate.get("engineering_work_lane") or "")
    if "DESIGN_SURVEY" in priority_class or lane == "survey_design":
        return (
            "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER",
            "run_design_survey_responsible_adapter_plan",
            ["design_survey_not_project_manager_release_mainline"],
        )
    if bool(readback.get("jzsc_company_first_identity_resolution_required")) and not supplement:
        return (
            "WAIT_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT",
            "run_company_first_identifier_resolution_before_p13b",
            ["project_manager_certificate_missing_before_company_first"],
        )
    if not responsible_person:
        return (
            "WAIT_RESPONSIBLE_PERSON_EXTRACTION",
            "targeted_original_or_attachment_readback_for_responsible_person",
            ["responsible_person_missing"],
        )
    if not certificate_no:
        return (
            "WAIT_CERTIFICATE_OR_PUBLIC_IDENTIFIER",
            "run_company_first_or_name_enumeration_before_p13b",
            ["project_manager_certificate_or_public_identifier_missing"],
        )
    return "READY_FOR_P13B_DATA_GGZY", "run_data_ggzy_company_history_overlap_triage", []


def _project_evidence_state(
    *,
    base_state: str,
    base_next_action: str,
    base_reasons: list[str],
    p13b_project: Mapping[str, Any],
    original_project: Mapping[str, Any],
    design_survey_project: Mapping[str, Any],
    design_survey_stage4_project: Mapping[str, Any],
    design_survey_flow08_project: Mapping[str, Any],
    design_survey_flow08_parse_project: Mapping[str, Any],
    design_survey_public_registry_project: Mapping[str, Any],
    p13b_supplied: bool,
    original_supplied: bool,
    design_survey_plan_supplied: bool,
    design_survey_stage4_supplied: bool,
    design_survey_flow08_supplied: bool,
    design_survey_flow08_parse_supplied: bool,
    design_survey_public_registry_supplied: bool,
) -> tuple[str, str, str, list[str], str]:
    if base_state == "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER":
        return _design_survey_evidence_state(
            base_next_action=base_next_action,
            base_reasons=base_reasons,
            design_survey_project=design_survey_project,
            design_survey_stage4_project=design_survey_stage4_project,
            design_survey_flow08_project=design_survey_flow08_project,
            design_survey_flow08_parse_project=design_survey_flow08_parse_project,
            design_survey_public_registry_project=design_survey_public_registry_project,
            design_survey_plan_supplied=design_survey_plan_supplied,
            design_survey_stage4_supplied=design_survey_stage4_supplied,
            design_survey_flow08_supplied=design_survey_flow08_supplied,
            design_survey_flow08_parse_supplied=design_survey_flow08_parse_supplied,
            design_survey_public_registry_supplied=design_survey_public_registry_supplied,
        )
    if base_state != "READY_FOR_P13B_DATA_GGZY":
        return base_state, "NOT_EVIDENCE_READY", base_next_action, base_reasons, "BASE_READINESS"

    original_overlap = _records_with_state(
        original_project.get("original_notice_overlap_signal_records"),
        "original_notice_overlap_signal_state",
        "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED",
    )
    if original_overlap:
        return (
            "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "A_STRONG_SIGNAL",
            "build_release_evidence_regional_adapter_plan",
            ["same_person_company_time_window_signal_from_original_notice"],
            "ORIGINAL_NOTICE_BACKTRACE",
        )

    direct_overlap = _records_with_state(
        p13b_project.get("overlap_signal_records"),
        "overlap_signal_state",
        "OVERLAP_SIGNAL_REVIEW_REQUIRED",
    )
    if direct_overlap:
        return (
            "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "A_STRONG_SIGNAL",
            "build_release_evidence_regional_adapter_plan",
            ["same_person_company_time_window_signal_from_data_ggzy_bid_show"],
            "DATA_GGZY_BID_SHOW_DIRECT",
        )

    backtrace_required = _records_with_state(
        p13b_project.get("overlap_signal_records"),
        "overlap_signal_state",
        "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
    )
    if original_supplied and backtrace_required and not _original_backtrace_covers_required(
        original_project,
        required_count=len(backtrace_required),
    ):
        return (
            "P13B_ORIGINAL_BACKTRACE_REQUIRED",
            "PENDING_ORIGINAL_BACKTRACE",
            "continue_p13b_original_notice_backtrace",
            ["original_notice_backtrace_budget_deferred_or_incomplete"],
            "ORIGINAL_NOTICE_BACKTRACE_PARTIAL",
        )

    if original_supplied and _has_original_backtrace_processed(original_project):
        blocker_count = _count_blocked_original_records(original_project)
        if blocker_count:
            return (
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                "D_EVIDENCE_INSUFFICIENT",
                "manual_review_or_retry_blocked_original_notice_backtrace",
                ["original_notice_backtrace_blocked_or_source_unsupported"],
                "ORIGINAL_NOTICE_BACKTRACE",
            )
        return (
            "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "D_EVIDENCE_INSUFFICIENT",
            "manual_review_or_expand_targeted_backtrace_if_value_justifies",
            ["original_notice_backtrace_no_same_person_company_time_window_signal"],
            "ORIGINAL_NOTICE_BACKTRACE",
        )

    if backtrace_required:
        return (
            "P13B_ORIGINAL_BACKTRACE_REQUIRED",
            "PENDING_ORIGINAL_BACKTRACE",
            "run_p13b_original_notice_backtrace",
            ["data_ggzy_bid_show_missing_person_or_period_for_direct_a_signal"],
            "DATA_GGZY_BID_SHOW_REVIEW",
        )

    if p13b_supplied and p13b_project:
        return (
            "P13B_NO_DIRECT_SIGNAL_REVIEW",
            "D_EVIDENCE_INSUFFICIENT",
            "manual_review_or_close_p13b_without_clearance_claim",
            ["data_ggzy_no_same_person_company_time_window_signal"],
            "DATA_GGZY_BID_SHOW_REVIEW",
        )

    return (
        "READY_FOR_P13B_DATA_GGZY",
        "PENDING_P13B",
        "run_data_ggzy_company_history_overlap_triage",
        [],
        "NOT_EXECUTED",
    )


def _design_survey_evidence_state(
    *,
    base_next_action: str,
    base_reasons: list[str],
    design_survey_project: Mapping[str, Any],
    design_survey_stage4_project: Mapping[str, Any],
    design_survey_flow08_project: Mapping[str, Any],
    design_survey_flow08_parse_project: Mapping[str, Any],
    design_survey_public_registry_project: Mapping[str, Any],
    design_survey_plan_supplied: bool,
    design_survey_stage4_supplied: bool,
    design_survey_flow08_supplied: bool,
    design_survey_flow08_parse_supplied: bool,
    design_survey_public_registry_supplied: bool,
) -> tuple[str, str, str, list[str], str]:
    if not design_survey_plan_supplied:
        return (
            "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER",
            "NOT_EVIDENCE_READY",
            base_next_action,
            base_reasons,
            "BASE_READINESS",
        )

    if not design_survey_project:
        return (
            "DESIGN_SURVEY_ADAPTER_PLAN_NOT_COVERING_PROJECT",
            "PENDING_DESIGN_SURVEY_ADAPTER",
            "rerun_design_survey_responsible_adapter_plan_for_project",
            ["design_survey_adapter_plan_missing_project"],
            "DESIGN_SURVEY_ADAPTER_PLAN",
        )

    readiness = str(design_survey_project.get("adapter_readiness_state") or "")
    if readiness and readiness != "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN":
        return (
            "D_DESIGN_SURVEY_TARGET_FIELDS_INSUFFICIENT",
            "D_EVIDENCE_INSUFFICIENT",
            "targeted_current_notice_or_attachment_readback_for_design_survey_responsible_fields",
            _list(design_survey_project.get("review_reasons")) or ["design_survey_target_fields_missing"],
            "DESIGN_SURVEY_ADAPTER_PLAN",
        )

    if not design_survey_stage4_supplied or not design_survey_stage4_project:
        return (
            "DESIGN_SURVEY_STAGE4_INPUTS_READY",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "run_design_survey_stage4_person_company_certificate_execution",
            ["design_survey_stage4_inputs_ready_not_executed"],
            "DESIGN_SURVEY_ADAPTER_PLAN",
        )

    supplement_states = {
        str(key): int(value or 0)
        for key, value in dict(design_survey_stage4_project.get("supplement_after_execution_state_counts") or {}).items()
    }
    execution_states = {
        str(key): int(value or 0)
        for key, value in dict(design_survey_stage4_project.get("stage4_execution_state_counts") or {}).items()
    }
    candidate_group_resolved_count = int(design_survey_stage4_project.get("candidate_group_resolved_count") or 0)
    fail_closed_count = sum(int(value or 0) for value in dict(design_survey_stage4_project.get("fail_closed_reason_counts") or {}).values())

    if candidate_group_resolved_count > 0 or supplement_states.get("COMPANY_FIRST_CERTIFICATE_RESOLVED", 0) > 0:
        return (
            "DESIGN_SURVEY_RESPONSIBLE_IDENTITY_MATCH_READY",
            "DESIGN_SURVEY_IDENTITY_MATCH_REVIEW",
            "continue_design_survey_qualification_and_service_clock_review",
            ["design_survey_person_company_certificate_or_public_id_resolved"],
            "DESIGN_SURVEY_STAGE4_EXECUTION",
        )

    if supplement_states.get("COMPANY_FIRST_PROVIDER_TASKS_READY", 0) > 0 or execution_states.get("QUEUED_NOT_EXECUTED", 0) > 0:
        return (
            "DESIGN_SURVEY_STAGE4_PROVIDER_TASKS_READY",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "execute_design_survey_stage4_provider_tasks",
            ["design_survey_stage4_provider_tasks_queued_not_executed"],
            "DESIGN_SURVEY_STAGE4_EXECUTION",
        )

    if supplement_states.get("NAME_ENUMERATION_FALLBACK_REQUIRED", 0) > 0:
        return (
            "DESIGN_SURVEY_NAME_ENUMERATION_FALLBACK_REQUIRED",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "run_design_survey_name_enumeration_or_local_registry_fallback",
            ["design_survey_company_first_no_match_requires_name_enumeration_or_local_registry"],
            "DESIGN_SURVEY_STAGE4_EXECUTION",
        )

    if supplement_states.get("DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED", 0) > 0:
        if design_survey_public_registry_supplied:
            return _design_survey_public_registry_evidence_state(
                design_survey_public_registry_project=design_survey_public_registry_project,
            )
        return (
            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "run_design_survey_natural_resource_or_local_public_registry_fallback",
            ["flow08_current_binding_found_but_jzsc_public_registration_unresolved"],
            "DESIGN_SURVEY_STAGE4_EXECUTION",
        )

    if supplement_states.get("FLOW_08_TARGETED_PARSE_REQUIRED", 0) > 0:
        if design_survey_flow08_supplied:
            return _design_survey_flow08_evidence_state(
                design_survey_flow08_project=design_survey_flow08_project,
                design_survey_flow08_parse_project=design_survey_flow08_parse_project,
                design_survey_flow08_parse_supplied=design_survey_flow08_parse_supplied,
            )
        return (
            "DESIGN_SURVEY_FLOW08_TARGETED_PARSE_REQUIRED",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "targeted_flow08_or_attachment_readback_for_design_survey_identity",
            ["design_survey_identity_requires_flow08_targeted_parse"],
            "DESIGN_SURVEY_STAGE4_EXECUTION",
        )

    if fail_closed_count > 0:
        return (
            "D_DESIGN_SURVEY_IDENTITY_INSUFFICIENT_OR_BLOCKED",
            "D_EVIDENCE_INSUFFICIENT",
            "manual_review_or_retry_design_survey_stage4_identity_sources",
            ["design_survey_stage4_identity_source_blocked_or_no_match"],
            "DESIGN_SURVEY_STAGE4_EXECUTION",
        )

    return (
        "D_DESIGN_SURVEY_IDENTITY_INSUFFICIENT_OR_BLOCKED",
        "D_EVIDENCE_INSUFFICIENT",
        "manual_review_design_survey_stage4_execution_without_clearance_claim",
        ["design_survey_stage4_execution_no_resolved_identity"],
        "DESIGN_SURVEY_STAGE4_EXECUTION",
    )


def _design_survey_flow08_evidence_state(
    *,
    design_survey_flow08_project: Mapping[str, Any],
    design_survey_flow08_parse_project: Mapping[str, Any],
    design_survey_flow08_parse_supplied: bool,
) -> tuple[str, str, str, list[str], str]:
    if not design_survey_flow08_project:
        return (
            "DESIGN_SURVEY_FLOW08_READBACK_NOT_COVERING_PROJECT",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "rerun_design_survey_flow08_targeted_readback_for_project",
            ["design_survey_flow08_readback_missing_project"],
            "DESIGN_SURVEY_FLOW08_TARGETED_READBACK",
        )

    if design_survey_flow08_parse_supplied and design_survey_flow08_parse_project:
        return _design_survey_flow08_attachment_parse_evidence_state(
            design_survey_flow08_parse_project=design_survey_flow08_parse_project,
        )

    state_counts = {
        str(key): int(value or 0)
        for key, value in dict(design_survey_flow08_project.get("flow08_readback_state_counts") or {}).items()
    }
    match_counts = {
        str(key): int(value or 0)
        for key, value in dict(design_survey_flow08_project.get("target_attachment_match_state_counts") or {}).items()
    }
    if state_counts.get("FLOW08_TARGET_ATTACHMENT_FETCHED", 0) > 0:
        return (
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_FETCHED_PARSE_PENDING",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "run_targeted_stage4_attachment_document_parse_for_design_survey_identity",
            ["design_survey_flow08_target_attachment_downloaded_parse_pending"],
            "DESIGN_SURVEY_FLOW08_TARGETED_READBACK",
        )
    if state_counts.get("FLOW08_TARGET_ATTACHMENT_BOUND_DOWNLOAD_DEFERRED", 0) > 0:
        return (
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_READY",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "download_bound_flow08_target_attachment_then_parse_responsible_fields",
            ["design_survey_flow08_target_attachment_bound_download_deferred"],
            "DESIGN_SURVEY_FLOW08_TARGETED_READBACK",
        )
    if state_counts.get("FLOW08_TARGETED_READBACK_READY_NOT_EXECUTED", 0) > 0:
        return (
            "DESIGN_SURVEY_FLOW08_READBACK_READY_NOT_EXECUTED",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "execute_design_survey_flow08_targeted_readback",
            ["design_survey_flow08_readback_plan_not_executed"],
            "DESIGN_SURVEY_FLOW08_TARGETED_READBACK",
        )
    if match_counts.get("TARGET_CANDIDATE_ATTACHMENT_BOUND", 0) > 0:
        return (
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_READY",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "download_bound_flow08_target_attachment_then_parse_responsible_fields",
            ["design_survey_flow08_target_attachment_bound_download_deferred"],
            "DESIGN_SURVEY_FLOW08_TARGETED_READBACK",
        )
    return (
        "D_DESIGN_SURVEY_FLOW08_READBACK_BLOCKED_OR_INSUFFICIENT",
        "D_EVIDENCE_INSUFFICIENT",
        "manual_review_or_retry_flow08_targeted_readback_without_clearance_claim",
        ["design_survey_flow08_readback_blocked_or_target_attachment_unresolved"],
        "DESIGN_SURVEY_FLOW08_TARGETED_READBACK",
    )


def _design_survey_public_registry_evidence_state(
    *,
    design_survey_public_registry_project: Mapping[str, Any],
) -> tuple[str, str, str, list[str], str]:
    if not design_survey_public_registry_project:
        return (
            "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_COVERING_PROJECT",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "rerun_design_survey_public_registry_fallback_for_project",
            ["design_survey_public_registry_fallback_missing_project"],
            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK",
        )
    target_count = int(design_survey_public_registry_project.get("target_record_count") or 0)
    task_count = int(design_survey_public_registry_project.get("task_count") or 0)
    matched_count = int(design_survey_public_registry_project.get("matched_public_registry_task_count") or 0)
    blocked_count = int(design_survey_public_registry_project.get("blocked_or_insufficient_task_count") or 0)
    if matched_count > 0:
        return (
            "DESIGN_SURVEY_PUBLIC_REGISTRY_IDENTITY_MATCH_READY",
            "DESIGN_SURVEY_IDENTITY_MATCH_REVIEW",
            "continue_design_survey_qualification_and_service_clock_review",
            ["registered_surveyor_public_registry_person_company_match_ready_for_review"],
            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK",
        )
    if task_count > 0:
        return (
            "DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "execute_registered_surveyor_public_registry_readback_or_manual_public_snapshot",
            ["registered_surveyor_public_registry_tasks_ready_not_executed"],
            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK",
        )
    if target_count > 0 or blocked_count > 0:
        return (
            "D_DESIGN_SURVEY_PUBLIC_REGISTRY_TARGET_INSUFFICIENT",
            "D_EVIDENCE_INSUFFICIENT",
            "manual_review_public_registry_fallback_target_fields_without_clearance_claim",
            ["registered_surveyor_public_registry_target_missing_or_blocked"],
            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK",
        )
    return (
        "D_DESIGN_SURVEY_PUBLIC_REGISTRY_TARGET_INSUFFICIENT",
        "D_EVIDENCE_INSUFFICIENT",
        "rerun_design_survey_public_registry_fallback_with_stage4_execution",
        ["registered_surveyor_public_registry_fallback_has_no_targets"],
        "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK",
    )


def _design_survey_flow08_attachment_parse_evidence_state(
    *,
    design_survey_flow08_parse_project: Mapping[str, Any],
) -> tuple[str, str, str, list[str], str]:
    parse_counts = {
        str(key): int(value or 0)
        for key, value in dict(design_survey_flow08_parse_project.get("attachment_parse_state_counts") or {}).items()
    }
    if (
        parse_counts.get("TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED", 0) > 0
        or parse_counts.get("TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED", 0) > 0
    ):
        return (
            "DESIGN_SURVEY_FLOW08_IDENTITY_FIELDS_EXTRACTED_REVIEW_READY",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "build_design_survey_flow08_stage4_inputs_from_person_dossier"
            if parse_counts.get("TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED", 0) > 0
            else "build_design_survey_flow08_stage4_inputs_from_extracted_fields",
            ["design_survey_flow08_target_attachment_fields_extracted"],
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_PARSE",
        )
    if parse_counts.get("TARGET_ATTACHMENT_OCR_REQUIRED", 0) > 0:
        return (
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_OCR_REQUIRED",
            "PENDING_DESIGN_SURVEY_STAGE4",
            "rerun_design_survey_flow08_target_attachment_parse_with_ocr",
            ["design_survey_flow08_target_attachment_requires_ocr"],
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_PARSE",
        )
    if parse_counts.get("TARGET_ATTACHMENT_OCR_ENGINE_UNAVAILABLE", 0) > 0:
        return (
            "D_DESIGN_SURVEY_FLOW08_OCR_RUNTIME_BLOCKED",
            "D_EVIDENCE_INSUFFICIENT",
            "fix_local_ocr_runtime_or_manual_ocr_readback",
            ["design_survey_flow08_ocr_runtime_blocked"],
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_PARSE",
        )
    if parse_counts.get("TARGET_ATTACHMENT_OCR_LANGUAGE_UNAVAILABLE", 0) > 0:
        return (
            "D_DESIGN_SURVEY_FLOW08_OCR_RUNTIME_BLOCKED",
            "D_EVIDENCE_INSUFFICIENT",
            "install_chinese_ocr_language_pack_or_manual_ocr_readback",
            ["design_survey_flow08_chinese_ocr_language_pack_unavailable"],
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_PARSE",
        )
    if parse_counts.get("TARGET_ATTACHMENT_OCR_NO_TEXT", 0) > 0:
        return (
            "D_DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_BLOCKED_OR_INSUFFICIENT",
            "D_EVIDENCE_INSUFFICIENT",
            "manual_review_pdf_pages_or_expand_ocr_page_budget",
            ["design_survey_flow08_ocr_executed_but_no_text"],
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_PARSE",
        )
    if parse_counts.get("TARGET_ATTACHMENT_NO_RESPONSIBLE_FIELD_FOUND", 0) > 0:
        return (
            "D_DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_BLOCKED_OR_INSUFFICIENT",
            "D_EVIDENCE_INSUFFICIENT",
            "manual_review_or_expand_targeted_attachment_parse_without_clearance_claim",
            ["design_survey_flow08_attachment_text_has_no_responsible_field"],
            "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_PARSE",
        )
    return (
        "D_DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_BLOCKED_OR_INSUFFICIENT",
        "D_EVIDENCE_INSUFFICIENT",
        "manual_review_or_retry_flow08_target_attachment_parse_without_clearance_claim",
        ["design_survey_flow08_attachment_parse_blocked_or_missing_result"],
        "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_PARSE",
    )


def _adapter_jobs_for_record(record: Mapping[str, Any], *, created_at: str) -> list[dict[str, Any]]:
    state = str(record.get("evidence_state") or "")
    project_id = str(record.get("project_id") or "")
    jobs: list[dict[str, Any]] = []
    if state == "WAIT_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT":
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="company_first_certificate_supplement",
                job_state="READY_TO_RUN",
                recommended_script="scripts/build-company-first-supplement-from-stage16-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
            )
        )
    elif state == "READY_FOR_P13B_DATA_GGZY":
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="data_ggzy_company_history_overlap_triage",
                job_state="READY_TO_RUN",
                recommended_script="scripts/run-stage16-p13b-continuation-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
            )
        )
    elif state == "P13B_ORIGINAL_BACKTRACE_REQUIRED":
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="p13b_original_notice_backtrace",
                job_state="READY_TO_RUN",
                recommended_script="scripts/build-p13b-original-notice-backtrace-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
            )
        )
    elif state == "A_STRONG_TIME_OVERLAP_SIGNAL_READY":
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="release_evidence_regional_adapter_plan",
                job_state="PLAN_ONLY_ADAPTER_REQUIRED",
                recommended_script="scripts/build-release-evidence-regional-adapter-plan-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                release_evidence_source_targets=_list(record.get("release_evidence_source_targets")),
            )
        )
    elif state in {"DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER", "DESIGN_SURVEY_ADAPTER_PLAN_NOT_COVERING_PROJECT"}:
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_responsible_adapter_plan",
                job_state="READY_TO_RUN_PLAN_ONLY",
                recommended_script="scripts/build-design-survey-responsible-adapter-plan-v1.ps1",
                recommended_next_action=record.get("recommended_next_action") or "run_design_survey_responsible_adapter_plan",
                created_at=created_at,
                adapter_source_targets=[
                    "candidate_notice_current_project",
                    "jzsc_or_local_design_survey_personnel_registry",
                    "enterprise_design_survey_qualification_public_record",
                    "current_project_design_survey_service_clock",
                    "data_ggzy_design_survey_history_review_when_needed",
                ],
                adapter_scope_guardrails={
                    "does_not_apply_construction_project_manager_release_rule": True,
                    "construction_release_source_targets_default_enabled": False,
                    "query_miss_is_not_clearance": True,
                },
            )
        )
    elif state in {"DESIGN_SURVEY_STAGE4_INPUTS_READY", "DESIGN_SURVEY_STAGE4_PROVIDER_TASKS_READY"}:
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_stage4_person_company_certificate_execution",
                job_state="READY_TO_RUN_AUTHORIZED_STAGE4",
                recommended_script="scripts/build-company-first-stage4-execution-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "jzsc_company_personnel_public_record",
                    "local_design_survey_personnel_registry",
                    "national_highway_construction_market_credit_personnel_when_route_matched",
                ],
                adapter_scope_guardrails={
                    "does_not_apply_construction_project_manager_release_rule": True,
                    "stage4_live_provider_requires_operator_authorization": True,
                    "query_miss_is_not_clearance": True,
                },
            )
        )
    elif state in {
        "DESIGN_SURVEY_NAME_ENUMERATION_FALLBACK_REQUIRED",
        "DESIGN_SURVEY_FLOW08_TARGETED_PARSE_REQUIRED",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
    }:
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_flow08_targeted_readback"
                if state == "DESIGN_SURVEY_FLOW08_TARGETED_PARSE_REQUIRED"
                else "design_survey_public_registry_fallback_plan"
                if state == "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED"
                else "design_survey_identity_fallback_plan",
                job_state="PLAN_ONLY_ADAPTER_REQUIRED",
                recommended_script="scripts/build-design-survey-flow08-targeted-readback-v1.ps1"
                if state == "DESIGN_SURVEY_FLOW08_TARGETED_PARSE_REQUIRED"
                else "scripts/build-design-survey-public-registry-fallback-v1.ps1"
                if state == "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED"
                else "scripts/build-evidence-verification-strategy-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "name_enumeration_public_personnel_registry",
                    "local_design_survey_personnel_registry",
                    "natural_resource_registered_surveyor_public_registry",
                    "flow_08_targeted_parse_only_if_triggered",
                ],
                adapter_scope_guardrails={
                    "do_not_parse_flow_08_by_default": True,
                    "no_name_only_final_proof": True,
                    "flow08_current_binding_does_not_need_reparse": state
                    == "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
                    "query_miss_is_not_clearance": True,
                },
            )
        )
    elif state in {"DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY", "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_COVERING_PROJECT"}:
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_public_registry_readback_or_manual_snapshot",
                job_state="RUNTIME_ADAPTER_OR_MANUAL_PUBLIC_SNAPSHOT_REQUIRED",
                recommended_script="scripts/build-design-survey-public-registry-fallback-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "natural_resource_registered_surveyor_public_registry",
                    "registered_surveyor_public_page_or_snapshot",
                    "flow08_certificate_extraction_only_if_certificate_missing",
                ],
                adapter_scope_guardrails={
                    "public_registry_task_plan_already_built": state == "DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY",
                    "entry_reachability_is_not_field_success": True,
                    "no_name_only_final_proof": True,
                    "query_miss_is_not_clearance": True,
                    "customer_visible_allowed": False,
                },
            )
        )
    elif state in {
        "DESIGN_SURVEY_FLOW08_READBACK_NOT_COVERING_PROJECT",
        "DESIGN_SURVEY_FLOW08_READBACK_READY_NOT_EXECUTED",
        "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_READY",
    }:
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_flow08_targeted_readback",
                job_state="READY_TO_RUN_TARGETED_READBACK",
                recommended_script="scripts/build-design-survey-flow08-targeted-readback-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "guangzhou_flow08_bid_file_publicity_detail",
                    "target_candidate_attachment_only",
                ],
                adapter_scope_guardrails={
                    "do_not_parse_all_flow_08_by_default": True,
                    "do_not_download_non_target_candidate_attachments": True,
                    "target_attachment_download_requires_explicit_switch": True,
                    "query_miss_is_not_clearance": True,
                },
            )
        )
    elif state in {
        "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_FETCHED_PARSE_PENDING",
        "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_OCR_REQUIRED",
    }:
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_flow08_target_attachment_parse",
                job_state="READY_TO_RUN_TARGETED_PARSE",
                recommended_script="scripts/build-design-survey-flow08-target-attachment-parse-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "downloaded_flow08_target_candidate_attachment",
                    "responsible_person_certificate_or_title_fields",
                ],
                adapter_scope_guardrails={
                    "targeted_parse_only": True,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
            )
        )
    elif state == "DESIGN_SURVEY_FLOW08_IDENTITY_FIELDS_EXTRACTED_REVIEW_READY":
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_flow08_build_stage4_inputs",
                job_state="READY_TO_BUILD_STAGE4_INPUTS",
                recommended_script="scripts/build-design-survey-flow08-stage4-inputs-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "flow08_target_attachment_extracted_fields_or_person_dossier",
                    "stage4_candidate_verification_inputs",
                ],
                adapter_scope_guardrails={
                    "extracted_field_is_review_input_not_legal_conclusion": True,
                    "no_name_only_final_proof": True,
                    "next_stage4_public_registration_replay_required": True,
                    "customer_visible_allowed": False,
                },
            )
        )
    elif state == "D_DESIGN_SURVEY_FLOW08_OCR_RUNTIME_BLOCKED":
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_flow08_ocr_runtime_fix_and_retry",
                job_state="ENVIRONMENT_FIX_REQUIRED",
                recommended_script="scripts/build-design-survey-flow08-target-attachment-parse-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "local_ocr_runtime",
                    "downloaded_flow08_target_candidate_attachment",
                ],
                adapter_scope_guardrails={
                    "targeted_parse_only": True,
                    "install_or_enable_chinese_ocr_language_pack_before_retry": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
            )
        )
    elif state == "DESIGN_SURVEY_RESPONSIBLE_IDENTITY_MATCH_READY":
        jobs.append(
            _adapter_job(
                project_id=project_id,
                project_name=record.get("project_name"),
                job_type="design_survey_qualification_service_clock_review",
                job_state="PLAN_ONLY_ADAPTER_REQUIRED",
                recommended_script="scripts/build-design-survey-responsible-adapter-plan-v1.ps1",
                recommended_next_action=record.get("recommended_next_action"),
                created_at=created_at,
                adapter_source_targets=[
                    "enterprise_design_survey_qualification_public_record",
                    "current_project_design_survey_service_clock",
                    "prior_design_survey_award_history_review",
                ],
                adapter_scope_guardrails={
                    "identity_match_is_not_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                    "customer_visible_allowed": False,
                },
            )
        )
    return jobs


def _adapter_job(
    *,
    project_id: str,
    project_name: Any,
    job_type: str,
    job_state: str,
    recommended_script: str,
    recommended_next_action: Any,
    created_at: str,
    release_evidence_source_targets: list[Any] | None = None,
    adapter_source_targets: list[Any] | None = None,
    adapter_scope_guardrails: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "adapter_job_id": _stable_id("ADAPTER-JOB", project_id, job_type),
        "project_id": project_id,
        "project_name": str(project_name or ""),
        "job_type": job_type,
        "job_state": job_state,
        "recommended_script": recommended_script,
        "recommended_next_action": str(recommended_next_action or ""),
        "release_evidence_source_targets": release_evidence_source_targets or [],
        "adapter_source_targets": adapter_source_targets or [],
        "adapter_scope_guardrails": dict(adapter_scope_guardrails or {}),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fact_package_record(record: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    state = str(record.get("stage6_fact_package_state") or "")
    return {
        "stage6_fact_package_readiness_id": _stable_id("STAGE6-FACT-READY", record.get("project_id"), state),
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "evidence_state": record.get("evidence_state"),
        "evidence_grade": record.get("evidence_grade"),
        "stage6_fact_package_state": state,
        "stage6_ready": state in {"A_STRONG_SIGNAL_FACT_PACKAGE_READY", "REVIEW_FACT_PACKAGE_READY"},
        "stage7_commercial_input_allowed": state == "A_STRONG_SIGNAL_FACT_PACKAGE_READY",
        "stage7_commercial_input_mode": "INTERNAL_REVIEW_ONLY" if state == "A_STRONG_SIGNAL_FACT_PACKAGE_READY" else "BLOCKED_OR_REVIEW",
        "recommended_next_action": record.get("recommended_next_action"),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "created_at": created_at,
    }


def _stage6_fact_package_state(evidence_state: str) -> str:
    if evidence_state == "A_STRONG_TIME_OVERLAP_SIGNAL_READY":
        return "A_STRONG_SIGNAL_FACT_PACKAGE_READY"
    if evidence_state in {
        "D_INSUFFICIENT_OR_BLOCKED_READBACK",
        "P13B_NO_DIRECT_SIGNAL_REVIEW",
        "DESIGN_SURVEY_RESPONSIBLE_IDENTITY_MATCH_READY",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_IDENTITY_MATCH_READY",
        "D_DESIGN_SURVEY_TARGET_FIELDS_INSUFFICIENT",
        "D_DESIGN_SURVEY_IDENTITY_INSUFFICIENT_OR_BLOCKED",
        "D_DESIGN_SURVEY_FLOW08_READBACK_BLOCKED_OR_INSUFFICIENT",
        "D_DESIGN_SURVEY_FLOW08_OCR_RUNTIME_BLOCKED",
        "D_DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_BLOCKED_OR_INSUFFICIENT",
        "D_DESIGN_SURVEY_PUBLIC_REGISTRY_TARGET_INSUFFICIENT",
    }:
        return "REVIEW_FACT_PACKAGE_READY"
    if evidence_state == "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER":
        return "DEFERRED_BY_SCOPE"
    return "NOT_READY_PENDING_EVIDENCE_OR_ADAPTER"


def _signal_counts(p13b_project: Mapping[str, Any], original_project: Mapping[str, Any]) -> dict[str, int]:
    p13b_states = _counts(
        record.get("overlap_signal_state")
        for record in _list(p13b_project.get("overlap_signal_records"))
        if isinstance(record, Mapping)
    )
    original_states = _counts(
        record.get("original_notice_overlap_signal_state")
        for record in _list(original_project.get("original_notice_overlap_signal_records"))
        if isinstance(record, Mapping)
    )
    return {
        "p13b_overlap_signal_record_count": len(_list(p13b_project.get("overlap_signal_records"))),
        "p13b_original_backtrace_required_count": int(p13b_states.get("ORIGINAL_NOTICE_BACKTRACE_REQUIRED", 0)),
        "p13b_a_strong_direct_signal_count": int(p13b_states.get("OVERLAP_SIGNAL_REVIEW_REQUIRED", 0)),
        "original_notice_overlap_record_count": len(_list(original_project.get("original_notice_overlap_signal_records"))),
        "original_notice_a_strong_signal_count": int(
            original_states.get("ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED", 0)
        ),
        "original_notice_fetch_blocked_count": int(original_states.get("ORIGINAL_NOTICE_FETCH_BLOCKED", 0)),
    }


def _design_survey_counts(
    design_survey_project: Mapping[str, Any],
    design_survey_stage4_project: Mapping[str, Any],
    design_survey_flow08_project: Mapping[str, Any],
    design_survey_flow08_parse_project: Mapping[str, Any],
    design_survey_public_registry_project: Mapping[str, Any],
) -> dict[str, int]:
    supplement_states = (
        design_survey_stage4_project.get("supplement_after_execution_state_counts")
        if isinstance(design_survey_stage4_project.get("supplement_after_execution_state_counts"), Mapping)
        else {}
    )
    execution_states = (
        design_survey_stage4_project.get("stage4_execution_state_counts")
        if isinstance(design_survey_stage4_project.get("stage4_execution_state_counts"), Mapping)
        else {}
    )
    return {
        "design_survey_plan_project_present": int(bool(design_survey_project)),
        "design_survey_plan_stage4_input_count": len(
            _list(design_survey_project.get("stage4_candidate_verification_input_records"))
        ),
        "design_survey_plan_verification_task_count": len(
            _list(design_survey_project.get("design_survey_verification_task_records"))
        ),
        "design_survey_stage4_project_present": int(bool(design_survey_stage4_project)),
        "design_survey_stage4_job_count": len(_list(design_survey_stage4_project.get("items"))),
        "design_survey_stage4_output_input_count": int(design_survey_stage4_project.get("stage4_input_count") or 0),
        "design_survey_stage4_provider_task_ready_count": int(
            supplement_states.get("COMPANY_FIRST_PROVIDER_TASKS_READY", 0)
        ),
        "design_survey_stage4_identity_resolved_count": int(
            supplement_states.get("COMPANY_FIRST_CERTIFICATE_RESOLVED", 0)
        ),
        "design_survey_stage4_queued_not_executed_count": int(execution_states.get("QUEUED_NOT_EXECUTED", 0)),
        "design_survey_candidate_group_resolved_count": int(
            design_survey_stage4_project.get("candidate_group_resolved_count") or 0
        ),
        "design_survey_flow08_project_present": int(bool(design_survey_flow08_project)),
        "design_survey_flow08_target_attachment_bound_count": int(
            design_survey_flow08_project.get("target_attachment_bound_count") or 0
        ),
        "design_survey_flow08_target_attachment_fetched_count": int(
            design_survey_flow08_project.get("target_attachment_fetched_count") or 0
        ),
        "design_survey_flow08_parse_project_present": int(bool(design_survey_flow08_parse_project)),
        "design_survey_flow08_attachment_parse_record_count": int(
            design_survey_flow08_parse_project.get("target_attachment_parse_record_count") or 0
        ),
        "design_survey_flow08_field_extracted_record_count": int(
            design_survey_flow08_parse_project.get("field_extracted_record_count") or 0
        ),
        "design_survey_flow08_ocr_required_record_count": int(
            design_survey_flow08_parse_project.get("ocr_required_record_count") or 0
        ),
        "design_survey_public_registry_project_present": int(bool(design_survey_public_registry_project)),
        "design_survey_public_registry_target_count": int(
            design_survey_public_registry_project.get("target_record_count") or 0
        ),
        "design_survey_public_registry_task_count": int(design_survey_public_registry_project.get("task_count") or 0),
        "design_survey_public_registry_provider_job_count": int(
            design_survey_public_registry_project.get("provider_job_count") or 0
        ),
    }


def _release_probe_targets(original_project: Mapping[str, Any]) -> list[str]:
    targets: list[str] = []
    for row in _list(original_project.get("manual_release_evidence_probe_table")):
        if isinstance(row, Mapping):
            targets.extend(str(item) for item in _list(row.get("release_evidence_source_targets")))
    return _dedupe(targets)


def _p13b_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for key in ("company_history_query_records", "bid_show_records", "overlap_signal_records", "manual_original_url_backtrace_table"):
        for record in _list(manifest.get(key)):
            if not isinstance(record, Mapping):
                continue
            project_id = str(record.get("project_id") or "")
            if not project_id:
                continue
            index.setdefault(project_id, {}).setdefault(key, []).append(dict(record))
    return index


def _original_backtrace_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for key in (
        "original_notice_fetch_records",
        "original_notice_extraction_records",
        "original_notice_overlap_signal_records",
        "manual_release_evidence_probe_table",
    ):
        for record in _list(manifest.get(key)):
            if not isinstance(record, Mapping):
                continue
            project_id = str(record.get("project_id") or "")
            if not project_id:
                continue
            index.setdefault(project_id, {}).setdefault(key, []).append(dict(record))
    return index


def _design_survey_plan_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    project_table = manifest.get("project_table") if isinstance(manifest.get("project_table"), Mapping) else {}
    for record in _list(project_table.get("records")):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        index.setdefault(project_id, {}).update(dict(record))

    stage4_inputs = (
        manifest.get("stage4_candidate_verification_inputs")
        if isinstance(manifest.get("stage4_candidate_verification_inputs"), Mapping)
        else {}
    )
    for record in _list(stage4_inputs.get("items")):
        _append_project_record(index, record, "stage4_candidate_verification_input_records")

    task_table = (
        manifest.get("design_survey_verification_task_table")
        if isinstance(manifest.get("design_survey_verification_task_table"), Mapping)
        else {}
    )
    for record in _list(task_table.get("records")):
        _append_project_record(index, record, "design_survey_verification_task_records")

    return index


def _design_survey_stage4_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in _list(manifest.get("items")):
        _append_project_record(index, record, "items")

    stage4_inputs = (
        manifest.get("stage4_candidate_verification_inputs")
        if isinstance(manifest.get("stage4_candidate_verification_inputs"), Mapping)
        else {}
    )
    for record in _list(stage4_inputs.get("items")):
        _append_project_record(index, record, "stage4_candidate_verification_input_records")

    for project in index.values():
        items = [item for item in _list(project.get("items")) if isinstance(item, Mapping)]
        stage4_input_items = [
            item for item in _list(project.get("stage4_candidate_verification_input_records")) if isinstance(item, Mapping)
        ]
        project["job_count"] = len(items)
        project["stage4_execution_state_counts"] = _counts(item.get("stage4_execution_state") for item in items)
        project["identity_resolution_state_counts"] = _counts(item.get("identity_resolution_state") for item in items)
        project["supplement_after_execution_state_counts"] = _counts(
            item.get("supplement_after_execution_state") for item in items
        )
        project["candidate_group_resolution_state_counts"] = _counts(
            item.get("candidate_group_resolution_state") for item in items
        )
        project["candidate_group_resolved_count"] = len(
            {
                (item.get("project_id"), item.get("candidate_group_id"))
                for item in items
                if item.get("candidate_group_id")
                and item.get("candidate_group_resolution_state")
                in {"RESOLVED_BY_THIS_MEMBER", "RESOLVED_BY_CONSORTIUM_MEMBER"}
            }
        )
        project["stage4_input_count"] = len(stage4_input_items)
        project["flow_08_targeted_parse_required_count"] = sum(
            1 for item in items if bool(item.get("flow_08_targeted_parse_required"))
        )
        project["fail_closed_reason_counts"] = _counts(
            reason
            for item in items
            for reason in list(item.get("fail_closed_reasons") or [])
        )
    return index


def _design_survey_flow08_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    table = (
        manifest.get("flow08_targeted_readback_table")
        if isinstance(manifest.get("flow08_targeted_readback_table"), Mapping)
        else {}
    )
    for record in _list(table.get("records")):
        _append_project_record(index, record, "flow08_targeted_readback_records")
    attachment_table = (
        manifest.get("target_attachment_table")
        if isinstance(manifest.get("target_attachment_table"), Mapping)
        else {}
    )
    for record in _list(attachment_table.get("records")):
        _append_project_record(index, record, "target_attachment_records")
    for project in index.values():
        readback_records = [
            item for item in _list(project.get("flow08_targeted_readback_records")) if isinstance(item, Mapping)
        ]
        attachment_records = [
            item for item in _list(project.get("target_attachment_records")) if isinstance(item, Mapping)
        ]
        project["flow08_readback_state_counts"] = _counts(
            item.get("flow08_readback_state") for item in readback_records
        )
        project["target_attachment_match_state_counts"] = _counts(
            item.get("target_attachment_match_state") for item in attachment_records
        )
        project["attachment_fetch_state_counts"] = _counts(
            item.get("attachment_fetch_state") for item in attachment_records
        )
        project["target_attachment_bound_count"] = sum(
            1
            for item in attachment_records
            if str(item.get("target_attachment_match_state") or "") == "TARGET_CANDIDATE_ATTACHMENT_BOUND"
        )
        project["target_attachment_fetched_count"] = sum(
            1 for item in attachment_records if str(item.get("attachment_fetch_state") or "") == "FETCHED"
        )
    return index


def _design_survey_flow08_attachment_parse_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    table = (
        manifest.get("target_attachment_parse_table")
        if isinstance(manifest.get("target_attachment_parse_table"), Mapping)
        else {}
    )
    for record in _list(table.get("records")):
        _append_project_record(index, record, "target_attachment_parse_records")
    for project in index.values():
        records = [
            item for item in _list(project.get("target_attachment_parse_records")) if isinstance(item, Mapping)
        ]
        project["target_attachment_parse_record_count"] = len(records)
        project["attachment_parse_state_counts"] = _counts(
            item.get("attachment_parse_state") for item in records
        )
        project["field_extracted_record_count"] = sum(
            1
            for item in records
            if str(item.get("attachment_parse_state") or "") == "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
        )
        project["ocr_required_record_count"] = sum(
            1 for item in records if str(item.get("attachment_parse_state") or "") == "TARGET_ATTACHMENT_OCR_REQUIRED"
        )
    return index


def _design_survey_public_registry_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    target_table = (
        manifest.get("public_registry_target_table")
        if isinstance(manifest.get("public_registry_target_table"), Mapping)
        else {}
    )
    task_table = (
        manifest.get("public_registry_task_table")
        if isinstance(manifest.get("public_registry_task_table"), Mapping)
        else {}
    )
    jobs_table = (
        manifest.get("stage4_provider_jobs")
        if isinstance(manifest.get("stage4_provider_jobs"), Mapping)
        else {}
    )
    for record in _list(target_table.get("records")):
        _append_project_record(index, record, "public_registry_target_records")
    for record in _list(task_table.get("records")):
        _append_project_record(index, record, "public_registry_task_records")
    for record in _list(jobs_table.get("jobs")):
        if not isinstance(record, Mapping):
            continue
        payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
        source_probe = payload.get("source_probe_item") if isinstance(payload.get("source_probe_item"), Mapping) else {}
        project_id = str(record.get("project_id") or source_probe.get("project_id") or "").strip()
        if project_id:
            index.setdefault(project_id, {}).setdefault("public_registry_provider_jobs", []).append(dict(record))
    for project in index.values():
        target_records = _list(project.get("public_registry_target_records"))
        task_records = _list(project.get("public_registry_task_records"))
        provider_jobs = _list(project.get("public_registry_provider_jobs"))
        project["target_record_count"] = len(target_records)
        project["task_count"] = len(task_records)
        project["provider_job_count"] = len(provider_jobs)
        project["task_type_counts"] = _counts(record.get("task_type") for record in task_records if isinstance(record, Mapping))
        project["task_state_counts"] = _counts(record.get("task_state") for record in task_records if isinstance(record, Mapping))
        project["matched_public_registry_task_count"] = sum(
            1
            for record in task_records
            if isinstance(record, Mapping)
            and str(record.get("verification_result") or record.get("public_registry_verification_result") or "")
            in {"MATCHED", "PERSON_COMPANY_CERTIFICATE_MATCHED"}
        )
        project["blocked_or_insufficient_task_count"] = sum(
            1
            for record in task_records
            if isinstance(record, Mapping)
            and str(record.get("task_state") or "").startswith(("BLOCKED", "FAIL_CLOSED"))
        )
    return index


def _append_project_record(index: dict[str, dict[str, Any]], record: Any, key: str) -> None:
    if not isinstance(record, Mapping):
        return
    project_id = str(record.get("project_id") or "").strip()
    if not project_id:
        return
    index.setdefault(project_id, {}).setdefault(key, []).append(dict(record))


def _has_original_backtrace_processed(original_project: Mapping[str, Any]) -> bool:
    return bool(
        _list(original_project.get("original_notice_fetch_records"))
        or _list(original_project.get("original_notice_extraction_records"))
        or _list(original_project.get("original_notice_overlap_signal_records"))
    )


def _original_backtrace_covers_required(original_project: Mapping[str, Any], *, required_count: int) -> bool:
    if required_count <= 0:
        return True
    # Deferred-by-budget fetch records are not evidence attempts; they keep the project pending.
    for record in _list(original_project.get("original_notice_fetch_records")):
        if not isinstance(record, Mapping):
            continue
        blockers = {str(item) for item in _list(record.get("blocker_taxonomy"))}
        if (
            str(record.get("execution_mode") or "") == "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT"
            or "max_live_original_notices_deferred" in blockers
        ):
            return False
    return len(_list(original_project.get("original_notice_overlap_signal_records"))) >= required_count


def _count_blocked_original_records(original_project: Mapping[str, Any]) -> int:
    blocked = 0
    for record in _list(original_project.get("original_notice_fetch_records")):
        if isinstance(record, Mapping) and str(record.get("fetch_state") or "") in {
            "ORIGINAL_NOTICE_FETCH_BLOCKED",
            "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
        }:
            blocked += 1
    for record in _list(original_project.get("original_notice_extraction_records")):
        if not isinstance(record, Mapping):
            continue
        blockers = {str(item) for item in _list(record.get("blocker_taxonomy"))}
        if (
            str(record.get("original_notice_extraction_state") or "") == "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"
            or "original_notice_browser_readback_required" in blockers
        ):
            blocked += 1
    return blocked


def _records_with_state(records: Any, state_key: str, state_value: str) -> list[Mapping[str, Any]]:
    return [
        record
        for record in _list(records)
        if isinstance(record, Mapping) and str(record.get(state_key) or "") == state_value
    ]


def _responsible_person(candidate: Mapping[str, Any], supplement: Mapping[str, Any] | None) -> str:
    if supplement:
        value = str(supplement.get("responsible_person_name") or supplement.get("project_manager_name") or "").strip()
        if value:
            return value
    for key in (
        "project_manager_name",
        "primary_responsible_person_name",
        "chief_supervision_engineer_name",
        "design_lead_name",
        "survey_lead_name",
    ):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def _certificate_no(candidate: Mapping[str, Any], supplement: Mapping[str, Any] | None) -> str:
    if supplement:
        value = str(
            supplement.get("certificate_no")
            or supplement.get("project_manager_certificate_no")
            or ""
        ).strip()
        if value:
            return value
    return str(candidate.get("project_manager_certificate_no") or "").strip()


def _group_members(candidate_companies: list[str], supplement: Mapping[str, Any] | None) -> list[str]:
    if supplement:
        members = _dedupe(str(item or "").strip() for item in _list(supplement.get("candidate_group_members")))
        if members:
            return members
        company = str(supplement.get("candidate_company_name") or "").strip()
        if company:
            return [company]
    return candidate_companies


def _split_companies(value: Any) -> list[str]:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[一二三四五六七八九十\d]+家[：:]\s*", "", text)
    marker_matches = list(
        re.finditer(
            r"(?:^|[,，;；、])\s*[（(]\s*(?:主|成)\s*[）)]\s*(?P<company>[^,，;；、]+)",
            text,
        )
    )
    if marker_matches:
        rows = [match.group("company") for match in marker_matches]
    else:
        rows = re.split(r"[,，;；、]", text)
    return _dedupe(_clean_company_name(row) for row in rows)


def _clean_company_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]\s*", "", text)
    text = re.sub(r"^(?:主|成)[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _company_first_inputs_by_project(path: str | Path | None) -> dict[str, Mapping[str, Any]]:
    if not path:
        return {}
    payload = _load_json(Path(path), [], "company_first_stage4_inputs_json_missing_or_invalid")
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    out: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        project_id = str(item.get("project_id") or "").strip()
        if project_id and (
            item.get("project_manager_certificate_no")
            or item.get("certificate_no")
            or item.get("person_public_id_optional")
        ):
            out[project_id] = item
    return out


def _evidence_summary(records: list[Mapping[str, Any]], blocking_reasons: list[str]) -> dict[str, Any]:
    return {
        "project_count": len(records),
        "evidence_state_counts": _counts(record.get("evidence_state") for record in records),
        "base_readiness_state_counts": _counts(record.get("base_readiness_state") for record in records),
        "evidence_grade_counts": _counts(record.get("evidence_grade") for record in records),
        "recommended_next_action_counts": _counts(record.get("recommended_next_action") for record in records),
        "a_strong_signal_project_count": sum(
            1 for record in records if str(record.get("evidence_state") or "") == "A_STRONG_TIME_OVERLAP_SIGNAL_READY"
        ),
        "original_backtrace_required_project_count": sum(
            1 for record in records if str(record.get("evidence_state") or "") == "P13B_ORIGINAL_BACKTRACE_REQUIRED"
        ),
        "design_survey_stage4_pending_project_count": sum(
            1
            for record in records
            if str(record.get("evidence_state") or "")
            in {
                "DESIGN_SURVEY_STAGE4_INPUTS_READY",
                "DESIGN_SURVEY_STAGE4_PROVIDER_TASKS_READY",
                "DESIGN_SURVEY_NAME_ENUMERATION_FALLBACK_REQUIRED",
                "DESIGN_SURVEY_FLOW08_TARGETED_PARSE_REQUIRED",
                "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
                "DESIGN_SURVEY_FLOW08_READBACK_NOT_COVERING_PROJECT",
                "DESIGN_SURVEY_FLOW08_READBACK_READY_NOT_EXECUTED",
                "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_READY",
                "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_FETCHED_PARSE_PENDING",
                "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_OCR_REQUIRED",
                "DESIGN_SURVEY_FLOW08_IDENTITY_FIELDS_EXTRACTED_REVIEW_READY",
                "DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY",
                "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_COVERING_PROJECT",
            }
        ),
        "design_survey_identity_match_project_count": sum(
            1
            for record in records
            if str(record.get("evidence_state") or "") in {
                "DESIGN_SURVEY_RESPONSIBLE_IDENTITY_MATCH_READY",
                "DESIGN_SURVEY_PUBLIC_REGISTRY_IDENTITY_MATCH_READY",
            }
        ),
        "ready_for_p13b_project_count": sum(
            1 for record in records if str(record.get("evidence_state") or "") == "READY_FOR_P13B_DATA_GGZY"
        ),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _adapter_job_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "adapter_job_count": len(records),
        "job_type_counts": _counts(record.get("job_type") for record in records),
        "job_state_counts": _counts(record.get("job_state") for record in records),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fact_package_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "stage6_fact_package_record_count": len(records),
        "stage6_fact_package_state_counts": _counts(record.get("stage6_fact_package_state") for record in records),
        "stage6_ready_count": sum(1 for record in records if bool(record.get("stage6_ready"))),
        "stage7_commercial_input_allowed_count": sum(
            1 for record in records if bool(record.get("stage7_commercial_input_allowed"))
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _batch_triage_records(records: list[Mapping[str, Any]], *, created_at: str) -> list[dict[str, Any]]:
    rows = [_batch_triage_record(record, created_at=created_at) for record in records]
    rows.sort(
        key=lambda row: (
            -int(row.get("batch_priority_score") or 0),
            str(row.get("project_id") or ""),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["batch_priority_rank"] = index
    return rows


def _batch_triage_record(record: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    bucket = _batch_triage_bucket(record)
    decision = _commercial_decision_state(bucket)
    stage6_state = str(record.get("stage6_fact_package_state") or "")
    continue_allowed = decision in {
        "CONTINUE_INTERNAL_EVIDENCE_RUN",
        "CONTINUE_INTERNAL_REVIEW_OR_STAGE6_FACT_PACKAGE",
        "PROMOTE_TO_STAGE6_FACT_PACKAGE_AND_STAGE7_GOVERNED_PREVIEW",
    }
    return {
        "batch_triage_id": _stable_id("BATCH-TRIAGE", record.get("project_id"), bucket),
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "candidate_group_members": _list(record.get("candidate_group_members")),
        "responsible_person_name": record.get("responsible_person_name"),
        "evidence_state": record.get("evidence_state"),
        "evidence_grade": record.get("evidence_grade"),
        "batch_triage_bucket": bucket,
        "commercial_decision_state": decision,
        "recommended_next_action": _batch_recommended_next_action(record, bucket),
        "batch_priority_score": _batch_priority_score(record, bucket),
        "batch_priority_rank": 0,
        "continue_allowed": continue_allowed,
        "stop_reason": "" if continue_allowed else _batch_stop_reason(record, bucket),
        "stage6_fact_package_state": stage6_state,
        "stage6_ready": stage6_state in {"A_STRONG_SIGNAL_FACT_PACKAGE_READY", "REVIEW_FACT_PACKAGE_READY"},
        "stage7_commercial_input_allowed": stage6_state == "A_STRONG_SIGNAL_FACT_PACKAGE_READY",
        "stage7_commercial_input_mode": (
            "GOVERNED_INTERNAL_PREVIEW_ONLY"
            if stage6_state == "A_STRONG_SIGNAL_FACT_PACKAGE_READY"
            else "BLOCKED_OR_REVIEW"
        ),
        "signal_counts": dict(record.get("signal_counts") or {}),
        "design_survey_adapter_counts": dict(record.get("design_survey_adapter_counts") or {}),
        "review_reasons": _list(record.get("review_reasons")),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
    }


def _batch_triage_bucket(record: Mapping[str, Any]) -> str:
    state = str(record.get("evidence_state") or "")
    if state == "A_STRONG_TIME_OVERLAP_SIGNAL_READY":
        return "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE"
    if state in {"DESIGN_SURVEY_RESPONSIBLE_IDENTITY_MATCH_READY", "DESIGN_SURVEY_PUBLIC_REGISTRY_IDENTITY_MATCH_READY"}:
        return "DESIGN_SURVEY_IDENTITY_MATCH_READY_FOR_REVIEW"
    if state == "P13B_ORIGINAL_BACKTRACE_REQUIRED":
        return "CONTINUE_ORIGINAL_BACKTRACE"
    if state == "READY_FOR_P13B_DATA_GGZY":
        return "RUN_P13B_COMPANY_HISTORY"
    if state in {"WAIT_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT", "WAIT_CERTIFICATE_OR_PUBLIC_IDENTIFIER"}:
        return "RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT"
    if state == "D_INSUFFICIENT_OR_BLOCKED_READBACK":
        return "D_BLOCKED_OR_INSUFFICIENT_REVIEW"
    if state == "P13B_NO_DIRECT_SIGNAL_REVIEW":
        return "LOW_VALUE_REVIEW_NO_CLEARANCE_CLAIM"
    if state in {"DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER", "DESIGN_SURVEY_ADAPTER_PLAN_NOT_COVERING_PROJECT"}:
        return "RUN_DESIGN_SURVEY_RESPONSIBLE_ADAPTER_PLAN"
    if state == "DESIGN_SURVEY_STAGE4_INPUTS_READY":
        return "RUN_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS"
    if state == "DESIGN_SURVEY_STAGE4_PROVIDER_TASKS_READY":
        return "EXECUTE_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS"
    if state in {
        "DESIGN_SURVEY_NAME_ENUMERATION_FALLBACK_REQUIRED",
        "DESIGN_SURVEY_FLOW08_TARGETED_PARSE_REQUIRED",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY",
        "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_COVERING_PROJECT",
    }:
        return "CONTINUE_DESIGN_SURVEY_IDENTITY_FALLBACK"
    if state in {
        "DESIGN_SURVEY_FLOW08_READBACK_NOT_COVERING_PROJECT",
        "DESIGN_SURVEY_FLOW08_READBACK_READY_NOT_EXECUTED",
        "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_READY",
        "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_FETCHED_PARSE_PENDING",
        "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_OCR_REQUIRED",
    }:
        return "CONTINUE_DESIGN_SURVEY_FLOW08_READBACK"
    if state == "DESIGN_SURVEY_FLOW08_IDENTITY_FIELDS_EXTRACTED_REVIEW_READY":
        return "CONTINUE_DESIGN_SURVEY_IDENTITY_FALLBACK"
    if state in {
        "D_DESIGN_SURVEY_TARGET_FIELDS_INSUFFICIENT",
        "D_DESIGN_SURVEY_IDENTITY_INSUFFICIENT_OR_BLOCKED",
        "D_DESIGN_SURVEY_FLOW08_READBACK_BLOCKED_OR_INSUFFICIENT",
        "D_DESIGN_SURVEY_FLOW08_OCR_RUNTIME_BLOCKED",
        "D_DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_BLOCKED_OR_INSUFFICIENT",
        "D_DESIGN_SURVEY_PUBLIC_REGISTRY_TARGET_INSUFFICIENT",
    }:
        return "D_BLOCKED_OR_INSUFFICIENT_REVIEW"
    if state == "WAIT_STAGE2_CAPTURE":
        return "FIX_STAGE2_CAPTURE"
    if state == "WAIT_RESPONSIBLE_PERSON_EXTRACTION":
        return "FIX_STAGE3_RESPONSIBLE_PERSON_EXTRACTION"
    return "BLOCKED_UPSTREAM_STAGE"


def _commercial_decision_state(bucket: str) -> str:
    if bucket == "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE":
        return "PROMOTE_TO_STAGE6_FACT_PACKAGE_AND_STAGE7_GOVERNED_PREVIEW"
    if bucket == "DESIGN_SURVEY_IDENTITY_MATCH_READY_FOR_REVIEW":
        return "CONTINUE_INTERNAL_REVIEW_OR_STAGE6_FACT_PACKAGE"
    if bucket in {
        "CONTINUE_ORIGINAL_BACKTRACE",
        "RUN_P13B_COMPANY_HISTORY",
        "RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT",
        "RUN_DESIGN_SURVEY_RESPONSIBLE_ADAPTER_PLAN",
        "RUN_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS",
        "EXECUTE_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS",
        "CONTINUE_DESIGN_SURVEY_IDENTITY_FALLBACK",
        "CONTINUE_DESIGN_SURVEY_FLOW08_READBACK",
    }:
        return "CONTINUE_INTERNAL_EVIDENCE_RUN"
    if bucket == "D_BLOCKED_OR_INSUFFICIENT_REVIEW":
        return "KEEP_INTERNAL_REVIEW_OR_MANUAL_RESOLVE"
    if bucket == "LOW_VALUE_REVIEW_NO_CLEARANCE_CLAIM":
        return "STOP_OR_PARK_WITHOUT_CLEARANCE_CLAIM"
    if bucket == "DEFER_NON_MAINLINE_ADAPTER":
        return "PARK_NON_MAINLINE_ADAPTER"
    return "FIX_UPSTREAM_EXTRACTION_OR_CAPTURE"


def _batch_recommended_next_action(record: Mapping[str, Any], bucket: str) -> str:
    if bucket == "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE":
        return "build_release_evidence_regional_adapter_plan_and_stage6_fact_package"
    if bucket == "DESIGN_SURVEY_IDENTITY_MATCH_READY_FOR_REVIEW":
        return "continue_design_survey_qualification_and_service_clock_review"
    if bucket == "CONTINUE_ORIGINAL_BACKTRACE":
        return "continue_p13b_original_notice_backtrace"
    if bucket == "RUN_P13B_COMPANY_HISTORY":
        return "run_data_ggzy_company_history_overlap_triage"
    if bucket == "RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT":
        return "run_company_first_identifier_resolution_before_p13b"
    if bucket == "RUN_DESIGN_SURVEY_RESPONSIBLE_ADAPTER_PLAN":
        return "run_design_survey_responsible_adapter_plan"
    if bucket == "RUN_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS":
        return "run_design_survey_stage4_person_company_certificate_execution"
    if bucket == "EXECUTE_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS":
        return "execute_design_survey_stage4_provider_tasks"
    if bucket == "CONTINUE_DESIGN_SURVEY_IDENTITY_FALLBACK":
        return str(record.get("recommended_next_action") or "continue_design_survey_identity_fallback")
    if bucket == "CONTINUE_DESIGN_SURVEY_FLOW08_READBACK":
        return str(record.get("recommended_next_action") or "continue_design_survey_flow08_targeted_readback")
    if bucket == "D_BLOCKED_OR_INSUFFICIENT_REVIEW":
        return "manual_review_or_retry_blocked_original_notice_backtrace_without_clearance_claim"
    if bucket == "LOW_VALUE_REVIEW_NO_CLEARANCE_CLAIM":
        return "park_or_manual_review_p13b_without_clearance_claim"
    if bucket == "DEFER_NON_MAINLINE_ADAPTER":
        return "park_until_design_survey_responsible_overlap_adapter_exists"
    if bucket == "FIX_STAGE2_CAPTURE":
        return "retry_stage2_detail_capture"
    if bucket == "FIX_STAGE3_RESPONSIBLE_PERSON_EXTRACTION":
        return "targeted_current_notice_or_attachment_readback_for_responsible_person"
    return str(record.get("recommended_next_action") or "manual_review_upstream_blocker")


def _batch_stop_reason(record: Mapping[str, Any], bucket: str) -> str:
    if bucket == "D_BLOCKED_OR_INSUFFICIENT_REVIEW":
        if str(record.get("evidence_state") or "").startswith("D_DESIGN_SURVEY_"):
            return "design_survey_identity_or_attachment_evidence_insufficient_or_blocked"
        return "release_evidence_or_original_readback_insufficient_or_blocked"
    if bucket == "LOW_VALUE_REVIEW_NO_CLEARANCE_CLAIM":
        return "p13b_no_same_person_time_window_signal_but_no_clearance_claim"
    if bucket == "DESIGN_SURVEY_IDENTITY_MATCH_READY_FOR_REVIEW":
        return ""
    if bucket == "DEFER_NON_MAINLINE_ADAPTER":
        return "design_or_survey_overlap_adapter_not_in_mainline_yet"
    if bucket == "FIX_STAGE2_CAPTURE":
        return "stage2_detail_capture_not_ready"
    if bucket == "FIX_STAGE3_RESPONSIBLE_PERSON_EXTRACTION":
        return "responsible_person_field_not_ready"
    reasons = _list(record.get("review_reasons"))
    return str(reasons[0]) if reasons else "upstream_evidence_or_adapter_not_ready"


def _batch_priority_score(record: Mapping[str, Any], bucket: str) -> int:
    base_scores = {
        "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE": 1000,
        "DESIGN_SURVEY_IDENTITY_MATCH_READY_FOR_REVIEW": 790,
        "CONTINUE_ORIGINAL_BACKTRACE": 820,
        "RUN_P13B_COMPANY_HISTORY": 760,
        "RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT": 700,
        "RUN_DESIGN_SURVEY_RESPONSIBLE_ADAPTER_PLAN": 640,
        "RUN_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS": 680,
        "EXECUTE_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS": 660,
        "CONTINUE_DESIGN_SURVEY_IDENTITY_FALLBACK": 620,
        "CONTINUE_DESIGN_SURVEY_FLOW08_READBACK": 610,
        "D_BLOCKED_OR_INSUFFICIENT_REVIEW": 430,
        "LOW_VALUE_REVIEW_NO_CLEARANCE_CLAIM": 260,
        "DEFER_NON_MAINLINE_ADAPTER": 220,
        "FIX_STAGE3_RESPONSIBLE_PERSON_EXTRACTION": 180,
        "FIX_STAGE2_CAPTURE": 120,
        "BLOCKED_UPSTREAM_STAGE": 100,
    }
    score = base_scores.get(bucket, 0)
    signal_counts = record.get("signal_counts") if isinstance(record.get("signal_counts"), Mapping) else {}
    score += min(int(signal_counts.get("p13b_original_backtrace_required_count") or 0), 5) * 8
    score += min(int(signal_counts.get("p13b_a_strong_direct_signal_count") or 0), 5) * 20
    score += min(int(signal_counts.get("original_notice_a_strong_signal_count") or 0), 5) * 20
    return score


def _batch_triage_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "batch_triage_record_count": len(records),
        "batch_triage_bucket_counts": _counts(record.get("batch_triage_bucket") for record in records),
        "commercial_decision_state_counts": _counts(record.get("commercial_decision_state") for record in records),
        "continue_internal_project_count": sum(
            1
            for record in records
            if str(record.get("commercial_decision_state") or "")
            in {
                "CONTINUE_INTERNAL_EVIDENCE_RUN",
                "CONTINUE_INTERNAL_REVIEW_OR_STAGE6_FACT_PACKAGE",
                "PROMOTE_TO_STAGE6_FACT_PACKAGE_AND_STAGE7_GOVERNED_PREVIEW",
            }
        ),
        "stop_or_park_project_count": sum(
            1
            for record in records
            if str(record.get("commercial_decision_state") or "")
            in {
                "KEEP_INTERNAL_REVIEW_OR_MANUAL_RESOLVE",
                "STOP_OR_PARK_WITHOUT_CLEARANCE_CLAIM",
                "PARK_NON_MAINLINE_ADAPTER",
                "FIX_UPSTREAM_EXTRACTION_OR_CAPTURE",
            }
        ),
        "stage6_ready_count": sum(1 for record in records if bool(record.get("stage6_ready"))),
        "stage7_commercial_input_allowed_count": sum(
            1 for record in records if bool(record.get("stage7_commercial_input_allowed"))
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _optional_manifest(*, explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> dict[str, Any]:
    if not explicit_json and not root:
        return {}
    source_paths = (
        [Path(path) for path in _split_path_values(explicit_json)]
        if explicit_json
        else [Path(path) / default_file_name for path in _split_path_values(root)]
    )
    manifests: list[Mapping[str, Any]] = []
    for source_path in source_paths:
        payload = _load_json(source_path, [], "optional_manifest_missing_or_invalid")
        source_manifest = _source_manifest(payload)
        if source_manifest:
            manifests.append(source_manifest)
    return _merge_source_manifests(manifests)


def _manifest_source_path(explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> str:
    if explicit_json:
        return ";".join(str(Path(path)) for path in _split_path_values(explicit_json))
    if root:
        return ";".join(str(Path(path) / default_file_name) for path in _split_path_values(root))
    return ""


def _merge_source_manifests(manifests: list[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for manifest in manifests:
        for key, value in manifest.items():
            if isinstance(value, list):
                existing = merged.setdefault(key, [])
                if isinstance(existing, list):
                    existing.extend(value)
                continue
            if isinstance(value, Mapping):
                existing = merged.get(key)
                merged[key] = {**(existing if isinstance(existing, Mapping) else {}), **dict(value)}
                continue
            if value not in ("", None, [], {}) or key not in merged:
                merged[key] = value
    for key, value in list(merged.items()):
        if isinstance(value, list):
            merged[key] = _dedupe_records(value)
    return merged


def _dedupe_records(records: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    indexes_by_key: dict[str, int] = {}
    for record in records:
        key = _record_identity(record)
        if key in indexes_by_key:
            out[indexes_by_key[key]] = record
            continue
        indexes_by_key[key] = len(out)
        out.append(record)
    return out


def _record_identity(record: Any) -> str:
    if isinstance(record, Mapping):
        for field in (
            "original_notice_task_id",
            "ygp_original_readback_task_id",
            "browser_original_readback_task_id",
            "design_survey_project_id",
            "stage4_input_id",
            "design_survey_verification_task_id",
            "target_attachment_parse_id",
            "job_id",
            "adapter_job_id",
            "stage6_fact_package_readiness_id",
            "batch_triage_id",
        ):
            value = str(record.get(field) or "").strip()
            if value:
                return f"{field}:{value}"
        project_id = str(record.get("project_id") or "").strip()
        source_url = str(record.get("original_notice_url") or record.get("source_url") or "").strip()
        company = str(record.get("candidate_company_name") or record.get("candidate_company") or "").strip()
        if project_id and source_url:
            return f"project_source:{project_id}|{company}|{source_url}"
    return f"fingerprint:{_fingerprint(record)}"


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _latest_autonomous_run_refs(payload: Mapping[str, Any]) -> dict[str, Any]:
    operator_actions = payload.get("operator_actions") if isinstance(payload.get("operator_actions"), Mapping) else {}
    rows = operator_actions.get("operator-autonomous-opportunity-search-runs") if isinstance(operator_actions, Mapping) else []
    if not isinstance(rows, list) or not rows:
        return {}
    latest = rows[-1] if isinstance(rows[-1], Mapping) else {}
    refs = latest.get("object_refs") if isinstance(latest.get("object_refs"), Mapping) else {}
    return dict(refs)


def _closed_by_project(closed_loop_results: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in closed_loop_results if isinstance(closed_loop_results, list) else []:
        if isinstance(row, Mapping) and row.get("project_id"):
            out[str(row.get("project_id"))] = row
    return out


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blocking_reasons.append(missing_reason)
        return {}
    return data if isinstance(data, dict) else {}


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


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"JG\d{4}-\d+(?:-\d+)?", text)
    if match:
        return match.group(0)
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _split_path_values(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[;,]", text) if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build evidence orchestration state tables for Stage1-6/P13B continuation.")
    parser.add_argument("--stage16-storage-json", required=True)
    parser.add_argument("--company-first-stage4-inputs-json", default="")
    parser.add_argument("--p13b-company-history-json", default="")
    parser.add_argument("--p13b-company-history-root", default="")
    parser.add_argument("--original-notice-backtrace-json", default="")
    parser.add_argument("--original-notice-backtrace-root", default="")
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
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evidence_orchestration_state(
        stage16_storage_json=args.stage16_storage_json,
        company_first_stage4_inputs_json=args.company_first_stage4_inputs_json or None,
        p13b_company_history_json=args.p13b_company_history_json or None,
        p13b_company_history_root=args.p13b_company_history_root or None,
        original_notice_backtrace_json=args.original_notice_backtrace_json or None,
        original_notice_backtrace_root=args.original_notice_backtrace_root or None,
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
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
    )
    output_json = (
        Path(args.output_json)
        if args.output_json
        else Path(args.output_root) / "evidence-orchestration-state-v1.json"
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "output_root": str(args.output_root),
                    "safe_to_execute": result["safe_to_execute"],
                    "summary": result["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVIDENCE_ORCHESTRATION_KIND",
    "build_evidence_orchestration_state",
]
