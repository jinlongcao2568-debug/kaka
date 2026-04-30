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
            "search_scope": _json_or_default(refs.get("search_scope_json"), {}),
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


def _customer_artifact_surface_with_search_context(payload: dict[str, Any]) -> dict[str, Any]:
    surface = build_customer_artifact_access_candidate_surface(payload)
    opportunity_id = str(surface.get("opportunity_id") or payload.get("opportunity_id") or "")
    metadata = _search_run_metadata_for_opportunity(opportunity_id)
    surface["search_run_metadata"] = metadata
    surface["source_verification"] = _source_verification_from_metadata(metadata)
    return surface


def _safe_filename_token(value: str) -> str:
    token = "".join(char if char.isascii() and (char.isalnum() or char in "-_") else "-" for char in value)
    token = "-".join(part for part in token.split("-") if part)
    return token or "opportunity"


def _internal_evidence_package_download_payload(payload: dict[str, Any]) -> dict[str, Any]:
    surface = _customer_artifact_surface_with_search_context(payload)
    formal = dict(surface.get("source_formal_client_export_page_layer_readiness", {}) or {})
    artifact = dict(surface.get("customer_artifact_readback", {}) or {})
    manifest = dict(formal.get("package_manifest", {}) or {})
    source_verification = dict(surface.get("source_verification", {}) or {})
    evidence_items = []
    for item in list(manifest.get("evidence_items", []) or []):
        row = dict(item)
        row.setdefault("source_url", source_verification.get("source_url"))
        row.setdefault("source_site_name", source_verification.get("source_site_name"))
        row.setdefault("source_profile_id", source_verification.get("source_profile_id"))
        evidence_items.append(row)
    return {
        "说明": "内部证据包预览文件；用于运营方验收，不会真实发送给客户。",
        "未来交付方式": "成交付款后由系统通过邮件发送证据包。",
        "商机编号": str(payload.get("opportunity_id") or ""),
        "公开来源验证": source_verification,
        "证据包": {
            "证据包编号": artifact.get("evidence_pack_id"),
            "交付包编号": artifact.get("package_id"),
            "清单编号": artifact.get("artifact_manifest_id"),
            "版本哈希": artifact.get("artifact_version_hash"),
            "水印": dict(artifact.get("watermark", {}) or {}),
            "页面草稿": dict(formal.get("page_draft", {}) or {}),
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
        "字段策略": dict(surface.get("field_allowlist_masking", {}) or {}),
        "模拟下载审计": dict(surface.get("download_auth", {}) or {}),
        "原始读回": surface,
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
        <p>任务创建、项目导入、阶段1-9运营、销售闭环、客户交付、支付交付、审计回写集中在同一入口。</p>
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
              <div><strong>客户交付</strong><p>字段白名单、脱敏、水印、版本哈希、下载授权、审计。</p></div>
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
              <button id="runAutonomousSearch">搜索并生成机会闭环</button>
            </section>
            <section>
              <h3>地区适配器状态</h3>
              <div id="regionAdapterSummary" class="empty-state">正在读取地区适配器...</div>
            </section>
            <section class="wide">
              <h3>搜索结果</h3>
              <div id="searchResult" class="empty-state">暂无搜索结果。</div>
            </section>
            <section class="wide">
              <h3>搜索运行记录</h3>
              <p class="muted-text" id="autonomousSearchRunMeta">待读取最新搜索记录。</p>
              <div id="autonomousSearchRuns" class="empty-state">暂无实战搜索运行记录。</div>
              <button id="refreshAutonomousSearchRuns">刷新搜索记录</button>
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
            <button id="refreshSystemRelease">刷新系统与放行</button>
          </section>
          <section>
            <h3>审批审计</h3>
            <div id="auditStatus"></div>
          </section>
          <section class="controlled_opening_requirement">
            <h3>内部测试放行状态</h3>
            <p>测试阶段内部预览、证据包生成、模拟下载、模拟外发链路可以打开；当前没有邮件、电话、支付、退款服务商接入，所以不会真实触达外部。</p>
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
  "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED": "真实样本闭环通过",
  "REVIEW_REQUIRED": "需要复核",
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
  "NATIONAL_FALLBACK_READY_LOCAL_ONBOARDING_PENDING": "全国兜底，本地入口待补",
  "GUANGDONG-PROVINCIAL-PORTAL": "广东公共资源入口",
  "BEIJING-PLATFORM-HOME": "北京公共资源入口",
  "GGZY-DEAL-LIST": "全国公共资源交易列表",
  "PASS": "通过",
  "PARTIAL": "部分满足",
  "NOT_EXPOSED": "未展示",
  "FAIL": "未通过",
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
function candidateRange(candidate) {
  return {
    minimum: candidate?.amount_min ?? candidate?.amount,
    maximum: candidate?.amount_max ?? candidate?.amount
  };
}
function opportunityActions(opportunityId) {
  if (!opportunityId) { return ""; }
  return `<div class="opportunity-actions">
    <a href="#autonomousWorkbench" data-workbench-opportunity="${opportunityId}">查看机会</a>
    <a href="/customer-artifact-portal/${encodeURIComponent(opportunityId)}">证据包预览</a>
    <a href="/customer-artifact-portal-download/${encodeURIComponent(opportunityId)}">下载证据包</a>
  </div>`;
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
      ${badge(candidate.analysis_score ? `评分 ${candidate.analysis_score}` : "评分 --")}
      <p>${candidate.source_site_name || candidate.source_profile_id || candidate.source_url || "来源待读回"}</p>
      ${activeOpportunityId && candidate.project_id === selectedProjectId ? opportunityActions(activeOpportunityId) : ""}
    </div>
  `).join("")}</div>`;
}
function renderSearchResultFromRun(run) {
  if (!run) {
    $("searchResult").className = "empty-state";
    $("searchResult").textContent = "暂无搜索结果。";
    return;
  }
  const scope = run.search_scope || {};
  $("searchResult").className = "";
  $("searchResult").innerHTML = `
    <div class="stage-card">
      <strong>${run.opportunity_id || "--"}</strong>
      <p>${run.project_name || run.query || "--"}</p>
      ${badge(run.search_state || "--", run.search_state === "AUTONOMOUS_SEARCH_ACCEPTED" ? "" : "warn")}
      ${badge(run.region_code || "--")}
      ${badge(run.project_type_label || run.project_type || "--")}
      <p>金额区间：${amountRangeText(run.amount_range || {minimum: run.amount_min, maximum: run.amount_max})}</p>
      <p>候选对象：${scope.candidate_count ?? (run.candidate_options || []).length ?? 0}；进入闭环：${scope.closed_loop_generated_count ?? (run.opportunity_id ? 1 : 0)}</p>
      ${opportunityActions(run.opportunity_id)}
    </div>
    <h3>候选对象明细</h3>
    ${renderCandidateCards(run.candidate_options || [], run.opportunity_id || "", scope.selected_project_id || run.project_id || "")}
  `;
}
function renderOpportunityDetail(first, panels) {
  const hook = panels.commercial_hook_panel || {};
  const buyer = panels.buyer_ranking_panel || {};
  const delivery = panels.delivery_state_panel || {};
  const next = panels.sales_next_action_panel || {};
  const risk = panels.evidence_risk_panel || {};
  $("opportunityDetail").className = "";
  $("opportunityDetail").innerHTML = `
    <h3>机会详情</h3>
    ${renderRows([
      ["机会编号", first.opportunity_id],
      ["机会级别", first.opportunity_grade],
      ["可售状态", first.saleability_status],
      ["推荐 SKU", first.recommended_sku],
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
function renderStageOverviewTelemetry(telemetry) {
  const defaultStages = [
    "市场扫描 / 机会发现", "来源蓝图 / 采集计划", "解析规范化", "证据风险核验", "规则证据门",
    "产品包", "商业钩子 / 买家匹配", "触达计划", "支付交付"
  ];
  const stages = telemetry?.stage_stats || defaultStages.map((name, index) => ({
    stage: index + 1,
    name,
    state: "等待运行",
    produced_count: 0,
    effective_count: 0,
    invalid_count: 0,
    note: "运行实战搜索后显示本阶段真实统计。"
  }));
  const totals = telemetry?.totals || {
    stage_count: stages.length,
    produced_count: 0,
    effective_count: 0,
    invalid_count: 0
  };
  $("stageDirection").textContent = telemetry?.direction
    ? `${telemetry.direction}。内部测试链路可跑；真实对外交付门禁保留。`
    : "系统方向：市场扫描 -> 来源蓝图 -> 阶段1-9内部链路 -> 工作台 -> 证据包预览。运行后显示每阶段产出。";
  $("stageMetrics").innerHTML = [
    `<div class="metric"><strong>${totals.stage_count || stages.length}</strong><span>阶段数</span></div>`,
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
    </div>
  `).join("");
}
function renderCapabilityExposure(readiness, scheduler, goLive) {
  const items = [
    ["阶段1-9数据流", "已展示", "运营总览显示阶段产出、有效数据、无效数据和运行日志。"],
    ["实战搜索与地区适配器", "已展示", "支持地区多选、项目类型多选、金额区间和搜索运行记录。"],
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
function renderUserAcceptanceContract(contract) {
  const product = contract?.productDefinition || {};
  const authority = contract?.acceptanceAuthority || {};
  const dimensions = Array.isArray(contract?.acceptanceDimensions) ? contract.acceptanceDimensions : [];
  const priorities = Array.isArray(contract?.currentOptimizationPriorities) ? contract.currentOptimizationPriorities : [];
  $("acceptanceContractSummary").innerHTML = renderRows([
    ["契约编号", contract?.contractId],
    ["状态", contract?.status],
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
  $("acceptancePriorityList").innerHTML = priorities.length
    ? priorities.map((item, index) => `<div>${index + 1}. ${safeText(item)}</div>`).join("")
    : `<div>暂无优化优先级。</div>`;
}
async function loadUserAcceptanceContract() {
  const contract = await json("GET", "/operator-console/user-acceptance-contract");
  renderUserAcceptanceContract(contract);
  return contract;
}
function acceptanceStatusKind(status) {
  if (status === "FAIL") { return "danger"; }
  if (status === "PARTIAL" || status === "NOT_EXPOSED") { return "warn"; }
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
async function loadReadiness(writeOutput = true) {
  const readiness = await json("GET", "/operator-console/readiness");
  const scheduler = await json("GET", "/operator-console/scheduler-status");
  const goLive = await json("GET", "/go-live/readiness");
  $("capability").textContent = labelOf(readiness.capability_state || "--");
  $("provider").textContent = readiness.provider_status?.mode ? "读回模式" : "读回";
  $("scheduler").textContent = labelOf(scheduler.readiness_state || "--");
  $("summary").textContent = "运营操作台已就绪。内部测试链路、证据包预览和模拟外发可跑；真实邮件/电话/支付/退款服务商未接入。";
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
  renderCapabilityExposure(readiness, scheduler, goLive);
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
      ${tags}
      <p>${labelOf(item.next_action || "--")}</p>
      ${opportunityActions(item.opportunity_id || "")}
    </div>`;
  }).join("");
  const panels = payload.panels || {};
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
  const select = $("searchRegion");
  select.innerHTML = "";
  for (const adapter of catalog.region_adapters || []) {
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
  const rows = (catalog.region_adapters || []).slice(0, 8).map((adapter) => {
    const flags = [
      badge(adapter.dedicated_local_profiles ? "本地入口" : "全国兜底", adapter.dedicated_local_profiles ? "" : "warn"),
      badge(adapter.commercial_pilot_region ? "商业试点" : "非试点"),
      badge(adapter.onboarding_required ? "待补本地配置" : "配置就绪", adapter.onboarding_required ? "warn" : "")
    ].join("");
    return `<div class="stage-card"><strong>${adapter.region_code} ${adapter.region_name}</strong><p>${adapter.primary_entry_profile_id || "--"}</p>${flags}</div>`;
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
  $("autonomousSearchRunMeta").textContent = collapsed
    ? `展示最新 ${runs.length} 个商机，已合并 ${collapsed} 条重复运行记录。`
    : `展示最新 ${runs.length} 个商机。`;
  if (!runs.length) {
    $("autonomousSearchRuns").className = "empty-state";
    $("autonomousSearchRuns").textContent = "暂无实战搜索运行记录。";
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
    const links = [
      run.opportunity_id ? `<a href="#autonomousWorkbench" data-workbench-opportunity="${run.opportunity_id}">工作台</a>` : "",
      run.opportunity_id ? `<a href="/customer-artifact-portal/${encodeURIComponent(run.opportunity_id)}">证据包预览</a>` : ""
    ].filter(Boolean).join(" · ");
    return `<div class="stage-card">
      <strong>${run.opportunity_id || "--"}</strong>
      <p>${run.project_name || run.query || "--"}</p>
      ${badge(run.search_state || "--", run.search_state === "AUTONOMOUS_SEARCH_ACCEPTED" ? "" : "warn")}
      ${badge(run.region_code || "--")}
      ${badge(run.entry_profile_id || "--")}
      <p>${labelOf(run.project_type_label || run.project_type)} · ${amountRangeText(run.amount_range || {minimum: run.amount_min, maximum: run.amount_max})}</p>
      <p>候选 ${run.search_scope?.candidate_count ?? (run.candidate_options || []).length ?? 0} · 闭环 ${run.search_scope?.closed_loop_generated_count ?? 1}</p>
      <p>${links || "读回路径待生成"}</p>
    </div>`;
  }).join("");
  return payload;
}
async function loadRealSourceProfiles() {
  const catalog = await json("GET", "/operator-console/real-source-profiles");
  fillSelect("entryProfile", catalog.entry_profiles || [], (item) => `${item.profile_id} | ${item.site_name}`);
  fillSelect("attachmentProfile", catalog.attachment_profiles || [], (item) => `${item.profile_id} | ${item.site_name}`);
  return catalog;
}
async function createTask() {
  const payload = { task_id: $("taskId").value, project_id: $("projectId").value, now: new Date().toISOString() };
  out(await json("POST", "/operator-console/tasks", payload));
}
async function importProject() {
  const payload = { project_id: $("projectId").value, source_mode: "INTERNAL_PROJECT_IMPORT", now: new Date().toISOString() };
  out(await json("POST", "/operator-console/project-imports", payload));
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
    candidate_count: 3,
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
    const accepted = result.search_state === "AUTONOMOUS_SEARCH_ACCEPTED";
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
      candidate_options: result.candidate_options || []
    });
    $("searchResult").insertAdjacentHTML("afterbegin", `<p class="muted-text">${accepted ? "已生成最高优先级机会闭环。" : "本次候选需要复核。"}</p>`);
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
Promise.all([loadReadiness(false), loadAutonomousWorkbench(), loadRegionAdapters(), loadAutonomousSearchRuns(), loadRealSourceProfiles(), loadRealSourceRuns(), loadUserAcceptanceContract(), loadAcceptanceGapMatrix()])
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
}};
function labelOf(value) {{
  const text = String(value ?? "--");
  return portalLabels[text] || text;
}}
function badge(text, kind="") {{ return `<span class="pill ${{kind}}">${{labelOf(text)}}</span>`; }}
function valueText(value) {{
  if (Array.isArray(value)) {{ return value.length ? value.map(labelOf).join(" / ") : "--"; }}
  if (value && typeof value === "object") {{ return JSON.stringify(value); }}
  return value === undefined || value === null || value === "" ? "--" : labelOf(value);
}}
function valueHtml(value) {{
  const text = valueText(value);
  if (/^https?:\/\//.test(text)) {{
    return `<a href="${{text}}" target="_blank" rel="noopener">${{text}}</a>`;
  }}
  return text;
}}
function rowsHtml(rows) {{
  return `<div class="detail-table">${{rows
    .filter(([, value]) => value !== undefined && value !== null && String(value).length)
    .map(([label, value]) => `<div class="detail-row"><strong>${{label}}</strong><span>${{valueHtml(value)}}</span></div>`)
    .join("")}}</div>`;
}}
function evidenceItemsHtml(items) {{
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {{ return `<div class="empty-state">暂无证据项读回。</div>`; }}
  return `<div class="compact-card-grid">${{rows.map((item) => `
    <div class="stage-card">
      <strong>${{labelOf(item.item_id || item.source_object || "--")}}</strong>
      <p>证据类型：${{labelOf(item.item_id || "--")}}</p>
      <p>线索类型：${{labelOf(item.source_object || "--")}}</p>
      <p>来源对象：${{item.source_id || "--"}}</p>
      ${{badge(item.manifest_state || item.status || "--", item.present === false ? "warn" : "")}}
      ${{badge(item.masking_policy || "--")}}
      <p>来源引用：${{valueText(item.source_refs)}}</p>
      <p>公开来源：${{item.source_url ? `<a href="${{item.source_url}}" target="_blank" rel="noopener">${{item.source_site_name || item.source_profile_id || item.source_url}}</a>` : "来源网址待读回"}}</p>
    </div>
  `).join("")}}</div>`;
}}
function renderEvidencePackage(payload, missing=false) {{
  const formal = payload?.source_formal_client_export_page_layer_readiness || {{}};
  const sourceVerification = payload?.source_verification || {{}};
  const readback = payload?.customer_artifact_readback || {{}};
  const manifest = formal.package_manifest || {{}};
  const pageDraft = formal.page_draft || {{}};
  const sourceUrl = sourceVerification.source_url || "";
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
    ["水印", watermark.watermark_text || "INTERNAL DRAFT"],
    ["页面草稿", pageDraft.page_draft_id],
    ["项目名称", sourceVerification.project_name],
    ["公开来源", sourceVerification.source_site_name || sourceVerification.source_profile_id],
    ["来源网址", sourceVerification.source_url],
    ["验证口径", sourceVerification.verification_hint],
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
    ])}}
  `;
  document.getElementById("evidencePackagePreview").innerHTML = evidenceItemsHtml(evidenceItems);
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
    `<div class="stage-card"><strong>内部验收可用</strong><p>可验收证据项清单、字段白名单、脱敏、水印、版本哈希、拟邮件附件和审计读回；真实发送能力等邮件服务商接入后再验收。</p>${{badge("内部预览")}} ${{badge("拟邮件包可看")}} ${{badge("真实邮件未接入", "warn")}}</div>`;
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
loadPortal().catch(renderMissingArtifact);
"""
    return _page("AX9S 内部证据包预览", body, script)


def render_customer_artifact_portal_readback(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _customer_artifact_surface_with_search_context(payload)
    except (TypeError, ValueError) as exc:
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
            "search_run_metadata": _search_run_metadata_for_opportunity(str(payload.get("opportunity_id") or "")),
            "source_verification": _source_verification_from_metadata(
                _search_run_metadata_for_opportunity(str(payload.get("opportunity_id") or ""))
            ),
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
