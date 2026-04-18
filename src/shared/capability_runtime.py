from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from shared.context_packet import ContextPacket
from shared.policy_executor import PolicyExecutor
from shared.state_packet import CapabilityResolution, StatePacket


class CapabilityResolver:
    DEFAULT_MODE_PRIORITY = (
        "EMERGENCY_OFF",
        "PERMANENTLY_BLOCKED",
        "BUILDABLE_BUT_OFF_BY_DEFAULT",
        "SHADOW_MODE",
        "DRY_RUN",
        "APPROVAL_REQUIRED",
        "INTERNAL_ONLY",
        "INTERNAL_GOVERNED",
        "REAL_RUN_READY",
    )
    DEFAULT_PROTECTED_SHORT_CIRCUIT_MODES = (
        "EMERGENCY_OFF",
        "PERMANENTLY_BLOCKED",
    )
    RELEASE_LEVEL_RANK = {
        "DEV_ALLOWED": 0,
        "INTERNAL_OPERABLE": 1,
        "LEADPACK_DELIVERABLE": 2,
        "EXTERNAL_BLOCKED": 3,
    }
    DEFAULT_ACTION = "PREVIEW_ONLY"
    DEFAULT_EFFECTIVE_MODE_SOURCE_ORDER = (
        "runtime_override",
        "target_policy_current_capability_mode",
        "target_registry_current_capability_mode",
        "family_current_capability_mode",
    )

    def __init__(self, settings: Any | None = None) -> None:
        repo_root = Path(settings.repo_root) if settings and getattr(settings, "repo_root", None) else Path(__file__).resolve().parents[2]
        self.repo_root = repo_root
        self.runtime_inventory = self._load_yaml("control/runtime_inventory.yaml")
        self.runtime_policy = self._load_json("contracts/release/runtime_policy_catalog.json")
        self.model_release_manifest = self._load_yaml("control/model_release_manifest.yaml")
        self.vendor_registry = self._load_json("contracts/sales/vendor_registry_catalog.json")
        self.source_vendor_usage_policy = self._load_json("contracts/sales/source_vendor_usage_policy.json")
        self.channel_vendor_execution_policy = self._load_json("contracts/sales/channel_vendor_execution_policy.json")
        self.model_catalog = self._load_json("contracts/model/model_catalog.json")
        self.tool_provider_registry = self._load_json("contracts/model/tool_provider_registry_catalog.json")
        self.tool_usage_policy = self._load_json("contracts/model/tool_usage_policy_catalog.json")
        self.model_usage_policy = self._load_json("contracts/model/model_usage_policy.json")
        self.release_gates = self._load_json("contracts/release/release_gates.json")

        self.family_policy_index = {
            entry["family_id"]: entry for entry in self.runtime_policy.get("capability_families", [])
        }
        self.family_inventory_index = self.runtime_inventory.get("capability_family_state_projection", {})
        self.vendor_index = {
            entry["vendor_id"]: entry for entry in self.vendor_registry.get("entries", [])
        }
        self.model_provider_index = {
            entry["provider_id"]: entry for entry in self.model_catalog.get("providers", [])
        }
        self.tool_provider_index = {
            entry["provider_id"]: entry for entry in self.tool_provider_registry.get("providers", [])
        }
        self.provider_family_projection_index = self.model_release_manifest.get("provider_family_projection", {})
        self.runtime_execution_projection_index = self.model_release_manifest.get("runtime_execution_projection", {})
        precedence_config = self.runtime_policy.get("runtime_resolver_precedence", {})
        self.mode_priority_order = tuple(
            self.runtime_policy.get("capability_mode_priority_order", self.DEFAULT_MODE_PRIORITY)
        )
        self.mode_priority_index = {
            mode: index for index, mode in enumerate(self.mode_priority_order)
        }
        self.effective_mode_source_order = tuple(
            precedence_config.get(
                "effective_capability_mode_sources",
                self.DEFAULT_EFFECTIVE_MODE_SOURCE_ORDER,
            )
        )
        self.precedence_group_resolution = str(
            precedence_config.get("within_precedence_group_resolution", "MOST_RESTRICTIVE_BY_PRIORITY_ORDER")
        )
        self.protected_short_circuit_modes = tuple(
            precedence_config.get(
                "protected_short_circuit_modes",
                self.DEFAULT_PROTECTED_SHORT_CIRCUIT_MODES,
            )
        )
        self.control_projection_sources_ignored_for_mode_resolution = tuple(
            precedence_config.get("control_projection_sources_ignored_for_mode_resolution", [])
        )
        self.external_blocked_release_level = str(
            precedence_config.get("release_layer_redline", "EXTERNAL_BLOCKED")
        )

    def _load_json(self, relative_path: str) -> dict[str, Any]:
        path = self.repo_root / relative_path
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_yaml(self, relative_path: str) -> dict[str, Any]:
        path = self.repo_root / relative_path
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def resolve(
        self,
        *,
        context: ContextPacket,
        capability_family: str,
        requested_action: str,
        target_id: str | None = None,
        target_type: str | None = None,
        target_role: str | None = None,
        release_level: str | None = None,
        approval_state: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> CapabilityResolution:
        requested_action = (requested_action or self.DEFAULT_ACTION).upper()
        release_level = release_level or context.release_level or "INTERNAL_OPERABLE"
        approval_state = approval_state or context.approval_state or "NOT_REQUIRED"
        metadata_map = dict(metadata or {})

        resolved_from: list[dict[str, Any]] = []
        allowed_modes: list[str] = []
        allowed_action_intents: list[str] = []
        blocked_action_intents: list[str] = []
        current_status = metadata_map.get("current_status")
        policy_state = metadata_map.get("policy_state")

        family_policy = self.family_policy_index.get(capability_family, {})
        if family_policy:
            allowed_modes.extend([str(mode) for mode in family_policy.get("allowed_capability_modes", [])])
            self._append_mode(
                resolved_from,
                "runtime_policy_family",
                family_policy.get("current_capability_mode"),
                "family_current_capability_mode",
            )

        if target_type == "source_vendor":
            source_result = self._resolve_source_vendor(stage=context.stage, target_id=target_id, target_role=target_role)
            resolved_from.extend(source_result["resolved_from"])
            allowed_modes.extend(source_result["allowed_modes"])
            allowed_action_intents.extend(source_result["allowed_action_intents"])
            blocked_action_intents.extend(source_result["blocked_action_intents"])
            current_status = current_status or source_result["current_status"]
            policy_state = policy_state or source_result["policy_state"]
        elif target_type == "execution_vendor":
            exec_result = self._resolve_execution_vendor(stage=context.stage, target_id=target_id, target_role=target_role)
            resolved_from.extend(exec_result["resolved_from"])
            allowed_modes.extend(exec_result["allowed_modes"])
            allowed_action_intents.extend(exec_result["allowed_action_intents"])
            blocked_action_intents.extend(exec_result["blocked_action_intents"])
            current_status = current_status or exec_result["current_status"]
            policy_state = policy_state or exec_result["policy_state"]
        elif target_type == "model_provider":
            model_result = self._resolve_model_provider(target_id=target_id)
            resolved_from.extend(model_result["resolved_from"])
            allowed_modes.extend(model_result["allowed_modes"])
            allowed_action_intents.extend(model_result["allowed_action_intents"])
            blocked_action_intents.extend(model_result["blocked_action_intents"])
            current_status = current_status or model_result["current_status"]
            policy_state = policy_state or model_result["policy_state"]
        elif target_type == "tool_provider":
            tool_result = self._resolve_tool_provider(stage=context.stage, target_id=target_id, target_role=target_role)
            resolved_from.extend(tool_result["resolved_from"])
            allowed_modes.extend(tool_result["allowed_modes"])
            allowed_action_intents.extend(tool_result["allowed_action_intents"])
            blocked_action_intents.extend(tool_result["blocked_action_intents"])
            current_status = current_status or tool_result["current_status"]
            policy_state = policy_state or tool_result["policy_state"]

        override_mode = metadata_map.get("override_mode") or context.override_mode(capability_family)
        self._append_mode(
            resolved_from,
            "runtime_override",
            override_mode,
            "runtime_override",
        )

        effective_mode = self._resolve_effective_mode(resolved_from)
        release_ceiling = self._release_ceiling_for_family(capability_family)
        control_projection = self._collect_control_projection(capability_family)

        decision, review_required, blocked_reason, short_circuit = self._decide(
            capability_family=capability_family,
            requested_action=requested_action,
            capability_mode=effective_mode,
            release_level=release_level,
            release_ceiling=release_ceiling,
            approval_state=approval_state,
            current_status=current_status,
            policy_state=policy_state,
            allowed_action_intents=allowed_action_intents,
            blocked_action_intents=blocked_action_intents,
        )

        governance_additions = {
            "required_approval": approval_state != "APPROVED" and effective_mode in ("APPROVAL_REQUIRED", "REAL_RUN_READY"),
            "release_level": release_level,
            "release_layer_ceiling": release_ceiling,
            "current_status": current_status or "UNKNOWN",
            "policy_state": policy_state or "UNSPECIFIED",
            "allowed_action_intents": sorted(set(allowed_action_intents)),
            "blocked_action_intents": sorted(set(blocked_action_intents)),
            "resolved_from": [item["source"] for item in resolved_from],
            "control_projection": control_projection,
        }
        trace_fields = {
            "event": "capability_resolution",
            "capability_family": capability_family,
            "requested_action": requested_action,
            "target_id": target_id,
            "target_type": target_type,
            "target_role": target_role,
            "release_level": release_level,
            "approval_state": approval_state,
            "capability_mode": effective_mode,
            "decision_state": decision,
            "review_required": review_required,
            "blocked_reason": blocked_reason,
            "current_status": current_status,
            "policy_state": policy_state,
            "resolved_from": resolved_from,
            "control_projection": control_projection,
            "short_circuit": short_circuit,
        }
        return CapabilityResolution(
            capability_family=capability_family,
            requested_action=requested_action,
            capability_mode=effective_mode,
            decision=decision,
            review_required=review_required,
            blocked_reason=blocked_reason,
            trace_fields=trace_fields,
            governance_additions=governance_additions,
        )

    def _append_mode(
        self,
        resolved_from: list[dict[str, Any]],
        source: str,
        mode: str | None,
        precedence_group: str,
    ) -> None:
        if mode:
            resolved_from.append(
                {
                    "source": source,
                    "mode": str(mode),
                    "precedence_group": precedence_group,
                }
            )

    def _collect_control_projection(self, capability_family: str) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "resolution_role": "TRACE_ONLY_PROJECTION",
            "mode_resolution_source": False,
            "ignored_sources": list(self.control_projection_sources_ignored_for_mode_resolution),
        }

        family_projection = self.family_inventory_index.get(capability_family, {})
        if family_projection:
            projection["runtime_inventory"] = {
                "projected_current_mode": family_projection.get("projected_current_mode"),
                "projected_release_layer_ceiling": family_projection.get("projected_release_layer_ceiling"),
                "projected_from": family_projection.get("projected_from"),
                "projection_only": family_projection.get("projection_only", True),
            }

        provider_projection = self.provider_family_projection_index.get(capability_family, {})
        if provider_projection:
            projection["model_release_manifest_provider"] = {
                "projected_current_mode": provider_projection.get("projected_current_capability_mode"),
                "projected_release_layer_ceiling": provider_projection.get("projected_release_layer_ceiling"),
                "projected_from": provider_projection.get("projected_from"),
                "projection_only": provider_projection.get("projection_only", True),
            }

        runtime_projection = self.runtime_execution_projection_index.get(capability_family, {})
        if runtime_projection:
            projection["model_release_manifest_runtime"] = {
                "projected_current_mode": runtime_projection.get("projected_current_capability_mode"),
                "projected_release_layer_ceiling": runtime_projection.get("projected_release_layer_ceiling"),
                "projected_from": runtime_projection.get("projected_from"),
                "projection_only": runtime_projection.get("projection_only", True),
            }

        return projection

    def _resolve_source_vendor(self, *, stage: int, target_id: str | None, target_role: str | None) -> dict[str, Any]:
        resolved_from: list[dict[str, Any]] = []
        allowed_modes: list[str] = []
        allowed_action_intents: list[str] = []
        blocked_action_intents: list[str] = []
        current_status: str | None = None
        policy_state: str | None = None

        entry = self.vendor_index.get(target_id or "")
        if entry:
            current_status = str(entry.get("current_status"))
            allowed_modes.extend([str(mode) for mode in entry.get("allowed_capability_modes", [])])
            self._append_mode(
                resolved_from,
                "vendor_registry",
                entry.get("current_capability_mode"),
                "target_registry_current_capability_mode",
            )

        for policy in self.source_vendor_usage_policy.get("stagePolicies", []):
            if not self._stage_matches(stage, str(policy.get("stage_range", ""))):
                continue
            if target_role and str(policy.get("vendor_role")) != target_role:
                continue
            policy_state = str(policy.get("usage_state", policy_state or "UNSPECIFIED"))
            allowed_modes.extend([str(mode) for mode in policy.get("allowed_capability_modes", [])])
            allowed_action_intents.extend([str(item) for item in policy.get("allowed_action_intents", [])])
            blocked_action_intents.extend([str(item) for item in policy.get("blocked_action_intents", [])])
            self._append_mode(
                resolved_from,
                "source_vendor_usage_policy",
                policy.get("current_capability_mode"),
                "target_policy_current_capability_mode",
            )
            break

        return {
            "resolved_from": resolved_from,
            "allowed_modes": allowed_modes,
            "allowed_action_intents": allowed_action_intents,
            "blocked_action_intents": blocked_action_intents,
            "current_status": current_status,
            "policy_state": policy_state,
        }

    def _resolve_execution_vendor(self, *, stage: int, target_id: str | None, target_role: str | None) -> dict[str, Any]:
        resolved_from: list[dict[str, Any]] = []
        allowed_modes: list[str] = []
        allowed_action_intents: list[str] = []
        blocked_action_intents: list[str] = []
        current_status: str | None = None
        policy_state: str | None = None

        entry = self.vendor_index.get(target_id or "")
        if entry:
            current_status = str(entry.get("current_status"))
            allowed_modes.extend([str(mode) for mode in entry.get("allowed_capability_modes", [])])
            self._append_mode(
                resolved_from,
                "vendor_registry",
                entry.get("current_capability_mode"),
                "target_registry_current_capability_mode",
            )

        for policy in self.channel_vendor_execution_policy.get("entries", []):
            if int(policy.get("stage", 0)) != stage:
                continue
            if target_id and str(policy.get("vendor_id")) != target_id:
                continue
            policy_state = str(policy.get("execution_policy_state", policy_state or "UNSPECIFIED"))
            allowed_modes.extend([str(mode) for mode in policy.get("allowed_capability_modes", [])])
            allowed_action_intents.extend([str(item) for item in policy.get("allowed_action_intents", [])])
            blocked_action_intents.extend([str(item) for item in policy.get("blocked_action_intents", [])])
            self._append_mode(
                resolved_from,
                "channel_vendor_execution_policy",
                policy.get("current_capability_mode"),
                "target_policy_current_capability_mode",
            )
            break

        return {
            "resolved_from": resolved_from,
            "allowed_modes": allowed_modes,
            "allowed_action_intents": allowed_action_intents,
            "blocked_action_intents": blocked_action_intents,
            "current_status": current_status,
            "policy_state": policy_state,
        }

    def _resolve_model_provider(self, *, target_id: str | None) -> dict[str, Any]:
        resolved_from: list[dict[str, Any]] = []
        allowed_modes: list[str] = []
        allowed_action_intents: list[str] = []
        blocked_action_intents: list[str] = []
        current_status: str | None = None
        policy_state = "model_provider"

        entry = self.model_provider_index.get(target_id or "")
        if entry:
            current_status = str(entry.get("current_status"))
            allowed_modes.extend([str(mode) for mode in entry.get("allowed_capability_modes", [])])
            self._append_mode(
                resolved_from,
                "model_catalog_provider",
                entry.get("current_capability_mode"),
                "target_registry_current_capability_mode",
            )
        allowed_action_intents.extend([str(item) for item in self.model_usage_policy.get("allowed_action_intents", [])])
        blocked_action_intents.extend([str(item) for item in self.model_usage_policy.get("blocked_action_intents", [])])
        return {
            "resolved_from": resolved_from,
            "allowed_modes": allowed_modes,
            "allowed_action_intents": allowed_action_intents,
            "blocked_action_intents": blocked_action_intents,
            "current_status": current_status,
            "policy_state": policy_state,
        }

    def _resolve_tool_provider(self, *, stage: int, target_id: str | None, target_role: str | None) -> dict[str, Any]:
        resolved_from: list[dict[str, Any]] = []
        allowed_modes: list[str] = []
        allowed_action_intents: list[str] = []
        blocked_action_intents: list[str] = []
        current_status: str | None = None
        policy_state = "tool_provider"

        entry = self.tool_provider_index.get(target_id or "")
        if entry:
            current_status = str(entry.get("current_status"))
        allowed_action_intents.extend([str(item) for item in self.tool_usage_policy.get("allowed_action_intents", [])])
        blocked_action_intents.extend([str(item) for item in self.tool_usage_policy.get("blocked_action_intents", [])])
        for policy in self.tool_usage_policy.get("policies", []):
            allowed_stages = [int(value) for value in policy.get("allowed_stages", [])]
            if allowed_stages and stage not in allowed_stages:
                continue
            if target_role and str(policy.get("provider_role")) != target_role:
                continue
            allowed_modes.extend([str(mode) for mode in policy.get("allowed_capability_modes", [])])
            allowed_action_intents.extend([str(item) for item in policy.get("allowed_action_intents", [])])
            blocked_action_intents.extend([str(item) for item in policy.get("blocked_action_intents", [])])
            self._append_mode(
                resolved_from,
                "tool_usage_policy_catalog",
                policy.get("current_capability_mode"),
                "target_policy_current_capability_mode",
            )
            break
        return {
            "resolved_from": resolved_from,
            "allowed_modes": allowed_modes,
            "allowed_action_intents": allowed_action_intents,
            "blocked_action_intents": blocked_action_intents,
            "current_status": current_status,
            "policy_state": policy_state,
        }

    def _pick_mode_by_priority(self, modes: list[str]) -> str | None:
        if not modes:
            return None
        unique_modes = list(dict.fromkeys(str(mode) for mode in modes if mode))
        if not unique_modes:
            return None
        return min(
            unique_modes,
            key=lambda mode: self.mode_priority_index.get(mode, len(self.mode_priority_index)),
        )

    def _resolve_effective_mode(self, resolved_from: list[dict[str, Any]]) -> str:
        modes = [entry["mode"] for entry in resolved_from if entry.get("mode")]
        for protected_mode in self.protected_short_circuit_modes:
            if protected_mode in modes:
                return protected_mode
        for precedence_group in self.effective_mode_source_order:
            group_modes = [
                entry["mode"]
                for entry in resolved_from
                if entry.get("precedence_group") == precedence_group and entry.get("mode")
            ]
            if group_modes:
                if self.precedence_group_resolution == "MOST_RESTRICTIVE_BY_PRIORITY_ORDER":
                    picked = self._pick_mode_by_priority(group_modes)
                    if picked:
                        return picked
                return group_modes[-1]
        picked = self._pick_mode_by_priority(modes)
        return picked or "INTERNAL_ONLY"

    def _release_ceiling_for_family(self, capability_family: str) -> str:
        family_policy = self.family_policy_index.get(capability_family, {})
        if family_policy.get("release_layer_ceiling"):
            return str(family_policy["release_layer_ceiling"])
        return "EXTERNAL_BLOCKED"

    def _decide(
        self,
        *,
        capability_family: str,
        requested_action: str,
        capability_mode: str,
        release_level: str,
        release_ceiling: str,
        approval_state: str,
        current_status: str | None,
        policy_state: str | None,
        allowed_action_intents: list[str],
        blocked_action_intents: list[str],
    ) -> tuple[str, bool, str | None, bool]:
        blocked_reason: str | None = None
        short_circuit = False
        decision_matrix = self.runtime_policy.get("decision_matrix", {})
        matrix_entry = (
            decision_matrix.get(requested_action, {}).get(capability_mode)
            if isinstance(decision_matrix, dict)
            else None
        )

        if capability_mode == "EMERGENCY_OFF":
            return "BLOCK", False, f"{capability_family} emergency off", True
        if capability_mode == "PERMANENTLY_BLOCKED":
            return "BLOCK", False, f"{capability_family} permanently blocked", True

        if release_level == self.external_blocked_release_level and requested_action == "LIVE_EXECUTION":
            return "BLOCK", False, "external release blocked redline", True
        if self.RELEASE_LEVEL_RANK.get(release_level, 0) > self.RELEASE_LEVEL_RANK.get(release_ceiling, 3):
            return "BLOCK", False, f"{capability_family} release ceiling {release_ceiling}", False

        if blocked_action_intents and requested_action in blocked_action_intents:
            return "BLOCK", False, f"{capability_family} blocked for {requested_action}", False
        if allowed_action_intents and requested_action not in allowed_action_intents:
            blocked_reason = f"{capability_family} action {requested_action} not permitted"
            if requested_action == "LIVE_EXECUTION":
                return "BLOCK", False, blocked_reason, False
            return "REVIEW", True, blocked_reason, False

        if current_status == "BLOCKED" and requested_action in ("APPROVAL_EXECUTION", "LIVE_EXECUTION"):
            return "BLOCK", False, f"{capability_family} target status blocked", False
        if policy_state == "BLOCKED" and requested_action in ("APPROVAL_EXECUTION", "LIVE_EXECUTION"):
            return "BLOCK", False, f"{capability_family} policy state blocked", False

        if matrix_entry and requested_action in ("INTERNAL_SOURCE_READ", "PREVIEW_ONLY", "DRY_RUN", "INTERNAL_WRITEBACK"):
            return str(matrix_entry.get("decision", "ALLOW")), bool(matrix_entry.get("review_required", False)), None, False

        if requested_action == "LIVE_EXECUTION":
            if capability_mode != "REAL_RUN_READY":
                return "BLOCK", False, f"{capability_family} requires REAL_RUN_READY for live execution", False
            if approval_state != "APPROVED":
                return "REVIEW", True, f"{capability_family} requires approval before live execution", False
            return "ALLOW", False, None, False

        if requested_action == "APPROVAL_EXECUTION":
            if matrix_entry and str(matrix_entry.get("decision")) == "BLOCK":
                return "BLOCK", False, f"{capability_family} cannot enter approval execution from {capability_mode}", False
            if approval_state != "APPROVED":
                return "REVIEW", True, f"{capability_family} approval pending", False
            if capability_mode in ("BUILDABLE_BUT_OFF_BY_DEFAULT", "SHADOW_MODE", "DRY_RUN"):
                return "BLOCK", False, f"{capability_family} mode {capability_mode} cannot execute after approval", False
            return "ALLOW", False, None, False

        if requested_action in ("INTERNAL_SOURCE_READ", "MODEL_ASSIST", "TOOL_QUERY"):
            if capability_mode == "APPROVAL_REQUIRED":
                return "REVIEW", True, f"{capability_family} requires review before {requested_action}", False
            return "ALLOW", False, None, False

        if capability_mode in ("APPROVAL_REQUIRED", "SHADOW_MODE", "BUILDABLE_BUT_OFF_BY_DEFAULT"):
            return "REVIEW", True, f"{capability_family} requires governed execution for {requested_action}", False
        return "ALLOW", False, None, False

    def _stage_matches(self, stage: int, stage_range: str) -> bool:
        if not stage_range:
            return False
        if "-" in stage_range:
            start, end = stage_range.split("-", 1)
            return int(start) <= stage <= int(end)
        return int(stage_range) == stage


class CapabilityRuntime:
    POLICY_SEQUENCES = {
        "stage7_sales": [
            "window_value",
            "price_normalization",
            "competitor_confidence",
            "value_scoring",
            "buyer_fit_scorecard",
            "sku_recommendation",
        ],
        "stage8_outreach": [
            "contact_source_policy",
            "contact_compliance",
            "contact_priority",
            "outreach_cadence",
            "retry_policy",
            "touch_stop",
        ],
        "stage9_delivery": [
            "payment_exception",
            "delivery_exception",
            "outcome_taxonomy",
            "governance_taxonomy",
        ],
    }

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self.executor = PolicyExecutor(settings)
        self.resolver = CapabilityResolver(settings)

    def resolve_permissions(
        self,
        context: ContextPacket,
        checks: list[dict[str, Any]],
        state: StatePacket | None = None,
    ) -> StatePacket:
        state = state or StatePacket(capability_mode=context.capability_mode)
        state.trace.append(
            {
                "event": "load_permission_context",
                "capability_mode": context.capability_mode,
                "stage": context.stage,
                "project_id": context.project_id,
                "release_level": context.release_level,
                "approval_state": context.approval_state,
            }
        )
        for check in checks:
            resolution = self.resolver.resolve(
                context=context,
                capability_family=check["capability_family"],
                requested_action=check.get("requested_action", CapabilityResolver.DEFAULT_ACTION),
                target_id=check.get("target_id"),
                target_type=check.get("target_type"),
                target_role=check.get("target_role"),
                release_level=check.get("release_level"),
                approval_state=check.get("approval_state"),
                metadata=check.get("metadata"),
            )
            state.add_capability_resolution(resolution)
            if resolution.trace_fields.get("short_circuit"):
                break
        state.trace.append(
            {
                "event": "write_permission_trace",
                "decision_state": state.decision_state,
                "permission_review_reasons": list(state.permission_review_reasons),
                "permission_blocked_reasons": list(state.permission_blocked_reasons),
                "permission_short_circuit": state.permission_short_circuit,
            }
        )
        return state

    def run(self, context: ContextPacket, state: StatePacket | None = None) -> StatePacket:
        state = state or StatePacket(capability_mode=context.capability_mode)
        state.trace.append(
            {
                "event": "load_context_state",
                "capability_mode": context.capability_mode,
                "stage": context.stage,
                "project_id": context.project_id,
            }
        )
        sequence = self.POLICY_SEQUENCES.get(context.capability_mode, [])
        state.trace.append(
            {
                "event": "resolve_capability_mode",
                "capability_mode": context.capability_mode,
                "policy_sequence": sequence,
            }
        )
        for policy_key in sequence:
            state.trace.append({"event": "load_policy", "policy_key": policy_key})
            decision = self.executor.execute(policy_key, context, state)
            state.add_decision(decision)
            state.trace.append(
                {
                    "event": "emit_decision",
                    "policy_key": policy_key,
                    "decision_state": decision.decision_state,
                }
            )
        state.trace.append(
            {
                "event": "write_trace",
                "decision_state": state.decision_state,
                "fallback_reasons": state.fallback_reasons,
                "review_reasons": state.review_reasons,
                "blocked_reasons": state.blocked_reasons,
                "permission_review_reasons": state.permission_review_reasons,
                "permission_blocked_reasons": state.permission_blocked_reasons,
            }
        )
        state.trace.append({"event": state.decision_state.lower()})
        return state


__all__ = ["CapabilityResolver", "CapabilityRuntime"]
