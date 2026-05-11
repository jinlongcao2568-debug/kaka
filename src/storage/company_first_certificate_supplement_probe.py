from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage4_verification.jzsc_personnel import build_jzsc_company_first_capture_plan
from stage4_verification.provider_handlers import MATCHED, run_jzsc_identity_provider_task
from stage4_verification.provider_registry import (
    JZSC_PERSON_IDENTITY,
    build_stage4_provider_plan,
)


COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_MANIFEST_KIND = "company_first_certificate_supplement_probe_manifest"
COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_VERSION = 1
COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_ADAPTER_ID = "company-first-certificate-supplement-probe-v1"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-responsible-person-early-probe-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-supplement-v1")
SUPPLEMENT_REQUIRED_STATES = {
    "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED",
    "NAME_ENUMERATION_FALLBACK_REQUIRED",
    "FLOW_08_TARGETED_PARSE_REQUIRED",
}


def build_company_first_certificate_supplement_probe(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    early_probe_json: str | Path | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    company_first_result_state: str = "NOT_RUN",
    name_enumeration_result_state: str = "NOT_RUN",
    source_stage4_records_json: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(input_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    early_path = Path(early_probe_json) if early_probe_json else in_root / "responsible-person-early-probe.json"
    blocking_reasons: list[str] = []
    early_payload = _load_json(early_path)
    if not early_payload:
        blocking_reasons.append("responsible_person_early_probe_missing")
    source_records = _load_source_records(source_stage4_records_json)
    selected_projects = {_project_code(project_id) for project_id in project_ids if _project_code(project_id)}
    early_items = _early_items(early_payload)
    if selected_projects:
        early_items = [item for item in early_items if _project_code(item.get("project_id")) in selected_projects]

    supplement_items = [
        _build_supplement_item(
            early_item=item,
            source_records=source_records,
            company_first_result_state=company_first_result_state,
            name_enumeration_result_state=name_enumeration_result_state,
            created_at=created,
        )
        for item in early_items
        if str(item.get("early_probe_state") or "") in SUPPLEMENT_REQUIRED_STATES
    ]
    provider_jobs = _provider_jobs(supplement_items)
    stage4_inputs = _stage4_inputs(supplement_items, created_at=created)
    summary = _summary(supplement_items, provider_jobs, stage4_inputs, blocking_reasons)
    manifest = {
        "manifest_version": COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_VERSION,
        "manifest_kind": COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_MANIFEST_KIND,
        "adapter_id": COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_ADAPTER_ID,
        "pipeline_stage": "CompanyFirstCertificateSupplementProbe",
        "manifest_id": f"COMPANY-FIRST-CERT-SUPPLEMENT-{_fingerprint({'items': supplement_items, 'summary': summary})[:16]}",
        "created_at": created,
        "source_input_root": str(in_root),
        "source_responsible_person_early_probe_json": str(early_path),
        "source_stage4_records_json_optional": str(source_stage4_records_json or ""),
        "company_first_result_state": _normalize_result_state(company_first_result_state),
        "name_enumeration_result_state": _normalize_result_state(name_enumeration_result_state),
        "items": supplement_items,
        "project_sample_items": supplement_items,
        "stage4_provider_jobs": provider_jobs,
        "stage4_candidate_verification_inputs": stage4_inputs,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "graphify_enabled": False,
            "mempalace_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "company_first_certificate_supplement_mode": "EXECUTED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": True,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    (out_root / "company-first-certificate-supplement.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "stage4_provider_jobs.json").write_text(
        json.dumps(provider_jobs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "stage4_candidate_verification_inputs.json").write_text(
        json.dumps(stage4_inputs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _build_supplement_item(
    *,
    early_item: Mapping[str, Any],
    source_records: Mapping[str, Mapping[str, Any]],
    company_first_result_state: str,
    name_enumeration_result_state: str,
    created_at: str,
) -> dict[str, Any]:
    project_id = str(early_item.get("project_id") or "")
    project_name = str(early_item.get("project_name") or "")
    supplement_targets = _supplement_targets(early_item)
    companies = _candidate_values(
        [target.get("candidate_company_name") for target in supplement_targets]
        or early_item.get("candidate_company_candidates"),
        limit=20,
    )
    persons = _candidate_values(
        [target.get("responsible_person_name") for target in supplement_targets]
        or early_item.get("responsible_person_candidates"),
        limit=20,
    )
    primary_company = companies[0] if companies else ""
    primary_person = persons[0] if persons else ""
    responsible_role = str(early_item.get("responsible_role") or "project_manager")
    priority_class = _priority_class(responsible_role)
    provider_plan = build_stage4_provider_plan(
        opportunity_priority_class=priority_class,
        candidate_company_name=primary_company,
        responsible_person_name=primary_person,
    )
    capture_plan = (
        build_jzsc_company_first_capture_plan(
            target_company_name=primary_company,
            target_project_manager_name=primary_person,
        )
        if primary_company and primary_person
        else {}
    )
    attempts = _company_first_attempts(project_id=project_id, companies=companies, persons=persons)
    source_record = source_records.get(project_id) or source_records.get(_project_code(project_id)) or {}
    provider_readback = _provider_readback(
        source_record=source_record,
        project_id=project_id,
        project_name=project_name,
        company=primary_company,
        person=primary_person,
        responsible_role=responsible_role,
    )
    item_state = _supplement_state(
        provider_readback=provider_readback,
        company_first_result_state=company_first_result_state,
        name_enumeration_result_state=name_enumeration_result_state,
        has_target=bool(primary_company and primary_person),
    )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "source_early_probe_state": early_item.get("early_probe_state"),
        "source_07_detail_path": early_item.get("source_07_detail_path", ""),
        "candidate_company_candidates": early_item.get("candidate_company_candidates", []),
        "responsible_person_candidates": early_item.get("responsible_person_candidates", []),
        "responsible_role": responsible_role,
        "opportunity_priority_class": priority_class,
        "primary_company_name": primary_company,
        "primary_responsible_person_name": primary_person,
        "supplement_verification_targets": supplement_targets,
        "company_first_attempts": attempts,
        "name_enumeration_targets": _name_enumeration_targets(project_id=project_id, companies=companies, persons=persons),
        "stage4_provider_plan": provider_plan,
        "jzsc_company_first_capture_plan": capture_plan,
        "provider_readback": provider_readback,
        "supplement_probe_state": item_state["supplement_probe_state"],
        "stage4_readiness_state": item_state["stage4_readiness_state"],
        "next_actions": item_state["next_actions"],
        "risk_escalation_state": item_state["risk_escalation_state"],
        "flow_08_targeted_parse_required": item_state["flow_08_targeted_parse_required"],
        "no_name_only_final_proof": True,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _provider_readback(
    *,
    source_record: Mapping[str, Any],
    project_id: str,
    project_name: str,
    company: str,
    person: str,
    responsible_role: str,
) -> dict[str, Any]:
    if not source_record:
        return {
            "provider_result_state": "NOT_RUN",
            "verification_result": "NOT_RUN",
            "identity_resolution_state": "NOT_RUN",
            "identity_fields": {},
            "review_reasons": ["stage4_source_record_not_supplied"],
            "customer_sellable_evidence_ready": False,
        }
    payload = {
        "provider_id": JZSC_PERSON_IDENTITY,
        "provider_role": "person_company_certificate_identity",
        "target": {
            "project_id": project_id,
            "project_name": project_name,
            "candidate_company_name": company,
            "responsible_person_name": person,
            "responsible_role": responsible_role,
        },
        "source_stage4_jzsc_record": dict(source_record),
    }
    return run_jzsc_identity_provider_task(payload)


def _supplement_state(
    *,
    provider_readback: Mapping[str, Any],
    company_first_result_state: str,
    name_enumeration_result_state: str,
    has_target: bool,
) -> dict[str, Any]:
    normalized_company_state = _normalize_result_state(company_first_result_state)
    normalized_name_state = _normalize_result_state(name_enumeration_result_state)
    if not has_target:
        return {
            "supplement_probe_state": "COMPANY_FIRST_TARGET_FIELDS_MISSING",
            "stage4_readiness_state": "STAGE4_BLOCKED_TARGET_FIELDS_MISSING",
            "next_actions": ["RETURN_TO_RESPONSIBLE_PERSON_EARLY_PROBE_OR_FLOW_08_TARGETED_PARSE"],
            "risk_escalation_state": "EVIDENCE_BLOCKED",
            "flow_08_targeted_parse_required": True,
        }
    if provider_readback.get("verification_result") == MATCHED:
        return {
            "supplement_probe_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
            "stage4_readiness_state": "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION",
            "next_actions": ["BUILD_STAGE4_CANDIDATE_VERIFICATION_INPUT", "CONTINUE_PROJECT_MANAGER_ACTIVE_CONFLICT_PROBE"],
            "risk_escalation_state": "NO_ESCALATION",
            "flow_08_targeted_parse_required": False,
        }
    if normalized_company_state == "NO_MATCH" and normalized_name_state == "NO_MATCH":
        return {
            "supplement_probe_state": "FLOW_08_TARGETED_PARSE_REQUIRED",
            "stage4_readiness_state": "STAGE4_BLOCKED_CERTIFICATE_NOT_FOUND",
            "next_actions": ["FLOW_08_TARGETED_PARSE", "DO_NOT_OUTPUT_FINAL_CONFLICT"],
            "risk_escalation_state": "HIGH_CLUE_REVIEW",
            "flow_08_targeted_parse_required": True,
        }
    if normalized_company_state == "NO_MATCH":
        return {
            "supplement_probe_state": "NAME_ENUMERATION_FALLBACK_REQUIRED",
            "stage4_readiness_state": "STAGE4_BLOCKED_COMPANY_FIRST_NO_MATCH",
            "next_actions": ["RUN_NAME_ENUMERATION_FALLBACK", "VERIFY_MATCHED_COMPANY_BEFORE_ACCEPTING_CERTIFICATE"],
            "risk_escalation_state": "MEDIUM_CLUE_REVIEW",
            "flow_08_targeted_parse_required": False,
        }
    if normalized_company_state == "AMBIGUOUS":
        return {
            "supplement_probe_state": "COMPANY_FIRST_AMBIGUOUS_REVIEW",
            "stage4_readiness_state": "STAGE4_BLOCKED_AMBIGUOUS_PUBLIC_MATCH",
            "next_actions": ["RUN_NAME_ENUMERATION_FALLBACK", "KEEP_NO_NAME_ONLY_FINAL_PROOF"],
            "risk_escalation_state": "MEDIUM_CLUE_REVIEW",
            "flow_08_targeted_parse_required": False,
        }
    return {
        "supplement_probe_state": "COMPANY_FIRST_PROVIDER_TASKS_READY",
        "stage4_readiness_state": "STAGE4_PROVIDER_TASKS_READY_NOT_EXECUTED",
        "next_actions": ["EXECUTE_AUTHORIZED_COMPANY_FIRST_PROVIDER_TASKS", "DO_NOT_PARSE_FLOW_08_UNTIL_PROVIDER_TASKS_RETURN_NO_MATCH"],
        "risk_escalation_state": "NO_ESCALATION",
        "flow_08_targeted_parse_required": False,
    }


def _stage4_inputs(supplement_items: list[Mapping[str, Any]], *, created_at: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in supplement_items:
        if item.get("supplement_probe_state") != "COMPANY_FIRST_CERTIFICATE_RESOLVED":
            continue
        identity = ((item.get("provider_readback") or {}).get("identity_fields") or {})
        certificate = str(identity.get("certificate_no") or "")
        person_public_id = str(identity.get("person_public_id") or "")
        if not (certificate or person_public_id):
            continue
        stage4_item = {
            "stage4_input_id": f"STAGE4-COMPANY-FIRST-{_fingerprint({'p': item.get('project_id'), 'cert': certificate, 'pid': person_public_id})[:16]}",
            "source_probe_adapter_id": COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_ADAPTER_ID,
            "project_id": item.get("project_id"),
            "project_name": item.get("project_name"),
            "flow_no": "07",
            "flow_title": "中标候选人公示",
            "candidate_company_name": item.get("primary_company_name"),
            "responsible_person_name": item.get("primary_responsible_person_name"),
            "responsible_role": item.get("responsible_role"),
            "project_manager_name": item.get("primary_responsible_person_name"),
            "project_manager_certificate_no": certificate,
            "certificate_no": certificate,
            "person_public_id_optional": person_public_id,
            "registered_unit_name_optional": identity.get("registered_unit_name", ""),
            "recommended_stage4_route": "JZSC_COMPANY_FIRST_PROJECT_MANAGER",
            "stage4_live_provider_enabled": False,
            "review_required": False,
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        items.append(stage4_item)
    return {
        "manifest_kind": "stage4_candidate_verification_inputs",
        "source_manifest_kind": COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_MANIFEST_KIND,
        "created_at": created_at,
        "items": items,
        "summary": {
            "stage4_input_count": len(items),
            "project_count": len({item.get("project_id") for item in items}),
            "with_certificate_count": sum(1 for item in items if item.get("certificate_no")),
            "with_person_public_id_count": sum(1 for item in items if item.get("person_public_id_optional")),
            "stage4_live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _provider_jobs(supplement_items: list[Mapping[str, Any]]) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    for item in supplement_items:
        if item.get("supplement_probe_state") != "COMPANY_FIRST_PROVIDER_TASKS_READY":
            continue
        targets = list(item.get("supplement_verification_targets") or [])
        if not targets:
            targets = [
                {
                    "candidate_company_name": item.get("primary_company_name", ""),
                    "responsible_person_name": item.get("primary_responsible_person_name", ""),
                    "candidate_group_id": "",
                }
            ]
        for target in targets:
            company = str((target or {}).get("candidate_company_name") or "").strip()
            person = str((target or {}).get("responsible_person_name") or "").strip()
            if not (company and person):
                continue
            task = _provider_task_for_target(
                item=item,
                company=company,
                person=person,
            )
            jobs.append(
                {
                    "job_id": f"STAGE4-JOB-{_fingerprint({'project': item.get('project_id'), 'target': target})[:20]}",
                    "provider_id": task.get("provider_id"),
                    "provider_role": task.get("provider_role"),
                    "payload": {
                        "provider_id": task.get("provider_id"),
                        "provider_role": task.get("provider_role"),
                        "target": task.get("target"),
                        "capture_plan": build_jzsc_company_first_capture_plan(
                            target_company_name=company,
                            target_project_manager_name=person,
                        ),
                        "candidate_group_id": (target or {}).get("candidate_group_id", ""),
                        "candidate_group_order": (target or {}).get("candidate_group_order", ""),
                        "candidate_group_members": (target or {}).get("candidate_group_members", []),
                        "consortium_member_role": (target or {}).get("consortium_member_role", ""),
                        "source_probe_item": {
                            "project_id": item.get("project_id"),
                            "project_name": item.get("project_name"),
                            "source_07_detail_path": item.get("source_07_detail_path"),
                        },
                    },
                    "status": "QUEUED_NOT_EXECUTED",
                    "stage4_live_provider_enabled": False,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return {
        "manifest_kind": "stage4_provider_jobs",
        "adapter_id": COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_ADAPTER_ID,
        "jobs": jobs,
        "summary": {
            "job_count": len(jobs),
            "provider_id_counts": _counts(job.get("provider_id") for job in jobs),
            "stage4_live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _provider_task_for_target(*, item: Mapping[str, Any], company: str, person: str) -> dict[str, Any]:
    plan = build_stage4_provider_plan(
        opportunity_priority_class=str(item.get("opportunity_priority_class") or ""),
        candidate_company_name=company,
        responsible_person_name=person,
    )
    tasks = [task for task in list(plan.get("tasks") or []) if isinstance(task, Mapping) and task.get("provider_id") == JZSC_PERSON_IDENTITY]
    return dict(tasks[0]) if tasks else {
        "provider_id": JZSC_PERSON_IDENTITY,
        "provider_role": "person_company_certificate_identity",
        "target": {
            "candidate_company_name": company,
            "responsible_person_name": person,
            "certificate_no_optional": "",
            "person_public_id_optional": "",
        },
    }


def _supplement_targets(early_item: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in list(early_item.get("verification_targets") or []):
        if not isinstance(target, Mapping):
            continue
        if target.get("certificate_no"):
            continue
        company = str(target.get("candidate_company_name") or "").strip()
        person = str(target.get("responsible_person_name") or "").strip()
        if not (company and person):
            continue
        rows.append(dict(target))
    if rows:
        return rows
    company = _candidate_values(early_item.get("candidate_company_candidates"), limit=1)
    person = _candidate_values(early_item.get("responsible_person_candidates"), limit=1)
    if company and person:
        return [
            {
                "candidate_company_name": company[0],
                "responsible_person_name": person[0],
                "candidate_group_id": "",
                "candidate_group_members": [company[0]],
                "consortium_member_role": "unknown",
            }
        ]
    return []


def _company_first_attempts(*, project_id: str, companies: list[str], persons: list[str]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for company in companies:
        for person in persons:
            attempts.append(
                {
                    "attempt_id": f"COMPANY-FIRST-ATTEMPT-{_fingerprint({'p': project_id, 'c': company, 'n': person})[:16]}",
                    "candidate_company_name": company,
                    "responsible_person_name": person,
                    "route": "JZSC_COMPANY_FIRST_PROJECT_MANAGER",
                    "result_state": "NOT_RUN",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return attempts[:25]


def _name_enumeration_targets(*, project_id: str, companies: list[str], persons: list[str]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for person in persons:
        targets.append(
            {
                "target_id": f"NAME-ENUMERATION-{_fingerprint({'p': project_id, 'n': person})[:16]}",
                "responsible_person_name": person,
                "company_names_to_verify_before_accepting": companies,
                "same_name_only_accepted": False,
                "must_match_one_candidate_company": True,
                "result_state": "NOT_RUN",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return targets[:10]


def _summary(
    supplement_items: list[Mapping[str, Any]],
    provider_jobs: Mapping[str, Any],
    stage4_inputs: Mapping[str, Any],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "project_count": len(supplement_items),
        "supplement_probe_state_counts": _counts(item.get("supplement_probe_state") for item in supplement_items),
        "stage4_readiness_state_counts": _counts(item.get("stage4_readiness_state") for item in supplement_items),
        "flow_08_targeted_parse_required_count": sum(1 for item in supplement_items if item.get("flow_08_targeted_parse_required")),
        "company_first_attempt_count": sum(len(item.get("company_first_attempts") or []) for item in supplement_items),
        "name_enumeration_target_count": sum(len(item.get("name_enumeration_targets") or []) for item in supplement_items),
        "provider_job_count": len((provider_jobs.get("jobs") or []) if isinstance(provider_jobs, Mapping) else []),
        "stage4_input_count": len(stage4_inputs.get("items") or []),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _early_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    return [item for item in (manifest.get("items") or []) if isinstance(item, Mapping)] if isinstance(manifest, Mapping) else []


def _candidate_values(values: Any, *, limit: int) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        raw = value.get("value") if isinstance(value, Mapping) else value
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _priority_class(responsible_role: str) -> str:
    role = str(responsible_role or "")
    if role == "chief_supervision_engineer":
        return "B_HIGH_SUPERVISION"
    if role in {"design_lead", "survey_lead"}:
        return "C_MEDIUM_DESIGN_SURVEY"
    return "A_HIGH_CONSTRUCTION_EPC"


def _load_source_records(path: str | Path | None) -> dict[str, Mapping[str, Any]]:
    if not path:
        return {}
    payload = _load_json(Path(path))
    if not payload:
        return {}
    if isinstance(payload.get("records"), list):
        records = payload.get("records") or []
    elif isinstance(payload.get("items"), list):
        records = payload.get("items") or []
    else:
        records = [payload]
    out: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or record.get("target_project_id") or "")
        if project_id:
            out[project_id] = record
            code = _project_code(project_id)
            if code:
                out[code] = record
    return out


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_result_state(value: Any) -> str:
    state = str(value or "NOT_RUN").strip().upper()
    if state in {"NOT_RUN", "MATCHED", "NO_MATCH", "AMBIGUOUS"}:
        return state
    return "NOT_RUN"


def _project_code(value: Any) -> str:
    import re

    match = re.search(r"JG\d{4}-\d+", str(value or "").upper())
    return match.group(0) if match else ""


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build CompanyFirstCertificateSupplementProbe v1.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--early-probe-json")
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--company-first-result-state", default="NOT_RUN")
    parser.add_argument("--name-enumeration-result-state", default="NOT_RUN")
    parser.add_argument("--source-stage4-records-json")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_company_first_certificate_supplement_probe(
        input_root=args.input_root,
        output_root=args.output_root,
        early_probe_json=args.early_probe_json,
        project_ids=_parse_csv(args.project_ids),
        company_first_result_state=args.company_first_result_state,
        name_enumeration_result_state=args.name_enumeration_result_state,
        source_stage4_records_json=args.source_stage4_records_json,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "company-first-certificate-supplement.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"company first certificate supplement probe built: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_MANIFEST_KIND",
    "build_company_first_certificate_supplement_probe",
]
