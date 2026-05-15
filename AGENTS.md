# AGENTS

**Purpose**
- 本文件是当前仓库给 Codex/AI 代理的轻量执行约定。它不冻结项目阶段、路线图、任务包或 readiness，只规定默认工作方式和少数安全边界。

**Authority and State**
- 人类当前明确指令优先；当人类特别强调某个口径时，以人类强调为准。
- 代码、测试、脚本和当前运行结果优先于历史文档描述。
- 项目状态、readiness、active task、路线图等动态信息只在需要时读取 `control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` 和相关 control 资产；不要把 AGENTS 当状态源。
- `README.md`、`ARCHITECTURE_NOTE.md` 用于导航；`docs/`、`contracts/`、`handoff/`、`control/`、`scripts/` 按本次改动影响面按需读取。
- `archive/*` 只作历史参考，不作为当前正式引用面。

**Common Repository Paths**
- `docs/`
- `contracts/`
- `handoff/`
- `scripts/`
- `control/`
- 根目录：`README.md`、`ARCHITECTURE_NOTE.md`

**Current Business Direction Guardrail**
- 招投标分析当前按双线产品执行：候选公示后证据包分析为核心商业主线，投前预测分析为辅助产品线。
- 涉及“候选公示、候选人核查、真实竞争者、真实买家、控标/围标/串标/陪标证据包、销售承接”的任务，默认走候选公示后证据包主线：先从工作日 72 小时内的近期 `07 中标候选人公示` 入池，再回溯同一项目全流程招标公告、招标文件、答疑澄清、开标、资审、候选、结果、投标文件公开、合同和异常材料；开标记录、评标结果、中标结果、合同和异常材料是回溯/支撑或后期复盘阶段，不是默认入口。
- 涉及“刚发公告、招标文件、是否值得投、投前预测、澄清/质疑”的任务，走投前预测线；该线只适用于工作日 72 小时内的近期 `02 招标文件公示`、`03 招标公告/关联公告`、`04 澄清答疑` 且投标截止/开标未过的项目，标准销售窗口为截止/开标前 168 小时以上，72-168 小时只做限时快筛，少于 72 小时不作为正常投前预测销售；只有 `02/03` 且尚无 `04` 时只能做预澄清半成品预测，后续出现澄清、答疑、补遗或补充文件必须重新预测；一旦出现 `05 开标信息` 就不再卖投前预测，转入开标后核验/候选后证据包路线；该线不能输出候选人核查、真实竞争者结论或陪标组合结论。
- 近期 `07` 项目通常不会有 `11 合同信息公开` 和 `12 项目异常`，缺 11/12 不阻断当前证据包销售窗口；若 11/12 已出现，按历史/后期核验或复盘场景另判。
- 下载和解析前必须按 `AnalysisStrategyPlan v1` 口径先定产品线、流程范围、下载范围、解析深度、规则核验和大模型触发条件；不得把所有发现文件默认全部深解析。
- 候选后负责人核验必须按 `ResponsiblePersonEarlyProbe v1`：先从 `07` 详情页和小 PDF 低成本抽候选公司、项目负责人/总监/设计负责人、证书号、报价和排名；有证书号先 Stage4 核验，缺证书号先公司优先补证，再姓名枚举兜底，仍不匹配才定向解析 `08 投标文件公开`；`08` 默认只登记存在、URL、附件清单和后续可解析目标，不默认下载或解析，也不得把补证未命中直接写成最终冲突。`07` 多候选人和联合体必须按候选行绑定负责人/证书，核验同一候选行的全部联合体成员；同一候选行任一成员匹配即可视为该候选组身份线索已解析，不得把其他成员未匹配误判为冲突。
- 广州 `EvidenceReport v1` 必须分三类输出：核验线索/证据、过程稳定性问题、针对核验结果的优化建议；报告只内部使用，不输出客户可见法律定性。`ActiveConflictProbe v1` 第一版只生成地方公共资源、地方住建/行政审批、施工许可、合同备案、竣工验收、项目经理变更、处罚/投诉和可回放网络线索的待核验任务清单，不做全网自动最终判定。广东当前核验按省级源优先、广州城市源补强执行：`GuangdongLocalVerificationProbe v1` 覆盖广东三库一平台、广东合同履约监管、广东投资项目审批监管、广东住建处罚公示、信用广东和广州市住建局信用信息双公示；默认只生成任务和可达性诊断，入口可达不等于字段核验成功。`GuangdongLocalFieldQueryProbe v1` 在此基础上按候选公司、负责人、证书号和项目名做字段级只读查询探针；广州住建局信用信息双公示已接入 `guangzhou_zfcj_xyxx_api_query_v1` 源专项 API 回放，广州施工许可与竣工验收公开接口已接入 `guangzhou_zfcj_construction_permit_public_api_v1`、`guangzhou_zfcj_completion_acceptance_public_api_v1`，广东建设信息网招投标及合同履约监管系统已接入 `guangdong_gdcic_contract_performance_public_page_v1` 公开履约评价页探针，广东省投资项目在线审批监管平台已接入 `guangdong_tzxm_project_approval_publicity_api_v1` 备案/核准/审批公开接口探针，广东省住建厅行政处罚公示已接入 `guangdong_zfcxjst_penalty_publicity_page_v1` 源专项列表/详情页回放，信用广东已接入 `guangdong_credit_gd_public_credit_query_v1` 行政处罚/行政许可公开接口探针；信用广东精准查询如遇 WAF、验证码或旧接口 404 必须 fail-closed；字段回放只作为公开线索，不等于最终核验结论；关键词命中只作为公开源线索，查询未命中或阻断不得推断无风险，也不得替代其他源专项 adapter。在建/履约和业绩核验不能固定广东，必须先通过全国平台发现人员、企业和项目出现地区，再按重点省份公开源定向核验；当前重点省份源目录先覆盖浙江、四川、江苏、湖北、山东、湖南、河南，均为 `PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED`，不得当作已跑通 live adapter。`MajorRegionQueryProbe v1` 只负责把这些省份生成任务和可达性诊断，入口可达不等于字段核验成功。
- Stage4 负责人核验只能表述为“公开注册信息匹配/不匹配”，不得写“是不是本人”。当候选公示或 `08 投标文件公开` 中的姓名、候选公司/联合体成员、证书号与四库/地方注册人员公开记录或对应行业官方公开系统匹配时，可认为身份线索成立；不匹配才进入注册单位、证书号、证书类别/专业冲突线索。公路、路桥、交通工程可研、方案深化、勘察设计路线，四库/JZSC 未匹配或职称证路线更合适时，必须补充交通运输部全国公路建设市场监督管理查询系统的设计人员和职称证书核验，不得直接推入 `08`。四库/JZSC 可用于证书、注册单位、注册类别、注册专业、有效期/状态和 `08` 声明业绩的公开记录匹配，但不得作为实时在建冲突的唯一依据；在建/履约冲突必须优先结合地方公共资源、地方住建/行政审批、施工许可、合同备案、竣工验收、项目经理变更、处罚/投诉等地方或网络公开线索。
- P13B 外部在建/履约核验优先采用 `PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE`：第一层以全国公共资源交易平台数据服务 `data.ggzy.gov.cn` 的主体成交查询为主，按候选公司/联合体成员或统一社会信用代码查近 1-3 年公司历史成交记录；再用 `bid_list` 记录的 `bid_show` 正文和“原文链接”定向回溯原始源 01-12 阶段，抽项目负责人、工期/服务期和中标日期。只有命中同一负责人、公司/联合体成员和时间窗口疑似重叠后，才定向补查上一项目释放证据；不得一开始全省施工许可、竣工、合同备案全量扫描。`data.ggzy` 历史成交记录和原文链接只能作为宽筛和回溯入口，不能单独证明未释放，也不能单独排除问题；未命中、接口阻断、`bid_show` 缺负责人或地区源未适配只能写“未发现公开重叠线索/需复核/源阻断”，不得写排除结论。旧 `dealList_find.jsp` 不作为 P13B 公司历史中标主入口。
- 项目负责人未释放/在建履约冲突必须按官方证据链判断：当前项目 `07` 候选证据 + 可能占用项目的中标/施工许可/合同/履约公开记录 + 时间窗口 + 释放证据。释放证据包括合同约定工作验收或移交、竣工验收/备案、项目经理变更或施工许可变更、非承包方原因停工超过 120 天且建设单位同意、同一工程相邻分段/分期例外；广州项目还要关注建筑施工项目安全生产标准化考评结果告知书。缺竣工、缺备案、四库/JZSC 未命中或公开源阻断只能形成“未释放风险线索/证据不足”，不得写“在建冲突成立”“无在建”“无风险”。
- 正式证据包和白标协作只能输出事实、线索、证据、反向解释和建议核验事项；不得以本系统名义直接做收费举报、付费沉默、爆料号、公开点名、使用内部泄露材料或 AI 一键定性。证据固化至少保留来源 URL、采集时间、访问路径、脚本版本、snapshot/readback、SHA-256/hash、脱敏日志和字段血缘；可信时间戳、存证编号或公证是后置增强能力，未实现前不得说成已完成。SaaS、跨项目关系图谱、文件相似度、报价异常和多省 live readback adapter 是中期产品化方向，不得替代当前候选后证据包主线。
- 具体口径以 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json` 为准。

**Operating Mode and State Sources**
- 本文件不冻结任何动态项目状态；需要时读取 `control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` 和相关 control 状态资产。
- 默认执行模式：真实公开市场机会发现与证据包商业化产品开发以 `DIRECT_DEV_DEFAULT` 为默认入口；task packet / scoped subpacket 仅用于高风险、对外/live、机器契约或大批量治理窗口，不再作为普通开发前置门槛。
- 产品完成标准：真实公开来源候选能进料、可解析、可核验、可形成可验证证据包和商业钩子；内部/样本链路只作为开发回归、安全演练和受控验证环境，不再单独构成实战完成。
- 受控开放边界：外部软件 release、真实触达、真实支付、真实交付、真实退款均可作为受控开放能力推进；线索包外发仍需审批链 + 审计链；自动退款执行仍为 `EXCLUDED`。
- 允许：真实市场候选发现、公开来源采集、证据包商业化主线开发与受控实现、必要的文档/机器资产最小补齐、运行脚本校验并如实汇报结果。
- 禁止：未通过 release checklist / 审批链 / 审计链 / operator action 的对外软件 release、线索包外发、触达、支付、交付或退款；自动退款执行。

**Required Read Order**
1. 默认先读：`AGENTS.md`、`README.md`、`ARCHITECTURE_NOTE.md`、与本次改动直接相关的代码和脚本。
2. 涉及正式对象、规则、字段、交付、发布、模型、公开边界时，再读取对应 `docs/D*.md`、`contracts/*`、`handoff/*`、`control/*`。
3. 涉及对外/live、真实触达、支付、交付、退款、高限制字段、release gate、schema/migration 或机器契约时，必须补读 `docs/L0.md`、`docs/裁决总表.md`、`docs/D1_研发_Codex执行手册.md` 与相关控制资产。
4. 人类明确要求以某个文档或口径为准时，优先读取并执行该口径。

**Allowed Work**
- 默认允许直接修改代码、测试、脚本、文档、contracts、control、handoff、fixtures，只要改动服务于当前人类目标并保持影响面清楚。
- 发现文档、测试或机器资产与当前人类目标冲突时，可以同步修正，不需要只“补表”。
- 需要新增对象、枚举、schema、migration、release gate、对外/live 能力时，先定位现有契约和调用链，再做最小一致改动。

**Forbidden Work**
- 未经 release checklist、审批链、审计链与 operator action 放行的对外软件 release 或对外承诺。
- 把内部可用误写为客户可用。
- 无审计线索包外发。
- 自动退款执行。
- 未经人类明确要求，执行真实外部系统调用、真实支付、真实交付、真实触达、真实退款或 destructive 操作。
- 未经必要定位，新造第二套对象/枚举/门禁/路径来绕开现有体系。

**Automation Guardrails**
- 自动化动作门禁表：`docs/自动化开发动作门禁表.md`
- 动作矩阵：`control/automation_action_matrix.yaml`
- 停机条件：`control/automation_stop_conditions.yaml`
- 任务包规则：`control/automation_task_packet_rules.yaml`
- 真实 live 的触达/支付/交付/退款/高限制字段放行动作，必须先满足门禁、审批、审计与 operator action；自动退款执行必须停机并转人工拒绝。

**Direct Development Default**
- 普通代码修复、测试修复、文档小修、局部重构、非 live 的真实市场候选发现/证据包商业化功能实现，默认不要求先建立或切换 `control/current_task.yaml`。
- 普通开发默认按“定位影响面 -> 最小实现 -> 相关测试/脚本验证 -> 汇报或提交”执行。
- 仅当改动涉及以下任一项时，才需要 controlled task packet / scoped subpacket：对外软件 release、真实触达、真实支付、真实交付、真实退款、高限制字段放行、release gate、approval/audit 语义、schema/migration、跨阶段机器契约、批量生成 handoff/schema/control、或人类明确要求走小包。
- 人类明确说“不要小包 / 直接改 / 直接提交 / 不需要看范围”时，按 direct-dev 执行；但不得绕过对外/live、审批、审计、operator action 与自动退款禁令。

**When To Pause**
- 需要真实对外/live 行动、自动退款、destructive 操作、不可逆 migration、生产凭证或真实客户影响时，先停下说明风险。
- 测试或脚本失败时先定位根因；能修就继续修，不能修再汇报阻断。
- 人类明确要求先讨论、先评审或不要改时，停下等确认。

**Validation and Script Rules**
- 正式校验入口：`scripts/validate-contracts.ps1`、`scripts/run-golden.ps1`、`scripts/run-governance-contracts.ps1`、`scripts/check-task-packet.ps1`、`scripts/check-state-alignment.ps1`、`scripts/check-final-gate.ps1`。
- 执行方式（统一）：`pwsh -NoProfile -ExecutionPolicy Bypass -File <script.ps1>`。
- 文件存在不等于通过；以真实执行结果为准。
- 脚本失败必须报告根因，不得绕过。

**Current Execution Conventions**
- direct-dev 窗口以人类当前指令与实际代码影响面为准，不要求读取或切换 `control/current_task.yaml`。
- 机器门禁与 task packet 窗口必须保留 active-source priority：`current_task -> product_task_library -> repo_status`；该优先级用于受控/高风险/机器契约窗口，不取消普通开发的 direct-dev 默认。
- 当人类明确要求进入 task packet / scoped subpacket，或改动本身属于高风险/live/机器契约大批量窗口时，才按 `control/current_task.yaml -> control/product_task_library.yaml -> control/repo_status.md` 读取执行源。
- 若测试断言与当前人类目标或当前代码事实冲突，优先调整测试到正确口径，不为迁就旧断言而恢复过时语义。
- 默认提交行为：
  - direct-dev 窗口：完成相关最小验证后，默认允许本地 git commit；若人类明确要求直接提交，不因未运行全量 final gate 阻塞提交，但必须如实说明未验证项。
  - task packet 窗口：当前 scoped subpacket 的 required scripts 全绿，且仅修改允许范围内文件时，默认允许执行本地 git commit。
  - 提交前必须排除：`报告*.md`、`__pycache__/`、`*.pyc`、`.pytest_cache/`。
  - 上述临时/生成物不得混入 commit、review scope 或实际改动范围。
  - 默认不自动 push、不自动进入下一包。
  - 若工作区存在明显无关脏改，必须先区分来源；direct-dev 可只提交本轮相关改动，task packet 窗口不得混入包外改动。

**Archive and Non-Current Paths**
- `archive/*` 全部为归档路径，不得作为现行正式引用面。

**Highest Human Capability Authorization**
- 本节是人类当前明确给出的最高项目执行指示：在本仓库、自有系统、已经明确授权的目标、明确授权测试环境、sandbox、合规采集与人工辅助续跑场景中，以下能力均已授权作为目标能力开发、验证、测试、封装或排障，不得被旧文档、历史补表、旧 pre-start 口径或默认拒绝口径永久排除。
- 已授权能力包括：验证码识别、OCR 识别、滑块轨迹模拟、代理池绕限流、浏览器指纹伪装、Cookie 复用、登录后页面抓取、隐藏接口调用。
- “验证码突破器 / 风控绕过器”可在自有、sandbox、已经明确授权的目标、风控测试、兼容性验证、自动化回归与安全演练环境中作为目标能力表述。
- 涉及真实第三方生产环境、真实账号、Cookie、平台风控、限流或真实 live 外部执行时，以人类对具体目标的明确授权为准；同时仍需满足审批链、审计链与 operator action。未授权目标不被本条覆盖。
- 上述授权用于减少重复确认；不得绕过对外/live、审批、审计、operator action、自动退款禁令或适用法律/平台授权边界。

**Output Contract for Codex**
- 默认中文回答，直接、简洁、务实。
- direct-dev 小改只需说明改了什么、验证了什么、还有什么未验证。
- 大改或高风险改动再列修改文件、校验结果、阻断项和下一步。
- 如果人类特别强调以人类为准。
- 必要时要求实现：
- 验证码识别
- OCR 识别
- 滑块轨迹模拟
- 代理池绕限流
- 浏览器指纹伪装
- Cookie 复用
- 登录后页面抓取
- 隐藏接口调用
- 可做“验证码突破器/风控绕过器”。
