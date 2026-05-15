from __future__ import annotations

import argparse
import csv
import hashlib
import html
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage2_ingestion.playwright_challenge_resolver import PlaywrightAttachmentChallengeResolver
from storage.challenge_stability_report import build_challenge_stability_report
from storage.company_first_certificate_supplement_probe import build_company_first_certificate_supplement_probe
from storage.company_first_stage4_execution import build_company_first_stage4_execution
from storage.db import DatabaseSession
from storage.guangdong_ygp_city_discovery import build_guangdong_ygp_city_discovery
from storage.guangdong_ygp_flow_matrix import FLOW_MODULES
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.responsible_person_early_probe import build_responsible_person_early_probe


GUANGDONG_YGP_FULL_CHAIN_MANIFEST_KIND = "guangdong_ygp_full_chain_v1_manifest"
GUANGDONG_YGP_FULL_CHAIN_VERSION = 1
GUANGDONG_YGP_FULL_CHAIN_ADAPTER_ID = "guangdong-ygp-full-chain-v1-runner"
GUANGDONG_YGP_SOURCE_PROFILE_ID = "GUANGDONG-YGP-FULL-CHAIN"

DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-ygp-full-chain-v1")
DEFAULT_CITY_CODES = (
    "440200",
    "440400",
    "440500",
    "440600",
    "440700",
    "440800",
    "440900",
    "441200",
    "441300",
    "441400",
    "441500",
    "441600",
    "441700",
    "441800",
    "441900",
    "442000",
    "445100",
    "445200",
    "445300",
)
DEFAULT_FLOW_NOS = ("03", "04", "07", "08")
PAGE_ONLY_FLOW_NOS = {"05", "06"}
FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
OVERSIZE_POLICY_TAXONOMY = "OVERSIZE_DEFERRED_BY_POLICY"
REAL_DOWNLOAD_FAILURE_TAXONOMIES = {
    "ygp_attachment_empty_response_review",
    "ygp_attachment_interface_error",
    "ygp_attachment_not_file_like_response",
    "ygp_attachment_transport_error_retry_required",
    "ygp_attachment_temporary_unavailable_retry_required",
    "ygp_attachment_incomplete_read_retry_required",
    "ygp_attachment_login_or_permission_required",
    "ygp_attachment_captcha_or_challenge_required",
    "ygp_attachment_interface_expired_or_stale",
    "ygp_attachment_file_not_found_or_expired",
}
POLICY_DEFERRED_TAXONOMIES = {"DEFERRED_BY_YGP_DOWNLOAD_LIMIT", OVERSIZE_POLICY_TAXONOMY}

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_guangdong_ygp_full_chain(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    city_codes: list[str] | tuple[str, ...] = DEFAULT_CITY_CODES,
    per_city_candidate_limit: int = 1,
    max_pages_per_city: int = 5,
    flow_nos: list[str] | tuple[str, ...] = DEFAULT_FLOW_NOS,
    max_attachments_per_flow_item: int = 5,
    max_bid_file_publicity_downloads_per_project: int = 2,
    enable_attachment_challenge_resolver: bool = False,
    execute: bool = False,
    execute_stage4: bool = False,
    company_first_result_state: str = "NOT_RUN",
    name_enumeration_result_state: str = "NOT_RUN",
    source_stage4_records_json: str | Path | None = None,
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    storage = out_root / "storage.json"
    objects = out_root / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(objects),
    )
    repository = ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)
    getter = http_getter or _default_http_getter

    discovery = build_guangdong_ygp_city_discovery(
        output_root=out_root / "city-discovery",
        city_codes=list(city_codes),
        per_city_candidate_limit=max(0, per_city_candidate_limit),
        max_pages_per_city=max(1, max_pages_per_city),
        build_flow_matrix=True,
        enable_live_public_query=bool(execute),
        http_getter=getter,
        created_at=created,
    )
    flow_matrix = _load_flow_matrix_from_discovery(discovery)
    candidate_index = _candidate_index(discovery)
    selected_flow_nos = {_flow_no(value) for value in flow_nos}
    project_bid_file_download_count: dict[str, int] = {}
    flow_items: list[dict[str, Any]] = []
    project_samples: list[dict[str, Any]] = []

    if execute:
        for detail in _selected_detail_records(flow_matrix, selected_flow_nos):
            result = _execute_detail_record(
                detail=detail,
                candidate_index=candidate_index,
                output_root=out_root,
                repository=repository,
                getter=getter,
                enable_attachment_challenge_resolver=enable_attachment_challenge_resolver,
                max_attachments_per_flow_item=max(0, max_attachments_per_flow_item),
                max_bid_file_publicity_downloads_per_project=max(0, max_bid_file_publicity_downloads_per_project),
                project_bid_file_download_count=project_bid_file_download_count,
                created_at=created,
            )
            flow_items.append(result["flow_item"])
            project_samples.append(result["project_sample"])
    else:
        for detail in _selected_detail_records(flow_matrix, selected_flow_nos):
            planned = _planned_detail_record(detail, candidate_index=candidate_index, output_root=out_root, created_at=created)
            flow_items.append(planned["flow_item"])
            project_samples.append(planned["project_sample"])

    summary = _summary(
        discovery=discovery,
        flow_matrix=flow_matrix,
        flow_items=flow_items,
        project_samples=project_samples,
        execute=execute,
    )
    manifest = {
        "manifest_version": GUANGDONG_YGP_FULL_CHAIN_VERSION,
        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
        "sub_kind": GUANGDONG_YGP_FULL_CHAIN_MANIFEST_KIND,
        "adapter_id": GUANGDONG_YGP_FULL_CHAIN_ADAPTER_ID,
        "pipeline_stage": "GuangdongYgpFullChainV1",
        "manifest_id": f"GUANGDONG-YGP-FULL-CHAIN-{_fingerprint({'items': flow_items, 'summary': summary})[:16]}",
        "created_at": created,
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": bool(execute),
        "source_profile_id": GUANGDONG_YGP_SOURCE_PROFILE_ID,
        "city_codes": list(city_codes),
        "per_city_candidate_limit": per_city_candidate_limit,
        "max_pages_per_city": max_pages_per_city,
        "flow_nos": sorted(selected_flow_nos),
        "max_attachments_per_flow_item": max_attachments_per_flow_item,
        "max_bid_file_publicity_downloads_per_project": max_bid_file_publicity_downloads_per_project,
        "company_first_result_state": company_first_result_state,
        "name_enumeration_result_state": name_enumeration_result_state,
        "source_stage4_records_json": str(source_stage4_records_json or ""),
        "source_city_discovery_manifest_path": str(out_root / "city-discovery" / "guangdong-ygp-city-discovery-v1.json"),
        "source_flow_matrix_manifest_path": str(out_root / "city-discovery" / "flow-matrix" / "guangdong-ygp-flow-matrix-v1.json"),
        "items": flow_items,
        "sample_items": flow_items[:120],
        "project_sample_items": project_samples,
        "project_sample_preview_items": project_samples[:120],
        "summary": summary,
        "safety": {
            "download_enabled": bool(execute),
            "parse_enabled": False,
            "stage4_live_provider_enabled": bool(execute_stage4),
            "llm_execution_enabled": False,
            "flow_08_default_parse_required": False,
            "not_guangzhou_primary_source": True,
            "not_shenzhen_primary_source": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangdong_ygp_full_chain_mode": "EXECUTED" if execute else "DRY_RUN",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": bool(execute),
            "download_enabled": bool(execute),
            "parse_enabled": False,
            "stage4_live_provider_enabled": bool(execute_stage4),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    manifest_path = out_root / "ygp-full-chain-manifest.json"
    _write_json(manifest_path, result)
    _write_json(out_root / "download-probe-manifest.json", result)
    _write_project_file_audit(out_root=out_root, project_samples=project_samples, summary=summary)
    _write_human_file_map(out_root=out_root, project_samples=project_samples)
    _write_global_attachment_list(out_root=out_root, project_samples=project_samples, summary=summary)
    _write_manual_url_check_table(out_root=out_root, discovery=discovery, flow_matrix=flow_matrix)
    stability = build_challenge_stability_report(real_sample_execution_manifest_json=manifest_path)
    _write_json(out_root / "challenge-stability-report.json", stability)

    responsible = build_responsible_person_early_probe(
        input_root=out_root,
        output_root=out_root / "responsible-person",
        created_at=created,
    )
    supplement = build_company_first_certificate_supplement_probe(
        input_root=out_root / "responsible-person",
        output_root=out_root / "company-first-supplement",
        company_first_result_state=company_first_result_state,
        name_enumeration_result_state=name_enumeration_result_state,
        source_stage4_records_json=source_stage4_records_json,
        created_at=created,
    )
    stage4_execution: dict[str, Any] = {}
    if execute_stage4:
        stage4_execution = build_company_first_stage4_execution(
            input_root=out_root / "company-first-supplement",
            output_root=out_root / "company-first-stage4-execution",
            execute=True,
            capture_personnel_project_records=True,
            created_at=created,
        )
    evidence_report = _build_evidence_report(
        out_root=out_root,
        full_chain=result,
        responsible=responsible,
        supplement=supplement,
        stage4_execution=stage4_execution,
        created_at=created,
    )
    closeout = _build_batch_closeout(
        out_root=out_root,
        full_chain=result,
        responsible=responsible,
        supplement=supplement,
        stage4_execution=stage4_execution,
        created_at=created,
    )
    result["summary"]["responsible_person_summary"] = responsible.get("summary", {})
    result["summary"]["company_first_supplement_summary"] = supplement.get("summary", {})
    result["summary"]["batch_closeout_state"] = closeout["summary"]["batch_closeout_state"]
    _write_json(out_root / "ygp-full-chain-manifest.json", result)
    _write_json(out_root / "download-probe-manifest.json", result)
    _write_json(out_root / "ygp-evidence-report-v1.json", evidence_report)
    _write_json(out_root / "guangdong-ygp-batch-stability-closeout-v1.json", closeout)
    _write_json(out_root / "ygp-batch-stability-closeout-v1.json", closeout)
    _scan_forbidden_or_raise(out_root / "ygp-full-chain-manifest.json")
    _scan_forbidden_or_raise(out_root / "ygp-evidence-report-v1.json")
    _scan_forbidden_or_raise(out_root / "guangdong-ygp-batch-stability-closeout-v1.json")
    return result


def _load_flow_matrix_from_discovery(discovery: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _source_manifest(discovery)
    raw_path = str(manifest.get("flow_matrix_manifest_path") or "")
    path = Path(raw_path) if raw_path else None
    if path and path.exists() and path.is_file():
        return _source_manifest(_load_json(path))
    flow = manifest.get("flow_matrix_result")
    return _source_manifest(flow if isinstance(flow, Mapping) else {})


def _candidate_index(discovery: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    manifest = _source_manifest(discovery)
    rows: dict[str, Mapping[str, Any]] = {}
    for record in _list(manifest.get("ygp_candidate_project_records")):
        if not isinstance(record, Mapping):
            continue
        url = str(record.get("ygp_project_url") or "")
        if url:
            rows[url] = record
    return rows


def _selected_detail_records(flow_matrix: Mapping[str, Any], flow_nos: set[str]) -> list[dict[str, Any]]:
    rows = []
    for record in _list(flow_matrix.get("ygp_detail_readback_records")):
        if not isinstance(record, Mapping):
            continue
        if str(record.get("detail_readback_state") or "") != "YGP_DETAIL_READBACK_READY":
            continue
        if _flow_no(record.get("flow_no")) not in flow_nos:
            continue
        rows.append(dict(record))
    rows.sort(key=lambda item: (str(item.get("site_code") or ""), str(item.get("project_code") or ""), str(item.get("flow_no") or ""), str(item.get("published_at") or "")))
    return rows


def _planned_detail_record(
    detail: Mapping[str, Any],
    *,
    candidate_index: Mapping[str, Mapping[str, Any]],
    output_root: Path,
    created_at: str,
) -> dict[str, dict[str, Any]]:
    project = _project_identity(detail, candidate_index=candidate_index)
    source_dir = _flow_notice_directory(
        output_root=output_root,
        city_code=project["city_code"],
        project_id=project["project_id"],
        flow_no=str(detail.get("flow_no") or ""),
        flow_title=str(detail.get("flow_title") or ""),
        published_date=str(detail.get("published_at") or ""),
        title=str(detail.get("notice_title") or detail.get("project_name") or ""),
    )
    attachments = _attachment_items(detail, project=project)
    flow_item = _flow_item_base(
        detail=detail,
        project=project,
        source_dir=source_dir,
        listed_attachment_count=len(attachments),
        download_attempted_count=0,
        deferred_attachment_count=len(attachments),
        detail_snapshot_refs=[],
        attachment_snapshot_refs=[],
        failure_taxonomy=["dry_run_not_executed"],
        challenge_diagnostics=[],
        created_at=created_at,
    )
    sample = _project_sample(
        detail=detail,
        project=project,
        source_dir=source_dir,
        detail_snapshot_refs=[],
        attachment_snapshot_refs=[],
        attachment_items=attachments,
        failure_taxonomy=["dry_run_not_executed"],
        challenge_diagnostics=[],
        target_execution_state="DRY_RUN_NOT_EXECUTED",
        created_at=created_at,
    )
    return {"flow_item": flow_item, "project_sample": sample}


def _execute_detail_record(
    *,
    detail: Mapping[str, Any],
    candidate_index: Mapping[str, Mapping[str, Any]],
    output_root: Path,
    repository: ObjectStorageRepository,
    getter: HttpGetter,
    enable_attachment_challenge_resolver: bool,
    max_attachments_per_flow_item: int,
    max_bid_file_publicity_downloads_per_project: int,
    project_bid_file_download_count: dict[str, int],
    created_at: str,
) -> dict[str, dict[str, Any]]:
    project = _project_identity(detail, candidate_index=candidate_index)
    flow_no = _flow_no(detail.get("flow_no"))
    source_dir = _flow_notice_directory(
        output_root=output_root,
        city_code=project["city_code"],
        project_id=project["project_id"],
        flow_no=flow_no,
        flow_title=str(detail.get("flow_title") or ""),
        published_date=str(detail.get("published_at") or ""),
        title=str(detail.get("notice_title") or detail.get("project_name") or ""),
    )
    for child in ("detail", "attachments", "extracted", "parsed"):
        (source_dir / child).mkdir(parents=True, exist_ok=True)
    attachments = _attachment_items(detail, project=project)
    failure_taxonomy: list[str] = []
    challenge_diagnostics: list[dict[str, Any]] = []
    detail_snapshot_refs: list[dict[str, Any]] = []
    attachment_snapshot_refs: list[dict[str, Any]] = []

    detail_ref = _save_detail_snapshot(detail=detail, project=project, source_dir=source_dir, repository=repository, created_at=created_at)
    if detail_ref:
        detail_snapshot_refs.append(detail_ref)
    else:
        failure_taxonomy.append("ygp_detail_snapshot_not_captured")
    _write_detail_html(detail=detail, project=project, source_dir=source_dir)

    selected_attachments: list[Mapping[str, Any]] = []
    if flow_no == "08":
        selected_attachments = []
    elif flow_no in PAGE_ONLY_FLOW_NOS:
        selected_attachments = []
    else:
        limit = len(attachments)
        if max_attachments_per_flow_item > 0:
            limit = min(limit, max_attachments_per_flow_item)
        selected_attachments = attachments[:limit]
    if flow_no == "08" and max_bid_file_publicity_downloads_per_project > 0:
        # v1 deliberately keeps 08 as registry/list-only unless a later strategy marks it as targeted.
        project_bid_file_download_count[project["project_id"]] = project_bid_file_download_count.get(project["project_id"], 0)
    deferred_attachment_count = max(0, len(attachments) - len(selected_attachments))
    if deferred_attachment_count and flow_no != "08":
        failure_taxonomy.append("DEFERRED_BY_YGP_DOWNLOAD_LIMIT")
    if flow_no == "08" and attachments:
        failure_taxonomy.append("FLOW_08_REGISTER_ONLY_NOT_DOWNLOADED_BY_DEFAULT")
    download_attempts: list[dict[str, Any]] = []
    policy_deferred_attachment_count = 0
    for index, attachment in enumerate(selected_attachments, start=1):
        attempt = _download_attachment(
            attachment=attachment,
            detail=detail,
            project=project,
            source_dir=source_dir,
            repository=repository,
            getter=getter,
            enable_attachment_challenge_resolver=enable_attachment_challenge_resolver,
            index=index,
            created_at=created_at,
        )
        download_attempts.append(attempt)
        if attempt.get("policy_deferred"):
            policy_deferred_attachment_count += 1
        if isinstance(attempt.get("snapshot_ref"), Mapping):
            attachment_snapshot_refs.append(dict(attempt["snapshot_ref"]))
        failure_taxonomy.extend(_list(attempt.get("failure_taxonomy")))
        if isinstance(attempt.get("challenge_diagnostic"), Mapping):
            challenge_diagnostics.append(dict(attempt["challenge_diagnostic"]))
    if not attachments and flow_no not in PAGE_ONLY_FLOW_NOS:
        failure_taxonomy.append("ygp_no_public_attachment_link_found")
    target_execution_state = _target_execution_state(
        detail_snapshot_refs=detail_snapshot_refs,
        attachment_snapshot_refs=attachment_snapshot_refs,
        failure_taxonomy=failure_taxonomy,
        page_only=flow_no in PAGE_ONLY_FLOW_NOS,
        register_only=flow_no == "08",
    )
    flow_item = _flow_item_base(
        detail=detail,
        project=project,
        source_dir=source_dir,
        listed_attachment_count=len(attachments),
        download_attempted_count=sum(1 for attempt in download_attempts if attempt.get("download_attempted")),
        deferred_attachment_count=deferred_attachment_count + policy_deferred_attachment_count,
        detail_snapshot_refs=detail_snapshot_refs,
        attachment_snapshot_refs=attachment_snapshot_refs,
        failure_taxonomy=_dedupe(failure_taxonomy),
        challenge_diagnostics=challenge_diagnostics,
        created_at=created_at,
    )
    sample = _project_sample(
        detail=detail,
        project=project,
        source_dir=source_dir,
        detail_snapshot_refs=detail_snapshot_refs,
        attachment_snapshot_refs=attachment_snapshot_refs,
        attachment_items=attachments,
        failure_taxonomy=_dedupe(failure_taxonomy),
        challenge_diagnostics=challenge_diagnostics,
        target_execution_state=target_execution_state,
        created_at=created_at,
    )
    _write_attachment_list(source_dir=source_dir, project=project, detail=detail, attachments=attachments, created_at=created_at)
    _write_json(source_dir / "download-probe.json", {"item": flow_item, "project_sample": sample, "download_attempts": download_attempts})
    return {"flow_item": flow_item, "project_sample": sample}


def _save_detail_snapshot(
    *,
    detail: Mapping[str, Any],
    project: Mapping[str, str],
    source_dir: Path,
    repository: ObjectStorageRepository,
    created_at: str,
) -> dict[str, Any] | None:
    payload = {
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "city_code": project["city_code"],
        "flow_no": str(detail.get("flow_no") or ""),
        "flow_title": str(detail.get("flow_title") or ""),
        "source_url": str(detail.get("source_url") or ""),
        "detail_url": str(detail.get("source_url") or ""),
        "notice_title": str(detail.get("notice_title") or ""),
        "published_at": str(detail.get("published_at") or ""),
        "text_probe": str(detail.get("text_probe") or ""),
        "text_probe_sha256": str(detail.get("text_probe_sha256") or ""),
        "attachment_items": _attachment_items(detail, project=project),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    snapshot_id = _stable_id("YGP-DETAIL", project["project_id"], detail.get("flow_no"), detail.get("source_url"), detail.get("notice_id"))
    manifest = repository.save_snapshot(
        data,
        snapshot_id=snapshot_id,
        snapshot_kind="YGP_DETAIL_READBACK",
        content_type="application/json;charset=utf-8",
        source_url_optional=str(detail.get("source_url") or ""),
        source_family_optional="guangdong_ygp",
        lineage_refs={"project_id": project["project_id"], "city_code": project["city_code"], "flow_no": str(detail.get("flow_no") or "")},
        adapter_id=GUANGDONG_YGP_FULL_CHAIN_ADAPTER_ID,
        fetched_at=created_at,
        captured_at=created_at,
        fetch_mode="ygp_detail_readback_manifest_snapshot",
        created_at=created_at,
    )
    readback = repository.replay_snapshot(snapshot_id)
    if not readback.get("replayable"):
        return None
    path = source_dir / "detail" / "detail.json"
    path.write_bytes(data)
    return {
        "snapshot_id": snapshot_id,
        "source_url": str(detail.get("source_url") or ""),
        "parent_source_url": str(detail.get("source_url") or ""),
        "parse_state": "NOT_RUN_YGP_FULL_CHAIN",
        "guangdong_ygp_flow_no": str(detail.get("flow_no") or ""),
        "guangdong_ygp_flow_title": str(detail.get("flow_title") or ""),
        "attachment_role_type": "detail",
        "content_type": manifest.content_type,
        "byte_size": manifest.byte_size,
        "sha256": manifest.sha256,
        "readback_state": str(readback.get("readback_state") or ""),
        "local_path": str(path),
        "human_readable_path": str(path),
        "human_file_name": path.name,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _write_detail_html(*, detail: Mapping[str, Any], project: Mapping[str, str], source_dir: Path) -> None:
    text = str(detail.get("text_probe") or "")
    body = "\n".join(
        part
        for part in (
            project.get("project_name", ""),
            str(detail.get("notice_title") or ""),
            str(detail.get("published_at") or ""),
            text,
        )
        if part
    )
    html_text = f"<!doctype html><meta charset=\"utf-8\"><title>{html.escape(str(detail.get('notice_title') or 'YGP detail'))}</title><pre>{html.escape(body)}</pre>"
    _write_text(source_dir / "detail" / "detail.html", html_text, encoding="utf-8")


def _download_attachment(
    *,
    attachment: Mapping[str, Any],
    detail: Mapping[str, Any],
    project: Mapping[str, str],
    source_dir: Path,
    repository: ObjectStorageRepository,
    getter: HttpGetter,
    enable_attachment_challenge_resolver: bool,
    index: int,
    created_at: str,
) -> dict[str, Any]:
    url = str(attachment.get("download_url") or "")
    file_name = str(attachment.get("file_name") or f"attachment-{index}")
    failure_taxonomy: list[str] = []
    size_diagnostic = _fetch_file_size_diagnostic(url=url, getter=getter, detail=detail, attachment=attachment)
    response_attempts: list[dict[str, Any]] = []
    prewarm_diagnostic: dict[str, Any] | None = None
    if not url:
        return {
            "project_id": project["project_id"],
            "city_code": project["city_code"],
            "flow_no": str(detail.get("flow_no") or ""),
            "attachment_url": "",
            "download_url": "",
            "attachment_name": file_name,
            "attachment_link_text": file_name,
            "status": "BLOCKED",
            "download_attempted": False,
            "policy_deferred": False,
            "snapshot_ref": None,
            "local_path": "",
            "status_code": 0,
            "content_type": "",
            "content_length": 0,
            "response_probe": "",
            **_size_summary_fields(size_diagnostic),
            "failure_taxonomy": ["ygp_attachment_download_url_missing"],
            "challenge_diagnostic": None,
            "download_diagnostics": {
                "file_size": size_diagnostic,
                "response_attempts": response_attempts,
                "detail_prewarm": prewarm_diagnostic,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    size_bytes = _diagnostic_size_bytes(size_diagnostic)
    max_bytes = _max_attachment_bytes()
    if size_bytes is not None and size_bytes > max_bytes:
        failure_taxonomy = [OVERSIZE_POLICY_TAXONOMY]
        return {
            "project_id": project["project_id"],
            "city_code": project["city_code"],
            "flow_no": str(detail.get("flow_no") or ""),
            "attachment_url": url,
            "download_url": url,
            "attachment_name": file_name,
            "attachment_link_text": file_name,
            "status": "POLICY_DEFERRED",
            "download_attempted": False,
            "policy_deferred": True,
            "policy_deferred_reason": OVERSIZE_POLICY_TAXONOMY,
            "snapshot_ref": None,
            "local_path": "",
            "status_code": _int(size_diagnostic.get("status_code")),
            "content_type": str(size_diagnostic.get("content_type") or ""),
            "content_length": 0,
            "response_probe": str(size_diagnostic.get("response_probe") or ""),
            **_size_summary_fields(size_diagnostic),
            "failure_taxonomy": failure_taxonomy,
            "challenge_diagnostic": None,
            "download_diagnostics": {
                "file_size": size_diagnostic,
                "response_attempts": response_attempts,
                "detail_prewarm": prewarm_diagnostic,
                "max_attachment_bytes": max_bytes,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    response = _fetch_bytes(
        url,
        getter=getter,
        route="ygp_attachment_download",
        detail=detail,
        attachment=attachment,
        headers=_ygp_attachment_headers(detail=detail),
    )
    response_attempts.append(_download_response_diagnostic(response, phase="initial_http_get"))
    data = bytes(response.get("content") or b"")
    content_type = str(response.get("content_type") or "")
    status_code = int(response.get("status_code") or 0)
    if not _file_like_response(content_type=content_type, data=data):
        failure_taxonomy.extend(_attachment_failure_taxonomy(status_code=status_code, content_type=content_type, data=data, error=str(response.get("error") or "")))
        if _should_detail_prewarm_retry(failure_taxonomy):
            prewarm_diagnostic = _prewarm_detail_for_attachment(detail=detail, attachment=attachment, getter=getter)
            retry_response = _fetch_bytes(
                url,
                getter=getter,
                route="ygp_attachment_download_retry",
                detail=detail,
                attachment=attachment,
                headers=_ygp_attachment_headers(detail=detail),
            )
            response_attempts.append(_download_response_diagnostic(retry_response, phase="after_detail_prewarm_retry"))
            retry_data = bytes(retry_response.get("content") or b"")
            retry_content_type = str(retry_response.get("content_type") or "")
            if _file_like_response(content_type=retry_content_type, data=retry_data):
                response = retry_response
                data = retry_data
                content_type = retry_content_type
                status_code = int(retry_response.get("status_code") or 0)
                failure_taxonomy = []
            else:
                response = retry_response
                data = retry_data
                content_type = retry_content_type
                status_code = int(retry_response.get("status_code") or 0)
                failure_taxonomy = _attachment_failure_taxonomy(
                    status_code=status_code,
                    content_type=content_type,
                    data=data,
                    error=str(retry_response.get("error") or ""),
                )
        challenge_diagnostic = None
        if _should_attempt_challenge_resolver(
            enable_attachment_challenge_resolver=enable_attachment_challenge_resolver,
            failure_taxonomy=failure_taxonomy,
            content_type=content_type,
            data=data,
        ):
            challenge = _resolve_with_browser(url=url, detail_url=str(detail.get("source_url") or ""), file_name=file_name)
            challenge_diagnostic = challenge.get("challenge_diagnostic") if isinstance(challenge.get("challenge_diagnostic"), Mapping) else None
            if isinstance(challenge.get("content"), (bytes, bytearray)) and _file_like_response(
                content_type=str(challenge.get("content_type") or ""),
                data=bytes(challenge.get("content") or b""),
            ):
                data = bytes(challenge.get("content") or b"")
                content_type = str(challenge.get("content_type") or "") or _content_type_from_file_name(file_name)
                failure_taxonomy = _dedupe([item for item in failure_taxonomy if not item.startswith("ygp_attachment_")])
            else:
                failure_taxonomy.extend(_list(challenge.get("failure_taxonomy")))
        if not _file_like_response(content_type=content_type, data=data):
            response_diagnostic = _download_response_diagnostic(response, phase="final_failed_response")
            return {
                "project_id": project["project_id"],
                "city_code": project["city_code"],
                "flow_no": str(detail.get("flow_no") or ""),
                "attachment_url": url,
                "download_url": url,
                "attachment_name": file_name,
                "attachment_link_text": file_name,
                "status": "DEGRADED",
                "download_attempted": True,
                "policy_deferred": False,
                "snapshot_ref": None,
                "local_path": "",
                "status_code": status_code,
                "content_type": content_type,
                "content_length": int(response_diagnostic.get("content_length") or 0),
                "response_probe": str(response_diagnostic.get("response_probe") or ""),
                **_size_summary_fields(size_diagnostic),
                "failure_taxonomy": _dedupe(failure_taxonomy or ["ygp_attachment_not_file_like_response"]),
                "challenge_diagnostic": challenge_diagnostic,
                "download_diagnostics": {
                    "file_size": size_diagnostic,
                    "response_attempts": response_attempts,
                    "detail_prewarm": prewarm_diagnostic,
                },
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
    snapshot_id = _stable_id("YGP-ATTACH", project["project_id"], detail.get("flow_no"), url, file_name)
    manifest = repository.save_snapshot(
        data,
        snapshot_id=snapshot_id,
        snapshot_kind="YGP_ATTACHMENT",
        content_type=content_type or _content_type_from_file_name(file_name),
        source_url_optional=url,
        source_family_optional="guangdong_ygp",
        lineage_refs={"project_id": project["project_id"], "city_code": project["city_code"], "flow_no": str(detail.get("flow_no") or "")},
        adapter_id=GUANGDONG_YGP_FULL_CHAIN_ADAPTER_ID,
        fetched_at=created_at,
        captured_at=created_at,
        fetch_mode="ygp_attachment_download",
        created_at=created_at,
    )
    readback = repository.replay_snapshot(snapshot_id)
    if not readback.get("replayable"):
        response_diagnostic = _download_response_diagnostic(response, phase="final_file_response")
        return {
            "project_id": project["project_id"],
            "city_code": project["city_code"],
            "flow_no": str(detail.get("flow_no") or ""),
            "attachment_url": url,
            "download_url": url,
            "attachment_name": file_name,
            "attachment_link_text": file_name,
            "status": "DEGRADED",
            "download_attempted": True,
            "policy_deferred": False,
            "snapshot_ref": None,
            "local_path": "",
            "status_code": status_code,
            "content_type": content_type,
            "content_length": int(response_diagnostic.get("content_length") or 0),
            "response_probe": str(response_diagnostic.get("response_probe") or ""),
            **_size_summary_fields(size_diagnostic),
            "failure_taxonomy": ["ygp_attachment_snapshot_readback_missing"],
            "challenge_diagnostic": None,
            "download_diagnostics": {
                "file_size": size_diagnostic,
                "response_attempts": response_attempts,
                "detail_prewarm": prewarm_diagnostic,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    try:
        local_path = _write_human_attachment(
            source_dir=source_dir,
            file_name=file_name,
            index=index,
            data=data,
            ref_sha256=manifest.sha256,
            snapshot_id=snapshot_id,
            source_url=url,
        )
    except (OSError, ValueError) as exc:
        response_diagnostic = _download_response_diagnostic(response, phase="final_file_response")
        return {
            "project_id": project["project_id"],
            "city_code": project["city_code"],
            "flow_no": str(detail.get("flow_no") or ""),
            "attachment_url": url,
            "download_url": url,
            "attachment_name": file_name,
            "attachment_link_text": file_name,
            "status": "DEGRADED",
            "download_attempted": True,
            "policy_deferred": False,
            "snapshot_ref": None,
            "captured_snapshot_ref": {
                "snapshot_id": snapshot_id,
                "source_url": url,
                "parent_source_url": str(detail.get("source_url") or ""),
                "attachment_url": url,
                "content_type": manifest.content_type,
                "byte_size": manifest.byte_size,
                "sha256": manifest.sha256,
                "readback_state": str(readback.get("readback_state") or ""),
                "local_path": "",
                "human_readable_path": "",
                "human_file_name": "",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            "local_path": "",
            "status_code": status_code,
            "content_type": content_type,
            "content_length": int(response_diagnostic.get("content_length") or 0),
            "response_probe": str(response_diagnostic.get("response_probe") or ""),
            **_size_summary_fields(size_diagnostic),
            "failure_taxonomy": [
                f"ygp_attachment_human_write_failed:{type(exc).__name__}",
                "ygp_attachment_snapshot_captured_human_write_failed",
            ],
            "challenge_diagnostic": None,
            "download_diagnostics": {
                "file_size": size_diagnostic,
                "response_attempts": response_attempts,
                "detail_prewarm": prewarm_diagnostic,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    ref = {
        "snapshot_id": snapshot_id,
        "source_url": url,
        "parent_source_url": str(detail.get("source_url") or ""),
        "attachment_url": url,
        "parse_state": "NOT_RUN_YGP_FULL_CHAIN",
        "guangdong_ygp_flow_no": str(detail.get("flow_no") or ""),
        "guangdong_ygp_flow_title": str(detail.get("flow_title") or ""),
        "attachment_role_type": _attachment_role(str(detail.get("flow_no") or "")),
        "attachment_link_text": file_name,
        "content_type": manifest.content_type,
        "byte_size": manifest.byte_size,
        "sha256": manifest.sha256,
        "readback_state": str(readback.get("readback_state") or ""),
        "local_path": local_path,
        "human_readable_path": local_path,
        "human_file_name": Path(local_path).name if local_path else "",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    response_diagnostic = _download_response_diagnostic(response, phase="final_file_response")
    return {
        "project_id": project["project_id"],
        "city_code": project["city_code"],
        "flow_no": str(detail.get("flow_no") or ""),
        "attachment_url": url,
        "download_url": url,
        "attachment_name": file_name,
        "attachment_link_text": file_name,
        "status": "FETCHED",
        "download_attempted": True,
        "policy_deferred": False,
        "snapshot_ref": ref,
        "local_path": local_path,
        "status_code": status_code,
        "content_type": content_type,
        "content_length": int(response_diagnostic.get("content_length") or len(data)),
        "response_probe": str(response_diagnostic.get("response_probe") or ""),
        **_size_summary_fields(size_diagnostic),
        "failure_taxonomy": [],
        "challenge_diagnostic": None,
        "download_diagnostics": {
            "file_size": size_diagnostic,
            "response_attempts": response_attempts,
            "detail_prewarm": prewarm_diagnostic,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fetch_file_size_diagnostic(*, url: str, getter: HttpGetter, detail: Mapping[str, Any], attachment: Mapping[str, Any]) -> dict[str, Any]:
    file_size_url = str(attachment.get("file_size_url") or "").strip()
    diagnostic: dict[str, Any] = {
        "file_size_url": file_size_url,
        "file_size_state": "FILE_SIZE_URL_MISSING",
        "file_size_bytes": None,
        "status_code": 0,
        "content_type": "",
        "content_length": 0,
        "response_probe": "",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if file_size_url:
        response = _fetch_bytes(
            file_size_url,
            getter=getter,
            route="ygp_attachment_file_size",
            detail=detail,
            attachment=attachment,
            binary=False,
            headers=_ygp_size_headers(detail=detail),
        )
        response_diag = _download_response_diagnostic(response, phase="file_size_get")
        size_bytes = _parse_file_size_response(response)
        diagnostic.update(
            {
                "file_size_state": "FILE_SIZE_READY" if size_bytes is not None else "FILE_SIZE_UNPARSED",
                "file_size_bytes": size_bytes,
                "status_code": response_diag["status_code"],
                "content_type": response_diag["content_type"],
                "content_length": response_diag["content_length"],
                "response_probe": response_diag["response_probe"],
                "response_url": response_diag["response_url"],
                "error": response_diag["error"],
            }
        )
        if size_bytes is not None:
            return diagnostic
    if not url:
        return diagnostic
    head_response = _fetch_bytes(
        url,
        getter=getter,
        route="ygp_attachment_head_size",
        detail=detail,
        attachment=attachment,
        binary=False,
        method="HEAD",
        headers=_ygp_attachment_headers(detail=detail),
    )
    head_diag = _download_response_diagnostic(head_response, phase="download_head_size")
    content_length = _content_length_from_response(head_response)
    diagnostic.update(
        {
            "file_size_state": "HEAD_CONTENT_LENGTH_READY" if content_length is not None else diagnostic["file_size_state"],
            "file_size_bytes": content_length,
            "head_status_code": head_diag["status_code"],
            "head_content_type": head_diag["content_type"],
            "head_content_length": head_diag["content_length"],
            "head_response_probe": head_diag["response_probe"],
            "head_response_url": head_diag["response_url"],
            "head_error": head_diag["error"],
        }
    )
    return diagnostic


def _prewarm_detail_for_attachment(*, detail: Mapping[str, Any], attachment: Mapping[str, Any], getter: HttpGetter) -> dict[str, Any]:
    detail_url = str(detail.get("source_url") or "")
    diagnostic: dict[str, Any] = {
        "prewarm_url": detail_url,
        "attempted": bool(detail_url),
        "status_code": 0,
        "content_type": "",
        "response_probe": "",
        "state": "DETAIL_PREWARM_SKIPPED_NO_URL",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if not detail_url:
        return diagnostic
    response = _fetch_bytes(
        detail_url,
        getter=getter,
        route="ygp_detail_prewarm",
        detail=detail,
        attachment=attachment,
        binary=False,
        headers=_ygp_detail_headers(detail=detail),
    )
    response_diag = _download_response_diagnostic(response, phase="detail_prewarm")
    diagnostic.update(response_diag)
    diagnostic["state"] = "DETAIL_PREWARM_ATTEMPTED"
    return diagnostic


def _download_response_diagnostic(response: Mapping[str, Any], *, phase: str) -> dict[str, Any]:
    data = bytes(response.get("content") or b"")
    body = str(response.get("body") or response.get("text") or "")
    probe_source = data if data else body.encode("utf-8", errors="replace")
    return {
        "phase": phase,
        "status_code": _int(response.get("status_code") or response.get("status")),
        "content_type": str(response.get("content_type") or ""),
        "content_length": len(data) if data else len(body.encode("utf-8", errors="replace")),
        "content_length_header": _content_length_from_response(response),
        "response_url": str(response.get("url") or ""),
        "response_probe": _response_probe(probe_source),
        "error": str(response.get("error") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _response_probe(data: bytes) -> str:
    if not data:
        return ""
    probe = data[:500]
    return probe.decode("utf-8", errors="replace")


def _size_summary_fields(size_diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "file_size_url": str(size_diagnostic.get("file_size_url") or ""),
        "file_size_status_code": _int(size_diagnostic.get("status_code") or size_diagnostic.get("head_status_code")),
        "file_size_content_type": str(size_diagnostic.get("content_type") or size_diagnostic.get("head_content_type") or ""),
        "file_size_bytes": size_diagnostic.get("file_size_bytes"),
        "file_size_state": str(size_diagnostic.get("file_size_state") or ""),
    }


def _diagnostic_size_bytes(size_diagnostic: Mapping[str, Any]) -> int | None:
    raw = size_diagnostic.get("file_size_bytes")
    try:
        if raw is None or raw == "":
            return None
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return None


def _parse_file_size_response(response: Mapping[str, Any]) -> int | None:
    data = bytes(response.get("content") or b"")
    text = str(response.get("body") or response.get("text") or "")
    if not text and data:
        text = data.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        return _content_length_from_response(response)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, Mapping):
        raw = payload.get("data")
        if isinstance(raw, Mapping):
            raw = raw.get("size") or raw.get("fileSize") or raw.get("file_size")
        parsed = _parse_int_or_none(raw)
        if parsed is not None:
            return parsed
    parsed_text = _parse_int_or_none(text)
    if parsed_text is not None:
        return parsed_text
    match = re.search(r'"?data"?\s*[:=]\s*"?(\d+)"?', text)
    if match:
        return int(match.group(1))
    return _content_length_from_response(response)


def _parse_int_or_none(raw: Any) -> int | None:
    try:
        if raw is None or raw == "":
            return None
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _content_length_from_response(response: Mapping[str, Any]) -> int | None:
    headers = response.get("headers") if isinstance(response.get("headers"), Mapping) else {}
    for key in ("Content-Length", "content-length"):
        value = headers.get(key)
        parsed = _parse_int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _should_detail_prewarm_retry(failure_taxonomy: Iterable[str]) -> bool:
    values = set(str(item) for item in failure_taxonomy)
    return bool(values & {"ygp_attachment_empty_response_review", "ygp_attachment_interface_error", "ygp_attachment_not_file_like_response"})


def _should_attempt_challenge_resolver(
    *,
    enable_attachment_challenge_resolver: bool,
    failure_taxonomy: Iterable[str],
    content_type: str,
    data: bytes,
) -> bool:
    values = set(str(item) for item in failure_taxonomy)
    if OVERSIZE_POLICY_TAXONOMY in values:
        return False
    if enable_attachment_challenge_resolver:
        return True
    if values & {"ygp_attachment_captcha_or_challenge_required", "ygp_attachment_login_or_permission_required"}:
        return True
    lowered_type = str(content_type or "").lower()
    if ("html" in lowered_type or "json" in lowered_type) and values & {"ygp_attachment_interface_error", "ygp_attachment_not_file_like_response"}:
        return True
    probe = _response_probe(data).lower()
    return bool(("验证码" in probe or "captcha" in probe or "登录" in probe or "login" in probe) and values)


def _ygp_attachment_headers(*, detail: Mapping[str, Any]) -> dict[str, str]:
    return _ygp_common_headers(
        detail=detail,
        accept="application/pdf,application/zip,application/x-rar-compressed,application/msword,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*",
    )


def _ygp_size_headers(*, detail: Mapping[str, Any]) -> dict[str, str]:
    return _ygp_common_headers(detail=detail, accept="application/json,text/plain,*/*")


def _ygp_detail_headers(*, detail: Mapping[str, Any]) -> dict[str, str]:
    return _ygp_common_headers(detail=detail, accept="application/json,text/plain,*/*")


def _ygp_common_headers(*, detail: Mapping[str, Any], accept: str) -> dict[str, str]:
    referer = str(detail.get("source_url") or "").strip() or "https://ygp.gdzwfw.gov.cn/ggzy-portal/"
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Origin": "https://ygp.gdzwfw.gov.cn",
    }


def _resolve_with_browser(*, url: str, detail_url: str, file_name: str) -> dict[str, Any]:
    try:
        resolver = PlaywrightAttachmentChallengeResolver.from_environment()
        if not os.environ.get("KAKA_CHALLENGE_TIMEOUT_MS"):
            resolver.timeout_ms = 15000
        if not os.environ.get("KAKA_CHALLENGE_OCR_ATTEMPTS"):
            resolver.ocr_attempts = 1
        if not os.environ.get("KAKA_CHALLENGE_JIGSAW_ATTEMPTS"):
            resolver.jigsaw_attempts = 1
        result = resolver.resolve_same_site_attachment({"attachment_url": url, "detail_page_url": detail_url})
        return {
            "content": bytes(result.get("content") or b""),
            "content_type": str(result.get("content_type") or _content_type_from_file_name(file_name)),
            "failure_taxonomy": [],
            "challenge_diagnostic": {
                "capture_kind": "attachment",
                "attachment_url": url,
                "attachment_link_text": file_name,
                "attempted": True,
                "state": "RESOLVED_AND_SNAPSHOT_CAPTURED",
                "resolution_method": str(result.get("resolution_method") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
        }
    except Exception as exc:  # pragma: no cover - runtime boundary
        return {
            "content": b"",
            "content_type": "",
            "failure_taxonomy": [f"ygp_attachment_challenge_resolver_failed:{type(exc).__name__}"],
            "challenge_diagnostic": {
                "capture_kind": "attachment",
                "attachment_url": url,
                "attachment_link_text": file_name,
                "attempted": True,
                "state": "FAILED_CLOSED_CHALLENGE_NOT_RESOLVED",
                "blocker_reason": str(exc)[:300],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
        }


def _fetch_bytes(
    url: str,
    *,
    getter: HttpGetter,
    route: str,
    detail: Mapping[str, Any],
    attachment: Mapping[str, Any],
    binary: bool = True,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    response = getter(
        url,
        {
            "route": route,
            "detail": dict(detail),
            "attachment": dict(attachment),
            "binary": bool(binary),
            "method": method,
            "headers": dict(headers or {}),
        },
    )
    if isinstance(response.get("content"), (bytes, bytearray)):
        content = bytes(response.get("content") or b"")
    else:
        body = response.get("body") if response.get("body") is not None else response.get("text") or ""
        content = str(body).encode("utf-8", errors="replace")
    headers = response.get("headers") if isinstance(response.get("headers"), Mapping) else {}
    body_text = response.get("body") if response.get("body") is not None else response.get("text")
    if body_text is None and not binary:
        body_text = content.decode("utf-8", errors="replace")
    return {
        "status_code": int(response.get("status_code") or response.get("status") or 0),
        "content_type": str(response.get("content_type") or headers.get("Content-Type") or headers.get("content-type") or ""),
        "headers": dict(headers),
        "content": content,
        "body": str(body_text or ""),
        "url": str(response.get("url") or url),
        "error": str(response.get("error") or ""),
    }


def _default_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    attempts = _http_attempt_count(context)
    last_result: Mapping[str, Any] = {}
    for attempt_no in range(1, attempts + 1):
        result = _default_http_getter_once(url, context)
        last_result = result
        if not _should_retry_http_result(result, context=context, attempt_no=attempt_no, attempts=attempts):
            return result
        time.sleep(_http_retry_delay_seconds(result, attempt_no=attempt_no))
    return dict(last_result)


def _default_http_getter_once(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    method = str(context.get("method") or "GET").upper()
    body: bytes | None = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaYgpFullChain/1.0",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://ygp.gdzwfw.gov.cn/ggzy-portal/",
    }
    context_headers = context.get("headers") if isinstance(context.get("headers"), Mapping) else {}
    headers.update({str(key): str(value) for key, value in dict(context_headers).items() if str(value)})
    if method == "POST":
        body = json.dumps(context.get("json_body") or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=UTF-8"
    request_url = _request_safe_url(url)
    request = urllib.request.Request(request_url, data=body, headers=headers, method=method)
    try:
        timeout_seconds = _http_timeout_seconds(context)
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            headers = dict(response.headers.items())
            content_type = response.headers.get("Content-Type", "")
            if context.get("binary"):
                max_bytes = _max_attachment_bytes()
                content_length = _int(headers.get("Content-Length") or headers.get("content-length"))
                if content_length > max_bytes:
                    return {
                        "status_code": int(getattr(response, "status", 0) or 0),
                        "content_type": content_type,
                        "headers": headers,
                        "body": "",
                        "content": b"",
                        "url": response.geturl(),
                        "error": f"attachment_content_length_exceeds_limit:{content_length}>{max_bytes}",
                    }
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    return {
                        "status_code": int(getattr(response, "status", 0) or 0),
                        "content_type": content_type,
                        "headers": headers,
                        "body": "",
                        "content": b"",
                        "url": response.geturl(),
                        "error": f"attachment_body_exceeds_limit:{len(data)}>{max_bytes}",
                    }
            else:
                data = response.read()
            if context.get("binary"):
                body = ""
                content = data
            else:
                body = data.decode("utf-8", errors="replace")
                content = b""
            return {
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": content_type,
                "headers": headers,
                "body": body,
                "content": content,
                "url": response.geturl(),
            }
    except urllib.error.HTTPError as exc:
        data = exc.read() if exc.fp else b""
        return {
            "status_code": int(exc.code),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body": data.decode("utf-8", errors="replace"),
            "content": data if context.get("binary") else b"",
            "url": url,
            "error": str(exc),
        }
    except urllib.error.URLError as exc:
        return {"status_code": 0, "content_type": "", "headers": {}, "body": "", "content": b"", "url": url, "error": str(exc.reason)}
    except http.client.IncompleteRead as exc:
        return {"status_code": 0, "content_type": "", "headers": {}, "body": "", "content": b"", "url": url, "error": f"IncompleteRead:{exc}"}
    except TimeoutError as exc:
        return {"status_code": 0, "content_type": "", "headers": {}, "body": "", "content": b"", "url": url, "error": f"TimeoutError:{exc}"}
    except OSError as exc:
        return {"status_code": 0, "content_type": "", "headers": {}, "body": "", "content": b"", "url": url, "error": f"{type(exc).__name__}:{exc}"}
    except (UnicodeEncodeError, ValueError) as exc:
        return {"status_code": 0, "content_type": "", "headers": {}, "body": "", "content": b"", "url": url, "error": f"{type(exc).__name__}:{exc}"}


def _request_safe_url(url: str) -> str:
    parts = urllib.parse.urlsplit(str(url or ""))
    if not parts.scheme or not parts.netloc:
        return url
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%")
    query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe="=&?/%:+,;@")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _http_timeout_seconds(context: Mapping[str, Any]) -> int:
    raw = os.environ.get("KAKA_YGP_HTTP_TIMEOUT_SECONDS")
    default_timeout = 20 if context.get("binary") else 60
    if raw is None or not str(raw).strip():
        return default_timeout
    try:
        return max(3, int(float(raw)))
    except ValueError:
        return default_timeout


def _http_attempt_count(context: Mapping[str, Any]) -> int:
    raw = os.environ.get("KAKA_YGP_HTTP_ATTEMPTS")
    default_attempts = 1 if context.get("binary") else 3
    if raw is None or not str(raw).strip():
        return default_attempts
    try:
        return max(1, min(5, int(raw)))
    except ValueError:
        return default_attempts


def _should_retry_http_result(result: Mapping[str, Any], *, context: Mapping[str, Any], attempt_no: int, attempts: int) -> bool:
    if attempt_no >= attempts or context.get("binary"):
        return False
    status_code = int(result.get("status_code") or 0)
    error = str(result.get("error") or "").lower()
    if status_code in {429, 500, 502, 503, 504}:
        return True
    if status_code == 0 and any(token in error for token in ("ssl", "eof", "timeout", "timed out", "connection reset", "temporarily unavailable")):
        return True
    return False


def _http_retry_delay_seconds(result: Mapping[str, Any], *, attempt_no: int) -> float:
    headers = result.get("headers") if isinstance(result.get("headers"), Mapping) else {}
    retry_after = str(headers.get("Retry-After") or headers.get("retry-after") or "").strip()
    body = str(result.get("body") or result.get("text") or "")
    candidates: list[float] = []
    if retry_after:
        try:
            candidates.append(float(retry_after))
        except ValueError:
            pass
    match = re.search(r"请\s*(\d{1,3})\s*秒后重试", body)
    if match:
        candidates.append(float(match.group(1)))
    base_delay = min(2.0, 0.5 * attempt_no)
    delay = max(candidates) if candidates else base_delay
    return min(delay, _http_retry_after_max_seconds())


def _http_retry_after_max_seconds() -> float:
    raw = os.environ.get("KAKA_YGP_RETRY_AFTER_MAX_SECONDS")
    if raw is None or not str(raw).strip():
        return 90.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 90.0


def _max_attachment_bytes() -> int:
    raw = os.environ.get("KAKA_YGP_MAX_ATTACHMENT_BYTES")
    default_limit = 30 * 1024 * 1024
    if raw is None or not str(raw).strip():
        return default_limit
    try:
        return max(1024 * 1024, int(float(raw)))
    except ValueError:
        return default_limit


def _write_human_attachment(*, source_dir: Path, file_name: str, index: int, data: bytes, ref_sha256: str, snapshot_id: str, source_url: str) -> str:
    attachment_dir = source_dir / "attachments"
    _ensure_dir(attachment_dir)
    safe_name = _short_human_file_name(file_name, max_chars=72) or f"attachment_{index:02d}.bin"
    path = attachment_dir / f"{index:02d}_{safe_name}"
    if _path_needs_short_fallback(path) or _path_needs_short_fallback(_attachment_meta_path(path)):
        path = _attachment_fallback_path(attachment_dir=attachment_dir, index=index, snapshot_id=snapshot_id, suffix=_safe_suffix(safe_name))
    _ensure_dir(path.parent)
    try:
        _write_bytes(path, data)
    except (OSError, ValueError):
        fallback_path = _attachment_fallback_path(attachment_dir=attachment_dir, index=index, snapshot_id=snapshot_id, suffix=_safe_suffix(safe_name))
        if fallback_path == path:
            raise
        _ensure_dir(fallback_path.parent)
        _write_bytes(fallback_path, data)
        path = fallback_path
    meta = {
        "snapshot_id": snapshot_id,
        "source_url": source_url,
        "source_file_name": file_name,
        "human_file_name": path.name,
        "human_readable_path": str(path),
        "byte_size": len(data),
        "sha256": ref_sha256,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_json(_attachment_meta_path(path), meta)
    return str(path)


def _project_identity(detail: Mapping[str, Any], *, candidate_index: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    project_url = str(detail.get("source_url") or "")
    # detail source_url is the API URL; use matrix task source URL for the human project route when available.
    project_route_url = str(detail.get("source_project_url") or detail.get("source_url") or "")
    candidate = candidate_index.get(project_route_url) or {}
    city_code = str(detail.get("site_code") or candidate.get("city_code") or candidate.get("region_code") or "")
    project_code = str(detail.get("project_code") or candidate.get("project_code") or "")
    project_name = str(detail.get("project_name") or candidate.get("project_name") or candidate.get("notice_title") or project_code or project_url)
    project_id = f"PROJ-CN-GD-YGP-{city_code}-{_stable_slug(project_code or project_name)}"
    return {
        "project_id": project_id,
        "project_name": project_name,
        "city_code": city_code or "44",
        "project_code": project_code,
        "project_url": project_route_url,
    }


def _flow_item_base(
    *,
    detail: Mapping[str, Any],
    project: Mapping[str, str],
    source_dir: Path,
    listed_attachment_count: int,
    download_attempted_count: int,
    deferred_attachment_count: int,
    detail_snapshot_refs: list[Mapping[str, Any]],
    attachment_snapshot_refs: list[Mapping[str, Any]],
    failure_taxonomy: list[str],
    challenge_diagnostics: list[Mapping[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    return {
        "download_probe_item_id": _stable_id("YGP-DOWNLOAD-PROBE", project["project_id"], detail.get("flow_no"), detail.get("source_url")),
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "city_code": project["city_code"],
        "source_profile_id": GUANGDONG_YGP_SOURCE_PROFILE_ID,
        "flow_no": _flow_no(detail.get("flow_no")),
        "flow_title": str(detail.get("flow_title") or ""),
        "document_kind": str(detail.get("document_kind") or ""),
        "source_url": str(detail.get("source_url") or ""),
        "published_date": str(detail.get("published_at") or ""),
        "download_policy": _download_policy(_flow_no(detail.get("flow_no"))),
        "download_policy_state": _download_policy_state(_flow_no(detail.get("flow_no")), download_attempted_count),
        "detail_capture_status": str(detail.get("detail_readback_state") or ""),
        "detail_snapshot_count": len(detail_snapshot_refs),
        "listed_attachment_count": listed_attachment_count,
        "download_attempted_count": download_attempted_count,
        "deferred_attachment_count": deferred_attachment_count,
        "attachment_snapshot_count": len(attachment_snapshot_refs),
        "challenge_diagnostics": list(challenge_diagnostics),
        "failure_taxonomy": _dedupe(failure_taxonomy),
        "flow_directory": str(source_dir),
        "parse_state": "NOT_RUN_YGP_FULL_CHAIN",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_sample(
    *,
    detail: Mapping[str, Any],
    project: Mapping[str, str],
    source_dir: Path,
    detail_snapshot_refs: list[Mapping[str, Any]],
    attachment_snapshot_refs: list[Mapping[str, Any]],
    attachment_items: list[Mapping[str, Any]],
    failure_taxonomy: list[str],
    challenge_diagnostics: list[Mapping[str, Any]],
    target_execution_state: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "target_id": f"YGP-{project['city_code']}-{_flow_no(detail.get('flow_no'))}",
        "source_profile_id": GUANGDONG_YGP_SOURCE_PROFILE_ID,
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "city_code": project["city_code"],
        "project_code": project["project_code"],
        "source_url": str(detail.get("source_url") or ""),
        "source_urls": [str(detail.get("source_url") or "")],
        "verification_urls": {
            "all_urls": _dedupe([detail.get("source_url"), *[item.get("download_url") for item in attachment_items]]),
            "detail_urls": [str(detail.get("source_url") or "")],
            "attachment_urls": _dedupe(item.get("download_url") for item in attachment_items),
        },
        "document_kind": str(detail.get("document_kind") or ""),
        "guangdong_ygp_flow_no": _flow_no(detail.get("flow_no")),
        "guangdong_ygp_flow_title": str(detail.get("flow_title") or ""),
        "detail_snapshot_refs": list(detail_snapshot_refs),
        "attachment_snapshot_refs": list(attachment_snapshot_refs),
        "attachment_link_items": [dict(item) for item in attachment_items],
        "file_inventory": {
            "listed_attachment_count": len(attachment_items),
            "attachment_snapshot_count": len(attachment_snapshot_refs),
            "detail_snapshot_count": len(detail_snapshot_refs),
        },
        "project_completeness_contract": {
            "detail_readback_required": True,
            "flow_08_default_download_required": False,
            "attachment_replay_required_for_downloaded_refs": True,
            "target_execution_state": target_execution_state,
        },
        "parse_metrics": {
            "parse_state": "NOT_RUN_YGP_FULL_CHAIN",
            "markitdown_enabled": False,
            "ocr_enabled": False,
        },
        "detail_snapshot_count": len(detail_snapshot_refs),
        "attachment_snapshot_count": len(attachment_snapshot_refs),
        "challenge_attempted_count": sum(1 for row in challenge_diagnostics if row.get("attempted")),
        "challenge_diagnostics": list(challenge_diagnostics),
        "failure_taxonomy": _dedupe(failure_taxonomy),
        "flow_directory": str(source_dir),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    discovery: Mapping[str, Any],
    flow_matrix: Mapping[str, Any],
    flow_items: list[Mapping[str, Any]],
    project_samples: list[Mapping[str, Any]],
    execute: bool,
) -> dict[str, Any]:
    projects = {str(item.get("project_id") or "") for item in project_samples if item.get("project_id")}
    city_codes = {str(item.get("city_code") or "") for item in project_samples if item.get("city_code")}
    attachment_count = sum(_int(item.get("attachment_snapshot_count")) for item in project_samples)
    listed_count = sum(_int(item.get("file_inventory", {}).get("listed_attachment_count")) for item in project_samples)
    attempted = sum(_int(item.get("download_attempted_count")) for item in flow_items)
    discovery_manifest = _source_manifest(discovery)
    city_tasks = [row for row in _list(discovery_manifest.get("ygp_city_task_records")) if isinstance(row, Mapping)]
    city_search_records = [row for row in _list(discovery_manifest.get("ygp_city_search_records")) if isinstance(row, Mapping)]
    candidate_records = [row for row in _list(discovery_manifest.get("ygp_candidate_project_records")) if isinstance(row, Mapping)]
    candidate_city_codes = {str(row.get("city_code") or "") for row in candidate_records if row.get("city_code")}
    searched_ready_city_codes = {str(row.get("city_code") or "") for row in city_search_records if _int(row.get("status_code")) == 200}
    unsupported_or_no_candidate_cities = [
        str(row.get("city_code") or "")
        for row in city_tasks
        if str(row.get("city_code") or "") in searched_ready_city_codes and str(row.get("city_code") or "") not in candidate_city_codes
    ]
    return {
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "city_task_count": len(city_tasks),
        "city_covered_count": len(city_codes),
        "city_search_ready_count": len(searched_ready_city_codes),
        "city_no_supported_07_candidate_count": len(unsupported_or_no_candidate_cities),
        "city_no_supported_07_candidate_codes": unsupported_or_no_candidate_cities,
        "city_discovery_blocker_taxonomy_counts": _counts(
            reason for row in city_search_records for reason in _list(row.get("blocker_taxonomy"))
        ),
        "city_search_rejected_record_count": sum(_int(row.get("rejected_record_count")) for row in city_search_records),
        "project_count": len(projects),
        "flow_item_count": len(flow_items),
        "flow_nos": sorted({str(item.get("flow_no") or "") for item in flow_items if item.get("flow_no")}),
        "flow_matrix_present_flow_nos": list((flow_matrix.get("summary") or {}).get("present_flow_nos") or []),
        "listed_attachment_count": listed_count,
        "download_attempted_count": attempted,
        "attachment_snapshot_count": attachment_count,
        "attachment_snapshot_success_rate": (attachment_count / attempted) if attempted else 0.0,
        "detail_snapshot_count": sum(_int(item.get("detail_snapshot_count")) for item in project_samples),
        "failure_taxonomy_counts": _counts(reason for item in flow_items for reason in _list(item.get("failure_taxonomy"))),
        "flow_08_register_only_count": sum(1 for item in flow_items if str(item.get("flow_no") or "") == "08"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _build_evidence_report(
    *,
    out_root: Path,
    full_chain: Mapping[str, Any],
    responsible: Mapping[str, Any],
    supplement: Mapping[str, Any],
    stage4_execution: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    responsible_manifest = _source_manifest(responsible)
    supplement_manifest = _source_manifest(supplement)
    stage4_manifest = _source_manifest(stage4_execution)
    project_records: list[dict[str, Any]] = []
    for item in _list(responsible_manifest.get("items")):
        if not isinstance(item, Mapping):
            continue
        project_records.append(
            {
                "project_id": str(item.get("project_id") or ""),
                "project_name": str(item.get("project_name") or ""),
                "early_probe_state": str(item.get("early_probe_state") or ""),
                "stage4_readiness_state": str(item.get("stage4_readiness_state") or ""),
                "candidate_group_count": len(_list(item.get("candidate_groups"))),
                "verification_target_count": len(_list(item.get("verification_targets"))),
                "flow_08_targeted_parse_required": bool(item.get("flow_08_targeted_parse_required")),
                "next_actions": _list(item.get("next_actions")),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    summary = {
        "project_count": len({row["project_id"] for row in project_records if row["project_id"]}),
        "candidate_group_count": sum(_int(row.get("candidate_group_count")) for row in project_records),
        "responsible_person_project_count": len(project_records),
        "flow_08_targeted_parse_required_project_count": sum(1 for row in project_records if row.get("flow_08_targeted_parse_required")),
        "company_first_provider_job_count": _int((supplement_manifest.get("stage4_provider_jobs") or {}).get("summary", {}).get("job_count")),
        "stage4_execution_item_count": len(_list(stage4_manifest.get("items"))),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    report = {
        "manifest_kind": "guangdong_ygp_evidence_report_v1",
        "adapter_id": "guangdong-ygp-evidence-report-v1-builder",
        "created_at": created_at,
        "source_full_chain_manifest_path": str(out_root / "ygp-full-chain-manifest.json"),
        "verification_evidence": {
            "project_records": project_records,
            "candidate_group_policy": "YGP_07_DETAIL_AND_SMALL_ATTACHMENT_FIRST",
            "flow_08_policy": "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "process_stability": {
            "full_chain_summary": dict(full_chain.get("summary") or {}),
            "responsible_person_summary": dict(responsible.get("summary") or {}),
            "company_first_supplement_summary": dict(supplement.get("summary") or {}),
            "stage4_execution_summary": dict(stage4_execution.get("summary") or {}),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "optimization_recommendations": _ygp_recommendations(project_records),
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return report


def _build_batch_closeout(
    *,
    out_root: Path,
    full_chain: Mapping[str, Any],
    responsible: Mapping[str, Any],
    supplement: Mapping[str, Any],
    stage4_execution: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    full_summary = dict(full_chain.get("summary") or {})
    responsible_summary = dict(responsible.get("summary") or {})
    supplement_summary = dict(supplement.get("summary") or {})
    stage4_summary = dict(stage4_execution.get("summary") or {})
    full_manifest = _source_manifest(full_chain)
    project_count = _int(full_summary.get("project_count"))
    detail_count = _int(full_summary.get("detail_snapshot_count"))
    blockers = dict(full_summary.get("failure_taxonomy_counts") or {})
    items = [item for item in _list(full_manifest.get("items")) if isinstance(item, Mapping)]
    download_required_items = [item for item in items if str(item.get("flow_no") or "") in {"03", "04", "07"}]
    download_required_listed_count = sum(_int(item.get("listed_attachment_count")) for item in download_required_items)
    download_required_attempted_count = sum(_int(item.get("download_attempted_count")) for item in download_required_items)
    download_required_snapshot_count = sum(_int(item.get("attachment_snapshot_count")) for item in download_required_items)
    download_required_deferred_count = sum(_int(item.get("deferred_attachment_count")) for item in download_required_items)
    download_required_failed_attempt_count = max(0, download_required_attempted_count - download_required_snapshot_count)
    download_required_success_rate = (
        download_required_snapshot_count / download_required_attempted_count if download_required_attempted_count else 0.0
    )
    download_blockers = {
        key: value
        for key, value in blockers.items()
        if str(key).startswith("ygp_attachment_")
        or str(key).startswith("FLOW_08_")
        or str(key).startswith("DEFERRED_")
        or str(key) == OVERSIZE_POLICY_TAXONOMY
    }
    real_download_failure_taxonomy_counts = {
        key: value for key, value in download_blockers.items() if str(key) in REAL_DOWNLOAD_FAILURE_TAXONOMIES
    }
    policy_deferred_taxonomy_counts = {
        key: value for key, value in download_blockers.items() if str(key) in POLICY_DEFERRED_TAXONOMIES
    }
    if project_count <= 0:
        state = "YGP_FULL_CHAIN_BLOCKED"
    elif detail_count <= 0:
        state = "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED"
    elif download_required_listed_count > 0 and download_required_snapshot_count <= 0:
        state = "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED"
    elif download_required_listed_count > 0 and download_required_failed_attempt_count > 0:
        state = "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED"
    elif download_required_listed_count > 0 and download_required_deferred_count > 0:
        state = "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED"
    else:
        state = "YGP_FULL_CHAIN_READY"
    summary = {
        "batch_closeout_state": state,
        "project_count": project_count,
        "city_covered_count": _int(full_summary.get("city_covered_count")),
        "flow_item_count": _int(full_summary.get("flow_item_count")),
        "listed_attachment_count": _int(full_summary.get("listed_attachment_count")),
        "attachment_snapshot_count": _int(full_summary.get("attachment_snapshot_count")),
        "attachment_snapshot_success_rate": float(full_summary.get("attachment_snapshot_success_rate") or 0.0),
        "download_required_listed_attachment_count": download_required_listed_count,
        "download_required_attempted_count": download_required_attempted_count,
        "download_required_attachment_snapshot_count": download_required_snapshot_count,
        "download_required_failed_attempt_count": download_required_failed_attempt_count,
        "download_required_deferred_attachment_count": download_required_deferred_count,
        "download_required_attachment_snapshot_success_rate": download_required_success_rate,
        "download_blocker_taxonomy_counts": download_blockers,
        "download_required_real_failure_taxonomy_counts": real_download_failure_taxonomy_counts,
        "download_required_policy_deferred_taxonomy_counts": policy_deferred_taxonomy_counts,
        "responsible_person_project_count": _int(responsible_summary.get("project_count")),
        "stage4_provider_job_count": _int((supplement_summary.get("provider_job_count") or supplement_summary.get("job_count"))),
        "stage4_execution_item_count": _int(stage4_summary.get("item_count")),
        "flow_08_targeted_parse_required_count": _int(responsible_summary.get("flow_08_targeted_parse_required_count")),
        "failure_taxonomy_counts": blockers,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return {
        "manifest_kind": "guangdong_ygp_batch_stability_closeout_v1",
        "adapter_id": "guangdong-ygp-batch-stability-closeout-v1-builder",
        "created_at": created_at,
        "source_full_chain_manifest_path": str(out_root / "ygp-full-chain-manifest.json"),
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _ygp_recommendations(project_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in project_records:
        if record.get("flow_08_targeted_parse_required"):
            action = "FLOW_08_TARGETED_PARSE_REQUIRED_AFTER_YGP_07_REVIEW"
        elif record.get("stage4_readiness_state") == "READY_FOR_STAGE4_INPUT":
            action = "STAGE4_PUBLIC_REGISTRATION_CHECK_READY"
        else:
            action = "COMPANY_FIRST_SUPPLEMENT_OR_SOURCE_RETRY_REQUIRED"
        rows.append(
            {
                "project_id": record.get("project_id", ""),
                "recommended_action": action,
                "reason": str(record.get("early_probe_state") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _write_project_file_audit(*, out_root: Path, project_samples: list[Mapping[str, Any]], summary: Mapping[str, Any]) -> None:
    by_project: dict[str, list[Mapping[str, Any]]] = {}
    for sample in project_samples:
        by_project.setdefault(str(sample.get("project_id") or ""), []).append(sample)
    records = []
    for project_id, samples in sorted(by_project.items()):
        records.append(
            {
                "project_id": project_id,
                "project_name": str(samples[0].get("project_name") or ""),
                "city_code": str(samples[0].get("city_code") or ""),
                "flow_count": len(samples),
                "flow_nos": _dedupe(sample.get("guangdong_ygp_flow_no") for sample in samples),
                "detail_snapshot_count": sum(_int(sample.get("detail_snapshot_count")) for sample in samples),
                "attachment_snapshot_count": sum(_int(sample.get("attachment_snapshot_count")) for sample in samples),
                "failure_taxonomy": _dedupe(reason for sample in samples for reason in _list(sample.get("failure_taxonomy"))),
                "verification_urls": {
                    "all_urls": _dedupe(url for sample in samples for url in _list((sample.get("verification_urls") or {}).get("all_urls"))),
                },
                "ready_for_tailored_analysis": False,
                "ready_for_evidence_report": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    payload = {
        "manifest_kind": "guangdong_ygp_project_file_audit_v1",
        "project_records": records,
        "summary": dict(summary),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_json(out_root / "project-file-audit.json", payload)


def _write_global_attachment_list(*, out_root: Path, project_samples: list[Mapping[str, Any]], summary: Mapping[str, Any]) -> None:
    records = [
        dict(item)
        for sample in project_samples
        for item in _list(sample.get("attachment_link_items"))
        if isinstance(item, Mapping)
    ]
    payload = {
        "manifest_kind": "guangdong_ygp_attachment_list_v1",
        "attachment_items": records,
        "summary": {
            "project_count": len({str(item.get("project_id") or "") for item in records if item.get("project_id")}),
            "flow_item_count": len({str(item.get("attachment_owner_key") or "") for item in records if item.get("attachment_owner_key")}),
            "attachment_count": len(records),
            "download_endpoint_ready_count": sum(1 for item in records if item.get("download_url")),
            "source_full_chain_summary": dict(summary),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_json(out_root / "attachment-list.json", payload)


def _write_human_file_map(*, out_root: Path, project_samples: list[Mapping[str, Any]]) -> None:
    rows = []
    for sample in project_samples:
        for ref in _list(sample.get("detail_snapshot_refs")):
            if isinstance(ref, Mapping):
                rows.append(_human_file_map_row(sample, ref, "detail"))
        for ref in _list(sample.get("attachment_snapshot_refs")):
            if isinstance(ref, Mapping):
                rows.append(_human_file_map_row(sample, ref, "attachment"))
    _write_json(out_root / "human-readable-file-map.json", rows)
    with (out_root / "human-readable-file-map.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["project_id", "project_name", "city_code", "flow_no", "flow_title", "file_role", "human_file_name", "human_readable_path", "source_url", "attachment_url", "snapshot_id", "content_type", "byte_size", "sha256"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _human_file_map_row(sample: Mapping[str, Any], ref: Mapping[str, Any], file_role: str) -> dict[str, Any]:
    return {
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "city_code": str(sample.get("city_code") or ""),
        "flow_no": str(sample.get("guangdong_ygp_flow_no") or ref.get("guangdong_ygp_flow_no") or ""),
        "flow_title": str(sample.get("guangdong_ygp_flow_title") or ref.get("guangdong_ygp_flow_title") or ""),
        "file_role": file_role,
        "human_file_name": str(ref.get("human_file_name") or ""),
        "human_readable_path": str(ref.get("human_readable_path") or ref.get("local_path") or ""),
        "source_url": str(ref.get("source_url") or ""),
        "attachment_url": str(ref.get("attachment_url") or ""),
        "snapshot_id": str(ref.get("snapshot_id") or ""),
        "content_type": str(ref.get("content_type") or ""),
        "byte_size": _int(ref.get("byte_size")),
        "sha256": str(ref.get("sha256") or ""),
    }


def _write_manual_url_check_table(*, out_root: Path, discovery: Mapping[str, Any], flow_matrix: Mapping[str, Any]) -> None:
    rows = []
    for record in _list(_source_manifest(discovery).get("manual_url_check_table")):
        if isinstance(record, Mapping):
            rows.append(dict(record))
    for detail in _list(flow_matrix.get("ygp_detail_readback_records")):
        if isinstance(detail, Mapping):
            rows.append(
                {
                    "check_type": "ygp_flow_detail",
                    "city_code": str(detail.get("site_code") or ""),
                    "flow_no": str(detail.get("flow_no") or ""),
                    "flow_title": str(detail.get("flow_title") or ""),
                    "project_name": str(detail.get("project_name") or ""),
                    "url": str(detail.get("source_url") or ""),
                    "attachment_names": _list(detail.get("attachment_names")),
                    "attachment_items": _attachment_items(detail),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    _write_json(out_root / "manual-url-check-table.json", rows)


def _flow_notice_directory(*, output_root: Path, city_code: str, project_id: str, flow_no: str, flow_title: str, published_date: str, title: str) -> Path:
    date = _date_part(published_date) or "unknown-date"
    flow_hash = _sha256(flow_title or flow_no)[:10]
    title_hash = _sha256(title or project_id)[:10]
    project_segment = _sanitize_path_segment(project_id)
    flow_segment = f"{_flow_no(flow_no)}_{_short_human_segment(flow_title or '流程', max_chars=24)}"
    notice_segment = f"{date}_{title_hash}_{_short_human_segment(title or '公告', max_chars=28)}"
    path = (
        output_root
        / "projects"
        / "CN-GD"
        / _sanitize_path_segment(city_code or "44")
        / project_segment
        / flow_segment
        / notice_segment
    )
    if _path_needs_short_fallback(path, reserve_chars=140):
        path = (
            output_root
            / "projects"
            / "CN-GD"
            / _sanitize_path_segment(city_code or "44")
            / project_segment
            / f"{_flow_no(flow_no)}_{flow_hash}"
            / f"{date}_{title_hash}"
        )
    if _path_needs_short_fallback(path, reserve_chars=80):
        path = (
            output_root
            / "projects"
            / "CN-GD"
            / _sanitize_path_segment(city_code or "44")
            / _short_project_segment(project_id=project_id, city_code=city_code)
            / f"{_flow_no(flow_no)}_{flow_hash}"
            / f"{date}_{title_hash}"
        )
    return path


def _attachment_items(detail: Mapping[str, Any], *, project: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _list(detail.get("attachment_items")):
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        flow_no = _flow_no(detail.get("flow_no"))
        row.update(
            {
                "project_id": str((project or {}).get("project_id") or row.get("project_id") or ""),
                "city_code": str((project or {}).get("city_code") or row.get("city_code") or detail.get("site_code") or ""),
                "project_code": str((project or {}).get("project_code") or row.get("project_code") or detail.get("project_code") or ""),
                "flow_no": flow_no,
                "flow_title": str(detail.get("flow_title") or row.get("flow_title") or ""),
                "detail_url": str(detail.get("detail_url") or detail.get("source_url") or ""),
                "attachment_owner_key": _stable_id(
                    "YGP-ATTACHMENT-OWNER",
                    (project or {}).get("project_id"),
                    (project or {}).get("city_code"),
                    flow_no,
                    detail.get("detail_url") or detail.get("source_url"),
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
        rows.append(row)
    return rows


def _write_attachment_list(
    *,
    source_dir: Path,
    project: Mapping[str, str],
    detail: Mapping[str, Any],
    attachments: list[Mapping[str, Any]],
    created_at: str,
) -> None:
    payload = {
        "manifest_kind": "guangdong_ygp_attachment_list_v1",
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "city_code": project["city_code"],
        "flow_no": _flow_no(detail.get("flow_no")),
        "flow_title": str(detail.get("flow_title") or ""),
        "detail_url": str(detail.get("detail_url") or detail.get("source_url") or ""),
        "attachment_items": [dict(item) for item in attachments],
        "summary": {
            "attachment_count": len(attachments),
            "download_endpoint_ready_count": sum(1 for item in attachments if item.get("download_url")),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_json(source_dir / "attachment-list.json", payload)


def _download_policy(flow_no: str) -> str:
    if flow_no == "08":
        return "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED"
    if flow_no in {"03", "04", "07"}:
        return "DOWNLOAD_REQUIRED"
    return "PAGE_REGISTER_ONLY"


def _download_policy_state(flow_no: str, attempted: int) -> str:
    if flow_no == "08":
        return "FLOW_08_REGISTER_ONLY"
    if attempted > 0:
        return "ATTACHMENT_DOWNLOAD_ATTEMPTED"
    return "DETAIL_REGISTERED"


def _target_execution_state(*, detail_snapshot_refs: list[Mapping[str, Any]], attachment_snapshot_refs: list[Mapping[str, Any]], failure_taxonomy: list[str], page_only: bool, register_only: bool) -> str:
    if page_only:
        return "PAGE_ONLY_REGISTERED" if detail_snapshot_refs else "PAGE_ONLY_DETAIL_BLOCKED"
    if register_only:
        return "REGISTER_ONLY_ATTACHMENT_LISTED" if detail_snapshot_refs else "REGISTER_ONLY_DETAIL_BLOCKED"
    if attachment_snapshot_refs:
        return "SAMPLE_READY"
    if detail_snapshot_refs:
        return "DETAIL_READY_ATTACHMENT_REVIEW_REQUIRED"
    return "BLOCKED"


def _file_like_response(*, content_type: str, data: bytes) -> bool:
    lowered = content_type.lower()
    if any(token in lowered for token in ("pdf", "zip", "doc", "word", "msword", "officedocument", "excel", "spreadsheet", "octet-stream", "rar")):
        return bool(data)
    return data.startswith(b"%PDF") or data.startswith(b"PK\x03\x04") or data.startswith(b"Rar!") or data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _attachment_failure_taxonomy(*, status_code: int, content_type: str, data: bytes, error: str) -> list[str]:
    reasons: list[str] = []
    lowered_error = str(error or "").lower()
    if status_code in {403, 401}:
        reasons.append("ygp_attachment_login_or_permission_required")
    if status_code in {429, 503, 504, 502, 500}:
        reasons.append("ygp_attachment_temporary_unavailable_retry_required")
    if status_code == 0 and error:
        reasons.append("ygp_attachment_transport_error_retry_required")
    if "content_length_exceeds_limit" in lowered_error or "body_exceeds_limit" in lowered_error:
        return [OVERSIZE_POLICY_TAXONOMY]
    if "incompleteread" in lowered_error:
        reasons.append("ygp_attachment_incomplete_read_retry_required")
    text_probe = data[:500].decode("utf-8", errors="replace")
    if status_code == 200 and not data:
        reasons.append("ygp_attachment_empty_response_review")
    if "验证码" in text_probe or "captcha" in text_probe.lower():
        reasons.append("ygp_attachment_captcha_or_challenge_required")
    if "请登录" in text_probe or "登录" in text_probe or "login" in text_probe.lower():
        reasons.append("ygp_attachment_login_or_permission_required")
    if "errcode" in text_probe.lower() or "errmsg" in text_probe.lower():
        reasons.append("ygp_attachment_interface_error")
    if "过期" in text_probe or "expired" in text_probe.lower() or "stale" in text_probe.lower():
        reasons.append("ygp_attachment_interface_expired_or_stale")
    if "文件不存在" in text_probe:
        reasons.append("ygp_attachment_file_not_found_or_expired")
    if not reasons:
        reasons.append("ygp_attachment_not_file_like_response")
    return _dedupe(reasons)


def _content_type_from_file_name(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".zip": "application/zip",
        ".rar": "application/vnd.rar",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(suffix, "application/octet-stream")


def _attachment_role(flow_no: str) -> str:
    return {
        "03": "tender_file",
        "04": "clarification_file",
        "07": "candidate_notice_attachment",
        "08": "bid_file_publicity_attachment",
    }.get(_flow_no(flow_no), "attachment")


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str, *, encoding: str) -> None:
    _ensure_dir(path.parent)
    _fs_path(path).write_text(text, encoding=encoding)


def _write_bytes(path: Path, data: bytes) -> None:
    _ensure_dir(path.parent)
    _fs_path(path).write_bytes(data)


def _ensure_dir(path: Path) -> None:
    _fs_path(path).mkdir(parents=True, exist_ok=True)


def _fs_path(path: Path) -> Path:
    path = Path(path)
    if os.name != "nt":
        return path
    raw = str(path)
    if raw.startswith("\\\\?\\"):
        return path
    absolute = path if path.is_absolute() else Path.cwd() / path
    absolute_text = str(absolute)
    if absolute_text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute_text[2:])
    return Path("\\\\?\\" + absolute_text)


def _scan_forbidden_or_raise(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hits = [term for term in FORBIDDEN_TERMS if term in text]
    if hits:
        raise RuntimeError(f"forbidden_report_terms:{','.join(hits)}")


def _sanitize_path_segment(value: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", str(value or "")).strip(" ._")
    return text[:80] or "unknown"


def _sanitize_file_name(value: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", str(value or "")).strip(" ._")
    return text[:160] or "attachment.bin"


def _short_human_segment(value: str, *, max_chars: int) -> str:
    text = _sanitize_path_segment(value)
    if len(text) <= max_chars:
        return text
    digest = _sha256(text)[:8]
    prefix_budget = max(4, max_chars - len(digest) - 1)
    prefix = text[:prefix_budget].strip(" ._-") or "item"
    return f"{prefix}_{digest}"


def _short_human_file_name(value: str, *, max_chars: int) -> str:
    text = _sanitize_file_name(value)
    if len(text) <= max_chars:
        return text
    suffix = _safe_suffix(text)
    stem = text[: -len(suffix)] if suffix else text
    digest = _sha256(text)[:8]
    stem_budget = max(4, max_chars - len(suffix) - len(digest) - 1)
    short_stem = stem[:stem_budget].strip(" ._-") or "attachment"
    return f"{short_stem}_{digest}{suffix}"


def _short_project_segment(*, project_id: str, city_code: str) -> str:
    digest = _sha256(project_id)[:12]
    city = _sanitize_path_segment(city_code or "44")
    return f"PROJ-CN-GD-{city}-{digest}"


def _safe_suffix(value: str) -> str:
    suffix = Path(_sanitize_file_name(value)).suffix
    if not suffix or len(suffix) > 12:
        return ".bin"
    return suffix


def _attachment_fallback_path(*, attachment_dir: Path, index: int, snapshot_id: str, suffix: str) -> Path:
    return attachment_dir / f"{index:02d}_{_sha256(snapshot_id)[:10]}{suffix or '.bin'}"


def _attachment_meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def _path_needs_short_fallback(path: Path, *, reserve_chars: int = 0) -> bool:
    if os.name != "nt":
        return False
    return len(str(path)) + reserve_chars >= 240


def _date_part(value: str) -> str:
    match = re.search(r"(20\d{2})[-/.年]?(\d{1,2})[-/.月]?(\d{1,2})", str(value or ""))
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _stable_slug(value: str) -> str:
    raw = str(value or "").strip()
    tail = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", raw).strip("-")
    return (tail[-28:] if tail else _sha256(raw)[:12]) or "unknown"


def _flow_no(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits.zfill(2)[-2:] if digits else ""


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        key = str(value).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:16]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Guangdong YGP non-Guangzhou/Shenzhen full-chain verification v1.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--city-code", action="append", default=[])
    parser.add_argument("--per-city-candidate-limit", type=int, default=1)
    parser.add_argument("--max-pages-per-city", type=int, default=5)
    parser.add_argument("--flow-nos", default=",".join(DEFAULT_FLOW_NOS))
    parser.add_argument("--max-attachments-per-flow-item", type=int, default=5)
    parser.add_argument("--max-bid-file-publicity-downloads-per-project", type=int, default=2)
    parser.add_argument("--enable-attachment-challenge-resolver", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--execute-stage4", action="store_true")
    parser.add_argument("--company-first-result-state", default="NOT_RUN")
    parser.add_argument("--name-enumeration-result-state", default="NOT_RUN")
    parser.add_argument("--source-stage4-records-json", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_guangdong_ygp_full_chain(
        output_root=args.output_root,
        city_codes=args.city_code or list(DEFAULT_CITY_CODES),
        per_city_candidate_limit=args.per_city_candidate_limit,
        max_pages_per_city=args.max_pages_per_city,
        flow_nos=[item.strip() for item in args.flow_nos.split(",") if item.strip()],
        max_attachments_per_flow_item=args.max_attachments_per_flow_item,
        max_bid_file_publicity_downloads_per_project=args.max_bid_file_publicity_downloads_per_project,
        enable_attachment_challenge_resolver=args.enable_attachment_challenge_resolver,
        execute=args.execute,
        execute_stage4=args.execute_stage4,
        company_first_result_state=args.company_first_result_state,
        name_enumeration_result_state=args.name_enumeration_result_state,
        source_stage4_records_json=args.source_stage4_records_json or None,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
