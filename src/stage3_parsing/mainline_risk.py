from __future__ import annotations

import re
from typing import Any, Mapping


_TEXT_KEYS = (
    "source_text",
    "detail_text",
    "document_text",
    "parsed_text",
    "attachment_text",
    "source_title",
    "project_name",
)

_METHOD_MARKERS = (
    ("bid_separation", ("评定分离", "定标候选")),
    ("reasonable_low_price", ("合理低价",)),
    ("reviewed_lowest_price", ("经评审最低投标价", "最低投标价法", "最低价评标")),
    ("technical_pass", ("技术标通过制", "技术标合格制")),
    ("technical_scored", ("技术标评分", "技术评分")),
    ("comprehensive", ("综合评分", "综合评估")),
)

_SCORE_TOKENS = {
    "price_score": ("价格分", "报价分", "价格部分", "报价部分", "投标报价"),
    "technical_score": ("技术分", "技术评分", "技术部分", "技术标", "技术方案", "施工组织设计"),
    "commercial_score": ("商务分", "商务评分", "商务部分", "商务标"),
    "subjective_score": ("主观分", "主观评分"),
    "objective_score": ("客观分", "客观评分"),
}

_TAILORED_SIGNAL_DEFS = (
    ("manufacturer_authorization", ("厂家授权", "制造商授权", "原厂授权", "生产厂家授权")),
    ("iso_certificate", ("ISO", "三体系", "质量管理体系", "环境管理体系", "职业健康安全管理体系")),
    ("cma_certificate", ("CMA", "检验检测机构资质认定")),
    ("mandatory_site_visit", ("现场踏勘", "踏勘证明", "踏勘回执", "踏勘确认函")),
    ("local_service", ("本地服务", "本地售后", "本市服务网点", "本地服务网点", "驻场服务")),
    ("local_performance", ("本地业绩", "本地区业绩", "本市业绩", "本省业绩")),
    ("specific_certificate", ("特定证书", "协会证书", "安全生产标准化证书")),
    ("over_specific_parameter", ("唯一参数", "指定参数", "不可偏离参数", "完全满足技术参数")),
)

_FATAL_SIGNAL_DEFS = (
    (
        "signature_seal_format",
        ("签字", "签章", "盖章", "法定代表人", "授权代表"),
        "FORMAL_DEFECT_REVIEW",
    ),
    ("bid_bond", ("投标保证金", "保证金"), "ONE_VOTE_REJECTION_CANDIDATE"),
    ("bid_validity", ("投标有效期",), "ONE_VOTE_REJECTION_CANDIDATE"),
    (
        "qualification_responsiveness",
        ("资格审查", "符合性审查", "实质性响应", "星号条款", "★", "不得偏离", "无效响应"),
        "ONE_VOTE_REJECTION_CANDIDATE",
    ),
    ("second_round_quotation", ("二次报价", "最后报价", "最终报价"), "ONE_VOTE_REJECTION_CANDIDATE"),
    ("mandatory_format", ("响应文件格式", "不得更改格式", "按格式填写", "格式文件"), "FORMAL_DEFECT_REVIEW"),
    ("clarification_or_deduction", ("澄清", "补正", "扣分"), "CLARIFICATION_OR_DEDUCTION"),
)

_UNBALANCED_BID_SIGNAL_DEFS = (
    ("unbalanced_pricing", ("不平衡报价", "不平衡报价法")),
    ("quantity_change_settlement", ("工程量变化", "清单偏差", "结算审计", "审计调整", "扣减")),
    ("high_low_bill_items", ("高价清单项", "低价清单项", "清单项报价")),
)

_PAYMENT_RISK_SIGNAL_DEFS = (
    ("third_party_payment_condition", ("第三方付款", "背靠背付款", "收到第三方款项后支付")),
    ("audit_as_payment_condition", ("审计后支付", "审计结果作为结算依据", "结算审计后支付")),
    ("long_payment_cycle", ("付款周期", "回款周期", "分期付款", "财政资金到位后支付")),
)


def build_mainline_risk_profile(inputs: Mapping[str, Any]) -> dict[str, Any]:
    text = _profile_text(inputs)
    evaluation_method_profile = _evaluation_method_profile(text)
    qualification_clause_hits = _qualification_clause_hits(text)
    fatal_rejection_risk_hits = _fatal_rejection_hits(text)
    price_performance_risk_profile = _price_performance_risk_profile(
        inputs,
        text=text,
        evaluation_method_profile=evaluation_method_profile,
    )
    tailored_bid_risk_level = _tailored_risk_level(qualification_clause_hits)
    bid_selection_score = _bid_selection_score(
        inputs,
        tailored_bid_risk_level=tailored_bid_risk_level,
        fatal_hit_count=len(fatal_rejection_risk_hits),
    )
    bid_selection_state = _bid_selection_state(inputs, bid_selection_score)
    blind_bid_pipeline_stage = _blind_bid_pipeline_stage(inputs, evaluation_method_profile)
    self_score_forecast = (
        "READY_FOR_INTERNAL_SCORING"
        if inputs.get("own_material_profile") or inputs.get("bidder_material_profile")
        else "NOT_RUN_MISSING_INTERNAL_MATERIALS"
    )
    review_reasons = _review_reasons(
        text=text,
        evaluation_method_profile=evaluation_method_profile,
        qualification_clause_hits=qualification_clause_hits,
        fatal_rejection_risk_hits=fatal_rejection_risk_hits,
        self_score_forecast=self_score_forecast,
        price_performance_risk_profile=price_performance_risk_profile,
    )
    return {
        "profile_state": "PROFILED_REVIEW_READY" if text else "PROFILE_REVIEW_REQUIRED",
        "bid_selection_score": bid_selection_score,
        "bid_selection_state": bid_selection_state,
        "blind_bid_pipeline_stage": blind_bid_pipeline_stage,
        "evaluation_method_profile": evaluation_method_profile,
        "tailored_bid_risk_level": tailored_bid_risk_level,
        "qualification_clause_hits": qualification_clause_hits,
        "fatal_rejection_risk_hits": fatal_rejection_risk_hits,
        "price_performance_risk_profile": price_performance_risk_profile,
        "payment_risk_level": price_performance_risk_profile["payment_risk_level"],
        "abnormally_low_bid_explanation_required": price_performance_risk_profile[
            "abnormally_low_bid_explanation_required"
        ],
        "abnormal_low_price_trigger": price_performance_risk_profile["abnormal_low_price_trigger"],
        "unbalanced_bid_risk_hits": price_performance_risk_profile["unbalanced_bid_risk_hits"],
        "cost_breakdown_ready": price_performance_risk_profile["cost_breakdown_ready"],
        "low_price_review_record": price_performance_risk_profile["low_price_review_record"],
        "self_score_forecast": self_score_forecast,
        "self_score_reasons": (
            []
            if self_score_forecast == "READY_FOR_INTERNAL_SCORING"
            else ["own_bidder_material_profile_missing"]
        ),
        "review_required": True,
        "review_reasons": review_reasons,
        "customer_visible": False,
        "no_illegality_or_reserved_winner_conclusion": True,
    }


def _profile_text(inputs: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _TEXT_KEYS:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(dict.fromkeys(parts))


def _evaluation_method_profile(text: str) -> dict[str, Any]:
    normalized = _normalize(text)
    family = "unknown"
    markers: list[str] = []
    for candidate_family, tokens in _METHOD_MARKERS:
        hits = [token for token in tokens if token in normalized]
        if hits:
            family = candidate_family
            markers = hits
            break
    score_split = {
        score_key: _score_value(normalized, tokens)
        for score_key, tokens in _SCORE_TOKENS.items()
    }
    parsed_score_keys = [key for key, value in score_split.items() if value is not None]
    review_reasons = ["evaluation_method_profile_review_required"]
    if family == "unknown":
        review_reasons.append("evaluation_method_family_unresolved")
    if not parsed_score_keys:
        review_reasons.append("score_split_unresolved")
    return {
        "evaluation_method_family": family,
        "raw_method_markers": markers,
        "score_split": score_split,
        "score_parse_state": "PARSED" if parsed_score_keys else "REVIEW_REQUIRED",
        "parsed_score_keys": parsed_score_keys,
        "has_subjective_score": bool(score_split.get("subjective_score") or score_split.get("technical_score")),
        "has_objective_score": bool(score_split.get("objective_score") or score_split.get("price_score")),
        "review_required": True,
        "review_reasons": list(dict.fromkeys(review_reasons)),
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


def _qualification_clause_hits(text: str) -> list[dict[str, Any]]:
    normalized = _normalize(text)
    hits: list[dict[str, Any]] = []
    for signal_type, tokens in _TAILORED_SIGNAL_DEFS:
        markers = [token for token in tokens if token in normalized]
        if not markers:
            continue
        hits.append(
            {
                "signal_type": signal_type,
                "markers": markers,
                "match_basis": "deterministic_public_text_marker",
                "risk_role": "tailored_or_restrictive_competition_clue",
                "review_required": True,
                "legal_conclusion_allowed": False,
            }
        )
    return hits


def _fatal_rejection_hits(text: str) -> list[dict[str, Any]]:
    normalized = _normalize(text)
    hits: list[dict[str, Any]] = []
    for risk_type, tokens, category in _FATAL_SIGNAL_DEFS:
        markers = [token for token in tokens if token in normalized]
        if not markers:
            continue
        hits.append(
            {
                "risk_type": risk_type,
                "category": category,
                "markers": markers,
                "match_basis": "deterministic_public_text_marker",
                "review_required": True,
                "no_rejection_conclusion": True,
            }
        )
    return hits


def _price_performance_risk_profile(
    inputs: Mapping[str, Any],
    *,
    text: str,
    evaluation_method_profile: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _normalize(text)
    legal_context = _price_legal_context(inputs, normalized)
    government_triggers = _government_procurement_low_price_triggers(normalized)
    engineering_triggers = _engineering_low_price_triggers(normalized, evaluation_method_profile)
    unbalanced_hits = _unbalanced_bid_hits(normalized)
    payment_hits = _payment_risk_hits(normalized)
    payment_risk_level = _payment_risk_level(payment_hits)
    cost_breakdown_ready = (
        "READY_WITH_INTERNAL_COST_INPUTS"
        if inputs.get("cost_breakdown_profile")
        or inputs.get("cost_evidence_package")
        or inputs.get("internal_cost_profile")
        else "NOT_RUN_MISSING_INTERNAL_COSTS"
    )

    abnormal_triggers: list[str] = []
    if legal_context == "GOVERNMENT_PROCUREMENT":
        abnormal_triggers.extend(government_triggers)
    elif legal_context == "ENGINEERING_TENDER":
        abnormal_triggers.extend(engineering_triggers)
    else:
        abnormal_triggers.extend(f"UNROUTED_{trigger}" for trigger in government_triggers)
        abnormal_triggers.extend(engineering_triggers)

    if government_triggers and legal_context == "GOVERNMENT_PROCUREMENT":
        explanation_required = "GOVERNMENT_PROCUREMENT_WRITTEN_EXPLANATION_REVIEW"
        review_record = "LOW_PRICE_REVIEW_RECORD_REQUIRED"
    elif government_triggers and legal_context != "GOVERNMENT_PROCUREMENT":
        explanation_required = "REVIEW_LEGAL_SYSTEM_BEFORE_APPLYING_GOV_PROCUREMENT_PROCEDURE"
        review_record = "LOW_PRICE_REVIEW_RECORD_LEGAL_SYSTEM_REVIEW"
    elif engineering_triggers:
        explanation_required = "ENGINEERING_LOW_PRICE_REVIEW_ONLY"
        review_record = "ENGINEERING_PRICE_REVIEW_RECORD_RECOMMENDED"
    else:
        explanation_required = "NO_PUBLIC_TRIGGER"
        review_record = "NOT_PRESENT"

    review_reasons = ["price_performance_internal_review_required"]
    if not text:
        review_reasons.append("profile_text_unavailable")
    if government_triggers and legal_context != "GOVERNMENT_PROCUREMENT":
        review_reasons.append("do_not_apply_government_procurement_low_price_procedure_without_legal_context")
    if abnormal_triggers:
        review_reasons.append("abnormal_low_price_public_markers_detected")
    if unbalanced_hits:
        review_reasons.append("unbalanced_bid_or_settlement_markers_detected")
    if payment_hits:
        review_reasons.append("payment_or_audit_condition_markers_detected")
    if cost_breakdown_ready == "NOT_RUN_MISSING_INTERNAL_COSTS":
        review_reasons.append("internal_cost_breakdown_missing")

    return {
        "profile_state": "PROFILED_REVIEW_READY" if text else "PROFILE_REVIEW_REQUIRED",
        "legal_context": legal_context,
        "payment_risk_level": payment_risk_level,
        "payment_risk_hits": payment_hits,
        "abnormally_low_bid_explanation_required": explanation_required,
        "abnormal_low_price_trigger": list(dict.fromkeys(abnormal_triggers)),
        "government_procurement_low_price_triggers": government_triggers,
        "engineering_low_price_triggers": engineering_triggers,
        "unbalanced_bid_risk_hits": unbalanced_hits,
        "cost_breakdown_ready": cost_breakdown_ready,
        "low_price_evidence_package": _low_price_evidence_package_state(cost_breakdown_ready, abnormal_triggers),
        "low_price_review_record": review_record,
        "review_required": True,
        "review_reasons": list(dict.fromkeys(review_reasons)),
        "customer_visible": False,
        "no_low_price_invalidity_conclusion": True,
        "no_payment_breach_conclusion": True,
        "no_legal_conclusion": True,
    }


def _tailored_risk_level(hits: list[Mapping[str, Any]]) -> str:
    count = len(hits)
    if count >= 4:
        return "HIGH_CLUE_REVIEW"
    if count >= 2:
        return "MEDIUM_CLUE_REVIEW"
    if count == 1:
        return "LOW_CLUE_REVIEW"
    return "NO_PUBLIC_MARKER"


def _bid_selection_score(
    inputs: Mapping[str, Any],
    *,
    tailored_bid_risk_level: str,
    fatal_hit_count: int,
) -> int:
    score = 45
    source_quality = _int_or_none(inputs.get("source_quality_score"))
    if source_quality is not None:
        if source_quality >= 80:
            score += 15
        elif source_quality >= 60:
            score += 8
        else:
            score -= 5
    document_state = str(inputs.get("document_completeness_state") or "")
    if document_state == "COMPLETE_WITH_ATTACHMENTS":
        score += 15
    elif document_state == "DETAIL_ONLY_NO_ATTACHMENTS":
        score += 4
    elif "REVIEW" in document_state or "FAILED" in document_state:
        score -= 10
    project_manager_state = str(inputs.get("project_manager_field_source_state") or "")
    if project_manager_state == "FIELD_EXTRACTED":
        score += 10
    elif project_manager_state:
        score -= 5
    legal_type = str(inputs.get("legal_system_type_candidate") or "")
    if legal_type in {"REVIEW_REQUIRED", "UNKNOWN", ""}:
        score -= 8
    if tailored_bid_risk_level.startswith("HIGH"):
        score -= 15
    elif tailored_bid_risk_level.startswith("MEDIUM"):
        score -= 8
    if fatal_hit_count:
        score -= min(20, fatal_hit_count * 4)
    if str(inputs.get("project_lifecycle_stage") or "") == "PRE_NOTICE_WATCHLIST":
        score = min(score, 60)
    return max(0, min(100, score))


def _bid_selection_state(inputs: Mapping[str, Any], score: int) -> str:
    if str(inputs.get("project_lifecycle_stage") or "") == "PRE_NOTICE_WATCHLIST":
        return "WATCHLIST_ONLY"
    if score >= 70:
        return "READY_FOR_INTERNAL_BID_DECISION"
    if score >= 45:
        return "REVIEW_BEFORE_BID"
    return "LOW_PRIORITY_REVIEW"


def _blind_bid_pipeline_stage(
    inputs: Mapping[str, Any],
    evaluation_method_profile: Mapping[str, Any],
) -> str:
    if str(inputs.get("project_lifecycle_stage") or "") == "PRE_NOTICE_WATCHLIST":
        return "PRE_NOTICE_WATCHLIST"
    document_state = str(inputs.get("document_completeness_state") or "")
    if "REVIEW" in document_state or "FAILED" in document_state:
        return "DOCUMENT_REVIEW_REQUIRED"
    if evaluation_method_profile.get("evaluation_method_family") != "unknown":
        return "SCORING_REVIEW_READY"
    return "FORMAL_NOTICE_REVIEW"


def _review_reasons(
    *,
    text: str,
    evaluation_method_profile: Mapping[str, Any],
    qualification_clause_hits: list[Mapping[str, Any]],
    fatal_rejection_risk_hits: list[Mapping[str, Any]],
    self_score_forecast: str,
    price_performance_risk_profile: Mapping[str, Any],
) -> list[str]:
    reasons = ["mainline_risk_profile_internal_review_required"]
    if not text:
        reasons.append("profile_text_unavailable")
    reasons.extend(str(reason) for reason in evaluation_method_profile.get("review_reasons", []))
    if qualification_clause_hits:
        reasons.append("tailored_or_restrictive_clause_markers_detected")
    if fatal_rejection_risk_hits:
        reasons.append("fatal_rejection_redline_markers_detected")
    if self_score_forecast == "NOT_RUN_MISSING_INTERNAL_MATERIALS":
        reasons.append("self_score_requires_internal_material_profile")
    for reason in price_performance_risk_profile.get("review_reasons", []):
        reasons.append(str(reason))
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _price_legal_context(inputs: Mapping[str, Any], text: str) -> str:
    legal_text = " ".join(
        str(inputs.get(key) or "")
        for key in (
            "legal_system_type_candidate",
            "procurement_regime",
            "procurement_category",
            "source_channel_type",
        )
    )
    combined = _normalize(f"{legal_text} {text}")
    if any(token in combined for token in ("政府采购", "供应商", "财库")):
        return "GOVERNMENT_PROCUREMENT"
    if any(token in combined for token in ("工程建设", "施工招标", "招标投标", "工程量清单")):
        return "ENGINEERING_TENDER"
    return "UNKNOWN_REVIEW_REQUIRED"


def _government_procurement_low_price_triggers(text: str) -> list[str]:
    triggers: list[str] = []
    if _has_percent_trigger(text, "平均报价", "50"):
        triggers.append("BELOW_AVERAGE_ACCEPTED_PRICE_50_PERCENT")
    if _has_percent_trigger(text, "次低报价", "50"):
        triggers.append("BELOW_SECOND_LOWEST_PRICE_50_PERCENT")
    if _has_percent_trigger(text, "最高限价", "45"):
        triggers.append("BELOW_CEILING_PRICE_45_PERCENT")
    if "评委" in text and ("专业判断" in text or "明显过低" in text or "报价过低" in text):
        triggers.append("EVALUATION_COMMITTEE_PROFESSIONAL_LOW_PRICE_JUDGMENT")
    if "30分钟" in text and ("成本说明" in text or "书面说明" in text or "证明材料" in text):
        triggers.append("MINIMUM_30_MINUTE_COST_EXPLANATION_WINDOW")
    return list(dict.fromkeys(triggers))


def _engineering_low_price_triggers(
    text: str,
    evaluation_method_profile: Mapping[str, Any],
) -> list[str]:
    triggers: list[str] = []
    method_family = str(evaluation_method_profile.get("evaluation_method_family") or "")
    if method_family == "reasonable_low_price" or "合理低价" in text:
        triggers.append("ENGINEERING_REASONABLE_LOW_PRICE_METHOD")
    if "低于成本" in text or "低于成本价" in text:
        triggers.append("ENGINEERING_BELOW_COST_REVIEW")
    if "经评审最低投标价" in text or "最低投标价法" in text or "最低价评标" in text:
        triggers.append("ENGINEERING_REVIEWED_LOWEST_PRICE_METHOD")
    return list(dict.fromkeys(triggers))


def _unbalanced_bid_hits(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for signal_type, tokens in _UNBALANCED_BID_SIGNAL_DEFS:
        markers = [token for token in tokens if token in text]
        if not markers:
            continue
        hits.append(
            {
                "signal_type": signal_type,
                "markers": markers,
                "match_basis": "deterministic_public_text_marker",
                "risk_role": "settlement_or_audit_review_clue",
                "review_required": True,
                "no_settlement_conclusion": True,
            }
        )
    return hits


def _payment_risk_hits(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for signal_type, tokens in _PAYMENT_RISK_SIGNAL_DEFS:
        markers = [token for token in tokens if token in text]
        if not markers:
            continue
        hits.append(
            {
                "signal_type": signal_type,
                "markers": markers,
                "match_basis": "deterministic_public_text_marker",
                "risk_role": "payment_or_performance_review_clue",
                "review_required": True,
                "no_payment_breach_conclusion": True,
            }
        )
    return hits


def _payment_risk_level(payment_hits: list[Mapping[str, Any]]) -> str:
    signal_types = {str(hit.get("signal_type") or "") for hit in payment_hits}
    if signal_types.intersection({"third_party_payment_condition", "audit_as_payment_condition"}):
        return "HIGH_REVIEW"
    if payment_hits:
        return "MEDIUM_REVIEW"
    return "NO_PUBLIC_MARKER"


def _low_price_evidence_package_state(cost_breakdown_ready: str, triggers: list[str]) -> str:
    if not triggers:
        return "NOT_TRIGGERED"
    if cost_breakdown_ready == "READY_WITH_INTERNAL_COST_INPUTS":
        return "READY_FOR_REVIEW"
    return "REQUIRED_BUT_MISSING_INTERNAL_COSTS"


def _has_percent_trigger(text: str, basis_token: str, percent: str) -> bool:
    if basis_token not in text:
        return False
    pattern = rf"{re.escape(basis_token)}.{{0,30}}{re.escape(percent)}\s*[％%]|{re.escape(percent)}\s*[％%].{{0,30}}{re.escape(basis_token)}"
    return bool(re.search(pattern, text))


def _score_value(text: str, tokens: tuple[str, ...]) -> float | None:
    for token in tokens:
        pattern = rf"{re.escape(token)}[^\d]{{0,12}}(?P<value>\d{{1,3}}(?:\.\d+)?)\s*分"
        match = re.search(pattern, text)
        if match:
            return float(match.group("value"))
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


__all__ = ["build_mainline_risk_profile"]
