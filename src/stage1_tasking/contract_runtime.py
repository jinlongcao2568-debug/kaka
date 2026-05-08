from __future__ import annotations

from typing import Any, Mapping

from stage1_tasking.extractors import Stage1Extraction


def _project_stage1_authority_fields(
    extracted: Stage1Extraction,
    *,
    requires_manual_review: bool,
) -> dict[str, Any]:
    authority_fields: dict[str, Any] = {
        "source_family": extracted.source_family,
        "platform_level": extracted.platform_level,
        "region_scope": extracted.region_scope,
        "coverage_tier": extracted.coverage_tier,
        "carrier_type": extracted.carrier_type,
        "default_route": extracted.default_route,
        "source_registry_id": extracted.source_registry_id,
        "route_policy_id": extracted.route_policy_id,
        "fallback_route": extracted.fallback_route,
        "baseline_collection_state": extracted.baseline_collection_state,
        "rollout_enabled": extracted.rollout_enabled,
        "backlog_reason_optional": extracted.backlog_reason_optional,
        "review_lane": extracted.review_lane,
        "procurement_regime_hint": extracted.procurement_regime,
        "procurement_category_hint": extracted.procurement_category,
        "legal_system_type_candidate": extracted.legal_system_type_candidate,
        "legal_system_classification_confidence": extracted.legal_system_classification_confidence,
        "legal_system_classification_reasons": extracted.legal_system_classification_reasons,
        "fund_source_type": extracted.fund_source_type,
        "regulator_route_candidate": extracted.regulator_route_candidate,
        "remedy_path_candidate": extracted.remedy_path_candidate,
        "pre_notice_type": extracted.pre_notice_type,
        "source_channel_type": extracted.source_channel_type,
        "project_lifecycle_stage": extracted.project_lifecycle_stage,
        "source_quality_score": extracted.source_quality_score,
        "source_quality_reasons": extracted.source_quality_reasons,
        "project_intelligence_folder": extracted.project_intelligence_folder,
        "project_intelligence_state": extracted.project_intelligence_state,
        "project_intelligence_missing_reasons": extracted.project_intelligence_missing_reasons,
        "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
        "clock_precedence_rule_id": extracted.clock_precedence_rule_id,
        "requires_manual_review": requires_manual_review,
    }
    if extracted.current_action_start_at_optional:
        authority_fields["current_action_start_at_optional"] = extracted.current_action_start_at_optional
    if extracted.current_action_deadline_at_optional:
        authority_fields["current_action_deadline_at_optional"] = extracted.current_action_deadline_at_optional
    return authority_fields


def build_stage1_handoff(
    payload: Mapping[str, Any],
    *,
    project_id: str,
    context_id: str,
    extracted: Stage1Extraction,
    requires_manual_review: bool,
) -> dict[str, Any]:
    handoff = {
        "task_id": payload["task_id"],
        "region_code": payload["region_code"],
        "time_range_from": extracted.time_range_from,
        "time_range_until": extracted.time_range_until,
        "strategy_template_id": extracted.strategy_template_id,
        "project_rooting_policy": extracted.project_rooting_policy,
        "window_priority_policy": extracted.window_priority_policy,
        "project_id": project_id,
        "context_id": context_id,
    }
    handoff.update(
        _project_stage1_authority_fields(
            extracted,
            requires_manual_review=requires_manual_review,
        )
    )
    return handoff


def build_stage1_inputs(
    payload: Mapping[str, Any],
    *,
    extracted: Stage1Extraction,
) -> dict[str, Any]:
    inputs_out = dict(payload)
    inputs_out.update(
        {
            "time_range_from": extracted.time_range_from,
            "time_range_until": extracted.time_range_until,
            "default_route": extracted.default_route,
            "fallback_route": extracted.fallback_route,
            "source_registry_id": extracted.source_registry_id,
            "route_policy_id": extracted.route_policy_id,
            "carrier_type": extracted.carrier_type,
            "procurement_regime": extracted.procurement_regime,
            "procurement_category": extracted.procurement_category,
            "legal_system_type_candidate": extracted.legal_system_type_candidate,
            "legal_system_classification_confidence": extracted.legal_system_classification_confidence,
            "legal_system_classification_reasons": extracted.legal_system_classification_reasons,
            "fund_source_type": extracted.fund_source_type,
            "regulator_route_candidate": extracted.regulator_route_candidate,
            "remedy_path_candidate": extracted.remedy_path_candidate,
            "pre_notice_type": extracted.pre_notice_type,
            "source_channel_type": extracted.source_channel_type,
            "project_lifecycle_stage": extracted.project_lifecycle_stage,
            "source_quality_score": extracted.source_quality_score,
            "source_quality_reasons": extracted.source_quality_reasons,
            "project_intelligence_folder": extracted.project_intelligence_folder,
            "project_intelligence_state": extracted.project_intelligence_state,
            "project_intelligence_missing_reasons": extracted.project_intelligence_missing_reasons,
            "baseline_collection_state": extracted.baseline_collection_state,
            "rollout_enabled": extracted.rollout_enabled,
            "backlog_reason_optional": extracted.backlog_reason_optional,
            "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
            "clock_precedence_rule_id": extracted.clock_precedence_rule_id,
            "current_action_start_at_optional": extracted.current_action_start_at_optional,
            "current_action_deadline_at_optional": extracted.current_action_deadline_at_optional,
            "stage12_extractor_trace": {
                "stage1": {
                    "fallback_reasons": extracted.fallback_reasons,
                    "mismatch_reasons": extracted.mismatch_reasons,
                    "legal_system_type_candidate": extracted.legal_system_type_candidate,
                    "legal_system_classification_confidence": extracted.legal_system_classification_confidence,
                    "legal_system_classification_reasons": extracted.legal_system_classification_reasons,
                    "fund_source_type": extracted.fund_source_type,
                    "regulator_route_candidate": extracted.regulator_route_candidate,
                    "remedy_path_candidate": extracted.remedy_path_candidate,
                    "pre_notice_type": extracted.pre_notice_type,
                    "source_channel_type": extracted.source_channel_type,
                    "project_lifecycle_stage": extracted.project_lifecycle_stage,
                    "source_quality_score": extracted.source_quality_score,
                    "source_quality_reasons": extracted.source_quality_reasons,
                    "project_intelligence_state": extracted.project_intelligence_state,
                    "project_intelligence_missing_reasons": extracted.project_intelligence_missing_reasons,
                }
            },
        }
    )
    return inputs_out
