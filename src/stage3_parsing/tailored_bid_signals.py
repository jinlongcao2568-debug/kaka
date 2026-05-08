from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "evaluation"
    / "tailored_bid_signal_seed.json"
)

REQUIRED_SIGNAL_FIELDS = (
    "sample_id",
    "signal_family",
    "signal_keyword",
    "keyword_patterns",
    "bid_file_sections",
    "index_targets",
    "base_weight",
    "counter_reasons",
    "source_classes",
    "signal_domain",
    "observable_from",
    "source_confidence",
    "rule_gate_condition",
    "evidence_gate_condition",
    "should_trigger_stage5_review",
    "should_trigger_ai_review",
    "customer_visible_allowed",
    "no_legal_conclusion",
)

TEXT_KEYS = (
    "source_text",
    "detail_text",
    "document_text",
    "parsed_text",
    "attachment_text",
    "source_title",
    "project_name",
)

INSUFFICIENT_DOCUMENT_STATES = {
    "DETAIL_SNAPSHOT_MISSING_REVIEW",
    "ATTACHMENTS_NOT_CAPTURED_REVIEW",
    "PARTIAL_REVIEW_REQUIRED",
}
INSUFFICIENT_VERSION_STATES = {"VERSION_REVIEW_REQUIRED", "CLARIFICATION_OR_ADDENDUM_PRESENT"}
INSUFFICIENT_OCR_STATES = {"OCR_REQUIRED", "OCR_ENGINE_UNAVAILABLE"}
TAILORED_INDEX_DOMAINS = {"TAILORED_COMPETITION"}
DEFAULT_TEXT_OBSERVABLE_FROM = {"tender_file", "attachment"}
DOCUMENT_KIND_OBSERVABLE_FROM = {
    "complaint_decision": {"complaint_case", "post_award_notice"},
    "official_case": {"complaint_case", "post_award_notice"},
    "failed_bid_notice": {"post_award_notice"},
    "flow_or_re_tender_notice": {"post_award_notice"},
    "candidate_notice": {"post_award_notice"},
    "award_notice": {"post_award_notice"},
    "tender_notice": {"tender_file", "attachment"},
    "tender": {"tender_file", "attachment"},
}


def load_tailored_bid_signal_seed(seed_path: str | Path | None = None) -> dict[str, Any]:
    return _load_tailored_bid_signal_seed(str(Path(seed_path or DEFAULT_SEED_PATH)))


@lru_cache(maxsize=8)
def _load_tailored_bid_signal_seed(seed_path: str) -> dict[str, Any]:
    path = Path(seed_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("tailored bid signal seed must be a JSON object")
    source_policy = dict(payload.get("source_class_policy") or {})
    allowed_classes = set(str(item) for item in source_policy.get("allowed_source_classes") or [])
    if "SOCIAL_EXPERIENCE" not in allowed_classes:
        raise ValueError("tailored bid signal seed must preserve SOCIAL_EXPERIENCE source class")
    domain_policy = dict(payload.get("signal_domain_policy") or {})
    allowed_domains = set(str(item) for item in domain_policy.get("allowed_signal_domains") or [])
    if not allowed_domains:
        raise ValueError("tailored bid signal seed must define allowed signal domains")
    observable_policy = dict(payload.get("observable_source_policy") or {})
    allowed_observable_from = set(
        str(item) for item in observable_policy.get("allowed_observable_from") or []
    )
    if not allowed_observable_from:
        raise ValueError("tailored bid signal seed must define allowed observable sources")
    confidence_policy = dict(payload.get("source_confidence_policy") or {})
    allowed_confidence = set(
        str(item) for item in confidence_policy.get("allowed_source_confidence") or []
    )
    if not allowed_confidence:
        raise ValueError("tailored bid signal seed must define allowed source confidence values")
    signals = payload.get("signals")
    if not isinstance(signals, list) or not signals:
        raise ValueError("tailored bid signal seed must include non-empty signals")

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_signal in enumerate(signals):
        if not isinstance(raw_signal, Mapping):
            raise ValueError(f"tailored bid signal at index {index} must be an object")
        signal = dict(raw_signal)
        missing = [field for field in REQUIRED_SIGNAL_FIELDS if field not in signal]
        if missing:
            raise ValueError(f"tailored bid signal {index} missing fields: {', '.join(missing)}")
        sample_id = str(signal.get("sample_id") or "").strip()
        if not sample_id:
            raise ValueError(f"tailored bid signal {index} missing sample_id")
        if sample_id in seen_ids:
            continue
        seen_ids.add(sample_id)
        if signal.get("customer_visible_allowed") is not False:
            raise ValueError(f"tailored bid signal {sample_id} must be customer invisible")
        if signal.get("no_legal_conclusion") is not True:
            raise ValueError(f"tailored bid signal {sample_id} must forbid legal conclusion")
        source_classes = [str(item) for item in signal.get("source_classes") or []]
        invalid_classes = sorted(set(source_classes) - allowed_classes)
        if invalid_classes:
            raise ValueError(
                f"tailored bid signal {sample_id} has invalid source classes: {', '.join(invalid_classes)}"
            )
        signal_domain = str(signal.get("signal_domain") or "").strip()
        if signal_domain not in allowed_domains:
            raise ValueError(f"tailored bid signal {sample_id} has invalid signal_domain")
        observable_from = _dedupe_strings(signal.get("observable_from"))
        invalid_observable = sorted(set(observable_from) - allowed_observable_from)
        if invalid_observable:
            raise ValueError(
                f"tailored bid signal {sample_id} has invalid observable_from: {', '.join(invalid_observable)}"
            )
        if not observable_from:
            raise ValueError(f"tailored bid signal {sample_id} must define observable_from")
        source_confidence = str(signal.get("source_confidence") or "").strip()
        if source_confidence not in allowed_confidence:
            raise ValueError(f"tailored bid signal {sample_id} has invalid source_confidence")
        for field in ("rule_gate_condition", "evidence_gate_condition"):
            if not str(signal.get(field) or "").strip():
                raise ValueError(f"tailored bid signal {sample_id} must define {field}")
        signal["keyword_patterns"] = _dedupe_strings(signal.get("keyword_patterns"))
        signal["counter_reason_keywords"] = _dedupe_strings(signal.get("counter_reason_keywords"))
        signal["source_classes"] = _dedupe_strings(source_classes)
        signal["observable_from"] = observable_from
        signal["bid_file_sections"] = _dedupe_strings(signal.get("bid_file_sections"))
        signal["index_targets"] = _dedupe_strings(signal.get("index_targets"))
        deduped.append(signal)

    result = dict(payload)
    result["signals"] = deduped
    result["signal_count"] = len(deduped)
    result["seed_path"] = str(path)
    return result


def build_tailored_bid_signal_profile(
    inputs: Mapping[str, Any],
    *,
    text: str | None = None,
    seed_path: str | Path | None = None,
) -> dict[str, Any]:
    seed = load_tailored_bid_signal_seed(seed_path)
    raw_text = text if text is not None else _profile_text(inputs)
    normalized = _normalize(raw_text)
    hits: list[dict[str, Any]] = []
    sub_indices: dict[str, int] = {}
    source_class_counts: dict[str, int] = {}
    blind_bid_suitability_offset = 0
    observed_sources = _observed_sources(inputs, raw_text)

    for signal in seed["signals"]:
        markers = _matched_markers(normalized, signal.get("keyword_patterns"))
        if not markers:
            continue
        counter_markers = _matched_markers(normalized, signal.get("counter_reason_keywords"))
        base_weight = _int_value(signal.get("base_weight"), default=0)
        risk_weight = max(base_weight, 0)
        counter_discount = min(risk_weight, len(counter_markers) * 5)
        applied_weight = max(risk_weight - counter_discount, 0)
        index_targets = list(signal.get("index_targets") or [])
        signal_domain = str(signal.get("signal_domain") or "")
        tailored_index_weight = (
            applied_weight
            if base_weight > 0 and signal_domain in TAILORED_INDEX_DOMAINS
            else 0
        )
        if base_weight < 0:
            blind_bid_suitability_offset += abs(base_weight)
            applied_weight = 0
            tailored_index_weight = 0

        for source_class in signal.get("source_classes") or []:
            source_class_counts[source_class] = source_class_counts.get(source_class, 0) + 1
        for target in index_targets:
            if not target:
                continue
            if base_weight < 0:
                sub_indices[target] = max(0, sub_indices.get(target, 0) - abs(base_weight))
            else:
                sub_indices[target] = min(100, sub_indices.get(target, 0) + applied_weight)
        observable_from = list(signal.get("observable_from") or [])
        observable_mismatch = bool(
            observed_sources and observable_from and not set(observable_from).intersection(observed_sources)
        )

        hits.append(
            {
                "sample_id": signal["sample_id"],
                "signal_family": signal["signal_family"],
                "signal_domain": signal_domain,
                "signal_type": signal["signal_family"],
                "signal_keyword": signal["signal_keyword"],
                "markers": markers,
                "bid_file_sections": list(signal.get("bid_file_sections") or []),
                "observable_from": observable_from,
                "observed_from": sorted(observed_sources),
                "observable_mismatch_review_required": observable_mismatch,
                "source_confidence": signal.get("source_confidence"),
                "index_targets": list(signal.get("index_targets") or []),
                "base_weight": base_weight,
                "applied_weight": applied_weight,
                "tailored_index_weight": tailored_index_weight,
                "counter_reason_markers": counter_markers,
                "counter_reasons": list(signal.get("counter_reasons") or []),
                "source_classes": list(signal.get("source_classes") or []),
                "rule_gate_condition": signal.get("rule_gate_condition"),
                "evidence_gate_condition": signal.get("evidence_gate_condition"),
                "match_basis": "seed_keyword_profile",
                "risk_role": _risk_role(signal),
                "should_trigger_stage5_review": bool(signal.get("should_trigger_stage5_review")),
                "should_trigger_ai_review": bool(signal.get("should_trigger_ai_review")),
                "review_required": True,
                "customer_visible_allowed": False,
                "customer_visible": False,
                "no_legal_conclusion": True,
                "legal_conclusion_allowed": False,
            }
        )

    tailored_bid_index = min(
        100,
        sum(_int_value(hit.get("tailored_index_weight"), default=0) for hit in hits),
    )
    evidence_state, evidence_reasons = _evidence_state(inputs, raw_text)
    risk_level = _risk_level(tailored_bid_index)
    if evidence_state == "INSUFFICIENT_EVIDENCE" and not normalized:
        risk_level = "INSUFFICIENT_EVIDENCE"
    stage5_required = (
        tailored_bid_index >= 21
        or evidence_state == "INSUFFICIENT_EVIDENCE"
        or any(
            bool(hit.get("should_trigger_stage5_review"))
            and hit.get("signal_domain") in TAILORED_INDEX_DOMAINS
            for hit in hits
        )
    )
    ai_required = (
        tailored_bid_index >= 41
        or evidence_state == "INSUFFICIENT_EVIDENCE"
        or any(
            bool(hit.get("should_trigger_ai_review"))
            and hit.get("signal_domain") in TAILORED_INDEX_DOMAINS
            for hit in hits
        )
        or any(bool(hit.get("observable_mismatch_review_required")) for hit in hits)
    )
    ai_review_reasons: list[str] = []
    if tailored_bid_index >= 41:
        ai_review_reasons.append(f"tailored_bid_index={tailored_bid_index}")
    ai_review_reasons.extend(evidence_reasons)
    for hit in hits:
        if hit.get("should_trigger_ai_review") and hit.get("signal_domain") in TAILORED_INDEX_DOMAINS:
            ai_review_reasons.append(f"seed_ai_review:{hit['sample_id']}:{hit['signal_family']}")
        if hit.get("observable_mismatch_review_required"):
            ai_review_reasons.append(f"observable_mismatch:{hit['sample_id']}")

    return {
        "profile_state": "PROFILED_REVIEW_READY" if normalized else "PROFILE_REVIEW_REQUIRED",
        "seed_id": seed.get("seed_id"),
        "seed_version": seed.get("seed_version"),
        "seed_path": seed.get("seed_path"),
        "tailored_bid_index": tailored_bid_index,
        "tailored_bid_risk_level": risk_level,
        "tailored_bid_sub_indices": dict(sorted(sub_indices.items())),
        "tailored_bid_signal_count": len(hits),
        "tailored_bid_signal_hits": hits,
        "signal_hits": hits,
        "tailored_bid_signal_families": _counts(hit.get("signal_family") for hit in hits),
        "tailored_bid_signal_domains": _counts(hit.get("signal_domain") for hit in hits),
        "source_class_counts": dict(sorted(source_class_counts.items())),
        "counter_reason_count": sum(1 for hit in hits if hit.get("counter_reason_markers")),
        "observable_from": sorted(observed_sources),
        "observable_mismatch_count": sum(
            1 for hit in hits if hit.get("observable_mismatch_review_required")
        ),
        "observable_mismatch_review_required": any(
            bool(hit.get("observable_mismatch_review_required")) for hit in hits
        ),
        "tailored_bid_stage5_review_required": stage5_required,
        "tailored_bid_ai_review_required": ai_required,
        "ai_review_reasons": _dedupe_strings(ai_review_reasons),
        "evidence_state": evidence_state,
        "evidence_reasons": evidence_reasons,
        "blind_bid_suitability_offset": blind_bid_suitability_offset,
        "allowed_output_terms": list(seed.get("allowed_output_terms") or []),
        "prohibited_output_terms": list(seed.get("prohibited_output_terms") or []),
        "customer_visible_allowed": False,
        "customer_visible": False,
        "internal_review_only": True,
        "no_legal_conclusion": True,
        "no_illegality_or_reserved_winner_conclusion": True,
    }


def _profile_text(inputs: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in TEXT_KEYS:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(dict.fromkeys(parts))


def _observed_sources(inputs: Mapping[str, Any], text: str) -> set[str]:
    for key in ("input_observable_from", "source_observable_from", "observed_from", "observable_from"):
        values = _dedupe_strings(_as_list(inputs.get(key)))
        if values:
            return set(values)
    document_kind = str(inputs.get("document_kind") or inputs.get("evaluation_document_kind") or "").strip()
    if document_kind in DOCUMENT_KIND_OBSERVABLE_FROM:
        return set(DOCUMENT_KIND_OBSERVABLE_FROM[document_kind])
    if str(text or "").strip():
        return set(DEFAULT_TEXT_OBSERVABLE_FROM)
    return set()


def _matched_markers(normalized_text: str, patterns: Any) -> list[str]:
    markers: list[str] = []
    for raw_pattern in patterns or []:
        pattern = str(raw_pattern or "").strip()
        if not pattern:
            continue
        normalized_pattern = _normalize(pattern)
        if normalized_pattern and (
            normalized_pattern in normalized_text or normalized_pattern.casefold() in normalized_text.casefold()
        ):
            markers.append(pattern)
    return _dedupe_strings(markers)


def _evidence_state(inputs: Mapping[str, Any], text: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    document_state = str(inputs.get("document_completeness_state") or "")
    version_state = str(inputs.get("notice_version_chain_state") or "")
    ocr_state = str(inputs.get("ocr_state") or "")
    if document_state in INSUFFICIENT_DOCUMENT_STATES:
        reasons.append(f"document_completeness_state={document_state}")
    if version_state in INSUFFICIENT_VERSION_STATES:
        reasons.append(f"notice_version_chain_state={version_state}")
    if ocr_state in INSUFFICIENT_OCR_STATES:
        reasons.append(f"ocr_state={ocr_state}")
    if _int_value(inputs.get("attachment_ocr_required_count"), default=0) > 0:
        reasons.append("attachment_ocr_required_count>0")
    if _int_value(inputs.get("attachment_missing_review_count"), default=0) > 0:
        reasons.append("attachment_missing_review_count>0")
    if not str(text or "").strip() and reasons:
        return "INSUFFICIENT_EVIDENCE", _dedupe_strings(reasons)
    if reasons:
        return "PARTIAL_EVIDENCE_REVIEW", _dedupe_strings(reasons)
    return "EVIDENCE_TEXT_AVAILABLE" if str(text or "").strip() else "NO_TEXT_SIGNAL", []


def _risk_level(index: int) -> str:
    if index <= 0:
        return "NO_SIGNAL"
    if index <= 20:
        return "LOW"
    if index <= 40:
        return "WEAK_CLUE_REVIEW"
    if index <= 60:
        return "MEDIUM_CLUE_REVIEW"
    if index <= 80:
        return "HIGH_CLUE_REVIEW"
    return "STRONG_CLUE_REVIEW"


def _risk_role(signal: Mapping[str, Any]) -> str:
    domain = str(signal.get("signal_domain") or "")
    if domain in {"FATAL_REJECTION", "DOCUMENT_QUALITY"}:
        return "rejection_or_document_obstruction_clue"
    if domain in {"ELECTRONIC_SUPERVISION", "PRICE_PERFORMANCE"}:
        return "collusion_or_electronic_supervision_clue"
    if domain == "BID_SELECTION":
        return "bid_selection_suitability_clue"
    if domain == "REGIONAL_RULE_PROFILE":
        return "regional_rule_profile_clue"
    return "tailored_or_restrictive_competition_clue"


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


__all__ = [
    "DEFAULT_SEED_PATH",
    "build_tailored_bid_signal_profile",
    "load_tailored_bid_signal_seed",
]
