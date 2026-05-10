from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage3_parsing.tailored_bid_signals import (
    DEFAULT_SEED_PATH as DEFAULT_TAILORED_SIGNAL_SEED_PATH,
    build_tailored_bid_signal_profile,
)


TAILORED_AUTO_JUDGEMENT_REPORT_MANIFEST_OBJECT_TYPE = "tailored_auto_judgement_report_manifest"
TAILORED_AUTO_JUDGEMENT_REPORT_MANIFEST_VERSION = 1
TAILORED_AUTO_JUDGEMENT_REPORT_ADAPTER_ID = "tailored-auto-judgement-report-builder"

SAMPLE_READY_MIN_COUNT = 50
INDEX_REVIEW_THRESHOLD = 21
INDEX_HIGH_THRESHOLD = 61
TEXT_PROBE_LIMIT = 1200

NO_SIGNAL = "NO_SIGNAL"
WEAK_SIGNAL_ONLY = "WEAK_SIGNAL_ONLY"
RISK_CLUE_DETECTED = "RISK_CLUE_DETECTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

PROCEED_STANDARD = "PROCEED_STANDARD"
TRACK_LOW_PRIORITY = "TRACK_LOW_PRIORITY"
CAUTION_TENDER = "CAUTION_TENDER"
AVOID_OR_CHALLENGE_EVALUATE = "AVOID_OR_CHALLENGE_EVALUATE"
EVIDENCE_BLOCKED_RETRY_PARSE = "EVIDENCE_BLOCKED_RETRY_PARSE"

INDEX_FIELDS = (
    "tailored_bid_index",
    "bid_rigging_index",
    "cover_bid_index",
    "collusion_trace_index",
    "fatal_rejection_complexity_index",
    "electronic_supervision_index",
)

EVIDENCE_BLOCKER_STATES = {
    "DETAIL_SNAPSHOT_MISSING_REVIEW",
    "ATTACHMENTS_NOT_CAPTURED_REVIEW",
    "PARTIAL_REVIEW_REQUIRED",
}
EVIDENCE_BLOCKER_MARKERS = {
    "CAPTCHA",
    "OCR_REQUIRED",
    "OCR_ENGINE_UNAVAILABLE",
    "attachment_missing",
    "detail_body_too_small",
    "detail_title_missing",
    "http_status:502",
    "MISSING_MANIFEST",
    "MISSING_OBJECT",
}


def build_tailored_auto_judgement_report_manifest(
    *,
    real_sample_execution_manifest_json: str | Path,
    rule_calibration_manifest_json: str | Path,
    tailored_review_adjudication_json: str | Path | None = None,
    markitdown_replay_impact_json: str | Path | None = None,
    tailored_signal_seed_json: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    execution_path = Path(real_sample_execution_manifest_json)
    calibration_path = Path(rule_calibration_manifest_json)
    adjudication_path = Path(tailored_review_adjudication_json) if tailored_review_adjudication_json else None
    markitdown_path = Path(markitdown_replay_impact_json) if markitdown_replay_impact_json else None
    seed_path = Path(tailored_signal_seed_json or DEFAULT_TAILORED_SIGNAL_SEED_PATH)
    blocking_reasons: list[str] = []

    execution_payload = _load_json_file(execution_path, "real_sample_execution_manifest", blocking_reasons)
    calibration_payload = _load_json_file(calibration_path, "rule_calibration_manifest", blocking_reasons)
    adjudication_payload, adjudication_state = _load_optional_json_file(
        adjudication_path,
        "tailored_review_adjudication",
    )
    markitdown_payload, markitdown_state = _load_optional_json_file(
        markitdown_path,
        "markitdown_replay_impact",
    )

    execution_manifest = _source_manifest(execution_payload)
    calibration_manifest = _source_manifest(calibration_payload)
    adjudication_manifest = _source_manifest(adjudication_payload)
    markitdown_manifest = _source_manifest(markitdown_payload)

    project_items = _project_sample_items(execution_manifest)
    calibration_index = _calibration_item_index(calibration_manifest)
    adjudication_index = _adjudication_item_index(adjudication_manifest)
    markitdown_index = _markitdown_item_index(markitdown_manifest)
    judgement_items = [
        _build_judgement_item(
            project_item,
            calibration_item=_match_calibration_item(project_item, calibration_index),
            adjudication_item=_match_optional_item(project_item, adjudication_index),
            markitdown_item=_match_optional_item(project_item, markitdown_index),
            seed_path=seed_path,
        )
        for project_item in project_items
    ]

    manifest = _build_manifest(
        judgement_items=judgement_items,
        execution_manifest=execution_manifest,
        calibration_manifest=calibration_manifest,
        adjudication_manifest=adjudication_manifest,
        markitdown_manifest=markitdown_manifest,
        execution_path=execution_path,
        calibration_path=calibration_path,
        adjudication_path=adjudication_path,
        markitdown_path=markitdown_path,
        adjudication_state=adjudication_state,
        markitdown_state=markitdown_state,
        seed_path=seed_path,
        created_at=created,
    )
    return {
        "tailored_auto_judgement_report_mode": "DRY_RUN",
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
            "formal_rule_threshold_mutation_enabled": False,
            "formal_seed_weight_mutation_enabled": False,
            "customer_visible_allowed": False,
        },
    }


def _build_manifest(
    *,
    judgement_items: list[dict[str, Any]],
    execution_manifest: Mapping[str, Any],
    calibration_manifest: Mapping[str, Any],
    adjudication_manifest: Mapping[str, Any],
    markitdown_manifest: Mapping[str, Any],
    execution_path: Path,
    calibration_path: Path,
    adjudication_path: Path | None,
    markitdown_path: Path | None,
    adjudication_state: str,
    markitdown_state: str,
    seed_path: Path,
    created_at: str,
) -> dict[str, Any]:
    summary = _summary(judgement_items, calibration_manifest)
    fingerprint = _fingerprint(
        {
            "source_real_sample_execution_manifest_id": execution_manifest.get("manifest_id"),
            "source_rule_calibration_manifest_id": calibration_manifest.get("manifest_id"),
            "source_tailored_review_adjudication_manifest_id": adjudication_manifest.get("manifest_id"),
            "source_markitdown_replay_impact_manifest_id": markitdown_manifest.get("manifest_id"),
            "summary": summary,
            "items": judgement_items,
        }
    )
    manifest = {
        "manifest_version": TAILORED_AUTO_JUDGEMENT_REPORT_MANIFEST_VERSION,
        "manifest_kind": TAILORED_AUTO_JUDGEMENT_REPORT_MANIFEST_OBJECT_TYPE,
        "adapter_id": TAILORED_AUTO_JUDGEMENT_REPORT_ADAPTER_ID,
        "manifest_id": f"TAILORED-AUTO-JUDGEMENT-{fingerprint[:16]}",
        "created_at": created_at,
        "source_real_sample_execution_manifest_id": str(execution_manifest.get("manifest_id") or ""),
        "source_real_sample_execution_manifest_path": str(execution_path),
        "source_rule_calibration_manifest_id": str(calibration_manifest.get("manifest_id") or ""),
        "source_rule_calibration_manifest_path": str(calibration_path),
        "source_tailored_review_adjudication_manifest_id": str(adjudication_manifest.get("manifest_id") or ""),
        "source_tailored_review_adjudication_manifest_path": str(adjudication_path or ""),
        "source_markitdown_replay_impact_manifest_id": str(markitdown_manifest.get("manifest_id") or ""),
        "source_markitdown_replay_impact_manifest_path": str(markitdown_path or ""),
        "optional_input_states": {
            "tailored_review_adjudication": adjudication_state,
            "markitdown_replay_impact": markitdown_state,
        },
        "tailored_signal_seed_path": str(seed_path),
        "items": judgement_items,
        "sample_items": judgement_items[:80],
        "summary": summary,
        "allowed_internal_terms": [
            "疑似定制标",
            "限制竞争线索",
            "控标风险线索",
            "围标线索",
            "串标线索",
            "陪标线索",
            "废标风险线索",
            "电子监管线索",
        ],
        "prohibited_output_policy_id": "NO_FORMAL_LEGAL_OR_AWARD_OUTCOME_CONCLUSION",
        "safety": {
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "formal_rule_threshold_mutation_enabled": False,
            "formal_seed_weight_mutation_enabled": False,
            "external_ai_review_executed": False,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "raw_html_or_blob_stored": False,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return manifest


def _build_judgement_item(
    project_item: Mapping[str, Any],
    *,
    calibration_item: Mapping[str, Any],
    adjudication_item: Mapping[str, Any],
    markitdown_item: Mapping[str, Any],
    seed_path: Path,
) -> dict[str, Any]:
    profile_inputs = _profile_inputs(project_item)
    profile = build_tailored_bid_signal_profile(
        profile_inputs,
        text=_profile_text(project_item),
        seed_path=seed_path,
    )
    merged_indices = _merged_indices(profile, calibration_item)
    evidence_status = _evidence_status(project_item, calibration_item, profile)
    system_judgement_state = _system_judgement_state(
        indices=merged_indices,
        signal_count=_int_value(profile.get("tailored_bid_signal_count"), default=0),
        evidence_status=evidence_status,
    )
    recommended_action = _recommended_system_action(system_judgement_state, merged_indices)
    allowed_terms = _allowed_terms(merged_indices)
    section_guardrail_reasons = _section_guardrail_reasons(profile)
    target_id = str(project_item.get("target_id") or calibration_item.get("target_id") or "")
    return {
        "judgement_item_id": f"TAILORED-AUTO-JDG-{_fingerprint({'target_id': target_id})[:12]}",
        "target_id": target_id,
        "parent_target_id": str(project_item.get("parent_target_id") or calibration_item.get("parent_target_id") or ""),
        "candidate_key": str(project_item.get("candidate_key") or calibration_item.get("candidate_key") or ""),
        "project_id": str(project_item.get("project_id") or calibration_item.get("project_id") or ""),
        "project_name": str(project_item.get("project_name") or calibration_item.get("project_name") or ""),
        "source_url": str(project_item.get("source_url") or calibration_item.get("source_url") or ""),
        "document_kind": str(project_item.get("document_kind") or calibration_item.get("document_kind") or ""),
        "jurisdiction": str(project_item.get("jurisdiction") or calibration_item.get("jurisdiction") or ""),
        "source_profile_id": str(project_item.get("source_profile_id") or calibration_item.get("source_profile_id") or ""),
        "target_execution_state": str(project_item.get("target_execution_state") or calibration_item.get("target_execution_state") or ""),
        "system_judgement_state": system_judgement_state,
        "recommended_system_action": recommended_action,
        "primary_allowed_terms": allowed_terms,
        **merged_indices,
        "tailored_bid_risk_level": str(
            profile.get("tailored_bid_risk_level")
            or calibration_item.get("tailored_bid_risk_level")
            or ""
        ),
        "tailored_bid_sub_indices": dict(
            profile.get("tailored_bid_sub_indices")
            or calibration_item.get("tailored_bid_sub_indices")
            or {}
        ),
        "tailored_bid_signal_count": _int_value(profile.get("tailored_bid_signal_count"), default=0),
        "tailored_bid_signal_families": dict(profile.get("tailored_bid_signal_families") or {}),
        "document_section_slice_types": list((profile.get("document_section_profile") or {}).get("section_slice_types") or []),
        "document_section_slice_count": _int_value((profile.get("document_section_profile") or {}).get("section_slice_count"), default=0),
        "section_guardrail_blocked_count": _int_value(profile.get("formal_index_weight_blocked_count"), default=0),
        "section_guardrail_reasons": section_guardrail_reasons,
        "evidence_status": evidence_status,
        "system_review_reason": _system_review_reason(
            indices=merged_indices,
            evidence_status=evidence_status,
            section_guardrail_reasons=section_guardrail_reasons,
            profile=profile,
        ),
        "adjudication_disposition_optional": str(adjudication_item.get("review_disposition") or ""),
        "markitdown_replay_state_optional": str(markitdown_item.get("replay_state") or ""),
        "markitdown_text_gain_optional": bool(markitdown_item.get("markitdown_text_gain")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    judgement_items: list[Mapping[str, Any]],
    calibration_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    calibration_summary = dict(calibration_manifest.get("summary") or {})
    sample_count = len(judgement_items)
    calibration_sample_count = _int_value(calibration_summary.get("tailored_sample_count"), default=0)
    effective_sample_count = max(sample_count, calibration_sample_count)
    sample_state = "SAMPLE_READY" if effective_sample_count >= SAMPLE_READY_MIN_COUNT else "INSUFFICIENT_SAMPLE"
    return {
        "sample_count": sample_count,
        "tailored_sample_count": effective_sample_count,
        "sample_state": sample_state,
        "system_judgement_state_counts": _counts(str(item.get("system_judgement_state") or "") for item in judgement_items),
        "recommended_system_action_counts": _counts(str(item.get("recommended_system_action") or "") for item in judgement_items),
        "source_profile_distribution": _counts(str(item.get("source_profile_id") or "") for item in judgement_items),
        "document_kind_distribution": _counts(str(item.get("document_kind") or "") for item in judgement_items),
        "jurisdiction_distribution": _counts(str(item.get("jurisdiction") or "") for item in judgement_items),
        "evidence_state_counts": _counts(
            str(dict(item.get("evidence_status") or {}).get("evidence_state") or "")
            for item in judgement_items
        ),
        "index_distribution": {
            field_name: _index_distribution(judgement_items, field_name)
            for field_name in INDEX_FIELDS
        },
        "section_guardrail_blocked_count": sum(
            _int_value(item.get("section_guardrail_blocked_count"), default=0)
            for item in judgement_items
        ),
        "section_guardrail_reason_counts": _counts(
            reason
            for item in judgement_items
            for reason in _string_list(item.get("section_guardrail_reasons"))
        ),
        "primary_allowed_term_counts": _counts(
            term
            for item in judgement_items
            for term in _string_list(item.get("primary_allowed_terms"))
        ),
        "formal_rule_threshold_mutation_enabled": False,
        "formal_seed_weight_mutation_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _merged_indices(profile: Mapping[str, Any], calibration_item: Mapping[str, Any]) -> dict[str, int]:
    sub_indices = dict(profile.get("tailored_bid_sub_indices") or calibration_item.get("tailored_bid_sub_indices") or {})
    return {
        "tailored_bid_index": max(
            _int_value(profile.get("tailored_bid_index"), default=0),
            _int_value(calibration_item.get("tailored_bid_index"), default=0),
        ),
        "bid_rigging_index": max(
            _int_value(profile.get("bid_rigging_index"), default=0),
            _int_value(calibration_item.get("bid_rigging_index"), default=0),
        ),
        "cover_bid_index": max(
            _int_value(profile.get("cover_bid_index"), default=0),
            _int_value(calibration_item.get("cover_bid_index"), default=0),
        ),
        "collusion_trace_index": max(
            _int_value(profile.get("collusion_trace_index"), default=0),
            _int_value(calibration_item.get("collusion_trace_index"), default=0),
        ),
        "fatal_rejection_complexity_index": max(
            _int_value(profile.get("fatal_rejection_complexity_index"), default=0),
            _int_value(calibration_item.get("fatal_rejection_complexity_index"), default=0),
            _int_value(sub_indices.get("fatal_rejection_complexity_index"), default=0),
        ),
        "electronic_supervision_index": max(
            _int_value(profile.get("electronic_supervision_index"), default=0),
            _int_value(calibration_item.get("electronic_supervision_index"), default=0),
        ),
    }


def _system_judgement_state(
    *,
    indices: Mapping[str, int],
    signal_count: int,
    evidence_status: Mapping[str, Any],
) -> str:
    if evidence_status.get("evidence_state") == INSUFFICIENT_EVIDENCE:
        return INSUFFICIENT_EVIDENCE
    if any(_int_value(indices.get(field_name), default=0) >= INDEX_REVIEW_THRESHOLD for field_name in INDEX_FIELDS):
        return RISK_CLUE_DETECTED
    if signal_count > 0:
        return WEAK_SIGNAL_ONLY
    return NO_SIGNAL


def _recommended_system_action(system_judgement_state: str, indices: Mapping[str, int]) -> str:
    if system_judgement_state == INSUFFICIENT_EVIDENCE:
        return EVIDENCE_BLOCKED_RETRY_PARSE
    max_index = max((_int_value(indices.get(field_name), default=0) for field_name in INDEX_FIELDS), default=0)
    if system_judgement_state == RISK_CLUE_DETECTED and max_index >= INDEX_HIGH_THRESHOLD:
        return AVOID_OR_CHALLENGE_EVALUATE
    if system_judgement_state == RISK_CLUE_DETECTED:
        return CAUTION_TENDER
    if system_judgement_state == WEAK_SIGNAL_ONLY:
        return TRACK_LOW_PRIORITY
    return PROCEED_STANDARD


def _allowed_terms(indices: Mapping[str, int]) -> list[str]:
    terms: list[str] = []
    if _int_value(indices.get("tailored_bid_index"), default=0) >= INDEX_REVIEW_THRESHOLD:
        terms.append("控标风险线索")
        terms.append("限制竞争线索")
    if _int_value(indices.get("bid_rigging_index"), default=0) >= INDEX_REVIEW_THRESHOLD:
        terms.append("围标线索")
        terms.append("串标线索")
    if _int_value(indices.get("collusion_trace_index"), default=0) >= INDEX_REVIEW_THRESHOLD:
        terms.append("串标线索")
    if _int_value(indices.get("cover_bid_index"), default=0) >= INDEX_REVIEW_THRESHOLD:
        terms.append("陪标线索")
    if _int_value(indices.get("fatal_rejection_complexity_index"), default=0) >= INDEX_REVIEW_THRESHOLD:
        terms.append("废标风险线索")
    if _int_value(indices.get("electronic_supervision_index"), default=0) >= INDEX_REVIEW_THRESHOLD:
        terms.append("电子监管线索")
    return _dedupe_strings(terms)


def _evidence_status(
    project_item: Mapping[str, Any],
    calibration_item: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    parse_summary = dict(project_item.get("parse_summary") or {})
    reasons: list[str] = []
    document_counts = _mapping_counts(parse_summary.get("document_completeness_state_counts"))
    document_state = str(project_item.get("document_completeness_state") or "")
    all_document_states = set(document_counts)
    if document_state:
        all_document_states.add(document_state)
    for state in sorted(all_document_states.intersection(EVIDENCE_BLOCKER_STATES)):
        reasons.append(f"document_completeness_state={state}")
    if _int_value(parse_summary.get("attachment_missing_review_count"), default=0):
        reasons.append("attachment_missing_review_count>0")
    ocr_count = _int_value(parse_summary.get("ocr_required_count"), default=0) + _int_value(
        parse_summary.get("attachment_ocr_required_count"),
        default=0,
    )
    if ocr_count:
        reasons.append("ocr_required_or_attachment_ocr_required")
    for failure in _string_list(project_item.get("failure_taxonomy")):
        if any(marker in failure for marker in EVIDENCE_BLOCKER_MARKERS):
            reasons.append(f"failure_taxonomy={failure}")
    profile_evidence_state = str(profile.get("evidence_state") or calibration_item.get("tailored_bid_evidence_state") or "")
    if profile_evidence_state == INSUFFICIENT_EVIDENCE:
        reasons.append("tailored_bid_evidence_state=INSUFFICIENT_EVIDENCE")
    evidence_state = INSUFFICIENT_EVIDENCE if reasons else (profile_evidence_state or "EVIDENCE_TEXT_AVAILABLE")
    return {
        "evidence_state": evidence_state,
        "evidence_blocker_reasons": _dedupe_strings(reasons),
        "document_completeness_state_counts": document_counts,
        "notice_version_chain_state_counts": _mapping_counts(
            parse_summary.get("notice_version_chain_state_counts")
        ),
    }


def _section_guardrail_reasons(profile: Mapping[str, Any]) -> list[str]:
    return _dedupe_strings(
        reason
        for hit in list(profile.get("signal_hits") or [])
        if isinstance(hit, Mapping)
        for reason in _string_list(hit.get("section_gate_discount_reasons"))
    )


def _system_review_reason(
    *,
    indices: Mapping[str, int],
    evidence_status: Mapping[str, Any],
    section_guardrail_reasons: list[str],
    profile: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    for field_name in INDEX_FIELDS:
        value = _int_value(indices.get(field_name), default=0)
        if value >= INDEX_REVIEW_THRESHOLD:
            reasons.append(f"{field_name}={value}")
    reasons.extend(_string_list(evidence_status.get("evidence_blocker_reasons")))
    reasons.extend(section_guardrail_reasons)
    reasons.extend(_string_list(profile.get("ai_review_reasons")))
    return _dedupe_strings(reasons)


def _profile_inputs(project_item: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(project_item)
    parse_summary = project_item.get("parse_summary")
    if not isinstance(parse_summary, Mapping):
        return result
    document_counts = _mapping_counts(parse_summary.get("document_completeness_state_counts"))
    version_counts = _mapping_counts(parse_summary.get("notice_version_chain_state_counts"))
    if not result.get("document_completeness_state") and document_counts:
        result["document_completeness_state"] = next(iter(document_counts))
    if not result.get("notice_version_chain_state") and version_counts:
        result["notice_version_chain_state"] = next(iter(version_counts))
    result["attachment_ocr_required_count"] = _int_value(
        parse_summary.get("attachment_ocr_required_count"),
        default=0,
    ) + _int_value(parse_summary.get("ocr_required_count"), default=0)
    result["attachment_missing_review_count"] = _int_value(
        parse_summary.get("attachment_missing_review_count"),
        default=0,
    )
    return result


def _profile_text(project_item: Mapping[str, Any]) -> str:
    parse_summary = dict(project_item.get("parse_summary") or {})
    parts: list[str] = []
    for value in (
        project_item.get("source_text"),
        project_item.get("detail_text"),
        project_item.get("document_text"),
        project_item.get("parsed_text"),
        project_item.get("attachment_text"),
        project_item.get("source_title"),
        project_item.get("project_name"),
        project_item.get("notice_title"),
        parse_summary.get("text_probe"),
        parse_summary.get("sample_text"),
        parse_summary.get("extracted_text"),
        parse_summary.get("ocr_text"),
    ):
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for block in _string_list(project_item.get("qualification_text_candidate_blocks")):
        parts.append(block)
    return _clip_text("\n".join(dict.fromkeys(parts)), TEXT_PROBE_LIMIT * 4)


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
    return _item_index(manifest.get("tailored_items") or manifest.get("items") or [])


def _adjudication_item_index(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return _item_index(manifest.get("items") or [])


def _markitdown_item_index(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return _item_index(manifest.get("items") or [])


def _item_index(items: Any) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for item in list(items or []):
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
    return _match_optional_item(project_item, calibration_index)


def _match_optional_item(
    project_item: Mapping[str, Any],
    item_index: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    target_id = str(project_item.get("target_id") or "")
    if target_id in item_index:
        return item_index[target_id]
    parent_target_id = str(project_item.get("parent_target_id") or "")
    candidate_key = str(project_item.get("candidate_key") or "")
    if parent_target_id and candidate_key:
        return item_index.get(f"{parent_target_id}::{candidate_key}", {})
    return {}


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


def _load_optional_json_file(path: Path | None, label: str) -> tuple[dict[str, Any], str]:
    if path is None:
        return {}, "NOT_PROVIDED"
    if not path.exists():
        return {}, "MISSING_OPTIONAL"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"LOAD_FAILED:{exc}"
    if isinstance(payload, Mapping):
        return dict(payload), "LOADED"
    return {}, "NOT_OBJECT"


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _mapping_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): _int_value(raw_value, default=0)
        for key, raw_value in value.items()
        if str(key)
    }


def _index_distribution(items: list[Mapping[str, Any]], field_name: str) -> dict[str, int]:
    return _counts(_index_bucket(_int_value(item.get(field_name), default=0)) for item in items)


def _index_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value <= 20:
        return "1-20"
    if value <= 40:
        return "21-40"
    if value <= 60:
        return "41-60"
    if value <= 80:
        return "61-80"
    return "81-100"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Mapping):
        return [str(value)]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


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


def _clip_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[TRUNCATED]"


def _fingerprint(payload: Mapping[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build tailored auto judgement report")
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
    parser.add_argument("--rule-calibration-manifest-json", required=True)
    parser.add_argument("--tailored-review-adjudication-json")
    parser.add_argument("--markitdown-replay-impact-json")
    parser.add_argument("--tailored-signal-seed-json")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_tailored_auto_judgement_report_manifest(
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
        rule_calibration_manifest_json=args.rule_calibration_manifest_json,
        tailored_review_adjudication_json=args.tailored_review_adjudication_json,
        markitdown_replay_impact_json=args.markitdown_replay_impact_json,
        tailored_signal_seed_json=args.tailored_signal_seed_json,
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
            "tailored auto judgement report: "
            f"sample_state={summary.get('sample_state')} "
            f"sample_count={summary.get('sample_count')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
