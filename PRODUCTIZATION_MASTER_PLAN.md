# Kaka 智能体产品化攻克总表

**版本**：2026-07-20 v19
**状态**：ACTIVE_WORKING_CHECKLIST
**目标**：把当前内部 owner-operated 证据包工作流，逐步收敛为可受控部署、可试点、可收费的企业私有智能体产品。
**边界**：本文件是问题汇总与执行清单，不是当前状态源，不替代 `control/current_task.yaml`、`control/product_task_library.yaml`、`control/repo_status.md` 或 `control/stage1_6_priority_execution_plan.yaml#current_focus`。

## 1. 使用规则

后续开发统一从本表选择问题编号，不再依赖聊天记忆。

每次只处理一个问题，或一个无法拆开的依赖小组，并按下面顺序关闭：

1. 写清问题证据和影响面。
2. 在 `修复 / 变通 / 砍掉 / 后置` 中选择一种决策。
3. 做最小闭环实现。
4. 跑对应验收，不用“代码存在”或“测试很多”替代产品结果。
5. 更新本表状态、验证证据和剩余风险。

状态只使用：

- `OPEN`：已确认，尚未开始。
- `IN_PROGRESS`：正在处理，尚未通过验收。
- `VALIDATED`：实现和验收都已完成。
- `WORKAROUND_ACCEPTED`：正式接受替代路径，原能力不再阻塞当前产品。
- `CUT`：从当前或最终产品承诺中删除。
- `DEFERRED`：不阻塞当前阶段，保留未来可能性。
- `BLOCKED_EXTERNAL`：依赖授权、服务商、客户或外部状态，代码不能单独解决。

优先级定义：

- `P0`：当前对外部署或收费试点阻断项。
- `P1`：企业私有试点稳定性和核心价值阻断项。
- `P2`：智能体产品化和规模化阻断项。
- `P3`：后续 SaaS、外部执行或扩张能力。

## 2. 最快可售产品裁剪

### 2.1 当前保留

- 固定地区、固定公开来源的候选发现。
- 列表、详情、附件快照和字段解析。
- Stage4 公开核验与来源阻断说明。
- Stage5 证据等级、规则门和人工复核。
- Stage6/7 内部证据包、商业钩子、买家匹配和 LeadPack 候选。
- 单租户、企业私有或由 owner 托管运行。
- 人工复核后，通过受控方式向客户交付文件。
- 人工报价、人工收款、人工开票和人工退款。

### 2.2 当前后置

- 多租户 SaaS。
- 全国全省全量来源覆盖。
- 客户自助注册、订阅、付款和下载。
- 自动邮件、短信、电话、企业微信触达。
- 实时 CRM 双向同步。
- 在线支付网关和自动对账。
- 生产自动退款。

### 2.3 永不直接承诺

- 不承诺公开数据绝对完整、绝对实时或零遗漏。
- 不承诺绕过登录、SSO、验证码、授权或网站访问限制。
- 不把 `NOT_FOUND`、`BLOCKED`、`NEEDS_BROWSER`、`LOGIN_OR_SSO_REQUIRED` 写成无风险或排除结论。
- 不输出无人复核的法律结论，不替代律师、招投标专家或客户最终判断。
- 不采集或推断无合法公开/授权依据的身份证、社保、私人联系方式等受限数据。

## 3. P0：部署与收费试点阻断项

| ID | 问题 | 当前证据/影响 | 默认决策 | 关闭标准 | 状态 |
|---|---|---|---|---|---|
| REL-001 | 当前修复没有形成可发布基线 | 工作树有大量未提交修改，CI、迁移和最小依赖文件未跟踪；从 Git 构建可能缺少当前修复 | 修复 | 审核 diff；关键回归通过；全部预期文件进入一个可追踪提交；生成版本号和变更说明；工作树只剩已确认的无关修改 | VALIDATED |
| SEC-001 | 标准浏览器认证链不可用 | `src/api/main.py` 要求 Bearer；`src/api/routes/operator_frontend.py` 的 `fetch()` 不携带 Bearer；TestClient 旁路掩盖真实浏览器 401 | 修复 | 选择 OIDC/SSO 或服务端 HttpOnly session；页面导航和异步请求都可认证；写请求有 CSRF 防护；未认证、过期、越权测试齐全；不把 token 放 URL/localStorage | VALIDATED |
| SEC-002 | 操作台存在 DOM XSS 面 | `operator_frontend.py` 大量 `innerHTML`；项目名、商业摘要、badge 等路径存在未统一转义的 API/公开来源数据 | 修复 | 不可信字段全部使用 `textContent`/安全 DOM 构造；剩余 HTML sink 有集中审计；加入恶意项目名回归；部署 CSP、frame 防护和必要安全头 | VALIDATED |
| TST-001 | 顶层文档同步测试与现行导航规则冲突 | `test_docs_business_direction_sync.py` 仍要求 README/AGENTS 复制几十条业务策略，但 `74f20a49` 已明确把顶层文件收敛为导航，且 AGENTS 禁止在此保存业务状态 | 修复测试 | 顶层测试只验证最小入口和职责边界；正式策略继续由业务方向文档和机器契约承载；定向与全量回归通过 | VALIDATED |
| SEC-003 | 认证、角色、审批被混为一体 | 旧版单个共享 token 获得多项权限，认证后直接投影 `approval_audit_confirmed=true`；客户/租户级对象所有权仍由 `SEC-004` 处理 | 修复 | 身份认证与业务审批分离；至少有 owner/operator/reviewer/admin 角色；敏感动作逐对象授权；审批记录不可由普通认证自动满足 | VALIDATED |
| SEC-004 | 没有租户/客户数据隔离边界 | 所有已认证调用者可访问同一内部数据和产物；不适合客户共享部署 | 变通后修复 | 当前 MVP 明确为单租户私有部署；用部署级隔离阻断跨客户访问；进入 SaaS 前实现 tenant_id、对象级授权、存储隔离和越权测试 | WORKAROUND_ACCEPTED |
| API-001 | 大部分写接口不是严格契约 | 当前 34 个内部写操作均已绑定严格请求/响应 Schema、拒绝未知字段并经过启动审计；智能体、产品配置和运营支持入口均独立归类，不再混入只读 readiness 路由组 | 修复 | 所有对产品状态有写入的接口有明确 Pydantic 请求/响应模型；拒绝未知字段；敏感字段分离内部/外部响应；OpenAPI 与运行读回一致 | VALIDATED |
| OPS-001 | 当前 Compose 只是本地定义 | `docker-compose.yml` 标记 `local_stack_definition_only`，只绑定 `127.0.0.1`，默认 JSON 文件存储 | 变通后修复 | 本地模式保持不变；新增独立 private-pilot 部署配置；TLS/反代/Host 限制/密钥注入明确；不得把本地 Compose 改名冒充生产配置 | VALIDATED |
| OPS-002 | 默认 JSON 文件不能承担多实例生产 | private-pilot 已切换 PostgreSQL 18.4、密码文件注入和 migration-before-app；静态/单元契约已通过，真实容器验收受当前 Docker Desktop daemon 无响应影响 | 修复 | 私有试点使用 PostgreSQL；启动前执行迁移；并发、幂等、唯一约束、事务和重启恢复测试通过；JSON 只保留开发/单进程模式 | BLOCKED_EXTERNAL |
| OPS-003 | PostgreSQL 迁移没有部署闭环 | 已新增显式 migration-before-app job、password-file CLI 和 `alembic_version=head` 启动门禁；空库/旧库真实 PostgreSQL 升级及失败发布演练受 OPS-002 同一 Docker daemon 锁阻断 | 修复 | 提供显式 migration job/命令；数据库健康与 schema version 检查；升级失败停止发布；完成一次空库安装和一次旧版本升级演练 | BLOCKED_EXTERNAL |
| EVD-001 | Stage4 释放证据链仍是核心瓶颈 | clean/projection 分母混淆和 data.ggzy/YGP 字段回写已修复，公开来源 URL/hash/标识符可进入 Stage4 queue 与 fallback plan；但 clean live30 仍不可售，GDCIC 项目经理变更缺合法授权会话 | 修复+限定范围 | 先固定广东/广州来源与四类核验；clean batch 明确分母；可回放 source URL/snapshot/hash/B-C-D/阻断/下一步；未命中不形成排除结论 | BLOCKED_EXTERNAL |
| PROD-001 | 尚无可收费的正式交付协议 | 已冻结 `SKU-B` 单项目四类公开来源履约风险证据核验包；Stage4 结构化核验记录可经 Stage6/7 进入 PDF/HTML/JSON/ZIP，缺真实记录、必要字段或逐对象审批时签发前失败关闭 | 修复 | 定义一个固定 SKU；生成可人工签发的 PDF/ZIP/HTML 证据包；包含版本、来源、时间、证据等级、限制声明、水印和交付审计；无需真实支付网关即可交付 | VALIDATED |

## 4. P1：核心业务效果与私有试点稳定性

| ID | 问题 | 当前证据/影响 | 默认决策 | 关闭标准 | 状态 |
|---|---|---|---|---|---|
| EVD-002 | GDCIC 授权会话缺少真实命中样本 | 真实授权命中仍为 0；现已把无授权 live 请求改为预检后零网络跳过，明确 `LOGIN_OR_SSO_REQUIRED` 并路由替代公开来源，GDCIC 不再阻断当前固定范围产品 | 变通 | 有合法授权会话时走授权浏览器；没有授权时跳过该来源并显示阻断；取得至少一个真实授权命中回放后再评估是否长期保留 | WORKAROUND_ACCEPTED |
| EVD-003 | P13B 和字段查询结果回灌仍不稳定 | 字段查询现会按项目自动固化 Stage5 校准样本，Stage6 从同一字段查询目录自动发现并合并；地区 adapter、授权 browser 和人工 truth-label 的责任层分别可路由 | 修复 | 同一项目从重叠信号到字段查询、Stage5、Stage6 状态可回放；失败能自动指向 adapter/browser/operator，而不是依赖人工记忆 | VALIDATED |
| DATA-001 | Stage3 负责人/OCR/复杂表格仍有误抽漏抽 | 已建立 5 例可回放金标（4 例真实公开结构、1 例受控 OCR 文本），负责人、证书、候选行和联合体成员均有分字段指标；“达到”等假姓名已在 Stage2/3/压力桥/Stage16 统一阻断，低置信度身份强制 REVIEW | 修复 | 建立真实金标集；分字段统计 precision/recall；关键身份字段低置信度必须 REVIEW；错误样本进入回归库 | VALIDATED |
| DATA-002 | 长尾附件、SPA、验证码和下载端点仍不稳定 | 已固化入口/详情/附件大小、格式、登记来源和终态契约；支持集内可回放或有限重试，SPA/挑战页、超大或不支持内容明确阻断，浏览器升级有硬预算且默认关闭 | 修复+砍尾部 | 固定支持的内容类型、大小和来源；支持集内可重试/回放；超出支持集明确 `BLOCKED/UNSUPPORTED`，不无限自动升级浏览器 | VALIDATED |
| DATA-003 | 来源覆盖率和新鲜度没有产品指标 | 已按 23 个登记入口逐源记录最后成功时间、观察窗口、列表/详情/附件覆盖和阻断率；dry-run、未观察、过期、查询无匹配和技术阻断已分离 | 修复 | 每个来源记录最后成功时间、列表覆盖、详情覆盖、附件覆盖、阻断率；对外只承诺已登记来源和时间窗口 | VALIDATED |
| RULE-001 | Stage5 缺少足够真实样本校准 | 已汇总 12 份真实执行清单、246 条观察并去重为 116 个真实项目；金标合同、可续标包、前后规则对比及误报/漏报评估器已完成，但 116/116 仍待人工真值标注，指标被正确扣留 | 修复+人工校准 | 先完成不少于 50 个去重真实项目金标；输出误报、漏报、REVIEW 占比；每次规则调整有前后对比；不以单一命中率代替证据质量 | BLOCKED_EXTERNAL |
| RUN-001 | 没有真正无人值守的周期调度 | 已复用现有持久队列实现独立 scheduler worker、周期任务、租约/心跳/重试/暂停/死信/重启恢复；Web `run-once` 已禁用执行，当前无人值守范围仅为内部 prepare-only，真实 live 执行仍关闭 | 修复 | 独立 worker/scheduler 进程；任务租约、心跳、重试、暂停、死信可观察；重启后续跑；不在 Web 请求内执行长链 | VALIDATED |
| RUN-002 | 长任务缺少完整进度、取消和预算边界 | 持久队列已补阶段/百分比/心跳/预算截止/协作取消/超时和错误分类；自主搜索、真实源采集和受控灰度任务均异步入队并返回 job_id，操作台显示和取消已接入；private-edge HTTP 强制异步，本地直接函数仅保留回归兼容 | 修复 | 所有部署长任务异步入队；返回 job_id；页面显示阶段进度、最近心跳、预算、超时、取消、重试和错误分类 | VALIDATED |
| RUN-003 | API 镜像与完整 worker 能力分离但未编排 | Dockerfile/private-pilot 已定义 API、core worker、browser-worker 三类 target/service；core prepare 与 browser 搜索/采集 job kind 按 payload capability 精确路由，静态配置和路由测试通过；真实镜像构建/启动仍受当前 Docker daemon 锁阻断 | 修复 | API、worker、browser-worker 明确拆分；Compose/private-pilot 配置能启动对应服务；任务按能力路由；API 容器不承担浏览器任务 | BLOCKED_EXTERNAL |
| SEC-005 | 请求体限制只依赖 Content-Length | 已修复缺失/伪造 Content-Length 绕过；Caddy 与应用双层 body 门禁、昂贵写操作 tenant+principal 速率/并发限制和 429 读回已验证 | 修复+单实例变通 | 边缘代理限制 body；应用层流式计数；搜索、抓取和编排等昂贵任务按用户/租户限流；多 API 副本前改共享 limiter | VALIDATED |
| SEC-006 | 缺少生产 Host、代理信任与安全响应头配置 | 已启用 Host 白名单、固定 edge 代理 IP/双网络隔离、动态 nonce CSP 和 edge/app 安全响应头；通配代理信任已删除 | 修复 | private-pilot 配置明确 allowed hosts 和可信代理 IP；运行测试读取真实响应头；CSP 不依赖 `unsafe-eval`/`unsafe-inline`；inline script 受逐响应 nonce 约束 | VALIDATED |
| SEC-007 | SSRF 仍有 DNS 校验与实际连接之间的竞态 | urllib/curl 已绑定本轮验证 IP；不可绑定 transport 经精确域名 egress proxy 二次解析并绑定；业务容器无直接公网路由 | 修复+基础设施缓解 | 允许域名清单；连接时绑定已验证 IP 或经受控 egress proxy；云元数据和内网由网络层阻断；保留重定向与子请求测试 | VALIDATED |
| SEC-008 | 依赖版本基线偏旧 | API/Worker 升级、双锁、审计、干净环境和回归已完成；旧 Starlette 的 9 条审计命中已消除，但 Docker daemon 不可达，尚无镜像内 `pip check` 实证 | 修复+外部验收 | 升级到兼容的受支持版本；锁定传递依赖；镜像内 `pip check` 和安全扫描通过；文件/请求回归通过 | BLOCKED_EXTERNAL |
| OPS-004 | 监控告警主要是 readback，不是真实生产观测 | 实际 JSONL/结构化 stderr、Prometheus 指标、trace/error 事件和独立 webhook dispatcher 已接入并完成本地受控实发；客户真实 paging/webhook 目的地和容器内运行证据仍缺失 | 修复+外部验收 | 至少接入日志、指标、错误追踪和告警目的地；覆盖抓取、队列、解析、DB、交付；完成一次受控告警演练 | BLOCKED_EXTERNAL |
| OPS-005 | 备份、恢复、回滚主要停在 dry-run/readiness | PostgreSQL 18 dump、对象 hash archive、隔离 restore、RPO/RTO report 和 previous-image 健康回滚路径已实现并通过本地受控代码演练；真实容器备份/恢复/回滚仍受 Docker daemon 与外部存储/调度阻断 | 修复+外部验收 | 私有试点数据库和对象存储有备份；完成隔离环境恢复；记录 RPO/RTO；发布具备上一版本回滚路径 | BLOCKED_EXTERNAL |
| PROD-002 | 缺少可量化的产品价值验收 | 已建立 clean-batch 固定分母和可回放价值报告；现有 live30 实测发现入组率 30/88、Stage4 ready 1/30、可复核 1/30，证据包、人工分钟、最终采用/退款因没有真实试点观测被明确扣留 | 修复+真实试点验收 | clean batch 固定分母；至少记录发现率、Stage4 ready率、可复核率、证据包率、人工分钟数、最终采用/退款原因 | BLOCKED_EXTERNAL |
| PROD-003 | 客户可见边界和法律免责声明尚未产品化 | 已建立单一边界合同并覆盖门户读回、内部预览 JSON、manifest、HTML、PDF 和 ZIP README；自动邮件误导文案与正式包内部字段泄露已修复 | 修复 | 所有交付面统一说明公开来源、查询时点、非完整性、非法律结论、人工复核和客户责任；黑箱字段不外泄 | VALIDATED |

## 5. P2：真正的智能体与企业产品能力

| ID | 问题 | 当前证据/影响 | 默认决策 | 关闭标准 | 状态 |
|---|---|---|---|---|---|
| AGENT-001 | 当前没有真实大模型调用 | 已实现默认关闭的 OpenAI Responses-compatible provider 与显式内部影子 canary；本地真实 HTTP 协议、重试和治理回归通过，但未提供真实 provider 凭据、受控出口批准或真实 canary 证据 | 修复+外部验收 | 接入一个可替换模型 provider；模型只做候选提取、摘要、解释和文案；事实、证据门、审批门仍由确定性代码决定 | BLOCKED_EXTERNAL |
| AGENT-002 | 没有面向用户的对话式任务入口 | 已增加内部自然语言入口，可显式确认创建幂等 Stage1 预览任务、查进度/证据/下一步；回答回链正式对象，模型关闭仍可用，未命中不写成无风险 | 修复 | 用户可用自然语言创建受限任务、追问证据和查看下一步；每个回答可回链到正式对象和来源；不能执行未授权 live 动作 | VALIDATED |
| AGENT-003 | 缺少模型工具调用与计划执行协议 | 已建立独立严格工具注册表和两阶段 planner：仅确定性只读工具可执行，call_id/输入/输出/权限/预算持久审计；内部写任务停在人工作业交接，外部/live 工具不登记且失败关闭 | 修复 | 建立严格工具注册表、参数 Schema、权限和预算；模型只能调用允许工具；每步有输入/输出/审计；高风险动作必须暂停等人工 | VALIDATED |
| AGENT-004 | 缺少用户/项目记忆和上下文治理 | 已建立私有部署租户作用域下的 principal 偏好与项目工作上下文；支持查看、带版本纠正、删除/过期清值、hash 审计和安全模型投影，且不进入事实/证据/citation/gate | 修复 | 记忆按租户/项目隔离；可查看、纠正、删除；敏感数据不进入模型；过期策略明确；模型不能把记忆当事实证据 | VALIDATED |
| AGENT-005 | 缺少模型质量、成本和降级验收 | 代码侧已建立 10 例离线协议金标、12 例真实质量金标、失败分类、无模型内容降级、token/延迟/费用扣留与版本回归门；离线 10/10 通过，但真实 provider 结果、人工标注、核准价格和 baseline 均为 0 | 修复+外部验收 | 建立 golden cases；记录模型版本、prompt、token、延迟、费用和失败；超时可降级到确定性链；模型输出永远是候选/草稿 | BLOCKED_EXTERNAL |
| PROD-004 | 缺少正式客户账号与企业空间 | 当前是单 owner/operator 视角 | 后置到私有试点后 | 企业、用户、项目、角色、邀请、停用和审计闭环；没有 tenant_id 的对象不得进入 SaaS | DEFERRED |
| PROD-005 | 缺少产品配置和客户 onboarding | 已提供 owner/admin 私有单租户配置向导；只允许登记地区/来源、固定行业/证据模板和有界预算，具备不可变版本、离线试跑前置、显式激活与新版本回滚 | 修复 | 提供受限配置向导；默认安全模板；配置有版本、校验、回滚和测试运行；客户不能绕过来源/审批边界 | VALIDATED |
| PROD-006 | 缺少授权、套餐、用量与许可证 | 无法限制客户能运行什么、运行多少、可看哪些产物 | 后置 | 私有版先使用合同+部署配置；SaaS 前实现 entitlement、配额、用量和停用，不把支付成功直接等同于全部权限 | DEFERRED |
| PROD-007 | 缺少运营后台和客户支持工具 | 已新增 owner/admin 运营支持工作台，统一查询当前私有租户的任务、阻断、队列审计和版本；失败/死信任务可在并发锁与二次确认下重试，原始 payload/错误与事实层不可编辑 | 修复 | 管理员可查任务、租户、阻断、重试、审计和版本；敏感操作有二次确认；不直接编辑事实层 | VALIDATED |
| OPS-006 | 对象存储仍是本地文件系统 | 多实例或远程 worker 不能安全共享产物 | 后置到私有试点扩容 | 单机私有试点可接受本地盘+备份；扩容前接入 S3/MinIO，校验 hash、权限、生命周期和不可执行下载 | DEFERRED |
| OPS-007 | 外部队列/多副本 worker 未启用 | 当前使用 storage queue，Redis/Dramatiq 仅登记未连接 | 后置到负载证明后 | 单节点稳定性先达标；需要横向扩容时再接外部队列；迁移必须保持租约、重试、死信和审计语义 | DEFERRED |

## 6. P3：外部执行、SaaS 与扩张能力

| ID | 问题 | 默认决策 | 当前最小替代方案 | 正式开放标准 | 状态 |
|---|---|---|---|---|---|
| EXT-001 | 真实邮件/企业微信/短信/电话触达未接入 | 后置 | 人工复制经审核话术并留痕 | provider sandbox、模板、频控、quiet hours、退订、审批、审计、熔断、live pilot | DEFERRED |
| EXT-002 | CRM 和报价系统未真实同步 | 后置 | 导出 CSV/PDF，人工录入 CRM | 双向幂等、字段映射、冲突处理、审批、失败重放和客户授权 | DEFERRED |
| EXT-003 | 在线支付、扣款和回调未接入 | 砍掉当前 MVP | 对公转账或人工收款，人工登记 payment record | 商户资质、签名回调、幂等、对账、退款、风控、审计和 live pilot | CUT |
| EXT-004 | 真实客户自助下载未开放 | 后置 | 人工签发带水印文件，通过受控渠道交付 | 客户身份、订单 entitlement、一次性/限时授权、下载审计、撤销和对象级权限 | DEFERRED |
| EXT-005 | 自动退款不适合当前产品 | 砍掉当前及近期版本 | 人工审核和人工退款，系统只记录异常与状态 | 即使未来实现，也必须审批、对账、operator action、暂停/回滚和受控试点 | CUT |
| EXT-006 | 全国所有省市来源适配成本不可控 | 砍掉“全覆盖”承诺 | 按客户和成交机会增加来源；显示覆盖矩阵 | 每个新增地区有来源登记、真实样本、错误预算、维护责任和退出标准 | CUT |
| SAAS-001 | 多租户公网 SaaS 体系尚不存在 | 后置 | 一客户一部署/一环境 | tenant 隔离、SSO/RBAC、密钥、配额、账单、数据删除、审计、HA、安全测试和合规评审 | DEFERRED |

## 7. 客观无法实现或不应实现的边界

| 边界 | 为什么不能直接实现 | 变通方案 | 产品决策 |
|---|---|---|---|
| 全国公开数据 100% 完整实时 | 来源分散、更新延迟、反爬、登录、页面变更和历史缺失不受本系统控制 | 对外展示来源覆盖、最后成功时间、查询窗口和阻断状态 | 砍掉绝对完整承诺 |
| 绕过登录/SSO/验证码 | 涉及授权、网站规则、账号风险和技术对抗 | 只使用公开接口或客户合法授权会话；否则停在 BLOCKED | 砍掉未授权绕过 |
| 自动法律定性 | 公开证据可能不完整，法律判断依赖规则、时点和专业责任 | 输出事实、证据等级、冲突和建议复核；必要时交律师/专家 | 永久人工复核 |
| `NOT_FOUND` 等于无风险 | 查询未命中可能来自覆盖不足、名称差异、源阻断或数据延迟 | 输出查询范围、来源、时间、阻断和下一步 | 永不作为 clearance |
| 100% 无人值守 | 来源授权、同名歧义、证据冲突和客户动作天然存在人工节点 | 让系统自动推进低风险步骤，在明确 gate 暂停 | 保留 human-in-the-loop |
| 自动访问受限个人数据 | 可能缺乏合法公开或授权依据 | 只处理必要的公开/授权字段，默认脱敏，保留来源和目的 | 砍掉无依据采集 |

## 8. 建议攻克顺序

### Wave 0：冻结可信基线

1. `REL-001` 发布基线和 Git 可追踪性。
2. 记录当前定向测试、全量测试、Compose 和镜像证据。
3. 确认第一版产品只做单租户私有/托管证据包。

### Wave 1：先让产品安全地“能被使用”

1. `SEC-001` 浏览器认证。
2. `SEC-002` DOM XSS 与 CSP。
3. `SEC-003` 身份、角色、审批分离。
4. `API-001` 严格写接口契约。
5. `OPS-001`、`OPS-002`、`OPS-003` 私有试点部署与 PostgreSQL 迁移。

### Wave 2：先让证据包“值得收费”

1. `EVD-001`、`EVD-002`、`EVD-003` Stage4/GDCIC/P13B。
2. `DATA-001`、`DATA-002` 解析和附件长尾。
3. `RULE-001` 真实金标校准。
4. `PROD-001` 固定证据包 SKU。
5. `PROD-002` 建立 clean batch 商业指标。

### Wave 3：把工作流变成真正智能体

1. `RUN-001`、`RUN-002`、`RUN-003` 后台运行闭环。
2. `AGENT-001` 真实模型 provider。
3. `AGENT-002` 对话入口。
4. `AGENT-003` 受限工具调用。
5. `AGENT-004`、`AGENT-005` 记忆与模型评估。

### Wave 4：企业私有版产品化

1. 客户配置、运营后台、监控、备份恢复。
2. 完成一个固定范围、固定来源、固定客户的受控试点。
3. 用真实人工耗时、证据包采用率和客户反馈决定保留/砍掉能力。

### Wave 5：只按真实收入需求打开外部能力

1. 先人工触达、人工收款、人工交付。
2. 有稳定需求后再接 CRM、邮件、支付和客户下载。
3. 多租户 SaaS、全国覆盖和自动退款不作为当前成功条件。

## 9. 每类问题的验收方式

| 问题类型 | 最低验收 |
|---|---|
| API/安全 | 单元测试 + 网络客户端认证/越权测试 + 真实浏览器 E2E + 响应头检查 |
| 前端 | 恶意字符串/XSS 回归 + Playwright 主流程 + 401/403/超时/空状态 |
| 数据源 | clean batch、固定分母、真实 snapshot、失败分类、来源时点，不使用 projection 冒充转化率 |
| 解析/规则 | 金标 precision/recall、误报/漏报样本、低置信度 REVIEW、历史回归不退化 |
| 队列/worker | 并发 claim、进程中断、租约过期、重试、暂停、死信、重启续跑 |
| 数据库 | 空库迁移、旧库升级、事务回滚、唯一约束、并发和备份恢复 |
| 模型 | golden cases、模型版本、prompt/输出审计、成本/延迟、超时降级、禁止事实写入 |
| 客户交付 | 字段白名单、脱敏、水印、版本 hash、来源、免责声明、授权和下载/交付审计 |
| 外部执行 | sandbox、审批、审计、幂等、对账、熔断、暂停、回滚、受控 live pilot |

## 10. 阶段性完成标准

### 可内部稳定使用

- P0 安全问题全部关闭或有正式接受的单租户变通。
- PostgreSQL 与后台 worker 可重复部署。
- 固定来源 clean batch 可稳定生成内部证据包。

### 可做收费私有试点

- `P0` 没有 `OPEN/IN_PROGRESS`。
- Stage4、Stage5 和证据包 SKU 达到约定指标。
- 客户边界、免责声明、人工签发和交付审计完成。
- 完成备份恢复、告警和回滚演练。

### 可称为企业智能体产品

- 真实模型、对话入口、受限工具调用、运行记忆和审计完成。
- 模型不决定事实、不绕过证据门和审批门。
- 用户无需阅读 raw JSON 或依赖 Codex 手工选择下一步。

### 可考虑公网 SaaS

- 多租户、对象级授权、配额、运维、合规和 HA 完成。
- 至少一个私有试点证明产品价值和维护成本可接受。
- SaaS 是收入驱动的下一步，不是当前项目“完成”的前置条件。

## 11. 直接依据

- `START_HERE.md`
- `DEV_MODE.md`
- `MINIMAL_PRODUCT_PATH.md`
- `CURRENT_PRODUCT_STATE.md`
- `docs/专题_Stage1-9_缺口收口与优先级清单.md`
- `control/stage1_6_priority_execution_plan.yaml`
- `control/product_operability_gap_matrix.yaml`
- `control/product_runtime_architecture_map.yaml`
- `control/operator_user_acceptance_gap_matrix.json`
- `src/api/main.py`
- `src/api/routes/operator_frontend.py`
- `src/shared/model_assist_governance.py`
- `src/runtime/controlled_gray_public_orchestrator.py`
- `Dockerfile`
- `docker-compose.yml`

## 12. 关闭记录

### REL-001：发布基线和 Git 可追踪性

- 关闭日期：`2026-07-19`
- 内部基线版本：`internal-baseline-2026.07.19.1`
- 状态：`VALIDATED`
- 变更范围：内部 API 鉴权与请求边界、Stage9 HTTP 持久化、队列原子转换和审计唯一性、JSON 多进程锁、公网抓取边界、受控文件路径、部署依赖、容器、CI、迁移、文档及回归测试。
- 静态闸门：`git diff --check`、Python `compileall`、`docker compose config --quiet`、常见私钥/API Token 模式扫描全部通过。
- 契约闸门：`scripts/validate-contracts.ps1` 与 `scripts/check-state-alignment.ps1` 全部通过。
- 定向回归：`221 passed, 6 skipped`，另有 `43 subtests passed`。
- 完整回归：在仓库声明的 `PyMuPDF==1.26.7` 依赖可用时，`1941 tests` 全部通过，`9 skipped`。
- 容器闸门：镜像构建成功；`/healthz=200`；未鉴权 `/openapi.json=401`；正确 Bearer Token 后为 `200`；容器以非 root 用户 `kaka` 运行；容器内 `pip check` 无冲突。
- 回滚方式：以包含本记录的 Git 提交和同名本地 tag 为基线；需要回看时使用 `git show internal-baseline-2026.07.19.1`，不执行破坏性重置。
- 发布说明：这是“可重复构建、可测试、可回滚”的内部基线，不代表公网、客户交付或生产 live readiness。`SEC-001`、`SEC-002`、`SEC-003`、`SEC-004`、`DEP-001` 等后续 P0 仍必须逐项关闭。

### SEC-001：标准浏览器认证链

- 关闭日期：`2026-07-19`
- 状态：`VALIDATED`
- 实现：Bearer 仅用于一次性交换服务端签名的一小时浏览器会话；Cookie 为 `HttpOnly`、`SameSite=Strict`，非本机部署默认 `Secure=true`；签名校验覆盖版本、签发时间、到期时间和最大 TTL，部署 Token 轮换会使旧会话失效。
- 浏览器边界：页面不把 Bearer 写入 URL、localStorage、sessionStorage、Cookie 或生成 HTML；`sessionStorage` 只保存与会话绑定、不能单独完成认证的 CSRF Token。
- CSRF：同源 `POST/PUT/PATCH/DELETE` 必须携带 `x-kaka-csrf-token`；缺失或错误返回 `403 BROWSER_SESSION_CSRF_REQUIRED`；Bearer API 客户端保持兼容。
- 网络测试：未认证页面 `303` 到同源登录页，JSON API 保持 `401`；Cookie 篡改、过期、Token 轮换、CSRF 缺失/错误和退出后失效测试通过。
- 真实浏览器：Playwright 在 `1440x900` 与 `390x844` 完成登录、15 组异步读回、创建内部任务和退出；控制台零错误，窄屏无横向溢出。
- 回归：API/operator console 定向 `37 passed`，另有 `5 subtests passed`；完整隔离回归 `1943 passed, 9 skipped`。
- 容器：未认证页面 `303`、登录页 `200`、会话后页面 `200`、缺 CSRF `403`、退出 `200`、退出后页面 `303`；Cookie 属性、非 root 用户 `kaka` 和 `pip check` 均通过。
- 剩余边界：当前仍是单租户内部共享凭据的会话交换，不等同于 OIDC、真实用户目录、角色授权或业务审批；这些分别由 `SEC-003`、`SEC-004` 继续处理。

### SEC-002：DOM XSS、CSP 与页面安全头

- 关闭日期：`2026-07-19`
- 状态：`VALIDATED`
- DOM 边界：所有动态结构化 HTML 写入统一经过 `safeHtml()`；其内部只在脱离文档的 `template` 上解析，并以标签、属性和链接协议白名单清洗后通过 `replaceChildren()` 进入页面。契约测试保证除这一审计点外没有直接 `innerHTML` sink。
- 字段转义：项目名、地区、运行日志、商业摘要、买家排序、badge、来源诊断、状态卡和证据包字段统一使用 `safeText()`/`textContent`；badge 样式只允许空值、`warn` 和 `danger`。
- 链接策略：动态公开来源只允许绝对 `http/https`；站内链接必须解析后仍为同源；`javascript:`、协议相对 URL 和反斜杠 host 绕过均被清空；新窗口链接自动收口为 `noopener noreferrer`。
- 浏览器策略：登录页和全部操作台页面使用逐响应 nonce 的 CSP；禁止 `unsafe-inline`、脚本/样式属性、对象和 framing，并部署 `X-Frame-Options=DENY`、`nosniff`、`Referrer-Policy=no-referrer`、`Permissions-Policy`、COOP/CORP 与 `Cache-Control=no-store`。
- 恶意数据回归：服务端恶意商机编号不会形成标签；静态契约锁定唯一审计 sink；真实 Chromium 注入 `img onerror`、`svg onload`、`script`、事件属性、内联样式和危险链接后，XSS 哨兵为 `0`，危险节点/属性为 `0`，CSP 对攻击样式产生预期阻断。
- 真实浏览器：本机与容器内均完成登录、操作台异步加载、攻击注入和退出；正常页面控制台/页面错误为 `0`；`390x844` 下 `scrollWidth=innerWidth=390`。
- 回归：操作台与认证定向回归 `39 passed`，另有 `5 subtests passed`；正式隔离全量回归 `1957 passed, 9 skipped`，另有 `608 subtests passed`。
- 容器：`kaka-sec002-api:local` 构建成功；`/healthz=200`；容器以非 root 用户 `kaka` 运行；`pip check` 无冲突；容器内登录、Cookie、CSP nonce、恶意 DOM/URL、窄屏和退出验证全部通过；一次性验证容器已删除。
- 测试治理：修正 `TST-001` 陈旧断言，README/AGENTS 保持轻量导航，业务策略继续由 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json` 承载。
- 剩余边界：本项只关闭操作台 DOM XSS 与页面防御纵深，不代表公网或多租户可部署；真实身份/角色/审批、租户隔离、Host/TLS/可信代理仍分别由 `SEC-003`、`SEC-004`、`SEC-006` 关闭。

### SEC-003：身份、角色、写操作与逐对象审批分离

- 关闭日期：`2026-07-19`
- 状态：`VALIDATED`
- 身份与角色：支持独立配置的 `owner/operator/reviewer/admin` principal；认证上下文只证明身份和角色，不再投影任何对象已审批。普通 operator 不能做审批决定，reviewer 不能申请、下载或执行内部写操作，admin 也不能自批。
- 写接口策略：现有 `26` 个写 operation 全部进入显式中央权限表，分为内部草稿、作业控制、sandbox 财务记录和 owner 公开来源抓取；未分类的新写路由会在应用启动审计时失败。Stage8/9 仍是 draft/mock/sandbox，真实触达、扣款、交付和退款没有因此开放。
- 对象审批：当前唯一已开放的敏感对象动作是 `opportunity/internal_preview_download`。审批绑定商机对象 Hash、完整证据包/脱敏策略 Hash、申请 principal 和独立复核事件；任一绑定目标变化，旧审批立即失效；不存在对象返回 `404`，并发申请/决定保持唯一。
- 生命周期：批准默认有效 `15` 分钟，可通过 `KAKA_INTERNAL_OBJECT_APPROVAL_TTL_SECONDS` 调整；reviewer/admin 可撤销，过期或撤销后可重新申请。有效期内允许同一申请人重复进行内部预览下载，但每次都生成独立授权审计，不等同于客户一次性下载 entitlement。
- 审计主体：网络写操作一律以认证上下文中的 principal/role 为准，请求体中的 `requested_by`、`requested_by_role` 不能伪造审计身份；离线 direct/mock 调用保留原兼容入口。
- 定向回归：审批并发/过期/撤销、API 网络角色矩阵、门户下载、Stage8/9 治理、仓储边界和灰度编排共 `123 tests` 通过；`git diff --check` 通过。
- 完整回归：通过仓库本地隔离依赖 `PyMuPDF==1.26.7` 运行 `tests/run_tests.py`，`1951 tests` 全部通过，`9 skipped`。
- 真实浏览器：两个隔离 Chromium 会话完成 operator 申请、reviewer 批准、operator 下载 `200`、reviewer 撤销、原下载地址立即 `403`；页面正确显示角色、职责分离、有效期和撤销状态。验收截图位于 `output/playwright/sec003-e2e/revoked-approval.png`。
- 容器：`kaka-sec003-api:local` 构建成功；`/healthz=200` 且审批工作流与 `26` 个写操作策略均 ready；operator 会话角色读回正确，reviewer 写 `/orders` 返回 `403`；容器以非 root 用户 `kaka` 运行，容器内 `pip check` 通过；一次性 smoke 容器已删除。
- 剩余边界：本项只对单租户内部部署建立角色和当前敏感动作的逐对象批准，不提供客户账号、tenant_id、跨租户存储隔离或对象 owner ACL；这些属于 `SEC-004`。生产触达、支付、客户交付、退款和客户自助下载仍关闭，不能据此宣称公网/SaaS/生产 live 可部署。

### API-001：内部写接口严格请求与响应契约

- 关闭日期：`2026-07-19`
- 状态：`VALIDATED`
- 覆盖范围：中央权限表中的 `34` 个内部写 operation 全部绑定显式 Pydantic 请求和响应模型；请求来源包括正式 JSON Schema 创建契约、Stage6-9 TypedDict 契约和操作台/编排/智能体/产品配置/支持专用契约，不再有写路由落入 `extra="allow"` 通用模型。
- 请求边界：全部写请求在顶层执行 `extra="forbid"`，未知 JSON 字段和写接口查询参数返回 `400`；`requested_by`、`requested_by_role` 不属于网络请求契约，审计主体继续只由认证中间件注入。金额、预算和所有 live/external 开关按既有业务语义显式约束，其中受控灰度 `execute=true` 在参数层直接拒绝。
- 响应边界：全部写响应使用顶层严格模型并由 FastAPI 执行运行时校验；Stage7-9 遗漏的 capability/governance/semantic envelope、provider 状态、workbench replay 和持久化字段已补入正式类型。历史嵌套 JSON carrier 暂保留结构化 `dict`，但顶层未知字段会失败，不再静默丢弃响应漂移。
- 启动门禁：应用启动时分别审计请求模型、响应模型、未知字段策略和 actor 字段暴露；任一新增写路由未分类、未绑定严格请求/响应模型或泄露请求方身份字段时拒绝启动。当前 request/response contracts 计数均为 `34`。
- OpenAPI 与运行读回：`/orders` 等正式创建接口和 Stage6-9/操作台写接口均发布实际严格 Schema；跨 Stage7-9 的 `11` 条成功写路径由真实 HTTP 响应校验，未知请求体、伪造身份和未知查询参数回归均返回 `400`。
- 回归：API transport 定向 `30 tests` 通过；真实样本自主搜索 `19 tests` 通过；隔离完整回归 `1953 tests` 全部通过，`9 skipped`。Python `compileall`、Compose 配置、`validate-contracts`、`check-state-alignment` 与 `git diff --check` 全部通过。
- 容器：`kaka-api001-api:local` 构建成功；`/healthz=200` 且 request/response strict count 均为 `26`；OpenAPI 请求/响应 `additionalProperties=false`；未知字段、伪造身份和未知查询参数均为 `400`；容器以非 root 用户 `kaka` 运行，容器内 `pip check` 通过；一次性 smoke 容器已删除。
- 剩余边界：本项规范的是单租户内部写传输，不新增客户公开 API，也不代表多租户、私有试点基础设施、公网、客户交付或生产 live readiness；租户/客户数据隔离由 `SEC-004` 继续处理。

### SEC-004：单客户单部署数据隔离变通

- 验收日期：`2026-07-19`
- 状态：`WORKAROUND_ACCEPTED`
- 产品决策：当前 MVP 只允许 `PRIVATE_SINGLE_TENANT`，即一客户一实例、一套 principal 注册表、一份数据库/文件存储、一份对象存储和一个网络命名空间；不在现有无 `tenant_id` 的业务对象上伪造多租户 SaaS。`LOCAL_DEVELOPMENT` 保持原开发行为，不能被当成客户部署配置。
- 启动门禁：私有模式必须显式配置合法 tenant/instance ID、持久化存储路径、对象存储路径、operator artifact root、Secure Cookie 和 principal 注册表；禁止旧 `KAKA_INTERNAL_API_TOKEN` 共享凭据、process-scoped 存储、非命名空间路径和当前不可执行的对象存储后端。任一条件不满足时应用在打开数据写链前拒绝启动。
- 双存储封印：数据库固定记录和对象存储固定文件共同绑定 tenant、instance、data namespace 与 SHA-256；复制、误挂或复用其他客户数据时启动失败。对象存储封印使用原子独占创建，两个客户同时争抢同一空数据域时只允许一个成功。
- 部署隔离配置：新增 `docker-compose.private-single-tenant.yml`，Compose project、命名卷和网络均由 tenant/instance 命名；只绑定宿主 `127.0.0.1`，不开放跨客户路由。配置明确标记 `private_pilot_deployment_ready=false`、`multi_tenant_saas_ready=false` 和 `network_egress_restriction_ready=false`，不冒充 OPS-001/SEC-007 已完成。
- 定向回归：配置失败关闭、双存储隔离、复制数据拒绝、并发首次抢占、封印幂等、私有应用健康读回和 Compose 边界共 `7 tests` 通过；连同 API/Settings 受影响范围共 `43 tests` 通过。
- 双容器验证：customer A/B 使用不同凭据、命名卷和网络同时启动；两边 boundary ready，A Token 访问 A 为 `200`、访问 B 为 `401`；A 创建的订单记录在 A 存在、在 B 不存在；两容器均以 `kaka` 运行。测试容器、网络和卷已删除。
- 最终容器：`kaka-sec004-private-single-tenant:local` 构建成功；正确 Token `200`、外来 Token `401`、数据库/对象存储封印 ready、非 root、`pip check` 通过；容器重启后封印恢复并保持 ready；一次性容器、网络和卷已删除。
- 完整验收：隔离全仓回归 `1960 tests` 全部通过，`9 skipped`；Python `compileall`、本地/私有 Compose 渲染、`validate-contracts`、`check-state-alignment` 与 `git diff --check` 全部通过。
- 剩余边界：业务对象仍无 `tenant_id`，因此严禁多个客户共享同一实例、数据库、卷或 principal 注册表；公网 TLS/反代/Host/出口控制、PostgreSQL、迁移、限流和多租户对象 ACL 分别属于 `OPS-001`、`OPS-002`、`OPS-003`、`SEC-005`/`SEC-006`/`SEC-007` 与 `SAAS-001`。本项不代表收费私有试点、公网、客户自助或生产 live 可部署。

### OPS-001：独立 private-pilot TLS 边缘部署定义

- 验收日期：`2026-07-19`
- 状态：`VALIDATED`
- 配置分层：原 `docker-compose.yml` 和开发行为保持不变；新增独立 `docker-compose.private-pilot.yml` 与 `deploy/private-pilot/` 运维说明，明确其只是单客户私有试点 edge definition，不是公网、多租户、收费交付或 production live 配置。
- 网络与 TLS：API 不发布宿主端口，只允许同一客户专属 Docker 网络中的 Caddy 访问；Caddy `2.11.4-alpine` 仅绑定宿主 `127.0.0.1:18443`，使用内部 CA、严格 SNI/Host、HSTS、nosniff、frame 和 referrer 响应头，关闭管理 API，根文件系统只读并启用 `no-new-privileges`。
- Host 与代理边界：应用启用 `TrustedHostMiddleware`；私有 edge 启动时必须显式配置 hostname、非通配 Host allowlist 和 `PRIVATE_EDGE_NETWORK_ONLY`。正确 Host 经 TLS 返回 `200`，伪造 Host 返回 `421`；伪造 `X-Forwarded-For: 203.0.113.9` 时应用日志仍看到 Caddy 网络地址，不采信外部伪造地址。Uvicorn 的 `--forwarded-allow-ips=*` 只在 API 无宿主端口且专属网络仅含 app/edge 的边界内成立。
- 密钥注入：principal 注册表改由 `KAKA_INTERNAL_API_PRINCIPALS_FILE` 读取并限制 `64 KiB`；私有 edge 禁止环境 JSON 和 secret file 同时配置，也禁止只用环境 JSON。Compose secret 以只读文件挂载到 `/run/secrets`，容器环境、应用日志和 Caddy 日志均未出现 Token；Caddy 对 Authorization 和 Set-Cookie 自动脱敏。宿主文件权限仍需部署管理员按说明收紧，Compose secret 不冒充外部 secret manager。
- 运行验收：完整 Compose 实际构建并启动，app healthy、edge running；可信内部 CA 请求 `/healthz=200`，边界、secret file、Host 和代理配置均 ready；正确 Bearer 访问 OpenAPI 为 `200`，外来 Bearer 为 `401`；浏览器会话 Cookie 包含 `Secure`、`HttpOnly`、`SameSite=Strict`。应用容器以非 root `kaka` 运行且 `pip check` 无冲突。
- 故障恢复：同时重启 app/edge 后应用恢复 healthy，TLS 根证书 SHA-256 保持不变，存储租户封印重新加载且 `/healthz=200`。测试专用容器、网络、三个命名卷、临时 CA 和 principal 文件均已精确删除。
- 回归与配置闸门：部署隔离、API transport 与 provider 配置共 `46 tests` 通过；隔离环境全仓回归 `1962 tests` 全部通过，`9 skipped`。Python `compileall`、本地/单租户/private-pilot 三份 Compose 渲染、官方 Caddy 配置校验、`validate-contracts`、`check-state-alignment` 与 `git diff --check` 全部通过。
- 剩余边界：本项验收时数据仍是单进程 JSON；当前工作树中的 `OPS-002` 已切换 PostgreSQL，但尚未完成真实容器验收，不能倒推扩大本项结论。数据库迁移、流式 body/速率限制、受控出口、外部观测、备份恢复和正式内网证书/防火墙分别仍由 `OPS-002`/`OPS-003`、`SEC-005`、`SEC-007`、`OPS-004`、`OPS-005` 和部署方基础设施处理。Caddy 官方镜像当前以只保留 `NET_BIND_SERVICE` capability 的 root 进程绑定容器内 `443`；强制全容器 rootless 的客户需另做高端口与卷权限初始化。本项不代表产品已经可以收费或 production live 部署。

### OPS-002 / OPS-003：PostgreSQL 私有试点与迁移部署（代码闭环，真实容器验收外部阻断）

- 开始日期：`2026-07-19`
- 状态：`BLOCKED_EXTERNAL / CODE_AND_STATIC_DEPLOYMENT_VALIDATED`
- 已实现：`docker-compose.private-pilot.yml` 已从 JSON 切换到官方 `postgres:18.4-alpine3.24`，使用每客户独立数据库名和命名卷，数据库不发布宿主端口；app 与 migration job 共享只读数据库密码 secret，连接密码不进入 Compose 环境变量。
- 启动顺序：PostgreSQL healthy 后运行 Alembic `upgrade head`；migration 仅以 `0` 退出时 app 才可启动。应用还会读取 `alembic_version`，只有当前 revision 等于仓库 head `20260717_0002` 才允许打开存储；“表存在但版本落后”也失败关闭。应用继续在非 root、只读根文件系统中运行；业务对象/对象存储仍遵守 `PRIVATE_SINGLE_TENANT` 封印。
- 配置门禁：新增密码文件连接解析，支持特殊字符 URL 编码、4 KiB 上限、单行/UTF-8 校验、host/port/user/database 校验，禁止显式 URL 与 password-file 组件混配；private edge 使用 PostgreSQL 时强制要求 password secret file。URL 和密码不会进入 Settings repr、健康读回或 readiness JSON。
- 存储健壮性：PostgreSQL SQLAlchemy engine 启用 `pool_pre_ping` 和 300 秒连接回收；现有 upsert 使用 PostgreSQL `ON CONFLICT`，队列状态与审计事件保持同一事务，数据库唯一约束由 Alembic 管理。
- 已修 BUG：`20260717_0002` 在 Alembic `--sql` 离线模式下会对空 bind 结果调用 `.first()`；现已在生成的 PostgreSQL SQL 中写入 `DO $$ ... IF EXISTS ... RAISE EXCEPTION` 重复审计检查，离线迁移可生成且仍保持失败关闭。
- 已通过：private-pilot Compose 渲染；密码文件/租户命名空间/密钥不读回及静态部署边界 `10 tests`；PostgreSQL/SQLAlchemy/Alembic 定向测试；API transport 全模块 `30 tests`；storage concurrency 全模块 `42 tests` 通过、`1 skipped`（真实 PostgreSQL）；Python `compileall`、`validate-contracts`、`check-state-alignment` 和 `git diff --check`。
- 未完成证据：真实 PostgreSQL 迁移、读写并发、唯一约束、事务、重启恢复和 TLS 端到端尚未执行。官方 PostgreSQL 镜像与最新 API 镜像均已构建；精确命名的数据库容器对象两次都在 daemon 内创建后卡在未接网/未启动状态，确认未写入数据并按精确 ID/name 删除。专属测试网络、两个测试卷和临时 secret 也已全部删除。只读审计确认此前 `sub2api` 和本项目超时 docker 客户端的父进程均已不存在，故仅终止这些孤儿/查询客户端；没有停止 Docker Desktop，也没有修改、停止或删除另一项目资源。清理客户端后 image/info/network/volume API 可用，但 daemon 的 container list/create 内部锁仍不恢复。代码与静态编排已无继续修补项；只有 Docker Linux daemon 恢复后执行空库安装、旧库升级、失败发布、重启恢复和 TLS 实机演练，才可改为 `VALIDATED`。

### EVD-001：Stage4 公开释放证据链收口（代码闭环，授权与真实来源证据外部阻断）

- 更新日期：`2026-07-19`
- 状态：`BLOCKED_EXTERNAL / CODE_AND_CURRENT_REAL_READBACK_VALIDATED`
- 已修复分母 BUG：scoreboard 现在把 follow-up、alternative、expansion、subqueue、projection 和 merged 输入统一标记为 `FOLLOWUP_PROJECT_ROWS`，`clean_batch_comparable=false`；即使输入没有 review candidate 或显式 `input_mode`，只要存在公开来源 follow-up 证据也不会冒充 clean batch。真实单项目和 9 项目 YGP 回放均已验证该口径。
- 已修复可售率 BUG：旧 `real_public_sellable_pack_rate` 错把 limited review candidate 当成可售包。现在该指标只使用 `stage7_sellable_count`，并拆出 `limited_sellable_review_candidate_rate` 与 `real_public_sellable_or_limited_review_rate`。clean live30 固定分母重放结果为 30 条、Stage2/3 各 30、真实可售率 `0`、有限复核率 `0.0333`，不再把 1 个内部复核候选宣传成可售转化。
- 已修复字段回写：P13B/data.ggzy 的 `bid_show` URL、原公告 URL、记录 ID、readback/record SHA-256、候选公司/人员，以及 YGP 的来源/详情/原公告 URL、节点 ID、项目/业务/站点/公告标识和 hash，均可从 scoreboard 进入 Stage4 follow-up queue、official readback context 和 runtime blocker fallback plan；不会把历史 YGP 指针误当当前项目 GDCIC 编码。
- 已补真实公开回放：海南样本已从 data.ggzy 记录追溯到湖北官方跳转壳，通过既有 browser worker 得到最终官方 URL、页面 snapshot hash 和公司命中，再回灌 original-notice 与 overlap closeout。正式 PowerShell 入口已登记到 automation registry，入口审计 `PASS`，输出继续保持内部、非客户可见、未命中不形成排除结论。
- 当前样本实情：`PROJ-CN-GD-JG2026-11731` 实际是海南三亚机场项目，按归属地走海南 adapter 是正确行为；四类目标当前均为 `NOT_FOUND/D`，只有公司上下文，没有目标人员/期间重叠证据，因此不能进入可售释放。9 项目 YGP 历史回放证明 URL/hash/标识符链路可用，但属于 follow-up projection，不能用于宣称 clean live30 转化率。
- 已通过：scoreboard、Stage4 queue、fallback plan、diagnostic 首轮共 `42 tests`；新增指标语义及其 comparison/diagnostic/attribution 回归 `36 tests`；P13B browser/original-notice、YGP flow 共 `47 tests`；Python `compileall`、automation entrypoint audit 与 `git diff --check` 通过。
- 未完成边界：当前环境没有合法 GDCIC `storage_state` 或 `user_data_dir`，项目经理变更真实授权命中只能保持 `LOGIN_OR_SSO_REQUIRED`，不得伪造登录或用 HTTP/Dynamic/Stealthy 代替。现有 clean live30 仍不可售；补齐证据需要合法授权会话与真实公开来源命中，而不是继续改代码或制造样本。取得授权后按既有入口回放并验收；若长期无法取得，则执行 `EVD-002` 已接受的替代来源/削减承诺方案。本项在此之前不得改为 `VALIDATED`。

### PROD-001：固定 SKU 与人工签发交付协议（已验证）

- 更新日期：`2026-07-19`
- 状态：`VALIDATED`
- 固定产品：新增 `SKU-B / 1.0.0`《单项目公开来源履约风险证据核验包》正式契约，范围固定为一个项目和施工许可、竣工验收、项目经理变更、合同履约四类核验；交付格式固定为 PDF、HTML、JSON manifest 和 ZIP，默认方式是人工签发后的受控交接，不依赖在线支付网关。
- 链路收口：新增独立 `stage4_release_evidence_items` 载体；Stage6 保留真实结构化记录，Stage7 归一化四类目标并写入 LeadPack package manifest，运营门户和 ZIP 优先消费该清单。商业对象证据与 Stage4 核验证据保持分离；没有真实四类记录时不造占位数据，产品包继续阻断签发。
- 签发门禁：仅四类名称齐全不再算完成。每项必须具备核验状态、证据等级、公开来源 URL、查询时点、snapshot SHA-256、阻断原因和下一步；还必须具备上游版本 hash、字段白名单/脱敏、水印、逐对象审批和职责分离。任一缺失均为 `BLOCKED_BEFORE_HUMAN_SIGNOFF`。
- 成品边界：生成 ZIP 不授权客户可见，不开放客户自助下载，不自动发邮件，不触发 Stage8/9，不记录虚假交付。人工签发后仍须另行记录接收方、渠道、时间和签发人；`NOT_FOUND/BLOCKED/NEEDS_BROWSER/LOGIN_OR_SSO_REQUIRED` 始终不是无风险或法律结论。
- 真实样本验收：海南三亚项目四类真实公开来源回放均为 `NOT_FOUND/D`，来源 URL、真实查询时点、readback SHA-256、阻断原因和下一步已进入两页 PDF/HTML/manifest/ZIP；验证包只使用视觉验收审批，因此仍正确缺 `production_object_approval_required`，没有冒充已签发或已交付。最终 ZIP SHA-256 为 `a4013504291117759eee53abc0b7a813a484397e71467dbd33858eb8ca62ecc1`。
- 视觉验收：PDF 已渲染为 PNG 逐页检查；中文字体、页眉页脚、页码、水印、长 URL、hash 和四类证据均无乱码、裁切或重叠；证据项使用不可拆分块，第四类记录不再跨页断开。
- 已通过：固定 SKU `3 tests`、Stage7 runtime closure `29 tests`、操作台门户 `13 tests`、客户访问 `10 tests`、LeadPack candidate `4 tests`、相关 API transport `3 tests`，合计 `62 tests`；Python `compileall`、`validate-contracts`、`check-state-alignment` 和 `git diff --check` 通过。
- 部署说明：宿主 `pip check` 仍报告桌面 Hermes/MCP 与项目既有旧版 httpx/Pydantic/Uvicorn/Starlette 的全局环境冲突；这不是本项新增 ReportLab 依赖造成，但说明正式部署必须使用项目镜像/独立虚拟环境，继续由 `SEC-008` 关闭。Docker daemon 的 container-interface 锁仍使新镜像真实容器验收不可执行，`OPS-002/OPS-003` 因而为 `BLOCKED_EXTERNAL`。
- 关闭口径：本项只确认固定 SKU、正式文件格式和人工签发协议已经可运行；不宣称当前 clean batch 已有可售证据。真实来源命中率与 GDCIC 授权仍由 `EVD-001/EVD-002` 负责，真实客户交付本轮未执行。

### EVD-002：GDCIC 无授权跳过与替代来源策略（已接受变通）

- 更新日期：`2026-07-20`
- 状态：`WORKAROUND_ACCEPTED`
- 决策：GDCIC 登录保护来源暂不作为当前固定范围产品的必需来源。存在用户明确提供的合法 `storage_state` 或 `user_data_dir` 时，才允许只读授权浏览器回放；没有授权输入时直接跳过受保护来源，并继续 data.ggzy、原公告/YGP 指针和项目归属地住建公开来源链。
- 已修边界 BUG：旧实现收到 `enable_live_browser_execution` 后，即使授权预检失败也会先启动浏览器访问受保护页面，再从页面判断登录阻断。现在执行模式为 `LIVE_BROWSER_EXECUTION_SKIPPED_NO_AUTHORIZED_SESSION`，不会创建 Playwright runner，不会访问网络；manifest 分离“请求 live”和“实际允许执行”，并记录网络尝试数及无授权跳过数。
- 真实任务验收：使用广州 live30 字段查询产物回放 60 个 GDCIC 任务（合同履约 30、项目经理变更 30），结果为网络尝试 `0`、无授权跳过 `60`、`LOGIN_OR_SSO_REQUIRED_BLOCKED=60`、替代公开来源路线 `60`。输出位于 `tmp/evaluation-real-samples/gdcic-noauth-skip-validation-v3/`；不含客户外发、法律结论或“未命中等于无风险”表述。
- 授权实情：当前进程没有配置 GDCIC 授权环境变量。仓库内历史会话路径虽仍存在，但既有回放分别停在 `NO_BROWSER_READBACK_RECORDS`、`PARTIAL_OR_BLOCKED_REVIEW_REQUIRED` 或 `LOGIN_OR_SSO_REQUIRED`，真实 ready/matched 均为 `0`；本轮没有擅自复用旧 Chrome profile，也没有尝试绕过登录、SSO 或验证码。
- 已通过：GDCIC browser authorized readback `9 tests`；广东字段查询、runtime blocker dispatch 和 Stage6 review cycle 联合 `105 tests`；Python `compileall` 通过。
- 保留条件：未来只有在用户提供合法授权会话后，取得至少一个真实 `BROWSER_AUTHORIZED_READBACK_READY` 命中并完成来源、时间、字段、hash、脱敏和人工复核回放，才重新评估 GDCIC 是否进入长期核心来源。当前不把该外部授权缺口记为代码阻断，也不声称 GDCIC 已验证可用。

### EVD-003：P13B → 字段查询 → Stage5 → Stage6 回放与责任路由（已验证）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED`
- 已修回灌缺口：release-evidence 字段查询对每个终态项目自动生成 `stage5-calibration-sample-table.json`，主 manifest 同时内嵌样本。Stage6 loop/cycle 收到字段查询 JSON 后会自动发现同目录样本，旧产物只有内嵌记录时也可直接读取，不再要求操作者记住第二条输入路径。
- Stage5 如实状态：字段查询终态只构成校准输入，不伪造 Stage5 已运行。样本明确记录 `STAGE5_GATE_NOT_RUN_FIELD_QUERY_OUTCOME_READY`、空 rule/evidence gate、`calibration_truth_label_required=true`、证据强度、来源 hash、阻断原因和建议动作；Stage6 保留原字段查询终态与下一步，不再被校准样本覆盖。
- 责任层修正：`LIVE_FIELD_QUERY_NEEDS_REGION_ADAPTER` 现在归类为 `BLOCKED`，Stage5 指向 `source_adapter + operator_truth_label_review`，Stage6 指向 `fallback_source/operator_action/retry`；GDCIC 登录或同会话缺口仍指向 `browser_worker + operator_action`。地区适配器缺口不再误投浏览器重试。
- 真实项目回放：项目 `PROJ-CN-GD-JG2026-11731` 可从 P13B 重叠信号产物回放到海南四类字段任务，再到 1 条 Stage5 校准样本和 Stage6 `RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY`。当前实际结果为 `BLOCKED=4`、`D_INSUFFICIENT_OR_BLOCKED_READBACK=4`、Stage5 gate 未运行、下一步 `build_fallback_source_adapter_plan_then_rerun_stage6_cycle`。字段查询与 Stage5 产物位于 `tmp/evaluation-real-samples/live-ops-smoke-current/active-batch-release-evidence-field-query-live-v2/`，Stage6 产物位于 `tmp/evaluation-real-samples/live-ops-smoke-current/active-batch-stage6-review-cycle-evd003-v1/`。
- 已通过：字段结果映射、字段查询、Stage6 loop/cycle 和 operator projection 联合 `140 tests`；另补 browser/operator 与 region-adapter/operator 两类责任路由断言，Python `compileall` 通过。
- 关闭口径：本项验证的是跨阶段状态可追踪和失败自动分流，不代表海南来源 adapter 已实现、不代表 Stage5 已取得人工真值，也不代表项目已有可售证据。海南 adapter 实现与真实 B/C 证据命中继续进入后续来源能力项；客户可见、支付、交付和退款均未启用。

### DATA-001：Stage3 关键身份与复杂候选表格金标回归（已验证）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED`
- 已修跨入口 BUG：真实批次 `PROJ-CN-GD-JG2026-11279` 的上游字段曾把“达到”写成 `project_manager_name`，Stage16 兼容桥随后原样生成负责人补证任务。现在 Stage2 详情抽取、Stage3 通用解析、真实压力桥和 Stage16 补证桥共用关键身份质量门禁；非姓名值不再下传，原始字段只进入 REVIEW/错误证据。
- 低置信度边界：关键身份置信度低于 `0.75` 时必须 `review_required=true`。PDF 内嵌文本当前基础置信度为 `0.74`，负责人字段仍可保留为候选，但 carrier 改为 `PARSED_WITH_REVIEW`；OCR 文本仍保持 fail-closed REVIEW，不以解析成功冒充身份已核实。
- 金标与指标：`contracts/evaluation/stage3_responsible_person_golden_set.json` 固化 5 例回放样本，覆盖广州三候选设计表、两组联合体、多候选无证书、真实 active-batch 假姓名和受控 OCR 文本。`stage3_responsible_person_gold_evaluation.py` 对候选企业、负责人、证书号、候选行绑定、联合体成员分别计算 TP/FP/FN、precision/recall，零分母不会虚报为 100%，失败样本自动写入 `regression-error-samples.json`。
- 本轮报告：`tmp/evaluation-real-samples/stage3-responsible-person-golden-evaluation-v1/` 中 5 个字段 precision/recall 均为 `1.0/1.0`，错误样本 `0`；该数值只代表当前小型仓库金标，不代表跨地区或任意 OCR 的普遍准确率。真实 Stage16 回放位于 `tmp/evaluation-real-samples/stage16-company-first-data001-replay-v1/`，`JG2026-11279` 被质量门禁拒绝，补证 job 和 Stage4 input 均为 `0`。
- 已通过：Stage2、Stage3、负责人表格、Stage16、压力桥、公司优先补证和金标评估联合 `110 tests`。
- 关闭口径：工程关闭标准已满足，但标签状态明确为 `INTERNAL_CURATED_REPLAYABLE_GOLDEN_PENDING_EXTERNAL_SECOND_REVIEW`。当前不把 5 例小样本宣传成外部 benchmark，不承诺全国来源、任意复杂表格或 OCR 识别率；扩大地区/附件支持集进入 `DATA-002`，来源覆盖与新鲜度进入 `DATA-003`。

### DATA-002：Stage2 内容支持集与长尾终止边界（已验证）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED`
- 支持集已固化：入口响应上限 `8 MiB`、详情 `16 MiB`、附件 `64 MiB`；附件支持 PDF、DOC/DOCX、XLS/XLSX、ZIP、RAR，以及明确作为附件的 HTML。当前登记入口 profile `23` 个、固定附件 profile `2` 个；同站附件只允许从已登记父入口和可验证下载信号派生。登记只表示允许有限尝试，不表示来源当前必然可达、字段必然可解析。
- 终态契约已统一：入口、详情和附件均输出 `READY / REVIEW / RETRYABLE / BLOCKED / UNSUPPORTED`。只有可回放 snapshot 为 `READY` 并允许下游使用；瞬时传输失败才进入有限重试；SPA/动态壳、登录/验证码/会话挑战明确 `BLOCKED`；超大响应和不支持内容明确 `UNSUPPORTED`，不会继续升级浏览器。
- 已修 4 个边界 BUG：附件网络异常分支对 dict 调用 `append` 会崩溃；后续字典合并会覆盖 `TIMEOUT/FETCH_FAILED` 分类；`.pdf` 文件名可覆盖实际 `image/png` MIME；已启用 resolver 时纯不支持类型也可能被误投浏览器。现在均有回归保护。
- 浏览器硬预算：默认不启用；每次同一附件抓取最多升级 `1` 次；OCR 最多 `3` 次、滑块最多 `3` 次、广州详情浏览器 route 最多 `12` 次、代理池最多 `4` 个、浏览器下载最大 `64 MiB`。运行时环境变量不能突破这些上限；不提供未授权绕过登录、SSO 或验证码的能力承诺。
- 离线验收：`tmp/evaluation-real-samples/stage2-capture-support-audit-v1/` 的受控矩阵 `12/12` 通过，覆盖 `READY/REVIEW/RETRYABLE/BLOCKED/UNSUPPORTED`、SPA、挑战页、误导文件名、超大响应和网络超时；报告明确 `network_enabled=false`、`browser_launched=false`。Stage2 抓取、候选捕获、来源适配、广州下载诊断和字段验证联合 `187 tests` 通过，Python `compileall` 通过。
- 关闭口径：本项关闭的是“支持什么、何时停止、是否重试或升级”的工程边界，不代表所有 23 个登记入口当前可用，也不代表脚本下载、超大附件、任意 SPA 或验证码都能自动处理。支持集外保持 `BLOCKED/UNSUPPORTED`；来源覆盖率和最后成功时间进入 `DATA-003`。

### DATA-003：真实来源覆盖率、新鲜度与无匹配解释（已验证）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED`
- 新增逐来源离线报告 `real_public_source_coverage_freshness.py`：以已执行的真实 batch manifest 和 snapshot 台账为输入，对全部 `23` 个登记入口记录观察窗口、最后列表/详情/附件成功时间、列表查询桶、发现候选、详情覆盖、附件目标桶覆盖、技术阻断率、失败分类和新鲜度。snapshot 有精确 `fetched_at` 时优先使用；没有时才明确标为 run-level 时间代理。
- 解释边界已拆开：未纳入本次输入窗口为 `NOT_OBSERVED_IN_INPUT_WINDOW`；实际查询过但未匹配为 `OBSERVED_NO_MATCH_IN_QUERY_SCOPE`；详情或附件有技术失败为 `PARTIAL_OR_BLOCKED`；dry-run 一律为 `DRY_RUN_NOT_OBSERVED`，不能产生覆盖或对外声明。`NO_MATCH` 永远不等于没有机会，也不能形成 clearance。
- 当前真实报告：输入 `controlled-live-public-batch-20260703-auto-v2` 的 25 个目标查询桶，共观察 `8/23` 个登记来源，`15` 个未观察；历史覆盖状态为详情完整来源 `4`、部分或阻断 `3`、观察窗口无匹配 `1`。发现候选 `38`，详情引用 `32/38`（`84.21%`，去重 snapshot `18`）；需要或出现附件信号的目标桶 `13`，至少一个附件 snapshot 的仅 `2/13`（`15.38%`）；技术阻断 `8/25`（`32%`）；查询无匹配目标桶 `6`。
- 新鲜度实情：当前报告生成时，8 个已观察来源全部超过 `72` 小时，为 `STALE`；15 个未观察来源为 `UNKNOWN`，所以 `external_claim_eligible_source_count=0`。这意味着系统现在可以准确说明历史覆盖和缺口，但不能拿 7 月 3 日的结果宣传 7 月 20 日仍实时可用。
- 对外声明契约：只有 `registered=true`、真实执行、观察时间不超过 `24` 小时且覆盖状态允许的来源，才可描述“该登记来源在该明确窗口内被观察”；`24-72` 小时为 `AGING`，超过 `72` 小时为 `STALE`。禁止声称全网覆盖、来源当前可达、零匹配等于无机会，或缺少附件等于来源没有附件。当前产品仍保持 `customer_visible_allowed=false`。
- 验收产物位于 `tmp/evaluation-real-samples/real-public-source-coverage-freshness-v1/`；来源覆盖/新鲜度、真实样本执行计划与执行、Stage2 来源验证和 DATA-002 联合 `110 tests` 通过，Python `compileall` 通过。
- 关闭口径：本项关闭的是指标、状态解释和对外声明边界，不是把旧数据变新，也不是补齐 15 个未观察来源或 3 个部分阻断来源。周期刷新依赖后续 `RUN-001` 调度；新增来源仍必须登记后才能进入报告和对外窗口。

### RULE-001：Stage5 真实项目金标与规则前后对比（代码闭环，人工真值外部阻断）

- 更新日期：`2026-07-20`
- 状态：`BLOCKED_EXTERNAL / CODE_VALIDATED_TRUTH_LABELS_PENDING`
- 样本盘点：离线扫描 `tmp/evaluation-real-samples`，只接受 `real_sample_execution_mode=EXECUTED`、`execute=true` 且 `execution.executed=true` 的真实执行清单；当前接受 `12` 份，汇总 `246` 条项目观察，按 `project_id`、缺失时按 `source_url` 去重后得到 `116` 个真实项目，超过最低 `50` 个样本门槛。另有 `24` 份 dry-run、非执行或无项目样本清单被显式跳过。
- 金标工作流已固化：`contracts/evaluation/stage5_rule_truth_label_contract.json` 规定 `PASS / REVIEW_REQUIRED / EXCLUDE_NOT_EVALUABLE`、人工 reviewer、标注时间、证据引用、复核说明和第二次外部复核边界；`stage5_real_project_rule_calibration.py` 生成稳定 sample ID、可重复续标 JSON/CSV、错误回归样本和摘要，重复运行会按稳定 sample ID 保留已有人类标签。
- 规则前后对比：baseline 为 `FILE_REVIEW_ONLY_V1`，current 为 `FILE_REVIEW_PLUS_TAILORED_REVIEW_V1`。当前无真值时仍可报告预测分布：baseline `PASS=44 / REVIEW=72`，REVIEW 占比 `62.07%`；current `PASS=18 / REVIEW=98`，REVIEW 占比 `84.48%`；共有 `26` 个项目预测发生变化。该分布只说明规则行为，不说明正确率。
- 真值边界：仓库现有 116 个项目全部为 `PENDING_HUMAN_REVIEW`，有效人工金标为 `0`。因此 TP/TN/FP/FN、precision、recall、误报率和漏报率全部保持 `null / WITHHELD_NO_VALID_HUMAN_TRUTH_LABELS`，不会伪报为零，也不会用当前规则输出自我生成真值。规则阈值不会自动修改。
- 验收产物位于 `tmp/evaluation-real-samples/stage5-real-project-rule-calibration-v1/`；新增及既有 Stage5 校准联合 `10 tests` 通过。待至少 50 个去重真实项目完成符合合同的人工标注后，重新运行同一评估器即可生成前后 confusion metrics 与误报/漏报回归集，再由人决定是否调阈值。
- 关闭口径：代码可解决的样本聚合、去重、续标、评估和防自证闭环已完成，但本项不能标为 `VALIDATED`，因为人工真值是外部事实而不是可由模型或规则替代的数据。产品化主线继续推进其他可自动解决项；此项保留为明确的人工作业门。

### RUN-001：独立持久化周期 Worker（已验证，限内部准备任务）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / INTERNAL_PREPARE_ONLY`
- 后台闭环：新增 `runtime.controlled_gray_scheduler_worker` 独立进程和薄启动脚本，复用现有 `controlled_gray_public_orchestrator` 持久队列。支持一次运行或持续轮询、稳定 schedule ID、60 秒至 31 天周期、错过周期跳到下一个未来时点，以及成功或单次死信后续排下一个 occurrence。
- 并发与恢复修正：队列写入从“只比较旧状态”升级为完整旧对象 CAS；租约到期时刻即失效；成功终态会清除 worker、lease、heartbeat 和 expires 字段。租约、心跳、有限重试、暂停/恢复、死信和进程重启后的过期任务回收均有回归测试。
- Web 边界：旧 `/worker/run-once` 兼容路由不再 claim 或执行任务，只返回 `INLINE_WEB_WORKER_EXECUTION_DISABLED` 和独立进程命令；操作台改为检查 Worker。同步 `/prepare` 只生成本地内部规划产物，不发起真实来源长链。
- 可观测性：进程状态原子写入 `tmp/runtime/controlled-gray-scheduler-worker-status-v1.json`；队列读回包含状态计数、租约、最近心跳、过期时间、重试次数、暂停、死信、周期和最近任务。入口已登记到 `control/automation_entrypoint_registry.yaml`，入口审计通过。
- 真实跨进程验收：独立 enqueue 进程写入到期任务，独立 CLI worker 进程 claim 并完成实际 prepare bundle，终态为 `succeeded`，租约字段清空，并生成下一周期任务。证据位于 `tmp/evaluation-real-samples/controlled-gray-scheduler-worker-run001-v1/`；专项、队列并发、入口审计和 API 运输层回归通过。
- 关闭口径：`unattended_recurring_run_ready=true` 必须与 `unattended_recurring_scope=INTERNAL_PREPARE_ONLY`、`unattended_live_execution_ready=false` 一起解释。本项不表示真实公开源抓取、浏览器、客户外发、支付、交付或退款已无人值守；生产服务编排属于 `RUN-003`，长任务通用进度/取消/预算属于 `RUN-002`。

### RUN-002：长任务进度、取消和预算（部署路径闭环）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / DEPLOYED_PATH_ASYNC_CONTROL_VALIDATED`
- 队列协议：现有 `PersistedWorkerQueueItem` 原位增加阶段、消息、完成/总单元、百分比、执行预算、预算起止、取消请求/操作者/原因/完成时间和错误分类；旧 JSON/SQLite/SQLAlchemy payload 缺少新字段时使用兼容默认值，没有新建第二套任务对象。
- Worker 行为：claim 时启动预算；运行中按心跳持久化最新进度；操作者取消通过持久状态通知执行控制器；支持协作式停止并写入 `cancelled` 终态；预算到期失败关闭为 `TIME_BUDGET_EXCEEDED`，不会把超时写成成功。排队、重试或暂停任务可立即取消，运行任务在安全检查点取消。
- 操作台：灰度队列显示阶段、百分比、进度消息、最近心跳、预算截止、重试次数和错误类别，并提供取消按钮。新增取消 API 使用严格请求/响应合同和现有 `internal_job_control` 权限。
- 入口迁移：`runOwnerRealPublicSourceCapture` 和 `runOperatorAutonomousOpportunitySearch` 已登记到 `operator_long_tasks` 队列并要求 `browser` capability；操作台默认只入队，private-edge 网络入口会强制 `async_execution=true`，旧同步行为仅保留在本地直接 Python 回归调用。
- 部署与读回：新增正式 `operator_long_task_browser_worker` 入口、专用状态/取消 API 和 UI 轮询；浏览器 worker 持久化业务结果后，页面从搜索运行记录、候选库、Stage2 快照或真实源运行记录读回，不依赖 HTTP 长连接。
- 已验证：进度落盘、运行中跨线程取消、预算超时、core/browser 能力隔离、搜索/采集异步入队、浏览器 job 执行、排队任务取消、既有租约/重试/暂停/死信/周期回归、28 个内部写契约和入口审计通过。
- 最终回归证据：后端相关组 `41 passed + 28 subtests`，前端门户组 `13 passed`；操作台内联 JavaScript `node --check`、两份控制 YAML 解析、`docker compose config --quiet` 和 `git diff --check` 均通过。
- 边界：取消为阶段检查点式协作取消；已进入阻塞系统调用的 Python 线程不能安全强杀，只能等待底层网络超时后终止并落盘。客户触达、发布、支付、交付和退款始终关闭。

### RUN-003：API / Worker / Browser Worker 能力分层（代码闭环，运行验收外部阻断）

- 更新日期：`2026-07-20`
- 状态：`BLOCKED_EXTERNAL / STATIC_COMPOSE_AND_JOB_ROUTING_VALIDATED`
- 镜像分层：Dockerfile 提供 `api`、`worker`、`browser-worker` target；API 只按 `requirements-api.lock.txt` 安装，core worker 按 `requirements.lock.txt` 安装完整文档/解析依赖，browser worker 在此基础上安装 Chromium；两类 Python 安装均强制 `--require-hashes`。默认构建仍落到 API target，不把浏览器塞回 Web 容器。
- 私有试点编排：private-pilot Compose 增加独立 core worker 和 browser worker，三者共享同一客户 PostgreSQL 队列和私有数据卷，不共享进程，也不对 worker 发布宿主端口；均在 migration 成功后启动并输出独立状态文件。
- 能力路由：受控灰度 prepare payload 使用 `required_worker_capability=core`；自主机会搜索和白名单真实源采集使用 `required_worker_capability=browser`。Worker 领取前精确过滤，core/browser 互不误领；API 镜像不安装或启动浏览器 worker。
- 已验证：Dockerfile/Compose 静态契约、core/browser 能力隔离、浏览器 job 执行、正式入口审计、Python 编译和 `docker compose ... config --quiet` 通过；完整依赖环境可导入 Playwright `1.61.0`。
- 剩余缺口：当前 Docker Desktop daemon 被内部 container-interface 锁占用，不能在不影响无关容器的情况下重启，所以三个镜像的真实 build/up/health 尚未执行；该外部运行证据与 `OPS-002/OPS-003` 同阻断。除这项实机证据外，代码和静态编排侧已闭环。

### SEC-005：请求体、昂贵请求速率与并发门禁（已验证，单 API 私有试点）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / SINGLE_API_PRIVATE_PILOT`
- 双层请求体门禁：private-pilot 的 Caddy `2.11.4` 在反向代理读取前限制 `2MB`；应用对 `POST/PUT/PATCH/DELETE` 始终迭代实际 ASGI body stream，在 JSON 解析前累计字节并限制为 `2097152`，不再只信任 `Content-Length`。已缓存的有界 body 会继续交给 FastAPI 正常解析，不破坏下游请求合同。
- 昂贵操作门禁：Stage1-6 编排、自主机会搜索、公开源采集、受控灰度准备/入队统一按 `tenant_id + principal_id` 执行每分钟 `20` 次、同时 `2` 个请求的门禁。并发拒绝不消耗速率配额；超限返回 `429`、`Retry-After`、`no-store`，已接受响应返回限额/剩余读回。
- 边缘实测：使用与正式配置相同的 Caddy `2.11.4` 二进制验证项目 Caddyfile为 `Valid configuration`；本地反向代理读取探针中，小请求返回 `200`，超过 `1KB` 的请求返回 `413`。应用集成测试还使用没有 `Content-Length` 的流式请求证明实际字节上限不能绕过。
- 决策边界：标准 Caddy 负责边缘 body 上限；需要认证身份的速率/并发门禁放在应用层，避免为了单宿主试点引入第三方 Caddy 插件供应链。当前 limiter 是单 API 进程内状态；多 API 副本前必须改为 Redis/网关等共享原子 limiter，不能把本状态冒充集群级限流。

### SEC-006：Host、可信代理与安全响应头（已验证）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / PRIVATE_PILOT_BOUNDARY`
- Host 门禁：private-edge 启动时要求显式 hostname 和非通配 `KAKA_API_ALLOWED_HOSTS`；FastAPI 使用 `TrustedHostMiddleware`，真实 HTTP 测试中 `pilot.localhost` 返回 `200`，`attacker.invalid` 返回 `400`。Caddy 同时启用严格 SNI Host。
- 代理信任修复：已删除 Uvicorn `--forwarded-allow-ips=*`。Compose 把 PostgreSQL/migration/workers 放入 internal backend 网络，只让 app 双网接入、Caddy 单独接入 edge 网络；Caddy 使用可配置固定私网 IP，Uvicorn 只信任该地址。应用配置门禁拒绝缺失代理 IP、通配 `*`、非法/非私网代理 IP；健康读回只公开数量，不泄露实际地址。
- 响应头：Caddy 统一输出 HSTS、nosniff、DENY frame、no-referrer、Permissions-Policy 并删除 Server；登录页和操作台真实响应使用逐响应随机 nonce 的 CSP，包含 `default/base/object/frame-ancestors` fail-closed、禁用 script/style attribute，并且不含 `unsafe-inline` 或 `unsafe-eval`。当前单文件 UI 仍有 inline script/style，但只能由匹配 nonce 执行，不把“大规模前端拆包”伪装成已完成。
- 已验证：私有 Host/secret/启动门禁和 Compose 网络静态测试、登录页与操作台真实响应头测试、Python 编译、项目 Caddyfile `validate` 和 Compose `config --quiet` 均通过。实际三容器 build/up/health 仍属于 RUN-003/OPS-002/OPS-003 的 Docker daemon 外部阻断，不影响本项代码和配置边界的关闭结论。

### SEC-007：SSRF DNS 竞态、出口域名与网络隔离（已验证）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / CODE_RUNTIME_AND_STATIC_DEPLOYMENT`
- 直接 transport：urllib 不再“先解析、后按域名连接”，而是为每次初始/重定向请求重新解析全部地址、拒绝任一非 global 地址，并让 HTTPConnection/HTTPSConnection 的实际 socket 直接连接已验证数值 IP；HTTPS 仍用原始 hostname 做 SNI/证书校验。curl 使用 `--resolve` 固定本轮 IP、禁用环境代理旁路，并限制 operator extra args，禁止覆盖 URL、Host、proxy、resolve、redirect 或 socket。
- 不可绑定 transport：Scrapling HTTP、Dynamic、Stealthy 与仓库 Playwright 启动点在 private-pilot 中必须使用 `KAKA_CONTROLLED_EGRESS_PROXY_URL`；缺少代理会失败关闭。Stage2 浏览器不再在已配置代理时先尝试 direct route。
- 受控出口代理：新增 `runtime.public_egress_proxy`，只允许 18 个正式 Stage2 来源域名和 Compose 显式登记的 13 个广东当前主线域名，不支持通配符或隐式子域；只允许 HTTP 80 / CONNECT 443。代理重新解析全部 DNS 答案，任一 loopback、private、link-local、云元数据或非 global 地址即拒绝，然后直接连接通过验证的数值 IP；HTTP 模式重写为 origin-form、重建 Host 并剥离 Proxy-Authorization/hop-by-hop headers，CONNECT/HTTP 均有并发、请求和响应预算。
- 网络层：PostgreSQL、migration、app、core worker 和 browser worker 只接内部网络，没有默认公网路由；Caddy 单独接 `public-ingress`，egress proxy 单独接 `public-egress`。browser worker 的 urllib/curl/HTTP_PROXY/HTTPS_PROXY/Playwright/Scrapling 均指向该代理，其他业务容器不能绕过代理直接访问元数据或内网目标。
- 回归证据：出口代理协议/allowlist/DNS 混合答案/数值 IP 连接/真实 socket 拒绝/CONNECT tunnel/HTTP Host 重写测试 `9 passed + 3 subtests`；Stage2 URL fetcher 全模块 `79 passed + 3 subtests`；浏览器与广东/GDCIC/P13B 相关联合 `127 passed + 3 subtests`；private-pilot 静态部署测试、Python compileall、proxy `--check-config` 和 Compose `config --quiet` 通过。
- 边界：GDCIC 历史 `210.76.80.152:8008` 继续因原始 IP + 非标准端口失败关闭，并已按 EVD-002 从固定 SKU 必需来源移除。新增地区/来源必须显式登记域名；不能把通配放行当成修复。完整容器 build/up/health 仍受 RUN-003/OPS-002/OPS-003 的 Docker daemon 锁阻断，本项没有虚报该外部证据。

### SEC-008：依赖升级、传递锁与持续审计（代码完成，镜像验收外部阻断）

- 更新日期：`2026-07-20`
- 状态：`BLOCKED_EXTERNAL / CODE_AND_CLEAN_PYTHON_3_12_VALIDATED`
- 版本基线：API/Worker 统一升级到 FastAPI `0.139.2`、Pydantic `2.13.4`、SQLAlchemy `2.0.51`、Alembic `1.18.5`、psycopg `3.3.4`、Uvicorn `0.51.0`、HTTPX `0.28.1`、PyYAML `6.0.3` 和 ReportLab `5.0.0`；Worker 另固定 PyMuPDF `1.28.0`、pypdf `6.14.2`、MarkItDown `0.1.6`、Scrapling `0.4.11` 与 Playwright `1.61.0`。`pypdf` 已从隐藏的 MarkItDown 传递依赖提升为项目直接依赖。
- 可复现安装：新增 `requirements-api.lock.txt` 与 `requirements.lock.txt`，均由 Python 3.12 `pip-compile` 解析完整传递树并记录 SHA-256；Docker API/Worker target 和 CI 都使用 `--require-hashes`。`scripts/validate_dependency_locks.py` 会拒绝非精确直接版本、缺失直接依赖、无哈希条目和自定义 index/trusted-host/URL 来源，防止输入与锁静默漂移。
- 安全结果：旧 API 传递树审计命中 Starlette `0.37.2` 的 9 条已知漏洞记录；升级后 API 锁和最终 Worker 锁分别经 pip-audit 审计，均为 `No known vulnerabilities found`。CI 固定安装 pip-audit `2.10.1` 并分别审计两份锁。
- 干净环境：使用独立 Python `3.12.13` API/Worker 虚拟环境按哈希锁安装；两者 `pip check` 均通过，API 核心依赖与 Worker 浏览器/文档/PDF 直接依赖显式导入通过。升级回归暴露并修复了 urllib HTTPSHandler 的 `_check_hostname` 兼容差异，以及 `pypdf` 不应依赖 extras 偶然带入的问题。
- 回归证据：API 请求体/认证/代理/限流核心 `6 tests` 通过；依赖锁 `3 tests`、部署/存储静态契约 `53 tests`（1 个可选 PostgreSQL 集成跳过）、Stage2-4 文档/公网/核验 `250 tests`、Stage5-9/存储/报告 `338 tests`（1 个真实 PostgreSQL 集成跳过）、灰度 manifest/固定 SKU/操作台 `31 tests` 均通过。全量发现入口曾因本机首次安装/杀毒冷启动超过 30 分钟而被工具超时终止，后续按文件顺序从断点分段覆盖剩余模块；不把该超时写成单次全量命令成功。
- 边界：当前完成的是 Python 依赖、锁、审计和代码兼容闭环；Docker client 可用但 Linux engine pipe 不存在，真实镜像 build 和镜像内 `pip check` 无法执行，因此本项不满足原关闭标准并保持 `BLOCKED_EXTERNAL`，与 RUN-003/OPS-002/OPS-003 共用后续容器验收窗口。FastAPI TestClient 对未来 `httpx2` 迁移会发出测试侧弃用提示，当前运行 HTTPX 客户端不受影响；后续框架升级需在独立任务迁移测试工具，不能忽略 warning 长期累积。

### OPS-004：实际运行观测与告警派发（代码完成，真实目的地外部阻断）

- 更新日期：`2026-07-20`
- 状态：`BLOCKED_EXTERNAL / CODE_AND_CONTROLLED_ALERT_DRILL_VALIDATED`
- 实际事件：新增 `runtime.operational_observability`，把结构化事件同时写入 stderr 和跨进程锁保护的持久 JSONL；单事件限制 32 KiB，敏感键统一脱敏，主 ledger 达到 64 MiB 后保留一代轮转。观测写入失败只输出不含错误正文/凭据的最小诊断，不会反向改变 HTTP、队列、抓取、解析、数据库或交付业务结果。
- 覆盖范围：API 中间件记录安全 request ID、路由模板、状态码和耗时；scheduler worker 记录 started/success/retry/cancel/budget/lease/dead-letter；Stage2 高层入口记录 entry/detail/attachment 实际抓取状态且只保留 host；Stage3 记录 parse state、附件类型、字段数和 review；SQLAlchemy engine hook 记录实际 statement 类型、耗时和连接/执行错误，不记录 SQL/参数/数据库 URL；固定 SKU bundle 与 Stage9 内部 delivery record 分别记录签发阻断或持久化结果，且明确 `external_delivery_executed=false`。
- 指标与错误追踪：认证后的 `/internal/observability` 和 `/internal/observability/metrics` 从实际 ledger 聚合 service/component/operation/outcome 计数、错误分类和最后事件时间；`X-Request-ID`、queue item ID、snapshot ID、opportunity/delivery ID 作为受限 trace ID 串联故障，不把原始 URL、文档内容、SQL、数据库凭据或 webhook secret 写入指标标签。
- 告警派发：新增独立 `runtime.operational_alert_dispatcher`。它只消费 `ERROR/CRITICAL + alert_eligible` 事件，忽略自身事件防递归；使用持久 delivered/dead-letter/attempt state 去重，指数退避、有限重试和 JSONL 死信。Webhook 必须 HTTPS、精确匹配 `KAKA_ALERT_ALLOWED_HOSTS`、经 `egress-proxy` 做公网 DNS/IP 门禁，并用 secret-file HMAC-SHA256 签名；示例 secret 会启动失败关闭。Compose 以显式 `alerting` profile 运行 dispatcher，未提供真实 URL/host/secret 时不会冒充告警已上线。
- 受控演练：本地实际 HTTP 接收器成功收到一次签名错误告警；相同 event ID 二次扫描未重复发送；500/503 路径验证了到期前不重试、到达上限后写死信；dispatcher 自身 error 事件未递归发送。专项观测/派发/API/四链路与冷启动导入测试 `13 passed`；Stage2/3、固定 SKU、SQLAlchemy/存储并发、scheduler、Stage9 surface 与 private-pilot 部署隔离分批回归合计 `175 passed, 1 skipped`，Compose 含 `alerting` profile 的 `config --quiet` 通过。
- 边界：这不是外部 APM/SaaS 已采购，也不是客户 paging 已接通。当前没有可由仓库自行生成的客户 webhook URL、接收端白名单和真实 secret，Docker Linux engine 同样不可达，故无法提供“容器内持续运行 + 客户真实目的地收到告警”的证据，本项保持 `BLOCKED_EXTERNAL`。部署方提供目的地后，只能通过受控告警演练确认接收、去重、升级联系人和轮值响应，再关闭该项；备份恢复仍由 `OPS-005` 独立处理。

### OPS-005：私有试点备份、隔离恢复与发布回滚（代码完成，真实容器演练外部阻断）

- 更新日期：`2026-07-20`
- 状态：`BLOCKED_EXTERNAL / CODE_AND_LOCAL_ISOLATED_DRILL_VALIDATED`
- 真实备份格式：新增仅含 Python 标准库和 PostgreSQL 18 原生工具的 `backup-tools` image target。数据库使用同 major `pg_dump --format=custom --serializable-deferrable --no-owner --no-acl`；本地 object storage 生成 tar.gz 和逐文件 path/size/SHA-256 JSONL inventory。数据库 dump、对象 archive、inventory 均写 size/hash；manifest 再做 canonical SHA-256，先写随机 `.partial` 目录，全部验证后原子改名，相同 backup ID 不覆盖。
- 一致性和凭据：当前数据库/本地文件不具备跨介质事务，备份脚本必须显式 `-PauseWriters`，会记录并停止原先运行的 API/core/browser writer，结束后只恢复原集合；runtime 还要求与 tenant/instance 精确匹配的 `WRITERS_PAUSED:*` acknowledgement。PostgreSQL 密码仅从 secret-file 读取并写入临时 `0600 PGPASSFILE`，拒绝换行注入，不进入 argv、manifest 或 stdout。备份根必须与 object root 分离，符号链接、filesystem root、路径逃逸和运行中对象变化均失败关闭。
- 隔离恢复：`restore-drill` profile 使用独立 `restore-postgres`、独立 DB/object volumes 和无公网 `restore-isolated` 网络，不挂载 active `pilot-data`。restore runtime 要求 target DB 与 source 不同、精确 `RESTORE_ISOLATED:<db>` 确认、全新 object 目录和全新报告名；先验证所有 artifact/hash，再安全逐文件解 tar（拒绝 absolute/`..`/symlink/hardlink/device），执行 `pg_restore --clean --if-exists --exit-on-error` 到隔离 DB，最后核对 Alembic revision、六类核心表计数及全部对象 hash。失败目标只保留在隔离卷供取证，不自动触达 active data。
- RPO/RTO：manifest 记录实际 backup duration、外部 schedule interval、目标 RPO 和“配置周期 + 本次耗时”的 worst-case estimate，并明确仍需观察真实 recurring schedule；成功 restore report 记录实际 isolated restore seconds、RTO target/met、目标 DB/object root 和 `active_*_mutated=false`。本地受控测试实际完成对象归档/恢复和逐文件校验，并以不含 secret 的 fake PostgreSQL tool boundary 验证 dump/restore/psql 命令、schema/count 校验和 RPO/RTO 字段。
- 发布回滚：private-pilot 所有项目服务镜像统一改用 `${KAKA_IMAGE_TAG:-local}`。新增 rollback 脚本要求 current/previous 两个显式 tag、三个运行时 previous image、本 tenant/instance 的完整 backup manifest 和人工确认；使用 `--no-build --wait` 健康门切回上一镜像，失败时自动恢复 current tag。脚本明确不自动 schema downgrade、不把备份覆盖到 active data；旧镜像若不接受当前 schema，会失败关闭并前向恢复。
- 验证证据：backup/restore/tamper/path traversal/secret injection 测试 `2 passed`；private-pilot 静态 backup/restore/rollback 隔离契约 `1 passed`；三个 PowerShell 脚本 AST 解析、Python compile、YAML 和含 `backup`/`restore-drill` profiles 的 Compose `config --quiet` 通过。
- 边界：当前 Docker Linux engine pipe 仍不存在，不能执行真实 PostgreSQL 18 容器 dump、独立 restore-postgres、previous-image health rollback，也没有仓库外备份盘/对象锁/外部 scheduler 可由代码自行提供。因此本项保持 `BLOCKED_EXTERNAL`；关闭前必须在目标私有试点完成一次真实备份、一次隔离恢复并保存 RTO report、至少观察一个调度周期的 RPO、一次 previous-image 回滚/前向恢复演练，并确认备份不与 active volume 同故障域。

### PROD-002：clean batch 产品价值验收（代码与现有基线完成，客户结果观测外部阻断）

- 更新日期：`2026-07-20`
- 状态：`BLOCKED_EXTERNAL / CODE_AND_EXISTING_CLEAN_BATCH_BASELINE_VALIDATED`
- 指标契约：新增 `contracts/evaluation/product_value_acceptance_contract.json` 和 `storage.product_value_acceptance`。只有显式 `clean_batch_comparable=true`、`denominator_kind=REAL_PUBLIC_CANDIDATES`、`projection_or_merge_state=CLEAN_BATCH_OR_DIRECT_STAGE1_6` 且 `candidate_count` 等于唯一项目行数的计分板可进入价值报告；旧计分板、follow-up、alternative、projection、merged 或重复项目全部失败关闭。无候选 clean batch 只允许 `NO_CANDIDATES`，发现率可记为真实 `0`，下游项目指标标记不适用。
- 分母修复：Stage4 `MATCHED` 原字段是任务数，不能除以项目数。新报告按每个项目是否至少存在一个 MATCHED 任务去重；可复核率按唯一项目的 Stage7 allowed 或 limited review candidate 计数。证据包必须携带 `project_id + opportunity_id` 才能归入 cohort，固定 SKU manifest、LeadPack summary、客户产物读回和 ZIP 已补项目标识；缺项目标识的包不会被统计。
- 当前真实基线：用 clean live30 计分板和其原始真实 `run-result.json` 重放，Stage1 扫描 `88` 个列表项，限额前接受 `50/88=56.82%`，因 clean cohort 上限截断 `20` 个，固定 cohort 入组发现率为 `30/88=34.09%`；Stage4 ready 为 `1/30=3.33%`，可复核为 `1/30=3.33%`。报告位于 `tmp/evaluation-real-samples/live-ops-smoke-current/product-value-acceptance-clean-live30-v1/product-value-acceptance-v1.json`，SHA-256 为 `5e6a39364abe435a81cbfc4d05034be983b550ebc2ae016691aa58b317c3cce9`。
- 缺失不冒充零：当前 clean live30 没有完整证据包观测窗、人工复核起止日志、真实客户 outcome 或 payment/refund 记录，因此这四项均为 `WITHHELD_MISSING_INPUT`，整份报告是 `PARTIALLY_OBSERVED / INSUFFICIENT_OBSERVATION`，不是产品价值通过。只有显式标记完成的时间窗才允许真实零值；缺文件、未完成窗口或不匹配 cohort 一律不出数。
- 真实客户门禁：人工分钟只接受同一时间窗内、同一 operator 不重叠的 `HUMAN_REVIEW` 起止日志；最终采用只消费 formal `opportunity_outcome_event` 的 `WON`；退款只消费 formal `payment_record` 的 `REQUESTED/APPROVED/COMPLETED`。outcome/payment 还必须有 `value_observation.real_customer_confirmed=true + confirmation_ref`，且 execution mode 不能包含 preview、dry-run、sandbox、fixture 或 sample，内部链路演示不会被算成成交或退款。
- 验证：价值报告的 clean/缺失扣留/follow-up 拒绝/旧 lineage 拒绝/真实客户门禁/人工时间重叠/零候选/文件回放共 `7 tests` 通过；固定 SKU 包共 `3 tests` 通过；运营门户实际 ZIP 下载回归通过；Python compile 和 JSON contract 解析通过。
- 关闭条件：本项的代码和现有 clean baseline 已完成，但仓库不能制造真实客户行为。关闭前必须在一个明确 pilot 观察窗记录真实证据包生成、人工复核分钟、最终采用或未采用原因，以及若发生退款时的正式原因；达到完整观测后再由产品负责人定义阈值并作接受/砍功能决定。在此之前状态保持 `BLOCKED_EXTERNAL`，不得用 `1/30` 内部复核候选宣称客户价值已验证。

### PROD-003：客户交付与责任边界（已验证）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED`
- 单一口径：新增 `contracts/sales/customer_delivery_boundary_contract.json`，固定公开来源范围、逐项查询时点、来源不完整性、查询状态不等于排除、非法律结论、人工复核签发和客户最终决策责任七类条款。门户读回、内部预览 JSON、正式 manifest、HTML、PDF 和 ZIP README 均从该合同生成，不再各自硬编码不同版本。
- 已修承诺 BUG：操作台原来把未来交付写成“成交付款后由系统通过邮件发送”，但正式 SKU 合同和当前运行能力均没有自动邮件交付。现在统一为“人工签发后通过与客户约定的受控渠道交付”，并显式显示自动邮件和客户自助下载均未开放；相关 UI 验收合同和 Stage9 下一步文案同步修正。
- 字段边界：固定 SKU manifest 不再原样复制审批申请人、复核人、执行 principal、内部字段黑名单或任意上游 `数据真实性边界` 字段。交付包仅保留审批存在、版本一致、职责分离、执行审计是否记录等客户安全结果；字段策略只公开门禁结果和客户字段白名单。递归 forbidden-key 扫描在文件渲染前失败关闭，恶意 `prompt`、内部推理、provider credential 或身份字段不会进入正式包。
- 签发门禁：字段白名单未执行、脱敏未启用或内部黑箱暴露时，新增明确签发缺口并保持 `BLOCKED_BEFORE_HUMAN_SIGNOFF`。包生成仍不授权客户发布，不执行真实外发，也不打开自助下载。
- 页面和可访问性：内部证据包页新增紧邻下载/审批的“交付与责任边界”区，显示合同版本、当前交付方式及完整条款；正式 HTML 增加键盘焦点、窄屏 padding 和横向表格回退，保持无脚本、无外部资源。`PRODUCT.md` 固化可信、克制、证据优先、边界贴近动作及 WCAG 2.1 AA 的产品约束。
- 验证：固定 SKU 与核心门户 `6 tests` 干净通过；门户空状态 `1 test`、客户访问 API `2 tests`、隔离存储正式导出投影 `1 test` 通过。来源上下文用例在组合执行中通过，单独复跑因环境累计耗时超过 `180s` 被终止，未出现断言失败。Python `compileall`、三个 JSON contract 解析和 `git diff --check` 通过；未执行真实客户交付。
- 关闭口径：本项确认交付材料的责任口径和字段投影已统一，不等于律师审阅、法律意见、客户合同条款或真实交付流程已经外部验收。正式试点上线前仍应由业务/法务确认措辞，并在人工交付后由运营另行记录接收方、渠道、时间和签发人。

### AGENT-001：可替换模型 Provider（代码完成，真实 Provider 验收外部阻断）

- 更新日期：`2026-07-20`
- 状态：`BLOCKED_EXTERNAL / CODE_AND_LOCAL_RESPONSES_PROTOCOL_VALIDATED`
- 运行时适配：新增 `contracts/model/model_provider_runtime_contract.json` 与 `src/shared/model_provider_runtime.py`，实现 OpenAI Responses-compatible transport，但不把具体供应商或型号写成产品承诺。唯一可执行模式是显式 `INTERNAL_SHADOW`；默认 `OFF`，kill switch 优先切到 `EMERGENCY_OFF`。现有 Stage3/4/5/7 确定性 carrier 不会自动请求外部模型，只能由受控 wrapper 或一次性 canary 显式调用。
- 能力边界：模型只允许 `CANDIDATE_EXTRACTION`、`EVIDENCE_SUMMARY`、`REVIEW_EXPLANATION`、`DRAFT_COPY`。请求限定 `PUBLIC/INTERNAL_SANITIZED`，敏感键按大小写、下划线和驼峰归一化后失败关闭；工具调用、正式事实写入、客户可见输出和法律结论均关闭。候选的 `source_ref` 必须来自本次输入，模型结果永远标为 `HUMAN_REVIEW_REQUIRED`，不得改变证据门、规则门或审批门。
- 安全与审计：provider/model/HTTPS host 必须精确配置；外部端口只允许 `443`，受控 proxy URL 拒绝凭据、查询和路径，HTTP 只在显式测试构造器中允许 loopback。API key 只从仓库外单行 secret 文件读取，不进入环境变量、结果或 trace；请求强制 `store=false`、无 tools、严格 JSON Schema。结果只记录 request/response hash、provider response ID、prompt 版本、token、延迟、尝试/重试次数和人工复核边界，不持久化 raw prompt/response。
- 激活门禁：真实执行同时要求内部影子审批为 `APPROVED`、非空 audit ref、eval 为 `PASSED`、精确 allowlist、secret file，以及受控出口 proxy 或单次明确 direct-HTTPS 批准。`scripts/run_model_provider_shadow_canary.py` 只写仓库外新文件，不能覆盖历史结果；private-pilot Compose 当前未注入模型 secret，也未为模型域名开放出口，因此不会因部署而隐式上线。
- 验证：默认关闭、紧急熔断、配置门、仓库外 secret、真实 loopback HTTP `/responses`、429 后有限重试、`store=false`、无 tools、strict schema、敏感输入拦截、驼峰键拦截、虚构 source ref 拒绝及既有 carrier wrapper 共 `10 tests`；与 deterministic assist、permission layer 和 external unlock gates 联合共 `35 passed + 15 subtests`。JSON/YAML 合同解析和 Python compile 通过；canary CLI 在默认 OFF 时以状态码 `2` 失败关闭且不生成输出文件。
- 外部阻断：没有真实 provider API key、模型治理 owner 的真实审批/审计号、对目标模型完成的 eval、受控出口开放和一次真实 provider canary。仓库不能伪造这些条件，因此本项不能写成真实模型已上线；补齐后还需保存真实延迟、token、费用、失败分类和人工复核结果，再决定是否进入 AGENT-005 的持续质量门。

### AGENT-002：受限自然语言任务入口（完成）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / INTERNAL_DETERMINISTIC_GROUNDED`
- 产品入口：运营操作台新增“智能体对话”，支持自然语言创建内部任务、查询队列进度、追问项目证据和读取下一步。入口独立登记为 `operator_agent` 路由组，使用现有浏览器会话、CSRF、RBAC、principal 限流/并发门和严格请求/响应契约，不再误归类为只读 readiness projection。
- 创建门禁：创建任务必须有项目 ID 和显式确认；确认前只返回方案且零队列写入，确认后复用正式 Stage1 scheduler 创建幂等 `SANITIZED_OFFLINE_INTERNAL` 任务。任务固定关闭 Stage2 fetch、真实外部抓取和 live execution；再次发送只读回原任务，不重复创建。
- 事实边界：证据、进度和下一步只从正式 task/work-item/project/evidence/report/opportunity 等持久对象生成。每项事实带 citation，公开 URL 会清理敏感查询参数并拒绝私网/loopback/sensitive ref；未找到明确返回 `INSUFFICIENT_EVIDENCE`，并说明“未找到不等于没有风险”。敏感输入和直接触达、支付、退款、交付、发布指令失败关闭且不回显原文。
- 运行边界：默认 `DETERMINISTIC_GROUNDED`，不会因为 AGENT-001 配置存在而调用模型；不显示模型内部推理、不保存长期对话历史。AGENT-004 只加载登记的 principal 偏好和显式项目上下文，并始终标为未验证、非证据。对话入口自身不自动调用工具；AGENT-003 的 planner 是独立受控接口，当前仍不能宣传为全自主智能体。
- 实测修复：真实浏览器验收发现并修复两项单测未覆盖问题——带修饰词的“创建一个内部任务”曾被误判为 HELP，以及任务实际创建成功后事实渲染调用跨页面函数导致 UI 误报失败。修复后已验证帮助、未确认零写入、确认创建、幂等读回、正式引用、证据不足提示和零 console warning/error。
- 验证：AGENT-002 定向与严格写契约/路由/前端安全联合 `13 passed + 29 subtests`；架构与 capability 联合 `40 passed + 71 subtests`；合同校验、Python compile 和 `git diff --check` 通过。Playwright 真实 Chromium 经登录页进入操作台完成端到端验收并保存本地截图；没有执行模型调用、真实抓取、触达、支付、退款、客户交付或发布。

### AGENT-003：严格工具注册与两阶段计划协议（完成）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / DETERMINISTIC_READ_ONLY_AND_HUMAN_HANDOFF`
- 注册表：新增 `contracts/agent/agent_tool_registry.json` 与 `agent_tool_plan_contract.json`。工具参数遵循 Responses strict function schema：所有对象 `additionalProperties=false`、字段全部 required（可选值显式 nullable）；只允许 `allowed_tools` 子集、`parallel_tool_calls=false`，每个 `call_id` 从提案贯穿执行结果和持久审计。可生成标准 Responses 工具配置片段，但生成配置不等于发起模型调用。
- 当前工具：登记任务状态读取、项目证据读取、项目下一步读取、Stage1 内部任务方案、AGENT-004 安全记忆上下文读取，以及“创建任务人工交接”。正式状态/方案均复用确定性读回；记忆工具只返回未验证、非证据上下文；任务创建交接永远输出 `WAITING_AUTHENTICATED_OPERATOR_CONFIRMATION`，不写队列、不在 planner 中恢复。邮件、短信、电话、支付、退款、交付、发布、任意 HTTP/shell、正式事实写回和 gate override 不在可执行注册表。
- 两阶段执行：完整计划先统一校验工具名、严格参数、专属 `internal_agent_plan` 权限、重复 call ID、每工具次数和总预算，任一错误则零执行。通过后只按顺序执行显式 `execute_read_only=true` 的只读步骤；最多 4 步、最多 3 个可执行读取、单工具最多 2 次、单步输出 32 KiB、总时间 5 秒、零重试、首错停止。遇到人工步骤立即暂停，前序读步骤可回放但后续不执行。
- 审计与幂等：每个 plan/step 都持久化正式记录，包含计划 hash、参数 hash、输出 hash、call ID、权限、风险、起止时间、结果和安全输出；不保存 raw prompt、模型内部推理或非法参数。相同 plan ID/相同 hash 返回原结果且不重跑；同 ID/不同 hash 拒绝且不覆盖历史。未登记工具和恶意额外参数只保留 hash，不回显邮箱、URL、凭据或任意原始输入。
- 真实模型边界：`MODEL_SHADOW_PROPOSAL` 只是结构化提案来源标签；AGENT-001 provider 仍强制无 tools，当前没有真实模型 planner loop、provider tool continuation 或 production tool autonomy。未来接入仍必须经过 AGENT-001 真实 canary 与 AGENT-005 质量/成本评估，且不能放宽本注册表、权限和人工暂停门。
- 验证：planner 定向/API/权限/严格写契约 `8 passed + 35 subtests`；与 AGENT-002、架构和 capability 联合 `55 passed + 76 subtests`。合同校验、Python compile 和 `git diff --check` 通过；未调用模型、未创建 planner 队列任务、未执行外部或 live 动作。

### AGENT-004：用户/项目记忆与上下文治理（完成）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / PRIVATE_SINGLE_TENANT_GOVERNED_MEMORY`
- 作用域：新增 `contracts/agent/agent_memory_governance_contract.json` 与 `src/shared/agent_memory.py`。租户作用域只能由认证 transport 注入，调用方不能提交或覆盖；个人偏好按 tenant+principal 隔离，项目工作上下文按 tenant+project 隔离并只在显式项目查询中读回。当前仍是每客户一实例的 `PRIVATE_SINGLE_TENANT`，不把这层作用域宣传成完整共享 SaaS 对象 ACL。
- 内容边界：只登记回复语言、回复详细度、输出格式、默认地区和最长 500 字的项目工作备注。凭据、token、Cookie、密码/私钥、邮箱、手机号、身份证、带 secret query 的 URL、原始对话历史、模型推理和受治理原文拒绝写入；安全模型投影在读取时再次扫描，旧记录若不符合也不会进入上下文。
- 生命周期：首次写入与相同值回放幂等；活动值变化必须 `CORRECT + expected_version`，删除必须 `DELETE + expected_version`。纠正、删除、过期均保留独立审计，但审计只有前后 value hash，不保留原值。删除或到期会立即把活动记录的 raw value 清空并默认隐藏；无原值墓碑 30 天后仅标记为可物理清理，当前没有虚报跨数据库/历史备份的自动硬删除或多 API 原子 CAS。
- 智能体边界：对话入口和 strict planner 新增受控 memory context/read tool；投影固定 `UNVERIFIED_CONTEXT_ONLY`，不会进入 `facts`、`evidence`、`citations`、规则门、证据门或审批门，也不会单独触发模型 provider。项目工作备注即使写着事实判断，也只能作为人工工作上下文；正式答案仍必须从正式对象和来源生成。
- 权限/API：`owner/operator/admin` 新增独立 `internal_agent_memory` 权限，`reviewer` 无权查看或修改。`GET/POST /operator-console/agent/memories` 分别提供查看与严格变更；POST 拒绝未知字段和 actor/tenant spoof。该项完成时 API catalog 为 `1.0.6`、中央严格写操作计数为 `31`；后续 PROD005/007 已在不放宽本项边界的前提下扩展总账。
- 验证：记忆、planner、对话、架构 anti-drift 和 capability/权限联合 `63 tests` 通过；API transport 全模块修正后 `32/32 tests` 通过。合同校验、状态对齐、Python compile、四份 JSON 解析和 `git diff --check` 均通过。真实浏览器在 `820x1180` 完成创建 v4、对话读取、删除确认和零活动记忆回读；删除后旧回答立即从 DOM 清除，页面不再出现原值，控制台 `0 errors / 0 warnings`，证据见 `output/playwright/agent-memory-governance.png`。敏感值零持久化、租户/principal/项目隔离、纠正/删除无原值审计、过期清值、记忆不形成证据、planner 只读和 reviewer 读写拒绝均有回归。未调用真实模型、未执行 live 或外部动作。

### AGENT-005：模型质量、成本、失败降级与版本回归（代码完成，外部阻断）

- 更新日期：`2026-07-20`
- 状态：`CODE_VALIDATED / BLOCKED_EXTERNAL_NO_REAL_PROVIDER_RESULTS`
- 质量合同：新增 `contracts/model/model_quality_evaluation_contract.json`，明确区分 `OFFLINE_PROTOCOL_REPLAY` 与 `REAL_PROVIDER_SHADOW`。离线通过只证明 Schema、来源追踪、安全拒绝和降级代码可用，不能声称真实模型准确率、延迟、token 或费用已验证；真实影子通过也不开放客户输出、正式事实写入、工具调用或 controlled-opening。
- 金标：新增 10 例离线协议金标，覆盖正常结构化结果、虚构 source_ref、额外 Schema 字段、超时、429、受限输入、模型拒绝、绝对结论/绕过人工、提示指令泄漏和 incomplete response；另冻结 12 例真实质量金标，四类任务各 3 例，要求人工标注接受、幻觉、边界泄漏和禁止结论。
- 降级：Provider 超时/网络/认证/限流/5xx、拒绝、非法响应/Schema、虚构来源和不安全输出统一返回 `FALLBACK_DETERMINISTIC_REVIEW_REQUIRED`。降级结果不复用失败模型内容，候选为空、草稿为空，只引导回正式对象、登记来源和人工复核；受限输入、非法请求和 Provider 未启用仍直接失败关闭。
- 追踪与费用：每例记录精确 provider/model、prompt ID/version、token、延迟、attempt、失败分类和执行证据类型。本地 HTTP/注入 transport 不再误报成外网调用；只有真实 external transport 才能形成 `EXTERNAL_PROVIDER_SHADOW`。费用仅在 token 有效且存在精确匹配、版本化、经审批价格快照时计算；否则金额为 `WITHHELD`/`NOT_APPLICABLE`，不伪报 0。
- 版本门：同一 golden 版本下比较人工接受率、trace 完整率、幻觉率、边界泄漏率与 p95 延迟；超过允许退化即 `BLOCKED_REGRESSION`。真实门还要求 12 例全覆盖、100% trace、0 幻觉、0 边界泄漏、至少 90% 人工接受、失败率不高于 10%、p95 不高于 30 秒和 100% 核准费用覆盖。
- 当前证据：`scripts/run_model_quality_evaluation.py --mode offline` 已生成 `output/model-evaluation/agent005-offline-quality-report.json`，10/10 通过，其中 8 例确定性降级、1 例敏感输入 transport 前失败关闭、外部调用数 0。`build_model_quality_canary_requests.py` 已生成 12 份 hash 绑定请求和 `REQUESTS_BUILT_NOT_EXECUTED` manifest，明确未调用 Provider。模型 runtime/assist/quality 首轮联合 `18 tests` 通过。真实 Provider canary、12 例真实运行与人工标注、核准价格快照和已批准 baseline 尚不存在，因此本项必须保持 `BLOCKED_EXTERNAL`；当前不能宣称模型质量或成本已验收。

### PROD-005：私有单租户产品配置与受控入驻（完成）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / PRIVATE_SINGLE_TENANT_OWNER_ADMIN_CONFIGURATION`
- 产品边界：新增 `contracts/governance/product_onboarding_config_contract.json` 和运营台“产品配置”入口。当前能力明确是每客户一实例的私有单租户 owner/admin 配置，不是客户自助注册、共享多租户 SaaS、订阅或在线付款 onboarding；普通 operator/reviewer 无权读写。
- 安全配置：只允许登记目录中的商业试点地区或全国观察入口、每地区登记默认来源、固定 `CONSTRUCTION_PUBLIC_EVIDENCE` 行业、固定 `SKU_B_PUBLIC_SOURCE_FOUR_FIELD_RISK_REVIEW` 模板及有界候选/详情/附件/时间预算。网络请求没有自由 URL、自由来源 ID、live 开关、审批覆盖或 gate override 字段；未知字段、敏感名称、未登记地区/来源和越界预算均失败关闭。
- 生命周期：`UPSERT_DRAFT` 每次生成不可变 `DRAFT_VALIDATED` 新版本；`ACTIVATE` 只接受最新草稿，且必须存在同一 version/config hash 的 `OFFLINE_VALIDATION PASSED`；激活另生成新活动版本和单一 active pointer。`ROLLBACK` 只能选历史活动版本，并生成新的 `ACTIVE_ROLLBACK` 版本，不改写历史。expected_version 保护并发变更，审计只保存配置 hash 而不复制原始配置。
- 试跑边界：离线试跑只验证地区、来源、模板、预算和固定门禁投影，不创建任务、不抓取来源、不调用模型，也不触发触达、支付、退款、客户交付或发布。活动配置本身仍不能扩大来源白名单或改变审批/放行门。
- UI 实测修复：真实浏览器发现并修复首次安全默认值缺少名称时覆盖预填名称、版本变更后陈旧 GET 读回、目录未加载完成前动作按钮可点击三项问题。内部 JSON 请求使用 `cache: no-store`，动作按钮按加载/版本状态启用。
- 验证：配置领域与 API 端到端、严格写契约、前端安全/挂载联合 `8 passed + 39 subtests`；领域/API 单独 `5 passed + 6 subtests`。合同 JSON、Python/JavaScript 语法和页面安全检查通过。真实 Chromium 经内部登录完成 v1 草稿、未试跑激活 409、离线通过、v2 激活、v3 改预算、v4 再激活和回滚为 v5；820×1180 无横向溢出，排除预期 409 网络错误后控制台 0 error/warning、页面 0 exception，截图为 `output/playwright/product-onboarding-config.png`。
- 关闭口径：本项关闭的是私有试点配置治理和负责人入驻流程，不代表多租户对象 ACL、客户自助 onboarding、全国来源覆盖或真实生产公开源运行已完成。后续若进入共享 SaaS，必须另做租户级授权、存储隔离、配置审批和配额计费，不能复用本项状态作替代证明。

### PROD-007：运营支持工作台与受治理故障恢复（完成）

- 更新日期：`2026-07-20`
- 状态：`VALIDATED / PRIVATE_SINGLE_TENANT_OWNER_ADMIN_SUPPORT`
- 统一读回：新增 `contracts/governance/operator_support_workbench_contract.json`、`shared.operator_support_workbench` 与运营台“运营支持”入口。owner/admin 可在同一页面查看当前部署租户、持久队列任务、阻断、状态计数、最新队列审计、API/catalog/支持合同/产品配置合同和存储 schema 版本；普通 operator/reviewer 无权访问。
- 最小暴露：任务列表只返回 allowlist 摘要，包括队列、状态、任务/项目 ID、job kind、worker capability、尝试次数、进度、错误分类和更新时间；不返回 raw task payload、raw error 或 audit detail。页面和 API 明确只有当前私有租户，`visible_tenant_count=1`、跨租户查询关闭，不冒充共享 SaaS 管理后台。
- 受治理重试：只允许 `failed/dead-letter` 内部队列项重试。请求必须带当前 `expected_status + expected_updated_at`、10-500 字安全原因和精确 `RETRY_FAILED_INTERNAL_TASK` 确认；页面点击后另有 confirm 二次确认。重试保持原 payload 完全相等，只把状态变为 `retry`、增加一次最大尝试并写 `manual_retry_queued` 审计；已打开 live/客户可见/支付/交付/自动退款任一边界的任务拒绝。
- 事实边界：支持工作台不提供任意 JSON、任务参数或正式对象编辑器；不会修改项目事实、证据、引用、规则门、审批门、销售/交付对象。运行中长任务继续复用现有协作取消入口，不在支持后台复制第二套取消状态机。
- 验证：支持领域/API/严格契约/页面安全首轮 `6 passed + 3 subtests`；与网络角色、严格写契约、前端、scheduler worker 和存储并发联合 `61 passed + 42 subtests`，1 个可选真实 PostgreSQL 用例按环境跳过。合同/JS/Python 校验通过。真实 Chromium 预置失败任务后完成任务/阻断/租户/版本/审计读回、二次确认、POST 200 重试和审计回读；原始失败详情未进入 DOM，820×1180 无横向溢出，控制台 0 error/warning、页面 0 exception，截图为 `output/playwright/operator-support-workbench.png`。
- 关闭口径：本项关闭的是当前私有实例的 owner/admin 故障查询和失败任务恢复，不代表 7×24 客服体系、跨租户检索、远程客户代操作、自动修复、真实告警轮值或 production live 运行已外部验收。真实告警、值班和容器运行证据仍受 OPS-004/RUN-003 等项约束。
