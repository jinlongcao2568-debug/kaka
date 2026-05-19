from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage4_verification.document_extraction import extract_document_text
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_KIND = "design_survey_flow08_target_attachment_parse_v1_manifest"
DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_VERSION = 1
DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_ID = "design-survey-flow08-target-attachment-parse-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/design-survey-flow08-target-attachment-parse-v1")

TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED = "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
TARGET_ATTACHMENT_OCR_REQUIRED = "TARGET_ATTACHMENT_OCR_REQUIRED"
TARGET_ATTACHMENT_OCR_ENGINE_UNAVAILABLE = "TARGET_ATTACHMENT_OCR_ENGINE_UNAVAILABLE"
TARGET_ATTACHMENT_OCR_LANGUAGE_UNAVAILABLE = "TARGET_ATTACHMENT_OCR_LANGUAGE_UNAVAILABLE"
TARGET_ATTACHMENT_OCR_NO_TEXT = "TARGET_ATTACHMENT_OCR_NO_TEXT"
TARGET_ATTACHMENT_NO_RESPONSIBLE_FIELD_FOUND = "TARGET_ATTACHMENT_NO_RESPONSIBLE_FIELD_FOUND"
TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED = "TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED"
TARGET_ATTACHMENT_PARSE_BLOCKED = "TARGET_ATTACHMENT_PARSE_BLOCKED"

PERSON_DOSSIER_DIRECTORY_PAGES = "1-8"
PERSON_DOSSIER_SPARSE_SCAN_STEP = 5
PERSON_DOSSIER_SPARSE_SCAN_MAX_PAGES = 80
PERSON_DOSSIER_WINDOW_BEFORE_PAGES = 2
PERSON_DOSSIER_WINDOW_AFTER_PAGES = 70
PERSON_DOSSIER_RESUME_MARKER_BACKTRACK_PAGES = 25


SnapshotReader = Callable[[str], bytes]
DocumentExtractor = Callable[..., Mapping[str, Any]]


def build_design_survey_flow08_target_attachment_parse(
    *,
    design_survey_flow08_readback_json: str | Path | None = None,
    design_survey_flow08_readback_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    enable_ocr: bool = False,
    max_pages: int = 20,
    ocr_max_pages: int = 2,
    ocr_page_ranges: str | None = None,
    person_dossier_enabled: bool = True,
    created_at: str | None = None,
    snapshot_reader: SnapshotReader | None = None,
    document_extractor: DocumentExtractor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    readback_manifest = _optional_manifest(
        explicit_json=design_survey_flow08_readback_json,
        root=design_survey_flow08_readback_root,
        default_file_name="design-survey-flow08-targeted-readback-v1.json",
    )
    if not readback_manifest:
        blocking_reasons.append("design_survey_flow08_readback_missing")

    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    target_records = [
        record
        for record in _target_attachment_records(readback_manifest)
        if not selected_projects or _project_key(record.get("project_id")) in selected_projects
    ]

    session: DatabaseSession | None = None
    repository: ObjectStorageRepository | None = None
    if snapshot_reader is None and readback_manifest:
        storage_root = _readback_storage_root(
            explicit_json=design_survey_flow08_readback_json,
            root=design_survey_flow08_readback_root,
        )
        settings = Settings(
            storage_backend="json-file",
            storage_path_optional=str(storage_root / "flow08-readback-storage.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(storage_root / "objects"),
        )
        session = DatabaseSession(settings=settings)
        repository = ObjectStorageRepository(session=session, settings=settings)
        snapshot_reader = repository.read_snapshot_bytes

    extractor = document_extractor or extract_document_text
    parse_records: list[dict[str, Any]] = []
    try:
        for record in target_records:
            parse_records.append(
                _build_parse_record(
                    attachment_record=record,
                    output_root=out_dir,
                    snapshot_reader=snapshot_reader,
                    extractor=extractor,
                    enable_ocr=enable_ocr,
                    max_pages=max_pages,
                    ocr_max_pages=ocr_max_pages,
                    ocr_page_ranges=ocr_page_ranges,
                    person_dossier_enabled=person_dossier_enabled,
                    created_at=created,
                )
            )
    finally:
        if session is not None:
            session.close()

    parse_table = {
        "summary": _summary(
            parse_records,
            blocking_reasons,
            enable_ocr=enable_ocr,
            ocr_page_ranges=ocr_page_ranges,
        ),
        "records": parse_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    person_dossier_table = {
        "summary": _person_dossier_summary(parse_records),
        "records": [
            record.get("person_dossier_evidence")
            for record in parse_records
            if isinstance(record.get("person_dossier_evidence"), Mapping)
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = dict(parse_table["summary"])
    summary.update(
        {
            "person_dossier_record_count": person_dossier_table["summary"]["person_dossier_record_count"],
            "person_dossier_current_binding_record_count": person_dossier_table["summary"][
                "person_dossier_current_binding_record_count"
            ],
        }
    )
    manifest = {
        "manifest_version": DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_VERSION,
        "manifest_kind": DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_KIND,
        "adapter_id": DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_ID,
        "pipeline_stage": "DesignSurveyFlow08TargetAttachmentParseV1",
        "manifest_id": f"DESIGN-SURVEY-FLOW08-PARSE-{_fingerprint({'records': parse_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_design_survey_flow08_readback_json": _manifest_source_path(
            design_survey_flow08_readback_json,
            design_survey_flow08_readback_root,
            "design-survey-flow08-targeted-readback-v1.json",
        ),
        "target_attachment_parse_table": parse_table,
        "person_dossier_evidence_table": person_dossier_table,
        "summary": summary,
        "scope_guardrails": {
            "consumes_existing_flow08_snapshot_only": True,
            "does_not_download_external_url": True,
            "targeted_parse_only": True,
            "do_not_parse_all_flow_08_by_default": True,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "external_service_connection_enabled": False,
            "fetch_public_urls_enabled": False,
            "download_enabled": False,
            "parse_enabled": True,
            "ocr_enabled": bool(enable_ocr),
            "ocr_page_ranges": str(ocr_page_ranges or ""),
            "person_dossier_enabled": bool(person_dossier_enabled),
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
        "design_survey_flow08_target_attachment_parse_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "design-survey-flow08-target-attachment-parse-v1.json", result)
    _write_json(out_dir / "target-attachment-parse-table.json", parse_table)
    return result


def _build_parse_record(
    *,
    attachment_record: Mapping[str, Any],
    output_root: Path,
    snapshot_reader: SnapshotReader | None,
    extractor: DocumentExtractor,
    enable_ocr: bool,
    max_pages: int,
    ocr_max_pages: int,
    ocr_page_ranges: str | None,
    person_dossier_enabled: bool,
    created_at: str,
) -> dict[str, Any]:
    project_id = str(attachment_record.get("project_id") or "").strip()
    snapshot_id = str(attachment_record.get("attachment_snapshot_id_optional") or "").strip()
    base = {
        "target_attachment_parse_id": _stable_id(
            "DESIGN-SURVEY-FLOW08-PARSE",
            project_id,
            attachment_record.get("target_attachment_id"),
            snapshot_id,
        ),
        "target_attachment_id": str(attachment_record.get("target_attachment_id") or ""),
        "project_id": project_id,
        "project_name": str(attachment_record.get("project_name") or ""),
        "candidate_company_text": str(attachment_record.get("candidate_company_text") or ""),
        "target_company_names": _list(attachment_record.get("target_company_names")),
        "matched_target_company_names": _list(attachment_record.get("matched_target_company_names")),
        "responsible_person_name": str(attachment_record.get("responsible_person_name") or ""),
        "attachment_url": str(attachment_record.get("attachment_url") or ""),
        "attachment_snapshot_id_optional": snapshot_id,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if str(attachment_record.get("attachment_fetch_state") or "") != "FETCHED":
        return {
            **base,
            "attachment_parse_state": TARGET_ATTACHMENT_PARSE_BLOCKED,
            "document_sha256": "",
            "extraction_methods": [],
            "extracted_fields": {},
            "extraction_failure_reasons": ["target_attachment_not_fetched"],
            "extraction_text_probe": "",
            "extraction_json_path": "",
            "next_action": "download_bound_flow08_target_attachment_then_parse_responsible_fields",
            "review_reasons": ["target_attachment_not_fetched"],
        }
    if not snapshot_id or snapshot_reader is None:
        return {
            **base,
            "attachment_parse_state": TARGET_ATTACHMENT_PARSE_BLOCKED,
            "document_sha256": "",
            "extraction_methods": [],
            "extracted_fields": {},
            "extraction_failure_reasons": ["attachment_snapshot_missing_or_reader_unavailable"],
            "extraction_text_probe": "",
            "extraction_json_path": "",
            "next_action": "retry_flow08_target_attachment_snapshot_readback",
            "review_reasons": ["attachment_snapshot_missing_or_reader_unavailable"],
        }

    try:
        data = snapshot_reader(snapshot_id)
    except Exception as exc:
        reason = f"attachment_snapshot_readback_failed:{type(exc).__name__}:{exc}"
        return {
            **base,
            "attachment_parse_state": TARGET_ATTACHMENT_PARSE_BLOCKED,
            "document_sha256": "",
            "extraction_methods": [],
            "extracted_fields": {},
            "extraction_failure_reasons": [reason],
            "extraction_text_probe": "",
            "extraction_json_path": "",
            "next_action": "retry_flow08_target_attachment_snapshot_readback",
            "review_reasons": [reason],
        }

    work_path = _materialize_snapshot(output_root, snapshot_id=snapshot_id, data=data)
    extraction = dict(
        extractor(
            work_path,
            enable_ocr=enable_ocr,
            max_pages=max_pages,
            ocr_max_pages=ocr_max_pages,
            ocr_page_ranges=ocr_page_ranges,
            opportunity_priority_class="C_MEDIUM_DESIGN_SURVEY",
        )
    )
    extraction_path = output_root / "extractions" / f"{base['target_attachment_parse_id']}.json"
    _write_json(extraction_path, extraction)
    person_dossier = (
        _build_person_dossier_evidence(
            work_path=work_path,
            target_person_name=str(base.get("responsible_person_name") or ""),
            extractor=extractor,
            output_root=output_root,
            parse_id=str(base["target_attachment_parse_id"]),
            enable_ocr=enable_ocr,
            created_at=created_at,
        )
        if person_dossier_enabled and enable_ocr
        else {}
    )
    parse_state, next_action, review_reasons = _parse_state(
        extraction,
        enable_ocr=enable_ocr,
        person_dossier=person_dossier,
    )
    return {
        **base,
        "attachment_parse_state": parse_state,
        "document_work_path": str(work_path),
        "document_sha256": str(extraction.get("sha256") or _sha256_bytes(data)),
        "extraction_methods": _list(extraction.get("extraction_methods")),
        "extracted_fields": dict(extraction.get("extracted_fields") or {}),
        "extraction_failure_reasons": _list(extraction.get("failure_reasons")),
        "extraction_page_count": len(_list(extraction.get("pages"))),
        "extraction_text_probe": _clip(extraction.get("text"), 1200),
        "extraction_json_path": str(extraction_path),
        "person_dossier_evidence": person_dossier,
        "next_action": next_action,
        "review_reasons": review_reasons,
    }


def _parse_state(
    extraction: Mapping[str, Any],
    *,
    enable_ocr: bool,
    person_dossier: Mapping[str, Any] | None = None,
) -> tuple[str, str, list[str]]:
    dossier = person_dossier if isinstance(person_dossier, Mapping) else {}
    if str(dossier.get("current_project_binding_state") or "") == "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND":
        return (
            TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED,
            "build_design_survey_flow08_stage4_inputs_from_person_dossier",
            ["current_project_person_dossier_extracted_from_target_flow08_attachment"],
        )
    failures = {str(item) for item in _list(extraction.get("failure_reasons"))}
    fields = extraction.get("extracted_fields") if isinstance(extraction.get("extracted_fields"), Mapping) else {}
    if str(fields.get("extraction_state") or "") == "FIELDS_EXTRACTED":
        return (
            TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED,
            "build_design_survey_flow08_stage4_inputs_from_extracted_fields",
            ["responsible_person_fields_extracted_from_target_flow08_attachment"],
        )
    text = str(extraction.get("text") or "").strip()
    if not enable_ocr and ("pdf_text_unavailable_or_ocr_required" in failures or len(text) < 80):
        return (
            TARGET_ATTACHMENT_OCR_REQUIRED,
            "rerun_design_survey_flow08_target_attachment_parse_with_ocr",
            ["target_attachment_has_no_embedded_text_ocr_required"],
        )
    if enable_ocr and "ocr_engine_unavailable" in failures and len(text) < 80:
        return (
            TARGET_ATTACHMENT_OCR_ENGINE_UNAVAILABLE,
            "fix_local_ocr_runtime_or_manual_ocr_readback",
            ["ocr_engine_unavailable_for_target_attachment"],
        )
    if enable_ocr and "tesseract_chinese_language_unavailable" in failures:
        return (
            TARGET_ATTACHMENT_OCR_LANGUAGE_UNAVAILABLE,
            "install_chinese_ocr_language_pack_or_manual_ocr_readback",
            ["chinese_ocr_language_pack_unavailable_for_target_attachment"],
        )
    if enable_ocr and "ocr_text_unavailable" in failures and len(text) < 80:
        return (
            TARGET_ATTACHMENT_OCR_NO_TEXT,
            "manual_review_pdf_pages_or_expand_ocr_page_budget",
            ["ocr_executed_but_no_text_extracted_from_target_attachment"],
        )
    if "document_path_missing" in failures:
        return (
            TARGET_ATTACHMENT_PARSE_BLOCKED,
            "retry_flow08_target_attachment_snapshot_readback",
            ["materialized_attachment_path_missing"],
        )
    return (
        TARGET_ATTACHMENT_NO_RESPONSIBLE_FIELD_FOUND,
        "manual_review_or_expand_targeted_attachment_parse_without_clearance_claim",
        ["target_attachment_text_extracted_but_no_responsible_person_field_found"],
    )


def _target_attachment_records(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    table = manifest.get("target_attachment_table") if isinstance(manifest.get("target_attachment_table"), Mapping) else {}
    records = [dict(record) for record in _list(table.get("records")) if isinstance(record, Mapping)]
    if records:
        return [
            record
            for record in records
            if str(record.get("target_attachment_match_state") or "") == "TARGET_CANDIDATE_ATTACHMENT_BOUND"
        ]
    readback_table = (
        manifest.get("flow08_targeted_readback_table")
        if isinstance(manifest.get("flow08_targeted_readback_table"), Mapping)
        else {}
    )
    out: list[dict[str, Any]] = []
    for readback in _list(readback_table.get("records")):
        if not isinstance(readback, Mapping):
            continue
        for record in _list(readback.get("target_attachment_records")):
            if isinstance(record, Mapping) and str(record.get("target_attachment_match_state") or "") == "TARGET_CANDIDATE_ATTACHMENT_BOUND":
                out.append(dict(record))
    return out


def _materialize_snapshot(output_root: Path, *, snapshot_id: str, data: bytes) -> Path:
    work_dir = output_root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".pdf" if data[:5] == b"%PDF-" else ".bin"
    path = work_dir / f"{_safe_filename(snapshot_id)}{suffix}"
    if not path.exists() or path.stat().st_size != len(data):
        path.write_bytes(data)
    return path


def _build_person_dossier_evidence(
    *,
    work_path: Path,
    target_person_name: str,
    extractor: DocumentExtractor,
    output_root: Path,
    parse_id: str,
    enable_ocr: bool,
    created_at: str,
) -> dict[str, Any]:
    target_name = str(target_person_name or "").strip()
    if not target_name:
        return {
            "person_dossier_state": "TARGET_PERSON_NAME_MISSING",
            "target_person_name": "",
            "current_project_binding_state": "PERSON_DOSSIER_NOT_EXTRACTED",
            "review_reasons": ["target_person_name_missing"],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    directory = dict(
        extractor(
            work_path,
            enable_ocr=enable_ocr,
            max_pages=1,
            ocr_max_pages=8,
            ocr_page_ranges=PERSON_DOSSIER_DIRECTORY_PAGES,
            opportunity_priority_class="C_MEDIUM_DESIGN_SURVEY",
        )
    )
    directory_entries = _personnel_directory_entries(_extracted_pages(directory))
    planned_ranges, strategy_state = _planned_person_dossier_ranges(
        work_path=work_path,
        directory_entries=directory_entries,
        target_person_name=target_name,
        extractor=extractor,
        enable_ocr=enable_ocr,
    )
    if not planned_ranges:
        return {
            "person_dossier_state": "PERSON_DOSSIER_PAGE_WINDOW_UNRESOLVED",
            "target_person_name": target_name,
            "directory_scan_pages": PERSON_DOSSIER_DIRECTORY_PAGES,
            "directory_entries": directory_entries,
            "planned_page_ranges": "",
            "current_project_binding_state": "PERSON_DOSSIER_NOT_EXTRACTED",
            "evidence_records": [],
            "review_reasons": ["person_dossier_directory_or_name_anchor_not_found"],
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    dossier_extraction = dict(
        extractor(
            work_path,
            enable_ocr=enable_ocr,
            max_pages=1,
            ocr_max_pages=len(_page_numbers_from_ranges(planned_ranges)),
            ocr_page_ranges=planned_ranges,
            opportunity_priority_class="C_MEDIUM_DESIGN_SURVEY",
        )
    )
    dossier_path = output_root / "person-dossiers" / f"{parse_id}.json"
    _write_json(dossier_path, dossier_extraction)
    evidence_records = _person_dossier_evidence_records(
        pages=_extracted_pages(dossier_extraction),
        target_person_name=target_name,
    )
    current_records = [
        record
        for record in evidence_records
        if str(record.get("current_project_binding_candidate_state") or "") == "CURRENT_PROJECT_PERSONNEL_CANDIDATE"
    ]
    supporting_records = [
        record
        for record in evidence_records
        if str(record.get("evidence_category") or "") in {
            "identity_document",
            "title_certificate",
            "degree_certificate",
            "social_security",
            "professional_qualification",
        }
    ]
    current_binding_state = (
        "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND"
        if current_records
        else "ONLY_SUPPORTING_OR_HISTORY_PERSON_EVIDENCE_FOUND"
        if evidence_records
        else "PERSON_DOSSIER_TARGET_NOT_FOUND"
    )
    return {
        "person_dossier_state": "PERSON_DOSSIER_EXTRACTED" if evidence_records else "PERSON_DOSSIER_TARGET_NOT_FOUND",
        "target_person_name": target_name,
        "directory_scan_pages": PERSON_DOSSIER_DIRECTORY_PAGES,
        "directory_entries": directory_entries,
        "page_window_strategy_state": strategy_state,
        "planned_page_ranges": planned_ranges,
        "current_project_binding_state": current_binding_state,
        "current_project_binding_evidence_count": len(current_records),
        "supporting_identity_or_credential_evidence_count": len(supporting_records),
        "evidence_category_counts": _counts(record.get("evidence_category") for record in evidence_records),
        "evidence_records": evidence_records,
        "dossier_extraction_json_path": str(dossier_path),
        "review_reasons": []
        if current_records
        else ["target_person_found_without_current_project_binding_table"]
        if evidence_records
        else ["target_person_not_found_in_person_dossier_window"],
        "sensitive_fields_policy": {
            "id_card_number_redacted": True,
            "social_security_number_redacted": True,
            "store_page_no_and_redacted_text_only": True,
        },
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _personnel_directory_entries(pages: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    keywords = ("人员简历表", "拟投入人员", "拟在本工程任职", "人员汇总表", "项目负责人", "社保", "身份证", "职称证", "学位证")
    entries: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page.get("page_no") or 0)
        for line in str(page.get("text") or "").splitlines():
            compact = _compact_text(line)
            if not any(keyword in compact for keyword in keywords):
                continue
            numbers = [int(value) for value in re.findall(r"\d{1,3}", line)]
            if not numbers:
                continue
            target_page = numbers[-1]
            if target_page <= 0:
                continue
            entries.append(
                {
                    "directory_source_page_no": page_no,
                    "entry_label": _clip(line, 160),
                    "target_page_no": target_page,
                    "entry_kind": _directory_entry_kind(compact),
                }
            )
    return _dedupe_records_by_key(entries, "target_page_no")


def _planned_person_dossier_ranges(
    *,
    work_path: Path,
    directory_entries: list[Mapping[str, Any]],
    target_person_name: str,
    extractor: DocumentExtractor,
    enable_ocr: bool,
) -> tuple[str, str]:
    page_count = _pdf_page_count(work_path)
    resume_pages = [
        int(entry.get("target_page_no") or 0)
        for entry in directory_entries
        if str(entry.get("entry_kind") or "") == "personnel_resume"
    ]
    personnel_pages = resume_pages or [
        int(entry.get("target_page_no") or 0)
        for entry in directory_entries
        if str(entry.get("entry_kind") or "") in {"personnel_resume", "personnel_summary", "project_personnel"}
    ]
    if personnel_pages:
        first_page = min(page for page in personnel_pages if page > 0)
        return _bounded_range(first_page, page_count), "DIRECTORY_PERSONNEL_ENTRY"

    sparse_pages = _sparse_scan_page_numbers(page_count)
    if not sparse_pages:
        return "", "PERSON_DOSSIER_PAGE_COUNT_UNAVAILABLE"
    sparse_extraction = dict(
        extractor(
            work_path,
            enable_ocr=enable_ocr,
            max_pages=1,
            ocr_max_pages=len(sparse_pages),
            ocr_page_ranges=",".join(str(page) for page in sparse_pages),
            opportunity_priority_class="C_MEDIUM_DESIGN_SURVEY",
        )
    )
    sparse_result_pages = _extracted_pages(sparse_extraction)
    hits = [
        int(page.get("page_no") or 0)
        for page in sparse_result_pages
        if _target_person_hit(str(page.get("text") or ""), target_person_name)
        and _person_dossier_page_hit_score(str(page.get("text") or ""), target_person_name) >= 10
    ]
    if hits:
        return _bounded_range(min(hits), page_count), "SPARSE_TARGET_NAME_OR_PERSONNEL_ANCHOR"
    resume_marker_hits = [
        int(page.get("page_no") or 0)
        for page in sparse_result_pages
        if int(page.get("page_no") or 0) > 20 and "人员简历表" in _compact_text(page.get("text"))
    ]
    if resume_marker_hits:
        # Sparse scan may hit the second person's resume first; back up a few pages to include the first responsible person.
        return (
            _bounded_range(max(1, min(resume_marker_hits) - PERSON_DOSSIER_RESUME_MARKER_BACKTRACK_PAGES), page_count),
            "SPARSE_PERSONNEL_RESUME_MARKER",
        )
    return "", "PERSON_DOSSIER_DIRECTORY_AND_SPARSE_SCAN_MISS"


def _person_dossier_evidence_records(
    *,
    pages: list[Mapping[str, Any]],
    target_person_name: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    in_target_person_block = False
    for page in pages:
        page_no = int(page.get("page_no") or 0)
        text = str(page.get("text") or "")
        compact = _compact_text(text)
        exact_name_hit = _target_person_hit(text, target_person_name)
        if "人员简历表" in compact:
            in_target_person_block = exact_name_hit
        if not exact_name_hit and not in_target_person_block:
            continue
        categories = _person_dossier_categories(text)
        if not categories:
            categories = ["person_name_context"]
        history_only = _is_history_performance_page(text)
        current_candidate = (
            exact_name_hit
            and not history_only
            and any(
                category in categories
                for category in ("personnel_resume", "personnel_summary", "project_personnel", "professional_qualification")
            )
        )
        for category in categories:
            records.append(
                {
                    "person_dossier_evidence_id": _stable_id(
                        "PERSON-DOSSIER-EVIDENCE",
                        target_person_name,
                        page_no,
                        category,
                        text[:80],
                    ),
                    "page_no": page_no,
                    "target_person_name": target_person_name,
                    "person_name_hit_state": "EXACT_OR_BLOCK_ANCHORED_NAME_HIT"
                    if exact_name_hit or in_target_person_block
                    else "NO_NAME_HIT",
                    "evidence_category": category,
                    "current_project_binding_candidate_state": "CURRENT_PROJECT_PERSONNEL_CANDIDATE"
                    if current_candidate
                    else "SUPPORTING_OR_HISTORY_EVIDENCE",
                    "history_performance_page": history_only,
                    "redacted_text_probe": _redact_sensitive(_clip(text, 900)),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return records


def _person_dossier_categories(text: str) -> list[str]:
    compact = _compact_text(text)
    categories: list[str] = []
    if "人员简历表" in compact:
        categories.append("personnel_resume")
    if any(token in compact for token in ("拟在本工程任职", "拟投入人员", "人员汇总表", "员汇总表", "人员投入", "项目负责人", "技术负责人", "目任")):
        categories.append("personnel_summary")
    if any(token in compact for token in ("身份证", "公民身份号码", "居民身份")):
        categories.append("identity_document")
    if any(token in compact for token in ("职称", "工程师", "专业技术资格")):
        categories.append("title_certificate")
    if any(token in compact for token in ("学位", "毕业证", "毕业院校", "学历")):
        categories.append("degree_certificate")
    if any(token in compact for token in ("社保", "社会保险", "参保", "参保证明")):
        categories.append("social_security")
    if any(token in compact for token in ("注册测绘师", "职业资格", "注册证书")):
        categories.append("professional_qualification")
    if _is_history_performance_page(text):
        categories.append("history_performance")
    return _dedupe(categories)


def _person_dossier_page_hit_score(text: str, target_person_name: str) -> int:
    compact = _compact_text(text)
    score = 0
    if _target_person_hit(text, target_person_name):
        score += 10
    if any(token in compact for token in ("人员简历表", "拟在本工程任职", "人员汇总表", "项目负责人")):
        score += 8
    if any(token in compact for token in ("职称", "注册测绘师", "身份证", "社保", "学位")):
        score += 3
    if _is_history_performance_page(text):
        score -= 6
    return score


def _target_person_hit(text: str, target_person_name: str) -> bool:
    target = _compact_text(target_person_name)
    compact = _compact_text(text)
    if not target:
        return False
    if target in compact:
        return True
    if len(target) >= 3:
        pairs = {target[:2], target[-2:]}
        if any(pair and pair in compact for pair in pairs):
            return True
    position = -1
    for char in target:
        next_position = compact.find(char, position + 1)
        if next_position < 0:
            return False
        if position >= 0 and next_position - position > 40:
            return False
        position = next_position
    return True


def _bounded_range(anchor_page: int, page_count: int) -> str:
    start = max(1, int(anchor_page or 1) - PERSON_DOSSIER_WINDOW_BEFORE_PAGES)
    end_limit = int(page_count or 0) if page_count else anchor_page + PERSON_DOSSIER_WINDOW_AFTER_PAGES
    end = min(end_limit, int(anchor_page or 1) + PERSON_DOSSIER_WINDOW_AFTER_PAGES)
    return f"{start}-{end}"


def _sparse_scan_page_numbers(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    pages = list(range(1, page_count + 1, PERSON_DOSSIER_SPARSE_SCAN_STEP))
    if page_count not in pages:
        pages.append(page_count)
    return pages[:PERSON_DOSSIER_SPARSE_SCAN_MAX_PAGES]


def _page_numbers_from_ranges(value: str) -> list[int]:
    pages: list[int] = []
    for part in str(value or "").split(","):
        text = part.strip()
        if not text:
            continue
        if "-" in text:
            left, right = text.split("-", 1)
            start = _safe_positive_int(left)
            end = _safe_positive_int(right)
        else:
            start = end = _safe_positive_int(text)
        if start <= 0 or end <= 0:
            continue
        if end < start:
            start, end = end, start
        pages.extend(range(start, end + 1))
    return _dedupe_ints(pages)


def _extracted_pages(extraction: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [page for page in _list(extraction.get("pages")) if isinstance(page, Mapping)]


def _directory_entry_kind(compact: str) -> str:
    if "人员简历表" in compact:
        return "personnel_resume"
    if any(token in compact for token in ("拟投入人员", "拟在本工程任职", "人员汇总表", "项目负责人")):
        return "personnel_summary"
    if any(token in compact for token in ("身份证", "职称证", "学位证", "社保")):
        return "supporting_person_document"
    return "project_personnel"


def _is_history_performance_page(text: str) -> bool:
    compact = _compact_text(text)
    return any(token in compact for token in ("类似项目业绩", "工程名称", "开竣工日期")) and "人员简历表" not in compact


def _compact_text(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or ""))


def _redact_sensitive(value: str) -> str:
    text = re.sub(
        r"(?<!\d)(\d{4})\d{10}(\d{3}[\dXx])(?!\d)",
        r"\1********\2",
        str(value or ""),
    )
    text = re.sub(r"(?<!\d)(\d{4})\d{8,}(\d{4})(?!\d)", r"\1********\2", text)
    return text


def _pdf_page_count(path: Path) -> int:
    try:
        import fitz  # type: ignore

        with fitz.open(str(path)) as doc:
            return int(getattr(doc, "page_count", 0) or 0)
    except Exception:
        return 0


def _summary(
    records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    *,
    enable_ocr: bool,
    ocr_page_ranges: str | None,
) -> dict[str, Any]:
    return {
        "target_attachment_parse_record_count": len(records),
        "attachment_parse_state_counts": _counts(record.get("attachment_parse_state") for record in records),
        "field_extracted_record_count": sum(
            1
            for record in records
            if str(record.get("attachment_parse_state") or "") == TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED
        ),
        "person_dossier_extracted_record_count": sum(
            1
            for record in records
            if str(record.get("attachment_parse_state") or "") == TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED
        ),
        "ocr_required_record_count": sum(
            1
            for record in records
            if str(record.get("attachment_parse_state") or "") == TARGET_ATTACHMENT_OCR_REQUIRED
        ),
        "ocr_enabled": bool(enable_ocr),
        "ocr_page_ranges": str(ocr_page_ranges or ""),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _person_dossier_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    dossiers = [record.get("person_dossier_evidence") for record in records if isinstance(record.get("person_dossier_evidence"), Mapping)]
    return {
        "person_dossier_record_count": len(dossiers),
        "person_dossier_state_counts": _counts(dossier.get("person_dossier_state") for dossier in dossiers),
        "person_dossier_current_binding_record_count": sum(
            1
            for dossier in dossiers
            if str(dossier.get("current_project_binding_state") or "") == "CURRENT_PROJECT_PERSONNEL_DOSSIER_FOUND"
        ),
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
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    return dict(manifest) if isinstance(manifest, Mapping) else {}


def _readback_storage_root(*, explicit_json: str | Path | None, root: str | Path | None) -> Path:
    if root:
        return Path(root)
    if explicit_json:
        return Path(explicit_json).parent
    return Path(".")


def _manifest_source_path(explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> str:
    if explicit_json:
        return str(explicit_json)
    if root:
        return str(Path(root) / default_file_name)
    return ""


def _project_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _safe_filename(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text[:120] or "attachment"


def _stable_id(prefix: str, *values: Any) -> str:
    return f"{prefix}-{_fingerprint(values)[:16].upper()}"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _dedupe_ints(values: Any) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number in seen:
            continue
        seen.add(number)
        out.append(number)
    return out


def _dedupe_records_by_key(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        value = str(record.get(key) or "")
        if value in seen:
            continue
        seen.add(value)
        out.append(record)
    return out


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _clip(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[: max(0, limit)]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _safe_positive_int(value: str) -> int:
    try:
        number = int(str(value or "").strip())
    except ValueError:
        return 0
    return number if number > 0 else 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse downloaded design-survey Flow08 target attachment snapshots.")
    parser.add_argument("--design-survey-flow08-readback-json", default="")
    parser.add_argument("--design-survey-flow08-readback-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--ocr-max-pages", type=int, default=2)
    parser.add_argument("--ocr-page-ranges", default="")
    parser.add_argument("--disable-person-dossier", action="store_true")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_design_survey_flow08_target_attachment_parse(
        design_survey_flow08_readback_json=args.design_survey_flow08_readback_json or None,
        design_survey_flow08_readback_root=args.design_survey_flow08_readback_root or None,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        enable_ocr=bool(args.enable_ocr),
        max_pages=max(1, int(args.max_pages or 1)),
        ocr_max_pages=max(1, int(args.ocr_max_pages or 1)),
        ocr_page_ranges=args.ocr_page_ranges or None,
        person_dossier_enabled=not bool(args.disable_person_dossier),
    )
    output_json = (
        Path(args.output_json)
        if args.output_json
        else Path(args.output_root) / "design-survey-flow08-target-attachment-parse-v1.json"
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
    "DESIGN_SURVEY_FLOW08_ATTACHMENT_PARSE_KIND",
    "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED",
    "TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED",
    "build_design_survey_flow08_target_attachment_parse",
]
