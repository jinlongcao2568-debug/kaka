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
TARGET_ATTACHMENT_PARSE_BLOCKED = "TARGET_ATTACHMENT_PARSE_BLOCKED"


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
    summary = dict(parse_table["summary"])
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
    parse_state, next_action, review_reasons = _parse_state(
        extraction,
        enable_ocr=enable_ocr,
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
        "next_action": next_action,
        "review_reasons": review_reasons,
    }


def _parse_state(extraction: Mapping[str, Any], *, enable_ocr: bool) -> tuple[str, str, list[str]]:
    failures = {str(item) for item in _list(extraction.get("failure_reasons"))}
    fields = extraction.get("extracted_fields") if isinstance(extraction.get("extracted_fields"), Mapping) else {}
    if str(fields.get("extraction_state") or "") == "FIELDS_EXTRACTED":
        return (
            TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED,
            "apply_flow08_extracted_fields_to_design_survey_stage4_or_manual_review",
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
    "build_design_survey_flow08_target_attachment_parse",
]
