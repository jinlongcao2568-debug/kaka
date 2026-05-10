from __future__ import annotations

import hashlib
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
SYSTEM_RISK_INDEX_FIELDS = (
    "collusion_trace_index",
    "cover_bid_index",
    "bid_rigging_index",
    "fatal_rejection_complexity_index",
    "electronic_supervision_index",
)
SYSTEM_INDEX_REVIEW_THRESHOLD = 21
DEFAULT_TEXT_OBSERVABLE_FROM = {"tender_file", "attachment"}
POST_AWARD_OR_AUXILIARY_DOCUMENT_KINDS = {
    "candidate_notice",
    "award_notice",
    "award_result",
    "failed_bid_notice",
    "flow_or_re_tender_notice",
}
DOCUMENT_KIND_OBSERVABLE_FROM = {
    "complaint_decision": {"complaint_case", "post_award_notice"},
    "official_case": {"complaint_case", "post_award_notice"},
    "failed_bid_notice": {"post_award_notice"},
    "flow_or_re_tender_notice": {"post_award_notice"},
    "candidate_notice": {"post_award_notice"},
    "award_notice": {"post_award_notice"},
    "award_result": {"post_award_notice"},
    "tender_notice": {"tender_file", "attachment"},
    "tender": {"tender_file", "attachment"},
    "tender_file": {"tender_file", "attachment"},
}
NON_PRIMARY_TEXT_MARKERS = (
    "开标记录",
    "开标情况",
    "澄清文件",
    "澄清公告",
    "补遗",
    "答疑文件",
    "变更通知",
    "更正公告",
    "中标候选人公示",
    "中标结果公告",
    "成交结果公告",
    "中标信息",
    "评标报告",
    "定标报告",
    "评审报告",
)
SECTION_MARKERS = {
    "资格条件": ("资格条件", "资格要求", "投标人资格", "供应商资格", "资格审查"),
    "评分办法": ("评分办法", "评标办法", "评分标准", "商务评分", "技术评分", "综合评分"),
    "技术参数": ("技术参数", "采购需求", "技术要求", "规格参数", "服务要求"),
    "废标条款": ("废标条款", "无效投标", "否决投标", "符合性审查", "实质性响应"),
    "附件补遗": ("附件", "澄清", "补遗", "答疑", "更正", "变更"),
    "合同付款": ("合同付款", "合同条款", "付款方式", "付款条件", "结算", "验收"),
    "电子监管线索": ("开标记录", "平台日志", "电子监管", "同一IP", "同一CA", "解密"),
    "历史公告": ("中标结果", "候选人公示", "历史公告", "投诉处理", "行政处罚"),
}
DOCUMENT_SECTION_OUTPUT_ORDER = (
    "资格条件",
    "评分办法",
    "技术参数",
    "废标条款",
    "附件补遗",
    "合同付款",
    "电子监管线索",
    "历史公告",
)
SECTION_CANONICAL_ALIASES = {
    "资格条件": "资格条件",
    "资格证明文件": "资格条件",
    "人员要求": "资格条件",
    "评分办法": "评分办法",
    "定标办法": "评分办法",
    "技术参数": "技术参数",
    "采购需求": "技术参数",
    "服务要求": "技术参数",
    "废标条款": "废标条款",
    "格式文件": "废标条款",
    "报价文件": "废标条款",
    "暗标要求": "废标条款",
    "投标文件": "废标条款",
    "投标函": "废标条款",
    "授权书": "废标条款",
    "报价表": "废标条款",
    "承诺书": "废标条款",
    "授权委托书": "废标条款",
    "工程量清单": "废标条款",
    "保证金": "废标条款",
    "声明函": "废标条款",
    "技术标": "废标条款",
    "附件": "附件补遗",
    "补遗澄清": "附件补遗",
    "商务条款": "合同付款",
    "合同付款": "合同付款",
    "合同条款": "合同付款",
    "验收条款": "合同付款",
    "电子监管线索": "电子监管线索",
    "平台日志": "电子监管线索",
    "历史公告": "历史公告",
    "公告": "历史公告",
    "投诉案例": "历史公告",
    "废标公告": "历史公告",
    "流标公告": "历史公告",
    "中标候选人公示": "历史公告",
    "中标结果公告": "历史公告",
    "监管通报": "历史公告",
    "内部材料": "历史公告",
    "中标结果": "历史公告",
    "候选人公示": "历史公告",
}
SECTION_FORMAL_INDEX_GUARDRAILS = {"附件补遗", "合同付款", "电子监管线索", "历史公告"}
PRIMARY_TENDER_CONTEXT_MARKERS = (
    "招标文件",
    "采购文件",
    "采购需求",
    "资格条件",
    "资格要求",
    "评分办法",
    "评标办法",
    "技术参数",
    "技术要求",
    "投标人须知",
)


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
    evidence_state, evidence_reasons = _evidence_state(inputs, raw_text)
    document_context_reasons = _document_context_discount_reasons(inputs, normalized)
    document_section_slices = _document_section_slices(raw_text)
    document_section_profile = _document_section_profile(raw_text, slices=document_section_slices)
    detected_sections = set(document_section_profile["detected_sections"])

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
        section_evidence = _signal_section_evidence(
            markers=markers,
            signal_sections=signal.get("bid_file_sections") or [],
            document_section_slices=document_section_slices,
        )
        section_gate_discount_reasons = _section_gate_discount_reasons(
            signal=signal,
            section_evidence=section_evidence,
        )
        evidence_gate_discount_reasons = _evidence_gate_discount_reasons(
            signal=signal,
            observable_mismatch=observable_mismatch,
            evidence_state=evidence_state,
            evidence_reasons=evidence_reasons,
            document_context_reasons=document_context_reasons,
            section_gate_discount_reasons=section_gate_discount_reasons,
        )
        if evidence_gate_discount_reasons:
            tailored_index_weight = 0
        system_index_discount_reasons = _system_index_discount_reasons(
            signal=signal,
            observable_mismatch=observable_mismatch,
            evidence_state=evidence_state,
            evidence_reasons=evidence_reasons,
            document_context_reasons=document_context_reasons,
            section_gate_discount_reasons=section_gate_discount_reasons,
        )
        system_index_weight = 0 if system_index_discount_reasons else applied_weight
        section_match_state = _section_match_state(
            signal_sections=signal.get("bid_file_sections") or [],
            detected_sections=detected_sections,
            section_evidence=section_evidence,
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
                "system_index_weight": system_index_weight,
                "system_index_discount_reasons": system_index_discount_reasons,
                "counter_reason_markers": counter_markers,
                "counter_reasons": list(signal.get("counter_reasons") or []),
                "evidence_gate_discount_reasons": evidence_gate_discount_reasons,
                "section_gate_discount_reasons": section_gate_discount_reasons,
                "formal_index_weight_blocked": bool(evidence_gate_discount_reasons),
                "system_index_weight_blocked": bool(system_index_discount_reasons),
                "section_match_state": section_match_state,
                "matched_document_sections": section_evidence["matched_sections"],
                "expected_document_sections": section_evidence["expected_sections"],
                "guardrail_document_sections": section_evidence["guardrail_sections"],
                "detected_document_sections": sorted(detected_sections),
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
    system_risk_indices = _system_risk_indices(hits)
    system_risk_levels = {
        field_name.replace("_index", "_risk_level"): _risk_level(value)
        for field_name, value in system_risk_indices.items()
    }
    risk_level = _risk_level(tailored_bid_index)
    if evidence_state == "INSUFFICIENT_EVIDENCE" and not normalized:
        risk_level = "INSUFFICIENT_EVIDENCE"
    stage5_required = (
        tailored_bid_index >= 21
        or any(value >= SYSTEM_INDEX_REVIEW_THRESHOLD for value in system_risk_indices.values())
        or evidence_state == "INSUFFICIENT_EVIDENCE"
        or any(
            bool(hit.get("should_trigger_stage5_review"))
            and (
                hit.get("signal_domain") in TAILORED_INDEX_DOMAINS
                or _int_value(hit.get("system_index_weight"), default=0) > 0
            )
            for hit in hits
        )
    )
    ai_required = (
        tailored_bid_index >= 41
        or any(value >= 41 for value in system_risk_indices.values())
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
    for field_name, value in system_risk_indices.items():
        if value >= 41:
            ai_review_reasons.append(f"{field_name}={value}")
    ai_review_reasons.extend(evidence_reasons)
    for hit in hits:
        if hit.get("should_trigger_ai_review") and hit.get("signal_domain") in TAILORED_INDEX_DOMAINS:
            ai_review_reasons.append(f"seed_ai_review:{hit['sample_id']}:{hit['signal_family']}")
        if hit.get("observable_mismatch_review_required"):
            ai_review_reasons.append(f"observable_mismatch:{hit['sample_id']}")
        for reason in hit.get("evidence_gate_discount_reasons") or []:
            ai_review_reasons.append(f"evidence_gate_discount:{hit['sample_id']}:{reason}")

    return {
        "profile_state": "PROFILED_REVIEW_READY" if normalized else "PROFILE_REVIEW_REQUIRED",
        "seed_id": seed.get("seed_id"),
        "seed_version": seed.get("seed_version"),
        "seed_path": seed.get("seed_path"),
        "tailored_bid_index": tailored_bid_index,
        "tailored_bid_risk_level": risk_level,
        "tailored_bid_sub_indices": dict(sorted(sub_indices.items())),
        **system_risk_indices,
        **system_risk_levels,
        "system_risk_indices": dict(sorted(system_risk_indices.items())),
        "system_risk_levels": dict(sorted(system_risk_levels.items())),
        "system_auto_judgement": _system_auto_judgement(
            tailored_bid_index=tailored_bid_index,
            tailored_bid_risk_level=risk_level,
            system_risk_indices=system_risk_indices,
            system_risk_levels=system_risk_levels,
            hits=hits,
            evidence_state=evidence_state,
        ),
        "document_section_profile": document_section_profile,
        "document_section_slices": document_section_slices,
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
        "formal_index_weight_blocked_count": sum(
            1 for hit in hits if hit.get("formal_index_weight_blocked")
        ),
        "formal_index_weight_block_reasons": _dedupe_strings(
            reason
            for hit in hits
            for reason in hit.get("evidence_gate_discount_reasons") or []
        ),
        "system_index_weight_blocked_count": sum(
            1 for hit in hits if hit.get("system_index_weight_blocked")
        ),
        "system_index_weight_block_reasons": _dedupe_strings(
            reason
            for hit in hits
            for reason in hit.get("system_index_discount_reasons") or []
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
    qualification_blocks = _dedupe_strings(inputs.get("qualification_text_candidate_blocks"))
    if qualification_blocks:
        parts.append("资格条件\n" + "\n".join(qualification_blocks))
    return "\n".join(dict.fromkeys(parts))


def _system_risk_indices(hits: list[Mapping[str, Any]]) -> dict[str, int]:
    indices = {field_name: 0 for field_name in SYSTEM_RISK_INDEX_FIELDS}
    for hit in hits:
        weight = _int_value(hit.get("system_index_weight"), default=0)
        if weight <= 0:
            continue
        targets = set(_dedupe_strings(hit.get("index_targets")))
        domain = str(hit.get("signal_domain") or "")
        family = str(hit.get("signal_family") or "")
        if "collusion_trace_index" in targets or family == "collusion_trace":
            indices["collusion_trace_index"] += weight
        if "cover_bid_index" in targets or family == "cover_bid_jargon":
            indices["cover_bid_index"] += weight
        if "bid_rigging_index" in targets or family == "bid_rigging_jargon":
            indices["bid_rigging_index"] += weight
        if domain == "FATAL_REJECTION":
            indices["fatal_rejection_complexity_index"] += weight
        if domain == "ELECTRONIC_SUPERVISION":
            indices["electronic_supervision_index"] += weight
    return {key: min(100, value) for key, value in indices.items()}


def _system_auto_judgement(
    *,
    tailored_bid_index: int,
    tailored_bid_risk_level: str,
    system_risk_indices: Mapping[str, int],
    system_risk_levels: Mapping[str, str],
    hits: list[Mapping[str, Any]],
    evidence_state: str,
) -> dict[str, Any]:
    triggered = [
        {
            "index_name": name,
            "index_value": value,
            "risk_level": system_risk_levels.get(name.replace("_index", "_risk_level"), _risk_level(value)),
        }
        for name, value in sorted(system_risk_indices.items())
        if value >= SYSTEM_INDEX_REVIEW_THRESHOLD
    ]
    if tailored_bid_index >= SYSTEM_INDEX_REVIEW_THRESHOLD:
        triggered.insert(
            0,
            {
                "index_name": "tailored_bid_index",
                "index_value": tailored_bid_index,
                "risk_level": tailored_bid_risk_level,
            },
        )
    judgement_state = "NO_SIGNAL"
    if evidence_state == "INSUFFICIENT_EVIDENCE":
        judgement_state = "INSUFFICIENT_EVIDENCE"
    elif triggered:
        judgement_state = "RISK_CLUE_DETECTED"
    elif hits:
        judgement_state = "WEAK_SIGNAL_ONLY"
    primary_terms: list[str] = []
    if tailored_bid_index >= SYSTEM_INDEX_REVIEW_THRESHOLD:
        primary_terms.append("控标风险线索")
    if system_risk_indices.get("bid_rigging_index", 0) >= SYSTEM_INDEX_REVIEW_THRESHOLD:
        primary_terms.append("围标线索")
        primary_terms.append("串标线索")
    if system_risk_indices.get("cover_bid_index", 0) >= SYSTEM_INDEX_REVIEW_THRESHOLD:
        primary_terms.append("陪标线索")
    if system_risk_indices.get("electronic_supervision_index", 0) >= SYSTEM_INDEX_REVIEW_THRESHOLD:
        primary_terms.append("电子监管线索")
    reasons = [
        f"{item['index_name']}={item['index_value']}"
        for item in triggered
    ]
    if evidence_state == "INSUFFICIENT_EVIDENCE":
        reasons.append("证据不足，不能输出结论")
    return {
        "judgement_state": judgement_state,
        "triggered_indices": triggered,
        "primary_allowed_terms": _dedupe_strings(primary_terms),
        "system_review_reasons": _dedupe_strings(reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "no_illegality_or_reserved_winner_conclusion": True,
    }


def _document_section_slices(text: str) -> list[dict[str, Any]]:
    raw_text = str(text or "")
    if not raw_text.strip():
        return []
    headings: list[dict[str, Any]] = []
    for start, end, line in _line_spans(raw_text):
        section_type, marker_hits = _line_section_match(line)
        if not section_type:
            continue
        headings.append(
            {
                "section_type": section_type,
                "title": line.strip()[:120],
                "marker_hits": marker_hits,
                "start": start,
                "heading_end": end,
            }
        )
    if headings:
        slices: list[dict[str, Any]] = []
        for index, heading in enumerate(headings):
            start = int(heading["start"])
            end = int(headings[index + 1]["start"]) if index + 1 < len(headings) else len(raw_text)
            slices.append(
                _section_slice_payload(
                    raw_text=raw_text,
                    section_type=str(heading["section_type"]),
                    title=str(heading.get("title") or ""),
                    marker_hits=heading.get("marker_hits") or [],
                    start=start,
                    end=end,
                    sequence=index + 1,
                    slice_strategy="heading_range",
                )
            )
        return slices

    fallback_slices: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    for section_type in DOCUMENT_SECTION_OUTPUT_ORDER:
        markers = SECTION_MARKERS.get(section_type) or ()
        found_positions = [
            raw_text.find(marker)
            for marker in markers
            if marker and raw_text.find(marker) >= 0
        ]
        if not found_positions or section_type in seen_sections:
            continue
        found_at = min(found_positions)
        start = max(0, found_at - 120)
        end = min(len(raw_text), found_at + 1000)
        marker_hits = [marker for marker in markers if marker and marker in raw_text[start:end]]
        seen_sections.add(section_type)
        fallback_slices.append(
            _section_slice_payload(
                raw_text=raw_text,
                section_type=section_type,
                title=section_type,
                marker_hits=marker_hits,
                start=start,
                end=end,
                sequence=len(fallback_slices) + 1,
                slice_strategy="marker_window",
            )
        )
    return fallback_slices


def _document_section_profile(text: str, *, slices: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    section_slices = list(slices if slices is not None else _document_section_slices(text))
    normalized = _normalize(text)
    detected: list[str] = []
    marker_hits: dict[str, list[str]] = {}
    for section, markers in SECTION_MARKERS.items():
        hits = [marker for marker in markers if _normalize(marker) in normalized]
        if hits:
            detected.append(section)
            marker_hits[section] = hits
    return {
        "profile_state": "SECTION_SLICED" if section_slices else ("SECTION_MARKERS_DETECTED" if detected else "SECTION_UNRESOLVED"),
        "detected_sections": _dedupe_strings(detected),
        "section_marker_hits": marker_hits,
        "section_slice_count": len(section_slices),
        "section_slice_types": _dedupe_strings(item.get("section_type") for item in section_slices),
        "section_weighting_enabled": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


def _section_match_state(
    *,
    signal_sections: Any,
    detected_sections: set[str],
    section_evidence: Mapping[str, Any] | None = None,
) -> str:
    evidence = section_evidence or {}
    matched_sections = set(_dedupe_strings(evidence.get("matched_sections")))
    expected_sections = set(_dedupe_strings(evidence.get("expected_sections")))
    if matched_sections and expected_sections.intersection(matched_sections):
        return "EXPECTED_SECTION_MATCH"
    if matched_sections and set(_dedupe_strings(evidence.get("guardrail_sections"))) == matched_sections:
        return "SECTION_GUARDRAIL_BLOCKED"
    sections = _canonical_sections(signal_sections)
    if not detected_sections:
        return "SECTION_UNRESOLVED"
    if sections.intersection(detected_sections):
        return "EXPECTED_SECTION_MATCH"
    return "SECTION_MISMATCH_REVIEW"


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    start = 0
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        spans.append((start, end, line))
        start = end
    if not spans:
        spans.append((0, len(text), text))
    return spans


def _line_section_match(line: str) -> tuple[str | None, list[str]]:
    stripped = line.strip()
    if not stripped:
        return None, []
    normalized = _normalize(stripped)
    for section_type in DOCUMENT_SECTION_OUTPUT_ORDER:
        marker_hits = [
            marker
            for marker in SECTION_MARKERS.get(section_type, ())
            if _normalize(marker) in normalized
        ]
        if not marker_hits:
            continue
        if any(_looks_like_section_heading(stripped, marker) for marker in marker_hits):
            return section_type, _dedupe_strings(marker_hits)
    return None, []


def _looks_like_section_heading(line: str, marker: str) -> bool:
    stripped = line.strip()
    if not stripped or marker not in stripped:
        return False
    if stripped == marker or stripped.endswith(marker):
        return len(stripped) <= 40
    marker_at = stripped.find(marker)
    prefix = stripped[:marker_at].strip()
    suffix = stripped[marker_at + len(marker):].strip()
    prefix_ok = not prefix or (
        len(prefix) <= 12
        and all(ch in "第章节款项一二三四五六七八九十0123456789、.．（）() " for ch in prefix)
    )
    suffix_ok = (
        not suffix
        or suffix.startswith((":", "：", "（", "(", "及要求", "一览表", "表"))
        or suffix in {"要求", "条款", "标准", "办法"}
    )
    return prefix_ok and suffix_ok


def _section_slice_payload(
    *,
    raw_text: str,
    section_type: str,
    title: str,
    marker_hits: Any,
    start: int,
    end: int,
    sequence: int,
    slice_strategy: str,
) -> dict[str, Any]:
    bounded_start = max(0, min(start, len(raw_text)))
    bounded_end = max(bounded_start, min(end, len(raw_text)))
    section_text = raw_text[bounded_start:bounded_end].strip()
    return {
        "section_type": section_type,
        "title_optional": title,
        "marker_hits": _dedupe_strings(marker_hits),
        "start_char": bounded_start,
        "end_char": bounded_end,
        "sequence": sequence,
        "slice_strategy": slice_strategy,
        "text_probe": _clip_text(section_text, limit=1200),
        "text_sha256": hashlib.sha256(section_text.encode("utf-8")).hexdigest() if section_text else "",
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


def _signal_section_evidence(
    *,
    markers: list[str],
    signal_sections: Any,
    document_section_slices: list[Mapping[str, Any]],
) -> dict[str, list[str]]:
    expected_sections = _canonical_sections(signal_sections)
    matched_sections: list[str] = []
    guardrail_sections: list[str] = []
    for section_slice in document_section_slices:
        section_type = str(section_slice.get("section_type") or "")
        probe = str(section_slice.get("text_probe") or "")
        normalized_probe = _normalize(probe)
        if not section_type or not normalized_probe:
            continue
        if any(_normalize(marker) in normalized_probe for marker in markers):
            matched_sections.append(section_type)
            if section_type in SECTION_FORMAL_INDEX_GUARDRAILS:
                guardrail_sections.append(section_type)
    return {
        "expected_sections": _dedupe_strings(expected_sections),
        "matched_sections": _dedupe_strings(matched_sections),
        "guardrail_sections": _dedupe_strings(guardrail_sections),
    }


def _section_gate_discount_reasons(
    *,
    signal: Mapping[str, Any],
    section_evidence: Mapping[str, Any],
) -> list[str]:
    matched_sections = set(_dedupe_strings(section_evidence.get("matched_sections")))
    if not matched_sections:
        return []
    guardrail_sections = set(_dedupe_strings(section_evidence.get("guardrail_sections")))
    if not guardrail_sections or not matched_sections.issubset(guardrail_sections):
        return []
    domain = str(signal.get("signal_domain") or "")
    if domain not in {"TAILORED_COMPETITION", "FATAL_REJECTION", "DOCUMENT_QUALITY"}:
        return []
    return [f"section_guardrail={section}" for section in sorted(guardrail_sections)]


def _canonical_sections(values: Any) -> set[str]:
    result: set[str] = set()
    for value in _dedupe_strings(values):
        result.add(SECTION_CANONICAL_ALIASES.get(value, value))
    return result


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


def _document_context_discount_reasons(inputs: Mapping[str, Any], normalized_text: str) -> list[str]:
    reasons: list[str] = []
    document_kind = str(inputs.get("document_kind") or inputs.get("evaluation_document_kind") or "").strip()
    if document_kind in POST_AWARD_OR_AUXILIARY_DOCUMENT_KINDS:
        reasons.append(f"auxiliary_document_kind={document_kind}")
    elif _has_primary_tender_context(normalized_text):
        return reasons
    for marker in NON_PRIMARY_TEXT_MARKERS:
        if _normalize(marker) in normalized_text:
            reasons.append(f"non_primary_text_marker={marker}")
    return _dedupe_strings(reasons)


def _has_primary_tender_context(normalized_text: str) -> bool:
    return any(_normalize(marker) in normalized_text for marker in PRIMARY_TENDER_CONTEXT_MARKERS)


def _evidence_gate_discount_reasons(
    *,
    signal: Mapping[str, Any],
    observable_mismatch: bool,
    evidence_state: str,
    evidence_reasons: list[str],
    document_context_reasons: list[str],
    section_gate_discount_reasons: list[str],
) -> list[str]:
    if str(signal.get("signal_domain") or "") not in TAILORED_INDEX_DOMAINS:
        return []
    reasons: list[str] = []
    if observable_mismatch:
        reasons.append("observable_mismatch")
    if evidence_state in {"PARTIAL_EVIDENCE_REVIEW", "INSUFFICIENT_EVIDENCE"}:
        reasons.extend(evidence_reasons)
    reasons.extend(document_context_reasons)
    reasons.extend(section_gate_discount_reasons)
    return _dedupe_strings(reasons)


def _system_index_discount_reasons(
    *,
    signal: Mapping[str, Any],
    observable_mismatch: bool,
    evidence_state: str,
    evidence_reasons: list[str],
    document_context_reasons: list[str],
    section_gate_discount_reasons: list[str],
) -> list[str]:
    domain = str(signal.get("signal_domain") or "")
    reasons: list[str] = []
    if observable_mismatch:
        reasons.append("observable_mismatch")
    if evidence_state in {"PARTIAL_EVIDENCE_REVIEW", "INSUFFICIENT_EVIDENCE"}:
        reasons.extend(evidence_reasons)
    if domain in {"TAILORED_COMPETITION", "FATAL_REJECTION", "DOCUMENT_QUALITY"}:
        reasons.extend(document_context_reasons)
        reasons.extend(section_gate_discount_reasons)
    return _dedupe_strings(reasons)


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


def _clip_text(value: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[TRUNCATED]"


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
