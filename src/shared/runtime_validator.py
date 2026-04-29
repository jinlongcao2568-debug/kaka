from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import json

from shared.runtime_semantic_rules import (
    _semantic_contact_target as _semantic_contact_target_rule,
    _semantic_delivery_record as _semantic_delivery_record_rule,
    _semantic_governance_feedback_event as _semantic_governance_feedback_event_rule,
    _semantic_opportunity_outcome_event as _semantic_opportunity_outcome_event_rule,
    _semantic_order_record as _semantic_order_record_rule,
    _semantic_outreach_plan as _semantic_outreach_plan_rule,
    _semantic_payment_record as _semantic_payment_record_rule,
    _semantic_touch_record as _semantic_touch_record_rule,
)
from shared.state_packet import GovernanceGuardResult, SemanticValidationResult


@dataclass(frozen=True)
class TypeSpec:
    expected_type: str
    item_type: str | None = None


class RuntimeValidator:
    RELEASE_LEVEL_RANK = {
        "DEV_ALLOWED": 0,
        "INTERNAL_OPERABLE": 1,
        "LEADPACK_DELIVERABLE": 2,
    }
    FIELD_POLICY_ALIASES = {
        "contact_target.person_name_optional": ("contact_target.person_name",),
    }
    STRICT_PROFILES: dict[str, dict[str, TypeSpec]] = {
        "project_fact": {
            "project_fact_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "sale_gate_status": TypeSpec("str"),
            "rule_gate_status": TypeSpec("str"),
            "evidence_gate_status": TypeSpec("str"),
            "rule_hit_summary": TypeSpec("list", "str"),
            "clue_summary": TypeSpec("list", "str"),
            "risk_summary": TypeSpec("list", "str"),
            "coverage_sellable_state": TypeSpec("str"),
            "delivery_risk_state": TypeSpec("str"),
            "manual_override_status": TypeSpec("str"),
            "real_competitor_count": TypeSpec("int"),
            "serviceable_competitor_count": TypeSpec("int"),
            "competitor_quality_grade": TypeSpec("str"),
        },
        "legal_action_recommendation": {
            "action_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "action_family": TypeSpec("str"),
            "applicable_regime": TypeSpec("str"),
            "competent_authority_scope": TypeSpec("str"),
            "window_status": TypeSpec("str"),
            "basis_summary": TypeSpec("str"),
            "blocking_reasons": TypeSpec("list", "str"),
            "recommended_next_step": TypeSpec("str"),
        },
        "review_queue_profile": {
            "queue_profile_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "review_lane": TypeSpec("str"),
            "review_priority_score": TypeSpec("int"),
            "review_queue_bucket": TypeSpec("str"),
            "window_risk_level": TypeSpec("str"),
            "commercial_urgency_level": TypeSpec("str"),
            "assigned_reviewer_optional": TypeSpec("str"),
        },
        "execution_context": {
            "context_id": TypeSpec("str"),
            "task_id": TypeSpec("str"),
            "project_unification_strategy": TypeSpec("str"),
            "review_lane": TypeSpec("str"),
            "window_priority": TypeSpec("str"),
            "region_scope": TypeSpec("str"),
            "source_family": TypeSpec("str"),
            "platform_level": TypeSpec("str"),
            "coverage_tier": TypeSpec("str"),
            "carrier_type": TypeSpec("str"),
            "default_route": TypeSpec("str"),
            "source_registry_id": TypeSpec("str"),
            "route_policy_id": TypeSpec("str"),
            "fallback_route": TypeSpec("str"),
            "requires_manual_review": TypeSpec("bool"),
            "created_at": TypeSpec("str"),
        },
        "public_chain": {
            "public_chain_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "announcement_url": TypeSpec("str"),
            "source_family": TypeSpec("str"),
            "platform_level": TypeSpec("str"),
            "region_scope": TypeSpec("str"),
            "coverage_tier": TypeSpec("str"),
            "carrier_type": TypeSpec("str"),
            "source_registry_id": TypeSpec("str"),
            "route_policy_id": TypeSpec("str"),
            "default_route": TypeSpec("str"),
            "fallback_route": TypeSpec("str"),
            "route_decision_state": TypeSpec("str"),
            "route_review_reasons": TypeSpec("list", "str"),
            "route_downgrade_signals": TypeSpec("list", "str"),
            "route_block_signals": TypeSpec("list", "str"),
            "collection_state": TypeSpec("str"),
            "requires_manual_review": TypeSpec("bool"),
            "timeline_nodes": TypeSpec("list", "str"),
            "required_node_set": TypeSpec("list", "str"),
            "node_presence_matrix": TypeSpec("object"),
            "statutory_node_completeness": TypeSpec("bool"),
            "window_clock_state": TypeSpec("str"),
            "clock_chain_id": TypeSpec("str"),
            "version_chain_id": TypeSpec("str"),
            "first_seen_at": TypeSpec("str"),
            "last_retrieved_at": TypeSpec("str"),
            "origin_carrier_type": TypeSpec("str"),
            "fixation_bundle_id": TypeSpec("str"),
        },
        "clock_chain_profile": {
            "clock_chain_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "publication_clock_state": TypeSpec("str"),
            "first_seen_clock_state": TypeSpec("str"),
            "correction_clock_state": TypeSpec("str"),
            "reply_clock_state": TypeSpec("str"),
            "remedy_clock_state": TypeSpec("str"),
            "clock_resolution_rule_id": TypeSpec("str"),
            "current_action_clock": TypeSpec("str"),
            "clock_conflict_state": TypeSpec("str"),
            "collection_state": TypeSpec("str"),
            "requires_manual_review": TypeSpec("bool"),
        },
        "notice_version_chain": {
            "version_chain_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "source_family": TypeSpec("str"),
            "platform_level": TypeSpec("str"),
            "region_scope": TypeSpec("str"),
            "carrier_type": TypeSpec("str"),
            "source_registry_id": TypeSpec("str"),
            "route_policy_id": TypeSpec("str"),
            "default_route": TypeSpec("str"),
            "fallback_route": TypeSpec("str"),
            "collection_state": TypeSpec("str"),
            "current_notice_version_id": TypeSpec("str"),
            "superseded_version_ids": TypeSpec("list", "str"),
            "replacement_edges": TypeSpec("list"),
            "version_conflict_state": TypeSpec("str"),
            "version_chain_strategy": TypeSpec("str"),
            "winning_version_resolution_rule_id": TypeSpec("str"),
        },
        "report_record": {
            "report_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "brief_path": TypeSpec("str"),
            "evidence_pack_path": TypeSpec("str"),
            "objection_draft_path": TypeSpec("str"),
            "review_task_status": TypeSpec("str"),
            "report_status": TypeSpec("str"),
            "review_lane": TypeSpec("str"),
            "review_sla_due_at": TypeSpec("str"),
            "minimum_release_level": TypeSpec("str"),
        },
        "challenger_candidate_profile": {
            "challenger_profile_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "focus_bidder_id": TypeSpec("str"),
            "challenger_bidder_id": TypeSpec("str"),
            "candidate_position_label": TypeSpec("str"),
            "focus_bidder_attackability_score": TypeSpec("number"),
            "challenger_pain_score": TypeSpec("number"),
            "succession_gain_score": TypeSpec("number"),
            "execution_readiness_score": TypeSpec("number"),
            "challenge_actionability_score": TypeSpec("number"),
        },
        "legal_action_actor_profile": {
            field: TypeSpec("str")
            for field in (
                "actor_id",
                "project_id",
                "actor_org_name",
                "actor_role_cluster",
                "standing_state",
                "action_window_state",
                "actionability_state",
                "action_family_scope",
            )
        },
        "procurement_decision_actor_profile": {
            field: TypeSpec("str")
            for field in (
                "actor_id",
                "project_id",
                "actor_org_name",
                "actor_role_cluster",
                "procurement_authority_state",
                "purchase_authority_state",
                "payment_authority_state",
                "reachable_state",
            )
        },
        "buyer_fit": {
            "buyer_fit_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "buyer_type": TypeSpec("str"),
            "fit_score": TypeSpec("number"),
            "attack_motivation_score": TypeSpec("number"),
            "purchase_intent_score": TypeSpec("number"),
            "payment_capacity_score": TypeSpec("number"),
            "window_urgency_score": TypeSpec("number"),
            "fit_reason_tags": TypeSpec("list", "str"),
        },
        "challenger_buyer_fit": {
            "challenger_buyer_fit_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "buyer_type": TypeSpec("str"),
            "fit_score": TypeSpec("number"),
            "attack_motivation_score": TypeSpec("number"),
            "purchase_intent_score": TypeSpec("number"),
            "payment_capacity_score": TypeSpec("number"),
            "window_urgency_score": TypeSpec("number"),
            "fit_reason_tags": TypeSpec("list", "str"),
        },
        "sales_lead": {
            "lead_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "lead_reason_summary": TypeSpec("str"),
            "lead_score": TypeSpec("number"),
            "lead_status": TypeSpec("str"),
            "generated_at": TypeSpec("str"),
        },
        "offer_recommendation": {
            "offer_recommendation_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "offer_recommendation_state": TypeSpec("str"),
            "sku_code": TypeSpec("str"),
            "recommended_delivery_form": TypeSpec("str"),
            "recommended_quote_band": TypeSpec("str"),
            "why_recommended": TypeSpec("str"),
            "prerequisites": TypeSpec("list", "str"),
        },
        "saleable_opportunity": {
            "opportunity_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "recommended_sku": TypeSpec("str"),
            "buyer_fit_id": TypeSpec("str"),
            "challenger_profile_id": TypeSpec("str"),
            "opportunity_grade": TypeSpec("str"),
            "saleability_status": TypeSpec("str"),
            "major_value_points": TypeSpec("list", "str"),
            "blocking_reasons": TypeSpec("list", "str"),
            "expected_close_days_band": TypeSpec("str"),
            "expected_contract_value_band": TypeSpec("str"),
            "expected_delivery_cost_band": TypeSpec("str"),
            "crm_owner_state": TypeSpec("str"),
        },
        "contact_target": {
            "contact_target_id": TypeSpec("str"),
            "opportunity_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "saleability_status": TypeSpec("str"),
            "org_name": TypeSpec("str"),
            "org_type": TypeSpec("str"),
            "person_name_optional": TypeSpec("str"),
            "role_cluster": TypeSpec("str"),
            "public_contact_source": TypeSpec("str"),
            "source_family": TypeSpec("str"),
            "source_auditability_state": TypeSpec("str"),
            "source_vendor_id_optional": TypeSpec("str"),
            "source_vendor_type_optional": TypeSpec("str"),
            "source_vendor_role": TypeSpec("str"),
            "contact_channel": TypeSpec("str"),
            "channel_family": TypeSpec("str"),
            "contact_target_status": TypeSpec("str"),
            "contact_validity_status": TypeSpec("str"),
            "contact_legal_basis": TypeSpec("str"),
            "reasonable_expectation_status": TypeSpec("str"),
            "channel_policy_status": TypeSpec("str"),
            "frequency_policy_state": TypeSpec("str"),
            "opt_out_state": TypeSpec("str"),
            "quiet_hours_policy_state": TypeSpec("str"),
            "auto_contact_allowed": TypeSpec("bool"),
            "source_audit_ref": TypeSpec("str"),
            "query_trace_id": TypeSpec("str"),
            "vendor_response_ref_optional": TypeSpec("str"),
            "fallback_vendor_id_optional": TypeSpec("str"),
            "requires_manual_review": TypeSpec("bool"),
            "primary_contact_flag": TypeSpec("bool"),
            "contact_priority_score": TypeSpec("int"),
            "contact_priority_reason_tags": TypeSpec("list", "str"),
            "contact_candidate_rank": TypeSpec("int"),
            "contact_selection_reason": TypeSpec("str"),
            "contact_conflict_flag": TypeSpec("bool"),
            "contact_conflict_reason": TypeSpec("str"),
            "blocking_reasons": TypeSpec("list", "str"),
            "last_evaluated_at": TypeSpec("str"),
        },
        "outreach_plan": {
            "outreach_plan_id": TypeSpec("str"),
            "opportunity_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "saleability_status": TypeSpec("str"),
            "contact_target_id": TypeSpec("str"),
            "execution_vendor_id_optional": TypeSpec("str"),
            "execution_vendor_type_optional": TypeSpec("str"),
            "execution_vendor_role_optional": TypeSpec("str"),
            "channel_strategy": TypeSpec("str"),
            "requested_delivery_surface": TypeSpec("str"),
            "projection_mode": TypeSpec("str"),
            "cadence_profile_id": TypeSpec("str"),
            "retry_policy_id": TypeSpec("str"),
            "stop_policy_id": TypeSpec("str"),
            "primary_message": TypeSpec("str"),
            "planned_touch_at": TypeSpec("str"),
            "attempt_index": TypeSpec("int"),
            "approval_state": TypeSpec("str"),
            "plan_status": TypeSpec("str"),
            "run_mode": TypeSpec("str"),
            "automation_level": TypeSpec("str"),
            "next_touch_due_at_optional": TypeSpec("str"),
            "retry_count": TypeSpec("int"),
            "max_retry_count": TypeSpec("int"),
            "stop_reason_optional": TypeSpec("str"),
            "approval_run_required": TypeSpec("bool"),
            "writeback_required": TypeSpec("bool"),
            "writeback_target_optional": TypeSpec("str"),
            "permission_decision_state": TypeSpec("str"),
            "governance_decision_state": TypeSpec("str"),
            "semantic_decision_state": TypeSpec("str"),
            "governed_metadata": TypeSpec("object"),
            "execution_trace_id_optional": TypeSpec("str"),
            "vendor_response_ref_optional": TypeSpec("str"),
            "fallback_vendor_id_optional": TypeSpec("str"),
            "requires_manual_review": TypeSpec("bool"),
        },
        "touch_record": {
            "touch_record_id": TypeSpec("str"),
            "opportunity_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "saleability_status": TypeSpec("str"),
            "contact_target_id": TypeSpec("str"),
            "outreach_plan_id": TypeSpec("str"),
            "execution_vendor_id_optional": TypeSpec("str"),
            "execution_vendor_type_optional": TypeSpec("str"),
            "execution_vendor_role_optional": TypeSpec("str"),
            "touch_at": TypeSpec("str"),
            "attempt_index": TypeSpec("int"),
            "touch_record_state": TypeSpec("str"),
            "response_status": TypeSpec("str"),
            "feedback_reason": TypeSpec("str"),
            "next_step_optional": TypeSpec("str"),
            "stop_reason_optional": TypeSpec("str"),
            "touch_channel": TypeSpec("str"),
            "written_back_at_optional": TypeSpec("str"),
            "retry_scheduled_optional": TypeSpec("bool"),
            "failure_reason_tag_optional": TypeSpec("str"),
            "writeback_targets": TypeSpec("list", "str"),
            "writeback_target_optional": TypeSpec("str"),
            "permission_decision_state": TypeSpec("str"),
            "governance_decision_state": TypeSpec("str"),
            "semantic_decision_state": TypeSpec("str"),
            "governed_metadata": TypeSpec("object"),
            "execution_trace_id_optional": TypeSpec("str"),
            "vendor_response_ref_optional": TypeSpec("str"),
        },
        "order_record": {
            "order_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "opportunity_id": TypeSpec("str"),
            "touch_record_id": TypeSpec("str"),
            "response_status": TypeSpec("str"),
            "saleability_status": TypeSpec("str"),
            "crm_owner_state": TypeSpec("str"),
            "commercial_status": TypeSpec("str"),
            "order_status": TypeSpec("str"),
            "approval_state": TypeSpec("str"),
            "archival_status": TypeSpec("str"),
            "amount_band": TypeSpec("str"),
            "plan_status": TypeSpec("str"),
            "touch_record_state": TypeSpec("str"),
            "governed_execution_mode": TypeSpec("str"),
            "permission_decision_state": TypeSpec("str"),
            "governance_decision_state": TypeSpec("str"),
            "semantic_decision_state": TypeSpec("str"),
            "governed_metadata": TypeSpec("object"),
            "created_at": TypeSpec("str"),
        },
        "payment_record": {
            "payment_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "order_id": TypeSpec("str"),
            "payment_status": TypeSpec("str"),
            "payment_proof_state": TypeSpec("str"),
            "payer_match_state": TypeSpec("str"),
            "amount_match_state": TypeSpec("str"),
            "amount_band": TypeSpec("str"),
            "payment_exception_family_optional": TypeSpec("str"),
            "payment_exception_reason_optional": TypeSpec("str"),
            "payment_exception_reason_tags_optional": TypeSpec("list", "str"),
            "amount_mismatch_state_optional": TypeSpec("str"),
            "refund_state": TypeSpec("str"),
            "refund_amount_band_optional": TypeSpec("str"),
            "paid_at_optional": TypeSpec("str"),
            "written_back_at_optional": TypeSpec("str"),
            "governed_execution_mode": TypeSpec("str"),
            "permission_decision_state": TypeSpec("str"),
            "governance_decision_state": TypeSpec("str"),
            "semantic_decision_state": TypeSpec("str"),
            "governed_metadata": TypeSpec("object"),
        },
        "delivery_record": {
            "delivery_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "order_id": TypeSpec("str"),
            "payment_id_optional": TypeSpec("str"),
            "delivery_form": TypeSpec("str"),
            "delivery_status": TypeSpec("str"),
            "delivered_at_optional": TypeSpec("str"),
            "customer_ack_state_optional": TypeSpec("str"),
            "delivery_exception_family_optional": TypeSpec("str"),
            "delivery_exception_reason_optional": TypeSpec("str"),
            "delivery_exception_reason_tags_optional": TypeSpec("list", "str"),
            "partial_delivery_state_optional": TypeSpec("str"),
            "resend_required_optional": TypeSpec("bool"),
            "redeliver_required_optional": TypeSpec("bool"),
            "archival_status": TypeSpec("str"),
            "retention_until": TypeSpec("str"),
            "retrieval_status": TypeSpec("str"),
            "written_back_at_optional": TypeSpec("str"),
            "governed_execution_mode": TypeSpec("str"),
            "permission_decision_state": TypeSpec("str"),
            "governance_decision_state": TypeSpec("str"),
            "semantic_decision_state": TypeSpec("str"),
            "governed_metadata": TypeSpec("object"),
        },
        "opportunity_outcome_event": {
            "outcome_event_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "opportunity_id": TypeSpec("str"),
            "outcome_family": TypeSpec("str"),
            "outcome_reason_tags": TypeSpec("list", "str"),
            "is_false_positive": TypeSpec("bool"),
            "window_missed_state": TypeSpec("str"),
            "contact_failure_state": TypeSpec("str"),
            "payer_mismatch_state": TypeSpec("str"),
            "feedback_reason": TypeSpec("str"),
            "trigger_type": TypeSpec("str"),
            "action_taken": TypeSpec("str"),
            "writeback_targets": TypeSpec("list", "str"),
            "governance_feedback_triggered_optional": TypeSpec("bool"),
            "written_back_at": TypeSpec("str"),
            "written_back_at_optional": TypeSpec("str"),
            "governed_execution_mode": TypeSpec("str"),
            "permission_decision_state": TypeSpec("str"),
            "governance_decision_state": TypeSpec("str"),
            "semantic_decision_state": TypeSpec("str"),
            "governed_metadata": TypeSpec("object"),
        },
        "governance_feedback_event": {
            "governance_feedback_event_id": TypeSpec("str"),
            "project_id": TypeSpec("str"),
            "trigger_type": TypeSpec("str"),
            "trigger_summary": TypeSpec("str"),
            "action_taken": TypeSpec("str"),
            "feedback_reason": TypeSpec("str"),
            "writeback_targets": TypeSpec("list", "str"),
            "written_back_at": TypeSpec("str"),
            "written_back_at_optional": TypeSpec("str"),
            "archive_scope": TypeSpec("str"),
            "governance_feedback_policy_id_optional": TypeSpec("str"),
            "impact_scope_optional": TypeSpec("str"),
            "governed_execution_mode": TypeSpec("str"),
            "permission_decision_state": TypeSpec("str"),
            "governance_decision_state": TypeSpec("str"),
            "semantic_decision_state": TypeSpec("str"),
            "governed_metadata": TypeSpec("object"),
        },
    }

    def __init__(self, repo_root: str | None = None) -> None:
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self.field_policy = self._load_json("contracts/governance/field_policy_dictionary.json")
        self.delivery_matrix = self._load_json("contracts/release/delivery_matrix.json")
        self.release_gates = self._load_json("contracts/release/release_gates.json")
        self.approval_chain_catalog = self._load_json("contracts/governance/approval_chain_catalog.json")
        self.handoff_dependency_order = self._load_json("handoff/dependency_order_matrix.json")
        self.integration_matrix = self._load_json("handoff/integration_matrix.json")
        self.field_policy_index = {
            entry["fieldPath"]: entry for entry in self.field_policy.get("entries", [])
        }
        self.delivery_index = {
            entry["object"]: entry for entry in self.delivery_matrix.get("objects", [])
        }
        self.release_gate_index = {
            entry["releaseGateId"]: entry for entry in self.release_gates.get("gates", [])
        }
        self.stage9_gate_alignment = {
            entry["object"]: entry for entry in self.release_gates.get("stage9_object_gate_alignment", [])
        }
        self.handoff_contract_index = self._build_handoff_contract_index()
        self.integration_index = {
            entry["contractId"]: entry for entry in self.integration_matrix.get("rows", [])
        }

    def _load_json(self, relative_path: str) -> dict[str, Any]:
        path = self.repo_root / relative_path
        return json.loads(path.read_text(encoding="utf-8"))

    def validate_payload(self, object_type: str, schema: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        required_fields = schema.get("required", [])
        missing = [field for field in required_fields if field not in payload or payload[field] in (None, "")]
        if missing:
            raise ValueError(f"{object_type} missing required fields: {', '.join(missing)}")

        self._validate_object_shape(
            object_type=object_type,
            schema=schema,
            payload=payload,
            path=object_type,
        )

        strict_profile = self.STRICT_PROFILES.get(object_type)
        if not strict_profile:
            return

        for field_name, spec in strict_profile.items():
            if field_name not in payload:
                raise ValueError(f"{object_type} missing runtime critical field: {field_name}")
            value = payload[field_name]
            if spec.expected_type == "bool":
                if type(value) is not bool:
                    raise ValueError(f"{object_type}.{field_name} must be bool, got {type(value).__name__}")
            elif spec.expected_type == "int":
                if type(value) is not int:
                    raise ValueError(f"{object_type}.{field_name} must be int, got {type(value).__name__}")
            elif spec.expected_type == "number":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"{object_type}.{field_name} must be number, got {type(value).__name__}")
            elif spec.expected_type == "list":
                if not isinstance(value, list):
                    raise ValueError(f"{object_type}.{field_name} must be list, got {type(value).__name__}")
                if spec.item_type == "str" and any(not isinstance(item, str) for item in value):
                    raise ValueError(f"{object_type}.{field_name} must be list[str]")
            elif spec.expected_type == "object":
                if not isinstance(value, dict):
                    raise ValueError(f"{object_type}.{field_name} must be object, got {type(value).__name__}")
            elif spec.expected_type == "str":
                if not isinstance(value, str):
                    raise ValueError(f"{object_type}.{field_name} must be str, got {type(value).__name__}")

    def _validate_object_shape(
        self,
        *,
        object_type: str,
        schema: Mapping[str, Any],
        payload: Mapping[str, Any],
        path: str,
    ) -> None:
        properties = dict(schema.get("properties", {}))
        additional = schema.get("additionalProperties", True)

        if additional is False:
            extra_fields = [field_name for field_name in payload.keys() if field_name not in properties]
            if extra_fields:
                raise ValueError(f"{object_type} contains undeclared fields: {extra_fields}")

        for field_name, value in payload.items():
            field_schema = properties.get(field_name)
            if field_schema is None:
                if isinstance(additional, Mapping):
                    self._validate_schema_value(field_schema=additional, value=value, path=f"{path}.{field_name}")
                continue
            self._validate_schema_value(field_schema=field_schema, value=value, path=f"{path}.{field_name}")

    def _validate_schema_value(
        self,
        *,
        field_schema: Mapping[str, Any],
        value: Any,
        path: str,
    ) -> None:
        expected_type = field_schema.get("type")
        if isinstance(expected_type, list):
            if any(self._matches_schema_type(schema_type=item, value=value) for item in expected_type):
                pass
            else:
                raise ValueError(f"{path} must match one of {expected_type}, got {type(value).__name__}")
        elif expected_type:
            if not self._matches_schema_type(schema_type=str(expected_type), value=value):
                raise ValueError(f"{path} must be {expected_type}, got {type(value).__name__}")

        if expected_type == "array":
            items_schema = field_schema.get("items", {})
            if items_schema:
                for index, item in enumerate(value):
                    self._validate_schema_value(field_schema=items_schema, value=item, path=f"{path}[{index}]")
        elif expected_type == "object" and isinstance(value, dict):
            nested_properties = dict(field_schema.get("properties", {}))
            nested_additional = field_schema.get("additionalProperties", True)
            if nested_additional is False:
                extra_fields = [field_name for field_name in value.keys() if field_name not in nested_properties]
                if extra_fields:
                    raise ValueError(f"{path} contains undeclared fields: {extra_fields}")
            if nested_properties:
                nested_required = field_schema.get("required", [])
                missing = [field_name for field_name in nested_required if field_name not in value or value[field_name] in (None, "")]
                if missing:
                    raise ValueError(f"{path} missing required fields: {missing}")
                for field_name, nested_value in value.items():
                    nested_schema = nested_properties.get(field_name)
                    if nested_schema is None:
                        if isinstance(nested_additional, Mapping):
                            self._validate_schema_value(
                                field_schema=nested_additional,
                                value=nested_value,
                                path=f"{path}.{field_name}",
                            )
                        continue
                    self._validate_schema_value(
                        field_schema=nested_schema,
                        value=nested_value,
                        path=f"{path}.{field_name}",
                    )

    def _matches_schema_type(self, *, schema_type: str, value: Any) -> bool:
        if schema_type == "string":
            return isinstance(value, str)
        if schema_type == "boolean":
            return type(value) is bool
        if schema_type == "integer":
            return type(value) is int
        if schema_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if schema_type == "array":
            return isinstance(value, list)
        if schema_type == "object":
            return isinstance(value, dict)
        if schema_type == "null":
            return value is None
        return True

    def evaluate_runtime_guards(
        self,
        object_type: str,
        payload: Mapping[str, Any],
        guard_context: Mapping[str, Any],
    ) -> GovernanceGuardResult:
        current_surface = str(guard_context.get("current_surface", "INTERNAL_OPERATIONS"))
        target_surfaces = [str(value) for value in guard_context.get("target_surfaces", [current_surface])]
        release_level = str(guard_context.get("release_level", "INTERNAL_OPERABLE"))
        approval_state = str(guard_context.get("approval_state", "NOT_REQUIRED"))
        action_intent = str(guard_context.get("action_intent", "PREVIEW_ONLY"))
        requested_gate_ids = [str(value) for value in guard_context.get("requested_gate_ids", [])]
        gate_conditions = dict(guard_context.get("gate_conditions", {}))
        reasons: list[str] = []
        decision_state = "ALLOW"

        field_trace, field_additions, field_decision = self._evaluate_field_policy(
            object_type=object_type,
            payload=payload,
            current_surface=current_surface,
            target_surfaces=target_surfaces,
            release_level=release_level,
            approval_state=approval_state,
            action_intent=action_intent,
        )
        decision_state = self._stricter_decision(decision_state, field_decision["decision_state"])
        reasons.extend(field_decision["reasons"])

        delivery_trace, delivery_additions, delivery_decision = self._evaluate_delivery_matrix(
            object_type=object_type,
            current_surface=current_surface,
            target_surfaces=target_surfaces,
            requested_target_surface=guard_context.get("requested_target_surface"),
        )
        decision_state = self._stricter_decision(decision_state, delivery_decision["decision_state"])
        reasons.extend(delivery_decision["reasons"])

        release_trace, release_additions, release_decision = self._evaluate_release_gates(
            object_type=object_type,
            requested_gate_ids=requested_gate_ids,
            release_level=release_level,
            approval_state=approval_state,
            action_intent=action_intent,
            gate_conditions=gate_conditions,
        )
        decision_state = self._stricter_decision(decision_state, release_decision["decision_state"])
        reasons.extend(release_decision["reasons"])

        trace_fields = {
            "event": "governance_guard",
            "object_type": object_type,
            "decision_state": decision_state,
            "current_surface": current_surface,
            "target_surfaces": target_surfaces,
            "release_level": release_level,
            "approval_state": approval_state,
            "action_intent": action_intent,
            "reasons": reasons,
            "field_policy": field_trace,
            "delivery_matrix": delivery_trace,
            "release_gates": release_trace,
        }
        governance_additions = {
            "field_policy": field_additions,
            "delivery_matrix": delivery_additions,
            "release_gates": release_additions,
        }
        return GovernanceGuardResult(
            object_type=object_type,
            decision_state=decision_state,
            reasons=reasons,
            trace_fields=trace_fields,
            governance_additions=governance_additions,
        )

    def evaluate_handoff_consumer(
        self,
        *,
        producer_bundle: Any,
        consumer_stage: int,
    ) -> SemanticValidationResult | None:
        contract_id = self._handoff_contract_id(producer_bundle.stage, consumer_stage)
        if not contract_id:
            return None
        contract = self.handoff_contract_index.get(contract_id, {})
        integration = self.integration_index.get(contract_id, {})
        required_fields = [str(value) for value in contract.get("consumer_runtime_required_fields", contract.get("required_payload_fields", []))]
        critical_objects = [str(value) for value in integration.get("criticalObjects", [])]
        must_not_recompute = [str(value) for value in integration.get("consumerMustNotRecompute", [])]
        reasons: list[str] = []
        decision_state = "ALLOW"

        missing_objects = [name for name in critical_objects if name not in producer_bundle.records]
        if missing_objects:
            decision_state = "BLOCK"
            reasons.append(f"missing critical objects: {missing_objects}")

        missing_fields = [name for name in required_fields if self._resolve_bundle_field(producer_bundle, name) in (None, "")]
        if missing_fields:
            decision_state = self._stricter_decision(decision_state, "BLOCK")
            reasons.append(f"missing required handoff fields: {missing_fields}")

        recompute_conflicts = []
        for field_name in must_not_recompute:
            canonical = self._resolve_bundle_field(producer_bundle, field_name)
            override = producer_bundle.inputs.get(field_name)
            if canonical not in (None, "") and override not in (None, "") and canonical != override:
                recompute_conflicts.append(field_name)
        if recompute_conflicts:
            decision_state = self._stricter_decision(decision_state, "BLOCK")
            reasons.append(f"must-not-recompute conflicts: {recompute_conflicts}")

        trace_fields = {
            "event": "semantic_handoff_validation",
            "semantic_scope": contract_id,
            "producer_stage": producer_bundle.stage,
            "consumer_stage": consumer_stage,
            "decision_state": decision_state,
            "required_fields": required_fields,
            "critical_objects": critical_objects,
            "missing_fields": missing_fields,
            "missing_objects": missing_objects,
            "must_not_recompute": must_not_recompute,
            "recompute_conflicts": recompute_conflicts,
            "reasons": reasons,
        }
        additions = {
            "required_fields": required_fields,
            "critical_objects": critical_objects,
            "missing_fields": missing_fields,
            "missing_objects": missing_objects,
            "must_not_recompute": must_not_recompute,
            "recompute_conflicts": recompute_conflicts,
        }
        return SemanticValidationResult(
            semantic_scope=contract_id,
            decision_state=decision_state,
            reasons=reasons,
            trace_fields=trace_fields,
            semantic_additions=additions,
        )

    def evaluate_object_semantics(
        self,
        *,
        stage: int,
        object_type: str,
        payload: Mapping[str, Any],
        semantic_context: Mapping[str, Any],
    ) -> SemanticValidationResult | None:
        rules = {
            "project_fact": self._semantic_project_fact,
            "report_record": self._semantic_report_record,
            "legal_action_recommendation": self._semantic_legal_action_recommendation,
            "challenger_candidate_profile": self._semantic_challenger_candidate_profile,
            "legal_action_actor_profile": self._semantic_legal_action_actor_profile,
            "procurement_decision_actor_profile": self._semantic_procurement_decision_actor_profile,
            "sales_lead": self._semantic_sales_lead,
            "offer_recommendation": self._semantic_offer_recommendation,
            "saleable_opportunity": self._semantic_saleable_opportunity,
            "contact_target": self._semantic_contact_target,
            "outreach_plan": self._semantic_outreach_plan,
            "touch_record": self._semantic_touch_record,
            "order_record": self._semantic_order_record,
            "payment_record": self._semantic_payment_record,
            "delivery_record": self._semantic_delivery_record,
            "opportunity_outcome_event": self._semantic_opportunity_outcome_event,
            "governance_feedback_event": self._semantic_governance_feedback_event,
        }
        rule = rules.get(object_type)
        if not rule:
            return None
        decision_state, reasons, additions = rule(payload, semantic_context)
        trace_fields = {
            "event": "semantic_object_validation",
            "semantic_scope": f"stage{stage}:{object_type}",
            "stage": stage,
            "object_type": object_type,
            "decision_state": decision_state,
            "reasons": reasons,
            "semantic_context": additions.get("semantic_context_snapshot", {}),
        }
        return SemanticValidationResult(
            semantic_scope=f"stage{stage}:{object_type}",
            decision_state=decision_state,
            reasons=reasons,
            trace_fields=trace_fields,
            semantic_additions=additions,
        )

    def _evaluate_field_policy(
        self,
        *,
        object_type: str,
        payload: Mapping[str, Any],
        current_surface: str,
        target_surfaces: list[str],
        release_level: str,
        approval_state: str,
        action_intent: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        reasons: list[str] = []
        decision_state = "ALLOW"
        blocked_fields: list[str] = []
        review_fields: list[str] = []
        projected_fields: dict[str, list[dict[str, str]]] = {}

        for field_name, value in payload.items():
            entry = self._field_policy_entry(object_type, field_name)
            if not entry:
                continue
            field_path = str(entry["fieldPath"])
            allowed_surfaces = [str(item) for item in entry.get("allowedSurfaces", [])]
            if current_surface not in allowed_surfaces:
                decision_state = self._stricter_decision(decision_state, "BLOCK")
                blocked_fields.append(field_path)
                reasons.append(f"{field_path} blocked on {current_surface}")
                continue

            if self._is_high_restriction(entry, value):
                if approval_state != "APPROVED":
                    next_decision = "BLOCK" if action_intent in ("APPROVAL_EXECUTION", "LIVE_EXECUTION") else "REVIEW"
                    decision_state = self._stricter_decision(decision_state, next_decision)
                    review_fields.append(field_path)
                    reasons.append(f"{field_path} requires restricted approval")

            if bool(entry.get("reviewRequired")) and approval_state not in ("APPROVED", "NOT_REQUIRED"):
                decision_state = self._stricter_decision(decision_state, "REVIEW")
                review_fields.append(field_path)
                reasons.append(f"{field_path} review required")

            for surface in target_surfaces:
                if surface == current_surface:
                    continue
                if surface not in allowed_surfaces:
                    blocked_fields.append(f"{field_path}@{surface}")
                    continue
                mask_rule = str(entry.get("maskRule", "NONE"))
                if mask_rule != "NONE":
                    projected_fields.setdefault(surface, []).append(
                        {
                            "field": field_path,
                            "mask_rule": mask_rule,
                        }
                    )

        trace = {
            "blocked_fields": blocked_fields,
            "review_fields": review_fields,
            "projected_fields": projected_fields,
        }
        additions = {
            "blocked_fields": blocked_fields,
            "review_fields": review_fields,
            "projected_fields": projected_fields,
        }
        return trace, additions, {"decision_state": decision_state, "reasons": reasons}

    def _evaluate_delivery_matrix(
        self,
        *,
        object_type: str,
        current_surface: str,
        target_surfaces: list[str],
        requested_target_surface: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        row = self.delivery_index.get(object_type)
        if not row:
            return {}, {}, {"decision_state": "ALLOW", "reasons": []}

        reasons: list[str] = []
        decision_state = "ALLOW"
        surface_policy = dict(row.get("surface_policy", {}))
        current_policy = str(surface_policy.get(current_surface, "BLOCK"))
        if current_policy == "BLOCK":
            decision_state = "BLOCK"
            reasons.append(f"{object_type} blocked on {current_surface} by delivery matrix")

        projection_policies = {
            surface: str(surface_policy.get(surface, "BLOCK"))
            for surface in target_surfaces
        }
        if requested_target_surface:
            requested_policy = str(surface_policy.get(str(requested_target_surface), "BLOCK"))
            if requested_policy == "BLOCK":
                decision_state = self._stricter_decision(decision_state, "BLOCK")
                reasons.append(f"{object_type} blocked on requested surface {requested_target_surface}")

        stage9_policy = dict(row.get("stage9Policy", {}))
        trace = {
            "current_policy": current_policy,
            "projection_policies": projection_policies,
            "stage9_policy": stage9_policy,
        }
        additions = {
            "current_policy": current_policy,
            "projection_policies": projection_policies,
            "stage9_policy": stage9_policy,
        }
        return trace, additions, {"decision_state": decision_state, "reasons": reasons}

    def _evaluate_release_gates(
        self,
        *,
        object_type: str,
        requested_gate_ids: list[str],
        release_level: str,
        approval_state: str,
        action_intent: str,
        gate_conditions: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        reasons: list[str] = []
        decision_state = "ALLOW"
        gate_results: list[dict[str, Any]] = []

        for gate_id in requested_gate_ids:
            gate = self.release_gate_index.get(gate_id)
            if not gate:
                continue
            gate_decision = "ALLOW"
            minimum_level = str(gate.get("minimumReleaseLevel", "DEV_ALLOWED"))
            if minimum_level == "EXTERNAL_CONTROLLED_OPENING":
                gate_decision = "BLOCK"
                reasons.append(f"{gate_id} is externally blocked")
            elif not self._release_level_allows(release_level, minimum_level):
                gate_decision = "REVIEW"
                reasons.append(f"{gate_id} requires {minimum_level}")

            if bool(gate.get("blockedByDefault")):
                gate_decision = "BLOCK"
                reasons.append(f"{gate_id} controlled opening required")

            if gate_id == "high_restriction_contact_release" and approval_state != "APPROVED":
                gate_decision = self._stricter_decision(gate_decision, "REVIEW" if action_intent != "LIVE_EXECUTION" else "BLOCK")
                reasons.append(f"{gate_id} approval missing")

            gate_results.append(
                {
                    "gate_id": gate_id,
                    "decision_state": gate_decision,
                    "minimum_release_level": minimum_level,
                }
            )
            decision_state = self._stricter_decision(decision_state, gate_decision)

        stage9_alignment = self.stage9_gate_alignment.get(object_type)
        if stage9_alignment:
            missing_conditions = [
                condition for condition in stage9_alignment.get("requiredConditions", [])
                if not bool(gate_conditions.get(condition, False))
            ]
            if missing_conditions:
                decision_state = self._stricter_decision(decision_state, "BLOCK")
                reasons.append(f"{object_type} gate conditions missing: {missing_conditions}")
            gate_results.append(
                {
                    "stage9_action": stage9_alignment.get("action"),
                    "missing_conditions": missing_conditions,
                    "allowed_gates": stage9_alignment.get("allowedGates", []),
                    "blocked_gates": stage9_alignment.get("blockedGates", []),
                }
            )

        trace = {"gate_results": gate_results}
        additions = {"gate_results": gate_results}
        return trace, additions, {"decision_state": decision_state, "reasons": reasons}

    def _field_policy_entry(self, object_type: str, field_name: str) -> Mapping[str, Any] | None:
        field_path = f"{object_type}.{field_name}"
        if field_path in self.field_policy_index:
            return self.field_policy_index[field_path]
        for alias in self.FIELD_POLICY_ALIASES.get(field_path, ()):
            if alias in self.field_policy_index:
                return self.field_policy_index[alias]
        return None

    def _is_high_restriction(self, entry: Mapping[str, Any], value: Any) -> bool:
        if str(entry.get("fieldClass")) != "NATURAL_PERSON_HIGH_RESTRICTION":
            return False
        return self._is_meaningful_value(value)

    def _is_meaningful_value(self, value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str) and value.upper() in {"UNKNOWN", "UNASSIGNED", "NOT_PROVIDED", "NOT_PAID", "NOT_DELIVERED", "NONE", "N/A"}:
            return False
        return True

    def _stricter_decision(self, left: str, right: str) -> str:
        order = {"ALLOW": 0, "FALLBACK": 1, "REVIEW": 2, "BLOCK": 3}
        return left if order.get(left, 0) >= order.get(right, 0) else right

    def _release_level_allows(self, current_level: str, minimum_level: str) -> bool:
        if minimum_level == "EXTERNAL_CONTROLLED_OPENING":
            return current_level == "EXTERNAL_CONTROLLED_OPENING"
        if current_level == "EXTERNAL_CONTROLLED_OPENING":
            return False
        return self.RELEASE_LEVEL_RANK.get(current_level, -1) >= self.RELEASE_LEVEL_RANK.get(minimum_level, -1)

    def _build_handoff_contract_index(self) -> dict[str, Mapping[str, Any]]:
        index: dict[str, Mapping[str, Any]] = {}
        for item in self.handoff_dependency_order.get("sequence", []):
            contract_path = self.repo_root / str(item["path"]) / "contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            index[str(contract["handoff_id"])] = contract
        return index

    def _handoff_contract_id(self, producer_stage: int, consumer_stage: int) -> str | None:
        for row in self.integration_matrix.get("rows", []):
            if int(row["producerStage"]) == producer_stage and int(row["consumerStage"]) == consumer_stage:
                return str(row["contractId"])
        return None

    def _resolve_bundle_field(self, bundle: Any, field_name: str) -> Any:
        if field_name in getattr(bundle, "handoff", {}):
            return bundle.handoff[field_name]
        if field_name in getattr(bundle, "inputs", {}):
            return bundle.inputs[field_name]
        for record in getattr(bundle, "records", {}).values():
            value = record.get(field_name)
            if value not in (None, ""):
                return value
        return None

    def _semantic_project_fact(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if payload.get("sale_gate_status") == "OPEN" and not (
            payload.get("rule_gate_status") == "PASS" and payload.get("evidence_gate_status") == "PASS"
        ):
            decision = "BLOCK"
            reasons.append("sale_gate_status=OPEN requires both gates PASS")
        if payload.get("sale_gate_status") == "HOLD" and context.get("report_status") == "ISSUED":
            decision = "REVIEW"
            reasons.append("sale_gate_status=HOLD should clear once report_status=ISSUED")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_report_record(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if payload.get("report_status") == "ISSUED":
            if context.get("rule_gate_status") != "PASS" or context.get("evidence_gate_status") != "PASS":
                decision = "BLOCK"
                reasons.append("ISSUED report requires both gates PASS")
            if payload.get("review_task_status") != "CLOSED":
                decision = "BLOCK"
                reasons.append("ISSUED report requires review_task_status=CLOSED")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_legal_action_recommendation(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if payload.get("action_family") == "OBJECTION_PREP" and context.get("sale_gate_status") != "OPEN":
            decision = "REVIEW"
            reasons.append("OBJECTION_PREP requires sale_gate_status=OPEN")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_challenger_candidate_profile(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if context.get("sale_gate_status") == "BLOCK" and payload.get("challenge_actionability_score", 0) > 0:
            decision = "REVIEW"
            reasons.append("blocked sale gate keeps challenger profile in review-only state")
        if context.get("real_competitor_count", 0) <= 0 and payload.get("challenge_actionability_score", 0) >= 55:
            decision = "REVIEW"
            reasons.append("challenge profile cannot stay actionable when real_competitor_count=0")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_legal_action_actor_profile(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if payload.get("actionability_state") == "ACTIONABLE" and context.get("saleability_status") == "BLOCKED":
            decision = "BLOCK"
            reasons.append("blocked opportunity cannot keep actionable legal actor")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_procurement_decision_actor_profile(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if payload.get("payment_authority_state") == "FULL_AUTHORITY" and context.get("saleability_status") == "BLOCKED":
            decision = "BLOCK"
            reasons.append("blocked opportunity cannot keep full payment authority")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_sales_lead(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if payload.get("lead_status") == "QUALIFIED":
            if context.get("sale_gate_status") != "OPEN":
                decision = "BLOCK"
                reasons.append("QUALIFIED lead requires sale_gate_status=OPEN")
            if context.get("report_status") != "ISSUED":
                decision = "BLOCK"
                reasons.append("QUALIFIED lead requires report_status=ISSUED")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_offer_recommendation(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if payload.get("offer_recommendation_state") == "APPROVED":
            if context.get("saleability_status") == "BLOCKED":
                decision = "BLOCK"
                reasons.append("APPROVED offer cannot exist on blocked opportunity")
            if context.get("report_status") != "ISSUED" and decision != "BLOCK":
                decision = "REVIEW"
                reasons.append("APPROVED offer requires issued report")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_saleable_opportunity(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        reasons: list[str] = []
        decision = "ALLOW"
        if not context.get("project_fact_present") or not context.get("challenger_profile_present"):
            decision = "BLOCK"
            reasons.append("saleable_opportunity requires stage6 project_fact + challenger profile")
        if payload.get("saleability_status") == "QUALIFIED":
            if context.get("sale_gate_status") != "OPEN" or context.get("report_status") != "ISSUED":
                decision = "BLOCK"
                reasons.append("QUALIFIED opportunity requires sale_gate_status=OPEN and report_status=ISSUED")
        return decision, reasons, {"semantic_context_snapshot": context}

    def _semantic_contact_target(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_contact_target_rule(payload, context)

    def _semantic_outreach_plan(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_outreach_plan_rule(payload, context)

    def _semantic_touch_record(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_touch_record_rule(payload, context)

    def _semantic_order_record(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_order_record_rule(payload, context)

    def _semantic_payment_record(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_payment_record_rule(payload, context)

    def _semantic_delivery_record(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_delivery_record_rule(payload, context)

    def _semantic_opportunity_outcome_event(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_opportunity_outcome_event_rule(payload, context)

    def _semantic_governance_feedback_event(self, payload: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return _semantic_governance_feedback_event_rule(payload, context)


__all__ = ["RuntimeValidator", "TypeSpec"]
