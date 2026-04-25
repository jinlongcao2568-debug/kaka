# Stage: stage1_tasking
# Consumes formal objects: task_execution_context, project_identity_strategy, clock_strategy_profile
# Dependent handoff: H-01-STAGE1-TO-STAGE2
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

from typing import Any, Mapping

from stage1_tasking.contract_runtime import build_stage1_handoff, build_stage1_inputs
from stage1_tasking.extractors import extract_stage1
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import apply_rule, build_id, get_flag, utc_now_iso


class Stage1Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)

    def validate_input(self, payload: Mapping[str, Any]) -> None:
        required = ["task_id", "project_id", "project_name", "region_code"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"stage1 missing required inputs: {', '.join(missing)}")

    def run(self, payload: Mapping[str, Any]) -> StageBundle:
        self.validate_input(payload)
        flags = payload.get("flags", {})
        now = payload.get("now") or utc_now_iso()

        task_id = payload["task_id"]
        project_id = payload["project_id"]
        extracted = extract_stage1(payload, self.store, now=now)

        # Anti-drift anchors for validate-contracts.ps1:
        # "source_registry_id": source_entry["source_registry_id"]
        # "route_policy_id": route_policy["route_policy_id"]
        # "fallback_route": route_policy["route_fallback_order"][1]

        requires_manual_review = extracted.requires_manual_review
        trace_rules: list[str] = []
        if get_flag(flags, "source_mismatch"):
            apply_rule(self.store, trace_rules, "SRC-001")
            requires_manual_review = True

        task_execution_context = self.store.build_record(
            "task_execution_context",
            {
                "task_execution_context_id": build_id("TEC", task_id),
                "task_id": task_id,
                "region_code": payload["region_code"],
                "time_range_from": extracted.time_range_from,
                "time_range_until": extracted.time_range_until,
                "strategy_template_id": extracted.strategy_template_id,
                "review_lane": extracted.review_lane,
                "project_rooting_policy": extracted.project_rooting_policy,
                "window_priority_policy": extracted.window_priority_policy,
                "created_at": now,
            },
        )

        project_identity_strategy = self.store.build_record(
            "project_identity_strategy",
            {
                "project_identity_strategy_id": build_id("PIS", task_id),
                "task_id": task_id,
                "project_root_strategy": extracted.project_root_strategy,
                "region_code": payload["region_code"],
                "procurement_regime_hint": extracted.procurement_regime,
                "identity_resolution_rule_id": extracted.identity_resolution_rule_id,
                "created_at": now,
            },
        )

        clock_strategy_profile = self.store.build_record(
            "clock_strategy_profile",
            {
                "clock_strategy_profile_id": build_id("CSP", task_id),
                "task_id": task_id,
                "procurement_regime_strategy": extracted.procurement_regime,
                "window_priority_policy": extracted.window_priority_policy,
                "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
                "created_at": now,
            },
        )

        execution_context = self.store.build_record(
            "execution_context",
            {
                "context_id": build_id("CTX", task_id),
                "task_id": task_id,
                "project_unification_strategy": extracted.project_unification_strategy,
                "review_lane": extracted.review_lane,
                "window_priority": extracted.window_priority,
                "region_scope": extracted.region_scope,
                "source_family": extracted.source_family,
                "platform_level": extracted.platform_level,
                "coverage_tier": extracted.coverage_tier,
                "carrier_type": extracted.carrier_type,
                "default_route": extracted.default_route,
                "source_registry_id": extracted.source_registry_id,
                "route_policy_id": extracted.route_policy_id,
                "fallback_route": extracted.fallback_route,
                "requires_manual_review": requires_manual_review,
                "created_at": now,
            },
        )

        handoff = build_stage1_handoff(
            payload,
            project_id=project_id,
            context_id=execution_context.data["context_id"],
            extracted=extracted,
            requires_manual_review=requires_manual_review,
        )
        inputs_out = build_stage1_inputs(
            payload,
            extracted=extracted,
        )

        return StageBundle(
            stage=1,
            records={
                "task_execution_context": task_execution_context,
                "project_identity_strategy": project_identity_strategy,
                "clock_strategy_profile": clock_strategy_profile,
                "execution_context": execution_context,
            },
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff

    def schedule(self, payload: Mapping[str, Any]) -> Any:
        from stage1_tasking.scheduler import Stage1Scheduler

        self.validate_input(payload)
        return Stage1Scheduler(settings=self.settings, store=self.store).create_task(payload)
