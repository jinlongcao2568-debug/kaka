# Stage: stage7_sales
# Internal commercial hook carrier for presale value teaser without evidence leakage.

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from shared.utils import build_id, ensure_list


COMMERCIAL_HOOK_LEAD_INPUT_KEY = "commercial_hook_lead"
COMMERCIAL_HOOK_READINESS_INPUT_KEY = "commercial_hook_readiness_summary"

DISCLOSURE_L1_HOOK = "L1_HOOK"
DISCLOSURE_INTERNAL_REVIEW_ONLY = "INTERNAL_REVIEW_ONLY"

WITHHELD_FIELDS = [
    "source_url",
    "full_person_name_with_identifier",
    "conflicting_project_name",
    "exact_overlap_window",
    "complete_verification_path",
    "raw_snapshot_or_attachment",
    "internal_scores",
]

FORBIDDEN_PRE_SALE_CLAIMS = [
    "concrete_source_url_that_reveals_full_evidence_path",
    "complete_project_manager_identity_plus_registration_combination",
    "complete_conflicting_project_name_and_time_window",
    "raw_snapshot_or_attachment_copy",
    "full_public_verification_route",
    "internal_score_model_or_buyer_ranking_logic",
    "legal_conclusion_or_guaranteed_outcome",
]

SAFE_ALLOWED_TALKING_POINT_TEMPLATES = [
    "存在公开记录风险信号",
    "证据强度已标注",
    "买家适配度和窗口优先级已标注",
    "建议报价区间已标注",
    "完整证据路径需审批交付后开放",
]

_EMPTY_VALUES = {None, "", "UNKNOWN", "None"}
_FORBIDDEN_TEXT_TOKENS = (
    "http://",
    "https://",
    "source_url",
    "raw_snapshot",
    "complete_verification_path",
    "full_public_verification_route",
    "internal_score_model",
    "registration_combination",
)


def build_commercial_hook_lead_carrier(
    *,
    sales_lead: Mapping[str, Any],
    saleable_opportunity: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
    buyer_fit: Mapping[str, Any],
    challenger_buyer_fit: Mapping[str, Any],
    legal_action_actor_profile: Mapping[str, Any],
    procurement_decision_actor_profile: Mapping[str, Any],
    stage6_product_package: Mapping[str, Any] | None,
    stage7_resolution_trace: Mapping[str, Any],
    leadpack_delivery_package: Mapping[str, Any],
    model_assist_summary: Mapping[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    stage6_package = dict(stage6_product_package or {})
    value_trace = dict(stage7_resolution_trace.get("value_derivation", {}) or {})
    formal_projection = dict(stage7_resolution_trace.get("formal_sink_projection", {}) or {})

    project_value_score = _coerce_int(
        formal_projection.get("project_value_score_optional"),
        default=_coerce_int(value_trace.get("project_value_score"), default=0),
    )
    opportunity_value_score = _coerce_int(
        saleable_opportunity.get("opportunity_value_score_optional"),
        default=_coerce_int(formal_projection.get("opportunity_value_score_optional"), default=0),
    )
    lead_score = _coerce_int(sales_lead.get("lead_score"), default=0)
    buyer_fit_score = _coerce_int(buyer_fit.get("fit_score"), default=0)
    challenger_fit_score = _coerce_int(challenger_buyer_fit.get("fit_score"), default=buyer_fit_score)
    objection_value_score = round(project_value_score * 0.4 + opportunity_value_score * 0.6)
    buyer_motivation_score = round(
        _coerce_int(buyer_fit.get("attack_motivation_score"), default=0) * 0.55
        + _coerce_int(buyer_fit.get("purchase_intent_score"), default=0) * 0.45
    )
    purchase_capacity_score = _coerce_int(buyer_fit.get("payment_capacity_score"), default=0)
    conversion_score = round(
        objection_value_score * 0.35
        + lead_score * 0.25
        + buyer_fit_score * 0.25
        + challenger_fit_score * 0.15
    )

    saleability_status = str(saleable_opportunity.get("saleability_status") or "UNKNOWN")
    lead_status = str(sales_lead.get("lead_status") or "UNKNOWN")
    offer_state = str(offer_recommendation.get("offer_recommendation_state") or "UNKNOWN")
    evidence_strength_label = _evidence_strength_label(
        saleability_status=saleability_status,
        lead_status=lead_status,
        offer_state=offer_state,
        objection_value_score=objection_value_score,
    )
    conversion_priority = _conversion_priority(
        conversion_score=conversion_score,
        saleability_status=saleability_status,
        lead_status=lead_status,
    )
    hook_eligible = (
        saleability_status == "QUALIFIED"
        and lead_status == "QUALIFIED"
        and offer_state == "APPROVED"
        and evidence_strength_label != "INSUFFICIENT_FOR_HOOK"
    )
    disclosure_level = DISCLOSURE_L1_HOOK if hook_eligible else DISCLOSURE_INTERNAL_REVIEW_ONLY

    defect_label = _defect_category_public_label(saleable_opportunity, stage7_resolution_trace)
    urgency_label = _urgency_label(buyer_fit)
    buyer_benefit_summary = _buyer_benefit_summary(
        buyer_fit=buyer_fit,
        offer_recommendation=offer_recommendation,
        conversion_priority=conversion_priority,
    )
    teaser_copy = _teaser_copy(
        defect_label=defect_label,
        evidence_strength_label=evidence_strength_label,
        urgency_label=urgency_label,
        conversion_priority=conversion_priority,
    )
    redacted_claim_summary = _redacted_claim_summary(
        defect_label=defect_label,
        evidence_strength_label=evidence_strength_label,
        disclosure_level=disclosure_level,
    )
    allowed_sales_talking_points = _allowed_talking_points(
        evidence_strength_label=evidence_strength_label,
        urgency_label=urgency_label,
        buyer_type=buyer_fit.get("buyer_type"),
        offer_recommendation=offer_recommendation,
    )
    forbidden_claims_filter_passed = not _contains_forbidden_text(
        [
            teaser_copy,
            redacted_claim_summary,
            *allowed_sales_talking_points,
            buyer_benefit_summary,
        ]
    )
    leakage_risk = _leakage_risk(
        disclosure_level=disclosure_level,
        hook_eligible=hook_eligible,
        forbidden_claims_filter_passed=forbidden_claims_filter_passed,
        conversion_priority=conversion_priority,
        evidence_strength_label=evidence_strength_label,
    )
    requires_manual_review = conversion_priority == "HIGH" or leakage_risk["risk_level"] != "LOW"

    source_product_package_id = (
        stage6_package.get("carrier_id")
        or stage6_package.get("product_package_id")
        or leadpack_delivery_package.get("package_id")
    )
    return {
        "hook_lead_id": _stable_hook_id(
            saleable_opportunity.get("opportunity_id"),
            sales_lead.get("lead_id"),
            source_product_package_id,
        ),
        "contract_id": "COMMERCIAL_HOOK_LEAD_V1",
        "source_product_package_id": source_product_package_id,
        "source_stage": "stage7_sales",
        "source_stage6_package_id_optional": stage6_package.get("carrier_id"),
        "source_leadpack_package_id_optional": leadpack_delivery_package.get("package_id"),
        "market_region": "REDACTED_OR_DERIVED_FROM_SOURCE_BLUEPRINT",
        "project_category": "PUBLIC_PROJECT_RISK_SIGNAL",
        "project_value_band": str(value_trace.get("project_value_band") or _score_band(project_value_score)),
        "notice_stage": "PUBLIC_NOTICE_REVIEW",
        "objection_window_state": _window_state(buyer_fit),
        "defect_category_public_label": defect_label,
        "evidence_strength_label": evidence_strength_label,
        "buyer_benefit_summary": buyer_benefit_summary,
        "urgency_label": urgency_label,
        "teaser_copy": teaser_copy,
        "redacted_claim_summary": redacted_claim_summary,
        "withheld_fields": list(WITHHELD_FIELDS),
        "disclosure_level": disclosure_level,
        "allowed_sales_talking_points": allowed_sales_talking_points,
        "forbidden_sales_claims": list(FORBIDDEN_PRE_SALE_CLAIMS),
        "forbidden_claims_filter_passed": forbidden_claims_filter_passed,
        "conversion_risk": _conversion_risk(
            conversion_priority=conversion_priority,
            saleability_status=saleability_status,
            lead_status=lead_status,
        ),
        "leakage_risk": leakage_risk,
        "requires_manual_review": requires_manual_review,
        "approval_state": "REVIEW_REQUIRED_BEFORE_CUSTOMER_VISIBLE",
        "hook_eligibility_state": (
            "ELIGIBLE_FOR_INTERNAL_HOOK_REVIEW" if hook_eligible else "REVIEW_REQUIRED"
        ),
        "hook_eligible_for_presale_touch": hook_eligible,
        "customer_visible_enabled": False,
        "external_send_enabled": False,
        "real_outreach_send_enabled": False,
        "provider_call_enabled": False,
        "no_full_evidence_leakage": forbidden_claims_filter_passed,
        "no_source_url_disclosure": True,
        "no_raw_snapshot_or_attachment_disclosure": True,
        "no_internal_score_model_disclosure": True,
        "llm_role": "sales_hook_copy_draft_only",
        "llm_output_not_final_claim": True,
        "model_assist_summary": dict(model_assist_summary or {}),
        "business_value_summary": {
            "objection_value_score": objection_value_score,
            "project_value_score": project_value_score,
            "opportunity_value_score": opportunity_value_score,
            "lead_score": lead_score,
            "conversion_score": conversion_score,
            "conversion_priority": conversion_priority,
            "score_source": "lead_value_scoring_catalog_and_buyer_fit_scorecard_outputs",
        },
        "buyer_fit_summary": {
            "buyer_fit_id": buyer_fit.get("buyer_fit_id"),
            "challenger_buyer_fit_id": challenger_buyer_fit.get("challenger_buyer_fit_id"),
            "buyer_type": buyer_fit.get("buyer_type"),
            "buyer_fit_score": buyer_fit_score,
            "challenger_buyer_fit_score": challenger_fit_score,
            "buyer_motivation_score": buyer_motivation_score,
            "purchase_capacity_score": purchase_capacity_score,
            "fit_reason_tags": list(ensure_list(buyer_fit.get("fit_reason_tags"))),
        },
        "source_object_refs": {
            "sales_lead_id": sales_lead.get("lead_id"),
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "offer_recommendation_id": offer_recommendation.get("offer_recommendation_id"),
            "buyer_fit_id": buyer_fit.get("buyer_fit_id"),
            "challenger_buyer_fit_id": challenger_buyer_fit.get("challenger_buyer_fit_id"),
            "legal_action_actor_id": legal_action_actor_profile.get("actor_id"),
            "procurement_decision_actor_id": procurement_decision_actor_profile.get("actor_id"),
            "stage6_product_package_id": stage6_package.get("carrier_id"),
            "leadpack_package_id": leadpack_delivery_package.get("package_id"),
        },
        "audit_refs": {
            "policy_ref": "control/product_runtime_architecture_map.yaml#commercial_hook_lead_contract",
            "buyer_fit_scorecard_ref": "contracts/sales/buyer_fit_scorecard.json",
            "lead_value_scoring_ref": "contracts/sales/lead_value_scoring_catalog.json",
            "opportunity_policy_ref": "contracts/sales/opportunity_policy_catalog.json",
            "created_at": now,
        },
    }


def build_commercial_hook_readiness_summary(carrier: Mapping[str, Any]) -> dict[str, Any]:
    business_value = dict(carrier.get("business_value_summary", {}) or {})
    buyer_fit = dict(carrier.get("buyer_fit_summary", {}) or {})
    leakage = dict(carrier.get("leakage_risk", {}) or {})
    return {
        "hook_lead_id": carrier.get("hook_lead_id"),
        "contract_id": carrier.get("contract_id"),
        "hook_eligibility_state": carrier.get("hook_eligibility_state"),
        "hook_eligible_for_presale_touch": bool(carrier.get("hook_eligible_for_presale_touch")),
        "disclosure_level": carrier.get("disclosure_level"),
        "evidence_strength_label": carrier.get("evidence_strength_label"),
        "conversion_priority": business_value.get("conversion_priority"),
        "objection_value_score": business_value.get("objection_value_score"),
        "buyer_fit_score": buyer_fit.get("buyer_fit_score"),
        "buyer_motivation_score": buyer_fit.get("buyer_motivation_score"),
        "purchase_capacity_score": buyer_fit.get("purchase_capacity_score"),
        "leakage_risk_level": leakage.get("risk_level"),
        "leakage_risk_classified": bool(leakage.get("classified")),
        "forbidden_claims_filter_passed": bool(carrier.get("forbidden_claims_filter_passed")),
        "requires_manual_review": bool(carrier.get("requires_manual_review")),
        "customer_visible_enabled": False,
        "external_send_enabled": False,
        "no_full_evidence_leakage": bool(carrier.get("no_full_evidence_leakage")),
        "withheld_field_count": len(ensure_list(carrier.get("withheld_fields"))),
    }


def _evidence_strength_label(
    *,
    saleability_status: str,
    lead_status: str,
    offer_state: str,
    objection_value_score: int,
) -> str:
    if saleability_status == "QUALIFIED" and lead_status == "QUALIFIED" and offer_state == "APPROVED":
        return "STRONG_PUBLIC_SIGNAL" if objection_value_score >= 70 else "REVIEWABLE_PUBLIC_SIGNAL"
    if saleability_status == "BLOCKED" or lead_status == "DISQUALIFIED":
        return "INSUFFICIENT_FOR_HOOK"
    return "REVIEWABLE_PUBLIC_SIGNAL"


def _conversion_priority(*, conversion_score: int, saleability_status: str, lead_status: str) -> str:
    if saleability_status == "BLOCKED" or lead_status == "DISQUALIFIED":
        return "BLOCKED"
    if conversion_score >= 82:
        return "HIGH"
    if conversion_score >= 65:
        return "MEDIUM"
    return "LOW"


def _conversion_risk(*, conversion_priority: str, saleability_status: str, lead_status: str) -> dict[str, Any]:
    reasons: list[str] = []
    if saleability_status != "QUALIFIED":
        reasons.append(f"saleability_status={saleability_status}")
    if lead_status != "QUALIFIED":
        reasons.append(f"lead_status={lead_status}")
    if conversion_priority in {"LOW", "BLOCKED"}:
        reasons.append(f"conversion_priority={conversion_priority}")
    return {
        "risk_level": "HIGH" if conversion_priority == "BLOCKED" else "MEDIUM" if reasons else "LOW",
        "conversion_priority": conversion_priority,
        "reasons": reasons,
    }


def _leakage_risk(
    *,
    disclosure_level: str,
    hook_eligible: bool,
    forbidden_claims_filter_passed: bool,
    conversion_priority: str,
    evidence_strength_label: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    if disclosure_level != DISCLOSURE_L1_HOOK:
        reasons.append(f"disclosure_level={disclosure_level}")
    if not hook_eligible:
        reasons.append("hook_not_eligible")
    if not forbidden_claims_filter_passed:
        reasons.append("forbidden_claims_filter_failed")
    if conversion_priority == "HIGH":
        reasons.append("high_value_hook_requires_manual_review")
    if evidence_strength_label == "INSUFFICIENT_FOR_HOOK":
        reasons.append("insufficient_evidence_for_hook")
    if not forbidden_claims_filter_passed or evidence_strength_label == "INSUFFICIENT_FOR_HOOK":
        risk_level = "HIGH"
    elif reasons:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    return {
        "risk_level": risk_level,
        "classified": True,
        "forbidden_claims_filter_passed": forbidden_claims_filter_passed,
        "reasons": reasons,
    }


def _defect_category_public_label(
    saleable_opportunity: Mapping[str, Any],
    stage7_resolution_trace: Mapping[str, Any],
) -> str:
    points = ensure_list(saleable_opportunity.get("major_value_points"))
    if any("PROJECT_MANAGER" in str(point) or "PM-" in str(point) for point in points):
        return "public_manager_or_performance_risk_signal"
    if any("QUAL" in str(point) for point in points):
        return "public_qualification_risk_signal"
    if any("CREDIT" in str(point) for point in points):
        return "public_credit_risk_signal"
    real_challenger = dict(stage7_resolution_trace.get("real_challenger_identification", {}) or {})
    if real_challenger.get("winning_candidate"):
        return "public_competition_risk_signal"
    return "public_procurement_risk_signal"


def _buyer_benefit_summary(
    *,
    buyer_fit: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
    conversion_priority: str,
) -> str:
    buyer_type = str(buyer_fit.get("buyer_type") or "REVIEW_BUYER")
    quote_band = str(offer_recommendation.get("recommended_quote_band") or "REVIEW")
    return (
        f"{_display_label(buyer_type)}：{_display_label(conversion_priority)}优先级；"
        f"建议报价区间{_display_label(quote_band)}；完整证据受交付门禁控制。"
    )


def _teaser_copy(
    *,
    defect_label: str,
    evidence_strength_label: str,
    urgency_label: str,
    conversion_priority: str,
) -> str:
    return (
        f"{_display_label(conversion_priority)}价值公开风险信号：{_display_label(defect_label)}；"
        f"证据强度：{_display_label(evidence_strength_label)}；"
        f"紧急度：{_display_label(urgency_label)}；"
        "完整核验路径需审批交付后开放。"
    )


def _redacted_claim_summary(*, defect_label: str, evidence_strength_label: str, disclosure_level: str) -> str:
    return (
        f"脱敏钩子摘要：{_display_label(defect_label)}；"
        f"证据强度：{_display_label(evidence_strength_label)}；"
        f"披露级别：{_display_label(disclosure_level)}；详细标识和复现路径暂不展示。"
    )


def _allowed_talking_points(
    *,
    evidence_strength_label: str,
    urgency_label: str,
    buyer_type: Any,
    offer_recommendation: Mapping[str, Any],
) -> list[str]:
    quote_band = offer_recommendation.get("recommended_quote_band") or "REVIEW"
    return [
        *SAFE_ALLOWED_TALKING_POINT_TEMPLATES,
        f"买家类型：{_display_label(buyer_type or 'REVIEW_BUYER')}",
        f"证据强度：{_display_label(evidence_strength_label)}",
        f"紧急度：{_display_label(urgency_label)}",
        f"建议报价区间：{_display_label(quote_band)}",
    ]


def _display_label(value: Any) -> str:
    text = str(value or "REVIEW")
    labels = {
        "LOW": "低",
        "MEDIUM": "中",
        "HIGH": "高",
        "URGENT": "紧急",
        "TIME_SENSITIVE": "时间敏感",
        "STANDARD": "常规",
        "REVIEW": "待复核",
        "REVIEW_BUYER": "待复核买家",
        "L1_HOOK": "一级钩子摘要",
        "INTERNAL_REVIEW_ONLY": "仅内部复核",
        "REVIEWABLE_PUBLIC_SIGNAL": "公开信号可复核",
        "public_manager_or_performance_risk_signal": "公开项目经理或履约风险信号",
        "public_qualification_risk_signal": "公开资质风险信号",
        "public_credit_risk_signal": "公开信用风险信号",
        "public_competition_risk_signal": "公开竞争风险信号",
        "public_procurement_risk_signal": "公开采购风险信号",
        "GOVERNMENT": "政府/采购主管",
        "legal_action_actor": "法务/异议行动方",
        "procurement_decision_actor": "采购决策方",
    }
    return labels.get(text, text.replace("_", " "))


def _urgency_label(buyer_fit: Mapping[str, Any]) -> str:
    score = _coerce_int(buyer_fit.get("window_urgency_score"), default=0)
    if score >= 85:
        return "URGENT"
    if score >= 65:
        return "TIME_SENSITIVE"
    return "STANDARD"


def _window_state(buyer_fit: Mapping[str, Any]) -> str:
    score = _coerce_int(buyer_fit.get("window_urgency_score"), default=0)
    if score >= 85:
        return "OPEN_URGENT"
    if score >= 55:
        return "OPEN_REVIEW"
    return "LOW_URGENCY_OR_UNKNOWN"


def _score_band(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _contains_forbidden_text(values: list[Any]) -> bool:
    haystack = " ".join(str(value).lower() for value in values if value not in _EMPTY_VALUES)
    return any(token in haystack for token in _FORBIDDEN_TEXT_TOKENS)


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _stable_hook_id(*parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:12].upper()
    return build_id("HOOK", digest)


__all__ = [
    "COMMERCIAL_HOOK_LEAD_INPUT_KEY",
    "COMMERCIAL_HOOK_READINESS_INPUT_KEY",
    "build_commercial_hook_lead_carrier",
    "build_commercial_hook_readiness_summary",
]
