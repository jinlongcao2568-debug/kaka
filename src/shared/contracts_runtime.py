from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
import json

from .settings import Settings
from .runtime_validator import RuntimeValidator


@dataclass(frozen=True)
class ContractRecord:
    object_type: str
    data: Dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass(frozen=True)
class StageBundle:
    stage: int
    records: Dict[str, ContractRecord]
    handoff: Dict[str, Any]
    trace_rules: List[str] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)

    def record(self, object_type: str) -> ContractRecord:
        return self.records[object_type]


class ContractStore:
    _default: Optional["ContractStore"] = None

    def __init__(self, repo_root: Optional[str] = None) -> None:
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self.schema_catalog = self._load_json("contracts/schemas/schema_catalog.json")
        self.enum_catalog = self._load_json("contracts/enums/enum_catalog.json")
        self.rule_catalog = self._load_json("contracts/rules/rule_catalog.json")
        self.source_registry = self._load_json("contracts/governance/source_registry.json")
        self.route_policy_catalog = self._load_json("contracts/governance/route_policy_catalog.json")
        self.regression_manifest = self._load_json("contracts/testing/regression_manifest.json")
        self.schema_index = {entry["object"]: entry for entry in self.schema_catalog.get("schemas", [])}
        self.enum_index = {entry["enum_name"]: entry for entry in self.enum_catalog.get("enums", [])}
        self.rule_index = {entry["rule_code"]: entry for entry in self.rule_catalog.get("rules", [])}
        self.source_registry_index = {
            entry["source_registry_id"]: entry for entry in self.source_registry.get("entries", [])
        }
        self.route_policy_index = {
            entry["route_policy_id"]: entry for entry in self.route_policy_catalog.get("policies", [])
        }
        self.runtime_validator = RuntimeValidator(repo_root=str(self.repo_root))

    @classmethod
    def default(cls, settings: Optional[Settings] = None) -> "ContractStore":
        if cls._default is None:
            root = settings.repo_root if settings else None
            cls._default = cls(repo_root=root)
        return cls._default

    def _load_json(self, relative_path: str) -> Dict[str, Any]:
        path = self.repo_root / relative_path
        if not path.exists():
            raise FileNotFoundError(f"contract file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def get_schema(self, object_type: str) -> Mapping[str, Any]:
        if object_type not in self.schema_index:
            raise KeyError(f"schema not found for object: {object_type}")
        return self.schema_index[object_type]

    def get_enum_values(self, enum_name: str) -> List[str]:
        enum_entry = self.enum_index.get(enum_name)
        if not enum_entry:
            raise KeyError(f"enum not found: {enum_name}")
        return [value["value"] for value in enum_entry.get("values", [])]

    def get_default_enum_value(self, enum_name: str, fallback: str) -> str:
        try:
            values = self.get_enum_values(enum_name)
        except KeyError:
            return fallback
        return values[0] if values else fallback

    def get_rule(self, rule_code: str) -> Mapping[str, Any]:
        if rule_code not in self.rule_index:
            raise KeyError(f"rule code not found: {rule_code}")
        return self.rule_index[rule_code]

    def resolve_source_entry(
        self,
        *,
        source_family: str,
        platform_level: str,
        region_scope: str | None = None,
        coverage_tier: str | None = None,
        carrier_type: str | None = None,
        source_registry_id: str | None = None,
    ) -> Mapping[str, Any]:
        if source_registry_id:
            entry = self.source_registry_index.get(source_registry_id)
            if not entry:
                raise KeyError(f"source registry entry not found: {source_registry_id}")
            return entry

        candidates = []
        for entry in self.source_registry.get("entries", []):
            if entry.get("source_family") != source_family:
                continue
            if entry.get("platform_level") != platform_level:
                continue
            if carrier_type and entry.get("carrier_type") != carrier_type:
                continue
            if region_scope and entry.get("region_scope") != region_scope:
                continue
            if coverage_tier and entry.get("coverage_tier") != coverage_tier:
                continue
            candidates.append(entry)
        if candidates:
            return candidates[0]

        for entry in self.source_registry.get("entries", []):
            if entry.get("source_family") == source_family and entry.get("platform_level") == platform_level:
                return entry
        raise KeyError(
            f"source registry entry not found for source_family={source_family}, platform_level={platform_level}"
        )

    def resolve_route_policy(
        self,
        *,
        route_policy_id: str | None = None,
        source_registry_id: str | None = None,
        source_family: str | None = None,
    ) -> Mapping[str, Any]:
        if route_policy_id:
            policy = self.route_policy_index.get(route_policy_id)
            if not policy:
                raise KeyError(f"route policy not found: {route_policy_id}")
            return policy

        for policy in self.route_policy_catalog.get("policies", []):
            registry_refs = [str(value) for value in policy.get("source_registry_refs", [])]
            family_refs = [str(value) for value in policy.get("source_family_refs", [])]
            if source_registry_id and source_registry_id in registry_refs:
                return policy
            if source_family and source_family in family_refs:
                return policy
        raise KeyError(
            f"route policy not found for source_registry_id={source_registry_id}, source_family={source_family}"
        )

    def build_record(self, object_type: str, payload: Dict[str, Any], guard_context: Mapping[str, Any] | None = None) -> ContractRecord:
        self.validate_record(object_type, payload, guard_context=guard_context)
        return ContractRecord(object_type=object_type, data=payload)

    def validate_record(self, object_type: str, payload: Dict[str, Any], guard_context: Mapping[str, Any] | None = None) -> None:
        schema = self.get_schema(object_type)
        self.runtime_validator.validate_payload(object_type, schema, payload)
        self._validate_enums(payload)

    def evaluate_runtime_guards(
        self,
        object_type: str,
        payload: Dict[str, Any],
        guard_context: Mapping[str, Any],
    ) -> Any:
        return self.runtime_validator.evaluate_runtime_guards(object_type, payload, guard_context)

    def evaluate_handoff_consumer(
        self,
        *,
        producer_bundle: StageBundle,
        consumer_stage: int,
    ) -> Any:
        return self.runtime_validator.evaluate_handoff_consumer(
            producer_bundle=producer_bundle,
            consumer_stage=consumer_stage,
        )

    def evaluate_object_semantics(
        self,
        *,
        stage: int,
        object_type: str,
        payload: Dict[str, Any],
        semantic_context: Mapping[str, Any],
    ) -> Any:
        return self.runtime_validator.evaluate_object_semantics(
            stage=stage,
            object_type=object_type,
            payload=payload,
            semantic_context=semantic_context,
        )

    def _validate_enums(self, payload: Dict[str, Any]) -> None:
        field_enum_map = {
            "rule_gate_status": "gate_status",
            "evidence_gate_status": "gate_status",
            "sale_gate_status": "sale_gate_status",
            "default_route": "route_type",
            "fallback_route": "route_type",
            "review_lane": "review_lane",
            "review_queue_bucket": "review_queue_bucket",
            "minimum_release_level": "release_level",
            "window_risk_level": "window_risk_level",
            "commercial_urgency_level": "commercial_urgency_level",
            "verification_state": "verification_state",
            "cross_check_state": "cross_check_state",
            "fixation_status": "fixation_status",
            "provenance_chain_status": "provenance_chain_status",
            "retrieval_readiness_status": "retrieval_readiness_status",
            "minimum_external_use_grade": "external_use_grade",
            "rule_hit_state": "rule_hit_state",
            "report_status": "report_status",
            "review_task_status": "review_task_status",
            "version_conflict_state": "version_conflict_state",
            "conflict_state": "conflict_state",
            "lineage_status": "lineage_status",
            "collection_state": "collection_state",
            "source_family": "source_family",
            "platform_level": "platform_level",
            "region_scope": "region_scope",
            "coverage_tier": "coverage_tier",
            "carrier_type": "carrier_type",
            "origin_carrier_type": "carrier_type",
            "public_chain_status": "public_chain_status",
            "window_clock_state": "window_clock_state",
            "clock_conflict_state": "conflict_state",
            "window_status": "window_status",
            "publication_clock_state": "clock_state",
            "first_seen_clock_state": "clock_state",
            "correction_clock_state": "clock_state",
            "reply_clock_state": "clock_state",
            "remedy_clock_state": "clock_state",
            "current_action_clock": "clock_state",
            "public_capability_tier": "public_capability_tier",
            "external_use_grade": "external_use_grade",
            "evidence_grade": "external_use_grade",
            "result_type": "result_type",
            "lead_status": "lead_status",
            "coverage_sellable_state": "coverage_sellable_state",
            "delivery_risk_state": "delivery_risk_state",
            "manual_override_status": "manual_override_status",
            "competitor_quality_grade": "competitor_quality_grade",
            "saleability_status": "saleability_status",
            "offer_recommendation_state": "offer_recommendation_state",
            "sku_code": "sku_code",
            "recommended_sku": "sku_code",
            "recommended_delivery_form": "recommended_delivery_form",
            "recommended_quote_band": "recommended_quote_band",
            "opportunity_grade": "opportunity_grade",
            "crm_owner_state": "crm_owner_state",
            "contact_target_status": "contact_target_status",
            "contact_validity_status": "contact_validity_status",
            "contact_legal_basis": "contact_legal_basis",
            "reasonable_expectation_status": "reasonable_expectation_status",
            "channel_family": "channel_family",
            "channel_policy_status": "channel_policy_status",
            "frequency_policy_state": "frequency_policy_state",
            "opt_out_state": "opt_out_state",
            "quiet_hours_policy_state": "quiet_hours_policy_state",
            "plan_status": "plan_status",
            "approval_state": "approval_state",
            "run_mode": "run_mode",
            "automation_level": "automation_level",
            "touch_record_state": "touch_record_state",
            "response_status": "response_status",
            "touch_channel": "channel_family",
            "commercial_status": "commercial_status",
            "amount_band": "amount_band",
            "order_status": "order_status",
            "payment_status": "payment_status",
            "delivery_status": "delivery_status",
            "archival_status": "archival_status",
            "retrieval_status": "retrieval_status",
            "outcome_family": "outcome_family",
            "window_missed_state": "window_missed_state",
            "contact_failure_state": "contact_failure_state",
            "payer_mismatch_state": "payer_mismatch_state",
            "trigger_type": "trigger_type",
            "action_family": "action_family",
            "candidate_group_label": "candidate_group_label",
            "candidate_position_label": "candidate_position_label",
            "confidence_band": "confidence_band",
            "project_manager_conflict_clue_status": "project_manager_conflict_clue_status",
            "missing_condition_family": "missing_condition_family",
            "candidate_order_mode": "candidate_order_mode",
            "award_determination_mode": "award_determination_mode",
            "procurement_regime": "procurement_regime",
        }
        for field_name, enum_name in field_enum_map.items():
            if field_name not in payload:
                continue
            value = payload[field_name]
            if enum_name not in self.enum_index:
                continue
            allowed = self.get_enum_values(enum_name)
            if isinstance(value, list):
                invalid = [item for item in value if item not in allowed]
                if invalid:
                    raise ValueError(f"{field_name} has invalid values: {invalid}")
            else:
                if value not in allowed:
                    raise ValueError(f"{field_name} has invalid value: {value}")


__all__ = ["ContractRecord", "StageBundle", "ContractStore"]
