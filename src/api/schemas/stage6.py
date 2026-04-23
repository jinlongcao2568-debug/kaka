# Stage: api_stage6
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any, TypedDict

from api.schemas.common import ErrorEnvelope


class Stage6Request(TypedDict, total=False):
    project_id: str
    project_fact_id: str
    report_record_id: str
    review_queue_profile_id: str
    challenger_candidate_profile_id: str
    action_id: str
    requested_surface_state: str
    include_formal_objects: bool


class FormalObjectRef(TypedDict, total=False):
    object_type: str
    object_id: str
    primary_status: str
    decision_states: dict[str, str]
    governed_metadata: dict[str, Any]
    trace_refs: dict[str, Any]


class Stage6PreviewProjection(TypedDict, total=False):
    project_fact_summary: dict[str, Any]
    report_status_summary: dict[str, Any]
    review_queue_summary: dict[str, Any]
    challenger_summary: dict[str, Any]
    legal_action_summary: dict[str, Any]


class Stage6Response(TypedDict, total=False):
    surface_id: str
    surface_state: str
    surface_mode: str
    surface_access: str
    internal_only: bool
    preview_only: bool
    draft_only: bool
    live_execution_enabled: bool
    blocked_by_default: bool
    formalization_scope: str
    release_layer: str
    decision_states: dict[str, str]
    formal_object_refs: dict[str, FormalObjectRef]
    preview_projection: Stage6PreviewProjection
    capability_envelope: dict[str, Any]
    governance_envelope: dict[str, Any]
    semantic_envelope: dict[str, Any]
    trace_refs: dict[str, Any]
    error: ErrorEnvelope


class Stage6ReviewReportWorkbenchRequest(Stage6Request, total=False):
    pass


class Stage6ReviewReportWorkbenchResponse(Stage6Response, total=False):
    pass


__all__ = [
    "FormalObjectRef",
    "Stage6PreviewProjection",
    "Stage6Request",
    "Stage6Response",
    "Stage6ReviewReportWorkbenchRequest",
    "Stage6ReviewReportWorkbenchResponse",
]
