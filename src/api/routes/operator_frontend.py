# Stage: api_operator_frontend
# Consumes formal objects: operator/customer access API readback only
# Dependent handoff: N/A
# Dependent schema/contracts: existing operator_customer_access route surfaces

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Mapping

from fastapi.responses import HTMLResponse, Response

from api.projections import build_customer_artifact_access_candidate_surface, register_route_table
from storage.repositories.operator_action_repo import OperatorActionRepository


OPERATOR_FRONTEND_ROUTE_METADATA = {
    "surface_mode": "internal-ui",
    "internal_only": True,
    "readiness_only": False,
    "projection_only": False,
    "live_execution_enabled": False,
    "external_release_enabled": False,
    "public_software_release": False,
    "provider_call_enabled": False,
    "real_provider_call_enabled": False,
    "stage8_real_execution_enabled": False,
    "stage9_real_payment_delivery_refund_enabled": False,
    "automated_refund_enabled": False,
    "owner_operable_frontend": True,
    "productized_owner_workbench": True,
    "stage1_to_stage9_operations_board": True,
    "business_closure_dashboard": True,
    "customer_artifact_portal": True,
    "customer_artifact_empty_state": True,
    "download_auth_required": True,
    "field_allowlist_masking_required": True,
    "approval_audit_readback_required": True,
}

AUTONOMOUS_SEARCH_WORK_ITEM_ID = "operator-autonomous-opportunity-search-runs"
USER_ACCEPTANCE_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "ui"
    / "operator_user_acceptance_contract.json"
)
USER_ACCEPTANCE_GAP_MATRIX_PATH = (
    Path(__file__).resolve().parents[3]
    / "control"
    / "operator_user_acceptance_gap_matrix.json"
)


def _load_user_acceptance_contract() -> dict[str, Any]:
    return json.loads(USER_ACCEPTANCE_CONTRACT_PATH.read_text(encoding="utf-8"))


def _load_user_acceptance_gap_matrix() -> dict[str, Any]:
    return json.loads(USER_ACCEPTANCE_GAP_MATRIX_PATH.read_text(encoding="utf-8"))


def _json_or_default(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _search_run_metadata_for_opportunity(opportunity_id: str) -> dict[str, Any]:
    if not opportunity_id:
        return {}
    actions = OperatorActionRepository().list(work_item_id=AUTONOMOUS_SEARCH_WORK_ITEM_ID)
    actions.sort(key=lambda item: str(item.requested_at or ""), reverse=True)
    for action in actions:
        refs = dict(action.object_refs)
        if str(refs.get("opportunity_id") or "") != opportunity_id:
            continue
        candidate_options = _json_or_default(refs.get("candidate_options_json"), [])
        search_scope = _json_or_default(refs.get("search_scope_json"), {})
        data_boundary = _json_or_default(refs.get("data_boundary_json"), {})
        selected_project_id = str(refs.get("project_id") or "")
        selected_candidate = next(
            (
                dict(candidate)
                for candidate in candidate_options
                if str(candidate.get("project_id") or "") == selected_project_id
            ),
            {},
        )
        source_url = str(selected_candidate.get("source_url") or refs.get("source_url") or "")
        source_site_name = str(selected_candidate.get("source_site_name") or refs.get("source_site_name") or "")
        source_profile_id = str(
            selected_candidate.get("source_profile_id")
            or refs.get("source_profile_id")
            or refs.get("entry_profile_id")
            or ""
        )
        return {
            "opportunity_id": opportunity_id,
            "search_run_id": action.action_event_id,
            "query": refs.get("query"),
            "project_id": refs.get("project_id"),
            "project_name": refs.get("project_name"),
            "region_code": refs.get("region_code"),
            "region_name": refs.get("region_name"),
            "project_type": refs.get("project_type"),
            "project_type_label": refs.get("project_type_label"),
            "source_url": source_url,
            "source_site_name": source_site_name,
            "source_profile_id": source_profile_id,
            "analysis_score": refs.get("analysis_score"),
            "analysis_decision": refs.get("analysis_decision"),
            "analysis_priority": refs.get("analysis_priority"),
            "amount_range": _json_or_default(refs.get("amount_range_json"), {}),
            "search_scope": search_scope,
            "source_candidate_mode": str(
                refs.get("source_candidate_mode")
                or search_scope.get("source_candidate_mode")
                or data_boundary.get("source_candidate_mode")
                or ""
            ),
            "real_market_discovery": str(refs.get("real_market_discovery") or "").lower() == "true",
            "offline_sample_validation": str(refs.get("offline_sample_validation") or "").lower() == "true",
            "customer_sellable_evidence_ready": str(
                refs.get("customer_sellable_evidence_ready") or ""
            ).lower()
            == "true",
            "data_boundary": data_boundary,
            "candidate_options": candidate_options,
            "selected_candidate": selected_candidate,
            "requested_at": action.requested_at,
        }
    return {}


def _source_verification_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_url": str(metadata.get("source_url") or ""),
        "source_site_name": str(metadata.get("source_site_name") or ""),
        "source_profile_id": str(metadata.get("source_profile_id") or ""),
        "project_name": str(metadata.get("project_name") or ""),
        "region_name": str(metadata.get("region_name") or metadata.get("region_code") or ""),
        "project_type_label": str(metadata.get("project_type_label") or metadata.get("project_type") or ""),
        "verification_hint": "公开来源验证：打开公开来源网址，核对项目名称、候选/中标信息、金额区间和公告阶段。",
    }


def _localized_data_boundary(surface: Mapping[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    metadata_boundary = dict(metadata.get("data_boundary", {}) or {})
    source_mode = str(
        metadata.get("source_candidate_mode")
        or dict(metadata.get("search_scope", {}) or {}).get("source_candidate_mode")
        or metadata_boundary.get("source_candidate_mode")
        or ""
    )
    project_name = str(metadata.get("project_name") or "")
    offline_sample = bool(metadata.get("offline_sample_validation")) or source_mode == "OFFLINE_SAMPLE_CANDIDATES"
    if not offline_sample and "机会搜索样本" in project_name:
        offline_sample = True
    has_source_url = bool(str(metadata.get("source_url") or "").strip())
    if offline_sample:
        mode_label = "离线样本验证"
        sellable_label = "不可作为客户可售证据，只能验证 Stage1-9、工作台和证据包链路。"
    elif source_mode == "REAL_SOURCE_REQUIRED":
        mode_label = "真实来源候选待接入"
        sellable_label = "尚未形成真实候选，不能生成客户证据包。"
    elif source_mode == "EXPLICIT_CANDIDATES":
        mode_label = "显式候选闭环"
        sellable_label = "可用于内部闭环验证；客户交付前仍需核验真实详情页、附件和回链。"
    else:
        mode_label = "来源模式待读取"
        sellable_label = "客户交付前需要完成真实来源核验。"
    return {
        "数据模式": mode_label,
        "来源候选模式": source_mode or "UNKNOWN",
        "是否离线样本": offline_sample,
        "是否真实市场发现": bool(metadata.get("real_market_discovery")) and not offline_sample,
        "客户可交付判断": sellable_label,
        "来源网址精度": "已提供公开来源网址，仍需核对是否为项目详情页/附件页。"
        if has_source_url
        else "缺少公开来源网址，不能作为客户证据。",
        "证据包用途": "内部运营验收，不会真实发送客户。",
        "客户可见导出已开放": bool(surface.get("customer_visible_export_enabled")),
        "真实外发已开放": bool(surface.get("external_release_enabled")),
    }


def _customer_artifact_surface_with_search_context(payload: dict[str, Any]) -> dict[str, Any]:
    surface = build_customer_artifact_access_candidate_surface(payload)
    opportunity_id = str(surface.get("opportunity_id") or payload.get("opportunity_id") or "")
    metadata = _search_run_metadata_for_opportunity(opportunity_id)
    surface["search_run_metadata"] = metadata
    surface["source_verification"] = _source_verification_from_metadata(metadata)
    surface["data_boundary"] = _localized_data_boundary(surface, metadata)
    return surface


def _safe_filename_token(value: str) -> str:
    token = "".join(char if char.isascii() and (char.isalnum() or char in "-_") else "-" for char in value)
    token = "-".join(part for part in token.split("-") if part)
    return token or "opportunity"


OWNER_VISIBLE_LABELS = {
    "ACTIVE": "启用",
    "ALLOW": "允许",
    "APPLIED_TO_DRAFT": "已加到草稿",
    "APPROVED": "已通过",
    "AUDITABLE": "可审计",
    "BUYER_FIT_SCORECARD": "买家匹配评分卡",
    "COMPREHENSIVE_SCORE": "综合评分",
    "CONSTRUCTION": "房建工程",
    "CUSTOMER": "客户",
    "DEAL": "交易",
    "DOC": "文档",
    "DRY_RUN": "试运行",
    "EMAIL": "邮件",
    "GET": "读取",
    "GOVERNMENT": "政府/采购主管",
    "GRADE_B": "B级机会",
    "HTML_PAGE": "网页",
    "INTERNAL": "内部",
    "INTERNAL DRAFT": "内部草稿",
    "INTERNAL DRAFT - NOT CUSTOMER RELEASED": "内部草稿，未发客户",
    "INTERNAL_PROJECT_IMPORT": "内部项目导入",
    "JSON": "结构化数据",
    "LIST": "列表",
    "LIST_TO_DETAIL": "列表到详情",
    "MANUAL": "人工处理",
    "MASKING_REQUIRED": "需要脱敏",
    "NATIONAL": "全国",
    "NO_RESPONSE": "暂无响应",
    "OFFLINE_FIXTURE": "离线样本",
    "OPEN_TENDER": "公开招标",
    "ORDERED": "已排序",
    "ORG_EMAIL": "机构邮箱",
    "OWNER": "运营方",
    "PAGE_DRAFT_ONLY": "仅页面草稿",
    "POST": "提交",
    "PROCUREMENT_NOTICE": "采购公告",
    "PROVINCIAL": "省级",
    "PUBLIC_OFFICIAL_SOURCE": "公开官方来源",
    "PUBLIC_ROLE_CONTACT": "公开角色联系人",
    "PUBLIC_SITE": "公开网站",
    "QUALIFIED": "合格机会",
    "REACHABLE": "可触达",
    "READY": "已就绪",
    "READBACK_READY": "读回就绪",
    "REASONABLE": "合理",
    "RELEASED": "已发布",
    "REPLAY_READY": "可回放",
    "ROOT": "根对象",
    "SAMPLE": "样本",
    "SANDBOX_CANDIDATE_READY": "测试候选已就绪",
    "SANDBOX_DRY_RUN_READBACK": "沙箱试运行读回",
    "SANITIZED_OFFLINE_INTERNAL": "脱敏离线内部",
    "SEARCH": "搜索",
    "SKU": "产品档位",
    "SLICE": "切片",
    "T0_CORE": "核心覆盖",
    "TASK": "任务",
    "TRACE_PRESENT": "痕迹已记录",
    "UNASSIGNED": "未分配",
    "VALID": "有效",
    "WINDOW_ACTIONABLE": "窗口可行动",
    "NO_CANDIDATES": "未发现候选",
    "REAL_SOURCE_REQUIRED": "需要真实来源候选",
    "OFFLINE_SAMPLE_CANDIDATES": "离线样本候选",
    "EXPLICIT_CANDIDATES": "显式候选",
    "SAMPLE_NOT_CUSTOMER_SELLABLE": "样本不可客户交付",
    "EXPLICIT_SOURCE_REVIEW_REQUIRED": "显式候选需真实回链复核",
    "allowed_projection": "允许展示摘要",
    "allowlist_enforced": "字段白名单已执行",
    "artifact_manifest_id": "清单编号",
    "artifact_version_hash": "版本哈希",
    "auth_required": "需要授权",
    "buyer_fit_summary": "买家匹配摘要",
    "crm_quote_workbench": "报价工作台",
    "crm_quote_workbench_snapshot": "报价工作台快照",
    "customer_download_enabled": "客户自助下载已开放",
    "download_enabled": "下载已开放",
    "evidence_pack_id": "证据包编号",
    "field_allowlist_masking": "字段白名单与脱敏",
    "internal_blackbox_fields_exposed": "内部黑箱字段已暴露",
    "internal_summary_only": "仅内部摘要",
    "internal_trace_summary": "内部痕迹摘要",
    "item_id": "证据项编号",
    "manifest_state": "清单状态",
    "masked_projection": "脱敏展示",
    "masking_policy": "脱敏策略",
    "masking_required": "需要脱敏",
    "offer_recommendation": "报价建议",
    "offer_recommendation_snapshot": "报价建议快照",
    "package_id": "交付包编号",
    "package_manifest": "证据包清单",
    "page_draft": "页面草稿",
    "page_draft_id": "页面草稿编号",
    "project_name": "项目名称",
    "region_name": "地区",
    "saleable_opportunity": "可售机会",
    "saleable_opportunity_snapshot": "可售机会快照",
    "source_object": "来源对象",
    "source_profile_id": "来源配置编号",
    "source_refs": "来源引用",
    "source_site_name": "公开来源名称",
    "source_url": "公开来源网址",
    "stage7.saleable_opportunity": "阶段7可售机会",
    "stage7.offer_recommendation": "阶段7报价建议",
    "stage7.buyer_fit": "阶段7买家匹配",
    "stage7_actor_profiles": "阶段7联系人画像",
    "stage7_resolution_trace": "阶段7决策痕迹",
    "stage7_resolution_trace_snapshot": "阶段7决策痕迹摘要",
    "summary_only": "仅摘要",
    "verification_hint": "验证口径",
    "watermark": "水印",
    "watermark_text": "水印文字",
}

OWNER_BLOCKED_REASON_LABELS = {
    "stage7_artifact_readback_missing": "阶段7证据包尚未生成",
    "stage8_stage9_delivery_context_not_required_for_access_candidate_readback": "阶段8/9真实交付上下文未进入内部预览；不影响内部证据包检查",
    "customer_visible_export_enabled=false": "客户自助页面未开放；当前按内部预览和邮件交付路线处理",
    "client_page_release_enabled=false": "客户自助页面未发布；当前不是客户工作台交付",
    "external_release_enabled=false": "真实外发未接入；内部测试不触达外部",
    "external_delivery_enabled=false": "真实交付未接入；内部测试不触达外部",
    "direct_export_enabled=false": "直接导出未接入；当前使用内部证据包下载",
    "approval_audit_and_implementation_decision_required_before_live": "真实外发前需要审批、审计和执行决策",
    "customer_account_access_control_required": "客户账号不作为当前内部测试前置",
    "download_auth_required": "客户自助下载不是当前交付路径；未来成交付款后邮件发送",
    "approval_audit_required_before_customer_download": "客户真实下载前需要审批和审计",
    "public_software_release_not_approved": "不交付客户软件平台；内部预览不受影响",
}


def _owner_visible_label(value: Any) -> str:
    text = str(value or "")
    return OWNER_VISIBLE_LABELS.get(text, text)


def _owner_visible_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            _owner_visible_label(key): _owner_visible_value(item)
            for key, item in value.items()
            if item not in (None, "")
        }
    if isinstance(value, list):
        return [_owner_visible_value(item) for item in value if item not in (None, "")]
    if isinstance(value, str):
        return _owner_visible_label(value)
    return value


def _owner_visible_blocked_reasons(reasons: list[Any]) -> list[str]:
    labels: list[str] = []
    for reason in reasons:
        text = str(reason or "").strip()
        if not text:
            continue
        labels.append(OWNER_BLOCKED_REASON_LABELS.get(text, text.replace("_", " ")))
    return labels


def _localized_source_verification(source_verification: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "公开来源网址": str(source_verification.get("source_url") or ""),
        "公开来源名称": str(source_verification.get("source_site_name") or ""),
        "来源配置编号": str(source_verification.get("source_profile_id") or ""),
        "项目名称": str(source_verification.get("project_name") or ""),
        "地区": str(source_verification.get("region_name") or ""),
        "项目类型": str(source_verification.get("project_type_label") or ""),
        "验证口径": str(source_verification.get("verification_hint") or ""),
    }


def _localized_field_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "字段白名单已执行": bool(policy.get("allowlist_enforced", True)),
        "脱敏必需": bool(policy.get("masking_required", True)),
        "内部黑箱字段已隐藏": not bool(policy.get("internal_blackbox_fields_exposed", False)),
        "允许字段": _owner_visible_value(policy.get("allowed_fields") or policy.get("allowlist") or []),
        "屏蔽字段": _owner_visible_value(policy.get("blocked_fields") or policy.get("blocked") or []),
    }


def _localized_download_auth(download_auth: Mapping[str, Any]) -> dict[str, Any]:
    customer_download_enabled = bool(download_auth.get("customer_download_enabled") or download_auth.get("download_enabled"))
    return {
        "当前下载用途": "内部运营预览，不会真实发送客户",
        "客户自助下载已开放": customer_download_enabled,
        "客户下载需要授权": bool(download_auth.get("auth_required", True)),
        "真实客户下载已执行": False,
        "授权状态说明": "当前只允许运营方下载内部预览包；客户未来通过成交付款后的邮件证据包接收。",
    }


def _localized_evidence_item(
    item: Mapping[str, Any],
    source_verification: Mapping[str, Any],
    data_boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    boundary = dict(data_boundary or {})
    return {
        "证据项编号": _owner_visible_label(item.get("item_id") or ""),
        "证据类型": _owner_visible_label(item.get("item_id") or item.get("source_object") or ""),
        "线索类型": _owner_visible_label(item.get("source_object") or ""),
        "证据说明": "内部证据包条目；用于核对项目事实、报价判断、买家匹配或阶段7决策痕迹。",
        "客户交付判断": str(boundary.get("客户可交付判断") or "客户交付前需要完成真实来源核验。"),
        "来源对象编号": str(item.get("source_id") or ""),
        "清单状态": _owner_visible_label(item.get("manifest_state") or item.get("status") or ""),
        "脱敏策略": _owner_visible_label(item.get("masking_policy") or ""),
        "来源引用": _owner_visible_value(item.get("source_refs") or []),
        "公开来源网址": str(item.get("source_url") or source_verification.get("source_url") or ""),
        "公开来源名称": str(item.get("source_site_name") or source_verification.get("source_site_name") or ""),
        "来源配置编号": str(item.get("source_profile_id") or source_verification.get("source_profile_id") or ""),
    }


def _internal_evidence_package_download_payload(payload: dict[str, Any]) -> dict[str, Any]:
    surface = _customer_artifact_surface_with_search_context(payload)
    formal = dict(surface.get("source_formal_client_export_page_layer_readiness", {}) or {})
    artifact = dict(surface.get("customer_artifact_readback", {}) or {})
    manifest = dict(formal.get("package_manifest", {}) or {})
    source_verification = dict(surface.get("source_verification", {}) or {})
    data_boundary = dict(surface.get("data_boundary", {}) or {})
    evidence_items = []
    for item in list(manifest.get("evidence_items", []) or []):
        row = dict(item)
        row.setdefault("source_url", source_verification.get("source_url"))
        row.setdefault("source_site_name", source_verification.get("source_site_name"))
        row.setdefault("source_profile_id", source_verification.get("source_profile_id"))
        evidence_items.append(_localized_evidence_item(row, source_verification, data_boundary))
    field_policy = dict(surface.get("field_allowlist_masking", {}) or {})
    download_auth = dict(surface.get("download_auth", {}) or {})
    return {
        "说明": "内部证据包预览文件；用于运营方验收，不会真实发送给客户。",
        "未来交付方式": "成交付款后由系统通过邮件发送证据包。",
        "商机编号": str(payload.get("opportunity_id") or ""),
        "数据真实性边界": data_boundary,
        "公开来源验证": _localized_source_verification(source_verification),
        "证据包": {
            "证据包编号": artifact.get("evidence_pack_id"),
            "交付包编号": artifact.get("package_id"),
            "清单编号": artifact.get("artifact_manifest_id"),
            "版本哈希": artifact.get("artifact_version_hash"),
            "水印": _owner_visible_value(dict(artifact.get("watermark", {}) or {})),
            "页面草稿": _owner_visible_value(dict(formal.get("page_draft", {}) or {})),
        },
        "拟邮件发送包": {
            "邮件主题": f"证据包交付 - {payload.get('opportunity_id') or ''}",
            "附件": [
                artifact.get("evidence_pack_id"),
                artifact.get("artifact_manifest_id"),
                dict(formal.get("page_draft", {}) or {}).get("page_draft_id"),
            ],
            "真实邮件已发送": False,
            "真实邮件服务商已接入": False,
        },
        "证据项清单": evidence_items,
        "字段策略": _localized_field_policy(field_policy),
        "模拟下载审计": _localized_download_auth(download_auth),
        "读回摘要": {
            "候选状态": "可内部预览" if not surface.get("empty_state") else "暂无证据包读回",
            "客户可见导出已开放": bool(surface.get("customer_visible_export_enabled")),
            "真实外发已开放": bool(surface.get("external_release_enabled")),
            "待接或受控原因": _owner_visible_blocked_reasons(list(surface.get("blocked_reasons", []) or [])),
        },
    }

CONTROLLED_SAMPLE_PAYLOAD = {
    "now": "2026-04-14T00:00:00Z",
    "task_id": "TASK-OWNER-SAMPLE-001",
    "project_id": "PROJ-OWNER-SAMPLE-001",
    "project_root_id": "ROOT-OWNER-SAMPLE-001",
    "project_name": "操作台受控样本项目",
    "region_code": "CN-BJ",
    "region_scope": "NATIONAL",
    "source_family": "PROCUREMENT_NOTICE",
    "platform_level": "NATIONAL",
    "coverage_tier": "T0_CORE",
    "default_route": "LIST_TO_DETAIL",
    "review_lane": "STANDARD",
    "carrier_type": "HTML_PAGE",
    "announcement_url": "https://example.invalid/notice/owner-sample-001",
    "source_document_ref": "DOC-OWNER-SAMPLE-001",
    "source_slice_ref": "SLICE-OWNER-SAMPLE-001",
    "normalization_rule_id": "NR-OWNER-SAMPLE-001",
    "parser_confidence_score": 0.92,
    "procurement_regime": "OPEN_TENDER",
    "candidate_order_mode": "ORDERED",
    "award_determination_mode": "COMPREHENSIVE_SCORE",
    "channel_family": "ORG_EMAIL",
    "contact_channel": "EMAIL",
    "contact_validity_status": "VALID",
    "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
    "reasonable_expectation_status": "REASONABLE",
    "channel_policy_status": "ALLOW",
    "public_contact_source": "PUBLIC_SITE",
    "source_auditability_state": "AUDITABLE",
    "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
    "frequency_policy_state": "ALLOW",
    "opt_out_state": "ACTIVE",
    "quiet_hours_policy_state": "ALLOW",
    "response_status": "NO_RESPONSE",
    "crm_owner_state": "UNASSIGNED",
    "run_mode": "DRY_RUN",
    "automation_level": "MANUAL",
    "approval_state": "NOT_REQUIRED",
    "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
    "source_mode": "OFFLINE_FIXTURE",
    "flags": {"report_approved": True},
}


def _page(title: str, body: str, script: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5e6b78;
      --line: #d8dee6;
      --panel: #ffffff;
      --soft: #f4f7fb;
      --nav: #10202d;
      --accent: #0f7b68;
      --warn: #b54708;
      --danger: #b42318;
      --ok: #157347;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, "Microsoft YaHei", sans-serif;
      background: var(--soft);
      color: var(--ink);
    }}
    html {{
      scroll-behavior: smooth;
    }}
    .layout {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
    }}
    .operator-shell {{
      height: 100vh;
      overflow: hidden;
    }}
    nav {{
      background: var(--nav);
      color: #eef5f2;
      padding: 24px 18px;
    }}
    .operator-shell nav {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}
    .layout:not(.operator-shell) nav {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}
    nav h1 {{
      margin: 0 0 18px;
      font-size: 22px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    nav a,
    nav button.nav-link {{
      display: block;
      width: 100%;
      color: #d7e6e1;
      text-decoration: none;
      padding: 10px 0;
      border-bottom: 1px solid rgba(255,255,255,.12);
      font-size: 14px;
      text-align: left;
      background: transparent;
      border-left: 0;
      border-right: 0;
      border-top: 0;
      border-radius: 0;
      cursor: pointer;
      margin: 0;
    }}
    nav a:hover,
    nav button.nav-link:hover,
    nav button.nav-link.active {{
      color: #fff;
      background: rgba(255,255,255,.08);
    }}
    main {{ padding: 28px; }}
    .operator-shell main {{
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .layout:not(.operator-shell) main {{
      height: 100vh;
      overflow: auto;
      scroll-padding-top: 18px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 20px;
    }}
    .operator-shell .topbar {{
      flex: 0 0 auto;
      margin-bottom: 0;
    }}
    h2 {{ margin: 0; font-size: 26px; letter-spacing: 0; }}
    .status {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 10px 12px;
      color: var(--muted);
      max-width: 520px;
    }}
    .status.warn {{
      border-color: #f2c078;
      background: #fff8ec;
      color: #80510a;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .workspace {{
      flex: 1 1 auto;
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
      gap: 16px;
    }}
    .panelStack {{
      min-height: 0;
      overflow: auto;
      padding-right: 4px;
    }}
    .view-panel {{
      display: none;
    }}
    .view-panel.active {{
      display: block;
    }}
    .view-panel > section,
    .view-panel > .view-grid {{
      margin-bottom: 16px;
    }}
    .view-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      min-width: 0;
      scroll-margin-top: 18px;
    }}
    section h3 {{
      margin: 0 0 12px;
      font-size: 17px;
      letter-spacing: 0;
    }}
    label {{
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin: 10px 0 6px;
    }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      font: inherit;
      background: #fff;
    }}
    textarea {{ min-height: 112px; resize: vertical; }}
    button {{
      border: 0;
      border-radius: 6px;
      padding: 10px 12px;
      font: inherit;
      color: #fff;
      background: var(--accent);
      cursor: pointer;
      margin-top: 10px;
    }}
    nav button.nav-link {{
      color: #d7e6e1;
      background: transparent;
      border-bottom: 1px solid rgba(255,255,255,.12);
      border-radius: 0;
      padding: 10px 0;
      margin-top: 0;
      font-weight: 400;
    }}
    nav button.nav-link:hover,
    nav button.nav-link.active {{
      color: #fff;
      background: rgba(255,255,255,.08);
    }}
    button.secondary {{ background: #31546b; }}
    button:focus, input:focus, textarea:focus, a:focus {{
      outline: 3px solid rgba(15,123,104,.24);
      outline-offset: 2px;
    }}
    .rail {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 14px 0;
    }}
    .operator-shell .rail {{
      flex: 0 0 auto;
      margin: 0;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
      min-height: 74px;
    }}
    .metric strong {{ display: block; font-size: 18px; margin-bottom: 4px; }}
    .metric span {{ color: var(--muted); font-size: 13px; }}
    .pill {{
      display: inline-block;
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 12px;
      margin: 2px 4px 2px 0;
      background: #e9f5f1;
      color: var(--accent);
    }}
    .pill.warn {{ background: #fff2df; color: var(--warn); }}
    .pill.danger {{ background: #fdecec; color: var(--danger); }}
    .stage-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .stage-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
      min-height: 108px;
    }}
    .stage-card strong {{
      display: block;
      margin-bottom: 6px;
      font-size: 15px;
    }}
    .stage-card p {{
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }}
    .muted-text {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }}
    .compact-card-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      max-height: 420px;
      overflow: auto;
      padding-right: 4px;
    }}
    .compact-card-grid .stage-card {{
      min-height: 96px;
    }}
    .workflow {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .workflow div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .field-row {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .field-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 8px 0 4px;
    }}
    .field-actions button {{
      margin-top: 0;
      padding: 7px 10px;
      font-size: 13px;
    }}
    .opportunity-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }}
    .opportunity-actions a,
    .opportunity-actions button {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 9px;
      font-size: 13px;
      text-decoration: none;
      color: var(--accent);
      background: #fff;
      cursor: pointer;
      margin-top: 0;
    }}
    .opportunity-actions a:hover,
    .opportunity-actions button:hover {{
      background: #edf8f4;
    }}
    select[multiple] {{
      min-height: 132px;
    }}
    .select-fallback {{
      display: none;
    }}
    .check-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }}
    .check-option {{
      display: flex;
      gap: 8px;
      align-items: flex-start;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fbfcfe;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.35;
    }}
    .check-option input {{
      width: auto;
      margin-top: 2px;
    }}
    .detail-table {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin: 10px 0;
    }}
    .detail-row {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fbfcfe;
      min-width: 0;
    }}
    .detail-row strong {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .detail-row span {{
      word-break: break-word;
      font-size: 14px;
    }}
    .timeline {{
      display: grid;
      gap: 8px;
    }}
    .timeline div {{
      border-left: 3px solid var(--accent);
      background: #fbfcfe;
      padding: 8px 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .empty-state {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      padding: 16px;
      color: var(--muted);
    }}
    pre {{
      overflow: auto;
      max-height: 260px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #0f1720;
      color: #d7e6e1;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .summary-list {{
      display: grid;
      gap: 8px;
      color: var(--ink);
    }}
    .summary-row {{
      display: grid;
      grid-template-columns: 144px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      font-size: 14px;
    }}
    .summary-row strong {{
      color: var(--muted);
      font-weight: 600;
    }}
    .summary-row span {{
      word-break: break-word;
    }}
    .resultPane {{
      min-height: 0;
      display: flex;
      flex-direction: column;
    }}
    .resultPane pre {{
      flex: 1 1 auto;
      min-height: 0;
      max-height: none;
      margin: 0;
    }}
    .wide {{ grid-column: 1 / -1; }}
    .controlled_opening_requirement {{
      border-left: 4px solid var(--danger);
      background: #fff7f6;
      color: #5c1f1a;
    }}
    @media (max-width: 840px) {{
      .layout {{ grid-template-columns: 1fr; }}
      nav {{ position: static; }}
      .operator-shell {{ height: auto; overflow: visible; }}
      .operator-shell nav {{ height: auto; }}
      .layout:not(.operator-shell) nav {{ height: auto; }}
      .operator-shell main {{ height: auto; overflow: visible; display: block; }}
      .workspace {{ display: block; }}
      .panelStack {{ overflow: visible; padding-right: 0; }}
      .resultPane pre {{ max-height: 260px; }}
      .grid, .rail, .stage-grid, .workflow, .compact-card-grid, .check-grid, .detail-table {{ grid-template-columns: 1fr; }}
      .view-grid {{ grid-template-columns: 1fr; }}
      .field-row {{ grid-template-columns: 1fr; }}
      main {{ padding: 18px; }}
      .topbar {{ display: block; }}
    }}
  </style>
</head>
<body>
  {body}
  <script>
  {script}
  </script>
</body>
</html>""",
        media_type="text/html; charset=utf-8",
    )


def render_operator_console(payload: Any) -> HTMLResponse:
    del payload
    controlled_sample_payload = escape(
        json.dumps(CONTROLLED_SAMPLE_PAYLOAD, ensure_ascii=False, indent=2),
        quote=False,
    )
    body = """
<div class="layout operator-shell">
  <nav aria-label="运营操作台导航">
    <h1>AX9S 运营操作台</h1>
    <button class="nav-link active" type="button" data-view="overview" aria-current="page">阶段1-9 运营总览</button>
    <button class="nav-link" type="button" data-view="search" aria-current="false">实战搜索</button>
    <button class="nav-link" type="button" data-view="autonomousWorkbench" aria-current="false">机会工作台</button>
    <button class="nav-link" type="button" data-view="run" aria-current="false">采集运行</button>
    <button class="nav-link" type="button" data-view="systemRelease" aria-current="false">系统与放行</button>
    <button class="nav-link" type="button" data-view="acceptanceContract" aria-current="false">验收契约</button>
    <a class="external" id="customerPortalLink" href="/customer-artifact-portal/OPP-HAPPY-001">证据包预览 · 样例</a>
  </nav>
  <main>
    <div class="topbar">
      <div>
        <h2>证据包运营操作台</h2>
        <p>真实公开市场机会发现 + 证据包商业化运营系统：默认目标是真实来源候选进料、证据核验和可售线索包；内部/样本只作为回归模式，客户不使用工作台。</p>
      </div>
      <div class="status" id="summary">正在读取启动状态和就绪状态...</div>
    </div>
    <div class="rail" aria-label="readiness summary">
      <div class="metric"><strong id="capability">--</strong><span>操作权限状态</span></div>
      <div class="metric"><strong id="provider">--</strong><span>服务商模式</span></div>
      <div class="metric"><strong id="scheduler">--</strong><span>队列就绪状态</span></div>
    </div>
    <div class="workspace">
      <div class="panelStack" aria-live="polite">
        <div class="view-panel active" id="overview" data-view-panel="overview">
          <section>
            <h3>阶段1-9 运营总览</h3>
            <p class="muted-text" id="stageDirection">系统方向：市场扫描 -> 来源蓝图 -> 阶段1-9内部链路 -> 工作台 -> 证据包预览。运行实战搜索后显示每阶段产出。</p>
            <div class="status" id="stageRunBoundary">运行边界：等待实战搜索或任务运行。</div>
            <div class="rail" id="stageMetrics">
              <div class="metric"><strong>9</strong><span>阶段数</span></div>
              <div class="metric"><strong>0</strong><span>产出对象</span></div>
              <div class="metric"><strong>0</strong><span>有效数据</span></div>
            </div>
            <div class="stage-grid" id="stageBoard">
              <div class="stage-card"><strong>阶段1 调度</strong><p>任务、窗口、队列、暂停恢复。</p><span class="pill">内部执行</span></div>
              <div class="stage-card"><strong>阶段2 公开源</strong><p>公开源适配器、快照、哈希、来源链。</p><span class="pill">仅公开来源</span></div>
              <div class="stage-card"><strong>阶段3 解析</strong><p>网页、文档、文字识别、附件字段候选与复核。</p><span class="pill">待核验</span></div>
              <div class="stage-card"><strong>阶段4 核验</strong><p>公开核验、证据等级、失败关闭。</p><span class="pill">公开核验</span></div>
              <div class="stage-card"><strong>阶段5 规则</strong><p>规则目录、金标用例、证据绑定。</p><span class="pill">规则工厂</span></div>
              <div class="stage-card"><strong>阶段6 产品包</strong><p>异议价值、可售判断、交付就绪。</p><span class="pill">产品包</span></div>
              <div class="stage-card"><strong>阶段7 销售</strong><p>真实竞争者、买家匹配、客户关系和报价。</p><span class="pill">销售闭环</span></div>
              <div class="stage-card"><strong>阶段8 触达</strong><p>模板、频控、退订、服务商执行读回。</p><span class="pill warn">门禁控制</span></div>
              <div class="stage-card"><strong>阶段9 支付交付</strong><p>订单、收款、交付、对账、人工退款异常。</p><span class="pill warn">无自动退款</span></div>
            </div>
            <h3>阶段对象流与失败分类</h3>
            <p class="muted-text">这里读取最新运行的阶段对象、输入输出、有效/无效分类和下一步动作，不再只是静态流程说明。</p>
            <div class="compact-card-grid" id="stageObjectFlow"></div>
          </section>
          <section>
            <h3>当前任务运行总览</h3>
            <p class="muted-text" id="taskRunOverviewNarrative">发起任务后这里显示队列状态、任务编号、项目编号、入口状态和下一步动作。</p>
            <div class="rail" id="taskRunMetrics">
              <div class="metric"><strong>--</strong><span>队列任务</span></div>
              <div class="metric"><strong>--</strong><span>排队中</span></div>
              <div class="metric"><strong>--</strong><span>最新任务</span></div>
            </div>
            <div id="taskRunOverviewList" class="empty-state">暂无任务运行记录；在“采集运行”里创建内部任务后显示。</div>
          </section>
          <section>
            <h3>Stage6 批次复核状态</h3>
            <p class="muted-text" id="stage6ReviewLoopNarrative">正在读取 Stage6 批次状态：项目到了哪里、是否还能续跑、为什么停、下一步做什么。</p>
            <div class="rail" id="stage6ReviewLoopMetrics">
              <div class="metric"><strong>--</strong><span>项目数</span></div>
              <div class="metric"><strong>--</strong><span>可续跑</span></div>
              <div class="metric"><strong>--</strong><span>人工停机</span></div>
            </div>
            <div id="stage6ReviewLoopProjectList" class="compact-card-grid"></div>
          </section>
          <section>
            <h3>真实可卖性判断</h3>
            <p class="muted-text" id="sellabilityDecision">正在读取当前能卖到哪一步、还差哪些接入。</p>
            <div class="rail" id="sellabilityMetrics">
              <div class="metric"><strong>--</strong><span>可卖性等级</span></div>
              <div class="metric"><strong>--</strong><span>最新商机</span></div>
              <div class="metric"><strong>--</strong><span>真实外部动作</span></div>
            </div>
            <div id="sellabilityBoundary"></div>
            <div id="sellabilityLaneList" class="compact-card-grid"></div>
          </section>
          <section>
            <h3>阶段运行日志</h3>
            <div id="stageRunLog" class="timeline"></div>
          </section>
          <section>
            <h3>业务闭环摘要</h3>
            <div class="workflow">
              <div><strong>证据链</strong><p>公开来源 -> 解析 -> 核验 -> 规则 -> 阶段6产品包。</p></div>
              <div><strong>销售闭环</strong><p>真实竞争者 -> 买家匹配 -> 客户关系和报价 -> 触达。</p></div>
              <div><strong>证据包交付候选</strong><p>字段白名单、脱敏、水印、版本哈希、下载授权、审计。</p></div>
              <div><strong>支付交付</strong><p>订单、支付、收据、发票、结算、交付、回滚。</p></div>
            </div>
          </section>
        </div>
        <div class="view-panel" id="search" data-view-panel="search">
          <div class="view-grid">
            <section>
              <h3>实战项目搜索</h3>
              <label for="searchRegion">地区适配器（可多选）</label>
              <select id="searchRegion" class="select-fallback" multiple size="5"></select>
              <div id="searchRegionChoices" class="check-grid"></div>
              <div class="field-actions">
                <button class="secondary" type="button" id="selectAllRegions">全选地区</button>
                <button class="secondary" type="button" id="clearRegions">清空地区</button>
              </div>
              <label for="searchKeyword">关键词</label>
              <input id="searchKeyword" value="公共建筑工程" />
              <label for="searchProjectType">项目类型（可多选）</label>
              <select id="searchProjectType" class="select-fallback" multiple size="4">
                <option value="construction" selected>房建工程</option>
                <option value="municipal">市政工程</option>
                <option value="highway">公路交通</option>
                <option value="water_conservancy">水利工程</option>
              </select>
              <div id="searchProjectTypeChoices" class="check-grid"></div>
              <div class="field-actions">
                <button class="secondary" type="button" id="selectAllProjectTypes">全选类型</button>
                <button class="secondary" type="button" id="clearProjectTypes">清空类型</button>
              </div>
              <label>金额区间（万元）</label>
              <div class="field-row">
                <input id="searchAmountMinWan" type="number" value="800" aria-label="最低金额（万元）" />
                <input id="searchAmountMaxWan" type="number" value="3000" aria-label="最高金额（万元）" />
              </div>
              <label class="check-option">
                <input id="offlineSampleCandidates" type="checkbox" />
                <span>使用离线样本验证后续链路（不代表真实市场发现）</span>
              </label>
              <button id="runAutonomousSearch">搜索并生成机会闭环</button>
            </section>
            <section>
              <h3>地区适配器状态</h3>
              <div class="rail" id="regionCoverageSummary">
                <div class="metric"><strong>--</strong><span>可搜索地区</span></div>
                <div class="metric"><strong>--</strong><span>本地专用入口</span></div>
                <div class="metric"><strong>--</strong><span>待补地区</span></div>
              </div>
              <p class="muted-text" id="regionCoverageNarrative">地区覆盖缺口待读取：正在读取本省实时源、全国搜索入口和商业试点缺口。</p>
              <div id="regionAdapterSummary" class="empty-state">正在读取地区适配器...</div>
            </section>
            <section class="wide">
              <h3>搜索结果</h3>
              <div id="searchResult" class="empty-state">暂无搜索结果。</div>
            </section>
            <section class="wide">
              <h3>无候选诊断 / 来源解析</h3>
              <p class="muted-text" id="realCandidateDiscoveryDiagnosticsMeta">待读取真实候选发现诊断。</p>
              <div id="realCandidateDiscoveryDiagnostics" class="empty-state">暂无真实候选发现诊断。</div>
              <div class="field-actions">
                <button id="refreshRealCandidateDiscoveryDiagnostics">刷新发现诊断</button>
              </div>
            </section>
            <section class="wide">
              <h3>真实候选入库 / 去重读回</h3>
              <p class="muted-text" id="realCandidateCatalogMeta">待读取真实列表页候选库。</p>
              <div id="realCandidateCatalog" class="empty-state">暂无已入库真实候选。</div>
              <div class="field-actions">
                <button id="refreshRealCandidateCatalog">刷新真实候选库</button>
              </div>
            </section>
            <section class="wide">
              <h3>候选详情快照 / Stage2 读回</h3>
              <p class="muted-text" id="realCandidateStage2CaptureMeta">待读取真实候选详情页快照。</p>
              <div id="realCandidateStage2Captures" class="empty-state">暂无候选详情快照。</div>
              <div class="field-actions">
                <button id="refreshRealCandidateStage2Captures">刷新详情快照</button>
              </div>
            </section>
            <section class="wide">
              <h3>搜索运行记录</h3>
              <p class="muted-text" id="autonomousSearchRunMeta">待读取最新搜索记录。</p>
              <p class="muted-text" id="autonomousSearchPersistence">数据来源待读取；页面刷新不会自动清空，清空必须由 owner 显式触发。</p>
              <div id="autonomousSearchRuns" class="empty-state">暂无实战搜索运行记录。</div>
              <div class="field-actions">
                <button id="refreshAutonomousSearchRuns">刷新搜索记录</button>
                <button class="secondary" id="clearAutonomousSearchRuns">清空测试搜索记录</button>
              </div>
            </section>
          </div>
        </div>
        <div class="view-panel" id="autonomousWorkbench" data-view-panel="autonomousWorkbench">
          <section>
            <h3>机会工作台</h3>
            <div class="rail" id="autonomousMetrics">
              <div class="metric"><strong>--</strong><span>机会队列</span></div>
              <div class="metric"><strong>--</strong><span>商业钩子</span></div>
              <div class="metric"><strong>--</strong><span>下一步动作</span></div>
            </div>
            <div id="autonomousQueue" class="empty-state">暂无已持久化机会队列。</div>
            <div id="opportunityDetail" class="empty-state">点击机会后显示等级、评分、证据强度、报价和证据包明细。</div>
            <div id="autonomousDetailPanels" class="stage-grid"></div>
            <button id="refreshAutonomousWorkbench">刷新机会工作台</button>
          </section>
          <section>
            <h3>阶段6-9读回</h3>
            <div id="workbenchStatus"></div>
            <p>阶段6-9状态在这里作为机会工作台的交付读回，不再单独占用一级页面。</p>
            <button id="refreshWorkbench">刷新阶段6-9读回</button>
          </section>
        </div>
        <div class="view-panel" id="run" data-view-panel="run">
          <div class="view-grid">
            <section>
              <h3>任务与项目</h3>
              <label for="taskId">任务编号</label>
              <input id="taskId" value="TASK-OWNER-127-001" />
              <label for="projectId">项目编号</label>
              <input id="projectId" value="PROJ-OWNER-127-001" />
              <button id="createTask">创建内部任务</button>
              <button class="secondary" id="importProject">导入项目</button>
            </section>
            <section>
              <h3>公开源采集</h3>
              <p>只执行白名单内的真实公开入口页和附件原始链接；采集按已批准采集计划、来源配置、同站证据链与服务商门禁执行。</p>
              <label for="entryProfile">入口页配置</label>
              <select id="entryProfile"></select>
              <button id="runEntryCapture">执行入口页抓取</button>
              <label for="attachmentProfile">附件配置</label>
              <select id="attachmentProfile"></select>
              <button class="secondary" id="runAttachmentCapture">执行附件抓取</button>
              <button class="secondary" id="readLatestSourceCapture">读取最近一次抓取读回</button>
              <button class="secondary" id="refreshRealSourceRuns">刷新真实源任务列表</button>
              <div id="realSourceRunList" class="empty-state">暂无真实源任务运行记录。</div>
            </section>
            <section class="wide">
              <h3>内部链路运行</h3>
              <p>只接受脱敏、离线、内部运行参数；阶段1-5外部实时传输不在本页执行。</p>
              <label for="payload">运行参数（结构化文本）</label>
              <textarea id="payload">__CONTROLLED_SAMPLE_PAYLOAD__</textarea>
              <button id="runControlledSample">运行内部样本链路</button>
              <button class="secondary" id="previewRun">检查运行入口</button>
            </section>
          </div>
        </div>
        <div class="view-panel" id="systemRelease" data-view-panel="systemRelease">
          <section>
            <h3>服务商与调度状态</h3>
            <div id="providerStatus"></div>
            <h3>真实服务商放行矩阵</h3>
            <div id="providerExecutionMatrix" class="compact-card-grid"></div>
            <button id="refreshSystemRelease">刷新系统与放行</button>
          </section>
          <section>
            <h3>审批审计</h3>
            <div id="auditStatus"></div>
            <h3>真实外部动作门禁矩阵</h3>
            <div id="liveActionGateMatrix" class="compact-card-grid"></div>
          </section>
          <section class="controlled_opening_requirement">
            <h3>回归与受控放行状态</h3>
            <p>内部/样本链路只用于回归和受控验证，不代表真实实战完成；当前没有邮件、电话、支付、退款服务商接入，所以不会真实触达外部。</p>
            <span class="pill">内部测试发布模拟已打开</span>
            <span class="pill">证据包预览可打开</span>
            <span class="pill">客户账号不作为内部测试前置</span>
            <span class="pill warn">真实邮件/电话未接入</span>
            <span class="pill warn">真实退款未接入，仅可模拟</span>
          </section>
          <section class="wide">
            <h3>后台能力暴露清单</h3>
            <p class="muted-text">这里用来检查系统已有能力是不是已经在 UI 可见，避免后端有能力但操作台看不见、用不上。</p>
            <div id="capabilityExposure" class="compact-card-grid"></div>
          </section>
        </div>
        <div class="view-panel" id="acceptanceContract" data-view-panel="acceptanceContract">
          <section>
            <h3>用户验收契约</h3>
            <p class="muted-text">后续 UI 和系统优化先按这份契约验收：产品定义、实战闭环、证据包可验收、能力暴露、真实可卖性都必须能让 owner 看懂和操作。</p>
            <div id="acceptanceContractSummary"></div>
          </section>
          <section>
            <h3>当前验收状态</h3>
            <p class="muted-text">这里按同一份契约列出当前通过、部分满足和未展示项，用来决定下一轮应该改 UI、接口还是数据读回。</p>
            <div id="acceptanceGapSummary"></div>
          </section>
          <section class="wide">
            <h3>验收差距矩阵</h3>
            <div id="acceptanceGapMatrix" class="compact-card-grid"></div>
          </section>
          <section class="wide">
            <h3>验收标准</h3>
            <div id="acceptanceDimensionList" class="compact-card-grid"></div>
          </section>
          <section class="wide">
            <h3>当前优化优先级</h3>
            <div id="acceptancePriorityList" class="timeline"></div>
          </section>
        </div>
      </div>
      <section class="resultPane" aria-label="操作结果">
        <h3>操作结果</h3>
        <pre id="output">等待操作...</pre>
      </section>
    </div>
  </main>
</div>
""".replace("__CONTROLLED_SAMPLE_PAYLOAD__", controlled_sample_payload)
    script = """
const $ = (id) => document.getElementById(id);
function formatOperatorSummary(value) {
  if (!value || typeof value !== "object" || value.raw_json_required !== false) {
    return "";
  }
  const rows = [
    ["状态", labelOf(value.search_state || value.state)],
    ["商机", value.opportunity_id],
    ["运行编号", value.search_run_id || value.run_id],
    ["地区", value.region_code],
    ["入口", labelOf(value.entry_profile_id)],
    ["金额区间", amountRangeText(value.amount_range)],
    ["工作台", value.workbench],
    ["材料候选", value.customer_artifact_candidate],
    ["说明", value.display_message],
  ].filter(([, text]) => text !== undefined && text !== null && String(text).length);
  return rows.map(([label, text]) => `${label}: ${text}`).join("\\n");
}
const out = (value) => {
  const summary = formatOperatorSummary(value);
  $("output").textContent = summary || JSON.stringify(value, null, 2);
};
const views = new Set(Array.from(document.querySelectorAll("[data-view-panel]")).map((panel) => panel.dataset.viewPanel));
function updateCustomerPortalLink(opportunityId) {
  const link = $("customerPortalLink");
  if (!link) { return; }
  if (opportunityId) {
    link.href = `/customer-artifact-portal/${encodeURIComponent(opportunityId)}`;
    link.textContent = "证据包预览 · 当前商机";
    link.title = opportunityId;
    return;
  }
  link.href = "/customer-artifact-portal/OPP-HAPPY-001";
  link.textContent = "证据包预览 · 样例";
  link.title = "OPP-HAPPY-001";
}
function showView(view) {
  const selected = views.has(view) ? view : "overview";
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === selected);
  });
  document.querySelectorAll("[data-view]").forEach((item) => {
    const active = item.dataset.view === selected;
    item.classList.toggle("active", active);
    item.setAttribute("aria-current", active ? "page" : "false");
  });
  const stack = document.querySelector(".panelStack");
  if (stack) { stack.scrollTop = 0; }
  const selectedPanel = document.querySelector(`[data-view-panel="${selected}"]`);
  if (selectedPanel) { selectedPanel.scrollTop = 0; }
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
}
async function json(method, url, body) {
  const options = { method, headers: { "accept": "application/json" } };
  if (body) { options.headers["content-type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(url, options);
  const text = await response.text();
  let payload;
  try { payload = JSON.parse(text); } catch { payload = { raw: text }; }
  if (!response.ok) { throw payload; }
  return payload;
}
const stateLabels = {
  "AUTONOMOUS_SEARCH_ACCEPTED": "自动搜索已接受",
  "NO_CANDIDATES": "未发现候选",
  "REAL_SOURCE_ADAPTER_REQUIRED": "需要真实来源适配器",
  "REAL_SOURCE_REQUIRED": "需要真实来源候选",
  "REAL_PUBLIC_SOURCE_CANDIDATES": "真实列表页候选",
  "REAL_PUBLIC_CANDIDATE_DETAIL_CAPTURE": "真实候选详情抓取",
  "REAL_DETAIL_SNAPSHOT_PARSED_NEEDS_STAGE4_TO_STAGE9": "详情快照已解析，待后续证据回链",
  "REAL_LIST_PAGE_CANDIDATE_NEEDS_DETAIL_CAPTURE": "列表候选待详情抓取",
  "REAL_SOURCE_NO_CANDIDATES": "真实来源未命中候选",
  "OFFLINE_SAMPLE_CANDIDATES": "离线样本候选",
  "EXPLICIT_CANDIDATES": "显式候选",
  "SAMPLE_NOT_CUSTOMER_SELLABLE": "样本不可客户交付",
  "EXPLICIT_SOURCE_REVIEW_REQUIRED": "显式候选需真实回链复核",
  "real_source_candidate_feed_missing": "真实来源候选列表未接入",
  "WAIT_REAL_SOURCE_CANDIDATES": "等待真实来源候选",
  "queued": "排队中",
  "running": "运行中",
  "completed": "已完成",
  "failed": "失败",
  "paused": "已暂停",
  "dead_letter": "死信",
  "stage1_scheduler": "阶段1调度队列",
  "stage1_scheduler_queue": "阶段1调度队列",
  "STAGE2_HANDOFF_READY": "阶段2交接已准备",
  "INTENT_ONLY_NO_FETCH": "只生成交接意图，不抓取",
  "upstream_stage_not_reached": "上游阶段未到达",
  "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED": "真实样本闭环通过",
  "REVIEW_REQUIRED": "需要复核",
  "FETCHED": "已抓取",
  "DEGRADED": "降级",
  "PARSED": "已解析",
  "PARSED_WITH_REVIEW": "已解析待复核",
  "NOT_RUN": "未运行",
  "APPROVAL_READY": "可进入审批",
  "PRODUCTION_READY": "内部生产就绪",
  "EXECUTABLE": "可执行",
  "ANALYZE": "已分析",
  "INTERNAL DRAFT": "内部草稿",
  "QUALIFIED": "合格机会",
  "REVIEWABLE_PUBLIC_SIGNAL": "公开信号可复核",
  "MEDIUM": "中优先级",
  "HIGH": "高优先级",
  "DELIVERY_BLOCKED": "真实交付待放行",
  "PREPARE_LEADPACK_REVIEW_AND_DELIVERY_GATE": "准备线索包复核与交付放行",
  "L1_HOOK": "一级钩子摘要",
  "DRAFT": "草稿",
  "public_competition_risk_signal": "公开竞争风险信号",
  "GOVERNMENT": "政府/采购主管",
  "legal_action_actor": "法务/异议行动方",
  "procurement_decision_actor": "采购决策方",
  "NATIONAL_DISCOVERY_READY": "全国发现就绪",
  "LOCAL_PROFILE_READY": "本地入口就绪",
  "LOCAL_REALTIME_SOURCE_REQUIRED": "本省实时源待补",
  "JIANGSU-GGZY-HOME": "江苏公共资源交易网",
  "ZHEJIANG-GGZY-JYXXGK-LIST": "浙江交易信息公开",
  "SHANDONG-GGZY-JYXXGK-LIST": "山东交易公开",
  "HUBEI-BIDCLOUD-JYXX-LIST": "湖北交易信息",
  "SICHUAN-GGZY-TRANSACTION-INFO": "四川交易信息",
  "BEIJING-PLATFORM-HOME": "北京公共资源入口",
  "GGZY-DEAL-LIST": "全国公共资源交易列表",
  "PASS": "通过",
  "PARTIAL": "部分满足",
  "NOT_EXPOSED": "未展示",
  "FAIL": "未通过",
  "NOT_READY": "未就绪",
  "PERSISTED_UNTIL_EXPLICIT_OPERATOR_CLEAR": "持久保存，直到 owner 显式清空",
  "local_repository_operator_action_log": "本地仓库操作日志",
  "OperatorActionRepository": "操作动作仓库",
  "BLOCKED": "已拦截",
  "LOW": "低风险",
  "STANDARD": "常规",
  "CUSTOM": "自定义报价",
  "NOT_REQUIRED": "当前不需要",
  "MISSING": "缺失",
  "PAGE_DRAFT_ONLY": "仅页面草稿",
  "ELIGIBLE_FOR_INTERNAL_HOOK_REVIEW": "可内部复核钩子",
  "source_url": "完整来源网址",
  "full_person_name_with_identifier": "完整人员身份组合",
  "conflicting_project_name": "冲突项目名称",
  "exact_overlap_window": "精确重叠窗口",
  "complete_verification_path": "完整核验路径",
  "raw_snapshot_or_attachment": "原始快照或附件",
  "internal_scores": "内部评分",
  "leadpack_delivery_gate_not_ready": "线索包交付门未就绪",
  "crm_quote_live_execution_blocked": "CRM/报价真实执行未放行",
  "BUYER_FIT_SCORECARD": "买家匹配评分卡",
  "SALE_GATE_OPEN": "销售门已打开",
  "REPORT_ISSUED": "报告已生成",
  "WINDOW_ACTIONABLE": "窗口可行动",
  "GRADE_B": "B级机会",
  "CRM_OWNER_UNASSIGNED": "CRM负责人未分配",
  "sales_outreach": "销售触达服务商",
  "crm_quote": "CRM/报价服务商",
  "leadpack_page_delivery": "线索包页面交付服务商",
  "payment_collection": "收款服务商",
  "real_provider_call_blocked_readback_only": "真实服务商调用当前仅读回",
  "provider_adapters_readback_only": "服务商适配器只读回",
  "approval_and_audit_required_before_any_live_provider_use": "真实服务商使用前需要审批和审计",
  "automated_refund_program_absent_blocked": "自动退款程序未开放",
  "province_platform_missing_detail_or_attachment": "省级平台详情或附件入口待补",
  "A_HIGH_CONSTRUCTION_EPC": "A类高优先：施工/EPC",
  "B_HIGH_SUPERVISION": "B类高优先：监理",
  "C_MEDIUM_DESIGN_SURVEY": "C类中优先：设计/勘察",
  "D_LOW_SUPPLIER_SERVICE": "D类低优先：设备材料/服务采购",
  "REVIEW_UNCLASSIFIED_ENGINEERING": "工程类型待复核",
  "project_manager_active_conflict_certificate_qualification_performance_chain": "项目经理在建/证书/资质/业绩链",
  "chief_supervision_engineer_registration_supervision_qualification_performance_chain": "总监理工程师注册/资质/业绩链",
  "design_survey_responsible_person_registration_qualification_performance_chain": "设计勘察负责人注册/资质/业绩链",
  "supplier_qualification_performance_price_credit_chain": "供应商资格/业绩/价格/信用链",
  "classify_engineering_lane_before_role_gate": "先复核工程类型再核验角色",
  "project_manager_name_or_primary_responsible_person_name": "项目经理/项目负责人",
  "chief_supervision_engineer_name_or_primary_responsible_person_name": "总监理工程师/监理负责人",
  "design_lead_name_or_survey_lead_name_or_primary_responsible_person_name": "设计/勘察负责人",
  "not_required_for_supplier_service": "供应商类不要求项目经理",
  "review_required_before_role_gate": "角色门前需要复核",
  "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY": "A类缺负责人：需企业优先补全",
  "B_CHIEF_SUPERVISION_ENGINEER_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY": "B类缺总监：需企业优先补全",
  "C_DESIGN_SURVEY_RESPONSIBLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY": "C类缺设计/勘察负责人：需企业优先补全",
  "ENGINEERING_LANE_UNCLASSIFIED_REQUIRES_REVIEW": "工程类型未分类：需复核",
  "CAPTURED_TEXT_HAS_NO_RESPONSIBLE_ROLE_FIELD": "快照文本未披露负责人字段",
  "ROLE_TOKEN_PRESENT_PARSER_MISSED_OR_COMPLEX_TABLE": "存在角色词但表格解析未命中",
  "RESPONSIBLE_ROLE_ONLY_IN_TENDER_REQUIREMENT_NOT_ASSIGNMENT": "角色词只出现在资格要求中，不是已任命负责人",
  "NO_REPLAYABLE_TEXT_FOR_RESPONSIBLE_ROLE": "无可回放文本，需重抓/OCR",
  "detail_and_attachment_text_replayable_but_no_responsible_role_tokens": "详情/附件可回放，但未出现负责人角色词",
  "captured_text_contains_responsible_role_tokens": "快照中出现负责人角色词",
  "role_tokens_appear_only_in_tender_qualification_requirement": "角色词只作为招标资格要求出现",
  "detail_and_attachment_text_missing_or_unreadable": "详情/附件文本缺失或不可读",
  "STAGE4_COMPANY_PROJECT_FIRST_PUBLIC_RECORD_LOOKUP": "Stage4 按公司+项目优先补全",
  "STAGE3_DEEP_TABLE_PARSE_THEN_STAGE4_COMPANY_FIRST": "先深解析表格，再转公司优先核验",
  "WAIT_FOR_CANDIDATE_NOTICE_OR_STAGE4_PROJECT_RECORD_LOOKUP": "等候候选结果或查公开项目记录",
  "RECAPTURE_OR_OCR_THEN_STAGE4_COMPANY_PROJECT_FIRST": "先重抓/OCR，再转公司+项目补全",
  "responsible_role_name_missing_in_stage3_source_text": "Stage3源文本未给负责人姓名",
  "role_tokens_present_but_not_structured": "角色词存在但未结构化",
  "role_mentioned_as_requirement_not_assigned_person": "角色仅是资格条件，不是人员身份",
  "source_text_not_replayable": "源文本不可回放",
  "ACTIVE": "启用",
  "ALLOW": "允许",
  "APPLIED_TO_DRAFT": "已加到草稿",
  "APPROVED": "已通过",
  "AUDITABLE": "可审计",
  "BEIJING": "北京",
  "COMPREHENSIVE_SCORE": "综合评分",
  "CONSTRUCTION": "房建工程",
  "CUSTOMER": "客户",
  "DEAL": "交易",
  "DOC": "文档",
  "DRY_RUN": "试运行",
  "EMAIL": "邮件",
  "GET": "读取",
  "GGZY": "公共资源交易",
  "GUANGDONG": "广东",
  "HAPPY": "样例",
  "HOME": "首页",
  "HTML_PAGE": "网页",
  "INTERNAL": "内部",
  "INTERNAL_PROJECT_IMPORT": "内部项目导入",
  "JSON": "结构化数据",
  "LIST": "列表",
  "LIST_TO_DETAIL": "列表到详情",
  "MANUAL": "人工处理",
  "MASKING_REQUIRED": "需要脱敏",
  "NATIONAL": "全国",
  "NO_RESPONSE": "暂无响应",
  "OFFLINE_FIXTURE": "离线样本",
  "OPEN_TENDER": "公开招标",
  "ORDERED": "已排序",
  "ORG_EMAIL": "机构邮箱",
  "OWNER": "运营方",
  "PLATFORM": "平台",
  "PORTAL": "门户",
  "POST": "提交",
  "PROCUREMENT_NOTICE": "采购公告",
  "PROVINCIAL": "省级",
  "PUBLIC_OFFICIAL_SOURCE": "公开官方来源",
  "PUBLIC_ROLE_CONTACT": "公开角色联系人",
  "PUBLIC_SITE": "公开网站",
  "REACHABLE": "可触达",
  "READY": "已就绪",
  "READBACK_READY": "读回就绪",
  "REASONABLE": "合理",
  "RELEASED": "已发布",
  "REPLAY_READY": "可回放",
  "ROOT": "根对象",
  "SAMPLE": "样本",
  "SANDBOX_CANDIDATE_READY": "测试候选已就绪",
  "SANDBOX_DRY_RUN_READBACK": "沙箱试运行读回",
  "SEARCH": "搜索",
  "SKU": "产品档位",
  "SLICE": "切片",
  "T0_CORE": "核心覆盖",
  "TASK": "任务",
  "TRACE_PRESENT": "痕迹已记录",
  "UNASSIGNED": "未分配",
  "VALID": "有效",
};
const projectTypeLabels = {
  "construction": "房建工程",
  "municipal": "市政工程",
  "highway": "公路交通",
  "water_conservancy": "水利工程",
};
function labelOf(value) {
  const text = String(value ?? "--");
  return stateLabels[text] || projectTypeLabels[text] || text;
}
const topicLabels = {
  "TOPIC-CERT-REG-TIME": "证书/注册单位/时间异常",
  "TOPIC-RELEASE-CONFLICT": "负责人未释放/履约冲突",
  "TOPIC-CREDIT-PENALTY": "信用处罚/监管风险",
  "TOPIC-COMPOSITE-OBJECTION": "综合质疑证据",
  "TOPIC-PRE-BID-RESTRICTION": "投前限制竞争预测",
  "TOPIC-TIMELINE-DEFECT": "程序时间线缺陷",
  "TOPIC-COMPETITOR-PATTERN": "竞争格局/陪标线索",
  "TOPIC-SOCIAL-INSURANCE-SIGNAL": "社保造假信号",
};
const serviceTierLabels = {
  "TRIAGE": "快筛",
  "EVIDENCE_PACK": "证据包深度",
  "DEEP_RELEASE_CHECK": "深度释放核查",
  "CUSTOMER_DELIVERY_READY": "客户交付就绪",
};
const packageTemplateLabels = {
  "PROJECT_BRIEF": "项目简报模板",
  "ANALYSIS_REPORT": "分析报告模板",
  "EVIDENCE_PACK": "证据包模板",
  "OBJECTION_DRAFT": "异议草稿模板",
};
function topicLabel(value) {
  const text = String(value ?? "--");
  return topicLabels[text] || text;
}
function serviceTierLabel(value) {
  const text = String(value ?? "--");
  return serviceTierLabels[text] || text;
}
function packageTemplateLabel(value) {
  const text = String(value ?? "--");
  return packageTemplateLabels[text] || text;
}
function reasonLabel(value) {
  const text = String(value ?? "");
  if (text.startsWith("missing_key_fields:")) {
    return `缺关键字段：${text.replace("missing_key_fields:", "").replaceAll(",", "、")}`;
  }
  if (text.startsWith("source_candidate_review_tag:")) {
    return `真实候选复核标签：${reasonLabel(text.replace("source_candidate_review_tag:", ""))}`;
  }
  if (text.startsWith("source_candidate_preserved_for_review:")) {
    return `真实候选保留复核：${reasonLabel(text.replace("source_candidate_preserved_for_review:", ""))}`;
  }
  const labels = {
    amount_below_minimum: "金额低于搜索下限",
    amount_above_maximum: "金额高于搜索上限",
    objection_window_expired: "异议/公告窗口已过",
    candidate_publicity_window_expired: "中标候选公示/异议窗口已过",
    candidate_publicity_window_deadline_pending_detail: "公示/异议截止待详情页确认",
    candidate_publicity_window_layer_pass: "通过中标候选公示窗口层",
    candidate_publicity_deadline_pending_detail_capture: "公示截止待详情页补链",
    not_candidate_publicity_stage: "不是中标候选公示阶段",
    score_below_analysis_threshold_priority_tag: "评分仅作优先级标签",
    no_competitor_signal: "缺少候选公司/竞争信号",
    score_below_analysis_threshold: "评分低于自动闭环阈值",
    project_type_not_engineering: "项目类型不是工程类",
    project_type_unknown: "项目类型未识别",
    region_parse_state_unconfirmed: "地区来源仍需复核",
    objection_window_unknown: "异议窗口未知",
    static_detail_links_missing: "没有静态详情链接",
    js_rendered_list_or_api_required: "疑似 JS 列表壳，需要接列表数据源",
    browser_rendered_realtime_list_required: "正确实时源需要浏览器渲染列表读取",
    province_realtime_source_not_registered: "本省实时来源未登记",
    candidate_links_accepted: "已接受候选链接",
    all_or_some_links_filtered_by_region: "部分/全部链接被地区过滤",
    all_or_some_links_filtered_by_project_type: "部分链接带项目类型复核标签",
    all_or_some_links_filtered_by_amount_range: "部分链接带金额区间复核标签",
    links_present_but_navigation_or_template_only: "只有栏目导航或模板占位链接",
    links_present_but_not_candidate_detail_pages: "有链接但不是候选详情页",
    links_present_but_no_candidate_after_filters: "有链接但未形成可入池候选",
    candidate_discovery_no_issue_detected: "未检测到明确解析问题",
    non_mapping_link_item: "链接对象格式异常",
    missing_source_url: "链接缺少 URL",
    navigation_or_template_link: "栏目导航或模板占位链接",
    not_candidate_detail_url: "不是候选详情页",
    region_mismatch: "地区不匹配",
    project_type_mismatch: "项目类型不匹配",
  };
  return labels[text] || labelOf(text);
}
function reasonListText(values) {
  return (values || []).map(reasonLabel).filter(Boolean).join("、");
}
function badge(text, kind="") { return `<span class="pill ${kind}">${labelOf(text)}</span>`; }
function safeText(value) {
  return String(value ?? "--")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
function amountWanToYuan(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) { return fallback; }
  return Math.round(parsed * 10000);
}
function moneyWanText(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) { return "--"; }
  return `${Math.round(parsed / 10000)} 万`;
}
function amountRangeText(range) {
  if (!range) { return "--"; }
  return `${moneyWanText(range.minimum)} - ${moneyWanText(range.maximum)}`;
}
function selectedValues(id) {
  const checks = Array.from(document.querySelectorAll(`[data-select-target="${id}"]`));
  if (checks.length) {
    return checks.filter((item) => item.checked).map((item) => item.value).filter(Boolean);
  }
  const select = $(id);
  return Array.from(select?.selectedOptions || []).map((option) => option.value).filter(Boolean);
}
function setAllSelected(id, selected) {
  const select = $(id);
  if (!select) { return; }
  Array.from(select.options).forEach((option) => { option.selected = selected; });
  document.querySelectorAll(`[data-select-target="${id}"]`).forEach((item) => { item.checked = selected; });
}
function syncSelectFromChecks(id) {
  const select = $(id);
  if (!select) { return; }
  const checkedValues = new Set(selectedValues(id));
  Array.from(select.options).forEach((option) => { option.selected = checkedValues.has(option.value); });
}
function renderSelectChoices(selectId, containerId) {
  const select = $(selectId);
  const container = $(containerId);
  if (!select || !container) { return; }
  container.replaceChildren();
  Array.from(select.options).forEach((option) => {
    const label = document.createElement("label");
    label.className = "check-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = option.value;
    input.checked = option.selected;
    input.dataset.selectTarget = selectId;
    input.addEventListener("change", () => syncSelectFromChecks(selectId));
    const text = document.createElement("span");
    text.textContent = option.textContent || option.value;
    label.append(input, text);
    container.appendChild(label);
  });
  syncSelectFromChecks(selectId);
}
function renderRows(rows) {
  return `<div class="detail-table">${rows
    .filter(([, value]) => value !== undefined && value !== null && String(value).length)
    .map(([label, value]) => `<div class="detail-row"><strong>${label}</strong><span>${labelOf(value)}</span></div>`)
    .join("")}</div>`;
}
function listText(items) {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  return rows.length ? rows.map(labelOf).join(" / ") : "--";
}
function renderInlineList(items, emptyText="暂无") {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  return rows.length
    ? rows.map((item) => `<li>${safeText(labelOf(item))}</li>`).join("")
    : `<li>${safeText(emptyText)}</li>`;
}
function candidateRange(candidate) {
  return {
    minimum: candidate?.amount_min ?? candidate?.amount,
    maximum: candidate?.amount_max ?? candidate?.amount
  };
}
function sourceModeOf(runOrCandidate) {
  return runOrCandidate?.source_candidate_mode
    || runOrCandidate?.search_scope?.source_candidate_mode
    || runOrCandidate?.data_boundary?.source_candidate_mode
    || "";
}
function isOfflineSample(runOrCandidate) {
  const sourceMode = sourceModeOf(runOrCandidate);
  return sourceMode === "OFFLINE_SAMPLE_CANDIDATES"
    || runOrCandidate?.offline_sample_validation === true
    || runOrCandidate?.is_offline_sample_candidate === true
    || String(runOrCandidate?.project_name || "").includes("机会搜索样本");
}
function searchBoundaryMessage(run) {
  const sourceMode = sourceModeOf(run);
  if (run?.search_state === "NO_CANDIDATES" || sourceMode === "REAL_SOURCE_REQUIRED") {
    return {
      title: "未发现真实候选",
      body: "默认实战搜索没有合成样本机会；当前真实来源候选列表未接入，所以本次为 0 候选、0 闭环。",
      kind: "warn",
    };
  }
  if (isOfflineSample(run)) {
    return {
      title: "离线样本验证",
      body: "这些机会只用于验证 Stage1-9、工作台和证据包链路，不代表真实市场发现，也不能作为客户可售证据。",
      kind: "warn",
    };
  }
  if (sourceMode === "EXPLICIT_CANDIDATES") {
    return {
      title: "显式候选闭环",
      body: "候选已进入内部闭环；客户交付前仍要核验真实详情页、附件和证据回链。",
      kind: "",
    };
  }
  if (sourceMode === "REAL_PUBLIC_SOURCE_CANDIDATES") {
    const count = run?.search_scope?.candidate_count ?? (run?.candidate_options || []).length ?? 0;
    return {
      title: count ? "真实列表页候选" : "真实列表页未命中",
      body: count
        ? "已从真实公开列表页解析候选，并自动尝试详情页与同站附件原文进入 Stage2/Stage3；客户可售前还需要 Stage4-9 证据回链。"
        : "已调用真实公开列表页候选发现器，但本次没有解析到符合条件的候选。",
      kind: count ? "" : "warn",
    };
  }
  return {
    title: "搜索读回",
    body: run?.display_message || "已读取搜索运行记录。",
    kind: "",
  };
}
function opportunityActions(opportunityId, sampleMode=false) {
  if (!opportunityId) { return ""; }
  return `<div class="opportunity-actions">
    <a href="#autonomousWorkbench" data-workbench-opportunity="${opportunityId}">${sampleMode ? "查看样本机会" : "查看机会"}</a>
    <a href="/customer-artifact-portal/${encodeURIComponent(opportunityId)}">证据包预览</a>
    <a href="/customer-artifact-portal-download/${encodeURIComponent(opportunityId)}">${sampleMode ? "下载内部样本证据包" : "下载证据包"}</a>
  </div>`;
}
function candidateOpportunityActions(candidate, activeOpportunityId="", selectedProjectId="") {
  const candidateOpportunityId = candidate.opportunity_id || (activeOpportunityId && candidate.project_id === selectedProjectId ? activeOpportunityId : "");
  return opportunityActions(candidateOpportunityId, isOfflineSample(candidate));
}
function renderCandidateCards(candidates, activeOpportunityId="", selectedProjectId="") {
  const rows = Array.isArray(candidates) ? candidates : [];
  if (!rows.length) {
    return `<div class="empty-state">暂无候选对象明细。</div>`;
  }
  return `<div class="compact-card-grid">${rows.map((candidate) => `
    <div class="stage-card">
      <strong>${candidate.project_name || candidate.project_id || "--"}</strong>
      <p>${candidate.region_name || candidate.region_code || "--"} · ${labelOf(candidate.project_type || "--")} · ${amountRangeText(candidateRange(candidate))}</p>
      ${badge(candidate.analysis_decision || "--", candidate.selected_for_capture_plan ? "" : "warn")}
      ${badge(candidate.analysis_priority || "--")}
      ${isOfflineSample(candidate) ? badge("离线样本，不可客户交付", "warn") : badge(candidate.source_candidate_mode || "真实候选待核验")}
      ${badge(candidate.analysis_score ? `评分 ${candidate.analysis_score}` : "评分 --")}
      ${badge(candidate.closed_loop_generated ? (isOfflineSample(candidate) ? "已生成样本闭环" : "已生成机会闭环") : "未生成机会闭环", candidate.closed_loop_generated ? "" : "warn")}
      ${candidate.closed_loop_state ? badge(`闭环 ${labelOf(candidate.closed_loop_state)}`, candidate.closed_loop_state === "STAGE1_6_INTERNAL_READY" ? "" : "warn") : ""}
      ${candidate.stage2_detail_capture_pending ? badge("详情待继续", "warn") : ""}
      ${candidate.stage1_6_time_budget_pending ? badge("Stage1-6待继续", "warn") : ""}
      ${candidate.stage2_detail_capture_state ? badge(`详情 ${candidate.stage2_detail_capture_state}`, candidate.stage2_detail_snapshot_id_optional ? "" : "warn") : ""}
      ${candidate.stage3_detail_parse_state ? badge(`解析 ${candidate.stage3_detail_parse_state}`, String(candidate.stage3_detail_parse_state).startsWith("PARSED") ? "" : "warn") : ""}
      ${candidate.opportunity_priority_class ? badge(candidate.opportunity_priority_class, candidate.responsible_role_gap_review_required ? "warn" : "") : ""}
      ${candidate.responsible_role_gap_code ? badge(candidate.responsible_role_gap_code, "warn") : ""}
      ${candidate.publication_window_state ? badge(labelOf(candidate.publication_window_state)) : ""}
      <p>${candidate.source_site_name || candidate.source_profile_id || candidate.source_url || "来源待读回"}</p>
      ${candidate.opportunity_priority_class || candidate.verification_focus || candidate.expected_responsible_role_field ? `<p><strong>分级核验</strong> 等级：${safeText(labelOf(candidate.opportunity_priority_class || "--"))}；核验链：${safeText(labelOf(candidate.verification_focus || "--"))}；预期角色：${safeText(labelOf(candidate.expected_responsible_role_field || "--"))}；角色状态：${candidate.expected_responsible_role_present ? "已满足" : "待企业优先补全"}</p>` : ""}
      ${candidate.responsible_role_gap_root_cause || candidate.stage4_identity_completion_route ? `<p><strong>角色缺口根因</strong> ${safeText(labelOf(candidate.responsible_role_gap_root_cause || "--"))}；证据：${safeText(labelOf(candidate.responsible_role_gap_source_evidence || "--"))}；下一步：${safeText(labelOf(candidate.stage4_identity_completion_route || "--"))}；阻塞：${safeText(labelOf(candidate.stage4_identity_completion_blocker || "--"))}</p>` : ""}
      ${Array.isArray(candidate.responsible_role_gap_token_hits) && candidate.responsible_role_gap_token_hits.length ? `<p><strong>角色词命中</strong> ${safeText(candidate.responsible_role_gap_token_hits.join(" / "))}</p>` : ""}
      ${candidate.candidate_company || candidate.primary_responsible_person_name || candidate.project_manager_certificate_no ? `<p><strong>核验对象</strong> 企业：${safeText(candidate.candidate_company || "待解析")}；主负责人：${safeText(candidate.primary_responsible_person_name || "待解析")}；项目经理：${safeText(candidate.project_manager_name || "待解析")}；总监：${safeText(candidate.chief_supervision_engineer_name || "待解析")}；设计负责人：${safeText(candidate.design_lead_name || "待解析")}；勘察负责人：${safeText(candidate.survey_lead_name || "待解析")}；证书：${safeText(candidate.project_manager_certificate_no || "待解析")}</p>` : ""}
      ${candidate.candidate_company_parse_state || candidate.project_manager_name_parse_state || candidate.project_manager_certificate_no_parse_state ? `<p><strong>核验字段解析</strong> 企业：${safeText(labelOf(candidate.candidate_company_parse_state || "--"))}；主负责人：${safeText(labelOf(candidate.primary_responsible_person_name_parse_state || "--"))}；项目经理：${safeText(labelOf(candidate.project_manager_name_parse_state || "--"))}；证书：${safeText(labelOf(candidate.project_manager_certificate_no_parse_state || "--"))}；类型：${safeText(labelOf(candidate.project_manager_certificate_type_parse_state || "--"))}；专业：${safeText(labelOf(candidate.project_manager_cert_specialty_parse_state || "--"))}；职称：${safeText(labelOf(candidate.project_manager_professional_title_parse_state || "--"))}</p>` : ""}
      ${candidate.source_url ? `<p><strong>来源网址</strong> <a href="${safeText(candidate.source_url)}" target="_blank" rel="noopener">${safeText(candidate.source_url)}</a></p>` : ""}
      ${candidate.published_at_optional ? `<p><strong>发布时间</strong> ${safeText(candidate.published_at_optional)}</p>` : ""}
      ${candidate.amount_parse_state || candidate.region_parse_state ? `<p><strong>解析状态</strong> 金额：${safeText(labelOf(candidate.amount_parse_state || "--"))}；地区：${safeText(labelOf(candidate.region_parse_state || "--"))}</p>` : ""}
      ${candidate.stage2_detail_snapshot_id_optional ? `<p><strong>详情快照</strong> ${safeText(candidate.stage2_detail_snapshot_id_optional)} · 附件线索 ${safeText(candidate.stage2_attachment_link_count ?? 0)} · 附件快照 ${safeText(candidate.stage2_attachment_snapshot_count ?? 0)}</p>` : ""}
      <p><strong>${candidate.selected_for_capture_plan ? "入选理由" : "未入选原因"}</strong> ${candidateDecisionReason(candidate, selectedProjectId)}</p>
      ${candidateOpportunityActions(candidate, activeOpportunityId, selectedProjectId)}
    </div>
  `).join("")}</div>`;
}
function candidateDecisionReason(candidate, selectedProjectId="") {
  if (isOfflineSample(candidate)) {
    return `离线样本命中地区、项目类型和金额区间，评分 ${candidate.analysis_score ?? "--"}；只验证后续链路，不代表真实市场机会。`;
  }
  if (candidate.selected_for_capture_plan || candidate.project_id === selectedProjectId) {
    return `通过中标候选公示/异议窗口第一层分流，评分 ${candidate.analysis_score ?? "--"}；金额、类型和证据字段作为复核/优先级标签，进入来源蓝图和闭环生成。`;
  }
  if ((candidate.why_skip || []).length) {
    return `跳过：${reasonListText(candidate.why_skip)}；评分 ${candidate.analysis_score ?? "--"}。`;
  }
  if ((candidate.review_reasons || []).length) {
    return `需要复核：${reasonListText(candidate.review_reasons)}；评分 ${candidate.analysis_score ?? "--"}。`;
  }
  if (!candidate.source_url && !candidate.source_profile_id) {
    return "公开来源入口缺失，进入来源补齐队列。";
  }
  if (candidate.analysis_priority === "LOW") {
    return "商业优先级偏低，暂不进入当前闭环。";
  }
  return `${labelOf(candidate.analysis_decision || "需要复核")}，等待批量复盘。`;
}
function candidateFailureCategory(candidate, selectedProjectId="") {
  if (isOfflineSample(candidate) && (candidate.selected_for_capture_plan || candidate.project_id === selectedProjectId)) {
    return "样本闭环，非真实可售";
  }
  if (candidate.selected_for_capture_plan || candidate.project_id === selectedProjectId) {
    return "通过窗口分流，进入闭环";
  }
  if (!candidate.source_url && !candidate.source_profile_id) {
    return "来源缺口";
  }
  if (candidate.analysis_priority === "LOW") {
    return "商业优先级低";
  }
  return "待复核";
}
function renderCandidateBatchReview(run) {
  const rows = Array.isArray(run?.candidate_options) ? run.candidate_options : [];
  if (!rows.length) {
    return `<div class="empty-state">暂无批量候选复盘。</div>`;
  }
  const selectedProjectId = run.search_scope?.selected_project_id || run.project_id || "";
  const selected = rows.filter((candidate) => candidate.selected_for_capture_plan || candidate.project_id === selectedProjectId);
  const nationalCount = rows.filter((candidate) => String(candidate.source_profile_id || "").includes("GGZY-DEAL-LIST")).length;
  const localCount = rows.length - nationalCount;
  const categories = {};
  rows.forEach((candidate) => {
    const category = candidateFailureCategory(candidate, selectedProjectId);
    categories[category] = (categories[category] || 0) + 1;
  });
  const categoryText = Object.entries(categories).map(([name, count]) => `${name} ${count}`).join(" / ");
  return `
    <div class="rail">
      <div class="metric"><strong>${rows.length}</strong><span>候选对象</span></div>
      <div class="metric"><strong>${selected.length}</strong><span>进入闭环</span></div>
      <div class="metric"><strong>${nationalCount}</strong><span>全国平台来源</span></div>
    </div>
    <p class="muted-text">失败分类：${safeText(categoryText || "暂无失败分类")}；本省实时入口 ${localCount} 条，全国平台 ${nationalCount} 条（只用于全国搜索，不代替省级来源）。</p>
    <div class="compact-card-grid">${rows.map((candidate) => `
      <div class="stage-card">
        <strong>${safeText(candidate.project_name || candidate.project_id || "--")}</strong>
        <p>${safeText(candidate.region_name || candidate.region_code || "--")} · ${safeText(labelOf(candidate.project_type || "--"))} · ${safeText(amountRangeText(candidateRange(candidate)))}</p>
        ${badge(candidateFailureCategory(candidate, selectedProjectId), candidate.selected_for_capture_plan ? "" : "warn")}
        ${badge(candidate.source_profile_id || "来源待补", candidate.source_profile_id ? "" : "warn")}
        <p><strong>判断</strong> ${safeText(candidateDecisionReason(candidate, selectedProjectId))}</p>
        <p><strong>来源</strong> ${candidate.source_url ? `<a href="${safeText(candidate.source_url)}">${safeText(candidate.source_site_name || candidate.source_url)}</a>` : "来源网址待补"}</p>
      </div>
    `).join("")}</div>
  `;
}
function renderStage16ValidationLedger(run) {
  const ledger = run?.stage1_6_validation_ledger || run?.search_scope?.stage1_6_validation_ledger || run?.data_boundary?.stage1_6_validation_ledger || {};
  const stages = Array.isArray(ledger.stage_counts) ? ledger.stage_counts : [];
  if (!stages.length) {
    return `<div class="empty-state">暂无 Stage1-6 验收账本。</div>`;
  }
  const caps = ledger.caps || {};
  const capText = [
    caps.candidate_limit ? `候选上限 ${caps.candidate_limit}` : "",
    caps.guangdong_page_limit ? `广东页数 ${caps.guangdong_page_limit}` : "",
    caps.guangdong_page_size ? `每页 ${caps.guangdong_page_size}` : "",
    caps.candidate_limit_truncated_count ? `截断 ${caps.candidate_limit_truncated_count}` : "未截断",
    caps.stage1_6_time_budget_exhausted ? "Stage1-6时间用尽" : ""
  ].filter(Boolean).join(" · ");
  return `
    <div class="stage-card">
      <strong>广东 Stage1-6 验收账本</strong>
      <p>${safeText(capText || "未设置运行上限")}；模式：${safeText(ledger.ledger_scope || "--")}</p>
      ${badge(ledger.validation_mode ? "跑通验收模式" : "普通运行", ledger.validation_mode ? "" : "warn")}
      ${caps.candidate_limit_source ? badge(caps.candidate_limit_source) : ""}
    </div>
    <div class="compact-card-grid">${stages.map((stage) => `
      <div class="stage-card">
        <strong>Stage${safeText(stage.stage)} ${safeText(stage.name || "")}</strong>
        <p>输入 ${safeText(stage.input_count ?? 0)} · 有效 ${safeText(stage.effective_count ?? 0)} · 无效 ${safeText(stage.invalid_count ?? 0)} · 待处理 ${safeText(stage.pending_count ?? 0)}</p>
        ${badge(stage.state || "待运行", stage.invalid_count || stage.pending_count ? "warn" : "")}
        ${stage.identity_resolution_required_count ? badge(`身份补全 ${stage.identity_resolution_required_count}`, "warn") : ""}
        ${stage.evidence_readback_ready_count !== undefined ? badge(`证据读回 ${stage.evidence_readback_ready_count}`) : ""}
        ${stage.failure_reasons && Object.keys(stage.failure_reasons).length ? `<p><strong>失败原因</strong> ${safeText(Object.entries(stage.failure_reasons).map(([name, count]) => `${name} ${count}`).join(" / "))}</p>` : ""}
        ${stage.review_reasons && Object.keys(stage.review_reasons).length ? `<p><strong>复核原因</strong> ${safeText(Object.entries(stage.review_reasons).map(([name, count]) => `${name} ${count}`).join(" / "))}</p>` : ""}
        ${stage.field_counts ? `<p><strong>字段</strong> ${safeText(Object.entries(stage.field_counts).map(([name, count]) => `${labelOf(name)} ${count}`).join(" / "))}</p>` : ""}
        ${stage.priority_class_counts && Object.keys(stage.priority_class_counts).length ? `<p><strong>分级</strong> ${safeText(Object.entries(stage.priority_class_counts).map(([name, count]) => `${labelOf(name)} ${count}`).join(" / "))}</p>` : ""}
        ${stage.responsible_role_gap_counts && Object.keys(stage.responsible_role_gap_counts).length ? `<p><strong>角色缺口</strong> ${safeText(Object.entries(stage.responsible_role_gap_counts).map(([name, count]) => `${labelOf(name)} ${count}`).join(" / "))}</p>` : ""}
      </div>
    `).join("")}</div>
  `;
}
function renderSearchResultFromRun(run) {
  if (!run) {
    $("searchResult").className = "empty-state";
    $("searchResult").textContent = "暂无搜索结果。";
    return;
  }
  const scope = run.search_scope || {};
  const boundary = searchBoundaryMessage(run);
  const sampleMode = isOfflineSample(run);
  const opportunityIds = Array.isArray(run.opportunity_ids) ? run.opportunity_ids.filter(Boolean) : [];
  const closedCount = scope.closed_loop_generated_count ?? opportunityIds.length ?? (run.opportunity_id ? 1 : 0);
  const opportunityTitle = closedCount > 1
    ? `已生成 ${closedCount} 个机会闭环`
    : run.opportunity_id
    ? (sampleMode ? `样本机会闭环：${run.opportunity_id}` : run.opportunity_id)
    : "未生成机会";
  $("searchResult").className = "";
  $("searchResult").innerHTML = `
    <div class="stage-card ${boundary.kind === "warn" ? "controlled_opening_requirement" : ""}">
      <strong>${safeText(boundary.title)}</strong>
      <p>${safeText(boundary.body)}</p>
      ${badge(sourceModeOf(run) || scope.source_candidate_mode || run.search_state || "--", boundary.kind)}
      ${sampleMode ? badge("样本不可客户交付", "warn") : ""}
    </div>
    <div class="stage-card">
      <strong>${safeText(opportunityTitle)}</strong>
      <p>${run.project_name || run.query || "--"}</p>
      ${badge(run.search_state || "--", run.search_state === "AUTONOMOUS_SEARCH_ACCEPTED" ? "" : "warn")}
      ${badge(run.region_code || "--")}
      ${badge(run.project_type_label || run.project_type || "--")}
      <p>金额区间：${amountRangeText(run.amount_range || {minimum: run.amount_min, maximum: run.amount_max})}</p>
      <p>候选对象：${scope.candidate_count ?? (run.candidate_options || []).length ?? 0}；进入闭环：${scope.selected_candidate_count ?? "--"}；生成闭环：${closedCount}</p>
      <p class="muted-text">${safeText(scope.stage1_policy || "Stage1 不是单选代表，而是按中标候选公示/异议窗口分流候选；未进入闭环者保留原因。")}</p>
      ${opportunityActions(run.opportunity_id, sampleMode)}
    </div>
    <h3>广东 Stage1-6 验收账本</h3>
    ${renderStage16ValidationLedger(run)}
    <h3>候选对象明细</h3>
    ${renderCandidateCards(run.candidate_options || [], run.opportunity_id || "", scope.selected_project_id || run.project_id || "")}
    <h3>批量候选复盘与失败分类</h3>
    ${renderCandidateBatchReview(run)}
  `;
}
function renderCommercialBoundary(hook, buyer, next, delivery, safeDisplay) {
  const buyerRows = Array.isArray(buyer.buyer_rankings) ? buyer.buyer_rankings : [];
  const topBuyer = buyerRows[0] || {};
  const forbidden = [
    ...(hook.withheld_fields || []),
    ...(hook.forbidden_sales_claims || [])
  ];
  const deliveryAfterPay = [
    delivery.package_id ? `证据包：${delivery.package_id}` : "",
    delivery.page_draft_id ? `页面草稿：${delivery.page_draft_id}` : "",
    "完整证据路径需审批/成交/交付后开放",
    safeDisplay?.source_url_visible ? "来源网址可见" : "完整来源网址卖前隐藏",
    safeDisplay?.raw_snapshot_visible ? "原始快照可见" : "原始快照卖前隐藏"
  ].filter(Boolean);
  return `<div class="stage-grid">
    <div class="stage-card">
      <strong>卖前价值摘要</strong>
      <p>${hook.redacted_claim_summary || hook.teaser_copy || "--"}</p>
      ${badge(hook.hook_eligibility_state || "--")}
      ${badge(hook.disclosure_level || "--")}
      ${badge(hook.leakage_risk_level || "--", hook.leakage_risk_level === "LOW" ? "" : "warn")}
    </div>
    <div class="stage-card">
      <strong>卖前可讲</strong>
      <ul>${renderInlineList((hook.allowed_sales_talking_points || []).slice(0, 8), "暂无可讲卖点")}</ul>
    </div>
    <div class="stage-card">
      <strong>卖前不可讲</strong>
      <ul>${renderInlineList(forbidden, "暂无暂不外泄字段")}</ul>
      ${badge(`暂不外泄 ${hook.withheld_field_count ?? forbidden.length}`, "warn")}
    </div>
    <div class="stage-card">
      <strong>交付后可见</strong>
      <ul>${renderInlineList(deliveryAfterPay, "等待交付候选")}</ul>
      ${badge(delivery.delivery_ready ? "交付就绪" : "交付待放行", delivery.delivery_ready ? "" : "warn")}
    </div>
    <div class="stage-card">
      <strong>买家与报价支撑</strong>
      <p>${labelOf(topBuyer.buyer_type || "--")} · 买家匹配 ${buyer.buyer_fit_score || topBuyer.buyer_fit_score || "--"} · 报价 ${next.quote_draft_id || "--"}</p>
      ${badge(next.quote_surface_state || "--")}
      ${badge(next.provider_execution_state || "--", next.provider_execution_state === "BLOCKED" ? "warn" : "")}
    </div>
    <div class="stage-card">
      <strong>真实外发状态</strong>
      <p>当前为内部复核和拟发送包预览；真实邮件/电话/CRM 发送需要服务商、审批、审计和 operator action。</p>
      ${badge(hook.customer_visible_enabled ? "客户可见" : "客户不可见", hook.customer_visible_enabled ? "" : "warn")}
      ${badge(hook.external_send_enabled ? "真实外发已开" : "真实外发未开", hook.external_send_enabled ? "" : "warn")}
    </div>
  </div>`;
}
function renderOpportunityDetail(first, panels) {
  const hook = panels.commercial_hook_panel || {};
  const buyer = panels.buyer_ranking_panel || {};
  const delivery = panels.delivery_state_panel || {};
  const next = panels.sales_next_action_panel || {};
  const risk = panels.evidence_risk_panel || {};
  const safeDisplay = panels.safe_display_contract || {};
  $("opportunityDetail").className = "";
  $("opportunityDetail").innerHTML = `
    <h3>机会详情</h3>
    ${renderRows([
      ["机会编号", first.opportunity_id],
      ["机会级别", first.opportunity_grade],
      ["可售状态", first.saleability_status],
      ["主专题", topicLabel(first.primary_evidence_topic_code || first.project_fact_primary_evidence_topic_code)],
      [
        "专题集合",
        ((first.resolved_evidence_topic_codes || first.project_fact_resolved_evidence_topic_codes || []).map(topicLabel).join(" / ")) || "--",
      ],
      ["正式 SKU", first.recommended_sku],
      ["服务深度", serviceTierLabel(first.service_tier_code)],
      ["包装模板", packageTemplateLabel(first.package_template_code)],
      ["转化优先级", first.conversion_priority],
      ["异议价值分", first.objection_value_score],
      ["买家匹配分", first.buyer_fit_score || buyer.buyer_fit_score],
      ["购买动机分", buyer.buyer_motivation_score],
      ["购买能力分", buyer.purchase_capacity_score],
      ["证据强度", first.evidence_strength_label || risk.evidence_strength_label],
      ["公开硬伤信号", first.hard_defect_public_label || risk.hard_defect_public_label],
      ["交付状态", delivery.delivery_state || first.delivery_state],
      ["报价草稿", next.quote_draft_id],
      ["证据包", delivery.package_id],
      ["页面草稿", delivery.page_draft_id],
    ])}
    <h3>卖前/交付后边界</h3>
    ${renderCommercialBoundary(hook, buyer, next, delivery, safeDisplay)}
    <div class="stage-grid">
      <div class="stage-card"><strong>商业钩子</strong><p>${hook.teaser_copy || first.commercial_hook_teaser || "--"}</p>${badge(hook.disclosure_level || "--")}${badge(hook.leakage_risk_level || "--")}</div>
      <div class="stage-card"><strong>可讲卖点</strong><p>${listText(hook.allowed_sales_talking_points || [])}</p></div>
      <div class="stage-card"><strong>暂不外泄字段</strong><p>${listText(hook.withheld_fields || [])}</p>${badge(`数量 ${hook.withheld_field_count ?? 0}`, "warn")}</div>
      <div class="stage-card"><strong>复核项</strong><p>${listText(risk.review_items || first.review_items || [])}</p></div>
      <div class="stage-card"><strong>买家排序</strong><p>${(buyer.buyer_rankings || first.buyer_rankings || []).map((row) => `${row.rank}.${labelOf(row.buyer_type || "--")} ${row.buyer_fit_score || row.actionability_state || row.reachable_state || ""}`).join(" / ") || "--"}</p></div>
      <div class="stage-card"><strong>下一步</strong><p>${labelOf(next.next_action || first.next_action || "--")}</p>${badge(next.provider_execution_state || "--", next.provider_execution_state === "BLOCKED" ? "warn" : "")}</div>
    </div>
    ${opportunityActions(first.opportunity_id || "")}
  `;
}
function stageObjectRefLabel(key) {
  const labels = {
    scan_run_id: "扫描批次",
    selected_project_id: "入选项目",
    selected_opportunity_candidate_id: "入选候选",
    region_codes: "地区范围",
    project_types: "项目类型",
    queue_item_id: "队列编号",
    source_blueprint_plan_id: "来源蓝图",
    entry_profile_id: "入口配置",
    capture_step_count: "采集步骤",
    project_id: "项目编号",
    project_name: "项目名称",
    source_url: "来源网址",
    evidence_risk_ref: "风险核验对象",
    review_profile_ref: "复核对象",
    acceptance_state: "验收状态",
    rule_evidence_ref: "规则证据",
    commercial_evidence_ref: "商业证据",
    report_record_ref: "报告记录",
    product_package_ref: "产品包对象",
    opportunity_id: "商机编号",
    saleable_opportunity_ref: "可售机会",
    buyer_fit_ref: "买家匹配",
    outreach_plan_ref: "触达计划",
    provider_execution_state: "服务商执行",
    order_record_ref: "订单对象",
    delivery_package_ref: "交付包",
    automated_refund_enabled: "自动退款"
  };
  return labels[key] || labelOf(key);
}
function renderStageObjectFlow(stages) {
  if (!$("stageObjectFlow")) { return; }
  const rows = Array.isArray(stages) ? stages : [];
  if (!rows.length) {
    $("stageObjectFlow").innerHTML = `<div class="empty-state">暂无阶段对象流；运行实战搜索后显示。</div>`;
    return;
  }
  $("stageObjectFlow").innerHTML = rows.map((stage) => {
    const refs = Object.entries(stage.object_refs || {})
      .filter(([, value]) => value !== undefined && value !== null && String(value).length)
      .slice(0, 6);
    const refList = refs.length
      ? refs.map(([key, value]) => `<li>${safeText(stageObjectRefLabel(key))}: ${safeText(labelOf(value))}</li>`).join("")
      : `<li>暂无对象引用</li>`;
    const reasons = Array.isArray(stage.failure_reasons) ? stage.failure_reasons.filter(Boolean) : [];
    const reasonList = reasons.length
      ? reasons.map((text) => `<li>${safeText(labelOf(text))}</li>`).join("")
      : `<li>未发现失败分类</li>`;
    const invalid = Number(stage.invalid_count || 0);
    return `<div class="stage-card">
      <strong>阶段${safeText(stage.stage)} ${safeText(stage.name)}</strong>
      <p>输入 ${stage.input_count ?? stage.produced_count ?? 0} · 输出 ${stage.output_count ?? stage.effective_count ?? 0} · 有效 ${stage.effective_count ?? 0} · 无效 ${stage.invalid_count ?? 0}</p>
      ${badge(stage.state || "等待运行", invalid ? "warn" : "")}
      <p><strong>对象流</strong></p>
      <ul>${refList}</ul>
      <p><strong>失败分类</strong></p>
      <ul>${reasonList}</ul>
      <p><strong>下一步</strong> ${safeText(stage.next_action || "等待运行。")}</p>
    </div>`;
  }).join("");
}
function renderStageRunBoundary(telemetry) {
  const sourceMode = telemetry?.source_candidate_mode || "";
  const offlineSample = Boolean(telemetry?.offline_sample_validation) || sourceMode === "OFFLINE_SAMPLE_CANDIDATES";
  const noRealCandidate = sourceMode === "REAL_SOURCE_REQUIRED" || telemetry?.test_path_unblocked === false;
  const customerReady = Boolean(telemetry?.customer_sellable_evidence_ready);
  const realPublicReadback = telemetry?.real_public_stage4_9_readback || {};
  const hardDefectPlan = realPublicReadback?.regional_hard_defect_source_plan || telemetry?.data_boundary?.regional_hard_defect_source_plan || {};
  const hardDefectReadback = realPublicReadback?.regional_hard_defect_source_readback || {};
  const missingSourceTypes = Array.isArray(hardDefectPlan?.missing_source_types) ? hardDefectPlan.missing_source_types : [];
  const coveredSourceTypes = Array.isArray(hardDefectReadback?.covered_source_types) ? hardDefectReadback.covered_source_types : [];
  const queriedSourceTypes = Array.isArray(hardDefectReadback?.queried_source_types) ? hardDefectReadback.queried_source_types : [];
  const sourceEntries = Array.isArray(hardDefectPlan?.source_entries) ? hardDefectPlan.source_entries : [];
  const parts = [];
  if (noRealCandidate) {
    parts.push("运行边界：默认实战搜索没有读取到真实来源候选，系统没有生成可售机会。");
  } else if (offlineSample) {
    parts.push("运行边界：离线样本验证，只证明 1-9 内部链路、工作台和证据包链路可跑。");
  } else if (sourceMode === "EXPLICIT_CANDIDATES") {
    parts.push("运行边界：显式候选闭环，客户交付前仍需核验真实详情页、附件和证据回链。");
  } else {
    parts.push("运行边界：等待实战搜索或任务运行。");
  }
  if (telemetry?.data_boundary_message) { parts.push(telemetry.data_boundary_message); }
  if (missingSourceTypes.length) {
    parts.push(`待补硬伤核验源：${missingSourceTypes.map(labelOf).join("、")}。`);
  }
  if (queriedSourceTypes.length) {
    parts.push(`已查询广东住建源：${queriedSourceTypes.map(labelOf).join("、")}。`);
  }
  if (coveredSourceTypes.length) {
    parts.push(`已命中核验证据：${coveredSourceTypes.map(labelOf).join("、")}。`);
  }
  if (sourceEntries.length) {
    parts.push(`下一批官方入口：${sourceEntries.slice(0, 3).map((entry) => labelOf(entry.source_name || entry.entry_id)).join("、")}。`);
  }
  if (!customerReady) { parts.push("客户可售证据：未就绪。"); }
  const boundary = $("stageRunBoundary");
  if (!boundary) { return; }
  boundary.className = `status ${offlineSample || noRealCandidate || !customerReady ? "warn" : ""}`;
  boundary.innerHTML = `${safeText(parts.join(" "))} ${
    [
      sourceMode ? badge(sourceMode, offlineSample || noRealCandidate ? "warn" : "") : "",
      offlineSample ? badge("离线样本", "warn") : "",
      noRealCandidate ? badge("真实候选缺失", "warn") : "",
      customerReady ? badge("客户可售证据就绪") : badge("客户可售证据未就绪", "warn")
    ].filter(Boolean).join("")
  }`;
}
function renderStageOverviewTelemetry(telemetry) {
  const defaultStages = [
    "市场扫描 / 机会发现", "来源蓝图 / 采集计划", "解析规范化", "证据风险核验", "规则证据门",
    "产品包", "商业钩子 / 买家匹配", "触达计划", "支付交付"
  ];
  const actualStages = Array.isArray(telemetry?.stage_stats) ? telemetry.stage_stats : [];
  const actualByStage = new Map(actualStages.map((stage) => [Number(stage.stage), stage]));
  const stages = defaultStages.map((name, index) => {
    const stageNumber = index + 1;
    const actual = actualByStage.get(stageNumber);
    if (actual) {
      return {
        stage: stageNumber,
        name: actual.name || name,
        state: actual.state || "已读回",
        produced_count: actual.produced_count ?? actual.output_count ?? 0,
        effective_count: actual.effective_count ?? 0,
        invalid_count: actual.invalid_count ?? 0,
        input_count: actual.input_count ?? actual.produced_count ?? 0,
        output_count: actual.output_count ?? actual.effective_count ?? 0,
        object_refs: actual.object_refs || {},
        failure_reasons: actual.failure_reasons || [],
        next_action: actual.next_action || "等待下一步动作。",
        note: actual.note || "已读取本阶段运行统计。",
      };
    }
    const upstreamHasRun = actualStages.length > 0;
    return {
      stage: stageNumber,
      name,
      state: upstreamHasRun ? "等待上游有效数据" : "等待运行",
      produced_count: 0,
      effective_count: 0,
      invalid_count: 0,
      input_count: 0,
      output_count: 0,
      object_refs: {},
      failure_reasons: upstreamHasRun ? ["upstream_stage_not_reached"] : [],
      next_action: upstreamHasRun ? "先补齐上游候选、采集或任务消费，达到本阶段后自动显示产出。" : "等待实战搜索或任务运行。",
      note: upstreamHasRun ? "本阶段还没有收到上游有效对象，不代表该阶段不存在。" : "运行实战搜索或创建任务后显示本阶段统计。",
    };
  });
  const totals = telemetry?.totals || {
    stage_count: stages.length,
    produced_count: 0,
    effective_count: 0,
    invalid_count: 0
  };
  $("stageDirection").textContent = telemetry?.direction
    ? `${telemetry.direction}。内部/样本链路只算回归；真实候选进料和对外交付门禁必须单独验收。`
    : "系统方向：市场扫描 -> 来源蓝图 -> 阶段1-9内部链路 -> 工作台 -> 证据包预览。运行后显示每阶段产出。";
  renderStageRunBoundary(telemetry);
  $("stageMetrics").innerHTML = [
    `<div class="metric"><strong>9</strong><span>阶段数</span></div>`,
    `<div class="metric"><strong>${totals.produced_count || 0}</strong><span>产出对象</span></div>`,
    `<div class="metric"><strong>${totals.effective_count || 0}</strong><span>有效数据</span></div>`
  ].join("");
  const logs = telemetry?.logs || ["等待运行。这里会记录搜索、选源、阶段1-9产出和交付候选生成过程。"];
  $("stageRunLog").innerHTML = logs.map((item, index) => `<div>${index + 1}. ${item}</div>`).join("");
  $("stageBoard").innerHTML = stages.map((stage) => `
    <div class="stage-card">
      <strong>阶段${stage.stage} ${stage.name}</strong>
      <p>${stage.note || "等待运行。"}</p>
      ${badge(stage.state || "等待运行", stage.invalid_count ? "warn" : "")}
      ${badge(`产出 ${stage.produced_count ?? 0}`)}
      ${badge(`有效 ${stage.effective_count ?? 0}`)}
      ${badge(`无效 ${stage.invalid_count ?? 0}`, stage.invalid_count ? "warn" : "")}
    </div>
  `).join("");
  renderStageObjectFlow(stages);
}
function renderCapabilityExposure(readiness, scheduler, goLive) {
  const items = [
    ["阶段1-9数据流", "已展示", "运营总览显示阶段产出、有效数据、无效数据和运行日志。"],
    ["真实候选发现器", "已接入首段", "默认实战搜索会调用真实公开列表页候选发现器，解析候选、去重入库并送入 Stage1。"],
    ["详情页/附件快照读回", "最小接入", "真实候选会自动尝试抓取同站详情页和同站附件原文，保存 Stage2 快照并运行 Stage3 parser；Stage4-9 正式消费仍需继续补。"],
    ["实战搜索与地区适配器", "部分接入", "UI 支持地区多选、项目类型多选、金额区间、搜索运行记录和真实候选读回；部分地区本省实时源仍待补，全国平台只用于全国搜索。"],
    ["机会评分与商业钩子", "已展示", "机会工作台可查看等级、评分、证据强度、报价、买家排序和下一步动作。"],
    ["证据包清单/下载预览", "已展示", "内部证据包预览页可看拟邮件包、证据项、字段策略，并可下载内部证据包文件。"],
    ["公开来源网址校验", "已展示", "证据包读回会补充来源站点、来源网址和验证口径，方便运营方回查。"],
    ["字段白名单/脱敏/水印/版本哈希", "已展示", "内部预览页显示字段策略、脱敏、水印、版本哈希和模拟下载审计。"],
    ["服务商读回/调度", "已展示", `服务商状态：${readiness?.provider_status?.mode ? "读回模式" : "读回"}；调度：${labelOf(scheduler?.readiness_state || "未知")}。`],
    ["文字识别/验证码/校验页处理入口", "待接操作台", "授权能力与采集链路已纳入产品方向，但操作台还缺少专门的运行、读回和失败复盘入口。"],
    ["真实邮件/电话/支付服务商", "未接入", "当前只做内部预览、模拟外发和读回，不会真实触达客户或产生支付。"],
    ["订单交付/退款异常", "未接入", "支付交付阶段已在流程中可见；真实订单、交付和退款异常处理还需要服务商与审计链接入。"],
    ["批量商机运营", "待补强", "当前可看单商机详情和最近运行记录，批量筛选、排序、标记和复盘还不够产品化。"],
  ];
  $("capabilityExposure").innerHTML = items.map(([name, state, detail]) => {
    const warn = state.includes("未接入") || state.includes("待接") || state.includes("待补");
    return `<div class="stage-card"><strong>${name}</strong><p>${detail}</p>${badge(state, warn ? "warn" : "")}</div>`;
  }).join("");
}
function renderProviderExecutionMatrix(readiness, scheduler, goLive) {
  const provider = goLive?.provider_config_readiness || {};
  const controlled = goLive?.controlled_opening_requirements || {};
  const families = provider.credential_redaction_audit?.families || {};
  const providerRows = [
    ["sales_outreach", "真实邮件/电话触达", controlled.stage8_real_execution_enabled, "拟外发、触达频控、退订和外发审计"],
    ["crm_quote", "CRM/报价", controlled.provider_live_execution_enabled, "报价草稿、CRM动作和报价发送回写"],
    ["leadpack_page_delivery", "线索包页面交付", controlled.real_delivery_enabled, "证据包页面、下载授权和交付审计"],
    ["payment_collection", "收款/支付", controlled.real_payment_enabled, "收款、支付记录和交付联动"]
  ];
  $("providerExecutionMatrix").innerHTML = providerRows.map(([family, title, liveEnabled, purpose]) => {
    const credential = families[family] || {};
    const credentialState = credential.credential_present ? "凭证已配置" : "凭证未配置";
    return `<div class="stage-card">
      <strong>${title}</strong>
      <p>${purpose}</p>
      ${badge(provider.mode || "--", provider.readback_only ? "warn" : "")}
      ${badge(credentialState, credential.credential_present ? "" : "warn")}
      ${badge(liveEnabled ? "真实执行已开" : "真实执行未开", liveEnabled ? "" : "warn")}
      <p><strong>下一步</strong> 接入 sandbox 凭证、健康检查、审批链、审计链和 operator action 后再做 live pilot。</p>
    </div>`;
  }).join("");
  const blocked = provider.summary?.blocked_reasons || [];
  const gateRows = [
    ["真实触达", controlled.stage8_real_execution_enabled, "服务商沙箱 + 审批 + 审计 + 操作确认"],
    ["真实支付", controlled.real_payment_enabled, "支付 sandbox + 订单记录 + 审批 + 审计"],
    ["真实交付", controlled.real_delivery_enabled, "下载授权 + 交付审计 + 客户账号控制"],
    ["真实退款异常", controlled.real_refund_enabled, "人工退款异常队列；自动退款继续排除"],
    ["自动退款执行", controlled.automated_refund_enabled, "保持排除，不作为自动程序开放"]
  ];
  $("liveActionGateMatrix").innerHTML = `
    <div class="stage-card">
      <strong>当前阻断原因</strong>
      <ul>${renderInlineList(blocked, "暂无阻断原因")}</ul>
    </div>
    ${gateRows.map(([name, enabled, prerequisite]) => `<div class="stage-card">
      <strong>${name}</strong>
      <p>${prerequisite}</p>
      ${badge(enabled ? "已放行" : "未放行", enabled ? "" : "warn")}
    </div>`).join("")}
  `;
}
function renderUserAcceptanceContract(contract) {
  const product = contract?.productDefinition || {};
  const authority = contract?.acceptanceAuthority || {};
  const dimensions = Array.isArray(contract?.acceptanceDimensions) ? contract.acceptanceDimensions : [];
  const hardGates = Array.isArray(contract?.authoritativeHardGates) ? contract.authoritativeHardGates : [];
  const acceptanceStates = Array.isArray(contract?.realWorldAcceptanceStates) ? contract.realWorldAcceptanceStates : [];
  const priorities = Array.isArray(contract?.currentOptimizationPriorities) ? contract.currentOptimizationPriorities : [];
  $("acceptanceContractSummary").innerHTML = renderRows([
    ["契约编号", contract?.contractId],
    ["状态", contract?.status],
    ["权威来源", authority.l0AndDSeriesAreAuthoritative ? "L0/D2-D14 为验收硬门" : "未声明"],
    ["平台定位", product.platformType],
    ["售卖对象", product.soldProduct],
    ["主用户", product.primaryUser],
    ["客户体验", product.customerExperience],
    ["主运营链路", product.primaryOperatingLoop],
    ["验收前置", authority.userAcceptancePrecedesUiRewrite ? "先验收契约，再改 UI/系统" : "未声明"],
    ["脚本绿灯", authority.scriptsPassingIsNotEnough ? "不等于产品验收通过" : "未声明"],
  ]);
  $("acceptanceDimensionList").innerHTML = dimensions.map((item) => {
    const pass = (item.passCriteria || []).slice(0, 3).map((text) => `<li>${safeText(text)}</li>`).join("");
    const fail = (item.failSignals || []).slice(0, 2).map((text) => `<li>${safeText(text)}</li>`).join("");
    return `<div class="stage-card">
      <strong>${safeText(item.dimensionId)} ${safeText(item.title)}</strong>
      <p>${safeText(item.userQuestion)}</p>
      ${badge("验收标准")}
      <ul>${pass}</ul>
      <p><strong>失败信号</strong></p>
      <ul>${fail}</ul>
    </div>`;
  }).join("");
  const gateHtml = hardGates.length
    ? `<h3>L0/D 权威硬门</h3><div class="stage-grid">${hardGates.map((gate) => `<div class="stage-card">
        <strong>${safeText(gate.gateId)} ${safeText(gate.title)}</strong>
        <p>${safeText(gate.requirement)}</p>
        ${badge("硬门")}
        <p><strong>失败信号</strong></p>
        <p>${safeText(gate.failSignal)}</p>
      </div>`).join("")}</div>`
    : "";
  const stateHtml = acceptanceStates.length
    ? `<h3>真实实战状态分层</h3><div class="stage-grid">${acceptanceStates.map((state) => `<div class="stage-card">
        <strong>${safeText(state.state)}</strong>
        <p>${safeText(state.meaning)}</p>
        <p><strong>最低证据</strong></p>
        <ul>${renderListItems(state.minimumEvidence)}</ul>
      </div>`).join("")}</div>`
    : "";
  $("acceptancePriorityList").innerHTML = priorities.length
    ? `${gateHtml}${stateHtml}<h3>当前优化优先级</h3>` + priorities.map((item, index) => `<div>${index + 1}. ${safeText(item)}</div>`).join("")
    : `<div>暂无优化优先级。</div>`;
}
async function loadUserAcceptanceContract() {
  const contract = await json("GET", "/operator-console/user-acceptance-contract");
  renderUserAcceptanceContract(contract);
  return contract;
}
function acceptanceStatusKind(status) {
  if (status === "FAIL") { return "danger"; }
  if (status === "PARTIAL" || status === "NOT_EXPOSED" || status === "NOT_READY") { return "warn"; }
  return "";
}
function renderListItems(items, emptyText="暂无") {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  return rows.length
    ? rows.map((text) => `<li>${safeText(text)}</li>`).join("")
    : `<li>${safeText(emptyText)}</li>`;
}
function renderAcceptanceGapMatrix(matrix) {
  const summary = matrix?.summary || {};
  const priorities = Array.isArray(matrix?.topPriorities) ? matrix.topPriorities : [];
  const authorityFindings = Array.isArray(matrix?.authorityFindings) ? matrix.authorityFindings : [];
  const dimensions = Array.isArray(matrix?.dimensions) ? matrix.dimensions : [];
  $("acceptanceGapSummary").innerHTML = renderRows([
    ["矩阵编号", matrix?.matrixId],
    ["契约引用", matrix?.contractRef],
    ["维度总数", summary.totalDimensions],
    ["通过", summary.passCount],
    ["部分满足", summary.partialCount],
    ["未展示", summary.notExposedCount],
    ["未通过", summary.failCount],
    ["操作结论", summary.operatorConclusion],
    ["下一步判断", summary.nextDecision],
  ]) + `<h3>优先修复</h3><div class="timeline">${
    priorities.length
      ? priorities.map((item) => `<div>${safeText(item.rank)}. ${safeText(item.title)}：${safeText(item.reason)}</div>`).join("")
      : `<div>暂无优先修复项。</div>`
  }</div><h3>权威复核发现</h3><div class="timeline">${
    authorityFindings.length
      ? authorityFindings.map((item) => `<div>${safeText(item.severity)} · ${safeText(item.title)}：${safeText(item.impact)}</div>`).join("")
      : `<div>暂无权威复核发现。</div>`
  }</div>`;
  $("acceptanceGapMatrix").innerHTML = dimensions.length
    ? dimensions.map((item) => {
      const status = item.status || "--";
      return `<div class="stage-card">
        <strong>${safeText(item.dimensionId)} ${safeText(item.title)}</strong>
        <p>${safeText(item.currentUiState)}</p>
        ${badge(status, acceptanceStatusKind(status))}
        <p><strong>当前缺口</strong></p>
        <ul>${renderListItems(item.gaps)}</ul>
        <p><strong>下一步</strong></p>
        <ul>${renderListItems(item.nextActions)}</ul>
        <p><strong>依据</strong></p>
        <ul>${renderListItems((item.evidenceRefs || []).slice(0, 3))}</ul>
      </div>`;
    }).join("")
    : `<div class="empty-state">暂无验收状态矩阵。</div>`;
}
async function loadAcceptanceGapMatrix() {
  const matrix = await json("GET", "/operator-console/user-acceptance-gap-matrix");
  renderAcceptanceGapMatrix(matrix);
  return matrix;
}
function renderRealWorldSellability(surface) {
  const summary = surface?.sellability_summary || {};
  const boundary = surface?.boundary || {};
  const lanes = Array.isArray(surface?.lanes) ? surface.lanes : [];
  const externalReady = summary.external_sellable_now ? "已闭合" : "待接入";
  $("sellabilityDecision").textContent = `${summary.sellability_level || "真实可卖性待读取"}：${summary.owner_decision || "等待系统读回。"} `;
  $("sellabilityMetrics").innerHTML = [
    `<div class="metric"><strong>${summary.sellability_level || "--"}</strong><span>可卖性等级</span></div>`,
    `<div class="metric"><strong>${summary.latest_opportunity_id || "待运行"}</strong><span>最新商机</span></div>`,
    `<div class="metric"><strong>${externalReady}</strong><span>真实外部动作</span></div>`
  ].join("");
  $("sellabilityBoundary").innerHTML = renderRows([
    ["回归搜索与证据包验收", boundary.regression_search_and_evidence_package_review ? "可用" : "待运行"],
    ["真实市场候选进料", boundary.real_market_candidate_feed_ready ? "已接入" : "未接入"],
    ["客户可售证据", boundary.customer_sellable_evidence_ready ? "已就绪" : "未就绪"],
    ["线索包交付候选", boundary.leadpack_delivery_candidate_visible ? "可见" : "待生成"],
    ["真实客户触达", boundary.real_customer_touch_enabled ? "已接入" : "未接入"],
    ["真实支付", boundary.real_payment_enabled ? "已接入" : "未接入"],
    ["真实交付", boundary.real_delivery_enabled ? "已接入" : "未接入"],
    ["自动退款", boundary.automated_refund_enabled ? "已开放" : "排除"],
  ]);
  $("sellabilityLaneList").innerHTML = lanes.length
    ? lanes.map((lane) => {
      const status = lane.status || "--";
      return `<div class="stage-card">
        <strong>${safeText(lane.title || lane.lane_id)}</strong>
        <p>${safeText(lane.current_state)}</p>
        ${badge(status, acceptanceStatusKind(status))}
        <p><strong>缺口</strong></p>
        <ul>${renderListItems(lane.gaps, "当前无关键缺口")}</ul>
        <p><strong>下一步</strong></p>
        <ul>${renderListItems(lane.next_actions)}</ul>
      </div>`;
    }).join("")
    : `<div class="empty-state">暂无真实可卖性读回。</div>`;
}
async function loadRealWorldSellability() {
  const surface = await json("GET", "/operator-console/real-world-sellability");
  renderRealWorldSellability(surface);
  return surface;
}
function renderStage6ReviewLoopStatus(surface) {
  const summary = surface?.summary || {};
  const rows = Array.isArray(surface?.project_status_rows) ? surface.project_status_rows : [];
  $("stage6ReviewLoopNarrative").textContent = `${summary.operator_batch_state_label || "Stage6 批次状态待读取"}：${surface?.operator_decision?.decision_label || "等待读回。"} `;
  $("stage6ReviewLoopMetrics").innerHTML = [
    `<div class="metric"><strong>${summary.project_count ?? 0}</strong><span>项目数</span></div>`,
    `<div class="metric"><strong>${summary.automated_dispatch_available_count ?? 0}</strong><span>可续跑</span></div>`,
    `<div class="metric"><strong>${summary.manual_hold_count ?? 0}</strong><span>人工停机</span></div>`
  ].join("");
  $("stage6ReviewLoopProjectList").innerHTML = rows.length
    ? rows.map((row) => `<div class="stage-card">
        <strong>${safeText(row.project_id || "--")} ${safeText(row.project_name || "")}</strong>
        <p>${safeText(row.owner_status_label || row.loop_terminal_state || "--")}</p>
        ${badge(row.loop_terminal_state || "--", row.manual_review_hold ? "warn" : "")}
        ${row.automated_dispatch_available ? badge("可受控续跑") : badge("不可自动续跑", "warn")}
        ${row.stage7_commercial_input_allowed ? badge("可进 Stage7 内部复核") : badge("暂不进 Stage7", "warn")}
        <p><strong>下一步</strong></p>
        <p>${safeText(row.owner_next_action_label || row.next_recommended_action || "--")}</p>
        <p><strong>停机/阻断原因</strong></p>
        <p>${safeText(row.manual_hold_reason || row.lineage?.dispatch_closeout_state || row.lineage?.dispatch_readback_state || "暂无")}</p>
        <p><strong>重新开启条件</strong></p>
        <ul>${renderListItems(row.reopen_conditions, "按下一步动作复核")}</ul>
      </div>`).join("")
    : `<div class="empty-state">暂无 Stage6 批次复核产物；先运行 Stage6 review loop 或指定状态表。</div>`;
}
async function loadStage6ReviewLoopStatus() {
  const surface = await json("GET", "/operator-console/stage6-review-loop-status");
  renderStage6ReviewLoopStatus(surface);
  return surface;
}
function queueStatusTotal(counts) {
  return Object.values(counts || {}).reduce((total, value) => total + Number(value || 0), 0);
}
function taskOverviewTelemetryFromQueueItem(item) {
  if (!item?.task_id && !item?.queue_item_id) { return null; }
  const taskId = item.task_id || "--";
  const projectId = item.project_id || "--";
  const queueItemId = item.queue_item_id || "--";
  return {
    direction: "内部任务发起 -> 队列调度 -> 阶段2交接意图 -> 后续采集/闭环",
    stage_stats: [
      {
        stage: 1,
        name: "调度 / 任务入队",
        state: item.status || "queued",
        input_count: 1,
        output_count: 1,
        produced_count: 1,
        effective_count: 1,
        invalid_count: item.last_error ? 1 : 0,
        note: `任务 ${taskId} 已进入内部队列。`,
        object_refs: {
          task_id: taskId,
          project_id: projectId,
          queue_item_id: queueItemId,
          source_registry_id: item.source_registry_id,
          route_policy_id: item.route_policy_id,
        },
        failure_reasons: item.last_error ? [item.last_error] : [],
        next_action: "等待内部 worker 或后续采集运行消费；当前不会真实外部抓取。",
      },
      {
        stage: 2,
        name: "阶段2交接意图",
        state: item.stage2_handoff_intent_state || "INTENT_ONLY_NO_FETCH",
        input_count: 1,
        output_count: 1,
        produced_count: 1,
        effective_count: 1,
        invalid_count: 0,
        note: "阶段2交接对象已生成，但真实外部抓取默认关闭。",
        object_refs: {
          queue_item_id: queueItemId,
          source_registry_id: item.source_registry_id,
        },
        failure_reasons: [],
        next_action: "如需采集，进入“采集运行”选择公开源入口执行受控抓取。",
      }
    ],
    totals: { stage_count: 9, produced_count: 2, effective_count: 2, invalid_count: item.last_error ? 1 : 0 },
    logs: [
      `已创建内部任务 ${taskId}。`,
      `队列编号 ${queueItemId}，状态 ${labelOf(item.status || "queued")}。`,
      "真实外部抓取、真实触达、真实支付和真实交付均未执行。",
    ],
  };
}
function renderTaskRunOverview(scheduler) {
  if (!$("taskRunOverviewList")) { return; }
  const counts = scheduler?.queue_status_counts || {};
  const items = Array.isArray(scheduler?.latest_queue_items) ? scheduler.latest_queue_items : [];
  const latest = items[0] || scheduler?.latest_queue_item || {};
  const total = queueStatusTotal(counts) || items.length;
  const queued = Number(counts.queued || 0);
  $("taskRunMetrics").innerHTML = [
    `<div class="metric"><strong>${total}</strong><span>队列任务</span></div>`,
    `<div class="metric"><strong>${queued}</strong><span>排队中</span></div>`,
    `<div class="metric"><strong>${latest.task_id || "待创建"}</strong><span>最新任务</span></div>`
  ].join("");
  if (!items.length) {
    $("taskRunOverviewNarrative").textContent = "暂无任务运行记录；创建内部任务后会显示队列状态、任务编号、项目编号和阶段2交接状态。";
    $("taskRunOverviewList").className = "empty-state";
    $("taskRunOverviewList").textContent = "暂无任务运行记录；在“采集运行”里创建内部任务后显示。";
    return;
  }
  $("taskRunOverviewNarrative").textContent = `已读回 ${items.length} 条最近任务；最新任务 ${latest.task_id || "--"} 当前为${labelOf(latest.status || "--")}，不会触发真实外部抓取。`;
  $("taskRunOverviewList").className = "compact-card-grid";
  $("taskRunOverviewList").innerHTML = items.map((item) => {
    const status = item.status || "--";
    const warn = status !== "queued" && status !== "completed";
    return `<div class="stage-card">
      <strong>${safeText(item.task_id || item.queue_item_id || "--")}</strong>
      <p>项目：${safeText(item.project_id || "--")} · 地区：${safeText(item.region_code || "--")}</p>
      ${badge(status, warn ? "warn" : "")}
      ${badge(item.queue_name || "--")}
      ${badge(item.stage2_handoff_intent_state || "阶段2交接待读取")}
      <p>队列编号：${safeText(item.queue_item_id || "--")}</p>
      <p>来源：${safeText(item.source_registry_id || "--")}；路由：${safeText(item.route_policy_id || "--")}</p>
      <p>尝试：${safeText(item.attempt_count ?? 0)} / ${safeText(item.max_attempts ?? "--")}；下一次运行：${safeText(item.next_run_at || "--")}</p>
      <p><strong>下一步</strong> ${status === "queued" ? "等待内部 worker/后续链路消费；当前不会真实外部抓取。" : "查看队列状态、错误和审计读回。"}</p>
    </div>`;
  }).join("");
  if (!selectedAutonomousOpportunityId) {
    const taskTelemetry = taskOverviewTelemetryFromQueueItem(latest);
    if (taskTelemetry) { renderStageOverviewTelemetry(taskTelemetry); }
  }
}
async function loadReadiness(writeOutput = true) {
  const readiness = await json("GET", "/operator-console/readiness");
  const scheduler = await json("GET", "/operator-console/scheduler-status");
  const goLive = await json("GET", "/go-live/readiness");
  $("capability").textContent = labelOf(readiness.capability_state || "--");
  $("provider").textContent = readiness.provider_status?.mode ? "读回模式" : "读回";
  $("scheduler").textContent = labelOf(scheduler.readiness_state || "--");
  $("summary").textContent = "运营操作台已就绪。默认实战搜索已接真实公开列表页候选发现、去重入库和详情页快照读回；真实附件原文、Stage4-9 正式消费、真实邮件/电话/支付/退款服务商仍未接入。";
  $("workbenchStatus").innerHTML = [
    badge("阶段6 产品包"),
    badge("阶段7 客户关系/报价"),
    badge("阶段8 销售触达"),
    badge("阶段9 支付交付"),
    badge(`测试上线模拟 ${goLive.go_live_enabled ? "已开放" : "可预览"}`)
  ].join("");
  $("providerStatus").innerHTML = [
    badge(`服务商 ${readiness.provider_status?.mode ? "读回模式" : "读回"}`),
    badge(`调度 ${labelOf(scheduler.readiness_state || "未知")}`),
    badge("内部服务商模拟读回可用"),
    badge("真实邮件/电话未接入", "warn")
  ].join("");
  $("auditStatus").innerHTML = [
    badge("内部测试不等客户账号"),
    badge("证据包预览可打开"),
    badge("真实外发审计未接入", "warn")
  ].join("");
  renderTaskRunOverview(scheduler);
  renderCapabilityExposure(readiness, scheduler, goLive);
  renderProviderExecutionMatrix(readiness, scheduler, goLive);
  if (writeOutput) { out({ readiness, scheduler, goLive }); }
}
let selectedAutonomousOpportunityId = "";
async function loadAutonomousWorkbench(opportunityId = selectedAutonomousOpportunityId) {
  selectedAutonomousOpportunityId = opportunityId || selectedAutonomousOpportunityId || "";
  const query = selectedAutonomousOpportunityId
    ? `?opportunity_id=${encodeURIComponent(selectedAutonomousOpportunityId)}`
    : "";
  const payload = await json("GET", `/operator-console/autonomous-workbench${query}`);
  const queue = payload.opportunity_queue || [];
  const first = queue[0] || {};
  $("autonomousMetrics").innerHTML = [
    `<div class="metric"><strong>${payload.productized_operator_workbench?.opportunity_queue_count ?? 0}</strong><span>机会队列</span></div>`,
    `<div class="metric"><strong>${first.commercial_hook_teaser ? "可读" : "待生成"}</strong><span>商业钩子</span></div>`,
    `<div class="metric"><strong>${labelOf(first.next_action || "--")}</strong><span>下一步动作</span></div>`
  ].join("");
  if (!queue.length) {
    $("autonomousQueue").className = "empty-state";
    $("autonomousQueue").textContent = "暂无已持久化机会队列。";
    $("opportunityDetail").className = "empty-state";
    $("opportunityDetail").textContent = "点击机会后显示等级、评分、证据强度、报价和证据包明细。";
    $("autonomousDetailPanels").innerHTML = "";
    return payload;
  }
  $("autonomousQueue").className = "";
  $("autonomousQueue").innerHTML = queue.map((item) => {
    const tags = [
      badge(item.saleability_status || "--"),
      badge(item.evidence_strength_label || "--"),
      badge(item.conversion_priority || "--"),
      badge(item.delivery_state || "--", item.customer_visible_enabled ? "" : "warn")
    ].join("");
    return `<div class="stage-card">
      <strong>${item.opportunity_id || "--"}</strong>
      <p>${item.commercial_hook_teaser || "商业钩子待生成"}</p>
      <p>${topicLabel(item.primary_evidence_topic_code || "--")} / ${labelOf(item.recommended_sku || "--")} / ${serviceTierLabel(item.service_tier_code || "--")} / ${packageTemplateLabel(item.package_template_code || "--")}</p>
      ${tags}
      <p>${labelOf(item.next_action || "--")}</p>
      ${opportunityActions(item.opportunity_id || "")}
    </div>`;
  }).join("");
  const panels = payload.panels || {};
  panels.safe_display_contract = payload.safe_display_contract || payload.productized_operator_workbench?.safe_display_contract || {};
  renderOpportunityDetail(first, panels);
  $("autonomousDetailPanels").innerHTML = [
    `<div class="stage-card"><strong>证据风险</strong><p>${labelOf(panels.evidence_risk_panel?.evidence_strength_label || "--")} / ${labelOf(panels.evidence_risk_panel?.hard_defect_public_label || "--")}</p>${badge((panels.evidence_risk_panel?.review_items || []).length + " 项复核")}</div>`,
    `<div class="stage-card"><strong>商业钩子</strong><p>${panels.commercial_hook_panel?.teaser_copy || first.commercial_hook_teaser || "--"}</p>${badge(panels.commercial_hook_panel?.disclosure_level || "--")}</div>`,
    `<div class="stage-card"><strong>买家排序</strong><p>${(panels.buyer_ranking_panel?.buyer_rankings || []).map((row) => `${row.rank}.${labelOf(row.buyer_type || "--")}`).join(" / ") || "--"}</p>${badge("匹配分 " + (panels.buyer_ranking_panel?.buyer_fit_score || "--"))}</div>`,
    `<div class="stage-card"><strong>交付状态</strong><p>${labelOf(panels.delivery_state_panel?.delivery_state || "--")} / ${panels.delivery_state_panel?.page_draft_id || "--"}</p>${badge(panels.delivery_state_panel?.delivery_ready ? "可交付" : "待审批", panels.delivery_state_panel?.delivery_ready ? "" : "warn")}</div>`,
    `<div class="stage-card"><strong>下一步动作</strong><p>${labelOf(panels.sales_next_action_panel?.next_action || first.next_action || "--")}</p>${badge(panels.sales_next_action_panel?.quote_surface_state || "--")}</div>`
  ].join("");
  return payload;
}
let lastRealSourceSnapshotId = "";
function fillSelect(id, items, labelBuilder) {
  const select = $(id);
  select.innerHTML = "";
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.profile_id;
    option.textContent = labelBuilder(item);
    select.appendChild(option);
  }
}
async function loadRegionAdapters() {
  const catalog = await json("GET", "/operator-console/region-adapters");
  const adapters = catalog.region_adapters || [];
  const select = $("searchRegion");
  select.innerHTML = "";
  for (const adapter of adapters) {
    const option = document.createElement("option");
    option.value = adapter.region_code;
    option.textContent = `${adapter.region_code} | ${adapter.region_name} | ${labelOf(adapter.adapter_state)}`;
    option.selected = adapter.region_code === "CN-GD";
    select.appendChild(option);
  }
  if (!selectedValues("searchRegion").length && select.options.length) {
    select.options[0].selected = true;
  }
  renderSelectChoices("searchRegion", "searchRegionChoices");
  const searchableCount = (catalog.searchable_region_codes || []).length;
  const dedicatedCount = (catalog.dedicated_local_profile_region_codes || []).length;
  const localGap = adapters.filter((adapter) => adapter.onboarding_required && adapter.commercial_pilot_region);
  $("regionCoverageSummary").innerHTML = [
    `<div class="metric"><strong>${searchableCount}</strong><span>可搜索地区</span></div>`,
    `<div class="metric"><strong>${dedicatedCount}</strong><span>本地专用入口</span></div>`,
    `<div class="metric"><strong>${localGap.length}</strong><span>商业试点待补</span></div>`
  ].join("");
  $("regionCoverageNarrative").textContent = `登记 ${adapters.length} 个地区；商业试点 ${catalog.commercial_pilot_region_codes?.length || 0} 个；${localGap.length} 个商业试点本省实时源待补，全国平台只用于全国搜索。`;
  const rows = adapters.slice(0, 8).map((adapter) => {
    const gaps = Array.isArray(adapter.coverage_gap_signals) ? adapter.coverage_gap_signals : [];
    const flags = [
      badge(adapter.dedicated_local_profiles ? "本省实时源" : "本省源待补", adapter.dedicated_local_profiles ? "" : "warn"),
      badge(adapter.commercial_pilot_region ? "商业试点" : "非试点"),
      badge(adapter.onboarding_required ? "待补本地配置" : "配置就绪", adapter.onboarding_required ? "warn" : ""),
      badge(gaps.length ? `覆盖缺口 ${gaps.length}` : "无覆盖缺口", gaps.length ? "warn" : "")
    ].join("");
    return `<div class="stage-card">
      <strong>${adapter.region_code} ${adapter.region_name}</strong>
      <p>主入口：${adapter.primary_entry_profile_id || "--"}；备用入口：${(adapter.fallback_entry_profile_ids || []).join(" / ") || "无"}</p>
      ${flags}
      <p><strong>失败分类</strong> ${gaps.length ? gaps.map(labelOf).join(" / ") : "当前无登记缺口"}</p>
      <p><strong>下一步</strong> ${adapter.onboarding_required ? "先验真本省官网是否有实时公告列表，再登记 profile、详情页和附件入口。" : "保持真实源诊断和后续详情页抓取验证。"}</p>
    </div>`;
  }).join("");
  $("regionAdapterSummary").className = rows ? "compact-card-grid" : "empty-state";
  $("regionAdapterSummary").innerHTML = rows || "暂无地区适配器。";
  return catalog;
}
async function loadAutonomousSearchRuns() {
  const payload = await json("GET", "/operator-console/autonomous-search-runs");
  const runs = payload.runs || [];
  updateCustomerPortalLink(payload.latest_opportunity_id || runs[0]?.opportunity_id || "");
  const collapsed = Number(payload.duplicate_collapsed_count || 0);
  const updatedAt = payload.last_updated_at || payload.latest_completed_at || payload.latest_requested_at || "暂无运行";
  $("autonomousSearchRunMeta").textContent = collapsed
    ? `展示最新 ${runs.length} 条搜索记录，已合并 ${collapsed} 条重复运行记录。`
    : `展示最新 ${runs.length} 条搜索记录。`;
  $("autonomousSearchPersistence").textContent = `数据来源：${payload.data_source || "OperatorActionRepository"}；原始记录 ${payload.raw_run_count ?? 0} 条，当前搜索记录 ${payload.run_count ?? runs.length} 条；保留状态：${labelOf(payload.retention_state || "PERSISTED_UNTIL_EXPLICIT_OPERATOR_CLEAR")}；最近更新时间：${updatedAt}；清空必须点击“清空测试搜索记录”。`;
  if (!runs.length) {
    $("autonomousSearchRuns").className = "empty-state";
    $("autonomousSearchRuns").textContent = "暂无实战搜索运行记录。";
    renderStageOverviewTelemetry();
    return payload;
  }
  const latestRun = runs[0];
  if (latestRun?.opportunity_id && !selectedAutonomousOpportunityId) {
    selectedAutonomousOpportunityId = latestRun.opportunity_id;
  }
  renderSearchResultFromRun(latestRun);
  if (payload.latest_runtime_flow?.stage_stats || latestRun?.runtime_flow?.stage_stats) {
    renderStageOverviewTelemetry(payload.latest_runtime_flow?.stage_stats ? payload.latest_runtime_flow : latestRun.runtime_flow);
  }
  $("autonomousSearchRuns").className = "compact-card-grid";
  $("autonomousSearchRuns").innerHTML = runs.slice(0, 8).map((run) => {
    const sampleMode = isOfflineSample(run);
    const links = [
      run.opportunity_id ? `<a href="#autonomousWorkbench" data-workbench-opportunity="${run.opportunity_id}">工作台</a>` : "",
      run.opportunity_id ? `<a href="/customer-artifact-portal/${encodeURIComponent(run.opportunity_id)}">证据包预览</a>` : ""
    ].filter(Boolean).join(" · ");
    return `<div class="stage-card">
      <strong>${sampleMode && run.opportunity_id ? "样本闭环 " + run.opportunity_id : (run.opportunity_id || "--")}</strong>
      <p>${run.project_name || run.query || "--"}</p>
      ${badge(run.search_state || "--", run.search_state === "AUTONOMOUS_SEARCH_ACCEPTED" ? "" : "warn")}
      ${badge(sourceModeOf(run) || "--", sampleMode ? "warn" : "")}
      ${badge(run.region_code || "--")}
      ${badge(run.entry_profile_id || "--")}
      <p>${labelOf(run.project_type_label || run.project_type)} · ${amountRangeText(run.amount_range || {minimum: run.amount_min, maximum: run.amount_max})}</p>
      <p>候选 ${run.search_scope?.candidate_count ?? (run.candidate_options || []).length ?? 0} · 闭环 ${run.search_scope?.closed_loop_generated_count ?? (run.opportunity_id ? 1 : 0)}</p>
      <p>${links || "读回路径待生成"}</p>
    </div>`;
  }).join("");
  return payload;
}
function rejectedCountsText(counts) {
  const entries = Object.entries(counts || {});
  if (!entries.length) { return "无剔除统计"; }
  return entries.map(([key, value]) => `${reasonLabel(key)} ${value}`).join(" / ");
}
async function loadRealCandidateDiscoveryDiagnostics() {
  const payload = await json("GET", "/operator-console/real-candidate-discovery-runs");
  const runs = payload.runs || [];
  const latest = runs[0] || {};
  const reports = latest.profile_reports || [];
  const summary = latest.candidate_discovery_diagnostics || {};
  $("realCandidateDiscoveryDiagnosticsMeta").textContent = runs.length
    ? `最近发现批次：${latest.discovery_run_id || "--"}；状态：${labelOf(latest.discovery_state || "--")}；候选 ${latest.candidate_count ?? 0} 条；${summary.headline || "诊断待生成"}`
    : "暂无真实候选发现运行记录。";
  if (!runs.length || !reports.length) {
    $("realCandidateDiscoveryDiagnostics").className = "empty-state";
    $("realCandidateDiscoveryDiagnostics").textContent = "暂无发现诊断；运行实战搜索后会显示每个来源为什么没有产出候选。";
    return payload;
  }
  $("realCandidateDiscoveryDiagnostics").className = "compact-card-grid";
  $("realCandidateDiscoveryDiagnostics").innerHTML = reports.map((report) => {
    const diagnostics = report.candidate_diagnostics || {};
    const diagnosis = diagnostics.operator_diagnosis || report.operator_diagnosis || [];
    const rejectedSamples = diagnostics.rejected_samples || [];
    const sampleText = rejectedSamples.slice(0, 3).map((sample) => {
      const title = safeText(sample.title || sample.url || "--");
      return `${reasonLabel(sample.reason)}：${title}`;
    }).join("<br>");
    return `<div class="stage-card">
      <strong>${safeText(report.profile_id || "--")}</strong>
      ${badge(report.status || "--", report.status === "FETCHED" ? "" : "warn")}
      ${badge(`链接 ${diagnostics.link_item_count ?? report.same_site_detail_link_count ?? 0}`)}
      ${badge(`候选 ${report.candidate_count ?? 0}`, (report.candidate_count ?? 0) ? "" : "warn")}
      <p><strong>来源</strong> ${report.entry_url ? `<a href="${safeText(report.entry_url)}" target="_blank" rel="noopener">${safeText(report.entry_url)}</a>` : "--"}</p>
      <p><strong>诊断</strong> ${(diagnosis || []).map(reasonLabel).join(" / ") || "暂无诊断"}</p>
      <p><strong>剔除统计</strong> ${safeText(rejectedCountsText(diagnostics.rejected_counts || report.rejected_counts || {}))}</p>
      <p><strong>下一步</strong> ${safeText(report.next_action || diagnostics.next_action || "查看来源快照和列表链接样本。")}</p>
      ${sampleText ? `<p><strong>样例</strong><br>${sampleText}</p>` : ""}
    </div>`;
  }).join("");
  return payload;
}
async function loadRealCandidateCatalog() {
  const payload = await json("GET", "/operator-console/real-candidates");
  const rows = payload.candidates || [];
  $("realCandidateCatalogMeta").textContent = `数据来源：${payload.data_source || "OperatorActionRepository"}；去重后 ${payload.candidate_count ?? rows.length} 条，原始事件 ${payload.raw_candidate_event_count ?? 0} 条，已合并重复 ${payload.duplicate_collapsed_count ?? 0} 条。刷新网页不会自动清空。`;
  if (!rows.length) {
    $("realCandidateCatalog").className = "empty-state";
    $("realCandidateCatalog").textContent = "暂无已入库真实候选；运行实战搜索后会显示真实列表页候选、来源网址、快照和去重状态。";
    return payload;
  }
  $("realCandidateCatalog").className = "compact-card-grid";
  $("realCandidateCatalog").innerHTML = rows.slice(0, 12).map((candidate) => `
    <div class="stage-card">
      <strong>${safeText(candidate.project_name || candidate.project_id || "--")}</strong>
      <p>${safeText(candidate.region_name || candidate.region_code || "--")} · ${safeText(labelOf(candidate.project_type || "--"))} · ${safeText(amountRangeText(candidateRange(candidate)))}</p>
      ${badge(candidate.dedupe_decision || "已入库")}
      ${badge(candidate.source_profile_id || "来源待补", candidate.source_profile_id ? "" : "warn")}
      ${badge(candidate.snapshot_id_optional ? "列表页快照已绑定" : "列表页快照待绑定", candidate.snapshot_id_optional ? "" : "warn")}
      ${candidate.stage2_detail_snapshot_id_optional ? badge("详情快照已绑定") : ""}
      <p><strong>来源</strong> ${candidate.source_url ? `<a href="${safeText(candidate.source_url)}" target="_blank" rel="noopener">${safeText(candidate.source_site_name || candidate.source_url)}</a>` : "来源网址待补"}</p>
      <p><strong>下一步</strong> 查看详情快照读回，把真实详情字段和附件线索送入后续证据回链。</p>
    </div>
  `).join("");
  return payload;
}
async function loadRealCandidateStage2Captures() {
  const payload = await json("GET", "/operator-console/real-candidate-stage2-captures");
  const rows = payload.captures || [];
  $("realCandidateStage2CaptureMeta").textContent = `数据来源：${payload.data_source || "OperatorActionRepository"}；候选详情 ${payload.capture_count ?? rows.length} 条，原始事件 ${payload.raw_capture_event_count ?? 0} 条，已合并重复 ${payload.duplicate_collapsed_count ?? 0} 条。`;
  if (!rows.length) {
    $("realCandidateStage2Captures").className = "empty-state";
    $("realCandidateStage2Captures").textContent = "暂无详情页快照；运行实战搜索后会自动尝试抓取真实候选详情页并保存快照。";
    return payload;
  }
  $("realCandidateStage2Captures").className = "compact-card-grid";
  $("realCandidateStage2Captures").innerHTML = rows.slice(0, 12).map((capture) => `
    <div class="stage-card">
      <strong>${safeText(capture.project_name || capture.project_id || "--")}</strong>
      ${badge(capture.detail_capture_status || "--", capture.detail_snapshot_id_optional ? "" : "warn")}
      ${badge(capture.stage3_parse_state || "--", String(capture.stage3_parse_state || "").startsWith("PARSED") ? "" : "warn")}
      ${badge(`附件线索 ${capture.attachment_link_count ?? 0}`)}
      ${badge(`附件快照 ${capture.attachment_snapshot_count ?? 0}`, (capture.attachment_snapshot_count ?? 0) ? "" : "warn")}
      <p><strong>来源</strong> ${capture.source_url ? `<a href="${safeText(capture.source_url)}" target="_blank" rel="noopener">${safeText(capture.source_url)}</a>` : "来源网址待补"}</p>
      <p><strong>快照</strong> ${capture.detail_snapshot_id_optional ? `<a href="/operator-console/real-source-runs/${encodeURIComponent(capture.detail_snapshot_id_optional)}" target="_blank" rel="noopener">${safeText(capture.detail_snapshot_id_optional)}</a>` : "未生成快照"}</p>
      ${capture.attachment_captures && capture.attachment_captures.length ? `<p><strong>附件原文</strong> ${capture.attachment_captures.map((item) => item.attachment_snapshot_id_optional ? `<a href="/operator-console/real-source-runs/${encodeURIComponent(item.attachment_snapshot_id_optional)}" target="_blank" rel="noopener">${safeText(item.attachment_filename || item.attachment_snapshot_id_optional)}</a>` : safeText(item.attachment_capture_status || "未生成附件快照")).join("、")}</p>` : ""}
      <p><strong>解析字段</strong> ${safeText((capture.detail_fields && capture.detail_fields.project_name) || capture.detail_title || "--")}</p>
    </div>
  `).join("");
  return payload;
}
async function clearAutonomousSearchRuns() {
  const confirmed = window.confirm("只清空本地测试搜索运行记录，不影响机会、证据包或真实外部系统。确认清空？");
  if (!confirmed) { return; }
  const result = await json("POST", "/operator-console/autonomous-search-runs/clear", {
    clear_scope: "local_test_autonomous_search_runs_only",
    explicit_operator_action: true,
    now: new Date().toISOString()
  });
  out(result);
  await loadAutonomousSearchRuns();
  await loadRealWorldSellability();
}
async function loadRealSourceProfiles() {
  const catalog = await json("GET", "/operator-console/real-source-profiles");
  fillSelect("entryProfile", catalog.entry_profiles || [], (item) => `${item.profile_id} | ${item.site_name}`);
  fillSelect("attachmentProfile", catalog.attachment_profiles || [], (item) => `${item.profile_id} | ${item.site_name}`);
  return catalog;
}
async function createTask() {
  const payload = { task_id: $("taskId").value, project_id: $("projectId").value, now: new Date().toISOString() };
  const result = await json("POST", "/operator-console/tasks", payload);
  out(result);
  await loadReadiness(false);
  renderStageOverviewTelemetry({
    direction: "内部任务发起 -> 队列调度 -> 阶段2交接意图 -> 后续采集/闭环",
    stage_stats: [
      {
        stage: 1,
        name: "调度 / 任务入队",
        state: result.scheduler_task?.status || "queued",
        input_count: 1,
        output_count: 1,
        produced_count: 1,
        effective_count: 1,
        invalid_count: 0,
        note: `任务 ${result.scheduler_task?.task_id || payload.task_id} 已进入内部队列。`,
        object_refs: {
          task_id: result.scheduler_task?.task_id || payload.task_id,
          project_id: result.scheduler_task?.project_id || payload.project_id,
          queue_item_id: result.scheduler_task?.queue_item_id,
          source_registry_id: result.scheduler_task?.source_registry_id,
          route_policy_id: result.scheduler_task?.route_policy_id,
        },
        failure_reasons: result.scheduler_task?.conflict_reasons || [],
        next_action: "等待内部 worker 或后续采集运行消费；当前不会真实外部抓取。",
      },
      {
        stage: 2,
        name: "阶段2交接意图",
        state: result.stage2_handoff_intent?.intent_state || "STAGE2_HANDOFF_READY",
        input_count: 1,
        output_count: 1,
        produced_count: 1,
        effective_count: 1,
        invalid_count: 0,
        note: "阶段2交接对象已生成，但真实外部抓取默认关闭。",
        object_refs: {
          handoff_id: result.stage2_handoff_intent?.handoff_id,
          queue_item_id: result.scheduler_task?.queue_item_id,
        },
        failure_reasons: [],
        next_action: "如需采集，进入“采集运行”选择公开源入口执行受控抓取。",
      }
    ],
    totals: { stage_count: 2, produced_count: 2, effective_count: 2, invalid_count: 0 },
    logs: [
      `已创建内部任务 ${result.scheduler_task?.task_id || payload.task_id}。`,
      `队列编号 ${result.scheduler_task?.queue_item_id || "--"}，状态 ${labelOf(result.scheduler_task?.status || "queued")}。`,
      "真实外部抓取、真实触达、真实支付和真实交付均未执行。",
    ],
  });
  showView("overview");
  history.replaceState(null, "", "#overview");
}
async function importProject() {
  const payload = { project_id: $("projectId").value, source_mode: "INTERNAL_PROJECT_IMPORT", now: new Date().toISOString() };
  const result = await json("POST", "/operator-console/project-imports", payload);
  out(result);
  await loadReadiness(false);
  showView("overview");
  history.replaceState(null, "", "#overview");
}
async function runAutonomousSearch() {
  const button = $("runAutonomousSearch");
  const regionCodes = selectedValues("searchRegion");
  const projectTypes = selectedValues("searchProjectType");
  const amountMin = amountWanToYuan($("searchAmountMinWan").value, 1000000);
  const amountMax = amountWanToYuan($("searchAmountMaxWan").value, 30000000);
  const normalizedMin = Math.min(amountMin, amountMax);
  const normalizedMax = Math.max(amountMin, amountMax);
  const payload = {
    region_code: regionCodes[0] || $("searchRegion").value,
    region_codes: regionCodes,
    query: $("searchKeyword").value,
    project_type: projectTypes[0] || $("searchProjectType").value,
    project_types: projectTypes,
    amount: normalizedMax,
    amount_min: normalizedMin,
    amount_max: normalizedMax,
    minimum_amount: normalizedMin,
    maximum_amount: normalizedMax,
    allow_offline_sample_candidates: Boolean($("offlineSampleCandidates")?.checked),
    now: new Date().toISOString()
  };
  button.disabled = true;
  button.textContent = "搜索运行中...";
  $("searchResult").className = "empty-state";
  $("searchResult").textContent = "正在生成机会、工作台和客户材料候选...";
  try {
    const result = await json("POST", "/operator-console/autonomous-opportunity-search", payload);
    selectedAutonomousOpportunityId = result.opportunity_id || "";
    updateCustomerPortalLink(selectedAutonomousOpportunityId);
    $("searchResult").className = "";
    renderSearchResultFromRun({
      run_id: result.search_run_id,
      search_state: result.search_state,
      opportunity_id: result.opportunity_id,
      project_name: result.candidate?.project_name,
      query: result.candidate?.project_name || payload.query,
      region_code: result.region_adapter?.region_code,
      project_type: result.candidate?.project_type,
      project_type_label: result.candidate?.project_type_label,
      amount_range: result.amount_range,
      search_scope: result.search_scope,
      source_candidate_mode: result.source_candidate_mode,
      offline_sample_validation: result.data_boundary?.offline_sample_validation,
      real_market_discovery: result.data_boundary?.real_market_discovery,
      display_message: result.display_message || result.data_boundary?.display_message,
      data_boundary: result.data_boundary,
      candidate_options: result.candidate_options || []
    });
    out({
      search_state: result.search_state,
      opportunity_id: result.opportunity_id,
      search_run_id: result.search_run_id,
      region_code: result.region_adapter?.region_code,
      entry_profile_id: result.entry_profile?.profile_id,
      amount_range: result.amount_range,
      workbench: result.operator_workbench_readback_path,
      customer_artifact_candidate: result.customer_artifact_candidate_path,
      raw_json_required: false
    });
    renderStageOverviewTelemetry(result.runtime_flow);
    await loadRealCandidateDiscoveryDiagnostics();
    await loadRealCandidateCatalog();
    await loadRealCandidateStage2Captures();
    await loadAutonomousSearchRuns();
    await loadAutonomousWorkbench(selectedAutonomousOpportunityId);
    return result;
  } catch (err) {
    $("searchResult").className = "empty-state";
    $("searchResult").textContent = "搜索失败，请查看操作结果。";
    out(err);
    throw err;
  } finally {
    button.disabled = false;
    button.textContent = "搜索并生成机会闭环";
  }
}
async function previewRun() {
  let payload = {};
  try { payload = JSON.parse($("payload").value); } catch (err) { out({ error: "运行参数不是有效JSON", detail: String(err) }); return; }
  out({ entry: "/internal/stage1-6/orchestrations", accepted_payload: payload, live_execution_enabled: false, display_message: "仅检查内部运行入口，不执行真实外部动作。" });
}
async function runControlledSample() {
  let payload = {};
  try { payload = JSON.parse($("payload").value); } catch (err) { out({ error: "运行参数不是有效JSON", detail: String(err) }); return; }
  payload.payload_boundary = "SANITIZED_OFFLINE_INTERNAL";
  payload.source_mode = payload.source_mode || "OFFLINE_FIXTURE";
  payload.run_mode = payload.run_mode || "DRY_RUN";
  payload.live_execution_enabled = false;
  const result = await json("POST", "/internal/stage1-6/orchestrations", payload);
  $("workbenchStatus").innerHTML = [
    badge(`阶段6 已持久化 ${result.stage6_persisted ? "是" : "否"}`),
    badge(`项目 ${result.stage6_project_id || "--"}`),
    badge("真实执行已关闭", "warn")
  ].join("");
  out(result);
}
async function runEntryCapture() {
  const result = await json("POST", "/operator-console/real-source-runs", {
    capture_kind: "entry",
    profile_id: $("entryProfile").value,
    task_id: $("taskId").value,
    project_id: $("projectId").value
  });
  lastRealSourceSnapshotId = result.snapshot_id_optional || "";
  await loadRealSourceRuns();
  out(result);
}
async function runAttachmentCapture() {
  const result = await json("POST", "/operator-console/real-source-runs", {
    capture_kind: "attachment",
    profile_id: $("attachmentProfile").value,
    task_id: $("taskId").value,
    project_id: $("projectId").value
  });
  lastRealSourceSnapshotId = result.snapshot_id_optional || "";
  await loadRealSourceRuns();
  out(result);
}
async function readLatestSourceCapture() {
  if (!lastRealSourceSnapshotId) {
    out({ error: "missing_snapshot_id", detail: "请先执行入口页或附件抓取。" });
    return;
  }
  out(await json("GET", `/operator-console/real-source-runs/${encodeURIComponent(lastRealSourceSnapshotId)}`));
}
async function loadRealSourceRuns() {
  const payload = await json("GET", "/operator-console/real-source-task-runs");
  const runs = payload.runs || [];
  if (!runs.length) {
    $("realSourceRunList").className = "empty-state";
    $("realSourceRunList").textContent = "暂无真实源任务运行记录。";
    return payload;
  }
  $("realSourceRunList").className = "";
  $("realSourceRunList").innerHTML = runs.slice(0, 8).map((run) => {
    const snapshot = run.snapshot_id_optional || "--";
    return `<div class="metric"><strong>${run.profile_id || "--"}</strong><span>${run.capture_kind || "--"} | ${run.status || "--"} | ${snapshot}</span></div>`;
  }).join("");
  return payload;
}
$("createTask").addEventListener("click", createTask);
$("importProject").addEventListener("click", importProject);
$("runAutonomousSearch").addEventListener("click", runAutonomousSearch);
$("selectAllRegions").addEventListener("click", () => setAllSelected("searchRegion", true));
$("clearRegions").addEventListener("click", () => setAllSelected("searchRegion", false));
$("selectAllProjectTypes").addEventListener("click", () => setAllSelected("searchProjectType", true));
$("clearProjectTypes").addEventListener("click", () => setAllSelected("searchProjectType", false));
$("refreshAutonomousSearchRuns").addEventListener("click", async () => out(await loadAutonomousSearchRuns()));
$("clearAutonomousSearchRuns").addEventListener("click", clearAutonomousSearchRuns);
$("refreshRealCandidateDiscoveryDiagnostics").addEventListener("click", async () => out(await loadRealCandidateDiscoveryDiagnostics()));
$("refreshRealCandidateCatalog").addEventListener("click", async () => out(await loadRealCandidateCatalog()));
$("refreshRealCandidateStage2Captures").addEventListener("click", async () => out(await loadRealCandidateStage2Captures()));
$("runEntryCapture").addEventListener("click", runEntryCapture);
$("runAttachmentCapture").addEventListener("click", runAttachmentCapture);
$("readLatestSourceCapture").addEventListener("click", readLatestSourceCapture);
$("refreshRealSourceRuns").addEventListener("click", async () => out(await loadRealSourceRuns()));
$("previewRun").addEventListener("click", previewRun);
$("runControlledSample").addEventListener("click", runControlledSample);
$("refreshWorkbench").addEventListener("click", loadReadiness);
$("refreshAutonomousWorkbench").addEventListener("click", async () => out(await loadAutonomousWorkbench()));
$("refreshSystemRelease").addEventListener("click", loadReadiness);
document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-workbench-opportunity]");
  if (!target) { return; }
  event.preventDefault();
  selectedAutonomousOpportunityId = target.dataset.workbenchOpportunity || "";
  showView("autonomousWorkbench");
  history.replaceState(null, "", "#autonomousWorkbench");
  await loadAutonomousWorkbench(selectedAutonomousOpportunityId);
});
document.querySelectorAll("[data-view]").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    const view = item.dataset.view;
    showView(view);
    history.replaceState(null, "", `#${view}`);
  });
});
window.addEventListener("hashchange", () => showView((window.location.hash || "#overview").slice(1)));
showView((window.location.hash || "#overview").slice(1));
renderStageOverviewTelemetry();
renderSelectChoices("searchProjectType", "searchProjectTypeChoices");
Promise.all([loadReadiness(false), loadAutonomousWorkbench(), loadRegionAdapters(), loadAutonomousSearchRuns(), loadRealCandidateDiscoveryDiagnostics(), loadRealCandidateCatalog(), loadRealCandidateStage2Captures(), loadRealSourceProfiles(), loadRealSourceRuns(), loadUserAcceptanceContract(), loadAcceptanceGapMatrix(), loadRealWorldSellability(), loadStage6ReviewLoopStatus()])
  .then(() => { $("output").textContent = "等待操作..."; })
  .catch(out);
"""
    return _page("AX9S 运营操作台", body, script)


def render_customer_artifact_portal(payload: dict[str, Any]) -> HTMLResponse:
    opportunity_id = escape(str(payload.get("opportunity_id") or ""))
    body = f"""
<div class="layout">
  <nav aria-label="证据包预览导航">
    <h1>AX9S 内部证据包预览</h1>
    <a href="/operator-console">运营操作台</a>
    <a href="#artifact">证据包</a>
    <a href="#mail">拟邮件包</a>
    <a href="#access">访问控制</a>
    <a href="#audit">下载审计</a>
  </nav>
  <main>
    <div class="topbar">
      <div>
        <h2>内部证据包预览 / 交付材料验收</h2>
        <p>商机 <strong id="opportunity">{opportunity_id}</strong></p>
      </div>
      <div class="status" id="portalSummary">正在读取证据包候选...</div>
    </div>
    <div class="grid">
      <section id="artifact">
        <h3>证据包状态</h3>
        <div id="artifactState"></div>
      </section>
      <section id="mail">
        <h3>拟邮件发送包</h3>
        <div id="mailPackagePreview"></div>
      </section>
      <section id="access">
        <h3>测试访问状态</h3>
        <div id="accessState"></div>
      </section>
      <section>
        <h3>字段策略</h3>
        <div id="fieldState"></div>
      </section>
      <section id="audit">
        <h3>下载审计</h3>
        <div id="auditState"></div>
      </section>
      <section class="wide">
        <h3>证据包内容</h3>
        <div id="evidencePackagePreview"></div>
      </section>
      <section class="wide">
        <h3>内部预览验收</h3>
        <div id="previewState"></div>
      </section>
      <section class="controlled_opening_requirement wide">
        <h3>测试阶段说明</h3>
        <p>客户未来不使用工作台；成交付款后由系统生成证据包，通过邮件发送。当前页面只给运营方验收证据包内容，不会真实发邮件、打电话、扣款或退款。</p>
      </section>
      <section class="wide">
        <h3>读回摘要</h3>
        <div id="output" class="empty-state summary-list">等待读取...</div>
      </section>
    </div>
  </main>
</div>
"""
    script = f"""
const opportunityId = {opportunity_id!r};
const portalLabels = {{
  "saleable_opportunity_snapshot": "可售机会快照",
  "offer_recommendation_snapshot": "报价建议快照",
  "buyer_fit_summary": "买家匹配摘要",
  "actor_reachability_summary": "可触达对象摘要",
  "crm_quote_workbench_snapshot": "报价工作台快照",
  "stage7_resolution_trace_snapshot": "阶段7决策痕迹摘要",
  "saleable_opportunity": "可售机会",
  "offer_recommendation": "报价建议",
  "buyer_fit": "买家匹配",
  "stage7_actor_profiles": "阶段7联系人画像",
  "crm_quote_workbench": "报价工作台",
  "stage7_resolution_trace": "阶段7决策痕迹",
  "QUALIFIED": "合格机会",
  "APPROVED": "已通过",
  "GOVERNMENT": "政府/采购主管",
  "REACHABLE": "可触达",
  "TRACE_PRESENT": "痕迹已记录",
  "READY": "已就绪",
  "allowed_projection": "允许展示摘要",
  "summary_only": "仅摘要",
  "masked_projection": "脱敏展示",
  "internal_summary_only": "仅内部摘要",
  "internal_trace_summary": "内部痕迹摘要",
  "READBACK_READY": "读回就绪",
  "MASKING_REQUIRED": "需要脱敏",
  "SANDBOX_CANDIDATE_READY": "测试候选已就绪",
  "PAGE_DRAFT_ONLY": "仅页面草稿",
  "REPLAY_READY": "可回放",
  "APPLIED_TO_DRAFT": "已加到草稿",
  "INTERNAL DRAFT - NOT CUSTOMER RELEASED": "内部草稿，未发客户",
  "MISSING": "未接入/未生成",
  "stage7.saleable_opportunity": "阶段7可售机会",
  "stage7.offer_recommendation": "阶段7报价建议",
  "stage7.buyer_fit": "阶段7买家匹配",
  "stage7.legal_action_actor_profile": "阶段7法务行动方画像",
  "stage7.procurement_decision_actor_profile": "阶段7采购决策方画像",
  "stage7.crm_quote_workbench": "阶段7报价工作台",
  "stage7_resolution_trace.review_gate_report_constraints": "复核门报告约束",
  "stage7_resolution_trace.opportunity_policy": "机会判断策略",
  "stage7_resolution_trace.price_resolution": "价格判断痕迹",
  "stage7_resolution_trace.formal_sink_projection": "正式输出投影",
  "CONSTRUCTION": "房建工程",
  "CUSTOMER": "客户",
  "DRAFT": "草稿",
  "INTERNAL": "内部",
  "JSON": "结构化数据",
  "RELEASED": "已发布",
  "SEARCH": "搜索",
  "source_url": "公开来源网址",
  "source_site_name": "公开来源名称",
  "source_profile_id": "来源配置编号",
  "source_refs": "来源引用",
  "source_object": "来源对象",
  "source_id": "来源对象编号",
  "item_id": "证据项编号",
  "manifest_state": "清单状态",
  "masking_policy": "脱敏策略",
  "package_manifest": "证据包清单",
  "page_draft": "页面草稿",
  "page_draft_id": "页面草稿编号",
  "artifact_manifest_id": "清单编号",
  "artifact_version_hash": "版本哈希",
  "evidence_pack_id": "证据包编号",
  "package_id": "交付包编号",
  "watermark": "水印",
  "watermark_text": "水印文字",
  "project_name": "项目名称",
  "region_name": "地区",
  "project_type_label": "项目类型",
  "verification_hint": "验证口径",
  "allowlist_enforced": "字段白名单已执行",
  "masking_required": "需要脱敏",
  "internal_blackbox_fields_exposed": "内部黑箱字段已暴露",
  "auth_required": "需要授权",
  "customer_download_enabled": "客户自助下载已开放",
  "download_enabled": "下载已开放",
  "NO_CANDIDATES": "未发现候选",
  "REAL_SOURCE_REQUIRED": "需要真实来源候选",
  "OFFLINE_SAMPLE_CANDIDATES": "离线样本候选",
  "EXPLICIT_CANDIDATES": "显式候选",
}};
function labelOf(value) {{
  const text = String(value ?? "--");
  return portalLabels[text] || text;
}}
function badge(text, kind="") {{ return `<span class="pill ${{kind}}">${{labelOf(text)}}</span>`; }}
function safeText(value) {{
  return String(value ?? "--")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}}
function scalarText(value) {{
  if (value === undefined || value === null || value === "") {{ return "--"; }}
  if (Array.isArray(value)) {{ return value.length ? value.map(scalarText).join(" / ") : "--"; }}
  if (value && typeof value === "object") {{ return objectSummary(value); }}
  return labelOf(value);
}}
function objectSummary(value) {{
  const entries = Object.entries(value || {{}})
    .filter(([, item]) => item !== undefined && item !== null && String(item).length);
  if (!entries.length) {{ return "--"; }}
  return entries
    .slice(0, 8)
    .map(([key, item]) => `${{labelOf(key)}}：${{scalarText(item)}}`)
    .join("；");
}}
function valueText(value) {{
  return scalarText(value);
}}
function valueHtml(value) {{
  const text = valueText(value);
  if (/^https?:\/\//.test(text)) {{
    return `<a href="${{safeText(text)}}" target="_blank" rel="noopener">${{safeText(text)}}</a>`;
  }}
  return safeText(text);
}}
function rowsHtml(rows) {{
  return `<div class="detail-table">${{rows
    .filter(([, value]) => value !== undefined && value !== null && String(value).length)
    .map(([label, value]) => `<div class="detail-row"><strong>${{label}}</strong><span>${{valueHtml(value)}}</span></div>`)
    .join("")}}</div>`;
}}
function evidenceItemsHtml(items, sampleMode=false, customerJudgement="") {{
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {{ return `<div class="empty-state">暂无证据项读回。</div>`; }}
  return `<div class="compact-card-grid">${{rows.map((item) => `
    <div class="stage-card">
      <strong>${{labelOf(item.item_id || item.source_object || "--")}}</strong>
      <p>证据类型：${{labelOf(item.item_id || "--")}}</p>
      <p>线索类型：${{labelOf(item.source_object || "--")}}</p>
      ${{sampleMode ? badge("样本证据项，非客户交付", "warn") : ""}}
      <p>来源对象：${{valueText(item.source_id)}}</p>
      ${{badge(item.manifest_state || item.status || "--", item.present === false ? "warn" : "")}}
      ${{badge(item.masking_policy || "--")}}
      <p>客户交付判断：${{safeText(customerJudgement || "客户交付前需要完成真实来源核验。")}}</p>
      <p>来源引用：${{valueText(item.source_refs)}}</p>
      <p>公开来源：${{item.source_url ? `<a href="${{safeText(item.source_url)}}" target="_blank" rel="noopener">${{safeText(item.source_site_name || item.source_profile_id || item.source_url)}}</a>` : "来源网址待读回"}}</p>
    </div>
  `).join("")}}</div>`;
}}
function renderEvidencePackage(payload, missing=false) {{
  const formal = payload?.source_formal_client_export_page_layer_readiness || {{}};
  const sourceVerification = payload?.source_verification || {{}};
  const dataBoundary = payload?.data_boundary || {{}};
  const readback = payload?.customer_artifact_readback || {{}};
  const manifest = formal.package_manifest || {{}};
  const pageDraft = formal.page_draft || {{}};
  const sourceUrl = sourceVerification.source_url || "";
  const sampleMode = dataBoundary["是否离线样本"] === true;
  const customerJudgement = dataBoundary["客户可交付判断"] || "";
  const evidenceItems = (manifest.evidence_items || []).map((item) => ({{
    ...item,
    source_url: item.source_url || sourceUrl,
    source_site_name: item.source_site_name || sourceVerification.source_site_name,
    source_profile_id: item.source_profile_id || sourceVerification.source_profile_id,
  }}));
  const watermark = readback.watermark || formal.watermark || {{}};
  const hash = readback.artifact_version_hash || formal.artifact_version_hash || "--";
  if (missing) {{
    document.getElementById("mailPackagePreview").innerHTML = `<div class="empty-state">还没有可预览的拟邮件证据包。</div>`;
    document.getElementById("evidencePackagePreview").innerHTML = `<div class="empty-state">还没有证据项清单。</div>`;
    return;
  }}
  document.getElementById("artifactState").innerHTML = rowsHtml([
    ["证据包", readback.evidence_pack_id],
    ["交付包", readback.package_id],
    ["清单", readback.artifact_manifest_id],
    ["版本哈希", hash],
    ["水印", labelOf(watermark.watermark_text || "INTERNAL DRAFT")],
    ["页面草稿", pageDraft.page_draft_id],
    ["项目名称", sourceVerification.project_name],
    ["公开来源", sourceVerification.source_site_name || sourceVerification.source_profile_id],
    ["来源网址", sourceVerification.source_url],
    ["验证口径", sourceVerification.verification_hint],
    ["数据模式", dataBoundary["数据模式"]],
    ["客户交付判断", dataBoundary["客户可交付判断"]],
    ["来源网址精度", dataBoundary["来源网址精度"]],
  ]);
  document.getElementById("mailPackagePreview").innerHTML = `
    <div class="stage-card">
      <strong>邮件发送包预览</strong>
      <p>主题：证据包交付 - ${{opportunityId}}</p>
      ${{badge("仅内部预览")}}
      ${{badge("真实邮件未接入", "warn")}}
      ${{badge("付款后发送")}}
      <div class="opportunity-actions"><a href="/customer-artifact-portal-download/${{encodeURIComponent(opportunityId)}}">下载内部证据包文件</a></div>
    </div>
    ${{rowsHtml([
      ["附件1", readback.evidence_pack_id || "证据包清单"],
      ["附件2", readback.artifact_manifest_id || "交付清单"],
      ["页面草稿", pageDraft.page_draft_id],
      ["版本哈希", hash],
      ["公开来源", sourceVerification.source_url],
      ["数据真实性", dataBoundary["客户可交付判断"]],
    ])}}
  `;
  document.getElementById("evidencePackagePreview").innerHTML = evidenceItemsHtml(evidenceItems, sampleMode, customerJudgement);
}}
function blockedReasonLabel(reason) {{
  const labels = {{
    "stage7_artifact_readback_missing": "阶段7证据包尚未生成",
    "stage8_stage9_delivery_context_not_required_for_access_candidate_readback": "阶段8/9真实交付上下文未进入内部预览",
    "customer_visible_export_enabled=false": "客户自助页面未开放；内部预览不受影响",
    "client_page_release_enabled=false": "客户自助页面未发布；未来改邮件发送",
    "external_release_enabled=false": "真实外发未接入；内部测试不阻塞",
    "external_delivery_enabled=false": "真实交付未接入；内部测试不阻塞",
    "direct_export_enabled=false": "直接导出未接入；内部预览可看",
    "approval_audit_and_implementation_decision_required_before_live": "真实外发前再做审批审计",
    "customer_account_access_control_required": "客户账号不作为当前内部测试前置",
    "download_auth_required": "客户下载不是当前交付路径；未来走邮件发送",
    "approval_audit_required_before_customer_download": "客户下载不是当前交付路径",
    "public_software_release_not_approved": "不做客户软件发布；内部预览不阻塞",
  }};
  const key = String(reason || "").trim();
  return labels[key] || "待运营复核：" + key.replaceAll("_", " ");
}}
function renderReadbackSummary(payload, missing=false) {{
  const output = document.getElementById("output");
  const downloadAuth = payload?.download_auth || {{}};
  const fieldPolicy = payload?.field_allowlist_masking || {{}};
  const blockedReasons = Array.isArray(payload?.blocked_reasons)
    ? Array.from(new Set(payload.blocked_reasons.map(blockedReasonLabel))).join("；")
    : "无";
  const detail = payload?.detail || payload?.readback_error?.detail || "";
  const rows = [
    ["商机", opportunityId],
    ["读回状态", missing ? "暂无可交付读回" : "已读取客户候选"],
    ["内部预览", missing ? "未形成" : "可查看"],
    ["真实邮件", "未接入，不会触达客户"],
    ["真实下载", "不是当前交付路径"],
    ["客户账号", "不作为内部测试前置"],
    ["模拟下载", downloadAuth.download_enabled ? "可读回" : "可预览读回"],
    ["字段策略", fieldPolicy.allowlist_enforced === false ? "白名单未确认" : "白名单已执行"],
    ["测试说明", blockedReasons],
  ];
  if (detail) {{ rows.push(["读回说明", detail]); }}
  output.className = missing ? "empty-state summary-list" : "summary-list";
  output.replaceChildren();
  rows.forEach(([label, value]) => {{
    const row = document.createElement("div");
    row.className = "summary-row";
    const name = document.createElement("strong");
    name.textContent = label;
    const text = document.createElement("span");
    text.textContent = String(value);
    row.append(name, text);
    output.appendChild(row);
  }});
}}
async function loadPortal() {{
  const response = await fetch(`/customer-artifact-portal-readback/${{encodeURIComponent(opportunityId)}}`);
  const payload = await response.json();
  if (!response.ok || payload.empty_state) {{
    renderMissingArtifact(payload);
    return;
  }}
  document.getElementById("portalSummary").textContent =
    "内部证据包预览已读取；真实邮件、电话、支付、退款服务商未接入，不会触达外部。";
  renderEvidencePackage(payload, false);
  document.getElementById("accessState").innerHTML = [
    badge("内部预览可打开"),
    badge("客户账号不作为测试前置"),
    badge("真实邮件未接入", "warn")
  ].join("");
  document.getElementById("fieldState").innerHTML = [
    badge("字段白名单已执行"),
    badge("脱敏必需"),
    badge("内部黑箱已隐藏")
  ].join("");
  document.getElementById("auditState").innerHTML = [
    badge("内部读回可审计"),
    badge("模拟下载读回可见"),
    badge("真实下载未执行", "warn")
  ].join("");
  document.getElementById("previewState").innerHTML =
    `<div class="stage-card"><strong>内部验收可用</strong><p>可验收证据项清单、字段白名单、脱敏、水印、版本哈希、拟邮件附件和审计读回；真实发送能力等邮件服务商接入后再验收。</p><p>${{safeText(payload?.data_boundary?.["客户可交付判断"] || "客户交付前需要完成真实来源核验。")}}</p>${{badge("内部预览")}} ${{badge("拟邮件包可看")}} ${{badge("真实邮件未接入", "warn")}}</div>`;
  renderReadbackSummary(payload, false);
}}
function renderMissingArtifact(payload) {{
  document.getElementById("portalSummary").textContent =
    "暂无证据包读回：请先在运营操作台完成实战搜索并生成机会闭环。";
  document.getElementById("artifactState").innerHTML =
    `<div class="empty-state"><strong>暂无证据包</strong><p>当前商机还没有可回放的证据包候选。先运行实战搜索生成机会闭环。</p></div>`;
  renderEvidencePackage(payload || {{}}, true);
  document.getElementById("accessState").innerHTML = [
    badge("内部预览待生成", "warn"),
    badge("客户账号不作为测试前置"),
    badge("真实邮件未接入", "warn")
  ].join("");
  document.getElementById("fieldState").innerHTML = [
    badge("字段白名单已执行"),
    badge("脱敏必需"),
    badge("内部黑箱已隐藏")
  ].join("");
  document.getElementById("auditState").innerHTML = [
    badge("内部读回待生成", "warn"),
    badge("真实下载未执行", "warn"),
    badge("客户自助发布不是当前路径")
  ].join("");
  document.getElementById("previewState").innerHTML =
    `<div class="empty-state"><strong>内部预览未形成</strong><p>当前商机缺少阶段7证据包读回。先从实战搜索生成机会闭环，再回到本页验收证据包、字段白名单和模拟下载审计状态。</p></div>`;
  renderReadbackSummary(payload || {{}}, true);
}}
function navigateArtifactSection(target) {{
  const section = document.querySelector(target);
  if (!section) {{ return; }}
  section.scrollIntoView({{ block: "start" }});
  history.replaceState(null, "", target);
}}
document.querySelectorAll('nav a[href^="#"]').forEach((link) => {{
  link.addEventListener("click", (event) => {{
    event.preventDefault();
    navigateArtifactSection(link.getAttribute("href"));
  }});
}});
loadPortal().catch(renderMissingArtifact);
"""
    return _page("AX9S 内部证据包预览", body, script)


def render_customer_artifact_portal_readback(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _customer_artifact_surface_with_search_context(payload)
    except (TypeError, ValueError) as exc:
        metadata = _search_run_metadata_for_opportunity(str(payload.get("opportunity_id") or ""))
        source_verification = _source_verification_from_metadata(metadata)
        fallback_surface = {
            "customer_visible_export_enabled": False,
            "external_release_enabled": False,
        }
        return {
            "empty_state": True,
            "opportunity_id": str(payload.get("opportunity_id") or ""),
            "readback_error": {"detail": str(exc)},
            "customer_visible_export_enabled": False,
            "external_release_enabled": False,
            "download_auth": {"customer_download_enabled": False, "auth_required": True},
            "field_allowlist_masking": {
                "allowlist_enforced": True,
                "masking_required": True,
                "internal_blackbox_fields_exposed": False,
            },
            "blocked_reasons": ["stage7_artifact_readback_missing"],
            "search_run_metadata": metadata,
            "source_verification": source_verification,
            "data_boundary": _localized_data_boundary(fallback_surface, metadata),
        }


def render_customer_artifact_portal_download(payload: dict[str, Any]) -> Response:
    opportunity_id = str(payload.get("opportunity_id") or "")
    package = _internal_evidence_package_download_payload(payload)
    filename = f"internal-evidence-package-{_safe_filename_token(opportunity_id)}.json"
    return Response(
        json.dumps(package, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def render_operator_user_acceptance_contract(payload: Any) -> dict[str, Any]:
    del payload
    return _load_user_acceptance_contract()


def render_operator_user_acceptance_gap_matrix(payload: Any) -> dict[str, Any]:
    del payload
    return _load_user_acceptance_gap_matrix()


OPERATOR_FRONTEND_ROUTES = [
    {
        "operationId": "renderOwnerOperatorConsole",
        "method": "GET",
        "path": "/operator-console",
        "handler": render_operator_console,
        "owner_operator_console_frontend": True,
        "task_creation_entry": True,
        "project_import_entry": True,
        "repository_backed_readback": True,
        **OPERATOR_FRONTEND_ROUTE_METADATA,
    },
    {
        "operationId": "renderCustomerArtifactPortal",
        "method": "GET",
        "path": "/customer-artifact-portal/{opportunity_id}",
        "handler": render_customer_artifact_portal,
        "customer_artifact_portal_frontend": True,
        "customer_artifact_access_readiness": True,
        "repository_backed_readback": True,
        **OPERATOR_FRONTEND_ROUTE_METADATA,
    },
    {
        "operationId": "renderCustomerArtifactPortalReadback",
        "method": "GET",
        "path": "/customer-artifact-portal-readback/{opportunity_id}",
        "handler": render_customer_artifact_portal_readback,
        "customer_artifact_portal_frontend_readback": True,
        "customer_artifact_empty_state": True,
        "repository_backed_readback": True,
        **OPERATOR_FRONTEND_ROUTE_METADATA,
    },
    {
        "operationId": "renderCustomerArtifactPortalDownload",
        "method": "GET",
        "path": "/customer-artifact-portal-download/{opportunity_id}",
        "handler": render_customer_artifact_portal_download,
        "customer_artifact_portal_frontend_download": True,
        "internal_evidence_package_download": True,
        "repository_backed_readback": True,
        **OPERATOR_FRONTEND_ROUTE_METADATA,
    },
    {
        "operationId": "renderOperatorUserAcceptanceContract",
        "method": "GET",
        "path": "/operator-console/user-acceptance-contract",
        "handler": render_operator_user_acceptance_contract,
        "operator_user_acceptance_contract": True,
        "ui_acceptance_authority": True,
        "repository_backed_readback": False,
        **OPERATOR_FRONTEND_ROUTE_METADATA,
    },
    {
        "operationId": "renderOperatorUserAcceptanceGapMatrix",
        "method": "GET",
        "path": "/operator-console/user-acceptance-gap-matrix",
        "handler": render_operator_user_acceptance_gap_matrix,
        "operator_user_acceptance_gap_matrix": True,
        "ui_acceptance_status": True,
        "repository_backed_readback": False,
        **OPERATOR_FRONTEND_ROUTE_METADATA,
    },
]


def register_operator_frontend_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(OPERATOR_FRONTEND_ROUTES))


__all__ = [
    "OPERATOR_FRONTEND_ROUTES",
    "register_operator_frontend_routes",
    "render_customer_artifact_portal",
    "render_customer_artifact_portal_download",
    "render_customer_artifact_portal_readback",
    "render_operator_console",
    "render_operator_user_acceptance_contract",
    "render_operator_user_acceptance_gap_matrix",
]
