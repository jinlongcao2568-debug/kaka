# Stage: api_operator_frontend
# Consumes formal objects: operator/customer access API readback only
# Dependent handoff: N/A
# Dependent schema/contracts: existing operator_customer_access route surfaces

from __future__ import annotations

import json
from html import escape
from typing import Any

from fastapi.responses import HTMLResponse

from api.projections import build_customer_artifact_access_candidate_surface, register_route_table


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
      .operator-shell main {{ height: auto; overflow: visible; display: block; }}
      .workspace {{ display: block; }}
      .panelStack {{ overflow: visible; padding-right: 0; }}
      .resultPane pre {{ max-height: 260px; }}
      .grid, .rail, .stage-grid, .workflow, .compact-card-grid {{ grid-template-columns: 1fr; }}
      .view-grid {{ grid-template-columns: 1fr; }}
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
    <button class="nav-link active" type="button" data-view="overview" aria-current="page">Stage1-9 运营总览</button>
    <button class="nav-link" type="button" data-view="search" aria-current="false">实战搜索</button>
    <button class="nav-link" type="button" data-view="run" aria-current="false">全链路运行</button>
    <button class="nav-link" type="button" data-view="business" aria-current="false">业务闭环</button>
    <button class="nav-link" type="button" data-view="autonomousWorkbench" aria-current="false">自主机会工作台</button>
    <button class="nav-link" type="button" data-view="workbench" aria-current="false">Stage6-9 工作台</button>
    <button class="nav-link" type="button" data-view="providers" aria-current="false">服务商状态</button>
    <button class="nav-link" type="button" data-view="audit" aria-current="false">审批审计</button>
    <a class="external" id="customerPortalLink" href="/customer-artifact-portal/OPP-HAPPY-001">客户材料门户 · 样例</a>
  </nav>
  <main>
    <div class="topbar">
      <div>
        <h2>证据包运营操作台</h2>
        <p>任务创建、项目导入、Stage1-9 运营、销售闭环、客户交付、支付交付、审计回写集中在同一入口。</p>
      </div>
      <div class="status" id="summary">正在读取 bootstrap / readiness...</div>
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
            <h3>Stage1-9 运营总览</h3>
            <div class="stage-grid" id="stageBoard">
              <div class="stage-card"><strong>Stage1 调度</strong><p>任务、窗口、队列、暂停恢复。</p><span class="pill">内部执行</span></div>
              <div class="stage-card"><strong>Stage2 公开源</strong><p>公开源适配器、快照、哈希、来源链。</p><span class="pill">仅公开来源</span></div>
              <div class="stage-card"><strong>Stage3 解析</strong><p>HTML/PDF/OCR/附件字段候选与复核。</p><span class="pill">待核验</span></div>
              <div class="stage-card"><strong>Stage4 核验</strong><p>公开核验、证据等级、失败关闭。</p><span class="pill">公开核验</span></div>
              <div class="stage-card"><strong>Stage5 规则</strong><p>规则目录、金标用例、证据绑定。</p><span class="pill">规则工厂</span></div>
              <div class="stage-card"><strong>Stage6 产品包</strong><p>异议价值、可售判断、交付就绪。</p><span class="pill">产品包</span></div>
              <div class="stage-card"><strong>Stage7 销售</strong><p>真实竞争者、买家匹配、CRM/报价。</p><span class="pill">销售闭环</span></div>
              <div class="stage-card"><strong>Stage8 触达</strong><p>模板、频控、退订、服务商执行读回。</p><span class="pill warn">门禁控制</span></div>
              <div class="stage-card"><strong>Stage9 支付交付</strong><p>订单、收款、交付、对账、人工退款异常。</p><span class="pill warn">无自动退款</span></div>
            </div>
          </section>
        </div>
        <div class="view-panel" id="business" data-view-panel="business">
          <section>
            <h3>业务闭环</h3>
            <div class="workflow">
              <div><strong>证据链</strong><p>公开来源 -> 解析 -> 核验 -> 规则 -> Stage6 产品包。</p></div>
              <div><strong>销售闭环</strong><p>真实竞争者 -> 买家匹配 -> CRM/报价 -> 触达。</p></div>
              <div><strong>客户交付</strong><p>字段白名单、脱敏、水印、版本哈希、下载授权、审计。</p></div>
              <div><strong>支付交付</strong><p>订单、支付、收据、发票、结算、交付、回滚。</p></div>
            </div>
          </section>
        </div>
        <div class="view-panel" id="search" data-view-panel="search">
          <div class="view-grid">
            <section>
              <h3>实战项目搜索</h3>
              <label for="searchRegion">地区适配器</label>
              <select id="searchRegion"></select>
              <label for="searchKeyword">关键词</label>
              <input id="searchKeyword" value="公共建筑工程" />
              <label for="searchProjectType">项目类型</label>
              <select id="searchProjectType">
                <option value="construction">construction</option>
                <option value="municipal">municipal</option>
                <option value="highway">highway</option>
                <option value="water_conservancy">water_conservancy</option>
              </select>
              <label for="searchAmount">金额</label>
              <input id="searchAmount" type="number" value="12000000" />
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
            <h3>自主机会工作台</h3>
            <div class="rail" id="autonomousMetrics">
              <div class="metric"><strong>--</strong><span>机会队列</span></div>
              <div class="metric"><strong>--</strong><span>商业钩子</span></div>
              <div class="metric"><strong>--</strong><span>下一步动作</span></div>
            </div>
            <div id="autonomousQueue" class="empty-state">暂无已持久化机会队列。</div>
            <div id="autonomousDetailPanels" class="stage-grid"></div>
            <button id="refreshAutonomousWorkbench">刷新自主机会工作台</button>
          </section>
        </div>
        <div class="view-panel" id="run" data-view-panel="run">
          <div class="view-grid">
            <section>
              <h3>任务创建</h3>
              <label for="taskId">任务 ID</label>
              <input id="taskId" value="TASK-OWNER-127-001" />
              <label for="projectId">项目 ID</label>
              <input id="projectId" value="PROJ-OWNER-127-001" />
              <button id="createTask">创建内部任务</button>
              <button class="secondary" id="importProject">导入项目</button>
            </section>
            <section>
              <h3>真实公开源验证</h3>
              <p>只执行 allowlist 的真实公开入口页和附件原始链接；采集按 approved capture plan、source profile、同站证据链与 provider gate 执行。</p>
              <label for="entryProfile">入口页 Profile</label>
              <select id="entryProfile"></select>
              <button id="runEntryCapture">执行入口页抓取</button>
              <label for="attachmentProfile">附件 Profile</label>
              <select id="attachmentProfile"></select>
              <button class="secondary" id="runAttachmentCapture">执行附件抓取</button>
              <button class="secondary" id="readLatestSourceCapture">读取最近一次抓取读回</button>
              <button class="secondary" id="refreshRealSourceRuns">刷新真实源任务列表</button>
              <div id="realSourceRunList" class="empty-state">暂无真实源任务运行记录。</div>
            </section>
            <section class="wide">
              <h3>全链路运行入口</h3>
              <p>只接受脱敏、离线、内部 payload；Stage1-5 外部 live transport 仍关闭。</p>
              <label for="payload">运行参数 JSON</label>
              <textarea id="payload">__CONTROLLED_SAMPLE_PAYLOAD__</textarea>
              <button id="runControlledSample">运行受控样本到 Stage6</button>
              <button class="secondary" id="previewRun">只检查运行入口</button>
            </section>
          </div>
        </div>
        <div class="view-panel" id="workbench" data-view-panel="workbench">
          <section>
            <h3>Stage6-9 工作台</h3>
            <div id="workbenchStatus"></div>
            <p>这里是后端 Stage6-9 读回的工作台入口，不会直接执行真实服务商。</p>
            <button id="refreshWorkbench">刷新工作台读回</button>
          </section>
        </div>
        <div class="view-panel" id="providers" data-view-panel="providers">
          <section>
            <h3>服务商与调度状态</h3>
            <div id="providerStatus"></div>
            <button id="refreshProvider">刷新服务商 / 调度</button>
          </section>
        </div>
        <div class="view-panel" id="audit" data-view-panel="audit">
          <section>
            <h3>审批审计</h3>
            <div id="auditStatus"></div>
            <button id="refreshAudit">刷新审计读回</button>
          </section>
          <section class="controlled_opening_requirement">
            <h3>受控开放要求</h3>
            <p>本页面不执行对外软件发布、真实触达、真实支付、真实交付、真实退款或自动退款。</p>
            <span class="pill danger">对外发布已阻断</span>
            <span class="pill danger">自动退款已排除</span>
            <span class="pill danger">客户真实下载默认关闭</span>
            <span class="pill warn">客户访问受门禁控制</span>
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
    ["状态", value.search_state || value.state],
    ["商机", value.opportunity_id],
    ["运行 ID", value.search_run_id || value.run_id],
    ["地区", value.region_code],
    ["入口 Profile", value.entry_profile_id],
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
    link.textContent = "客户材料门户 · 当前商机";
    link.title = opportunityId;
    return;
  }
  link.href = "/customer-artifact-portal/OPP-HAPPY-001";
  link.textContent = "客户材料门户 · 样例";
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
function badge(text, kind="") { return `<span class="pill ${kind}">${text}</span>`; }
async function loadReadiness(writeOutput = true) {
  const readiness = await json("GET", "/operator-console/readiness");
  const scheduler = await json("GET", "/operator-console/scheduler-status");
  const goLive = await json("GET", "/go-live/readiness");
  $("capability").textContent = readiness.capability_state || "--";
  $("provider").textContent = readiness.provider_status?.mode ? "读回模式" : "读回";
  $("scheduler").textContent = scheduler.readiness_state || "--";
  $("summary").textContent = "运营操作台已就绪。客户访问仍受审批和审计门禁控制。";
  $("workbenchStatus").innerHTML = [
    badge("Stage6 产品包"),
    badge("Stage7 CRM/报价"),
    badge("Stage8 销售触达"),
    badge("Stage9 支付交付"),
    badge(`上线 ${goLive.go_live_enabled ? "已开放" : "已阻断"}`, goLive.go_live_enabled ? "" : "warn")
  ].join("");
  $("providerStatus").innerHTML = [
    badge(`服务商 ${readiness.provider_status?.mode ? "读回模式" : "读回"}`),
    badge(`调度 ${scheduler.readiness_state || "未知"}`),
    badge("真实服务商调用已关闭", "warn")
  ].join("");
  $("auditStatus").innerHTML = [
    badge("审批可见"),
    badge("审计可见"),
    badge("下载授权必需", "warn")
  ].join("");
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
    `<div class="metric"><strong>${first.next_action || "--"}</strong><span>下一步动作</span></div>`
  ].join("");
  if (!queue.length) {
    $("autonomousQueue").className = "empty-state";
    $("autonomousQueue").textContent = "暂无已持久化机会队列。";
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
    return `<div class="stage-card"><strong>${item.opportunity_id || "--"}</strong><p>${item.commercial_hook_teaser || "商业钩子待生成"}</p>${tags}<p>${item.next_action || "--"}</p></div>`;
  }).join("");
  const panels = payload.panels || {};
  $("autonomousDetailPanels").innerHTML = [
    `<div class="stage-card"><strong>证据风险</strong><p>${panels.evidence_risk_panel?.evidence_strength_label || "--"} / ${panels.evidence_risk_panel?.hard_defect_public_label || "--"}</p>${badge((panels.evidence_risk_panel?.review_items || []).length + " 项复核")}</div>`,
    `<div class="stage-card"><strong>商业钩子</strong><p>${panels.commercial_hook_panel?.teaser_copy || first.commercial_hook_teaser || "--"}</p>${badge(panels.commercial_hook_panel?.disclosure_level || "--")}</div>`,
    `<div class="stage-card"><strong>买家排序</strong><p>${(panels.buyer_ranking_panel?.buyer_rankings || []).map((row) => `${row.rank}.${row.buyer_type || "--"}`).join(" / ") || "--"}</p>${badge("fit " + (panels.buyer_ranking_panel?.buyer_fit_score || "--"))}</div>`,
    `<div class="stage-card"><strong>交付状态</strong><p>${panels.delivery_state_panel?.delivery_state || "--"} / ${panels.delivery_state_panel?.page_draft_id || "--"}</p>${badge(panels.delivery_state_panel?.delivery_ready ? "可交付" : "待审批", panels.delivery_state_panel?.delivery_ready ? "" : "warn")}</div>`,
    `<div class="stage-card"><strong>下一步动作</strong><p>${panels.sales_next_action_panel?.next_action || first.next_action || "--"}</p>${badge(panels.sales_next_action_panel?.quote_surface_state || "--")}</div>`
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
    option.textContent = `${adapter.region_code} | ${adapter.region_name} | ${adapter.adapter_state}`;
    select.appendChild(option);
  }
  const rows = (catalog.region_adapters || []).slice(0, 8).map((adapter) => {
    const flags = [
      badge(adapter.dedicated_local_profiles ? "本地入口" : "全国兜底", adapter.dedicated_local_profiles ? "" : "warn"),
      badge(adapter.commercial_pilot_region ? "商业试点" : "非试点"),
      badge(adapter.onboarding_required ? "待补本地 profile" : "profile 就绪", adapter.onboarding_required ? "warn" : "")
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
  $("autonomousSearchRuns").className = "compact-card-grid";
  $("autonomousSearchRuns").innerHTML = runs.slice(0, 8).map((run) => {
    const links = [
      run.opportunity_id ? `<a href="#autonomousWorkbench" data-workbench-opportunity="${run.opportunity_id}">工作台</a>` : "",
      run.opportunity_id ? `<a href="/customer-artifact-portal/${encodeURIComponent(run.opportunity_id)}">材料门户</a>` : ""
    ].filter(Boolean).join(" · ");
    return `<div class="stage-card">
      <strong>${run.opportunity_id || "--"}</strong>
      <p>${run.project_name || run.query || "--"}</p>
      ${badge(run.search_state || "--", run.search_state === "AUTONOMOUS_SEARCH_ACCEPTED" ? "" : "warn")}
      ${badge(run.region_code || "--")}
      ${badge(run.entry_profile_id || "--")}
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
  const payload = {
    region_code: $("searchRegion").value,
    query: $("searchKeyword").value,
    project_type: $("searchProjectType").value,
    amount: Number($("searchAmount").value || 12000000),
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
    $("searchResult").innerHTML = `
      <div class="stage-card">
        <strong>${result.opportunity_id || "--"}</strong>
        <p>${result.candidate?.project_name || "--"}</p>
        ${badge(result.search_state || "--", accepted ? "" : "warn")}
        ${badge(result.acceptance?.acceptance_state || "--", accepted ? "" : "warn")}
        ${badge(result.region_adapter?.region_code || "--")}
        ${badge(result.search_run_id || "--")}
        <p>${result.acceptance?.owner_workbench_acceptance?.queue_item?.commercial_hook_teaser || "商业钩子待生成"}</p>
      </div>`;
    out({
      search_state: result.search_state,
      opportunity_id: result.opportunity_id,
      search_run_id: result.search_run_id,
      region_code: result.region_adapter?.region_code,
      entry_profile_id: result.entry_profile?.profile_id,
      workbench: result.operator_workbench_readback_path,
      customer_artifact_candidate: result.customer_artifact_candidate_path,
      raw_json_required: false
    });
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
  try { payload = JSON.parse($("payload").value); } catch (err) { out({ error: "invalid JSON", detail: String(err) }); return; }
  out({ entry: "/internal/stage1-6/orchestrations", accepted_payload: payload, live_execution_enabled: false, display_message: "仅检查内部运行入口，不执行真实外部动作。" });
}
async function runControlledSample() {
  let payload = {};
  try { payload = JSON.parse($("payload").value); } catch (err) { out({ error: "invalid JSON", detail: String(err) }); return; }
  payload.payload_boundary = "SANITIZED_OFFLINE_INTERNAL";
  payload.source_mode = payload.source_mode || "OFFLINE_FIXTURE";
  payload.run_mode = payload.run_mode || "DRY_RUN";
  payload.live_execution_enabled = false;
  const result = await json("POST", "/internal/stage1-6/orchestrations", payload);
  $("workbenchStatus").innerHTML = [
    badge(`Stage6 已持久化 ${result.stage6_persisted ? "是" : "否"}`),
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
$("refreshAutonomousSearchRuns").addEventListener("click", async () => out(await loadAutonomousSearchRuns()));
$("runEntryCapture").addEventListener("click", runEntryCapture);
$("runAttachmentCapture").addEventListener("click", runAttachmentCapture);
$("readLatestSourceCapture").addEventListener("click", readLatestSourceCapture);
$("refreshRealSourceRuns").addEventListener("click", async () => out(await loadRealSourceRuns()));
$("previewRun").addEventListener("click", previewRun);
$("runControlledSample").addEventListener("click", runControlledSample);
$("refreshWorkbench").addEventListener("click", loadReadiness);
$("refreshAutonomousWorkbench").addEventListener("click", async () => out(await loadAutonomousWorkbench()));
$("refreshProvider").addEventListener("click", loadReadiness);
$("refreshAudit").addEventListener("click", loadReadiness);
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
Promise.all([loadReadiness(false), loadAutonomousWorkbench(), loadRegionAdapters(), loadAutonomousSearchRuns(), loadRealSourceProfiles(), loadRealSourceRuns()])
  .then(() => { $("output").textContent = "等待操作..."; })
  .catch(out);
"""
    return _page("AX9S 运营操作台", body, script)


def render_customer_artifact_portal(payload: dict[str, Any]) -> HTMLResponse:
    opportunity_id = escape(str(payload.get("opportunity_id") or ""))
    body = f"""
<div class="layout">
  <nav aria-label="客户门户导航">
    <h1>AX9S 客户材料门户</h1>
    <a href="/operator-console">运营操作台</a>
    <a href="#artifact">交付材料</a>
    <a href="#access">访问控制</a>
    <a href="#audit">下载审计</a>
  </nav>
  <main>
    <div class="topbar">
      <div>
        <h2>客户材料门户</h2>
        <p>Opportunity <strong id="opportunity">{opportunity_id}</strong></p>
      </div>
      <div class="status" id="portalSummary">正在读取客户 artifact access candidate...</div>
    </div>
    <div class="grid">
      <section id="artifact">
        <h3>客户可见材料</h3>
        <div id="artifactState"></div>
      </section>
      <section id="access">
        <h3>访问控制</h3>
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
      <section class="controlled_opening_requirement wide">
        <h3>客户侧受控开放要求</h3>
        <p>无授权不生成下载；内部黑箱评分、未复核推断或未审批材料不会展示。</p>
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
function badge(text, kind="") {{ return `<span class="pill ${{kind}}">${{text}}</span>`; }}
function blockedReasonLabel(reason) {{
  const labels = {{
    "stage7_artifact_readback_missing": "Stage7 客户材料尚未生成",
    "stage8_stage9_delivery_context_not_required_for_access_candidate_readback": "Stage8/Stage9 交付上下文未进入客户开放面",
    "customer_visible_export_enabled=false": "客户可见导出未开启",
    "client_page_release_enabled=false": "客户页面未发布",
    "external_release_enabled=false": "对外发布未批准",
    "external_delivery_enabled=false": "对外交付未开启",
    "direct_export_enabled=false": "直接导出未开启",
    "approval_audit_and_implementation_decision_required_before_live": "需要审批、审计和实施决策",
    "customer_account_access_control_required": "需要配置客户账号访问",
    "download_auth_required": "需要下载授权",
    "approval_audit_required_before_customer_download": "客户下载前需要审批审计",
    "public_software_release_not_approved": "公开软件发布未批准",
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
    ["客户可见", payload?.customer_visible_export_enabled ? "已批准" : "未开放"],
    ["对外交付", payload?.external_release_enabled ? "已开放" : "未开放"],
    ["下载授权", downloadAuth.customer_download_enabled ? "已授权" : "未授权"],
    ["字段策略", fieldPolicy.allowlist_enforced === false ? "白名单未确认" : "白名单已执行"],
    ["阻断原因", blockedReasons],
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
    payload.release_blocked ? "材料仍受审批、账号访问、下载授权和审计门禁控制。" : "已存在审批后的客户可见读回。";
  document.getElementById("artifactState").innerHTML = [
    badge(payload.capability_state || "APPROVAL_READY"),
    badge(payload.customer_visible_export_enabled ? "客户可见已批准" : "客户可见已阻断", payload.customer_visible_export_enabled ? "" : "warn"),
    badge(payload.external_release_enabled ? "对外交付已开放" : "对外交付已阻断", payload.external_release_enabled ? "" : "danger")
  ].join("");
  document.getElementById("accessState").innerHTML = [
    badge("账号访问控制必需", "warn"),
    badge("下载授权必需", "warn"),
    badge(payload.download_auth?.customer_download_enabled ? "下载读回已批准" : "下载已阻断", payload.download_auth?.customer_download_enabled ? "" : "warn")
  ].join("");
  document.getElementById("fieldState").innerHTML = [
    badge("字段白名单已执行"),
    badge("脱敏必需"),
    badge("内部黑箱已隐藏")
  ].join("");
  document.getElementById("auditState").innerHTML = [
    badge("审批必需"),
    badge("审计必需"),
    badge("未执行真实下载", "warn")
  ].join("");
  renderReadbackSummary(payload, false);
}}
function renderMissingArtifact(payload) {{
  document.getElementById("portalSummary").textContent =
    "暂无材料读回：请先在运营操作台完成项目导入、Stage7/LeadPack 生成和审批审计。";
  document.getElementById("artifactState").innerHTML =
    `<div class="empty-state"><strong>暂无客户材料</strong><p>当前商机还没有可回放的客户交付候选。系统保持下载授权、字段白名单、脱敏和审批审计门禁关闭。</p></div>`;
  document.getElementById("accessState").innerHTML = [
    badge("账号访问必需", "warn"),
    badge("下载授权必需", "warn"),
    badge("未执行真实下载", "warn")
  ].join("");
  document.getElementById("fieldState").innerHTML = [
    badge("字段白名单已执行"),
    badge("脱敏必需"),
    badge("内部黑箱已隐藏")
  ].join("");
  document.getElementById("auditState").innerHTML = [
    badge("审批必需"),
    badge("审计必需"),
    badge("客户可见发布已阻断", "danger")
  ].join("");
  renderReadbackSummary(payload || {{}}, true);
}}
loadPortal().catch(renderMissingArtifact);
"""
    return _page("AX9S 客户材料门户", body, script)


def render_customer_artifact_portal_readback(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return build_customer_artifact_access_candidate_surface(payload)
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
        }


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
]


def register_operator_frontend_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(OPERATOR_FRONTEND_ROUTES))


__all__ = [
    "OPERATOR_FRONTEND_ROUTES",
    "register_operator_frontend_routes",
    "render_customer_artifact_portal",
    "render_customer_artifact_portal_readback",
    "render_operator_console",
]
