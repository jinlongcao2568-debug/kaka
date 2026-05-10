from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage3_parsing import markitdown_adapter
from stage3_parsing.real_parser import OCR_REQUIRED, Stage3RealParser
from stage3_parsing.tailored_bid_signals import build_tailored_bid_signal_profile
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


GUANGZHOU_PARSE_PROBE_MANIFEST_KIND = "guangzhou_parse_probe_manifest"
GUANGZHOU_PARSE_PROBE_VERSION = 1
GUANGZHOU_PARSE_PROBE_ADAPTER_ID = "guangzhou-parse-probe-v1-runner"
DEFAULT_PARSE_FLOW_NOS = ("03", "04")
DEFAULT_PROJECT_IDS = ("PROJ-CN-GD-JG2026-10815", "PROJ-CN-GD-JG2026-11021")
TEXT_PROBE_LIMIT = 4000
BID_FILE_PUBLICITY_FLOW_NO = "08"
POST_CANDIDATE_TEXT_PROBE_FLOW_NOS = {"07"}
SECTION_PARSE_FLOW_NOS = {"03", "04"}


def build_guangzhou_parse_probe(
    *,
    input_root: str | Path,
    output_root: str | Path,
    project_ids: list[str] | tuple[str, ...] = DEFAULT_PROJECT_IDS,
    flow_nos: list[str] | tuple[str, ...] = DEFAULT_PARSE_FLOW_NOS,
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    execute: bool = False,
    created_at: str | None = None,
    object_repository: ObjectStorageRepository | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(input_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    storage = Path(storage_path) if storage_path else in_root / "storage.json"
    object_storage = Path(object_storage_path) if object_storage_path else in_root / "objects"

    blocking_reasons: list[str] = []
    download_payload = _load_json(in_root / "download-probe-manifest.json", blocking_reasons, "download_probe_manifest_missing")
    analysis_payload = _load_json(in_root / "analysis-plan.json", [], "analysis_plan_missing")
    download_manifest = _source_manifest(download_payload)
    analysis_manifest = _source_manifest(analysis_payload)
    selected_samples = _select_project_samples(
        download_manifest=download_manifest,
        project_ids=project_ids,
        flow_nos=flow_nos,
    )
    if not selected_samples and not blocking_reasons:
        blocking_reasons.append("parse_probe_no_downloaded_samples_selected")

    repository = object_repository or _repository(storage_path=storage, object_storage_path=object_storage)
    should_close_repository = object_repository is None
    try:
        parser = Stage3RealParser(repository=repository)
        parse_items: list[dict[str, Any]] = []
        project_sample_items: list[dict[str, Any]] = []
        if execute and not blocking_reasons:
            for sample in selected_samples:
                sample_result = _parse_sample(
                    sample=sample,
                    input_root=in_root,
                    output_root=out_root,
                    repository=repository,
                    parser=parser,
                    analysis_manifest=analysis_manifest,
                    created_at=created,
                )
                parse_items.extend(sample_result["items"])
                project_sample_items.append(sample_result["project_sample"])
        else:
            for sample in selected_samples:
                planned = _planned_sample(sample=sample, input_root=in_root, output_root=out_root, created_at=created)
                parse_items.extend(planned["items"])
                project_sample_items.append(planned["project_sample"])
    finally:
        if should_close_repository:
            repository.session.close()

    summary = _summary(parse_items=parse_items, project_sample_items=project_sample_items, blocking_reasons=blocking_reasons)
    manifest = {
        "manifest_version": GUANGZHOU_PARSE_PROBE_VERSION,
        "manifest_kind": GUANGZHOU_PARSE_PROBE_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_PARSE_PROBE_ADAPTER_ID,
        "pipeline_stage": "ParseProbe",
        "manifest_id": f"GUANGZHOU-PARSE-PROBE-{_fingerprint({'items': parse_items, 'summary': summary})[:16]}",
        "created_at": created,
        "source_input_root": str(in_root),
        "source_download_probe_manifest_path": str(in_root / "download-probe-manifest.json"),
        "source_analysis_plan_path": str(in_root / "analysis-plan.json"),
        "storage_path_optional": str(storage),
        "object_storage_path_optional": str(object_storage),
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": bool(execute),
        "project_ids": list(project_ids),
        "flow_nos": [_flow_no(value) for value in flow_nos],
        "items": parse_items,
        "sample_items": parse_items[:80],
        "project_sample_items": project_sample_items,
        "project_sample_preview_items": project_sample_items[:80],
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage3_parse_enabled": bool(execute),
            "markitdown_enabled": bool(execute),
            "graphify_enabled": False,
            "mempalace_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_parse_probe_mode": "EXECUTED" if execute else "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": bool(execute),
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "parse_enabled": bool(execute),
            "markitdown_enabled": bool(execute),
            "graphify_enabled": False,
            "mempalace_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    output_path = out_root / "parse-probe-manifest.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _parse_sample(
    *,
    sample: Mapping[str, Any],
    input_root: Path,
    output_root: Path,
    repository: ObjectStorageRepository,
    parser: Stage3RealParser,
    analysis_manifest: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    flow_no = _sample_flow_no(sample)
    flow_dir = _flow_parse_directory(sample=sample, input_root=input_root, output_root=output_root)
    parsed_dir = flow_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    refs = [
        dict(ref)
        for ref in list(sample.get("attachment_snapshot_refs") or [])
        if isinstance(ref, Mapping)
    ]
    items: list[dict[str, Any]] = []
    if flow_no == BID_FILE_PUBLICITY_FLOW_NO:
        for ref in refs:
            items.append(_skipped_item(sample=sample, ref=ref, parse_state="SKIPPED_BID_FILE_PUBLICITY_DEEP_PARSE"))
    elif flow_no not in SECTION_PARSE_FLOW_NOS | POST_CANDIDATE_TEXT_PROBE_FLOW_NOS:
        for ref in refs:
            items.append(_skipped_item(sample=sample, ref=ref, parse_state="SKIPPED_FLOW_NOT_IN_PARSE_PROBE_SCOPE"))
    elif not refs:
        items.append(_no_attachment_item(sample=sample, flow_dir=flow_dir))
    else:
        for index, ref in enumerate(refs, start=1):
            item = _parse_ref(
                sample=sample,
                ref=ref,
                index=index,
                flow_dir=flow_dir,
                repository=repository,
                parser=parser,
                analysis_manifest=analysis_manifest,
                created_at=created_at,
            )
            items.append(item)
            (parsed_dir / f"{_safe_path_part(item['parse_probe_item_id'])}.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    project_sample = _project_sample(sample=sample, items=items, flow_dir=flow_dir)
    (parsed_dir / "parse-summary.json").write_text(
        json.dumps(
            {
                "project_id": project_sample["project_id"],
                "project_name": project_sample["project_name"],
                "flow_no": project_sample["guangzhou_flow_no"],
                "flow_title": project_sample["guangzhou_flow_title"],
                "source_url": project_sample["source_url"],
                "parse_probe_state": project_sample["parse_probe_state"],
                "parse_metrics": project_sample["parse_metrics"],
                "section_flags": project_sample["section_flags"],
                "file_parse_attributions": project_sample["parse_summary"]["file_parse_attributions"],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"items": items, "project_sample": project_sample}


def _parse_ref(
    *,
    sample: Mapping[str, Any],
    ref: Mapping[str, Any],
    index: int,
    flow_dir: Path,
    repository: ObjectStorageRepository,
    parser: Stage3RealParser,
    analysis_manifest: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    snapshot_id = str(ref.get("snapshot_id") or "")
    base = _base_item(sample=sample, ref=ref, index=index, flow_dir=flow_dir, created_at=created_at)
    readback = repository.replay_snapshot(snapshot_id)
    if not bool(readback.get("replayable")):
        state = str(readback.get("readback_state") or "READBACK_NOT_REPLAYABLE")
        return {
            **base,
            "parse_state": "SNAPSHOT_READBACK_FAILED",
            "stage3_parse_state": "NOT_RUN_READBACK_FAILED",
            "snapshot_readback_state": state,
            "snapshot_readback_failure": state,
            "markitdown_state": "MARKITDOWN_NOT_ATTEMPTED",
            "parse_error_taxonomy": [state],
            "section_flags": _section_flags(""),
            "document_section_profile": {},
            "document_section_slices": [],
            "tailored_signal_profile_summary": _empty_signal_summary(),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    data = readback.get("bytes") or b""
    archive_inventory = _archive_inventory(data, source_url=_ref_url(ref, readback), content_type=str(readback.get("content_type") or ""))
    if archive_inventory["archive_state"] != "NOT_ARCHIVE":
        return {
            **base,
            "parse_state": "ARCHIVE_INVENTORY_ONLY",
            "stage3_parse_state": "NOT_RUN_ARCHIVE_INVENTORY_ONLY",
            "snapshot_readback_state": str(readback.get("readback_state") or ""),
            "snapshot_readback_failure": "",
            "attachment_type": archive_inventory["archive_type"],
            "markitdown_state": "MARKITDOWN_NOT_ATTEMPTED",
            "archive_inventory": archive_inventory,
            "parse_error_taxonomy": ["archive_deep_parse_deferred"],
            "section_flags": _section_flags(""),
            "document_section_profile": {},
            "document_section_slices": [],
            "tailored_signal_profile_summary": _empty_signal_summary(),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    carrier = parser.parse_readback(readback)
    markitdown_result = _markitdown_result_from_stage3_audit(carrier)
    if markitdown_result is None:
        markitdown_result = markitdown_adapter.convert_bytes_to_markdown_text(
            bytes(data),
            source_url=_ref_url(ref, readback),
            content_type=str(readback.get("content_type") or ""),
            source_file_ref=str(readback.get("object_key") or snapshot_id),
        )
    text = _best_text(markitdown_result=markitdown_result, carrier=carrier)
    profile_inputs = _signal_profile_inputs(sample=sample, ref=ref)
    tailored_profile = build_tailored_bid_signal_profile(profile_inputs, text=text)
    section_flags = _section_flags(text)
    parse_error_taxonomy = _dedupe_strings(
        [
            *list(carrier.get("parse_error_taxonomy") or []),
            *list(markitdown_result.warnings or []),
        ]
    )
    if OCR_REQUIRED in parse_error_taxonomy:
        parse_state = "OCR_REQUIRED_REVIEW"
    elif markitdown_result.state == markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED or text:
        parse_state = "PARSED_TEXT_PROBE"
    elif str(carrier.get("parse_state") or "") in {"PARSED", "PARSED_WITH_REVIEW"}:
        parse_state = "PARSED_FIELD_ONLY"
    else:
        parse_state = "PARSE_REVIEW_REQUIRED"
    if _sample_flow_no(sample) in POST_CANDIDATE_TEXT_PROBE_FLOW_NOS:
        parse_depth_executed = "TEXT_PROBE"
    else:
        parse_depth_executed = "SECTION_PARSE"
    return {
        **base,
        "parse_state": parse_state,
        "parse_depth_executed": parse_depth_executed,
        "stage3_parse_state": str(carrier.get("parse_state") or ""),
        "stage3_attachment_type": str(carrier.get("attachment_type") or ""),
        "snapshot_readback_state": str(readback.get("readback_state") or ""),
        "snapshot_readback_failure": "",
        "content_type": str(readback.get("content_type") or ""),
        "byte_size": _int(readback.get("byte_size")),
        "sha256": str(readback.get("sha256") or ""),
        "markitdown_state": markitdown_result.state,
        "markitdown_text_sha256": markitdown_result.text_sha256,
        "markitdown_text_length": markitdown_result.text_length,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
        "text_length": len(text),
        "text_probe": _clip(text, TEXT_PROBE_LIMIT),
        "parsed_field_count": len(list(carrier.get("parsed_fields") or [])),
        "parsed_fields_probe": _parsed_fields_probe(carrier),
        "parse_error_taxonomy": parse_error_taxonomy,
        "section_flags": section_flags,
        "document_section_profile": dict(tailored_profile.get("document_section_profile") or {}),
        "document_section_slices": list(tailored_profile.get("document_section_slices") or [])[:12],
        "tailored_signal_profile_summary": _signal_summary(tailored_profile),
        "formal_index_weight_blocked_count": _int(tailored_profile.get("formal_index_weight_blocked_count")),
        "llm_execution_enabled": False,
        "graphify_enabled": False,
        "mempalace_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _planned_sample(
    *,
    sample: Mapping[str, Any],
    input_root: Path,
    output_root: Path,
    created_at: str,
) -> dict[str, Any]:
    flow_dir = _flow_parse_directory(sample=sample, input_root=input_root, output_root=output_root)
    refs = [
        dict(ref)
        for ref in list(sample.get("attachment_snapshot_refs") or [])
        if isinstance(ref, Mapping)
    ]
    items = [
        {
            **_base_item(sample=sample, ref=ref, index=index, flow_dir=flow_dir, created_at=created_at),
            "parse_state": "PARSE_PROBE_PLANNED_NOT_EXECUTED",
            "stage3_parse_state": "NOT_RUN_DRY_RUN",
            "markitdown_state": "MARKITDOWN_NOT_ATTEMPTED",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for index, ref in enumerate(refs, start=1)
    ]
    if not items:
        items = [_no_attachment_item(sample=sample, flow_dir=flow_dir)]
    return {"items": items, "project_sample": _project_sample(sample=sample, items=items, flow_dir=flow_dir)}


def _project_sample(*, sample: Mapping[str, Any], items: list[Mapping[str, Any]], flow_dir: Path) -> dict[str, Any]:
    success_count = sum(1 for item in items if str(item.get("parse_state") or "") in {"PARSED_TEXT_PROBE", "PARSED_FIELD_ONLY"})
    review_count = sum(1 for item in items if "REVIEW" in str(item.get("parse_state") or ""))
    skipped_count = sum(1 for item in items if str(item.get("parse_state") or "").startswith("SKIPPED"))
    section_flags = _aggregate_section_flags(items)
    state = "PARSE_PROBE_READY"
    if not items or all(str(item.get("parse_state") or "") == "NO_ATTACHMENT_TO_PARSE" for item in items):
        state = "NO_ATTACHMENT_TO_PARSE"
    elif success_count == 0 and review_count:
        state = "PARSE_PROBE_REVIEW_REQUIRED"
    elif skipped_count and success_count == 0:
        state = "PARSE_PROBE_SKIPPED"
    metrics = {
        "parse_attempted_file_count": sum(1 for item in items if _parse_attempted(item)),
        "stage3_parse_success_count": success_count,
        "stage3_parse_review_count": review_count,
        "stage3_parse_failed_count": sum(1 for item in items if str(item.get("parse_state") or "") == "SNAPSHOT_READBACK_FAILED"),
        "parse_skipped_file_count": skipped_count,
        "section_flags": section_flags,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return {
        "target_id": str(sample.get("target_id") or ""),
        "parent_target_id": str(sample.get("parent_target_id") or ""),
        "candidate_key": str(sample.get("candidate_key") or ""),
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "source_url": str(sample.get("source_url") or ""),
        "document_kind": str(sample.get("document_kind") or ""),
        "jurisdiction": str(sample.get("jurisdiction") or "CN-GD"),
        "source_profile_id": str(sample.get("source_profile_id") or ""),
        "pipeline_stage": "ParseProbe",
        "guangzhou_flow_no": _sample_flow_no(sample),
        "guangzhou_flow_title": _sample_flow_title(sample),
        "guangzhou_flow_folder": str(flow_dir),
        "parse_probe_state": state,
        "stage3_parse_state": state,
        "attachment_snapshot_count": len(list(sample.get("attachment_snapshot_refs") or [])),
        "parse_item_count": len(items),
        "parse_metrics": metrics,
        "section_flags": section_flags,
        "parse_summary": {
            "stage3_parse_success_count": success_count,
            "stage3_parse_failed_count": metrics["stage3_parse_failed_count"],
            "stage3_parse_review_count": review_count,
            "stage3_parse_state": state,
            "file_parse_attributions": [_file_attribution(item) for item in items],
            "document_section_slice_count": sum(len(list(item.get("document_section_slices") or [])) for item in items),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _base_item(
    *,
    sample: Mapping[str, Any],
    ref: Mapping[str, Any],
    index: int,
    flow_dir: Path,
    created_at: str,
) -> dict[str, Any]:
    snapshot_id = str(ref.get("snapshot_id") or "")
    flow_no = _sample_flow_no(sample)
    return {
        "parse_probe_item_id": f"PARSE-PROBE-{flow_no}-{index:03d}-{_fingerprint({'snapshot': snapshot_id, 'url': ref.get('source_url') or ref.get('attachment_url')})[:12]}",
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "flow_no": flow_no,
        "flow_title": _sample_flow_title(sample),
        "document_kind": str(sample.get("document_kind") or ""),
        "source_url": str(sample.get("source_url") or ""),
        "attachment_url": str(ref.get("attachment_url") or ref.get("source_url") or ""),
        "attachment_link_text": str(ref.get("attachment_link_text") or ""),
        "attachment_role_type": str(ref.get("attachment_role_type") or ""),
        "snapshot_id": snapshot_id,
        "flow_directory": str(flow_dir),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _skipped_item(*, sample: Mapping[str, Any], ref: Mapping[str, Any], parse_state: str) -> dict[str, Any]:
    return {
        **_base_item(sample=sample, ref=ref, index=1, flow_dir=Path(str(sample.get("guangzhou_flow_folder") or "")), created_at=""),
        "parse_state": parse_state,
        "stage3_parse_state": "NOT_RUN_POLICY_SKIPPED",
        "markitdown_state": "MARKITDOWN_NOT_ATTEMPTED",
        "skip_reason": parse_state.lower(),
        "section_flags": _section_flags(""),
        "document_section_profile": {},
        "document_section_slices": [],
        "tailored_signal_profile_summary": _empty_signal_summary(),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _no_attachment_item(*, sample: Mapping[str, Any], flow_dir: Path) -> dict[str, Any]:
    return {
        "parse_probe_item_id": f"PARSE-PROBE-NOATT-{_fingerprint({'project': sample.get('project_id'), 'url': sample.get('source_url')})[:12]}",
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "flow_no": _sample_flow_no(sample),
        "flow_title": _sample_flow_title(sample),
        "document_kind": str(sample.get("document_kind") or ""),
        "source_url": str(sample.get("source_url") or ""),
        "snapshot_id": "",
        "flow_directory": str(flow_dir),
        "parse_state": "NO_ATTACHMENT_TO_PARSE",
        "stage3_parse_state": "NOT_RUN_NO_ATTACHMENT",
        "markitdown_state": "MARKITDOWN_NOT_ATTEMPTED",
        "parse_error_taxonomy": ["no_attachment_snapshot_refs"],
        "section_flags": _section_flags(""),
        "document_section_profile": {},
        "document_section_slices": [],
        "tailored_signal_profile_summary": _empty_signal_summary(),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _select_project_samples(
    *,
    download_manifest: Mapping[str, Any],
    project_ids: list[str] | tuple[str, ...],
    flow_nos: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    requested_projects = {_normalize_project_token(value) for value in project_ids if _normalize_project_token(value)}
    requested_flows = {_flow_no(value) for value in flow_nos if _flow_no(value)}
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for sample in list(download_manifest.get("project_sample_items") or []):
        if not isinstance(sample, Mapping):
            continue
        project_id = str(sample.get("project_id") or "")
        flow_no = _sample_flow_no(sample)
        if requested_projects and not (_project_aliases(project_id) & requested_projects):
            continue
        if requested_flows and flow_no not in requested_flows:
            continue
        key = (project_id, flow_no, str(sample.get("source_url") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(sample))
    return out


def _repository(*, storage_path: Path, object_storage_path: Path) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage_path),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage_path),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def _best_text(*, markitdown_result: markitdown_adapter.MarkItDownText, carrier: Mapping[str, Any]) -> str:
    if markitdown_result.text:
        return markitdown_result.text
    audit = dict(carrier.get("parser_audit") or {})
    audit_probe = str(audit.get("markitdown_text_probe") or "")
    if audit_probe:
        return audit_probe
    parts = []
    for field in list(carrier.get("parsed_fields") or []):
        if isinstance(field, Mapping):
            parts.append(str(field.get("raw_text") or field.get("source_slice") or ""))
    return "\n".join(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _markitdown_result_from_stage3_audit(carrier: Mapping[str, Any]) -> markitdown_adapter.MarkItDownText | None:
    audit = dict(carrier.get("parser_audit") or {})
    state = str(audit.get("markitdown_state") or "")
    probe = str(audit.get("markitdown_text_probe") or "")
    if state != markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED or not probe:
        return None
    return markitdown_adapter.MarkItDownText(
        text=probe,
        state=state,
        text_sha256=str(audit.get("markitdown_text_sha256") or hashlib.sha256(probe.encode("utf-8")).hexdigest()),
        text_length=_int(audit.get("markitdown_text_length")) or len(probe),
        text_probe=probe,
    )


def _archive_inventory(data: bytes, *, source_url: str, content_type: str) -> dict[str, Any]:
    extension = Path(urlsplit(source_url).path).suffix.lower()
    normalized_content_type = str(content_type or "").lower()
    if zipfile.is_zipfile(BytesIO(data)):
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = archive.namelist()
        except Exception as exc:
            return {
                "archive_state": "ARCHIVE_INVENTORY_FAILED",
                "archive_type": "ZIP",
                "failure_reason": f"zip_inventory_failed:{type(exc).__name__}",
            }
        return {
            "archive_state": "ARCHIVE_INVENTORY_RECORDED",
            "archive_type": "ZIP",
            "member_count": len(names),
            "member_name_probes": names[:50],
            "deep_extract_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    if extension == ".rar" or "rar" in normalized_content_type:
        return {
            "archive_state": "ARCHIVE_INVENTORY_DEFERRED",
            "archive_type": "RAR",
            "deep_extract_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return {"archive_state": "NOT_ARCHIVE", "archive_type": ""}


def _signal_profile_inputs(*, sample: Mapping[str, Any], ref: Mapping[str, Any]) -> dict[str, Any]:
    flow_no = _sample_flow_no(sample)
    role = str(ref.get("attachment_role_type") or "")
    result = {
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "document_kind": str(sample.get("document_kind") or ""),
        "evaluation_document_kind": str(sample.get("document_kind") or ""),
        "attachment_role_type": role,
        "input_observable_from": ["tender_file", "attachment"] if flow_no in {"03", "04"} else ["post_award_notice"],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if flow_no == "04":
        result["notice_version_chain_state"] = "CLARIFICATION_OR_ADDENDUM_PRESENT"
    return result


def _signal_summary(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tailored_bid_index": _int(profile.get("tailored_bid_index")),
        "tailored_bid_risk_level": str(profile.get("tailored_bid_risk_level") or ""),
        "tailored_bid_signal_count": _int(profile.get("tailored_bid_signal_count")),
        "collusion_trace_index": _int(profile.get("collusion_trace_index")),
        "cover_bid_index": _int(profile.get("cover_bid_index")),
        "bid_rigging_index": _int(profile.get("bid_rigging_index")),
        "fatal_rejection_complexity_index": _int(profile.get("fatal_rejection_complexity_index")),
        "electronic_supervision_index": _int(profile.get("electronic_supervision_index")),
        "tailored_bid_stage5_review_required": bool(profile.get("tailored_bid_stage5_review_required")),
        "tailored_bid_ai_review_required": bool(profile.get("tailored_bid_ai_review_required")),
        "signal_families": dict(profile.get("tailored_bid_signal_families") or {}),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _empty_signal_summary() -> dict[str, Any]:
    return _signal_summary({})


def _section_flags(text: str) -> dict[str, Any]:
    normalized = str(text or "")
    flags = {
        "qualification_section_found": _contains_any(normalized, ("资格条件", "资格要求", "投标人资格", "供应商资格", "投标人资格要求")),
        "scoring_section_found": _contains_any(normalized, ("评分办法", "评标办法", "评分标准", "综合评分", "综合评估法")),
        "technical_section_found": _contains_any(normalized, ("技术参数", "技术要求", "采购需求", "服务要求", "技术标准和要求", "设计任务书", "发包人要求")),
        "fatal_rejection_section_found": _contains_any(normalized, ("废标", "无效投标", "否决投标", "符合性审查")),
        "contract_payment_section_found": _contains_any(normalized, ("合同条款", "付款方式", "结算", "验收")),
    }
    if flags["qualification_section_found"] and not any(flags[key] for key in ("scoring_section_found", "technical_section_found")):
        state = "SECTION_PARTIAL_QUALIFICATION_ONLY"
    elif any(flags.values()):
        state = "SECTION_PARTIAL" if not all(flags[key] for key in ("qualification_section_found", "scoring_section_found", "technical_section_found")) else "SECTION_CORE_READY"
    else:
        state = "SECTION_UNRESOLVED"
    return {**flags, "section_analysis_state": state}


def _aggregate_section_flags(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    merged = {
        "qualification_section_found": False,
        "scoring_section_found": False,
        "technical_section_found": False,
        "fatal_rejection_section_found": False,
        "contract_payment_section_found": False,
    }
    for item in items:
        flags = dict(item.get("section_flags") or {})
        for key in merged:
            merged[key] = merged[key] or bool(flags.get(key))
    if merged["qualification_section_found"] and merged["scoring_section_found"] and merged["technical_section_found"]:
        state = "SECTION_CORE_READY"
    elif any(merged.values()):
        state = "SECTION_PARTIAL"
    else:
        state = "SECTION_UNRESOLVED"
    if merged["qualification_section_found"] and not merged["scoring_section_found"] and not merged["technical_section_found"]:
        state = "SECTION_PARTIAL_QUALIFICATION_ONLY"
    return {**merged, "section_analysis_state": state}


def _file_attribution(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(item.get("project_id") or ""),
        "snapshot_id": str(item.get("snapshot_id") or ""),
        "source_url": str(item.get("attachment_url") or item.get("source_url") or ""),
        "flow_no": str(item.get("flow_no") or ""),
        "file_role": str(item.get("attachment_role_type") or ""),
        "parse_state": str(item.get("parse_state") or ""),
        "stage3_parse_state": str(item.get("stage3_parse_state") or ""),
        "section_flags": dict(item.get("section_flags") or {}),
        "text_sha256": str(item.get("text_sha256") or ""),
        "text_length": _int(item.get("text_length")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _parsed_fields_probe(carrier: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in list(carrier.get("parsed_fields") or [])[:20]:
        if not isinstance(field, Mapping):
            continue
        rows.append(
            {
                "field_name": str(field.get("field_name") or ""),
                "source_slice": _clip(str(field.get("source_slice") or ""), 260),
                "locator": dict(field.get("locator") or {}),
                "confidence": field.get("confidence"),
                "review_required": bool(field.get("review_required")),
            }
        )
    return rows


def _flow_parse_directory(*, sample: Mapping[str, Any], input_root: Path, output_root: Path) -> Path:
    folder = str(sample.get("guangzhou_flow_folder") or "")
    if folder:
        try:
            source_path = Path(folder)
            rel = source_path.relative_to(input_root)
            return output_root / rel
        except ValueError:
            pass
    date_part = _safe_path_part(str(sample.get("published_at_optional") or "")[:10] or "NO_DATE")
    title_part = _safe_path_part(str(sample.get("project_name") or "流程页面"))[:90]
    return (
        output_root
        / "projects"
        / _safe_path_part(str(sample.get("jurisdiction") or "CN-GD"))
        / _safe_path_part(str(sample.get("project_id") or "UNKNOWN_PROJECT"))
        / _safe_path_part(f"{_sample_flow_no(sample)}_{_sample_flow_title(sample)}")
        / _safe_path_part(f"{date_part}_{title_part}")
    )


def _sample_flow_no(sample: Mapping[str, Any]) -> str:
    return _flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no"))


def _sample_flow_title(sample: Mapping[str, Any]) -> str:
    return str(sample.get("guangzhou_flow_title") or sample.get("flow_title") or "")


def _ref_url(ref: Mapping[str, Any], readback: Mapping[str, Any]) -> str:
    manifest = readback.get("manifest") if isinstance(readback.get("manifest"), Mapping) else {}
    return str(ref.get("attachment_url") or ref.get("source_url") or manifest.get("source_url_optional") or "")


def _parse_attempted(item: Mapping[str, Any]) -> bool:
    state = str(item.get("parse_state") or "")
    return state not in {"NO_ATTACHMENT_TO_PARSE"} and not state.startswith("SKIPPED")


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _summary(
    *,
    parse_items: list[Mapping[str, Any]],
    project_sample_items: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    attempted = [item for item in parse_items if _parse_attempted(item)]
    return {
        "parse_probe_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "project_sample_count": len(project_sample_items),
        "parse_item_count": len(parse_items),
        "parse_attempted_file_count": len(attempted),
        "parse_success_count": sum(1 for item in parse_items if str(item.get("parse_state") or "") in {"PARSED_TEXT_PROBE", "PARSED_FIELD_ONLY"}),
        "parse_review_required_count": sum(1 for item in parse_items if "REVIEW" in str(item.get("parse_state") or "")),
        "parse_skipped_file_count": sum(1 for item in parse_items if str(item.get("parse_state") or "").startswith("SKIPPED")),
        "archive_inventory_count": sum(1 for item in parse_items if str(item.get("parse_state") or "") == "ARCHIVE_INVENTORY_ONLY"),
        "flow_no_counts": _counts(item.get("flow_no") for item in parse_items),
        "parse_state_counts": _counts(item.get("parse_state") for item in parse_items),
        "stage3_parse_state_counts": _counts(item.get("stage3_parse_state") for item in parse_items),
        "markitdown_state_counts": _counts(item.get("markitdown_state") for item in parse_items),
        "section_analysis_state_counts": _counts((item.get("section_flags") or {}).get("section_analysis_state") for item in parse_items),
        "tailored_signal_positive_count": sum(
            1 for item in parse_items if _int((item.get("tailored_signal_profile_summary") or {}).get("tailored_bid_signal_count")) > 0
        ),
        "tailored_index_positive_count": sum(
            1 for item in parse_items if _int((item.get("tailored_signal_profile_summary") or {}).get("tailored_bid_index")) > 0
        ),
        "snapshot_readback_failure_counts": _counts(
            item.get("snapshot_readback_failure") for item in parse_items if item.get("snapshot_readback_failure")
        ),
        "parse_failure_taxonomy_counts": _counts(
            reason
            for item in parse_items
            for reason in list(item.get("parse_error_taxonomy") or [])
        ),
        "blocking_reasons": blocking_reasons,
        "recommended_next_action": _recommended_next_action(parse_items, blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _recommended_next_action(items: list[Mapping[str, Any]], blocking_reasons: list[str]) -> str:
    if blocking_reasons:
        return "FIX_PARSE_PROBE_INPUTS"
    if not any(_parse_attempted(item) for item in items):
        return "NO_PARSEABLE_ATTACHMENT_SELECTED"
    if any(str(item.get("parse_state") or "") == "OCR_REQUIRED_REVIEW" for item in items):
        return "ADD_OCR_PROBE_FOR_SCANNED_FILES"
    if any(str(item.get("parse_state") or "") == "ARCHIVE_INVENTORY_ONLY" for item in items):
        return "ADD_CONTROLLED_ARCHIVE_EXTRACT_PROBE"
    return "REVIEW_PARSE_PROBE_SECTION_COVERAGE"


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _flow_no(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(2) if text else ""


def _project_aliases(project_id: str) -> set[str]:
    return {_normalize_project_token(project_id), _normalize_project_token(_extract_project_code(project_id))}


def _normalize_project_token(value: Any) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    code = _extract_project_code(text)
    return code or text


def _extract_project_code(value: Any) -> str:
    match = re.search(r"JG\d{4}-\d+", str(value or "").upper())
    return match.group(0) if match else ""


def _safe_path_part(value: Any) -> str:
    text = str(value or "").strip() or "UNKNOWN"
    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff._-]+", "_", text)
    return text.strip("._") or "UNKNOWN"


def _clip(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[TRUNCATED]"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


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


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou ParseProbe v1.")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--project-ids", default=",".join(DEFAULT_PROJECT_IDS))
    parser.add_argument("--flow-nos", default=",".join(DEFAULT_PARSE_FLOW_NOS))
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_parse_probe(
        input_root=args.input_root,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        flow_nos=_parse_csv(args.flow_nos),
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
        execute=args.execute,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "parse-probe-manifest.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"guangzhou parse probe {result['guangzhou_parse_probe_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GUANGZHOU_PARSE_PROBE_MANIFEST_KIND",
    "build_guangzhou_parse_probe",
]
