from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from stage4_verification.provider_registry import NATURAL_RESOURCE_REGISTERED_SURVEYOR


DESIGN_SURVEY_PUBLIC_REGISTRY_KIND = "design_survey_public_registry_fallback_v1_manifest"
DESIGN_SURVEY_PUBLIC_REGISTRY_VERSION = 1
DESIGN_SURVEY_PUBLIC_REGISTRY_ID = "design-survey-public-registry-fallback-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/design-survey-public-registry-fallback-v1")

PUBLIC_REGISTRY_REQUIRED_STATE = "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED"
REGISTERED_SURVEYOR_REGISTRY_URL = "https://rsurveyor.ch.mnr.gov.cn/XZSP/Classification.html"
REGISTERED_SURVEYOR_REGISTRY_BASE_URL = "https://rsurveyor.ch.mnr.gov.cn/XZSP/"
MNR_SERVICE_GUIDE_REFERENCE_URL = (
    "https://banshi.beijing.gov.cn/pubtask/task/1/110000000000/"
    "8f41b8f8-2459-4c67-bedd-06ab0ff13e33.html"
)


def build_design_survey_public_registry_fallback(
    *,
    design_survey_stage4_execution_json: str | Path | None = None,
    design_survey_stage4_execution_root: str | Path | None = None,
    flow08_stage4_inputs_json: str | Path | None = None,
    flow08_stage4_inputs_root: str | Path | None = None,
    flow08_attachment_parse_json: str | Path | None = None,
    flow08_attachment_parse_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    stage4_manifest = _optional_manifest(
        explicit_json=design_survey_stage4_execution_json,
        root=design_survey_stage4_execution_root,
        default_file_name="company-first-stage4-execution.json",
    )
    if not stage4_manifest:
        blocking_reasons.append("design_survey_stage4_execution_missing")
    flow08_inputs_manifest = _optional_manifest(
        explicit_json=flow08_stage4_inputs_json,
        root=flow08_stage4_inputs_root,
        default_file_name="stage4_candidate_verification_inputs.json",
    )
    flow08_parse_manifest = _optional_manifest(
        explicit_json=flow08_attachment_parse_json,
        root=flow08_attachment_parse_root,
        default_file_name="design-survey-flow08-target-attachment-parse-v1.json",
    )

    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    flow08_inputs = _flow08_stage4_inputs_index(flow08_inputs_manifest)
    flow08_parse_records = _flow08_parse_records_by_project(flow08_parse_manifest)

    target_records: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    provider_jobs: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []
    seen_targets: set[str] = set()

    for item in _stage4_execution_items(stage4_manifest):
        if str(item.get("supplement_after_execution_state") or "") != PUBLIC_REGISTRY_REQUIRED_STATE:
            continue
        project_id = str(item.get("project_id") or "").strip()
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue

        flow08_input = _matching_flow08_input(item, flow08_inputs)
        target = _target_record(
            item,
            flow08_input=flow08_input,
            flow08_parse_records=flow08_parse_records.get(project_id, []),
            created_at=created,
        )
        target_key = _target_key(target)
        if target_key in seen_targets:
            continue
        seen_targets.add(target_key)
        if target["target_readiness_state"] != "READY_FOR_REGISTERED_SURVEYOR_PUBLIC_REGISTRY":
            skipped_records.append(_skipped_record(target, "public_registry_target_fields_missing", created_at=created))
            target_records.append(target)
            continue
        target_records.append(target)
        natural_task = _registered_surveyor_task(target, created_at=created)
        task_records.append(natural_task)
        provider_jobs.append(_provider_job(natural_task, target, created_at=created))
        if not str(target.get("certificate_no_optional") or "").strip():
            task_records.append(_flow08_certificate_extraction_task(target, created_at=created))
        if _should_add_local_natural_resource_fallback(target):
            task_records.append(_local_natural_resource_fallback_task(target, created_at=created))

    task_table = {
        "summary": _task_summary(task_records),
        "records": task_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    target_table = {
        "summary": _target_summary(target_records),
        "records": target_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    stage4_provider_jobs = {
        "manifest_kind": "stage4_provider_jobs",
        "source_adapter_id": DESIGN_SURVEY_PUBLIC_REGISTRY_ID,
        "jobs": provider_jobs,
        "summary": {
            "job_count": len(provider_jobs),
            "provider_id_counts": _counts(job.get("provider_id") for job in provider_jobs),
            "status_counts": _counts(job.get("status") for job in provider_jobs),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = _summary(
        target_records=target_records,
        task_records=task_records,
        provider_jobs=provider_jobs,
        skipped_records=skipped_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": DESIGN_SURVEY_PUBLIC_REGISTRY_VERSION,
        "manifest_kind": DESIGN_SURVEY_PUBLIC_REGISTRY_KIND,
        "adapter_id": DESIGN_SURVEY_PUBLIC_REGISTRY_ID,
        "pipeline_stage": "DesignSurveyPublicRegistryFallbackV1",
        "manifest_id": f"DESIGN-SURVEY-PUBLIC-REG-{_fingerprint({'summary': summary, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_design_survey_stage4_execution_json": _manifest_source_path(
            design_survey_stage4_execution_json,
            design_survey_stage4_execution_root,
            "company-first-stage4-execution.json",
        ),
        "source_flow08_stage4_inputs_json": _manifest_source_path(
            flow08_stage4_inputs_json,
            flow08_stage4_inputs_root,
            "stage4_candidate_verification_inputs.json",
        ),
        "source_flow08_attachment_parse_json": _manifest_source_path(
            flow08_attachment_parse_json,
            flow08_attachment_parse_root,
            "design-survey-flow08-target-attachment-parse-v1.json",
        ),
        "public_registry_target_table": target_table,
        "public_registry_task_table": task_table,
        "stage4_provider_jobs": stage4_provider_jobs,
        "skipped_records": skipped_records,
        "summary": summary,
        "source_policy": _source_policy(),
        "scope_guardrails": _scope_guardrails(),
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "design_survey_public_registry_fallback_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "design-survey-public-registry-fallback-v1.json", result)
    _write_json(out_dir / "design-survey-public-registry-target-table.json", target_table)
    _write_json(out_dir / "design-survey-public-registry-task-table.json", task_table)
    _write_json(out_dir / "stage4_provider_jobs.json", stage4_provider_jobs)
    return result


def _target_record(
    item: Mapping[str, Any],
    *,
    flow08_input: Mapping[str, Any],
    flow08_parse_records: list[Mapping[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    project_id = str(item.get("project_id") or flow08_input.get("project_id") or "").strip()
    company = _clean_company_name(item.get("candidate_company_name") or flow08_input.get("candidate_company_name"))
    person = str(item.get("responsible_person_name") or flow08_input.get("responsible_person_name") or "").strip()
    certificate_no = str(
        item.get("source_certificate_no_optional")
        or item.get("resolved_certificate_no_optional")
        or flow08_input.get("certificate_no")
        or flow08_input.get("project_manager_certificate_no")
        or ""
    ).strip()
    evidence = flow08_input.get("flow08_current_candidate_binding_evidence")
    evidence_profile = dict(evidence) if isinstance(evidence, Mapping) else {}
    parse_profile = _best_flow08_parse_profile(flow08_parse_records)
    missing = []
    if not project_id:
        missing.append("project_id_missing")
    if not company:
        missing.append("candidate_company_name_missing")
    if not person:
        missing.append("responsible_person_name_missing")
    return {
        "public_registry_target_id": _stable_id("DESIGN-SURVEY-PUBLIC-REG-TARGET", project_id, company, person),
        "project_id": project_id,
        "project_name": str(item.get("project_name") or flow08_input.get("project_name") or ""),
        "candidate_company_name": company,
        "candidate_group_id": str(item.get("candidate_group_id") or flow08_input.get("candidate_group_id") or ""),
        "candidate_group_members": _dedupe(
            [
                *_list(item.get("candidate_group_members")),
                *_list(flow08_input.get("candidate_group_members")),
                company,
            ]
        ),
        "candidate_group_match_mode": str(
            item.get("candidate_group_match_mode") or flow08_input.get("candidate_group_match_mode") or ""
        ),
        "consortium_member_role": str(item.get("consortium_member_role") or flow08_input.get("consortium_member_role") or ""),
        "responsible_person_name": person,
        "responsible_role": str(item.get("responsible_role") or flow08_input.get("responsible_role") or "survey_mapping_project_lead"),
        "certificate_no_optional": certificate_no,
        "person_public_id_optional": str(item.get("person_public_id_optional") or flow08_input.get("person_public_id_optional") or ""),
        "source_probe_adapter_id": str(item.get("source_probe_adapter_id") or flow08_input.get("source_probe_adapter_id") or ""),
        "source_flow08_attachment_url": str(
            item.get("source_flow08_attachment_url") or flow08_input.get("source_flow08_attachment_url") or ""
        ),
        "source_flow08_attachment_snapshot_id": str(
            item.get("source_flow08_attachment_snapshot_id")
            or flow08_input.get("source_flow08_attachment_snapshot_id")
            or evidence_profile.get("attachment_snapshot_id_optional")
            or ""
        ),
        "flow08_current_candidate_binding_evidence": evidence_profile,
        "flow08_attachment_parse_profile": parse_profile,
        "stage4_execution_ref": {
            "job_id": item.get("job_id", ""),
            "provider_id": item.get("provider_id", ""),
            "stage4_execution_state": item.get("stage4_execution_state", ""),
            "identity_resolution_state": item.get("identity_resolution_state", ""),
            "supplement_after_execution_state": item.get("supplement_after_execution_state", ""),
            "fail_closed_reasons": _list(item.get("fail_closed_reasons")),
        },
        "target_readiness_state": (
            "READY_FOR_REGISTERED_SURVEYOR_PUBLIC_REGISTRY"
            if not missing
            else "BLOCKED_PUBLIC_REGISTRY_TARGET_FIELDS_MISSING"
        ),
        "missing_required_fields": missing,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _registered_surveyor_task(target: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    return {
        "public_registry_task_id": _stable_id(
            "DESIGN-SURVEY-PUBLIC-REG-TASK",
            target.get("project_id"),
            target.get("candidate_company_name"),
            target.get("responsible_person_name"),
            "registered_surveyor",
        ),
        "project_id": target.get("project_id", ""),
        "project_name": target.get("project_name", ""),
        "candidate_company_name": target.get("candidate_company_name", ""),
        "candidate_group_id": target.get("candidate_group_id", ""),
        "candidate_group_members": _list(target.get("candidate_group_members")),
        "responsible_person_name": target.get("responsible_person_name", ""),
        "responsible_role": target.get("responsible_role", ""),
        "task_type": "NATURAL_RESOURCE_REGISTERED_SURVEYOR_PERSON_COMPANY_MATCH",
        "task_state": "PLAN_ONLY_ENTRY_NEEDS_LIVE_VERIFY",
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "source_family": "natural_resource_registered_surveyor_public_registry",
        "source_entry": _registered_surveyor_source_entry(),
        "query_fields": {
            "person_name": target.get("responsible_person_name", ""),
            "registered_unit_or_candidate_company": target.get("candidate_company_name", ""),
            "certificate_no_optional": target.get("certificate_no_optional", ""),
            "candidate_group_members": _list(target.get("candidate_group_members")),
        },
        "success_fields": [
            "person_name",
            "registered_unit_name",
            "certificate_no_or_registration_no",
            "certificate_type",
            "registration_status",
            "registration_valid_from_optional",
            "registration_valid_until_optional",
            "source_url_or_snapshot_id",
        ],
        "matching_policy": {
            "person_name_and_registered_unit_required": True,
            "certificate_no_match_strengthens_evidence": True,
            "candidate_group_match_mode": target.get("candidate_group_match_mode", ""),
            "name_only_is_not_final_proof": True,
            "not_found_is_review_not_negative_fact": True,
        },
        "evidence_gate": {
            "requires_public_page_or_snapshot": True,
            "entry_reachability_is_not_field_success": True,
            "flow08_dossier_is_current_binding_only_not_public_registration_proof": True,
        },
        "recommended_next_action": "execute_registered_surveyor_public_registry_readback_or_manual_public_snapshot",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow08_certificate_extraction_task(target: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    evidence = target.get("flow08_current_candidate_binding_evidence")
    evidence_profile = dict(evidence) if isinstance(evidence, Mapping) else {}
    parse_profile = dict(target.get("flow08_attachment_parse_profile") or {})
    return {
        "public_registry_task_id": _stable_id(
            "DESIGN-SURVEY-PUBLIC-REG-TASK",
            target.get("project_id"),
            target.get("candidate_company_name"),
            target.get("responsible_person_name"),
            "flow08_certificate_extraction",
        ),
        "project_id": target.get("project_id", ""),
        "project_name": target.get("project_name", ""),
        "candidate_company_name": target.get("candidate_company_name", ""),
        "responsible_person_name": target.get("responsible_person_name", ""),
        "task_type": "FLOW08_REGISTERED_SURVEYOR_CERTIFICATE_FIELD_EXTRACTION",
        "task_state": "PLAN_ONLY_LOCAL_EVIDENCE_EXTRACTION_REQUIRED",
        "source_family": "current_flow08_person_dossier_certificate_or_credential_pages",
        "query_fields": {
            "attachment_snapshot_id": target.get("source_flow08_attachment_snapshot_id", ""),
            "attachment_url": target.get("source_flow08_attachment_url", ""),
            "document_work_path": parse_profile.get("document_work_path", "")
            or evidence_profile.get("document_work_path", ""),
            "extraction_json_path": parse_profile.get("extraction_json_path", "")
            or evidence_profile.get("extraction_json_path", ""),
            "planned_page_ranges": evidence_profile.get("planned_page_ranges", ""),
            "person_name": target.get("responsible_person_name", ""),
            "candidate_company_name": target.get("candidate_company_name", ""),
        },
        "success_fields": [
            "registered_surveyor_certificate_no_if_present",
            "certificate_type_or_title_text",
            "redacted_evidence_page_refs",
            "source_attachment_snapshot_id",
        ],
        "matching_policy": {
            "extract_only_from_current_target_dossier_window": True,
            "redact_sensitive_identity_social_security_fields": True,
            "extracted_certificate_requires_public_registry_replay": True,
        },
        "recommended_next_action": "extract_registered_surveyor_certificate_from_flow08_dossier_then_replay_public_registry",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _local_natural_resource_fallback_task(target: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    return {
        "public_registry_task_id": _stable_id(
            "DESIGN-SURVEY-PUBLIC-REG-TASK",
            target.get("project_id"),
            target.get("candidate_company_name"),
            target.get("responsible_person_name"),
            "local_natural_resource_registry",
        ),
        "project_id": target.get("project_id", ""),
        "project_name": target.get("project_name", ""),
        "candidate_company_name": target.get("candidate_company_name", ""),
        "responsible_person_name": target.get("responsible_person_name", ""),
        "task_type": "LOCAL_NATURAL_RESOURCE_OR_DESIGN_SURVEY_PERSONNEL_REGISTRY_MATCH",
        "task_state": "PLAN_ONLY_AFTER_NATIONAL_SOURCE_BLOCKED_OR_UNCLEAR",
        "source_family": "project_or_registration_region_natural_resource_public_source",
        "query_fields": {
            "person_name": target.get("responsible_person_name", ""),
            "candidate_company_name": target.get("candidate_company_name", ""),
            "certificate_no_optional": target.get("certificate_no_optional", ""),
        },
        "success_fields": [
            "person_name",
            "registered_unit_name",
            "certificate_no_or_public_person_id",
            "source_url_or_snapshot_id",
        ],
        "matching_policy": {
            "only_run_after_national_registered_surveyor_source_blocked_or_ambiguous": True,
            "project_location_source_discovery_required_before_local_query": True,
            "not_found_is_review_not_negative_fact": True,
        },
        "recommended_next_action": "discover_project_or_registration_region_natural_resource_public_source_if_national_source_blocked",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _provider_job(task: Mapping[str, Any], target: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    payload = {
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "provider_role": "registered_surveyor_person_company_certificate_identity",
        "target": {
            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
            "candidate_company_name": target.get("candidate_company_name", ""),
            "responsible_person_name": target.get("responsible_person_name", ""),
            "certificate_no_optional": target.get("certificate_no_optional", ""),
            "person_public_id_optional": target.get("person_public_id_optional", ""),
            "responsible_role": target.get("responsible_role", ""),
            "source_entry": _registered_surveyor_source_entry(),
        },
        "source_probe_item": {
            "project_id": target.get("project_id", ""),
            "project_name": target.get("project_name", ""),
            "source_probe_adapter_id": DESIGN_SURVEY_PUBLIC_REGISTRY_ID,
            "source_flow08_attachment_url": target.get("source_flow08_attachment_url", ""),
            "source_flow08_attachment_snapshot_id": target.get("source_flow08_attachment_snapshot_id", ""),
        },
        "source_public_registry_task": dict(task),
        "source_stage4_execution_ref": dict(target.get("stage4_execution_ref") or {}),
    }
    return {
        "job_id": _stable_id(
            "STAGE4-PUBLIC-REG-JOB",
            target.get("project_id"),
            target.get("candidate_company_name"),
            target.get("responsible_person_name"),
        ),
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "provider_role": "registered_surveyor_person_company_certificate_identity",
        "payload": payload,
        "status": "QUEUED_NOT_EXECUTED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _registered_surveyor_source_entry() -> dict[str, Any]:
    return {
        "source_name": "注册测绘师注册管理系统/注册人员查询",
        "source_authority": "自然资源部测绘地理信息管理相关国家级垂管系统",
        "source_family": "natural_resource_registered_surveyor_public_registry",
        "entry_url": REGISTERED_SURVEYOR_REGISTRY_URL,
        "fallback_entry_url": REGISTERED_SURVEYOR_REGISTRY_BASE_URL,
        "service_guide_reference_url": MNR_SERVICE_GUIDE_REFERENCE_URL,
        "entry_verification_state": "ENTRY_DISCOVERED_NEEDS_LIVE_PAGE_VERIFY",
        "runtime_adapter_state": "PLANNED_NOT_IMPLEMENTED",
        "query_miss_is_not_clearance": True,
    }


def _source_policy() -> dict[str, Any]:
    return {
        "primary_source": "natural_resource_registered_surveyor_public_registry",
        "why_not_jzsc_only": "construction_market_platform_does_not_reliably_cover_registered_surveyor_credentials",
        "flow08_dossier_role": "current_candidate_binding_and_certificate_clue_only",
        "local_source_fallback": "only_after_national_registered_surveyor_source_blocked_or_ambiguous",
        "entry_live_verification_required": True,
        "query_miss_is_not_clearance": True,
    }


def _scope_guardrails() -> dict[str, Any]:
    return {
        "does_not_apply_construction_project_manager_release_rule": True,
        "does_not_reparse_flow08_by_default": True,
        "no_name_only_final_proof": True,
        "public_registration_replay_required_after_flow08_dossier": True,
        "entry_reachability_is_not_field_success": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _stage4_execution_items(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _flow08_stage4_inputs_index(manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    items: list[Any] = []
    if isinstance(manifest.get("items"), list):
        items = list(manifest.get("items") or [])
    nested = manifest.get("stage4_candidate_verification_inputs")
    if isinstance(nested, Mapping) and isinstance(nested.get("items"), list):
        items.extend(list(nested.get("items") or []))
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = dict(item)
        for key in _flow08_match_keys(record):
            index.setdefault(key, []).append(record)
    return index


def _matching_flow08_input(item: Mapping[str, Any], index: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    for key in _flow08_match_keys(item):
        records = index.get(key) or []
        if records:
            return dict(records[0])
    project_id = str(item.get("project_id") or "").strip()
    person = str(item.get("responsible_person_name") or "").strip()
    fallback_key = f"{project_id}||{person}"
    records = index.get(fallback_key) or []
    return dict(records[0]) if records else {}


def _flow08_match_keys(record: Mapping[str, Any]) -> list[str]:
    project_id = str(record.get("project_id") or "").strip()
    company = _clean_company_name(record.get("candidate_company_name"))
    person = str(record.get("responsible_person_name") or "").strip()
    keys = []
    if project_id and company and person:
        keys.append(f"{project_id}|{company}|{person}")
    if project_id and person:
        keys.append(f"{project_id}||{person}")
    return keys


def _flow08_parse_records_by_project(manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    table = manifest.get("target_attachment_parse_table") if isinstance(manifest.get("target_attachment_parse_table"), Mapping) else {}
    out: dict[str, list[dict[str, Any]]] = {}
    for record in _list(table.get("records")):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out.setdefault(project_id, []).append(dict(record))
    return out


def _best_flow08_parse_profile(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    record = dict(records[0])
    dossier = record.get("person_dossier_evidence") if isinstance(record.get("person_dossier_evidence"), Mapping) else {}
    return {
        "target_attachment_parse_id": record.get("target_attachment_parse_id", ""),
        "attachment_parse_state": record.get("attachment_parse_state", ""),
        "attachment_snapshot_id_optional": record.get("attachment_snapshot_id_optional", ""),
        "document_sha256": record.get("document_sha256", ""),
        "document_work_path": record.get("document_work_path", ""),
        "extraction_json_path": record.get("extraction_json_path", ""),
        "person_dossier_state": dossier.get("person_dossier_state", ""),
        "planned_page_ranges": dossier.get("planned_page_ranges", ""),
        "current_project_binding_state": dossier.get("current_project_binding_state", ""),
    }


def _should_add_local_natural_resource_fallback(target: Mapping[str, Any]) -> bool:
    text = " ".join(
        [
            str(target.get("project_name") or ""),
            str(target.get("responsible_role") or ""),
        ]
    )
    return any(keyword in text for keyword in ("测绘", "规划", "勘测", "自然资源", "国土空间"))


def _target_key(target: Mapping[str, Any]) -> str:
    return "|".join(
        [
            str(target.get("project_id") or ""),
            str(target.get("candidate_company_name") or ""),
            str(target.get("responsible_person_name") or ""),
        ]
    )


def _target_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "target_record_count": len(records),
        "project_count": len({record.get("project_id") for record in records}),
        "candidate_company_count": len({record.get("candidate_company_name") for record in records}),
        "target_readiness_state_counts": _counts(record.get("target_readiness_state") for record in records),
        "with_certificate_count": sum(1 for record in records if str(record.get("certificate_no_optional") or "").strip()),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _task_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "task_count": len(records),
        "task_type_counts": _counts(record.get("task_type") for record in records),
        "task_state_counts": _counts(record.get("task_state") for record in records),
        "primary_registered_surveyor_task_count": sum(
            1
            for record in records
            if record.get("task_type") == "NATURAL_RESOURCE_REGISTERED_SURVEYOR_PERSON_COMPANY_MATCH"
        ),
        "flow08_certificate_extraction_task_count": sum(
            1 for record in records if record.get("task_type") == "FLOW08_REGISTERED_SURVEYOR_CERTIFICATE_FIELD_EXTRACTION"
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    target_records: list[Mapping[str, Any]],
    task_records: list[Mapping[str, Any]],
    provider_jobs: list[Mapping[str, Any]],
    skipped_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    task_summary = _task_summary(task_records)
    return {
        "target_record_count": len(target_records),
        "ready_target_count": sum(
            1
            for record in target_records
            if record.get("target_readiness_state") == "READY_FOR_REGISTERED_SURVEYOR_PUBLIC_REGISTRY"
        ),
        "task_count": len(task_records),
        "provider_job_count": len(provider_jobs),
        "primary_registered_surveyor_task_count": task_summary["primary_registered_surveyor_task_count"],
        "flow08_certificate_extraction_task_count": task_summary["flow08_certificate_extraction_task_count"],
        "skipped_record_count": len(skipped_records),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _skipped_record(target: Mapping[str, Any], reason: str, *, created_at: str) -> dict[str, Any]:
    return {
        "project_id": target.get("project_id", ""),
        "project_name": target.get("project_name", ""),
        "candidate_company_name": target.get("candidate_company_name", ""),
        "responsible_person_name": target.get("responsible_person_name", ""),
        "skip_reason": reason,
        "missing_required_fields": _list(target.get("missing_required_fields")),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _optional_manifest(
    *,
    explicit_json: str | Path | None,
    root: str | Path | None,
    default_file_name: str,
) -> dict[str, Any]:
    path = Path(explicit_json) if explicit_json else (Path(root) / default_file_name if root else None)
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        return {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    return dict(manifest)


def _manifest_source_path(explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> str:
    if explicit_json:
        return str(explicit_json)
    if root:
        return str(Path(root) / default_file_name)
    return ""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
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


def _clean_company_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]\s*", "", text)
    text = re.sub(r"^(?:主|成)[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"JG\d{4}-\d+(?:-\d+)?", text)
    if match:
        return match.group(0)
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint(parts)[:20]}"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_project_ids(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；\s]+", value or "") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build design/survey registered-surveyor public-registry fallback tasks after Flow08/JZSC miss."
    )
    parser.add_argument("--design-survey-stage4-execution-json", default="")
    parser.add_argument("--design-survey-stage4-execution-root", default="")
    parser.add_argument("--flow08-stage4-inputs-json", default="")
    parser.add_argument("--flow08-stage4-inputs-root", default="")
    parser.add_argument("--flow08-attachment-parse-json", default="")
    parser.add_argument("--flow08-attachment-parse-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args(argv)

    result = build_design_survey_public_registry_fallback(
        design_survey_stage4_execution_json=args.design_survey_stage4_execution_json or None,
        design_survey_stage4_execution_root=args.design_survey_stage4_execution_root or None,
        flow08_stage4_inputs_json=args.flow08_stage4_inputs_json or None,
        flow08_stage4_inputs_root=args.flow08_stage4_inputs_root or None,
        flow08_attachment_parse_json=args.flow08_attachment_parse_json or None,
        flow08_attachment_parse_root=args.flow08_attachment_parse_root or None,
        output_root=args.output_root,
        project_ids=_parse_project_ids(args.project_ids),
        created_at=args.created_at or None,
    )
    if args.output_json:
        _write_json(Path(args.output_json), result)
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
    "DESIGN_SURVEY_PUBLIC_REGISTRY_ID",
    "DESIGN_SURVEY_PUBLIC_REGISTRY_KIND",
    "REGISTERED_SURVEYOR_REGISTRY_URL",
    "build_design_survey_public_registry_fallback",
]
