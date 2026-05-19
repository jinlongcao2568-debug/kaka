from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_KIND = "design_survey_flow08_stage4_inputs_v1_manifest"
DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_VERSION = 1
DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_ID = "design-survey-flow08-stage4-inputs-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/design-survey-flow08-stage4-inputs-v1")

FLOW08_TEXT_FIELDS_EXTRACTED = "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
FLOW08_PERSON_DOSSIER_EXTRACTED = "TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED"


def build_design_survey_flow08_stage4_inputs(
    *,
    design_survey_flow08_attachment_parse_json: str | Path | None = None,
    design_survey_flow08_attachment_parse_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    parse_manifest = _optional_manifest(
        explicit_json=design_survey_flow08_attachment_parse_json,
        root=design_survey_flow08_attachment_parse_root,
        default_file_name="design-survey-flow08-target-attachment-parse-v1.json",
    )
    if not parse_manifest:
        blocking_reasons.append("design_survey_flow08_attachment_parse_missing")

    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    parse_records = _target_attachment_parse_records(parse_manifest)
    stage4_items: list[dict[str, Any]] = []
    fact_records: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []

    for record in parse_records:
        project_id = str(record.get("project_id") or "").strip()
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue
        state = str(record.get("attachment_parse_state") or "").strip()
        if state not in {FLOW08_TEXT_FIELDS_EXTRACTED, FLOW08_PERSON_DOSSIER_EXTRACTED}:
            skipped_records.append(_skipped_record(record, "flow08_attachment_parse_not_field_ready", created_at=created))
            continue

        companies = _target_companies(record)
        person = _responsible_person_name(record)
        if not (project_id and companies and person):
            skipped_records.append(_skipped_record(record, "stage4_target_project_company_or_person_missing", created_at=created))
            continue

        evidence_profile = _flow08_evidence_profile(record)
        fact_records.append(_fact_record(record, evidence_profile=evidence_profile, created_at=created))
        group_id = _candidate_group_id(project_id, companies) if len(companies) > 1 else ""
        group_members = [company["company_name"] for company in companies]
        for index, company in enumerate(companies, start=1):
            stage4_items.append(
                _stage4_input_item(
                    record=record,
                    company=company,
                    group_id=group_id,
                    group_order=str(index),
                    group_members=group_members,
                    evidence_profile=evidence_profile,
                    created_at=created,
                )
            )

    stage4_inputs = _stage4_candidate_verification_inputs(stage4_items, created_at=created)
    fact_table = {
        "summary": _fact_summary(fact_records),
        "records": fact_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = _summary(
        parse_records=parse_records,
        stage4_items=stage4_items,
        fact_records=fact_records,
        skipped_records=skipped_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_VERSION,
        "manifest_kind": DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_KIND,
        "adapter_id": DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_ID,
        "pipeline_stage": "DesignSurveyFlow08Stage4InputsV1",
        "manifest_id": f"DESIGN-SURVEY-FLOW08-STAGE4-{_fingerprint({'summary': summary, 'stage4': stage4_items})[:16]}",
        "created_at": created,
        "source_design_survey_flow08_attachment_parse_json": _manifest_source_path(
            design_survey_flow08_attachment_parse_json,
            design_survey_flow08_attachment_parse_root,
            "design-survey-flow08-target-attachment-parse-v1.json",
        ),
        "stage4_candidate_verification_inputs": stage4_inputs,
        "flow08_current_candidate_evidence_table": fact_table,
        "skipped_records": skipped_records,
        "summary": summary,
        "scope_guardrails": {
            "flow08_targeted_attachment_only": True,
            "does_not_parse_all_flow_08_by_default": True,
            "flow08_bid_document_evidence_is_current_candidate_binding_not_public_registration_proof": True,
            "next_stage4_public_registration_replay_required": True,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "design_survey_flow08_stage4_inputs_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "design-survey-flow08-stage4-inputs-v1.json", result)
    _write_json(out_dir / "stage4_candidate_verification_inputs.json", stage4_inputs)
    _write_json(out_dir / "flow08-current-candidate-evidence-table.json", fact_table)
    return result


def _stage4_input_item(
    *,
    record: Mapping[str, Any],
    company: Mapping[str, str],
    group_id: str,
    group_order: str,
    group_members: list[str],
    evidence_profile: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    company_name = company["company_name"]
    person = _responsible_person_name(record)
    role = _responsible_role(record)
    certificate_no = _certificate_no(record)
    return {
        "stage4_input_id": _stable_id(
            "DESIGN-SURVEY-FLOW08-STAGE4",
            record.get("project_id"),
            company_name,
            person,
            role,
            record.get("target_attachment_parse_id"),
        ),
        "source_probe_adapter_id": DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_ID,
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "flow_no": "07",
        "flow_title": "中标候选人公示",
        "source_07_detail_path": "",
        "source_flow08_attachment_url": record.get("attachment_url", ""),
        "source_flow08_attachment_snapshot_id": record.get("attachment_snapshot_id_optional", ""),
        "candidate_company_name": company_name,
        "candidate_group_id": group_id,
        "candidate_group_order": group_order if group_id else "",
        "candidate_group_members": group_members,
        "candidate_group_match_mode": "ANY_CONSORTIUM_MEMBER" if group_id and len(group_members) > 1 else "SINGLE_COMPANY",
        "consortium_member_role": company.get("consortium_member_role", ""),
        "responsible_person_name": person,
        "project_manager_name": person,
        "responsible_role": role,
        "certificate_no": certificate_no,
        "project_manager_certificate_no": certificate_no,
        "person_public_id_optional": "",
        "flow08_current_candidate_binding_evidence": dict(evidence_profile),
        "recommended_stage4_route": "JZSC_COMPANY_FIRST_OR_LOCAL_DESIGN_SURVEY_PERSONNEL_REGISTRY",
        "stage4_live_provider_enabled": False,
        "review_required": True,
        "review_reason": "flow08_person_dossier_or_extracted_field_requires_public_registration_stage4_replay",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow08_evidence_profile(record: Mapping[str, Any]) -> dict[str, Any]:
    dossier = record.get("person_dossier_evidence") if isinstance(record.get("person_dossier_evidence"), Mapping) else {}
    fields = record.get("extracted_fields") if isinstance(record.get("extracted_fields"), Mapping) else {}
    evidence_records = _dossier_evidence_page_refs(dossier)
    return {
        "source_adapter_id": DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_ID,
        "target_attachment_parse_id": record.get("target_attachment_parse_id", ""),
        "target_attachment_id": record.get("target_attachment_id", ""),
        "attachment_parse_state": record.get("attachment_parse_state", ""),
        "attachment_url": record.get("attachment_url", ""),
        "attachment_snapshot_id_optional": record.get("attachment_snapshot_id_optional", ""),
        "document_sha256": record.get("document_sha256", ""),
        "document_work_path": record.get("document_work_path", ""),
        "extraction_json_path": record.get("extraction_json_path", ""),
        "extracted_fields": dict(fields),
        "person_dossier_state": dossier.get("person_dossier_state", ""),
        "page_window_strategy_state": dossier.get("page_window_strategy_state", ""),
        "planned_page_ranges": dossier.get("planned_page_ranges", ""),
        "current_project_binding_state": dossier.get("current_project_binding_state", ""),
        "current_project_binding_evidence_count": int(dossier.get("current_project_binding_evidence_count") or 0),
        "supporting_identity_or_credential_evidence_count": int(
            dossier.get("supporting_identity_or_credential_evidence_count") or 0
        ),
        "evidence_category_counts": dict(dossier.get("evidence_category_counts") or {}),
        "evidence_page_refs": evidence_records,
        "sensitive_fields_policy": dict(dossier.get("sensitive_fields_policy") or {}),
        "stage4_use": "current_candidate_person_role_binding_and_identity_clue_only",
        "not_public_registration_proof": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fact_record(record: Mapping[str, Any], *, evidence_profile: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "flow08_current_candidate_evidence_id": _stable_id(
            "FLOW08-CURRENT-CANDIDATE-EVIDENCE",
            record.get("project_id"),
            record.get("target_attachment_parse_id"),
        ),
        "project_id": record.get("project_id", ""),
        "project_name": record.get("project_name", ""),
        "responsible_person_name": _responsible_person_name(record),
        "responsible_role": _responsible_role(record),
        "target_company_names": [company["company_name"] for company in _target_companies(record)],
        "attachment_parse_state": record.get("attachment_parse_state", ""),
        "current_project_binding_state": evidence_profile.get("current_project_binding_state", ""),
        "current_project_binding_evidence_count": evidence_profile.get("current_project_binding_evidence_count", 0),
        "supporting_identity_or_credential_evidence_count": evidence_profile.get(
            "supporting_identity_or_credential_evidence_count", 0
        ),
        "evidence_category_counts": evidence_profile.get("evidence_category_counts", {}),
        "evidence_page_refs": evidence_profile.get("evidence_page_refs", []),
        "stage4_replay_state": "READY_FOR_STAGE4_PUBLIC_REGISTRATION_REPLAY",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _stage4_candidate_verification_inputs(items: list[Mapping[str, Any]], *, created_at: str) -> dict[str, Any]:
    return {
        "manifest_kind": "stage4_candidate_verification_inputs",
        "source_manifest_kind": DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_KIND,
        "source_probe_adapter_id": DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_ID,
        "created_at": created_at,
        "items": list(items),
        "summary": {
            "stage4_input_count": len(items),
            "project_count": len({item.get("project_id") for item in items}),
            "candidate_company_count": len({item.get("candidate_company_name") for item in items}),
            "flow08_current_candidate_binding_input_count": len(items),
            "with_certificate_count": sum(1 for item in items if item.get("certificate_no")),
            "stage4_live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _target_attachment_parse_records(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    table = manifest.get("target_attachment_parse_table") if isinstance(manifest.get("target_attachment_parse_table"), Mapping) else {}
    return [dict(record) for record in _list(table.get("records")) if isinstance(record, Mapping)]


def _target_companies(record: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = _list(record.get("matched_target_company_names")) or _list(record.get("target_company_names"))
    companies = [_clean_company_name(item) for item in raw]
    if not companies:
        companies = [_clean_company_name(item) for item in _split_companies(record.get("candidate_company_text"))]
    return [
        {
            "company_name": company,
            "consortium_member_role": _consortium_member_role(company, record.get("candidate_company_text")),
        }
        for company in _dedupe(companies)
        if company
    ]


def _responsible_person_name(record: Mapping[str, Any]) -> str:
    fields = record.get("extracted_fields") if isinstance(record.get("extracted_fields"), Mapping) else {}
    return str(
        fields.get("primary_responsible_person_name")
        or fields.get("project_manager_name")
        or record.get("responsible_person_name")
        or ""
    ).strip()


def _responsible_role(record: Mapping[str, Any]) -> str:
    fields = record.get("extracted_fields") if isinstance(record.get("extracted_fields"), Mapping) else {}
    return str(fields.get("primary_responsible_role") or "survey_design_project_lead").strip()


def _certificate_no(record: Mapping[str, Any]) -> str:
    fields = record.get("extracted_fields") if isinstance(record.get("extracted_fields"), Mapping) else {}
    return str(
        fields.get("primary_certificate_no_optional")
        or fields.get("certificate_no_optional")
        or fields.get("project_manager_certificate_no")
        or ""
    ).strip()


def _dossier_evidence_page_refs(dossier: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for record in _list(dossier.get("evidence_records")):
        if not isinstance(record, Mapping):
            continue
        refs.append(
            {
                "person_dossier_evidence_id": record.get("person_dossier_evidence_id", ""),
                "page_no": record.get("page_no", 0),
                "evidence_category": record.get("evidence_category", ""),
                "current_project_binding_candidate_state": record.get("current_project_binding_candidate_state", ""),
                "history_performance_page": bool(record.get("history_performance_page")),
                "redacted_text_probe": _clip(record.get("redacted_text_probe"), 360),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return refs


def _skipped_record(record: Mapping[str, Any], reason: str, *, created_at: str) -> dict[str, Any]:
    return {
        "project_id": record.get("project_id", ""),
        "project_name": record.get("project_name", ""),
        "target_attachment_parse_id": record.get("target_attachment_parse_id", ""),
        "attachment_parse_state": record.get("attachment_parse_state", ""),
        "skip_reason": reason,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    parse_records: list[Mapping[str, Any]],
    stage4_items: list[Mapping[str, Any]],
    fact_records: list[Mapping[str, Any]],
    skipped_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "target_attachment_parse_record_count": len(parse_records),
        "attachment_parse_state_counts": _counts(record.get("attachment_parse_state") for record in parse_records),
        "stage4_input_count": len(stage4_items),
        "fact_record_count": len(fact_records),
        "project_count": len({record.get("project_id") for record in fact_records}),
        "candidate_company_count": len({item.get("candidate_company_name") for item in stage4_items}),
        "skipped_record_count": len(skipped_records),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fact_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "fact_record_count": len(records),
        "project_count": len({record.get("project_id") for record in records}),
        "stage4_replay_state_counts": _counts(record.get("stage4_replay_state") for record in records),
        "current_project_binding_state_counts": _counts(record.get("current_project_binding_state") for record in records),
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


def _split_companies(value: Any) -> list[str]:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[一二三四五六七八九十\d]+家[：:]\s*", "", text)
    marker_matches = list(
        re.finditer(
            r"(?:^|[,，;；、])\s*[（(]\s*(?:主|成)\s*[）)]\s*(?P<company>[^,，;；、]+)",
            text,
        )
    )
    rows = [match.group("company") for match in marker_matches] if marker_matches else re.split(r"[,，;；、]", text)
    return _dedupe(_clean_company_name(row) for row in rows)


def _consortium_member_role(company: str, candidate_text: Any) -> str:
    text = str(candidate_text or "")
    if re.search(rf"[（(]\s*主\s*[）)]\s*{re.escape(company)}", text):
        return "lead_member"
    if re.search(rf"[（(]\s*成\s*[）)]\s*{re.escape(company)}", text):
        return "member"
    return ""


def _clean_company_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]\s*", "", text)
    text = re.sub(r"^(?:主|成)[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _candidate_group_id(project_id: str, companies: list[Mapping[str, str]]) -> str:
    return _stable_id("DESIGN-SURVEY-FLOW08-GROUP", project_id, *[item.get("company_name", "") for item in companies])


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint(parts)[:20]}"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


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
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


def _project_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _parse_project_ids(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；\s]+", value or "") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Stage4 inputs from targeted Flow08 design-survey attachment parse output.")
    parser.add_argument("--design-survey-flow08-attachment-parse-json", default="")
    parser.add_argument("--design-survey-flow08-attachment-parse-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = build_design_survey_flow08_stage4_inputs(
        design_survey_flow08_attachment_parse_json=args.design_survey_flow08_attachment_parse_json or None,
        design_survey_flow08_attachment_parse_root=args.design_survey_flow08_attachment_parse_root or None,
        output_root=args.output_root,
        project_ids=_parse_project_ids(args.project_ids),
        created_at=args.created_at or None,
    )
    if args.output_json:
        _write_json(Path(args.output_json), result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_ID",
    "DESIGN_SURVEY_FLOW08_STAGE4_INPUTS_KIND",
    "build_design_survey_flow08_stage4_inputs",
]
