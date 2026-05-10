from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


PROFESSIONAL_CLEAN_ARCHIVE_MANIFEST_KIND = "professional_clean_project_archive_manifest"
PROFESSIONAL_CLEAN_ARCHIVE_MANIFEST_VERSION = 1
PROFESSIONAL_CLEAN_ARCHIVE_ADAPTER_ID = "professional-clean-project-archive-builder"

PROJECT_STAGE_POLLUTION_MARKERS = (
    "中标候选人公示",
    "中标结果",
    "成交结果",
    "合同",
    "招标计划",
    "开标记录",
)
SECTION_MARKERS = {
    "qualification_section_found": ("资格条件", "资格要求", "投标人资格", "供应商资格"),
    "scoring_section_found": ("评分办法", "评标办法", "评分标准", "综合评分"),
    "technical_section_found": ("技术参数", "技术要求", "采购需求", "服务要求"),
}
VALID_ATTACHMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"}
VALID_ATTACHMENT_CONTENT_MARKERS = (
    "pdf",
    "word",
    "excel",
    "spreadsheet",
    "zip",
    "rar",
    "octet-stream",
)


def build_professional_clean_project_archive_manifest(
    *,
    real_sample_execution_manifest_json: str | Path,
    output_root: str | Path,
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    object_repository: ObjectStorageRepository | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    input_path = Path(real_sample_execution_manifest_json)
    root = Path(output_root)
    blocking_reasons: list[str] = []
    payload = _load_json_file(input_path, "real_sample_execution_manifest", blocking_reasons)
    source_manifest = _source_manifest(payload)
    project_items = [
        dict(item)
        for item in list(source_manifest.get("project_sample_items") or [])
        if isinstance(item, Mapping)
    ]
    if not project_items and not blocking_reasons:
        blocking_reasons.append("project_sample_items_missing")

    repository = object_repository or _repository(
        storage_path=storage_path,
        object_storage_path=object_storage_path,
    )
    project_groups = _group_project_items(project_items)
    archive_items = [
        _archive_project(
            project_id=project_id,
            samples=samples,
            root=root,
            repository=repository,
        )
        for project_id, samples in sorted(project_groups.items())
    ]
    summary = _summary(archive_items)
    manifest = {
        "manifest_version": PROFESSIONAL_CLEAN_ARCHIVE_MANIFEST_VERSION,
        "manifest_kind": PROFESSIONAL_CLEAN_ARCHIVE_MANIFEST_KIND,
        "adapter_id": PROFESSIONAL_CLEAN_ARCHIVE_ADAPTER_ID,
        "manifest_id": f"PROFESSIONAL-CLEAN-ARCHIVE-{_fingerprint({'items': archive_items, 'summary': summary})[:16]}",
        "created_at": created,
        "source_real_sample_execution_manifest_id": str(source_manifest.get("manifest_id") or ""),
        "source_real_sample_execution_manifest_path": str(input_path),
        "output_root": str(root),
        "projects_root": str(root / "projects"),
        "items": archive_items,
        "sample_items": archive_items[:80],
        "summary": summary,
        "safety": {
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "database_write_enabled": False,
            "active_legacy_path_allowed": False,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    root.mkdir(parents=True, exist_ok=True)
    (root / "project-file-audit.json").write_text(
        json.dumps({"manifest": manifest, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "professional_clean_project_archive_mode": "DRY_RUN",
        "execute": False,
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "database_write_enabled": False,
            "customer_visible_allowed": False,
        },
    }


def _archive_project(
    *,
    project_id: str,
    samples: list[Mapping[str, Any]],
    root: Path,
    repository: ObjectStorageRepository,
) -> dict[str, Any]:
    first = samples[0] if samples else {}
    jurisdiction = str(first.get("jurisdiction") or "UNKNOWN")
    project_dir = root / "projects" / _safe_path_part(jurisdiction) / _safe_path_part(project_id)
    detail_dir = project_dir / "detail"
    file_dir = project_dir / "files"
    parsed_dir = project_dir / "parsed"
    for directory in (detail_dir, file_dir, parsed_dir):
        directory.mkdir(parents=True, exist_ok=True)

    detail_files = _materialize_refs(
        samples=samples,
        ref_key="detail_snapshot_refs",
        output_dir=detail_dir,
        file_prefix="detail",
        repository=repository,
    )
    attachment_files = _materialize_refs(
        samples=samples,
        ref_key="attachment_snapshot_refs",
        output_dir=file_dir,
        file_prefix="attachment",
        repository=repository,
    )
    source_text = "\n".join(
        str(value)
        for sample in samples
        for value in (
            sample.get("project_name"),
            sample.get("source_text"),
            (sample.get("parse_summary") or {}).get("text_probe")
            if isinstance(sample.get("parse_summary"), Mapping)
            else "",
        )
        if value
    )
    stage_pollution_reasons = _stage_pollution_reasons(samples, source_text)
    section_flags = _section_flags(source_text)
    parse_metrics = _parse_metrics(samples=samples, section_flags=section_flags)
    project_contract = _project_completeness_contract(
        samples=samples,
        detail_files=detail_files,
        attachment_files=attachment_files,
        parse_metrics=parse_metrics,
        stage_pollution_reasons=stage_pollution_reasons,
    )
    file_inventory = _file_inventory(
        project_id=project_id,
        detail_files=detail_files,
        attachment_files=attachment_files,
        parse_metrics=parse_metrics,
    )
    verification_urls = _verification_urls(samples=samples, file_inventory=file_inventory)
    failure_reasons = _failure_reasons(
        samples,
        detail_files,
        attachment_files,
        stage_pollution_reasons,
        parse_metrics,
        project_contract,
    )
    audit = {
        "project_id": project_id,
        "project_name": str(first.get("project_name") or ""),
        "jurisdiction": jurisdiction,
        "source_profile_ids": _dedupe_strings(sample.get("source_profile_id") for sample in samples),
        "document_kinds": _dedupe_strings(sample.get("document_kind") for sample in samples),
        "source_urls": _dedupe_strings(sample.get("source_url") for sample in samples),
        "verification_urls": verification_urls,
        "sample_count": len(samples),
        "detail_file_count": len(detail_files),
        "attachment_file_count": len(attachment_files),
        "replayable_file_count": sum(1 for item in detail_files + attachment_files if item.get("replayable")),
        "parsed_file_count": parse_metrics["stage3_parse_success_count"],
        "parse_attempted_file_count": parse_metrics["parse_attempted_file_count"],
        "parse_failed_file_count": parse_metrics["stage3_parse_failed_count"],
        "parse_blocked_file_count": parse_metrics["parse_blocked_file_count"],
        "valid_tender_attachment_count": sum(1 for item in attachment_files if item.get("valid_tender_attachment")),
        "html_pollution_file_count": sum(1 for item in attachment_files if item.get("html_pollution")),
        "stage_pollution_reasons": stage_pollution_reasons,
        **section_flags,
        "parse_metrics": parse_metrics,
        "project_completeness_contract": project_contract,
        "file_inventory": file_inventory,
        "completion_rate": _completion_rate(detail_files=detail_files, attachment_files=attachment_files),
        "failure_reasons": failure_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    project_payload = {
        "project_id": project_id,
        "project_name": audit["project_name"],
        "jurisdiction": jurisdiction,
        "source_profile_ids": audit["source_profile_ids"],
        "document_kinds": audit["document_kinds"],
        "source_urls": audit["source_urls"],
        "verification_urls": verification_urls,
        "samples": [_sample_card(sample) for sample in samples],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    (project_dir / "project.json").write_text(
        json.dumps(project_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (project_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (parsed_dir / "parse-summary.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "project_name": audit["project_name"],
                "verification_urls": verification_urls,
                "parse_metrics": parse_metrics,
                "section_flags": section_flags,
                "project_completeness_contract": project_contract,
                "file_level_parse_attribution_state": parse_metrics["file_level_parse_attribution_state"],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        **audit,
        "project_dir": str(project_dir),
        "detail_files": detail_files,
        "attachment_files": attachment_files,
    }


def _materialize_refs(
    *,
    samples: list[Mapping[str, Any]],
    ref_key: str,
    output_dir: Path,
    file_prefix: str,
    repository: ObjectStorageRepository,
) -> list[dict[str, Any]]:
    refs: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        for ref in list(sample.get(ref_key) or []):
            if not isinstance(ref, Mapping):
                continue
            snapshot_id = str(ref.get("snapshot_id") or "")
            if not snapshot_id or snapshot_id in seen:
                continue
            seen.add(snapshot_id)
            ref_payload = dict(ref)
            ref_payload.setdefault("parent_document_kind", sample.get("document_kind"))
            ref_payload.setdefault("parent_source_url", sample.get("source_url"))
            refs.append(ref_payload)

    materialized: list[dict[str, Any]] = []
    for index, ref in enumerate(refs, start=1):
        snapshot_id = str(ref.get("snapshot_id") or "")
        readback = repository.replay_snapshot(snapshot_id)
        content_type = str(readback.get("content_type") or "")
        extension = _extension_for_ref(ref, content_type)
        file_name = f"{index:03d}_{file_prefix}_{_safe_path_part(snapshot_id[-12:])}{extension}"
        file_path = output_dir / file_name
        replayable = bool(readback.get("replayable"))
        source_url = _ref_source_url(ref, readback)
        if replayable:
            file_path.write_bytes(readback.get("bytes") or b"")
        meta = {
            "file_id": f"{file_prefix.upper()}-{index:03d}-{_safe_path_part(snapshot_id[-12:])}",
            "file_role": file_prefix,
            "snapshot_id": snapshot_id,
            "source_url": source_url,
            "parent_source_url": str(ref.get("parent_source_url") or ""),
            "parent_document_kind": str(ref.get("parent_document_kind") or ""),
            "content_type": content_type,
            "byte_size": _int_value(readback.get("byte_size"), default=0),
            "sha256": str(readback.get("sha256") or ""),
            "replayable": replayable,
            "download_state": "DOWNLOADED_REPLAYABLE" if replayable else "SNAPSHOT_READBACK_FAILED",
            "readback_state": str(readback.get("readback_state") or ""),
            "file_path": str(file_path) if replayable else "",
            "meta_path": str(file_path.with_suffix(file_path.suffix + ".meta.json")),
            "attachment_role_type": str(ref.get("attachment_role_type") or ""),
            "attachment_parse_state": str(ref.get("parse_state") or ""),
            "valid_tender_attachment": _is_valid_tender_attachment(ref, content_type, extension),
            "html_pollution": _is_html_pollution(content_type, extension),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        file_path.with_suffix(file_path.suffix + ".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        materialized.append(meta)
    return materialized


def _summary(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "project_count": len(items),
        "detail_file_count": sum(_int_value(item.get("detail_file_count"), default=0) for item in items),
        "attachment_file_count": sum(_int_value(item.get("attachment_file_count"), default=0) for item in items),
        "replayable_file_count": sum(_int_value(item.get("replayable_file_count"), default=0) for item in items),
        "valid_tender_attachment_count": sum(
            _int_value(item.get("valid_tender_attachment_count"), default=0) for item in items
        ),
        "html_pollution_file_count": sum(_int_value(item.get("html_pollution_file_count"), default=0) for item in items),
        "stage_pollution_project_count": sum(1 for item in items if item.get("stage_pollution_reasons")),
        "complete_project_count": sum(1 for item in items if not item.get("failure_reasons")),
        "download_incomplete_project_count": sum(
            1
            for item in items
            if (item.get("project_completeness_contract") or {}).get("download_completeness_state")
            != "DOWNLOAD_COMPLETE"
        ),
        "parse_incomplete_project_count": sum(
            1
            for item in items
            if (item.get("project_completeness_contract") or {}).get("parse_completeness_state")
            != "PARSE_COMPLETE"
        ),
        "project_readiness_state_counts": _counts(
            (item.get("project_completeness_contract") or {}).get("overall_project_readiness_state")
            for item in items
        ),
        "parse_insufficiency_counts": _counts(
            reason
            for item in items
            for reason in _as_list((item.get("parse_metrics") or {}).get("parse_insufficiency_reasons"))
        ),
        "failure_reason_counts": _counts(
            reason for item in items for reason in _as_list(item.get("failure_reasons"))
        ),
        "file_level_parse_attribution_missing_count": sum(
            1
            for item in items
            if (item.get("parse_metrics") or {}).get("file_level_parse_attribution_state")
            == "PROJECT_LEVEL_ONLY_MISSING_FILE_LEVEL_ATTRIBUTION"
        ),
        "source_profile_counts": _counts(
            profile_id
            for item in items
            for profile_id in _as_list(item.get("source_profile_ids"))
        ),
        "document_kind_counts": _counts(
            document_kind
            for item in items
            for document_kind in _as_list(item.get("document_kinds"))
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _repository(
    *,
    storage_path: str | Path | None,
    object_storage_path: str | Path | None,
) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage_path or "tmp/evaluation-real-samples/professional-clean-v1/storage.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage_path or "tmp/evaluation-real-samples/professional-clean-v1/objects"),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def _sample_card(sample: Mapping[str, Any]) -> dict[str, Any]:
    parse_summary = sample.get("parse_summary") if isinstance(sample.get("parse_summary"), Mapping) else {}
    return {
        "target_id": str(sample.get("target_id") or ""),
        "parent_target_id": str(sample.get("parent_target_id") or ""),
        "candidate_key": str(sample.get("candidate_key") or ""),
        "document_kind": str(sample.get("document_kind") or ""),
        "source_profile_id": str(sample.get("source_profile_id") or ""),
        "source_url": str(sample.get("source_url") or ""),
        "target_execution_state": str(sample.get("target_execution_state") or ""),
        "document_completeness_state": str(sample.get("document_completeness_state") or ""),
        "notice_version_chain_state": str(sample.get("notice_version_chain_state") or ""),
        "detail_snapshot_count": len(list(sample.get("detail_snapshot_refs") or [])),
        "attachment_snapshot_count": len(list(sample.get("attachment_snapshot_refs") or [])),
        "parse_summary": {
            "stage3_parse_success_count": parse_summary.get("stage3_parse_success_count", 0),
            "stage3_parse_failed_count": parse_summary.get("stage3_parse_failed_count", 0),
            "attachment_missing_review_count": parse_summary.get("attachment_missing_review_count", 0),
            "unknown_attachment_count": parse_summary.get("unknown_attachment_count", 0),
        },
        "failure_taxonomy": _as_list(sample.get("failure_taxonomy")),
    }


def _stage_pollution_reasons(samples: list[Mapping[str, Any]], source_text: str) -> list[str]:
    reasons: list[str] = []
    if any(str(sample.get("document_kind") or "") == "tender_file" for sample in samples):
        for marker in PROJECT_STAGE_POLLUTION_MARKERS:
            if marker in source_text:
                reasons.append(f"tender_file_stage_text_contains:{marker}")
    return _dedupe_strings(reasons)


def _section_flags(source_text: str) -> dict[str, bool]:
    return {
        field_name: any(marker in source_text for marker in markers)
        for field_name, markers in SECTION_MARKERS.items()
    }


def _parse_metrics(*, samples: list[Mapping[str, Any]], section_flags: Mapping[str, bool]) -> dict[str, Any]:
    parse_summaries = [
        dict(sample.get("parse_summary") or {})
        for sample in samples
        if isinstance(sample.get("parse_summary"), Mapping)
    ]
    success_count = sum(
        _int_value(summary.get("stage3_parse_success_count"), default=0)
        for summary in parse_summaries
    )
    failed_count = sum(
        _int_value(summary.get("stage3_parse_failed_count"), default=0)
        for summary in parse_summaries
    )
    ocr_required_count = sum(
        _int_value(summary.get("ocr_required_count"), default=0)
        + _int_value(summary.get("attachment_ocr_required_count"), default=0)
        for summary in parse_summaries
    )
    attachment_missing_count = sum(
        _int_value(summary.get("attachment_missing_review_count"), default=0)
        for summary in parse_summaries
    )
    unknown_attachment_count = sum(
        _int_value(summary.get("unknown_attachment_count"), default=0)
        for summary in parse_summaries
    )
    clarification_review_count = sum(
        _int_value(summary.get("clarification_version_review_count"), default=0)
        for summary in parse_summaries
    )
    parse_attempted_count = success_count + failed_count + ocr_required_count
    section_missing = [
        key
        for key in (
            "qualification_section_found",
            "scoring_section_found",
            "technical_section_found",
        )
        if not bool(section_flags.get(key))
    ]
    markitdown_state_counts = _counts(
        _string_value(summary.get("markitdown_state"))
        for summary in parse_summaries
        if _string_value(summary.get("markitdown_state"))
    )
    parse_insufficiency_reasons: list[str] = []
    if not parse_summaries:
        parse_insufficiency_reasons.append("parse_summary_missing")
    if success_count <= 0:
        parse_insufficiency_reasons.append("stage3_parse_success_missing")
    if failed_count > 0:
        parse_insufficiency_reasons.append("stage3_parse_failed")
    if ocr_required_count > 0:
        parse_insufficiency_reasons.append("ocr_required")
    if attachment_missing_count > 0:
        parse_insufficiency_reasons.append("attachment_missing_review")
    if unknown_attachment_count > 0:
        parse_insufficiency_reasons.append("unknown_attachment_review")
    if clarification_review_count > 0:
        parse_insufficiency_reasons.append("clarification_or_addendum_review")
    if section_missing:
        parse_insufficiency_reasons.append("required_section_text_missing")

    return {
        "stage3_parse_success_count": success_count,
        "stage3_parse_failed_count": failed_count,
        "ocr_required_count": ocr_required_count,
        "attachment_missing_review_count": attachment_missing_count,
        "unknown_attachment_count": unknown_attachment_count,
        "clarification_version_review_count": clarification_review_count,
        "parse_attempted_file_count": parse_attempted_count,
        "parse_blocked_file_count": ocr_required_count + attachment_missing_count + unknown_attachment_count,
        "section_missing_fields": section_missing,
        "markitdown_state_counts": markitdown_state_counts,
        "parse_insufficiency_reasons": _dedupe_strings(parse_insufficiency_reasons),
        "file_level_parse_attribution_state": "PROJECT_LEVEL_ONLY_MISSING_FILE_LEVEL_ATTRIBUTION"
        if parse_summaries
        else "PARSE_SUMMARY_MISSING",
        "download_then_parse_required": True,
        "parse_from_replay_snapshot_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_completeness_contract(
    *,
    samples: list[Mapping[str, Any]],
    detail_files: list[Mapping[str, Any]],
    attachment_files: list[Mapping[str, Any]],
    parse_metrics: Mapping[str, Any],
    stage_pollution_reasons: list[str],
) -> dict[str, Any]:
    has_tender_sample = any(str(sample.get("document_kind") or "") == "tender_file" for sample in samples)
    replayable_detail_count = sum(1 for item in detail_files if item.get("replayable"))
    replayable_attachment_count = sum(1 for item in attachment_files if item.get("replayable"))
    valid_tender_attachment_count = sum(1 for item in attachment_files if item.get("valid_tender_attachment"))
    expected_detail_min = 1
    expected_valid_tender_attachment_min = 1 if has_tender_sample else 0
    download_reasons: list[str] = []
    if replayable_detail_count < expected_detail_min:
        download_reasons.append("detail_snapshot_not_replayable")
    if has_tender_sample and not attachment_files:
        download_reasons.append("tender_attachment_not_found_or_not_downloaded")
    if has_tender_sample and attachment_files and replayable_attachment_count <= 0:
        download_reasons.append("attachment_snapshot_not_replayable")
    if has_tender_sample and replayable_attachment_count > 0 and valid_tender_attachment_count <= 0:
        download_reasons.append("valid_tender_attachment_not_identified")
    if stage_pollution_reasons:
        download_reasons.append("stage_pollution_detected")

    parse_reasons = list(parse_metrics.get("parse_insufficiency_reasons") or [])
    if valid_tender_attachment_count > 0 and _int_value(parse_metrics.get("stage3_parse_success_count"), default=0) <= 0:
        parse_reasons.append("downloaded_tender_attachment_but_parse_success_missing")
    if valid_tender_attachment_count > 0 and _as_list(parse_metrics.get("section_missing_fields")):
        parse_reasons.append("downloaded_tender_attachment_but_required_sections_missing")

    download_state = "DOWNLOAD_COMPLETE" if not download_reasons else "DOWNLOAD_INCOMPLETE"
    parse_state = "PARSE_COMPLETE" if not _dedupe_strings(parse_reasons) else "PARSE_INCOMPLETE"
    if download_state != "DOWNLOAD_COMPLETE":
        overall = "DOWNLOAD_BLOCKED"
    elif parse_state != "PARSE_COMPLETE":
        overall = "PARSE_BLOCKED"
    elif stage_pollution_reasons:
        overall = "STAGE_POLLUTION_REVIEW"
    else:
        overall = "PROJECT_READY_FOR_SIGNAL_ANALYSIS"

    return {
        "expected_detail_min": expected_detail_min,
        "expected_valid_tender_attachment_min": expected_valid_tender_attachment_min,
        "replayable_detail_count": replayable_detail_count,
        "replayable_attachment_count": replayable_attachment_count,
        "valid_tender_attachment_count": valid_tender_attachment_count,
        "download_completeness_state": download_state,
        "download_blocking_reasons": _dedupe_strings(download_reasons),
        "parse_completeness_state": parse_state,
        "parse_blocking_reasons": _dedupe_strings(parse_reasons),
        "overall_project_readiness_state": overall,
        "download_before_parse_required": True,
        "official_analysis_input": "LOCAL_REPLAY_SNAPSHOT_ONLY",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _file_inventory(
    *,
    project_id: str,
    detail_files: list[Mapping[str, Any]],
    attachment_files: list[Mapping[str, Any]],
    parse_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for item in detail_files + attachment_files:
        file_role = str(item.get("file_role") or "")
        replayable = bool(item.get("replayable"))
        valid_tender_attachment = bool(item.get("valid_tender_attachment"))
        parse_state = "NOT_PARSE_TARGET"
        if file_role == "detail":
            parse_state = "DETAIL_TEXT_OR_METADATA_CAPTURED" if replayable else "DETAIL_SNAPSHOT_READBACK_FAILED"
        elif file_role == "attachment":
            if not replayable:
                parse_state = "ATTACHMENT_SNAPSHOT_READBACK_FAILED"
            elif not valid_tender_attachment:
                parse_state = "ATTACHMENT_NOT_VALID_TENDER_DOCUMENT"
            elif _int_value(parse_metrics.get("stage3_parse_success_count"), default=0) > 0:
                parse_state = "PROJECT_LEVEL_PARSE_SUCCESS_FILE_ATTRIBUTION_UNCONFIRMED"
            elif _int_value(parse_metrics.get("ocr_required_count"), default=0) > 0:
                parse_state = "OCR_REQUIRED"
            elif _int_value(parse_metrics.get("stage3_parse_failed_count"), default=0) > 0:
                parse_state = "PARSE_FAILED"
            else:
                parse_state = "PARSE_NOT_CONFIRMED"
        inventory.append(
            {
                "project_id": project_id,
                "file_id": str(item.get("file_id") or ""),
                "file_role": file_role,
                "snapshot_id": str(item.get("snapshot_id") or ""),
                "source_url": str(item.get("source_url") or ""),
                "file_path": str(item.get("file_path") or ""),
                "content_type": str(item.get("content_type") or ""),
                "byte_size": _int_value(item.get("byte_size"), default=0),
                "sha256": str(item.get("sha256") or ""),
                "download_state": str(item.get("download_state") or ""),
                "readback_state": str(item.get("readback_state") or ""),
                "valid_tender_attachment": valid_tender_attachment,
                "html_pollution": bool(item.get("html_pollution")),
                "parse_state": parse_state,
                "parse_attribution_state": str(parse_metrics.get("file_level_parse_attribution_state") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return inventory


def _verification_urls(
    *,
    samples: list[Mapping[str, Any]],
    file_inventory: list[Mapping[str, Any]],
) -> dict[str, Any]:
    sample_urls = _dedupe_strings(sample.get("source_url") for sample in samples)
    detail_urls = _dedupe_strings(
        row.get("source_url")
        for row in file_inventory
        if str(row.get("file_role") or "") == "detail"
    )
    attachment_urls = _dedupe_strings(
        row.get("source_url")
        for row in file_inventory
        if str(row.get("file_role") or "") == "attachment"
    )
    all_urls = _dedupe_strings([*sample_urls, *detail_urls, *attachment_urls])
    return {
        "manual_verification_required": True,
        "project_source_urls": sample_urls,
        "detail_snapshot_urls": detail_urls,
        "attachment_snapshot_urls": attachment_urls,
        "all_urls": all_urls,
        "url_count": len(all_urls),
        "verification_workflow": [
            "open_project_source_url",
            "compare_project_name_and_project_id",
            "open_detail_snapshot_url",
            "verify_attachment_links_match_file_inventory",
            "compare_downloaded_files_with_source_page",
            "confirm_parse_summary_matches_downloaded_files",
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _failure_reasons(
    samples: list[Mapping[str, Any]],
    detail_files: list[Mapping[str, Any]],
    attachment_files: list[Mapping[str, Any]],
    stage_pollution_reasons: list[str],
    parse_metrics: Mapping[str, Any],
    project_contract: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not detail_files:
        reasons.append("detail_snapshot_missing")
    if any(str(sample.get("document_kind") or "") == "tender_file" for sample in samples):
        if not attachment_files:
            reasons.append("tender_file_attachment_missing")
        if attachment_files and not any(item.get("valid_tender_attachment") for item in attachment_files):
            reasons.append("valid_tender_attachment_missing")
    if any(item.get("html_pollution") for item in attachment_files):
        reasons.append("html_pollution_attachment_present")
    reasons.extend(stage_pollution_reasons)
    reasons.extend(_as_list(project_contract.get("download_blocking_reasons")))
    reasons.extend(_as_list(project_contract.get("parse_blocking_reasons")))
    reasons.extend(_as_list(parse_metrics.get("parse_insufficiency_reasons")))
    for sample in samples:
        reasons.extend(_as_list(sample.get("failure_taxonomy")))
    return _dedupe_strings(reasons)


def _completion_rate(
    *,
    detail_files: list[Mapping[str, Any]],
    attachment_files: list[Mapping[str, Any]],
) -> float:
    expected = len(detail_files) + len(attachment_files)
    if expected <= 0:
        return 0.0
    replayable = sum(1 for item in detail_files + attachment_files if item.get("replayable"))
    return round(replayable / expected, 4)


def _group_project_items(items: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        project_id = str(item.get("project_id") or item.get("target_id") or "")
        if not project_id:
            project_id = f"PROJECT-{_fingerprint(item)[:12]}"
        groups.setdefault(project_id, []).append(item)
    return groups


def _load_json_file(path: Path, label: str, blocking_reasons: list[str]) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(f"{label}_missing")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        blocking_reasons.append(f"{label}_load_failed:{exc}")
        return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    blocking_reasons.append(f"{label}_not_object")
    return {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _declared_ref_url(ref: Mapping[str, Any]) -> str:
    return str(
        ref.get("source_url")
        or ref.get("attachment_url")
        or ref.get("download_url")
        or ref.get("href")
        or ""
    )


def _ref_source_url(ref: Mapping[str, Any], readback: Mapping[str, Any]) -> str:
    manifest = readback.get("manifest") if isinstance(readback.get("manifest"), Mapping) else {}
    return str(_declared_ref_url(ref) or manifest.get("source_url_optional") or "")


def _extension_for_ref(ref: Mapping[str, Any], content_type: str) -> str:
    source_url = _declared_ref_url(ref)
    suffix = Path(source_url.split("?", 1)[0]).suffix.lower()
    if suffix in VALID_ATTACHMENT_EXTENSIONS or suffix in {".html", ".htm"}:
        return suffix
    normalized = content_type.lower()
    if "pdf" in normalized:
        return ".pdf"
    if "word" in normalized:
        return ".docx"
    if "spreadsheet" in normalized or "excel" in normalized:
        return ".xlsx"
    if "zip" in normalized:
        return ".zip"
    if "html" in normalized:
        return ".html"
    return ".bin"


def _is_valid_tender_attachment(ref: Mapping[str, Any], content_type: str, extension: str) -> bool:
    role = str(ref.get("attachment_role_type") or "").lower()
    role_text = " ".join(
        str(value or "")
        for value in (
            ref.get("attachment_link_text"),
            ref.get("attachment_name"),
            _declared_ref_url(ref),
            ref.get("parse_state"),
            ref.get("parent_document_kind"),
        )
    ).lower()
    content = content_type.lower()
    type_ok = extension.lower() in VALID_ATTACHMENT_EXTENSIONS or any(
        marker in content for marker in VALID_ATTACHMENT_CONTENT_MARKERS
    )
    if not type_ok or _is_html_pollution(content_type, extension):
        return False
    tender_tokens = ("tender", "招标", "采购", "答疑", "澄清", "补遗", "清单")
    if any(token in role or token in role_text for token in tender_tokens):
        return True
    parent_document_kind = str(ref.get("parent_document_kind") or "")
    parse_state = str(ref.get("parse_state") or "")
    if (
        parent_document_kind == "tender_file"
        and extension.lower() in VALID_ATTACHMENT_EXTENSIONS
        and parse_state in {"PDF_TEXT_EXTRACTED", "MARKITDOWN_TEXT_EXTRACTED"}
    ):
        return True
    return False


def _is_html_pollution(content_type: str, extension: str) -> bool:
    return "html" in content_type.lower() or extension.lower() in {".html", ".htm"}


def _safe_path_part(value: str) -> str:
    text = str(value or "").strip() or "UNKNOWN"
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text.strip("._") or "UNKNOWN"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item not in (None, "")]
    return [value]


def _dedupe_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _string_value(value: Any) -> str:
    return str(value or "").strip()


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build professional clean project archive")
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_professional_clean_project_archive_manifest(
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
        output_root=args.output_root,
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result["summary"]
        print(
            "professional clean project archive: "
            f"project_count={summary.get('project_count')} "
            f"valid_tender_attachment_count={summary.get('valid_tender_attachment_count')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
