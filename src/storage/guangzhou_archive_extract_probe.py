from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


GUANGZHOU_ARCHIVE_EXTRACT_PROBE_MANIFEST_KIND = "guangzhou_archive_extract_probe_manifest"
GUANGZHOU_ARCHIVE_EXTRACT_PROBE_VERSION = 1
GUANGZHOU_ARCHIVE_EXTRACT_PROBE_ADAPTER_ID = "guangzhou-archive-extract-probe-v1-runner"

DEFAULT_PROJECT_IDS = ("PROJ-CN-GD-JG2026-10815", "PROJ-CN-GD-JG2026-11021")
DEFAULT_MAX_EXTRACT_FILES = 12
DEFAULT_MAX_SINGLE_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_TOTAL_EXTRACT_BYTES = 80 * 1024 * 1024
MAX_INVENTORY_MEMBERS = 200
ALLOWED_CHILD_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}


def build_guangzhou_archive_extract_probe(
    *,
    input_root: str | Path,
    strategy_root: str | Path,
    output_root: str | Path,
    project_ids: list[str] | tuple[str, ...] = DEFAULT_PROJECT_IDS,
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    max_extract_files: int = DEFAULT_MAX_EXTRACT_FILES,
    max_single_file_bytes: int = DEFAULT_MAX_SINGLE_FILE_BYTES,
    max_total_extract_bytes: int = DEFAULT_MAX_TOTAL_EXTRACT_BYTES,
    execute: bool = False,
    created_at: str | None = None,
    object_repository: ObjectStorageRepository | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(input_root)
    strategy_dir = Path(strategy_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    storage = Path(storage_path) if storage_path else in_root / "storage.json"
    object_storage = Path(object_storage_path) if object_storage_path else in_root / "objects"

    blocking_reasons: list[str] = []
    download_payload = _load_json(in_root / "download-probe-manifest.json", blocking_reasons, "download_probe_manifest_missing")
    strategy_payload = _load_json(strategy_dir / "evidence-verification-strategy.json", blocking_reasons, "evidence_verification_strategy_missing")
    download_manifest = _source_manifest(download_payload)
    strategy_manifest = _source_manifest(strategy_payload)
    strategy_items = _select_strategy_items(strategy_manifest=strategy_manifest, project_ids=project_ids)

    repository = object_repository or _repository(storage_path=storage, object_storage_path=object_storage)
    should_close_repository = object_repository is None
    try:
        items: list[dict[str, Any]] = []
        project_sample_items: list[dict[str, Any]] = []
        for strategy_item in strategy_items:
            result = _process_strategy_item(
                strategy_item=strategy_item,
                download_manifest=download_manifest,
                output_root=out_root,
                repository=repository,
                execute=execute,
                max_extract_files=max_extract_files,
                max_single_file_bytes=max_single_file_bytes,
                max_total_extract_bytes=max_total_extract_bytes,
                created_at=created,
            )
            items.append(result["item"])
            project_sample_items.append(result["project_sample"])
    finally:
        if should_close_repository:
            repository.session.close()

    summary = _summary(items=items, project_sample_items=project_sample_items, blocking_reasons=blocking_reasons)
    manifest = {
        "manifest_version": GUANGZHOU_ARCHIVE_EXTRACT_PROBE_VERSION,
        "manifest_kind": GUANGZHOU_ARCHIVE_EXTRACT_PROBE_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_ARCHIVE_EXTRACT_PROBE_ADAPTER_ID,
        "pipeline_stage": "ArchiveExtractProbe",
        "manifest_id": f"GUANGZHOU-ARCHIVE-EXTRACT-PROBE-{_fingerprint({'items': items})[:16]}",
        "created_at": created,
        "source_input_root": str(in_root),
        "source_strategy_root": str(strategy_dir),
        "source_download_probe_manifest_path": str(in_root / "download-probe-manifest.json"),
        "source_evidence_verification_strategy_path": str(strategy_dir / "evidence-verification-strategy.json"),
        "storage_path_optional": str(storage),
        "object_storage_path_optional": str(object_storage),
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": bool(execute),
        "project_ids": list(project_ids),
        "items": items,
        "sample_items": items[:100],
        "project_sample_items": project_sample_items,
        "project_sample_preview_items": project_sample_items[:80],
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "archive_extract_enabled": bool(execute),
            "parse_enabled": False,
            "llm_execution_enabled": False,
            "graphify_enabled": False,
            "mempalace_enabled": False,
            "path_traversal_block_enabled": True,
            "zip_bomb_guard_enabled": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_archive_extract_probe_mode": "EXECUTED" if execute else "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    output_path = out_root / "archive-extract-probe-manifest.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _process_strategy_item(
    *,
    strategy_item: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    output_root: Path,
    repository: ObjectStorageRepository,
    execute: bool,
    max_extract_files: int,
    max_single_file_bytes: int,
    max_total_extract_bytes: int,
    created_at: str,
) -> dict[str, Any]:
    project_id = str(strategy_item.get("project_id") or "")
    flow_no = _flow_no(strategy_item.get("flow_no"))
    snapshot_id = str(strategy_item.get("attachment_snapshot_id") or "")
    flow_dir = _flow_directory(strategy_item=strategy_item, download_manifest=download_manifest, output_root=output_root)
    (flow_dir / "extracted").mkdir(parents=True, exist_ok=True)
    base = _base_item(strategy_item=strategy_item, flow_dir=flow_dir, created_at=created_at)
    child_refs: list[dict[str, Any]] = []
    failure_taxonomy: list[str] = []
    inventory: dict[str, Any] = {}

    if str(strategy_item.get("extract_policy") or "") not in {"TARGETED_EXTRACT", "INVENTORY_ONLY"}:
        item = {
            **base,
            "archive_extract_state": "SKIPPED_BY_EVIDENCE_STRATEGY",
            "failure_taxonomy": ["extract_policy_not_targeted"],
            "archive_inventory": {},
            "child_snapshot_refs": [],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        return {"item": item, "project_sample": _project_sample(strategy_item=strategy_item, item=item, flow_dir=flow_dir)}

    readback = repository.replay_snapshot(snapshot_id)
    if not bool(readback.get("replayable")):
        state = str(readback.get("readback_state") or "READBACK_NOT_REPLAYABLE")
        item = {
            **base,
            "archive_extract_state": "SNAPSHOT_READBACK_FAILED",
            "snapshot_readback_state": state,
            "failure_taxonomy": [state],
            "archive_inventory": {},
            "child_snapshot_refs": [],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        return {"item": item, "project_sample": _project_sample(strategy_item=strategy_item, item=item, flow_dir=flow_dir)}

    data = readback.get("bytes") or b""
    source_url = str(strategy_item.get("attachment_url") or (readback.get("manifest") or {}).get("source_url_optional") or "")
    if _is_rar(source_url=source_url, content_type=str(readback.get("content_type") or ""), data=data):
        item = {
            **base,
            "archive_extract_state": "RAR_EXTRACTION_UNSUPPORTED_IN_V1",
            "snapshot_readback_state": str(readback.get("readback_state") or ""),
            "failure_taxonomy": ["rar_inventory_or_extract_deferred"],
            "archive_inventory": {"archive_type": "RAR", "deep_extract_enabled": False},
            "child_snapshot_refs": [],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        return {"item": item, "project_sample": _project_sample(strategy_item=strategy_item, item=item, flow_dir=flow_dir)}

    if not zipfile.is_zipfile(BytesIO(data)):
        item = {
            **base,
            "archive_extract_state": "NOT_ARCHIVE_OR_UNSUPPORTED_ARCHIVE",
            "snapshot_readback_state": str(readback.get("readback_state") or ""),
            "failure_taxonomy": ["not_zip_archive"],
            "archive_inventory": {},
            "child_snapshot_refs": [],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        return {"item": item, "project_sample": _project_sample(strategy_item=strategy_item, item=item, flow_dir=flow_dir)}

    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            inventory = _zip_inventory(infos)
            selected_infos, selection_failures = _select_zip_members(
                infos,
                strategy_item=strategy_item,
                max_extract_files=max_extract_files,
                max_single_file_bytes=max_single_file_bytes,
                max_total_extract_bytes=max_total_extract_bytes,
            )
            failure_taxonomy.extend(selection_failures)
            if execute and str(strategy_item.get("extract_policy") or "") == "TARGETED_EXTRACT":
                total_written = 0
                for index, info in enumerate(selected_infos, start=1):
                    child_data = archive.read(info)
                    total_written += len(child_data)
                    child_ref = _save_child_snapshot(
                        repository=repository,
                        strategy_item=strategy_item,
                        parent_readback=readback,
                        info=info,
                        child_data=child_data,
                        output_dir=flow_dir / "extracted",
                        index=index,
                        created_at=created_at,
                    )
                    child_refs.append(child_ref)
                if total_written > max_total_extract_bytes:
                    failure_taxonomy.append("archive_total_extract_size_limit_exceeded_after_read")
    except zipfile.BadZipFile:
        failure_taxonomy.append("zip_bad_file")
        inventory = {"archive_type": "ZIP", "archive_state": "ARCHIVE_INVENTORY_FAILED"}
    except RuntimeError as exc:
        failure_taxonomy.append(f"zip_extract_runtime_error:{type(exc).__name__}")
    except Exception as exc:  # pragma: no cover - defensive boundary
        failure_taxonomy.append(f"archive_extract_exception:{type(exc).__name__}")

    if child_refs:
        state = "TARGETED_CHILD_SNAPSHOTS_CAPTURED"
    elif str(strategy_item.get("extract_policy") or "") == "INVENTORY_ONLY":
        state = "ARCHIVE_INVENTORY_ONLY"
    elif failure_taxonomy:
        state = "ARCHIVE_EXTRACT_REVIEW_REQUIRED"
    else:
        state = "NO_ELIGIBLE_CHILD_DOCUMENTS"
    item = {
        **base,
        "archive_extract_state": state,
        "snapshot_readback_state": str(readback.get("readback_state") or ""),
        "archive_inventory": inventory,
        "child_snapshot_refs": child_refs,
        "child_snapshot_count": len(child_refs),
        "failure_taxonomy": _dedupe_strings(failure_taxonomy),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_item_files(flow_dir=flow_dir, item=item)
    return {"item": item, "project_sample": _project_sample(strategy_item=strategy_item, item=item, flow_dir=flow_dir)}


def _select_zip_members(
    infos: list[zipfile.ZipInfo],
    *,
    strategy_item: Mapping[str, Any],
    max_extract_files: int,
    max_single_file_bytes: int,
    max_total_extract_bytes: int,
) -> tuple[list[zipfile.ZipInfo], list[str]]:
    failures: list[str] = []
    candidates: list[zipfile.ZipInfo] = []
    total_size = 0
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        safe, reason = _safe_inner_path(name)
        if not safe:
            failures.append(reason)
            continue
        suffix = Path(PurePosixPath(name).name).suffix.lower()
        if suffix not in ALLOWED_CHILD_EXTENSIONS:
            continue
        if info.flag_bits & 0x1:
            failures.append("archive_member_encrypted")
            continue
        if info.file_size > max_single_file_bytes:
            failures.append("archive_member_single_file_size_limit_exceeded")
            continue
        if info.file_size > 1024 * 1024 and info.compress_size and info.file_size / max(1, info.compress_size) > 100:
            failures.append("archive_member_suspicious_compression_ratio")
            continue
        total_size += info.file_size
        if total_size > max_total_extract_bytes:
            failures.append("archive_total_extract_size_limit_exceeded")
            break
        candidates.append(info)
    keywords = [str(value).lower() for value in list(strategy_item.get("file_name_priority_keywords") or []) if value]
    candidates.sort(key=lambda info: _member_priority(info.filename, keywords))
    return candidates[: max(0, min(_int(strategy_item.get("max_extract_files")) or max_extract_files, max_extract_files))], _dedupe_strings(failures)


def _member_priority(name: str, keywords: list[str]) -> tuple[int, str]:
    lowered = name.lower()
    hit = 0 if any(keyword and keyword in lowered for keyword in keywords) else 1
    return (hit, lowered)


def _save_child_snapshot(
    *,
    repository: ObjectStorageRepository,
    strategy_item: Mapping[str, Any],
    parent_readback: Mapping[str, Any],
    info: zipfile.ZipInfo,
    child_data: bytes,
    output_dir: Path,
    index: int,
    created_at: str,
) -> dict[str, Any]:
    parent_snapshot_id = str(strategy_item.get("attachment_snapshot_id") or parent_readback.get("snapshot_id") or "")
    inner_path = info.filename
    suffix = Path(PurePosixPath(inner_path).name).suffix.lower()
    content_type = _content_type_for_suffix(suffix)
    child_snapshot_id = f"GZ-ARCH-CHILD-{_fingerprint({'parent': parent_snapshot_id, 'inner': inner_path, 'sha': hashlib.sha256(child_data).hexdigest()})[:20]}"
    manifest = repository.save_snapshot(
        child_data,
        snapshot_id=child_snapshot_id,
        snapshot_kind="guangzhou_archive_child_document",
        content_type=content_type,
        source_url_optional=str(strategy_item.get("attachment_url") or ""),
        source_family_optional="GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        lineage_refs={
            "project_id": str(strategy_item.get("project_id") or ""),
            "flow_no": _flow_no(strategy_item.get("flow_no")),
            "parent_archive_snapshot_id": parent_snapshot_id,
            "archive_inner_path": inner_path,
            "evidence_strategy_item_id": str(strategy_item.get("evidence_strategy_item_id") or ""),
        },
        created_at=created_at,
        adapter_id=GUANGZHOU_ARCHIVE_EXTRACT_PROBE_ADAPTER_ID,
        source_visibility_state="PUBLIC_VISIBLE",
        fetch_mode="LOCAL_ARCHIVE_CHILD_EXTRACT",
        fetch_audit={
            "parent_archive_snapshot_id": parent_snapshot_id,
            "archive_inner_path": inner_path,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    local_path = output_dir / f"{index:02d}_{_safe_path_part(PurePosixPath(inner_path).name)}"
    local_path.write_bytes(child_data)
    meta = {
        "snapshot_id": child_snapshot_id,
        "parent_archive_snapshot_id": parent_snapshot_id,
        "archive_inner_path": inner_path,
        "content_type": content_type,
        "byte_size": len(child_data),
        "sha256": hashlib.sha256(child_data).hexdigest(),
        "file_path": str(local_path),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    local_path.with_suffix(local_path.suffix + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "snapshot_id": child_snapshot_id,
        "child_snapshot_id": child_snapshot_id,
        "parent_archive_snapshot_id": parent_snapshot_id,
        "archive_inner_path": inner_path,
        "source_url": str(strategy_item.get("attachment_url") or ""),
        "attachment_url": str(strategy_item.get("attachment_url") or ""),
        "attachment_link_text": PurePosixPath(inner_path).name,
        "attachment_role_type": str(strategy_item.get("attachment_role_type") or ""),
        "content_type": content_type,
        "byte_size": len(child_data),
        "sha256": manifest.sha256,
        "local_path": str(local_path),
        "evidence_strategy_item_id": str(strategy_item.get("evidence_strategy_item_id") or ""),
        "target_fields": list(strategy_item.get("target_fields") or []),
        "stage4_targets": list(strategy_item.get("stage4_targets") or []),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _base_item(*, strategy_item: Mapping[str, Any], flow_dir: Path, created_at: str) -> dict[str, Any]:
    return {
        "archive_extract_item_id": f"ARCHIVE-EXTRACT-{_flow_no(strategy_item.get('flow_no'))}-{_fingerprint(strategy_item)[:12]}",
        "evidence_strategy_item_id": str(strategy_item.get("evidence_strategy_item_id") or ""),
        "project_id": str(strategy_item.get("project_id") or ""),
        "project_name": str(strategy_item.get("project_name") or ""),
        "flow_no": _flow_no(strategy_item.get("flow_no")),
        "flow_title": str(strategy_item.get("flow_title") or ""),
        "document_kind": str(strategy_item.get("document_kind") or ""),
        "source_url": str(strategy_item.get("source_url") or ""),
        "attachment_url": str(strategy_item.get("attachment_url") or ""),
        "attachment_snapshot_id": str(strategy_item.get("attachment_snapshot_id") or ""),
        "attachment_link_text": str(strategy_item.get("attachment_link_text") or ""),
        "attachment_role_type": str(strategy_item.get("attachment_role_type") or ""),
        "extract_policy": str(strategy_item.get("extract_policy") or ""),
        "parse_policy": str(strategy_item.get("parse_policy") or ""),
        "target_fields": list(strategy_item.get("target_fields") or []),
        "stage4_targets": list(strategy_item.get("stage4_targets") or []),
        "flow_directory": str(flow_dir),
        "created_at": created_at,
    }


def _project_sample(*, strategy_item: Mapping[str, Any], item: Mapping[str, Any], flow_dir: Path) -> dict[str, Any]:
    child_refs = [dict(ref) for ref in list(item.get("child_snapshot_refs") or []) if isinstance(ref, Mapping)]
    return {
        "target_id": str(item.get("archive_extract_item_id") or ""),
        "parent_target_id": "GUANGZHOU-ARCHIVE-EXTRACT-PROBE-V1",
        "candidate_key": str(strategy_item.get("evidence_strategy_item_id") or ""),
        "project_id": str(strategy_item.get("project_id") or ""),
        "project_name": str(strategy_item.get("project_name") or ""),
        "source_url": str(strategy_item.get("source_url") or ""),
        "document_kind": str(strategy_item.get("document_kind") or ""),
        "jurisdiction": "CN-GD",
        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        "pipeline_stage": "ArchiveExtractProbe",
        "guangzhou_flow_no": _flow_no(strategy_item.get("flow_no")),
        "guangzhou_flow_title": str(strategy_item.get("flow_title") or ""),
        "guangzhou_flow_folder": str(flow_dir),
        "parent_archive_snapshot_id": str(strategy_item.get("attachment_snapshot_id") or ""),
        "archive_extract_state": str(item.get("archive_extract_state") or ""),
        "attachment_snapshot_refs": child_refs,
        "child_snapshot_refs": child_refs,
        "child_snapshot_count": len(child_refs),
        "failure_taxonomy": list(item.get("failure_taxonomy") or []),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_directory(*, strategy_item: Mapping[str, Any], download_manifest: Mapping[str, Any], output_root: Path) -> Path:
    download_sample = _download_sample_lookup(download_manifest).get(
        (
            str(strategy_item.get("project_id") or ""),
            _flow_no(strategy_item.get("flow_no")),
            str(strategy_item.get("source_url") or ""),
        )
    )
    folder = str((download_sample or {}).get("guangzhou_flow_folder") or "")
    if folder:
        source_input_root = Path(str(download_manifest.get("source_input_root") or ""))
        try:
            return output_root / Path(folder).relative_to(source_input_root)
        except Exception:
            pass
    date_part = _safe_path_part(str(strategy_item.get("published_date") or "")[:10] or "NO_DATE")
    title_part = _safe_path_part(str(strategy_item.get("project_name") or "流程页面"))[:90]
    return output_root / "projects" / "CN-GD" / _safe_path_part(str(strategy_item.get("project_id") or "UNKNOWN")) / _safe_path_part(f"{_flow_no(strategy_item.get('flow_no'))}_{strategy_item.get('flow_title') or '流程'}") / _safe_path_part(f"{date_part}_{title_part}")


def _download_sample_lookup(download_manifest: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    out: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for sample in list(download_manifest.get("project_sample_items") or []):
        if not isinstance(sample, Mapping):
            continue
        out[(str(sample.get("project_id") or ""), _flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no")), str(sample.get("source_url") or ""))] = sample
    return out


def _select_strategy_items(*, strategy_manifest: Mapping[str, Any], project_ids: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    requested = {_normalize_project_token(value) for value in project_ids if _normalize_project_token(value)}
    out: list[dict[str, Any]] = []
    for item in list(strategy_manifest.get("items") or []):
        if not isinstance(item, Mapping):
            continue
        project_id = str(item.get("project_id") or "")
        if requested and not (_project_aliases(project_id) & requested):
            continue
        if str(item.get("extract_policy") or "") not in {"TARGETED_EXTRACT", "INVENTORY_ONLY"}:
            continue
        out.append(dict(item))
    return out


def _zip_inventory(infos: list[zipfile.ZipInfo]) -> dict[str, Any]:
    return {
        "archive_type": "ZIP",
        "archive_state": "ARCHIVE_INVENTORY_RECORDED",
        "member_count": len(infos),
        "member_name_probes": [info.filename for info in infos[:MAX_INVENTORY_MEMBERS]],
        "total_uncompressed_bytes": sum(info.file_size for info in infos),
        "total_compressed_bytes": sum(info.compress_size for info in infos),
        "deep_extract_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _safe_inner_path(name: str) -> tuple[bool, str]:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return False, "archive_member_absolute_path_blocked"
    if any(part in {"..", ""} for part in path.parts):
        return False, "archive_member_path_traversal_blocked"
    if re.match(r"^[A-Za-z]:", normalized):
        return False, "archive_member_drive_path_blocked"
    return True, ""


def _is_rar(*, source_url: str, content_type: str, data: bytes) -> bool:
    return Path(urlsplit(source_url).path).suffix.lower() == ".rar" or "rar" in str(content_type or "").lower() or data.startswith(b"Rar!")


def _content_type_for_suffix(suffix: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(suffix.lower(), "application/octet-stream")


def _write_item_files(*, flow_dir: Path, item: Mapping[str, Any]) -> None:
    extract_dir = flow_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    (extract_dir / "archive-extract-probe.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")


def _summary(*, items: list[Mapping[str, Any]], project_sample_items: list[Mapping[str, Any]], blocking_reasons: list[str]) -> dict[str, Any]:
    if blocking_reasons:
        archive_extract_state = "INPUT_BLOCKED"
    elif not items:
        archive_extract_state = "NO_ARCHIVE_CANDIDATES"
    else:
        archive_extract_state = "READY"
    return {
        "archive_extract_state": archive_extract_state,
        "project_sample_count": len(project_sample_items),
        "archive_item_count": len(items),
        "archive_inventory_count": sum(1 for item in items if item.get("archive_inventory")),
        "child_snapshot_count": sum(_int(item.get("child_snapshot_count")) for item in items),
        "targeted_child_snapshot_count": sum(_int(item.get("child_snapshot_count")) for item in items if str(item.get("extract_policy") or "") == "TARGETED_EXTRACT"),
        "archive_extract_state_counts": _counts(item.get("archive_extract_state") for item in items),
        "flow_no_counts": _counts(item.get("flow_no") for item in items),
        "failure_taxonomy_counts": _counts(reason for item in items for reason in list(item.get("failure_taxonomy") or [])),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
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


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _flow_no(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(2) if text else ""


def _project_aliases(project_id: str) -> set[str]:
    return {_normalize_project_token(project_id), _normalize_project_token(_extract_project_code(project_id))}


def _normalize_project_token(value: Any) -> str:
    text = str(value or "").upper().strip()
    return _extract_project_code(text) or text


def _extract_project_code(value: Any) -> str:
    match = re.search(r"JG\d{4}-\d+", str(value or "").upper())
    return match.group(0) if match else ""


def _safe_path_part(value: Any) -> str:
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


def _dedupe_strings(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou ArchiveExtractProbe v1.")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--strategy-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--project-ids", default=",".join(DEFAULT_PROJECT_IDS))
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--max-extract-files", type=int, default=DEFAULT_MAX_EXTRACT_FILES)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_archive_extract_probe(
        input_root=args.input_root,
        strategy_root=args.strategy_root,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
        max_extract_files=args.max_extract_files,
        execute=args.execute,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "archive-extract-probe-manifest.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"guangzhou archive extract probe {result['guangzhou_archive_extract_probe_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GUANGZHOU_ARCHIVE_EXTRACT_PROBE_MANIFEST_KIND",
    "build_guangzhou_archive_extract_probe",
]
