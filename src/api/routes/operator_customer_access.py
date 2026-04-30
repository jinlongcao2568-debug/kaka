# Stage: api_operator_customer_access
# Consumes formal objects: API/readback projections only
# Dependent handoff: N/A
# Dependent schema/contracts: existing Stage1-9 contracts through mounted routes

from __future__ import annotations

from typing import Any, Mapping

from api.deps import get_settings
from api.projections import (
    build_autonomous_operator_workbench_surface,
    build_customer_artifact_access_candidate_surface,
    build_go_live_readiness_surface,
    build_operator_customer_access_readiness_surface,
    build_real_sample_autonomous_opportunity_acceptance_surface,
    register_route_table,
)
from api.routes.stage1 import create_stage1_scheduler_task, read_stage1_scheduler_task
from shared.pipeline import run_internal_chain
from shared.utils import build_id, utc_now_iso
from stage1_tasking.market_scan import Stage1MarketScanEngine
from stage1_tasking.region_adapters import (
    list_region_source_adapters,
    resolve_entry_profile_for_region,
)
from stage1_tasking.source_blueprint import Stage1SourceBlueprintOrchestrator
from stage2_ingestion import (
    REAL_PUBLIC_ATTACHMENT_PROFILES,
    REAL_PUBLIC_ENTRY_PROFILES,
)
from stage2_ingestion.service import Stage2Service
from storage.db import PersistedOperatorAction, build_persisted_at
from storage.repositories.operator_action_repo import OperatorActionRepository
from storage.repositories.worker_queue_repo import WorkerQueueRepository
from storage.repository_boundary import persist_stage_bundle


OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA = {
    "surface_mode": "internal-readback",
    "internal_only": True,
    "readiness_only": True,
    "projection_only": True,
    "live_execution_enabled": False,
    "external_release_enabled": False,
    "public_software_release": False,
    "provider_call_enabled": False,
    "real_provider_call_enabled": False,
    "stage8_real_execution_enabled": False,
    "stage9_real_payment_delivery_refund_enabled": False,
    "automated_refund_enabled": False,
}


def _json_safe_snapshot_replay(replay: Mapping[str, Any]) -> dict[str, Any]:
    safe = dict(replay)
    raw_bytes = safe.pop("bytes", None)
    if isinstance(raw_bytes, (bytes, bytearray)):
        safe["bytes_present"] = True
        safe["bytes_redacted_for_json"] = True
        safe["byte_size_readback"] = len(raw_bytes)
        safe["byte_preview_hex"] = bytes(raw_bytes[:16]).hex()
    else:
        safe["bytes_present"] = raw_bytes is not None
        safe["bytes_redacted_for_json"] = False
    return safe


def _settings_bootstrap() -> tuple[dict[str, Any], dict[str, Any]]:
    settings = get_settings()
    return settings.storage_bootstrap_payload(), settings.provider_adapter_bootstrap_payload()


def _operator_audit_log() -> list[dict[str, Any]]:
    return [entry.as_payload() for entry in OperatorActionRepository().list_all()]


def _operator_operation_readback(routes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return [
        {
            key: route[key]
            for key in (
                "operationId",
                "method",
                "path",
                "surface_mode",
                "internal_only",
                "readiness_only",
                "projection_only",
                "live_execution_enabled",
                "external_release_enabled",
                "public_software_release",
                "provider_call_enabled",
                "real_provider_call_enabled",
                "stage8_real_execution_enabled",
                "stage9_real_payment_delivery_refund_enabled",
                "automated_refund_enabled",
                "autonomous_operator_workbench",
                "productized_owner_workbench",
                "opportunity_queue_visible",
                "commercial_hook_review_visible",
                "buyer_ranking_visible",
                "evidence_risk_visible",
                "delivery_state_visible",
                "next_action_visible",
                "raw_json_required",
                "real_sample_autonomous_acceptance",
                "real_sample_flow_visible",
            )
            if key in route
        }
        for route in (routes or OPERATOR_CUSTOMER_ACCESS_ROUTES)
    ]


def preview_operator_customer_access_readiness(payload: Any) -> dict[str, Any]:
    storage_bootstrap, provider_bootstrap = _settings_bootstrap()
    return build_operator_customer_access_readiness_surface(
        payload,
        storage_bootstrap=storage_bootstrap,
        provider_adapter_bootstrap=provider_bootstrap,
        audit_log=_operator_audit_log(),
        operator_operation_readback=_operator_operation_readback(),
    )


def preview_autonomous_operator_workbench(payload: Any) -> dict[str, Any]:
    return build_autonomous_operator_workbench_surface(payload)


def preview_real_sample_autonomous_opportunity_acceptance(payload: Any) -> dict[str, Any]:
    return build_real_sample_autonomous_opportunity_acceptance_surface(payload)


def create_operator_task(payload: dict[str, Any]) -> dict[str, Any]:
    response = create_stage1_scheduler_task(payload)
    response.update(
        {
            "surface_id": "operator_task_creation",
            "internal_only": True,
            "repository_backed_readback": True,
            "task_creation_visible": True,
            "stage2_fetch_enabled": False,
            "real_external_fetch_enabled": False,
            "unregistered_capture_enabled": False,
            "live_execution_enabled": False,
        }
    )
    return response


def read_operator_task(payload: dict[str, Any]) -> dict[str, Any]:
    response = read_stage1_scheduler_task(payload)
    response.update(
        {
            "surface_id": "operator_task_readback",
            "internal_only": True,
            "live_execution_enabled": False,
        }
    )
    return response


def import_operator_project(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id", "")).strip()
    if not project_id:
        raise ValueError("project_id is required for project import readiness")
    task_payload = {
        **dict(payload),
        "task_id": str(payload.get("task_id") or f"IMPORT-{project_id}"),
        "source_mode": str(payload.get("source_mode") or "INTERNAL_PROJECT_IMPORT"),
        "project_import_entry": True,
    }
    response = create_stage1_scheduler_task(task_payload)
    response.update(
        {
            "surface_id": "operator_project_import",
            "project_import_entry": True,
            "project_import_state": "IMPORTED_AS_INTERNAL_STAGE1_TASK_INTENT",
            "internal_only": True,
            "repository_backed_readback": True,
            "stage2_fetch_enabled": False,
            "real_external_fetch_enabled": False,
            "unregistered_capture_enabled": False,
            "live_execution_enabled": False,
        }
    )
    return response


def preview_customer_artifact_access_candidate(payload: Any) -> dict[str, Any]:
    return build_customer_artifact_access_candidate_surface(payload)


def preview_go_live_readiness(payload: Any) -> dict[str, Any]:
    storage_bootstrap, provider_bootstrap = _settings_bootstrap()
    return build_go_live_readiness_surface(
        storage_bootstrap=storage_bootstrap,
        provider_adapter_bootstrap=provider_bootstrap,
        audit_log=_operator_audit_log(),
    )


def _queue_status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in WorkerQueueRepository().list():
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def _entry_profiles_readback() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "expected_title_contains": profile.expected_title_contains,
            "sample_detail_url": profile.sample_detail_url,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
        }
        for profile in REAL_PUBLIC_ENTRY_PROFILES
    ]


def _attachment_profiles_readback() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "detail_page_url_optional": profile.detail_page_url_optional,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
        }
        for profile in REAL_PUBLIC_ATTACHMENT_PROFILES
    ]


def list_real_public_source_profiles(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    return {
        "surface_id": "operator_real_public_source_profiles",
        "internal_only": True,
        "readiness_only": True,
        "projection_only": True,
        "repository_backed_readback": False,
        "entry_profiles": _entry_profiles_readback(),
        "attachment_profiles": _attachment_profiles_readback(),
        "entry_profile_count": len(REAL_PUBLIC_ENTRY_PROFILES),
        "attachment_profile_count": len(REAL_PUBLIC_ATTACHMENT_PROFILES),
        "allowed_capture_kinds": ["entry", "attachment"],
        "unapproved_capture_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def list_operator_region_adapters(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    adapters = list_region_source_adapters()
    return {
        "surface_id": "operator_region_source_adapters",
        "internal_only": True,
        "readiness_only": False,
        "projection_only": True,
        "region_adapter_catalog": True,
        "region_adapter_count": len(adapters),
        "searchable_region_codes": [
            adapter["region_code"]
            for adapter in adapters
            if bool(adapter.get("searchable_now", False))
        ],
        "dedicated_local_profile_region_codes": [
            adapter["region_code"]
            for adapter in adapters
            if bool(adapter.get("dedicated_local_profiles", False))
        ],
        "commercial_pilot_region_codes": [
            adapter["region_code"]
            for adapter in adapters
            if bool(adapter.get("commercial_pilot_region", False))
        ],
        "region_adapters": adapters,
        "manual_url_picker_primary_flow": False,
        "real_external_fetch_enabled": False,
        "unapproved_capture_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _id_token(value: Any, default: str) -> str:
    token = "".join(
        char.upper() if char.isascii() and char.isalnum() else "-"
        for char in str(value or "").strip()
    ).strip("-")
    token = "-".join(part for part in token.split("-") if part)
    return token or default


def _search_candidate_from_payload(
    payload: Mapping[str, Any],
    *,
    region_adapter: Mapping[str, Any],
    entry_profile: Mapping[str, Any],
    now: str,
) -> dict[str, Any]:
    region_code = str(region_adapter.get("region_code") or payload.get("region_code") or "CN-NATIONAL")
    keyword = str(payload.get("query") or payload.get("project_keyword") or payload.get("keyword") or "工程项目").strip()
    project_type = str(payload.get("project_type") or "construction").strip() or "construction"
    amount = _as_float(payload.get("amount") or payload.get("minimum_amount"), 12_000_000.0)
    candidate_count = _as_int(payload.get("candidate_count"), 3)
    project_id = str(
        payload.get("project_id")
        or build_id("PROJ", _id_token(region_code, "REGION"), _id_token(keyword, "SEARCH")[:18])
    )
    project_name = str(payload.get("project_name") or f"{region_adapter.get('region_name')} {keyword} 机会搜索样本")
    source_url = str(entry_profile.get("sample_detail_url") or entry_profile.get("url") or "")
    return {
        "notice_id": str(payload.get("notice_id") or build_id("NOTICE", project_id)),
        "project_id": project_id,
        "project_name": project_name,
        "region_code": region_code,
        "project_type": project_type,
        "procurement_category": project_type,
        "notice_stage": str(payload.get("notice_stage") or "candidate_notice"),
        "amount": amount,
        "estimated_amount": amount,
        "candidate_count": candidate_count,
        "candidate_company": str(payload.get("candidate_company") or "第一候选施工企业"),
        "objection_deadline_at_optional": str(
            payload.get("objection_deadline_at_optional") or "2026-05-08T00:00:00+00:00"
        ),
        "key_fields_present": [
            "project_name",
            "candidate_company",
            "notice_stage",
        ],
        "source_url": source_url,
        "source_family": str(entry_profile.get("source_family") or "local_public_resource_trading_center"),
        "source_registry_id": str(payload.get("source_registry_id") or "SRC-REG-PROC-NATIONAL-HTML"),
        "source_profile_id": str(entry_profile.get("profile_id") or ""),
        "source_site_name": str(entry_profile.get("site_name") or ""),
        "market_scan_generated_at": now,
    }


def _internal_chain_payload_from_search(
    payload: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    market_scan: Mapping[str, Any],
    source_blueprint: Mapping[str, Any],
    now: str,
) -> dict[str, Any]:
    capture_plan = dict(source_blueprint.get("stage2_capture_plan", {}) or {})
    return {
        "now": now,
        "task_id": str(payload.get("task_id") or build_id("TASK", market_scan.get("scan_run_id") or "SEARCH")),
        "project_id": str(candidate.get("project_id") or payload.get("project_id") or "PROJ-SEARCH"),
        "project_root_id": str(payload.get("project_root_id") or build_id("ROOT", candidate.get("project_id") or "SEARCH")),
        "project_name": str(candidate.get("project_name") or payload.get("project_name") or "机会搜索项目"),
        "region_code": str(candidate.get("region_code") or payload.get("region_code") or "CN-NATIONAL"),
        "region_scope": str(payload.get("region_scope") or "NATIONAL"),
        "source_family": str(candidate.get("source_family") or "PROCUREMENT_NOTICE"),
        "platform_level": str(payload.get("platform_level") or "NATIONAL"),
        "coverage_tier": str(payload.get("coverage_tier") or "T0_CORE"),
        "default_route": str(payload.get("default_route") or "LIST_TO_DETAIL"),
        "review_lane": str(payload.get("review_lane") or "STANDARD"),
        "carrier_type": str(payload.get("carrier_type") or "HTML_PAGE"),
        "announcement_url": str(candidate.get("source_url") or payload.get("announcement_url") or "https://example.invalid/notice/search"),
        "source_document_ref": str(payload.get("source_document_ref") or build_id("DOC", candidate.get("project_id") or "SEARCH")),
        "source_slice_ref": str(payload.get("source_slice_ref") or build_id("SLICE", candidate.get("project_id") or "SEARCH")),
        "normalization_rule_id": str(payload.get("normalization_rule_id") or "NR-001"),
        "parser_confidence_score": _as_float(payload.get("parser_confidence_score"), 0.92),
        "procurement_regime": str(payload.get("procurement_regime") or "OPEN_TENDER"),
        "candidate_order_mode": str(payload.get("candidate_order_mode") or "ORDERED"),
        "award_determination_mode": str(payload.get("award_determination_mode") or "COMPREHENSIVE_SCORE"),
        "channel_family": str(payload.get("channel_family") or "ORG_EMAIL"),
        "contact_channel": str(payload.get("contact_channel") or "EMAIL"),
        "contact_validity_status": str(payload.get("contact_validity_status") or "VALID"),
        "contact_legal_basis": str(payload.get("contact_legal_basis") or "PUBLIC_ROLE_CONTACT"),
        "reasonable_expectation_status": str(payload.get("reasonable_expectation_status") or "REASONABLE"),
        "channel_policy_status": str(payload.get("channel_policy_status") or "ALLOW"),
        "public_contact_source": str(payload.get("public_contact_source") or "PUBLIC_SITE"),
        "source_auditability_state": str(payload.get("source_auditability_state") or "AUDITABLE"),
        "source_vendor_role": str(payload.get("source_vendor_role") or "PUBLIC_OFFICIAL_SOURCE"),
        "frequency_policy_state": str(payload.get("frequency_policy_state") or "ALLOW"),
        "opt_out_state": str(payload.get("opt_out_state") or "ACTIVE"),
        "quiet_hours_policy_state": str(payload.get("quiet_hours_policy_state") or "ALLOW"),
        "response_status": str(payload.get("response_status") or "NO_RESPONSE"),
        "crm_owner_state": str(payload.get("crm_owner_state") or "UNASSIGNED"),
        "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
        "source_mode": "OFFLINE_REAL_PUBLIC_SAMPLE",
        "run_mode": "DRY_RUN",
        "automation_level": "AUTONOMOUS",
        "approval_state": "NOT_REQUIRED",
        "live_execution_enabled": False,
        "real_external_fetch_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "manual_url_picker_primary_flow": False,
        "source_blueprint_plan_id": str(source_blueprint.get("source_blueprint_plan_id") or ""),
        "stage2_capture_plan_id": str(capture_plan.get("capture_plan_id") or ""),
        "flags": {"report_approved": True},
    }


def run_operator_autonomous_opportunity_search(payload: Mapping[str, Any]) -> dict[str, Any]:
    now = str(payload.get("now") or utc_now_iso())
    region_code = str(payload.get("region_code") or "CN-NATIONAL").strip() or "CN-NATIONAL"
    resolved = resolve_entry_profile_for_region(
        region_code,
        requested_profile_id=str(payload.get("profile_id") or payload.get("entry_profile_id") or "").strip() or None,
    )
    region_adapter = dict(resolved["region_adapter"])
    entry_profile = dict(resolved["entry_profile"])
    candidate = _search_candidate_from_payload(
        payload,
        region_adapter=region_adapter,
        entry_profile=entry_profile,
        now=now,
    )
    scan_run_id = str(
        payload.get("scan_run_id")
        or build_id("MKTSCAN", candidate["project_id"], candidate["region_code"])
    )
    market_scan = Stage1MarketScanEngine().run(
        {
            **dict(payload),
            "now": now,
            "scan_run_id": scan_run_id,
            "batch_id": str(payload.get("source_blueprint_batch_id") or "PTL-I100-ROADMAP-01"),
            "source_blueprint_batch_id": str(payload.get("source_blueprint_batch_id") or "PTL-I100-ROADMAP-01"),
            "minimum_amount": _as_float(payload.get("minimum_amount"), 1_000_000.0),
            "analysis_score_threshold": _as_int(payload.get("analysis_score_threshold"), 50),
            "notice_candidates": [candidate],
            "manual_url_picker_primary_flow": False,
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "real_provider_call_enabled": False,
        }
    )
    selected = list(market_scan.get("opportunity_candidates", []))
    source_blueprint = (
        Stage1SourceBlueprintOrchestrator().build(
            {
                "scan_run_id": market_scan["scan_run_id"],
                "source_blueprint_plan_id": str(
                    payload.get("source_blueprint_plan_id")
                    or build_id("SRCBLUE", candidate["project_id"], candidate["region_code"])
                ),
                "coverage_gap_signals": list(region_adapter.get("coverage_gap_signals", [])),
                "region_code": region_adapter["region_code"],
            }
        )
        if selected
        else {}
    )
    if not source_blueprint:
        return {
            "surface_id": "operator_autonomous_opportunity_search",
            "search_state": "REVIEW_REQUIRED",
            "region_adapter": region_adapter,
            "entry_profile": entry_profile,
            "market_scan": market_scan,
            "selected_candidate_count": 0,
            "reason": "market_scan_did_not_select_candidate",
            "manual_url_picker_primary_flow": False,
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
        }

    chain_payload = _internal_chain_payload_from_search(
        payload,
        candidate=selected[0],
        market_scan=market_scan,
        source_blueprint=source_blueprint,
        now=now,
    )
    chain = run_internal_chain(chain_payload)
    for stage_key in ("stage6", "stage7", "stage8", "stage9"):
        persist_stage_bundle(chain[stage_key])
    acceptance_payload = {
        **chain,
        "market_scan": market_scan,
        "source_blueprint_plan": source_blueprint,
    }
    acceptance = build_real_sample_autonomous_opportunity_acceptance_surface(acceptance_payload)
    opportunity_ref = dict(acceptance.get("stage_refs", {}).get("stage7_saleable_opportunity", {}))
    opportunity_id = str(opportunity_ref.get("object_id") or "")
    return {
        "surface_id": "operator_autonomous_opportunity_search",
        "search_state": "AUTONOMOUS_SEARCH_ACCEPTED"
        if acceptance.get("acceptance_state") == "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED"
        else "REVIEW_REQUIRED",
        "capability_state": acceptance.get("capability_state"),
        "internal_only": True,
        "repository_backed_readback": True,
        "productized_owner_workbench": True,
        "region_adapter": region_adapter,
        "entry_profile": entry_profile,
        "candidate": candidate,
        "market_scan": market_scan,
        "source_blueprint_plan": source_blueprint,
        "acceptance": acceptance,
        "opportunity_id": opportunity_id,
        "operator_workbench_readback_path": f"/operator-console/autonomous-workbench?opportunity_id={opportunity_id}"
        if opportunity_id
        else "",
        "customer_artifact_candidate_path": f"/customer-artifact-access-candidates/{opportunity_id}"
        if opportunity_id
        else "",
        "manual_url_picker_primary_flow": False,
        "live_execution_enabled": False,
        "real_external_fetch_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
        "automated_refund_enabled": False,
    }


def _lineage_refs_from_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for source_key, target_key in (
        ("task_id", "owner_task_id"),
        ("project_id", "project_id"),
        ("source_blueprint_batch_id", "source_blueprint_batch_id"),
    ):
        value = str(payload.get(source_key, "")).strip()
        if value:
            refs[target_key] = value
    refs["operator_surface"] = "operator_console_real_source_runner"
    return refs


def _real_source_run_work_item_id() -> str:
    return "operator-real-public-source-task-runs"


def _record_real_source_run(
    *,
    capture_kind: str,
    profile_id: str,
    result: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    requested_at = build_persisted_at()
    snapshot_id = str(result.get("snapshot_id_optional") or result.get("snapshot_id") or "").strip()
    status = str(result.get("status") or result.get("readback_state") or "UNKNOWN")
    fail_closed = bool(result.get("fail_closed", False))
    action_state = "FAILED_CLOSED" if fail_closed else status
    run_id = f"REAL-SOURCE-RUN-{snapshot_id or profile_id}-{requested_at}".replace(":", "").replace("+", "")
    object_refs = {
        "capture_kind": capture_kind,
        "profile_id": profile_id,
        "status": status,
    }
    if snapshot_id:
        object_refs["snapshot_id"] = snapshot_id
    for key in ("task_id", "project_id", "source_blueprint_batch_id"):
        value = str(payload.get(key, "")).strip()
        if value:
            object_refs[key] = value
    action = PersistedOperatorAction(
        action_event_id=run_id,
        work_item_id=_real_source_run_work_item_id(),
        stage_scope=2,
        action_id="real_public_source_capture",
        button_flow_id="owner_console_real_source_runner",
        action_state=action_state,
        resulting_assignment_lifecycle_state=None,
        requested_by_role="single_operator",
        requested_by="卡卡罗特",
        assigned_owner_role="single_operator",
        assigned_owner="卡卡罗特",
        reviewer_role="single_operator",
        reviewer="卡卡罗特",
        reason="owner_console_allowlisted_real_public_source_capture",
        object_refs=object_refs,
        trace_refs={
            "operator_console_route": "/operator-console/real-source-runs",
            "readback_path": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else "",
        },
        audit_refs={
            "run_audit_ref": run_id,
            "public_boundary": "allowlisted_public_source_only",
        },
        requested_at=requested_at,
        completed_at=requested_at,
    )
    OperatorActionRepository().append(action)
    return _real_source_run_action_payload(action)


def _real_source_run_action_payload(action: PersistedOperatorAction) -> dict[str, Any]:
    refs = dict(action.object_refs)
    snapshot_id = refs.get("snapshot_id")
    return {
        "run_id": action.action_event_id,
        "capture_kind": refs.get("capture_kind"),
        "profile_id": refs.get("profile_id"),
        "snapshot_id_optional": snapshot_id,
        "status": refs.get("status") or action.action_state,
        "action_state": action.action_state,
        "task_id_optional": refs.get("task_id"),
        "project_id_optional": refs.get("project_id"),
        "requested_at": action.requested_at,
        "completed_at": action.completed_at,
        "readback_path_optional": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else None,
        "repository_backed": True,
        "internal_only": True,
        "unapproved_capture_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
    }


def list_owner_real_public_source_task_runs(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    actions = OperatorActionRepository().list(work_item_id=_real_source_run_work_item_id())
    runs = [_real_source_run_action_payload(action) for action in actions]
    runs.sort(key=lambda row: str(row.get("requested_at") or ""), reverse=True)
    status_counts: dict[str, int] = {}
    for row in runs:
        status = str(row.get("status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "surface_id": "operator_real_public_source_task_runs",
        "internal_only": True,
        "repository_backed_readback": True,
        "run_count": len(runs),
        "status_counts": status_counts,
        "runs": runs,
        "allowed_capture_kinds": ["entry", "attachment"],
        "unapproved_capture_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def run_owner_real_public_source_capture(payload: Mapping[str, Any]) -> dict[str, Any]:
    capture_kind = str(payload.get("capture_kind", "")).strip().lower()
    profile_id = str(payload.get("profile_id", "")).strip()
    if not profile_id:
        raise ValueError("profile_id is required")

    service = Stage2Service()
    lineage_refs = _lineage_refs_from_payload(payload)
    if capture_kind == "entry":
        profile = next((item for item in REAL_PUBLIC_ENTRY_PROFILES if item.profile_id == profile_id), None)
        if profile is None:
            raise ValueError(f"unregistered_entry_profile_id:{profile_id}")
        result = service.fetch_real_public_entry_url(
            profile.url,
            profile_id=profile.profile_id,
            lineage_refs=lineage_refs,
        )
    elif capture_kind == "attachment":
        profile = next((item for item in REAL_PUBLIC_ATTACHMENT_PROFILES if item.profile_id == profile_id), None)
        if profile is None:
            raise ValueError(f"unregistered_attachment_profile_id:{profile_id}")
        result = service.fetch_real_public_attachment_url(
            profile.url,
            profile_id=profile.profile_id,
            lineage_refs=lineage_refs,
            detail_page_url=profile.detail_page_url_optional,
        )
    else:
        raise ValueError("capture_kind must be entry or attachment")

    return {
        "surface_id": "operator_real_public_source_run",
        "capture_kind": capture_kind,
        "profile_id": profile_id,
        "snapshot_id_optional": result.get("snapshot_id_optional"),
        "capture_status": result.get("status"),
        "run_record": _record_real_source_run(
            capture_kind=capture_kind,
            profile_id=profile_id,
            result=result,
            payload=payload,
        ),
        "repository_backed_readback": True,
        "readback_path_template": "/operator-console/real-source-runs/{snapshot_id}",
        "result": result,
        "internal_only": True,
        "unapproved_capture_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def read_owner_real_public_source_capture(payload: Mapping[str, Any]) -> dict[str, Any]:
    snapshot_id = str(payload.get("snapshot_id", "")).strip()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")
    replay = _json_safe_snapshot_replay(Stage2Service().replay_public_source_snapshot(snapshot_id))
    return {
        "surface_id": "operator_real_public_source_readback",
        "snapshot_id": snapshot_id,
        "readback_state": replay.get("readback_state"),
        "repository_backed_readback": True,
        "replayable": bool(replay.get("replayable", False)),
        "result": replay,
        "internal_only": True,
        "unapproved_capture_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def preview_scheduler_status(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    storage_bootstrap, _ = _settings_bootstrap()
    worker_queue = dict(storage_bootstrap.get("worker_queue_bootstrap", {}))
    return {
        "surface_id": "operator_scheduler_status",
        "internal_only": True,
        "readback_ready": True,
        "repository_backed": True,
        "replayable": True,
        "readiness_state": worker_queue.get("readiness_state"),
        "queue_backend": worker_queue.get("queue_backend"),
        "effective_queue_backend": worker_queue.get("effective_queue_backend"),
        "queue_status_counts": _queue_status_counts(),
        "stage2_fetch_enabled": False,
        "unregistered_capture_enabled": False,
        "real_external_fetch_enabled": False,
        "external_queue_connection_enabled": False,
        "real_provider_execution_enabled": False,
    }


OPERATOR_CUSTOMER_ACCESS_ROUTES = [
    {
        "operationId": "previewOperatorCustomerAccessReadiness",
        "method": "GET",
        "path": "/operator-console/readiness",
        "handler": preview_operator_customer_access_readiness,
        "operator_console_readiness": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewAutonomousOperatorWorkbench",
        "method": "GET",
        "path": "/operator-console/autonomous-workbench",
        "handler": preview_autonomous_operator_workbench,
        "autonomous_operator_workbench": True,
        "productized_owner_workbench": True,
        "opportunity_queue_visible": True,
        "commercial_hook_review_visible": True,
        "buyer_ranking_visible": True,
        "evidence_risk_visible": True,
        "delivery_state_visible": True,
        "next_action_visible": True,
        "raw_json_required": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewRealSampleAutonomousOpportunityAcceptance",
        "method": "GET",
        "path": "/operator-console/real-sample-autonomous-acceptance",
        "handler": preview_real_sample_autonomous_opportunity_acceptance,
        "real_sample_autonomous_acceptance": True,
        "real_sample_flow_visible": True,
        "productized_owner_workbench": True,
        "opportunity_queue_visible": True,
        "commercial_hook_review_visible": True,
        "buyer_ranking_visible": True,
        "evidence_risk_visible": True,
        "delivery_state_visible": True,
        "next_action_visible": True,
        "raw_json_required": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "createOperatorTask",
        "method": "POST",
        "path": "/operator-console/tasks",
        "handler": create_operator_task,
        "task_creation_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "listRealPublicSourceProfiles",
        "method": "GET",
        "path": "/operator-console/real-source-profiles",
        "handler": list_real_public_source_profiles,
        "real_public_source_profile_catalog": True,
        "repository_backed_readback": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "listOperatorRegionAdapters",
        "method": "GET",
        "path": "/operator-console/region-adapters",
        "handler": list_operator_region_adapters,
        "region_adapter_catalog": True,
        "repository_backed_readback": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "runOperatorAutonomousOpportunitySearch",
        "method": "POST",
        "path": "/operator-console/autonomous-opportunity-search",
        "handler": run_operator_autonomous_opportunity_search,
        "autonomous_search_entry": True,
        "region_adapter_catalog": True,
        "real_sample_flow_visible": True,
        "productized_owner_workbench": True,
        "opportunity_queue_visible": True,
        "commercial_hook_review_visible": True,
        "buyer_ranking_visible": True,
        "evidence_risk_visible": True,
        "delivery_state_visible": True,
        "next_action_visible": True,
        "raw_json_required": False,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "runOwnerRealPublicSourceCapture",
        "method": "POST",
        "path": "/operator-console/real-source-runs",
        "handler": run_owner_real_public_source_capture,
        "real_public_source_runner_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "listOwnerRealPublicSourceTaskRuns",
        "method": "GET",
        "path": "/operator-console/real-source-task-runs",
        "handler": list_owner_real_public_source_task_runs,
        "real_public_source_task_run_list": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "readOwnerRealPublicSourceCapture",
        "method": "GET",
        "path": "/operator-console/real-source-runs/{snapshot_id}",
        "handler": read_owner_real_public_source_capture,
        "real_public_source_readback": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "readOperatorTask",
        "method": "GET",
        "path": "/operator-console/tasks/{queue_item_id}",
        "handler": read_operator_task,
        "task_readback_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "importOperatorProject",
        "method": "POST",
        "path": "/operator-console/project-imports",
        "handler": import_operator_project,
        "project_import_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewCustomerArtifactAccessCandidate",
        "method": "GET",
        "path": "/customer-artifact-access-candidates/{opportunity_id}",
        "handler": preview_customer_artifact_access_candidate,
        "customer_artifact_access_readiness": True,
        "candidate_only": True,
        "review_only": True,
        "download_auth_required": True,
        "field_allowlist_masking_required": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewGoLiveReadiness",
        "method": "GET",
        "path": "/go-live/readiness",
        "handler": preview_go_live_readiness,
        "go_live_readiness": True,
        "deployment_readiness": True,
        "monitoring_rollback_refs": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "previewOperatorSchedulerStatus",
        "method": "GET",
        "path": "/operator-console/scheduler-status",
        "handler": preview_scheduler_status,
        "scheduler_status_readback": True,
        "repository_backed_readback": True,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
]


def register_operator_customer_access_routes(
    router: object | None = None,
) -> list[dict[str, Any]]:
    return register_route_table(router, list(OPERATOR_CUSTOMER_ACCESS_ROUTES))


__all__ = [
    "OPERATOR_CUSTOMER_ACCESS_ROUTES",
    "create_operator_task",
    "import_operator_project",
    "list_owner_real_public_source_task_runs",
    "list_operator_region_adapters",
    "list_real_public_source_profiles",
    "preview_autonomous_operator_workbench",
    "preview_customer_artifact_access_candidate",
    "preview_go_live_readiness",
    "preview_operator_customer_access_readiness",
    "preview_real_sample_autonomous_opportunity_acceptance",
    "preview_scheduler_status",
    "read_owner_real_public_source_capture",
    "read_operator_task",
    "register_operator_customer_access_routes",
    "run_operator_autonomous_opportunity_search",
    "run_owner_real_public_source_capture",
]
