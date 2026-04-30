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
)
from stage1_tasking.source_blueprint import Stage1SourceBlueprintOrchestrator
from stage2_ingestion import (
    REAL_PUBLIC_ATTACHMENT_PROFILES,
    REAL_PUBLIC_ENTRY_PROFILES,
)
from stage2_ingestion.service import Stage2Service
from storage.db import DatabaseSession, PersistedOperatorAction, build_persisted_at
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
    go_live = preview_go_live_readiness({})
    runs = list(search_runs.get("runs", []) or [])
    latest_run = dict(runs[0]) if runs else {}
    accepted_run_count = sum(
        1
        for run in runs
        if str(run.get("search_state") or "") == "AUTONOMOUS_SEARCH_ACCEPTED"
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
            status="PASS" if accepted_run_count else "PARTIAL",
            current_state=(
                f"已读回 {len(runs)} 个搜索商机，{accepted_run_count} 个形成闭环。"
                if runs
                else "尚未在当前本地仓库读回搜索商机。"
            ),
            evidence=[
                "/operator-console/autonomous-search-runs",
                "/operator-console/autonomous-opportunity-search",
            ],
            gaps=[] if accepted_run_count else ["需要至少运行一次实战搜索形成可售机会读回。"],
            next_actions=[
                "从实战搜索选择地区、类型和金额区间运行一次闭环。",
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
                else ["部分地区仍依赖全国兜底或待补本地公开源入口。"]
            ),
            next_actions=["补商业重点地区的本地公开源入口和失败诊断。"],
        ),
        _sellability_lane(
            lane_id="evidence_quality",
            title="证据质量与来源回链",
            status="PASS" if latest_opportunity_id else "PARTIAL",
            current_state=(
                "最新机会已可进入证据包预览并回到公开来源验证。"
                if latest_opportunity_id
                else "证据包能力已接入，但当前没有最新机会读回。"
            ),
            evidence=[
                "/customer-artifact-portal/{opportunity_id}",
                "/customer-artifact-portal-download/{opportunity_id}",
            ],
            gaps=[] if latest_opportunity_id else ["需要一条最新机会来绑定证据包预览和下载。"],
            next_actions=["用最新搜索机会打开证据包预览，核对来源网址、字段策略和下载审计。"],
        ),
        _sellability_lane(
            lane_id="commercial_hook",
            title="商业钩子与买家匹配",
            status="PASS" if latest_opportunity_id else "PARTIAL",
            current_state=(
                "机会工作台已展示商业钩子、买家排序、证据强度和下一步动作。"
                if latest_opportunity_id
                else "商业钩子工作台已接入，等待最新机会数据。"
            ),
            evidence=["/operator-console/autonomous-workbench"],
            gaps=[] if latest_opportunity_id else ["需要最新机会来展示真实钩子读回。"],
            next_actions=["把可讲卖点、暂不外泄字段和报价草稿继续压到一屏可卖性摘要。"],
        ),
        _sellability_lane(
            lane_id="leadpack_delivery_candidate",
            title="线索包交付候选",
            status="PASS" if latest_opportunity_id else "PARTIAL",
            current_state=(
                "内部证据包预览和下载可用；客户真实下载仍不自动开放。"
                if latest_opportunity_id
                else "内部证据包预览可用，等待机会绑定后验收。"
            ),
            evidence=["/customer-artifact-access-candidates/{opportunity_id}"],
            gaps=[
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
        and accepted_run_count
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
        "ua11_satisfied": True,
        "live_execution_enabled": False,
        "external_release_enabled": False,
        "public_software_release": False,
        "real_provider_call_enabled": False,
        "automated_refund_enabled": False,
        "sellability_summary": {
            "sellability_level": "内部实战可判断，真实成交交付待接入",
            "owner_decision": (
                "可以用来内部实战筛选机会、查看证据包和判断销售价值；"
                "暂不能宣称真实客户触达、真实支付和真实交付已闭合。"
            ),
            "latest_opportunity_id": latest_opportunity_id,
            "accepted_run_count": accepted_run_count,
            "observed_stage_count": observed_stage_count,
            "external_sellable_now": external_sellable_now,
            "lane_counts": counts,
        },
        "boundary": {
            "internal_search_and_evidence_package_review": bool(latest_opportunity_id or region_count),
            "leadpack_delivery_candidate_visible": bool(latest_opportunity_id),
            "real_customer_touch_enabled": real_touch_ready,
            "real_payment_enabled": bool(controlled.get("real_payment_enabled", False)),
            "real_delivery_enabled": bool(controlled.get("real_delivery_enabled", False)),
            "automated_refund_enabled": False,
        },
        "lanes": lanes,
        "remaining_real_world_closures": [
            "阶段1-9细粒度运行读回",
            "重点地区本地适配器覆盖",
            "真实触达 provider sandbox 与审批审计",
            "真实支付/交付 provider sandbox 与回写治理",
            "显式数据保留与清空控制",
        ],
        "source_readbacks": {
            "region_adapter_count": region_count,
            "latest_search_run_id": latest_run.get("run_id"),
            "go_live_enabled": bool(go_live.get("go_live_enabled", False)),
            "remaining_blockers": list(go_live.get("remaining_blockers", [])),
        },
    }


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
    amount_min = _as_float(payload.get("amount_min") or payload.get("minimum_amount"), 1_000_000.0)
    amount_max = _as_float(
        payload.get("amount_max") or payload.get("maximum_amount") or payload.get("amount"),
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
    state: str = "已完成",
    note: str = "",
) -> dict[str, Any]:
    effective = produced_count if effective_count is None else effective_count
    return {
        "stage": stage,
        "name": name,
        "state": state,
        "produced_count": max(produced_count, 0),
        "effective_count": max(effective, 0),
        "invalid_count": max(invalid_count, 0),
        "note": note,
    }


def _build_autonomous_runtime_flow(
    *,
    payload: Mapping[str, Any],
    candidate: Mapping[str, Any],
    market_scan: Mapping[str, Any],
    source_blueprint: Mapping[str, Any],
    chain: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    capture_plan = dict(source_blueprint.get("stage2_capture_plan", {}) or {})
    capture_steps = list(capture_plan.get("capture_steps", []) or [])
    input_candidates = _as_int(market_scan.get("input_candidate_count"), 1)
    selected_candidates = _as_int(market_scan.get("selected_candidate_count"), 0)
    review_candidates = _as_int(market_scan.get("review_candidate_count"), 0)
    skipped_candidates = _as_int(market_scan.get("skipped_candidate_count"), 0)
    stage_stats = [
        _runtime_stage(
            stage=1,
            name="市场扫描 / 机会发现",
            produced_count=input_candidates,
            effective_count=selected_candidates,
            invalid_count=review_candidates + skipped_candidates,
            note="按地区、项目类型、金额区间和竞争信号筛选机会。",
        ),
        _runtime_stage(
            stage=2,
            name="来源蓝图 / 采集计划",
            produced_count=len(capture_steps),
            effective_count=len(capture_steps),
            note="自动选择公开入口和采集步骤；当前不执行真实外部抓取。",
        ),
        _runtime_stage(
            stage=3,
            name="解析规范化",
            produced_count=_bundle_record_count(chain.get("stage3")),
            note="把公开材料解析成统一项目字段。",
        ),
        _runtime_stage(
            stage=4,
            name="证据风险核验",
            produced_count=_bundle_record_count(chain.get("stage4")),
            note="生成公开核验、硬伤风险和复核项。",
        ),
        _runtime_stage(
            stage=5,
            name="规则证据门",
            produced_count=_bundle_record_count(chain.get("stage5")),
            note="把证据链、规则命中和产品化条件合并。",
        ),
        _runtime_stage(
            stage=6,
            name="产品包",
            produced_count=_bundle_record_count(chain.get("stage6")),
            note="形成可售判断、报告记录和内部产品包。",
        ),
        _runtime_stage(
            stage=7,
            name="商业钩子 / 买家匹配",
            produced_count=_bundle_record_count(chain.get("stage7")),
            note="生成商业钩子、买家排序和销售下一步。",
        ),
        _runtime_stage(
            stage=8,
            name="触达计划",
            produced_count=_bundle_record_count(chain.get("stage8")),
            state="已生成草稿",
            note="内部生成触达计划；真实触达需单独审批和审计。",
        ),
        _runtime_stage(
            stage=9,
            name="支付交付",
            produced_count=_bundle_record_count(chain.get("stage9")),
            state="已生成交付候选",
            note="内部生成交付候选；真实下载、支付、退款不在本次自动执行。",
        ),
    ]
    total_produced = sum(row["produced_count"] for row in stage_stats)
    total_effective = sum(row["effective_count"] for row in stage_stats)
    total_invalid = sum(row["invalid_count"] for row in stage_stats)
    return {
        "surface_id": "autonomous_search_runtime_flow",
        "flow_mode": "内部实战测试闭环",
        "direction": "地区机会扫描 -> 来源蓝图 -> 阶段1-9内部链路 -> 工作台 -> 客户材料候选",
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
            f"阶段1 选择 {selected_candidates}/{input_candidates} 个候选机会。",
            f"阶段2 生成 {len(capture_steps)} 个采集计划步骤。",
            "阶段3-9已在内部链路生成结构化对象、商业钩子和交付候选。",
            "真实对外交付门禁保留；内部测试链路可完整跑通。",
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
                "amount_min": amount_min,
                "amount_max": amount_max,
                "analysis_score": row.get("analysis_score"),
                "analysis_decision": str(row.get("analysis_decision") or ""),
                "analysis_priority": str(row.get("analysis_priority") or ""),
                "selected_for_capture_plan": bool(row.get("selected_for_capture_plan")),
                "source_url": str(raw.get("source_url") or source_refs.get("source_url") or ""),
                "source_profile_id": str(raw.get("source_profile_id") or ""),
                "source_site_name": str(raw.get("source_site_name") or ""),
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

    resolved_by_region: dict[str, dict[str, Any]] = {}
    raw_candidates: list[dict[str, Any]] = []
    for region_index, requested_region_code in enumerate(requested_region_codes):
        resolved = resolve_entry_profile_for_region(
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
        for type_index, requested_project_type in enumerate(requested_project_types):
            candidate_payload = {
                **dict(payload),
                "region_code": str(region_adapter_for_candidate.get("region_code") or requested_region_code),
                "project_type": requested_project_type,
            }
            if len(requested_region_codes) > 1 or len(requested_project_types) > 1:
                candidate_payload["multi_search_candidate_index"] = f"{region_index + 1}-{type_index + 1}"
            raw_candidates.append(
                _search_candidate_from_payload(
                    candidate_payload,
                    region_adapter=region_adapter_for_candidate,
                    entry_profile=entry_profile_for_candidate,
                    now=now,
                )
            )
    if not raw_candidates:
        resolved = resolve_entry_profile_for_region(region_code)
        region_adapter_fallback = dict(resolved["region_adapter"])
        entry_profile_fallback = dict(resolved["entry_profile"])
        raw_candidates.append(
            _search_candidate_from_payload(
                payload,
                region_adapter=region_adapter_fallback,
                entry_profile=entry_profile_fallback,
                now=now,
            )
        )
        resolved_by_region[str(region_adapter_fallback.get("region_code") or region_code)] = {
            "region_adapter": region_adapter_fallback,
            "entry_profile": entry_profile_fallback,
        }
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
            "minimum_amount": _as_float(payload.get("minimum_amount"), 1_000_000.0),
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
    selected_candidate = (
        dict(
            max(
                selected,
                key=lambda item: _candidate_selection_key(
                    item,
                    region_rank=region_rank,
                    project_type_rank=project_type_rank,
                ),
            )
        )
        if selected
        else {}
    )
    if selected_candidate:
        selected_raw_candidate = dict(
            raw_by_project_id.get(str(selected_candidate.get("project_id") or ""), primary_candidate_seed)
        )
        selected_raw_candidate.update(
            {
                "opportunity_candidate_id": selected_candidate.get("opportunity_candidate_id"),
                "analysis_score": selected_candidate.get("analysis_score"),
                "analysis_decision": selected_candidate.get("analysis_decision"),
                "analysis_priority": selected_candidate.get("analysis_priority"),
                "selected_for_capture_plan": selected_candidate.get("selected_for_capture_plan"),
            }
        )
        candidate = selected_raw_candidate
    selected_region_code = str(candidate.get("region_code") or region_adapter.get("region_code") or region_code)
    selected_resolved = resolved_by_region.get(selected_region_code, primary_resolved)
    region_adapter = dict(selected_resolved["region_adapter"])
    entry_profile = dict(selected_resolved["entry_profile"])
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
            "search_scope": {
                "region_codes": requested_region_codes,
                "project_types": requested_project_types,
                "candidate_count": len(raw_candidates),
                "selected_candidate_count": len(selected),
                "closed_loop_generated_count": 0,
            },
            "candidate_options": _candidate_option_surface(
                market_scan=market_scan,
                raw_candidates=raw_candidates,
            ),
            "selected_candidate_count": 0,
            "reason": "market_scan_did_not_select_candidate",
            "manual_url_picker_primary_flow": False,
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
        }

    chain_payload = _internal_chain_payload_from_search(
        {
            **dict(payload),
            "region_code": candidate.get("region_code"),
            "project_type": candidate.get("project_type"),
        },
        candidate=selected_candidate,
        market_scan=market_scan,
        source_blueprint=source_blueprint,
        now=now,
    )
    chain = run_internal_chain(chain_payload)
    with DatabaseSession.default().bulk_write():
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
        response = {
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
            "candidate_options": _candidate_option_surface(
                market_scan=market_scan,
                raw_candidates=raw_candidates,
            ),
            "search_scope": {
                "region_codes": requested_region_codes,
                "project_types": requested_project_types,
                "candidate_count": len(raw_candidates),
                "selected_candidate_count": len(selected),
                "closed_loop_generated_count": 1,
                "selected_project_id": candidate.get("project_id"),
            },
            "market_scan": market_scan,
            "source_blueprint_plan": source_blueprint,
            "acceptance": acceptance,
            "runtime_flow": _build_autonomous_runtime_flow(
                payload=payload,
                candidate=candidate,
                market_scan=market_scan,
                source_blueprint=source_blueprint,
                chain=chain,
                acceptance=acceptance,
            ),
            "opportunity_id": opportunity_id,
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
    opportunity_id = str(result.get("opportunity_id") or "").strip()
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
        "project_id": str(candidate.get("project_id") or ""),
        "project_name": str(candidate.get("project_name") or ""),
        "source_url": str(candidate.get("source_url") or ""),
        "source_profile_id": str(candidate.get("source_profile_id") or entry_profile.get("profile_id") or ""),
        "source_site_name": str(candidate.get("source_site_name") or entry_profile.get("site_name") or ""),
        "analysis_score": str(candidate.get("analysis_score") or ""),
        "analysis_decision": str(candidate.get("analysis_decision") or ""),
        "analysis_priority": str(candidate.get("analysis_priority") or ""),
        "search_state": search_state,
        "acceptance_state": str(acceptance.get("acceptance_state") or ""),
        "market_scan_run_id": str(market_scan.get("scan_run_id") or ""),
        "source_blueprint_plan_id": str(source_blueprint.get("source_blueprint_plan_id") or ""),
        "operator_workbench_readback_path": str(result.get("operator_workbench_readback_path") or ""),
        "customer_artifact_candidate_path": str(result.get("customer_artifact_candidate_path") or ""),
        "customer_artifact_portal_path": f"/customer-artifact-portal/{opportunity_id}" if opportunity_id else "",
        "search_scope_json": _json_text(search_scope),
        "candidate_options_json": _json_text(candidate_options),
        "runtime_flow_json": _json_text(runtime_flow),
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
    runtime_flow = _json_value(refs.get("runtime_flow_json"), {})
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
        "project_id": refs.get("project_id"),
        "project_name": refs.get("project_name"),
        "source_url": refs.get("source_url"),
        "source_profile_id": refs.get("source_profile_id"),
        "source_site_name": refs.get("source_site_name"),
        "analysis_score": refs.get("analysis_score"),
        "analysis_decision": refs.get("analysis_decision"),
        "analysis_priority": refs.get("analysis_priority"),
        "acceptance_state": refs.get("acceptance_state"),
        "market_scan_run_id": refs.get("market_scan_run_id"),
        "source_blueprint_plan_id": refs.get("source_blueprint_plan_id"),
        "operator_workbench_readback_path": refs.get("operator_workbench_readback_path"),
        "customer_artifact_candidate_path": refs.get("customer_artifact_candidate_path"),
        "customer_artifact_portal_path": refs.get("customer_artifact_portal_path"),
        "search_scope": search_scope,
        "candidate_options": candidate_options,
        "runtime_flow": runtime_flow,
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
    return {
        "surface_id": "operator_autonomous_search_runs",
        "internal_only": True,
        "repository_backed_readback": True,
        "autonomous_search_run_list": True,
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
    "list_operator_autonomous_search_runs",
    "list_owner_real_public_source_task_runs",
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
