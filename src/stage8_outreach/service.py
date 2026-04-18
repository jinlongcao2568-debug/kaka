# Stage: stage8_outreach
# Consumes formal objects: contact_target, outreach_plan, touch_record
# Dependent handoff: H-07-STAGE7-TO-STAGE8, H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/sales/contact_policy_catalog.json, contracts/governance/field_policy_dictionary.json, contracts/release/release_gates.json

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from stage8_outreach.resolution import (
    resolve_execution_vendor,
    resolve_source_vendor,
    select_contact_candidate,
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


class Stage8Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)
        self.runtime = CapabilityRuntime(settings)

    def _source_vendor_payload(self, candidate: Mapping[str, Any], project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        resolved = resolve_source_vendor(
            settings=self.settings,
            candidate=candidate,
            project_id=project_id,
        )
        trace = dict(resolved.pop("source_resolution_trace", {}))
        payload = {
            **resolved,
            "source_vendor_type_optional": ensure_enum(
                self.store, "vendor_type", resolved.get("source_vendor_type_optional", "SOURCE_VENDOR")
            ),
            "source_vendor_role": ensure_enum(
                self.store, "vendor_role", resolved.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE")
            ),
        }
        return payload, trace

    def _execution_vendor_payload(self, candidate: Mapping[str, Any], project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        resolved = resolve_execution_vendor(
            settings=self.settings,
            candidate=candidate,
            project_id=project_id,
        )
        trace = dict(resolved.pop("execution_resolution_trace", {}))
        payload = {
            **resolved,
            "execution_vendor_type_optional": ensure_enum(
                self.store, "vendor_type", resolved.get("execution_vendor_type_optional", "EXECUTION_VENDOR")
            ),
            "execution_vendor_role_optional": ensure_enum(
                self.store, "vendor_role", resolved.get("execution_vendor_role_optional", "EXECUTION_VENDOR")
            ),
        }
        return payload, trace

    def _source_capability_family(self, source_vendor_role: str) -> str:
        if source_vendor_role == "CONTACT_ENRICHMENT_SOURCE":
            return "contact_enrichment"
        return "external_source"

    def _execution_action_intent(self, run_mode: str) -> str:
        return {
            "DRY_RUN": "DRY_RUN",
            "APPROVAL_RUN": "APPROVAL_EXECUTION",
            "REAL_RUN": "LIVE_EXECUTION",
        }.get(run_mode, "PREVIEW_ONLY")

    def _resolution_guard(
        self,
        trace: Mapping[str, Any],
        *,
        default_policy_state: str,
        blocked_reason: str,
    ) -> tuple[dict[str, Any], list[str], bool, bool]:
        resolution_state = str(trace.get("decision_state", "ALLOW")).upper()
        unresolved_reason = str(trace.get("unresolved_reason_optional") or "")
        metadata = {
            "policy_state": str(trace.get("policy_state") or default_policy_state),
        }
        reasons = [unresolved_reason or blocked_reason] if resolution_state == "BLOCK" else []
        if resolution_state == "BLOCK":
            metadata.update(
                {
                    "current_status": "BLOCKED",
                    "policy_state": "BLOCKED",
                    "override_mode": "PERMANENTLY_BLOCKED",
                }
            )
        return metadata, reasons, resolution_state == "BLOCK", resolution_state == "REVIEW"

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

    def _governed_metadata(
        self,
        *,
        runtime_state: Any,
        requested_delivery_surface: str,
        projection_mode: str,
        run_mode: str,
        approval_state: str,
        writeback_targets: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "requested_delivery_surface": requested_delivery_surface,
            "projection_mode": projection_mode,
            "run_mode": run_mode,
            "approval_state": approval_state,
            "permission_decision_state": runtime_state.permission_decision_state,
            "governance_decision_state": runtime_state.governance_decision_state,
            "semantic_decision_state": runtime_state.semantic_decision_state,
            "policy_decision_state": runtime_state.decision_state,
            "candidate_compliance_decision": runtime_state.resolve("candidate_compliance_decision"),
            "execution_compliance_decision": runtime_state.resolve("execution_compliance_decision"),
            "stop_semantics": runtime_state.resolve("stop_semantics"),
            "permission_trace": runtime_state.capability_trace,
            "governance_trace": runtime_state.governance_trace,
            "semantic_trace": runtime_state.semantic_trace,
            "writeback_targets": ensure_list(writeback_targets),
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

    def _contact_candidate_base(self, inputs: Mapping[str, Any], now: str) -> dict[str, Any]:
        return {
            "candidate_id": str(inputs.get("candidate_id", "single-input-candidate")),
            "org_name": inputs.get("org_name", "DEFAULT_ORG"),
            "org_type": inputs.get("org_type", "ENTERPRISE"),
            "person_name_optional": inputs.get("person_name_optional", "UNKNOWN"),
            "role_cluster": inputs.get("role_cluster", "PROCUREMENT_DECISION"),
            "public_contact_source": inputs.get("public_contact_source", "PUBLIC_SITE"),
            "source_family": inputs.get("source_family", "PROCUREMENT_NOTICE"),
            "source_auditability_state": inputs.get("source_auditability_state", "AUDITABLE"),
            "contact_channel": inputs.get("contact_channel", "EMAIL"),
            "channel_family": inputs.get("channel_family", "ORG_EMAIL"),
            "contact_validity_status": inputs.get("contact_validity_status", "UNKNOWN"),
            "contact_legal_basis": inputs.get("contact_legal_basis", "REVIEW_REQUIRED"),
            "reasonable_expectation_status": inputs.get("reasonable_expectation_status", "UNKNOWN"),
            "channel_policy_status": inputs.get("channel_policy_status", "REVIEW"),
            "frequency_policy_state": inputs.get("frequency_policy_state", "REVIEW"),
            "opt_out_state": inputs.get("opt_out_state", "PENDING_CONFIRMATION"),
            "quiet_hours_policy_state": inputs.get("quiet_hours_policy_state", "REVIEW"),
            "source_vendor_role": inputs.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE"),
            "last_evaluated_at": inputs.get("last_evaluated_at", now),
        }

    def _build_reselect_history(
        self,
        *,
        inputs: Mapping[str, Any],
        winning_contact_candidate_id: str,
        now: str,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        previous_candidate_id = (
            inputs.get("previous_contact_candidate_id_optional")
            or inputs.get("last_contact_candidate_id_optional")
            or inputs.get("previous_primary_contact_candidate_id_optional")
        )
        reselect_reason = inputs.get("reselect_reason_optional")
        if not reselect_reason:
            reselect_reason = {
                "WRONG_ROLE": "wrong_role_reselect_required",
                "INVALID_CONTACT": "invalid_contact_reselect_required",
                "OPPORTUNITY_CHANGED": "opportunity_changed_reselect_required",
                "DECLINED": "declined_contact_reselect_optional",
                "NO_RESPONSE": "no_response_reselect_optional",
            }.get(str(inputs.get("response_status", "")))
        if not previous_candidate_id or not reselect_reason or str(previous_candidate_id) == winning_contact_candidate_id:
            return (str(reselect_reason) if reselect_reason else None), []
        return (
            str(reselect_reason),
            [
                {
                    "reselect_from_candidate_id": str(previous_candidate_id),
                    "reselect_to_candidate_id": winning_contact_candidate_id,
                    "reselect_reason": str(reselect_reason),
                    "trigger_response_status": str(inputs.get("response_status", "UNKNOWN")),
                    "recorded_at": now,
                }
            ],
        )

    def _build_contact_candidate_carriers(
        self,
        *,
        saleable_opportunity: Mapping[str, Any],
        inputs: Mapping[str, Any],
        now: str,
        selected_candidate: Mapping[str, Any],
        candidate_trace: Mapping[str, Any],
        multi_competitor_collection_id: str,
        winning_challenger_profile_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        project_id = str(saleable_opportunity.get("project_id"))
        saleable_opportunity_id = str(saleable_opportunity.get("opportunity_id"))
        base = self._contact_candidate_base(inputs, now)
        resolved_candidates = candidate_trace.get("merged_candidates")
        raw_candidates = (
            list(resolved_candidates)
            if isinstance(resolved_candidates, list) and resolved_candidates
            else [dict(selected_candidate)]
        )
        candidate_lookup: dict[str, dict[str, Any]] = {}
        for index, raw_candidate in enumerate(raw_candidates, start=1):
            if not isinstance(raw_candidate, Mapping):
                continue
            candidate_id = str(raw_candidate.get("candidate_id", f"candidate-{index}"))
            candidate_lookup[candidate_id] = {
                **base,
                **dict(raw_candidate),
                "candidate_id": candidate_id,
            }
        selected_candidate_id = str(
            candidate_trace.get("selected_candidate_id", selected_candidate.get("candidate_id", base["candidate_id"]))
        )
        ordered_trace_entries = list(candidate_trace.get("ranked_candidates", []))
        if not ordered_trace_entries:
            ordered_trace_entries = [
                {
                    "candidate_id": selected_candidate_id,
                    "score": int(selected_candidate.get("contact_priority_score", 0)),
                    "role_cluster": selected_candidate.get("role_cluster", base["role_cluster"]),
                    "channel_family": selected_candidate.get("channel_family", base["channel_family"]),
                    "organization_channel": True,
                    "blocked": False,
                }
            ]

        candidate_list: list[dict[str, Any]] = []
        trace_entries: list[dict[str, Any]] = []
        for rank, trace_entry in enumerate(ordered_trace_entries, start=1):
            candidate_id = str(trace_entry.get("candidate_id", f"candidate-{rank}"))
            raw_candidate = candidate_lookup.get(candidate_id, {**base, **dict(selected_candidate), "candidate_id": candidate_id})
            selected_flag = candidate_id == selected_candidate_id
            candidate_item = {
                "candidate_id": candidate_id,
                "org_name": str(raw_candidate.get("org_name", base["org_name"])),
                "org_type": str(raw_candidate.get("org_type", base["org_type"])),
                "person_name_optional": str(raw_candidate.get("person_name_optional", base["person_name_optional"])),
                "role_cluster": str(raw_candidate.get("role_cluster", base["role_cluster"])),
                "public_contact_source": str(raw_candidate.get("public_contact_source", base["public_contact_source"])),
                "contact_channel": str(raw_candidate.get("contact_channel", base["contact_channel"])),
                "channel_family": str(raw_candidate.get("channel_family", base["channel_family"])),
                "source_family": str(raw_candidate.get("source_family", base["source_family"])),
                "source_auditability_state": str(raw_candidate.get("source_auditability_state", base["source_auditability_state"])),
                "merge_key": str(raw_candidate.get("merge_key", f"candidate_identity::{candidate_id}")),
                "merged_candidate_ids": ensure_list(raw_candidate.get("merged_candidate_ids", [candidate_id])),
                "merged_source_roles": ensure_list(raw_candidate.get("merged_source_roles", [raw_candidate.get("source_vendor_role", "PUBLIC_OFFICIAL_SOURCE")])),
                "merged_source_vendor_ids_optional": ensure_list(raw_candidate.get("merged_source_vendor_ids_optional", [])),
                "formal_merge_state": str(raw_candidate.get("formal_merge_state", "NOT_REQUIRED_SINGLE_SOURCE")),
                "source_conflict_flag": bool(raw_candidate.get("source_conflict_flag", False)),
                "source_conflict_reason": str(raw_candidate.get("source_conflict_reason", "no_source_conflict")),
                "source_conflict_fields": ensure_list(raw_candidate.get("source_conflict_fields", [])),
                "source_merge_review_required": bool(raw_candidate.get("source_merge_review_required", False)),
                "contact_priority_score": int(trace_entry.get("score", raw_candidate.get("contact_priority_score", 0))),
                "contact_priority_reason_tags": ensure_list(
                    raw_candidate.get(
                        "contact_priority_reason_tags",
                        selected_candidate.get("contact_priority_reason_tags", [] if not selected_flag else []),
                    )
                ),
                "contact_candidate_rank": rank,
                "primary_contact_flag": selected_flag and bool(selected_candidate.get("primary_contact_flag", False)),
                "contact_conflict_flag": selected_flag and bool(candidate_trace.get("conflict_flag", False)),
                "contact_conflict_reason": str(
                    candidate_trace.get("conflict_reason", "single candidate")
                    if selected_flag and candidate_trace.get("conflict_flag", False)
                    else "no_conflict"
                ),
                "contact_selection_reason": str(
                    selected_candidate.get("contact_selection_reason", "resolver selection")
                    if selected_flag
                    else raw_candidate.get("contact_selection_reason", "ranked candidate")
                ),
                "contactability_snapshot": {
                    "contact_validity_status": str(raw_candidate.get("contact_validity_status", base["contact_validity_status"])),
                    "contact_legal_basis": str(raw_candidate.get("contact_legal_basis", base["contact_legal_basis"])),
                    "reasonable_expectation_status": str(raw_candidate.get("reasonable_expectation_status", base["reasonable_expectation_status"])),
                    "channel_policy_status": str(raw_candidate.get("channel_policy_status", base["channel_policy_status"])),
                    "frequency_policy_state": str(raw_candidate.get("frequency_policy_state", base["frequency_policy_state"])),
                    "opt_out_state": str(raw_candidate.get("opt_out_state", base["opt_out_state"])),
                    "quiet_hours_policy_state": str(raw_candidate.get("quiet_hours_policy_state", base["quiet_hours_policy_state"])),
                },
                "selected_flag": selected_flag,
                "blocked": bool(trace_entry.get("blocked", False)),
            }
            candidate_list.append(candidate_item)
            trace_entries.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_rank": rank,
                    "score": int(trace_entry.get("score", candidate_item["contact_priority_score"])),
                    "role_cluster": str(trace_entry.get("role_cluster", candidate_item["role_cluster"])),
                    "channel_family": str(trace_entry.get("channel_family", candidate_item["channel_family"])),
                    "merge_key": str(trace_entry.get("merge_key", candidate_item["merge_key"])),
                    "merged_candidate_ids": ensure_list(trace_entry.get("merged_candidate_ids", candidate_item["merged_candidate_ids"])),
                    "merged_source_roles": ensure_list(trace_entry.get("merged_source_roles", candidate_item["merged_source_roles"])),
                    "source_conflict_flag": bool(trace_entry.get("source_conflict_flag", candidate_item["source_conflict_flag"])),
                    "source_conflict_reason_optional": (
                        str(trace_entry.get("source_conflict_reason_optional", candidate_item["source_conflict_reason"]))
                        if bool(trace_entry.get("source_conflict_flag", candidate_item["source_conflict_flag"]))
                        else None
                    ),
                    "source_merge_review_required": bool(
                        trace_entry.get("source_merge_review_required", candidate_item["source_merge_review_required"])
                    ),
                    "organization_channel": bool(trace_entry.get("organization_channel", False)),
                    "blocked": bool(trace_entry.get("blocked", False)),
                    "selected_flag": selected_flag,
                }
            )

        winning_candidate = next(
            (item for item in candidate_list if item["candidate_id"] == selected_candidate_id),
            candidate_list[0],
        )
        winning_candidate_raw = candidate_lookup.get(
            winning_candidate["candidate_id"],
            {**base, **dict(selected_candidate), "candidate_id": winning_candidate["candidate_id"]},
        )
        winning_candidate_snapshot = {
            **winning_candidate_raw,
            **winning_candidate["contactability_snapshot"],
            "contact_priority_score": winning_candidate["contact_priority_score"],
            "contact_priority_reason_tags": winning_candidate["contact_priority_reason_tags"],
            "contact_candidate_rank": winning_candidate["contact_candidate_rank"],
            "primary_contact_flag": winning_candidate["primary_contact_flag"],
            "contact_conflict_flag": winning_candidate["contact_conflict_flag"],
            "contact_conflict_reason": winning_candidate["contact_conflict_reason"],
            "contact_selection_reason": winning_candidate["contact_selection_reason"],
            "merge_key": winning_candidate["merge_key"],
            "merged_candidate_ids": winning_candidate["merged_candidate_ids"],
            "merged_source_roles": winning_candidate["merged_source_roles"],
            "merged_source_vendor_ids_optional": winning_candidate["merged_source_vendor_ids_optional"],
            "formal_merge_state": winning_candidate["formal_merge_state"],
            "source_conflict_flag": winning_candidate["source_conflict_flag"],
            "source_conflict_reason": winning_candidate["source_conflict_reason"],
            "source_conflict_fields": winning_candidate["source_conflict_fields"],
            "source_merge_review_required": winning_candidate["source_merge_review_required"],
        }
        reselect_reason, reselect_history = self._build_reselect_history(
            inputs=inputs,
            winning_contact_candidate_id=winning_candidate["candidate_id"],
            now=now,
        )
        collection_id = build_id("CCOLL", project_id)
        selection_trace_id = build_id("CTRACE", project_id)
        collection_payload = {
            "contact_candidate_collection_id": collection_id,
            "saleable_opportunity_id": saleable_opportunity_id,
            "project_id": project_id,
            "multi_competitor_collection_id": multi_competitor_collection_id,
            "winning_challenger_profile_id": winning_challenger_profile_id,
            "candidate_list": candidate_list,
            "winning_contact_candidate_id": winning_candidate["candidate_id"],
            "selection_trace_id": selection_trace_id,
            "merge_policy_id": str(candidate_trace.get("merge_policy_id", "contact_candidate_formal_merge_v1")),
            "dedupe_applied": bool(candidate_trace.get("dedupe_applied", False)),
            "source_conflict_candidate_count": int(candidate_trace.get("source_conflict_candidate_count", 0)),
            "source_merge_review_required_count": int(
                candidate_trace.get("source_merge_review_required_count", 0)
            ),
            "reselect_reason_optional": reselect_reason,
            "reselect_history": reselect_history,
            "created_by_stage": 8,
            "downstream_consumer": [
                "contact_target",
                "outreach_plan",
                "touch_record",
            ],
        }
        trace_payload = {
            "contact_selection_trace_id": selection_trace_id,
            "contact_candidate_collection_id": collection_id,
            "saleable_opportunity_id": saleable_opportunity_id,
            "multi_competitor_collection_id": multi_competitor_collection_id,
            "winning_contact_candidate_id": winning_candidate["candidate_id"],
            "selection_policy_id": "contact_candidate_pool_equivalent_v1",
            "selection_basis": [
                "higher_score",
                "organization_channel_first",
                "auditability_auditable_first",
                "newer_last_evaluated_at_first",
            ],
            "merge_policy_id": str(candidate_trace.get("merge_policy_id", "contact_candidate_formal_merge_v1")),
            "dedupe_applied": bool(candidate_trace.get("dedupe_applied", False)),
            "source_conflict_candidate_count": int(candidate_trace.get("source_conflict_candidate_count", 0)),
            "source_merge_review_required_count": int(
                candidate_trace.get("source_merge_review_required_count", 0)
            ),
            "trace_entries": trace_entries,
            "winning_selection_reason": winning_candidate["contact_selection_reason"],
            "conflict_flag": bool(candidate_trace.get("conflict_flag", False)),
            "conflict_reason_optional": (
                str(candidate_trace.get("conflict_reason"))
                if candidate_trace.get("conflict_flag", False)
                else None
            ),
            "reselect_reason_optional": reselect_reason,
            "reselect_history": reselect_history,
            "created_by_stage": 8,
            "downstream_consumer": [
                "contact_target",
                "outreach_plan",
                "touch_record",
            ],
        }
        return collection_payload, trace_payload, winning_candidate_snapshot

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
        now = inputs.get("now") or utc_now_iso()
        formal_sink_trace = {
            field_name: stage7_handoff.get(field_name, inputs.get(field_name))
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
        project_id = saleable_opportunity.get("project_id")
        upstream_multi_competitor_collection = stage7_bundle.records.get("multi_competitor_collection")
        if upstream_multi_competitor_collection is None:
            raise ValueError("multi_competitor_collection must be present before Stage8 contact resolution")
        selected_candidate, candidate_trace = select_contact_candidate(
            settings=self.settings,
            saleable_opportunity=saleable_opportunity,
            inputs=inputs,
            now=now,
        )
        multi_competitor_collection_id = stage7_handoff.get(
            "multi_competitor_collection_id_optional",
            upstream_multi_competitor_collection.get("multi_competitor_collection_id"),
        )
        winning_challenger_profile_id = stage7_handoff.get(
            "winning_challenger_profile_id_optional",
            upstream_multi_competitor_collection.get("winning_challenger_profile_id"),
        )
        contact_candidate_collection_payload, contact_selection_trace_payload, winning_contact_candidate = self._build_contact_candidate_carriers(
            saleable_opportunity=saleable_opportunity,
            inputs=inputs,
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

        role_cluster = selected_candidate.get("role_cluster", "PROCUREMENT_DECISION")
        release_level = inputs.get("release_level", inputs.get("minimum_release_level", "INTERNAL_OPERABLE"))
        source_family = selected_candidate.get("source_family", inputs.get("source_family", "PROCUREMENT_NOTICE"))
        source_auditability_state = selected_candidate.get("source_auditability_state", inputs.get("source_auditability_state", "AUDITABLE"))
        response_status = ensure_enum(self.store, "response_status", inputs.get("response_status", "NO_RESPONSE"))
        run_mode = ensure_enum(self.store, "run_mode", inputs.get("run_mode", "DRY_RUN"))
        approval_state = ensure_enum(
            self.store, "approval_state", inputs.get("approval_state", "NOT_REQUIRED")
        )
        source_vendor_payload, source_vendor_trace = self._source_vendor_payload(selected_candidate, project_id)
        execution_vendor_payload, execution_vendor_trace = self._execution_vendor_payload(execution_vendor_candidate, project_id)
        source_resolution_metadata, source_resolution_reasons, source_resolution_blocked, source_resolution_review = self._resolution_guard(
            source_vendor_trace,
            default_policy_state=str(inputs.get("source_policy_state", "SOURCE_POLICY_ACTIVE")),
            blocked_reason="source_vendor_resolution_blocked",
        )
        execution_resolution_metadata, execution_resolution_reasons, execution_resolution_blocked, execution_resolution_review = self._resolution_guard(
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
                **dict(inputs),
                **formal_sink_trace,
                **dict(selected_candidate),
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
                "capability_family": self._source_capability_family(source_vendor_payload["source_vendor_role"]),
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
                "requested_action": self._execution_action_intent(run_mode),
                "target_id": execution_vendor_payload["execution_vendor_id_optional"],
                "target_type": "execution_vendor",
                "target_role": execution_vendor_payload["execution_vendor_role_optional"],
                "release_level": release_level,
                "approval_state": approval_state,
                "metadata": execution_resolution_metadata,
            },
            {
                "capability_family": "stage8_execution",
                "requested_action": self._execution_action_intent(run_mode),
                "release_level": release_level,
                "approval_state": approval_state,
            },
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
        permission_state = self.runtime.resolve_permissions(context, permission_checks)
        runtime_state = permission_state if permission_state.permission_short_circuit else self.runtime.run(context, state=permission_state)
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

        blocking_reasons = ensure_list(inputs.get("blocking_reasons", []))
        blocking_reasons.extend(source_resolution_reasons)
        blocking_reasons.extend(execution_resolution_reasons)
        blocking_reasons.extend(runtime_state.blocked_reasons)
        blocking_reasons.extend(runtime_state.review_reasons)
        blocking_reasons.extend(runtime_state.fallback_reasons)
        blocking_reasons.extend(runtime_state.permission_blocked_reasons)
        blocking_reasons.extend(runtime_state.permission_review_reasons)
        contact_target_status = runtime_state.resolve("contact_target_status", "REVIEW_REQUIRED")
        if source_resolution_blocked or emergency_short_circuit or candidate_permission_blocked:
            contact_target_status = "BLOCKED"
        elif (source_resolution_review or candidate_permission_review) and contact_target_status == "ELIGIBLE":
            contact_target_status = "REVIEW_REQUIRED"
        if source_merge_review_required and contact_target_status == "ELIGIBLE":
            contact_target_status = "REVIEW_REQUIRED"
            blocking_reasons.append("source_merge_requires_manual_review")
        action_intent = self._execution_action_intent(run_mode)
        audit_trail_present = bool(source_vendor_payload["source_audit_ref"] and source_vendor_payload["query_trace_id"])
        contact_gate_ids = ["internal_review_release"]
        if inputs.get("person_name_optional") not in (None, "", "UNKNOWN"):
            contact_gate_ids.append("high_restriction_contact_release")
        contact_guard_context = self._guard_context(
            inputs=inputs,
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
            "channel_family": ensure_enum(self.store, "channel_family", selected_candidate.get("channel_family", inputs.get("channel_family"))),
            "contact_target_status": contact_target_status,
            "contact_validity_status": ensure_enum(self.store, "contact_validity_status", selected_candidate.get("contact_validity_status", "UNKNOWN")),
            "contact_legal_basis": ensure_enum(self.store, "contact_legal_basis", selected_candidate.get("contact_legal_basis", "REVIEW_REQUIRED")),
            "reasonable_expectation_status": ensure_enum(self.store, "reasonable_expectation_status", selected_candidate.get("reasonable_expectation_status", "UNKNOWN")),
            "channel_policy_status": ensure_enum(self.store, "channel_policy_status", selected_candidate.get("channel_policy_status", "REVIEW")),
            "frequency_policy_state": ensure_enum(self.store, "frequency_policy_state", selected_candidate.get("frequency_policy_state", "REVIEW")),
            "opt_out_state": ensure_enum(self.store, "opt_out_state", runtime_state.resolve("opt_out_state", selected_candidate.get("opt_out_state", "PENDING_CONFIRMATION"))),
            "quiet_hours_policy_state": ensure_enum(self.store, "quiet_hours_policy_state", selected_candidate.get("quiet_hours_policy_state", "REVIEW")),
            "auto_contact_allowed": bool(runtime_state.resolve("auto_contact_allowed", False))
            and not runtime_state.permission_blocked_reasons
            and not source_merge_review_required,
            "requires_manual_review": bool(
                emergency_short_circuit
                or contact_target_status in ("REVIEW_REQUIRED", "BLOCKED")
                or candidate_permission_review
                or candidate_permission_blocked
                or source_merge_review_required
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

        plan_status = runtime_state.resolve("plan_status", "DRAFT")
        if execution_resolution_blocked or runtime_state.permission_blocked_reasons:
            plan_status = "BLOCKED"
        elif (execution_resolution_review or runtime_state.permission_review_reasons) and plan_status == "APPROVED":
            plan_status = "REVIEW_REQUIRED"
        if source_merge_review_required and plan_status == "APPROVED":
            plan_status = "REVIEW_REQUIRED"
        if run_mode in ("APPROVAL_RUN", "REAL_RUN") and approval_state != "APPROVED":
            plan_status = "REVIEW_REQUIRED"
        plan_requires_manual_review = bool(
            contact_target.get("requires_manual_review")
            or plan_status in ("REVIEW_REQUIRED", "BLOCKED")
            or approval_state == "PENDING"
        )

        outreach_gate_ids = ["internal_review_release"]
        if action_intent in ("APPROVAL_EXECUTION", "LIVE_EXECUTION"):
            outreach_gate_ids.append("high_restriction_contact_release")
        outreach_guard_context = self._guard_context(
            inputs=inputs,
            release_level=release_level,
            approval_state=approval_state,
            action_intent=action_intent,
            requested_gate_ids=outreach_gate_ids,
            audit_trail_present=bool(execution_vendor_payload["execution_trace_id_optional"]),
        )
        runtime_writeback_targets = ensure_list(
            runtime_state.resolve("writeback_targets", inputs.get("writeback_targets"))
        )
        runtime_writeback_target = runtime_state.resolve(
            "writeback_target_optional",
            inputs.get("writeback_target_optional"),
        )
        if not runtime_writeback_targets and runtime_writeback_target not in (None, ""):
            runtime_writeback_targets = [runtime_writeback_target]
        if runtime_writeback_target in (None, "") and runtime_writeback_targets:
            runtime_writeback_target = runtime_writeback_targets[0]

        outreach_payload = {
            "outreach_plan_id": build_id("PLAN", project_id),
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "project_id": project_id,
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "contact_target_id": contact_target.get("contact_target_id"),
            "channel_strategy": inputs.get("channel_strategy", "DEFAULT"),
            "requested_delivery_surface": str(
                runtime_state.resolve(
                    "requested_delivery_surface",
                    inputs.get("requested_delivery_surface", "INTERNAL_OPERATIONS"),
                )
            ),
            "projection_mode": str(runtime_state.resolve("projection_mode", "INTERNAL_GOVERNED_PREVIEW")),
            "cadence_profile_id": str(
                runtime_state.resolve("cadence_profile_id", inputs.get("cadence_profile_id"))
            ),
            "retry_policy_id": str(
                runtime_state.resolve("retry_policy_id", inputs.get("retry_policy_id"))
            ),
            "stop_policy_id": str(
                runtime_state.resolve("stop_policy_id", inputs.get("stop_policy_id"))
            ),
            "primary_message": inputs.get("primary_message", "internal preview"),
            "planned_touch_at": inputs.get("planned_touch_at", now),
            "attempt_index": int(runtime_state.resolve("attempt_index", inputs.get("attempt_index", 1))),
            "approval_state": approval_state,
            "plan_status": plan_status,
            "run_mode": run_mode,
            "automation_level": ensure_enum(
                self.store, "automation_level", inputs.get("automation_level", "MANUAL")
            ),
            "next_touch_due_at_optional": str(
                runtime_state.resolve(
                    "next_touch_due_at_optional",
                    inputs.get("next_touch_due_at_optional", now),
                )
            ),
            "retry_count": int(runtime_state.resolve("retry_count", inputs.get("retry_count", 0))),
            "max_retry_count": int(
                runtime_state.resolve("max_retry_count", inputs.get("max_retry_count", 0))
            ),
            "stop_reason_optional": str(
                runtime_state.resolve("stop_reason_optional", inputs.get("stop_reason_optional"))
            ),
            "approval_run_required": bool(runtime_state.resolve("approval_run_required", run_mode in ("APPROVAL_RUN", "REAL_RUN"))),
            "writeback_required": bool(runtime_state.resolve("writeback_required", True)),
            "writeback_target_optional": str(runtime_writeback_target),
            "permission_decision_state": runtime_state.permission_decision_state,
            "governance_decision_state": runtime_state.governance_decision_state,
            "semantic_decision_state": runtime_state.semantic_decision_state,
            "requires_manual_review": bool(plan_requires_manual_review),
            **execution_vendor_payload,
        }
        outreach_guard = self.store.evaluate_runtime_guards("outreach_plan", outreach_payload, outreach_guard_context)
        runtime_state.add_governance_guard(outreach_guard)
        if outreach_guard.decision_state == "BLOCK":
            outreach_payload["plan_status"] = "BLOCKED"
            outreach_payload["requires_manual_review"] = True
        elif outreach_guard.decision_state == "REVIEW" and outreach_payload["plan_status"] == "APPROVED":
            outreach_payload["plan_status"] = "REVIEW_REQUIRED"
            outreach_payload["requires_manual_review"] = True
        outreach_semantic = self.store.evaluate_object_semantics(
            stage=8,
            object_type="outreach_plan",
            payload=outreach_payload,
            semantic_context={
                "contact_target_status": contact_payload["contact_target_status"],
                "upstream_saleability_status": saleable_opportunity.get("saleability_status"),
            },
        )
        if outreach_semantic:
            runtime_state.add_semantic_validation(outreach_semantic)
            if outreach_semantic.decision_state == "BLOCK":
                outreach_payload["plan_status"] = "BLOCKED"
                outreach_payload["requires_manual_review"] = True
            elif outreach_semantic.decision_state == "REVIEW" and outreach_payload["plan_status"] == "APPROVED":
                outreach_payload["plan_status"] = "REVIEW_REQUIRED"
                outreach_payload["requires_manual_review"] = True
        outreach_payload["permission_decision_state"] = runtime_state.permission_decision_state
        outreach_payload["governance_decision_state"] = runtime_state.governance_decision_state
        outreach_payload["semantic_decision_state"] = runtime_state.semantic_decision_state
        outreach_payload["governed_metadata"] = self._governed_metadata(
            runtime_state=runtime_state,
            requested_delivery_surface=outreach_payload["requested_delivery_surface"],
            projection_mode=outreach_payload["projection_mode"],
            run_mode=run_mode,
            approval_state=approval_state,
            writeback_targets=runtime_writeback_targets,
        )

        outreach_plan = self.store.build_record(
            "outreach_plan",
            outreach_payload,
        )

        trace_rules = [
            f"POLICY:emit_decision:{entry.get('policy_key', '')}"
            for entry in runtime_state.trace
            if entry.get("event") == "emit_decision"
        ]
        next_step_optional = runtime_state.resolve(
            "next_step_optional",
            inputs.get("next_step_optional"),
        )
        stop_reason_optional = runtime_state.resolve(
            "stop_reason_optional",
            inputs.get("stop_reason_optional"),
        )
        retry_scheduled_optional = bool(
            runtime_state.resolve("retry_scheduled_optional", False)
        )
        human_handoff = self._build_human_handoff(
            response_status=response_status,
            commercial_urgency_level=str(
                inputs.get("commercial_urgency_level")
                or inputs.get("commercial_urgency_level_optional")
                or "NORMAL"
            ),
            now=now,
        )
        if human_handoff and next_step_optional in (None, ""):
            next_step_optional = human_handoff["next_step_optional"]
        if human_handoff and next_step_optional not in (None, ""):
            human_handoff["next_step_optional"] = next_step_optional
        next_step_optional = str(next_step_optional or inputs.get("next_step_optional") or "WAIT")
        written_back_at_optional = runtime_state.resolve(
            "written_back_at_optional",
            inputs.get("written_back_at_optional", now),
        )
        touch_state = "CREATED"
        if runtime_state.permission_blocked_reasons or plan_status in ("CANCELLED", "BLOCKED"):
            touch_state = "CANCELLED"
        elif plan_status != "APPROVED" or run_mode == "DRY_RUN":
            touch_state = "CREATED"
        elif response_status in ("CONNECTED", "DECLINED", "OPTED_OUT", "WRONG_ROLE", "INVALID_CONTACT", "FOLLOWUP_REQUIRED", "OPPORTUNITY_CHANGED"):
            touch_state = "RESPONDED"
        else:
            touch_state = "SENT"

        touch_guard_context = self._guard_context(
            inputs=inputs,
            release_level=release_level,
            approval_state=approval_state,
            action_intent=action_intent,
            requested_gate_ids=["internal_review_release"],
            audit_trail_present=bool(execution_vendor_payload["execution_trace_id_optional"] and written_back_at_optional),
        )
        touch_writeback_targets = ensure_list(
            runtime_state.resolve("writeback_targets", inputs.get("writeback_targets"))
        )
        touch_writeback_target = runtime_state.resolve(
            "writeback_target_optional",
            inputs.get("writeback_target_optional"),
        )
        if not touch_writeback_targets and touch_writeback_target not in (None, ""):
            touch_writeback_targets = [touch_writeback_target]
        if touch_writeback_target in (None, "") and touch_writeback_targets:
            touch_writeback_target = touch_writeback_targets[0]
        touch_payload = {
            "touch_record_id": build_id("TOUCH", project_id),
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "project_id": project_id,
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "contact_target_id": contact_target.get("contact_target_id"),
            "outreach_plan_id": outreach_plan.get("outreach_plan_id"),
            "touch_at": inputs.get("touch_at", now),
            "attempt_index": int(runtime_state.resolve("attempt_index", inputs.get("attempt_index", 1))),
            "touch_record_state": touch_state,
            "response_status": response_status,
            "feedback_reason": str(
                runtime_state.resolve("feedback_reason", inputs.get("feedback_reason", response_status))
            ),
            "next_step_optional": next_step_optional,
            "stop_reason_optional": str(stop_reason_optional),
            "touch_channel": ensure_enum(self.store, "channel_family", inputs.get("channel_family")),
            "written_back_at_optional": written_back_at_optional,
            "retry_scheduled_optional": retry_scheduled_optional,
            "failure_reason_tag_optional": str(
                runtime_state.resolve(
                    "failure_reason_tag_optional",
                    inputs.get("failure_reason_tag_optional", response_status),
                )
            ),
            "writeback_targets": touch_writeback_targets,
            "writeback_target_optional": str(touch_writeback_target),
            "permission_decision_state": runtime_state.permission_decision_state,
            "governance_decision_state": runtime_state.governance_decision_state,
            "semantic_decision_state": runtime_state.semantic_decision_state,
            "execution_vendor_id_optional": execution_vendor_payload["execution_vendor_id_optional"],
            "execution_vendor_type_optional": execution_vendor_payload["execution_vendor_type_optional"],
            "execution_vendor_role_optional": execution_vendor_payload["execution_vendor_role_optional"],
            "execution_trace_id_optional": execution_vendor_payload["execution_trace_id_optional"],
            "vendor_response_ref_optional": execution_vendor_payload["vendor_response_ref_optional"],
        }
        touch_guard = self.store.evaluate_runtime_guards("touch_record", touch_payload, touch_guard_context)
        runtime_state.add_governance_guard(touch_guard)
        if touch_guard.decision_state == "BLOCK":
            touch_payload["touch_record_state"] = "CANCELLED"
        elif touch_guard.decision_state == "REVIEW" and touch_payload["touch_record_state"] == "SENT":
            touch_payload["touch_record_state"] = "CREATED"
        touch_semantic = self.store.evaluate_object_semantics(
            stage=8,
            object_type="touch_record",
            payload=touch_payload,
            semantic_context={
                "plan_status": outreach_payload["plan_status"],
                "upstream_saleability_status": saleable_opportunity.get("saleability_status"),
            },
        )
        if touch_semantic:
            runtime_state.add_semantic_validation(touch_semantic)
            if touch_semantic.decision_state == "BLOCK":
                touch_payload["touch_record_state"] = "CANCELLED"
            elif touch_semantic.decision_state == "REVIEW" and touch_payload["touch_record_state"] == "SENT":
                touch_payload["touch_record_state"] = "CREATED"
        touch_payload["permission_decision_state"] = runtime_state.permission_decision_state
        touch_payload["governance_decision_state"] = runtime_state.governance_decision_state
        touch_payload["semantic_decision_state"] = runtime_state.semantic_decision_state
        touch_payload["governed_metadata"] = self._governed_metadata(
            runtime_state=runtime_state,
            requested_delivery_surface=outreach_plan.get("requested_delivery_surface"),
            projection_mode=outreach_plan.get("projection_mode"),
            run_mode=run_mode,
            approval_state=approval_state,
            writeback_targets=touch_payload["writeback_targets"],
        )
        if human_handoff:
            touch_payload["governed_metadata"]["human_handoff"] = human_handoff

        touch_record = self.store.build_record(
            "touch_record",
            touch_payload,
        )

        handoff = {
            "project_id": project_id,
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "touch_record_id": touch_record.get("touch_record_id"),
            "response_status": touch_record.get("response_status"),
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "crm_owner_state": saleable_opportunity.get("crm_owner_state"),
            "contact_target_status": contact_target.get("contact_target_status"),
            "plan_status": outreach_plan.get("plan_status"),
            "touch_record_state": touch_record.get("touch_record_state"),
            "feedback_reason": touch_record.get("feedback_reason"),
            "written_back_at_optional": touch_record.get("written_back_at_optional"),
            "human_handoff_policy_id_optional": human_handoff.get("policy_id") if human_handoff else None,
            "human_handoff_next_owner_role_optional": human_handoff.get("next_owner_role_optional") if human_handoff else None,
            "human_handoff_sla_hours_optional": human_handoff.get("sla_hours_optional") if human_handoff else None,
            "human_handoff_sla_due_at_optional": human_handoff.get("sla_due_at_optional") if human_handoff else None,
            "human_handoff_reason_optional": human_handoff.get("reason_optional") if human_handoff else None,
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
        }

        inputs_out = dict(inputs)
        inputs_out["policy_trace"] = runtime_state.trace
        inputs_out["policy_decision_state"] = runtime_state.decision_state
        inputs_out["permission_trace"] = runtime_state.capability_trace
        inputs_out["permission_decision_state"] = runtime_state.permission_decision_state
        inputs_out["permission_governance"] = runtime_state.capability_governance()
        inputs_out["governance_trace"] = runtime_state.governance_trace
        inputs_out["governance_decision_state"] = runtime_state.governance_decision_state
        inputs_out["governance_additions"] = runtime_state.governance_additions
        inputs_out["semantic_trace"] = runtime_state.semantic_trace
        inputs_out["semantic_decision_state"] = runtime_state.semantic_decision_state
        inputs_out["semantic_additions"] = runtime_state.semantic_additions
        inputs_out["opportunity_id"] = saleable_opportunity.get("opportunity_id")
        inputs_out["touch_record_id"] = touch_record.get("touch_record_id")
        inputs_out["response_status"] = touch_record.get("response_status")
        inputs_out["saleability_status"] = saleable_opportunity.get("saleability_status")
        inputs_out["crm_owner_state"] = saleable_opportunity.get("crm_owner_state")
        inputs_out["requested_delivery_surface"] = outreach_plan.get("requested_delivery_surface")
        inputs_out["projection_mode"] = outreach_plan.get("projection_mode")
        inputs_out["next_step_optional"] = touch_record.get("next_step_optional")
        inputs_out["feedback_reason"] = touch_record.get("feedback_reason")
        inputs_out["written_back_at_optional"] = touch_record.get("written_back_at_optional")
        inputs_out["stop_reason_optional"] = touch_record.get("stop_reason_optional")
        inputs_out["retry_scheduled_optional"] = touch_record.get("retry_scheduled_optional")
        inputs_out["writeback_targets"] = touch_record.get("writeback_targets")
        inputs_out["writeback_target_optional"] = touch_record.get("writeback_target_optional")
        inputs_out["failure_reason_tag_optional"] = touch_record.get("failure_reason_tag_optional")
        inputs_out["human_handoff_policy_id_optional"] = human_handoff.get("policy_id") if human_handoff else None
        inputs_out["human_handoff_next_owner_role_optional"] = human_handoff.get("next_owner_role_optional") if human_handoff else None
        inputs_out["human_handoff_sla_hours_optional"] = human_handoff.get("sla_hours_optional") if human_handoff else None
        inputs_out["human_handoff_sla_due_at_optional"] = human_handoff.get("sla_due_at_optional") if human_handoff else None
        inputs_out["human_handoff_reason_optional"] = human_handoff.get("reason_optional") if human_handoff else None
        inputs_out["next_touch_due_at_optional"] = runtime_state.resolve("next_touch_due_at_optional")
        inputs_out["retry_count"] = runtime_state.resolve("retry_count", outreach_plan.get("retry_count"))
        inputs_out["max_retry_count"] = runtime_state.resolve(
            "max_retry_count",
            outreach_plan.get("max_retry_count"),
        )
        inputs_out["attempt_index"] = runtime_state.resolve(
            "attempt_index",
            touch_record.get("attempt_index"),
        )
        inputs_out["cadence_profile_id"] = outreach_plan.get("cadence_profile_id")
        inputs_out["retry_policy_id"] = outreach_plan.get("retry_policy_id")
        inputs_out["stop_policy_id"] = outreach_plan.get("stop_policy_id")
        inputs_out["stage8_resolution_trace"] = {
            "candidate_resolution": candidate_trace,
            "contact_candidate_collection_id": contact_candidate_collection.get("contact_candidate_collection_id"),
            "contact_selection_trace_id": contact_selection_trace.get("contact_selection_trace_id"),
            "winning_contact_candidate_id": contact_candidate_collection.get("winning_contact_candidate_id"),
            "contact_selection_trace": {
                "winning_selection_reason": contact_selection_trace.get("winning_selection_reason"),
                "conflict_flag": contact_selection_trace.get("conflict_flag"),
                "conflict_reason_optional": contact_selection_trace.get("conflict_reason_optional"),
                "reselect_reason_optional": contact_selection_trace.get("reselect_reason_optional"),
                "reselect_history": contact_selection_trace.get("reselect_history"),
            },
            "source_vendor_resolution": source_vendor_trace,
            "execution_vendor_resolution": execution_vendor_trace,
            "human_handoff": human_handoff,
            "formal_sink_consumption": formal_sink_trace,
        }
        inputs_out["contact_candidate_collection_id_optional"] = contact_candidate_collection.get("contact_candidate_collection_id")
        inputs_out["contact_selection_trace_id_optional"] = contact_selection_trace.get("contact_selection_trace_id")
        inputs_out["winning_contact_candidate_id_optional"] = contact_candidate_collection.get("winning_contact_candidate_id")
        inputs_out["reselect_reason_optional"] = contact_candidate_collection.get("reselect_reason_optional")
        inputs_out["contact_candidate_collection_snapshot"] = contact_candidate_collection.data
        inputs_out["contact_selection_trace_snapshot"] = contact_selection_trace.data

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
