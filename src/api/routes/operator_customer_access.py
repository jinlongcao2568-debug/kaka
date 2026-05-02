# Stage: api_operator_customer_access
# Consumes formal objects: API/readback projections only
# Dependent handoff: N/A
# Dependent schema/contracts: existing Stage1-9 contracts through mounted routes

from __future__ import annotations

import json
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
    resolve_region_source_adapter,
)
from stage1_tasking.real_candidate_discovery import (
    REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
    RealPublicCandidateDiscoveryService,
    list_persisted_real_candidates,
    list_real_candidate_discovery_runs,
)
from stage1_tasking.source_blueprint import Stage1SourceBlueprintOrchestrator
from stage2_ingestion import (
    REAL_PUBLIC_ATTACHMENT_PROFILES,
    REAL_PUBLIC_ENTRY_PROFILES,
)
from stage2_ingestion.real_candidate_capture import (
    DEFAULT_ATTACHMENT_CAPTURE_LIMIT,
    DEFAULT_DETAIL_CAPTURE_LIMIT,
    RealCandidateStage2CaptureService,
    list_real_candidate_stage2_captures,
)
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.guangdong_gdcic_openplatform import (
    query_guangdong_gdcic_openplatform_hard_defect_sources,
)
from stage4_verification.service import Stage4Service
from stage4_verification.regional_hard_defect_sources import build_regional_hard_defect_source_plan
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from stage7_sales.service import Stage7Service
from stage8_outreach.service import Stage8Service
from stage9_delivery.service import Stage9Service
from storage.db import DatabaseSession, PersistedOperatorAction, build_persisted_at
from storage.repositories.object_storage_repo import ObjectStorageRepository
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

DEFAULT_AUTONOMOUS_PROJECT_TYPES = (
    "construction",
    "municipal",
    "highway",
    "water_conservancy",
)
DEFAULT_OPERATOR_TASK_PAYLOAD = {
    "region_code": "CN-GD",
    "region_scope": "NATIONAL",
    "source_family": "PROCUREMENT_NOTICE",
    "platform_level": "NATIONAL",
    "coverage_tier": "T0_CORE",
    "default_route": "LIST_TO_DETAIL",
    "review_lane": "STANDARD",
    "carrier_type": "HTML_PAGE",
    "procurement_regime": "OPEN_TENDER",
    "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
    "source_mode": "INTERNAL_OPERATOR_TASK",
    "run_mode": "DRY_RUN",
    "live_execution_enabled": False,
    "real_external_fetch_enabled": False,
    "real_provider_call_enabled": False,
    "external_release_enabled": False,
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
                "region_adapter_catalog",
                "real_candidate_catalog",
                "real_candidate_discovery_run_list",
                "real_candidate_stage2_capture_run_list",
                "autonomous_search_entry",
                "autonomous_search_run_list",
                "real_sample_autonomous_acceptance",
                "real_sample_flow_visible",
                "real_world_sellability_readiness",
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


def _operator_task_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    task_payload = {**DEFAULT_OPERATOR_TASK_PAYLOAD, **dict(payload)}
    project_id = str(task_payload.get("project_id") or "").strip()
    task_id = str(task_payload.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required for operator task creation")
    if not project_id:
        raise ValueError("project_id is required for operator task creation")
    task_payload["task_id"] = task_id
    task_payload["project_id"] = project_id
    task_payload.setdefault("project_name", f"内部运营任务 {project_id}")
    task_payload.setdefault("now", utc_now_iso())
    return task_payload


def create_operator_task(payload: dict[str, Any]) -> dict[str, Any]:
    task_payload = _operator_task_payload(payload)
    response = create_stage1_scheduler_task(task_payload)
    scheduler_task = dict(response.get("scheduler_task", {}) or {})
    scheduler_task["region_code"] = str(task_payload.get("region_code") or "")
    response["scheduler_task"] = scheduler_task
    response["queue_item_id"] = str(scheduler_task.get("queue_item_id") or "")
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
            "operator_task_overview": _queue_item_summary(
                WorkerQueueRepository().get(str(dict(response.get("scheduler_task", {}) or {}).get("queue_item_id") or ""))
            ),
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
        **_operator_task_payload(
            {
                **dict(payload),
                "task_id": str(payload.get("task_id") or f"IMPORT-{project_id}"),
            }
        ),
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


def _sellability_status_label(status: str) -> str:
    return {
        "PASS": "已满足",
        "PARTIAL": "部分满足",
        "NOT_READY": "未就绪",
    }.get(status, status)


def _sellability_lane(
    *,
    lane_id: str,
    title: str,
    status: str,
    current_state: str,
    evidence: list[str],
    gaps: list[str],
    next_actions: list[str],
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "title": title,
        "status": status,
        "status_label": _sellability_status_label(status),
        "current_state": current_state,
        "evidence": evidence,
        "gaps": gaps,
        "next_actions": next_actions,
    }


def preview_operator_real_world_sellability(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    region_surface = list_operator_region_adapters()
    search_runs = list_operator_autonomous_search_runs()
    stage2_captures = list_operator_real_candidate_stage2_captures()
    go_live = preview_go_live_readiness({})
    runs = list(search_runs.get("runs", []) or [])
    latest_run = dict(runs[0]) if runs else {}
    accepted_run_count = sum(
        1
        for run in runs
        if str(run.get("search_state") or "") == "AUTONOMOUS_SEARCH_ACCEPTED"
    )
    real_market_run_count = sum(
        1
        for run in runs
        if bool(run.get("real_market_discovery"))
        and not bool(run.get("offline_sample_validation"))
        and str(run.get("source_candidate_mode") or "") not in {"", "OFFLINE_SAMPLE_CANDIDATES", "REAL_SOURCE_REQUIRED"}
        and _as_int(dict(run.get("search_scope", {}) or {}).get("candidate_count"), 0) > 0
    )
    customer_sellable_ready_count = sum(
        1
        for run in runs
        if bool(run.get("customer_sellable_evidence_ready"))
    )
    stage2_detail_snapshot_count = sum(
        1
        for capture in list(stage2_captures.get("captures", []) or [])
        if str(capture.get("detail_snapshot_id_optional") or "").strip()
    )
    stage2_attachment_snapshot_count = sum(
        _as_int(capture.get("attachment_snapshot_count"), 0)
        for capture in list(stage2_captures.get("captures", []) or [])
    )
    latest_opportunity_id = str(latest_run.get("opportunity_id") or "")
    dedicated_region_count = len(region_surface.get("dedicated_local_profile_region_codes", []) or [])
    searchable_region_count = len(region_surface.get("searchable_region_codes", []) or [])
    region_count = int(region_surface.get("region_adapter_count") or 0)
    provider_config = dict(go_live.get("provider_config_readiness", {}) or {})
    controlled = dict(go_live.get("controlled_opening_requirements", {}) or {})
    real_provider_ready = bool(provider_config.get("real_provider_call_enabled", False))
    real_touch_ready = bool(controlled.get("stage8_real_execution_enabled", False))
    real_payment_ready = bool(controlled.get("stage9_real_payment_delivery_refund_enabled", False))
    latest_runtime_flow = dict(search_runs.get("latest_runtime_flow", {}) or {})
    stage_stats = list(latest_runtime_flow.get("stage_stats", []) or [])
    observed_stage_count = len(stage_stats)

    lanes = [
        _sellability_lane(
            lane_id="market_scan_to_opportunity",
            title="市场扫描到机会",
            status="PASS" if real_market_run_count else "PARTIAL",
            current_state=(
                f"已读回 {len(runs)} 个搜索记录，{accepted_run_count} 个形成内部/样本闭环；真实列表页候选进料记录 {real_market_run_count} 个。"
                if runs
                else "尚未在当前本地仓库读回搜索记录。"
            ),
            evidence=[
                "/operator-console/autonomous-search-runs",
                "/operator-console/autonomous-opportunity-search",
            ],
            gaps=[] if real_market_run_count else [
                "需要至少一次真实公开列表页候选发现命中并生成 notice_candidates。",
                "离线样本或显式候选只能算回归模式，不能算真实市场进料完成。",
            ],
            next_actions=[
                "继续硬化真实列表页搜索、公告解析、候选去重入库，并把真实候选稳定喂给 Stage1。",
            ],
        ),
        _sellability_lane(
            lane_id="region_adapter_coverage",
            title="地区适配器覆盖",
            status="PASS" if dedicated_region_count >= region_count and region_count else "PARTIAL",
            current_state=(
                f"可搜索地区 {searchable_region_count} 个；本地专用入口 {dedicated_region_count} 个；登记地区 {region_count} 个。"
            ),
            evidence=["/operator-console/region-adapters"],
            gaps=(
                []
                if dedicated_region_count >= region_count and region_count
                else ["部分地区本省实时公开源入口待补；全国平台只用于全国搜索，不能代替地方来源。"]
            ),
            next_actions=["补商业重点地区的本地公开源入口和失败诊断。"],
        ),
        _sellability_lane(
            lane_id="evidence_quality",
            title="证据质量与来源回链",
            status="PASS" if customer_sellable_ready_count else "PARTIAL",
            current_state=(
                "已有客户可售证据包就绪记录。"
                if customer_sellable_ready_count
                else f"证据包预览链路已接入；真实候选详情快照已读回 {stage2_detail_snapshot_count} 条，同站附件原文快照 {stage2_attachment_snapshot_count} 条，但客户可售证据未就绪。"
            ),
            evidence=[
                "/operator-console/real-candidate-stage2-captures",
                "/customer-artifact-portal/{opportunity_id}",
                "/customer-artifact-portal-download/{opportunity_id}",
            ],
            gaps=[] if customer_sellable_ready_count else [
                "需要真实详情页/附件快照正式进入 Stage4-9 解析、核验、证据包链路。",
                "需要来源网址、快照哈希、字段策略和可售判断同时就绪。"
            ],
            next_actions=["把真实公开来源快照接入 Stage4-9，再核对来源网址、字段策略和下载审计。"],
        ),
        _sellability_lane(
            lane_id="commercial_hook",
            title="商业钩子与买家匹配",
            status="PASS" if customer_sellable_ready_count else "PARTIAL",
            current_state=(
                "真实客户可售证据已支撑商业钩子。"
                if customer_sellable_ready_count
                else "机会工作台已能展示商业钩子、买家排序、证据强度和下一步动作；真实市场证据支撑仍需接入。"
            ),
            evidence=["/operator-console/autonomous-workbench"],
            gaps=[] if customer_sellable_ready_count else ["需要真实候选和真实证据快照支撑可售钩子，不能只用样本钩子。"],
            next_actions=["把真实来源证据强度、可讲卖点、暂不外泄字段和报价草稿压到一屏可卖性摘要。"],
        ),
        _sellability_lane(
            lane_id="leadpack_delivery_candidate",
            title="线索包交付候选",
            status="PASS" if customer_sellable_ready_count else "PARTIAL",
            current_state=(
                "客户可售证据包候选已就绪。"
                if customer_sellable_ready_count
                else "内部证据包预览可用，等待真实机会绑定后验收。"
            ),
            evidence=[
                "/customer-artifact-access-candidates/{opportunity_id}",
            ],
            gaps=[
                "客户可售证据包需要真实市场候选和真实来源快照支撑。",
                "真实客户下载需要账号/审批/审计/下载授权，不因内部预览而自动开放。"
            ],
            next_actions=["保留内部预览，后续接真实交付前补审批和下载授权读回。"],
        ),
        _sellability_lane(
            lane_id="governed_outreach",
            title="触达服务商与外发治理",
            status="PARTIAL" if not real_touch_ready else "PASS",
            current_state="内部模拟链路可预览；真实邮件、电话、CRM/报价发送未接入 live provider。",
            evidence=["/go-live/readiness", "/operator-console/readiness"],
            gaps=[] if real_touch_ready else ["真实触达 provider、sandbox、审批、审计和 operator action 未闭合。"],
            next_actions=["补真实邮件/电话/CRM provider 状态表和 sandbox 结果读回。"],
        ),
        _sellability_lane(
            lane_id="payment_delivery_writeback",
            title="支付交付与回写治理",
            status="PARTIAL" if not real_payment_ready else "PASS",
            current_state="支付、交付、退款仍是受控开放读回；自动退款保持排除。",
            evidence=["/go-live/readiness", "AGENTS.md#Automation Guardrails"],
            gaps=[] if real_payment_ready else ["真实支付、真实交付、真实退款异常处理和回写治理未接入 live provider。"],
            next_actions=["补支付/交付 sandbox、小样本 live pilot 状态和人工退款异常读回。"],
        ),
    ]
    counts: dict[str, int] = {}
    for lane in lanes:
        status = str(lane["status"])
        counts[status] = counts.get(status, 0) + 1

    external_sellable_now = bool(
        latest_opportunity_id
        and real_market_run_count
        and customer_sellable_ready_count
        and real_provider_ready
        and real_touch_ready
        and real_payment_ready
    )
    return {
        "surface_id": "operator_real_world_sellability_readiness",
        "surface_mode": "internal-readback",
        "contract_ref": "contracts/ui/operator_user_acceptance_contract.json#UA-11-real-world-sellability",
        "gap_matrix_ref": "control/operator_user_acceptance_gap_matrix.json#UA-11-real-world-sellability",
        "internal_only": True,
        "readiness_only": True,
        "projection_only": True,
        "raw_json_required": False,
        "ua11_satisfied": False,
        "real_world_product_completion_satisfied": False,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "public_software_release": False,
        "real_provider_call_enabled": False,
        "automated_refund_enabled": False,
        "sellability_summary": {
            "sellability_level": "真实实战未完成：缺真实快照入链和客户可售证据"
            if real_market_run_count or stage2_detail_snapshot_count
            else "真实实战未完成：缺真实市场候选进料",
            "owner_decision": (
                "内部/样本链路可用于回归、观察和证据包预览；"
                "真实列表页候选发现、详情快照读回和同站附件原文快照已进入最小闭环，但客户可售前仍需 Stage4-9 证据回链。"
                if real_market_run_count or stage2_detail_snapshot_count
                else "默认实战搜索尚未命中真实公开来源候选，不能宣称真实可售。"
            ),
            "latest_opportunity_id": latest_opportunity_id,
            "accepted_run_count": accepted_run_count,
            "real_market_run_count": real_market_run_count,
            "stage2_detail_snapshot_count": stage2_detail_snapshot_count,
            "stage2_attachment_snapshot_count": stage2_attachment_snapshot_count,
            "customer_sellable_ready_count": customer_sellable_ready_count,
            "observed_stage_count": observed_stage_count,
            "external_sellable_now": external_sellable_now,
            "lane_counts": counts,
        },
        "boundary": {
            "regression_search_and_evidence_package_review": bool(latest_opportunity_id or region_count),
            "real_market_candidate_feed_ready": bool(real_market_run_count),
            "real_detail_snapshot_feed_ready": bool(stage2_detail_snapshot_count),
            "real_attachment_snapshot_feed_ready": bool(stage2_attachment_snapshot_count),
            "customer_sellable_evidence_ready": bool(customer_sellable_ready_count),
            "leadpack_delivery_candidate_visible": bool(latest_opportunity_id),
            "real_customer_touch_enabled": real_touch_ready,
            "real_payment_enabled": bool(controlled.get("real_payment_enabled", False)),
            "real_delivery_enabled": bool(controlled.get("real_delivery_enabled", False)),
            "automated_refund_enabled": False,
        },
        "lanes": lanes,
        "remaining_real_world_closures": [
            "真实公开来源候选发现器硬化：更多列表页搜索、公告解析、候选去重入库",
            "真实详情页/附件快照已接首段；继续补 Stage4-9 正式消费",
            "重点地区本地适配器覆盖",
            "真实触达 provider sandbox 与审批审计",
            "真实支付/交付 provider sandbox 与回写治理",
        ],
        "source_readbacks": {
            "region_adapter_count": region_count,
            "latest_search_run_id": latest_run.get("run_id"),
            "stage2_detail_snapshot_count": stage2_detail_snapshot_count,
            "go_live_enabled": bool(go_live.get("go_live_enabled", False)),
            "remaining_blockers": list(go_live.get("remaining_blockers", [])),
        },
    }


def _queue_status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in WorkerQueueRepository().list():
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def _queue_item_summary(item: Any) -> dict[str, Any]:
    if item is None:
        return {}
    payload = dict(getattr(item, "payload", {}) or {})
    scheduler_task = dict(payload.get("scheduler_task", {}) or {})
    stage1_inputs = dict(payload.get("stage1_inputs", {}) or {})
    handoff = dict(
        scheduler_task.get("stage2_handoff_intent", {})
        or payload.get("stage2_handoff_intent", {})
        or {}
    )
    handoff_payload = dict(handoff.get("handoff_payload", {}) or {})
    trace_refs = dict(getattr(item, "trace_refs", {}) or {})
    audit_refs = dict(getattr(item, "audit_refs", {}) or {})
    return {
        "queue_item_id": str(getattr(item, "queue_item_id", "") or ""),
        "queue_name": str(getattr(item, "queue_name", "") or ""),
        "status": str(getattr(item, "status", "") or ""),
        "task_id": str(scheduler_task.get("task_id") or trace_refs.get("task_id") or ""),
        "project_id": str(scheduler_task.get("project_id") or trace_refs.get("project_id") or ""),
        "region_code": str(stage1_inputs.get("region_code") or handoff_payload.get("region_code") or ""),
        "source_registry_id": str(scheduler_task.get("source_registry_id") or trace_refs.get("source_registry_id") or ""),
        "route_policy_id": str(scheduler_task.get("route_policy_id") or trace_refs.get("route_policy_id") or ""),
        "stage2_handoff_intent_state": str(handoff.get("intent_state") or ""),
        "priority": getattr(item, "priority", None),
        "attempt_count": getattr(item, "attempt_count", None),
        "max_attempts": getattr(item, "max_attempts", None),
        "next_run_at": getattr(item, "next_run_at", None),
        "created_at": getattr(item, "created_at", None),
        "updated_at": getattr(item, "updated_at", None),
        "last_error": getattr(item, "last_error", None),
        "audit_ref": audit_refs.get("scheduling_audit_id") or audit_refs.get("run_audit_ref") or "",
    }


def _latest_queue_item_summaries(limit: int = 8) -> list[dict[str, Any]]:
    items = WorkerQueueRepository().list()
    items.sort(key=lambda item: str(getattr(item, "updated_at", "") or ""), reverse=True)
    return [_queue_item_summary(item) for item in items[:limit]]


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


def _overlay_stage2_capture_on_candidate(
    candidate: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(candidate)
    fields = dict(capture.get("detail_fields", {}) or {})
    detail_snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
    attachment_captures = list(capture.get("attachment_captures", []) or [])
    attachment_snapshot_ids = [
        str(item.get("attachment_snapshot_id_optional") or "")
        for item in attachment_captures
        if str(item.get("attachment_snapshot_id_optional") or "")
    ]
    row["stage2_detail_capture_state"] = str(capture.get("detail_capture_status") or "")
    row["stage2_detail_snapshot_id_optional"] = detail_snapshot_id
    row["stage3_detail_parse_state"] = str(capture.get("stage3_parse_state") or "")
    row["stage2_attachment_link_count"] = _as_int(capture.get("attachment_link_count"), 0)
    row["stage2_attachment_snapshot_count"] = len(attachment_snapshot_ids)
    row["stage2_attachment_snapshot_ids"] = attachment_snapshot_ids
    row["stage2_attachment_captures"] = attachment_captures
    if fields.get("project_name"):
        row["project_name"] = str(fields["project_name"])
    if fields.get("notice_stage"):
        row["notice_stage"] = str(fields["notice_stage"])
    if fields.get("amount") is not None:
        row["amount"] = fields["amount"]
        row["estimated_amount"] = fields["amount"]
        row["amount_parse_state"] = fields.get("amount_parse_state") or "DETAIL_TEXT"
    if fields.get("candidate_company"):
        row["candidate_company"] = str(fields["candidate_company"])
        row["candidate_company_parse_state"] = fields.get("candidate_company_parse_state") or "DETAIL_TEXT"
    if fields.get("objection_deadline_at_optional"):
        row["objection_deadline_at_optional"] = str(fields["objection_deadline_at_optional"])
    if detail_snapshot_id:
        row["source_document_ref"] = detail_snapshot_id
        row["source_slice_ref"] = detail_snapshot_id
        row["real_snapshot_ids"] = [
            value
            for value in [
                str(row.get("snapshot_id_optional") or ""),
                detail_snapshot_id,
                *attachment_snapshot_ids,
            ]
            if value
        ]
    key_fields = set(str(item) for item in list(row.get("key_fields_present", []) or []) if item)
    for key in ("project_name", "notice_stage", "candidate_company"):
        if row.get(key):
            key_fields.add(key)
    row["key_fields_present"] = sorted(key_fields)
    row["sellability_evidence_state"] = (
        "REAL_DETAIL_AND_ATTACHMENT_SNAPSHOTS_PARSED_NEEDS_STAGE4_TO_STAGE9"
        if detail_snapshot_id and attachment_snapshot_ids
        else "REAL_DETAIL_SNAPSHOT_PARSED_NEEDS_STAGE4_TO_STAGE9"
        if detail_snapshot_id
        else row.get("sellability_evidence_state")
    )
    row["truth_boundary"] = (
        "真实候选库已合并最新详情/附件快照读回；客户可售前仍需 Stage4-9 正式消费快照并完成证据回链。"
        if detail_snapshot_id
        else row.get("truth_boundary")
    )
    row["stage2_capture_overlay_applied"] = bool(capture)
    return row


def list_operator_real_candidates(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    limit = _as_int((payload or {}).get("limit"), 100) if isinstance(payload, Mapping) else 100
    catalog = list_persisted_real_candidates(limit=limit)
    captures = list_real_candidate_stage2_captures(limit=limit)
    capture_by_key = {
        str(capture.get("candidate_key") or ""): capture
        for capture in list(captures.get("captures", []) or [])
        if str(capture.get("candidate_key") or "")
    }
    catalog["candidates"] = [
        _overlay_stage2_capture_on_candidate(candidate, capture_by_key[str(candidate.get("candidate_key") or "")])
        if str(candidate.get("candidate_key") or "") in capture_by_key
        else candidate
        for candidate in list(catalog.get("candidates", []) or [])
    ]
    catalog["stage2_capture_overlay_applied"] = bool(capture_by_key)
    catalog["stage2_capture_overlay_count"] = sum(
        1
        for candidate in list(catalog.get("candidates", []) or [])
        if bool(candidate.get("stage2_capture_overlay_applied"))
    )
    catalog["stage2_capture_catalog_count"] = _as_int(captures.get("capture_count"), 0)
    return catalog


def list_operator_real_candidate_discovery_runs(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    limit = _as_int((payload or {}).get("limit"), 50) if isinstance(payload, Mapping) else 50
    return list_real_candidate_discovery_runs(limit=limit)


def list_operator_real_candidate_stage2_captures(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    limit = _as_int((payload or {}).get("limit"), 100) if isinstance(payload, Mapping) else 100
    return list_real_candidate_stage2_captures(limit=limit)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}
    return bool(value)


def _id_token(value: Any, default: str) -> str:
    token = "".join(
        char.upper() if char.isascii() and char.isalnum() else "-"
        for char in str(value or "").strip()
    ).strip("-")
    token = "-".join(part for part in token.split("-") if part)
    return token or default


def _as_string_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items or list(default)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(str(text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _project_type_label(project_type: str) -> str:
    labels = {
        "construction": "房建工程",
        "municipal": "市政工程",
        "highway": "公路交通",
        "water_conservancy": "水利工程",
    }
    return labels.get(project_type, project_type)


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
    amount_min = _as_float(_first_present(payload.get("amount_min"), payload.get("minimum_amount")), 1_000_000.0)
    amount_max = _as_float(
        _first_present(payload.get("amount_max"), payload.get("maximum_amount"), payload.get("amount")),
        12_000_000.0,
    )
    if amount_max < amount_min:
        amount_min, amount_max = amount_max, amount_min
    amount = _as_float(payload.get("amount"), amount_max)
    if amount < amount_min or amount > amount_max:
        amount = amount_max
    candidate_count = _as_int(payload.get("candidate_count"), 3)
    project_id_parts = [_id_token(region_code, "REGION"), _id_token(keyword, "SEARCH")[:18]]
    if payload.get("multi_search_candidate_index") not in (None, ""):
        project_id_parts.insert(1, _id_token(project_type, "TYPE"))
    project_id = str(
        payload.get("project_id")
        or build_id("PROJ", "-".join(project_id_parts[:-1]), project_id_parts[-1])
    )
    project_name = str(payload.get("project_name") or f"{region_adapter.get('region_name')} {keyword} 机会搜索样本")
    source_url = str(entry_profile.get("sample_detail_url") or entry_profile.get("url") or "")
    return {
        "notice_id": str(payload.get("notice_id") or build_id("NOTICE", project_id)),
        "project_id": project_id,
        "project_name": project_name,
        "region_code": region_code,
        "region_name": str(region_adapter.get("region_name") or region_code),
        "project_type": project_type,
        "project_type_label": _project_type_label(project_type),
        "procurement_category": project_type,
        "notice_stage": str(payload.get("notice_stage") or "candidate_notice"),
        "amount": amount,
        "estimated_amount": amount,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "amount_range_label": f"{amount_min:,.0f}-{amount_max:,.0f}",
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


def _resolve_entry_profile_for_search(
    region_code: str,
    *,
    requested_profile_id: str | None = None,
) -> dict[str, Any]:
    try:
        return resolve_entry_profile_for_region(
            region_code,
            requested_profile_id=requested_profile_id,
        )
    except ValueError as exc:
        if not str(exc).startswith("region_adapter_profile_missing:"):
            raise
        return {
            "region_adapter": resolve_region_source_adapter(region_code),
            "entry_profile": {},
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
    candidate_source_mode = str(candidate.get("source_candidate_mode") or "")
    detail_snapshot_ref = str(
        candidate.get("source_document_ref")
        or candidate.get("stage2_detail_snapshot_id_optional")
        or payload.get("source_document_ref")
        or build_id("DOC", candidate.get("project_id") or "SEARCH")
    )
    slice_snapshot_ref = str(
        candidate.get("source_slice_ref")
        or candidate.get("stage2_detail_snapshot_id_optional")
        or payload.get("source_slice_ref")
        or build_id("SLICE", candidate.get("project_id") or "SEARCH")
    )
    real_snapshot_ids = [
        str(item)
        for item in list(candidate.get("real_snapshot_ids", []) or [])
        if str(item)
    ]
    if detail_snapshot_ref.startswith("REAL-") and detail_snapshot_ref not in real_snapshot_ids:
        real_snapshot_ids.append(detail_snapshot_ref)
    for attachment_snapshot_id in list(candidate.get("stage2_attachment_snapshot_ids", []) or []):
        value = str(attachment_snapshot_id or "")
        if value and value not in real_snapshot_ids:
            real_snapshot_ids.append(value)
    return {
        "now": now,
        "task_id": str(payload.get("task_id") or build_id("TASK", market_scan.get("scan_run_id") or "SEARCH")),
        "project_id": str(candidate.get("project_id") or payload.get("project_id") or "PROJ-SEARCH"),
        "project_root_id": str(payload.get("project_root_id") or build_id("ROOT", candidate.get("project_id") or "SEARCH")),
        "project_name": str(candidate.get("project_name") or payload.get("project_name") or "机会搜索项目"),
        "region_code": str(candidate.get("region_code") or payload.get("region_code") or "CN-NATIONAL"),
        "region_scope": str(payload.get("region_scope") or "NATIONAL"),
        "source_family": str(payload.get("source_family") or "PROCUREMENT_NOTICE"),
        "platform_level": str(payload.get("platform_level") or "NATIONAL"),
        "coverage_tier": str(payload.get("coverage_tier") or "T0_CORE"),
        "default_route": str(payload.get("default_route") or "LIST_TO_DETAIL"),
        "review_lane": str(payload.get("review_lane") or "STANDARD"),
        "carrier_type": str(payload.get("carrier_type") or "HTML_PAGE"),
        "announcement_url": str(candidate.get("source_url") or payload.get("announcement_url") or "https://example.invalid/notice/search"),
        "source_document_ref": detail_snapshot_ref,
        "source_slice_ref": slice_snapshot_ref,
        "real_snapshot_ids": real_snapshot_ids,
        "stage2_detail_snapshot_id_optional": str(candidate.get("stage2_detail_snapshot_id_optional") or ""),
        "stage2_attachment_snapshot_ids": [
            str(item)
            for item in list(candidate.get("stage2_attachment_snapshot_ids", []) or [])
            if str(item)
        ],
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
        "payload_boundary": "REAL_PUBLIC_INTERNAL_REPLAY"
        if candidate_source_mode == "REAL_PUBLIC_SOURCE_CANDIDATES"
        else "SANITIZED_OFFLINE_INTERNAL",
        "source_mode": "REAL_PUBLIC_CANDIDATE_DETAIL_CAPTURE"
        if candidate_source_mode == "REAL_PUBLIC_SOURCE_CANDIDATES"
        else "OFFLINE_REAL_PUBLIC_SAMPLE",
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


def _stage3_field_value(
    parsed: Mapping[str, Any],
    *field_names: str,
    prefer_review_free: bool = True,
) -> str:
    fields = [
        dict(field)
        for field in list(parsed.get("parsed_fields", []) or [])
        if isinstance(field, Mapping)
    ]
    if prefer_review_free:
        for field_name in field_names:
            for field in fields:
                if field.get("field_name") != field_name:
                    continue
                value = str(field.get("field_value_optional") or "").strip()
                if value and not bool(field.get("review_required")):
                    return value
    for field_name in field_names:
        for field in fields:
            if field.get("field_name") != field_name:
                continue
            value = str(field.get("field_value_optional") or "").strip()
            if value:
                return value
    return ""


def _build_review_required_real_public_stage4_9_summary(
    *,
    snapshot_id: str,
    source_url: str,
    fail_closed_reasons: list[str],
) -> dict[str, Any]:
    reasons = [str(reason) for reason in fail_closed_reasons if str(reason).strip()]
    return {
        "surface_id": "operator_real_public_stage4_9_readback",
        "readback_state": "REVIEW_REQUIRED",
        "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
        "stage4_public_verification_result": "NOT_RUN",
        "stage4_public_verification_readback_state": "REVIEW_REQUIRED",
        "stage5_rule_gate_status": "NOT_RUN",
        "stage5_evidence_gate_status": "NOT_RUN",
        "stage6_real_public_product_package_chain_state": "NOT_RUN",
        "stage7_real_public_sales_package_chain_state": "NOT_RUN",
        "stage8_real_public_outreach_chain_state": "NOT_RUN",
        "stage9_real_public_order_payment_delivery_chain_state": "NOT_RUN",
        "source_snapshot_id": snapshot_id,
        "source_url": source_url,
        "stage4_verification_target_type": "",
        "stage4_verification_target_identifier": "",
        "formal_real_public_readback_ready": False,
        "real_public_sellable_gate_ready": False,
        "customer_sellable_evidence_ready": False,
        "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
        "regional_hard_defect_source_plan": build_regional_hard_defect_source_plan({}),
        "remaining_real_world_gaps": [
            "stage4_5_local_housing_contract_completion_pm_change_penalty_adapters_pending",
        ],
        "fail_closed_reasons": reasons,
    }


def _build_real_public_stage4_9_readback_from_candidate(
    *,
    candidate: Mapping[str, Any],
    chain: Mapping[str, Any],
    object_repository: ObjectStorageRepository | None = None,
) -> dict[str, Any]:
    source_mode = str(candidate.get("source_candidate_mode") or "")
    if source_mode != REAL_PUBLIC_SOURCE_CANDIDATE_MODE:
        return {}
    snapshot_id = str(
        candidate.get("stage2_detail_snapshot_id_optional")
        or candidate.get("source_document_ref")
        or ""
    ).strip()
    source_url = str(candidate.get("source_url") or "").strip()
    if not snapshot_id:
        return _build_review_required_real_public_stage4_9_summary(
            snapshot_id="",
            source_url=source_url,
            fail_closed_reasons=["stage2_detail_snapshot_missing"],
        )

    repository = object_repository or ObjectStorageRepository()
    snapshot_readback = dict(repository.replay_snapshot(snapshot_id))
    if not bool(snapshot_readback.get("replayable")):
        return _build_review_required_real_public_stage4_9_summary(
            snapshot_id=snapshot_id,
            source_url=source_url,
            fail_closed_reasons=[
                f"stage2_detail_snapshot_not_replayable:{snapshot_readback.get('readback_state')}",
            ],
        )

    base_stage4 = chain.get("stage4")
    if base_stage4 is None:
        return _build_review_required_real_public_stage4_9_summary(
            snapshot_id=snapshot_id,
            source_url=source_url,
            fail_closed_reasons=["base_stage4_bundle_missing"],
        )

    try:
        parsed = dict(Stage3Service().parse_raw_snapshot(snapshot_id, repository=repository))
        target_identifier = (
            _stage3_field_value(parsed, "announcement_title", "project_name")
            or str(candidate.get("project_name") or "").strip()
        )
        if not target_identifier:
            return _build_review_required_real_public_stage4_9_summary(
                snapshot_id=snapshot_id,
                source_url=source_url,
                fail_closed_reasons=["stage4_verification_target_identifier_missing"],
            )
        stage4_verification = dict(
            Stage4Service().verify_public_parsed_carrier(
                parsed,
                target={
                    "verification_target_id": build_id(
                        "ST4T",
                        candidate.get("project_id") or snapshot_id,
                        "notice_public_record",
                    ),
                    "verification_target_type": "performance_public_record",
                    "target_identifier": target_identifier,
                    "source_snapshot_id": snapshot_id,
                    "source_url": source_url,
                },
                repository=repository,
                snapshot_readback=snapshot_readback,
            )
        )
        stage5 = Stage5Service().run_public_verification_readback(
            base_stage4,
            stage4_verification,
            requested_rule_codes=["DOC-001"],
        )
        stage6 = Stage6Service().run_real_public_rule_evidence_readback(stage5)
        stage7 = Stage7Service().run_real_public_product_package_readback(stage6)
        stage8 = Stage8Service().run_real_public_sales_execution_readback(stage7)
        stage9 = Stage9Service().run_real_public_outreach_delivery_readback(stage8)
        for bundle in (stage6, stage7, stage8, stage9):
            persist_stage_bundle(bundle)
    except Exception as exc:
        return _build_review_required_real_public_stage4_9_summary(
            snapshot_id=snapshot_id,
            source_url=source_url,
            fail_closed_reasons=[f"real_public_stage4_9_exception:{exc}"],
        )

    stage4_readback = dict(stage5.inputs.get("stage4_public_verification_readback_summary", {}) or {})
    stage5_readback = dict(stage5.inputs.get("stage5_rule_readback_summary", {}) or {})
    stage6_summary = dict(stage6.inputs.get(Stage6Service.REAL_PUBLIC_STAGE6_READBACK_KEY, {}) or {})
    stage7_summary = dict(stage7.inputs.get(Stage7Service.REAL_PUBLIC_STAGE7_READBACK_KEY, {}) or {})
    stage8_summary = dict(stage8.inputs.get(Stage8Service.REAL_PUBLIC_STAGE8_READBACK_KEY, {}) or {})
    stage9_summary = dict(stage9.inputs.get(Stage9Service.REAL_PUBLIC_STAGE9_READBACK_KEY, {}) or {})
    fail_closed_reasons = [
        *list(stage6_summary.get("fail_closed_reasons", []) or []),
        *list(stage7_summary.get("fail_closed_reasons", []) or []),
        *list(stage8_summary.get("fail_closed_reasons", []) or []),
        *list(stage9_summary.get("fail_closed_reasons", []) or []),
    ]
    formal_chain_state = str(
        stage9_summary.get("real_public_order_payment_delivery_chain_state")
        or stage8_summary.get("real_public_outreach_chain_state")
        or stage7_summary.get("real_public_sales_package_chain_state")
        or stage6_summary.get("real_public_product_package_chain_state")
        or "REVIEW_REQUIRED"
    )
    regional_source_readback: dict[str, Any] = {}
    if str(candidate.get("region_code") or "").upper() == "CN-GD":
        regional_source_readback = dict(
            query_guangdong_gdcic_openplatform_hard_defect_sources(
                candidate,
                repository=repository,
            )
        )
    covered_source_types = {
        str(stage4_verification.get("verification_target_type") or ""),
        *[
            str(source_type)
            for source_type in list(regional_source_readback.get("covered_source_types", []) or [])
            if str(source_type).strip()
        ],
    }
    regional_source_plan = build_regional_hard_defect_source_plan(
        candidate,
        covered_source_types=covered_source_types,
    )
    remaining_source_types = list(regional_source_plan.get("missing_source_types", []) or [])
    real_world_gate_state = (
        "READY_FOR_SELLABLE_EVIDENCE_REVIEW"
        if formal_chain_state == "INTERNAL_READY" and not remaining_source_types
        else "PARTIAL_SOURCE_COVERAGE"
    )
    remaining_real_world_gaps = [
        f"missing_stage4_5_source_type:{source_type}"
        for source_type in remaining_source_types
    ]
    if remaining_real_world_gaps:
        remaining_real_world_gaps.append(
            "stage4_5_local_housing_contract_completion_pm_change_penalty_adapters_pending"
        )
    regional_failures = list(regional_source_readback.get("failure_reasons", []) or [])
    return {
        "surface_id": "operator_real_public_stage4_9_readback",
        "readback_state": "READBACK_READY" if formal_chain_state == "INTERNAL_READY" else "REVIEW_REQUIRED",
        "real_public_stage4_9_chain_state": formal_chain_state,
        "stage4_public_verification_run_id": stage4_verification.get("verification_run_id"),
        "stage4_public_verification_result": stage4_verification.get("verification_result"),
        "stage4_public_verification_readback_state": stage4_readback.get("readback_state"),
        "stage4_public_verification_review_required": bool(stage4_verification.get("review_required")),
        "stage4_verification_target_type": stage4_verification.get("verification_target_type"),
        "stage4_verification_target_identifier": target_identifier,
        "stage5_rule_gate_status": stage5.handoff.get("rule_gate_status"),
        "stage5_evidence_gate_status": stage5.handoff.get("evidence_gate_status"),
        "stage5_public_verification_refs": list(stage5_readback.get("stage4_public_verification_refs", []) or []),
        "stage6_real_public_product_package_chain_state": stage6_summary.get(
            "real_public_product_package_chain_state"
        ),
        "stage7_real_public_sales_package_chain_state": stage7_summary.get(
            "real_public_sales_package_chain_state"
        ),
        "stage8_real_public_outreach_chain_state": stage8_summary.get("real_public_outreach_chain_state"),
        "stage9_real_public_order_payment_delivery_chain_state": stage9_summary.get(
            "real_public_order_payment_delivery_chain_state"
        ),
        "source_snapshot_id": stage4_verification.get("source_snapshot_id") or snapshot_id,
        "source_url": stage4_verification.get("source_url") or source_url,
        "input_parse_run_id": stage4_verification.get("input_parse_run_id") or parsed.get("parse_run_id"),
        "source_refs": {
            "stage4_public_verification": {
                "verification_run_id": stage4_verification.get("verification_run_id"),
                "source_snapshot_id": stage4_verification.get("source_snapshot_id"),
                "input_parse_run_id": stage4_verification.get("input_parse_run_id"),
            },
            "stage4_5_regional_source_readback": {
                "source_readback_id": regional_source_readback.get("source_readback_id"),
                "adapter_id": regional_source_readback.get("adapter_id"),
                "covered_source_types": list(regional_source_readback.get("covered_source_types", []) or []),
                "queried_source_types": list(regional_source_readback.get("queried_source_types", []) or []),
            },
            "stage6": dict(stage6_summary.get("source_refs", {}) or {}),
            "stage7": dict(stage7_summary.get("source_refs", {}) or {}),
            "stage8": dict(stage8_summary.get("source_refs", {}) or {}),
            "stage9": dict(stage9_summary.get("source_refs", {}) or {}),
        },
        "formal_real_public_readback_ready": formal_chain_state == "INTERNAL_READY",
        "real_public_sellable_gate_ready": formal_chain_state == "INTERNAL_READY" and not remaining_real_world_gaps,
        "customer_sellable_evidence_ready": False,
        "real_world_hard_defect_gate_state": real_world_gate_state,
        "regional_hard_defect_source_plan": regional_source_plan,
        "regional_hard_defect_source_readback": regional_source_readback,
        "remaining_real_world_gaps": remaining_real_world_gaps,
        "fail_closed_reasons": list(
            dict.fromkeys(
                str(reason)
                for reason in [*fail_closed_reasons, *regional_failures]
                if reason
            )
        ),
    }


def _bundle_record_count(bundle: Any) -> int:
    records = getattr(bundle, "records", None)
    if isinstance(records, Mapping):
        return len(records)
    return 0


def _runtime_stage(
    *,
    stage: int,
    name: str,
    produced_count: int,
    effective_count: int | None = None,
    invalid_count: int = 0,
    input_count: int | None = None,
    output_count: int | None = None,
    state: str = "已完成",
    note: str = "",
    object_refs: Mapping[str, Any] | None = None,
    failure_reasons: list[str] | None = None,
    next_action: str = "",
) -> dict[str, Any]:
    effective = produced_count if effective_count is None else effective_count
    refs = {
        key: value
        for key, value in dict(object_refs or {}).items()
        if value not in (None, "", [], {})
    }
    return {
        "stage": stage,
        "name": name,
        "state": state,
        "input_count": max(input_count if input_count is not None else produced_count, 0),
        "output_count": max(output_count if output_count is not None else effective, 0),
        "produced_count": max(produced_count, 0),
        "effective_count": max(effective, 0),
        "invalid_count": max(invalid_count, 0),
        "note": note,
        "object_refs": refs,
        "failure_reasons": list(failure_reasons or []),
        "next_action": next_action,
    }


def _build_autonomous_runtime_flow(
    *,
    payload: Mapping[str, Any],
    candidate: Mapping[str, Any],
    market_scan: Mapping[str, Any],
    source_blueprint: Mapping[str, Any],
    chain: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    real_public_stage4_9_readback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    capture_plan = dict(source_blueprint.get("stage2_capture_plan", {}) or {})
    capture_steps = list(capture_plan.get("capture_steps", []) or [])
    input_candidates = _as_int(market_scan.get("input_candidate_count"), 1)
    selected_candidates = _as_int(market_scan.get("selected_candidate_count"), 0)
    review_candidates = _as_int(market_scan.get("review_candidate_count"), 0)
    skipped_candidates = _as_int(market_scan.get("skipped_candidate_count"), 0)
    stage_refs = {
        str(key): dict(value or {})
        for key, value in dict(acceptance.get("stage_refs", {}) or {}).items()
        if isinstance(value, Mapping)
    }
    stage_ref_ids = {
        key: str(value.get("object_id") or "")
        for key, value in stage_refs.items()
        if str(value.get("object_id") or "").strip()
    }
    acceptance_state = str(acceptance.get("acceptance_state") or "")
    acceptance_reasons = [
        str(reason)
        for reason in list(acceptance.get("fail_closed_reasons", []) or acceptance.get("blocked_reasons", []) or [])
        if str(reason).strip()
    ]
    stage1_reasons = []
    if review_candidates:
        stage1_reasons.append(f"{review_candidates} 个候选进入复核")
    if skipped_candidates:
        stage1_reasons.append(f"{skipped_candidates} 个候选被过滤")
    stage2_reasons = [] if capture_steps else ["未生成公开来源采集步骤"]
    source_profile_id = str(candidate.get("source_profile_id") or "")
    source_candidate_mode = str(candidate.get("source_candidate_mode") or "EXPLICIT_CANDIDATES")
    offline_sample_validation = bool(candidate.get("is_offline_sample_candidate")) or source_candidate_mode == "OFFLINE_SAMPLE_CANDIDATES"
    real_public_readback = dict(real_public_stage4_9_readback or {})
    real_public_chain_state = str(real_public_readback.get("real_public_stage4_9_chain_state") or "")
    real_public_fail_reasons = [
        str(reason)
        for reason in list(real_public_readback.get("fail_closed_reasons", []) or [])
        if str(reason).strip()
    ]
    remaining_real_world_gaps = [
        str(reason)
        for reason in list(real_public_readback.get("remaining_real_world_gaps", []) or [])
        if str(reason).strip()
    ]
    real_public_formal_ready = bool(real_public_readback.get("formal_real_public_readback_ready"))
    opportunity_id = str(stage_ref_ids.get("stage7_saleable_opportunity") or "")
    requested_regions_text = ", ".join(
        str(value)
        for value in list(payload.get("region_codes", []) or [candidate.get("region_code") or payload.get("region_code") or ""])
        if str(value).strip()
    )
    requested_project_types_text = ", ".join(
        str(value)
        for value in list(payload.get("project_types", []) or [candidate.get("project_type") or payload.get("project_type") or ""])
        if str(value).strip()
    )
    stage_stats = [
        _runtime_stage(
            stage=1,
            name="市场扫描 / 机会发现",
            produced_count=input_candidates,
            effective_count=selected_candidates,
            invalid_count=review_candidates + skipped_candidates,
            input_count=input_candidates,
            output_count=selected_candidates,
            note="按地区、项目类型、金额区间和竞争信号筛选机会。",
            object_refs={
                "scan_run_id": market_scan.get("scan_run_id"),
                "selected_project_id": candidate.get("project_id"),
                "selected_opportunity_candidate_id": candidate.get("opportunity_candidate_id"),
                "passed_filter_candidate_count": selected_candidates,
                "review_candidate_count": review_candidates,
                "filtered_candidate_count": skipped_candidates,
                "region_codes": requested_regions_text,
                "project_types": requested_project_types_text,
            },
            failure_reasons=stage1_reasons,
            next_action="保留所有通过过滤的候选并进入来源蓝图。",
        ),
        _runtime_stage(
            stage=2,
            name="来源蓝图 / 采集计划",
            produced_count=len(capture_steps),
            effective_count=len(capture_steps),
            input_count=selected_candidates,
            output_count=len(capture_steps),
            note=(
                "自动选择公开入口并已读取真实候选详情快照。"
                if real_public_readback
                else "自动选择公开入口和采集步骤；当前不执行真实外部抓取。"
            ),
            object_refs={
                "source_blueprint_plan_id": source_blueprint.get("source_blueprint_plan_id"),
                "entry_profile_id": source_profile_id,
                "capture_step_count": len(capture_steps),
                "stage2_detail_snapshot_id": candidate.get("stage2_detail_snapshot_id_optional"),
                "stage2_attachment_snapshot_count": candidate.get("stage2_attachment_snapshot_count"),
            },
            failure_reasons=stage2_reasons,
            next_action="采集计划进入公开源执行或内部样本链路。",
        ),
        _runtime_stage(
            stage=3,
            name="解析规范化",
            produced_count=_bundle_record_count(chain.get("stage3")),
            input_count=len(capture_steps),
            object_refs={
                "project_id": candidate.get("project_id"),
                "project_name": candidate.get("project_name"),
                "source_url": candidate.get("source_url"),
                "stage2_detail_snapshot_id": candidate.get("stage2_detail_snapshot_id_optional"),
                "stage3_detail_parse_state": candidate.get("stage3_detail_parse_state"),
            },
            note="把公开材料解析成统一项目字段。",
            next_action="统一项目字段后进入证据风险核验。",
        ),
        _runtime_stage(
            stage=4,
            name="证据风险核验",
            produced_count=_bundle_record_count(chain.get("stage4")),
            state=(
                "已接入真实快照"
                if real_public_formal_ready
                else "待补强"
                if real_public_readback
                else "已完成"
            ),
            object_refs={
                "evidence_risk_ref": stage_ref_ids.get("stage4_evidence_risk"),
                "review_profile_ref": stage_ref_ids.get("stage4_review_profile"),
                "real_public_verification_run_id": real_public_readback.get("stage4_public_verification_run_id"),
                "real_public_verification_result": real_public_readback.get("stage4_public_verification_result"),
                "real_public_chain_state": real_public_chain_state,
                "real_world_hard_defect_gate_state": real_public_readback.get("real_world_hard_defect_gate_state"),
                "regional_hard_defect_source_plan_id": dict(
                    real_public_readback.get("regional_hard_defect_source_plan", {}) or {}
                ).get("source_plan_id"),
            },
            failure_reasons=remaining_real_world_gaps or real_public_fail_reasons,
            note="生成公开核验、硬伤风险和复核项。",
            next_action="核验结果进入规则证据门。",
        ),
        _runtime_stage(
            stage=5,
            name="规则证据门",
            produced_count=_bundle_record_count(chain.get("stage5")),
            state=(
                "已接入真实读回"
                if real_public_formal_ready
                else "待复核"
                if acceptance_reasons or real_public_fail_reasons
                else "已完成"
            ),
            object_refs={
                "acceptance_state": acceptance_state,
                "rule_evidence_ref": stage_ref_ids.get("stage5_rule_evidence"),
                "commercial_evidence_ref": stage_ref_ids.get("stage5_commercial_evidence"),
                "stage5_real_public_rule_gate_status": real_public_readback.get("stage5_rule_gate_status"),
                "stage5_real_public_evidence_gate_status": real_public_readback.get("stage5_evidence_gate_status"),
            },
            failure_reasons=acceptance_reasons + real_public_fail_reasons,
            note="把证据链、规则命中和产品化条件合并。",
            next_action="通过后进入可售产品包；待复核则回到证据补强。",
        ),
        _runtime_stage(
            stage=6,
            name="产品包",
            produced_count=_bundle_record_count(chain.get("stage6")),
            object_refs={
                "report_record_ref": stage_ref_ids.get("stage6_report_record"),
                "product_package_ref": stage_ref_ids.get("stage6_product_package"),
            },
            note="形成可售判断、报告记录和内部产品包。",
            next_action="形成机会详情和证据包候选。",
        ),
        _runtime_stage(
            stage=7,
            name="商业钩子 / 买家匹配",
            produced_count=_bundle_record_count(chain.get("stage7")),
            object_refs={
                "opportunity_id": opportunity_id,
                "saleable_opportunity_ref": stage_ref_ids.get("stage7_saleable_opportunity"),
                "buyer_fit_ref": stage_ref_ids.get("stage7_buyer_fit"),
            },
            note="生成商业钩子、买家排序和销售下一步。",
            next_action="进入触达计划草稿和机会工作台。",
        ),
        _runtime_stage(
            stage=8,
            name="触达计划",
            produced_count=_bundle_record_count(chain.get("stage8")),
            state="已生成草稿",
            object_refs={
                "outreach_plan_ref": stage_ref_ids.get("stage8_outreach_plan"),
                "provider_execution_state": "内部草稿，真实触达未执行",
            },
            note="内部生成触达计划；真实触达需单独审批和审计。",
            next_action="内部预览可复核；真实触达需 provider/sandbox/live 放行。",
        ),
        _runtime_stage(
            stage=9,
            name="支付交付",
            produced_count=_bundle_record_count(chain.get("stage9")),
            state="已生成交付候选",
            object_refs={
                "order_record_ref": stage_ref_ids.get("stage9_order_record"),
                "delivery_package_ref": stage_ref_ids.get("stage9_delivery_package"),
                "automated_refund_enabled": "false",
            },
            note="内部生成交付候选；真实下载、支付、退款不在本次自动执行。",
            next_action="成交付款后进入受控邮件交付；自动退款不执行。",
        ),
    ]
    total_produced = sum(row["produced_count"] for row in stage_stats)
    total_effective = sum(row["effective_count"] for row in stage_stats)
    total_invalid = sum(row["invalid_count"] for row in stage_stats)
    data_boundary_message = (
        "离线样本只验证 Stage1-9、工作台和证据包链路；不能当作真实市场发现或客户可售证据。"
        if offline_sample_validation
        else "真实候选详情快照已被 Stage4-9 正式读回；客户可售前仍需地方住建、合同备案、竣工、项目经理变更和处罚源补强。"
        if real_public_formal_ready
        else "真实列表页候选已进入内部闭环；客户可交付前仍需核验真实来源详情页、附件和证据回链。"
        if source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE
        else "显式候选已进入内部闭环；客户可交付前仍需核验真实来源详情页、附件和证据回链。"
    )
    return {
        "surface_id": "autonomous_search_runtime_flow",
        "flow_mode": "真实候选内部闭环" if source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE else "内部实战测试闭环",
        "direction": (
            "地区机会扫描 -> 真实详情快照 -> Stage4-9真实读回 -> 工作台 -> 客户材料候选"
            if real_public_readback
            else "地区机会扫描 -> 来源蓝图 -> 阶段1-9内部链路 -> 工作台 -> 客户材料候选"
        ),
        "source_candidate_mode": source_candidate_mode,
        "real_market_discovery": not offline_sample_validation,
        "real_candidate_discovery_attempted": source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
        "offline_sample_validation": offline_sample_validation,
        "customer_sellable_evidence_ready": False,
        "real_public_stage4_9_readback": real_public_readback,
        "data_boundary_message": data_boundary_message,
        "test_path_unblocked": True,
        "live_delivery_gates_preserved": True,
        "amount_range": {
            "minimum": candidate.get("amount_min"),
            "maximum": candidate.get("amount_max"),
            "unit": "CNY",
        },
        "project_type": candidate.get("project_type") or payload.get("project_type"),
        "acceptance_state": acceptance.get("acceptance_state"),
        "stage_stats": stage_stats,
        "totals": {
            "stage_count": len(stage_stats),
            "produced_count": total_produced,
            "effective_count": total_effective,
            "invalid_count": total_invalid,
        },
        "logs": [
            "收到搜索条件并生成候选项目。",
            f"阶段1 过滤后通过 {selected_candidates}/{input_candidates} 个候选机会。",
            f"阶段2 生成 {len(capture_steps)} 个采集计划步骤。",
            (
                f"真实详情快照已进入 Stage4-9 读回，链路状态 {real_public_chain_state}。"
                if real_public_readback
                else "阶段3-9已在内部链路生成结构化对象、商业钩子和交付候选。"
            ),
            "真实对外交付门禁保留；内部/样本链路仅代表回归跑通。",
        ],
    }


def _candidate_option_surface(
    *,
    market_scan: Mapping[str, Any],
    raw_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_by_project_id = {str(candidate.get("project_id") or ""): candidate for candidate in raw_candidates}
    options: list[dict[str, Any]] = []
    for row in list(market_scan.get("market_scan_candidates", []) or []):
        if not isinstance(row, Mapping):
            continue
        project_id = str(row.get("project_id") or "")
        raw = raw_by_project_id.get(project_id, {})
        source_refs = dict(row.get("source_refs", {}) or {})
        amount_min = raw.get("amount_min")
        amount_max = raw.get("amount_max")
        options.append(
            {
                "opportunity_candidate_id": str(row.get("opportunity_candidate_id") or ""),
                "project_id": project_id,
                "project_name": str(row.get("project_name") or raw.get("project_name") or ""),
                "region_code": str(row.get("region_code") or raw.get("region_code") or ""),
                "region_name": str(raw.get("region_name") or row.get("region_code") or ""),
                "project_type": str(row.get("project_type") or raw.get("project_type") or ""),
                "project_type_label": _project_type_label(str(row.get("project_type") or raw.get("project_type") or "")),
                "amount": row.get("amount"),
                "candidate_company": str(raw.get("candidate_company") or row.get("candidate_company") or ""),
                "amount_min": amount_min,
                "amount_max": amount_max,
                "analysis_score": row.get("analysis_score"),
                "analysis_decision": str(row.get("analysis_decision") or ""),
                "analysis_priority": str(row.get("analysis_priority") or ""),
                "selected_for_capture_plan": bool(row.get("selected_for_capture_plan")),
                "why_analyze": list(row.get("why_analyze", []) or []),
                "why_skip": list(row.get("why_skip", []) or []),
                "review_reasons": list(row.get("review_reasons", []) or []),
                "score_components": dict(row.get("score_components", {}) or {}),
                "source_url": str(raw.get("source_url") or source_refs.get("source_url") or ""),
                "source_profile_id": str(raw.get("source_profile_id") or ""),
                "source_site_name": str(raw.get("source_site_name") or ""),
                "source_candidate_mode": str(raw.get("source_candidate_mode") or ""),
                "is_offline_sample_candidate": bool(raw.get("is_offline_sample_candidate")),
                "sellability_evidence_state": str(raw.get("sellability_evidence_state") or ""),
                "truth_boundary": str(raw.get("truth_boundary") or ""),
                "candidate_key": str(raw.get("candidate_key") or ""),
                "source_entry_url": str(raw.get("source_entry_url") or ""),
                "snapshot_id_optional": str(raw.get("snapshot_id_optional") or ""),
                "entry_fetch_status": str(raw.get("entry_fetch_status") or ""),
                "amount_parse_state": str(raw.get("amount_parse_state") or ""),
                "region_parse_state": str(raw.get("region_parse_state") or ""),
                "candidate_company_parse_state": str(raw.get("candidate_company_parse_state") or ""),
                "stage2_detail_capture_state": str(raw.get("stage2_detail_capture_state") or ""),
                "stage2_detail_snapshot_id_optional": str(raw.get("stage2_detail_snapshot_id_optional") or ""),
                "stage3_detail_parse_state": str(raw.get("stage3_detail_parse_state") or ""),
                "stage2_attachment_link_count": _as_int(raw.get("stage2_attachment_link_count"), 0),
                "stage2_attachment_snapshot_count": _as_int(raw.get("stage2_attachment_snapshot_count"), 0),
                "published_at_optional": str(raw.get("published_at_optional") or ""),
                "publication_window_state": str(raw.get("publication_window_state") or ""),
            }
        )
    return options


def _candidate_selection_key(
    candidate: Mapping[str, Any],
    *,
    region_rank: Mapping[str, int],
    project_type_rank: Mapping[str, int],
) -> tuple[float, int, int, int]:
    priority_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    return (
        _as_float(candidate.get("analysis_score"), 0.0),
        priority_rank.get(str(candidate.get("analysis_priority") or ""), 0),
        -project_type_rank.get(str(candidate.get("project_type") or ""), 999),
        -region_rank.get(str(candidate.get("region_code") or ""), 999),
    )


def _merge_selected_candidate(
    selected_candidate: Mapping[str, Any],
    *,
    raw_by_project_id: Mapping[str, Mapping[str, Any]],
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = dict(raw_by_project_id.get(str(selected_candidate.get("project_id") or ""), fallback))
    candidate.update(
        {
            "opportunity_candidate_id": selected_candidate.get("opportunity_candidate_id"),
            "analysis_score": selected_candidate.get("analysis_score"),
            "analysis_decision": selected_candidate.get("analysis_decision"),
            "analysis_priority": selected_candidate.get("analysis_priority"),
            "selected_for_capture_plan": selected_candidate.get("selected_for_capture_plan"),
        }
    )
    return candidate


def _candidate_options_with_closed_loop_results(
    options: list[dict[str, Any]],
    closed_loop_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_project_id = {
        str(result.get("project_id") or ""): result
        for result in closed_loop_results
        if str(result.get("project_id") or "").strip()
    }
    enriched: list[dict[str, Any]] = []
    for option in options:
        row = dict(option)
        result = by_project_id.get(str(row.get("project_id") or ""))
        if result:
            row["opportunity_id"] = result.get("opportunity_id")
            row["operator_workbench_readback_path"] = result.get("operator_workbench_readback_path")
            row["customer_artifact_candidate_path"] = result.get("customer_artifact_candidate_path")
            row["closed_loop_generated"] = bool(result.get("opportunity_id"))
            row["closed_loop_state"] = result.get("search_state")
            row["real_public_stage4_9_chain_state"] = result.get("real_public_stage4_9_chain_state")
            row["real_world_hard_defect_gate_state"] = result.get("real_world_hard_defect_gate_state")
            row["customer_sellable_evidence_ready"] = bool(result.get("customer_sellable_evidence_ready"))
        else:
            row["closed_loop_generated"] = False
        enriched.append(row)
    return enriched


def run_operator_autonomous_opportunity_search(payload: Mapping[str, Any]) -> dict[str, Any]:
    now = str(payload.get("now") or utc_now_iso())
    all_region_codes = [
        str(adapter.get("region_code") or "").strip()
        for adapter in list_region_source_adapters()
        if str(adapter.get("region_code") or "").strip()
    ]
    region_code = str(payload.get("region_code") or "CN-NATIONAL").strip() or "CN-NATIONAL"
    requested_region_codes = _as_string_list(payload.get("region_codes") or region_code, [region_code])
    if "__all__" in requested_region_codes:
        requested_region_codes = all_region_codes or ["CN-NATIONAL"]
    project_type = str(payload.get("project_type") or "construction").strip() or "construction"
    requested_project_types = _as_string_list(payload.get("project_types") or project_type, [project_type])
    if "__all__" in requested_project_types:
        requested_project_types = list(DEFAULT_AUTONOMOUS_PROJECT_TYPES)

    explicit_candidates = payload.get("notice_candidates") or payload.get("market_scan_candidates")
    explicit_candidate_list = (
        [dict(candidate) for candidate in explicit_candidates if isinstance(candidate, Mapping)]
        if isinstance(explicit_candidates, list)
        else []
    )
    offline_sample_candidates_enabled = _truthy(payload.get("allow_offline_sample_candidates")) or _truthy(
        payload.get("offline_sample_candidates_enabled")
    )
    resolved_by_region: dict[str, dict[str, Any]] = {}
    raw_candidates: list[dict[str, Any]] = []
    real_candidate_discovery: dict[str, Any] = {}
    real_candidate_stage2_capture: dict[str, Any] = {}
    for requested_region_code in requested_region_codes:
        resolved = _resolve_entry_profile_for_search(
            requested_region_code,
            requested_profile_id=str(payload.get("profile_id") or payload.get("entry_profile_id") or "").strip()
            or None,
        )
        region_adapter_for_candidate = dict(resolved["region_adapter"])
        entry_profile_for_candidate = dict(resolved["entry_profile"])
        resolved_by_region[str(region_adapter_for_candidate.get("region_code") or requested_region_code)] = {
            "region_adapter": region_adapter_for_candidate,
            "entry_profile": entry_profile_for_candidate,
        }
    if explicit_candidate_list:
        raw_candidates = []
        for candidate in explicit_candidate_list:
            row = dict(candidate)
            row.setdefault("source_candidate_mode", "EXPLICIT_CANDIDATES")
            row.setdefault("is_offline_sample_candidate", False)
            row.setdefault("sellability_evidence_state", "EXPLICIT_SOURCE_REVIEW_REQUIRED")
            raw_candidates.append(row)
    elif offline_sample_candidates_enabled:
        for region_index, requested_region_code in enumerate(requested_region_codes):
            resolved = resolved_by_region.get(str(requested_region_code)) or next(iter(resolved_by_region.values()))
            if not dict(resolved.get("entry_profile") or {}):
                continue
            region_adapter_for_candidate = dict(resolved["region_adapter"])
            entry_profile_for_candidate = dict(resolved["entry_profile"])
            for type_index, requested_project_type in enumerate(requested_project_types):
                candidate_payload = {
                    **dict(payload),
                    "region_code": str(region_adapter_for_candidate.get("region_code") or requested_region_code),
                    "project_type": requested_project_type,
                }
                if len(requested_region_codes) > 1 or len(requested_project_types) > 1:
                    candidate_payload["multi_search_candidate_index"] = f"{region_index + 1}-{type_index + 1}"
                raw_candidates.append(
                    {
                        **_search_candidate_from_payload(
                            candidate_payload,
                            region_adapter=region_adapter_for_candidate,
                            entry_profile=entry_profile_for_candidate,
                            now=now,
                        ),
                        "source_candidate_mode": "OFFLINE_SAMPLE_CANDIDATES",
                        "is_offline_sample_candidate": True,
                        "sellability_evidence_state": "SAMPLE_NOT_CUSTOMER_SELLABLE",
                        "truth_boundary": "离线样本只验证后续链路，不代表真实市场发现或可售证据。",
                    }
                )
    else:
        real_candidate_discovery = RealPublicCandidateDiscoveryService().discover(
            {
                **dict(payload),
                "region_codes": requested_region_codes,
                "project_types": requested_project_types,
                "amount_min": _as_float(_first_present(payload.get("amount_min"), payload.get("minimum_amount")), 1_000_000.0),
                "amount_max": _as_float(
                    _first_present(payload.get("amount_max"), payload.get("maximum_amount"), payload.get("amount")),
                    30_000_000.0,
                ),
                "now": now,
            },
            now=now,
        )
        raw_candidates = [
            dict(candidate)
            for candidate in list(real_candidate_discovery.get("candidates", []) or [])
            if isinstance(candidate, Mapping)
        ]
        if raw_candidates and not _truthy(payload.get("disable_real_candidate_stage2_capture")):
            real_candidate_stage2_capture = RealCandidateStage2CaptureService().capture_candidates(
                raw_candidates,
                now=now,
                detail_capture_limit=_as_int(
                    payload.get("detail_capture_limit")
                    or payload.get("real_candidate_detail_capture_limit"),
                    DEFAULT_DETAIL_CAPTURE_LIMIT,
                ),
                attachment_capture_limit=_as_int(
                    payload.get("attachment_capture_limit")
                    or payload.get("real_candidate_attachment_capture_limit"),
                    DEFAULT_ATTACHMENT_CAPTURE_LIMIT,
                ),
            )
            raw_candidates = [
                dict(candidate)
                for candidate in list(real_candidate_stage2_capture.get("enriched_candidates", []) or raw_candidates)
                if isinstance(candidate, Mapping)
            ]
    if not raw_candidates:
        discovery_attempted = bool(real_candidate_discovery)
        no_candidate_mode = REAL_PUBLIC_SOURCE_CANDIDATE_MODE if discovery_attempted else "REAL_SOURCE_REQUIRED"
        no_candidate_reason = (
            "real_public_candidate_discovery_returned_no_candidates"
            if discovery_attempted
            else "real_search_requires_source_candidates_or_explicit_offline_sample_mode"
        )
        no_candidate_message = (
            "已调用真实公开列表页候选发现器，但本次没有解析到符合地区、类型和金额区间的候选；没有生成机会。"
            if discovery_attempted
            else "默认实战搜索未读取到真实来源候选，因此没有生成机会；系统没有合成样本机会。"
        )
        primary_region_code = requested_region_codes[0] if requested_region_codes else region_code
        resolved = resolved_by_region.get(str(primary_region_code)) or _resolve_entry_profile_for_search(primary_region_code)
        region_adapter = dict(resolved["region_adapter"])
        entry_profile = dict(resolved["entry_profile"])
        result = {
            "surface_id": "operator_autonomous_opportunity_search",
            "search_state": "NO_CANDIDATES",
            "capability_state": "REAL_SOURCE_NO_CANDIDATES" if discovery_attempted else "REAL_SOURCE_ADAPTER_REQUIRED",
            "internal_only": True,
            "repository_backed_readback": True,
            "productized_owner_workbench": True,
            "region_adapter": region_adapter,
            "entry_profile": entry_profile,
            "candidate": {},
            "candidate_options": [],
            "closed_loop_results": [],
            "opportunity_ids": [],
            "search_scope": {
                "region_codes": requested_region_codes,
                "project_types": requested_project_types,
                "candidate_count": 0,
                "selected_candidate_count": 0,
                "closed_loop_generated_count": 0,
                "selection_semantics": "PASSED_FILTERS_NOT_SINGLE_PICK",
                "stage1_policy": "所有候选先进入当前时间窗口、地区、项目类型、金额区间、公告状态和证据字段过滤；通过者批量进入后续闭环，未通过者保留原因。",
                "source_candidate_mode": no_candidate_mode,
                "real_market_discovery": False,
                "real_candidate_discovery_attempted": discovery_attempted,
                "offline_sample_candidates_enabled": False,
            },
            "data_boundary": {
                "source_candidate_mode": no_candidate_mode,
                "real_market_discovery": False,
                "real_candidate_discovery_attempted": discovery_attempted,
                "offline_sample_validation": False,
                "customer_sellable_evidence_ready": False,
                "display_message": no_candidate_message,
            },
            "real_candidate_discovery": real_candidate_discovery,
            "real_candidate_stage2_capture": real_candidate_stage2_capture,
            "market_scan": {
                "scan_run_id": str(
                    payload.get("scan_run_id")
                    or build_id("MKTSCAN", "NO-CANDIDATES", region_adapter.get("region_code") or region_code)
                ),
                "input_candidate_count": 0,
                "selected_candidate_count": 0,
                "review_candidate_count": 0,
                "skipped_candidate_count": 0,
                "market_scan_candidates": [],
                "opportunity_candidates": [],
                "next_action": "WAIT_REAL_SOURCE_CANDIDATES",
            },
            "runtime_flow": {
                "surface_id": "autonomous_search_runtime_flow",
                "flow_mode": "真实列表页候选发现已执行但未命中" if discovery_attempted else "真实来源候选待接入",
                "direction": "地区机会扫描 -> 真实来源候选 -> Stage1-9",
                "source_candidate_mode": no_candidate_mode,
                "real_market_discovery": False,
                "real_candidate_discovery_attempted": discovery_attempted,
                "offline_sample_validation": False,
                "customer_sellable_evidence_ready": False,
                "data_boundary_message": no_candidate_message,
                "test_path_unblocked": False,
                "live_delivery_gates_preserved": True,
                "stage_stats": [
                    _runtime_stage(
                        stage=1,
                        name="市场扫描 / 机会发现",
                        produced_count=0,
                        effective_count=0,
                        invalid_count=0,
                        state="无候选",
                        note=no_candidate_message,
                        failure_reasons=[
                            "real_public_candidate_discovery_no_match"
                            if discovery_attempted
                            else "real_source_candidate_feed_missing"
                        ],
                        next_action="查看真实候选发现运行记录和来源失败原因，必要时补地区 profile 或列表页解析规则。"
                        if discovery_attempted
                        else "接入真实地区适配器候选列表，或打开离线样本验证后续链路。",
                    )
                ],
                "totals": {
                    "stage_count": 1,
                    "produced_count": 0,
                    "effective_count": 0,
                    "invalid_count": 0,
                },
                "logs": [
                    "默认实战搜索没有执行离线样本合成。",
                    "已执行真实公开列表页候选发现。" if discovery_attempted else "未读取到真实来源候选列表。",
                    "未解析到符合条件的真实候选，因此没有生成可售机会。"
                    if discovery_attempted
                    else "未读取到真实来源候选列表，因此没有生成可售机会。",
                ],
            },
            "reason": no_candidate_reason,
            "display_message": no_candidate_message,
            "opportunity_id": "",
            "operator_workbench_readback_path": "",
            "customer_artifact_candidate_path": "",
            "amount_range": {},
            "manual_url_picker_primary_flow": False,
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
            "customer_download_enabled": False,
            "automated_refund_enabled": False,
        }
        result["search_run_record"] = _record_autonomous_search_run(payload=payload, result=result)
        result["search_run_id"] = result["search_run_record"]["run_id"]
        return result
    primary_candidate_seed = raw_candidates[0]
    primary_resolved = resolved_by_region.get(str(primary_candidate_seed.get("region_code") or "")) or next(
        iter(resolved_by_region.values())
    )
    region_adapter = dict(primary_resolved["region_adapter"])
    entry_profile = dict(primary_resolved["entry_profile"])
    candidate = primary_candidate_seed
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
            "minimum_amount": _as_float(
                _first_present(
                    payload.get("minimum_amount"),
                    payload.get("amount_min"),
                    payload.get("minimum_amount_optional"),
                ),
                1_000_000.0,
            ),
            "maximum_amount": _as_float(
                _first_present(
                    payload.get("maximum_amount"),
                    payload.get("amount_max"),
                    payload.get("maximum_amount_optional"),
                ),
                0.0,
            ),
            "analysis_score_threshold": _as_int(payload.get("analysis_score_threshold"), 50),
            "notice_candidates": raw_candidates,
            "manual_url_picker_primary_flow": False,
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "real_provider_call_enabled": False,
        }
    )
    selected = list(market_scan.get("opportunity_candidates", []))
    raw_by_project_id = {str(item.get("project_id") or ""): item for item in raw_candidates}
    region_rank = {region: index for index, region in enumerate(requested_region_codes)}
    project_type_rank = {project_type_item: index for index, project_type_item in enumerate(requested_project_types)}
    selected_ranked = sorted(
        [dict(item) for item in selected],
        key=lambda item: _candidate_selection_key(
            item,
            region_rank=region_rank,
            project_type_rank=project_type_rank,
        ),
        reverse=True,
    )
    if not selected_ranked:
        source_candidate_mode = (
            "EXPLICIT_CANDIDATES"
            if explicit_candidate_list
            else "OFFLINE_SAMPLE_CANDIDATES"
            if offline_sample_candidates_enabled
            else REAL_PUBLIC_SOURCE_CANDIDATE_MODE
        )
        offline_sample_mode = source_candidate_mode == "OFFLINE_SAMPLE_CANDIDATES"
        review_response = {
            "surface_id": "operator_autonomous_opportunity_search",
            "search_state": "REVIEW_REQUIRED",
            "region_adapter": region_adapter,
            "entry_profile": entry_profile,
            "candidate": raw_candidates[0] if raw_candidates else {},
            "market_scan": market_scan,
            "real_candidate_discovery": real_candidate_discovery,
            "real_candidate_stage2_capture": real_candidate_stage2_capture,
            "search_scope": {
                "region_codes": requested_region_codes,
                "project_types": requested_project_types,
                "candidate_count": len(raw_candidates),
                "selected_candidate_count": len(selected),
                "closed_loop_generated_count": 0,
                "selection_semantics": "PASSED_FILTERS_NOT_SINGLE_PICK",
                "stage1_policy": "所有候选先进入当前时间窗口、地区、项目类型、金额区间、公告状态和证据字段过滤；通过者批量进入后续闭环，未通过者保留原因。",
                "stage2_detail_snapshot_count": _as_int(
                    real_candidate_stage2_capture.get("detail_snapshot_count"), 0
                ),
                "stage3_parse_success_count": _as_int(
                    real_candidate_stage2_capture.get("stage3_parse_success_count"), 0
                ),
                "stage2_attachment_snapshot_count": _as_int(
                    real_candidate_stage2_capture.get("attachment_snapshot_count"), 0
                ),
                "source_candidate_mode": source_candidate_mode,
                "real_market_discovery": source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
                "real_candidate_discovery_attempted": bool(real_candidate_discovery),
                "offline_sample_candidates_enabled": offline_sample_mode,
            },
            "data_boundary": {
                "source_candidate_mode": source_candidate_mode,
                "real_market_discovery": source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
                "real_candidate_discovery_attempted": bool(real_candidate_discovery),
                "offline_sample_validation": offline_sample_mode,
                "customer_sellable_evidence_ready": False,
                "display_message": "真实列表页候选已入库，详情页快照已尝试进入 Stage2/Stage3；当前仍未满足自动闭环阈值，需要补字段解析、附件或后续核验。"
                if source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE
                else "候选进入 Stage1 评分，但未入选闭环生成。",
            },
            "candidate_options": _candidate_option_surface(
                market_scan=market_scan,
                raw_candidates=raw_candidates,
            ),
            "selected_candidate_count": 0,
            "reason": "market_scan_did_not_select_candidate",
            "runtime_flow": {
                "surface_id": "autonomous_search_runtime_flow",
                "flow_mode": "真实候选发现后待详情页补链"
                if source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE
                else "候选待复核",
                "direction": "真实列表页候选 -> Stage1 评分 -> Stage2 详情页/附件补链",
                "source_candidate_mode": source_candidate_mode,
                "real_market_discovery": source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
                "real_candidate_discovery_attempted": bool(real_candidate_discovery),
                "offline_sample_validation": offline_sample_mode,
                "customer_sellable_evidence_ready": False,
                "data_boundary_message": "已发现真实列表页候选并尝试 Stage2 详情页快照；客户可售前还要完成真实详情字段、附件和 Stage4-9 证据回链。"
                if source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE
                else "候选未入选闭环生成。",
                "test_path_unblocked": bool(raw_candidates),
                "live_delivery_gates_preserved": True,
                "stage_stats": [
                    _runtime_stage(
                        stage=1,
                        name="市场扫描 / 机会发现",
                        produced_count=len(raw_candidates),
                        effective_count=len(selected),
                        invalid_count=max(len(raw_candidates) - len(selected), 0),
                        state="候选待复核",
                        note="真实候选已送入 Stage1，但未满足自动闭环阈值。",
                        failure_reasons=["candidate_fields_need_detail_capture"],
                        next_action="把真实详情/附件快照送入 Stage4-9，并继续补字段解析硬化。",
                    ),
                    _runtime_stage(
                        stage=2,
                        name="详情页快照 / 附件原文",
                        produced_count=_as_int(real_candidate_stage2_capture.get("detail_capture_attempted_count"), 0),
                        effective_count=_as_int(real_candidate_stage2_capture.get("detail_snapshot_count"), 0),
                        invalid_count=max(
                            _as_int(real_candidate_stage2_capture.get("detail_capture_attempted_count"), 0)
                            - _as_int(real_candidate_stage2_capture.get("detail_snapshot_count"), 0),
                            0,
                        ),
                        state="详情和附件已抓取"
                        if real_candidate_stage2_capture.get("attachment_snapshot_count")
                        else "详情已抓取"
                        if real_candidate_stage2_capture.get("detail_snapshot_count")
                        else "详情待补链",
                        note="从已发现候选的来源网址抓取同站详情页，保存可回放快照，并抓取同站公开附件原文。",
                        object_refs={
                            "attachment_link_count": real_candidate_stage2_capture.get("attachment_link_count"),
                            "attachment_snapshot_count": real_candidate_stage2_capture.get("attachment_snapshot_count"),
                            "stage3_parse_success_count": real_candidate_stage2_capture.get("stage3_parse_success_count"),
                        },
                        failure_reasons=[]
                        if real_candidate_stage2_capture.get("detail_snapshot_count")
                        else ["detail_snapshot_missing_or_degraded"],
                        next_action="把 detail/attachment snapshot 的解析字段作为 Stage4-9 正式输入。",
                    )
                ],
                "totals": {
                    "stage_count": 2,
                    "produced_count": len(raw_candidates)
                    + _as_int(real_candidate_stage2_capture.get("detail_capture_attempted_count"), 0),
                    "effective_count": len(selected)
                    + _as_int(real_candidate_stage2_capture.get("detail_snapshot_count"), 0),
                    "invalid_count": max(len(raw_candidates) - len(selected), 0),
                },
                "logs": [
                    f"真实候选发现产出 {len(raw_candidates)} 条候选。",
                    f"Stage2 详情页快照尝试 {real_candidate_stage2_capture.get('detail_capture_attempted_count', 0)} 条，成功 {real_candidate_stage2_capture.get('detail_snapshot_count', 0)} 条。",
                    "Stage1 已评分，但没有候选进入自动闭环。",
                    "没有合成样本机会；候选保留在本地候选库。",
                ],
            },
            "opportunity_id": "",
            "opportunity_ids": [],
            "amount_range": {
                "minimum": raw_candidates[0].get("amount_min") if raw_candidates else None,
                "maximum": raw_candidates[0].get("amount_max") if raw_candidates else None,
                "unit": "CNY",
            },
            "manual_url_picker_primary_flow": False,
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
            "customer_download_enabled": False,
            "automated_refund_enabled": False,
        }
        review_response["search_run_record"] = _record_autonomous_search_run(
            payload=payload,
            result=review_response,
        )
        review_response["search_run_id"] = review_response["search_run_record"]["run_id"]
        return review_response

    closed_loop_results: list[dict[str, Any]] = []
    primary_chain: dict[str, Any] = {}
    primary_acceptance: dict[str, Any] = {}
    primary_source_blueprint: dict[str, Any] = {}
    primary_region_adapter: dict[str, Any] = {}
    primary_entry_profile: dict[str, Any] = {}
    primary_candidate: dict[str, Any] = {}
    primary_real_public_stage4_9_readback: dict[str, Any] = {}
    with DatabaseSession.default().bulk_write():
        for selected_candidate in selected_ranked:
            loop_candidate = _merge_selected_candidate(
                selected_candidate,
                raw_by_project_id=raw_by_project_id,
                fallback=primary_candidate_seed,
            )
            selected_region_code = str(loop_candidate.get("region_code") or region_adapter.get("region_code") or region_code)
            selected_resolved = resolved_by_region.get(selected_region_code, primary_resolved)
            loop_region_adapter = dict(selected_resolved["region_adapter"])
            loop_entry_profile = dict(selected_resolved["entry_profile"])
            loop_source_blueprint = Stage1SourceBlueprintOrchestrator().build(
                {
                    "scan_run_id": market_scan["scan_run_id"],
                    "source_blueprint_plan_id": str(
                        payload.get("source_blueprint_plan_id")
                        or build_id("SRCBLUE", loop_candidate["project_id"], loop_candidate["region_code"])
                    ),
                    "coverage_gap_signals": list(loop_region_adapter.get("coverage_gap_signals", [])),
                    "region_code": loop_region_adapter["region_code"],
                }
            )
            loop_chain = run_internal_chain(
                _internal_chain_payload_from_search(
                    {
                        **dict(payload),
                        "region_code": loop_candidate.get("region_code"),
                        "project_type": loop_candidate.get("project_type"),
                    },
                    candidate=loop_candidate,
                    market_scan=market_scan,
                    source_blueprint=loop_source_blueprint,
                    now=now,
                )
            )
            for stage_key in ("stage6", "stage7", "stage8", "stage9"):
                persist_stage_bundle(loop_chain[stage_key])
            loop_real_public_stage4_9_readback = _build_real_public_stage4_9_readback_from_candidate(
                candidate=loop_candidate,
                chain=loop_chain,
            )
            loop_acceptance = build_real_sample_autonomous_opportunity_acceptance_surface(
                {
                    **loop_chain,
                    "market_scan": market_scan,
                    "source_blueprint_plan": loop_source_blueprint,
                }
            )
            opportunity_ref = dict(loop_acceptance.get("stage_refs", {}).get("stage7_saleable_opportunity", {}))
            loop_opportunity_id = str(opportunity_ref.get("object_id") or "")
            loop_real_public_chain_state = str(
                loop_real_public_stage4_9_readback.get("real_public_stage4_9_chain_state") or ""
            )
            loop_real_public_mode = str(loop_candidate.get("source_candidate_mode") or "") == REAL_PUBLIC_SOURCE_CANDIDATE_MODE
            loop_real_public_sellable_gate_ready = bool(
                loop_real_public_stage4_9_readback.get("real_public_sellable_gate_ready")
            )
            loop_search_state = (
                "AUTONOMOUS_SEARCH_ACCEPTED"
                if loop_acceptance.get("acceptance_state") == "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED"
                and (not loop_real_public_mode or loop_real_public_sellable_gate_ready)
                else "REVIEW_REQUIRED"
            )
            closed_loop_results.append(
                {
                    "project_id": loop_candidate.get("project_id"),
                    "project_name": loop_candidate.get("project_name"),
                    "region_code": loop_region_adapter.get("region_code"),
                    "project_type": loop_candidate.get("project_type"),
                    "opportunity_id": loop_opportunity_id,
                    "search_state": loop_search_state,
                    "analysis_score": loop_candidate.get("analysis_score"),
                    "analysis_priority": loop_candidate.get("analysis_priority"),
                    "operator_workbench_readback_path": f"/operator-console/autonomous-workbench?opportunity_id={loop_opportunity_id}"
                    if loop_opportunity_id
                    else "",
                    "customer_artifact_candidate_path": f"/customer-artifact-access-candidates/{loop_opportunity_id}"
                    if loop_opportunity_id
                    else "",
                    "real_public_stage4_9_readback": loop_real_public_stage4_9_readback,
                    "real_public_stage4_9_chain_state": loop_real_public_chain_state,
                    "real_world_hard_defect_gate_state": loop_real_public_stage4_9_readback.get(
                        "real_world_hard_defect_gate_state"
                    ),
                    "customer_sellable_evidence_ready": bool(
                        loop_real_public_stage4_9_readback.get("customer_sellable_evidence_ready")
                    ),
                }
            )
            if not primary_candidate:
                primary_candidate = loop_candidate
                primary_region_adapter = loop_region_adapter
                primary_entry_profile = loop_entry_profile
                primary_source_blueprint = loop_source_blueprint
                primary_chain = loop_chain
                primary_acceptance = loop_acceptance
                primary_real_public_stage4_9_readback = loop_real_public_stage4_9_readback
    closed_loop_generated_count = sum(1 for item in closed_loop_results if item.get("opportunity_id"))
    candidate = primary_candidate or primary_candidate_seed
    region_adapter = primary_region_adapter or region_adapter
    entry_profile = primary_entry_profile or entry_profile
    source_blueprint = primary_source_blueprint
    chain = primary_chain
    acceptance = primary_acceptance
    opportunity_id = str((closed_loop_results[0] if closed_loop_results else {}).get("opportunity_id") or "")
    source_candidate_mode = (
        "EXPLICIT_CANDIDATES"
        if explicit_candidate_list
        else "OFFLINE_SAMPLE_CANDIDATES"
        if offline_sample_candidates_enabled
        else REAL_PUBLIC_SOURCE_CANDIDATE_MODE
    )
    offline_sample_mode = source_candidate_mode == "OFFLINE_SAMPLE_CANDIDATES"
    primary_real_public_mode = source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE
    primary_real_public_chain_state = str(
        primary_real_public_stage4_9_readback.get("real_public_stage4_9_chain_state") or ""
    )
    primary_real_public_sellable_gate_ready = bool(
        primary_real_public_stage4_9_readback.get("real_public_sellable_gate_ready")
    )
    search_state = (
        "AUTONOMOUS_SEARCH_ACCEPTED"
        if closed_loop_generated_count
        and acceptance.get("acceptance_state") == "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED"
        and (not primary_real_public_mode or primary_real_public_sellable_gate_ready)
        else "REVIEW_REQUIRED"
    )
    candidate_options = _candidate_options_with_closed_loop_results(
        _candidate_option_surface(
            market_scan=market_scan,
            raw_candidates=raw_candidates,
        ),
        closed_loop_results,
    )
    capability_state = str(acceptance.get("capability_state") or "")
    if primary_real_public_mode:
        capability_state = (
            "REAL_PUBLIC_SELLABLE_EVIDENCE_READY"
            if primary_real_public_sellable_gate_ready
            else "REAL_PUBLIC_STAGE4_5_SOURCE_COVERAGE_PENDING"
            if primary_real_public_chain_state == "INTERNAL_READY"
            else "REAL_PUBLIC_STAGE4_9_REVIEW_REQUIRED"
        )
    response = {
        "surface_id": "operator_autonomous_opportunity_search",
        "search_state": search_state,
        "capability_state": capability_state,
        "internal_only": True,
        "repository_backed_readback": True,
        "productized_owner_workbench": True,
        "region_adapter": region_adapter,
        "entry_profile": entry_profile,
        "candidate": candidate,
        "candidate_options": candidate_options,
        "real_candidate_discovery": real_candidate_discovery,
        "real_candidate_stage2_capture": real_candidate_stage2_capture,
        "closed_loop_results": closed_loop_results,
        "opportunity_ids": [
            str(item.get("opportunity_id"))
            for item in closed_loop_results
            if str(item.get("opportunity_id") or "").strip()
        ],
        "search_scope": {
            "region_codes": requested_region_codes,
            "project_types": requested_project_types,
            "candidate_count": len(raw_candidates),
            "selected_candidate_count": len(selected),
            "closed_loop_generated_count": closed_loop_generated_count,
            "selection_semantics": "PASSED_FILTERS_NOT_SINGLE_PICK",
            "stage1_policy": "所有候选先进入当前时间窗口、地区、项目类型、金额区间、公告状态和证据字段过滤；通过者批量进入后续闭环，未通过者保留原因。",
            "stage2_detail_snapshot_count": _as_int(
                real_candidate_stage2_capture.get("detail_snapshot_count"), 0
            ),
            "stage3_parse_success_count": _as_int(
                real_candidate_stage2_capture.get("stage3_parse_success_count"), 0
            ),
            "stage2_attachment_snapshot_count": _as_int(
                real_candidate_stage2_capture.get("attachment_snapshot_count"), 0
            ),
            "selected_project_id": candidate.get("project_id"),
            "primary_project_id": candidate.get("project_id"),
            "primary_opportunity_id": opportunity_id,
            "source_candidate_mode": source_candidate_mode,
            "real_market_discovery": not offline_sample_mode,
            "real_candidate_discovery_attempted": bool(real_candidate_discovery),
            "offline_sample_candidates_enabled": offline_sample_mode,
            "real_public_stage4_9_chain_state": primary_real_public_chain_state,
            "real_world_hard_defect_gate_state": primary_real_public_stage4_9_readback.get(
                "real_world_hard_defect_gate_state"
            ),
        },
        "data_boundary": {
            "source_candidate_mode": source_candidate_mode,
            "real_market_discovery": not offline_sample_mode,
            "real_candidate_discovery_attempted": bool(real_candidate_discovery),
            "offline_sample_validation": offline_sample_mode,
            "customer_sellable_evidence_ready": False,
            "real_public_stage4_9_chain_state": primary_real_public_chain_state,
            "real_world_hard_defect_gate_state": primary_real_public_stage4_9_readback.get(
                "real_world_hard_defect_gate_state"
            ),
            "remaining_real_world_gaps": list(
                primary_real_public_stage4_9_readback.get("remaining_real_world_gaps", []) or []
            ),
            "regional_hard_defect_source_plan": dict(
                primary_real_public_stage4_9_readback.get("regional_hard_defect_source_plan", {}) or {}
            ),
            "display_message": (
                "离线样本只验证 Stage1-9、工作台和证据包链路；不能当作真实市场发现或客户可售证据。"
                if offline_sample_mode
                else "真实候选详情快照已被 Stage4-9 正式读回；客户可售前仍需地方住建、合同备案、竣工、项目经理变更和处罚源补强。"
                if primary_real_public_chain_state == "INTERNAL_READY"
                else "真实列表页候选已进入内部闭环；客户可交付前仍需核验真实来源详情页、附件和证据回链。"
                if source_candidate_mode == REAL_PUBLIC_SOURCE_CANDIDATE_MODE
                else "显式候选已进入内部闭环；客户可交付前仍需核验真实来源详情页、附件和证据回链。"
            ),
        },
        "market_scan": market_scan,
        "source_blueprint_plan": source_blueprint,
        "acceptance": acceptance,
        "real_public_stage4_9_readback": primary_real_public_stage4_9_readback,
        "runtime_flow": _build_autonomous_runtime_flow(
            payload=payload,
            candidate=candidate,
            market_scan=market_scan,
            source_blueprint=source_blueprint,
            chain=chain,
            acceptance=acceptance,
            real_public_stage4_9_readback=primary_real_public_stage4_9_readback,
        ),
        "opportunity_id": opportunity_id,
        "source_candidate_mode": source_candidate_mode,
        "operator_workbench_readback_path": f"/operator-console/autonomous-workbench?opportunity_id={opportunity_id}"
        if opportunity_id
        else "",
        "customer_artifact_candidate_path": f"/customer-artifact-access-candidates/{opportunity_id}"
        if opportunity_id
        else "",
        "amount_range": {
            "minimum": candidate.get("amount_min"),
            "maximum": candidate.get("amount_max"),
            "unit": "CNY",
        },
        "manual_url_picker_primary_flow": False,
        "live_execution_enabled": False,
        "real_external_fetch_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
        "automated_refund_enabled": False,
    }
    response["search_run_record"] = _record_autonomous_search_run(
        payload=payload,
        result=response,
    )
    response["search_run_id"] = response["search_run_record"]["run_id"]
    return response


def _autonomous_search_work_item_id() -> str:
    return "operator-autonomous-opportunity-search-runs"


def _autonomous_search_clear_work_item_id() -> str:
    return "operator-autonomous-opportunity-search-run-clears"


def _record_autonomous_search_run(
    *,
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    requested_at = build_persisted_at()
    region_adapter = dict(result.get("region_adapter", {}) or {})
    entry_profile = dict(result.get("entry_profile", {}) or {})
    candidate = dict(result.get("candidate", {}) or {})
    market_scan = dict(result.get("market_scan", {}) or {})
    source_blueprint = dict(result.get("source_blueprint_plan", {}) or {})
    acceptance = dict(result.get("acceptance", {}) or {})
    runtime_flow = dict(result.get("runtime_flow", {}) or {})
    search_scope = dict(result.get("search_scope", {}) or {})
    candidate_options = list(result.get("candidate_options", []) or [])
    data_boundary = dict(result.get("data_boundary", {}) or {})
    opportunity_id = str(result.get("opportunity_id") or "").strip()
    opportunity_ids = [
        str(item)
        for item in list(result.get("opportunity_ids", []) or [])
        if str(item).strip()
    ]
    closed_loop_results = list(result.get("closed_loop_results", []) or [])
    search_state = str(result.get("search_state") or "UNKNOWN")
    action_state = search_state
    run_id = (
        f"AUTONOMOUS-SEARCH-RUN-{opportunity_id or region_adapter.get('region_code') or 'SEARCH'}-{requested_at}"
        .replace(":", "")
        .replace("+", "")
    )
    object_refs = {
        "region_code": str(region_adapter.get("region_code") or payload.get("region_code") or ""),
        "region_name": str(region_adapter.get("region_name") or ""),
        "adapter_state": str(region_adapter.get("adapter_state") or ""),
        "entry_profile_id": str(entry_profile.get("profile_id") or ""),
        "query": str(payload.get("query") or payload.get("project_keyword") or payload.get("keyword") or ""),
        "project_type": str(candidate.get("project_type") or payload.get("project_type") or ""),
        "project_type_label": str(candidate.get("project_type_label") or _project_type_label(str(candidate.get("project_type") or ""))),
        "amount": str(payload.get("amount") or payload.get("minimum_amount") or ""),
        "amount_min": str(payload.get("amount_min") or payload.get("minimum_amount") or ""),
        "amount_max": str(payload.get("amount_max") or payload.get("maximum_amount") or payload.get("amount") or ""),
        "amount_range_json": _json_text(result.get("amount_range") or {}),
        "opportunity_id": opportunity_id,
        "opportunity_ids_json": _json_text(opportunity_ids),
        "closed_loop_results_json": _json_text(closed_loop_results),
        "project_id": str(candidate.get("project_id") or ""),
        "project_name": str(candidate.get("project_name") or ""),
        "source_url": str(candidate.get("source_url") or ""),
        "source_profile_id": str(candidate.get("source_profile_id") or entry_profile.get("profile_id") or ""),
        "source_site_name": str(candidate.get("source_site_name") or entry_profile.get("site_name") or ""),
        "analysis_score": str(candidate.get("analysis_score") or ""),
        "analysis_decision": str(candidate.get("analysis_decision") or ""),
        "analysis_priority": str(candidate.get("analysis_priority") or ""),
        "search_state": search_state,
        "source_candidate_mode": str(
            search_scope.get("source_candidate_mode") or data_boundary.get("source_candidate_mode") or ""
        ),
        "real_market_discovery": str(bool(data_boundary.get("real_market_discovery"))).lower(),
        "offline_sample_validation": str(bool(data_boundary.get("offline_sample_validation"))).lower(),
        "customer_sellable_evidence_ready": str(bool(data_boundary.get("customer_sellable_evidence_ready"))).lower(),
        "display_message": str(data_boundary.get("display_message") or result.get("display_message") or ""),
        "acceptance_state": str(acceptance.get("acceptance_state") or ""),
        "market_scan_run_id": str(market_scan.get("scan_run_id") or ""),
        "source_blueprint_plan_id": str(source_blueprint.get("source_blueprint_plan_id") or ""),
        "operator_workbench_readback_path": str(result.get("operator_workbench_readback_path") or ""),
        "customer_artifact_candidate_path": str(result.get("customer_artifact_candidate_path") or ""),
        "customer_artifact_portal_path": f"/customer-artifact-portal/{opportunity_id}" if opportunity_id else "",
        "search_scope_json": _json_text(search_scope),
        "candidate_options_json": _json_text(candidate_options),
        "runtime_flow_json": _json_text(runtime_flow),
        "data_boundary_json": _json_text(data_boundary),
    }
    action = PersistedOperatorAction(
        action_event_id=run_id,
        work_item_id=_autonomous_search_work_item_id(),
        stage_scope=1,
        action_id="operator_autonomous_opportunity_search",
        button_flow_id="owner_console_autonomous_opportunity_search",
        action_state=action_state,
        resulting_assignment_lifecycle_state=None,
        requested_by_role="single_operator",
        requested_by="卡卡罗特",
        assigned_owner_role="single_operator",
        assigned_owner="卡卡罗特",
        reviewer_role="single_operator",
        reviewer="卡卡罗特",
        reason="region_adapter_to_autonomous_opportunity_closed_loop",
        object_refs=object_refs,
        trace_refs={
            "operator_console_route": "/operator-console/autonomous-opportunity-search",
            "run_list_path": "/operator-console/autonomous-search-runs",
            "workbench_readback_path": object_refs["operator_workbench_readback_path"],
        },
        audit_refs={
            "run_audit_ref": run_id,
            "internal_only": "true",
            "live_execution_enabled": "false",
            "real_provider_call_enabled": "false",
        },
        requested_at=requested_at,
        completed_at=requested_at,
    )
    OperatorActionRepository().append(action)
    return _autonomous_search_action_payload(action)


def _autonomous_search_action_payload(action: PersistedOperatorAction) -> dict[str, Any]:
    refs = dict(action.object_refs)
    amount_range = _json_value(refs.get("amount_range_json"), {})
    search_scope = _json_value(refs.get("search_scope_json"), {})
    candidate_options = _json_value(refs.get("candidate_options_json"), [])
    opportunity_ids = _json_value(refs.get("opportunity_ids_json"), [])
    closed_loop_results = _json_value(refs.get("closed_loop_results_json"), [])
    runtime_flow = _json_value(refs.get("runtime_flow_json"), {})
    data_boundary = _json_value(refs.get("data_boundary_json"), {})
    return {
        "run_id": action.action_event_id,
        "search_state": refs.get("search_state") or action.action_state,
        "region_code": refs.get("region_code"),
        "region_name": refs.get("region_name"),
        "adapter_state": refs.get("adapter_state"),
        "entry_profile_id": refs.get("entry_profile_id"),
        "query": refs.get("query"),
        "project_type": refs.get("project_type"),
        "project_type_label": refs.get("project_type_label"),
        "amount": refs.get("amount"),
        "amount_min": refs.get("amount_min"),
        "amount_max": refs.get("amount_max"),
        "amount_range": amount_range,
        "opportunity_id": refs.get("opportunity_id"),
        "opportunity_ids": opportunity_ids,
        "closed_loop_results": closed_loop_results,
        "project_id": refs.get("project_id"),
        "project_name": refs.get("project_name"),
        "source_url": refs.get("source_url"),
        "source_profile_id": refs.get("source_profile_id"),
        "source_site_name": refs.get("source_site_name"),
        "analysis_score": refs.get("analysis_score"),
        "analysis_decision": refs.get("analysis_decision"),
        "analysis_priority": refs.get("analysis_priority"),
        "source_candidate_mode": refs.get("source_candidate_mode"),
        "real_market_discovery": refs.get("real_market_discovery") == "true",
        "offline_sample_validation": refs.get("offline_sample_validation") == "true",
        "customer_sellable_evidence_ready": refs.get("customer_sellable_evidence_ready") == "true",
        "display_message": refs.get("display_message"),
        "acceptance_state": refs.get("acceptance_state"),
        "market_scan_run_id": refs.get("market_scan_run_id"),
        "source_blueprint_plan_id": refs.get("source_blueprint_plan_id"),
        "operator_workbench_readback_path": refs.get("operator_workbench_readback_path"),
        "customer_artifact_candidate_path": refs.get("customer_artifact_candidate_path"),
        "customer_artifact_portal_path": refs.get("customer_artifact_portal_path"),
        "search_scope": search_scope,
        "candidate_options": candidate_options,
        "runtime_flow": runtime_flow,
        "data_boundary": data_boundary,
        "requested_at": action.requested_at,
        "completed_at": action.completed_at,
        "repository_backed": True,
        "internal_only": True,
        "manual_url_picker_primary_flow": False,
        "live_execution_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def list_operator_autonomous_search_runs(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    actions = OperatorActionRepository().list(work_item_id=_autonomous_search_work_item_id())
    raw_runs = [_autonomous_search_action_payload(action) for action in actions]
    raw_runs.sort(key=lambda row: str(row.get("requested_at") or ""), reverse=True)
    latest_by_opportunity: dict[str, dict[str, Any]] = {}
    for row in raw_runs:
        dedupe_key = str(row.get("opportunity_id") or row.get("run_id") or "").strip()
        if not dedupe_key or dedupe_key in latest_by_opportunity:
            continue
        latest_by_opportunity[dedupe_key] = row
    runs = list(latest_by_opportunity.values())
    status_counts: dict[str, int] = {}
    for row in runs:
        status = str(row.get("search_state") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    latest_opportunity_id = str(runs[0].get("opportunity_id") or "") if runs else ""
    latest_runtime_flow = dict(runs[0].get("runtime_flow", {}) or {}) if runs else {}
    latest_requested_at = str(runs[0].get("requested_at") or "") if runs else ""
    latest_completed_at = str(runs[0].get("completed_at") or "") if runs else ""
    return {
        "surface_id": "operator_autonomous_search_runs",
        "internal_only": True,
        "repository_backed_readback": True,
        "autonomous_search_run_list": True,
        "data_source": "OperatorActionRepository",
        "storage_scope": "local_repository_operator_action_log",
        "retention_state": "PERSISTED_UNTIL_EXPLICIT_OPERATOR_CLEAR",
        "auto_clear_enabled": False,
        "explicit_operator_clear_required": True,
        "clear_endpoint": "/operator-console/autonomous-search-runs/clear",
        "latest_requested_at": latest_requested_at,
        "latest_completed_at": latest_completed_at,
        "last_updated_at": latest_completed_at or latest_requested_at,
        "run_count": len(runs),
        "raw_run_count": len(raw_runs),
        "duplicate_collapsed_count": max(len(raw_runs) - len(runs), 0),
        "latest_opportunity_id": latest_opportunity_id,
        "latest_customer_artifact_portal_path": f"/customer-artifact-portal/{latest_opportunity_id}"
        if latest_opportunity_id
        else "",
        "latest_runtime_flow": latest_runtime_flow,
        "status_counts": status_counts,
        "runs": runs,
        "raw_json_required": False,
        "manual_url_picker_primary_flow": False,
        "live_execution_enabled": False,
        "real_external_fetch_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
    }


def clear_operator_autonomous_search_runs(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    del payload
    repo = OperatorActionRepository()
    work_item_id = _autonomous_search_work_item_id()
    clear_audit_work_item_id = _autonomous_search_clear_work_item_id()
    requested_at = build_persisted_at()
    existing_count = len(repo.list(work_item_id=work_item_id))
    cleared_count = repo.clear(work_item_id=work_item_id)
    clear_event_id = f"AUTONOMOUS-SEARCH-RUN-CLEAR-{requested_at}".replace(":", "").replace("+", "")
    audit_action = PersistedOperatorAction(
        action_event_id=clear_event_id,
        work_item_id=clear_audit_work_item_id,
        stage_scope=1,
        action_id="operator_clear_autonomous_search_runs",
        button_flow_id="owner_console_clear_autonomous_search_runs",
        action_state="CLEARED",
        resulting_assignment_lifecycle_state=None,
        requested_by_role="single_operator",
        requested_by="卡卡罗特",
        assigned_owner_role="single_operator",
        assigned_owner="卡卡罗特",
        reviewer_role="single_operator",
        reviewer="卡卡罗特",
        reason="explicit_owner_clear_local_test_autonomous_search_records",
        object_refs={
            "cleared_work_item_id": work_item_id,
            "clear_scope": "local_test_autonomous_search_runs_only",
            "existing_count_before_clear": str(existing_count),
            "cleared_count": str(cleared_count),
            "data_source": "OperatorActionRepository",
            "affects_opportunity_records": "false",
            "affects_customer_artifacts": "false",
            "affects_external_systems": "false",
        },
        trace_refs={
            "operator_console_route": "/operator-console/autonomous-search-runs/clear",
            "run_list_path": "/operator-console/autonomous-search-runs",
        },
        audit_refs={
            "clear_audit_ref": clear_event_id,
            "internal_only": "true",
            "explicit_operator_action": "true",
            "live_execution_enabled": "false",
            "real_provider_call_enabled": "false",
        },
        requested_at=requested_at,
        completed_at=requested_at,
    )
    repo.append(audit_action)
    remaining_count = len(repo.list(work_item_id=work_item_id))
    return {
        "surface_id": "operator_autonomous_search_runs_clear",
        "internal_only": True,
        "repository_backed_readback": True,
        "explicit_operator_action": True,
        "autonomous_search_run_clear": True,
        "data_source": "OperatorActionRepository",
        "clear_scope": "local_test_autonomous_search_runs_only",
        "cleared_work_item_id": work_item_id,
        "clear_audit_work_item_id": clear_audit_work_item_id,
        "clear_audit_event_id": clear_event_id,
        "existing_count_before_clear": existing_count,
        "cleared_count": cleared_count,
        "remaining_run_count": remaining_count,
        "retention_state": "PERSISTED_UNTIL_EXPLICIT_OPERATOR_CLEAR",
        "affects_opportunity_records": False,
        "affects_customer_artifacts": False,
        "affects_external_systems": False,
        "live_execution_enabled": False,
        "real_external_fetch_enabled": False,
        "real_provider_call_enabled": False,
        "external_release_enabled": False,
        "customer_download_enabled": False,
        "automated_refund_enabled": False,
        "requested_at": requested_at,
        "completed_at": requested_at,
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
    latest_queue_items = _latest_queue_item_summaries()
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
        "latest_queue_items": latest_queue_items,
        "latest_queue_item": (latest_queue_items or [{}])[0],
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
        "operationId": "previewOperatorRealWorldSellability",
        "method": "GET",
        "path": "/operator-console/real-world-sellability",
        "handler": preview_operator_real_world_sellability,
        "real_world_sellability_readiness": True,
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
        "operationId": "listOperatorRealCandidates",
        "method": "GET",
        "path": "/operator-console/real-candidates",
        "handler": list_operator_real_candidates,
        "real_candidate_catalog": True,
        "repository_backed_readback": True,
        "raw_json_required": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "listOperatorRealCandidateDiscoveryRuns",
        "method": "GET",
        "path": "/operator-console/real-candidate-discovery-runs",
        "handler": list_operator_real_candidate_discovery_runs,
        "real_candidate_discovery_run_list": True,
        "repository_backed_readback": True,
        "raw_json_required": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "listOperatorRealCandidateStage2Captures",
        "method": "GET",
        "path": "/operator-console/real-candidate-stage2-captures",
        "handler": list_operator_real_candidate_stage2_captures,
        "real_candidate_stage2_capture_run_list": True,
        "repository_backed_readback": True,
        "raw_json_required": False,
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
        "operationId": "listOperatorAutonomousSearchRuns",
        "method": "GET",
        "path": "/operator-console/autonomous-search-runs",
        "handler": list_operator_autonomous_search_runs,
        "autonomous_search_run_list": True,
        "repository_backed_readback": True,
        "raw_json_required": False,
        **OPERATOR_CUSTOMER_ACCESS_ROUTE_METADATA,
    },
    {
        "operationId": "clearOperatorAutonomousSearchRuns",
        "method": "POST",
        "path": "/operator-console/autonomous-search-runs/clear",
        "handler": clear_operator_autonomous_search_runs,
        "autonomous_search_run_clear": True,
        "repository_backed_readback": True,
        "explicit_operator_action": True,
        "raw_json_required": False,
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
    "clear_operator_autonomous_search_runs",
    "create_operator_task",
    "import_operator_project",
    "list_operator_autonomous_search_runs",
    "list_owner_real_public_source_task_runs",
    "list_operator_real_candidate_discovery_runs",
    "list_operator_real_candidate_stage2_captures",
    "list_operator_real_candidates",
    "list_operator_region_adapters",
    "list_real_public_source_profiles",
    "preview_autonomous_operator_workbench",
    "preview_customer_artifact_access_candidate",
    "preview_go_live_readiness",
    "preview_operator_customer_access_readiness",
    "preview_operator_real_world_sellability",
    "preview_real_sample_autonomous_opportunity_acceptance",
    "preview_scheduler_status",
    "read_owner_real_public_source_capture",
    "read_operator_task",
    "register_operator_customer_access_routes",
    "run_operator_autonomous_opportunity_search",
    "run_owner_real_public_source_capture",
]
