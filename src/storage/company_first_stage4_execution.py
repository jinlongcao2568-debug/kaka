from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage4_verification.highway_market_personnel import (
    HIGHWAY_MARKET_PERSONNEL_ADAPTER_ID,
    HIGHWAY_MARKET_PERSON_INDEX_URL,
    query_highway_market_person_title,
)
from stage4_verification.provider_registry import JZSC_PERSON_IDENTITY
from stage4_verification.service import Stage4Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


COMPANY_FIRST_STAGE4_EXECUTION_MANIFEST_KIND = "company_first_stage4_execution_manifest"
COMPANY_FIRST_STAGE4_EXECUTION_VERSION = 1
COMPANY_FIRST_STAGE4_EXECUTION_ADAPTER_ID = "company-first-stage4-execution-v1"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-supplement-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v1")


BrowserRunner = Callable[[Mapping[str, Any]], Mapping[str, Any]]
HighwayMarketRunner = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def build_company_first_stage4_execution(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    provider_jobs_json: str | Path | None = None,
    stage4_inputs_json: str | Path | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    candidate_group_ids: list[str] | tuple[str, ...] = (),
    execute: bool = False,
    max_personnel_pages: int = 12,
    max_project_pages: int = 3,
    personnel_retry_attempts: int = 2,
    capture_personnel_project_records: bool = False,
    browser_runner: BrowserRunner | None = None,
    highway_market_runner: HighwayMarketRunner | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(input_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    jobs_path = Path(provider_jobs_json) if provider_jobs_json else in_root / "stage4_provider_jobs.json"
    jobs_payload = _load_json(jobs_path)
    blocking_reasons: list[str] = []
    stage4_inputs_path = Path(stage4_inputs_json) if stage4_inputs_json else None
    stage4_inputs_payload = _load_json(stage4_inputs_path) if stage4_inputs_path else {}
    if not jobs_payload and not stage4_inputs_payload:
        blocking_reasons.append("stage4_provider_jobs_missing")

    selected_projects = {_project_code(value) for value in project_ids if _project_code(value)}
    selected_candidate_groups = {str(value).strip() for value in candidate_group_ids if str(value).strip()}
    jobs = [*_jobs(jobs_payload), *_jobs_from_stage4_inputs(stage4_inputs_payload)]
    if selected_projects:
        jobs = [
            job
            for job in jobs
            if _project_code(((job.get("payload") or {}).get("source_probe_item") or {}).get("project_id"))
            in selected_projects
        ]
    if selected_candidate_groups:
        jobs = [
            job
            for job in jobs
            if _candidate_group_id_from_job(job) in selected_candidate_groups
        ]

    repository = _repository(
        storage_path=out_root / "stage4-execution-storage.json",
        object_storage_path=out_root / "objects",
    )
    service = Stage4Service()
    items = [
        _execute_job(
            job=job,
            service=service,
            repository=repository,
            execute=execute,
            max_personnel_pages=max_personnel_pages,
            max_project_pages=max_project_pages,
            personnel_retry_attempts=personnel_retry_attempts,
            capture_personnel_project_records=capture_personnel_project_records,
            browser_runner=browser_runner,
            highway_market_runner=highway_market_runner,
            created_at=created,
        )
        for job in jobs
    ]
    items = _apply_candidate_group_resolution(items)
    stage4_inputs = _stage4_inputs(items, created_at=created)
    summary = _summary(items, stage4_inputs, blocking_reasons)
    manifest = {
        "manifest_version": COMPANY_FIRST_STAGE4_EXECUTION_VERSION,
        "manifest_kind": COMPANY_FIRST_STAGE4_EXECUTION_MANIFEST_KIND,
        "adapter_id": COMPANY_FIRST_STAGE4_EXECUTION_ADAPTER_ID,
        "pipeline_stage": "CompanyFirstStage4Execution",
        "manifest_id": f"COMPANY-FIRST-STAGE4-{_fingerprint({'items': items, 'summary': summary})[:16]}",
        "created_at": created,
        "source_input_root": str(in_root),
        "source_stage4_provider_jobs_json": str(jobs_path),
        "source_stage4_inputs_json_optional": str(stage4_inputs_path or ""),
        "execute_enabled": bool(execute),
        "max_personnel_pages": max_personnel_pages,
        "max_project_pages": max_project_pages,
        "personnel_retry_attempts": personnel_retry_attempts,
        "capture_personnel_project_records": bool(capture_personnel_project_records),
        "items": items,
        "project_sample_items": items,
        "stage4_candidate_verification_inputs": stage4_inputs,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": bool(execute),
            "stage4_live_provider_enabled": bool(execute),
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
            "no_name_only_final_proof": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "company_first_stage4_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": bool(execute),
            "download_enabled": False,
            "fetch_public_urls_enabled": bool(execute),
            "stage4_live_provider_enabled": bool(execute),
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    (out_root / "company-first-stage4-execution.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "stage4_candidate_verification_inputs.json").write_text(
        json.dumps(stage4_inputs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _execute_job(
    *,
    job: Mapping[str, Any],
    service: Stage4Service,
    repository: ObjectStorageRepository,
    execute: bool,
    max_personnel_pages: int,
    max_project_pages: int,
    personnel_retry_attempts: int,
    capture_personnel_project_records: bool,
    browser_runner: BrowserRunner | None,
    highway_market_runner: HighwayMarketRunner | None,
    created_at: str,
) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    target = dict(payload.get("target") or {})
    source_probe_item = dict(payload.get("source_probe_item") or {})
    project_id = str(source_probe_item.get("project_id") or "")
    project_name = str(source_probe_item.get("project_name") or "")
    company = _normalize_company_name(target.get("candidate_company_name"))
    person = str(target.get("responsible_person_name") or "").strip()
    certificate_no = str(target.get("certificate_no_optional") or "").strip()
    candidate_group_members = _candidate_group_members(payload=payload, target=target)
    candidate_group_id = str(payload.get("candidate_group_id") or target.get("candidate_group_id") or "").strip()
    required_registration_category = _required_registration_category(target)
    base = {
        "job_id": job.get("job_id", ""),
        "provider_id": job.get("provider_id", ""),
        "provider_role": job.get("provider_role", ""),
        "project_id": project_id,
        "project_name": project_name,
        "flow_no": "07",
        "flow_title": "中标候选人公示",
        "source_07_detail_path": source_probe_item.get("source_07_detail_path", ""),
        "candidate_company_name": company,
        "responsible_person_name": person,
        "source_certificate_no_optional": certificate_no,
        "candidate_group_id": candidate_group_id,
        "candidate_group_order": payload.get("candidate_group_order") or target.get("candidate_group_order") or "",
        "candidate_group_members": candidate_group_members,
        "candidate_group_match_mode": "ANY_CONSORTIUM_MEMBER" if candidate_group_id and len(candidate_group_members) > 1 else "SINGLE_COMPANY",
        "required_registration_category_optional": required_registration_category,
        "consortium_member_role": payload.get("consortium_member_role") or target.get("consortium_member_role") or "",
        "candidate_group_resolution_state": "NOT_EVALUATED",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "created_at": created_at,
    }
    if job.get("provider_id") != JZSC_PERSON_IDENTITY:
        return {
            **base,
            "stage4_execution_state": "SKIPPED_UNSUPPORTED_PROVIDER",
            "identity_resolution_state": "NOT_RUN",
            "supplement_after_execution_state": "STAGE4_PROVIDER_SKIPPED",
            "stage4_readiness_state": "STAGE4_BLOCKED_UNSUPPORTED_PROVIDER",
            "next_actions": ["KEEP_PROVIDER_JOB_FOR_SUPPORTED_HANDLER"],
            "fail_closed_reasons": ["unsupported_provider_id"],
        }
    if not company or not person:
        return {
            **base,
            "stage4_execution_state": "SKIPPED_TARGET_FIELDS_MISSING",
            "identity_resolution_state": "NOT_RUN",
            "supplement_after_execution_state": "COMPANY_FIRST_TARGET_FIELDS_MISSING",
            "stage4_readiness_state": "STAGE4_BLOCKED_TARGET_FIELDS_MISSING",
            "next_actions": ["RETURN_TO_RESPONSIBLE_PERSON_EARLY_PROBE_OR_FLOW_08_TARGETED_PARSE"],
            "fail_closed_reasons": ["candidate_company_or_responsible_person_missing"],
        }
    if not execute:
        return {
            **base,
            "stage4_execution_state": "QUEUED_NOT_EXECUTED",
            "identity_resolution_state": "NOT_RUN",
            "supplement_after_execution_state": "COMPANY_FIRST_PROVIDER_TASKS_READY",
            "stage4_readiness_state": "STAGE4_PROVIDER_TASKS_READY_NOT_EXECUTED",
            "next_actions": ["EXECUTE_AUTHORIZED_COMPANY_FIRST_PROVIDER_TASKS"],
            "fail_closed_reasons": [],
        }

    highway_market_readback: dict[str, Any] = {}
    prior_stage4_fail_closed_reasons: list[Any] = []
    stage4_result: dict[str, Any]
    if _should_try_highway_market(
        project_name=project_name,
        company=company,
        person=person,
        certificate_no=certificate_no,
        responsible_role=str(target.get("responsible_role") or ""),
        priority_class=str(target.get("opportunity_priority_class") or ""),
    ):
        highway_market_readback = _run_highway_market_readback(
            runner=highway_market_runner,
            project_id=project_id,
            project_name=project_name,
            company=company,
            person=person,
            certificate_no=certificate_no,
            responsible_role=str(target.get("responsible_role") or ""),
            candidate_group_id=candidate_group_id,
        )
        if _highway_market_resolved(highway_market_readback):
            stage4_result = _stage4_result_from_highway_readback(
                highway_market_readback,
                prior_stage4_fail_closed_reasons=[],
            )
            state = _post_execution_state(stage4_result)
        else:
            stage4_result, state = _run_jzsc_company_first(
                job=job,
                service=service,
                repository=repository,
                company=company,
                person=person,
                certificate_no=certificate_no,
                required_registration_category=required_registration_category,
                max_personnel_pages=max_personnel_pages,
                max_project_pages=max_project_pages,
                personnel_retry_attempts=personnel_retry_attempts,
                capture_personnel_project_records=capture_personnel_project_records,
                browser_runner=browser_runner,
            )
            prior_stage4_fail_closed_reasons = list(stage4_result.get("fail_closed_reasons") or [])
            stage4_result["highway_market_readback"] = highway_market_readback
            stage4_result["browser_nonfatal_diagnostics"] = [
                *list(stage4_result.get("browser_nonfatal_diagnostics") or []),
                f"highway_market_precheck_not_resolved:{highway_market_readback.get('query_state', '')}",
            ]
    else:
        stage4_result, state = _run_jzsc_company_first(
            job=job,
            service=service,
            repository=repository,
            company=company,
            person=person,
            certificate_no=certificate_no,
            required_registration_category=required_registration_category,
            max_personnel_pages=max_personnel_pages,
            max_project_pages=max_project_pages,
            personnel_retry_attempts=personnel_retry_attempts,
            capture_personnel_project_records=capture_personnel_project_records,
            browser_runner=browser_runner,
        )
        prior_stage4_fail_closed_reasons = list(stage4_result.get("fail_closed_reasons") or [])
    carrier = dict(stage4_result.get("personnel_carrier") or {})
    resolved_certificate = carrier.get("project_manager_certificate_no_optional") or stage4_result.get(
        "resolved_public_identifier_optional", ""
    )
    certificate_category_review_required = bool(
        state.get("certificate_category_review_required")
        or (
            "DESIGN_SURVEY" in str(target.get("opportunity_priority_class") or "").upper()
            and resolved_certificate
        )
    )
    return {
        **base,
        "stage4_execution_state": stage4_result.get("executor_state", ""),
        "readback_state": stage4_result.get("readback_state", ""),
        "identity_resolution_state": stage4_result.get("identity_resolution_state", ""),
        "verification_result": carrier.get("verification_result", ""),
        "matched_company_name_optional": stage4_result.get("matched_company_name_optional", ""),
        "matched_company_public_id_optional": stage4_result.get("matched_company_public_id_optional", ""),
        "resolved_certificate_no_optional": resolved_certificate,
        "person_public_id_optional": carrier.get("person_public_id_optional", ""),
        "registered_unit_name_optional": carrier.get("project_manager_registered_unit_optional", ""),
        "company_personnel_source_url": stage4_result.get("company_personnel_source_url", ""),
        "company_personnel_source_snapshot_id": stage4_result.get("company_personnel_source_snapshot_id", ""),
        "personnel_project_source_url": stage4_result.get("personnel_project_source_url", ""),
        "personnel_project_source_snapshot_id": stage4_result.get("personnel_project_source_snapshot_id", ""),
        "stage4_resolution_route": stage4_result.get("route") or stage4_result.get("adapter_id", ""),
        "highway_market_fallback_attempted": bool(highway_market_readback),
        "highway_market_readback_state": highway_market_readback.get("readback_state", ""),
        "highway_market_query_state": highway_market_readback.get("query_state", ""),
        "highway_market_readback": highway_market_readback,
        "prior_jzsc_fail_closed_reasons": prior_stage4_fail_closed_reasons
        if highway_market_readback
        else [],
        "rendered_company_personnel_row_count": stage4_result.get("rendered_company_personnel_row_count", 0),
        "rendered_personnel_project_row_count": stage4_result.get("rendered_personnel_project_row_count", 0),
        "browser_runner_id": stage4_result.get("browser_runner_id", ""),
        "live_browser_executed": bool(stage4_result.get("live_browser_executed") or execute),
        "stage4_live_provider_executed": bool(execute),
        "browser_attempts": stage4_result.get("browser_attempts", []),
        "browser_nonfatal_diagnostics": stage4_result.get("browser_nonfatal_diagnostics", []),
        "fail_closed_reasons": stage4_result.get("fail_closed_reasons", []),
        "supplement_after_execution_state": state["supplement_after_execution_state"],
        "stage4_readiness_state": state["stage4_readiness_state"],
        "next_actions": state["next_actions"],
        "risk_escalation_state": state["risk_escalation_state"],
        "flow_08_targeted_parse_required": state["flow_08_targeted_parse_required"],
        "certificate_category_review_required": certificate_category_review_required,
        "public_registration_match_basis": state.get("public_registration_match_basis", ""),
        "field_level_public_registration_match": _field_level_public_registration_match(stage4_result),
        "no_name_only_final_proof": True,
    }


def _run_jzsc_company_first(
    *,
    job: Mapping[str, Any],
    service: Stage4Service,
    repository: ObjectStorageRepository,
    company: str,
    person: str,
    certificate_no: str,
    required_registration_category: str,
    max_personnel_pages: int,
    max_project_pages: int,
    personnel_retry_attempts: int,
    capture_personnel_project_records: bool,
    browser_runner: BrowserRunner | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        stage4_result = dict(
            service.run_jzsc_company_first_browser_execution(
                _parsed_context(job),
                target_company_name=company,
                target_project_manager_name=person,
                target_identifier=certificate_no or None,
                repository=repository,
                browser_runner=browser_runner,
                max_personnel_pages=max_personnel_pages,
                max_project_pages=max_project_pages,
                personnel_retry_attempts=personnel_retry_attempts,
                capture_personnel_project_records=capture_personnel_project_records,
                required_registration_category=required_registration_category or None,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive boundary
        stage4_result = {
            "executor_state": "FAIL_CLOSED",
            "readback_state": "REVIEW_REQUIRED",
            "identity_resolution_state": "REVIEW_REQUIRED",
            "fail_closed_reasons": [f"stage4_company_first_execution_exception:{exc}"],
            "customer_sellable_evidence_ready": False,
        }
    return stage4_result, _post_execution_state(stage4_result)


def _post_execution_state(stage4_result: Mapping[str, Any]) -> dict[str, Any]:
    carrier = dict(stage4_result.get("personnel_carrier") or {})
    if carrier.get("verification_result") == "MATCHED":
        return {
            "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
            "stage4_readiness_state": "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION",
            "next_actions": ["BUILD_STAGE4_CANDIDATE_VERIFICATION_INPUT", "CONTINUE_PROJECT_MANAGER_ACTIVE_CONFLICT_PROBE"],
            "risk_escalation_state": "NO_ESCALATION",
            "flow_08_targeted_parse_required": False,
            "certificate_category_review_required": False,
            "public_registration_match_basis": "provider_identity_matched",
        }
    if _field_level_public_registration_match(stage4_result):
        return {
            "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
            "stage4_readiness_state": "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION",
            "next_actions": [
                "BUILD_STAGE4_CANDIDATE_VERIFICATION_INPUT",
                "KEEP_CERTIFICATE_CATEGORY_REVIEW_IF_REQUIRED",
                "CONTINUE_PROJECT_MANAGER_ACTIVE_CONFLICT_PROBE",
            ],
            "risk_escalation_state": "NO_ESCALATION",
            "flow_08_targeted_parse_required": False,
            "certificate_category_review_required": True,
            "public_registration_match_basis": "field_level_company_unit_certificate_readback",
        }
    if _name_enumeration_fallback_exhausted(stage4_result):
        return {
            "supplement_after_execution_state": "FLOW_08_TARGETED_PARSE_REQUIRED",
            "stage4_readiness_state": "STAGE4_BLOCKED_COMPANY_FIRST_AND_NAME_ENUMERATION_NO_MATCH",
            "next_actions": ["FLOW_08_TARGETED_PARSE", "DO_NOT_OUTPUT_FINAL_CONFLICT"],
            "risk_escalation_state": "HIGH_CLUE_REVIEW",
            "flow_08_targeted_parse_required": True,
        }
    reasons = [str(reason) for reason in list(stage4_result.get("fail_closed_reasons") or [])]
    joined = " ".join(reasons)
    if "company_search_result_not_found" in joined:
        return {
            "supplement_after_execution_state": "NAME_ENUMERATION_FALLBACK_REQUIRED",
            "stage4_readiness_state": "STAGE4_BLOCKED_COMPANY_FIRST_COMPANY_NO_MATCH",
            "next_actions": ["RUN_NAME_ENUMERATION_FALLBACK", "VERIFY_MATCHED_COMPANY_BEFORE_ACCEPTING_CERTIFICATE"],
            "risk_escalation_state": "MEDIUM_CLUE_REVIEW",
            "flow_08_targeted_parse_required": False,
        }
    if "project_manager_not_found_by_company_name" in joined or "rendered_company_personnel_rows_missing" in joined:
        return {
            "supplement_after_execution_state": "NAME_ENUMERATION_FALLBACK_REQUIRED",
            "stage4_readiness_state": "STAGE4_BLOCKED_COMPANY_FIRST_PERSON_NO_MATCH",
            "next_actions": ["RUN_NAME_ENUMERATION_FALLBACK", "VERIFY_MATCHED_COMPANY_BEFORE_ACCEPTING_CERTIFICATE"],
            "risk_escalation_state": "MEDIUM_CLUE_REVIEW",
            "flow_08_targeted_parse_required": False,
        }
    return {
        "supplement_after_execution_state": "COMPANY_FIRST_PROVIDER_REVIEW_REQUIRED",
        "stage4_readiness_state": "STAGE4_BLOCKED_PROVIDER_REVIEW_REQUIRED",
        "next_actions": ["REVIEW_PROVIDER_DIAGNOSTICS", "DO_NOT_OUTPUT_FINAL_CONFLICT"],
        "risk_escalation_state": "MEDIUM_CLUE_REVIEW",
        "flow_08_targeted_parse_required": False,
        "certificate_category_review_required": False,
        "public_registration_match_basis": "",
    }


def _should_try_highway_market(
    *,
    project_name: str,
    company: str,
    person: str,
    certificate_no: str,
    responsible_role: str,
    priority_class: str,
) -> bool:
    if not (company and person):
        return False
    text = " ".join(
        [
            project_name,
            company,
            certificate_no,
            responsible_role,
            priority_class,
        ]
    )
    highway_keywords = (
        "高速",
        "公路",
        "路桥",
        "道路",
        "桥梁",
        "隧道",
        "互通",
        "交通规划",
        "交通运输",
        "工程可行性研究",
        "方案深化",
    )
    if any(keyword in text for keyword in highway_keywords):
        return True
    if responsible_role in {"design_lead", "survey_lead"} and any(
        keyword in text for keyword in ("交通", "勘察设计", "设计研究院")
    ):
        return True
    return False


def _run_highway_market_readback(
    *,
    runner: HighwayMarketRunner | None,
    project_id: str,
    project_name: str,
    company: str,
    person: str,
    certificate_no: str,
    responsible_role: str,
    candidate_group_id: str,
) -> dict[str, Any]:
    request = {
        "project_id": project_id,
        "project_name": project_name,
        "target_company_name": company,
        "target_person_name": person,
        "target_certificate_no": certificate_no,
        "responsible_role": responsible_role,
        "candidate_group_id": candidate_group_id,
    }
    try:
        return dict((runner or query_highway_market_person_title)(request))
    except Exception as exc:  # pragma: no cover - defensive boundary
        return {
            "adapter_id": HIGHWAY_MARKET_PERSONNEL_ADAPTER_ID,
            "source_family": "national_highway_construction_market_credit_system",
            "entry_url": HIGHWAY_MARKET_PERSON_INDEX_URL,
            "query_state": "FAIL_CLOSED_PUBLIC_QUERY_ERROR",
            "readback_state": "REVIEW_REQUIRED",
            "verification_result": "REVIEW_REQUIRED",
            "target_company_name": company,
            "target_person_name": person,
            "target_certificate_no_optional": certificate_no,
            "fail_closed_reasons": [f"highway_market_query_exception:{exc}"],
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }


def _highway_market_resolved(readback: Mapping[str, Any]) -> bool:
    if str(readback.get("verification_result") or "") != "MATCHED":
        return False
    if str(readback.get("readback_state") or "") != "READBACK_READY":
        return False
    return bool(
        str(readback.get("matched_company_name_optional") or "").strip()
        and str(readback.get("registered_unit_name_optional") or "").strip()
        and (
            str(readback.get("resolved_certificate_no_optional") or "").strip()
            or str(readback.get("person_public_id_optional") or "").strip()
        )
    )


def _stage4_result_from_highway_readback(
    readback: Mapping[str, Any],
    *,
    prior_stage4_fail_closed_reasons: list[Any],
) -> dict[str, Any]:
    matched_company = str(readback.get("matched_company_name_optional") or "").strip()
    person_public_id = str(readback.get("person_public_id_optional") or "").strip()
    resolved_certificate = str(readback.get("resolved_certificate_no_optional") or "").strip()
    source_url = str(readback.get("entry_url") or HIGHWAY_MARKET_PERSON_INDEX_URL)
    academic_url = ""
    for attempt in list(readback.get("route_attempts") or []):
        if isinstance(attempt, Mapping) and attempt.get("route") == "person_academic_query":
            academic_url = str(attempt.get("source_url") or "")
            break
    return {
        "adapter_id": HIGHWAY_MARKET_PERSONNEL_ADAPTER_ID,
        "route": "MOT_HIGHWAY_MARKET_PERSON_TITLE",
        "source_family": "national_highway_construction_market_credit_system",
        "executor_state": "READBACK_READY",
        "readback_state": "READBACK_READY",
        "identity_resolution_state": "MATCHED",
        "matched_company_name_optional": matched_company,
        "matched_company_public_id_optional": readback.get("matched_company_public_id_optional", ""),
        "resolved_public_identifier_optional": resolved_certificate,
        "company_personnel_source_url": source_url,
        "company_personnel_source_snapshot_id": "",
        "personnel_project_source_url": academic_url,
        "personnel_project_source_snapshot_id": "",
        "rendered_company_personnel_row_count": 1,
        "rendered_personnel_project_row_count": len(readback.get("academic_records") or []),
        "browser_runner_id": "highway_market_public_query",
        "live_browser_executed": False,
        "browser_attempts": list(readback.get("route_attempts") or []),
        "browser_nonfatal_diagnostics": [
            "jzsc_company_first_unresolved_then_highway_market_readback_matched"
        ],
        "fail_closed_reasons": [],
        "prior_jzsc_fail_closed_reasons": [str(reason) for reason in prior_stage4_fail_closed_reasons],
        "highway_market_readback": dict(readback),
        "personnel_carrier": {
            "verification_result": "MATCHED",
            "verification_provider": "MOT_HIGHWAY_MARKET_PERSON_TITLE",
            "verification_route": "HIGHWAY_MARKET_PERSON_ACADEMIC_LIST",
            "source_url": source_url,
            "source_family": "national_highway_construction_market_credit_system",
            "public_visibility_state": "PUBLIC_VISIBLE",
            "project_manager_certificate_no_optional": resolved_certificate,
            "project_manager_public_identifier_optional": resolved_certificate or person_public_id,
            "project_manager_registered_unit_optional": matched_company,
            "person_public_id_optional": person_public_id,
            "personnel_detail_url_optional": academic_url or source_url,
            "failure_reasons": [],
            "review_required": False,
            "confidence": 0.9,
            "evidence_grade": "PUBLIC_OFFICIAL_HIGHWAY_MARKET_FIELD_MATCH",
            "customer_visible": False,
            "no_legal_conclusion": True,
        },
        "customer_sellable_evidence_ready": False,
        "no_name_only_final_proof": True,
    }


def _field_level_public_registration_match(stage4_result: Mapping[str, Any]) -> bool:
    reasons = [str(reason) for reason in list(stage4_result.get("fail_closed_reasons") or []) if str(reason)]
    if reasons:
        return False
    readback_ready = str(stage4_result.get("readback_state") or "") == "READBACK_READY" or str(
        stage4_result.get("executor_state") or ""
    ) == "READBACK_READY"
    if not readback_ready:
        return False
    carrier = dict(stage4_result.get("personnel_carrier") or {})
    matched_company = str(stage4_result.get("matched_company_name_optional") or "").strip()
    registered_unit = str(carrier.get("project_manager_registered_unit_optional") or "").strip()
    certificate_or_person_id = str(
        carrier.get("project_manager_certificate_no_optional")
        or stage4_result.get("resolved_public_identifier_optional")
        or carrier.get("person_public_id_optional")
        or ""
    ).strip()
    if not (matched_company and registered_unit and certificate_or_person_id):
        return False
    return _company_names_equivalent(matched_company, registered_unit)


def _company_names_equivalent(left: Any, right: Any) -> bool:
    def normalize(value: Any) -> str:
        text = str(value or "").strip()
        text = text.replace("（", "(").replace("）", ")")
        text = text.replace("(主)", "").replace("(成)", "")
        text = "".join(text.split())
        return text.strip("；;，,、")

    return bool(normalize(left) and normalize(left) == normalize(right))


def _apply_candidate_group_resolution(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in items:
        group_id = str(item.get("candidate_group_id") or "").strip()
        if not group_id:
            item["candidate_group_resolution_state"] = "SINGLE_COMPANY_OR_NO_GROUP"
            continue
        key = (
            str(item.get("project_id") or ""),
            group_id,
            str(item.get("responsible_person_name") or ""),
            str(item.get("source_certificate_no_optional") or ""),
        )
        grouped.setdefault(key, []).append(item)

    for group_items in grouped.values():
        if all(item.get("stage4_execution_state") == "QUEUED_NOT_EXECUTED" for item in group_items):
            for item in group_items:
                item["candidate_group_resolution_state"] = "PENDING_EXECUTION"
            continue
        matched_items = [
            item
            for item in group_items
            if item.get("supplement_after_execution_state") == "COMPANY_FIRST_CERTIFICATE_RESOLVED"
            or item.get("verification_result") == "MATCHED"
        ]
        if not matched_items:
            for item in group_items:
                item["candidate_group_resolution_state"] = "UNRESOLVED_NO_MEMBER_MATCHED"
            continue
        matched = matched_items[0]
        matched_company = str(matched.get("candidate_company_name") or matched.get("matched_company_name_optional") or "")
        for item in group_items:
            if item in matched_items:
                item["candidate_group_resolution_state"] = "RESOLVED_BY_THIS_MEMBER"
                item["candidate_group_matched_company_name_optional"] = matched_company
                continue
            item["candidate_group_resolution_state"] = "RESOLVED_BY_CONSORTIUM_MEMBER"
            item["candidate_group_matched_company_name_optional"] = matched_company
            item["supplement_after_execution_state"] = "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED"
            item["stage4_readiness_state"] = "READY_BY_CONSORTIUM_MEMBER_MATCH"
            item["risk_escalation_state"] = "NO_ESCALATION"
            item["flow_08_targeted_parse_required"] = False
            item["next_actions"] = [
                "GROUP_RESOLVED_BY_CONSORTIUM_MEMBER",
                "DO_NOT_ESCALATE_NONMATCHED_MEMBER_AS_CONFLICT",
            ]
    return items


def _name_enumeration_fallback_exhausted(stage4_result: Mapping[str, Any]) -> bool:
    fallback_attempts = [
        attempt
        for attempt in list(stage4_result.get("browser_attempts") or [])
        if isinstance(attempt, Mapping)
        and attempt.get("attempt_type") == "person_search_name_only_paginated_company_filter"
    ]
    if not fallback_attempts:
        return False
    return all(int(attempt.get("matched_count") or 0) == 0 for attempt in fallback_attempts)


def _stage4_inputs(items: list[Mapping[str, Any]], *, created_at: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.get("supplement_after_execution_state") != "COMPANY_FIRST_CERTIFICATE_RESOLVED":
            continue
        certificate = str(item.get("resolved_certificate_no_optional") or "").strip()
        person_public_id = str(item.get("person_public_id_optional") or "").strip()
        if not (certificate or person_public_id):
            continue
        rows.append(
            {
                "stage4_input_id": f"STAGE4-COMPANY-FIRST-LIVE-{_fingerprint({'p': item.get('project_id'), 'c': certificate, 'pid': person_public_id})[:16]}",
                "source_probe_adapter_id": COMPANY_FIRST_STAGE4_EXECUTION_ADAPTER_ID,
                "project_id": item.get("project_id", ""),
                "project_name": item.get("project_name", ""),
                "flow_no": "07",
                "flow_title": "中标候选人公示",
                "candidate_company_name": item.get("candidate_company_name", ""),
                "candidate_group_id": item.get("candidate_group_id", ""),
                "candidate_group_order": item.get("candidate_group_order", ""),
                "candidate_group_members": item.get("candidate_group_members", []),
                "candidate_group_match_mode": item.get("candidate_group_match_mode", ""),
                "candidate_group_resolution_state": item.get("candidate_group_resolution_state", ""),
                "consortium_member_role": item.get("consortium_member_role", ""),
                "responsible_person_name": item.get("responsible_person_name", ""),
                "project_manager_name": item.get("responsible_person_name", ""),
                "project_manager_certificate_no": certificate,
                "certificate_no": certificate,
                "person_public_id_optional": person_public_id,
                "registered_unit_name_optional": item.get("registered_unit_name_optional", ""),
                "company_personnel_source_snapshot_id": item.get("company_personnel_source_snapshot_id", ""),
                "recommended_stage4_route": item.get("stage4_resolution_route")
                or "JZSC_COMPANY_FIRST_PROJECT_MANAGER",
                "stage4_live_provider_enabled": False,
                "review_required": False,
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return {
        "manifest_kind": "stage4_candidate_verification_inputs",
        "source_manifest_kind": COMPANY_FIRST_STAGE4_EXECUTION_MANIFEST_KIND,
        "created_at": created_at,
        "items": rows,
        "summary": {
            "stage4_input_count": len(rows),
            "project_count": len({item.get("project_id") for item in rows}),
            "with_certificate_count": sum(1 for item in rows if item.get("certificate_no")),
            "with_person_public_id_count": sum(1 for item in rows if item.get("person_public_id_optional")),
            "stage4_live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    items: list[Mapping[str, Any]],
    stage4_inputs: Mapping[str, Any],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "project_count": len({item.get("project_id") for item in items}),
        "job_count": len(items),
        "stage4_execution_state_counts": _counts(item.get("stage4_execution_state") for item in items),
        "identity_resolution_state_counts": _counts(item.get("identity_resolution_state") for item in items),
        "supplement_after_execution_state_counts": _counts(item.get("supplement_after_execution_state") for item in items),
        "candidate_group_resolution_state_counts": _counts(item.get("candidate_group_resolution_state") for item in items),
        "candidate_group_resolved_count": len(
            {
                (item.get("project_id"), item.get("candidate_group_id"))
                for item in items
                if item.get("candidate_group_id")
                and item.get("candidate_group_resolution_state")
                in {"RESOLVED_BY_THIS_MEMBER", "RESOLVED_BY_CONSORTIUM_MEMBER"}
            }
        ),
        "stage4_input_count": len(stage4_inputs.get("items") or []),
        "flow_08_targeted_parse_required_count": sum(1 for item in items if item.get("flow_08_targeted_parse_required")),
        "fail_closed_reason_counts": _counts(
            reason
            for item in items
            for reason in list(item.get("fail_closed_reasons") or [])
        ),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _parsed_context(job: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    target = dict(payload.get("target") or {})
    source = dict(payload.get("source_probe_item") or {})
    return {
        "parse_run_id": f"PARSE-COMPANY-FIRST-STAGE4-{job.get('job_id', '')}",
        "snapshot_id": f"SNAP-COMPANY-FIRST-STAGE4-{job.get('job_id', '')}",
        "source_url": str(source.get("source_07_detail_path") or ""),
        "parsed_fields": [
            {
                "field_name": "candidate_company_name",
                "field_value_optional": target.get("candidate_company_name", ""),
            },
            {
                "field_name": "project_manager_name",
                "field_value_optional": target.get("responsible_person_name", ""),
            },
            {
                "field_name": "certificate_no",
                "field_value_optional": target.get("certificate_no_optional", ""),
            },
        ],
    }


def _repository(*, storage_path: Path, object_storage_path: Path) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage_path),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage_path),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def _jobs(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in list(payload.get("jobs") or []) if isinstance(item, Mapping)]


def _candidate_group_id_from_job(job: Mapping[str, Any]) -> str:
    payload = dict(job.get("payload") or {})
    target = dict(payload.get("target") or {})
    return str(payload.get("candidate_group_id") or target.get("candidate_group_id") or "").strip()


def _jobs_from_stage4_inputs(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    jobs: list[Mapping[str, Any]] = []
    for item in list(payload.get("items") or []):
        if not isinstance(item, Mapping):
            continue
        project_id = str(item.get("project_id") or "")
        company = _normalize_company_name(item.get("candidate_company_name"))
        person = str(item.get("responsible_person_name") or item.get("project_manager_name") or "").strip()
        if not (project_id and company and person):
            continue
        jobs.append(
            {
                "job_id": f"STAGE4-INPUT-JOB-{_fingerprint({'p': project_id, 'c': company, 'n': person, 'cert': item.get('certificate_no')})[:20]}",
                "provider_id": JZSC_PERSON_IDENTITY,
                "provider_role": "person_company_certificate_identity",
                "payload": {
                    "provider_id": JZSC_PERSON_IDENTITY,
                    "provider_role": "person_company_certificate_identity",
                    "target": {
                        "opportunity_priority_class": _priority_class(str(item.get("responsible_role") or "")),
                        "candidate_company_name": company,
                        "responsible_person_name": person,
                        "certificate_no_optional": item.get("certificate_no") or item.get("project_manager_certificate_no") or "",
                        "person_public_id_optional": item.get("person_public_id_optional") or "",
                        "candidate_group_id": item.get("candidate_group_id") or "",
                        "candidate_group_order": item.get("candidate_group_order") or "",
                        "candidate_group_members": item.get("candidate_group_members") or [],
                        "consortium_member_role": item.get("consortium_member_role") or "",
                    },
                    "source_probe_item": {
                        "project_id": project_id,
                        "project_name": item.get("project_name", ""),
                        "source_07_detail_path": item.get("source_07_detail_path", ""),
                    },
                },
                "status": "QUEUED_FROM_STAGE4_INPUT",
                "stage4_live_provider_enabled": False,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return jobs


def _candidate_group_members(*, payload: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    raw = payload.get("candidate_group_members") or target.get("candidate_group_members") or []
    rows: list[str] = []
    for item in list(raw) if isinstance(raw, list) else []:
        if isinstance(item, Mapping):
            value = str(item.get("company_name") or item.get("candidate_company_name") or "").strip()
        else:
            value = str(item or "").strip()
        if value and value not in rows:
            rows.append(value)
    return rows


def _required_registration_category(target: Mapping[str, Any]) -> str:
    priority_class = str(target.get("opportunity_priority_class") or "").upper()
    if "SUPERVISION" in priority_class:
        return "注册监理工程师"
    if "CONSTRUCTION" in priority_class or "EPC" in priority_class:
        return "注册建造师"
    return ""


def _normalize_company_name(value: Any) -> str:
    text = str(value or "").strip()
    for prefix in ("3家：", "2家：", "1家：", "三家：", "两家：", "一家："):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    for marker in ("(主)", "（主）", "(成)", "（成）", "主：", "成："):
        text = text.replace(marker, "")
    return text.strip(" ：:;；、，,")


def _priority_class(responsible_role: str) -> str:
    role = str(responsible_role or "")
    if role == "chief_supervision_engineer":
        return "B_HIGH_SUPERVISION"
    if role in {"design_lead", "survey_lead", "service_project_lead"}:
        return "C_MEDIUM_DESIGN_SURVEY"
    return "A_HIGH_CONSTRUCTION_EPC"


def _project_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _split_csv(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run controlled company-first Stage4 browser execution.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--provider-jobs-json", default="")
    parser.add_argument("--stage4-inputs-json", default="")
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--candidate-group-ids", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-personnel-pages", type=int, default=12)
    parser.add_argument("--max-project-pages", type=int, default=3)
    parser.add_argument("--personnel-retry-attempts", type=int, default=2)
    parser.add_argument("--capture-personnel-project-records", action="store_true")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    result = build_company_first_stage4_execution(
        input_root=args.input_root,
        output_root=args.output_root,
        provider_jobs_json=args.provider_jobs_json or None,
        stage4_inputs_json=args.stage4_inputs_json or None,
        project_ids=_split_csv(args.project_ids),
        candidate_group_ids=_split_csv(args.candidate_group_ids),
        execute=bool(args.execute),
        max_personnel_pages=args.max_personnel_pages,
        max_project_pages=args.max_project_pages,
        personnel_retry_attempts=args.personnel_retry_attempts,
        capture_personnel_project_records=bool(args.capture_personnel_project_records),
    )
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "output_root": str(args.output_root),
                    "job_count": result["summary"]["job_count"],
                    "stage4_input_count": result["summary"]["stage4_input_count"],
                    "state_counts": result["summary"]["supplement_after_execution_state_counts"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
