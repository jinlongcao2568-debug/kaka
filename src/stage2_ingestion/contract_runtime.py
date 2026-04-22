from __future__ import annotations

from typing import Any, Mapping

from stage2_ingestion.extractors import Stage2Extraction


def _project_stage2_authority_fields(
    extracted: Stage2Extraction,
    *,
    collection_state: str,
    version_conflict_state: str,
) -> dict[str, Any]:
    authority_fields: dict[str, Any] = {
        "source_registry_id": extracted.source_registry_id,
        "route_policy_id": extracted.route_policy_id,
        "fallback_route": extracted.fallback_route,
        "route_decision_state": extracted.route_decision_state,
        "route_review_reasons": extracted.route_review_reasons,
        "winning_version_resolution_rule_id": extracted.winning_version_resolution_rule_id,
        "version_conflict_state": version_conflict_state,
        "clock_precedence_rule_id": extracted.clock_precedence_rule_id,
        "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
        "collection_state": collection_state,
    }
    if extracted.current_action_start_at_optional:
        authority_fields["current_action_start_at_optional"] = extracted.current_action_start_at_optional
    if extracted.current_action_deadline_at_optional:
        authority_fields["current_action_deadline_at_optional"] = extracted.current_action_deadline_at_optional
    return authority_fields


def build_stage2_handoff(
    *,
    extracted: Stage2Extraction,
    clock_chain_id: str,
    version_chain_id: str,
    fixation_bundle_id: str,
    origin_carrier_type: str,
    first_seen_at: str,
    last_retrieved_at: str,
    clock_conflict_state: str,
    project_rooting_policy: str,
    window_priority_policy: str,
    identity_resolution_rule_id: str,
    collection_state: str,
    version_conflict_state: str,
) -> dict[str, Any]:
    handoff = {
        "project_id": extracted.project_id,
        "clock_chain_id": clock_chain_id,
        "version_chain_id": version_chain_id,
        "fixation_bundle_id": fixation_bundle_id,
        "origin_carrier_type": origin_carrier_type,
        "first_seen_at": first_seen_at,
        "last_retrieved_at": last_retrieved_at,
        "clock_conflict_state": clock_conflict_state,
        "project_rooting_policy": project_rooting_policy,
        "window_priority_policy": window_priority_policy,
        "identity_resolution_rule_id": identity_resolution_rule_id,
    }
    handoff.update(
        _project_stage2_authority_fields(
            extracted,
            collection_state=collection_state,
            version_conflict_state=version_conflict_state,
        )
    )
    return handoff


def build_stage2_inputs(
    inputs: Mapping[str, Any],
    *,
    extracted: Stage2Extraction,
    fixation_bundle_id: str,
    origin_carrier_type: str,
    first_seen_at: str,
    last_retrieved_at: str,
    clock_conflict_state: str,
    collection_state: str,
    version_conflict_state: str,
) -> dict[str, Any]:
    inputs_out = dict(inputs)
    inputs_out.update(
        {
            "fixation_bundle_id": fixation_bundle_id,
            "origin_carrier_type": origin_carrier_type,
            "first_seen_at": first_seen_at,
            "last_retrieved_at": last_retrieved_at,
            "clock_conflict_state": clock_conflict_state,
            "source_registry_id": extracted.source_registry_id,
            "route_policy_id": extracted.route_policy_id,
            "default_route": extracted.default_route,
            "fallback_route": extracted.fallback_route,
            "route_decision_state": extracted.route_decision_state,
            "route_review_reasons": extracted.route_review_reasons,
            "route_downgrade_signals": extracted.route_downgrade_signals,
            "route_block_signals": extracted.route_block_signals,
            "collection_state": collection_state,
            "winning_version_resolution_rule_id": extracted.winning_version_resolution_rule_id,
            "version_conflict_state": version_conflict_state,
            "version_precedence_source": extracted.version_precedence_source,
            "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
            "clock_precedence_rule_id": extracted.clock_precedence_rule_id,
            "clock_precedence_source": extracted.clock_precedence_source,
            "current_action_start_at_optional": extracted.current_action_start_at_optional,
            "current_action_deadline_at_optional": extracted.current_action_deadline_at_optional,
            "stage12_extractor_trace": {
                **dict(inputs.get("stage12_extractor_trace", {})),
                "stage2": {
                    "route_review_reasons": extracted.route_review_reasons,
                    "route_decision_state": extracted.route_decision_state,
                    "route_downgrade_signals": extracted.route_downgrade_signals,
                    "route_block_signals": extracted.route_block_signals,
                    "source_registry_id_source": extracted.source_registry_id_source,
                    "route_policy_id_source": extracted.route_policy_id_source,
                    "default_route_source": extracted.default_route_source,
                    "fallback_route_source": extracted.fallback_route_source,
                    "collection_state_source": "route_policy_runtime_map",
                    "clock_resolution_rule_id_source": extracted.clock_resolution_rule_source,
                    "winning_version_resolution_rule_id_source": extracted.version_precedence_source,
                    "clock_precedence_rule_id_source": extracted.clock_precedence_source,
                },
            },
        }
    )
    return inputs_out

