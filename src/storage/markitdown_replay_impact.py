from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage3_parsing import markitdown_adapter
from stage3_parsing.real_parser import OCR_REQUIRED, Stage3RealParser
from stage3_parsing.tailored_bid_signals import (
    DEFAULT_SEED_PATH as DEFAULT_TAILORED_SIGNAL_SEED_PATH,
    build_tailored_bid_signal_profile,
)
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


MARKITDOWN_REPLAY_IMPACT_MANIFEST_OBJECT_TYPE = "markitdown_replay_impact_manifest"
MARKITDOWN_REPLAY_IMPACT_MANIFEST_VERSION = 1
MARKITDOWN_REPLAY_IMPACT_ADAPTER_ID = "markitdown-replay-impact-builder"

MARKITDOWN_NOT_ATTEMPTED = "MARKITDOWN_NOT_ATTEMPTED"
INSUFFICIENT_REPLAYABLE_SNAPSHOT = "INSUFFICIENT_REPLAYABLE_SNAPSHOT"
MANUAL_REVIEW_MARKITDOWN_TEXT_GAINS_BEFORE_RULE_MUTATION = (
    "MANUAL_REVIEW_MARKITDOWN_TEXT_GAINS_BEFORE_RULE_MUTATION"
)
NO_MARKITDOWN_TEXT_GAIN_KEEP_CURRENT_RULES = "NO_MARKITDOWN_TEXT_GAIN_KEEP_CURRENT_RULES"

REPLAY_ATTACHMENT_TYPES = {"PDF", "WORD_DOCX", "EXCEL_XLSX"}
NON_PRIMARY_DOCUMENT_KINDS = {
    "candidate_notice",
    "award_notice",
    "award_result",
    "failed_bid_notice",
    "flow_or_re_tender_notice",
}
NON_PRIMARY_ATTACHMENT_ROLES = {
    "CLARIFICATION_OR_ADDENDUM",
    "OPENING_RECORD",
    "AWARD_RESULT",
    "CANDIDATE_NOTICE",
}
QUALIFICATION_MARKERS = (
    "资格条件",
    "资格要求",
    "投标人资格",
    "供应商资格",
    "厂家授权",
    "原厂授权",
    "本地社保",
    "类似业绩",
    "项目负责人",
    "评分办法",
    "技术参数",
)


def build_markitdown_replay_impact_manifest(
    *,
    real_sample_execution_manifest_json: str | Path,
    rule_calibration_manifest_json: str | Path,
    tailored_review_adjudication_json: str | Path | None = None,
    tailored_signal_seed_json: str | Path | None = None,
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    database_url: str | None = None,
    target_backend: str = "json-file",
    created_at: str | None = None,
    object_repository: ObjectStorageRepository | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    execution_path = Path(real_sample_execution_manifest_json)
    calibration_path = Path(rule_calibration_manifest_json)
    adjudication_path = Path(tailored_review_adjudication_json) if tailored_review_adjudication_json else None
    seed_path = Path(tailored_signal_seed_json or DEFAULT_TAILORED_SIGNAL_SEED_PATH)
    blocking_reasons: list[str] = []

    execution_payload = _load_json_file(execution_path, "real_sample_execution_manifest", blocking_reasons)
    calibration_payload = _load_json_file(calibration_path, "rule_calibration_manifest", blocking_reasons)
    adjudication_payload = (
        _load_json_file(adjudication_path, "tailored_review_adjudication", blocking_reasons)
        if adjudication_path
        else {}
    )
    execution_manifest = _source_manifest(execution_payload)
    calibration_manifest = _source_manifest(calibration_payload)
    adjudication_manifest = _source_manifest(adjudication_payload)
    project_items = _project_sample_items(execution_manifest)
    calibration_index = _calibration_item_index(calibration_manifest)

    repository = object_repository or _object_repository(
        storage_path=storage_path,
        object_storage_path=object_storage_path,
        database_url=database_url,
        target_backend=target_backend,
    )
    should_close_repository = object_repository is None
    try:
        replay_items = _build_replay_items(
            project_items=project_items,
            calibration_index=calibration_index,
            repository=repository,
            seed_path=seed_path,
        )
    finally:
        if should_close_repository:
            repository.session.close()

    manifest = _build_manifest(
        replay_items=replay_items,
        project_items=project_items,
        execution_manifest=execution_manifest,
        calibration_manifest=calibration_manifest,
        adjudication_manifest=adjudication_manifest,
        execution_path=execution_path,
        calibration_path=calibration_path,
        adjudication_path=adjudication_path,
        seed_path=seed_path,
        storage_path=storage_path,
        object_storage_path=object_storage_path,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created,
    )
    result = {
        "markitdown_replay_impact_mode": "DRY_RUN",
        "execute": False,
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": manifest["summary"],
        "execution": {
            "executed": False,
            "database_write_enabled": False,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "external_service_connection_enabled": False,
            "formal_rule_threshold_mutation_enabled": False,
            "formal_seed_weight_mutation_enabled": False,
            "customer_visible_allowed": False,
        },
    }
    return result


def _build_replay_items(
    *,
    project_items: list[dict[str, Any]],
    calibration_index: Mapping[str, Mapping[str, Any]],
    repository: ObjectStorageRepository,
    seed_path: Path,
) -> list[dict[str, Any]]:
    parser = Stage3RealParser(repository=repository)
    replay_items: list[dict[str, Any]] = []
    for project_item in project_items:
        attachment_refs = [
            dict(ref)
            for ref in list(project_item.get("attachment_snapshot_refs") or [])
            if isinstance(ref, Mapping)
        ]
        if not attachment_refs:
            replay_items.append(_no_attachment_replay_item(project_item))
            continue
        for attachment_ref in attachment_refs:
            replay_items.append(
                _replay_attachment_item(
                    project_item=project_item,
                    attachment_ref=attachment_ref,
                    calibration_item=_match_calibration_item(project_item, calibration_index),
                    parser=parser,
                    repository=repository,
                    seed_path=seed_path,
                )
            )
    return replay_items


def _replay_attachment_item(
    *,
    project_item: Mapping[str, Any],
    attachment_ref: Mapping[str, Any],
    calibration_item: Mapping[str, Any],
    parser: Stage3RealParser,
    repository: ObjectStorageRepository,
    seed_path: Path,
) -> dict[str, Any]:
    snapshot_id = str(attachment_ref.get("snapshot_id") or "").strip()
    base = _base_replay_item(project_item, attachment_ref, snapshot_id=snapshot_id)
    if not snapshot_id:
        return {
            **base,
            "replay_state": "SNAPSHOT_ID_MISSING",
            "snapshot_readback_failure": "SNAPSHOT_ID_MISSING",
            "markitdown_state": MARKITDOWN_NOT_ATTEMPTED,
            "markitdown_text_gain": False,
            "qualification_block_gain_count": 0,
            "tailored_signal_delta": _empty_profile_delta(),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    readback = repository.replay_snapshot(snapshot_id)
    if not readback.get("replayable"):
        readback_state = str(readback.get("readback_state") or "READBACK_NOT_REPLAYABLE")
        return {
            **base,
            "replay_state": readback_state,
            "snapshot_readback_failure": readback_state,
            "manifest_present": bool(readback.get("manifest_present")),
            "object_present": bool(readback.get("object_present")),
            "markitdown_state": MARKITDOWN_NOT_ATTEMPTED,
            "markitdown_text_gain": False,
            "qualification_block_gain_count": 0,
            "tailored_signal_delta": _empty_profile_delta(),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    carrier = parser.parse_readback(readback)
    audit = dict(carrier.get("parser_audit") or {})
    markitdown_state = str(audit.get("markitdown_state") or MARKITDOWN_NOT_ATTEMPTED)
    markitdown_text_length = _int_value(audit.get("markitdown_text_length"), default=0)
    markitdown_text_sha256 = str(audit.get("markitdown_text_sha256") or "")
    markitdown_text_probe = str(audit.get("markitdown_text_probe") or "")
    parse_error_taxonomy = _string_list(carrier.get("parse_error_taxonomy"))

    baseline_text = _baseline_text(project_item)
    augmented_text = _dedupe_join([baseline_text, markitdown_text_probe])
    baseline_profile = _baseline_profile(project_item, calibration_item, baseline_text, seed_path=seed_path)
    replay_profile = build_tailored_bid_signal_profile(
        _profile_inputs(project_item, attachment_ref=attachment_ref),
        text=augmented_text,
        seed_path=seed_path,
    )
    baseline_blocks = _qualification_blocks(baseline_text)
    augmented_blocks = _qualification_blocks(augmented_text)
    new_block_count = len([block for block in augmented_blocks if block not in set(baseline_blocks)])
    signal_delta = _profile_delta(baseline_profile, replay_profile)
    guardrail_applied = _non_primary_document_guardrail_applied(
        project_item=project_item,
        attachment_ref=attachment_ref,
        replay_profile=replay_profile,
    )
    replay_failure_taxonomy = []
    if OCR_REQUIRED in parse_error_taxonomy:
        replay_failure_taxonomy.append(OCR_REQUIRED)
    if carrier.get("parse_state") == "REVIEW_REQUIRED" and not markitdown_text_length:
        replay_failure_taxonomy.append("REVIEW_REQUIRED_WITHOUT_MARKITDOWN_TEXT")
    if markitdown_state in {
        markitdown_adapter.MARKITDOWN_UNAVAILABLE,
        markitdown_adapter.MARKITDOWN_CONVERT_FAILED,
        markitdown_adapter.MARKITDOWN_TEXT_EMPTY,
    }:
        replay_failure_taxonomy.append(markitdown_state)

    return {
        **base,
        "replay_state": "REPLAYED",
        "snapshot_readback_failure": "",
        "manifest_present": True,
        "object_present": True,
        "attachment_type": str(carrier.get("attachment_type") or ""),
        "parse_state": str(carrier.get("parse_state") or ""),
        "parse_error_taxonomy": parse_error_taxonomy,
        "markitdown_state": markitdown_state,
        "markitdown_text_length": markitdown_text_length,
        "markitdown_text_sha256": markitdown_text_sha256,
        "markitdown_text_gain": bool(
            markitdown_state == markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED
            and markitdown_text_length > 0
            and markitdown_text_probe
            and markitdown_text_probe not in baseline_text
        ),
        "qualification_block_gain_count": new_block_count,
        "baseline_tailored_bid_index": _int_value(
            baseline_profile.get("tailored_bid_index"),
            default=0,
        ),
        "replay_tailored_bid_index": _int_value(
            replay_profile.get("tailored_bid_index"),
            default=0,
        ),
        "baseline_tailored_signal_count": _int_value(
            baseline_profile.get("tailored_bid_signal_count"),
            default=0,
        ),
        "replay_tailored_signal_count": _int_value(
            replay_profile.get("tailored_bid_signal_count"),
            default=0,
        ),
        "tailored_signal_delta": signal_delta,
        "baseline_stage5_review_required": bool(
            baseline_profile.get("tailored_bid_stage5_review_required")
        ),
        "replay_stage5_review_required": bool(
            replay_profile.get("tailored_bid_stage5_review_required")
        ),
        "baseline_ai_review_required": bool(
            baseline_profile.get("tailored_bid_ai_review_required")
        ),
        "replay_ai_review_required": bool(
            replay_profile.get("tailored_bid_ai_review_required")
        ),
        "non_tender_document_guardrail_applied": guardrail_applied,
        "formal_index_weight_blocked_count": _int_value(
            replay_profile.get("formal_index_weight_blocked_count"),
            default=0,
        ),
        "replay_failure_taxonomy": _dedupe_strings(replay_failure_taxonomy),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _no_attachment_replay_item(project_item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_base_replay_item(project_item, {}, snapshot_id=""),
        "replay_state": "NO_ATTACHMENT_SNAPSHOT",
        "snapshot_readback_failure": "NO_ATTACHMENT_SNAPSHOT",
        "markitdown_state": MARKITDOWN_NOT_ATTEMPTED,
        "markitdown_text_gain": False,
        "qualification_block_gain_count": 0,
        "tailored_signal_delta": _empty_profile_delta(),
        "baseline_stage5_review_required": False,
        "replay_stage5_review_required": False,
        "baseline_ai_review_required": False,
        "replay_ai_review_required": False,
        "non_tender_document_guardrail_applied": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _base_replay_item(
    project_item: Mapping[str, Any],
    attachment_ref: Mapping[str, Any],
    *,
    snapshot_id: str,
) -> dict[str, Any]:
    return {
        "target_id": str(project_item.get("target_id") or ""),
        "parent_target_id": str(project_item.get("parent_target_id") or ""),
        "candidate_key": str(project_item.get("candidate_key") or ""),
        "project_id": str(project_item.get("project_id") or ""),
        "project_name_sha256": _hash_text(str(project_item.get("project_name") or "")),
        "source_url_sha256": _hash_text(str(project_item.get("source_url") or "")),
        "document_kind": str(project_item.get("document_kind") or ""),
        "jurisdiction": str(project_item.get("jurisdiction") or ""),
        "source_profile_id": str(project_item.get("source_profile_id") or ""),
        "target_execution_state": str(project_item.get("target_execution_state") or ""),
        "attachment_snapshot_id": snapshot_id,
        "attachment_url_sha256": _hash_text(str(attachment_ref.get("attachment_url") or "")),
        "attachment_role_type": str(attachment_ref.get("attachment_role_type") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _baseline_profile(
    project_item: Mapping[str, Any],
    calibration_item: Mapping[str, Any],
    baseline_text: str,
    *,
    seed_path: Path,
) -> dict[str, Any]:
    if calibration_item:
        return {
            "tailored_bid_index": _int_value(calibration_item.get("tailored_bid_index"), default=0),
            "tailored_bid_signal_count": _int_value(
                calibration_item.get("tailored_bid_signal_count"),
                default=0,
            ),
            "tailored_bid_signal_families": dict(
                calibration_item.get("tailored_bid_signal_families") or {}
            ),
            "tailored_bid_stage5_review_required": bool(
                calibration_item.get("tailored_bid_stage5_review_required")
            ),
            "tailored_bid_ai_review_required": bool(
                calibration_item.get("tailored_bid_ai_review_required")
            ),
        }
    return build_tailored_bid_signal_profile(
        _profile_inputs(project_item),
        text=baseline_text,
        seed_path=seed_path,
    )


def _profile_inputs(
    project_item: Mapping[str, Any],
    *,
    attachment_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(project_item)
    parse_summary = dict(project_item.get("parse_summary") or {})
    document_counts = _mapping_counts(parse_summary.get("document_completeness_state_counts"))
    version_counts = _mapping_counts(parse_summary.get("notice_version_chain_state_counts"))
    if not result.get("document_completeness_state") and document_counts:
        result["document_completeness_state"] = next(iter(document_counts))
    if not result.get("notice_version_chain_state") and version_counts:
        result["notice_version_chain_state"] = next(iter(version_counts))
    result["attachment_ocr_required_count"] = _int_value(
        result.get("attachment_ocr_required_count"),
        default=_int_value(parse_summary.get("attachment_ocr_required_count"), default=0)
        + _int_value(parse_summary.get("ocr_required_count"), default=0),
    )
    result["attachment_missing_review_count"] = _int_value(
        result.get("attachment_missing_review_count"),
        default=_int_value(parse_summary.get("attachment_missing_review_count"), default=0),
    )
    role = str((attachment_ref or {}).get("attachment_role_type") or "")
    if role == "CLARIFICATION_OR_ADDENDUM":
        result["notice_version_chain_state"] = "CLARIFICATION_OR_ADDENDUM_PRESENT"
    return result


def _profile_delta(
    baseline_profile: Mapping[str, Any],
    replay_profile: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_index = _int_value(baseline_profile.get("tailored_bid_index"), default=0)
    replay_index = _int_value(replay_profile.get("tailored_bid_index"), default=0)
    baseline_signal_count = _int_value(
        baseline_profile.get("tailored_bid_signal_count"),
        default=0,
    )
    replay_signal_count = _int_value(
        replay_profile.get("tailored_bid_signal_count"),
        default=0,
    )
    return {
        "index_delta": replay_index - baseline_index,
        "signal_count_delta": replay_signal_count - baseline_signal_count,
        "baseline_signal_families": dict(baseline_profile.get("tailored_bid_signal_families") or {}),
        "replay_signal_families": dict(replay_profile.get("tailored_bid_signal_families") or {}),
        "family_delta_counts": _family_delta(
            dict(baseline_profile.get("tailored_bid_signal_families") or {}),
            dict(replay_profile.get("tailored_bid_signal_families") or {}),
        ),
    }


def _empty_profile_delta() -> dict[str, Any]:
    return {
        "index_delta": 0,
        "signal_count_delta": 0,
        "baseline_signal_families": {},
        "replay_signal_families": {},
        "family_delta_counts": {},
    }


def _family_delta(baseline: Mapping[str, Any], replay: Mapping[str, Any]) -> dict[str, int]:
    keys = sorted(set(str(key) for key in baseline) | set(str(key) for key in replay))
    return {
        key: _int_value(replay.get(key), default=0) - _int_value(baseline.get(key), default=0)
        for key in keys
        if _int_value(replay.get(key), default=0) - _int_value(baseline.get(key), default=0)
    }


def _non_primary_document_guardrail_applied(
    *,
    project_item: Mapping[str, Any],
    attachment_ref: Mapping[str, Any],
    replay_profile: Mapping[str, Any],
) -> bool:
    document_kind = str(project_item.get("document_kind") or "")
    attachment_role = str(attachment_ref.get("attachment_role_type") or "")
    if document_kind not in NON_PRIMARY_DOCUMENT_KINDS and attachment_role not in NON_PRIMARY_ATTACHMENT_ROLES:
        return False
    return _int_value(replay_profile.get("formal_index_weight_blocked_count"), default=0) > 0


def _build_manifest(
    *,
    replay_items: list[dict[str, Any]],
    project_items: list[Mapping[str, Any]],
    execution_manifest: Mapping[str, Any],
    calibration_manifest: Mapping[str, Any],
    adjudication_manifest: Mapping[str, Any],
    execution_path: Path,
    calibration_path: Path,
    adjudication_path: Path | None,
    seed_path: Path,
    storage_path: str | Path | None,
    object_storage_path: str | Path | None,
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    summary = _summary(project_items, replay_items)
    fingerprint = _fingerprint(
        {
            "source_real_sample_execution_manifest_id": execution_manifest.get("manifest_id"),
            "source_rule_calibration_manifest_id": calibration_manifest.get("manifest_id"),
            "source_tailored_review_adjudication_manifest_id": adjudication_manifest.get("manifest_id"),
            "summary": summary,
            "items": replay_items,
        }
    )
    manifest = {
        "manifest_version": MARKITDOWN_REPLAY_IMPACT_MANIFEST_VERSION,
        "manifest_kind": MARKITDOWN_REPLAY_IMPACT_MANIFEST_OBJECT_TYPE,
        "adapter_id": MARKITDOWN_REPLAY_IMPACT_ADAPTER_ID,
        "manifest_id": f"MARKITDOWN-REPLAY-IMPACT-{fingerprint[:16]}",
        "created_at": created_at,
        "source_real_sample_execution_manifest_id": str(execution_manifest.get("manifest_id") or ""),
        "source_real_sample_execution_manifest_path": str(execution_path),
        "source_rule_calibration_manifest_id": str(calibration_manifest.get("manifest_id") or ""),
        "source_rule_calibration_manifest_path": str(calibration_path),
        "source_tailored_review_adjudication_manifest_id": str(
            adjudication_manifest.get("manifest_id") or ""
        ),
        "source_tailored_review_adjudication_manifest_path": str(adjudication_path or ""),
        "tailored_signal_seed_path": str(seed_path),
        "target_storage_backend": target_backend,
        "storage_path_optional": str(storage_path or ""),
        "object_storage_path_optional": str(object_storage_path or ""),
        "database_url_redacted": _redact_database_url(database_url),
        "items": replay_items,
        "sample_items": replay_items[:80],
        "summary": summary,
        "safety": {
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "external_service_connection_enabled": False,
            "formal_rule_threshold_mutation_enabled": False,
            "formal_seed_weight_mutation_enabled": False,
            "raw_html_or_blob_stored": False,
            "markitdown_text_probe_stored": False,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return manifest


def _summary(
    project_items: list[Mapping[str, Any]],
    replay_items: list[Mapping[str, Any]],
) -> dict[str, Any]:
    attempted = [item for item in replay_items if item.get("replay_state") != "NO_ATTACHMENT_SNAPSHOT"]
    replayed = [item for item in replay_items if item.get("replay_state") == "REPLAYED"]
    attachment_text_gain_count = sum(1 for item in replay_items if item.get("markitdown_text_gain"))
    qualification_block_gain_count = sum(
        _int_value(item.get("qualification_block_gain_count"), default=0)
        for item in replay_items
    )
    baseline_stage5_count = sum(1 for item in replayed if item.get("baseline_stage5_review_required"))
    replay_stage5_count = sum(1 for item in replayed if item.get("replay_stage5_review_required"))
    baseline_ai_count = sum(1 for item in replayed if item.get("baseline_ai_review_required"))
    replay_ai_count = sum(1 for item in replayed if item.get("replay_ai_review_required"))
    replay_attempted_count = len(attempted)
    if replay_attempted_count == 0 or not replayed:
        recommended_next_action = INSUFFICIENT_REPLAYABLE_SNAPSHOT
    elif attachment_text_gain_count or qualification_block_gain_count:
        recommended_next_action = MANUAL_REVIEW_MARKITDOWN_TEXT_GAINS_BEFORE_RULE_MUTATION
    else:
        recommended_next_action = NO_MARKITDOWN_TEXT_GAIN_KEEP_CURRENT_RULES
    return {
        "project_sample_count": len(project_items),
        "replay_attempted_count": replay_attempted_count,
        "markitdown_state_counts": _counts(str(item.get("markitdown_state") or "") for item in replay_items),
        "snapshot_readback_failure_counts": _counts(
            str(item.get("snapshot_readback_failure") or "")
            for item in replay_items
            if str(item.get("snapshot_readback_failure") or "")
        ),
        "attachment_text_gain_count": attachment_text_gain_count,
        "qualification_block_gain_count": qualification_block_gain_count,
        "tailored_signal_delta": _aggregate_signal_delta(replayed),
        "stage5_trigger_delta": {
            "baseline_required_count": baseline_stage5_count,
            "replay_required_count": replay_stage5_count,
            "delta": replay_stage5_count - baseline_stage5_count,
        },
        "ai_review_trigger_delta": {
            "baseline_required_count": baseline_ai_count,
            "replay_required_count": replay_ai_count,
            "delta": replay_ai_count - baseline_ai_count,
        },
        "non_tender_document_guardrail_hits": sum(
            1 for item in replay_items if item.get("non_tender_document_guardrail_applied")
        ),
        "parser_failure_taxonomy_counts": _counts(
            value
            for item in replay_items
            for value in _string_list(item.get("parse_error_taxonomy"))
        ),
        "replay_failure_taxonomy_counts": _counts(
            value
            for item in replay_items
            for value in _string_list(item.get("replay_failure_taxonomy"))
        ),
        "recommended_next_action": recommended_next_action,
        "formal_rule_threshold_mutation_enabled": False,
        "formal_seed_weight_mutation_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _aggregate_signal_delta(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    baseline_index_sum = sum(_int_value(item.get("baseline_tailored_bid_index"), default=0) for item in items)
    replay_index_sum = sum(_int_value(item.get("replay_tailored_bid_index"), default=0) for item in items)
    baseline_signal_sum = sum(
        _int_value(item.get("baseline_tailored_signal_count"), default=0) for item in items
    )
    replay_signal_sum = sum(
        _int_value(item.get("replay_tailored_signal_count"), default=0) for item in items
    )
    family_delta_counts: dict[str, int] = {}
    for item in items:
        delta = dict((item.get("tailored_signal_delta") or {}).get("family_delta_counts") or {})
        for family, raw_count in delta.items():
            family_delta_counts[str(family)] = family_delta_counts.get(str(family), 0) + _int_value(
                raw_count,
                default=0,
            )
    return {
        "baseline_index_sum": baseline_index_sum,
        "replay_index_sum": replay_index_sum,
        "index_delta_sum": replay_index_sum - baseline_index_sum,
        "baseline_signal_count_sum": baseline_signal_sum,
        "replay_signal_count_sum": replay_signal_sum,
        "signal_count_delta_sum": replay_signal_sum - baseline_signal_sum,
        "positive_delta_count": sum(
            1
            for item in items
            if _int_value((item.get("tailored_signal_delta") or {}).get("index_delta"), default=0) > 0
            or _int_value((item.get("tailored_signal_delta") or {}).get("signal_count_delta"), default=0) > 0
        ),
        "family_delta_counts": dict(sorted(family_delta_counts.items())),
    }


def _object_repository(
    *,
    storage_path: str | Path | None,
    object_storage_path: str | Path | None,
    database_url: str | None,
    target_backend: str,
) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend=target_backend,
        storage_path_optional=str(storage_path) if storage_path else None,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage_path) if object_storage_path else None,
    )
    session = DatabaseSession(settings=settings)
    return ObjectStorageRepository(session=session, settings=settings)


def _project_sample_items(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    project_items = [
        dict(item)
        for item in list(manifest.get("project_sample_items") or [])
        if isinstance(item, Mapping)
    ]
    if project_items:
        return project_items
    return [
        dict(item)
        for item in list(manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]


def _calibration_item_index(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for item in list(manifest.get("tailored_items") or []):
        if not isinstance(item, Mapping):
            continue
        target_id = str(item.get("target_id") or "")
        if target_id:
            index[target_id] = dict(item)
        parent_target_id = str(item.get("parent_target_id") or "")
        candidate_key = str(item.get("candidate_key") or "")
        if parent_target_id and candidate_key:
            index[f"{parent_target_id}::{candidate_key}"] = dict(item)
    return index


def _match_calibration_item(
    project_item: Mapping[str, Any],
    calibration_index: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    target_id = str(project_item.get("target_id") or "")
    if target_id in calibration_index:
        return calibration_index[target_id]
    parent_target_id = str(project_item.get("parent_target_id") or "")
    candidate_key = str(project_item.get("candidate_key") or "")
    if parent_target_id and candidate_key:
        return calibration_index.get(f"{parent_target_id}::{candidate_key}", {})
    return {}


def _baseline_text(project_item: Mapping[str, Any]) -> str:
    parse_summary = dict(project_item.get("parse_summary") or {})
    return _dedupe_join(
        [
            str(project_item.get("source_text") or ""),
            str(parse_summary.get("text_probe") or ""),
            str(project_item.get("project_name") or ""),
        ]
    )


def _qualification_blocks(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    blocks: list[str] = []
    for marker in QUALIFICATION_MARKERS:
        start = normalized.find(marker)
        if start < 0:
            continue
        blocks.append(normalized[start : start + 260])
    return _dedupe_strings(blocks)


def _load_json_file(path: Path | None, label: str, blocking_reasons: list[str]) -> dict[str, Any]:
    if path is None:
        return {}
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


def _mapping_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        text = str(key or "")
        if text:
            result[text] = _int_value(raw_count, default=0)
    return result


def _dedupe_join(values: list[str]) -> str:
    return "\n".join(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_text(value: str) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _redact_database_url(database_url: str | None) -> str:
    if not database_url or "://" not in database_url or "@" not in database_url:
        return database_url or ""
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build internal MarkItDown replay impact report for existing real samples."
    )
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
    parser.add_argument("--rule-calibration-manifest-json", required=True)
    parser.add_argument("--tailored-review-adjudication-json")
    parser.add_argument("--tailored-signal-seed-json")
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--database-url")
    parser.add_argument("--target-backend", default="json-file")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_markitdown_replay_impact_manifest(
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
        rule_calibration_manifest_json=args.rule_calibration_manifest_json,
        tailored_review_adjudication_json=args.tailored_review_adjudication_json,
        tailored_signal_seed_json=args.tailored_signal_seed_json,
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
        database_url=args.database_url,
        target_backend=args.target_backend,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "markitdown replay impact "
            f"{result['markitdown_replay_impact_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INSUFFICIENT_REPLAYABLE_SNAPSHOT",
    "MARKITDOWN_REPLAY_IMPACT_MANIFEST_OBJECT_TYPE",
    "build_markitdown_replay_impact_manifest",
]
