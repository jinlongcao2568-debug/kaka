# Stage: api_operator_frontend
# Consumes formal objects: operator/customer access API readback only
# Dependent handoff: N/A
# Dependent schema/contracts: existing operator_customer_access route surfaces

from __future__ import annotations

from html import escape
from typing import Any

from fastapi.responses import HTMLResponse

from api.projections import register_route_table


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
    "customer_artifact_portal": True,
    "download_auth_required": True,
    "field_allowlist_masking_required": True,
    "approval_audit_readback_required": True,
}


def _page(title: str, body: str, script: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
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
    nav {{
      background: var(--nav);
      color: #eef5f2;
      padding: 24px 18px;
    }}
    nav h1 {{
      margin: 0 0 18px;
      font-size: 22px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    nav a {{
      display: block;
      color: #d7e6e1;
      text-decoration: none;
      padding: 10px 0;
      border-bottom: 1px solid rgba(255,255,255,.12);
      font-size: 14px;
    }}
    main {{ padding: 28px; }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 20px;
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
    input, textarea {{
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
    .wide {{ grid-column: 1 / -1; }}
    .redline {{
      border-left: 4px solid var(--danger);
      background: #fff7f6;
      color: #5c1f1a;
    }}
    @media (max-width: 840px) {{
      .layout {{ grid-template-columns: 1fr; }}
      nav {{ position: static; }}
      .grid, .rail {{ grid-template-columns: 1fr; }}
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
    body = """
<div class="layout">
  <nav aria-label="Owner console navigation">
    <h1>AX9S Owner Console</h1>
    <a href="#run">全链路运行</a>
    <a href="#workbench">Stage6-9 工作台</a>
    <a href="#providers">Provider 状态</a>
    <a href="#audit">审批审计</a>
    <a href="/customer-artifact-portal/OPP-HAPPY-001">客户 Artifact 门户</a>
  </nav>
  <main>
    <div class="topbar">
      <div>
        <h2>证据包运营操作台</h2>
        <p>任务创建、项目导入、运行状态、客户授权与审计读回集中在同一入口。</p>
      </div>
      <div class="status" id="summary">正在读取 bootstrap / readiness...</div>
    </div>
    <div class="rail" aria-label="readiness summary">
      <div class="metric"><strong id="capability">--</strong><span>operator access state</span></div>
      <div class="metric"><strong id="provider">--</strong><span>provider mode</span></div>
      <div class="metric"><strong id="scheduler">--</strong><span>queue readiness</span></div>
    </div>
    <div class="grid">
      <section id="run">
        <h3>任务创建</h3>
        <label for="taskId">Task ID</label>
        <input id="taskId" value="TASK-OWNER-127-001" />
        <label for="projectId">Project ID</label>
        <input id="projectId" value="PROJ-OWNER-127-001" />
        <button id="createTask">创建内部任务</button>
        <button class="secondary" id="importProject">导入项目</button>
      </section>
      <section>
        <h3>全链路运行入口</h3>
        <p>只接受 sanitized/offline/internal payload；Stage1-5 external live transport 仍关闭。</p>
        <label for="payload">Payload JSON</label>
        <textarea id="payload">{"payload_boundary":"SANITIZED_OFFLINE_INTERNAL","source_mode":"SANITIZED_OFFLINE_INTERNAL","run_mode":"internal_preview"}</textarea>
        <button id="previewRun">检查运行入口</button>
      </section>
      <section id="workbench">
        <h3>Stage6-9 工作台</h3>
        <div id="workbenchStatus"></div>
        <button id="refreshWorkbench">刷新工作台读回</button>
      </section>
      <section id="providers">
        <h3>Provider 与调度状态</h3>
        <div id="providerStatus"></div>
        <button id="refreshProvider">刷新 provider / scheduler</button>
      </section>
      <section id="audit">
        <h3>审批审计</h3>
        <div id="auditStatus"></div>
        <button id="refreshAudit">刷新审计读回</button>
      </section>
      <section class="redline">
        <h3>红线</h3>
        <p>本页面不执行 public software release、真实触达、真实支付、真实交付、真实退款或自动退款。</p>
        <span class="pill danger">external release blocked</span>
        <span class="pill danger">auto refund excluded</span>
        <span class="pill warn">customer access gated</span>
      </section>
      <section class="wide">
        <h3>操作结果</h3>
        <pre id="output">等待操作...</pre>
      </section>
    </div>
  </main>
</div>
"""
    script = """
const $ = (id) => document.getElementById(id);
const out = (value) => { $("output").textContent = JSON.stringify(value, null, 2); };
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
async function loadReadiness() {
  const readiness = await json("GET", "/operator-console/readiness");
  const scheduler = await json("GET", "/operator-console/scheduler-status");
  const goLive = await json("GET", "/go-live/readiness");
  $("capability").textContent = readiness.capability_state || "--";
  $("provider").textContent = readiness.provider_status?.mode || "readback";
  $("scheduler").textContent = scheduler.readiness_state || "--";
  $("summary").textContent = "Owner console ready. Customer access remains approval/audit gated.";
  $("workbenchStatus").innerHTML = [
    badge("Stage6 product package"),
    badge("Stage7 CRM/Quote"),
    badge("Stage8 outreach"),
    badge("Stage9 payment/delivery"),
    badge(`go-live ${goLive.go_live_enabled ? "enabled" : "blocked"}`, goLive.go_live_enabled ? "" : "warn")
  ].join("");
  $("providerStatus").innerHTML = [
    badge(`provider ${readiness.provider_status?.mode || "readback"}`),
    badge(`scheduler ${scheduler.readiness_state || "unknown"}`),
    badge("real provider disabled", "warn")
  ].join("");
  $("auditStatus").innerHTML = [
    badge("approval visible"),
    badge("audit visible"),
    badge("download auth required", "warn")
  ].join("");
  out({ readiness, scheduler, goLive });
}
async function createTask() {
  const payload = { task_id: $("taskId").value, project_id: $("projectId").value, now: new Date().toISOString() };
  out(await json("POST", "/operator-console/tasks", payload));
}
async function importProject() {
  const payload = { project_id: $("projectId").value, source_mode: "INTERNAL_PROJECT_IMPORT", now: new Date().toISOString() };
  out(await json("POST", "/operator-console/project-imports", payload));
}
async function previewRun() {
  let payload = {};
  try { payload = JSON.parse($("payload").value); } catch (err) { out({ error: "invalid JSON", detail: String(err) }); return; }
  out({ entry: "/internal/stage1-6/orchestrations", accepted_payload: payload, live_execution_enabled: false });
}
$("createTask").addEventListener("click", createTask);
$("importProject").addEventListener("click", importProject);
$("previewRun").addEventListener("click", previewRun);
$("refreshWorkbench").addEventListener("click", loadReadiness);
$("refreshProvider").addEventListener("click", loadReadiness);
$("refreshAudit").addEventListener("click", loadReadiness);
loadReadiness().catch(out);
"""
    return _page("AX9S Owner Console", body, script)


def render_customer_artifact_portal(payload: dict[str, Any]) -> HTMLResponse:
    opportunity_id = escape(str(payload.get("opportunity_id") or ""))
    body = f"""
<div class="layout">
  <nav aria-label="Customer portal navigation">
    <h1>AX9S Artifact Portal</h1>
    <a href="/operator-console">Owner Console</a>
    <a href="#artifact">Artifact</a>
    <a href="#access">Access Control</a>
    <a href="#audit">Download Audit</a>
  </nav>
  <main>
    <div class="topbar">
      <div>
        <h2>客户 Artifact 门户</h2>
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
      <section class="redline wide">
        <h3>客户侧红线</h3>
        <p>无授权不生成下载；内部黑箱评分、未复核推断、private/gray 数据不会展示。</p>
      </section>
      <section class="wide">
        <h3>Readback</h3>
        <pre id="output">等待读取...</pre>
      </section>
    </div>
  </main>
</div>
"""
    script = f"""
const opportunityId = {opportunity_id!r};
const out = (value) => {{ document.getElementById("output").textContent = JSON.stringify(value, null, 2); }};
function badge(text, kind="") {{ return `<span class="pill ${{kind}}">${{text}}</span>`; }}
async function loadPortal() {{
  const response = await fetch(`/customer-artifact-access-candidates/${{encodeURIComponent(opportunityId)}}`);
  const payload = await response.json();
  if (!response.ok) {{ throw payload; }}
  document.getElementById("portalSummary").textContent =
    payload.release_blocked ? "Artifact is gated by approval, account access, download auth, and audit." : "Approved customer-visible readback is available.";
  document.getElementById("artifactState").innerHTML = [
    badge(payload.capability_state || "APPROVAL_READY"),
    badge(payload.customer_visible_export_enabled ? "customer visible approved" : "customer visible blocked", payload.customer_visible_export_enabled ? "" : "warn"),
    badge(payload.external_release_enabled ? "external release enabled" : "external release blocked", payload.external_release_enabled ? "" : "danger")
  ].join("");
  document.getElementById("accessState").innerHTML = [
    badge("account control required", "warn"),
    badge("download auth required", "warn"),
    badge(payload.download_auth?.customer_download_enabled ? "download readback approved" : "download blocked", payload.download_auth?.customer_download_enabled ? "" : "warn")
  ].join("");
  document.getElementById("fieldState").innerHTML = [
    badge("allowlist enforced"),
    badge("masking required"),
    badge("blackbox hidden")
  ].join("");
  document.getElementById("auditState").innerHTML = [
    badge("approval required"),
    badge("audit required"),
    badge("real download not executed", "warn")
  ].join("");
  out(payload);
}}
loadPortal().catch(out);
"""
    return _page("AX9S Customer Artifact Portal", body, script)


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
]


def register_operator_frontend_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, list(OPERATOR_FRONTEND_ROUTES))


__all__ = [
    "OPERATOR_FRONTEND_ROUTES",
    "register_operator_frontend_routes",
    "render_customer_artifact_portal",
    "render_operator_console",
]
