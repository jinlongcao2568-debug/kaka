from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage1_tasking.real_candidate_discovery import RealPublicCandidateDiscoveryService
from stage2_ingestion.real_candidate_capture import (
    RealCandidateStage2CaptureRepository,
    RealCandidateStage2CaptureService,
)
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.evaluation_corpus import default_evaluation_seed_path
from storage.evaluation_real_sample_plan import (
    PLAN_READY,
    build_evaluation_real_sample_plan,
    default_evaluation_real_project_sample_targets_path,
)
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.repositories.operator_action_repo import OperatorActionRepository


EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_OBJECT_TYPE = "evaluation_real_project_sample_execution_manifest"
EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_VERSION = 1
EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_RULESET_ID = "evaluation-real-project-sample-execution-v1"
EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_ADAPTER_ID = "evaluation-real-sample-controlled-execution-runner"

DEFAULT_SMALL_REAL_SAMPLE_TARGET_IDS = (
    "REAL-GD-TENDER-001",
    "REAL-GD-CANDIDATE-001",
    "REAL-GD-AWARD-001",
    "REAL-JS-TENDER-001",
    "REAL-JS-CANDIDATE-001",
    "REAL-HB-TENDER-001",
    "REAL-ZJ-CANDIDATE-001",
    "REAL-SD-AWARD-001",
    "REAL-SH-TENDER-001",
    "REAL-GP-FAILED-BID-001",
    "REAL-GP-COMPLAINT-001",
    "REAL-GGZY-FLOW-RETENDER-001",
    "REAL-OFFICIAL-CASE-FAIRNESS-001",
)

EXECUTION_READY = "EXECUTION_READY"
DISCOVERY_NO_MATCH_REVIEW = "DISCOVERY_NO_MATCH_REVIEW"
DISCOVERY_FAILED_CLOSED = "DISCOVERY_FAILED_CLOSED"
CAPTURE_PARTIAL_REVIEW = "CAPTURE_PARTIAL_REVIEW"
CAPTURED_WITH_SNAPSHOTS = "CAPTURED_WITH_SNAPSHOTS"


def build_evaluation_real_sample_execution(
    *,
    targets_json: str | Path | None = None,
    seed_json: str | Path | None = None,
    database_url: str | None = None,
    target_backend: str = "postgresql",
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    execute: bool = False,
    created_at: str | None = None,
    target_limit: int | None = None,
    target_ids: list[str] | tuple[str, ...] | str | None = None,
    per_target_candidate_limit: int = 1,
    discovery_service: RealPublicCandidateDiscoveryService | None = None,
    capture_service: RealCandidateStage2CaptureService | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    plan = build_evaluation_real_sample_plan(
        targets_json=targets_json,
        seed_json=seed_json,
        database_url=None,
        target_backend=target_backend,
        execute=False,
        created_at=created,
    )
    if execute and not plan.get("safe_to_execute"):
        raise RuntimeError(
            "evaluation real sample execution is not safe to execute: "
            + ", ".join(str(item) for item in list(plan.get("blocking_reasons") or []))
        )

    plan_items = [
        dict(item)
        for item in list((plan.get("manifest") or {}).get("items") or [])
        if str(item.get("plan_state") or "") == PLAN_READY
    ]
    requested_target_ids = _target_id_list(target_ids)
    if requested_target_ids:
        requested_set = set(requested_target_ids)
        plan_items = [
            item
            for item in plan_items
            if str(item.get("target_id") or "") in requested_set
        ]
    if target_limit is not None:
        plan_items = plan_items[: max(0, int(target_limit))]
    selected_target_ids = [str(item.get("target_id") or "") for item in plan_items]
    missing_requested_target_ids = [
        target_id
        for target_id in requested_target_ids
        if target_id not in selected_target_ids
    ]

    runner_discovery_service = discovery_service or RealPublicCandidateDiscoveryService()
    runner_capture_service = capture_service or _build_capture_service(
        target_backend=target_backend,
        database_url=database_url,
        storage_path=storage_path,
        object_storage_path=object_storage_path,
    )
    items: list[dict[str, Any]] = []
    for item in plan_items:
        if not execute:
            items.append(_dry_run_execution_item(item))
            continue
        items.append(
            _execute_target_item(
                item,
                discovery_service=runner_discovery_service,
                capture_service=runner_capture_service,
                created_at=created,
                per_target_candidate_limit=per_target_candidate_limit,
            )
        )

    manifest = _build_execution_manifest(
        plan=plan,
        items=items,
        created_at=created,
        execute=execute,
        database_url=database_url,
        target_backend=target_backend,
        requested_target_ids=requested_target_ids,
        selected_target_ids=selected_target_ids,
        missing_requested_target_ids=missing_requested_target_ids,
        target_limit=target_limit,
        per_target_candidate_limit=per_target_candidate_limit,
    )
    result = {
        "real_sample_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": bool(plan.get("safe_to_execute")),
        "blocking_reasons": list(plan.get("blocking_reasons") or []),
        "manifest": manifest,
        "summary": manifest["summary"],
        "execution": {
            "executed": execute,
            "target_mutation_enabled": False,
            "database_write_enabled": False,
            "download_enabled": execute,
            "fetch_public_urls_enabled": execute,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
            "storage_path_optional": str(storage_path or ""),
            "object_storage_path_optional": str(object_storage_path or ""),
        },
    }
    if execute and database_url:
        settings = Settings(
            storage_backend=target_backend,
            storage_path_optional=str(storage_path) if storage_path else None,
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(object_storage_path) if object_storage_path else None,
        )
        session = DatabaseSession(settings=settings)
        try:
            with session.bulk_write():
                session.upsert_record(_execution_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                **result["execution"],
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_evaluation_real_project_sample_execution_manifest_count": 1,
            }
        finally:
            session.close()
    return result


def _dry_run_execution_item(plan_item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "target_id": str(plan_item.get("target_id") or ""),
        "jurisdiction": str(plan_item.get("jurisdiction") or ""),
        "platform_name": str(plan_item.get("platform_name") or ""),
        "document_kind": str(plan_item.get("document_kind") or ""),
        "source_family": str(plan_item.get("source_family") or ""),
        "source_profile_id": _target_source_profile_id(plan_item),
        "selection_filters": _string_list(plan_item.get("selection_filters")),
        "target_count": _int_value(plan_item.get("target_count"), default=0),
        "target_execution_state": EXECUTION_READY,
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "discovery_candidate_count": 0,
        "candidate_refs": [],
        "detail_snapshot_refs": [],
        "attachment_snapshot_refs": [],
        "parse_summary": _empty_parse_summary(),
        "failure_taxonomy": [],
    }


def _build_capture_service(
    *,
    target_backend: str,
    database_url: str | None,
    storage_path: str | Path | None,
    object_storage_path: str | Path | None,
) -> RealCandidateStage2CaptureService:
    settings = Settings(
        storage_backend=target_backend,
        storage_path_optional=str(storage_path) if storage_path else None,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage_path) if object_storage_path else None,
    )
    session = DatabaseSession(settings=settings)
    action_repository = OperatorActionRepository(session=session)
    capture_repository = RealCandidateStage2CaptureRepository(repository=action_repository)
    object_repository = ObjectStorageRepository(session=session, settings=settings)
    return RealCandidateStage2CaptureService(
        object_repository=object_repository,
        repository=capture_repository,
    )


def _execute_target_item(
    plan_item: Mapping[str, Any],
    *,
    discovery_service: RealPublicCandidateDiscoveryService,
    capture_service: RealCandidateStage2CaptureService,
    created_at: str,
    per_target_candidate_limit: int,
) -> dict[str, Any]:
    target_id = str(plan_item.get("target_id") or "")
    profile_id = _target_source_profile_id(plan_item)
    candidate_limit = max(1, min(_int_value(plan_item.get("target_count"), default=1), per_target_candidate_limit))
    base = _dry_run_execution_item(plan_item)
    payload = {
        "region_code": _target_region_code(plan_item),
        "region_codes": [_target_region_code(plan_item)],
        "project_type": str(plan_item.get("project_type") or "construction"),
        "project_types": [str(plan_item.get("project_type") or "construction")],
        "candidate_limit": candidate_limit,
        "discovery_candidate_limit": candidate_limit,
        "discovery_profile_limit_per_region": 1,
        "source_profile_ids": [profile_id] if profile_id else [],
        "evaluation_corpus_mode": True,
        "evaluation_document_kind": str(plan_item.get("document_kind") or ""),
        "selection_filters": _string_list(plan_item.get("selection_filters")),
        "candidate_discovery_run_id": f"B7-REAL-SAMPLE-{_slug(target_id)}-{_hash_text(created_at, 8)}",
        "now": created_at,
    }
    try:
        discovery_result = discovery_service.discover(payload, now=created_at)
    except Exception as exc:  # pragma: no cover - defensive path covered by manifest state tests through fake failures.
        return {
            **base,
            "target_execution_state": DISCOVERY_FAILED_CLOSED,
            "failure_taxonomy": [f"discovery_exception:{exc}"],
        }

    candidates = [dict(item) for item in list(discovery_result.get("candidates") or []) if isinstance(item, Mapping)]
    profile_reports = [dict(item) for item in list(discovery_result.get("profile_reports") or []) if isinstance(item, Mapping)]
    if not candidates:
        profile_failed_closed = any(
            str(row.get("status") or "")
            in {"FAILED", "DEGRADED", "SOURCE_PROFILE_NOT_CONFIGURED", "SOURCE_NOT_CONFIGURED"}
            for row in profile_reports
        )
        return {
            **base,
            "target_execution_state": DISCOVERY_FAILED_CLOSED if profile_failed_closed else DISCOVERY_NO_MATCH_REVIEW,
            "discovery_state": str(discovery_result.get("discovery_state") or "NO_CANDIDATES"),
            "discovery_profile_reports": _profile_report_refs(profile_reports),
            "failure_taxonomy": _discovery_failure_taxonomy(profile_reports) or ["discovery_no_match"],
        }

    selected_candidates = candidates[:candidate_limit]
    try:
        capture_result = capture_service.capture_candidates(
            selected_candidates,
            now=created_at,
            detail_capture_limit=candidate_limit,
            attachment_capture_limit=None,
            reuse_existing_captures=True,
            reparse_existing_snapshots=True,
        )
    except Exception as exc:  # pragma: no cover - defensive path covered by fake failure tests if needed.
        return {
            **base,
            "target_execution_state": CAPTURE_PARTIAL_REVIEW,
            "discovery_state": str(discovery_result.get("discovery_state") or ""),
            "discovery_candidate_count": len(candidates),
            "candidate_refs": _candidate_refs(selected_candidates),
            "failure_taxonomy": _discovery_failure_taxonomy(profile_reports) + [f"capture_exception:{exc}"],
        }

    capture_summary = _capture_manifest_summary(capture_result)
    state = (
        CAPTURED_WITH_SNAPSHOTS
        if capture_summary["detail_snapshot_count"] > 0
        and capture_summary["detail_capture_failed_count"] == 0
        and capture_summary["stage3_parse_failed_count"] == 0
        else CAPTURE_PARTIAL_REVIEW
    )
    return {
        **base,
        "target_execution_state": state,
        "discovery_state": str(discovery_result.get("discovery_state") or ""),
        "discovery_candidate_count": len(candidates),
        "discovery_profile_reports": _profile_report_refs(profile_reports),
        "candidate_refs": _candidate_refs(selected_candidates),
        "detail_snapshot_refs": capture_summary["detail_snapshot_refs"],
        "attachment_snapshot_refs": capture_summary["attachment_snapshot_refs"],
        "parse_summary": capture_summary["parse_summary"],
        "failure_taxonomy": _dedupe_strings(
            _discovery_failure_taxonomy(profile_reports) + capture_summary["failure_taxonomy"]
        ),
    }


def _build_execution_manifest(
    *,
    plan: Mapping[str, Any],
    items: list[dict[str, Any]],
    created_at: str,
    execute: bool,
    database_url: str | None,
    target_backend: str,
    requested_target_ids: list[str],
    selected_target_ids: list[str],
    missing_requested_target_ids: list[str],
    target_limit: int | None,
    per_target_candidate_limit: int,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "plan_manifest_id": (plan.get("manifest") or {}).get("manifest_id"),
            "execute": execute,
            "requested_target_ids": requested_target_ids,
            "target_limit": target_limit,
            "per_target_candidate_limit": per_target_candidate_limit,
            "items": items,
        }
    )
    manifest = {
        "manifest_version": EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_VERSION,
        "ruleset_id": EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_RULESET_ID,
        "adapter_id": EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_ADAPTER_ID,
        "manifest_id": f"EVALUATION-REAL-PROJECT-SAMPLE-EXECUTION-{fingerprint[:16]}",
        "manifest_kind": EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_OBJECT_TYPE,
        "created_at": created_at,
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "plan_manifest_id": str((plan.get("manifest") or {}).get("manifest_id") or ""),
        "plan_fingerprint": str((plan.get("manifest") or {}).get("plan_fingerprint") or ""),
        "database_url_redacted": _redact_database_url(database_url),
        "target_storage_backend": target_backend,
        "requested_target_ids": requested_target_ids,
        "selected_target_ids": selected_target_ids,
        "missing_requested_target_ids": missing_requested_target_ids,
        "target_limit": target_limit if target_limit is not None else "ALL_PLAN_READY_TARGETS",
        "per_target_candidate_limit": per_target_candidate_limit,
        "items": items,
        "sample_items": items[:80],
        "summary": _summary(items, execute=execute),
        "coverage_quality_summary": _coverage_quality_summary(items, execute=execute),
        "safety": _safety(execute=execute),
    }
    manifest["summary"] = {
        **manifest["summary"],
        "coverage_quality_state": manifest["coverage_quality_summary"]["coverage_quality_state"],
        "sample_quality_reasons": manifest["coverage_quality_summary"]["sample_quality_reasons"],
        "real_snapshot_covered_target_count": manifest["coverage_quality_summary"]["captured_target_count"],
    }
    manifest["manifest_sha256"] = _manifest_sha256(manifest)
    return manifest


def _execution_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    manifest_id = str(manifest["manifest_id"])
    return PersistedRecord(
        object_type=EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_OBJECT_TYPE,
        record_id=manifest_id,
        stage_scope=0,
        project_id=None,
        object_refs={
            "manifest_id": manifest_id,
            "plan_manifest_id": str(manifest.get("plan_manifest_id") or ""),
        },
        decision_states={"evaluation_real_project_sample_execution_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest.get("manifest_sha256") or "")},
        governed_state={
            "primary_status": "EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_READY",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_release_enabled": False,
        },
        writeback_state={
            "download_enabled": bool(manifest.get("execute")),
            "fetch_public_urls_enabled": bool(manifest.get("execute")),
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at or build_persisted_at(),
    )


def _capture_manifest_summary(capture_result: Mapping[str, Any]) -> dict[str, Any]:
    captures = [dict(item) for item in list(capture_result.get("captures") or []) if isinstance(item, Mapping)]
    detail_snapshot_refs: list[dict[str, Any]] = []
    attachment_snapshot_refs: list[dict[str, Any]] = []
    failure_taxonomy: list[str] = []
    document_state_values: list[str] = []
    version_state_values: list[str] = []
    document_quality_reasons: list[str] = []
    download_manifest_quality_reasons: list[str] = []
    unknown_attachment_count = 0
    attachment_missing_review_count = 0
    clarification_version_review_count = 0
    attachment_ocr_required_count = 0
    attachment_ocr_extracted_count = 0
    for capture in captures:
        candidate_key = str(capture.get("candidate_key") or "")
        detail_snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
        document_summary = dict(capture.get("document_completeness_summary") or {})
        document_state = str(
            capture.get("document_completeness_state")
            or document_summary.get("document_completeness_state")
            or ""
        )
        version_state = str(
            capture.get("notice_version_chain_state")
            or document_summary.get("notice_version_chain_state")
            or ""
        )
        download_archive_manifest = dict(
            capture.get("download_archive_manifest")
            or document_summary.get("download_archive_manifest")
            or {}
        )
        fields = dict(capture.get("detail_fields") or {})
        attachment_ocr_required_count += _int_value(
            capture.get("attachment_ocr_required_count")
            or fields.get("attachment_ocr_required_count"),
            default=0,
        )
        attachment_ocr_extracted_count += _int_value(
            capture.get("attachment_ocr_extracted_count")
            or fields.get("attachment_ocr_extracted_count"),
            default=0,
        )
        if document_state:
            document_state_values.append(document_state)
        if version_state:
            version_state_values.append(version_state)
        if document_state in {
            "DETAIL_SNAPSHOT_MISSING_REVIEW",
            "ATTACHMENTS_NOT_CAPTURED_REVIEW",
            "PARTIAL_REVIEW_REQUIRED",
        }:
            attachment_missing_review_count += 1
        if version_state in {"VERSION_REVIEW_REQUIRED", "CLARIFICATION_OR_ADDENDUM_PRESENT"}:
            clarification_version_review_count += 1
        for reason in list(capture.get("document_quality_reasons") or document_summary.get("document_quality_reasons") or []):
            if str(reason):
                document_quality_reasons.append(str(reason))
        for reason in list(download_archive_manifest.get("quality_reasons") or []):
            if str(reason):
                download_manifest_quality_reasons.append(str(reason))
                if str(reason) in {"unknown_attachment_format", "unknown_attachment_role"}:
                    unknown_attachment_count += 1
        if detail_snapshot_id:
            detail_snapshot_refs.append(
                {
                    "candidate_key": candidate_key,
                    "snapshot_id": detail_snapshot_id,
                    "source_url": str(capture.get("source_url") or ""),
                    "parse_state": str(capture.get("stage3_parse_state") or ""),
                    "document_completeness_state": document_state,
                    "notice_version_chain_state": version_state,
                    "download_archive_manifest_quality_state": str(
                        download_archive_manifest.get("manifest_quality_state")
                        or download_archive_manifest.get("document_quality_state")
                        or ""
                    ),
                    "download_archive_manifest_quality_reasons": _dedupe_strings(download_manifest_quality_reasons),
                }
            )
        failure_taxonomy.extend(str(item) for item in list(capture.get("stage3_parse_error_taxonomy") or []) if str(item))
        for attachment in list(capture.get("attachment_captures") or []):
            if not isinstance(attachment, Mapping):
                continue
            snapshot_id = str(attachment.get("attachment_snapshot_id_optional") or attachment.get("snapshot_id") or "")
            if snapshot_id:
                attachment_parse_state = str(attachment.get("parse_state") or attachment.get("stage3_parse_state") or "")
                if attachment_parse_state in {"OCR_REQUIRED", "OCR_ENGINE_UNAVAILABLE"}:
                    attachment_ocr_required_count += 1
                attachment_snapshot_refs.append(
                    {
                        "candidate_key": candidate_key,
                        "snapshot_id": snapshot_id,
                        "attachment_url": str(attachment.get("attachment_url") or attachment.get("url") or ""),
                        "parse_state": attachment_parse_state,
                        "attachment_role_type": str(attachment.get("attachment_role_type") or ""),
                    }
                )
            for key in (
                "attachment_blocker_class",
                "attachment_blocker_reason",
                "attachment_capture_status",
            ):
                value = str(attachment.get(key) or "")
                if value and value not in {"SUCCESS", "FETCHED", "PARSED"}:
                    failure_taxonomy.append(value)
    detail_failure_summary = dict(capture_result.get("detail_capture_failure_summary") or {})
    for reason, count in detail_failure_summary.items():
        failure_taxonomy.append(f"detail_capture_failure:{reason}:{count}")
    return {
        "detail_snapshot_count": _int_value(capture_result.get("detail_snapshot_count"), default=len(detail_snapshot_refs)),
        "attachment_snapshot_count": _int_value(
            capture_result.get("attachment_snapshot_count"),
            default=len(attachment_snapshot_refs),
        ),
        "detail_capture_failed_count": _int_value(capture_result.get("detail_capture_failed_count"), default=0),
        "stage3_parse_success_count": _int_value(capture_result.get("stage3_parse_success_count"), default=0),
        "stage3_parse_failed_count": _int_value(capture_result.get("stage3_parse_failed_count"), default=0),
        "ocr_required_count": _count_ocr_required(capture_result),
        "detail_snapshot_refs": detail_snapshot_refs,
        "attachment_snapshot_refs": attachment_snapshot_refs,
        "parse_summary": {
            "stage3_parse_success_count": _int_value(capture_result.get("stage3_parse_success_count"), default=0),
            "stage3_parse_failed_count": _int_value(capture_result.get("stage3_parse_failed_count"), default=0),
            "ocr_required_count": _count_ocr_required(capture_result),
            "attachment_ocr_required_count": attachment_ocr_required_count,
            "attachment_ocr_extracted_count": attachment_ocr_extracted_count,
            "document_completeness_state_counts": _counts(document_state_values),
            "notice_version_chain_state_counts": _counts(version_state_values),
            "document_quality_reasons": _dedupe_strings(document_quality_reasons),
            "download_archive_quality_reasons": _dedupe_strings(download_manifest_quality_reasons),
            "attachment_missing_review_count": attachment_missing_review_count,
            "clarification_version_review_count": clarification_version_review_count,
            "unknown_attachment_count": unknown_attachment_count,
        },
        "failure_taxonomy": _dedupe_strings(failure_taxonomy),
    }


def _candidate_refs(candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for candidate in candidates:
        refs.append(
            {
                "candidate_key": str(candidate.get("candidate_key") or ""),
                "project_id": str(candidate.get("project_id") or ""),
                "notice_id": str(candidate.get("notice_id") or ""),
                "project_name": str(candidate.get("project_name") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "source_profile_id": str(candidate.get("source_profile_id") or ""),
                "notice_stage": str(candidate.get("notice_stage") or ""),
            }
        )
    return refs


def _profile_report_refs(profile_reports: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "region_code": str(row.get("region_code") or ""),
            "profile_id": str(row.get("profile_id") or ""),
            "entry_url": str(row.get("entry_url") or ""),
            "status": str(row.get("status") or ""),
            "failure_reason": str(row.get("failure_reason") or ""),
            "candidate_count": _int_value(row.get("candidate_count"), default=0),
        }
        for row in profile_reports
    ]


def _discovery_failure_taxonomy(profile_reports: list[Mapping[str, Any]]) -> list[str]:
    failures: list[str] = []
    for row in profile_reports:
        status = str(row.get("status") or "")
        reason = str(row.get("failure_reason") or "")
        if status in {"FAILED", "DEGRADED", "SOURCE_PROFILE_NOT_CONFIGURED", "SOURCE_NOT_CONFIGURED"}:
            failures.append(f"discovery_profile:{status}:{reason or 'unknown'}")
    return _dedupe_strings(failures)


def _summary(items: list[Mapping[str, Any]], *, execute: bool) -> dict[str, Any]:
    return {
        "target_execution_bucket_count": len(items),
        "execution_state_counts": _counts(str(item.get("target_execution_state") or "") for item in items),
        "document_kind_bucket_counts": _counts(str(item.get("document_kind") or "") for item in items),
        "jurisdiction_bucket_counts": _counts(str(item.get("jurisdiction") or "") for item in items),
        "discovery_candidate_count": sum(_int_value(item.get("discovery_candidate_count"), default=0) for item in items),
        "detail_snapshot_count": sum(
            len(list(item.get("detail_snapshot_refs") or []))
            for item in items
            if isinstance(item.get("detail_snapshot_refs"), list)
        ),
        "attachment_snapshot_count": sum(
            len(list(item.get("attachment_snapshot_refs") or []))
            for item in items
            if isinstance(item.get("attachment_snapshot_refs"), list)
        ),
        "stage3_parse_success_count": sum(
            _int_value((item.get("parse_summary") or {}).get("stage3_parse_success_count"), default=0)
            for item in items
            if isinstance(item.get("parse_summary"), Mapping)
        ),
        "stage3_parse_failed_count": sum(
            _int_value((item.get("parse_summary") or {}).get("stage3_parse_failed_count"), default=0)
            for item in items
            if isinstance(item.get("parse_summary"), Mapping)
        ),
        "ocr_required_count": sum(
            _int_value((item.get("parse_summary") or {}).get("ocr_required_count"), default=0)
            for item in items
            if isinstance(item.get("parse_summary"), Mapping)
        ),
        "attachment_ocr_required_count": sum(
            _int_value((item.get("parse_summary") or {}).get("attachment_ocr_required_count"), default=0)
            for item in items
            if isinstance(item.get("parse_summary"), Mapping)
        ),
        "attachment_missing_review_count": sum(
            _int_value((item.get("parse_summary") or {}).get("attachment_missing_review_count"), default=0)
            for item in items
            if isinstance(item.get("parse_summary"), Mapping)
        ),
        "clarification_version_review_count": sum(
            _int_value((item.get("parse_summary") or {}).get("clarification_version_review_count"), default=0)
            for item in items
            if isinstance(item.get("parse_summary"), Mapping)
        ),
        "unknown_attachment_count": sum(
            _int_value((item.get("parse_summary") or {}).get("unknown_attachment_count"), default=0)
            for item in items
            if isinstance(item.get("parse_summary"), Mapping)
        ),
        "download_enabled": execute,
        "fetch_public_urls_enabled": execute,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
    }


def _coverage_quality_summary(items: list[Mapping[str, Any]], *, execute: bool) -> dict[str, Any]:
    state_counts = _counts(str(item.get("target_execution_state") or "") for item in items)
    failure_values: list[str] = []
    site_values: list[str] = []
    target_bucket_values: list[str] = []
    captured_target_count = 0
    partial_target_count = 0
    ocr_blocked_count = 0
    detail_snapshot_count = 0
    attachment_snapshot_count = 0
    for item in items:
        target_bucket_values.append(str(item.get("document_kind") or "UNKNOWN_DOCUMENT_KIND"))
        site_values.append(str(item.get("source_profile_id") or item.get("source_family") or "UNKNOWN_SOURCE"))
        state = str(item.get("target_execution_state") or "")
        if state == CAPTURED_WITH_SNAPSHOTS:
            captured_target_count += 1
        if state in {CAPTURE_PARTIAL_REVIEW, DISCOVERY_NO_MATCH_REVIEW, DISCOVERY_FAILED_CLOSED}:
            partial_target_count += 1
        detail_snapshot_count += len(list(item.get("detail_snapshot_refs") or []))
        attachment_snapshot_count += len(list(item.get("attachment_snapshot_refs") or []))
        parse_summary = item.get("parse_summary")
        if isinstance(parse_summary, Mapping):
            ocr_blocked_count += _int_value(parse_summary.get("ocr_required_count"), default=0)
            ocr_blocked_count += _int_value(parse_summary.get("attachment_ocr_required_count"), default=0)
        failure_values.extend(str(value) for value in list(item.get("failure_taxonomy") or []) if str(value))

    quality_reasons: list[str] = []
    if not execute:
        quality_reasons.append("dry_run_only_no_real_snapshots")
    if execute and captured_target_count == 0:
        quality_reasons.append("no_target_captured_with_snapshots")
    if partial_target_count:
        quality_reasons.append("partial_or_failed_target_requires_review")
    if ocr_blocked_count:
        quality_reasons.append("ocr_required_blocks_full_text_extraction")
    if failure_values:
        quality_reasons.append("failure_taxonomy_present")
    if not items:
        quality_reasons.append("no_plan_ready_targets")

    if execute and captured_target_count and not partial_target_count and not ocr_blocked_count:
        coverage_quality_state = "REAL_SNAPSHOT_COVERED"
    elif execute and captured_target_count:
        coverage_quality_state = "PARTIAL_REAL_SNAPSHOT_COVERAGE_REVIEW"
    elif execute:
        coverage_quality_state = "NO_REAL_SNAPSHOT_CAPTURED_REVIEW"
    else:
        coverage_quality_state = "DRY_RUN_ONLY_NO_REAL_SNAPSHOT"

    return {
        "coverage_quality_state": coverage_quality_state,
        "target_bucket_coverage": _counts(target_bucket_values),
        "site_coverage": _counts(site_values),
        "execution_state_counts": state_counts,
        "captured_target_count": captured_target_count,
        "partial_or_failed_target_count": partial_target_count,
        "detail_snapshot_count": detail_snapshot_count,
        "attachment_snapshot_count": attachment_snapshot_count,
        "ocr_blocked_count": ocr_blocked_count,
        "failure_taxonomy_counts": _counts(failure_values),
        "sample_quality_reasons": list(dict.fromkeys(quality_reasons)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _safety(*, execute: bool) -> dict[str, Any]:
    return {
        "external_service_connection_enabled": execute,
        "download_enabled": execute,
        "fetch_public_urls_enabled": execute,
        "login_required_fetch_enabled": False,
        "captcha_resolution_enabled": False,
        "hidden_api_call_enabled": False,
        "bulk_ocr_enabled": False,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
        "manifest_stores_raw_html_or_blob": False,
    }


def _empty_parse_summary() -> dict[str, Any]:
    return {
        "stage3_parse_success_count": 0,
        "stage3_parse_failed_count": 0,
        "ocr_required_count": 0,
        "attachment_ocr_required_count": 0,
        "attachment_ocr_extracted_count": 0,
        "attachment_missing_review_count": 0,
        "clarification_version_review_count": 0,
        "unknown_attachment_count": 0,
        "document_completeness_state_counts": {},
        "notice_version_chain_state_counts": {},
        "document_quality_reasons": [],
        "download_archive_quality_reasons": [],
    }


def _target_source_profile_id(plan_item: Mapping[str, Any]) -> str:
    return str(
        plan_item.get("required_fetch_profile_id_optional")
        or plan_item.get("entry_seed_fetch_profile_id_optional")
        or ""
    ).strip()


def _target_region_code(plan_item: Mapping[str, Any]) -> str:
    jurisdiction = str(plan_item.get("jurisdiction") or "").strip()
    return jurisdiction if jurisdiction else "CN-NATIONAL"


def _target_id_list(value: Any) -> list[str]:
    raw_values = _string_list(value)
    result: list[str] = []
    for raw in raw_values:
        for part in str(raw).replace(";", ",").replace("\n", ",").split(","):
            text = part.strip()
            if text:
                result.append(text)
    return list(dict.fromkeys(result))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _count_ocr_required(value: Any) -> int:
    if isinstance(value, Mapping):
        return sum(_count_ocr_required(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_ocr_required(item) for item in value)
    if isinstance(value, str):
        return 1 if "OCR_REQUIRED" in value else 0
    return 0


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})


def _hash_text(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in str(value).upper())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "TARGET"


def _redact_database_url(database_url: str | None) -> str:
    if not database_url or "://" not in database_url or "@" not in database_url:
        return database_url or ""
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run controlled evaluation real project sample execution.")
    parser.add_argument("--targets-json", default=str(default_evaluation_real_project_sample_targets_path()))
    parser.add_argument("--seed-json", default=str(default_evaluation_seed_path()))
    parser.add_argument("--database-url")
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--target-limit", type=int)
    parser.add_argument("--target-ids", nargs="*")
    parser.add_argument("--per-target-candidate-limit", type=int, default=1)
    parser.add_argument("--output-json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evaluation_real_sample_execution(
        targets_json=args.targets_json,
        seed_json=args.seed_json,
        database_url=args.database_url,
        target_backend=args.target_backend,
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
        execute=args.execute,
        target_limit=args.target_limit,
        target_ids=args.target_ids,
        per_target_candidate_limit=args.per_target_candidate_limit,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "evaluation real sample execution "
            f"{result['real_sample_execution_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAPTURED_WITH_SNAPSHOTS",
    "CAPTURE_PARTIAL_REVIEW",
    "DISCOVERY_FAILED_CLOSED",
    "DISCOVERY_NO_MATCH_REVIEW",
    "EVALUATION_REAL_PROJECT_SAMPLE_EXECUTION_OBJECT_TYPE",
    "EXECUTION_READY",
    "DEFAULT_SMALL_REAL_SAMPLE_TARGET_IDS",
    "build_evaluation_real_sample_execution",
]
