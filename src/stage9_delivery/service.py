# Stage: stage9_delivery
# Consumes formal objects: saleable_opportunity, touch_record, order_record, payment_record, delivery_record, governance_feedback_event, opportunity_outcome_event
# Dependent handoff: H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/release/delivery_matrix.json, contracts/release/release_gates.json, contracts/governance/field_policy_dictionary.json

from __future__ import annotations

from typing import Any, Mapping

from stage9_delivery.impact_executor import ImpactExecutor
from shared.capability_runtime import CapabilityRuntime
from shared.contract_loader import load_contract
from shared.context_packet import ContextPacket
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import build_id, ensure_enum, ensure_list, resolve_bundle, utc_now_iso


class Stage9Service:
    POLICY_SEQUENCE = (
        "payment_exception",
        "delivery_exception",
        "outcome_taxonomy",
        "governance_taxonomy",
    )
    H08_OPTIONAL_FIELDS = (
        "plan_status",
        "touch_record_state",
        "feedback_reason",
        "written_back_at_optional",
        "governance_decision_state",
        "permission_decision_state",
        "semantic_decision_state",
    )
    REQUIRED_H08_FIELDS = (
        "opportunity_id",
        "touch_record_id",
        "response_status",
        "saleability_status",
        "crm_owner_state",
    )
    CONTACT_FAILURE_RESPONSES = {
        "NO_RESPONSE",
        "INVALID_CONTACT",
        "OPTED_OUT",
        "WRONG_ROLE",
    }
    DECISION_ORDER = {"ALLOW": 0, "REVIEW": 1, "BLOCK": 2}

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)
        self.runtime = CapabilityRuntime(settings)
        self.impact_executor = ImpactExecutor(settings)

    def _guard_context(
        self,
        *,
        inputs: Mapping[str, Any],
        release_level: str,
        approval_state: str,
        action_intent: str,
        requested_gate_ids: list[str],
        gate_conditions: Mapping[str, Any],
    ) -> dict[str, Any]:
        requested_target_surface = inputs.get("requested_delivery_surface")
        target_surfaces = ["INTERNAL_OPERATIONS", "SALES_CONSUMABLE", "LEADPACK_DELIVERABLE"]
        if requested_target_surface and requested_target_surface not in target_surfaces:
            target_surfaces.append(str(requested_target_surface))
        return {
            "current_surface": "INTERNAL_OPERATIONS",
            "target_surfaces": target_surfaces,
            "requested_target_surface": requested_target_surface,
            "release_level": release_level,
            "approval_state": approval_state,
            "action_intent": action_intent,
            "requested_gate_ids": requested_gate_ids,
            "gate_conditions": dict(gate_conditions),
        }

    def _stricter_decision(self, *states: str | None) -> str:
        effective = "ALLOW"
        for state in states:
            token = str(state or "ALLOW")
            if self.DECISION_ORDER.get(token, 0) > self.DECISION_ORDER.get(effective, 0):
                effective = token
        return effective

    def _stage9_governed_metadata(
        self,
        *,
        plan_status: str,
        touch_record_state: str,
        feedback_reason: str,
        written_back_at_optional: str | None,
        upstream_governance_decision_state: str,
        outcome_writeback_targets: list[str],
        outcome_authoritative_base_targets: list[str],
        governance_writeback_targets: list[str],
        governance_legacy_writeback_targets: list[str],
        governance_owned_self_target: str,
        payment_exception_writeback_targets: list[str],
        delivery_exception_writeback_targets: list[str],
        effective_writeback_targets: list[str],
        writeback_contract: Mapping[str, Any],
        writeback_source_contracts: Mapping[str, Any],
        writeback_target_sources: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "skeleton_only": True,
            "live_execution_enabled": False,
            "projection_only": True,
            "governed_execution_mode": "INTERNAL_GOVERNED",
            "source_handoff_id": "H-08-STAGE8-TO-STAGE9",
            "upstream_plan_status": plan_status,
            "upstream_touch_record_state": touch_record_state,
            "upstream_feedback_reason": feedback_reason,
            "upstream_written_back_at_optional": written_back_at_optional,
            "upstream_governance_decision_state": upstream_governance_decision_state,
            "outcome_writeback_targets": list(outcome_writeback_targets),
            "outcome_authoritative_base_targets": list(outcome_authoritative_base_targets),
            "governance_writeback_targets_optional": list(governance_writeback_targets),
            "governance_legacy_writeback_targets": list(governance_legacy_writeback_targets),
            "governance_owned_self_target": governance_owned_self_target,
            "payment_exception_writeback_targets_optional": list(payment_exception_writeback_targets),
            "delivery_exception_writeback_targets_optional": list(delivery_exception_writeback_targets),
            "effective_writeback_targets": list(effective_writeback_targets),
            "writeback_contract_state": writeback_contract.get("writeback_contract_state", "UNKNOWN"),
            "writeback_projected_targets": list(writeback_contract.get("writeback_projected_targets", [])),
            "writeback_persistence_targets": list(writeback_contract.get("writeback_persistence_targets", [])),
            "writeback_advisory_targets": list(writeback_contract.get("writeback_advisory_targets", [])),
            "writeback_trace_only_targets": list(writeback_contract.get("writeback_trace_only_targets", [])),
            "writeback_source_contracts": dict(writeback_source_contracts),
            "writeback_target_sources": dict(writeback_target_sources),
        }

    def _outcome_feedback_policy(self) -> dict[str, Any]:
        catalog = load_contract("contracts/sales/opportunity_policy_catalog.json", self.settings)
        for policy in catalog.get("policies", []):
            if policy.get("policyId") == "opportunity_outcome_writeback_v1":
                return dict(policy)
        raise ValueError("Stage9 requires contracts/sales/opportunity_policy_catalog.json#opportunity_outcome_writeback_v1")

    def _resolve_upstream_feedback_contract(
        self,
        *,
        outcome_family: str,
        projected_feedback_only_targets: list[str],
        advisory_targets: list[str],
        feedback_loop_contract_ref: str | None,
    ) -> dict[str, Any]:
        policy = self._outcome_feedback_policy()
        outcome_key = str(outcome_family or "").lower()
        required_outcomes = {str(item).lower() for item in policy.get("requiredOutcomes", [])}
        if not (projected_feedback_only_targets or advisory_targets):
            return {
                "upstream_feedback_projected_targets": [],
                "upstream_feedback_advisory_targets": [],
                "upstream_feedback_contracts": {},
            }
        if outcome_key not in required_outcomes:
            raise ValueError(
                f"Stage9 upstream feedback loop outcome not declared: outcome_family={outcome_family}"
            )

        contract = dict(policy.get("upstreamFeedbackLoopContracts", {}).get(outcome_key, {}))
        if not contract:
            raise ValueError(
                f"Stage9 upstream feedback loop contract missing for outcome_family={outcome_family}"
            )
        projected_contracts = dict(contract.get("projectedOnlyTargets", {}))
        advisory_contracts = dict(contract.get("advisoryTargets", {}))
        missing_projected_targets = [
            target for target in projected_feedback_only_targets if target not in projected_contracts
        ]
        missing_advisory_targets = [
            target for target in advisory_targets if target not in advisory_contracts
        ]
        if missing_projected_targets or missing_advisory_targets:
            raise ValueError(
                "Stage9 upstream feedback loop target contract mismatch: "
                f"missing_projected={missing_projected_targets}; "
                f"missing_advisory={missing_advisory_targets}"
            )
        return {
            "upstream_feedback_projected_targets": list(projected_feedback_only_targets),
            "upstream_feedback_advisory_targets": list(advisory_targets),
            "upstream_feedback_contracts": {
                "outcome_family": outcome_key,
                "feedback_loop_contract_ref": feedback_loop_contract_ref,
                "projectedOnlyTargets": {
                    target: projected_contracts[target] for target in projected_feedback_only_targets
                },
                "advisoryTargets": {
                    target: advisory_contracts[target] for target in advisory_targets
                },
                "mustWriteBackTo": [
                    target
                    for target in policy.get("mustWriteBackTo", [])
                    if target in projected_feedback_only_targets
                ],
                "mustAdvisoryWriteBackTo": [
                    target
                    for target in policy.get("mustAdvisoryWriteBackTo", [])
                    if target in advisory_targets
                ],
            },
        }

    def _match_state_from_mismatch(self, mismatch_state: str | None) -> str:
        if mismatch_state in (None, "", "NO_MISMATCH"):
            return "MATCHED"
        if mismatch_state == "CONFIRMED":
            return "MISMATCHED"
        return "REVIEW_REQUIRED"

    def _require_h08_payload(
        self,
        stage8_bundle: StageBundle,
        inputs: Mapping[str, Any],
        touch_record: Mapping[str, Any],
        saleable_opportunity: Mapping[str, Any],
        outreach_plan: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(stage8_bundle.handoff or {})
        missing_fields = [
            field_name for field_name in self.REQUIRED_H08_FIELDS if payload.get(field_name) in (None, "")
        ]
        if missing_fields:
            raise ValueError(f"Stage9 requires complete H-08 payload fields: {missing_fields}")

        for field_name in self.REQUIRED_H08_FIELDS:
            input_value = inputs.get(field_name)
            if input_value not in (None, "") and input_value != payload[field_name]:
                raise ValueError(f"Stage9 detected H-08 drift for field: {field_name}")

        expected_projection = {
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "touch_record_id": touch_record.get("touch_record_id"),
            "response_status": touch_record.get("response_status"),
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "crm_owner_state": saleable_opportunity.get("crm_owner_state"),
        }
        drift_fields = [
            field_name
            for field_name, expected_value in expected_projection.items()
            if payload.get(field_name) != expected_value
        ]
        if drift_fields:
            raise ValueError(f"Stage9 detected H-08 projection drift: {drift_fields}")

        optional_projection = {
            "plan_status": outreach_plan.get("plan_status") if outreach_plan else None,
            "touch_record_state": touch_record.get("touch_record_state"),
            "feedback_reason": touch_record.get("feedback_reason"),
            "written_back_at_optional": touch_record.get("written_back_at_optional"),
            "governance_decision_state": touch_record.get("governance_decision_state"),
            "permission_decision_state": touch_record.get("permission_decision_state"),
            "semantic_decision_state": touch_record.get("semantic_decision_state"),
        }
        for field_name in self.H08_OPTIONAL_FIELDS:
            input_value = inputs.get(field_name)
            payload_value = payload.get(field_name)
            if input_value not in (None, "") and payload_value not in (None, "") and input_value != payload_value:
                raise ValueError(f"Stage9 detected H-08 optional drift for field: {field_name}")
            expected_value = optional_projection.get(field_name)
            if payload_value not in (None, "") and expected_value not in (None, "") and payload_value != expected_value:
                raise ValueError(f"Stage9 detected H-08 optional projection drift: {field_name}")

        return payload

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage8_bundle = resolve_bundle(payload)
        handoff_validation = self.store.evaluate_handoff_consumer(
            producer_bundle=stage8_bundle,
            consumer_stage=9,
        )
        if handoff_validation and handoff_validation.decision_state == "BLOCK":
            raise ValueError(f"{handoff_validation.semantic_scope} blocked: {handoff_validation.reasons}")
        inputs = stage8_bundle.inputs or {}
        now = inputs.get("now") or utc_now_iso()

        try:
            touch_record = stage8_bundle.record("touch_record")
        except KeyError as exc:
            raise ValueError("Stage9 requires Stage8 record: touch_record") from exc
        try:
            saleable_opportunity = stage8_bundle.record("saleable_opportunity")
        except KeyError as exc:
            raise ValueError("Stage9 requires Stage8 record: saleable_opportunity") from exc
        outreach_plan = stage8_bundle.records.get("outreach_plan")
        h08_payload = self._require_h08_payload(
            stage8_bundle=stage8_bundle,
            inputs=inputs,
            touch_record=touch_record,
            saleable_opportunity=saleable_opportunity,
            outreach_plan=outreach_plan,
        )
        project_id = touch_record.get("project_id")
        response_status = h08_payload["response_status"]
        saleability_status = h08_payload["saleability_status"]
        crm_owner_state = h08_payload["crm_owner_state"]
        plan_status = h08_payload.get("plan_status", inputs.get("plan_status", "DRAFT"))
        touch_record_state = h08_payload.get("touch_record_state", inputs.get("touch_record_state", "CREATED"))
        feedback_reason = h08_payload.get("feedback_reason", inputs.get("feedback_reason", response_status))
        written_back_at_optional = h08_payload.get(
            "written_back_at_optional",
            inputs.get("written_back_at_optional"),
        )
        upstream_governance_decision_state = h08_payload.get(
            "governance_decision_state",
            inputs.get("governance_decision_state", "ALLOW"),
        )
        upstream_permission_decision_state = h08_payload.get(
            "permission_decision_state",
            inputs.get("permission_decision_state", "ALLOW"),
        )
        upstream_semantic_decision_state = h08_payload.get(
            "semantic_decision_state",
            inputs.get("semantic_decision_state", "ALLOW"),
        )
        contact_failure = response_status in self.CONTACT_FAILURE_RESPONSES
        release_level = inputs.get("release_level", inputs.get("minimum_release_level", "INTERNAL_OPERABLE"))
        approval_state = inputs.get("approval_state", "NOT_REQUIRED")
        governed_execution_mode = str(inputs.get("governed_execution_mode", "INTERNAL_GOVERNED"))

        commercial_status_default = "DRAFT"
        order_status_default = "DRAFT"
        if (
            saleability_status == "BLOCKED"
            or upstream_governance_decision_state == "BLOCK"
            or plan_status in ("BLOCKED", "CANCELLED", "REJECTED")
            or touch_record_state == "CANCELLED"
        ):
            commercial_status_default = "ON_HOLD"
            order_status_default = "ON_HOLD"
        elif crm_owner_state == "UNASSIGNED":
            commercial_status_default = "PENDING_APPROVAL"
            order_status_default = "PENDING_APPROVAL"
        elif crm_owner_state in ("ON_HOLD", "CLOSED") or contact_failure:
            commercial_status_default = "ON_HOLD"
            order_status_default = "ON_HOLD"
        elif (
            upstream_governance_decision_state == "REVIEW"
            or plan_status in ("DRAFT", "REVIEW_REQUIRED", "APPROVAL_PENDING", "SCHEDULED")
        ):
            commercial_status_default = "PENDING_APPROVAL"
            order_status_default = "PENDING_APPROVAL"

        delivery_status_default = (
            "RELEASE_BLOCKED"
            if saleability_status == "BLOCKED"
            or contact_failure
            or upstream_governance_decision_state == "BLOCK"
            or plan_status in ("BLOCKED", "CANCELLED", "REJECTED")
            or touch_record_state == "CANCELLED"
            else "NOT_READY"
        )
        trigger_type_default = (
            "EVIDENCE_INSUFFICIENT"
            if saleability_status == "BLOCKED"
            else "DELIVERY_BLOCK"
            if upstream_governance_decision_state == "BLOCK"
            else "APPROVAL_MISSING"
            if plan_status in ("DRAFT", "REVIEW_REQUIRED", "APPROVAL_PENDING")
            else "APPROVAL_MISSING"
            if crm_owner_state in ("UNASSIGNED", "ON_HOLD", "CLOSED")
            else "OTHER"
        )
        outcome_family_default = (
            "CONTACT_FAILED"
            if contact_failure
            else "LOST"
            if saleability_status == "BLOCKED"
            else "WON"
        )
        outcome_reason_tags_default = (
            [feedback_reason]
            if contact_failure
            else ["COMPETITOR_WON"]
            if saleability_status == "BLOCKED"
            else ["SIGNED"]
        )
        runtime_inputs = {
            **dict(inputs),
            **h08_payload,
            "now": now,
            "release_level": release_level,
            "approval_state": approval_state,
            "governed_execution_mode": governed_execution_mode,
            "plan_status": plan_status,
            "touch_record_state": touch_record_state,
            "feedback_reason": feedback_reason,
            "written_back_at_optional": written_back_at_optional,
            "governance_decision_state": upstream_governance_decision_state,
            "permission_decision_state": upstream_permission_decision_state,
            "semantic_decision_state": upstream_semantic_decision_state,
            "trigger_type": inputs.get("trigger_type", trigger_type_default),
            "trigger_summary": inputs.get(
                "trigger_summary",
                (
                    f"H08 opportunity_id={h08_payload['opportunity_id']}; "
                    f"touch_record_id={h08_payload['touch_record_id']}; "
                    f"response_status={response_status}; "
                    f"saleability_status={saleability_status}; "
                    f"crm_owner_state={crm_owner_state}; "
                    f"plan_status={plan_status}; "
                    f"touch_record_state={touch_record_state}; "
                    f"feedback_reason={feedback_reason}; "
                    f"governance_decision_state={upstream_governance_decision_state}"
                ),
            ),
            "outcome_family": inputs.get("outcome_family", outcome_family_default),
            "outcome_reason_tags": inputs.get("outcome_reason_tags", outcome_reason_tags_default),
            "contact_failure_state": inputs.get(
                "contact_failure_state",
                response_status if contact_failure else "OTHER",
            ),
            "window_missed_state": inputs.get("window_missed_state", "NOT_MISSED"),
            "payer_mismatch_state": inputs.get("payer_mismatch_state", "NO_MISMATCH"),
            "commercial_status": inputs.get("commercial_status", commercial_status_default),
            "order_status": inputs.get("order_status", order_status_default),
            "delivery_status": inputs.get("delivery_status", delivery_status_default),
            "amount_band": inputs.get(
                "amount_band",
                saleable_opportunity.get("expected_contract_value_band", "UNKNOWN"),
            ),
        }

        runtime_context = ContextPacket.from_records(
            capability_mode="stage9_delivery",
            stage=9,
            project_id=project_id,
            records={
                "touch_record": touch_record,
                "saleable_opportunity": saleable_opportunity,
            },
            inputs=runtime_inputs,
        )
        permission_checks = [
            {
                "capability_family": "stage9_execution",
                "requested_action": "INTERNAL_WRITEBACK",
                "release_level": release_level,
                "approval_state": approval_state,
                "metadata": {
                    "policy_state": "INTERNAL_GOVERNED",
                },
            }
        ]
        if inputs.get("model_provider_id_optional"):
            permission_checks.append(
                {
                    "capability_family": "model_provider",
                    "requested_action": "PREVIEW_ONLY",
                    "target_id": inputs.get("model_provider_id_optional"),
                    "target_type": "model_provider",
                    "target_role": inputs.get("model_provider_role_optional", "GENERAL_ASSIST_MODEL"),
                    "release_level": release_level,
                    "approval_state": approval_state,
                }
            )
        if inputs.get("tool_provider_id_optional"):
            permission_checks.append(
                {
                    "capability_family": "tool_provider",
                    "requested_action": "PREVIEW_ONLY",
                    "target_id": inputs.get("tool_provider_id_optional"),
                    "target_type": "tool_provider",
                    "target_role": inputs.get("tool_provider_role_optional", "INTERNAL_OBJECT_QUERY_TOOL"),
                    "release_level": release_level,
                    "approval_state": approval_state,
                }
            )
        permission_state = self.runtime.resolve_permissions(runtime_context, permission_checks)
        runtime_state = permission_state if permission_state.permission_short_circuit else self.runtime.run(runtime_context, state=permission_state)
        if runtime_state.permission_blocked_reasons:
            runtime_inputs["commercial_status"] = "ON_HOLD"
            runtime_inputs["order_status"] = "ON_HOLD"
            runtime_inputs["delivery_status"] = "RELEASE_BLOCKED"
            runtime_inputs["trigger_type"] = "OTHER"
            runtime_inputs["trigger_summary"] = (
                f"Stage9 runtime permission blocked: {'; '.join(runtime_state.permission_blocked_reasons)}; "
                f"opportunity_id={h08_payload['opportunity_id']}; touch_record_id={h08_payload['touch_record_id']}"
            )

        outcome_taxonomy_output = runtime_state.outputs.get("outcome_taxonomy", {})
        outcome_writeback_targets = ensure_list(
            runtime_state.outputs.get("outcome_taxonomy", {}).get("writeback_targets", ["project_fact"])
        )
        outcome_authoritative_base_targets = ensure_list(
            outcome_taxonomy_output.get("authoritative_base_targets", outcome_writeback_targets)
        )
        resolved_outcome_family = str(
            runtime_state.resolve("outcome_family", runtime_inputs["outcome_family"])
        )
        upstream_feedback_contract = self._resolve_upstream_feedback_contract(
            outcome_family=resolved_outcome_family,
            projected_feedback_only_targets=ensure_list(
                outcome_taxonomy_output.get("projected_feedback_only_targets", [])
            ),
            advisory_targets=ensure_list(outcome_taxonomy_output.get("advisory_targets", [])),
            feedback_loop_contract_ref=outcome_taxonomy_output.get("feedback_loop_contract_ref"),
        )
        upstream_feedback_projected_targets = ensure_list(
            upstream_feedback_contract.get("upstream_feedback_projected_targets", [])
        )
        upstream_feedback_advisory_targets = ensure_list(
            upstream_feedback_contract.get("upstream_feedback_advisory_targets", [])
        )
        governance_taxonomy_output = runtime_state.outputs.get("governance_taxonomy", {})
        governance_writeback_targets = ensure_list(
            runtime_state.outputs.get("governance_taxonomy", {}).get(
                "additive_writeback_targets",
                runtime_state.outputs.get("governance_taxonomy", {}).get("writeback_targets", []),
            )
        )
        governance_legacy_writeback_targets = ensure_list(
            governance_taxonomy_output.get("writeback_targets", governance_writeback_targets)
        )
        governance_owned_self_target = str(
            governance_taxonomy_output.get(
                "governance_owned_self_target",
                "governance_feedback_event",
            )
        )
        payment_exception_writeback_targets = ensure_list(
            runtime_state.resolve("payment_exception_writeback_targets_optional", [])
        )
        delivery_exception_writeback_targets = ensure_list(
            runtime_state.resolve("delivery_exception_writeback_targets_optional", [])
        )
        effective_writeback_targets = list(outcome_writeback_targets)
        for target in (
            governance_writeback_targets
            + payment_exception_writeback_targets
            + delivery_exception_writeback_targets
        ):
            if target not in effective_writeback_targets:
                effective_writeback_targets.append(target)
        writeback_target_resolution = self.impact_executor.resolve_effective_targets(
            outcome_targets=outcome_authoritative_base_targets,
            upstream_feedback_targets=(
                upstream_feedback_projected_targets + upstream_feedback_advisory_targets
            ),
            governance_targets=governance_writeback_targets,
            payment_exception_targets=payment_exception_writeback_targets,
            delivery_exception_targets=delivery_exception_writeback_targets,
            governance_self_target=governance_owned_self_target,
        )
        resolved_effective_writeback_targets = list(
            writeback_target_resolution["effective_writeback_targets"]
        )
        writeback_contract = self.impact_executor.describe_targets(
            resolved_effective_writeback_targets,
            target_sources=writeback_target_resolution["writeback_target_sources"],
        )

        governed_metadata = self._stage9_governed_metadata(
            plan_status=plan_status,
            touch_record_state=touch_record_state,
            feedback_reason=feedback_reason,
            written_back_at_optional=written_back_at_optional,
            upstream_governance_decision_state=upstream_governance_decision_state,
            outcome_writeback_targets=outcome_writeback_targets,
            outcome_authoritative_base_targets=outcome_authoritative_base_targets,
            governance_writeback_targets=governance_writeback_targets,
            governance_legacy_writeback_targets=governance_legacy_writeback_targets,
            governance_owned_self_target=governance_owned_self_target,
            payment_exception_writeback_targets=payment_exception_writeback_targets,
            delivery_exception_writeback_targets=delivery_exception_writeback_targets,
            effective_writeback_targets=effective_writeback_targets,
            writeback_contract=writeback_contract,
            writeback_source_contracts=writeback_target_resolution["writeback_source_contracts"],
            writeback_target_sources=writeback_target_resolution["writeback_target_sources"],
        )

        approval_chain_present = approval_state in ("APPROVED", "NOT_REQUIRED")
        audit_trail_present = bool(h08_payload["touch_record_id"] and h08_payload["opportunity_id"])
        order_approval_state = approval_state
        if (
            order_approval_state == "NOT_REQUIRED"
            and order_status_default == "PENDING_APPROVAL"
        ):
            order_approval_state = "PENDING"
        resolved_refund_state = runtime_state.resolve(
            "refund_state",
            runtime_inputs.get("refund_state", "NOT_REQUESTED"),
        )
        payment_status_value = runtime_state.resolve(
            "payment_status",
            runtime_inputs.get("payment_status", "NOT_STARTED"),
        )
        if payment_status_value == "NOT_STARTED":
            if resolved_refund_state == "COMPLETED":
                payment_status_value = "REFUNDED"
            elif resolved_refund_state in ("REQUESTED", "APPROVED"):
                payment_status_value = "REFUND_PENDING"
        payment_exception_family = runtime_state.resolve("payment_exception_family_optional")
        payment_exception_tags = ensure_list(
            runtime_state.resolve("payment_exception_reason_tags_optional")
        )
        payment_exception_reason = runtime_state.resolve(
            "payment_exception_reason_optional",
            payment_exception_tags[0] if payment_exception_tags else payment_exception_family,
        )
        amount_mismatch_state = runtime_state.resolve(
            "amount_mismatch_state_optional",
            runtime_inputs.get("amount_mismatch_state_optional"),
        )
        refund_amount_band_optional = runtime_inputs.get("refund_amount_band_optional")
        if resolved_refund_state not in (None, "", "NOT_REQUESTED") and refund_amount_band_optional in (None, ""):
            refund_amount_band_optional = runtime_inputs["amount_band"]
        payment_written_back_at = written_back_at_optional or now
        payer_match_state = runtime_state.resolve(
            "payer_match_state",
            self._match_state_from_mismatch(runtime_inputs.get("payer_mismatch_state", "NO_MISMATCH")),
        )
        amount_match_state = runtime_state.resolve(
            "amount_match_state",
            self._match_state_from_mismatch(amount_mismatch_state),
        )
        resolved_delivery_status = runtime_state.resolve("delivery_status", runtime_inputs["delivery_status"])
        delivery_exception_family = runtime_state.resolve("delivery_exception_family_optional")
        delivery_exception_tags = ensure_list(
            runtime_state.resolve("delivery_exception_reason_tags_optional")
        )
        delivery_exception_reason = runtime_state.resolve(
            "delivery_exception_reason_optional",
            delivery_exception_tags[0] if delivery_exception_tags else delivery_exception_family,
        )
        customer_ack_state_optional = runtime_state.resolve(
            "customer_ack_state_optional",
            runtime_inputs.get("customer_ack_state_optional"),
        )
        if customer_ack_state_optional in (None, ""):
            if resolved_delivery_status == "ACKNOWLEDGED":
                customer_ack_state_optional = "ACKNOWLEDGED"
            elif resolved_delivery_status in ("DELIVERED", "ACK_PENDING"):
                customer_ack_state_optional = "PENDING"
            else:
                customer_ack_state_optional = "NOT_REQUESTED"
        governance_effective_state = self._stricter_decision(
            runtime_state.governance_decision_state,
            upstream_governance_decision_state,
        )
        permission_effective_state = self._stricter_decision(
            runtime_state.permission_decision_state,
            upstream_permission_decision_state,
        )
        semantic_effective_state = self._stricter_decision(
            runtime_state.semantic_decision_state,
            upstream_semantic_decision_state,
        )

        order_payload = {
            "order_id": build_id("ORDER", project_id),
            "project_id": project_id,
            "opportunity_id": h08_payload["opportunity_id"],
            "touch_record_id": h08_payload["touch_record_id"],
            "response_status": response_status,
            "saleability_status": saleability_status,
            "crm_owner_state": crm_owner_state,
            "commercial_status": ensure_enum(
                self.store,
                "commercial_status",
                runtime_inputs["commercial_status"],
            ),
            "order_status": ensure_enum(
                self.store,
                "order_status",
                runtime_inputs["order_status"],
            ),
            "approval_state": ensure_enum(
                self.store,
                "approval_state",
                order_approval_state,
            ),
            "archival_status": ensure_enum(
                self.store,
                "archival_status",
                runtime_state.resolve(
                    "archival_status",
                    runtime_inputs.get("archival_status", "NOT_ARCHIVED"),
                ),
            ),
            "amount_band": ensure_enum(
                self.store,
                "amount_band",
                runtime_inputs["amount_band"],
            ),
            "plan_status": ensure_enum(
                self.store,
                "plan_status",
                plan_status,
            ),
            "touch_record_state": ensure_enum(
                self.store,
                "touch_record_state",
                touch_record_state,
            ),
            "governed_execution_mode": governed_execution_mode,
            "permission_decision_state": permission_effective_state,
            "governance_decision_state": governance_effective_state,
            "semantic_decision_state": semantic_effective_state,
            "governed_metadata": governed_metadata,
            "created_at": now,
        }
        order_guard = self.store.evaluate_runtime_guards(
            "order_record",
            order_payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=["internal_review_release", "sales_consumption_release"],
                gate_conditions={
                    "approval chain present": approval_chain_present,
                    "audit trail present": audit_trail_present,
                },
            ),
        )
        runtime_state.add_governance_guard(order_guard)
        if order_guard.decision_state == "BLOCK":
            order_payload["commercial_status"] = "ON_HOLD"
            order_payload["order_status"] = "ON_HOLD"
        elif order_guard.decision_state == "REVIEW" and order_payload["order_status"] == "DRAFT":
            order_payload["order_status"] = "PENDING_APPROVAL"
            if order_payload["approval_state"] == "NOT_REQUIRED":
                order_payload["approval_state"] = "PENDING"
        order_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type="order_record",
            payload=order_payload,
            semantic_context={
                "saleability_status": saleability_status,
                "crm_owner_state": crm_owner_state,
                "plan_status": plan_status,
                "touch_record_state": touch_record_state,
                "feedback_reason": feedback_reason,
                "governance_decision_state": upstream_governance_decision_state,
            },
        )
        if order_semantic:
            runtime_state.add_semantic_validation(order_semantic)
            if order_semantic.decision_state == "BLOCK":
                order_payload["commercial_status"] = "ON_HOLD"
                order_payload["order_status"] = "ON_HOLD"
            elif order_semantic.decision_state == "REVIEW" and order_payload["order_status"] == "DRAFT":
                order_payload["order_status"] = "PENDING_APPROVAL"
                if order_payload["approval_state"] == "NOT_REQUIRED":
                    order_payload["approval_state"] = "PENDING"
        order_record = self.store.build_record("order_record", order_payload)

        payment_payload = {
            "payment_id": build_id("PAY", project_id),
            "project_id": project_id,
            "order_id": order_record.get("order_id"),
            "payment_status": ensure_enum(
                self.store,
                "payment_status",
                payment_status_value,
            ),
            "payment_proof_state": runtime_inputs.get("payment_proof_state", "NOT_PROVIDED"),
            "amount_band": order_record.get("amount_band"),
            "payer_match_state": payer_match_state,
            "amount_match_state": amount_match_state,
            "payment_exception_family_optional": payment_exception_family or "NO_EXCEPTION",
            "payment_exception_reason_optional": payment_exception_reason or "NO_EXCEPTION",
            "payment_exception_reason_tags_optional": payment_exception_tags,
            "amount_mismatch_state_optional": amount_mismatch_state or "NO_MISMATCH",
            "refund_state": resolved_refund_state,
            "refund_amount_band_optional": refund_amount_band_optional or "NOT_APPLICABLE",
            "paid_at_optional": runtime_inputs.get("paid_at_optional", "NOT_PAID"),
            "written_back_at_optional": payment_written_back_at,
            "governed_execution_mode": governed_execution_mode,
            "permission_decision_state": permission_effective_state,
            "governance_decision_state": governance_effective_state,
            "semantic_decision_state": semantic_effective_state,
            "governed_metadata": governed_metadata,
        }
        payment_guard = self.store.evaluate_runtime_guards(
            "payment_record",
            payment_payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=["internal_review_release", "sales_consumption_release"],
                gate_conditions={
                    "payment proof or audit present for received state": payment_payload["payment_status"] != "PAID" or payment_payload["payment_proof_state"] != "NOT_PROVIDED" or audit_trail_present,
                    "no payer mismatch block": runtime_inputs.get("payer_mismatch_state", "NO_MISMATCH") == "NO_MISMATCH",
                    "audit trail present": audit_trail_present,
                },
            ),
        )
        runtime_state.add_governance_guard(payment_guard)
        payment_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type="payment_record",
            payload=payment_payload,
            semantic_context={
                "payer_mismatch_state": runtime_inputs.get("payer_mismatch_state", "NO_MISMATCH"),
                "feedback_reason": feedback_reason,
            },
        )
        if payment_semantic:
            runtime_state.add_semantic_validation(payment_semantic)
            if payment_semantic.decision_state == "BLOCK" and payment_payload["payment_status"] == "PAID":
                payment_payload["payment_status"] = "PAYMENT_EXCEPTION"
            elif payment_semantic.decision_state == "REVIEW" and payment_payload["payment_status"] == "NOT_STARTED":
                payment_payload["payment_status"] = "PENDING_PAYMENT"
        payment_record = self.store.build_record("payment_record", payment_payload)

        delivery_payload = {
            "delivery_id": build_id("DELIVERY", project_id),
            "project_id": project_id,
            "order_id": order_record.get("order_id"),
            "payment_id_optional": payment_record.get("payment_id"),
            "delivery_form": ensure_enum(
                self.store,
                "delivery_form",
                runtime_inputs.get("delivery_form", "INTERNAL_REVIEW"),
            ),
            "delivery_status": ensure_enum(
                self.store,
                "delivery_status",
                resolved_delivery_status,
            ),
            "delivered_at_optional": runtime_inputs.get("delivered_at_optional", "NOT_DELIVERED"),
            "customer_ack_state_optional": customer_ack_state_optional,
            "delivery_exception_family_optional": delivery_exception_family or "NO_EXCEPTION",
            "delivery_exception_reason_optional": delivery_exception_reason or "NO_EXCEPTION",
            "delivery_exception_reason_tags_optional": delivery_exception_tags,
            "partial_delivery_state_optional": runtime_state.resolve("partial_delivery_state_optional", "NOT_PARTIAL"),
            "resend_required_optional": bool(runtime_state.resolve("resend_required_optional", False)),
            "redeliver_required_optional": bool(runtime_state.resolve("redeliver_required_optional", False)),
            "archival_status": ensure_enum(
                self.store,
                "archival_status",
                runtime_state.resolve(
                    "archival_status",
                    runtime_inputs.get("archival_status", "NOT_ARCHIVED"),
                ),
            ),
            "retention_until": runtime_inputs.get("retention_until", now),
            "retrieval_status": ensure_enum(
                self.store,
                "retrieval_status",
                runtime_state.resolve(
                    "retrieval_status",
                    runtime_inputs.get("retrieval_status", "NOT_AVAILABLE"),
                ),
            ),
            "written_back_at_optional": written_back_at_optional or now,
            "governed_execution_mode": governed_execution_mode,
            "permission_decision_state": permission_effective_state,
            "governance_decision_state": governance_effective_state,
            "semantic_decision_state": semantic_effective_state,
            "governed_metadata": governed_metadata,
        }
        delivery_guard = self.store.evaluate_runtime_guards(
            "delivery_record",
            delivery_payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=["internal_review_release", "sales_consumption_release"],
                gate_conditions={
                    "release gate present": True,
                    "approval chain present": approval_chain_present,
                    "audit trail present": audit_trail_present,
                    "archival or retrieval not failed": delivery_payload["archival_status"] != "ARCHIVE_EXCEPTION" and delivery_payload["retrieval_status"] != "FAILED",
                },
            ),
        )
        runtime_state.add_governance_guard(delivery_guard)
        if delivery_guard.decision_state == "BLOCK":
            delivery_payload["delivery_status"] = "RELEASE_BLOCKED"
        delivery_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type="delivery_record",
            payload=delivery_payload,
            semantic_context={
                "saleability_status": saleability_status,
                "plan_status": plan_status,
                "touch_record_state": touch_record_state,
            },
        )
        if delivery_semantic:
            runtime_state.add_semantic_validation(delivery_semantic)
            if delivery_semantic.decision_state == "BLOCK":
                delivery_payload["delivery_status"] = "RELEASE_BLOCKED"
        delivery_record = self.store.build_record("delivery_record", delivery_payload)

        governance_payload = {
            "governance_feedback_event_id": build_id("GOV", project_id),
            "project_id": project_id,
            "trigger_type": ensure_enum(
                self.store,
                "trigger_type",
                runtime_state.resolve("trigger_type", runtime_inputs["trigger_type"]),
            ),
            "trigger_summary": runtime_inputs["trigger_summary"],
            "action_taken": "; ".join(
                runtime_state.resolve(
                    "required_actions",
                    [runtime_inputs.get("action_taken", "NONE")],
                )
            ),
            "written_back_at": now,
            "written_back_at_optional": written_back_at_optional or now,
            "archive_scope": runtime_inputs.get(
                "archive_scope",
                runtime_state.resolve("impact_scope", "INTERNAL"),
            ),
            "feedback_reason": feedback_reason,
            "writeback_targets": governance_legacy_writeback_targets or [governance_owned_self_target],
            "governance_feedback_policy_id_optional": runtime_state.resolve(
                "governance_feedback_policy_id_optional",
                runtime_state.resolve("trigger_type", runtime_inputs["trigger_type"]),
            ),
            "impact_scope_optional": runtime_state.resolve("impact_scope", "INTERNAL"),
            "governed_execution_mode": governed_execution_mode,
            "permission_decision_state": permission_effective_state,
            "governance_decision_state": governance_effective_state,
            "semantic_decision_state": semantic_effective_state,
            "governed_metadata": governed_metadata,
        }
        governance_guard = self.store.evaluate_runtime_guards(
            "governance_feedback_event",
            governance_payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=["internal_review_release"],
                gate_conditions={
                    "trigger and action valid": bool(governance_payload["trigger_type"] and governance_payload["action_taken"]),
                    "written_back_at present": bool(governance_payload["written_back_at"]),
                    "governance audit present": audit_trail_present,
                },
            ),
        )
        runtime_state.add_governance_guard(governance_guard)
        governance_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type="governance_feedback_event",
            payload=governance_payload,
            semantic_context={},
        )
        if governance_semantic:
            runtime_state.add_semantic_validation(governance_semantic)
        governance_feedback_event = self.store.build_record("governance_feedback_event", governance_payload)

        outcome_payload = {
            "outcome_event_id": build_id("OUTCOME", project_id),
            "project_id": project_id,
            "opportunity_id": order_record.get("opportunity_id"),
            "outcome_family": ensure_enum(
                self.store,
                "outcome_family",
                runtime_state.resolve("outcome_family", runtime_inputs["outcome_family"]),
            ),
            "outcome_reason_tags": ensure_list(
                runtime_state.resolve(
                    "outcome_reason_tags",
                    runtime_inputs["outcome_reason_tags"],
                )
            ),
            "is_false_positive": bool(runtime_inputs.get("is_false_positive", False)),
            "window_missed_state": ensure_enum(
                self.store,
                "window_missed_state",
                runtime_inputs["window_missed_state"],
            ),
            "contact_failure_state": ensure_enum(
                self.store,
                "contact_failure_state",
                runtime_inputs["contact_failure_state"],
            ),
            "payer_mismatch_state": ensure_enum(
                self.store,
                "payer_mismatch_state",
                runtime_inputs["payer_mismatch_state"],
            ),
            "feedback_reason": feedback_reason,
            "trigger_type": governance_payload["trigger_type"],
            "action_taken": governance_payload["action_taken"],
            "writeback_targets": outcome_writeback_targets,
            "governance_feedback_triggered_optional": bool(
                runtime_state.resolve("governance_feedback_triggered_optional", False)
            ),
            "written_back_at": written_back_at_optional or now,
            "written_back_at_optional": written_back_at_optional or now,
            "governed_execution_mode": governed_execution_mode,
            "permission_decision_state": permission_effective_state,
            "governance_decision_state": governance_effective_state,
            "semantic_decision_state": semantic_effective_state,
            "governed_metadata": governed_metadata,
        }
        outcome_guard = self.store.evaluate_runtime_guards(
            "opportunity_outcome_event",
            outcome_payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=["internal_review_release", "sales_consumption_release"],
                gate_conditions={
                    "taxonomy valid": bool(outcome_payload["outcome_family"] and outcome_payload["outcome_reason_tags"]),
                    "written_back_at present": bool(outcome_payload["written_back_at"]),
                    "audit trail present": audit_trail_present,
                },
            ),
        )
        runtime_state.add_governance_guard(outcome_guard)
        outcome_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type="opportunity_outcome_event",
            payload=outcome_payload,
            semantic_context={
                "delivery_status": delivery_payload["delivery_status"],
                "plan_status": plan_status,
                "feedback_reason": feedback_reason,
                "governance_decision_state": governance_effective_state,
            },
        )
        if outcome_semantic:
            runtime_state.add_semantic_validation(outcome_semantic)
        opportunity_outcome_event = self.store.build_record("opportunity_outcome_event", outcome_payload)
        impact_result = self.impact_executor.execute(
            project_id=project_id,
            saleable_opportunity=saleable_opportunity,
            touch_record=touch_record,
            opportunity_outcome_event=opportunity_outcome_event,
            governance_feedback_event=governance_feedback_event,
            effective_writeback_targets=resolved_effective_writeback_targets,
            target_sources=writeback_target_resolution["writeback_target_sources"],
            now=now,
        )

        handoff = {
            "project_id": project_id,
            "order_status": order_record.get("order_status"),
            "delivery_status": delivery_record.get("delivery_status"),
            "plan_status": plan_status,
            "touch_record_state": touch_record_state,
            "feedback_reason": feedback_reason,
            "written_back_at_optional": written_back_at_optional or now,
            "governed_execution_mode": governed_execution_mode,
            "outcome_writeback_targets": outcome_writeback_targets,
            "outcome_authoritative_base_targets": outcome_authoritative_base_targets,
            "upstream_feedback_projected_targets": upstream_feedback_projected_targets,
            "upstream_feedback_advisory_targets": upstream_feedback_advisory_targets,
            "upstream_feedback_contracts": upstream_feedback_contract["upstream_feedback_contracts"],
            "governance_writeback_targets_optional": governance_writeback_targets,
            "governance_legacy_writeback_targets": governance_legacy_writeback_targets,
            "governance_owned_self_target": governance_owned_self_target,
            "payment_exception_writeback_targets_optional": payment_exception_writeback_targets,
            "delivery_exception_writeback_targets_optional": delivery_exception_writeback_targets,
            "effective_writeback_targets": effective_writeback_targets,
            "resolved_effective_writeback_targets": resolved_effective_writeback_targets,
            "writeback_contract_state": impact_result["writeback_contract_state"],
            "writeback_contract_semantics": impact_result["writeback_contract_semantics"],
            "writeback_source_contracts": impact_result["writeback_source_contracts"],
            "writeback_target_sources": impact_result["writeback_target_sources"],
            "writeback_target_contracts": impact_result["writeback_target_contracts"],
            "writeback_persistence_targets": impact_result["writeback_persistence_targets"],
            "writeback_projected_targets": impact_result["writeback_projected_targets"],
            "writeback_advisory_targets": impact_result["writeback_advisory_targets"],
            "writeback_trace_only_targets": impact_result["writeback_trace_only_targets"],
            "policy_trace": runtime_state.trace,
            "policy_decision_state": runtime_state.decision_state,
            "permission_trace": runtime_state.capability_trace,
            "permission_decision_state": runtime_state.permission_decision_state,
            "permission_governance": runtime_state.capability_governance(),
            "governance_trace": runtime_state.governance_trace,
            "governance_decision_state": runtime_state.governance_decision_state,
            "governance_additions": runtime_state.governance_additions,
            "semantic_trace": runtime_state.semantic_trace,
            "semantic_decision_state": runtime_state.semantic_decision_state,
            "semantic_additions": runtime_state.semantic_additions,
            "impact_executor_state": impact_result["impact_executor_state"],
            "impact_targets_projected": impact_result["impact_targets_projected"],
            "impact_targets_projected_contract_only": impact_result["impact_targets_projected_contract_only"],
            "impact_targets_advisory": impact_result["impact_targets_advisory"],
            "impact_mutations": impact_result["impact_mutations"],
            "impact_projected_contracts": impact_result["impact_projected_contracts"],
            "impact_advisories": impact_result["impact_advisories"],
            "impact_trace": impact_result["impact_trace"],
        }

        return StageBundle(
            stage=9,
            records={
                "order_record": order_record,
                "payment_record": payment_record,
                "delivery_record": delivery_record,
                "governance_feedback_event": governance_feedback_event,
                "opportunity_outcome_event": opportunity_outcome_event,
            },
            handoff=handoff,
            trace_rules=[
                f"POLICY:emit_decision:{entry.get('policy_key', '')}"
                for entry in runtime_state.trace
                if entry.get("event") == "emit_decision"
            ],
            inputs={
                **runtime_inputs,
                "outcome_writeback_targets": outcome_writeback_targets,
                "outcome_authoritative_base_targets": outcome_authoritative_base_targets,
                "upstream_feedback_projected_targets": upstream_feedback_projected_targets,
                "upstream_feedback_advisory_targets": upstream_feedback_advisory_targets,
                "upstream_feedback_contracts": upstream_feedback_contract["upstream_feedback_contracts"],
                "governance_writeback_targets_optional": governance_writeback_targets,
                "governance_legacy_writeback_targets": governance_legacy_writeback_targets,
                "governance_owned_self_target": governance_owned_self_target,
                "payment_exception_writeback_targets_optional": payment_exception_writeback_targets,
                "delivery_exception_writeback_targets_optional": delivery_exception_writeback_targets,
                "effective_writeback_targets": effective_writeback_targets,
                "resolved_effective_writeback_targets": resolved_effective_writeback_targets,
                "writeback_contract_state": impact_result["writeback_contract_state"],
                "writeback_contract_semantics": impact_result["writeback_contract_semantics"],
                "writeback_source_contracts": impact_result["writeback_source_contracts"],
                "writeback_target_sources": impact_result["writeback_target_sources"],
                "writeback_target_contracts": impact_result["writeback_target_contracts"],
                "writeback_persistence_targets": impact_result["writeback_persistence_targets"],
                "writeback_projected_targets": impact_result["writeback_projected_targets"],
                "writeback_advisory_targets": impact_result["writeback_advisory_targets"],
                "writeback_trace_only_targets": impact_result["writeback_trace_only_targets"],
                "policy_trace": runtime_state.trace,
                "policy_decision_state": runtime_state.decision_state,
                "permission_trace": runtime_state.capability_trace,
                "permission_decision_state": runtime_state.permission_decision_state,
                "permission_governance": runtime_state.capability_governance(),
                "governance_trace": runtime_state.governance_trace,
                "governance_decision_state": runtime_state.governance_decision_state,
                "governance_additions": runtime_state.governance_additions,
                "semantic_trace": runtime_state.semantic_trace,
                "semantic_decision_state": runtime_state.semantic_decision_state,
                "semantic_additions": runtime_state.semantic_additions,
                "impact_executor_state": impact_result["impact_executor_state"],
                "impact_runtime_executor_enabled": impact_result["runtime_executor_enabled"],
                "impact_mutation_mode": impact_result["mutation_mode"],
                "impact_formal_targets": impact_result["formal_targets"],
                "impact_targets_projected": impact_result["impact_targets_projected"],
                "impact_targets_projected_contract_only": impact_result["impact_targets_projected_contract_only"],
                "impact_targets_advisory": impact_result["impact_targets_advisory"],
                "impact_mutations": impact_result["impact_mutations"],
                "impact_projected_contracts": impact_result["impact_projected_contracts"],
                "impact_advisories": impact_result["impact_advisories"],
                "impact_trace": impact_result["impact_trace"],
            },
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff
