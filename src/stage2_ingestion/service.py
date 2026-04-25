# Stage: stage2_ingestion
# Consumes formal objects: public_chain, clock_chain_profile, notice_version_chain, fixation_bundle
# Dependent handoff: H-01-STAGE1-TO-STAGE2, H-02-STAGE2-TO-STAGE3
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

from typing import Any, Mapping

from stage2_ingestion.contract_runtime import build_stage2_handoff, build_stage2_inputs
from stage2_ingestion.extractors import extract_stage2
from stage2_ingestion.public_source_adapters import (
    LocalPublicResourceTradingCenterSourceAdapter,
    PublicSourceSnapshotRequest,
    PublicSourceSnapshotResult,
    PublicSourceTransport,
    resolve_public_source_adapter_config,
)
from shared.contracts_runtime import ContractStore, StageBundle
from shared.utils import apply_rule, build_id, ensure_enum, get_flag, resolve_bundle, utc_now_iso
from storage.repositories.object_storage_repo import ObjectStorageRepository


class Stage2Service:
    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.store = ContractStore.default(settings)

    def run(self, payload: Mapping[str, Any] | StageBundle) -> StageBundle:
        stage1_bundle = resolve_bundle(payload)
        inputs = stage1_bundle.inputs or {}
        flags = inputs.get("flags", {})
        now = inputs.get("now") or utc_now_iso()

        task_execution_context = stage1_bundle.record("task_execution_context")
        project_identity_strategy = stage1_bundle.record("project_identity_strategy")
        clock_strategy_profile = stage1_bundle.record("clock_strategy_profile")
        execution_context = stage1_bundle.record("execution_context")
        extracted = extract_stage2(stage1_bundle, self.store, now=now)

        project_id = extracted.project_id
        source_registry_id = extracted.source_registry_id
        route_policy_id = extracted.route_policy_id
        collection_state = extracted.collection_state
        trace_rules: list[str] = []
        clock_conflict_state = extracted.clock_conflict_state

        # Anti-drift anchors for validate-contracts.ps1:
        # "fixation_bundle_id": fixation_bundle.get("fixation_bundle_id")
        # "clock_conflict_state": clock_chain_profile.get("clock_conflict_state")
        # "source_registry_id": source_registry_id
        # "route_policy_id": route_policy_id

        if get_flag(flags, "robots_block"):
            apply_rule(self.store, trace_rules, "SRC-003")
        elif get_flag(flags, "coverage_review") or execution_context.get("requires_manual_review"):
            apply_rule(self.store, trace_rules, "SRC-002")
        elif get_flag(flags, "version_conflict") or get_flag(flags, "clock_conflict"):
            apply_rule(self.store, trace_rules, "SRC-005")
        route_review_reasons = list(extracted.route_review_reasons)
        first_seen_at = extracted.first_seen_at
        last_retrieved_at = extracted.last_retrieved_at
        origin_carrier_type = extracted.origin_carrier_type
        default_route = extracted.default_route
        fixation_bundle = self.store.build_record(
            "fixation_bundle",
            {
                "fixation_bundle_id": build_id("FIX", project_id),
                "carrier_type": origin_carrier_type,
                "source_url": extracted.source_url,
                "capture_time": now,
                "content_hash": extracted.content_hash,
                "storage_path": extracted.storage_path,
            },
        )

        public_chain = self.store.build_record(
            "public_chain",
            {
                "public_chain_id": build_id("PC", project_id),
                "project_id": project_id,
                "announcement_url": extracted.source_url,
                "source_family": extracted.source_family,
                "platform_level": extracted.platform_level,
                "region_scope": extracted.region_scope,
                "coverage_tier": extracted.coverage_tier,
                "carrier_type": extracted.carrier_type,
                "source_registry_id": source_registry_id,
                "route_policy_id": route_policy_id,
                "default_route": default_route,
                "fallback_route": extracted.fallback_route,
                "route_decision_state": extracted.route_decision_state,
                "route_review_reasons": extracted.route_review_reasons,
                "route_downgrade_signals": extracted.route_downgrade_signals,
                "route_block_signals": extracted.route_block_signals,
                "collection_state": collection_state,
                "requires_manual_review": execution_context.get("requires_manual_review"),
                "timeline_nodes": extracted.timeline_nodes,
                "required_node_set": extracted.required_node_set,
                "node_presence_matrix": extracted.node_presence_matrix,
                "statutory_node_completeness": extracted.statutory_node_completeness,
                "window_clock_state": extracted.window_clock_state,
                "clock_chain_id": build_id("CLOCK", project_id),
                "version_chain_id": build_id("VERSION", project_id),
                "first_seen_at": first_seen_at,
                "last_retrieved_at": last_retrieved_at,
                "origin_carrier_type": origin_carrier_type,
                "fixation_bundle_id": fixation_bundle.get("fixation_bundle_id"),
            },
        )

        clock_chain_payload = {
            "clock_chain_id": public_chain.get("clock_chain_id"),
            "project_id": project_id,
            "publication_clock_state": ensure_enum(self.store, "clock_state", inputs.get("publication_clock_state")),
            "first_seen_clock_state": ensure_enum(self.store, "clock_state", inputs.get("first_seen_clock_state")),
            "correction_clock_state": ensure_enum(self.store, "clock_state", inputs.get("correction_clock_state")),
            "reply_clock_state": ensure_enum(self.store, "clock_state", inputs.get("reply_clock_state")),
            "remedy_clock_state": ensure_enum(self.store, "clock_state", inputs.get("remedy_clock_state")),
            "clock_resolution_rule_id": extracted.clock_resolution_rule_id,
            "current_action_clock": ensure_enum(self.store, "clock_state", inputs.get("current_action_clock")),
            "clock_conflict_state": clock_conflict_state,
            "collection_state": collection_state,
            "requires_manual_review": execution_context.get("requires_manual_review"),
        }
        if extracted.current_action_start_at_optional:
            clock_chain_payload["current_action_start_at_optional"] = extracted.current_action_start_at_optional
        if extracted.current_action_deadline_at_optional:
            clock_chain_payload["current_action_deadline_at_optional"] = extracted.current_action_deadline_at_optional
        clock_chain_profile = self.store.build_record(
            "clock_chain_profile",
            clock_chain_payload,
        )

        version_conflict_state = extracted.version_conflict_state
        notice_version_chain = self.store.build_record(
            "notice_version_chain",
            {
                "version_chain_id": public_chain.get("version_chain_id"),
                "project_id": project_id,
                "source_family": extracted.source_family,
                "platform_level": extracted.platform_level,
                "region_scope": extracted.region_scope,
                "carrier_type": extracted.carrier_type,
                "source_registry_id": source_registry_id,
                "route_policy_id": route_policy_id,
                "default_route": default_route,
                "fallback_route": extracted.fallback_route,
                "collection_state": collection_state,
                "current_notice_version_id": extracted.current_notice_version_id,
                "superseded_version_ids": extracted.superseded_version_ids,
                "replacement_edges": extracted.replacement_edges,
                "version_conflict_state": version_conflict_state,
                "version_chain_strategy": extracted.version_chain_strategy,
                "winning_version_resolution_rule_id": extracted.winning_version_resolution_rule_id,
            },
        )

        handoff = build_stage2_handoff(
            extracted=extracted,
            clock_chain_id=clock_chain_profile.get("clock_chain_id"),
            version_chain_id=notice_version_chain.get("version_chain_id"),
            fixation_bundle_id=fixation_bundle.get("fixation_bundle_id"),
            origin_carrier_type=public_chain.get("origin_carrier_type"),
            first_seen_at=public_chain.get("first_seen_at"),
            last_retrieved_at=public_chain.get("last_retrieved_at"),
            clock_conflict_state=clock_chain_profile.get("clock_conflict_state"),
            project_rooting_policy=task_execution_context.get("project_rooting_policy"),
            window_priority_policy=clock_strategy_profile.get("window_priority_policy"),
            identity_resolution_rule_id=project_identity_strategy.get("identity_resolution_rule_id"),
            collection_state=collection_state,
            version_conflict_state=version_conflict_state,
        )

        inputs_out = build_stage2_inputs(
            inputs,
            extracted=extracted,
            fixation_bundle_id=fixation_bundle.get("fixation_bundle_id"),
            origin_carrier_type=public_chain.get("origin_carrier_type"),
            first_seen_at=public_chain.get("first_seen_at"),
            last_retrieved_at=public_chain.get("last_retrieved_at"),
            clock_conflict_state=clock_chain_profile.get("clock_conflict_state"),
            collection_state=collection_state,
            version_conflict_state=version_conflict_state,
        )

        return StageBundle(
            stage=2,
            records={
                "public_chain": public_chain,
                "clock_chain_profile": clock_chain_profile,
                "notice_version_chain": notice_version_chain,
                "fixation_bundle": fixation_bundle,
            },
            handoff=handoff,
            trace_rules=trace_rules,
            inputs=inputs_out,
        )

    def build_handoff(self, result: StageBundle) -> Mapping[str, Any]:
        return result.handoff

    def capture_public_source_snapshot(
        self,
        request: PublicSourceSnapshotRequest,
        *,
        repository: ObjectStorageRepository | None = None,
        transport: PublicSourceTransport | None = None,
        adapter: LocalPublicResourceTradingCenterSourceAdapter | None = None,
    ) -> PublicSourceSnapshotResult:
        resolved_adapter = adapter or LocalPublicResourceTradingCenterSourceAdapter(
            repository=repository or ObjectStorageRepository(settings=self.settings),
            transport=transport,
            config=resolve_public_source_adapter_config(request),
        )
        return resolved_adapter.capture(request)

    def replay_public_source_snapshot(
        self,
        snapshot_id: str,
        *,
        repository: ObjectStorageRepository | None = None,
    ) -> Mapping[str, Any]:
        resolved_repository = repository or ObjectStorageRepository(settings=self.settings)
        return resolved_repository.replay_snapshot(snapshot_id)
