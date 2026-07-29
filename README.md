# kaka

真实公开市场机会发现与候选公示后证据包商业化系统。

## 入口

- [`START_HERE.md`](START_HERE.md)：新手和 AI 代理先从这里开始。
- [`DEV_MODE.md`](DEV_MODE.md)：唯一的 DEV / TEST / PROD_LIVE 边界说明。
- [`CURRENT_PRODUCT_STATE.md`](CURRENT_PRODUCT_STATE.md)：当前产品开发程度和审计结论。
- [`MINIMAL_PRODUCT_PATH.md`](MINIMAL_PRODUCT_PATH.md)：先做出最小可用产品的路线。
- [`AGENTS.md`](AGENTS.md)：AI 代理默认工作规则。
- [`ARCHITECTURE_NOTE.md`](ARCHITECTURE_NOTE.md)：架构补充，不是日常入口。

默认不要遍历 `docs/` 全部文件。普通开发、补功能、修 bug 或跑验证，先读入口文件、当前产品状态和当前要改的代码/测试。

## 目录

- `src/`：核心实现。
- `tests/`：单元测试、契约测试和回归测试。
- `scripts/`：本地命令入口和运维按钮；脚本不是状态机本体。
- `docs/`：正式文档、专题说明和状态板。
- `contracts/`：机器契约。
- `control/`：任务、状态、门禁、入口登记和审计资产。
- `handoff/`：阶段间 handoff 机器资产。
- `fixtures/`：样本数据。
- `archive/`：历史稿，不作为默认入口。

## 自动化

- 正式自动化入口登记在 `control/automation_entrypoint_registry.yaml`。
- `scripts/*.ps1` 是薄入口和运维按钮，脚本不是状态机本体。
- Stage1-6 direct-dev 当前 focus 以 `control/stage1_6_priority_execution_plan.yaml#current_focus` 为准。
- Stage1-6/P0 常用入口：`stage1_6_real_public_pressure_runner`、`stage4_release_evidence_bridge_builder`、`stage6_review_cycle_runner`。
- 业务来源授权/登录态缺失：优先用 `NEEDS_AUTH`；若顶层没有该枚举，用 `authorization_readiness_state=LOGIN_OR_SSO_REQUIRED` 和 `operator_next_action` 表达。这个业务状态不替代内部 HTTP API 鉴权。
- 客户证据包生产发布：按 [`deploy/production/README.md`](deploy/production/README.md) 执行。该入口覆盖生产部署、支付、交付、退款、告警和灾备，默认失败关闭，且不会绕过独立复核。

## 内部 API

网络访问默认 fail-closed。除 `/healthz` 和内部登录页外，API 客户端都应配置 `KAKA_INTERNAL_API_TOKEN` 并发送 `Authorization: Bearer <token>`；没有配置 token 时，网络请求返回 `503`，不会静默开放。标准浏览器从 `/internal/login` 用 Bearer 凭据交换一小时的服务端签名 `HttpOnly` 会话 Cookie；同源写请求还必须携带会话绑定的 CSRF Token。Bearer 不写入 URL、localStorage、sessionStorage、Cookie 或镜像层；浏览器只在 `sessionStorage` 保存非认证用途的 CSRF Token。

建议在独立虚拟环境中运行，避免污染系统 Python 或其他工具的共享环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --require-hashes -r requirements.lock.txt
$env:KAKA_INTERNAL_API_TOKEN = '<由本机密钥管理生成的随机 token>'
$env:KAKA_INTERNAL_API_COOKIE_SECURE = 'false' # 仅限 127.0.0.1 明文 HTTP 开发
$env:PYTHONPATH = (Resolve-Path .\src).Path
.\.venv\Scripts\python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000 --no-server-header
```

非本机部署必须保持 `KAKA_INTERNAL_API_COOKIE_SECURE=true`（默认值）并由 HTTPS 反向代理提供 TLS；可用 `KAKA_INTERNAL_API_SESSION_TTL_SECONDS` 调整短时会话寿命。退出按钮会删除当前浏览器 Cookie，Bearer 轮换会立即使既有签名会话失效。

需要运行 operator 文件输入/输出能力时，应显式收紧目录：

```powershell
$env:KAKA_OPERATOR_INPUT_ROOT = 'D:\受控输入目录'
$env:KAKA_OPERATOR_ARTIFACT_ROOT = 'D:\受控产物目录'
```

容器入口会真正启动 Uvicorn，并以非 root 用户运行；Compose 默认只映射到本机回环地址：

```powershell
$env:KAKA_INTERNAL_API_TOKEN = '<由本机密钥管理生成的随机 token>'
docker compose up --build app
```

`requirements-api.txt` 与 `requirements.txt` 是直接依赖输入，部署安装只使用对应的 `requirements-api.lock.txt` 与 `requirements.lock.txt` 全传递哈希锁。默认镜像使用 API 锁，适合内部 HTTP/API、JSON/SQLite/PostgreSQL 存储与队列读写；Scrapling 浏览器、MarkItDown 和富文档解析属于 worker/browser 可选能力，不会默认塞进 API 镜像。确需构建全量能力镜像时显式执行：

```powershell
docker build --target worker --build-arg KAKA_REQUIREMENTS_FILE=requirements.lock.txt -t kaka-worker-full:dev .
```

`/healthz` 仅报告进程健康和鉴权是否已配置，不返回 token，也不代表生产 live、外部交付或真实支付已开放。

## 本地验证

依赖输入或锁有变化时先验证锁策略；正式环境必须使用哈希锁安装：

```powershell
python scripts/validate_dependency_locks.py
```

默认用隔离的 json-file 测试环境，避免被本机数据库环境变量污染：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest <相关测试> -v
```

只有改了 contracts/control/docs 同步语义时再跑：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/validate-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
```

原“专题_SKU重构收口清单.md”已退出现行引用面。
