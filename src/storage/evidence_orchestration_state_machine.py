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
    p13b_index = _p13b_index_by_project(p13b_manifest)
    original_index = _original_backtrace_index_by_project(original_manifest)
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
            p13b_supplied=bool(p13b_manifest),
            original_supplied=bool(original_manifest),
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
    summary = {
        **evidence_table["summary"],
        "adapter_job_count": len(adapter_jobs),
        "stage6_fact_package_record_count": len(fact_package_records),
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
        "evidence_state_table": evidence_table,
        "adapter_job_table": adapter_job_table,
        "stage6_fact_package_readiness_table": fact_package_table,
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
    return result


def _evidence_record(
    *,
    candidate: Mapping[str, Any],
    closed: Mapping[str, Any],
    supplement: Mapping[str, Any] | None,
    p13b_project: Mapping[str, Any],
    original_project: Mapping[str, Any],
    p13b_supplied: bool,
    original_supplied: bool,
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
        p13b_supplied=p13b_supplied,
        original_supplied=original_supplied,
    )
    signal_counts = _signal_counts(p13b_project, original_project)
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
            "build_design_survey_responsible_overlap_adapter_or_keep_stage4_general_gap_review",
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
    p13b_supplied: bool,
    original_supplied: bool,
) -> tuple[str, str, str, list[str], str]:
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

    backtrace_required = _records_with_state(
        p13b_project.get("overlap_signal_records"),
        "overlap_signal_state",
        "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
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
    if evidence_state in {"D_INSUFFICIENT_OR_BLOCKED_READBACK", "P13B_NO_DIRECT_SIGNAL_REVIEW"}:
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


def _has_original_backtrace_processed(original_project: Mapping[str, Any]) -> bool:
    return bool(
        _list(original_project.get("original_notice_fetch_records"))
        or _list(original_project.get("original_notice_extraction_records"))
        or _list(original_project.get("original_notice_overlap_signal_records"))
    )


def _count_blocked_original_records(original_project: Mapping[str, Any]) -> int:
    blocked = 0
    for record in _list(original_project.get("original_notice_fetch_records")):
        if isinstance(record, Mapping) and str(record.get("fetch_state") or "") in {
            "ORIGINAL_NOTICE_FETCH_BLOCKED",
            "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
        }:
            blocked += 1
    for record in _list(original_project.get("original_notice_extraction_records")):
        if isinstance(record, Mapping) and str(record.get("original_notice_extraction_state") or "") == "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED":
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


def _optional_manifest(*, explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> dict[str, Any]:
    if not explicit_json and not root:
        return {}
    source_path = Path(explicit_json) if explicit_json else Path(root or "") / default_file_name
    payload = _load_json(source_path, [], "optional_manifest_missing_or_invalid")
    return dict(_source_manifest(payload))


def _manifest_source_path(explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> str:
    if explicit_json:
        return str(explicit_json)
    if root:
        return str(Path(root) / default_file_name)
    return ""


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build evidence orchestration state tables for Stage1-6/P13B continuation.")
    parser.add_argument("--stage16-storage-json", required=True)
    parser.add_argument("--company-first-stage4-inputs-json", default="")
    parser.add_argument("--p13b-company-history-json", default="")
    parser.add_argument("--p13b-company-history-root", default="")
    parser.add_argument("--original-notice-backtrace-json", default="")
    parser.add_argument("--original-notice-backtrace-root", default="")
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
