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
    "contract_text",
    "acceptance_text",
    "settlement_text",
    "complaint_text",
    "remedy_material_text",
)

_QUALIFICATION_LEGALITY_SIGNAL_DEFS = (
    ("manufacturer_authorization", ("厂家授权", "制造商授权", "原厂授权", "生产厂家授权")),
    ("iso_certificate", ("ISO", "三体系", "质量管理体系", "环境管理体系", "职业健康安全管理体系")),
    ("cma_certificate", ("CMA", "检验检测机构资质认定")),
    ("site_visit_condition", ("现场踏勘", "踏勘证明", "踏勘回执", "踏勘确认函")),
    ("local_experience_or_service", ("本地业绩", "本地区业绩", "本市业绩", "本地服务", "本市服务网点")),
    ("industry_specific_experience", ("特定行业经验", "同类行业业绩", "指定行业业绩")),
    ("non_essential_certificate", ("非必要证书", "协会证书", "安全生产标准化证书", "特定证书")),
    ("substantive_requirement_marker", ("实质性要求", "不可偏离", "星号条款", "★")),
)

_POST_AWARD_CONTRACT_SIGNAL_DEFS = (
    ("abandon_award_or_signing", ("放弃中标", "弃标", "不签合同", "无正当理由放弃")),
    ("second_candidate_successor_review", ("第二名递补", "顺延第二名", "重新招标")),
    ("performance_guarantee_added", ("履约保证金", "履约保函", "签合同时另行缴纳", "临时加码")),
    ("substantive_contract_change", ("合同实质性变更", "变更采购标的", "变更数量", "变更价格", "变更履约期限")),
    ("post_award_authorization_gate", ("原厂授权", "本地经销商授权", "验收授权", "后置授权")),
    ("acceptance_extra_condition", ("拒绝验收", "验收额外条件", "验收付款条件", "交付后新增")),
)

_SETTLEMENT_AUDIT_SIGNAL_DEFS = (
    ("unbalanced_bid", ("不平衡报价", "高价清单项", "低价清单项")),
    ("fixed_unit_price_settlement", ("固定单价", "单价合同", "工程量变化", "清单偏差")),
    ("variation_and_site_instruction", ("签证变更", "现场签证", "变更签证", "工程变更")),
    ("hidden_work_evidence", ("隐蔽工程影像", "隐蔽工程验收", "标准施工段", "过程影像")),
    ("process_documentation_gap", ("后补资料", "过程资料", "验收记录", "材料进场", "会议纪要")),
    ("image_tampering_review", ("P图", "p图", "图片造假", "补拍")),
    ("performance_commitment_closure", ("承诺履约", "履约资料", "结算审计", "审计扣减")),
)

_PAYMENT_SIGNAL_DEFS = (
    ("payment_30_60_day_term", ("30日", "30 日", "60日", "60 日", "最长60", "一般30")),
    ("third_party_payment_condition", ("第三方付款", "背靠背付款", "收到第三方款项后支付", "财政资金到位后支付")),
    ("forced_commercial_bill", ("强制商业汇票", "商业汇票", "承兑汇票", "非现金方式")),
    ("audit_as_settlement_basis", ("审计结果作为结算依据", "以审计结果为准", "审计后支付", "审计作为付款条件")),
    ("cash_only_guarantee", ("现金保证金", "只接受现金", "不得使用保函", "限定现金")),
    ("arrears_remedy_signal", ("拖欠款", "逾期付款", "投诉受理", "欠款投诉", "清欠")),
)

_WHISTLEBLOWER_SIGNAL_DEFS = (
    ("bid_rigging_or_collusion", ("围标", "串标", "串通投标", "陪标")),
    ("bid_broker_or_trading", ("买标", "卖标", "黄牛", "掮客")),
    ("rotating_award", ("轮流中标", "轮流成交")),
    ("fixed_supplier_pattern", ("长期固定供应商", "固定供应商", "连续中标")),
    ("tailored_parameter", ("参数定制", "量身定制", "唯一参数", "指定参数")),
    ("agent_abnormality", ("代理异常", "招标代理违规", "代理机构违规")),
    ("special_rectification", ("专项整治", "整治行动", "监督检查")),
    ("rewarded_report_policy", ("有奖举报", "举报奖励", "举报线索", "举报专区")),
)


def build_remedy_performance_settlement_profile(inputs: Mapping[str, Any]) -> dict[str, Any]:
    text = _profile_text(inputs)
    has_text = bool(text)

    remedy_context = _remedy_context(inputs, text)
    remedy_window_state = _remedy_window_state(remedy_context, text)
    challenge_evidence_chain_state = _challenge_evidence_chain_state(text)
    qualification_legality_risk_hits = _signal_hits(
        text,
        _QUALIFICATION_LEGALITY_SIGNAL_DEFS,
        "qualification_legality_review_clue",
    )
    post_award_contract_risk_hits = _signal_hits(
        text,
        _POST_AWARD_CONTRACT_SIGNAL_DEFS,
        "post_award_contract_or_procedure_review_clue",
    )
    settlement_audit_risk_hits = _signal_hits(
        text,
        _SETTLEMENT_AUDIT_SIGNAL_DEFS,
        "settlement_audit_review_clue",
    )
    payment_term_violation = _signal_hits(
        text,
        _PAYMENT_SIGNAL_DEFS,
        "payment_term_or_guarantee_review_clue",
    )
    whistleblower_reward_policy_signal = _signal_hits(
        text,
        _WHISTLEBLOWER_SIGNAL_DEFS,
        "special_rectification_or_report_supervision_clue",
    )

    hit_count = sum(
        len(items)
        for items in (
            qualification_legality_risk_hits,
            post_award_contract_risk_hits,
            settlement_audit_risk_hits,
            payment_term_violation,
            whistleblower_reward_policy_signal,
        )
    )

    review_reasons = ["remedy_performance_settlement_profile_internal_only"]
    if not has_text:
        review_reasons.append("public_text_missing")
    if remedy_window_state != "NO_PUBLIC_MARKER":
        review_reasons.append(f"remedy_window_state={remedy_window_state}")
    if challenge_evidence_chain_state != "NO_PUBLIC_MARKER":
        review_reasons.append(f"challenge_evidence_chain_state={challenge_evidence_chain_state}")
    if qualification_legality_risk_hits:
        review_reasons.append("qualification_legality_markers_detected")
    if post_award_contract_risk_hits:
        review_reasons.append("post_award_contract_markers_detected")
    if settlement_audit_risk_hits:
        review_reasons.append("settlement_audit_markers_detected")
    if payment_term_violation:
        review_reasons.append("payment_term_or_guarantee_markers_detected")
    if whistleblower_reward_policy_signal:
        review_reasons.append("special_rectification_or_report_markers_detected")

    if not has_text:
        profile_state = "PROFILE_REVIEW_REQUIRED"
    elif (
        hit_count
        or remedy_window_state != "NO_PUBLIC_MARKER"
        or challenge_evidence_chain_state != "NO_PUBLIC_MARKER"
    ):
        profile_state = "PROFILED_REVIEW_READY"
    else:
        profile_state = "PROFILED_NO_PUBLIC_MARKER"

    return {
        "profile_state": profile_state,
        "remedy_legal_context": remedy_context,
        "remedy_window_state": remedy_window_state,
        "challenge_evidence_chain_state": challenge_evidence_chain_state,
        "qualification_legality_risk_hits": qualification_legality_risk_hits,
        "post_award_contract_risk_hits": post_award_contract_risk_hits,
        "settlement_audit_risk_hits": settlement_audit_risk_hits,
        "payment_term_violation": payment_term_violation,
        "whistleblower_reward_policy_signal": whistleblower_reward_policy_signal,
        "review_required": profile_state in {"PROFILE_REVIEW_REQUIRED", "PROFILED_REVIEW_READY"},
        "review_reasons": _dedupe(review_reasons),
        "customer_visible": False,
        "internal_review_only": True,
        "no_legal_conclusion": True,
        "no_payment_breach_conclusion": True,
        "no_illegality_or_reserved_winner_conclusion": True,
    }


def _profile_text(inputs: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _TEXT_KEYS:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return _normalize("\n".join(dict.fromkeys(parts)))


def _remedy_context(inputs: Mapping[str, Any], text: str) -> str:
    explicit = str(
        inputs.get("legal_system_type_candidate")
        or inputs.get("procurement_regime")
        or inputs.get("procurement_category")
        or ""
    )
    combined = _normalize(f"{explicit}\n{text}")
    if any(
        token in text
        for token in (
            "依法必须招标",
            "工程建设",
            "公共资源交易",
            "招标文件异议",
            "投标截止时间10日前",
            "投标截止10日前",
        )
    ):
        return "TENDERING_BIDDING"
    if any(token in combined for token in ("政府采购", "供应商", "财政部门", "采购人", "财库")):
        return "GOVERNMENT_PROCUREMENT"
    if any(token in combined for token in ("招标投标", "依法必须招标", "工程建设", "公共资源交易", "投标人")):
        return "TENDERING_BIDDING"
    return "UNKNOWN_REVIEW_REQUIRED"


def _remedy_window_state(remedy_context: str, text: str) -> str:
    if not text:
        return "REVIEW_REQUIRED"
    gov_markers = (
        "质疑",
        "7个工作日",
        "7 个工作日",
        "15个工作日",
        "15 个工作日",
        "30个工作日",
        "30 个工作日",
        "答复期满",
    )
    tender_markers = (
        "异议",
        "投标截止时间10日前",
        "投标截止10日前",
        "10日前",
        "10日内",
        "3日公示",
        "公示不少于3日",
        "公示期不得少于3日",
        "资格预审文件",
    )
    if remedy_context == "GOVERNMENT_PROCUREMENT" and any(marker in text for marker in gov_markers):
        return "GOVERNMENT_PROCUREMENT_REMEDY_WINDOW_REVIEW"
    if remedy_context == "TENDERING_BIDDING" and any(marker in text for marker in tender_markers):
        return "TENDERING_BIDDING_REMEDY_WINDOW_REVIEW"
    if any(marker in text for marker in gov_markers + tender_markers):
        return "REMEDY_WINDOW_CONTEXT_REVIEW_REQUIRED"
    if "投诉" in text or "质疑" in text or "异议" in text:
        return "REMEDY_WINDOW_DATE_MISSING_REVIEW_REQUIRED"
    return "NO_PUBLIC_MARKER"


def _challenge_evidence_chain_state(text: str) -> str:
    if not text:
        return "REVIEW_REQUIRED"
    formality_markers = ("书面", "书面形式", "盖章", "签字", "联系方式", "明确诉求", "请求事项")
    evidence_markers = ("证据", "事实理由", "证据链", "截图", "录音", "公告", "投标文件")
    precondition_markers = ("前置", "先质疑", "先提出异议", "投诉前", "答复期满", "主体适格")
    has_formality = any(marker in text for marker in formality_markers)
    has_evidence = any(marker in text for marker in evidence_markers)
    has_precondition = any(marker in text for marker in precondition_markers)
    if has_formality and has_evidence and has_precondition:
        return "CHALLENGE_EVIDENCE_CHAIN_REVIEW_READY"
    if has_formality or has_evidence or has_precondition:
        return "CHALLENGE_EVIDENCE_CHAIN_PARTIAL_REVIEW_REQUIRED"
    return "NO_PUBLIC_MARKER"


def _signal_hits(
    text: str,
    defs: tuple[tuple[str, tuple[str, ...]], ...],
    risk_role: str,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not text:
        return hits
    for signal_type, tokens in defs:
        markers = [token for token in tokens if token in text]
        if not markers:
            continue
        hits.append(
            {
                "signal_type": signal_type,
                "markers": markers,
                "match_basis": "deterministic_public_text_marker",
                "risk_role": risk_role,
                "review_required": True,
                "customer_visible": False,
                "no_conclusion": True,
            }
        )
    return hits


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


__all__ = ["build_remedy_performance_settlement_profile"]
