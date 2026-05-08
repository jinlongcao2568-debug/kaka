from __future__ import annotations

import re
from typing import Any, Mapping


_INTERNAL_BID_TEXT_KEYS = (
    "internal_bid_document_text",
    "bid_document_text",
    "bid_file_text",
    "technical_bid_text",
    "commercial_bid_text",
    "response_document_text",
)

_DARK_BID_SIGNAL_DEFS = (
    ("company_identity_marker", ("公司名称", "投标人名称", "单位名称", "有限公司", "集团有限公司")),
    ("logo_or_watermark_marker", ("LOGO", "Logo", "logo", "水印", "页眉", "页脚")),
    ("contact_or_person_marker", ("联系人", "联系电话", "手机", "邮箱", "法定代表人", "项目经理")),
    ("file_metadata_marker", ("文件属性", "作者", "创建者", "修订者", "模板路径")),
    ("special_layout_marker", ("特殊标记", "彩色字体", "特殊符号", "隐藏文字", "异常空格")),
)

_AUTHORIZATION_SIGNATURE_SIGNAL_DEFS = (
    ("pasted_signature", ("抠图签名", "机打签名", "图片签名", "签名图片", "扫描签名")),
    ("name_stamp_signature", ("人名章", "姓名章", "签名章")),
    ("overbroad_authorization", ("全权代理", "全权委托")),
    ("missing_no_subdelegation", ("未写无转委托", "无转委托缺失", "转委托")),
    ("id_card_stamp_review", ("身份证复印件", "身份证正反面", "身份证未盖章")),
)

_DECLARATION_SIGNAL_DEFS = (
    ("sme_declaration", ("中小企业声明函", "小微企业声明函")),
    ("sme_industry_or_unit_review", ("行业分类", "从业人员", "营业收入", "资产总额", "万元", "制造商")),
    ("domestic_product_declaration", ("本国产品声明函", "国产产品声明函", "本国产品")),
    ("import_product_conflict", ("进口产品", "国产声明", "混投")),
    ("false_declaration_review", ("虚假声明", "声明不实", "追责")),
)

_FINANCIAL_TAX_AUDIT_SIGNAL_DEFS = (
    ("tax_rate_review", ("税率", "征收率", "增值税", "专票", "普票")),
    ("audit_report_review", ("审计报告", "资产负债表", "利润表", "现金流量表", "附注")),
    ("audit_verification_review", ("二维码", "验证码", "查询验证", "会计师事务所", "签字盖章")),
    ("financial_data_conflict_review", ("财务数据不一致", "勾稽关系", "负债", "担保", "诉讼")),
)

_ELECTRONIC_ENV_SIGNAL_DEFS = (
    ("shared_computer_or_network", ("同一电脑", "同一IP", "同一 IP", "同一网络", "MAC", "网卡")),
    ("shared_ca_or_account", ("CA锁混用", "CA 混用", "加密锁混用", "同一账号", "同一联系人")),
    ("shared_file_source", ("文件属性相同", "同源文件", "同一模板", "复制粘贴", "技术方案相似")),
    ("shared_tool_or_device", ("清单软件", "同一打印设备", "同一扫描设备", "打印复印设备")),
)


def build_bid_document_internal_qa_profile(inputs: Mapping[str, Any]) -> dict[str, Any]:
    text = _internal_bid_text(inputs)
    normalized = _normalize(text)
    has_internal_text = bool(normalized)

    dark_bid_risk_hits = _signal_hits(
        normalized,
        _DARK_BID_SIGNAL_DEFS,
        "dark_bid_anonymity_review",
    )
    authorization_signature_risk_hits = _authorization_signature_hits(normalized)
    declaration_form_risk_hits = _declaration_hits(normalized)
    financial_tax_audit_risk_hits = _signal_hits(
        normalized,
        _FINANCIAL_TAX_AUDIT_SIGNAL_DEFS,
        "financial_tax_audit_internal_review",
    )
    electronic_bid_environment_risk_hits = _signal_hits(
        normalized,
        _ELECTRONIC_ENV_SIGNAL_DEFS,
        "electronic_bid_environment_internal_review",
    )
    positive_deviation_quality_state = _positive_deviation_quality_state(normalized)
    structured_response_score = _structured_response_score(normalized)
    ai_review_readability = _ai_review_readability(structured_response_score, normalized)

    all_hit_count = sum(
        len(items)
        for items in (
            dark_bid_risk_hits,
            authorization_signature_risk_hits,
            declaration_form_risk_hits,
            financial_tax_audit_risk_hits,
            electronic_bid_environment_risk_hits,
        )
    )

    review_reasons = ["bid_document_internal_qa_profile_internal_only"]
    if not has_internal_text:
        review_reasons.append("internal_bid_document_text_missing")
    if dark_bid_risk_hits:
        review_reasons.append("dark_bid_anonymity_markers_detected")
    if positive_deviation_quality_state == "WEAK_OR_UNPROVEN_REVIEW":
        review_reasons.append("positive_deviation_unquantified_or_unproven")
    if authorization_signature_risk_hits:
        review_reasons.append("authorization_signature_markers_require_review")
    if declaration_form_risk_hits:
        review_reasons.append("declaration_form_markers_require_review")
    if financial_tax_audit_risk_hits:
        review_reasons.append("financial_tax_audit_markers_require_review")
    if electronic_bid_environment_risk_hits:
        review_reasons.append("electronic_bid_environment_markers_require_review")
    if structured_response_score < 60 and has_internal_text:
        review_reasons.append("structured_response_score_low")

    if not has_internal_text:
        profile_state = "NOT_RUN_MISSING_INTERNAL_BID_DOCUMENT"
    elif all_hit_count or positive_deviation_quality_state == "WEAK_OR_UNPROVEN_REVIEW":
        profile_state = "PROFILED_REVIEW_READY"
    else:
        profile_state = "PROFILED_NO_PUBLIC_MARKER"

    return {
        "profile_state": profile_state,
        "internal_bid_document_present": has_internal_text,
        "dark_bid_risk_hits": dark_bid_risk_hits,
        "positive_deviation_quality_state": positive_deviation_quality_state,
        "authorization_signature_risk_hits": authorization_signature_risk_hits,
        "declaration_form_risk_hits": declaration_form_risk_hits,
        "financial_tax_audit_risk_hits": financial_tax_audit_risk_hits,
        "electronic_bid_environment_risk_hits": electronic_bid_environment_risk_hits,
        "ai_review_readability": ai_review_readability,
        "structured_response_score": structured_response_score if has_internal_text else None,
        "review_required": has_internal_text,
        "review_reasons": _dedupe(review_reasons),
        "customer_visible": False,
        "internal_qa_only": True,
        "no_rejection_conclusion": True,
        "no_illegality_or_reserved_winner_conclusion": True,
    }


def _internal_bid_text(inputs: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _INTERNAL_BID_TEXT_KEYS:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(dict.fromkeys(parts))


def _signal_hits(
    text: str,
    defs: tuple[tuple[str, tuple[str, ...]], ...],
    risk_role: str,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not text:
        return hits
    for signal_type, tokens in defs:
        markers = [token for token in tokens if _contains(text, token)]
        if not markers:
            continue
        hits.append(
            {
                "signal_type": signal_type,
                "markers": markers,
                "match_basis": "deterministic_internal_bid_text_marker",
                "risk_role": risk_role,
                "review_required": True,
                "customer_visible": False,
                "no_conclusion": True,
            }
        )
    return hits


def _authorization_signature_hits(text: str) -> list[dict[str, Any]]:
    hits = _signal_hits(
        text,
        _AUTHORIZATION_SIGNATURE_SIGNAL_DEFS,
        "authorization_signature_internal_review",
    )
    if "授权委托书" not in text:
        return hits
    if "无转委托" not in text and "不得转委托" not in text:
        hits.append(
            _synthetic_hit(
                "authorization_scope_missing_no_subdelegation",
                "authorization_signature_internal_review",
            )
        )
    if not re.search(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        hits.append(
            _synthetic_hit(
                "authorization_period_date_missing",
                "authorization_signature_internal_review",
            )
        )
    if "授权范围" not in text and "签署" not in text and "澄清" not in text and "报价" not in text:
        hits.append(
            _synthetic_hit(
                "authorization_scope_not_specific",
                "authorization_signature_internal_review",
            )
        )
    return hits


def _declaration_hits(text: str) -> list[dict[str, Any]]:
    hits = _signal_hits(text, _DECLARATION_SIGNAL_DEFS, "declaration_form_internal_review")
    if "中小企业声明函" in text:
        for required_signal, tokens in (
            ("sme_industry_missing", ("行业分类", "所属行业")),
            ("sme_staff_revenue_asset_missing", ("从业人员", "营业收入", "资产总额")),
            ("sme_manufacturer_or_subject_missing", ("制造商", "承接主体", "声明主体")),
        ):
            if not any(token in text for token in tokens):
                hits.append(_synthetic_hit(required_signal, "declaration_form_internal_review"))
    if "进口产品" in text and ("本国产品声明函" in text or "国产产品声明函" in text):
        hits.append(
            _synthetic_hit("domestic_import_declaration_conflict", "declaration_form_internal_review")
        )
    return hits


def _positive_deviation_quality_state(text: str) -> str:
    if "正偏离" not in text:
        return "NOT_PRESENT"
    has_quantified_marker = bool(
        re.search(r"\d+(?:\.\d+)?\s*(%|％|天|日|小时|年|个月|项|次|公里|米|万元|元)", text)
    )
    has_evidence_marker = any(
        token in text
        for token in ("检测报告", "证明材料", "产品参数", "技术参数", "证书", "承诺函", "截图", "合同", "发票")
    )
    if has_quantified_marker and has_evidence_marker:
        return "QUANTIFIED_AND_EVIDENCED_REVIEW_READY"
    return "WEAK_OR_UNPROVEN_REVIEW"


def _structured_response_score(text: str) -> int:
    if not text:
        return 0
    score = 35
    positive_markers = (
        "目录",
        "评分索引",
        "响应矩阵",
        "页码",
        "证明材料",
        "证据链",
        "技术偏离表",
        "商务偏离表",
        "报价说明",
        "附件索引",
    )
    for marker in positive_markers:
        if marker in text:
            score += 6
    if "完全响应" in text and not any(marker in text for marker in ("证明材料", "页码", "附件索引")):
        score -= 12
    return max(0, min(100, score))


def _ai_review_readability(score: int, text: str) -> str:
    if not text:
        return "NOT_RUN_MISSING_INTERNAL_BID_DOCUMENT"
    if score >= 75:
        return "STRUCTURED_REVIEW_READY"
    if score >= 55:
        return "PARTIAL_STRUCTURE_REVIEW"
    return "LOW_STRUCTURE_REVIEW_REQUIRED"


def _synthetic_hit(signal_type: str, risk_role: str) -> dict[str, Any]:
    return {
        "signal_type": signal_type,
        "markers": [],
        "match_basis": "derived_internal_bid_text_gap",
        "risk_role": risk_role,
        "review_required": True,
        "customer_visible": False,
        "no_conclusion": True,
    }


def _contains(text: str, token: str) -> bool:
    return token.lower() in text.lower()


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


__all__ = ["build_bid_document_internal_qa_profile"]
