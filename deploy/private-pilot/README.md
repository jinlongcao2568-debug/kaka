# Private pilot edge deployment

本目录只提供单客户私有试点的 TLS 边缘定义，不是公网、多租户或 production live 配置。

## 前置变量

- `KAKA_DEPLOYMENT_TENANT_ID`：小写字母、数字和连字符，3-63 字符。
- `KAKA_DEPLOYMENT_INSTANCE_ID`：同上；同一组副本必须使用同一实例 ID。
- `KAKA_PRIVATE_HOSTNAME`：私有 DNS 名称；本机验收可使用 `pilot.localhost`。
- `KAKA_PRIVATE_TLS_PORT`：默认 `18443`，只绑定宿主 `127.0.0.1`。
- `KAKA_PRIVATE_PRINCIPALS_FILE`：仓库外的 principal JSON 文件绝对路径。
- `KAKA_PRIVATE_POSTGRES_PASSWORD_FILE`：仓库外的 PostgreSQL 密码文件绝对路径；建议使用独立随机值且不少于 32 字符。
- `KAKA_PRIVATE_EDGE_SUBNET`：可选，edge 专用桥接网段，默认 `172.31.252.0/24`；同一宿主部署多个客户实例时必须为每个实例选择不重叠私网段。
- `KAKA_PRIVATE_EDGE_PROXY_IP`：可选，Caddy 在上述网段中的固定地址，默认 `172.31.252.254`；必须属于该网段且不能与其他容器冲突。
- `KAKA_ALERT_WEBHOOK_URL`：可选的实际告警 HTTPS webhook；只有显式启用 `alerting` profile 时需要。
- `KAKA_ALERT_ALLOWED_HOSTS`：告警目的地精确域名，必须与 webhook host 完全一致；不允许通配符。
- `KAKA_ALERT_SIGNING_SECRET_FILE`：仓库外告警 HMAC secret 文件的宿主绝对路径；至少 16 字节，建议使用 32 字节以上随机值。
- `KAKA_PRIVATE_BACKUP_ROOT`：仓库外的备份根目录；正式试点必须放在与 active data 不同的磁盘/受控备份位置。
- `KAKA_PRIVATE_RESTORE_REPORT_ROOT`：仓库外的隔离恢复报告目录。

principal 文件必须是 JSON 数组，每项只包含 `principal_id`、`role`、`token`。至少配置不同的 requester 和 reviewer；Token 不得复用到其他客户部署。不要把该文件提交到 Git，也不要放在仓库目录内。Linux 主机应把文件所有者设为部署账号并限制为 `0600`；Windows 主机应使用 ACL 只允许部署账号和管理员读取。Compose secret 只负责避免把凭据放进环境变量，并不替代宿主机静态密钥保护或外部 secret manager。

PostgreSQL 密码文件也必须执行同样的仓库外存放和最小读取权限。应用和 migration job 从同一只读 secret 文件构造连接 URL；密码不会进入 Compose 环境变量。数据库名称固定为 `<tenant-id>-<instance-id>`，不得跨客户复用数据库或数据卷。

## 启动

```powershell
docker compose -f docker-compose.private-pilot.yml config --quiet
docker compose -f docker-compose.private-pilot.yml up -d --build
```

需要启用真实 webhook 告警时，先提供上述三个 `KAKA_ALERT_*` 值，再显式启动 profile：

```powershell
docker compose --profile alerting -f docker-compose.private-pilot.yml config --quiet
docker compose --profile alerting -f docker-compose.private-pilot.yml up -d --build
```

未提供 URL、精确 host、非示例 secret 或受控出口代理时，alert dispatcher 会失败关闭。仓库内 `alert-signing-secret.example` 只用于让未启用 profile 的 Compose 配置可解析，运行时明确拒绝该值。

Compose 先等待 PostgreSQL healthy，再运行一次 Alembic migration job；只有 migration 以 `0` 退出后才启动应用。应用启动还会读取 `alembic_version` 并要求版本等于仓库 head `20260717_0002`，因此“表存在但版本落后”同样会失败关闭。PostgreSQL、migration、app 和 worker 使用无公网默认路由的 `private-backend`；app 与 Caddy 另用内部 `private-edge`；Caddy 单独接入 `public-ingress` 并使用固定 edge 私网 IP；受控出口代理单独接入 `public-egress`。应用容器和 PostgreSQL 都没有宿主端口，Uvicorn 只信任这一个 Caddy IP 传入的代理头，不再使用 `*`。Caddy 只把 TLS 端口绑定到 `127.0.0.1`，使用内部 CA、严格 SNI/Host、HSTS 和安全响应头；后端同时执行 Host 白名单。应用以非 root 用户运行；Caddy 官方镜像为绑定容器内 `443` 端口仍以 root 启动，但已删除全部 capability 后只恢复 `NET_BIND_SERVICE`，并启用只读根文件系统和 `no-new-privileges`。

运行镜像按能力拆分：`app` 使用 Dockerfile 的 `api` target，只按哈希安装 `requirements-api.lock.txt` 并只承担 HTTP；`worker` 按哈希安装 `requirements.lock.txt` 的完整依赖但不安装浏览器，只消费 `required_worker_capability=core` 的内部准备任务；`browser-worker` 额外安装 Chromium，只消费 `required_worker_capability=browser` 的自主机会搜索和白名单公开源采集任务。browser worker 没有直接公网路由，urllib、curl、Scrapling 和 Playwright 在 private-pilot 中统一经 `egress-proxy`；代理只允许 18 个正式 Stage2 来源域名、部署文件中显式登记的 13 个广东当前主线域名，以及启用告警时显式提供的精确告警域名，不接受通配域名。三者共享同一客户的 PostgreSQL 队列和私有数据卷，但不共享进程；这些后台任务仍为 internal-only，不表示客户触达、支付、交付、退款或 production live 已开放。

API、core worker、browser worker 与可选 alert dispatcher 会把实际运行事件写到共享数据卷的 `/app/.kaka-local/runtime/operational-events-v1.jsonl`，同时输出结构化 stderr；认证后的 `/internal/observability` 和 `/internal/observability/metrics` 提供实际事件聚合与 Prometheus 文本。抓取、队列、解析、SQLAlchemy DB 和内部交付记录均已接入；观测写入异常不会替代业务结果。alert dispatcher 持久记录去重、重试和死信，只发送 `ERROR/CRITICAL`，并忽略自身事件防止递归。固定 SKU 证据包仍要求人工签发，事件中的 `external_delivery_executed=false` 不能解释为已经完成客户交付。

固定 SKU 的门户读回、预览 JSON、manifest、HTML、PDF 和 ZIP README 必须共同消费 `contracts/sales/customer_delivery_boundary_contract.json`。当前交付方式是人工复核签发后通过客户约定的受控渠道交接；自动邮件和客户自助下载均未开放。部署方不得修改页面文案去暗示自动交付能力，也不得从 manifest 恢复申请人、复核人、principal、内部推理或内部字段黑名单。

## 模型 Provider（默认关闭）

可替换的 OpenAI Responses-compatible 适配层位于 `src/shared/model_provider_runtime.py`，运行边界由 `contracts/model/model_provider_runtime_contract.json` 冻结。它只允许候选提取、证据摘要、复核解释和内部文案草稿；工具调用、正式事实写入、客户可见输出和自动执行始终关闭。普通 Stage1-7 流程仍走确定性实现，不会因为配置了 API key 自动发起模型请求。

当前 private-pilot Compose 没有注入模型凭据，也没有把模型域名加入出口代理白名单，因此真实外部调用默认不可达。首次内部影子 canary 必须由模型治理 owner 显式批准，在仓库外创建单行 secret 文件，并同时配置精确 provider/model/host、`PASSED` eval 状态和非空审计引用。凭据不得放进环境变量、仓库、请求 JSON 或输出文件；输出文件也必须位于仓库外且不能覆盖已有文件。

受控出口已批准时优先提供 `KAKA_CONTROLLED_EGRESS_PROXY_URL`；只有单次受监督 canary 获得明确直连批准时才设置 `KAKA_MODEL_PROVIDER_DIRECT_HTTPS_ALLOWED=true`。`KAKA_MODEL_PROVIDER_KILL_SWITCH=true` 会无条件切到 `EMERGENCY_OFF`。示例（占位值不能直接用于验收）：

```powershell
$env:KAKA_MODEL_PROVIDER_MODE = "INTERNAL_SHADOW"
$env:KAKA_MODEL_PROVIDER_ID = "openai_responses"
$env:KAKA_MODEL_PROVIDER_BASE_URL = "https://api.openai.com/v1"
$env:KAKA_MODEL_PROVIDER_ALLOWED_HOSTS = "api.openai.com"
$env:KAKA_MODEL_PROVIDER_MODEL = "<approved-model-id>"
$env:KAKA_MODEL_PROVIDER_API_KEY_FILE = "C:\secure\kaka-model-api-key"
$env:KAKA_MODEL_PROVIDER_SHADOW_APPROVAL_STATE = "APPROVED"
$env:KAKA_MODEL_PROVIDER_SHADOW_AUDIT_REF = "<approval-or-change-ticket>"
$env:KAKA_MODEL_PROVIDER_EVAL_STATE = "PASSED"
$env:KAKA_MODEL_PROVIDER_DIRECT_HTTPS_ALLOWED = "true"
python .\scripts\run_model_provider_shadow_canary.py `
  --request C:\kaka-pilot-evidence\model-shadow-canary-request.json `
  --output C:\kaka-pilot-evidence\model-shadow-canary-result.json
```

Canary 成功结果只是 `COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED`，必须人工复核；超时、网络、429、拒绝、非法 Schema、虚构来源或不安全结论会写出 `FALLBACK_DETERMINISTIC_REVIEW_REQUIRED` 并以非零状态退出，失败模型内容不会进入降级结果。受限输入、非法请求和 Provider 未启用仍直接失败关闭。任何结果都不会修改项目事实、证据门、审批门、销售对象或交付对象。

AGENT005 的离线协议金标可直接运行，不访问外网，也不能产生真实延迟、token 或费用结论：

```powershell
python .\scripts\run_model_quality_evaluation.py `
  --mode offline `
  --output .\output\model-evaluation\agent005-offline-quality-report.json `
  --overwrite
```

真实质量门必须把 `contracts/testing/model_provider_quality_golden_cases.json#real_quality_cases` 的 12 个 case 逐项执行并人工标注。先生成 hash 绑定的请求与未执行 manifest；这一步不会调用 Provider：

```powershell
python .\scripts\build_model_quality_canary_requests.py `
  --output-dir C:\kaka-pilot-evidence\model-quality-requests
```

对 manifest 中每个 request 运行上面的单例 canary，把结果文件路径填到对应 `result_path`，并完成四项 `human_review` 与 `reviewer_ref`。然后连同经过审批且精确匹配 provider/model 的版本化价格快照评估。没有价格快照时费用为 `WITHHELD`，不是 0；没有真实外部调用证据或 request hash 不匹配时整套结果仍为外部阻断。模型或 prompt 版本变化还要提供已批准 baseline，若人工接受率、幻觉/越界率、trace 完整性或 p95 延迟退化则阻断变更：

```powershell
python .\scripts\run_model_quality_evaluation.py `
  --mode real-results `
  --input C:\kaka-pilot-evidence\model-quality-requests\model-quality-canary-manifest.json `
  --pricing-snapshot C:\kaka-pilot-evidence\approved-model-pricing.json `
  --baseline C:\kaka-pilot-evidence\approved-model-quality-baseline.json `
  --output C:\kaka-pilot-evidence\model-quality-report.json
```

仓库内 example 和离线报告都不能作为真实 Provider 证据。当前没有真实 canary、12 例人工复核、核准价格快照或版本 baseline，因此 AGENT001/005 只能记为“代码与离线协议验证通过、真实模型质量/成本验收外部阻塞”。

## 智能体对话入口（内部受控）

认证后的运营操作台包含“智能体对话”入口，可用自然语言创建 Stage1 内部预览任务、查询任务进度、追问已有证据和读取下一步。当前回答由确定性规则和正式存储对象生成，即使模型 Provider 保持 `OFF` 也可使用；每项事实必须带正式对象或登记来源引用，查询未命中会明确显示“证据不足/未找到不等于没有风险”。

创建任务必须提供项目 ID 并显式勾选确认。确认前不会写入队列；确认后只创建幂等的 `SANITIZED_OFFLINE_INTERNAL` 任务，真实公开源抓取仍关闭。对话入口自身不自动调用工具、客户触达、支付、退款、客户交付或发布，也不保存长期对话历史。不要输入密码、Token、Cookie、身份证、银行卡或未脱敏原文。

独立的 `/operator-console/agent/plans` 提供内部工具计划协议，只接受 `contracts/agent/agent_tool_registry.json` 中登记的结构化 function call。参数 Schema 为 strict、拒绝额外字段，关闭并行调用；最多 4 步、最多执行 3 个确定性只读调用、单工具最多 2 次、无重试，并保留 `call_id`、输入/输出 hash 和持久审计。当前可执行能力包括任务状态、项目证据、下一步、内部任务方案和安全记忆上下文读取；“创建任务”只能返回人工交接并停在操作台显式确认，planner 不会自行恢复执行。未登记的邮件、电话、支付、退款、交付、发布、任意 HTTP/shell 和正式事实写回全部拒绝。真实模型 Provider 仍保持工具调用关闭；只有 AGENT-001 的真实影子调用和 AGENT-005 评估完成后，才可考虑把模型提出的结构化调用接入本协议。

受治理记忆使用 `GET/POST /operator-console/agent/memories`。只允许登记的个人偏好和项目工作备注；租户与 principal 由认证层绑定，项目记忆必须显式指定项目。纠正和删除都要求当前 `expected_version`，删除/过期立即清空原值，审计只留 hash。所有记忆均为 `UNVERIFIED_CONTEXT_ONLY`，不能作为事实、证据、citation、gate 或审批；系统不保存原始对话历史。当前是单客户一实例，不得把这一能力解释为共享 SaaS 多租户隔离。

## 产品配置与受控入驻（owner/admin）

认证后的运营操作台“产品配置”入口只服务当前私有单租户实例的 owner/admin，不是客户自助 SaaS onboarding。普通 operator/reviewer 无权访问。配置只能选择登记目录里的地区及其默认来源，行业固定为 `CONSTRUCTION_PUBLIC_EVIDENCE`，证据模板固定为 `SKU_B_PUBLIC_SOURCE_FOUR_FIELD_RISK_REVIEW`，候选、详情、附件和任务时间预算均有上限；接口不接受自由来源 URL、自由来源 ID、live 开关或审批覆盖字段。

变更顺序固定为“保存新草稿版本 → 对同一版本和配置 hash 做离线试跑 → 显式激活”。离线试跑不创建任务、不抓取来源、不调用模型，也不触发触达、支付、退款、客户交付或发布。回滚只能选择历史活动版本，并生成新的活动回滚版本，历史配置不可改写。任何配置都不能扩大来源白名单或绕过审批/放行门。

API 为：

- `GET /operator-console/onboarding/configs?include_history=true`
- `POST /operator-console/onboarding/configs`
- `POST /operator-console/onboarding/config-test-runs`

部署完成后，owner 应先在页面创建安全草稿并完成离线试跑。只有页面显示活动版本，才表示当前实例已有受治理的产品配置；这仍不表示真实公开源执行、客户自助、多租户 SaaS 或外部交付已开放。

## 运营支持与失败任务恢复（owner/admin）

运营操作台“运营支持”页面和 `GET /operator-console/support/overview` 汇总当前私有实例的任务、阻断、队列审计和版本。它只显示当前部署租户，不能跨租户查询；任务只返回队列、状态、任务/项目 ID、进度、错误分类和更新时间等 allowlist 摘要，不返回 raw task payload、raw error 或 audit detail。

失败或死信任务可以在页面点击“受控重试”，也可调用 `POST /operator-console/support/task-actions`。请求必须携带页面刚读到的 `expected_status`、`expected_updated_at`、至少 10 字的安全原因和精确确认 `RETRY_FAILED_INTERNAL_TASK`；页面还会弹出二次确认。成功只把原队列项转为 `retry` 并记录 `manual_retry_queued`，不会修改任务 payload 或项目事实。状态已变化、确认不精确、原因含敏感信息，或任务打开了 live/客户可见/支付/交付/自动退款边界时均失败关闭。

支持工作台不提供事实、证据、规则门、审批门或交付对象编辑器。运行中长任务取消继续使用现有协作取消路径；真实告警目的地、值班、跨租户客服和 production live 自动修复不属于当前私有试点能力。

## 备份、隔离恢复和版本回滚

备份工具使用与服务端同 major 的 `postgres:18.4-alpine3.24`，以 custom-format `pg_dump` 备份数据库，同时把当前客户 object storage 打成 tar.gz，并生成逐文件 SHA-256 inventory、三项 artifact hash、schema revision、核心表计数、备份耗时和估算 RPO。密码只通过 secret-file 生成临时 `PGPASSFILE`，不会进入命令行、manifest 或 stdout。备份目录先写 `.partial`，全部校验完成后才原子改名；相同 backup ID 不可覆盖。

由于数据库与本地对象目录不是同一事务，当前单宿主试点必须短暂停止 API/core/browser writer。脚本会记住原本运行的 writer、停止后执行备份并校验，然后默认恢复原运行集合；不允许仅靠环境变量假装 writer 已暂停：

```powershell
.\scripts\backup-private-pilot.ps1 `
  -TenantId customer-a -InstanceId primary -PrivateHostname pilot.localhost `
  -PrincipalsFile C:\secure\customer-a-principals.json `
  -PostgresPasswordFile C:\secure\customer-a-postgres-password `
  -BackupRoot E:\kaka-backups\customer-a -BackupId BACKUP-customer-a-primary-20260720T120000Z `
  -PauseWriters
```

隔离恢复不会连接或清理 active PostgreSQL/`pilot-data`。Compose 会启动只接 `restore-isolated` 内部网络的 `restore-postgres`、独立 DB volume 和独立 object volume；恢复前校验 manifest/artifact/inventory，恢复后核对 Alembic revision、六类核心表计数和每个对象 hash，并把实际耗时写成 RTO report。精确确认串由脚本生成，目标目录或同名报告已存在时失败关闭：

```powershell
.\scripts\restore-private-pilot-isolated.ps1 `
  -TenantId customer-a -InstanceId primary -PrivateHostname pilot.localhost `
  -PrincipalsFile C:\secure\customer-a-principals.json `
  -PostgresPasswordFile C:\secure\customer-a-postgres-password `
  -BackupRoot E:\kaka-backups\customer-a `
  -BackupId BACKUP-customer-a-primary-20260720T120000Z `
  -RestoreReportRoot E:\kaka-restore-reports\customer-a `
  -ConfirmIsolatedRestore
```

应用、worker、browser worker、migration 和 egress/alert 镜像统一使用 `KAKA_IMAGE_TAG`。上一版本回滚要求三类 previous image 已在本机、存在属于同一 tenant/instance 的完整 backup manifest，并显式确认。脚本停用可选 alert dispatcher，使用 `--no-build --wait` 健康门切回 previous tag；失败会立即用 `CurrentImageTag` 做前向恢复。脚本绝不自动 downgrade schema 或把备份覆盖回 active data；旧镜像若不接受当前 schema，会启动失败并回到当前镜像：

```powershell
.\scripts\rollback-private-pilot-release.ps1 `
  -TenantId customer-a -InstanceId primary -PrivateHostname pilot.localhost `
  -PrincipalsFile C:\secure\customer-a-principals.json `
  -PostgresPasswordFile C:\secure\customer-a-postgres-password `
  -CurrentImageTag 2026.07.20.2 -PreviousImageTag 2026.07.20.1 `
  -ValidatedBackupManifest E:\kaka-backups\customer-a\BACKUP-customer-a-primary-20260720T120000Z\manifest.json `
  -RollbackReportRoot E:\kaka-rollback-reports\customer-a `
  -ConfirmReleaseRollback
```

直接运行 Compose profile 时，`./output/...` 只是本地配置解析/开发兜底，不是合格备份位置；正式试点必须通过上述脚本传入仓库外绝对路径，并由外部 scheduler 按 RPO 周期触发。只有至少一次真实容器备份、一次隔离恢复报告和一次 previous-image 健康回滚演练通过后，才能把 OPS-005 写成部署已验证。

请求防护采用双层限制：Caddy 在转发前对实际 body 读取设置 `2MB` 上限；应用不信任 `Content-Length`，会在 JSON 解析前逐块累计并再次限制为 `2097152` 字节。搜索、公开源采集、Stage1-6 编排和灰度准备/入队按“tenant + principal”共享每分钟 `20` 次、同时 `2` 个的门禁，超过时返回 `429` 和 `Retry-After`。该 limiter 位于单 API 进程内，符合当前单宿主/单 API private-pilot；扩展为多 API 副本前必须改为共享限流后端。

SSRF 防护采用“精确域名 + 实际连接 IP”双门禁。urllib/curl 直连模式把本轮解析并验证为公网的数值 IP 绑定到 socket；private-pilot 的不可绑定传输统一交给受控出口代理，代理重新解析目标，任一 DNS 答案属于私网、loopback、link-local、云元数据或其他非 global 地址即拒绝，并直接连接已验证数值 IP。代理只允许 80/443、同源后续请求和有限请求/响应体；`KAKA_CURL_EXTRA_ARGS` 不能覆盖 URL、Host、proxy、resolve 或 socket。GDCIC 历史 `210.76.80.152:8008` 非标准端口继续失败关闭，且已按 EVD-002 从当前固定范围必需来源中移除。

## 产品价值观察与验收

产品价值验收必须使用同一 clean cohort，不允许把 follow-up/projection 样本并入分母。现有真实运行结果可直接提供发现阶段分母，命令如下：

```powershell
$env:PYTHONPATH = "src"
python -m storage.product_value_acceptance `
  --scoreboard C:\kaka-pilot-evidence\stage1-6-sellable-scoreboard-v1.json `
  --run-result C:\kaka-pilot-evidence\run-result.json `
  --observations C:\kaka-pilot-evidence\product-value-observations.json `
  --output C:\kaka-pilot-evidence\product-value-acceptance-v1.json
```

`product-value-observations.json` 是单一 pilot 时间窗的内部审计输入，至少包含：

- `observation_window.batch_id/started_at/ended_at`，时间必须含时区。
- `evidence_bundle_observation_window_complete` 和 `evidence_bundles`；每个包必须有同一 cohort 的 `project_id`、`opportunity_id`、生成时间和正式包状态。
- `human_review_observation_window_complete` 和 `human_review_logs`；每项必须有 `work_log_id`、`project_id`、匿名 operator ID、`HUMAN_REVIEW`、起止时间和 action/source ref。同一 operator 的重叠时段会被拒绝。
- `outcome_observation_window_complete` 和 formal `opportunity_outcomes`；真实客户记录必须增加 `value_observation.real_customer_confirmed=true` 与非空 `confirmation_ref`。
- `payment_observation_window_complete` 和 formal `payment_records`；退款阶段与原因沿用 `refund_state`、`payment_exception_family_optional` 和 reason tags。

只有观察窗被明确标记完整时，“没有包、零分钟、零采用或零退款”才可作为真实 `0`；文件缺失或窗口未完成时报告会输出 `WITHHELD_*`，不会把未知写成零。preview、dry-run、sandbox、fixture、sample outcome/payment 会失败关闭。报告仍是 internal-only；它不授权客户可见、外发、支付或退款。

## 客户端信任

Caddy 内部 CA 不会自动进入宿主或客户设备信任库。由部署管理员从 edge 容器导出：

```powershell
docker compose -f docker-compose.private-pilot.yml cp edge:/data/caddy/pki/authorities/local/root.crt ./kaka-private-ca.crt
```

只通过受控设备管理方式安装根证书。测试请求示例：

```powershell
curl.exe --cacert .\kaka-private-ca.crt --resolve pilot.localhost:18443:127.0.0.1 https://pilot.localhost:18443/healthz
```

Windows `curl.exe` 使用 Schannel 时可能对内部 CA 返回吊销状态未知，可在本机私有试点 smoke 中追加 `--ssl-no-revoke`；不要用该参数替代正式公网证书和证书生命周期治理。

Windows Schannel 若因内部 CA 无撤销端点返回 `CERT_TRUST_REVOCATION_STATUS_UNKNOWN`，仅在本机验收时可追加 `--ssl-no-revoke`；这不会代替正式设备信任分发。

## 仍未完成

- 业务记录后端已切换到每客户独立 PostgreSQL 18.4；本轮只承诺单宿主私有试点，不代表跨主机高可用数据库集群。
- API、core worker 和 browser worker 已分镜像/进程编排；browser worker 已登记自主机会搜索和白名单真实公开源采集两类 job kind。操作台始终异步入队，private-edge HTTP 入口会强制异步；本地直接 Python 调用保留同步回归兼容，不属于部署运行路径。
- migration job 已接入启动依赖；schema version 健康门、失败升级/旧版本升级演练和回滚闭环仍由 `OPS-003` 处理。
- 当前只提供本机 loopback TLS；变更为内网地址前必须完成防火墙、DNS、证书分发和 Host 验收。
- 当前 edge 采用最小 capability 的官方 Caddy root 进程；若客户基线强制全容器 rootless，需要另做高端口监听和持久卷权限初始化后再验收。
- SEC-005 的 edge body、应用流式 body 与单实例 principal 限速/并发门禁已接入；SEC-007 的精确域名出口代理、私网 DNS 拒绝和连接 IP 绑定已接入。多 API 副本的共享 limiter 不在当前 private-pilot 范围；出口域名扩展必须先进入正式来源登记或部署级显式白名单，不能使用通配符。
- 仓库内实际日志、指标、错误 trace 和 webhook dispatcher 已完成；客户真实 paging/webhook 目的地、联系人轮值和容器内实发验收仍由 `OPS-004` 外部关闭。OPS-005 已具备 PostgreSQL/object backup、隔离 restore drill、RPO/RTO report 和 previous-image rollback 代码路径；真实容器演练及外部调度仍未完成。
- `PRIVATE_SINGLE_TENANT` 不允许两个客户共享实例、卷、数据库、对象存储、网络或 principal 文件。

实现依据：[Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)、[Docker Compose internal networks](https://docs.docker.com/reference/compose-file/networks/#internal)、[Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、[Caddy request_body](https://caddyserver.com/docs/caddyfile/directives/request_body)、[Caddy tls internal](https://caddyserver.com/docs/caddyfile/directives/tls)、[Uvicorn 可信代理头配置](https://www.uvicorn.org/settings/#http)。
