from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
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
    "qualification_section_found": ("资格条件", "资格要求", "投标人资格", "供应商资格", "投标人资格要求"),
    "scoring_section_found": ("评分办法", "评标办法", "评分标准", "综合评分", "综合评估法"),
    "technical_section_found": (
        "技术参数",
        "技术要求",
        "采购需求",
        "服务要求",
        "技术标准和要求",
        "设计任务书",
        "发包人要求",
        "设计要求",
    ),
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
POST_CANDIDATE_ENTRY_DOCUMENT_KINDS = {"candidate_notice"}
CORE_BACKTRACE_DOCUMENT_KINDS = ("tender_file", "candidate_notice", "award_result")
RECENT_CANDIDATE_LATE_STAGE_FLOW_NOS = ("11", "12")
GUANGZHOU_FLOW_MODULES = (
    {"flow_no": "01", "flow_code": "08", "flow_title": "招标计划", "document_kind": "bid_plan"},
    {"flow_no": "02", "flow_code": "17", "flow_title": "招标文件公示", "document_kind": "tender_file_publicity"},
    {"flow_no": "03", "flow_code": "01", "flow_title": "招标公告/关联公告", "document_kind": "tender_file"},
    {"flow_no": "04", "flow_code": "18", "flow_title": "澄清答疑", "document_kind": "clarification_notice"},
    {"flow_no": "05", "flow_code": "19", "flow_title": "开标信息", "document_kind": "opening_info"},
    {"flow_no": "06", "flow_code": "02", "flow_title": "资审结果公示", "document_kind": "qualification_review_result"},
    {"flow_no": "07", "flow_code": "03", "flow_title": "中标候选人公示", "document_kind": "candidate_notice"},
    {"flow_no": "08", "flow_code": "04", "flow_title": "投标(资格预审申请)文件公开", "document_kind": "bid_file_publicity"},
    {"flow_no": "09", "flow_code": "06", "flow_title": "中标结果公示/公告", "document_kind": "award_result"},
    {"flow_no": "10", "flow_code": "05", "flow_title": "中标信息", "document_kind": "award_info"},
    {"flow_no": "11", "flow_code": "07", "flow_title": "合同信息公开", "document_kind": "contract_public_info"},
    {"flow_no": "12", "flow_code": "20", "flow_title": "项目异常", "document_kind": "project_exception"},
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
    guangzhou_flow_inventory = _materialize_guangzhou_flow_view(
        project_dir=project_dir,
        samples=samples,
        detail_files=detail_files,
        attachment_files=attachment_files,
    )
    source_text = "\n".join(
        str(value)
        for sample in samples
        for value in _sample_text_values(sample)
        if value
    )
    stage_pollution_reasons = _stage_pollution_reasons(samples, source_text)
    section_flags = _section_flags(source_text)
    parse_metrics = _parse_metrics(samples=samples, section_flags=section_flags)
    post_candidate_entry_state = _post_candidate_entry_state(samples)
    backtrace_stage_attempts = _backtrace_stage_attempts(samples)
    missing_stage_kinds = _missing_stage_kinds(samples)
    backtrace_completeness_state = _backtrace_completeness_state(missing_stage_kinds)
    late_stage_missing_non_blocking = _recent_candidate_late_stage_missing_non_blocking(samples)
    project_contract = _project_completeness_contract(
        samples=samples,
        detail_files=detail_files,
        attachment_files=attachment_files,
        parse_metrics=parse_metrics,
        stage_pollution_reasons=stage_pollution_reasons,
        post_candidate_entry_state=post_candidate_entry_state,
        backtrace_completeness_state=backtrace_completeness_state,
        late_stage_missing_non_blocking=late_stage_missing_non_blocking,
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
        "post_candidate_entry_state": post_candidate_entry_state,
        "post_candidate_entry_document_kinds": sorted(POST_CANDIDATE_ENTRY_DOCUMENT_KINDS),
        "late_stage_flows_required_for_recent_candidate": False,
        "recent_candidate_late_stage_missing_non_blocking": late_stage_missing_non_blocking,
        "backtrace_stage_attempts": backtrace_stage_attempts,
        "matched_project_keys": _dedupe_strings(
            key
            for sample in samples
            for key in _as_list(sample.get("matched_project_keys"))
        ),
        "base_project_names": _dedupe_strings(sample.get("base_project_name") for sample in samples),
        "backtrace_query_variants": _dedupe_strings(
            value
            for sample in samples
            for value in _as_list(sample.get("backtrace_query_variants"))
        ),
        "backtrace_match_reasons": _dedupe_strings(sample.get("backtrace_match_reason") for sample in samples),
        "guangzhou_flow_modules_present": _guangzhou_flow_modules_present(samples),
        "guangzhou_flow_modules_missing": _guangzhou_flow_modules_missing(samples),
        "guangzhou_flow_completeness_state": _guangzhou_flow_completeness_state(samples),
        "guangzhou_flow_inventory": guangzhou_flow_inventory,
        "missing_stage_kinds": missing_stage_kinds,
        "backtrace_completeness_state": backtrace_completeness_state,
        "download_completeness_state": str(project_contract.get("download_completeness_state") or ""),
        "parse_completeness_state": str(project_contract.get("parse_completeness_state") or ""),
        "ready_for_tailored_analysis": str(project_contract.get("overall_project_readiness_state") or "")
        == "PROJECT_READY_FOR_SIGNAL_ANALYSIS",
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
        "guangzhou_flow_modules_present": audit["guangzhou_flow_modules_present"],
        "guangzhou_flow_modules_missing": audit["guangzhou_flow_modules_missing"],
        "guangzhou_flow_inventory": guangzhou_flow_inventory,
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
                "post_candidate_entry_state": post_candidate_entry_state,
                "post_candidate_entry_document_kinds": sorted(POST_CANDIDATE_ENTRY_DOCUMENT_KINDS),
                "late_stage_flows_required_for_recent_candidate": False,
                "recent_candidate_late_stage_missing_non_blocking": late_stage_missing_non_blocking,
                "backtrace_stage_attempts": backtrace_stage_attempts,
                "missing_stage_kinds": missing_stage_kinds,
                "backtrace_completeness_state": backtrace_completeness_state,
                "guangzhou_flow_modules_present": audit["guangzhou_flow_modules_present"],
                "guangzhou_flow_modules_missing": audit["guangzhou_flow_modules_missing"],
                "guangzhou_flow_completeness_state": audit["guangzhou_flow_completeness_state"],
                "guangzhou_flow_inventory": guangzhou_flow_inventory,
                "file_parse_attributions": _project_file_parse_attributions(samples),
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
            ref_payload.setdefault("parent_published_at", sample.get("published_at_optional"))
            ref_payload.setdefault("source_trading_process", sample.get("source_trading_process"))
            ref_payload.setdefault("source_dataset_name", sample.get("source_dataset_name"))
            ref_payload.setdefault("guangzhou_flow_no", sample.get("guangzhou_flow_no"))
            ref_payload.setdefault("guangzhou_flow_title", sample.get("guangzhou_flow_title"))
            ref_payload.setdefault("guangzhou_flow_code", sample.get("guangzhou_flow_code"))
            ref_payload.setdefault("guangzhou_flow_folder", sample.get("guangzhou_flow_folder"))
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
            "parent_published_at": str(ref.get("parent_published_at") or ""),
            "source_trading_process": str(ref.get("source_trading_process") or ""),
            "source_dataset_name": str(ref.get("source_dataset_name") or ""),
            "guangzhou_flow_no": str(ref.get("guangzhou_flow_no") or ""),
            "guangzhou_flow_title": str(ref.get("guangzhou_flow_title") or ""),
            "guangzhou_flow_code": str(ref.get("guangzhou_flow_code") or ""),
            "guangzhou_flow_folder": str(ref.get("guangzhou_flow_folder") or ""),
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


def _materialize_guangzhou_flow_view(
    *,
    project_dir: Path,
    samples: list[Mapping[str, Any]],
    detail_files: list[Mapping[str, Any]],
    attachment_files: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    legacy_flow_root = project_dir / "flow"
    inventory: list[dict[str, Any]] = []
    materialized_url_keys: set[tuple[str, str]] = set()
    for sample in samples:
        flow_no = _sample_flow_no(sample)
        flow_title = _sample_flow_title(sample)
        source_url = str(sample.get("source_url") or "").strip()
        if not flow_no or not flow_title or not source_url:
            continue
        key = (flow_no, source_url)
        if key in materialized_url_keys:
            continue
        materialized_url_keys.add(key)
        publish_date = _publish_date_for_sample(sample)
        destination_dir = _flow_notice_directory(
            project_dir=project_dir,
            flow_no=flow_no,
            flow_title=flow_title,
            publish_date=publish_date,
            title=str(sample.get("project_name") or sample.get("document_kind") or "流程页面"),
        )
        for child in ("detail", "attachments", "extracted", "parsed"):
            (destination_dir / child).mkdir(parents=True, exist_ok=True)
        meta = {
            "flow_no": flow_no,
            "flow_title": flow_title,
            "flow_code": str(sample.get("guangzhou_flow_code") or sample.get("source_trading_process") or ""),
            "published_date": publish_date,
            "file_id": f"FLOW-URL-{flow_no}-{_fingerprint(source_url)[:10]}",
            "file_role": "detail_url",
            "snapshot_id": "",
            "source_url": source_url,
            "parent_source_url": "",
            "copied_file_path": "",
            "primary_flow_directory": str(destination_dir),
            "replayable": False,
            "target_execution_state": str(sample.get("target_execution_state") or ""),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        (destination_dir / "detail" / f"{_safe_path_part(str(meta['file_id']))}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        inventory.append(meta)
    for item in [*detail_files, *attachment_files]:
        flow_no = str(item.get("guangzhou_flow_no") or "").strip()
        flow_title = str(item.get("guangzhou_flow_title") or "").strip()
        if not flow_no:
            flow_no = _flow_no_for_document_kind(str(item.get("parent_document_kind") or ""))
        if not flow_title:
            flow_title = _flow_title_for_no(flow_no)
        if not flow_no or not flow_title:
            continue
        publish_date = _publish_date_for_item(item)
        destination_dir = _flow_notice_directory(
            project_dir=project_dir,
            flow_no=flow_no,
            flow_title=flow_title,
            publish_date=publish_date,
            title=str(item.get("parent_document_kind") or item.get("file_id") or "流程文件"),
        )
        for child in ("detail", "attachments", "extracted", "parsed"):
            (destination_dir / child).mkdir(parents=True, exist_ok=True)
        role_dir = "detail" if str(item.get("file_role") or "") == "detail" else "attachments"
        file_destination_dir = destination_dir / role_dir
        destination_dir.mkdir(parents=True, exist_ok=True)
        source_path = Path(str(item.get("file_path") or ""))
        copied_path = ""
        if source_path.exists() and bool(item.get("replayable")):
            copied = file_destination_dir / source_path.name
            if source_path.resolve() != copied.resolve():
                shutil.copy2(source_path, copied)
            copied_path = str(copied)
        meta = {
            "flow_no": flow_no,
            "flow_title": flow_title,
            "flow_code": str(item.get("guangzhou_flow_code") or item.get("source_trading_process") or ""),
            "published_date": publish_date,
            "file_id": str(item.get("file_id") or ""),
            "file_role": str(item.get("file_role") or ""),
            "snapshot_id": str(item.get("snapshot_id") or ""),
            "source_url": str(item.get("source_url") or ""),
            "parent_source_url": str(item.get("parent_source_url") or ""),
            "copied_file_path": copied_path,
            "primary_flow_directory": str(destination_dir),
            "replayable": bool(item.get("replayable")),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        (file_destination_dir / f"{_safe_path_part(str(item.get('file_id') or 'file'))}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        inventory.append(meta)
    if inventory:
        legacy_flow_root.mkdir(parents=True, exist_ok=True)
        (legacy_flow_root / "flow-index.json").write_text(
            json.dumps({"items": inventory}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (project_dir / "flow-index.json").write_text(
            json.dumps({"items": inventory}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return inventory


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
        "post_candidate_entry_state_counts": _counts(item.get("post_candidate_entry_state") for item in items),
        "backtrace_completeness_state_counts": _counts(item.get("backtrace_completeness_state") for item in items),
        "guangzhou_flow_completeness_state_counts": _counts(
            item.get("guangzhou_flow_completeness_state") for item in items
        ),
        "guangzhou_flow_no_counts": _counts(
            module.get("flow_no")
            for item in items
            for module in _as_list(item.get("guangzhou_flow_modules_present"))
            if isinstance(module, Mapping)
        ),
        "ready_for_tailored_analysis_count": sum(1 for item in items if bool(item.get("ready_for_tailored_analysis"))),
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
        "source_project_code": str(sample.get("source_project_code") or ""),
        "project_match_key": str(sample.get("project_match_key") or ""),
        "published_at_optional": str(sample.get("published_at_optional") or ""),
        "guangzhou_flow_no": _sample_flow_no(sample),
        "guangzhou_flow_title": _sample_flow_title(sample),
        "guangzhou_flow_code": str(sample.get("guangzhou_flow_code") or sample.get("source_trading_process") or ""),
        "guangzhou_flow_folder": str(sample.get("guangzhou_flow_folder") or ""),
        "matched_project_keys": _as_list(sample.get("matched_project_keys")),
        "base_project_name": str(sample.get("base_project_name") or ""),
        "backtrace_query_variants": _as_list(sample.get("backtrace_query_variants")),
        "backtrace_match_reason": str(sample.get("backtrace_match_reason") or ""),
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
            "file_parse_attribution_count": len(list(parse_summary.get("file_parse_attributions") or [])),
        },
        "failure_taxonomy": _as_list(sample.get("failure_taxonomy")),
    }


def _post_candidate_entry_state(samples: list[Mapping[str, Any]]) -> str:
    document_kinds = {str(sample.get("document_kind") or "") for sample in samples}
    if document_kinds & POST_CANDIDATE_ENTRY_DOCUMENT_KINDS:
        return "POST_CANDIDATE_ENTRY_PRESENT"
    return "POST_CANDIDATE_ENTRY_MISSING"


def _backtrace_stage_attempts(samples: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        for existing in list(sample.get("backtrace_stage_attempts") or []):
            if not isinstance(existing, Mapping):
                continue
            key = "|".join(
                str(existing.get(part) or "")
                for part in ("target_id", "document_kind", "source_url", "target_execution_state")
            )
            if key in seen:
                continue
            seen.add(key)
            attempts.append(
                {
                    "document_kind": str(existing.get("document_kind") or ""),
                    "target_id": str(existing.get("target_id") or ""),
                    "source_url": str(existing.get("source_url") or ""),
                    "target_execution_state": str(existing.get("target_execution_state") or ""),
                    "detail_snapshot_count": _int_value(existing.get("detail_snapshot_count"), default=0),
                    "attachment_snapshot_count": _int_value(existing.get("attachment_snapshot_count"), default=0),
                    "failure_taxonomy": _as_list(existing.get("failure_taxonomy")),
                    "base_project_name": str(existing.get("base_project_name") or ""),
                    "backtrace_query_variants": _as_list(existing.get("backtrace_query_variants")),
                    "backtrace_match_reason": str(existing.get("backtrace_match_reason") or ""),
                    "guangzhou_flow_no": str(existing.get("guangzhou_flow_no") or ""),
                    "guangzhou_flow_title": str(existing.get("guangzhou_flow_title") or ""),
                    "guangzhou_flow_code": str(existing.get("guangzhou_flow_code") or ""),
                    "guangzhou_flow_folder": str(existing.get("guangzhou_flow_folder") or ""),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
        document_kind = str(sample.get("document_kind") or "")
        source_url = str(sample.get("source_url") or "")
        target_id = str(sample.get("parent_target_id") or sample.get("target_id") or "")
        state = str(sample.get("target_execution_state") or "")
        key = "|".join((target_id, document_kind, source_url, state))
        if key in seen:
            continue
        seen.add(key)
        attempts.append(
            {
                "document_kind": document_kind,
                "target_id": target_id,
                "source_url": source_url,
                "target_execution_state": state,
                "detail_snapshot_count": _int_value(sample.get("detail_snapshot_count"), default=0),
                "attachment_snapshot_count": _int_value(sample.get("attachment_snapshot_count"), default=0),
                "failure_taxonomy": _as_list(sample.get("failure_taxonomy")),
                "base_project_name": str(sample.get("base_project_name") or ""),
                "backtrace_query_variants": _as_list(sample.get("backtrace_query_variants")),
                "backtrace_match_reason": str(sample.get("backtrace_match_reason") or ""),
                "guangzhou_flow_no": _sample_flow_no(sample),
                "guangzhou_flow_title": _sample_flow_title(sample),
                "guangzhou_flow_code": str(sample.get("guangzhou_flow_code") or sample.get("source_trading_process") or ""),
                "guangzhou_flow_folder": str(sample.get("guangzhou_flow_folder") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return attempts


def _missing_stage_kinds(samples: list[Mapping[str, Any]]) -> list[str]:
    present = {str(sample.get("document_kind") or "") for sample in samples}
    return [kind for kind in CORE_BACKTRACE_DOCUMENT_KINDS if kind not in present]


def _guangzhou_flow_modules_present(samples: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    present: dict[str, dict[str, str]] = {}
    for sample in samples:
        flow_no = _sample_flow_no(sample)
        if not flow_no:
            continue
        flow_title = _sample_flow_title(sample)
        flow_code = str(sample.get("guangzhou_flow_code") or sample.get("source_trading_process") or "")
        present.setdefault(
            flow_no,
            {
                "flow_no": flow_no,
                "flow_code": flow_code,
                "flow_title": flow_title,
                "document_kind": str(sample.get("document_kind") or ""),
            },
        )
    return [present[key] for key in sorted(present)]


def _guangzhou_flow_modules_missing(samples: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    present = {_sample_flow_no(sample) for sample in samples}
    present.discard("")
    return [dict(module) for module in GUANGZHOU_FLOW_MODULES if str(module["flow_no"]) not in present]


def _recent_candidate_late_stage_missing_non_blocking(samples: list[Mapping[str, Any]]) -> list[str]:
    if _post_candidate_entry_state(samples) != "POST_CANDIDATE_ENTRY_PRESENT":
        return []
    present = {_sample_flow_no(sample) for sample in samples}
    return [flow_no for flow_no in RECENT_CANDIDATE_LATE_STAGE_FLOW_NOS if flow_no not in present]


def _guangzhou_flow_completeness_state(samples: list[Mapping[str, Any]]) -> str:
    return "GUANGZHOU_FLOW_COMPLETE" if not _guangzhou_flow_modules_missing(samples) else "GUANGZHOU_FLOW_PARTIAL"


def _sample_flow_no(sample: Mapping[str, Any]) -> str:
    explicit = str(sample.get("guangzhou_flow_no") or "").strip()
    if explicit:
        return explicit
    flow_code = str(sample.get("guangzhou_flow_code") or sample.get("source_trading_process") or "").strip()
    for module in GUANGZHOU_FLOW_MODULES:
        if str(module["flow_code"]) == flow_code:
            return str(module["flow_no"])
    return _flow_no_for_document_kind(str(sample.get("document_kind") or ""))


def _sample_flow_title(sample: Mapping[str, Any]) -> str:
    explicit = str(sample.get("guangzhou_flow_title") or "").strip()
    if explicit:
        return explicit
    return _flow_title_for_no(_sample_flow_no(sample))


def _flow_no_for_document_kind(document_kind: str) -> str:
    for module in GUANGZHOU_FLOW_MODULES:
        if str(module["document_kind"]) == document_kind:
            return str(module["flow_no"])
    return ""


def _flow_title_for_no(flow_no: str) -> str:
    for module in GUANGZHOU_FLOW_MODULES:
        if str(module["flow_no"]) == flow_no:
            return str(module["flow_title"])
    return ""


def _publish_date_for_item(item: Mapping[str, Any]) -> str:
    for value in (item.get("parent_published_at"), item.get("source_url"), item.get("parent_source_url")):
        text = str(value or "")
        match = re.search(r"(20\d{2})[-/]?([01]\d)[-/]?([0-3]\d)", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def _publish_date_for_sample(sample: Mapping[str, Any]) -> str:
    for value in (sample.get("published_at_optional"), sample.get("source_url")):
        text = str(value or "")
        match = re.search(r"(20\d{2})[-/]?([01]\d)[-/]?([0-3]\d)", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def _flow_notice_directory(
    *,
    project_dir: Path,
    flow_no: str,
    flow_title: str,
    publish_date: str,
    title: str,
) -> Path:
    flow_dir = project_dir / _safe_path_part(f"{flow_no}_{flow_title}")
    title_part = _safe_path_part(str(title or "流程页面"))[:80]
    date_part = _safe_path_part(publish_date or "unknown-date")
    return flow_dir / _safe_path_part(f"{date_part}_{title_part}")


def _backtrace_completeness_state(missing_stage_kinds: list[str]) -> str:
    if not missing_stage_kinds:
        return "BACKTRACE_CORE_COMPLETE"
    if len(missing_stage_kinds) < len(CORE_BACKTRACE_DOCUMENT_KINDS):
        return "BACKTRACE_PARTIAL"
    return "BACKTRACE_MISSING"


def _stage_pollution_reasons(samples: list[Mapping[str, Any]], source_text: str) -> list[str]:
    reasons: list[str] = []
    if any(str(sample.get("document_kind") or "") == "tender_file" for sample in samples):
        tender_source_text = "\n".join(
            str(value)
            for sample in samples
            if str(sample.get("document_kind") or "") == "tender_file"
            for value in _sample_text_values(sample)
            if value
        ) or source_text
        for marker in PROJECT_STAGE_POLLUTION_MARKERS:
            if marker in tender_source_text:
                reasons.append(f"tender_file_stage_text_contains:{marker}")
    return _dedupe_strings(reasons)


def _section_flags(source_text: str) -> dict[str, bool]:
    flags = {
        field_name: any(marker in source_text for marker in markers)
        for field_name, markers in SECTION_MARKERS.items()
    }
    found = [field_name for field_name, present in flags.items() if present]
    if len(found) == len(SECTION_MARKERS):
        state = "SECTION_COMPLETE"
    elif found == ["qualification_section_found"]:
        state = "SECTION_PARTIAL_QUALIFICATION_ONLY"
    elif found:
        state = "SECTION_PARTIAL"
    else:
        state = "SECTION_NOT_FOUND"
    return {
        **flags,
        "section_analysis_state": state,
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
    section_analysis_state = str(section_flags.get("section_analysis_state") or "")
    if section_analysis_state == "SECTION_PARTIAL_QUALIFICATION_ONLY":
        parse_insufficiency_reasons.append("section_partial_qualification_only")
    if _tender_notice_pdf_lacks_full_tender_sections(samples=samples, section_flags=section_flags):
        parse_insufficiency_reasons.append("tender_notice_pdf_lacks_full_tender_sections")
    file_parse_attributions = _project_file_parse_attributions(samples)

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
        "section_analysis_state": section_analysis_state,
        "markitdown_state_counts": markitdown_state_counts,
        "parse_insufficiency_reasons": _dedupe_strings(parse_insufficiency_reasons),
        "file_level_parse_attribution_state": "FILE_LEVEL_PARSE_ATTRIBUTION_READY"
        if file_parse_attributions
        else "PROJECT_LEVEL_ONLY_MISSING_FILE_LEVEL_ATTRIBUTION"
        if parse_summaries
        else "PARSE_SUMMARY_MISSING",
        "file_parse_attribution_count": len(file_parse_attributions),
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
    post_candidate_entry_state: str,
    backtrace_completeness_state: str,
    late_stage_missing_non_blocking: list[str],
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
        "post_candidate_entry_state": post_candidate_entry_state,
        "backtrace_completeness_state": backtrace_completeness_state,
        "late_stage_flows_required_for_recent_candidate": False,
        "recent_candidate_late_stage_missing_non_blocking": late_stage_missing_non_blocking,
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
                "parent_document_kind": str(item.get("parent_document_kind") or ""),
                "parent_published_at": str(item.get("parent_published_at") or ""),
                "guangzhou_flow_no": str(item.get("guangzhou_flow_no") or ""),
                "guangzhou_flow_title": str(item.get("guangzhou_flow_title") or ""),
                "guangzhou_flow_code": str(item.get("guangzhou_flow_code") or ""),
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
        parse_summary = sample.get("parse_summary")
        if isinstance(parse_summary, Mapping):
            reasons.extend(_as_list(parse_summary.get("document_quality_reasons")))
            reasons.extend(_as_list(parse_summary.get("download_archive_quality_reasons")))
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


def _sample_text_values(sample: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = [
        sample.get("project_name"),
        sample.get("source_text"),
    ]
    parse_summary = sample.get("parse_summary")
    if isinstance(parse_summary, Mapping):
        values.append(parse_summary.get("text_probe"))
        values.append(parse_summary.get("detail_text_probe"))
        values.extend(_text_probe_values(parse_summary.get("attachment_text_probes")))
        values.extend(_text_probe_values(parse_summary.get("file_parse_attributions")))
        for key in (
            "markitdown_text_probe",
            "attachment_text_probe",
            "document_text_probe",
        ):
            values.append(parse_summary.get(key))
    detail_fields = sample.get("detail_fields")
    if isinstance(detail_fields, Mapping):
        values.extend(_as_list(detail_fields.get("qualification_text_candidate_blocks")))
        values.extend(_as_list(detail_fields.get("document_section_slices")))
    values.extend(_as_list(sample.get("qualification_text_candidate_blocks")))
    return values


def _text_probe_values(value: Any) -> list[str]:
    probes: list[str] = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            text = str(item.get("text_probe") or "")
        else:
            text = str(item or "")
        if text.strip():
            probes.append(text)
    return probes


def _project_file_parse_attributions(samples: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    attributions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        parse_summary = sample.get("parse_summary")
        if not isinstance(parse_summary, Mapping):
            continue
        for item in list(parse_summary.get("file_parse_attributions") or []):
            if not isinstance(item, Mapping):
                continue
            key = "|".join(
                str(item.get(part) or "")
                for part in ("project_id", "snapshot_id", "file_role", "source_url")
            )
            if key in seen:
                continue
            seen.add(key)
            attributions.append(
                {
                    "project_id": str(item.get("project_id") or sample.get("project_id") or ""),
                    "snapshot_id": str(item.get("snapshot_id") or ""),
                    "source_url": str(item.get("source_url") or ""),
                    "file_role": str(item.get("file_role") or ""),
                    "parse_state": str(item.get("parse_state") or ""),
                    "section_flags": dict(item.get("section_flags") or {}),
                    "text_sha256": str(item.get("text_sha256") or ""),
                    "text_probe": str(item.get("text_probe") or ""),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return attributions


def _tender_notice_pdf_lacks_full_tender_sections(
    *,
    samples: list[Mapping[str, Any]],
    section_flags: Mapping[str, bool],
) -> bool:
    if bool(section_flags.get("scoring_section_found")):
        return False
    source_text = "\n".join(str(value) for sample in samples for value in _sample_text_values(sample) if value)
    if "招标公告" not in source_text:
        return False
    for sample in samples:
        for ref in list(sample.get("attachment_snapshot_refs") or []):
            if not isinstance(ref, Mapping):
                continue
            text = " ".join(
                str(ref.get(key) or "")
                for key in ("attachment_url", "source_url", "attachment_type", "content_type", "parse_state")
            ).lower()
            if ".pdf" in text or "pdf" in text:
                return True
    return False


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
    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff._-]+", "_", text)
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
