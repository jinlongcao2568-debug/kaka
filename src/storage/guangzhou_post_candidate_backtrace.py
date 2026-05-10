from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage1_tasking.real_candidate_discovery import (
    RealPublicCandidateDiscoveryService,
    RealPublicCandidateRepository,
    _discover_profile_api_link_items,
)
from stage1_tasking.region_adapters import resolve_source_quality_policy
from stage2_ingestion.real_public_url_fetcher import RealPublicEntryFetcher
from storage.db import DatabaseSession
from storage.evaluation_corpus import default_evaluation_seed_path
from storage.evaluation_real_sample_execution import build_evaluation_real_sample_execution
from storage.evaluation_real_sample_plan import PLAN_READY, build_evaluation_real_sample_plan
from storage.evaluation_real_sample_plan import default_evaluation_real_project_sample_targets_path
from storage.professional_clean_project_archive import build_professional_clean_project_archive_manifest
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.repositories.operator_action_repo import OperatorActionRepository


GUANGZHOU_POST_CANDIDATE_BACKTRACE_MANIFEST_KIND = "guangzhou_post_candidate_backtrace_manifest"
GUANGZHOU_POST_CANDIDATE_BACKTRACE_VERSION = 1
GUANGZHOU_POST_CANDIDATE_BACKTRACE_ADAPTER_ID = "guangzhou-post-candidate-backtrace-v1-runner"

GUANGZHOU_PROFILE_ID = "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
PIPELINE_STAGE_FLOW_URL_ONLY = "FlowUrlOnly"
PIPELINE_STAGE_ATTACHMENT_LIST = "AttachmentList"
PIPELINE_STAGE_DOWNLOAD = "Download"
PIPELINE_STAGE_PARSE = "Parse"
PIPELINE_STAGE_FULL = "Full"
PIPELINE_STAGES = {
    PIPELINE_STAGE_FLOW_URL_ONLY.lower(): PIPELINE_STAGE_FLOW_URL_ONLY,
    PIPELINE_STAGE_ATTACHMENT_LIST.lower(): PIPELINE_STAGE_ATTACHMENT_LIST,
    PIPELINE_STAGE_DOWNLOAD.lower(): PIPELINE_STAGE_DOWNLOAD,
    PIPELINE_STAGE_PARSE.lower(): PIPELINE_STAGE_PARSE,
    PIPELINE_STAGE_FULL.lower(): PIPELINE_STAGE_FULL,
}
FLOW_URL_DISCOVERED = "FLOW_URL_DISCOVERED"
ATTACHMENT_LISTED = "ATTACHMENT_LISTED"
PARTIAL_RUN_INTERRUPTED = "PARTIAL_RUN_INTERRUPTED"
FAILED_RETRYABLE = "FAILED_RETRYABLE"
FAILED_FINAL = "FAILED_FINAL"
NO_PUBLIC_ATTACHMENT = "NO_PUBLIC_ATTACHMENT"
STATIC_ATTACHMENT_LINK_FOUND = "STATIC_ATTACHMENT_LINK_FOUND"
SCRIPT_DOWNLOAD_ENDPOINT_FOUND = "SCRIPT_DOWNLOAD_ENDPOINT_FOUND"
CLICK_DOWNLOAD_ENDPOINT_FOUND = "CLICK_DOWNLOAD_ENDPOINT_FOUND"
EPOINT_CHALLENGE_REQUIRED = "EPOINT_CHALLENGE_REQUIRED"
LOGIN_OR_CA_REQUIRED = "LOGIN_OR_CA_REQUIRED"
INTERFACE_UNRESOLVED = "INTERFACE_UNRESOLVED"
FLOW_SAMPLE_NOT_FOUND = "FLOW_SAMPLE_NOT_FOUND"
OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND = "OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND"
ENTRY_TARGET_IDS = ("REAL-GD-CANDIDATE-001", "REAL-GD-AWARD-001")
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
GUANGZHOU_HUMAN_PROVIDED_FLOW_SEEDS = (
    {
        "flow_no": "02",
        "flow_code": "17",
        "flow_title": "招标文件公示",
        "document_kind": "tender_file_publicity",
        "project_id": "PROJ-CN-GD-0020010071061283",
        "project_name": "广州新机场航站楼施工监理招标文件公示",
        "source_url": "https://ywtb.gzggzy.cn/jyfw/002001/002001008/20251121/0020010071061283.html",
        "published_at_optional": "2025-11-21 17:18",
        "source_record_id": "0020010071061283",
        "sample_source_type": "HUMAN_PROVIDED_FLOW_SEED",
        "seed_evidence": "human_confirmed_independent_flow_02_page",
    },
)
CORE_BACKTRACE_DOCUMENT_KINDS = tuple(str(module["document_kind"]) for module in GUANGZHOU_FLOW_MODULES)


def build_guangzhou_post_candidate_backtrace(
    *,
    output_root: str | Path,
    targets_json: str | Path | None = None,
    seed_json: str | Path | None = None,
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    target_backend: str = "json-file",
    execute: bool = False,
    per_target_candidate_limit: int = 3,
    pipeline_stage: str = PIPELINE_STAGE_FULL,
    resume: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    storage = Path(storage_path) if storage_path else root / "storage.json"
    object_storage = Path(object_storage_path) if object_storage_path else root / "objects"
    storage.parent.mkdir(parents=True, exist_ok=True)
    object_storage.mkdir(parents=True, exist_ok=True)
    seed_path = Path(seed_json) if seed_json else default_evaluation_seed_path()
    base_targets_path = Path(targets_json) if targets_json else default_evaluation_real_project_sample_targets_path()
    resolved_pipeline_stage = _normalize_pipeline_stage(pipeline_stage)
    if resolved_pipeline_stage == PIPELINE_STAGE_FLOW_URL_ONLY:
        resumed = _maybe_resume_flow_url_manifest(
            root=root,
            per_target_candidate_limit=per_target_candidate_limit,
            created_at=created,
            resume=resume,
        )
        if resumed:
            return resumed
        return _build_guangzhou_flow_url_only_backtrace(
            root=root,
            base_targets_path=base_targets_path,
            seed_path=seed_path,
            storage=storage,
            object_storage=object_storage,
            target_backend=target_backend,
            execute=execute,
            per_target_candidate_limit=per_target_candidate_limit,
            created=created,
            resume=resume,
        )
    if resolved_pipeline_stage == PIPELINE_STAGE_ATTACHMENT_LIST:
        resumed = _maybe_resume_interface_coverage_manifest(
            root=root,
            created_at=created,
            resume=resume,
        )
        if resumed:
            return resumed
        return _build_guangzhou_attachment_list_interface_coverage(
            root=root,
            seed_path=seed_path,
            storage=storage,
            object_storage=object_storage,
            target_backend=target_backend,
            execute=execute,
            per_flow_candidate_limit=per_target_candidate_limit,
            created=created,
            resume=resume,
        )
    entry_targets_path = _entry_targets_with_candidate_limit(
        base_targets_path=base_targets_path,
        output_root=root,
        per_target_candidate_limit=per_target_candidate_limit,
    )

    entry_result = build_evaluation_real_sample_execution(
        targets_json=entry_targets_path,
        seed_json=seed_path,
        target_backend=target_backend,
        storage_path=storage,
        object_storage_path=object_storage,
        execute=execute,
        target_ids=list(ENTRY_TARGET_IDS),
        per_target_candidate_limit=max(1, per_target_candidate_limit),
        professional_source_only=True,
        created_at=created,
    )
    entry_manifest = _source_manifest(entry_result)
    entry_samples = _project_samples(entry_manifest)
    selected_entries = _select_post_candidate_entries(entry_samples, limit=per_target_candidate_limit)
    backtrace_targets = _backtrace_targets_for_entries(selected_entries)
    backtrace_targets_path = root / "backtrace-targets.json"
    backtrace_targets_path.write_text(
        json.dumps(backtrace_targets, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    backtrace_result: dict[str, Any] = {
        "real_sample_execution_mode": "SKIPPED",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": {
            "items": [],
            "project_sample_items": [],
            "summary": {},
        },
        "summary": {},
    }
    if backtrace_targets["targets"]:
        backtrace_result = build_evaluation_real_sample_execution(
            targets_json=backtrace_targets_path,
            seed_json=seed_path,
            target_backend=target_backend,
            storage_path=storage,
            object_storage_path=object_storage,
            execute=execute,
            target_ids=[str(item.get("target_id") or "") for item in backtrace_targets["targets"]],
            per_target_candidate_limit=max(5, per_target_candidate_limit),
            professional_source_only=True,
            created_at=created,
        )
    backtrace_manifest = _source_manifest(backtrace_result)

    selected_project_keys = {_project_match_key(entry) for entry in selected_entries if _project_match_key(entry)}
    selected_entry_samples = [
        sample
        for sample in _project_samples(entry_manifest)
        if _project_match_key(sample) in selected_project_keys
    ]
    raw_project_samples = [
        *selected_entry_samples,
        *_project_samples(backtrace_manifest),
    ]
    items = [
        *_target_items(entry_manifest),
        *_target_items(backtrace_manifest),
    ]
    project_samples = _annotate_project_samples(raw_project_samples, target_items=items)
    summary = _summary(project_samples=project_samples, items=items, selected_entries=selected_entries)
    manifest = {
        "manifest_version": GUANGZHOU_POST_CANDIDATE_BACKTRACE_VERSION,
        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
        "sub_kind": GUANGZHOU_POST_CANDIDATE_BACKTRACE_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_POST_CANDIDATE_BACKTRACE_ADAPTER_ID,
        "pipeline_stage": resolved_pipeline_stage,
        "resume_enabled": bool(resume),
        "manifest_id": f"GUANGZHOU-POST-CANDIDATE-BACKTRACE-{_fingerprint({'samples': project_samples, 'items': items})[:16]}",
        "created_at": created,
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "target_storage_backend": target_backend,
        "source_profile_id": GUANGZHOU_PROFILE_ID,
        "entry_target_ids": list(ENTRY_TARGET_IDS),
        "selected_post_candidate_entry_count": len(selected_entries),
        "backtrace_targets_json": str(backtrace_targets_path),
        "items": items,
        "sample_items": items[:80],
        "project_sample_items": project_samples,
        "project_sample_preview_items": project_samples[:80],
        "summary": summary,
        "coverage_quality_summary": {
            "coverage_quality_state": _coverage_state(project_samples),
            "failure_taxonomy_counts": _counts(
                reason
                for sample in project_samples
                for reason in list(sample.get("failure_taxonomy") or [])
            ),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "external_service_connection_enabled": execute,
            "download_enabled": execute,
            "fetch_public_urls_enabled": execute,
            "login_required_fetch_enabled": False,
            "ca_certificate_required_fetch_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_post_candidate_backtrace_mode": "EXECUTED" if execute else "DRY_RUN",
        "pipeline_stage": resolved_pipeline_stage,
        "resume_enabled": bool(resume),
        "real_sample_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": bool(entry_result.get("safe_to_execute")) and bool(backtrace_result.get("safe_to_execute")),
        "blocking_reasons": _dedupe_strings(
            [
                *list(entry_result.get("blocking_reasons") or []),
                *list(backtrace_result.get("blocking_reasons") or []),
            ]
        ),
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": execute,
            "download_enabled": execute,
            "fetch_public_urls_enabled": execute,
            "storage_path_optional": str(storage),
            "object_storage_path_optional": str(object_storage),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }

    run_manifest_path = root / "run-manifest.json"
    run_manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    build_professional_clean_project_archive_manifest(
        real_sample_execution_manifest_json=run_manifest_path,
        output_root=root,
        storage_path=storage,
        object_storage_path=object_storage,
    )
    return result


def _build_guangzhou_flow_url_only_backtrace(
    *,
    root: Path,
    base_targets_path: Path,
    seed_path: Path,
    storage: Path,
    object_storage: Path,
    target_backend: str,
    execute: bool,
    per_target_candidate_limit: int,
    created: str,
    resume: bool,
) -> dict[str, Any]:
    entry_targets_path = _entry_targets_with_candidate_limit(
        base_targets_path=base_targets_path,
        output_root=root,
        per_target_candidate_limit=per_target_candidate_limit,
    )
    entry_items = _discover_flow_url_target_items(
        targets_json=entry_targets_path,
        seed_json=seed_path,
        storage_path=storage,
        object_storage_path=object_storage,
        target_backend=target_backend,
        target_ids=list(ENTRY_TARGET_IDS),
        execute=execute,
        per_target_candidate_limit=per_target_candidate_limit,
        created_at=created,
    )
    entry_manifest = {"items": entry_items, "project_sample_items": _flatten_project_samples(entry_items)}
    selected_entries = _select_post_candidate_entries(
        _project_samples(entry_manifest),
        limit=per_target_candidate_limit,
    )
    backtrace_targets = _backtrace_targets_for_entries(selected_entries)
    backtrace_targets_path = root / "backtrace-targets.json"
    backtrace_targets_path.write_text(
        json.dumps(backtrace_targets, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    backtrace_items = _discover_flow_url_target_items(
        targets_json=backtrace_targets_path,
        seed_json=seed_path,
        storage_path=storage,
        object_storage_path=object_storage,
        target_backend=target_backend,
        target_ids=[str(item.get("target_id") or "") for item in backtrace_targets["targets"]],
        execute=execute,
        per_target_candidate_limit=max(5, per_target_candidate_limit),
        created_at=created,
    ) if backtrace_targets["targets"] else []
    backtrace_manifest = {
        "items": backtrace_items,
        "project_sample_items": _flatten_project_samples(backtrace_items),
    }

    selected_project_keys = {_project_match_key(entry) for entry in selected_entries if _project_match_key(entry)}
    selected_entry_samples = [
        sample
        for sample in _project_samples(entry_manifest)
        if _project_match_key(sample) in selected_project_keys
    ]
    raw_project_samples = [
        *selected_entry_samples,
        *_project_samples(backtrace_manifest),
    ]
    items = [*entry_items, *backtrace_items]
    project_samples = _annotate_project_samples(raw_project_samples, target_items=items)
    summary = _summary(project_samples=project_samples, items=items, selected_entries=selected_entries)
    summary["pipeline_stage"] = PIPELINE_STAGE_FLOW_URL_ONLY
    summary["download_enabled"] = False
    summary["parse_enabled"] = False
    manifest = {
        "manifest_version": GUANGZHOU_POST_CANDIDATE_BACKTRACE_VERSION,
        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
        "sub_kind": GUANGZHOU_POST_CANDIDATE_BACKTRACE_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_POST_CANDIDATE_BACKTRACE_ADAPTER_ID,
        "pipeline_stage": PIPELINE_STAGE_FLOW_URL_ONLY,
        "resume_enabled": bool(resume),
        "manifest_id": f"GUANGZHOU-FLOW-URL-ONLY-{_fingerprint({'samples': project_samples, 'items': items})[:16]}",
        "created_at": created,
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "target_storage_backend": target_backend,
        "source_profile_id": GUANGZHOU_PROFILE_ID,
        "entry_target_ids": list(ENTRY_TARGET_IDS),
        "selected_post_candidate_entry_count": len(selected_entries),
        "backtrace_targets_json": str(backtrace_targets_path),
        "items": items,
        "sample_items": items[:80],
        "project_sample_items": project_samples,
        "project_sample_preview_items": project_samples[:80],
        "summary": summary,
        "coverage_quality_summary": {
            "coverage_quality_state": "FLOW_URL_ONLY_NO_SNAPSHOT_CAPTURE",
            "failure_taxonomy_counts": _counts(
                reason
                for sample in project_samples
                for reason in list(sample.get("failure_taxonomy") or [])
            ),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "external_service_connection_enabled": execute,
            "download_enabled": False,
            "fetch_public_urls_enabled": execute,
            "login_required_fetch_enabled": False,
            "ca_certificate_required_fetch_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_post_candidate_backtrace_mode": "FLOW_URL_ONLY_EXECUTED" if execute else "FLOW_URL_ONLY_DRY_RUN",
        "pipeline_stage": PIPELINE_STAGE_FLOW_URL_ONLY,
        "resume_enabled": bool(resume),
        "real_sample_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": execute,
            "download_enabled": False,
            "parse_enabled": False,
            "fetch_public_urls_enabled": execute,
            "storage_path_optional": str(storage),
            "object_storage_path_optional": str(object_storage),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    run_manifest_path = root / "run-manifest.json"
    run_manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_result = build_professional_clean_project_archive_manifest(
        real_sample_execution_manifest_json=run_manifest_path,
        output_root=root,
        storage_path=storage,
        object_storage_path=object_storage,
    )
    flow_url_manifest = _build_flow_url_manifest(
        project_samples=project_samples,
        archive_manifest=(archive_result.get("manifest") or {}),
        created_at=created,
        output_root=root,
        per_target_candidate_limit=per_target_candidate_limit,
    )
    pipeline_state = _build_pipeline_state_manifest(
        project_samples=project_samples,
        items=items,
        created_at=created,
        pipeline_stage=PIPELINE_STAGE_FLOW_URL_ONLY,
    )
    manual_table = _build_manual_url_check_table(flow_url_manifest)
    (root / "flow-url-manifest.json").write_text(
        json.dumps(flow_url_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "pipeline-state.json").write_text(
        json.dumps(pipeline_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "manual-url-check-table.json").write_text(
        json.dumps(manual_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _build_guangzhou_attachment_list_interface_coverage(
    *,
    root: Path,
    seed_path: Path,
    storage: Path,
    object_storage: Path,
    target_backend: str,
    execute: bool,
    per_flow_candidate_limit: int,
    created: str,
    resume: bool,
) -> dict[str, Any]:
    targets_path = _guangzhou_flow_interface_targets(
        output_root=root,
        per_flow_candidate_limit=per_flow_candidate_limit,
    )
    target_ids = [
        f"GZ-FLOW-INTERFACE-{module['flow_no']}-{_document_kind_suffix(str(module['document_kind']))}"
        for module in GUANGZHOU_FLOW_MODULES
    ]
    items = _discover_flow_url_target_items(
        targets_json=targets_path,
        seed_json=seed_path,
        storage_path=storage,
        object_storage_path=object_storage,
        target_backend=target_backend,
        target_ids=target_ids,
        execute=execute,
        per_target_candidate_limit=per_flow_candidate_limit,
        created_at=created,
        pipeline_stage=PIPELINE_STAGE_ATTACHMENT_LIST,
    )
    project_samples = _annotate_project_samples(_flatten_project_samples(items), target_items=items)
    interface_report = _build_flow_interface_coverage_manifest(
        items=items,
        project_samples=project_samples,
        execute=execute,
        per_flow_candidate_limit=per_flow_candidate_limit,
        created_at=created,
        output_root=root,
    )
    pipeline_state = _build_pipeline_state_manifest(
        project_samples=project_samples,
        items=items,
        created_at=created,
        pipeline_stage=PIPELINE_STAGE_ATTACHMENT_LIST,
    )
    manual_table = _build_manual_interface_check_table(interface_report)
    summary = dict(interface_report["summary"])
    summary["pipeline_stage"] = PIPELINE_STAGE_ATTACHMENT_LIST
    manifest = {
        "manifest_version": GUANGZHOU_POST_CANDIDATE_BACKTRACE_VERSION,
        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
        "sub_kind": GUANGZHOU_POST_CANDIDATE_BACKTRACE_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_POST_CANDIDATE_BACKTRACE_ADAPTER_ID,
        "pipeline_stage": PIPELINE_STAGE_ATTACHMENT_LIST,
        "resume_enabled": bool(resume),
        "manifest_id": f"GUANGZHOU-ATTACHMENT-LIST-{_fingerprint({'samples': project_samples, 'items': items})[:16]}",
        "created_at": created,
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "target_storage_backend": target_backend,
        "source_profile_id": GUANGZHOU_PROFILE_ID,
        "flow_interface_targets_json": str(targets_path),
        "items": items,
        "sample_items": items[:80],
        "project_sample_items": project_samples,
        "project_sample_preview_items": project_samples[:80],
        "summary": summary,
        "coverage_quality_summary": {
            "coverage_quality_state": str(summary.get("interface_coverage_state") or ""),
            "failure_taxonomy_counts": dict(summary.get("failure_taxonomy_counts") or {}),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "external_service_connection_enabled": execute,
            "download_enabled": False,
            "fetch_public_urls_enabled": execute,
            "login_required_fetch_enabled": False,
            "ca_certificate_required_fetch_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_post_candidate_backtrace_mode": "ATTACHMENT_LIST_EXECUTED" if execute else "ATTACHMENT_LIST_DRY_RUN",
        "pipeline_stage": PIPELINE_STAGE_ATTACHMENT_LIST,
        "resume_enabled": bool(resume),
        "real_sample_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": execute,
            "download_enabled": False,
            "parse_enabled": False,
            "fetch_public_urls_enabled": execute,
            "storage_path_optional": str(storage),
            "object_storage_path_optional": str(object_storage),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    (root / "run-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "guangzhou-flow-interface-coverage.json").write_text(
        json.dumps(interface_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "pipeline-state.json").write_text(
        json.dumps(pipeline_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "manual-interface-check-table.json").write_text(
        json.dumps(manual_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _discover_flow_url_target_items(
    *,
    targets_json: Path,
    seed_json: Path,
    storage_path: Path,
    object_storage_path: Path,
    target_backend: str,
    target_ids: list[str],
    execute: bool,
    per_target_candidate_limit: int,
    created_at: str,
    pipeline_stage: str = PIPELINE_STAGE_FLOW_URL_ONLY,
) -> list[dict[str, Any]]:
    plan = build_evaluation_real_sample_plan(
        targets_json=targets_json,
        seed_json=seed_json,
        database_url=None,
        target_backend=target_backend,
        execute=False,
        created_at=created_at,
    )
    plan_items = [
        dict(item)
        for item in list((plan.get("manifest") or {}).get("items") or [])
        if str(item.get("plan_state") or "") == PLAN_READY
        and str(item.get("target_id") or "") in set(target_ids)
        and resolve_source_quality_policy(_target_source_profile_id(item)).get("source_quality_state") == "PRIMARY_FRIENDLY"
    ]
    if not execute:
        return [_flow_url_dry_run_item(item, pipeline_stage=pipeline_stage) for item in plan_items]
    settings = Settings(
        storage_backend=target_backend,
        storage_path_optional=str(storage_path),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage_path),
    )
    session = DatabaseSession(settings=settings)
    try:
        object_repository = ObjectStorageRepository(session=session, settings=settings)
        discovery_service = RealPublicCandidateDiscoveryService(
            fetcher=RealPublicEntryFetcher(repository=object_repository),
            repository=RealPublicCandidateRepository(repository=OperatorActionRepository(session=session)),
            profile_api_link_discoverer=_discover_profile_api_link_items,
        )
        return [
            _discover_flow_url_target_item(
                item,
                discovery_service=discovery_service,
                created_at=created_at,
                per_target_candidate_limit=per_target_candidate_limit,
                pipeline_stage=pipeline_stage,
            )
            for item in plan_items
        ]
    finally:
        session.close()


def _discover_flow_url_target_item(
    plan_item: Mapping[str, Any],
    *,
    discovery_service: RealPublicCandidateDiscoveryService,
    created_at: str,
    per_target_candidate_limit: int,
    pipeline_stage: str = PIPELINE_STAGE_FLOW_URL_ONLY,
) -> dict[str, Any]:
    base = _flow_url_dry_run_item(plan_item, pipeline_stage=pipeline_stage)
    target_id = str(plan_item.get("target_id") or "")
    profile_id = _target_source_profile_id(plan_item)
    candidate_limit = max(1, min(_int(plan_item.get("target_count")), per_target_candidate_limit))
    payload = {
        "region_code": str(plan_item.get("jurisdiction") or ""),
        "region_codes": [str(plan_item.get("jurisdiction") or "")],
        "project_type": str(plan_item.get("project_type") or "construction"),
        "project_types": [str(plan_item.get("project_type") or "construction")],
        "candidate_limit": candidate_limit,
        "discovery_candidate_limit": candidate_limit,
        "discovery_profile_limit_per_region": 1,
        "source_profile_ids": [profile_id] if profile_id else [],
        "evaluation_corpus_mode": True,
        "evaluation_document_kind": str(plan_item.get("document_kind") or ""),
        "selection_filters": _string_list(plan_item.get("selection_filters")),
        "candidate_discovery_run_id": f"GZ-FLOW-URL-{_slug(target_id)}-{_fingerprint(created_at)[:8]}",
        "now": created_at,
    }
    try:
        discovery_result = discovery_service.discover(payload, now=created_at)
    except Exception as exc:  # pragma: no cover - network-specific defensive branch.
        return {
            **base,
            "target_execution_state": FAILED_RETRYABLE,
            "failure_taxonomy": [f"discovery_exception:{exc}"],
        }
    candidates = [dict(item) for item in list(discovery_result.get("candidates") or []) if isinstance(item, Mapping)]
    profile_reports = [dict(item) for item in list(discovery_result.get("profile_reports") or []) if isinstance(item, Mapping)]
    if not candidates:
        failure_taxonomy = _discovery_failure_taxonomy(profile_reports) or ["discovery_no_match"]
        return {
            **base,
            "target_execution_state": FAILED_RETRYABLE,
            "discovery_state": str(discovery_result.get("discovery_state") or "NO_CANDIDATES"),
            "discovery_profile_reports": _profile_report_refs(profile_reports),
            "failure_taxonomy": failure_taxonomy,
        }
    selected = candidates[:candidate_limit]
    target_state = FLOW_URL_DISCOVERED if pipeline_stage == PIPELINE_STAGE_FLOW_URL_ONLY else ATTACHMENT_LISTED
    return {
        **base,
        "target_execution_state": target_state,
        "discovery_state": str(discovery_result.get("discovery_state") or ""),
        "discovery_candidate_count": len(candidates),
        "discovery_profile_reports": _profile_report_refs(profile_reports),
        "candidate_refs": _candidate_refs(selected),
        "project_sample_items": _flow_url_project_sample_items(
            plan_item=plan_item,
            selected_candidates=selected,
            target_execution_state=target_state,
            failure_taxonomy=_discovery_failure_taxonomy(profile_reports),
            pipeline_stage=pipeline_stage,
        ),
        "failure_taxonomy": _discovery_failure_taxonomy(profile_reports),
    }


def _flow_url_dry_run_item(
    plan_item: Mapping[str, Any],
    *,
    pipeline_stage: str = PIPELINE_STAGE_FLOW_URL_ONLY,
) -> dict[str, Any]:
    source_quality_policy = resolve_source_quality_policy(_target_source_profile_id(plan_item))
    return {
        "target_id": str(plan_item.get("target_id") or ""),
        "jurisdiction": str(plan_item.get("jurisdiction") or ""),
        "platform_name": str(plan_item.get("platform_name") or ""),
        "document_kind": str(plan_item.get("document_kind") or ""),
        "source_family": str(plan_item.get("source_family") or ""),
        "source_profile_id": _target_source_profile_id(plan_item),
        "source_quality_state": str(source_quality_policy.get("source_quality_state") or ""),
        "selection_filters": _string_list(plan_item.get("selection_filters")),
        "target_count": _int(plan_item.get("target_count")),
        "target_execution_state": "EXECUTION_READY",
        "pipeline_stage": pipeline_stage,
        "guangzhou_flow_no": str(plan_item.get("guangzhou_flow_no") or _target_item_filter_value(plan_item, "BACKTRACE_FLOW_NO:")),
        "guangzhou_flow_title": str(plan_item.get("guangzhou_flow_title") or ""),
        "guangzhou_flow_code": str(plan_item.get("guangzhou_flow_code") or _target_item_filter_value(plan_item, "BACKTRACE_FLOW_CODE:")),
        "download_enabled": False,
        "parse_enabled": False,
        "review_required": True,
        "candidate_refs": [],
        "project_sample_items": [],
        "failure_taxonomy": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_url_project_sample_items(
    *,
    plan_item: Mapping[str, Any],
    selected_candidates: list[Mapping[str, Any]],
    target_execution_state: str,
    failure_taxonomy: list[str],
    pipeline_stage: str = PIPELINE_STAGE_FLOW_URL_ONLY,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    stage_suffix = _pipeline_stage_state_suffix(pipeline_stage)
    for candidate in selected_candidates:
        candidate_key = str(candidate.get("candidate_key") or "")
        source_quality_policy = resolve_source_quality_policy(
            candidate.get("source_profile_id") or _target_source_profile_id(plan_item)
        )
        source_text = _clip_text(
            " ".join(
                str(value or "").strip()
                for value in (
                    candidate.get("project_name"),
                    candidate.get("notice_stage"),
                    candidate.get("source_profile_id"),
                )
                if str(value or "").strip()
            )
        )
        items.append(
            {
                "sample_id": f"{plan_item.get('target_id') or 'TARGET'}::{_fingerprint(candidate_key or candidate.get('source_url') or '')[:12]}",
                "parent_target_id": str(plan_item.get("target_id") or ""),
                "target_id": f"{plan_item.get('target_id') or 'TARGET'}::{_fingerprint(candidate_key or candidate.get('source_url') or '')[:12]}",
                "candidate_key": candidate_key,
                "project_id": str(candidate.get("project_id") or ""),
                "notice_id": str(candidate.get("notice_id") or ""),
                "project_name": str(candidate.get("project_name") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "document_kind": str(plan_item.get("document_kind") or ""),
                "jurisdiction": str(plan_item.get("jurisdiction") or ""),
                "source_profile_id": str(candidate.get("source_profile_id") or _target_source_profile_id(plan_item)),
                "source_quality_state": str(candidate.get("source_quality_state") or source_quality_policy.get("source_quality_state") or ""),
                "source_calibration_role": str(candidate.get("source_calibration_role") or source_quality_policy.get("source_calibration_role") or ""),
                "professional_source_priority": bool(candidate.get("professional_source_priority") or source_quality_policy.get("professional_source_priority")),
                "source_trading_process": str(candidate.get("source_trading_process") or ""),
                "source_dataset_name": str(candidate.get("source_dataset_name") or ""),
                "source_query_process_label": str(candidate.get("source_query_process_label") or ""),
                "source_notice_third_type_desc": str(candidate.get("source_notice_third_type_desc") or ""),
                "published_at_optional": str(candidate.get("published_at_optional") or ""),
                "source_project_code": str(candidate.get("source_project_code") or ""),
                "source_record_id": str(candidate.get("source_record_id") or ""),
                "project_match_key": str(candidate.get("project_match_key") or ""),
                "base_project_name": str(candidate.get("base_project_name") or ""),
                "guangzhou_flow_no": str(candidate.get("guangzhou_flow_no") or ""),
                "guangzhou_flow_title": str(candidate.get("guangzhou_flow_title") or ""),
                "guangzhou_flow_code": str(candidate.get("guangzhou_flow_code") or candidate.get("source_trading_process") or ""),
                "guangzhou_flow_folder": str(candidate.get("guangzhou_flow_folder") or ""),
                "guangzhou_relation_guid": str(candidate.get("guangzhou_relation_guid") or candidate.get("source_project_code") or ""),
                "backtrace_query_variants": _dedupe_strings(candidate.get("backtrace_query_variants") or []),
                "backtrace_match_reason": str(candidate.get("backtrace_match_reason") or ""),
                "matched_project_keys": _dedupe_strings(
                    [
                        *list(candidate.get("matched_project_keys") or []),
                        candidate.get("source_project_code"),
                        candidate.get("project_match_key"),
                    ]
                ),
                "source_family": str(plan_item.get("source_family") or ""),
                "project_type": str(plan_item.get("project_type") or ""),
                "target_execution_state": target_execution_state,
                "pipeline_stage": pipeline_stage,
                "detail_capture_status": f"NOT_RUN_{stage_suffix}",
                "stage3_parse_state": f"NOT_RUN_{stage_suffix}",
                "document_completeness_state": pipeline_stage,
                "notice_version_chain_state": pipeline_stage,
                "detail_snapshot_refs": [],
                "attachment_snapshot_refs": [],
                "detail_snapshot_count": 0,
                "attachment_snapshot_count": 0,
                "challenge_diagnostics": [],
                "parse_summary": _empty_parse_summary(),
                "source_text": source_text,
                "failure_taxonomy": _dedupe_strings(failure_taxonomy),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return items


def _entry_targets_with_candidate_limit(
    *,
    base_targets_path: Path,
    output_root: Path,
    per_target_candidate_limit: int,
) -> Path:
    payload = json.loads(base_targets_path.read_text(encoding="utf-8"))
    targets = [
        dict(item)
        for item in list(payload.get("targets") or [])
        if isinstance(item, Mapping)
    ]
    desired_count = max(1, per_target_candidate_limit)
    entry_targets: list[dict[str, Any]] = []
    for target in targets:
        if str(target.get("target_id") or "") not in ENTRY_TARGET_IDS:
            continue
        row = dict(target)
        row["target_count"] = max(_int(row.get("target_count")), desired_count)
        filters = _dedupe_strings(
            [
                *list(row.get("selection_filters") or []),
                f"POST_CANDIDATE_BATCH_LIMIT:{desired_count}",
            ]
        )
        row["selection_filters"] = filters
        entry_targets.append(row)
    entry_payload = {
        "target_version": int(payload.get("target_version") or 1),
        "target_set_id": "guangzhou-post-candidate-entry-targets-v1",
        "minimum_total_sample_goal": sum(_int(item.get("target_count")) for item in entry_targets),
        "created_from": "POST_CANDIDATE_BACKTRACE_V1_ENTRY_TARGET_OVERRIDE",
        "target_policy": dict(payload.get("target_policy") or {}),
        "targets": entry_targets,
    }
    entry_targets_path = output_root / "entry-targets.json"
    entry_targets_path.write_text(json.dumps(entry_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry_targets_path


def _guangzhou_flow_interface_targets(*, output_root: Path, per_flow_candidate_limit: int) -> Path:
    targets = []
    desired_count = max(1, per_flow_candidate_limit)
    for module in GUANGZHOU_FLOW_MODULES:
        document_kind = str(module["document_kind"])
        flow_no = str(module["flow_no"])
        flow_code = str(module["flow_code"])
        flow_title = str(module["flow_title"])
        targets.append(
            {
                "target_id": f"GZ-FLOW-INTERFACE-{flow_no}-{_document_kind_suffix(document_kind)}",
                "jurisdiction": "CN-GD",
                "platform_name": "广州交易集团",
                "entry_seed_id": "ENTRY-GUANGZHOU-YWTB",
                "required_fetch_profile_id_optional": GUANGZHOU_PROFILE_ID,
                "source_family": "local_public_resource_trading_center",
                "project_type": "construction",
                "document_kind": document_kind,
                "target_count": desired_count,
                "selection_filters": [
                    "工程建设",
                    flow_title,
                    "FLOW_INTERFACE_COVERAGE",
                    "FLOW_INTERFACE_PAGE_LIMIT:8",
                    "FLOW_INTERFACE_MONTH_WINDOWS:12",
                    f"FLOW_INTERFACE_SAMPLE_LIMIT:{desired_count}",
                    f"BACKTRACE_FLOW_NO:{flow_no}",
                    f"BACKTRACE_FLOW_CODE:{flow_code}",
                ],
                "guangzhou_flow_no": flow_no,
                "guangzhou_flow_title": flow_title,
                "guangzhou_flow_code": flow_code,
            }
        )
    payload = {
        "target_version": 1,
        "target_set_id": "guangzhou-flow-interface-coverage-v1",
        "minimum_total_sample_goal": len(targets) * desired_count,
        "created_from": "GUANGZHOU_ATTACHMENT_LIST_INTERFACE_COVERAGE_V1",
        "target_policy": {
            "download_enabled": False,
            "fetch_public_urls_enabled": True,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "do_not_fabricate_project_urls": True,
        },
        "targets": targets,
    }
    targets_path = output_root / "flow-interface-targets.json"
    targets_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return targets_path


def _build_flow_interface_coverage_manifest(
    *,
    items: list[Mapping[str, Any]],
    project_samples: list[Mapping[str, Any]],
    execute: bool,
    per_flow_candidate_limit: int,
    created_at: str,
    output_root: Path,
) -> dict[str, Any]:
    samples_by_flow: dict[str, list[Mapping[str, Any]]] = {}
    for sample in project_samples:
        flow_no = _sample_flow_no(sample)
        if flow_no:
            samples_by_flow.setdefault(flow_no, []).append(sample)
    for sample in _human_provided_flow_seed_samples():
        flow_no = _sample_flow_no(sample)
        if not flow_no:
            continue
        existing_urls = {
            str(existing.get("source_url") or "")
            for existing in samples_by_flow.get(flow_no, [])
            if isinstance(existing, Mapping)
        }
        if str(sample.get("source_url") or "") not in existing_urls:
            samples_by_flow.setdefault(flow_no, []).append(sample)
    target_by_flow: dict[str, Mapping[str, Any]] = {}
    for item in items:
        flow_no = str(item.get("guangzhou_flow_no") or _target_item_filter_value(item, "BACKTRACE_FLOW_NO:"))
        if flow_no:
            target_by_flow[flow_no] = item
    flow_reports = [
        _flow_interface_report_row(
            module=module,
            samples=samples_by_flow.get(str(module["flow_no"]), []),
            target_item=target_by_flow.get(str(module["flow_no"]), {}),
            execute=execute,
            per_flow_candidate_limit=per_flow_candidate_limit,
        )
        for module in GUANGZHOU_FLOW_MODULES
    ]
    required_flow_nos = {f"{index:02d}" for index in range(1, 12)}
    missing_required = [
        str(row.get("flow_no") or "")
        for row in flow_reports
        if str(row.get("flow_no") or "") in required_flow_nos
        and str(row.get("flow_interface_coverage_state") or "") == FLOW_SAMPLE_NOT_FOUND
    ]
    missing_optional = [
        str(row.get("flow_no") or "")
        for row in flow_reports
        if str(row.get("flow_interface_coverage_state") or "") == OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND
    ]
    required_with_sample = len(required_flow_nos) - len(missing_required)
    optional_with_sample = len(
        [
            row
            for row in flow_reports
            if str(row.get("flow_no") or "") not in required_flow_nos
            and str(row.get("flow_interface_coverage_state") or "") != OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND
        ]
    )
    state = "SAMPLE_READY" if not missing_required else "PARTIAL_REVIEW_REQUIRED"
    failure_taxonomy_counts = _counts(
        reason
        for row in flow_reports
        for sample in list(row.get("sample_interface_items") or [])
        for reason in list(sample.get("failure_taxonomy") or [])
    )
    human_seed_count = sum(
        1
        for row in flow_reports
        for sample in list(row.get("sample_interface_items") or [])
        if str(sample.get("sample_source_type") or "") == "HUMAN_PROVIDED_FLOW_SEED"
    )
    status_counts = _counts(
        str(sample.get("interface_status") or "")
        for row in flow_reports
        for sample in list(row.get("sample_interface_items") or [])
    )
    summary = {
        "pipeline_stage": PIPELINE_STAGE_ATTACHMENT_LIST,
        "interface_coverage_state": state,
        "flow_count": len(flow_reports),
        "required_flow_count": 11,
        "required_flow_covered_count": required_with_sample,
        "required_flow_with_sample_count": required_with_sample,
        "optional_flow_with_sample_count": optional_with_sample,
        "missing_required_flow_nos": missing_required,
        "optional_low_frequency_flow_nos": ["12"],
        "optional_missing_flow_nos": missing_optional,
        "sample_interface_count": sum(len(list(row.get("sample_interface_items") or [])) for row in flow_reports),
        "interface_status_counts": status_counts,
        "failure_taxonomy_counts": failure_taxonomy_counts,
        "human_provided_flow_seed_count": human_seed_count,
        "attachment_snapshot_count": 0,
        "download_enabled": False,
        "parse_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_version": 1,
        "manifest_kind": "guangzhou_flow_interface_coverage_manifest",
        "adapter_id": "guangzhou-flow-interface-coverage-v1",
        "manifest_id": f"GUANGZHOU-FLOW-INTERFACE-{_fingerprint({'flows': flow_reports, 'summary': summary})[:16]}",
        "created_at": created_at,
        "output_root": str(output_root),
        "source_profile_id": GUANGZHOU_PROFILE_ID,
        "official_entry_url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/trade_purchasetoplen6.html",
        "pipeline_stage": PIPELINE_STAGE_ATTACHMENT_LIST,
        "flow_reports": flow_reports,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    return {"manifest": manifest, "summary": summary}


def _human_provided_flow_seed_samples() -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for seed in GUANGZHOU_HUMAN_PROVIDED_FLOW_SEEDS:
        source_url = str(seed.get("source_url") or "")
        flow_no = str(seed.get("flow_no") or "")
        flow_title = str(seed.get("flow_title") or "")
        source_quality_policy = resolve_source_quality_policy(GUANGZHOU_PROFILE_ID)
        samples.append(
            {
                "sample_id": f"HUMAN-FLOW-SEED-{flow_no}-{_fingerprint(source_url)[:12]}",
                "parent_target_id": f"GZ-FLOW-INTERFACE-{flow_no}-HUMAN-SEED",
                "target_id": f"GZ-FLOW-INTERFACE-{flow_no}-HUMAN-SEED::{_fingerprint(source_url)[:12]}",
                "candidate_key": _fingerprint(source_url)[:24],
                "project_id": str(seed.get("project_id") or f"PROJ-CN-GD-HUMAN-{_fingerprint(source_url)[:10]}"),
                "notice_id": f"NOTICE-GUANGZHOU-HUMAN-SEED-{_fingerprint(source_url)[:10]}",
                "project_name": str(seed.get("project_name") or ""),
                "source_url": source_url,
                "document_kind": str(seed.get("document_kind") or ""),
                "jurisdiction": "CN-GD",
                "source_profile_id": GUANGZHOU_PROFILE_ID,
                "source_quality_state": str(source_quality_policy.get("source_quality_state") or ""),
                "source_calibration_role": str(source_quality_policy.get("source_calibration_role") or ""),
                "professional_source_priority": bool(source_quality_policy.get("professional_source_priority")),
                "source_trading_process": str(seed.get("flow_code") or ""),
                "source_dataset_name": flow_title,
                "source_query_process_label": "human_provided_flow_seed",
                "source_notice_third_type_desc": flow_title,
                "published_at_optional": str(seed.get("published_at_optional") or ""),
                "source_project_code": "",
                "source_record_id": str(seed.get("source_record_id") or ""),
                "project_match_key": str(seed.get("source_record_id") or ""),
                "base_project_name": str(seed.get("project_name") or ""),
                "guangzhou_flow_no": flow_no,
                "guangzhou_flow_title": flow_title,
                "guangzhou_flow_code": str(seed.get("flow_code") or ""),
                "guangzhou_flow_folder": f"{flow_no}_{flow_title}" if flow_no and flow_title else "",
                "guangzhou_relation_guid": "",
                "backtrace_query_variants": [],
                "backtrace_match_reason": "human_provided_flow_seed",
                "matched_project_keys": _dedupe_strings([seed.get("source_record_id"), seed.get("project_name")]),
                "source_family": "local_public_resource_trading_center",
                "project_type": "construction",
                "target_execution_state": ATTACHMENT_LISTED,
                "pipeline_stage": PIPELINE_STAGE_ATTACHMENT_LIST,
                "detail_capture_status": "NOT_RUN_ATTACHMENT_LIST",
                "stage3_parse_state": "NOT_RUN_ATTACHMENT_LIST",
                "document_completeness_state": PIPELINE_STAGE_ATTACHMENT_LIST,
                "notice_version_chain_state": PIPELINE_STAGE_ATTACHMENT_LIST,
                "detail_snapshot_refs": [],
                "attachment_snapshot_refs": [],
                "detail_snapshot_count": 0,
                "attachment_snapshot_count": 0,
                "challenge_diagnostics": [],
                "parse_summary": _empty_parse_summary(),
                "source_text": str(seed.get("project_name") or ""),
                "failure_taxonomy": [],
                "sample_source_type": str(seed.get("sample_source_type") or "HUMAN_PROVIDED_FLOW_SEED"),
                "seed_evidence": str(seed.get("seed_evidence") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return samples


def _flow_interface_report_row(
    *,
    module: Mapping[str, Any],
    samples: list[Mapping[str, Any]],
    target_item: Mapping[str, Any],
    execute: bool,
    per_flow_candidate_limit: int,
) -> dict[str, Any]:
    flow_no = str(module.get("flow_no") or "")
    sample_rows = samples[: max(1, per_flow_candidate_limit)]
    sample_items = [
        _scan_guangzhou_interface_sample(sample, execute=execute)
        for sample in sample_rows
    ]
    human_seed_count = sum(
        1 for sample in sample_items if str(sample.get("sample_source_type") or "") == "HUMAN_PROVIDED_FLOW_SEED"
    )
    if not sample_items:
        status = OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND if flow_no == "12" else FLOW_SAMPLE_NOT_FOUND
    else:
        status = "FLOW_INTERFACE_SAMPLED"
    target_failures = list(target_item.get("failure_taxonomy") or [])
    process_attempts = _target_item_public_api_process_attempts(target_item)
    attempted_pages = sum(_int(attempt.get("attempted_pages")) or 1 for attempt in process_attempts)
    record_count = sum(_int(attempt.get("record_count")) for attempt in process_attempts)
    accepted_item_count = sum(_int(attempt.get("accepted_item_count")) for attempt in process_attempts)
    sample_urls = _dedupe_strings(
        str(sample.get("source_url") or "") for sample in sample_items if str(sample.get("source_url") or "")
    )
    flow_failure_taxonomy = _dedupe_strings(
        [
            *target_failures,
            *(["human_provided_flow_seed_used"] if human_seed_count else []),
            *[
                str(reason or "")
                for attempt in process_attempts
                for reason in list(attempt.get("failure_taxonomy") or [])
            ],
        ]
    )
    if not sample_items and not flow_failure_taxonomy:
        flow_failure_taxonomy = [
            "optional_low_frequency_flow_no_sample"
            if flow_no == "12"
            else "flow_interface_no_sample"
        ]
    if not sample_items and record_count == 0:
        flow_failure_taxonomy = _dedupe_strings(
            [*flow_failure_taxonomy, "flow_interface_no_records_after_page_scan"]
        )
    elif not sample_items and record_count > 0 and accepted_item_count == 0:
        flow_failure_taxonomy = _dedupe_strings(
            [*flow_failure_taxonomy, "flow_interface_records_rejected"]
        )
    return {
        "flow_no": flow_no,
        "flow_title": str(module.get("flow_title") or ""),
        "flow_code": str(module.get("flow_code") or ""),
        "document_kind": str(module.get("document_kind") or ""),
        "required_for_recent_acceptance": flow_no != "12",
        "flow_interface_coverage_state": status,
        "target_execution_state": str(target_item.get("target_execution_state") or ""),
        "target_failure_taxonomy": target_failures,
        "attempted_pages": attempted_pages,
        "record_count": record_count,
        "accepted_item_count": accepted_item_count,
        "sample_urls": sample_urls,
        "failure_taxonomy": flow_failure_taxonomy,
        "public_api_process_attempts": process_attempts,
        "sample_interface_items": sample_items,
        "sample_count": len(sample_items),
        "human_provided_flow_seed_count": human_seed_count,
        "interface_status_counts": _counts(str(item.get("interface_status") or "") for item in sample_items),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _scan_guangzhou_interface_sample(sample: Mapping[str, Any], *, execute: bool) -> dict[str, Any]:
    source_url = str(sample.get("source_url") or "")
    base = {
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "flow_no": _sample_flow_no(sample),
        "flow_title": _sample_flow_title(sample),
        "document_kind": str(sample.get("document_kind") or ""),
        "source_url": source_url,
        "published_at_optional": str(sample.get("published_at_optional") or ""),
        "source_project_code": str(sample.get("source_project_code") or ""),
        "sample_source_type": str(sample.get("sample_source_type") or ""),
        "seed_evidence": str(sample.get("seed_evidence") or ""),
        "download_enabled": False,
        "snapshot_write_enabled": False,
        "parse_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if not execute:
        return {
            **base,
            "interface_status": INTERFACE_UNRESOLVED,
            "attachment_entry_count": 0,
            "discovered_endpoints": [],
            "probe_text": "",
            "failure_taxonomy": ["dry_run_interface_scan_not_executed"],
        }
    html_result = _fetch_public_text(source_url)
    if not html_result["ok"]:
        return {
            **base,
            "interface_status": INTERFACE_UNRESOLVED,
            "attachment_entry_count": 0,
            "discovered_endpoints": [],
            "probe_text": "",
            "failure_taxonomy": list(html_result["failure_taxonomy"]),
        }
    scan = _scan_guangzhou_interface_html(str(html_result["text"]), source_url=source_url)
    if scan["interface_status"] in {NO_PUBLIC_ATTACHMENT, INTERFACE_UNRESOLVED}:
        playwright_scan = _playwright_interface_probe(source_url)
        if playwright_scan.get("interface_status") == CLICK_DOWNLOAD_ENDPOINT_FOUND:
            scan = playwright_scan
        elif playwright_scan.get("failure_taxonomy"):
            scan["failure_taxonomy"] = _dedupe_strings(
                [*list(scan.get("failure_taxonomy") or []), *list(playwright_scan.get("failure_taxonomy") or [])]
            )
    return {
        **base,
        **scan,
    }


def _target_item_public_api_process_attempts(target_item: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for report in list(target_item.get("discovery_profile_reports") or []):
        if not isinstance(report, Mapping):
            continue
        for attempt in list(report.get("public_api_process_attempts") or []):
            if isinstance(attempt, Mapping):
                attempts.append(dict(attempt))
    return attempts


def _fetch_public_text(source_url: str) -> dict[str, Any]:
    if not source_url:
        return {"ok": False, "text": "", "failure_taxonomy": ["source_url_missing"]}
    request = Request(
        source_url,
        headers={
            "User-Agent": "AX9S-Guangzhou-InterfaceCoverage/0.1 (+public-readonly-validation)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/trade_purchasetoplen6.html",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=18) as response:
            raw = response.read(1_500_000)
            content_type = str(response.headers.get("Content-Type") or "")
        text = raw.decode("utf-8", "ignore")
        return {"ok": True, "text": text, "content_type": content_type, "failure_taxonomy": []}
    except HTTPError as exc:
        return {"ok": False, "text": "", "failure_taxonomy": [f"interface_http_error:{exc.code}"]}
    except URLError as exc:
        return {"ok": False, "text": "", "failure_taxonomy": [f"interface_url_error:{exc.reason}"]}
    except Exception as exc:  # pragma: no cover - network failures vary.
        return {"ok": False, "text": "", "failure_taxonomy": [f"interface_fetch_exception:{exc}"]}


def _scan_guangzhou_interface_html(html: str, *, source_url: str) -> dict[str, Any]:
    text = str(html or "")
    lower = text.lower()
    endpoints = _extract_interface_endpoints(text, source_url=source_url)
    probe = _clip_text(_visible_interface_probe(text), 800)
    failure_taxonomy: list[str] = []
    if _has_login_or_ca_marker(text):
        status = LOGIN_OR_CA_REQUIRED
        failure_taxonomy.append("login_or_ca_required")
    elif _has_epoint_challenge_marker(text):
        status = EPOINT_CHALLENGE_REQUIRED
        failure_taxonomy.append("epoint_challenge_required")
    elif any(_is_script_download_endpoint(item.get("url", "")) or _is_script_download_endpoint(item.get("raw", "")) for item in endpoints):
        status = SCRIPT_DOWNLOAD_ENDPOINT_FOUND
    elif any(_is_static_attachment_endpoint(item.get("url", "")) for item in endpoints):
        status = STATIC_ATTACHMENT_LINK_FOUND
    elif _has_no_public_attachment_marker(text):
        status = NO_PUBLIC_ATTACHMENT
    elif _has_attachment_words(text):
        status = INTERFACE_UNRESOLVED
        failure_taxonomy.append("attachment_words_present_but_endpoint_unresolved")
    else:
        status = NO_PUBLIC_ATTACHMENT
    return {
        "interface_status": status,
        "attachment_entry_count": len(endpoints),
        "discovered_endpoints": endpoints[:20],
        "probe_text": probe,
        "failure_taxonomy": failure_taxonomy,
        "html_probe_sha256": _fingerprint(probe),
    }


def _extract_interface_endpoints(html: str, *, source_url: str) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    patterns = [
        r"""(?:href|data-url|data-href|action)=["']([^"']+)["']""",
        r"""(?:ztbfjyz|downloadztbattach|downloadZtbAttach|ztbAttachDownloadAction)[^"'<>\s)]*""",
        r"""["']([^"']*(?:downloadztbattach|downloadZtbAttach|ztbAttachDownloadAction|sys-file/download|tempdownattach|AttachGuid|\.pdf|\.docx?|\.xlsx?|\.zip|\.rar)[^"']*)["']""",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE):
            raw = match.group(1) if match.lastindex else match.group(0)
            raw = str(raw or "").strip()
            if not raw or raw.startswith("javascript:void"):
                continue
            if any(token in raw for token in ("<", ">")) and not re.match(r"^https?://", raw, flags=re.IGNORECASE):
                continue
            url = raw if re.match(r"^https?://", raw, flags=re.IGNORECASE) else urljoin(source_url, raw)
            if not _looks_like_interface_endpoint(raw, url):
                continue
            endpoints.append(
                {
                    "url": url,
                    "raw": raw[:300],
                    "endpoint_kind": _endpoint_kind(raw, url),
                }
            )
    return _dedupe_endpoint_rows(endpoints)


def _visible_interface_probe(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_login_or_ca_marker(text: str) -> bool:
    return any(token in text for token in ("请登录", "登录后", "CA锁", "数字证书", "证书登录", "CA登录"))


def _has_epoint_challenge_marker(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in ("pageverify", "blockpuzzle", "captcha", "initandcheckcaptcha"))


def _has_attachment_words(text: str) -> bool:
    return any(token in text for token in ("附件", "下载", "招标文件", "招标资料", "投标文件", "答疑", "补遗", "澄清"))


def _has_no_public_attachment_marker(text: str) -> bool:
    return any(token in text for token in ("无附件", "暂无附件", "没有附件", "未上传附件"))


def _looks_like_interface_endpoint(raw: str, url: str) -> bool:
    combined = f"{raw} {url}".lower()
    return any(
        token in combined
        for token in (
            "download",
            "attach",
            "downloadztbattach",
            "ztbattachdownloadaction",
            "ztbfjyz",
            "sys-file/download",
            "tempdownattach",
            "attachguid",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".zip",
            ".rar",
        )
    )


def _is_script_download_endpoint(value: str) -> bool:
    lower = str(value or "").lower()
    return any(token in lower for token in ("ztbfjyz", "downloadztbattach", "downloadztbattach.jspx", "ztbattachdownloadaction"))


def _is_static_attachment_endpoint(value: str) -> bool:
    lower = str(value or "").lower()
    return any(
        token in lower
        for token in (
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".zip",
            ".rar",
            "sys-file/download",
            "tempdownattach",
            "attachguid=",
            "/download?",
        )
    )


def _endpoint_kind(raw: str, url: str) -> str:
    if _is_script_download_endpoint(raw) or _is_script_download_endpoint(url):
        return "SCRIPT_DOWNLOAD_ENDPOINT"
    if _is_static_attachment_endpoint(url):
        return "STATIC_ATTACHMENT_LINK"
    return "POSSIBLE_ATTACHMENT_INTERFACE"


def _dedupe_endpoint_rows(rows: list[Mapping[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(dict(row))
    return result


def _playwright_interface_probe(source_url: str) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return {"interface_status": INTERFACE_UNRESOLVED, "failure_taxonomy": ["playwright_unavailable"]}
    endpoints: list[dict[str, str]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on(
                "request",
                lambda request: endpoints.append(
                    {
                        "url": request.url,
                        "raw": request.url[:300],
                        "endpoint_kind": _endpoint_kind(request.url, request.url),
                    }
                )
                if _looks_like_interface_endpoint(request.url, request.url)
                else None,
            )
            page.goto(source_url, wait_until="domcontentloaded", timeout=18_000)
            locators = page.locator("text=/附件|下载|招标文件|招标资料|答疑|补遗|澄清|投标文件/")
            count = min(locators.count(), 8)
            for index in range(count):
                try:
                    locators.nth(index).click(timeout=1_500, trial=False)
                    page.wait_for_timeout(300)
                except Exception:
                    continue
            browser.close()
    except Exception as exc:  # pragma: no cover - browser/network variance.
        return {"interface_status": INTERFACE_UNRESOLVED, "failure_taxonomy": [f"playwright_probe_failed:{exc}"]}
    endpoints = _dedupe_endpoint_rows(endpoints)
    if endpoints:
        return {
            "interface_status": CLICK_DOWNLOAD_ENDPOINT_FOUND,
            "attachment_entry_count": len(endpoints),
            "discovered_endpoints": endpoints[:20],
            "probe_text": "",
            "failure_taxonomy": [],
            "html_probe_sha256": "",
        }
    return {"interface_status": INTERFACE_UNRESOLVED, "failure_taxonomy": ["playwright_no_download_endpoint"]}


def _build_manual_interface_check_table(interface_report: Mapping[str, Any]) -> dict[str, Any]:
    manifest = interface_report.get("manifest") if isinstance(interface_report.get("manifest"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    for flow in list(manifest.get("flow_reports") or []):
        if not isinstance(flow, Mapping):
            continue
        sample_items = list(flow.get("sample_interface_items") or [])
        if not sample_items:
            rows.append(
                {
                    "flow_no": str(flow.get("flow_no") or ""),
                    "flow_title": str(flow.get("flow_title") or ""),
                    "project_id": "",
                    "project_name": "",
                    "source_url": "",
                    "published_at_optional": "",
                    "interface_status": str(flow.get("flow_interface_coverage_state") or ""),
                    "attachment_entry_count": 0,
                    "failure_taxonomy": list(flow.get("failure_taxonomy") or flow.get("target_failure_taxonomy") or []),
                    "sample_source_type": "",
                    "seed_evidence": "",
                    "attempted_pages": _int(flow.get("attempted_pages")),
                    "record_count": _int(flow.get("record_count")),
                    "accepted_item_count": _int(flow.get("accepted_item_count")),
                    "manual_check_state": "NO_SAMPLE_TO_CHECK",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
            continue
        for sample in sample_items:
            if not isinstance(sample, Mapping):
                continue
            rows.append(
                {
                    "flow_no": str(flow.get("flow_no") or ""),
                    "flow_title": str(flow.get("flow_title") or ""),
                    "project_id": str(sample.get("project_id") or ""),
                    "project_name": str(sample.get("project_name") or ""),
                    "source_url": str(sample.get("source_url") or ""),
                    "published_at_optional": str(sample.get("published_at_optional") or ""),
                    "interface_status": str(sample.get("interface_status") or ""),
                    "attachment_entry_count": _int(sample.get("attachment_entry_count")),
                    "failure_taxonomy": list(sample.get("failure_taxonomy") or []),
                    "sample_source_type": str(sample.get("sample_source_type") or ""),
                    "seed_evidence": str(sample.get("seed_evidence") or ""),
                    "attempted_pages": _int(flow.get("attempted_pages")),
                    "record_count": _int(flow.get("record_count")),
                    "accepted_item_count": _int(flow.get("accepted_item_count")),
                    "manual_check_state": "PENDING",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return {
        "manifest": {
            "manifest_version": 1,
            "manifest_kind": "guangzhou_manual_interface_check_table",
            "pipeline_stage": PIPELINE_STAGE_ATTACHMENT_LIST,
            "items": rows,
            "summary": {
                "row_count": len(rows),
                "flow_count": len({row["flow_no"] for row in rows if row["flow_no"]}),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    }


def _maybe_resume_interface_coverage_manifest(
    *,
    root: Path,
    created_at: str,
    resume: bool,
) -> dict[str, Any] | None:
    if not resume:
        return None
    state_path = root / "pipeline-state.json"
    if state_path.exists():
        state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        _mark_interrupted_pipeline_rows(state_payload, created_at=created_at)
        state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    run_path = root / "run-manifest.json"
    coverage_path = root / "guangzhou-flow-interface-coverage.json"
    if not run_path.exists() or not coverage_path.exists():
        return None
    result = json.loads(run_path.read_text(encoding="utf-8"))
    coverage_payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage_manifest = coverage_payload.get("manifest") if isinstance(coverage_payload.get("manifest"), Mapping) else {}
    if str(coverage_manifest.get("pipeline_stage") or "") != PIPELINE_STAGE_ATTACHMENT_LIST:
        return None
    result["pipeline_resume"] = {
        "resume_state": "RESUMED_FROM_INTERFACE_COVERAGE_MANIFEST",
        "coverage_manifest_path": str(coverage_path),
        "pipeline_state_path": str(state_path),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return result


def _build_flow_url_manifest(
    *,
    project_samples: list[Mapping[str, Any]],
    archive_manifest: Mapping[str, Any],
    created_at: str,
    output_root: Path,
    per_target_candidate_limit: int,
) -> dict[str, Any]:
    archive_items = [
        dict(item)
        for item in list(archive_manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]
    by_project: dict[str, list[Mapping[str, Any]]] = {}
    for sample in project_samples:
        project_id = str(sample.get("project_id") or sample.get("target_id") or "")
        if not project_id:
            continue
        by_project.setdefault(project_id, []).append(sample)
    archive_by_project = {str(item.get("project_id") or ""): item for item in archive_items}
    projects = [
        _flow_url_project_row(
            project_id=project_id,
            samples=samples,
            archive_item=archive_by_project.get(project_id, {}),
        )
        for project_id, samples in sorted(by_project.items())
    ]
    summary = {
        "pipeline_stage": PIPELINE_STAGE_FLOW_URL_ONLY,
        "project_count": len(projects),
        "requested_project_limit": max(1, per_target_candidate_limit),
        "flow_url_count": sum(len(row.get("verification_urls", {}).get("all_urls", [])) for row in projects),
        "download_enabled": False,
        "parse_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_version": 1,
        "manifest_kind": "guangzhou_flow_url_manifest",
        "adapter_id": "guangzhou-flow-url-only-manifest-builder",
        "manifest_id": f"GUANGZHOU-FLOW-URL-MANIFEST-{_fingerprint({'projects': projects})[:16]}",
        "created_at": created_at,
        "output_root": str(output_root),
        "pipeline_stage": PIPELINE_STAGE_FLOW_URL_ONLY,
        "projects": projects,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    return {"manifest": manifest, "summary": summary}


def _flow_url_project_row(
    *,
    project_id: str,
    samples: list[Mapping[str, Any]],
    archive_item: Mapping[str, Any],
) -> dict[str, Any]:
    first = samples[0] if samples else {}
    flow_inventory = [
        dict(item)
        for item in list(archive_item.get("guangzhou_flow_inventory") or [])
        if isinstance(item, Mapping)
    ]
    flow_matrix = [
        _flow_url_matrix_row(module=module, samples=samples, flow_inventory=flow_inventory)
        for module in GUANGZHOU_FLOW_MODULES
    ]
    all_urls = _dedupe_strings(
        [
            *[
                str(sample.get("source_url") or "")
                for sample in samples
                if str(sample.get("source_url") or "")
            ],
            *[
                str(item.get("source_url") or "")
                for item in flow_inventory
                if str(item.get("source_url") or "")
            ],
        ]
    )
    return {
        "project_id": project_id,
        "project_name": str(first.get("project_name") or archive_item.get("project_name") or ""),
        "source_project_code": str(first.get("source_project_code") or ""),
        "matched_project_keys": _dedupe_strings(
            key
            for sample in samples
            for key in list(sample.get("matched_project_keys") or [])
        ),
        "flow_matrix": flow_matrix,
        "present_flow_nos": [row["flow_no"] for row in flow_matrix if row["present"]],
        "missing_flow_nos": [row["flow_no"] for row in flow_matrix if not row["present"]],
        "verification_urls": {
            "all_urls": all_urls,
            "url_count": len(all_urls),
            "manual_check_hint": "逐个打开流程 URL，核对页面是否属于同一 project_id/source_project_code。",
        },
        "project_dir": str(archive_item.get("project_dir") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_url_matrix_row(
    *,
    module: Mapping[str, Any],
    samples: list[Mapping[str, Any]],
    flow_inventory: list[Mapping[str, Any]],
) -> dict[str, Any]:
    flow_no = str(module.get("flow_no") or "")
    sample_rows = [sample for sample in samples if _sample_flow_no(sample) == flow_no]
    inventory_rows = [row for row in flow_inventory if str(row.get("flow_no") or "") == flow_no]
    urls = _dedupe_strings(
        [
            *[sample.get("source_url") for sample in sample_rows],
            *[row.get("source_url") for row in inventory_rows],
        ]
    )
    failure_taxonomy = _dedupe_strings(
        reason
        for sample in sample_rows
        for reason in list(sample.get("failure_taxonomy") or [])
    )
    attempts = [
        dict(attempt)
        for sample in samples
        for attempt in list(sample.get("backtrace_stage_attempts") or [])
        if isinstance(attempt, Mapping) and str(attempt.get("guangzhou_flow_no") or "") == flow_no
    ]
    failure_taxonomy = _dedupe_strings(
        [
            *failure_taxonomy,
            *[
                reason
                for attempt in attempts
                for reason in list(attempt.get("failure_taxonomy") or [])
            ],
        ]
    )
    return {
        "flow_no": flow_no,
        "flow_title": str(module.get("flow_title") or ""),
        "document_kind": str(module.get("document_kind") or ""),
        "present": bool(urls),
        "detail_urls": urls,
        "published_dates": _dedupe_strings(
            [
                *[str(sample.get("published_at_optional") or "")[:10] for sample in sample_rows],
                *[row.get("published_date") for row in inventory_rows],
            ]
        ),
        "target_execution_states": _dedupe_strings(
            [
                *[sample.get("target_execution_state") for sample in sample_rows],
                *[attempt.get("target_execution_state") for attempt in attempts],
            ]
        ),
        "failure_taxonomy": failure_taxonomy,
        "download_enabled": False,
        "parse_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _build_pipeline_state_manifest(
    *,
    project_samples: list[Mapping[str, Any]],
    items: list[Mapping[str, Any]],
    created_at: str,
    pipeline_stage: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for sample in project_samples:
        flow_no = _sample_flow_no(sample)
        if str(sample.get("source_url") or ""):
            state = ATTACHMENT_LISTED if pipeline_stage == PIPELINE_STAGE_ATTACHMENT_LIST else FLOW_URL_DISCOVERED
        else:
            state = FAILED_RETRYABLE
        rows.append(
            {
                "project_id": str(sample.get("project_id") or ""),
                "project_name": str(sample.get("project_name") or ""),
                "flow_no": flow_no,
                "flow_title": _sample_flow_title(sample),
                "source_url": str(sample.get("source_url") or ""),
                "state": state,
                "attempt_count": 1,
                "failure_taxonomy": list(sample.get("failure_taxonomy") or []),
                "artifact_refs": {
                    "detail_snapshot_refs": [],
                    "attachment_snapshot_refs": [],
                },
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    sample_project_keys = {
        _project_match_key(sample)
        for sample in project_samples
        if _project_match_key(sample)
    }
    for item in items:
        if str(item.get("target_execution_state") or "") in {FLOW_URL_DISCOVERED, ATTACHMENT_LISTED}:
            continue
        target_key = _target_item_project_key(item)
        if target_key and target_key not in sample_project_keys:
            continue
        state = FAILED_RETRYABLE if str(item.get("target_execution_state") or "") else FAILED_FINAL
        rows.append(
            {
                "project_id": target_key,
                "project_name": "",
                "flow_no": str(item.get("guangzhou_flow_no") or _target_item_filter_value(item, "BACKTRACE_FLOW_NO:")),
                "flow_title": str(item.get("guangzhou_flow_title") or ""),
                "source_url": "",
                "state": state,
                "attempt_count": 1,
                "failure_taxonomy": list(item.get("failure_taxonomy") or []),
                "artifact_refs": {},
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    summary = {
        "pipeline_stage": pipeline_stage,
        "state_counts": _counts(row.get("state") for row in rows),
        "row_count": len(rows),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_version": 1,
        "manifest_kind": "guangzhou_pipeline_state_manifest",
        "adapter_id": "guangzhou-pipeline-state-v1",
        "created_at": created_at,
        "pipeline_stage": pipeline_stage,
        "items": rows,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    return {"manifest": manifest, "summary": summary}


def _build_manual_url_check_table(flow_url_manifest: Mapping[str, Any]) -> dict[str, Any]:
    manifest = flow_url_manifest.get("manifest") if isinstance(flow_url_manifest.get("manifest"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    for project in list(manifest.get("projects") or []):
        if not isinstance(project, Mapping):
            continue
        for flow in list(project.get("flow_matrix") or []):
            if not isinstance(flow, Mapping):
                continue
            for url in list(flow.get("detail_urls") or []):
                rows.append(
                    {
                        "project_id": str(project.get("project_id") or ""),
                        "project_name": str(project.get("project_name") or ""),
                        "flow_no": str(flow.get("flow_no") or ""),
                        "flow_title": str(flow.get("flow_title") or ""),
                        "published_dates": list(flow.get("published_dates") or []),
                        "url": str(url or ""),
                        "manual_check_state": "PENDING",
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                )
    return {
        "manifest": {
            "manifest_version": 1,
            "manifest_kind": "guangzhou_manual_url_check_table",
            "pipeline_stage": PIPELINE_STAGE_FLOW_URL_ONLY,
            "items": rows,
            "summary": {
                "url_count": len(rows),
                "project_count": len({row["project_id"] for row in rows if row["project_id"]}),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    }


def _maybe_resume_flow_url_manifest(
    *,
    root: Path,
    per_target_candidate_limit: int,
    created_at: str,
    resume: bool,
) -> dict[str, Any] | None:
    if not resume:
        return None
    state_path = root / "pipeline-state.json"
    if state_path.exists():
        state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        _mark_interrupted_pipeline_rows(state_payload, created_at=created_at)
        state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    run_path = root / "run-manifest.json"
    flow_path = root / "flow-url-manifest.json"
    if not run_path.exists() or not flow_path.exists():
        return None
    result = json.loads(run_path.read_text(encoding="utf-8"))
    flow_payload = json.loads(flow_path.read_text(encoding="utf-8"))
    flow_manifest = flow_payload.get("manifest") if isinstance(flow_payload.get("manifest"), Mapping) else {}
    if str(flow_manifest.get("pipeline_stage") or "") != PIPELINE_STAGE_FLOW_URL_ONLY:
        return None
    project_count = _int((flow_manifest.get("summary") or {}).get("project_count"))
    if project_count < max(1, per_target_candidate_limit):
        return None
    result["pipeline_resume"] = {
        "resume_state": "RESUMED_FROM_FLOW_URL_MANIFEST",
        "flow_url_manifest_path": str(flow_path),
        "pipeline_state_path": str(state_path),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return result


def _mark_interrupted_pipeline_rows(payload: dict[str, Any], *, created_at: str) -> None:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    rows = list(manifest.get("items") or [])
    changed = False
    for row in rows:
        if isinstance(row, dict) and str(row.get("state") or "") == "RUNNING":
            row["state"] = PARTIAL_RUN_INTERRUPTED
            row["interrupted_at"] = created_at
            changed = True
    if changed:
        manifest["summary"] = {
            **dict(manifest.get("summary") or {}),
            "state_counts": _counts(str(row.get("state") or "") for row in rows if isinstance(row, Mapping)),
        }


def _source_manifest(result: Mapping[str, Any]) -> dict[str, Any]:
    manifest = result.get("manifest")
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return {}


def _project_samples(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(manifest.get("project_sample_items") or [])
        if isinstance(item, Mapping)
        and str(item.get("source_profile_id") or "") == GUANGZHOU_PROFILE_ID
    ]


def _target_items(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(manifest.get("items") or [])
        if isinstance(item, Mapping)
        and (
            str(item.get("source_profile_id") or "") == GUANGZHOU_PROFILE_ID
            or str(item.get("required_fetch_profile_id_optional") or "") == GUANGZHOU_PROFILE_ID
        )
    ]


def _flatten_project_samples(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for item in items:
        samples.extend(
            dict(sample)
            for sample in list(item.get("project_sample_items") or [])
            if isinstance(sample, Mapping)
        )
    return samples


def _select_post_candidate_entries(samples: list[Mapping[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        if str(sample.get("document_kind") or "") not in {"candidate_notice", "award_result"}:
            continue
        key = _project_match_key(sample)
        if not key:
            continue
        grouped.setdefault(key, []).append(sample)
    seen: set[str] = set()
    for key, project_samples in grouped.items():
        if not key or key in seen:
            continue
        seen.add(key)
        row = dict(project_samples[0])
        row["present_document_kinds"] = _dedupe_strings(
            str(sample.get("document_kind") or "") for sample in project_samples
        )
        row["entry_source_urls"] = _dedupe_strings(str(sample.get("source_url") or "") for sample in project_samples)
        selected.append(row)
        if len(selected) >= max(1, limit):
            break
    return selected


def _backtrace_targets_for_entries(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        project_code = str(entry.get("source_project_code") or "").strip()
        project_name = str(entry.get("project_name") or "").strip()
        match_key = _project_match_key(entry)
        base_project_name = _base_guangzhou_project_name(project_name)
        query_variants = _backtrace_query_variants(entry, base_project_name=base_project_name)
        present_flow_nos = {
            str(entry.get("guangzhou_flow_no") or "")
        } | {
            _flow_no_for_document_kind(str(kind))
            for kind in list(entry.get("present_document_kinds") or [])
        }
        present_flow_nos.discard("")
        suffix = _slug(project_code or match_key or f"PROJECT-{index}")[:36]
        for module in GUANGZHOU_FLOW_MODULES:
            document_kind = str(module["document_kind"])
            flow_no = str(module["flow_no"])
            flow_code = str(module["flow_code"])
            flow_title = str(module["flow_title"])
            if flow_no in present_flow_nos:
                continue
            target_id = f"GZ-BACKTRACE-{suffix}-{flow_no}-{_document_kind_suffix(document_kind)}"
            filters = [
                "工程建设",
                flow_title,
                f"BACKTRACE_STAGE:{document_kind}",
                f"BACKTRACE_FLOW_NO:{flow_no}",
                f"BACKTRACE_FLOW_CODE:{flow_code}",
                f"BACKTRACE_PROJECT_KEY:{match_key}",
            ]
            if project_code:
                filters.append(f"BACKTRACE_PROJECT_CODE:{project_code}")
                filters.append(f"BACKTRACE_RELATION_GUID:{project_code}")
            if project_name:
                filters.append(f"BACKTRACE_PROJECT_NAME:{project_name}")
            if base_project_name:
                filters.append(f"BACKTRACE_BASE_PROJECT_NAME:{base_project_name}")
            filters.append("BACKTRACE_RELATION_SITE_GUID:7eb5f7f1-9041-43ad-8e13-8fcb82ea831a")
            filters.append("BACKTRACE_RELATION_CATEGORY_NUM:002001001")
            for variant in query_variants:
                filters.append(f"BACKTRACE_QUERY_VARIANT:{variant}")
            targets.append(
                {
                    "target_id": target_id,
                    "jurisdiction": "CN-GD",
                    "platform_name": "广州交易集团",
                    "entry_seed_id": "ENTRY-GUANGZHOU-YWTB",
                    "required_fetch_profile_id_optional": GUANGZHOU_PROFILE_ID,
                    "source_family": "local_public_resource_trading_center",
                    "project_type": "construction",
                    "document_kind": document_kind,
                    "target_count": 5,
                    "selection_filters": filters,
                    "base_project_name": base_project_name,
                    "backtrace_query_variants": query_variants,
                    "guangzhou_flow_no": flow_no,
                    "guangzhou_flow_title": flow_title,
                    "guangzhou_flow_code": flow_code,
                    "guangzhou_flow_folder": f"{flow_no}_{flow_title}",
                }
            )
    return {
        "target_version": 1,
        "target_set_id": "guangzhou-post-candidate-backtrace-v1",
        "minimum_total_sample_goal": len(targets),
        "created_from": "POST_CANDIDATE_BACKTRACE_V1",
        "target_policy": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "do_not_fabricate_project_urls": True,
        },
        "targets": targets,
    }


def _annotate_project_samples(
    samples: list[Mapping[str, Any]],
    *,
    target_items: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault(str(sample.get("project_id") or sample.get("target_id") or ""), []).append(sample)
    annotated: list[dict[str, Any]] = []
    target_items = list(target_items or [])
    for project_samples in grouped.values():
        document_kinds = {str(sample.get("document_kind") or "") for sample in project_samples}
        present_flow_nos = {_sample_flow_no(sample) for sample in project_samples}
        present_flow_nos.discard("")
        missing_flow_modules = [
            dict(module)
            for module in GUANGZHOU_FLOW_MODULES
            if str(module["flow_no"]) not in present_flow_nos
        ]
        missing = [str(module["document_kind"]) for module in missing_flow_modules]
        post_state = (
            "POST_CANDIDATE_ENTRY_PRESENT"
            if document_kinds & {"candidate_notice", "award_result"}
            else "POST_CANDIDATE_ENTRY_MISSING"
        )
        backtrace_state = "BACKTRACE_CORE_COMPLETE" if not missing else "BACKTRACE_PARTIAL"
        flow_state = "GUANGZHOU_FLOW_COMPLETE" if not missing_flow_modules else "GUANGZHOU_FLOW_PARTIAL"
        project_keys = {
            key
            for sample in project_samples
            for key in [
                _project_match_key(sample),
                str(sample.get("source_project_code") or ""),
                str(sample.get("project_match_key") or ""),
            ]
            if key
        }
        base_project_names = _dedupe_strings(
            str(sample.get("base_project_name") or "") for sample in project_samples
        )
        query_variants = _dedupe_strings(
            value
            for sample in project_samples
            for value in list(sample.get("backtrace_query_variants") or [])
        )
        match_reasons = _dedupe_strings(
            str(sample.get("backtrace_match_reason") or "") for sample in project_samples
        )
        attempts = [
            {
                "document_kind": str(sample.get("document_kind") or ""),
                "target_id": str(sample.get("parent_target_id") or sample.get("target_id") or ""),
                "source_url": str(sample.get("source_url") or ""),
                "target_execution_state": str(sample.get("target_execution_state") or ""),
                "detail_snapshot_count": _int(sample.get("detail_snapshot_count")),
                "attachment_snapshot_count": _int(sample.get("attachment_snapshot_count")),
                "failure_taxonomy": list(sample.get("failure_taxonomy") or []),
                "base_project_name": str(sample.get("base_project_name") or ""),
                "backtrace_query_variants": list(sample.get("backtrace_query_variants") or []),
                "backtrace_match_reason": str(sample.get("backtrace_match_reason") or ""),
                "guangzhou_flow_no": _sample_flow_no(sample),
                "guangzhou_flow_title": _sample_flow_title(sample),
                "guangzhou_flow_code": str(sample.get("guangzhou_flow_code") or sample.get("source_trading_process") or ""),
                "guangzhou_flow_folder": str(sample.get("guangzhou_flow_folder") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            for sample in project_samples
        ]
        attempt_keys = {(attempt["target_id"], attempt["document_kind"], attempt["source_url"]) for attempt in attempts}
        for target_item in target_items:
            target_key = _target_item_project_key(target_item)
            if not target_key or target_key not in project_keys:
                continue
            target_base_project_name = str(
                target_item.get("base_project_name") or _target_item_filter_value(target_item, "BACKTRACE_BASE_PROJECT_NAME:")
            )
            target_query_variants = list(target_item.get("backtrace_query_variants") or []) or _target_item_query_variants(
                target_item
            )
            attempt = {
                "document_kind": str(target_item.get("document_kind") or ""),
                "target_id": str(target_item.get("target_id") or ""),
                "source_url": "",
                "target_execution_state": str(target_item.get("target_execution_state") or ""),
                "detail_snapshot_count": _int(target_item.get("detail_snapshot_count")),
                "attachment_snapshot_count": _int(target_item.get("attachment_snapshot_count")),
                "failure_taxonomy": list(target_item.get("failure_taxonomy") or []),
                "base_project_name": target_base_project_name,
                "backtrace_query_variants": target_query_variants,
                "backtrace_match_reason": str(target_item.get("backtrace_match_reason") or ""),
                "guangzhou_flow_no": str(
                    target_item.get("guangzhou_flow_no") or _target_item_filter_value(target_item, "BACKTRACE_FLOW_NO:")
                ),
                "guangzhou_flow_title": str(target_item.get("guangzhou_flow_title") or ""),
                "guangzhou_flow_code": str(
                    target_item.get("guangzhou_flow_code") or _target_item_filter_value(target_item, "BACKTRACE_FLOW_CODE:")
                ),
                "guangzhou_flow_folder": str(target_item.get("guangzhou_flow_folder") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            key = (attempt["target_id"], attempt["document_kind"], attempt["source_url"])
            if key in attempt_keys:
                continue
            attempt_keys.add(key)
            attempts.append(attempt)
        for sample in project_samples:
            row = dict(sample)
            row["post_candidate_entry_state"] = post_state
            row["backtrace_stage_attempts"] = attempts
            row["matched_project_keys"] = _dedupe_strings(
                [
                    *list(row.get("matched_project_keys") or []),
                    row.get("source_project_code"),
                    row.get("project_match_key"),
                    _project_match_key(row),
                ]
            )
            row["base_project_name"] = str(
                row.get("base_project_name") or (base_project_names[0] if base_project_names else "")
            )
            row["backtrace_query_variants"] = _dedupe_strings(
                [
                    *list(row.get("backtrace_query_variants") or []),
                    *query_variants,
                ]
            )
            row["backtrace_match_reason"] = str(
                row.get("backtrace_match_reason") or (match_reasons[0] if match_reasons else "")
            )
            row["missing_stage_kinds"] = missing
            row["backtrace_completeness_state"] = backtrace_state
            row["guangzhou_flow_modules_present"] = _present_flow_modules(project_samples)
            row["guangzhou_flow_modules_missing"] = missing_flow_modules
            row["guangzhou_flow_completeness_state"] = flow_state
            annotated.append(row)
    return annotated


def _target_item_project_key(target_item: Mapping[str, Any]) -> str:
    for value in list(target_item.get("selection_filters") or []):
        text = str(value or "")
        if (
            text.startswith("BACKTRACE_RELATION_GUID:")
            or text.startswith("BACKTRACE_PROJECT_CODE:")
            or text.startswith("BACKTRACE_PROJECT_KEY:")
        ):
            return text.split(":", 1)[1].strip()
    return ""


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
    flow_no = _sample_flow_no(sample)
    for module in GUANGZHOU_FLOW_MODULES:
        if str(module["flow_no"]) == flow_no:
            return str(module["flow_title"])
    return ""


def _present_flow_modules(samples: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    present: dict[str, dict[str, str]] = {}
    for sample in samples:
        flow_no = _sample_flow_no(sample)
        if not flow_no:
            continue
        title = _sample_flow_title(sample)
        flow_code = str(sample.get("guangzhou_flow_code") or sample.get("source_trading_process") or "")
        document_kind = str(sample.get("document_kind") or "")
        present.setdefault(
            flow_no,
            {
                "flow_no": flow_no,
                "flow_code": flow_code,
                "flow_title": title,
                "document_kind": document_kind,
            },
        )
    return [present[key] for key in sorted(present)]


def _target_item_filter_value(target_item: Mapping[str, Any], prefix: str) -> str:
    for value in list(target_item.get("selection_filters") or []):
        text = str(value or "")
        if text.startswith(prefix):
            return text.split(":", 1)[1].strip()
    return ""


def _target_item_query_variants(target_item: Mapping[str, Any]) -> list[str]:
    return _dedupe_strings(
        str(value or "").split(":", 1)[1].strip()
        for value in list(target_item.get("selection_filters") or [])
        if str(value or "").startswith("BACKTRACE_QUERY_VARIANT:")
    )


def _backtrace_query_variants(entry: Mapping[str, Any], *, base_project_name: str = "") -> list[str]:
    candidates: list[str] = []
    candidates.extend(str(value or "") for value in list(entry.get("backtrace_query_variants") or []))
    candidates.extend(
        [
            str(entry.get("source_project_code") or ""),
            str(entry.get("project_match_key") or ""),
            base_project_name,
            str(entry.get("project_name") or ""),
            _remove_parenthetical_text(base_project_name),
            _short_project_query(base_project_name),
        ]
    )
    return _dedupe_strings(value for value in candidates if str(value or "").strip())[:8]


def _base_guangzhou_project_name(value: Any) -> str:
    text = str(value or "").strip()
    for marker in (
        "中标候选人公示",
        "中标结果公告",
        "中标结果",
        "中标信息",
        "招标公告",
        "重新招标公告",
        "变更公告",
        "补充公告",
        "答疑公告",
        "澄清公告",
        "投标文件公开",
        "开标记录",
    ):
        text = text.replace(marker, "")
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _remove_parenthetical_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[（(][^（）()]{1,40}[）)]", "", text)
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _short_project_query(value: Any) -> str:
    text = _remove_parenthetical_text(value)
    text = re.sub(r"(第[一二三四五六七八九十0-9]+次|标段[一二三四五六七八九十0-9]+|第[一二三四五六七八九十0-9]+标段)", "", text)
    text = re.sub(r"(工程监理服务|设计施工总承包|勘察设计施工总承包及运营|施工总承包|工程施工|施工|监理服务)$", "", text)
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _summary(
    *,
    project_samples: list[Mapping[str, Any]],
    items: list[Mapping[str, Any]],
    selected_entries: list[Mapping[str, Any]],
) -> dict[str, Any]:
    project_ids = {str(sample.get("project_id") or "") for sample in project_samples if str(sample.get("project_id") or "")}
    return {
        "target_execution_bucket_count": len(items),
        "project_sample_count": len(project_samples),
        "unique_project_count": len(project_ids),
        "selected_post_candidate_entry_count": len(selected_entries),
        "project_sample_document_kind_counts": _counts(str(sample.get("document_kind") or "") for sample in project_samples),
        "guangzhou_flow_no_counts": _counts(str(sample.get("guangzhou_flow_no") or "") for sample in project_samples),
        "guangzhou_flow_completeness_state_counts": _counts(
            str(sample.get("guangzhou_flow_completeness_state") or "") for sample in project_samples
        ),
        "post_candidate_entry_state_counts": _counts(str(sample.get("post_candidate_entry_state") or "") for sample in project_samples),
        "backtrace_completeness_state_counts": _counts(str(sample.get("backtrace_completeness_state") or "") for sample in project_samples),
        "detail_snapshot_count": sum(_int(sample.get("detail_snapshot_count")) for sample in project_samples),
        "attachment_snapshot_count": sum(_int(sample.get("attachment_snapshot_count")) for sample in project_samples),
        "failure_taxonomy_counts": _counts(
            reason
            for sample in project_samples
            for reason in list(sample.get("failure_taxonomy") or [])
        ),
        "backtrace_match_reason_counts": _counts(str(sample.get("backtrace_match_reason") or "") for sample in project_samples),
        "download_enabled": True,
        "fetch_public_urls_enabled": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _coverage_state(project_samples: list[Mapping[str, Any]]) -> str:
    if not project_samples:
        return "NO_REAL_SNAPSHOT_CAPTURED_REVIEW"
    if any(_int(sample.get("detail_snapshot_count")) > 0 for sample in project_samples):
        return "PARTIAL_REAL_SNAPSHOT_COVERAGE_REVIEW"
    return "NO_REAL_SNAPSHOT_CAPTURED_REVIEW"


def _project_match_key(sample: Mapping[str, Any]) -> str:
    for value in (
        sample.get("source_project_code"),
        sample.get("project_match_key"),
        sample.get("project_id"),
        sample.get("project_name"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _document_kind_suffix(document_kind: str) -> str:
    return {
        "bid_plan": "BID-PLAN",
        "tender_file_publicity": "TENDER-FILE-PUBLICITY",
        "tender_file": "TENDER",
        "clarification_notice": "CLARIFICATION",
        "opening_info": "OPENING",
        "qualification_review_result": "QUALIFICATION",
        "candidate_notice": "CANDIDATE",
        "bid_file_publicity": "BID-FILE-PUBLICITY",
        "award_result": "AWARD",
        "award_info": "AWARD-INFO",
        "contract_public_info": "CONTRACT",
        "project_exception": "EXCEPTION",
    }.get(document_kind, _slug(document_kind))


def _flow_no_for_document_kind(document_kind: str) -> str:
    for module in GUANGZHOU_FLOW_MODULES:
        if str(module["document_kind"]) == document_kind:
            return str(module["flow_no"])
    return ""


def _normalize_pipeline_stage(value: Any) -> str:
    text = str(value or PIPELINE_STAGE_FULL).strip()
    return PIPELINE_STAGES.get(text.lower(), PIPELINE_STAGE_FULL)


def _pipeline_stage_state_suffix(value: str) -> str:
    return {
        PIPELINE_STAGE_FLOW_URL_ONLY: "FLOW_URL_ONLY",
        PIPELINE_STAGE_ATTACHMENT_LIST: "ATTACHMENT_LIST",
        PIPELINE_STAGE_DOWNLOAD: "DOWNLOAD",
        PIPELINE_STAGE_PARSE: "PARSE",
        PIPELINE_STAGE_FULL: "FULL",
    }.get(value, _slug(value))


def _target_source_profile_id(plan_item: Mapping[str, Any]) -> str:
    return str(
        plan_item.get("required_fetch_profile_id_optional")
        or plan_item.get("source_profile_id")
        or plan_item.get("fetch_profile_id_optional")
        or ""
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = [value]
    return _dedupe_strings(str(item or "") for item in raw)


def _profile_report_refs(profile_reports: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for report in profile_reports:
        refs.append(
            {
                "profile_id": str(report.get("profile_id") or ""),
                "status": str(report.get("status") or ""),
                "candidate_count": _int(report.get("candidate_count")),
                "profile_api_discovery_state": str(report.get("profile_api_discovery_state") or ""),
                "public_api_process_attempts": list(report.get("public_api_process_attempts") or []),
                "operator_diagnosis": list(report.get("operator_diagnosis") or []),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return refs


def _discovery_failure_taxonomy(profile_reports: list[Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for report in profile_reports:
        status = str(report.get("status") or "")
        if status in {"FAILED", "DEGRADED", "SOURCE_PROFILE_NOT_CONFIGURED", "SOURCE_NOT_CONFIGURED"}:
            reasons.append(f"discovery_profile_{status.lower()}")
        for attempt in list(report.get("public_api_process_attempts") or []):
            if not isinstance(attempt, Mapping):
                continue
            reasons.extend(str(item or "") for item in list(attempt.get("failure_taxonomy") or []))
            if str(attempt.get("state") or "") == "FAILED":
                reasons.append("guangzhou_flow_url_discovery_failed")
    return _dedupe_strings(reasons)


def _candidate_refs(candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_key": str(candidate.get("candidate_key") or ""),
            "project_id": str(candidate.get("project_id") or ""),
            "project_name": str(candidate.get("project_name") or ""),
            "source_url": str(candidate.get("source_url") or ""),
            "source_project_code": str(candidate.get("source_project_code") or ""),
            "project_match_key": str(candidate.get("project_match_key") or ""),
            "published_at_optional": str(candidate.get("published_at_optional") or ""),
            "guangzhou_flow_no": str(candidate.get("guangzhou_flow_no") or ""),
            "guangzhou_flow_title": str(candidate.get("guangzhou_flow_title") or ""),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for candidate in candidates
    ]


def _empty_parse_summary() -> dict[str, Any]:
    return {
        "stage3_parse_success_count": 0,
        "stage3_parse_failed_count": 0,
        "attachment_missing_review_count": 0,
        "unknown_attachment_count": 0,
        "file_parse_attributions": [],
        "text_probe": "",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _clip_text(value: Any, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(0, limit)]


def _slug(value: Any) -> str:
    text = str(value or "").strip()
    token = "".join(char.upper() if char.isascii() and char.isalnum() else "-" for char in text)
    token = "-".join(part for part in token.split("-") if part)
    return token or f"H{_fingerprint(text)[:12].upper()}"


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou post-candidate backtrace v1.")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--targets-json")
    parser.add_argument("--seed-json")
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--target-backend", default="json-file")
    parser.add_argument("--per-target-candidate-limit", type=int, default=3)
    parser.add_argument("--pipeline-stage", default=PIPELINE_STAGE_FULL, choices=sorted(PIPELINE_STAGES.values()))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output-json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_post_candidate_backtrace(
        output_root=args.output_root,
        targets_json=args.targets_json,
        seed_json=args.seed_json,
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
        target_backend=args.target_backend,
        execute=args.execute,
        per_target_candidate_limit=args.per_target_candidate_limit,
        pipeline_stage=args.pipeline_stage,
        resume=args.resume,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "run-manifest.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "guangzhou post-candidate backtrace "
            f"{result['guangzhou_post_candidate_backtrace_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())
