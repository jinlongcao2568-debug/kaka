from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from storage.operator_workbench_projection import (
    build_operator_context_projection,
    build_workbench_replay_projection,
    sanitize_transient_preview_context,
)
from shared.contract_loader import load_contract


STAGE6_SURFACE_ID = "review_report_workbench"
STAGE6_OPERATOR_OPERATION_ID = "submitStage6OperatorAction"
STAGE6_FORMAL_OBJECTS = (
    "project_fact",
    "report_record",
    "review_queue_profile",
    "challenger_candidate_profile",
    "legal_action_recommendation",
)


@dataclass(frozen=True)
class ReviewActionSpec:
    action_id: str
    applies_to_objects: tuple[str, ...]
    surface_modes: tuple[str, ...]
    requires_approval_chain: bool
    requires_audit_trace: bool
    review_requirement: str
    audit_requirement: str
    internal_only: bool
    reads_repository_boundary: bool
    persists_governed_state: bool
    resulting_operational_state: str | None
    resulting_assignment_lifecycle_state: str | None
    allowed_current_operational_states: tuple[str, ...]
    allowed_surface_operational_states: tuple[str, ...]
    allowed_assignment_lifecycle_states: tuple[str, ...]


@dataclass(frozen=True)
class ButtonFlowSpec:
    flow_id: str
    button_type: str
    from_workbench: str
    api_operation_id: str | None
    review_action_id: str | None
    allowed_when: tuple[str, ...]
    blocked_when: tuple[str, ...]


@dataclass(frozen=True)
class WorkQueueProfile:
    profile_id: str
    stage_scope: int
    allowed_surface_operational_states: tuple[str, ...]
    allowed_current_operational_states: tuple[str, ...]
    work_item_key_components: tuple[str, ...]
    lifecycle_states: tuple[str, ...]
    operational_lifecycle_map: Mapping[str, str]
    assignment_policy: Mapping[str, Any]


@dataclass(frozen=True)
class PendingButtonFlow:
    button_flow_id: str
    action_id: str
    button_type: str

    def as_payload(self) -> dict[str, str]:
        return {
            "button_flow_id": self.button_flow_id,
            "action_id": self.action_id,
            "button_type": self.button_type,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _review_action_specs() -> dict[str, ReviewActionSpec]:
    catalog = load_contract("contracts/ui/review_action_catalog.json")
    specs: dict[str, ReviewActionSpec] = {}
    for entry in catalog["actions"]:
        action_id = str(entry["actionId"])
        specs[action_id] = ReviewActionSpec(
            action_id=action_id,
            applies_to_objects=tuple(entry.get("appliesToObjects", [])),
            surface_modes=tuple(entry.get("surfaceModes", [])),
            requires_approval_chain=bool(entry.get("requiresApprovalChain", False)),
            requires_audit_trace=bool(entry.get("requiresAuditTrace", False)),
            review_requirement=str(entry.get("reviewRequirement", "none")),
            audit_requirement=str(entry.get("auditRequirement", "not_required")),
            internal_only=bool(entry.get("internalOnly", False)),
            reads_repository_boundary=bool(entry.get("readsRepositoryBoundary", False)),
            persists_governed_state=bool(entry.get("persistsGovernedState", False)),
            resulting_operational_state=str(entry["resultingOperationalState"])
            if entry.get("resultingOperationalState")
            else None,
            resulting_assignment_lifecycle_state=str(entry["resultingAssignmentLifecycleState"])
            if entry.get("resultingAssignmentLifecycleState")
            else None,
            allowed_current_operational_states=tuple(entry.get("allowedCurrentOperationalStates", [])),
            allowed_surface_operational_states=tuple(entry.get("allowedSurfaceOperationalStates", [])),
            allowed_assignment_lifecycle_states=tuple(entry.get("allowedAssignmentLifecycleStates", [])),
        )
    specs.update(_stage6_review_action_specs())
    return specs


@lru_cache(maxsize=1)
def _button_flow_specs() -> dict[str, ButtonFlowSpec]:
    catalog = load_contract("contracts/ui/button_flow_catalog.json")
    specs: dict[str, ButtonFlowSpec] = {}
    for entry in catalog["flows"]:
        flow_id = str(entry["flowId"])
        specs[flow_id] = ButtonFlowSpec(
            flow_id=flow_id,
            button_type=str(entry.get("buttonType", "unknown")),
            from_workbench=str(entry.get("fromWorkbench", "")),
            api_operation_id=str(entry["apiOperationId"]) if entry.get("apiOperationId") else None,
            review_action_id=str(entry["reviewActionId"]) if entry.get("reviewActionId") else None,
            allowed_when=tuple(entry.get("allowedWhen", [])),
            blocked_when=tuple(entry.get("blockedWhen", [])),
        )
    specs.update(_stage6_button_flow_specs())
    return specs


@lru_cache(maxsize=1)
def _queue_profiles() -> dict[int, WorkQueueProfile]:
    catalog = load_contract("contracts/ui/page_surface_states.json")
    profiles: dict[int, WorkQueueProfile] = {}
    for entry in catalog.get("workQueueProfiles", []):
        stage_scope = int(entry["stageScope"])
        profiles[stage_scope] = WorkQueueProfile(
            profile_id=str(entry["profileId"]),
            stage_scope=stage_scope,
            allowed_surface_operational_states=tuple(entry.get("allowedSurfaceOperationalStates", [])),
            allowed_current_operational_states=tuple(entry.get("allowedCurrentOperationalStates", [])),
            work_item_key_components=tuple(entry.get("workItemKeyComponents", [])),
            lifecycle_states=tuple(entry.get("lifecycleStates", [])),
            operational_lifecycle_map=dict(entry.get("operationalLifecycleMap", {})),
            assignment_policy=dict(entry.get("assignmentPolicy", {})),
        )
    profiles[6] = _stage6_work_queue_profile()
    return profiles


def _stage6_review_action_specs() -> dict[str, ReviewActionSpec]:
    common = {
        "applies_to_objects": STAGE6_FORMAL_OBJECTS,
        "surface_modes": ("preview-only",),
        "requires_approval_chain": False,
        "requires_audit_trace": False,
        "internal_only": True,
        "reads_repository_boundary": True,
        "persists_governed_state": False,
        "allowed_surface_operational_states": ("preview_ready", "review_required", "governed_hold"),
        "allowed_assignment_lifecycle_states": ("assigned", "returned", "in_review", "unassigned"),
    }
    return {
        "stage6_mark_reviewed": ReviewActionSpec(
            action_id="stage6_mark_reviewed",
            review_requirement="stage6_internal_review",
            audit_requirement="operator_action_history_persisted",
            resulting_operational_state="action_completed",
            resulting_assignment_lifecycle_state="completed",
            allowed_current_operational_states=(
                "ready_for_internal_operator_action",
                "review_required",
                "action_returned_for_revision",
            ),
            **common,
        ),
        "stage6_return_for_revision": ReviewActionSpec(
            action_id="stage6_return_for_revision",
            review_requirement="stage6_internal_revision_required",
            audit_requirement="operator_action_history_persisted",
            resulting_operational_state="action_returned_for_revision",
            resulting_assignment_lifecycle_state="returned",
            allowed_current_operational_states=(
                "ready_for_internal_operator_action",
                "review_required",
            ),
            **common,
        ),
    }


def _stage6_button_flow_specs() -> dict[str, ButtonFlowSpec]:
    return {
        "submit_stage6_mark_reviewed": ButtonFlowSpec(
            flow_id="submit_stage6_mark_reviewed",
            button_type="review",
            from_workbench=STAGE6_SURFACE_ID,
            api_operation_id=STAGE6_OPERATOR_OPERATION_ID,
            review_action_id="stage6_mark_reviewed",
            allowed_when=("repository_state_available", "internal_only_surface"),
            blocked_when=("external_surface_requested", "live_execution_requested"),
        ),
        "submit_stage6_return_for_revision": ButtonFlowSpec(
            flow_id="submit_stage6_return_for_revision",
            button_type="review",
            from_workbench=STAGE6_SURFACE_ID,
            api_operation_id=STAGE6_OPERATOR_OPERATION_ID,
            review_action_id="stage6_return_for_revision",
            allowed_when=("repository_state_available", "internal_only_surface"),
            blocked_when=("external_surface_requested", "live_execution_requested"),
        ),
    }


def _stage6_work_queue_profile() -> WorkQueueProfile:
    return WorkQueueProfile(
        profile_id="stage6_review_report_operator_queue",
        stage_scope=6,
        allowed_surface_operational_states=("preview_ready", "review_required", "governed_hold"),
        allowed_current_operational_states=(
            "review_required",
            "ready_for_internal_operator_action",
            "action_completed",
            "action_returned_for_revision",
        ),
        work_item_key_components=(
            "stage_scope",
            "surface_id",
            "primary_object_type",
            "primary_record_id",
        ),
        lifecycle_states=("unassigned", "assigned", "in_review", "returned", "completed", "denied"),
        operational_lifecycle_map={
            "ready_for_internal_operator_action": "assigned",
            "review_required": "in_review",
            "governed_hold": "in_review",
            "action_returned_for_revision": "returned",
            "action_completed": "completed",
            "action_denied": "denied",
        },
        assignment_policy={
            "assignmentProfileId": "stage6_review_report_assignment",
            "rosterBinding": "currentTask",
            "assignedOwnerRole": "single_operator",
            "reviewerRole": "single_operator",
            "simplifiedBoundary": [
                "no_claim",
                "no_reassign",
                "stage6_internal_only_queue",
            ],
        },
    )


def review_action_spec(action_id: str) -> ReviewActionSpec:
    return _review_action_specs()[action_id]


def button_flow_spec(flow_id: str) -> ButtonFlowSpec:
    return _button_flow_specs()[flow_id]


def work_queue_profile(stage_scope: int) -> WorkQueueProfile:
    return _queue_profiles()[stage_scope]


def build_work_item_key(
    *,
    stage_scope: int,
    surface_id: str,
    primary_object_type: str,
    primary_record_id: str,
) -> str:
    profile = work_queue_profile(stage_scope)
    values = {
        "stage_scope": stage_scope,
        "surface_id": surface_id,
        "primary_object_type": primary_object_type,
        "primary_record_id": primary_record_id,
    }
    return ":".join(str(values[name]) for name in profile.work_item_key_components)


def resolve_button_flow(
    *,
    surface_id: str,
    action_id: str,
    button_flow_id: str | None,
) -> ButtonFlowSpec | None:
    candidates = [
        flow
        for flow in _button_flow_specs().values()
        if flow.from_workbench == surface_id and flow.review_action_id == action_id
    ]
    if button_flow_id:
        return next((flow for flow in candidates if flow.flow_id == button_flow_id), None)
    if len(candidates) == 1:
        return candidates[0]
    return None


def list_pending_button_flows(
    *,
    stage_scope: int,
    surface_id: str,
    surface_operational_state: str,
    current_operational_state: str,
    assignment_lifecycle_state: str,
    has_repository_state: bool,
    has_approval_chain: bool,
    has_audit_trace: bool,
    internal_only: bool,
) -> list[PendingButtonFlow]:
    pending: list[PendingButtonFlow] = []
    seen: set[tuple[str, str]] = set()
    for flow in _button_flow_specs().values():
        if flow.from_workbench != surface_id or not flow.review_action_id:
            continue
        action = _review_action_specs().get(flow.review_action_id)
        if action is None:
            continue
        if not _action_is_currently_allowed(
            action=action,
            flow=flow,
            surface_operational_state=surface_operational_state,
            current_operational_state=current_operational_state,
            assignment_lifecycle_state=assignment_lifecycle_state,
            has_repository_state=has_repository_state,
            has_approval_chain=has_approval_chain,
            has_audit_trace=has_audit_trace,
            internal_only=internal_only,
        ):
            continue
        key = (flow.flow_id, action.action_id)
        if key in seen:
            continue
        pending.append(
            PendingButtonFlow(
                button_flow_id=flow.flow_id,
                action_id=action.action_id,
                button_type=flow.button_type,
            )
        )
        seen.add(key)
    return pending


def action_is_currently_allowed(
    *,
    action_id: str,
    surface_id: str,
    surface_operational_state: str,
    current_operational_state: str,
    assignment_lifecycle_state: str,
    button_flow_id: str | None,
    has_repository_state: bool,
    has_approval_chain: bool,
    has_audit_trace: bool,
    internal_only: bool,
) -> tuple[ReviewActionSpec, ButtonFlowSpec | None]:
    action = review_action_spec(action_id)
    flow = resolve_button_flow(surface_id=surface_id, action_id=action_id, button_flow_id=button_flow_id)
    if flow is None:
        raise KeyError("button_flow_not_resolved")
    if not _action_is_currently_allowed(
        action=action,
        flow=flow,
        surface_operational_state=surface_operational_state,
        current_operational_state=current_operational_state,
        assignment_lifecycle_state=assignment_lifecycle_state,
        has_repository_state=has_repository_state,
        has_approval_chain=has_approval_chain,
        has_audit_trace=has_audit_trace,
        internal_only=internal_only,
    ):
        raise KeyError("action_not_allowed")
    return action, flow


def resolve_assignment(
    *,
    stage_scope: int,
    current_operational_state: str,
) -> dict[str, Any]:
    profile = work_queue_profile(stage_scope)
    policy = dict(profile.assignment_policy)
    roster = _load_roster_binding(str(policy.get("rosterBinding", "")))

    assigned_owner_role = str(
        roster.get("assigned_owner_role")
        or roster.get("responsible_role")
        or policy.get("assignedOwnerRole")
        or ""
    )
    reviewer_role = str(
        roster.get("reviewer_role")
        or roster.get("responsible_role")
        or policy.get("reviewerRole")
        or ""
    )
    assigned_owner = str(roster.get("assigned_owner") or roster.get("responsible_person") or "").strip()
    reviewer = str(roster.get("reviewer") or roster.get("responsible_person") or "").strip()
    resolved_from = str(policy.get("rosterBinding") or "unresolved")
    lifecycle_state = _resolve_lifecycle_state(
        profile=profile,
        current_operational_state=current_operational_state,
        has_assignment=bool(assigned_owner),
    )
    return {
        "assignment_profile_id": str(policy.get("assignmentProfileId", profile.profile_id)),
        "assignment_lifecycle_state": lifecycle_state,
        "assigned_owner_role": assigned_owner_role,
        "assigned_owner": assigned_owner,
        "reviewer_role": reviewer_role,
        "reviewer": reviewer,
        "resolved_from": resolved_from if assigned_owner or reviewer else "unassigned",
        "simplified_boundary": list(policy.get("simplifiedBoundary", [])),
    }


def _load_current_task() -> Mapping[str, Any]:
    path = _repo_root() / "control" / "current_task.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_roster_binding(binding: str) -> Mapping[str, Any]:
    if not binding:
        return {}
    current_task = _load_current_task()
    current: Any = current_task
    for token in binding.split("."):
        if not isinstance(current, Mapping) or token not in current:
            return {}
        current = current[token]
    return current if isinstance(current, Mapping) else {}


def _resolve_lifecycle_state(
    *,
    profile: WorkQueueProfile,
    current_operational_state: str,
    has_assignment: bool,
) -> str:
    mapped = str(profile.operational_lifecycle_map.get(current_operational_state, ""))
    if mapped == "assigned" and not has_assignment:
        return "unassigned"
    if mapped:
        return mapped
    return "assigned" if has_assignment else "unassigned"


def _action_is_currently_allowed(
    *,
    action: ReviewActionSpec,
    flow: ButtonFlowSpec,
    surface_operational_state: str,
    current_operational_state: str,
    assignment_lifecycle_state: str,
    has_repository_state: bool,
    has_approval_chain: bool,
    has_audit_trace: bool,
    internal_only: bool,
) -> bool:
    if action.allowed_current_operational_states and current_operational_state not in action.allowed_current_operational_states:
        return False
    if action.allowed_surface_operational_states and surface_operational_state not in action.allowed_surface_operational_states:
        return False
    if action.allowed_assignment_lifecycle_states and assignment_lifecycle_state not in action.allowed_assignment_lifecycle_states:
        return False
    if action.requires_approval_chain and not has_approval_chain:
        return False
    return _flow_conditions_met(
        flow=flow,
        surface_operational_state=surface_operational_state,
        has_repository_state=has_repository_state,
        has_approval_chain=has_approval_chain,
        has_audit_trace=has_audit_trace,
        internal_only=internal_only,
    )


def _flow_conditions_met(
    *,
    flow: ButtonFlowSpec,
    surface_operational_state: str,
    has_repository_state: bool,
    has_approval_chain: bool,
    has_audit_trace: bool,
    internal_only: bool,
) -> bool:
    for token in flow.allowed_when:
        if not _token_matches(
            token=token,
            surface_operational_state=surface_operational_state,
            has_repository_state=has_repository_state,
            has_approval_chain=has_approval_chain,
            has_audit_trace=has_audit_trace,
            internal_only=internal_only,
        ):
            return False
    for token in flow.blocked_when:
        if _token_matches(
            token=token,
            surface_operational_state=surface_operational_state,
            has_repository_state=has_repository_state,
            has_approval_chain=has_approval_chain,
            has_audit_trace=has_audit_trace,
            internal_only=internal_only,
        ):
            return False
    return True


def _token_matches(
    *,
    token: str,
    surface_operational_state: str,
    has_repository_state: bool,
    has_approval_chain: bool,
    has_audit_trace: bool,
    internal_only: bool,
) -> bool:
    if token == "repository_state_available":
        return has_repository_state
    if token == "approval_chain_available":
        return has_approval_chain
    if token == "audit_trace_present":
        return has_audit_trace
    if token == "internal_only_surface":
        return internal_only

    surface_state_tokens = {
        "surface_state_preview_ready_or_review_required": {"preview_ready", "review_required"},
        "surface_state_draft_only_or_review_required": {"draft_only", "review_required"},
        "surface_state_draft_only_or_review_required_or_governed_hold": {"draft_only", "review_required", "governed_hold"},
        "surface_state_draft_only_or_governed_hold": {"draft_only", "governed_hold"},
        "surface_state_preview_ready_or_governed_hold": {"preview_ready", "governed_hold"},
    }
    if token in surface_state_tokens:
        return surface_operational_state in surface_state_tokens[token]

    blocked_tokens = {
        "external_surface_requested": False,
        "live_execution_requested": False,
        "release_gate_blocked": False,
    }
    if token in blocked_tokens:
        return blocked_tokens[token]

    return False


__all__ = [
    "ButtonFlowSpec",
    "PendingButtonFlow",
    "ReviewActionSpec",
    "WorkQueueProfile",
    "action_is_currently_allowed",
    "build_operator_context_projection",
    "build_workbench_replay_projection",
    "build_work_item_key",
    "list_pending_button_flows",
    "resolve_assignment",
    "resolve_button_flow",
    "review_action_spec",
    "sanitize_transient_preview_context",
    "work_queue_profile",
]
