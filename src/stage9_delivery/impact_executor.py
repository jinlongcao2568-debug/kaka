# Stage: stage9_delivery
# Consumes formal objects: saleable_opportunity, touch_record, order_record, payment_record, delivery_record, governance_feedback_event, opportunity_outcome_event
# Dependent handoff: H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: contracts/governance/writeback_impact_policy.json

from __future__ import annotations

from typing import Any, Mapping

from shared.contract_loader import load_contract


class ImpactExecutor:
    REQUIRED_TARGET_CONTRACT_FIELDS = {
        "target_family",
        "mutation_semantics",
        "persistence_semantics",
        "additive_governance_allowed",
        "silent_override_forbidden",
    }
    REQUIRED_SOURCE_CONTRACT_FIELDS = {
        "source_output_field",
        "merge_semantics",
        "persisted_stage9_record_target",
        "silent_override_forbidden",
    }
    REQUIRED_TARGET_SEMANTIC_GROUPS = (
        "projected_only_targets",
        "persisted_targets",
        "advisory_targets",
        "trace_only_governance_targets",
    )
    SOURCE_ORDER = (
        "outcome_taxonomy",
        "upstream_feedback_loop",
        "governance_taxonomy",
        "payment_exception",
        "delivery_exception",
    )
    SOURCE_EXPECTED_MERGE_SEMANTICS = {
        "outcome_taxonomy": "AUTHORITATIVE_BASE",
        "upstream_feedback_loop": "PROJECTED_FEEDBACK_ONLY",
        "governance_taxonomy": "ADDITIVE_ONLY",
        "payment_exception": "ADDITIVE_ONLY",
        "delivery_exception": "ADDITIVE_ONLY",
    }

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.policy = load_contract("contracts/governance/writeback_impact_policy.json", settings)

    def _source_order(self) -> tuple[str, ...]:
        order = tuple(self.policy.get("target_source_resolution_order") or self.SOURCE_ORDER)
        missing = [source for source in self.SOURCE_ORDER if source not in order]
        if missing:
            raise ValueError(f"Stage9 writeback source resolution order missing source families: {missing}")
        return order

    def _target_semantic_groups(self) -> dict[str, tuple[str, ...]]:
        groups = dict(self.policy.get("target_semantic_groups", {}))
        missing = [
            group_name
            for group_name in self.REQUIRED_TARGET_SEMANTIC_GROUPS
            if group_name not in groups
        ]
        if missing:
            raise ValueError(f"Stage9 target semantic groups missing groups: {missing}")

        normalized: dict[str, tuple[str, ...]] = {}
        seen_by_group: dict[str, set[str]] = {}
        for group_name in self.REQUIRED_TARGET_SEMANTIC_GROUPS:
            group_targets: list[str] = []
            seen_targets: set[str] = set()
            for target in groups.get(group_name, []):
                target_name = str(target)
                if target_name in seen_targets:
                    continue
                seen_targets.add(target_name)
                group_targets.append(target_name)
            normalized[group_name] = tuple(group_targets)
            seen_by_group[group_name] = seen_targets

        for index, group_name in enumerate(self.REQUIRED_TARGET_SEMANTIC_GROUPS):
            for other_group_name in self.REQUIRED_TARGET_SEMANTIC_GROUPS[index + 1 :]:
                overlap = sorted(seen_by_group[group_name] & seen_by_group[other_group_name])
                if overlap:
                    raise ValueError(
                        "Stage9 target semantic groups must be disjoint: "
                        f"{group_name} vs {other_group_name}; overlap={overlap}"
                    )
        return normalized

    def describe_source_contracts(self) -> dict[str, Any]:
        source_contracts = self.policy.get("writeback_source_contracts", {})
        described: dict[str, dict[str, Any]] = {}
        for source_name in self._source_order():
            contract = dict(source_contracts.get(source_name, {}))
            if not contract:
                raise ValueError(
                    f"Stage9 writeback source contract missing for source_family={source_name}"
                )
            missing_fields = sorted(self.REQUIRED_SOURCE_CONTRACT_FIELDS - set(contract.keys()))
            if missing_fields:
                raise ValueError(
                    f"Stage9 writeback source contract incomplete for source_family={source_name}: missing={missing_fields}"
                )
            described[source_name] = {
                "source_family": source_name,
                **contract,
            }
        return described

    def _require_target_contract(self, target: str) -> dict[str, Any]:
        target_contracts = self.policy.get("target_contracts", {})
        contract = dict(target_contracts.get(target, {}))
        if not contract:
            raise ValueError(f"Stage9 writeback target contract missing for target={target}")
        missing_fields = sorted(self.REQUIRED_TARGET_CONTRACT_FIELDS - set(contract.keys()))
        if missing_fields:
            raise ValueError(
                f"Stage9 writeback target contract incomplete for target={target}: missing={missing_fields}"
            )
        contract.setdefault("additive_source_families_allowed", [])
        contract.setdefault("future_input_roles", [])
        return contract

    def resolve_effective_targets(
        self,
        *,
        outcome_targets: list[str],
        outcome_legacy_targets: list[str] | None = None,
        upstream_feedback_targets: list[str],
        governance_targets: list[str],
        payment_exception_targets: list[str],
        delivery_exception_targets: list[str],
        governance_self_target: str | None = None,
    ) -> dict[str, Any]:
        source_contracts = self.describe_source_contracts()
        effective_targets: list[str] = []
        legacy_effective_targets: list[str] = []
        target_sources: dict[str, list[str]] = {}
        additive_sources_allowed_targets = {
            source_family: {
                str(target)
                for target in self.policy.get("additive_sources_allowed_targets", {}).get(
                    source_family, []
                )
            }
            for source_family in self._source_order()
        }
        outcome_legacy_targets = list(outcome_targets if outcome_legacy_targets is None else outcome_legacy_targets)
        explicit_targets_by_source = {
            "outcome_taxonomy": list(outcome_targets),
            "upstream_feedback_loop": list(upstream_feedback_targets),
            "governance_taxonomy": list(governance_targets),
            "payment_exception": list(payment_exception_targets),
            "delivery_exception": list(delivery_exception_targets),
        }
        legacy_targets_by_source = {
            "outcome_taxonomy": list(outcome_legacy_targets),
            "upstream_feedback_loop": [],
            "governance_taxonomy": list(governance_targets),
            "payment_exception": list(payment_exception_targets),
            "delivery_exception": list(delivery_exception_targets),
        }

        def register_target(
            target: str,
            source_family: str,
            *,
            source_persisted_record: bool = False,
            include_in_legacy_effective: bool = False,
        ) -> None:
            contract = self._require_target_contract(target)
            if source_family != "outcome_taxonomy" and not source_persisted_record:
                additive_sources = set(contract.get("additive_source_families_allowed", []))
                if source_family not in additive_sources:
                    raise ValueError(
                        f"Stage9 writeback target {target} does not allow additive source {source_family}"
                    )
                allowed_targets = additive_sources_allowed_targets.get(source_family, set())
                if target not in allowed_targets:
                    raise ValueError(
                        "Stage9 writeback target "
                        f"{target} is not declared in additive_sources_allowed_targets for {source_family}"
                    )
            if target not in effective_targets:
                effective_targets.append(target)
            resolved_sources = target_sources.setdefault(target, [])
            if source_family not in resolved_sources:
                resolved_sources.append(source_family)
            if include_in_legacy_effective and target not in legacy_effective_targets:
                legacy_effective_targets.append(target)

        for source_family in self._source_order():
            expected_merge_semantics = self.SOURCE_EXPECTED_MERGE_SEMANTICS[source_family]
            if source_contracts[source_family]["merge_semantics"] != expected_merge_semantics:
                raise ValueError(
                    "Stage9 writeback source contract must use "
                    f"{expected_merge_semantics} merge semantics: {source_family}"
                )
            for target in explicit_targets_by_source.get(source_family, []):
                register_target(
                    target,
                    source_family=source_family,
                    include_in_legacy_effective=target in legacy_targets_by_source.get(source_family, []),
                )
            for target in legacy_targets_by_source.get(source_family, []):
                if target in explicit_targets_by_source.get(source_family, []):
                    continue
                self._require_target_contract(target)
                if target not in legacy_effective_targets:
                    legacy_effective_targets.append(target)
            if source_family == "upstream_feedback_loop":
                continue

            persisted_target = str(source_contracts[source_family]["persisted_stage9_record_target"])
            if source_family == "governance_taxonomy":
                if explicit_targets_by_source[source_family] or governance_self_target:
                    register_target(
                        governance_self_target if governance_self_target else persisted_target,
                        source_family,
                        source_persisted_record=True,
                    )
                continue
            if source_family == "outcome_taxonomy" or explicit_targets_by_source[source_family]:
                register_target(
                    persisted_target,
                    source_family,
                    source_persisted_record=True,
                )

        return {
            "writeback_source_contracts": source_contracts,
            "effective_writeback_targets": effective_targets,
            "legacy_effective_writeback_targets": legacy_effective_targets,
            "writeback_target_sources": target_sources,
        }

    def describe_targets(
        self,
        effective_writeback_targets: list[str],
        *,
        target_sources: Mapping[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        described: dict[str, dict[str, Any]] = {}
        persistence_targets: list[str] = []
        projected_targets: list[str] = []
        trace_only_targets: list[str] = []
        advisory_targets: list[str] = []
        resolved_target_sources: dict[str, list[str]] = {}
        source_contracts = self.describe_source_contracts()
        source_order_index = {
            source_family: index
            for index, source_family in enumerate(self._source_order())
        }
        target_semantic_groups = self._target_semantic_groups()
        projected_target_set = set(target_semantic_groups["projected_only_targets"])
        persisted_target_set = set(target_semantic_groups["persisted_targets"])
        advisory_target_set = set(target_semantic_groups["advisory_targets"])
        trace_only_governance_target_set = set(
            target_semantic_groups["trace_only_governance_targets"]
        )
        trace_only_target_set = advisory_target_set | trace_only_governance_target_set

        for target in effective_writeback_targets:
            contract = self._require_target_contract(target)
            target_source_list = list(target_sources.get(target, [])) if target_sources else []
            target_source_list.sort(
                key=lambda source_family: source_order_index.get(
                    source_family,
                    len(source_order_index),
                )
            )
            resolved_target_sources[target] = target_source_list
            described[target] = {
                "target": target,
                "resolved_from_sources": target_source_list,
                **contract,
            }
            mutation_semantics = str(contract.get("mutation_semantics", "UNDECLARED"))
            persistence_semantics = str(contract.get("persistence_semantics", "UNDECLARED"))
            if target in projected_target_set:
                if mutation_semantics != "PROJECTED_MUTATION_ONLY" or persistence_semantics != "NOT_PERSISTED_IN_STAGE9_RUNTIME":
                    raise ValueError(
                        f"Stage9 projected-only target contract drift for target={target}"
                    )
                projected_targets.append(target)
            elif target in persisted_target_set:
                if mutation_semantics != "PERSISTED_STAGE9_RECORD" or persistence_semantics != "PERSISTED_IN_STAGE9_RUNTIME":
                    raise ValueError(
                        f"Stage9 persisted target contract drift for target={target}"
                    )
                persistence_targets.append(target)
            elif target in trace_only_target_set:
                if mutation_semantics != "TRACE_ONLY_CONTRACT" or persistence_semantics != "NOT_PERSISTED_IN_STAGE9_RUNTIME":
                    raise ValueError(
                        f"Stage9 trace-only target contract drift for target={target}"
                    )
                trace_only_targets.append(target)
                if target in advisory_target_set:
                    advisory_targets.append(target)
            else:
                raise ValueError(
                    f"Stage9 writeback target missing target_semantic_groups membership: {target}"
                )

        return {
            "writeback_contract_state": self.policy.get("contract_state", "UNKNOWN"),
            "writeback_contract_semantics": dict(self.policy.get("contract_semantics", {})),
            "writeback_source_contracts": source_contracts,
            "writeback_target_sources": resolved_target_sources,
            "writeback_target_contracts": described,
            "writeback_persistence_targets": persistence_targets,
            "writeback_projected_targets": projected_targets,
            "writeback_advisory_targets": advisory_targets,
            "writeback_trace_only_targets": trace_only_targets,
        }

    def execute(
        self,
        *,
        project_id: str,
        saleable_opportunity: Mapping[str, Any],
        touch_record: Mapping[str, Any],
        opportunity_outcome_event: Mapping[str, Any],
        governance_feedback_event: Mapping[str, Any],
        effective_writeback_targets: list[str],
        target_sources: Mapping[str, list[str]] | None = None,
        now: str,
    ) -> dict[str, Any]:
        formal_targets = set(self.policy.get("formal_targets", []))
        contract_summary = self.describe_targets(
            effective_writeback_targets,
            target_sources=target_sources,
        )
        projected_targets = set(contract_summary["writeback_projected_targets"])
        advisory_targets = set(contract_summary["writeback_advisory_targets"])
        allowed_targets = [
            target
            for target in effective_writeback_targets
            if target in formal_targets
            and contract_summary["writeback_target_contracts"].get(target, {}).get("mutation_semantics")
            == "PROJECTED_MUTATION_ONLY"
        ]
        contract_only_targets = [
            target for target in effective_writeback_targets if target in projected_targets and target not in set(allowed_targets)
        ]
        mutations: dict[str, dict[str, Any]] = {}
        contract_only_projections: dict[str, dict[str, Any]] = {}
        advisories: dict[str, dict[str, Any]] = {}
        trace: list[dict[str, Any]] = []

        for rule in self.policy.get("rules", []):
            target = str(rule.get("target"))
            application_mode: str | None = None
            target_bucket: dict[str, dict[str, Any]] | None = None
            if target in allowed_targets:
                application_mode = "PROJECTED_MUTATION"
                target_bucket = mutations
            elif target in contract_only_targets:
                application_mode = "PROJECTED_CONTRACT_ONLY"
                target_bucket = contract_only_projections
            elif target in advisory_targets:
                application_mode = "ADVISORY_TRACE_ONLY"
                target_bucket = advisories
            else:
                continue
            if not self._matches(rule.get("match", {}), opportunity_outcome_event, governance_feedback_event):
                continue
            mutation = target_bucket.setdefault(
                target,
                {
                    "target_object": target,
                    "target_ref": self._target_ref(
                        target=target,
                        project_id=project_id,
                        saleable_opportunity=saleable_opportunity,
                        touch_record=touch_record,
                    ),
                    "mutation_mode": (
                        self.policy.get("mutation_mode", "ADDITIVE_INTERNAL_ONLY")
                        if application_mode == "PROJECTED_MUTATION"
                        else application_mode
                    ),
                    "field_patches": {},
                    "append_lists": {},
                    "applied_rule_ids": [],
                    "effect_summaries": [],
                    "generated_at": now,
                },
            )
            mutation["field_patches"].update(rule.get("field_patches", {}))
            for field_name, items in rule.get("append_lists", {}).items():
                current = list(mutation["append_lists"].get(field_name, []))
                for item in items:
                    if item not in current:
                        current.append(item)
                mutation["append_lists"][field_name] = current
            mutation["applied_rule_ids"].append(rule["rule_id"])
            mutation["effect_summaries"].append(rule.get("effect_summary", ""))
            trace.append(
                {
                    "event": "writeback_impact_rule_applied",
                    "rule_id": rule["rule_id"],
                    "target": target,
                    "runtime_application_mode": application_mode,
                    "target_mutation_semantics": contract_summary["writeback_target_contracts"]
                    .get(target, {})
                    .get("mutation_semantics"),
                    "match": dict(rule.get("match", {})),
                    "effect_summary": rule.get("effect_summary", ""),
                }
            )

        return {
            "impact_executor_state": self.policy.get("current_state", "UNKNOWN"),
            "runtime_executor_enabled": bool(self.policy.get("runtime_executor_enabled", False)),
            "mutation_mode": self.policy.get("mutation_mode", "ADDITIVE_INTERNAL_ONLY"),
            "formal_targets": list(self.policy.get("formal_targets", [])),
            "allowed_targets": allowed_targets,
            "impact_targets_projected": list(mutations.keys()),
            "impact_targets_projected_contract_only": list(contract_only_projections.keys()),
            "impact_targets_advisory": list(advisories.keys()),
            "impact_mutations": mutations,
            "impact_projected_contracts": contract_only_projections,
            "impact_advisories": advisories,
            "impact_trace": trace,
            **contract_summary,
        }

    def _matches(
        self,
        match: Mapping[str, Any],
        outcome: Mapping[str, Any],
        governance: Mapping[str, Any],
    ) -> bool:
        for field_name, expected_values in match.items():
            if field_name == "outcome_family":
                actual = outcome.get("outcome_family")
            elif field_name == "feedback_reason":
                actual = outcome.get("feedback_reason")
            elif field_name == "trigger_type":
                actual = governance.get("trigger_type")
            else:
                actual = None
            if actual not in set(expected_values):
                return False
        return True

    def _target_ref(
        self,
        *,
        target: str,
        project_id: str,
        saleable_opportunity: Mapping[str, Any],
        touch_record: Mapping[str, Any],
    ) -> dict[str, Any]:
        if target == "project_fact":
            return {"project_id": project_id}
        if target == "saleable_opportunity":
            return {
                "project_id": project_id,
                "opportunity_id": saleable_opportunity.get("opportunity_id"),
            }
        if target == "contact_target":
            return {
                "project_id": project_id,
                "opportunity_id": saleable_opportunity.get("opportunity_id"),
                "contact_target_id": touch_record.get("contact_target_id"),
            }
        if target == "review_queue_profile":
            return {"project_id": project_id}
        if target == "sales_lead":
            return {
                "project_id": project_id,
                "opportunity_id": saleable_opportunity.get("opportunity_id"),
            }
        if target == "report_record":
            return {"project_id": project_id}
        if target == "buyer_fit":
            return {
                "project_id": project_id,
                "opportunity_id": saleable_opportunity.get("opportunity_id"),
            }
        if target == "challenger_candidate_profile":
            return {"project_id": project_id}
        return {"project_id": project_id}


__all__ = ["ImpactExecutor"]
