from __future__ import annotations

from typing import Any, Mapping

from shared.contracts_runtime import ContractStore
from shared.utils import build_id, utc_now_iso
from stage2_ingestion.public_source_adapters import (
    CREDIT_CHINA_ADAPTER_ID,
    CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
    CREDIT_CHINA_SOURCE_FAMILY,
    GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
    INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
    INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID,
    INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY,
    LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
    PublicSourceSnapshotRequest,
    resolve_public_source_adapter_config,
)
from storage.repositories.stage1_market_scan_repo import Stage1MarketScanRepository
from storage.repositories.stage1_source_blueprint_repo import (
    SOURCE_BLUEPRINT_OBJECT_TYPE,
    Stage1SourceBlueprintRepository,
)


SOURCE_BLUEPRINT_QUEUE_NAME = "stage1_source_blueprint_queue"
CITY_COVERAGE_GAP_SIGNALS = {
    "city_source_contains_detail_missing_from_province",
    "city_source_contains_attachment_missing_from_province",
    "city_source_contains_regulatory_complaint_or_filing_evidence",
    "high_value_project_only_visible_on_city_or_agency_site",
    "province_platform_missing_detail_or_attachment",
    "province_platform_updates_lag_national_or_city_source",
    "province_portal_is_spa_or_weak_shell_but_city_page_is_parseable",
}
PILOT_PROVINCE_PORTFOLIO = (
    {
        "region_code": "CN-SC",
        "province_name": "Sichuan",
        "value_rationale": "large construction and public procurement volume",
        "risk_rationale": "platform fragmentation and attachment variance",
    },
    {
        "region_code": "CN-JS",
        "province_name": "Jiangsu",
        "value_rationale": "dense contractor and municipal project market",
        "risk_rationale": "city and province notices can diverge by timing",
    },
    {
        "region_code": "CN-ZJ",
        "province_name": "Zhejiang",
        "value_rationale": "active private and public project mix",
        "risk_rationale": "source structure changes frequently",
    },
    {
        "region_code": "CN-SD",
        "province_name": "Shandong",
        "value_rationale": "high project count and regional enterprise signals",
        "risk_rationale": "local attachment quality varies",
    },
    {
        "region_code": "CN-GD",
        "province_name": "Guangdong",
        "value_rationale": "high-value infrastructure and buyer density",
        "risk_rationale": "multi-platform source duplication",
    },
    {
        "region_code": "CN-HB",
        "province_name": "Hubei",
        "value_rationale": "strong transport and public building opportunity surface",
        "risk_rationale": "window timing and version chain need verification",
    },
)
_BLOCKED_EXECUTION_FLAGS = (
    "capture_execution_enabled",
    "customer_visible_enabled",
    "external_fetch_enabled",
    "live_execution_enabled",
    "provider_call_enabled",
    "real_external_fetch_enabled",
    "real_provider_call_enabled",
    "stage2_fetch_execute",
    "stage2_fetch_executed",
    "unregistered_capture_enabled",
)
_SOURCE_SURFACES = (
    {
        "surface_key": "trading_platform",
        "source_role": "transaction_platform",
        "adapter_id": LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
        "source_family": "PROCUREMENT_NOTICE",
        "source_registry_id": "SRC-REG-PROC-NATIONAL-HTML",
        "record_kind": "",
        "selection_reason": "primary public transaction notice discovery surface",
    },
    {
        "surface_key": "government_procurement",
        "source_role": "government_procurement",
        "adapter_id": GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
        "source_family": GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
        "source_registry_id": "SRC-REG-GOV-PROCUREMENT-NOTICE",
        "record_kind": GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
        "selection_reason": "government procurement notice and result cross-check",
    },
    {
        "surface_key": "national_construction_market_platform",
        "source_role": "construction_market_platform",
        "adapter_id": NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID,
        "source_family": NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY,
        "source_registry_id": "SRC-REG-NCMP-ENTERPRISE-PUBLIC-RECORD",
        "record_kind": NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
        "selection_reason": "construction enterprise and project public record verification",
    },
    {
        "surface_key": "credit_china",
        "source_role": "credit_risk_public_record",
        "adapter_id": CREDIT_CHINA_ADAPTER_ID,
        "source_family": CREDIT_CHINA_SOURCE_FAMILY,
        "source_registry_id": "SRC-REG-CREDIT-CHINA-PUBLIC-RECORD",
        "record_kind": CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
        "selection_reason": "public credit and penalty risk check",
    },
    {
        "surface_key": "national_enterprise_credit_publicity_system",
        "source_role": "enterprise_credit_publicity",
        "adapter_id": NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
        "source_family": NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
        "source_registry_id": "SRC-REG-NECPS-ENTERPRISE-PUBLIC-RECORD",
        "record_kind": NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
        "selection_reason": "enterprise identity and abnormal-operation cross-check",
    },
    {
        "surface_key": "industry_authority_filing",
        "source_role": "supervisor_filing",
        "adapter_id": INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID,
        "source_family": INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY,
        "source_registry_id": "SRC-REG-INDUSTRY-AUTHORITY-CONSTRUCTION-PERMIT",
        "record_kind": INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
        "selection_reason": "industry authority filing and permit verification",
    },
)
_CONTRACT_BASELINE_SURFACES = (
    {
        "surface_key": "award_announcement",
        "source_role": "award_or_candidate_announcement",
        "source_registry_id": "SRC-REG-AWARD-CITY-HTML",
        "selection_reason": "candidate or award announcement follow-up",
    },
    {
        "surface_key": "regulatory_publication",
        "source_role": "regulatory_publication",
        "source_registry_id": "SRC-REG-REG-NATIONAL-HTML",
        "selection_reason": "national regulatory publication cross-check",
    },
    {
        "surface_key": "annex_text",
        "source_role": "supplement_or_qa_text",
        "source_registry_id": "SRC-REG-ANNEX-PROVINCE-TEXT",
        "selection_reason": "province supplement text and version delta check",
    },
)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "live"}
    return bool(value)


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", (), {}):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _source_locator(surface_key: str, registry_id: str) -> str:
    return f"sandbox://stage1-source-blueprint/{surface_key}/{registry_id}"


class Stage1SourceBlueprintOrchestrator:
    def __init__(
        self,
        *,
        repository: Stage1SourceBlueprintRepository | None = None,
        market_scan_repository: Stage1MarketScanRepository | None = None,
        store: ContractStore | None = None,
    ) -> None:
        self.repository = repository or Stage1SourceBlueprintRepository()
        self.market_scan_repository = market_scan_repository or Stage1MarketScanRepository()
        self.store = store or ContractStore.default()

    def build(self, payload: Mapping[str, Any], *, persist: bool = True) -> dict[str, Any]:
        payload_dict = dict(payload)
        self._assert_plan_only_boundary(payload_dict)
        now = str(payload_dict.get("now") or utc_now_iso())
        market_scan = self._resolve_market_scan(payload_dict)
        opportunity = self._resolve_opportunity_candidate(payload_dict, market_scan)
        source_blueprint_plan_id = str(
            payload_dict.get("source_blueprint_plan_id")
            or build_id(
                "SRCBLUE",
                str(opportunity.get("opportunity_candidate_id") or opportunity.get("project_id") or "PLAN"),
            )
        )
        scan_run_id = str(
            payload_dict.get("scan_run_id")
            or market_scan.get("scan_run_id")
            or opportunity.get("scan_run_id")
            or ""
        )
        coverage_gap_signals = self._coverage_gap_signals(payload_dict, market_scan, opportunity)
        city_adapter_triggered = bool(coverage_gap_signals & CITY_COVERAGE_GAP_SIGNALS)
        region_code = str(opportunity.get("region_code") or payload_dict.get("region_code") or "UNKNOWN")
        commercial_pilot_policy = self._commercial_pilot_policy(region_code)
        source_mix = self._build_source_mix(
            opportunity=opportunity,
            city_adapter_triggered=city_adapter_triggered,
            coverage_gap_signals=coverage_gap_signals,
        )
        capture_steps = [
            self._capture_step(
                index=index,
                source=source,
                opportunity=opportunity,
                plan_id=source_blueprint_plan_id,
            )
            for index, source in enumerate(source_mix, start=1)
            if source["selected"]
        ]
        source_approval_summary = self._source_approval_summary(capture_steps)
        capture_plan_id = build_id("S2CAPPLAN", source_blueprint_plan_id)
        stage2_capture_plan = {
            "capture_plan_id": capture_plan_id,
            "plan_state": "PLAN_READY_NOT_EXECUTED",
            "target_stage": "stage2_ingestion",
            "opportunity_candidate_id": str(opportunity.get("opportunity_candidate_id", "")),
            "project_id": str(opportunity.get("project_id", "")),
            "project_name": str(opportunity.get("project_name", "")),
            "region_code": region_code,
            "capture_steps": capture_steps,
            "selected_source_registry_ids": [
                str(step.get("source_registry_id")) for step in capture_steps
            ],
            "execution_boundary": {
                "stage2_fetch_executed": False,
                "capture_execution_enabled": False,
                "real_external_fetch_enabled": False,
                "unregistered_capture_enabled": False,
                "customer_visible_claim_enabled": False,
            },
            "next_action": "DISPATCH_STAGE2_CAPTURE_PLAN",
        }
        plan = {
            "source_blueprint_plan_id": source_blueprint_plan_id,
            "source_blueprint_orchestrator_id": build_id("SRCBLUEORCH", source_blueprint_plan_id),
            "object_type": SOURCE_BLUEPRINT_OBJECT_TYPE,
            "scan_run_id": scan_run_id,
            "task_id": str(
                payload_dict.get("task_id")
                or market_scan.get("task_id")
                or opportunity.get("task_id")
                or source_blueprint_plan_id
            ),
            "source_blueprint_batch_id": str(
                payload_dict.get("source_blueprint_batch_id")
                or market_scan.get("batch_id")
                or market_scan.get("source_blueprint_batch_id")
                or "PTL-I100-ROADMAP-01"
            ),
            "created_at": now,
            "updated_at": now,
            "capability_state": "INTERNAL_READY",
            "plan_state": "PLAN_READY",
            "internal_only": True,
            "customer_visible": False,
            "capture_execution_enabled": False,
            "stage2_fetch_executed": False,
            "real_external_fetch_enabled": False,
            "unregistered_capture_enabled": False,
            "source_blueprint_auto_selection": True,
            "stage2_capture_plan_generation": True,
            "opportunity_candidate": opportunity,
            "source_mix": source_mix,
            "stage2_capture_plan": stage2_capture_plan,
            "coverage_gap_policy": {
                "city_adapter_trigger_mode": "GAP_DRIVEN_ONLY",
                "coverage_gap_signals": sorted(coverage_gap_signals),
                "city_adapter_triggered": city_adapter_triggered,
                "city_adapter_registry_id": "SRC-REG-PROC-CITY-PDF",
                "blanket_city_rollout_enabled": False,
            },
            "national_aggregator_policy": {
                "role": "FIRST_LEVEL_DISCOVERY_AND_DEDUPE_ONLY",
                "not_assumed": ["full_coverage", "realtime_sync"],
                "source_registry_id": "SRC-REG-PROC-NATIONAL-HTML",
            },
            "commercial_pilot_policy": commercial_pilot_policy,
            "pilot_province_portfolio": [dict(row) for row in PILOT_PROVINCE_PORTFOLIO],
            "source_approval_summary": source_approval_summary,
            "readback_summary": {
                "readback_state": "READBACK_READY",
                "repository_backed": persist,
                "replayable": persist,
                "source_blueprint_auto_selection": True,
                "stage2_capture_plan_generation": True,
                "selected_source_count": len(capture_steps),
                "city_adapter_trigger_mode": "GAP_DRIVEN_ONLY",
                "beijing_first_batch_commercial_pilot": False,
                "stage2_fetch_executed": False,
            },
            "controlled_opening_requirements": {
                "approved_source_selection_required": True,
                "unapproved_source_selected": source_approval_summary["unapproved_source_selected"],
                "real_external_fetch_enabled": False,
                "provider_call_enabled": False,
                "customer_visible_claim_enabled": False,
            },
            "next_action": "DISPATCH_STAGE2_CAPTURE_PLAN",
            "audit_refs": {
                "source_blueprint_audit_id": build_id("SRCBLUEAUD", source_blueprint_plan_id),
                "capture_plan_audit_id": build_id("S2CAPPLANAUD", source_blueprint_plan_id),
            },
        }
        if persist:
            self.repository.save(plan)
            plan["readback_summary"]["repository_backed"] = True
            plan["readback_summary"]["replayable"] = True
        return plan

    def readback(self, source_blueprint_plan_id: str) -> dict[str, Any]:
        return self.repository.readback(source_blueprint_plan_id)

    def replay(self, source_blueprint_plan_id: str) -> dict[str, Any]:
        return self.repository.replay(source_blueprint_plan_id)

    def _resolve_market_scan(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        market_scan = _as_mapping(payload.get("market_scan"))
        if market_scan:
            return market_scan
        scan_run_id = str(payload.get("scan_run_id") or payload.get("market_scan_run_id") or "")
        if not scan_run_id:
            return {}
        try:
            return dict(self.market_scan_repository.readback(scan_run_id).get("market_scan", {}))
        except ValueError:
            return {}

    def _resolve_opportunity_candidate(
        self,
        payload: Mapping[str, Any],
        market_scan: Mapping[str, Any],
    ) -> dict[str, Any]:
        candidate = _as_mapping(payload.get("opportunity_candidate"))
        if candidate:
            return candidate
        for key in ("opportunity_candidates", "market_scan_candidates"):
            candidates = _as_list(payload.get(key))
            if candidates and isinstance(candidates[0], Mapping):
                return dict(candidates[0])
        candidates = _as_list(market_scan.get("opportunity_candidates"))
        if candidates and isinstance(candidates[0], Mapping):
            return dict(candidates[0])
        raise ValueError("source blueprint requires an opportunity_candidate or a scan_run_id with selected candidates")

    def _coverage_gap_signals(
        self,
        payload: Mapping[str, Any],
        market_scan: Mapping[str, Any],
        opportunity: Mapping[str, Any],
    ) -> set[str]:
        values: list[Any] = []
        for source in (payload, market_scan, opportunity, _as_mapping(opportunity.get("source_refs"))):
            values.extend(_as_list(source.get("coverage_gap_signals")))
        return {str(value).strip() for value in values if str(value).strip()}

    def _commercial_pilot_policy(self, region_code: str) -> dict[str, Any]:
        is_beijing = region_code == "CN-BJ"
        pilot_codes = {row["region_code"] for row in PILOT_PROVINCE_PORTFOLIO}
        return {
            "candidate_region_code": region_code,
            "first_batch_pilot_region_codes": sorted(pilot_codes),
            "commercial_pilot_eligible": region_code in pilot_codes,
            "beijing_first_batch_commercial_pilot": False,
            "beijing_policy": "TECHNICAL_REGRESSION_ONLY" if is_beijing else "NOT_APPLICABLE",
            "selection_reason": "pilot_province_portfolio"
            if region_code in pilot_codes
            else "not_first_batch_commercial_pilot",
        }

    def _build_source_mix(
        self,
        *,
        opportunity: Mapping[str, Any],
        city_adapter_triggered: bool,
        coverage_gap_signals: set[str],
    ) -> list[dict[str, Any]]:
        source_mix = [
            self._source_decision(
                source,
                selected=True,
                selection_reason=str(source["selection_reason"]),
                trigger_signals=[],
            )
            for source in _SOURCE_SURFACES
        ]
        for surface in _CONTRACT_BASELINE_SURFACES:
            entry = dict(self.store.source_registry_index[str(surface["source_registry_id"])])
            source_mix.append(
                self._source_decision(
                    {
                        **surface,
                        "adapter_id": "contract_store_baseline",
                        "source_family": str(entry.get("source_family", "")),
                        "record_kind": "",
                    },
                    selected=True,
                    selection_reason=str(surface["selection_reason"]),
                    trigger_signals=[],
                )
            )
        city_surface = {
            "surface_key": "city_adapter",
            "source_role": "gap_driven_city_adapter",
            "adapter_id": LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
            "source_family": "PROCUREMENT_NOTICE",
            "source_registry_id": "SRC-REG-PROC-CITY-PDF",
            "record_kind": "",
            "selection_reason": "city source is only selected when a coverage gap is observed",
        }
        source_mix.append(
            self._source_decision(
                city_surface,
                selected=city_adapter_triggered,
                selection_reason="coverage_gap_signal"
                if city_adapter_triggered
                else "skipped_without_coverage_gap_signal",
                trigger_signals=sorted(coverage_gap_signals & CITY_COVERAGE_GAP_SIGNALS),
            )
        )
        return source_mix

    def _source_decision(
        self,
        source: Mapping[str, Any],
        *,
        selected: bool,
        selection_reason: str,
        trigger_signals: list[str],
    ) -> dict[str, Any]:
        registry_id = str(source["source_registry_id"])
        source_family = str(source.get("source_family", ""))
        contract_entry = self.store.source_registry_index.get(registry_id)
        adapter_policy = self._adapter_policy(
            registry_id=registry_id,
            source_family=source_family,
            record_kind=str(source.get("record_kind") or ""),
            surface_key=str(source["surface_key"]),
        )
        approved_by_contract = contract_entry is not None
        approved_by_adapter = bool(adapter_policy.get("registry_allowlisted"))
        return {
            "surface_key": str(source["surface_key"]),
            "source_role": str(source["source_role"]),
            "selected": selected,
            "selection_reason": selection_reason,
            "skip_reason": "" if selected else selection_reason,
            "source_registry_id": registry_id,
            "source_family": source_family,
            "record_kind": str(source.get("record_kind") or ""),
            "adapter_id": str(source.get("adapter_id") or adapter_policy.get("adapter_id") or ""),
            "approved": approved_by_contract or approved_by_adapter,
            "approval_source": "contract_store"
            if approved_by_contract
            else "stage2_adapter_allowlist"
            if approved_by_adapter
            else "unapproved",
            "contract_baseline_entry": approved_by_contract,
            "adapter_allowlisted": approved_by_adapter,
            "triggered_by_coverage_gap": bool(trigger_signals),
            "trigger_signals": list(trigger_signals),
            "planned_source_locator": _source_locator(str(source["surface_key"]), registry_id),
            "fetch_mode": "controlled_test_transport",
        }

    def _adapter_policy(
        self,
        *,
        registry_id: str,
        source_family: str,
        record_kind: str,
        surface_key: str,
    ) -> dict[str, Any]:
        request = PublicSourceSnapshotRequest(
            source_url=_source_locator(surface_key, registry_id),
            source_registry_id=registry_id,
            source_family=source_family,
            record_kind=record_kind or None,
            fetch_mode="controlled_test_transport",
        )
        config = resolve_public_source_adapter_config(request)
        return {
            "adapter_id": config.adapter_id,
            "registry_allowlisted": registry_id in config.allowlisted_source_registry_ids,
            "allowed_source_families": sorted(config.allowed_source_families),
            "allowlisted_source_registry_ids": sorted(config.allowlisted_source_registry_ids),
            "allowed_fetch_modes": sorted(config.allowed_fetch_modes),
        }

    def _capture_step(
        self,
        *,
        index: int,
        source: Mapping[str, Any],
        opportunity: Mapping[str, Any],
        plan_id: str,
    ) -> dict[str, Any]:
        registry_id = str(source["source_registry_id"])
        contract_entry = self.store.source_registry_index.get(registry_id)
        route_policy = (
            self.store.resolve_route_policy(
                route_policy_id=str(contract_entry.get("route_policy_id", "")),
                source_registry_id=registry_id,
            )
            if contract_entry
            else {}
        )
        return {
            "capture_step_id": build_id("S2CAPSTEP", plan_id, str(index).zfill(2)),
            "step_order": index,
            "surface_key": str(source["surface_key"]),
            "source_role": str(source["source_role"]),
            "source_registry_id": registry_id,
            "source_family": str(source.get("source_family", "")),
            "record_kind": str(source.get("record_kind", "")),
            "adapter_id": str(source.get("adapter_id", "")),
            "route_policy_id": str(
                contract_entry.get("route_policy_id")
                if contract_entry
                else "STAGE2-ADAPTER-ALLOWLIST-PLAN"
            ),
            "route_policy_source": "contract_store"
            if contract_entry
            else "stage2_adapter_runtime_allowlist",
            "default_route": str(
                contract_entry.get("default_route")
                if contract_entry
                else "CONTROLLED_TEST_TRANSPORT_PLAN"
            ),
            "fallback_route": str(
                contract_entry.get("fallback_route")
                if contract_entry
                else "ADAPTER_POLICY_FALLBACK"
            ),
            "route_fallback_order": list(route_policy.get("route_fallback_order", [])),
            "source_locator": str(source["planned_source_locator"]),
            "target_project_id": str(opportunity.get("project_id", "")),
            "target_company": str(
                opportunity.get("candidate_company")
                or opportunity.get("winner_name")
                or opportunity.get("first_rank_company")
                or ""
            ),
            "approved": bool(source.get("approved")),
            "approval_source": str(source.get("approval_source", "")),
            "triggered_by_coverage_gap": bool(source.get("triggered_by_coverage_gap", False)),
            "trigger_signals": list(source.get("trigger_signals", [])),
            "stage2_fetch_executed": False,
            "capture_execution_enabled": False,
            "real_external_fetch_enabled": False,
        }

    def _source_approval_summary(self, capture_steps: list[Mapping[str, Any]]) -> dict[str, Any]:
        selected_registry_ids = [str(step["source_registry_id"]) for step in capture_steps]
        unapproved = [
            registry_id
            for registry_id in selected_registry_ids
            if not any(
                str(step.get("source_registry_id")) == registry_id and bool(step.get("approved"))
                for step in capture_steps
            )
        ]
        return {
            "selected_source_registry_ids": selected_registry_ids,
            "approved_source_registry_ids": [
                str(step["source_registry_id"])
                for step in capture_steps
                if bool(step.get("approved"))
            ],
            "unapproved_source_registry_ids": unapproved,
            "unapproved_source_selected": bool(unapproved),
            "approval_sources": sorted(
                {str(step.get("approval_source")) for step in capture_steps if step.get("approval_source")}
            ),
        }

    def _assert_plan_only_boundary(self, payload: Mapping[str, Any]) -> None:
        requested_execution_flags = [flag for flag in _BLOCKED_EXECUTION_FLAGS if _truthy(payload.get(flag))]
        if requested_execution_flags:
            raise ValueError(
                "source blueprint builds a Stage2 capture plan only; blocked execution flags: "
                + ", ".join(requested_execution_flags)
            )


__all__ = [
    "CITY_COVERAGE_GAP_SIGNALS",
    "PILOT_PROVINCE_PORTFOLIO",
    "SOURCE_BLUEPRINT_OBJECT_TYPE",
    "SOURCE_BLUEPRINT_QUEUE_NAME",
    "Stage1SourceBlueprintOrchestrator",
]
