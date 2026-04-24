# Stage: stage8_outreach
# Consumes formal objects: contact_target, outreach_plan, touch_record
# Dependent handoff: H-07-STAGE7-TO-STAGE8, H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/sales/contact_policy_catalog.json, contracts/governance/field_policy_dictionary.json, contracts/release/release_gates.json

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from stage8_outreach.candidate_compliance import (
    H07_AUTHORITATIVE_FIELDS as STAGE8_H07_AUTHORITATIVE_FIELDS,
    build_contact_candidate_carriers,
    build_execution_vendor_payload,
    build_source_vendor_payload,
    execution_action_intent,
    merge_stage7_authoritative_inputs,
    resolution_guard,
    select_stage8_contact_candidate,
    source_capability_family,
)
from stage8_outreach.execution_outbox import build_outreach_execution_outbox_payload
from stage8_outreach.plan_touch import (
    apply_outreach_plan_policy_projection,
    apply_touch_record_policy_projection,
    build_h08_handoff_payload,
    build_outreach_plan_payload,
    build_stage8_inputs_projection,
    build_touch_record_payload,
    build_trace_rules,
    collect_writeback_projection,
    project_next_step_optional,
    project_plan_requires_manual_review,
    project_plan_status,
    project_touch_record_state,
)
from shared.capability_runtime import CapabilityRuntime
from shared.context_packet import ContextPacket
from shared.contract_loader import load_contract
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import (
    build_id,
    ensure_enum,
    ensure_list,
    resolve_bundle,
    utc_now_iso,
)


_STAGE8_STATIC_VALIDATION_ANCHORS = (
    "_stage7_authoritative_inputs(",
    '"opportunity_id":',
    '"touch_record_id":',
    '"response_status":',
    '"saleability_status":',
    '"crm_owner_state":',
    '"next_step_optional": next_step_optional',
    '"written_back_at_optional": written_back_at_optional',
    'inputs_out["opportunity_id"]',
    'inputs_out["touch_record_id"]',
    'inputs_out["response_status"]',
    'inputs_out["saleability_status"]',
    'inputs_out["crm_owner_state"]',
    'inputs_out["next_step_optional"] = touch_record.get("next_step_optional")',
    'inputs_out["written_back_at_optional"] = touch_record.get("written_back_at_optional")',
    'inputs_out["winning_competitor_candidate_id_optional"] = winning_competitor_candidate_id',
    'inputs_out["winning_challenger_profile_id_optional"] = str(winning_challenger_profile_id)',
    'inputs_out["multi_competitor_collection_id_optional"] = str(multi_competitor_collection_id)',
)


class Stage8Service:
    H07_AUTHORITATIVE_FIELDS = STAGE8_H07_AUTHORITATIVE_FIELDS

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)
        self.runtime = CapabilityRuntime(settings)

    def _guard_context(
        self,
        *,
        inputs: Mapping[str, Any],
        release_level: str,
        approval_state: str,
        action_intent: str,
        requested_gate_ids: list[str],
        audit_trail_present: bool,
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
            "gate_conditions": {
                "approval chain present": approval_state in ("APPROVED", "NOT_REQUIRED"),
                "audit trail present": audit_trail_present,
            },
        }

    def _stage8_resolution_policy(self) -> dict[str, Any]:
        return load_contract("contracts/sales/stage8_resolution_policy.json", self.settings)

    @staticmethod
    def _parse_iso_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _format_iso_time(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _build_human_handoff(
        self,
        *,
        response_status: str,
        commercial_urgency_level: str,
        now: str,
    ) -> dict[str, Any] | None:
        policy = self._stage8_resolution_policy().get("humanHandoff", {})
        route = policy.get("routes", {}).get(response_status)
        if not isinstance(route, Mapping):
            return None
        urgency = str(commercial_urgency_level or "NORMAL")
        sla_hours_by_urgency = route.get("slaHoursByUrgency", {})
        try:
            sla_hours = int(sla_hours_by_urgency.get(urgency, sla_hours_by_urgency.get("NORMAL", 24)))
        except (TypeError, ValueError):
            sla_hours = 24
        due_at = self._format_iso_time(self._parse_iso_time(now) + timedelta(hours=sla_hours))
        return {
            "policy_id": str(policy.get("policyId", "stage8_human_handoff_v1")),
            "response_status": response_status,
            "next_step_optional": str(route.get("nextStep", "WAIT")),
            "next_owner_role_optional": str(route.get("nextOwnerRole", "sales_user")),
            "sla_hours_optional": sla_hours,
            "sla_due_at_optional": due_at,
            "reason_optional": str(route.get("reason", "human_handoff_required")),
        }

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage7_bundle = resolve_bundle(payload)
        handoff_validation = self.store.evaluate_handoff_consumer(
            producer_bundle=stage7_bundle,
            consumer_stage=8,
        )
        if handoff_validation and handoff_validation.decision_state == "BLOCK":
            raise ValueError(f"{handoff_validation.semantic_scope} blocked: {handoff_validation.reasons}")
        inputs = stage7_bundle.inputs or {}
        stage7_handoff = stage7_bundle.handoff or {}
        authoritative_inputs = merge_stage7_authoritative_inputs(
            inputs=inputs,
            stage7_handoff=stage7_handoff,
        )
        now = authoritative_inputs.get("now") or inputs.get("now") or utc_now_iso()
        formal_sink_trace = {
            field_name: stage7_handoff.get(field_name, authoritative_inputs.get(field_name, inputs.get(field_name)))
            for field_name in (
                "project_value_score_optional",
                "opportunity_value_score_optional",
                "normalized_price_amount_optional",
                "price_conflict_gate_status_optional",
                "confidence_score_optional",
                "current_action_start_at_optional",
                "current_action_deadline_at_optional",
            )
        }

        saleable_opportunity = stage7_bundle.record("saleable_opportunity")
        legal_action_actor_profile = stage7_bundle.records.get("legal_action_actor_profile")
        procurement_decision_actor_profile = stage7_bundle.records.get(
            "procurement_decision_actor_profile"
        )
        project_id = saleable_opportunity.get("project_id")
        upstream_multi_competitor_collection = stage7_bundle.records.get("multi_competitor_collection")
        if upstream_multi_competitor_collection is None:
            raise ValueError("multi_competitor_collection must be present before Stage8 contact resolution")
        selected_candidate, candidate_trace = select_stage8_contact_candidate(
            settings=self.settings,
            saleable_opportunity=saleable_opportunity,
            legal_action_actor_profile=legal_action_actor_profile,
            procurement_decision_actor_profile=procurement_decision_actor_profile,
            inputs=authoritative_inputs,
            now=now,
        )
        multi_competitor_collection_id = stage7_handoff.get(
            "multi_competitor_collection_id_optional",
            upstream_multi_competitor_collection.get("multi_competitor_collection_id"),
        )
        winning_competitor_candidate_id = stage7_handoff.get(
            "winning_competitor_candidate_id_optional",
            upstream_multi_competitor_collection.get("winning_candidate_id"),
        )
        winning_challenger_profile_id = stage7_handoff.get(
            "winning_challenger_profile_id_optional",
            upstream_multi_competitor_collection.get("winning_challenger_profile_id"),
        )
        contact_candidate_collection_payload, contact_selection_trace_payload, winning_contact_candidate = build_contact_candidate_carriers(
            saleable_opportunity=saleable_opportunity,
            inputs=authoritative_inputs,
            now=now,
            selected_candidate=selected_candidate,
            candidate_trace=candidate_trace,
            multi_competitor_collection_id=str(multi_competitor_collection_id),
            winning_challenger_profile_id=str(winning_challenger_profile_id),
        )
        contact_candidate_collection = self.store.build_record(
            "contact_candidate_collection",
            contact_candidate_collection_payload,
        )
        contact_selection_trace = self.store.build_record(
            "contact_selection_trace",
            contact_selection_trace_payload,
        )
        selected_candidate = {
            **winning_contact_candidate,
        }
        source_merge_review_required = bool(selected_candidate.get("source_merge_review_required", False))
        execution_vendor_candidate = {
            **selected_candidate,
            "execution_vendor_id_optional": inputs.get(
                "execution_vendor_id_optional",
                selected_candidate.get("execution_vendor_id_optional"),
            ),
            "execution_vendor_type_optional": inputs.get(
                "execution_vendor_type_optional",
                selected_candidate.get("execution_vendor_type_optional"),
            ),
            "execution_vendor_role_optional": inputs.get(
                "execution_vendor_role_optional",
                selected_candidate.get("execution_vendor_role_optional"),
            ),
            "execution_fallback_vendor_id_optional": inputs.get(
                "execution_fallback_vendor_id_optional",
                selected_candidate.get("execution_fallback_vendor_id_optional"),
            ),
            "execution_vendor_response_ref_optional": inputs.get(
                "execution_vendor_response_ref_optional",
                selected_candidate.get("execution_vendor_response_ref_optional"),
            ),
        }

        role_cluster = selected_candidate.get(
            "role_cluster",
            authoritative_inputs.get("role_cluster", "PROCUREMENT_DECISION"),
        )
        release_level = authoritative_inputs.get(
            "release_level",
            authoritative_inputs.get("minimum_release_level", "INTERNAL_OPERABLE"),
        )
        source_family = selected_candidate.get(
            "source_family",
            authoritative_inputs.get("source_family", "PROCUREMENT_NOTICE"),
        )
        source_auditability_state = selected_candidate.get(
            "source_auditability_state",
            authoritative_inputs.get("source_auditability_state", "AUDITABLE"),
        )
        response_status = ensure_enum(
            self.store, "response_status", authoritative_inputs.get("response_status", "NO_RESPONSE")
        )
        run_mode = ensure_enum(
            self.store, "run_mode", authoritative_inputs.get("run_mode", "DRY_RUN")
        )
        approval_state = ensure_enum(
            self.store, "approval_state", authoritative_inputs.get("approval_state", "NOT_REQUIRED")
        )
        source_vendor_payload, source_vendor_trace = build_source_vendor_payload(
            settings=self.settings,
            store=self.store,
            candidate=selected_candidate,
            project_id=project_id,
        )
        execution_vendor_payload, execution_vendor_trace = build_execution_vendor_payload(
            settings=self.settings,
            store=self.store,
            candidate=execution_vendor_candidate,
            project_id=project_id,
        )
        source_resolution_metadata, source_resolution_reasons, source_resolution_blocked, source_resolution_review = resolution_guard(
            source_vendor_trace,
            default_policy_state=str(authoritative_inputs.get("source_policy_state", "SOURCE_POLICY_ACTIVE")),
            blocked_reason="source_vendor_resolution_blocked",
        )
        execution_resolution_metadata, execution_resolution_reasons, execution_resolution_blocked, execution_resolution_review = resolution_guard(
            execution_vendor_trace,
            default_policy_state=str(execution_vendor_trace.get("policy_state", "PREVIEW_ONLY")),
            blocked_reason="execution_vendor_resolution_blocked",
        )
        context = ContextPacket.from_records(
            capability_mode="stage8_outreach",
            stage=8,
            project_id=project_id,
            records={"saleable_opportunity": saleable_opportunity},
            inputs={
                **dict(authoritative_inputs),
                **dict(selected_candidate),
                **formal_sink_trace,
                "now": now,
                "role_cluster": role_cluster,
                "source_family": source_family,
                "source_auditability_state": source_auditability_state,
                "response_status": response_status,
                "release_level": release_level,
                "approval_state": approval_state,
                "execution_policy_state": execution_vendor_trace.get("policy_state", "PREVIEW_ONLY"),
                **source_vendor_payload,
                **execution_vendor_payload,
            },
        )
        permission_checks = [
            {
                "capability_family": source_capability_family(source_vendor_payload["source_vendor_role"]),
                "requested_action": "INTERNAL_SOURCE_READ",
                "target_id": source_vendor_payload["source_vendor_id_optional"],
                "target_type": "source_vendor",
                "target_role": source_vendor_payload["source_vendor_role"],
                "release_level": release_level,
                "approval_state": approval_state,
                "metadata": source_resolution_metadata,
            },
            {
                "capability_family": "execution_vendor",
                "requested_action": execution_action_intent(run_mode),
                "target_id": execution_vendor_payload["execution_vendor_id_optional"],
                "target_type": "execution_vendor",
                "target_role": execution_vendor_payload["execution_vendor_role_optional"],
                "release_level": release_level,
                "approval_state": approval_state,
                "metadata": execution_resolution_metadata,
            },
            {
                "capability_family": "stage8_execution",
                "requested_action": execution_action_intent(run_mode),
                "release_level": release_level,
                "approval_state": approval_state,
            },
        ]
        if authoritative_inputs.get("model_provider_id_optional"):
            permission_checks.append(
                {
                    "capability_family": "model_provider",
                    "requested_action": "PREVIEW_ONLY",
                    "target_id": authoritative_inputs.get("model_provider_id_optional"),
                    "target_type": "model_provider",
                    "target_role": authoritative_inputs.get("model_provider_role_optional", "GENERAL_ASSIST_MODEL"),
                    "release_level": release_level,
                    "approval_state": approval_state,
                }
            )
        if authoritative_inputs.get("tool_provider_id_optional"):
            permission_checks.append(
                {
                    "capability_family": "tool_provider",
                    "requested_action": "PREVIEW_ONLY",
                    "target_id": authoritative_inputs.get("tool_provider_id_optional"),
                    "target_type": "tool_provider",
                    "target_role": authoritative_inputs.get("tool_provider_role_optional", "INTERNAL_OBJECT_QUERY_TOOL"),
                    "release_level": release_level,
                    "approval_state": approval_state,
                }
            )
        permission_state = self.runtime.resolve_permissions(context, permission_checks)
        runtime_state = self.runtime.run(context, state=permission_state)

        candidate_permission_families = {"external_source", "contact_enrichment"}
        candidate_permission_blocked = any(
            entry.get("event") == "capability_resolution"
            and entry.get("capability_family") in candidate_permission_families
            and entry.get("decision_state") == "BLOCK"
            for entry in runtime_state.capability_trace
        )
        candidate_permission_review = any(
            entry.get("event") == "capability_resolution"
            and entry.get("capability_family") in candidate_permission_families
            and entry.get("decision_state") == "REVIEW"
            for entry in runtime_state.capability_trace
        )
        emergency_short_circuit = bool(runtime_state.permission_short_circuit)

        blocking_reasons = ensure_list(authoritative_inputs.get("blocking_reasons", []))
        blocking_reasons.extend(source_resolution_reasons)
        blocking_reasons.extend(execution_resolution_reasons)
        blocking_reasons.extend(runtime_state.blocked_reasons)
        blocking_reasons.extend(runtime_state.review_reasons)
        blocking_reasons.extend(runtime_state.fallback_reasons)
        blocking_reasons.extend(runtime_state.permission_blocked_reasons)
        blocking_reasons.extend(runtime_state.permission_review_reasons)
        source_conflict_present = bool(selected_candidate.get("source_conflict_flag", False))
        contact_target_status = runtime_state.resolve("contact_target_status", "REVIEW_REQUIRED")
        if source_resolution_blocked or emergency_short_circuit or candidate_permission_blocked:
            contact_target_status = "BLOCKED"
        elif (source_resolution_review or candidate_permission_review or source_conflict_present) and contact_target_status == "ELIGIBLE":
            contact_target_status = "REVIEW_REQUIRED"
        if source_merge_review_required and contact_target_status == "ELIGIBLE":
            contact_target_status = "REVIEW_REQUIRED"
            blocking_reasons.append("source_merge_requires_manual_review")
        if source_conflict_present:
            if contact_target_status == "ELIGIBLE":
                contact_target_status = "REVIEW_REQUIRED"
            blocking_reasons.append("source_conflict_requires_manual_review")
        action_intent = execution_action_intent(run_mode)
        audit_trail_present = bool(source_vendor_payload["source_audit_ref"] and source_vendor_payload["query_trace_id"])
        contact_gate_ids = ["internal_review_release"]
        if authoritative_inputs.get("person_name_optional") not in (None, "", "UNKNOWN"):
            contact_gate_ids.append("high_restriction_contact_release")
        contact_guard_context = self._guard_context(
            inputs=authoritative_inputs,
            release_level=release_level,
            approval_state=approval_state,
            action_intent=action_intent,
            requested_gate_ids=contact_gate_ids,
            audit_trail_present=audit_trail_present,
        )

        contact_payload = {
            "contact_target_id": build_id("CT", project_id),
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "project_id": project_id,
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "org_name": selected_candidate.get("org_name", "DEFAULT_ORG"),
            "org_type": selected_candidate.get("org_type", "ENTERPRISE"),
            "person_name_optional": selected_candidate.get("person_name_optional", "UNKNOWN"),
            "role_cluster": ensure_enum(self.store, "actor_role_cluster", role_cluster),
            "public_contact_source": selected_candidate.get("public_contact_source", "PUBLIC_SITE"),
            "source_family": source_family,
            "source_auditability_state": source_auditability_state,
            "contact_channel": selected_candidate.get("contact_channel", "EMAIL"),
            "channel_family": ensure_enum(
                self.store,
                "channel_family",
                selected_candidate.get(
                    "channel_family",
                    authoritative_inputs.get("channel_family", inputs.get("channel_family")),
                ),
            ),
            "contact_target_status": contact_target_status,
            "contact_validity_status": ensure_enum(
                self.store,
                "contact_validity_status",
                selected_candidate.get(
                    "contact_validity_status",
                    authoritative_inputs.get("contact_validity_status", "UNKNOWN"),
                ),
            ),
            "contact_legal_basis": ensure_enum(
                self.store,
                "contact_legal_basis",
                selected_candidate.get(
                    "contact_legal_basis",
                    authoritative_inputs.get("contact_legal_basis", "REVIEW_REQUIRED"),
                ),
            ),
            "reasonable_expectation_status": ensure_enum(
                self.store,
                "reasonable_expectation_status",
                selected_candidate.get(
                    "reasonable_expectation_status",
                    authoritative_inputs.get("reasonable_expectation_status", "UNKNOWN"),
                ),
            ),
            "channel_policy_status": ensure_enum(
                self.store,
                "channel_policy_status",
                selected_candidate.get(
                    "channel_policy_status",
                    authoritative_inputs.get("channel_policy_status", "REVIEW"),
                ),
            ),
            "frequency_policy_state": ensure_enum(
                self.store,
                "frequency_policy_state",
                selected_candidate.get(
                    "frequency_policy_state",
                    authoritative_inputs.get("frequency_policy_state", "REVIEW"),
                ),
            ),
            "opt_out_state": ensure_enum(
                self.store,
                "opt_out_state",
                runtime_state.resolve(
                    "opt_out_state",
                    selected_candidate.get(
                        "opt_out_state",
                        authoritative_inputs.get("opt_out_state", "PENDING_CONFIRMATION"),
                    ),
                ),
            ),
            "quiet_hours_policy_state": ensure_enum(
                self.store,
                "quiet_hours_policy_state",
                selected_candidate.get(
                    "quiet_hours_policy_state",
                    authoritative_inputs.get("quiet_hours_policy_state", "REVIEW"),
                ),
            ),
            "auto_contact_allowed": bool(runtime_state.resolve("auto_contact_allowed", False))
            and not runtime_state.permission_blocked_reasons
            and contact_target_status == "ELIGIBLE"
            and not source_merge_review_required
            and not source_conflict_present,
            "requires_manual_review": bool(
                emergency_short_circuit
                or contact_target_status in ("REVIEW_REQUIRED", "BLOCKED")
                or candidate_permission_review
                or candidate_permission_blocked
                or source_merge_review_required
                or source_conflict_present
            ),
            "blocking_reasons": blocking_reasons,
            "last_evaluated_at": selected_candidate.get("last_evaluated_at", now),
            "primary_contact_flag": bool(selected_candidate.get("primary_contact_flag", runtime_state.resolve("primary_contact_flag", False))),
            "contact_priority_score": int(selected_candidate.get("contact_priority_score", runtime_state.resolve("contact_priority_score", 0))),
            "contact_priority_reason_tags": ensure_list(selected_candidate.get("contact_priority_reason_tags", runtime_state.resolve("contact_priority_reason_tags", []))),
            "contact_candidate_rank": int(selected_candidate.get("contact_candidate_rank", runtime_state.resolve("contact_candidate_rank", 99))),
            "contact_selection_reason": str(selected_candidate.get("contact_selection_reason", runtime_state.resolve("contact_selection_reason", "manual review required"))),
            "contact_conflict_flag": bool(selected_candidate.get("contact_conflict_flag", runtime_state.resolve("contact_conflict_flag", False))),
            "contact_conflict_reason": str(selected_candidate.get("contact_conflict_reason", runtime_state.resolve("contact_conflict_reason", "no_conflict"))),
            **source_vendor_payload,
        }
        contact_guard = self.store.evaluate_runtime_guards("contact_target", contact_payload, contact_guard_context)
        runtime_state.add_governance_guard(contact_guard)
        blocking_reasons.extend(contact_guard.reasons)
        if contact_guard.decision_state == "BLOCK":
            contact_payload["contact_target_status"] = "BLOCKED"
            contact_payload["auto_contact_allowed"] = False
            contact_payload["requires_manual_review"] = True
        elif contact_guard.decision_state == "REVIEW" and contact_payload["contact_target_status"] == "ELIGIBLE":
            contact_payload["contact_target_status"] = "REVIEW_REQUIRED"
            contact_payload["auto_contact_allowed"] = False
            contact_payload["requires_manual_review"] = True
        contact_semantic = self.store.evaluate_object_semantics(
            stage=8,
            object_type="contact_target",
            payload=contact_payload,
            semantic_context={
                "upstream_saleability_status": saleable_opportunity.get("saleability_status"),
            },
        )
        if contact_semantic:
            runtime_state.add_semantic_validation(contact_semantic)
            if contact_semantic.decision_state == "BLOCK":
                contact_payload["contact_target_status"] = "BLOCKED"
                contact_payload["auto_contact_allowed"] = False
                contact_payload["requires_manual_review"] = True
            elif contact_semantic.decision_state == "REVIEW" and contact_payload["contact_target_status"] == "ELIGIBLE":
                contact_payload["contact_target_status"] = "REVIEW_REQUIRED"
                contact_payload["auto_contact_allowed"] = False
                contact_payload["requires_manual_review"] = True

        contact_target = self.store.build_record(
            "contact_target",
            contact_payload,
        )

        plan_status = project_plan_status(
            runtime_state=runtime_state,
            execution_resolution_blocked=execution_resolution_blocked,
            execution_resolution_review=execution_resolution_review,
            source_merge_review_required=source_merge_review_required,
            source_conflict_present=source_conflict_present,
            run_mode=run_mode,
            approval_state=approval_state,
        )
        plan_requires_manual_review = project_plan_requires_manual_review(
            contact_target=contact_target,
            plan_status=plan_status,
            approval_state=approval_state,
        )

        outreach_gate_ids = ["internal_review_release"]
        if action_intent in ("APPROVAL_EXECUTION", "LIVE_EXECUTION"):
            outreach_gate_ids.append("high_restriction_contact_release")
        outreach_guard_context = self._guard_context(
            inputs=authoritative_inputs,
            release_level=release_level,
            approval_state=approval_state,
            action_intent=action_intent,
            requested_gate_ids=outreach_gate_ids,
            audit_trail_present=bool(execution_vendor_payload["execution_trace_id_optional"]),
        )
        runtime_writeback_projection = collect_writeback_projection(runtime_state)
        outreach_payload = build_outreach_plan_payload(
            store=self.store,
            runtime_state=runtime_state,
            project_id=project_id,
            saleable_opportunity=saleable_opportunity,
            contact_target=contact_target,
            authoritative_inputs=authoritative_inputs,
            now=now,
            run_mode=run_mode,
            approval_state=approval_state,
            plan_status=plan_status,
            plan_requires_manual_review=plan_requires_manual_review,
            execution_vendor_payload=execution_vendor_payload,
            writeback_projection=runtime_writeback_projection,
        )
        outreach_payload = apply_outreach_plan_policy_projection(
            store=self.store,
            runtime_state=runtime_state,
            outreach_payload=outreach_payload,
            outreach_guard_context=outreach_guard_context,
            saleable_opportunity=saleable_opportunity,
            contact_payload=contact_payload,
            run_mode=run_mode,
            approval_state=approval_state,
            writeback_targets=runtime_writeback_projection["writeback_targets"],
        )

        outreach_plan = self.store.build_record(
            "outreach_plan",
            outreach_payload,
        )

        trace_rules = build_trace_rules(runtime_state)
        stop_reason_optional = runtime_state.resolve(
            "stop_reason_optional",
            authoritative_inputs.get("stop_reason_optional"),
        )
        retry_scheduled_optional = bool(
            runtime_state.resolve("retry_scheduled_optional", False)
        )
        human_handoff = self._build_human_handoff(
            response_status=response_status,
            commercial_urgency_level=str(
                authoritative_inputs.get("commercial_urgency_level")
                or authoritative_inputs.get("commercial_urgency_level_optional")
                or "NORMAL"
            ),
            now=now,
        )
        next_step_optional = project_next_step_optional(
            runtime_state=runtime_state,
            authoritative_inputs=authoritative_inputs,
            human_handoff=human_handoff,
        )
        written_back_at_optional = runtime_state.resolve(
            "written_back_at_optional",
            authoritative_inputs.get("written_back_at_optional", now),
        )
        touch_state = project_touch_record_state(
            runtime_state=runtime_state,
            plan_status=plan_status,
            run_mode=run_mode,
            response_status=response_status,
        )

        touch_guard_context = self._guard_context(
            inputs=authoritative_inputs,
            release_level=release_level,
            approval_state=approval_state,
            action_intent=action_intent,
            requested_gate_ids=["internal_review_release"],
            audit_trail_present=bool(execution_vendor_payload["execution_trace_id_optional"] and written_back_at_optional),
        )
        touch_writeback_projection = collect_writeback_projection(runtime_state)
        touch_payload = build_touch_record_payload(
            store=self.store,
            runtime_state=runtime_state,
            project_id=project_id,
            saleable_opportunity=saleable_opportunity,
            contact_target=contact_target,
            outreach_plan=outreach_plan,
            authoritative_inputs=authoritative_inputs,
            now=now,
            response_status=response_status,
            touch_state=touch_state,
            next_step_optional=next_step_optional,
            stop_reason_optional=stop_reason_optional,
            written_back_at_optional=written_back_at_optional,
            retry_scheduled_optional=retry_scheduled_optional,
            execution_vendor_payload=execution_vendor_payload,
            writeback_projection=touch_writeback_projection,
        )
        touch_payload = apply_touch_record_policy_projection(
            store=self.store,
            runtime_state=runtime_state,
            touch_payload=touch_payload,
            touch_guard_context=touch_guard_context,
            outreach_payload=outreach_payload,
            saleable_opportunity=saleable_opportunity,
            outreach_plan=outreach_plan,
            run_mode=run_mode,
            approval_state=approval_state,
            human_handoff=human_handoff,
        )

        touch_record = self.store.build_record(
            "touch_record",
            touch_payload,
        )
        outreach_execution_outbox = build_outreach_execution_outbox_payload(
            runtime_state=runtime_state,
            contact_target=contact_target,
            outreach_plan=outreach_plan,
            touch_record=touch_record,
            authoritative_inputs=authoritative_inputs,
            execution_vendor_payload=execution_vendor_payload,
            execution_vendor_trace=execution_vendor_trace,
            now=now,
            run_mode=run_mode,
            approval_state=approval_state,
        )

        handoff = build_h08_handoff_payload(
            project_id=project_id,
            saleable_opportunity=saleable_opportunity,
            contact_candidate_collection=contact_candidate_collection,
            contact_selection_trace=contact_selection_trace,
            contact_target=contact_target,
            outreach_plan=outreach_plan,
            touch_record=touch_record,
            outreach_execution_outbox=outreach_execution_outbox,
            human_handoff=human_handoff,
            runtime_state=runtime_state,
        )

        inputs_out = build_stage8_inputs_projection(
            authoritative_inputs=authoritative_inputs,
            original_inputs=inputs,
            h07_authoritative_fields=self.H07_AUTHORITATIVE_FIELDS,
            saleable_opportunity=saleable_opportunity,
            outreach_plan=outreach_plan,
            touch_record=touch_record,
            outreach_execution_outbox=outreach_execution_outbox,
            human_handoff=human_handoff,
            runtime_state=runtime_state,
            multi_competitor_collection_id=str(multi_competitor_collection_id),
            winning_competitor_candidate_id=winning_competitor_candidate_id,
            winning_challenger_profile_id=str(winning_challenger_profile_id),
            candidate_trace=candidate_trace,
            contact_candidate_collection=contact_candidate_collection,
            contact_selection_trace=contact_selection_trace,
            source_vendor_trace=source_vendor_trace,
            execution_vendor_trace=execution_vendor_trace,
            formal_sink_trace=formal_sink_trace,
        )

        return StageBundle(
            stage=8,
            records={
                "saleable_opportunity": saleable_opportunity,
                "contact_target": contact_target,
                "outreach_plan": outreach_plan,
                "touch_record": touch_record,
            },
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff
