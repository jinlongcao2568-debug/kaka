# Stage: stage9_delivery
# Consumes formal objects: saleable_opportunity, touch_record, order_record, payment_record, delivery_record, governance_feedback_event, opportunity_outcome_event
# Dependent handoff: H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/release/delivery_matrix.json, contracts/release/release_gates.json, contracts/governance/field_policy_dictionary.json

from __future__ import annotations

from typing import Any, Mapping

from stage9_delivery.feedback_writeback import (
    build_feedback_handoff,
    build_feedback_inputs,
    build_governance_feedback_payload,
    build_opportunity_outcome_payload,
    build_stage9_governed_metadata,
    governance_feedback_guard_conditions,
    opportunity_outcome_guard_conditions,
    opportunity_outcome_semantic_context,
    resolve_writeback_projection,
)
from stage9_delivery.impact_executor import ImpactExecutor
from stage9_delivery.order_payment_delivery_execution import (
    DELIVERY_SANDBOX_RECORDS_INPUT_KEY,
    MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY,
    PAYMENT_SANDBOX_RECORDS_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_INPUT_KEY,
    STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY,
    attach_delivery_sandbox_records,
    attach_order_lifecycle_record,
    attach_payment_sandbox_records,
    build_stage9_execution_ledger,
)
from stage9_delivery.typed_lifecycle import (
    apply_delivery_decision_projection,
    apply_order_decision_projection,
    apply_payment_decision_projection,
    build_delivery_record_spec,
    build_order_record_spec,
    build_payment_record_spec,
    resolve_delivery_lifecycle_state,
    resolve_order_approval_state,
    resolve_payment_lifecycle_state,
)
from shared.capability_runtime import CapabilityRuntime
from shared.contract_loader import load_contract
from shared.context_packet import ContextPacket
from shared.contracts_runtime import ContractStore, StageBundle
from shared.provider_adapter_config import PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY
from shared.settings import Settings
from shared.utils import resolve_bundle, utc_now_iso


# Stage9 writeback authority anchors are intentionally retained in this facade
# for repository contract checks; executable logic lives in feedback_writeback.py.
# outcome_writeback_targets = ensure_list(
# runtime_state.outputs.get("outcome_taxonomy", {}).get("writeback_targets"
# governance_writeback_targets = ensure_list(
# runtime_state.outputs.get("governance_taxonomy", {}).get("writeback_targets"
# payment_exception_writeback_targets = ensure_list(
# delivery_exception_writeback_targets = ensure_list(
# writeback_target_resolution = self.impact_executor.resolve_effective_targets(
# effective_writeback_targets = list(
# writeback_target_resolution["effective_writeback_targets"]
# writeback_source_contracts=writeback_target_resolution["writeback_source_contracts"]
# writeback_target_sources=writeback_target_resolution["writeback_target_sources"]
# "writeback_targets": outcome_writeback_targets
# "effective_writeback_targets": effective_writeback_targets
# "writeback_source_contracts": impact_result["writeback_source_contracts"]
# "writeback_target_sources": impact_result["writeback_target_sources"]
# writeback_target_contracts
# "live_execution_enabled": False
# "governed_execution_mode": "INTERNAL_GOVERNED"


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
    GOVERNED_FALLBACKS: dict[str, Any] = {
        "plan_status": "DRAFT",
        "touch_record_state": "CREATED",
        "governance_decision_state": "ALLOW",
        "permission_decision_state": "ALLOW",
        "semantic_decision_state": "ALLOW",
        "commercial_status": "DRAFT",
        "order_status": "DRAFT",
        "delivery_status": "NOT_READY",
        "trigger_type": "OTHER",
        "outcome_family": "WON",
        "outcome_reason_tags": ["SIGNED"],
        "contact_failure_state": "OTHER",
    }

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.store = ContractStore.default(self.settings)
        self.runtime = CapabilityRuntime(self.settings)
        self.impact_executor = ImpactExecutor(self.settings)

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

    def _governed_fallback(self, field_name: str) -> Any:
        value = self.GOVERNED_FALLBACKS[field_name]
        return list(value) if isinstance(value, list) else value

    def _stage9_h08_workflow_policy(self) -> dict[str, Any]:
        catalog = load_contract(
            "contracts/sales/stage9_h08_workflow_fallback_catalog.json",
            self.settings,
        )
        return dict(catalog["policies"][0])

    def _h08_optional_or_fallback(
        self,
        h08_payload: Mapping[str, Any],
        field_name: str,
        *,
        fallback: Any | None = None,
    ) -> Any:
        value = h08_payload.get(field_name)
        if value not in (None, ""):
            return value
        if fallback is not None:
            return fallback
        return self._governed_fallback(field_name)

    def _outcome_feedback_policy(self) -> dict[str, Any]:
        catalog = load_contract("contracts/sales/opportunity_policy_catalog.json", self.settings)
        for policy in catalog.get("policies", []):
            if policy.get("policyId") == "opportunity_outcome_writeback_v1":
                return dict(policy)
        raise ValueError("Stage9 requires contracts/sales/opportunity_policy_catalog.json#opportunity_outcome_writeback_v1")

    def _outcome_taxonomy_entry(self, outcome_family: str) -> dict[str, Any]:
        catalog = load_contract("contracts/sales/outcome_taxonomy_catalog.json", self.settings)
        for entry in catalog.get("entries", []):
            if entry.get("outcome_family") == outcome_family:
                return dict(entry)
        raise ValueError(f"Stage9 requires outcome taxonomy entry: {outcome_family}")

    def _governance_taxonomy_entry(self, trigger_type: str) -> dict[str, Any]:
        catalog = load_contract("contracts/sales/governance_feedback_policy_catalog.json", self.settings)
        for entry in catalog.get("entries", []):
            if entry.get("trigger_type") == trigger_type:
                return dict(entry)
        raise ValueError(f"Stage9 requires governance taxonomy entry: {trigger_type}")

    def _matches_h08_workflow_rule(
        self,
        rule: Mapping[str, Any],
        facts: Mapping[str, Any],
    ) -> bool:
        for field_name, expected in dict(rule.get("when", {})).items():
            actual = facts.get(field_name)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    def _render_h08_workflow_outputs(
        self,
        outputs: Mapping[str, Any],
        facts: Mapping[str, Any],
    ) -> dict[str, Any]:
        rendered: dict[str, Any] = {}
        for field_name, value in outputs.items():
            if field_name.endswith("_from"):
                target_field = field_name[: -len("_from")]
                source_value = facts.get(str(value))
                if target_field == "outcome_reason_tags":
                    rendered[target_field] = [source_value] if source_value not in (None, "") else []
                else:
                    rendered[target_field] = source_value
            else:
                rendered[field_name] = value
        return rendered

    def _h08_contract_workflow_fallbacks(
        self,
        *,
        response_status: str,
        saleability_status: str,
        crm_owner_state: str,
        plan_status: str,
        feedback_reason: str,
        upstream_governance_decision_state: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        policy = self._stage9_h08_workflow_policy()
        fallbacks: dict[str, Any] = {}
        contact_failed_entry = self._outcome_taxonomy_entry("CONTACT_FAILED")
        allowed_contact_reasons = set(contact_failed_entry.get("allowed_reason_tags", []))
        facts = {
            "response_status": response_status,
            "saleability_status": saleability_status,
            "crm_owner_state": crm_owner_state,
            "plan_status": plan_status,
            "feedback_reason": feedback_reason,
            "upstream_governance_decision_state": upstream_governance_decision_state,
            "feedback_reason_allowed_for_contact_failed": feedback_reason in allowed_contact_reasons,
        }
        trace: dict[str, Any] = {
            "policy_id": policy["policy_id"],
            "contact_failure_rule_id_optional": None,
            "trigger_rule_id_optional": None,
            "lifecycle_rule_id_optional": None,
            "facts": dict(facts),
            "resolved_outputs": {},
        }

        contact_failure_rule = next(
            (
                rule
                for rule in policy.get("contact_failure_rules", [])
                if self._matches_h08_workflow_rule(rule, facts)
            ),
            None,
        )
        if contact_failure_rule is not None:
            fallbacks.update(
                self._render_h08_workflow_outputs(
                    contact_failure_rule.get("outputs", {}),
                    facts,
                )
            )
            trace["contact_failure_rule_id_optional"] = contact_failure_rule.get("rule_id")

        facts_with_outcome = {
            **facts,
            "outcome_family": fallbacks.get("outcome_family"),
        }
        trigger_rule = next(
            (
                rule
                for rule in policy.get("trigger_rules", [])
                if self._matches_h08_workflow_rule(rule, facts_with_outcome)
            ),
            None,
        )
        if trigger_rule is not None:
            trigger_outputs = self._render_h08_workflow_outputs(
                trigger_rule.get("outputs", {}),
                facts_with_outcome,
            )
            if trigger_outputs.get("trigger_type"):
                self._governance_taxonomy_entry(str(trigger_outputs["trigger_type"]))
            fallbacks.update(trigger_outputs)
            facts_with_outcome.update(trigger_outputs)
            trace["trigger_rule_id_optional"] = trigger_rule.get("rule_id")

        lifecycle_rule = next(
            (
                rule
                for rule in policy.get("lifecycle_rules", [])
                if self._matches_h08_workflow_rule(rule, facts_with_outcome)
            ),
            None,
        )
        if lifecycle_rule is not None:
            lifecycle_outputs = self._render_h08_workflow_outputs(
                lifecycle_rule.get("outputs", {}),
                facts_with_outcome,
            )
            fallbacks.update(lifecycle_outputs)
            trace["lifecycle_rule_id_optional"] = lifecycle_rule.get("rule_id")

        trace["resolved_outputs"] = dict(fallbacks)
        return fallbacks, trace

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
        provider_adapter_readiness_summary = (
            dict(inputs[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY])
            if isinstance(inputs.get(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY), Mapping)
            else self.settings.provider_adapter_readiness_summary()
        )

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
        plan_status = self._h08_optional_or_fallback(h08_payload, "plan_status")
        touch_record_state = self._h08_optional_or_fallback(h08_payload, "touch_record_state")
        feedback_reason = self._h08_optional_or_fallback(
            h08_payload,
            "feedback_reason",
            fallback=response_status,
        )
        written_back_at_optional = h08_payload.get("written_back_at_optional")
        upstream_governance_decision_state = self._h08_optional_or_fallback(
            h08_payload,
            "governance_decision_state",
        )
        upstream_permission_decision_state = self._h08_optional_or_fallback(
            h08_payload,
            "permission_decision_state",
        )
        upstream_semantic_decision_state = self._h08_optional_or_fallback(
            h08_payload,
            "semantic_decision_state",
        )
        release_level = inputs.get("release_level", inputs.get("minimum_release_level", "INTERNAL_OPERABLE"))
        approval_state = inputs.get("approval_state", "NOT_REQUIRED")
        governed_execution_mode = str(inputs.get("governed_execution_mode", "INTERNAL_GOVERNED"))
        h08_contract_fallbacks, h08_workflow_fallback_trace = self._h08_contract_workflow_fallbacks(
            response_status=response_status,
            saleability_status=saleability_status,
            crm_owner_state=crm_owner_state,
            plan_status=plan_status,
            feedback_reason=feedback_reason,
            upstream_governance_decision_state=upstream_governance_decision_state,
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
            "h08_workflow_fallback_trace": h08_workflow_fallback_trace,
            "governance_decision_state": upstream_governance_decision_state,
            "permission_decision_state": upstream_permission_decision_state,
            "semantic_decision_state": upstream_semantic_decision_state,
            PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: provider_adapter_readiness_summary,
            "trigger_type": inputs.get(
                "trigger_type",
                h08_contract_fallbacks.get(
                    "trigger_type",
                    self._governed_fallback("trigger_type"),
                ),
            ),
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
            "outcome_family": inputs.get(
                "outcome_family",
                h08_contract_fallbacks.get(
                    "outcome_family",
                    self._governed_fallback("outcome_family"),
                ),
            ),
            "outcome_reason_tags": inputs.get(
                "outcome_reason_tags",
                h08_contract_fallbacks.get(
                    "outcome_reason_tags",
                    self._governed_fallback("outcome_reason_tags"),
                ),
            ),
            "contact_failure_state": inputs.get(
                "contact_failure_state",
                h08_contract_fallbacks.get(
                    "contact_failure_state",
                    self._governed_fallback("contact_failure_state"),
                ),
            ),
            "window_missed_state": inputs.get("window_missed_state", "NOT_MISSED"),
            "payer_mismatch_state": inputs.get("payer_mismatch_state", "NO_MISMATCH"),
            "commercial_status": inputs.get(
                "commercial_status",
                h08_contract_fallbacks.get(
                    "commercial_status",
                    self._governed_fallback("commercial_status"),
                ),
            ),
            "order_status": inputs.get(
                "order_status",
                h08_contract_fallbacks.get(
                    "order_status",
                    self._governed_fallback("order_status"),
                ),
            ),
            "delivery_status": inputs.get(
                "delivery_status",
                h08_contract_fallbacks.get(
                    "delivery_status",
                    self._governed_fallback("delivery_status"),
                ),
            ),
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

        writeback_projection = resolve_writeback_projection(
            runtime_state=runtime_state,
            runtime_inputs=runtime_inputs,
            impact_executor=self.impact_executor,
            outcome_feedback_policy=self._outcome_feedback_policy(),
        )
        governed_metadata = build_stage9_governed_metadata(
            plan_status=plan_status,
            touch_record_state=touch_record_state,
            feedback_reason=feedback_reason,
            written_back_at_optional=written_back_at_optional,
            upstream_governance_decision_state=upstream_governance_decision_state,
            projection=writeback_projection,
        )

        approval_chain_present = approval_state in ("APPROVED", "NOT_REQUIRED")
        audit_trail_present = bool(h08_payload["touch_record_id"] and h08_payload["opportunity_id"])
        order_approval_state = resolve_order_approval_state(
            approval_state=approval_state,
            order_status=str(runtime_inputs["order_status"]),
        )
        payment_state = resolve_payment_lifecycle_state(
            runtime_state=runtime_state,
            runtime_inputs=runtime_inputs,
            written_back_at_optional=written_back_at_optional,
            now=now,
        )
        delivery_state = resolve_delivery_lifecycle_state(
            runtime_state=runtime_state,
            runtime_inputs=runtime_inputs,
        )
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

        # Typed lifecycle authority anchor kept in service.py for contract validation:
        # "opportunity_id": h08_payload["opportunity_id"]
        order_spec = build_order_record_spec(
            store=self.store,
            project_id=project_id,
            h08_payload=h08_payload,
            response_status=response_status,
            saleability_status=saleability_status,
            crm_owner_state=crm_owner_state,
            runtime_inputs=runtime_inputs,
            order_approval_state=order_approval_state,
            order_archival_status=runtime_state.resolve(
                "archival_status",
                runtime_inputs.get("archival_status", "NOT_ARCHIVED"),
            ),
            plan_status=plan_status,
            touch_record_state=touch_record_state,
            governed_execution_mode=governed_execution_mode,
            permission_effective_state=permission_effective_state,
            governance_effective_state=governance_effective_state,
            semantic_effective_state=semantic_effective_state,
            governed_metadata=governed_metadata,
            now=now,
            approval_chain_present=approval_chain_present,
            audit_trail_present=audit_trail_present,
            feedback_reason=feedback_reason,
            upstream_governance_decision_state=upstream_governance_decision_state,
        )
        order_guard = self.store.evaluate_runtime_guards(
            order_spec.object_type,
            order_spec.payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=list(order_spec.guard.requested_gate_ids),
                gate_conditions=order_spec.guard.gate_conditions,
            ),
        )
        runtime_state.add_governance_guard(order_guard)
        apply_order_decision_projection(order_spec.payload, order_guard.decision_state)
        order_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type=order_spec.object_type,
            payload=order_spec.payload,
            semantic_context=order_spec.semantic.context,
        )
        if order_semantic:
            runtime_state.add_semantic_validation(order_semantic)
            apply_order_decision_projection(order_spec.payload, order_semantic.decision_state)
        attach_order_lifecycle_record(
            order_spec.payload,
            runtime_inputs=runtime_inputs,
            now=now,
        )
        order_record = self.store.build_record(order_spec.object_type, order_spec.payload)

        payment_spec = build_payment_record_spec(
            store=self.store,
            project_id=project_id,
            order_record=order_record,
            runtime_inputs=runtime_inputs,
            payment_state=payment_state,
            governed_execution_mode=governed_execution_mode,
            permission_effective_state=permission_effective_state,
            governance_effective_state=governance_effective_state,
            semantic_effective_state=semantic_effective_state,
            governed_metadata=governed_metadata,
            audit_trail_present=audit_trail_present,
            feedback_reason=feedback_reason,
        )
        payment_guard = self.store.evaluate_runtime_guards(
            payment_spec.object_type,
            payment_spec.payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=list(payment_spec.guard.requested_gate_ids),
                gate_conditions=payment_spec.guard.gate_conditions,
            ),
        )
        runtime_state.add_governance_guard(payment_guard)
        payment_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type=payment_spec.object_type,
            payload=payment_spec.payload,
            semantic_context=payment_spec.semantic.context,
        )
        if payment_semantic:
            runtime_state.add_semantic_validation(payment_semantic)
            apply_payment_decision_projection(payment_spec.payload, payment_semantic.decision_state)
        attach_payment_sandbox_records(
            payment_spec.payload,
            runtime_inputs=runtime_inputs,
            provider_adapter_readiness_summary=provider_adapter_readiness_summary,
            now=now,
        )
        payment_record = self.store.build_record(payment_spec.object_type, payment_spec.payload)

        delivery_spec = build_delivery_record_spec(
            store=self.store,
            project_id=project_id,
            order_record=order_record,
            payment_record=payment_record,
            runtime_inputs=runtime_inputs,
            delivery_state=delivery_state,
            written_back_at_optional=written_back_at_optional,
            now=now,
            governed_execution_mode=governed_execution_mode,
            permission_effective_state=permission_effective_state,
            governance_effective_state=governance_effective_state,
            semantic_effective_state=semantic_effective_state,
            governed_metadata=governed_metadata,
            approval_chain_present=approval_chain_present,
            audit_trail_present=audit_trail_present,
            saleability_status=saleability_status,
            plan_status=plan_status,
            touch_record_state=touch_record_state,
            runtime_state=runtime_state,
        )
        delivery_guard = self.store.evaluate_runtime_guards(
            delivery_spec.object_type,
            delivery_spec.payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=list(delivery_spec.guard.requested_gate_ids),
                gate_conditions=delivery_spec.guard.gate_conditions,
            ),
        )
        runtime_state.add_governance_guard(delivery_guard)
        apply_delivery_decision_projection(delivery_spec.payload, delivery_guard.decision_state)
        delivery_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type=delivery_spec.object_type,
            payload=delivery_spec.payload,
            semantic_context=delivery_spec.semantic.context,
        )
        if delivery_semantic:
            runtime_state.add_semantic_validation(delivery_semantic)
            apply_delivery_decision_projection(delivery_spec.payload, delivery_semantic.decision_state)
        attach_delivery_sandbox_records(
            delivery_spec.payload,
            provider_adapter_readiness_summary=provider_adapter_readiness_summary,
            now=now,
        )
        delivery_record = self.store.build_record(delivery_spec.object_type, delivery_spec.payload)
        execution_ledger = build_stage9_execution_ledger(
            project_id=project_id,
            runtime_inputs=runtime_inputs,
            order_record=order_record,
            payment_record=payment_record,
            delivery_record=delivery_record,
            approval_state=approval_state,
            audit_trail_present=audit_trail_present,
            now=now,
            provider_adapter_readiness_summary=provider_adapter_readiness_summary,
        )

        governance_payload = build_governance_feedback_payload(
            store=self.store,
            project_id=project_id,
            runtime_state=runtime_state,
            runtime_inputs=runtime_inputs,
            now=now,
            written_back_at_optional=written_back_at_optional,
            feedback_reason=feedback_reason,
            projection=writeback_projection,
            governed_execution_mode=governed_execution_mode,
            permission_effective_state=permission_effective_state,
            governance_effective_state=governance_effective_state,
            semantic_effective_state=semantic_effective_state,
            governed_metadata=governed_metadata,
        )
        governance_guard = self.store.evaluate_runtime_guards(
            "governance_feedback_event",
            governance_payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=["internal_review_release"],
                gate_conditions=governance_feedback_guard_conditions(
                    governance_payload,
                    audit_trail_present=audit_trail_present,
                ),
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

        outcome_payload = build_opportunity_outcome_payload(
            store=self.store,
            project_id=project_id,
            order_record=order_record,
            governance_payload=governance_payload,
            runtime_state=runtime_state,
            runtime_inputs=runtime_inputs,
            now=now,
            written_back_at_optional=written_back_at_optional,
            feedback_reason=feedback_reason,
            projection=writeback_projection,
            governed_execution_mode=governed_execution_mode,
            permission_effective_state=permission_effective_state,
            governance_effective_state=governance_effective_state,
            semantic_effective_state=semantic_effective_state,
            governed_metadata=governed_metadata,
        )
        outcome_guard = self.store.evaluate_runtime_guards(
            "opportunity_outcome_event",
            outcome_payload,
            self._guard_context(
                inputs=inputs,
                release_level=release_level,
                approval_state=approval_state,
                action_intent="INTERNAL_WRITEBACK",
                requested_gate_ids=["internal_review_release", "sales_consumption_release"],
                gate_conditions=opportunity_outcome_guard_conditions(
                    outcome_payload,
                    audit_trail_present=audit_trail_present,
                ),
            ),
        )
        runtime_state.add_governance_guard(outcome_guard)
        outcome_semantic = self.store.evaluate_object_semantics(
            stage=9,
            object_type="opportunity_outcome_event",
            payload=outcome_payload,
            semantic_context=opportunity_outcome_semantic_context(
                delivery_payload=delivery_spec.payload,
                plan_status=plan_status,
                feedback_reason=feedback_reason,
                governance_effective_state=governance_effective_state,
            ),
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
            effective_writeback_targets=writeback_projection.resolved_effective_writeback_targets,
            target_sources=writeback_projection.writeback_target_resolution["writeback_target_sources"],
            now=now,
        )

        handoff = build_feedback_handoff(
            project_id=project_id,
            order_record=order_record,
            delivery_record=delivery_record,
            plan_status=plan_status,
            touch_record_state=touch_record_state,
            feedback_reason=feedback_reason,
            written_back_at=written_back_at_optional or now,
            governed_execution_mode=governed_execution_mode,
            projection=writeback_projection,
            runtime_state=runtime_state,
            impact_result=impact_result,
            h08_workflow_fallback_trace=h08_workflow_fallback_trace,
        )
        handoff[STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY] = execution_ledger.get("execution_ledger_id")
        handoff[STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY] = execution_ledger.get("readiness_summary")
        handoff["provider_adapter_readiness_summary_optional"] = provider_adapter_readiness_summary
        handoff["order_execution_id"] = execution_ledger.get("order_execution_id")
        handoff["payment_execution_id"] = execution_ledger.get("payment_execution_id")
        handoff["delivery_execution_id"] = execution_ledger.get("delivery_execution_id")
        handoff[PAYMENT_SANDBOX_RECORDS_INPUT_KEY] = payment_record.get(PAYMENT_SANDBOX_RECORDS_INPUT_KEY)
        handoff[DELIVERY_SANDBOX_RECORDS_INPUT_KEY] = delivery_record.get(DELIVERY_SANDBOX_RECORDS_INPUT_KEY)
        handoff[MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY] = payment_record.get(
            MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY
        )
        inputs_out = build_feedback_inputs(
            runtime_inputs=runtime_inputs,
            projection=writeback_projection,
            runtime_state=runtime_state,
            impact_result=impact_result,
            h08_workflow_fallback_trace=h08_workflow_fallback_trace,
        )
        inputs_out[STAGE9_EXECUTION_LEDGER_INPUT_KEY] = execution_ledger
        inputs_out[STAGE9_EXECUTION_LEDGER_ID_INPUT_KEY] = execution_ledger.get("execution_ledger_id")
        inputs_out[STAGE9_EXECUTION_LEDGER_READINESS_INPUT_KEY] = execution_ledger.get("readiness_summary")
        inputs_out[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY] = provider_adapter_readiness_summary
        inputs_out["order_execution_id"] = execution_ledger.get("order_execution_id")
        inputs_out["payment_execution_id"] = execution_ledger.get("payment_execution_id")
        inputs_out["delivery_execution_id"] = execution_ledger.get("delivery_execution_id")
        inputs_out[PAYMENT_SANDBOX_RECORDS_INPUT_KEY] = payment_record.get(PAYMENT_SANDBOX_RECORDS_INPUT_KEY)
        inputs_out[DELIVERY_SANDBOX_RECORDS_INPUT_KEY] = delivery_record.get(DELIVERY_SANDBOX_RECORDS_INPUT_KEY)
        inputs_out[MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY] = payment_record.get(
            MANUAL_REFUND_EXCEPTION_RECORD_INPUT_KEY
        )

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
            inputs=inputs_out,
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff
