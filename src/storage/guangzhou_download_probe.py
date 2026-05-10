from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage2_ingestion.service import Stage2Service
from storage.challenge_stability_report import build_challenge_stability_report
from storage.db import DatabaseSession
from storage.professional_clean_project_archive import build_professional_clean_project_archive_manifest
from storage.repositories.object_storage_repo import ObjectStorageRepository


GUANGZHOU_DOWNLOAD_PROBE_MANIFEST_KIND = "guangzhou_download_probe_manifest"
GUANGZHOU_DOWNLOAD_PROBE_VERSION = 1
GUANGZHOU_DOWNLOAD_PROBE_ADAPTER_ID = "guangzhou-download-probe-v1-runner"
GUANGZHOU_PROFILE_ID = "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
NOT_RUN_PARSE_STATE = "NOT_RUN_DOWNLOAD_PROBE"
PAGE_ONLY_FLOW_NOS = {"05", "06"}
DEFAULT_DOWNLOAD_FLOW_NOS = ("03", "04", "07", "08")


FLOW_TITLES = {
    "01": "招标计划",
    "02": "招标文件公示",
    "03": "招标公告/关联公告",
    "04": "澄清答疑",
    "05": "开标信息",
    "06": "资审结果公示",
    "07": "中标候选人公示",
    "08": "投标(资格预审申请)文件公开",
    "09": "中标结果公示/公告",
    "10": "中标信息",
    "11": "合同信息公开",
    "12": "项目异常",
}


def build_guangzhou_download_probe(
    *,
    input_root: str | Path,
    output_root: str | Path,
    project_ids: list[str] | tuple[str, ...],
    flow_nos: list[str] | tuple[str, ...] = DEFAULT_DOWNLOAD_FLOW_NOS,
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    max_bid_file_publicity_downloads_per_project: int = 2,
    max_attachments_per_flow_item: int = 0,
    use_all_analysis_projects: bool = False,
    execute: bool = False,
    created_at: str | None = None,
    stage2_service: Any | None = None,
    object_repository: Any | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(input_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    storage = Path(storage_path) if storage_path else out_root / "storage.json"
    object_storage = Path(object_storage_path) if object_storage_path else out_root / "objects"
    storage.parent.mkdir(parents=True, exist_ok=True)
    object_storage.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    analysis_payload = _load_json(in_root / "analysis-plan.json", blocking_reasons, "analysis_plan_missing")
    run_payload = _load_json(in_root / "run-manifest.json", blocking_reasons, "run_manifest_missing")
    audit_payload = _load_json(in_root / "project-file-audit.json", [], "project_file_audit_missing")
    analysis_manifest = _source_manifest(analysis_payload)
    run_manifest = _source_manifest(run_payload)
    audit_manifest = _source_manifest(audit_payload)
    selected = _select_strategy_items(
        analysis_manifest=analysis_manifest,
        run_manifest=run_manifest,
        project_ids=[] if use_all_analysis_projects else project_ids,
        flow_nos=flow_nos,
    )
    if not selected and not blocking_reasons:
        blocking_reasons.append("download_probe_no_strategy_items_selected")

    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage),
    )
    repository = object_repository or ObjectStorageRepository(
        session=DatabaseSession(settings=settings),
        settings=settings,
    )
    service = stage2_service or Stage2Service(settings=settings)

    project_bid_publicity_download_counts: dict[str, int] = {}
    flow_items: list[dict[str, Any]] = []
    project_samples: list[dict[str, Any]] = []
    if execute and not blocking_reasons:
        for item in selected:
            result = _execute_probe_item(
                item=item,
                output_root=out_root,
                service=service,
                repository=repository,
                project_bid_publicity_download_counts=project_bid_publicity_download_counts,
                max_bid_file_publicity_downloads_per_project=max(0, max_bid_file_publicity_downloads_per_project),
                max_attachments_per_flow_item=max(0, max_attachments_per_flow_item),
                created_at=created,
            )
            flow_items.append(result["flow_item"])
            project_samples.append(result["project_sample"])
            _write_checkpoint_manifest(
                output_root=out_root,
                input_root=in_root,
                storage=storage,
                object_storage=object_storage,
                project_ids=project_ids,
                use_all_analysis_projects=use_all_analysis_projects,
                flow_nos=flow_nos,
                flow_items=flow_items,
                project_samples=project_samples,
                run_manifest=run_manifest,
                blocking_reasons=blocking_reasons,
                created_at=created,
                checkpoint_state="PARTIAL_RUN_IN_PROGRESS",
            )
    else:
        for item in selected:
            planned = _planned_probe_item(item)
            flow_items.append(planned["flow_item"])
            project_samples.append(planned["project_sample"])

    summary = _summary(
        flow_items=flow_items,
        project_samples=project_samples,
        run_manifest=run_manifest,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GUANGZHOU_DOWNLOAD_PROBE_VERSION,
        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
        "sub_kind": GUANGZHOU_DOWNLOAD_PROBE_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_DOWNLOAD_PROBE_ADAPTER_ID,
        "pipeline_stage": "DownloadProbe",
        "manifest_id": f"GUANGZHOU-DOWNLOAD-PROBE-{_fingerprint({'items': flow_items, 'samples': project_samples})[:16]}",
        "created_at": created,
        "source_input_root": str(in_root),
        "source_analysis_plan_path": str(in_root / "analysis-plan.json"),
        "source_run_manifest_path": str(in_root / "run-manifest.json"),
        "source_project_file_audit_path": str(in_root / "project-file-audit.json"),
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": bool(execute),
        "source_profile_id": GUANGZHOU_PROFILE_ID,
        "project_ids": list(project_ids),
        "use_all_analysis_projects": bool(use_all_analysis_projects),
        "flow_nos": [_flow_no(value) for value in flow_nos],
        "max_attachments_per_flow_item": max(0, max_attachments_per_flow_item),
        "items": flow_items,
        "sample_items": flow_items[:80],
        "project_sample_items": project_samples,
        "project_sample_preview_items": project_samples[:80],
        "summary": summary,
        "safety": {
            "download_enabled": bool(execute),
            "parse_enabled": False,
            "stage3_parse_enabled": False,
            "markitdown_enabled": False,
            "ocr_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_download_probe_mode": "EXECUTED" if execute else "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
        "source_audit_summary": dict(audit_manifest.get("summary") or {}),
        "execution": {
            "executed": bool(execute),
            "download_enabled": bool(execute),
            "parse_enabled": False,
            "storage_path_optional": str(storage),
            "object_storage_path_optional": str(object_storage),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }

    manifest_path = out_root / "download-probe-manifest.json"
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if execute and not blocking_reasons:
        build_professional_clean_project_archive_manifest(
            real_sample_execution_manifest_json=manifest_path,
            output_root=out_root,
            storage_path=storage,
            object_storage_path=object_storage,
            object_repository=repository,
        )
    stability = build_challenge_stability_report(real_sample_execution_manifest_json=manifest_path)
    (out_root / "challenge-stability-report.json").write_text(
        json.dumps(stability, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _write_checkpoint_manifest(
    *,
    output_root: Path,
    input_root: Path,
    storage: Path,
    object_storage: Path,
    project_ids: list[str] | tuple[str, ...],
    use_all_analysis_projects: bool,
    flow_nos: list[str] | tuple[str, ...],
    flow_items: list[Mapping[str, Any]],
    project_samples: list[Mapping[str, Any]],
    run_manifest: Mapping[str, Any],
    blocking_reasons: list[str],
    created_at: str,
    checkpoint_state: str,
) -> None:
    summary = _summary(
        flow_items=flow_items,
        project_samples=project_samples,
        run_manifest=run_manifest,
        blocking_reasons=blocking_reasons,
    )
    payload = {
        "guangzhou_download_probe_mode": checkpoint_state,
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": {
            "manifest_version": GUANGZHOU_DOWNLOAD_PROBE_VERSION,
            "manifest_kind": "evaluation_real_project_sample_execution_manifest",
            "sub_kind": GUANGZHOU_DOWNLOAD_PROBE_MANIFEST_KIND,
            "adapter_id": GUANGZHOU_DOWNLOAD_PROBE_ADAPTER_ID,
            "pipeline_stage": "DownloadProbe",
            "checkpoint_state": checkpoint_state,
            "created_at": created_at,
            "source_input_root": str(input_root),
            "source_analysis_plan_path": str(input_root / "analysis-plan.json"),
            "source_run_manifest_path": str(input_root / "run-manifest.json"),
            "storage_path_optional": str(storage),
            "object_storage_path_optional": str(object_storage),
            "execution_mode": "PARTIAL",
            "execute": True,
            "source_profile_id": GUANGZHOU_PROFILE_ID,
            "project_ids": list(project_ids),
            "use_all_analysis_projects": bool(use_all_analysis_projects),
            "flow_nos": [_flow_no(value) for value in flow_nos],
            "items": list(flow_items),
            "project_sample_items": list(project_samples),
            "summary": summary,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "summary": summary,
    }
    (output_root / "download-probe-manifest.partial.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _execute_probe_item(
    *,
    item: Mapping[str, Any],
    output_root: Path,
    service: Any,
    repository: Any,
    project_bid_publicity_download_counts: dict[str, int],
    max_bid_file_publicity_downloads_per_project: int,
    max_attachments_per_flow_item: int,
    created_at: str,
) -> dict[str, dict[str, Any]]:
    project_id = str(item.get("project_id") or "")
    flow_no = _flow_no(item.get("flow_no"))
    flow_title = str(item.get("flow_title") or FLOW_TITLES.get(flow_no, "流程"))
    source_url = str(item.get("source_url") or "")
    source_title = str(item.get("source_title") or item.get("project_name") or "")
    source_dir = _flow_notice_directory(
        output_root=output_root,
        project_id=project_id,
        flow_no=flow_no,
        flow_title=flow_title,
        published_date=str(item.get("published_date") or ""),
        title=source_title or flow_title,
    )
    for child in ("detail", "attachments", "extracted", "parsed"):
        (source_dir / child).mkdir(parents=True, exist_ok=True)

    failure_taxonomy: list[str] = []
    challenge_diagnostics: list[dict[str, Any]] = []
    detail_snapshot_refs: list[dict[str, Any]] = []
    attachment_snapshot_refs: list[dict[str, Any]] = []
    attachment_link_items: list[dict[str, str]] = []
    attachment_attempts: list[dict[str, Any]] = []
    deferred_attachment_count = 0
    detail_carrier: Mapping[str, Any] = {}

    try:
        detail_carrier = service.fetch_real_public_candidate_detail_url(
            source_url,
            profile_id=GUANGZHOU_PROFILE_ID,
            repository=repository,
            lineage_refs={
                "project_id": project_id,
                "flow_no": flow_no,
                "download_probe": "v1",
            },
            project_id=project_id,
            candidate_id=str(item.get("strategy_item_id") or ""),
        )
    except Exception as exc:  # pragma: no cover - exact boundary exceptions vary by runtime
        failure_taxonomy.append(f"detail_fetch_exception:{type(exc).__name__}")
        detail_carrier = {
            "status": "DEGRADED",
            "degraded_reasons": [str(exc)],
            "failure_taxonomy": [f"detail_fetch_exception:{type(exc).__name__}"],
        }
    failure_taxonomy.extend(_carrier_failure_taxonomy(detail_carrier, prefix="detail"))
    detail_ref = _snapshot_ref_from_carrier(
        carrier=detail_carrier,
        repository=repository,
        source_url=source_url,
        parent_source_url="",
        flow_no=flow_no,
        flow_title=flow_title,
        role="detail",
        parse_state=NOT_RUN_PARSE_STATE,
    )
    if detail_ref:
        detail_snapshot_refs.append(detail_ref)
        _materialize_snapshot(
            ref=detail_ref,
            repository=repository,
            output_dir=source_dir / "detail",
            prefix="detail",
        )
    elif str(detail_carrier.get("snapshot_id_optional") or ""):
        failure_taxonomy.append("detail_snapshot_readback_missing")
    elif str(detail_carrier.get("status") or "") != "FETCHED":
        failure_taxonomy.append("detail_snapshot_not_captured")

    if flow_no in PAGE_ONLY_FLOW_NOS:
        download_policy_state = "PAGE_ONLY_REGISTERED"
    else:
        raw_attachment_link_count = len(list(detail_carrier.get("same_site_attachment_link_items") or []))
        attachment_link_items = _attachment_link_items(detail_carrier)
        download_limit = len(attachment_link_items)
        if flow_no == "08":
            already = project_bid_publicity_download_counts.get(project_id, 0)
            remaining = max(0, max_bid_file_publicity_downloads_per_project - already)
            download_limit = min(len(attachment_link_items), remaining)
        elif max_attachments_per_flow_item > 0:
            download_limit = min(len(attachment_link_items), max_attachments_per_flow_item)
        selected_links = attachment_link_items[:download_limit]
        deferred_attachment_count = max(0, len(attachment_link_items) - len(selected_links))
        if deferred_attachment_count and flow_no != "08":
            failure_taxonomy.append("DEFERRED_BY_DOWNLOAD_REPAIR_LIMIT")
        if flow_no == "08":
            project_bid_publicity_download_counts[project_id] = (
                project_bid_publicity_download_counts.get(project_id, 0) + len(selected_links)
            )
        for index, link in enumerate(selected_links, start=1):
            attempt = _download_attachment(
                link=link,
                source_url=source_url,
                item=item,
                repository=repository,
                service=service,
                flow_no=flow_no,
                flow_title=flow_title,
                source_dir=source_dir,
                index=index,
            )
            if not attempt.get("snapshot_ref") and _should_retry_attachment_attempt(attempt):
                retry_attempt = _retry_attachment_after_detail_refresh(
                    original_link=link,
                    source_url=source_url,
                    item=item,
                    repository=repository,
                    service=service,
                    flow_no=flow_no,
                    flow_title=flow_title,
                    source_dir=source_dir,
                    index=index,
                )
                if retry_attempt:
                    retry_attempt["retry_of_attachment_url"] = attempt.get("attachment_url")
                    if retry_attempt.get("snapshot_ref"):
                        retry_attempt["failure_taxonomy"] = _dedupe_strings(
                            list(retry_attempt.get("failure_taxonomy") or [])
                        )
                    else:
                        retry_attempt["failure_taxonomy"] = _dedupe_strings(
                            [
                                "attachment_retry_after_detail_refresh",
                                *list(retry_attempt.get("failure_taxonomy") or []),
                            ]
                        )
                    attempt = retry_attempt
            attachment_attempts.append(attempt)
            if attempt.get("snapshot_ref"):
                attachment_snapshot_refs.append(dict(attempt["snapshot_ref"]))
            failure_taxonomy.extend(list(attempt.get("failure_taxonomy") or []))
            if attempt.get("challenge_diagnostic"):
                challenge_diagnostics.append(dict(attempt["challenge_diagnostic"]))
        if not attachment_link_items:
            failure_taxonomy.append(
                "attachment_links_rejected_as_non_download_navigation"
                if raw_attachment_link_count
                else "no_public_attachment_link_found"
            )
        download_policy_state = "ATTACHMENT_DOWNLOAD_ATTEMPTED"

    target_execution_state = _target_execution_state(
        detail_snapshot_refs=detail_snapshot_refs,
        attachment_snapshot_refs=attachment_snapshot_refs,
        failure_taxonomy=failure_taxonomy,
        page_only=flow_no in PAGE_ONLY_FLOW_NOS,
    )
    sample = _project_sample(
        item=item,
        target_execution_state=target_execution_state,
        detail_snapshot_refs=detail_snapshot_refs,
        attachment_snapshot_refs=attachment_snapshot_refs,
        challenge_diagnostics=challenge_diagnostics,
        failure_taxonomy=_dedupe_strings(failure_taxonomy),
        attachment_link_items=attachment_link_items,
        download_attempted_count=len(attachment_attempts),
        deferred_attachment_count=deferred_attachment_count,
        source_dir=source_dir,
    )
    flow_item = {
        "download_probe_item_id": f"DOWNLOAD-PROBE-{flow_no}-{_fingerprint({'project': project_id, 'url': source_url})[:12]}",
        "project_id": project_id,
        "project_name": str(item.get("project_name") or ""),
        "flow_no": flow_no,
        "flow_title": flow_title,
        "document_kind": str(item.get("document_kind") or ""),
        "source_url": source_url,
        "published_date": str(item.get("published_date") or ""),
        "download_policy": str(item.get("download_policy") or ""),
        "download_policy_state": download_policy_state,
        "detail_capture_status": str(detail_carrier.get("status") or ""),
        "detail_snapshot_count": len(detail_snapshot_refs),
        "listed_attachment_count": len(attachment_link_items),
        "download_attempted_count": len(attachment_attempts),
        "deferred_attachment_count": deferred_attachment_count,
        "attachment_snapshot_count": len(attachment_snapshot_refs),
        "challenge_diagnostics": challenge_diagnostics,
        "failure_taxonomy": _dedupe_strings(failure_taxonomy),
        "flow_directory": str(source_dir),
        "parse_state": NOT_RUN_PARSE_STATE,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    (source_dir / "download-probe.json").write_text(
        json.dumps({"item": flow_item, "project_sample": sample}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"flow_item": flow_item, "project_sample": sample}


def _download_attachment(
    *,
    link: Mapping[str, Any],
    source_url: str,
    item: Mapping[str, Any],
    repository: Any,
    service: Any,
    flow_no: str,
    flow_title: str,
    source_dir: Path,
    index: int,
) -> dict[str, Any]:
    attachment_url = str(link.get("url") or "").strip()
    link_text = str(link.get("text") or link.get("attachment_link_text") or "")
    failure_taxonomy: list[str] = []
    try:
        carrier = service.fetch_real_public_same_site_attachment_url(
            attachment_url,
            parent_profile_id=GUANGZHOU_PROFILE_ID,
            repository=repository,
            lineage_refs={
                "project_id": str(item.get("project_id") or ""),
                "flow_no": flow_no,
                "download_probe": "v1",
            },
            detail_page_url=source_url,
            project_id=str(item.get("project_id") or ""),
            candidate_id=str(item.get("strategy_item_id") or ""),
        )
    except Exception as exc:  # pragma: no cover - exact boundary exceptions vary by runtime
        carrier = {
            "status": "DEGRADED",
            "attachment_url": attachment_url,
            "attachment_failure_taxonomy": [f"attachment_fetch_exception:{type(exc).__name__}"],
            "degraded_reasons": [str(exc)],
        }
    failure_taxonomy.extend(_carrier_failure_taxonomy(carrier, prefix="attachment"))
    snapshot_ref = _snapshot_ref_from_carrier(
        carrier=carrier,
        repository=repository,
        source_url=attachment_url,
        parent_source_url=source_url,
        flow_no=flow_no,
        flow_title=flow_title,
        role=_attachment_role(flow_no),
        parse_state=NOT_RUN_PARSE_STATE,
        attachment_link_text=link_text,
    )
    local_path = ""
    if snapshot_ref:
        local_path = _materialize_snapshot(
            ref=snapshot_ref,
            repository=repository,
            output_dir=source_dir / "attachments",
            prefix=f"attachment_{index:02d}",
        )
        snapshot_ref["local_path"] = local_path
    elif str(carrier.get("snapshot_id_optional") or ""):
        failure_taxonomy.append("attachment_snapshot_readback_missing")
        failure_taxonomy.append("attachment_snapshot_not_captured")
    elif str(carrier.get("status") or "") != "FETCHED":
        failure_taxonomy.append("attachment_snapshot_not_captured")
    challenge_state = str(carrier.get("automated_challenge_resolution_state") or "")
    challenge_diagnostic = None
    if bool(carrier.get("automated_challenge_resolution_attempted")) or challenge_state:
        challenge_diagnostic = {
            "capture_kind": "attachment",
            "attachment_url": attachment_url,
            "attachment_link_text": link_text,
            "attempted": bool(carrier.get("automated_challenge_resolution_attempted")) or bool(challenge_state),
            "state": challenge_state,
            "blocker_class": str(carrier.get("attachment_blocker_class") or ""),
            "blocker_reason": str(carrier.get("attachment_blocker_reason") or ""),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return {
        "attachment_url": attachment_url,
        "attachment_link_text": link_text,
        "status": str(carrier.get("status") or ""),
        "snapshot_ref": snapshot_ref,
        "local_path": local_path,
        "failure_taxonomy": _dedupe_strings(failure_taxonomy),
        "challenge_diagnostic": challenge_diagnostic,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _should_retry_attachment_attempt(attempt: Mapping[str, Any]) -> bool:
    reasons = {str(reason or "") for reason in list(attempt.get("failure_taxonomy") or [])}
    retry_markers = {
        "attachment_url_expired",
        "attachment_html_blocker:interface_error_or_expired_link",
        "ATTACHMENT_INTERFACE_ERROR",
        "recapture_detail_page_and_refresh_attachment_link",
        "attachment_snapshot_not_captured",
    }
    return bool(reasons & retry_markers)


def _retry_attachment_after_detail_refresh(
    *,
    original_link: Mapping[str, Any],
    source_url: str,
    item: Mapping[str, Any],
    repository: Any,
    service: Any,
    flow_no: str,
    flow_title: str,
    source_dir: Path,
    index: int,
) -> dict[str, Any] | None:
    try:
        refreshed_detail = service.fetch_real_public_candidate_detail_url(
            source_url,
            profile_id=GUANGZHOU_PROFILE_ID,
            repository=repository,
            lineage_refs={
                "project_id": str(item.get("project_id") or ""),
                "flow_no": flow_no,
                "download_probe": "v1",
                "retry_reason": "refresh_attachment_link",
            },
            project_id=str(item.get("project_id") or ""),
            candidate_id=str(item.get("strategy_item_id") or ""),
        )
    except Exception as exc:  # pragma: no cover - exact boundary exceptions vary by runtime
        return {
            "attachment_url": str(original_link.get("url") or ""),
            "attachment_link_text": str(original_link.get("text") or original_link.get("attachment_link_text") or ""),
            "status": "DEGRADED",
            "snapshot_ref": None,
            "local_path": "",
            "failure_taxonomy": [f"attachment_retry_detail_fetch_exception:{type(exc).__name__}"],
            "challenge_diagnostic": None,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    refreshed_links = _attachment_link_items(refreshed_detail)
    retry_link = _select_retry_attachment_link(original_link=original_link, refreshed_links=refreshed_links)
    if not retry_link:
        return {
            "attachment_url": str(original_link.get("url") or ""),
            "attachment_link_text": str(original_link.get("text") or original_link.get("attachment_link_text") or ""),
            "status": str(refreshed_detail.get("status") or "DEGRADED"),
            "snapshot_ref": None,
            "local_path": "",
            "failure_taxonomy": _dedupe_strings(
                [
                    "attachment_retry_no_refreshed_link",
                    *_carrier_failure_taxonomy(refreshed_detail, prefix="detail_retry"),
                ]
            ),
            "challenge_diagnostic": None,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return _download_attachment(
        link=retry_link,
        source_url=source_url,
        item=item,
        repository=repository,
        service=service,
        flow_no=flow_no,
        flow_title=flow_title,
        source_dir=source_dir,
        index=index,
    )


def _select_retry_attachment_link(
    *,
    original_link: Mapping[str, Any],
    refreshed_links: list[dict[str, str]],
) -> dict[str, str] | None:
    if not refreshed_links:
        return None
    original_url = str(original_link.get("url") or "")
    original_text = str(original_link.get("text") or original_link.get("attachment_link_text") or "")
    for link in refreshed_links:
        if original_text and str(link.get("text") or "") == original_text:
            return link
    for link in refreshed_links:
        if original_url and str(link.get("url") or "") == original_url:
            return link
    return refreshed_links[0]


def _planned_probe_item(item: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sample = _project_sample(
        item=item,
        target_execution_state="DOWNLOAD_PROBE_PLANNED",
        detail_snapshot_refs=[],
        attachment_snapshot_refs=[],
        challenge_diagnostics=[],
        failure_taxonomy=[],
        attachment_link_items=[],
        source_dir=Path(""),
    )
    flow_item = {
        "download_probe_item_id": f"DOWNLOAD-PROBE-PLANNED-{_fingerprint(item)[:12]}",
        "project_id": str(item.get("project_id") or ""),
        "project_name": str(item.get("project_name") or ""),
        "flow_no": _flow_no(item.get("flow_no")),
        "flow_title": str(item.get("flow_title") or ""),
        "document_kind": str(item.get("document_kind") or ""),
        "source_url": str(item.get("source_url") or ""),
        "published_date": str(item.get("published_date") or ""),
        "download_policy": str(item.get("download_policy") or ""),
        "download_policy_state": "PLANNED_NOT_EXECUTED",
        "detail_snapshot_count": 0,
        "listed_attachment_count": 0,
        "download_attempted_count": 0,
        "attachment_snapshot_count": 0,
        "failure_taxonomy": [],
        "parse_state": NOT_RUN_PARSE_STATE,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return {"flow_item": flow_item, "project_sample": sample}


def _project_sample(
    *,
    item: Mapping[str, Any],
    target_execution_state: str,
    detail_snapshot_refs: list[dict[str, Any]],
    attachment_snapshot_refs: list[dict[str, Any]],
    challenge_diagnostics: list[dict[str, Any]],
    failure_taxonomy: list[str],
    attachment_link_items: list[dict[str, str]],
    download_attempted_count: int = 0,
    deferred_attachment_count: int = 0,
    source_dir: Path,
) -> dict[str, Any]:
    flow_no = _flow_no(item.get("flow_no"))
    flow_title = str(item.get("flow_title") or FLOW_TITLES.get(flow_no, ""))
    return {
        "target_id": f"DOWNLOAD-PROBE-{flow_no}-{_fingerprint({'project': item.get('project_id'), 'url': item.get('source_url')})[:12]}",
        "parent_target_id": "GUANGZHOU-DOWNLOAD-PROBE-V1",
        "candidate_key": str(item.get("strategy_item_id") or ""),
        "project_id": str(item.get("project_id") or ""),
        "project_name": str(item.get("project_name") or ""),
        "source_url": str(item.get("source_url") or ""),
        "document_kind": str(item.get("document_kind") or ""),
        "jurisdiction": "CN-GD",
        "source_profile_id": GUANGZHOU_PROFILE_ID,
        "target_execution_state": target_execution_state,
        "pipeline_stage": "DownloadProbe",
        "guangzhou_flow_no": flow_no,
        "guangzhou_flow_title": flow_title,
        "guangzhou_flow_folder": str(source_dir) if str(source_dir) != "." else "",
        "published_at_optional": str(item.get("published_date") or ""),
        "download_policy": str(item.get("download_policy") or ""),
        "parse_depth": str(item.get("parse_depth") or ""),
        "detail_capture_status": "FETCHED" if detail_snapshot_refs else "NOT_CAPTURED_OR_NOT_RUN",
        "stage3_parse_state": NOT_RUN_PARSE_STATE,
        "document_completeness_state": "DOWNLOAD_PROBE_CAPTURED" if detail_snapshot_refs else "DOWNLOAD_PROBE_DETAIL_MISSING",
        "notice_version_chain_state": "NOT_EVALUATED_DOWNLOAD_PROBE",
        "detail_snapshot_count": len(detail_snapshot_refs),
        "attachment_snapshot_count": len(attachment_snapshot_refs),
        "listed_attachment_count": len(attachment_link_items),
        "download_attempted_count": max(0, download_attempted_count),
        "deferred_attachment_count": max(0, deferred_attachment_count),
        "detail_snapshot_refs": detail_snapshot_refs,
        "attachment_snapshot_refs": attachment_snapshot_refs,
        "same_site_attachment_link_items": attachment_link_items,
        "challenge_diagnostics": challenge_diagnostics,
        "failure_taxonomy": _dedupe_strings(failure_taxonomy),
        "source_text": "",
        "parse_summary": {
            "stage3_parse_success_count": 0,
            "stage3_parse_failed_count": 0,
            "attachment_missing_review_count": 0 if attachment_snapshot_refs else (1 if attachment_link_items else 0),
            "deferred_attachment_count": max(0, deferred_attachment_count),
            "unknown_attachment_count": 0,
            "text_probe": "",
            "stage3_parse_state": NOT_RUN_PARSE_STATE,
            "document_quality_reasons": _dedupe_strings(failure_taxonomy),
            "download_archive_quality_reasons": [],
            "file_parse_attributions": [],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _snapshot_ref_from_carrier(
    *,
    carrier: Mapping[str, Any],
    repository: Any,
    source_url: str,
    parent_source_url: str,
    flow_no: str,
    flow_title: str,
    role: str,
    parse_state: str,
    attachment_link_text: str = "",
) -> dict[str, Any] | None:
    snapshot_id = str(carrier.get("snapshot_id_optional") or "")
    if not snapshot_id:
        return None
    readback = repository.replay_snapshot(snapshot_id)
    if not bool(readback.get("replayable")):
        return None
    ref = {
        "snapshot_id": snapshot_id,
        "source_url": source_url,
        "parent_source_url": parent_source_url,
        "parse_state": parse_state,
        "guangzhou_flow_no": flow_no,
        "guangzhou_flow_title": flow_title,
        "attachment_role_type": role,
        "attachment_link_text": attachment_link_text,
        "content_type": str(readback.get("content_type") or carrier.get("content_type") or ""),
        "byte_size": _int(readback.get("byte_size") or carrier.get("byte_size")),
        "sha256": str(readback.get("sha256") or carrier.get("sha256") or ""),
        "readback_state": str(readback.get("readback_state") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if role != "detail":
        ref["attachment_url"] = source_url
    return ref


def _materialize_snapshot(*, ref: Mapping[str, Any], repository: Any, output_dir: Path, prefix: str) -> str:
    snapshot_id = str(ref.get("snapshot_id") or "")
    readback = repository.replay_snapshot(snapshot_id)
    if not bool(readback.get("replayable")):
        return ""
    output_dir.mkdir(parents=True, exist_ok=True)
    source_url = str(ref.get("source_url") or ref.get("attachment_url") or "")
    extension = _extension_for(source_url=source_url, content_type=str(readback.get("content_type") or ""))
    file_name = f"{_safe_path_part(prefix)}_{_safe_path_part(snapshot_id[-12:])}{extension}"
    path = output_dir / file_name
    try:
        path.write_bytes(readback.get("bytes") or b"")
    except OSError:
        return ""
    meta = {
        "snapshot_id": snapshot_id,
        "source_url": source_url,
        "content_type": str(readback.get("content_type") or ""),
        "byte_size": _int(readback.get("byte_size")),
        "sha256": str(readback.get("sha256") or ""),
        "readback_state": str(readback.get("readback_state") or ""),
        "file_path": str(path),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    try:
        path.with_suffix(path.suffix + ".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return str(path)


def _select_strategy_items(
    *,
    analysis_manifest: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
    project_ids: list[str] | tuple[str, ...],
    flow_nos: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    requested_flow_nos = {_flow_no(value) for value in flow_nos if _flow_no(value)}
    run_lookup = _run_sample_lookup(run_manifest)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in list(analysis_manifest.get("items") or []):
        if not isinstance(item, Mapping):
            continue
        project_id = str(item.get("project_id") or "")
        flow_no = _flow_no(item.get("flow_no"))
        source_url = str(item.get("source_url") or "")
        if requested_flow_nos and flow_no not in requested_flow_nos:
            continue
        if not _project_requested(project_id, project_ids):
            continue
        if bool(item.get("adapter_validation_only")):
            continue
        if str(item.get("download_policy") or "") == "SKIP":
            continue
        if not source_url:
            continue
        key = (project_id, flow_no, source_url)
        if key in seen:
            continue
        seen.add(key)
        row = dict(item)
        sample = run_lookup.get(key)
        if sample:
            row["source_title"] = str(sample.get("project_name") or row.get("project_name") or "")
            row["published_date"] = str(row.get("published_date") or _published_date(sample) or "")
            row["source_project_code"] = str(sample.get("source_project_code") or "")
            row["project_match_key"] = str(sample.get("project_match_key") or "")
            row["guangzhou_flow_code"] = str(sample.get("guangzhou_flow_code") or "")
        out.append(row)
    return out


def _run_sample_lookup(run_manifest: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    lookup: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for sample in list(run_manifest.get("project_sample_items") or []):
        if not isinstance(sample, Mapping):
            continue
        key = (
            str(sample.get("project_id") or ""),
            _flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no")),
            str(sample.get("source_url") or ""),
        )
        lookup[key] = sample
    return lookup


def _attachment_link_items(carrier: Mapping[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in list(carrier.get("same_site_attachment_link_items") or []):
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        if not _looks_like_download_attachment_url(url, text=str(item.get("text") or "")):
            continue
        seen.add(url)
        out.append({"url": url, "text": str(item.get("text") or "")})
    return out


def _looks_like_download_attachment_url(url: str, *, text: str = "") -> bool:
    parsed = urlsplit(str(url or ""))
    lowered_path = parsed.path.lower()
    lowered_url = str(url or "").lower()
    lowered_text = str(text or "").lower()
    if "downloadztbattach" in lowered_url or "ztbattachdownloadaction" in lowered_url:
        return True
    if re.search(r"\.(pdf|docx?|xlsx?|zip|rar)(?:$|[?#])", lowered_url, flags=re.IGNORECASE):
        return True
    if re.search(r"\.(pdf|docx?|xlsx?|zip|rar)$", lowered_text, flags=re.IGNORECASE):
        return True
    if lowered_path.endswith((".html", ".htm", ".shtml")):
        return False
    if "download" in lowered_url and any(token in lowered_url for token in ("attach", "file", "guid", "code")):
        return True
    return False


def _attachment_role(flow_no: str) -> str:
    return {
        "03": "TENDER_FILE",
        "04": "CLARIFICATION_OR_ADDENDUM",
        "07": "CANDIDATE_NOTICE_ATTACHMENT",
        "08": "BID_FILE_PUBLICITY_SAMPLE",
    }.get(flow_no, "FLOW_ATTACHMENT")


def _target_execution_state(
    *,
    detail_snapshot_refs: list[Mapping[str, Any]],
    attachment_snapshot_refs: list[Mapping[str, Any]],
    failure_taxonomy: list[str],
    page_only: bool,
) -> str:
    if not detail_snapshot_refs:
        return "DOWNLOAD_PROBE_DETAIL_FAILED"
    if page_only:
        return "DOWNLOAD_PROBE_DETAIL_REGISTERED"
    if attachment_snapshot_refs:
        return "DOWNLOAD_PROBE_CAPTURED"
    if failure_taxonomy:
        return "DOWNLOAD_PROBE_PARTIAL_REVIEW"
    return "DOWNLOAD_PROBE_NO_ATTACHMENT"


def _carrier_failure_taxonomy(carrier: Mapping[str, Any], *, prefix: str) -> list[str]:
    reasons: list[str] = []
    for key in ("failure_taxonomy", "attachment_failure_taxonomy", "degraded_reasons"):
        for value in list(carrier.get(key) or []):
            text = str(value or "").strip()
            if text:
                reasons.append(text)
    for key in ("attachment_blocker_class", "attachment_blocker_reason", "attachment_resolution_route"):
        text = str(carrier.get(key) or "").strip()
        if text:
            reasons.append(text)
    if str(carrier.get("status") or "") == "DEGRADED":
        reasons.append(f"{prefix}_degraded")
    return _dedupe_strings(reasons)


def _summary(
    *,
    flow_items: list[Mapping[str, Any]],
    project_samples: list[Mapping[str, Any]],
    run_manifest: Mapping[str, Any],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    download_attempted_count = sum(_int(item.get("download_attempted_count")) for item in flow_items)
    attachment_snapshot_count = sum(_int(item.get("attachment_snapshot_count")) for item in project_samples)
    flowurl_project_count = len(
        {
            str(item.get("project_id") or "")
            for item in list(run_manifest.get("project_sample_items") or [])
            if isinstance(item, Mapping) and item.get("project_id")
        }
    )
    download_probe_project_count = len({str(item.get("project_id") or "") for item in project_samples if item.get("project_id")})
    return {
        "download_probe_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "flow_item_count": len(flow_items),
        "project_sample_count": len(project_samples),
        "unique_project_count": download_probe_project_count,
        "flowurl_project_count": flowurl_project_count,
        "download_probe_project_count": download_probe_project_count,
        "detail_snapshot_count": sum(_int(item.get("detail_snapshot_count")) for item in project_samples),
        "attachment_snapshot_count": attachment_snapshot_count,
        "listed_attachment_count": sum(_int(item.get("listed_attachment_count")) for item in flow_items),
        "download_attempted_count": download_attempted_count,
        "attachment_snapshot_success_rate": _rate(attachment_snapshot_count, download_attempted_count),
        "flow_no_counts": _counts(str(item.get("flow_no") or "") for item in flow_items),
        "flow_no_failure_taxonomy_counts": _flow_no_failure_taxonomy_counts(flow_items, project_samples),
        "target_execution_state_counts": _counts(str(item.get("target_execution_state") or "") for item in project_samples),
        "failure_taxonomy_counts": _counts(
            reason
            for item in [*flow_items, *project_samples]
            for reason in list(item.get("failure_taxonomy") or [])
        ),
        "project_flow_repair_items": _project_flow_repair_items(flow_items, project_samples),
        "parse_state_counts": _counts(str(item.get("stage3_parse_state") or item.get("parse_state") or "") for item in project_samples),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_no_failure_taxonomy_counts(
    flow_items: list[Mapping[str, Any]],
    project_samples: list[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for item in [*flow_items, *project_samples]:
        flow_no = _flow_no(item.get("flow_no") or item.get("guangzhou_flow_no"))
        if not flow_no:
            continue
        bucket = result.setdefault(flow_no, {})
        for reason in list(item.get("failure_taxonomy") or []):
            text = str(reason or "").strip()
            if text:
                bucket[text] = bucket.get(text, 0) + 1
    return {key: dict(sorted(value.items())) for key, value in sorted(result.items())}


def _project_flow_repair_items(
    flow_items: list[Mapping[str, Any]],
    project_samples: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    flow_lookup = {
        (str(item.get("project_id") or ""), _flow_no(item.get("flow_no")), str(item.get("source_url") or "")): item
        for item in flow_items
    }
    for sample in project_samples:
        key = (
            str(sample.get("project_id") or ""),
            _flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no")),
            str(sample.get("source_url") or ""),
        )
        flow_item = flow_lookup.get(key, {})
        failure_taxonomy = _dedupe_strings(
            [
                *list(flow_item.get("failure_taxonomy") or []),
                *list(sample.get("failure_taxonomy") or []),
            ]
        )
        if not failure_taxonomy and _int(sample.get("attachment_snapshot_count")) > 0:
            continue
        rows.append(
            {
                "project_id": key[0],
                "project_name": str(sample.get("project_name") or flow_item.get("project_name") or ""),
                "flow_no": key[1],
                "flow_title": str(sample.get("guangzhou_flow_title") or flow_item.get("flow_title") or ""),
                "source_url": key[2],
                "target_execution_state": str(sample.get("target_execution_state") or ""),
                "listed_attachment_count": _int(flow_item.get("listed_attachment_count")),
                "download_attempted_count": _int(flow_item.get("download_attempted_count")),
                "attachment_snapshot_count": _int(sample.get("attachment_snapshot_count")),
                "failure_taxonomy": failure_taxonomy,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _flow_notice_directory(
    *,
    output_root: Path,
    project_id: str,
    flow_no: str,
    flow_title: str,
    published_date: str,
    title: str,
) -> Path:
    date_part = _safe_path_part(published_date[:10] if published_date else "NO_DATE")
    title_part = _safe_path_part(title)[:18] or "流程页面"
    title_hash = _fingerprint({"title": title})[:8]
    flow_part = _safe_path_part(f"{flow_no}_{flow_title}")[:18]
    return (
        output_root
        / "projects"
        / "CN-GD"
        / _safe_path_part(project_id)
        / flow_part
        / _safe_path_part(f"{date_part}_{title_hash}_{title_part}")
    )


def _extension_for(*, source_url: str, content_type: str) -> str:
    suffix = Path(urlsplit(source_url).path).suffix.lower()
    if suffix in {".html", ".htm", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"}:
        return suffix
    normalized = content_type.lower()
    if "html" in normalized:
        return ".html"
    if "pdf" in normalized:
        return ".pdf"
    if "word" in normalized:
        return ".docx"
    if "spreadsheet" in normalized or "excel" in normalized:
        return ".xlsx"
    if "zip" in normalized:
        return ".zip"
    return ".bin"


def _project_requested(project_id: str, requested: list[str] | tuple[str, ...]) -> bool:
    if not requested:
        return True
    aliases = {_normalize_project_token(value) for value in requested if _normalize_project_token(value)}
    project_aliases = {
        _normalize_project_token(project_id),
        _normalize_project_token(_extract_project_code(project_id)),
    }
    return bool(aliases & project_aliases)


def _normalize_project_token(value: Any) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    code = _extract_project_code(text)
    return code or text


def _extract_project_code(value: Any) -> str:
    match = re.search(r"JG\d{4}-\d+", str(value or "").upper())
    return match.group(0) if match else ""


def _published_date(item: Mapping[str, Any]) -> str:
    for key in ("published_date", "published_at_optional", "published_at", "parent_published_at"):
        value = str(item.get(key) or "")
        if len(value) >= 10:
            return value[:10]
    return ""


def _flow_no(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(2) if text else ""


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
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou DownloadProbe v1.")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--flow-nos", default=",".join(DEFAULT_DOWNLOAD_FLOW_NOS))
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--max-bid-file-publicity-downloads-per-project", type=int, default=2)
    parser.add_argument("--max-attachments-per-flow-item", type=int, default=0)
    parser.add_argument("--use-all-analysis-projects", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_download_probe(
        input_root=args.input_root,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        flow_nos=_parse_csv(args.flow_nos),
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
        max_bid_file_publicity_downloads_per_project=args.max_bid_file_publicity_downloads_per_project,
        max_attachments_per_flow_item=args.max_attachments_per_flow_item,
        use_all_analysis_projects=args.use_all_analysis_projects,
        execute=args.execute,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "download-probe-manifest.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "guangzhou download probe "
            f"{result['guangzhou_download_probe_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GUANGZHOU_DOWNLOAD_PROBE_MANIFEST_KIND",
    "NOT_RUN_PARSE_STATE",
    "build_guangzhou_download_probe",
]
