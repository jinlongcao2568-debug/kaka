# Kaka 智能体产品化攻克总表

**版本**：2026-07-19 v1
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
| SEC-003 | 认证、角色、审批被混为一体 | 单个共享 token 获得多项权限，认证后直接投影 `approval_audit_confirmed=true`；没有用户、角色、对象所有权 | 修复 | 身份认证与业务审批分离；至少有 owner/operator/reviewer/admin 角色；敏感动作逐对象授权；审批记录不可由普通认证自动满足 | OPEN |
| SEC-004 | 没有租户/客户数据隔离边界 | 所有已认证调用者可访问同一内部数据和产物；不适合客户共享部署 | 变通后修复 | 当前 MVP 明确为单租户私有部署；用部署级隔离阻断跨客户访问；进入 SaaS 前实现 tenant_id、对象级授权、存储隔离和越权测试 | OPEN |
| API-001 | 大部分写接口不是严格契约 | 26 个写操作只有 5 个正式创建接口使用严格 Schema，其余依赖 `extra="allow"` 通用请求模型；响应普遍是 `dict[str, Any]` | 修复 | 所有对产品状态有写入的接口有明确 Pydantic 请求/响应模型；拒绝未知字段；敏感字段分离内部/外部响应；OpenAPI 与运行读回一致 | OPEN |
| OPS-001 | 当前 Compose 只是本地定义 | `docker-compose.yml` 标记 `local_stack_definition_only`，只绑定 `127.0.0.1`，默认 JSON 文件存储 | 变通后修复 | 本地模式保持不变；新增独立 private-pilot 部署配置；TLS/反代/Host 限制/密钥注入明确；不得把本地 Compose 改名冒充生产配置 | OPEN |
| OPS-002 | 默认 JSON 文件不能承担多实例生产 | JSON 后端虽有锁和写前重载，但不适合作为生产多副本数据库 | 修复 | 私有试点使用 PostgreSQL；启动前执行迁移；并发、幂等、唯一约束、事务和重启恢复测试通过；JSON 只保留开发/单进程模式 | OPEN |
| OPS-003 | PostgreSQL 迁移没有部署闭环 | Compose 标记 migration required，但应用不会自动迁移，也没有 release job | 修复 | 提供显式 migration job/命令；数据库健康与 schema version 检查；升级失败停止发布；完成一次空库安装和一次旧版本升级演练 | OPEN |
| EVD-001 | Stage4 释放证据链仍是核心瓶颈 | 当前 focus 是 `P0_STAGE4_RELEASE_EVIDENCE_CHAIN`；clean live30 中 Stage3 完成但 Stage4 仍有大量缺口，客户可见交付关闭 | 修复+限定范围 | 先固定广东/广州来源与四类核验；clean batch 明确分母；可回放 source URL/snapshot/hash/B-C-D/阻断/下一步；未命中不形成排除结论 | OPEN |
| PROD-001 | 尚无可收费的正式交付协议 | 当前有内部证据包/LeadPack 候选，但客户可见内容、免责声明、版本、水印、字段白名单和人工签发流程未形成正式最小产品 | 修复 | 定义一个固定 SKU；生成可人工签发的 PDF/ZIP/HTML 证据包；包含版本、来源、时间、证据等级、限制声明、水印和交付审计；无需真实支付网关即可交付 | OPEN |

## 4. P1：核心业务效果与私有试点稳定性

| ID | 问题 | 当前证据/影响 | 默认决策 | 关闭标准 | 状态 |
|---|---|---|---|---|---|
| EVD-002 | GDCIC 授权会话缺少真实命中样本 | 无 storage state/user data dir 时只能正确停在登录阻断；HTTP/Dynamic/Stealthy 不能代替登录态 | 变通 | 有合法授权会话时走授权浏览器；没有授权时跳过该来源并显示阻断；取得至少一个真实授权命中回放后再评估是否长期保留 | OPEN |
| EVD-003 | P13B 和字段查询结果回灌仍不稳定 | 任务、bridge、readback 已存在，但真实项目常停在来源缺口、字段缺口或 manual hold | 修复 | 同一项目从重叠信号到字段查询、Stage5、Stage6 状态可回放；失败能自动指向 adapter/browser/operator，而不是依赖人工记忆 | OPEN |
| DATA-001 | Stage3 负责人/OCR/复杂表格仍有误抽漏抽 | 已修复一批假姓名和附件问题，但更多地区、OCR、联合体、多候选行仍未稳定 | 修复 | 建立真实金标集；分字段统计 precision/recall；关键身份字段低置信度必须 REVIEW；错误样本进入回归库 | OPEN |
| DATA-002 | 长尾附件、SPA、验证码和下载端点仍不稳定 | 主流文件可跑，挑战页、脚本下载、超大附件和动态壳仍需要专项路径 | 修复+砍尾部 | 固定支持的内容类型、大小和来源；支持集内可重试/回放；超出支持集明确 `BLOCKED/UNSUPPORTED`，不无限自动升级浏览器 | OPEN |
| DATA-003 | 来源覆盖率和新鲜度没有产品指标 | 不能判断“系统没发现”是没有机会、来源没覆盖、解析失败还是抓取过期 | 修复 | 每个来源记录最后成功时间、列表覆盖、详情覆盖、附件覆盖、阻断率；对外只承诺已登记来源和时间窗口 | OPEN |
| RULE-001 | Stage5 缺少足够真实样本校准 | 规则框架和双闸门已存在，但真实误报/漏报证据不足 | 修复 | 先完成不少于 50 个去重真实项目金标；输出误报、漏报、REVIEW 占比；每次规则调整有前后对比；不以单一命中率代替证据质量 | OPEN |
| RUN-001 | 没有真正无人值守的周期调度 | orchestrator 明确 `unattended_recurring_run_ready=false`；当前需要 run-once、CLI 或 OS scheduler | 修复 | 独立 worker/scheduler 进程；任务租约、心跳、重试、暂停、死信可观察；重启后续跑；不在 Web 请求内执行长链 | OPEN |
| RUN-002 | 长任务缺少完整进度、取消和预算边界 | 操作台/真实样本测试可持续数分钟；同步等待影响体验和稳定性 | 修复 | 所有长任务异步入队；返回 job_id；页面显示阶段进度、最近心跳、预算、超时、取消、重试和错误分类 | OPEN |
| RUN-003 | API 镜像与完整 worker 能力分离但未编排 | 默认 API 镜像不含浏览器、MarkItDown 和富文档能力；全量 worker 需单独构建 | 修复 | API、worker、browser-worker 明确拆分；Compose/private-pilot 配置能启动对应服务；任务按能力路由；API 容器不承担浏览器任务 | OPEN |
| SEC-005 | 请求体限制只依赖 Content-Length | chunked/缺失 Content-Length 时应用层限制可绕过；昂贵接口没有统一用户级限流 | 修复 | 边缘代理限制 body、并发和速率；应用层流式计数；对搜索、抓取、解析等昂贵任务按用户/租户限流 | OPEN |
| SEC-006 | 缺少生产 Host、代理信任与安全响应头配置 | 应用未见 TrustedHost/CSP/nosniff/frame/referrer/permissions 等完整配置；可能由未来边缘层提供 | 修复 | private-pilot 配置明确 allowed hosts 和可信代理 IP；运行测试读取真实响应头；CSP 不依赖 `unsafe-eval`，尽量移除 inline script | OPEN |
| SEC-007 | SSRF 仍有 DNS 校验与实际连接之间的竞态 | 已阻断私网、非标准端口和跨主机重定向，但预解析后 transport 仍可能重新解析 DNS | 修复+基础设施缓解 | 允许域名清单；连接时绑定已验证 IP 或经受控 egress proxy；云元数据和内网由网络层阻断；保留重定向与子请求测试 | OPEN |
| SEC-008 | 依赖版本基线偏旧 | 当前 FastAPI/Pydantic/Starlette 版本较旧；现有 API 未使用 FileResponse/multipart，但以后扩展文件能力会扩大风险面 | 修复 | 升级到兼容的受支持版本；锁定传递依赖；镜像内 `pip check` 和安全扫描通过；文件/请求回归通过 | OPEN |
| OPS-004 | 监控告警主要是 readback，不是真实生产观测 | 外部 APM、paging、通知和 live alert dispatch 均关闭 | 修复 | 至少接入日志、指标、错误追踪和告警目的地；覆盖抓取、队列、解析、DB、交付；完成一次受控告警演练 | OPEN |
| OPS-005 | 备份、恢复、回滚主要停在 dry-run/readiness | 当前 `safe_to_restore=false`，真实恢复和回滚未执行 | 修复 | 私有试点数据库和对象存储有备份；完成隔离环境恢复；记录 RPO/RTO；发布具备上一版本回滚路径 | OPEN |
| PROD-002 | 缺少可量化的产品价值验收 | 现在更关注链路是否存在，缺少客户视角的有效机会率、复核耗时、证据包产出率 | 修复 | clean batch 固定分母；至少记录发现率、Stage4 ready率、可复核率、证据包率、人工分钟数、最终采用/退款原因 | OPEN |
| PROD-003 | 客户可见边界和法律免责声明尚未产品化 | 内部已有 no-legal-conclusion 语义，但正式交付合同、页面和文件需一致 | 修复 | 所有交付面统一说明公开来源、查询时点、非完整性、非法律结论、人工复核和客户责任；黑箱字段不外泄 | OPEN |

## 5. P2：真正的智能体与企业产品能力

| ID | 问题 | 当前证据/影响 | 默认决策 | 关闭标准 | 状态 |
|---|---|---|---|---|---|
| AGENT-001 | 当前没有真实大模型调用 | `model_assist_governance.py` 是 `LOCAL_DETERMINISTIC_ASSIST`，明确不调用外部模型 | 修复 | 接入一个可替换模型 provider；模型只做候选提取、摘要、解释和文案；事实、证据门、审批门仍由确定性代码决定 | OPEN |
| AGENT-002 | 没有面向用户的对话式任务入口 | 现在主要是表单、操作台、按钮和读回，不是自然语言智能体体验 | 修复 | 用户可用自然语言创建受限任务、追问证据和查看下一步；每个回答可回链到正式对象和来源；不能执行未授权 live 动作 | OPEN |
| AGENT-003 | 缺少模型工具调用与计划执行协议 | 已有运行控制器和入口注册，但没有真实模型 planner/tool-call 循环 | 修复 | 建立严格工具注册表、参数 Schema、权限和预算；模型只能调用允许工具；每步有输入/输出/审计；高风险动作必须暂停等人工 | OPEN |
| AGENT-004 | 缺少用户/项目记忆和上下文治理 | 当前持久化以运行对象为主，没有面向客户的长期偏好、项目空间和记忆删除机制 | 修复 | 记忆按租户/项目隔离；可查看、纠正、删除；敏感数据不进入模型；过期策略明确；模型不能把记忆当事实证据 | OPEN |
| AGENT-005 | 缺少模型质量、成本和降级验收 | 尚无真实 provider，因此没有延迟、成本、幻觉、超时和版本回归数据 | 修复 | 建立 golden cases；记录模型版本、prompt、token、延迟、费用和失败；超时可降级到确定性链；模型输出永远是候选/草稿 | OPEN |
| PROD-004 | 缺少正式客户账号与企业空间 | 当前是单 owner/operator 视角 | 后置到私有试点后 | 企业、用户、项目、角色、邀请、停用和审计闭环；没有 tenant_id 的对象不得进入 SaaS | DEFERRED |
| PROD-005 | 缺少产品配置和客户 onboarding | 来源、地区、行业、证据模板和运行预算更多依赖内部配置 | 修复 | 提供受限配置向导；默认安全模板；配置有版本、校验、回滚和测试运行；客户不能绕过来源/审批边界 | OPEN |
| PROD-006 | 缺少授权、套餐、用量与许可证 | 无法限制客户能运行什么、运行多少、可看哪些产物 | 后置 | 私有版先使用合同+部署配置；SaaS 前实现 entitlement、配额、用量和停用，不把支付成功直接等同于全部权限 | DEFERRED |
| PROD-007 | 缺少运营后台和客户支持工具 | 出错后主要靠日志、JSON 或开发者处理 | 修复 | 管理员可查任务、租户、阻断、重试、审计和版本；敏感操作有二次确认；不直接编辑事实层 | OPEN |
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
