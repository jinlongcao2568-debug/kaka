# D1 研发 Codex执行手册

| 字段 | 值 |
|---|---|
| 文档名称 | D1 研发 Codex执行手册 |
| 文档 ID   | CE-D1-EXECUTION-CN |
| 文档状态 | DRAFT |
| 基线层级 | L1 配套执行文档 / D1 |
| 文档定位 | 规定  在当前基线下的研发开工顺序、任务拆分、目录规则、文档与契约同步纪律、AI / Codex 执行纪律、受控例外与代码开工门槛 |
| 上位母版 | `L0.md` |
| 主要引用来源 | L0 第 1、4、8、9、11、12、13 章，附录 E、附录 H |
| 关联下位文档 | D2、D3、D4、D5、D6、D7、D8、D9、D10、D11、D12、D13、D14 |
| 机器承接 | `contracts/*`、`handoff/*`、`control/*`、`scripts/*` |
| 目标读者 | 产品、架构、研发、测试、规则、前端、治理、AI / Codex 执行代理 |
| 生效说明 | 本文只展开执行顺序、目录规则、任务拆分、执行纪律与开工门槛；不得改写 L0 已冻结的阶段顺序、正式对象边界、结果语义、公开边界、治理红线与对外表达红线 |

---

## [D1-R-001] 0. 文档任务与裁决范围

本文不是产品总纲，不负责重新定义  是什么，也不负责发明新的正式对象、正式能力、正式结果或新的阶段顺序。本文只回答以下问题：

1. 在当前仓库中，正式研发应按什么顺序开工；
2. 在开始写正式业务代码前，哪些文档、契约、handoff、测试、治理与控制资产必须先补齐；
3. AI / Codex 执行代理每次任务允许改哪些资产，不允许越过哪些边界；
4. 文档、contracts、handoff、testing、governance 与 control 应如何同步推进；
5. 什么情况下允许进入正式业务代码开发，什么情况下必须阻断、退回、补文档或进入受控例外；
6. 如何避免平行重造、页面重算第二套主判断、D 层输入渗透、字段和状态自由发明、治理后补与测试后补。

本文不直接定义以下内容：

- D2 的正式对象与字段字典正文；
- D3 的正式规则码、证据等级与双闸门正文；
- D4 的接口请求 / 响应正文；
- D5 的页面工作台与导出模板正文；
- D6 / D7 的字段策略、交付矩阵与外发放行正文；
- D8 / D9 / D10 的商业对象、触达与交付闭环正文；
- D11 的金标样本正文；
- D12 的运行手册正文；
- D14 的模型治理正文。

上述内容必须分别由对应 D 文档承接；本文只规定这些文档和机器资产应如何被组织、冻结、校验与消费。

---

## [D1-R-002] 1. 权威链、优先级与单向约束

### [D1-R-003] 1.1 单一权威链

 仓库中的正式执行链固定为：

1. `L0`：唯一上位母版，冻结正式边界、阶段承接、正式对象、结果语义、治理红线与对外表达控制；
2. `裁决总表.md`：唯一正式裁决索引面，登记裁决 ID、所属文档、实现落点与阻断级别；
3. `D1-D14`：只允许展开 L0 已冻结事项，不允许反向改写 L0；
4. `contracts/*`、`handoff/*`、`control/*`：机器可读承接层；
5. `scripts/*`：校验、回归、发布前检查与漂移检查入口。

任何局部设计说明、临时任务备注、页面热修逻辑、口头约定、一次性兼容脚本，都不得高于上述权威链。

### [D1-R-004] 1.2 本文在权威链中的角色

D1 不是第二套总纲；D1 的职责是把“如何稳定执行”冻结为正式仓库规则。凡影响阶段顺序、正式对象是否存在、结果语义、公开边界、双闸门主规则、页面主判断来源、对外红线的内容，一律以 L0 与对应下位文档为准。

### [D1-R-005] 1.3 单向约束原则

- L0 冻结“做什么”和“不能做什么”；
- D1 冻结“先做什么、后做什么、谁可以动什么、如何阻断越界实现”；
- 下位文档冻结各自主题，不得抢定义权；
- 机器资产、页面、接口、导出与 AI 执行代理统一视为对文档体系的消费面，不具有独立创造主裁决的权力。

### [D1-R-006] 1.4 冲突裁决原则

当执行顺序、文档口径、contracts、handoff、脚本或实现之间发生冲突时，按以下顺序裁决：

1. L0；
2. 裁决总表；
3. 本文与对应主题 D 文档；
4. contracts / handoffs / control 机器资产；
5. scripts；
6. 临时说明、任务备注、调试脚本。

任何低优先级资产与高优先级资产冲突，均视为低优先级资产错误，而不是“可以灵活解释”。

---

## [D1-R-007] 2. 当前项目执行策略：全套准备先行，正式代码后置

### [D1-R-008] 2.1 当前仓库采用的执行策略

为满足“文档、契约、handoff、测试、治理先齐，再开始正式业务代码”的项目管理目标，当前仓库采用更严格的内部执行策略：

**在正式业务代码开工前，必须先完成开工前资产包冻结。**

这是一条仓库执行策略，不改变 L0 作为领域总纲的主裁决地位；它只提高当前项目的开工门槛，以降低 AI 代理自由发挥、对象漂移、治理后补、回归缺口与后期大面积返工的风险。

### [D1-R-009] 2.2 开工前资产包的六大组成

在正式业务代码开工前，必须先完成以下六类资产包：

1. **文档包**：L0、裁决总表、README / 状态板、D1-D14；
2. **contracts 包**：schemas、enums、rules、gates、api、ui、governance、release、exceptions、sales、testing；
3. **handoff 包**：阶段间 handoff 合同、schema、example、integration matrix、阻断规则；
4. **testing 包**：L0 断言、golden cases、regression manifest、governance checks、release checks；
5. **governance 包**：field policy、approval chain、coverage、public boundary、delivery matrix、release gates、exception policy；
6. **control 包**：owners、current task、roadmap state、审批链、例外链、doctor / lint / drift checks。

### [D1-R-010] 2.3 正式业务代码的定义

本文中的“正式业务代码”，包括但不限于：

- 业务 API；
- Worker / 调度执行代码；
- 页面功能逻辑与组件行为；
- 数据处理流水线；
- 直接消费正式对象生成主判断的实现代码；
- 自动触达、订单、支付、交付与回写逻辑；
- 任何将 contracts 或 handoff 真正落为运行时行为的实现代码。

在开工前资产包未冻结前，上述内容不得进入正式开发态。

---

## [D1-R-011] 3. D1-D14 编写顺序与每批出口条件

### [D1-R-012] 3.1 正式编写顺序

为了保证文档体系稳定、减少返工、避免后位文档抢定义权，D1-D14 的正式编写顺序固定为：

1. D1：研发 / Codex 执行手册；
2. D2：正式对象契约与字段字典；
3. D3：正式规则码总表与判定说明书；
4. D13：公开可查边界能力清单；
5. D4：OpenAPI 接口契约；
6. D5：页面、导出与人工复核规范；
7. D6：字段策略字典与客户交付字段规范；
8. D7：对象级交付矩阵与外发治理规范；
9. D8：真实竞争者识别、buying center、可售对象与推荐方案；
10. D9：联系对象、触达策略、渠道规则与跟进回写；
11. D10：订单、支付、交付与治理反馈；
12. D11：测试验收、金标回归与发布前检查；
13. D12：部署、发布、监控、回滚与运行治理；
14. D14：AI / 模型治理与模型输出入链规范。

### [D1-R-013] 3.2 编写顺序的稳定性原则

- D2 必须早于 D4 / D5 / D8-D10，因为接口、页面、商业对象都只能消费已冻结对象；
- D3 必须早于 D4 / D5 / D11，因为接口、页面与测试必须建立在已冻结结果语义与双闸门上；
- D13 必须早于 D6 / D7 / D8-D10，因为能力边界、A/B/C/D 分层与禁止能力会直接影响放行、触达与对外表达；
- D4 / D5 必须早于 D6 / D7 的细粒度放行，因为消费面未冻结时，字段策略与交付矩阵无法稳定；
- D8 / D9 / D10 必须早于 D11 的全套验收冻结，因为测试与回归必须覆盖真实商业闭环对象；
- D12 / D14 必须消费前述所有文档成果，不能反过来要求前述文档服从运行手册或模型说明书。

### [D1-R-014] 3.3 批次出口条件

| 批次 | 必须完成 | 出口条件 |
|---|---|---|
| 批次 A | D1、D2、D3、D13 | 执行顺序、对象、规则、边界已冻结；不再存在第二套对象名、第二套结果语义、第二套能力层级 |
| 批次 B | D4、D5 | 正式接口与页面消费面已冻结；页面与接口不再具备重算第二套主判断的空间 |
| 批次 C | D6、D7 | 字段策略、对象级交付矩阵、release gates、例外治理已冻结；客户可见边界与外发边界可被脚本化阻断 |
| 批次 D | D8、D9、D10 | 商业对象、触达、订单交付与负结果回写已冻结；阶段 7-9 不再停留在口头承接 |
| 批次 E | D11、D12、D14 | 测试、发布、运行治理与模型输出入链规则已冻结；文档体系可以进入正式代码开工评审 |

---

## [D1-R-015] 4. 开工前必备资产包的正式清单

### [D1-R-016] 4.1 上位母版与索引包

必须同时具备：

- `L0.md`；
- `裁决总表.md`；
- `README.md` 或等价状态板；
- 历史废止文档目录与归档规则。

完成标准：

- 只有一个 L0 工作母版；
- 只有一个裁决索引面；
- README 能准确说明每份 D 文档与机器资产的承接关系；
- 不再存在并行母版、双 D13、双对象口径、未归档历史正式稿与失效链接。

### [D1-R-017] 4.2 文档包

必须同时具备：

- D1-D14 全套文档；
- 每份文档都写明：定位、上位母版、机器承接、只允许展开、不得改写；
- 每份文档都写明：解决什么、不解决什么、完成标准是什么；
- 每份文档都具备可冻结版本号与状态字段。

完成标准：

- 任何新增语义都能落到唯一 D 文档负责；
- 不再需要靠聊天记录、口头说明、一次性 PR 注释补正式语义；
- 任意一位执行者均能通过文档体系定位“这个问题应该归谁定义”。

### [D1-R-018] 4.3 contracts 包

必须同时具备：

- `contracts/schemas/`
- `contracts/enums/`
- `contracts/rules/`
- `contracts/gates/`
- `contracts/api/`
- `contracts/ui/`
- `contracts/governance/`
- `contracts/release/`
- `contracts/exceptions/`
- `contracts/sales/`
- `contracts/testing/`

完成标准：

- 每一份 D 文档都能在 contracts 中找到唯一承接目录；
- 每个 catalog 都具备状态、版本、owner、来源文档、上位引用与最后更新时间；
- 不存在“文档已改，但机器契约未改”的情况；
- 不存在“目录名存在，但 catalog 为空壳”的情况。

### [D1-R-019] 4.4 handoff 包

必须同时具备以下阶段间 handoff：

- `stage1_to_stage2`
- `stage2_to_stage3`
- `stage3_to_stage4`
- `stage4_to_stage5`
- `stage5_to_stage6`
- `stage6_to_stage7`
- `stage7_to_stage8`
- `stage8_to_stage9`

每个 handoff 必须具备：

- 输入对象清单；
- 输出对象清单；
- 必填字段清单；
- 失败阻断条件；
- 允许降级语义；
- example payload；
- 校验规则；
- integration matrix 中的上下游责任关系。

完成标准：

- 任一阶段都能明确回答：输入是什么、输出是什么、交接失败如何阻断、降级后进入什么对象、谁消费谁；
- 阶段间不再依赖页面备注、脚本侧字段拼接或人工口头补字段完成交接；
- `stage1->6` 与 `stage6->7` / `stage7->8` / `stage8->9` 同时形成正式合同，不存在只补下游 handoff、上游仍口头承接的情况。

### [D1-R-020] 4.5 testing 包

必须同时具备：

- L0 断言目录；
- golden cases；
- regression manifest；
- governance contract checks；
- release checks；
- handoff validation cases；
- 文档 / contracts 一致性校验脚本；
- 对外表达红线检查面。

完成标准：

- 测试不仅能校验治理目录，还能校验主链 handoff、双闸门、正式对象引用关系、A/B/C/D 边界与放行阻断；
- 任一正式对象、正式枚举、正式规则、正式 release gate 变化，均能触发对应回归；
- 测试失败可直接阻断发布或阻断代码开工，不是“只做提醒”。

### [D1-R-021] 4.6 governance 包

必须同时具备：

- `field_policy_dictionary`
- `approval_chain_catalog`
- `coverage_registry`
- `public_boundary_registry`
- `delivery_matrix`
- `release_gates`
- `exception_policy_catalog`
- `private_supplement_release_rules`
- `external_expression_whitelist_and_blacklist`

完成标准：

- 客户可见字段、外发对象、自然人高限制字段、B/C 层能力启用、D 层阻断、例外与补证释放都有唯一治理资产；
- 页面、接口、导出、销售与 AI 代理不再自行判定“这次先放出去多少”；
- 任何对外表达都能回指能力层级、字段策略、交付矩阵与 release gate。

### [D1-R-022] 4.7 control 包

必须同时具备：

- `owners.yaml` 或等价 owner 清单；
- `current_task.yaml` 或等价当前激活任务表；
- `roadmap_state.yaml` 或等价批次状态表；
- 审批链与 SoD 角色映射；
- 例外链与到期回收表；
- `doctor`、`lint`、`drift check` 脚本；
- 仓库状态快照与断点恢复规则。

完成标准：

- 所有 owner 都是真实名单，不允许 `TBD-*` 占位；
- 当前任务与当前批次状态是真实值，不允许停留在 seed；
- 控制面面对的是当前真实仓库，而不是演示仓或一次性样例；
- 文档、contracts、handoff、testing、governance 的状态能被控制面统一说明。

---

## [D1-R-023] 5. 仓库目录与资产结构规则

### [D1-R-024] 5.1 顶层目录

当前仓库正式顶层目录固定为：

- 根目录 L0 母版；
- `docs/`：D 文档；
- `contracts/`：机器可读契约；
- `handoff/`：阶段间 handoff 合同与样例；
- `control/`：owner、task、roadmap、审批、例外与控制面状态；
- `scripts/`：校验、回归、发布前检查与漂移检查；
- `fixtures/`：golden、regression、handoff example 等样例；
- `archive/`：废止文档、废止 contracts、历史版本与迁移说明。

### [D1-R-025] 5.2 docs 目录规则

- 文件名统一使用 `D{编号}.md`；
- 每份文档必须有统一元数据头；
- 每份文档必须声明机器承接位置；
- 每份文档必须声明“不得改写”的上位事项；
- 不允许在 docs 内并存第二份同主题正式稿。

### [D1-R-026] 5.3 contracts 目录规则

- 每个目录至少有一个主 catalog；
- 每个 catalog 必须显式声明 `version`、`status`、`owner`、`source_docs`、`last_updated_at`；
- schema、enum、rule、gate、api、ui、governance、release、exception、sales、testing 必须可互相追溯；
- 不允许以页面常量、接口临时字段或测试内置字典替代 contracts 中的正式定义。

### [D1-R-027] 5.4 handoffs 目录规则

- handoff 目录只保存阶段交接合同，不保存业务实现逻辑；
- 每条 handoff 必须用统一命名：`stageX_to_stageY`；
- handoff example 必须与 contract 版本绑定；
- integration matrix 必须说明 producer、consumer、blockers、fallback path；
- handoff 失败只能产生阻断、降级或 review path，不允许静默丢字段。

### [D1-R-028] 5.5 control 目录规则

- control 目录只承接状态与责任，不承接领域语义；
- owner、task、approval、exception、roadmap 必须有统一 ID；
- 任何控制面占位符都属于一票失败项；
- 任何控制面变更都必须留下审计记录与生效时间。

---

## [D1-R-029] 6. 文档、contracts 与 handoff 的同步纪律

### [D1-R-030] 6.1 先文档、再契约、再样例、最后代码

当前执行策略固定为：

1. 先冻结文档语义；
2. 再冻结对应 contracts；
3. 再冻结 handoff、example 与 testing；
4. 最后才允许进入正式业务代码。

不允许采用“先把功能写出来，再回头补文档”的路径。

### [D1-R-031] 6.2 同步修改原则

任何结构性或语义性修改，必须在同一变更批次内同步修改：

- 对应 D 文档；
- 对应 contracts；
- 对应 handoff；
- 对应 testing；
- 对应 governance / release 资产；
- 对应 README / 状态板。

### [D1-R-032] 6.3 绝对禁止的不同步行为

以下行为一律禁止：

- 改了文档，不改 catalog；
- 改了 schema，不改 example；
- 改了 rule / gate，不改回归；
- 改了交付矩阵，不改字段策略；
- 改了触达边界，不改审批链与 quiet hours 规则；
- 改了页面 / 接口的消费方向，却不改 D4 / D5。

---

## [D1-R-033] 7. 命名、状态与版本规则

### [D1-R-034] 7.1 命名规则

- 正式对象统一使用 `snake_case`；
- 状态字段统一使用 `*_status`、`*_state`、`*_level`、`*_lane`、`*_bucket`；
- ID 字段统一使用 `*_id`；
- 时间字段统一使用 `*_at`、`*_from`、`*_until`、`*_due_at`；
- handoff ID 统一使用 `stageX_to_stageY`；
- 规则码统一使用 `TOPIC-XXX`；
- catalog 统一使用 `{topic}_catalog.json` 或 `{topic}_registry.json`。

### [D1-R-035] 7.2 文档与资产状态

正式状态只允许使用：

- `DRAFT`
- `EFFECTIVE`
- `SUPERSEDED`

不允许再造“试行正式版”“内部正式版”“半生效版”等平行状态。

### [D1-R-036] 7.3 版本规则

- 裁决 ID 只能追加，不允许重排；
- object / enum / rule / gate / handoff 版本必须可追溯；
- 任何会影响正式对象、正式枚举、边界层级、放行条件的修改，都必须提升版本并触发回归；
- 不允许以覆盖文件替代版本记录。

---

## [D1-R-037] 8. AI / Codex 执行纪律

### [D1-R-038] 8.1 开始任务前必须完成的动作

AI / Codex 在开始任何正式任务前，必须完成：

1. 搜索并确认唯一上位依据；
2. 定位任务所属阶段；
3. 定位任务消费的正式对象；
4. 定位任务输出的正式对象；
5. 定位对应能力层级与边界；
6. 确认对应 handoff 与 testing；
7. 确认是否涉及客户可见、对外表达、自然人高限制字段、触达、外发或 release；
8. 确认本次变更不会创造第二套主判断。

### [D1-R-039] 8.2 任务执行中一律不得做的事

AI / Codex 一律不得：

- 绕开 `project_fact` 重算主结论；
- 绕开 `rule_gate_decision` / `evidence_gate_decision` 升级正式结果；
- 绕开 D13 的 A/B/C/D 边界创造新能力层级；
- 绕开 D6 / D7 决定客户可见字段和外发对象；
- 绕开合规来源生成 `contact_target`；
- 把 D 层输入静默带入正式公开主链；
- 把截图、OCR 文本、模型摘要、销售备注、口头说明写成正式主证；
- 以“实现方便”“测试方便”“页面展示需要”为由改写 L0 已冻结语义；
- 在无 owner、无当前任务、无 handoff、无 testing 的情况下推进正式业务代码。

### [D1-R-040] 8.3 任务完成时必须输出的内容

每次正式任务结束时，执行代理必须给出：

1. 本次任务对应的上位依据；
2. 修改文件清单；
3. 新增或变更的对象 / 枚举 / 规则 / gate / handoff / testing / governance 资产；
4. 未修改但受影响的资产清单；
5. 风险与未解问题；
6. 对应回归是否已补齐；
7. 是否触发下一任务。

仅输出“已完成开发”或“文档已更新”视为不合格交付。

---

## [D1-R-041] 9. 任务拆分、粒度与允许产物

### [D1-R-042] 9.1 任务类型

正式任务只允许分为以下类型：

1. **文档冻结任务**：修改 `docs/`、`README`、裁决索引面；
2. **contracts 冻结任务**：修改 `contracts/` 与对应 docs；
3. **handoff 冻结任务**：修改 `handoff/`、example 与 validation；
4. **testing / governance 冻结任务**：修改 `contracts/testing/`、`contracts/governance/`、`contracts/release/`、scripts；
5. **控制面任务**：修改 `control/`、doctor / lint / drift check；
6. **正式业务代码任务**：仅在开工门槛满足后才允许创建。

### [D1-R-043] 9.2 当前阶段允许产物

在正式业务代码开工前，只允许新增或修改以下资产：

- D 文档；
- contracts；
- handoff 合同与样例；
- golden / regression / governance / release 检查；
- owner / task / approval / exception 控制面；
- 校验、发布前检查、漂移检查脚本。

### [D1-R-044] 9.3 当前阶段禁止产物

在正式业务代码开工前，一律禁止：

- 业务 API 实现；
- Worker / pipeline 实现；
- 页面业务逻辑；
- 自动触达实现；
- 订单、支付、交付运行逻辑；
- 把 contracts 当作运行时业务逻辑直接消费的实现代码；
- 任何依赖未冻结文档、未冻结 handoff、未冻结 testing 的正式主链代码。

---

## [D1-R-045] 10. 阶段 handoff 与集成矩阵纪律

### [D1-R-046] 10.1 handoff 是正式资产，不是备注

 的核心不是静态对象，而是九阶段主链如何有序交接。任何阶段间 handoff 都必须作为正式资产冻结，不允许依赖页面备注、脚本拼接、临时字段、测试假设或人工经验完成阶段交接。

### [D1-R-047] 10.2 每条 handoff 的最小结构

每条 handoff 至少必须包含：

- handoff ID；
- producer stage；
- consumer stage；
- input object families；
- output object families；
- required fields；
- optional fields；
- blockers；
- downgrade paths；
- error codes；
- example payloads；
- consumer obligations；
- linked tests。

### [D1-R-048] 10.3 阶段失败与阻断规则

- producer 未满足最小退出条件时，不得向下游声明 handoff 成立；
- handoff 校验失败时，下游不得自补主字段继续执行；
- handoff 降级后，只允许进入 review / observation / restricted path，不得伪装成正式主链成功；
- 多版本、多时钟、项目归一未解时，不得通过 handoff 静默抹平冲突；
- 阶段 6 之前的失败，不得由阶段 7-9 用商业对象重算掩盖。

---

## [D1-R-049] 11. 评审、回归与发布前检查

### [D1-R-050] 11.1 评审分级

- **编辑性变更**：只改表达，不改语义；
- **语义性变更**：限定语、边界、口径、说明改变；
- **结构性变更**：对象、阶段承接、门禁、放行链、外发边界改变；
- **发布影响变更**：会影响客户可见范围、外发、触达、订单交付、coverage、release gates 的变更。

### [D1-R-051] 11.2 回归触发原则

以下任一变更必须触发对应回归：

- 正式对象或正式枚举变化；
- rule / gate / evidence grade 变化；
- A/B/C/D 能力层级变化；
- page / api 消费优先级变化；
- 字段策略或交付矩阵变化；
- 触达渠道、频控、quiet hours、lawful basis 变化；
- handoff 结构变化；
- 例外或补证释放边界变化。

### [D1-R-052] 11.3 正式检查面

在进入正式业务代码开发前，必须至少通过以下检查面：

1. 仓库搜索与双口径检查；
2. contracts 结构校验；
3. handoff 校验；
4. golden / regression 校验；
5. governance contracts 校验；
6. release checks；
7. control 面完整性检查；
8. 漂移与死链接检查。

### [D1-R-053] 11.4 命令入口要求

正式校验入口必须同时提供：

- 统一入口命令；
- 直接脚本入口命令；
- 失败即返回非零状态码；
- 可用于 CI 或本地执行；
- 明确的失败分类与下一步处理建议。

---

## [D1-R-054] 12. 受控例外与回收机制

### [D1-R-055] 12.1 允许例外的场景

只有以下场景允许申请受控例外：

- 紧急止损；
- 合规阻断处置；
- 线上高风险错误隔离；
- 有明确时限的兼容过渡；
- 法定窗口期内的最小应急响应。

### [D1-R-056] 12.2 例外的强制字段

每条例外必须至少具备：

- `exception_id`
- `reason`
- `scope`
- `effective_from`
- `effective_until`
- `rollback_plan`
- `approver`
- `audit_ref`
- `affected_assets`
- `exception_state`

### [D1-R-057] 12.3 例外的硬限制

受控例外只允许：

- 降级；
- 暂停；
- 限制；
- 延后；
- 受限放行。

受控例外一律不得：

- 把 D 层输入提升为正式公开依据；
- 绕开项目归一、多版本 / 多时钟、双闸门、coverage、delivery 与 release gates；
- 静默永久化；
- 只写在口头说明、热修脚本或页面隐藏开关中。

---

## [D1-R-058] 13. 正式业务代码开工门槛

### [D1-R-059] 13.1 Go / No-Go 总门槛

只有当以下条件全部满足时，才允许开始正式业务代码开发：

1. 上位母版、裁决索引面、README / 状态板已统一；
2. D1-D14 已全部成文；
3. contracts 全套已齐；
4. handoff 全套已齐；
5. testing / governance / release 资产已齐；
6. control 面已齐；
7. 无并行母版、无第二套对象口径、无第二套能力边界、无第二套主判断；
8. 无占位 owner、占位 task、空 catalog、空 handoff、失效链接与无审计例外；
9. D 层渗透风险、客户可见字段越界风险、自然人高限制触达越界风险均已被治理资产覆盖；
10. 已完成正式开工评审与签字。

### [D1-R-060] 13.2 一票否决项

以下任一项存在时，正式业务代码一律不得开工：

- 缺 D8、D9、D10、D12、D14 任一正式文档；
- 缺 `contracts/sales/` 或等价商业对象契约承接层；
- 缺 `stage1->6` 正式 handoff；
- 测试仅覆盖治理目录，未覆盖主链 handoff、双闸门与统一事实；
- `owners`、`current_task` 仍为 seed / placeholder；
- 仍存在双母版、双 D13、双对象口径或死链接；
- 仍存在“文档已改、contracts 未改、testing 未改”的不同步状态；
- 仍需要靠聊天记录、口头说明解释关键正式语义。

### [D1-R-061] 13.3 开工后的执行约束

正式业务代码开工后，仍必须遵守：

- 不得反向改写文档体系；
- 不得跳过 contracts / handoff / testing；
- 不得绕开 `project_fact`、gate objects、field policy、delivery matrix、release gates；
- 不得把受限能力、保留态能力、演示态能力包装成正式完成能力。

---

## [D1-R-062] 14. 完成定义（Definition of Done）

一个正式任务只有同时满足以下条件，才算完成：

1. 上位依据明确；
2. 归属文档明确；
3. 对应 contracts 已同步；
4. 对应 handoff 已同步；
5. 对应 testing 已同步；
6. 对应 governance / release 资产已同步；
7. 控制面状态已更新；
8. 不引入第二套主判断；
9. 不扩大公开边界；
10. 不引入 D 层渗透；
11. 回归已通过；
12. 变更记录可审计。

只满足其中部分条件的任务，一律只能标记为“部分完成”，不得宣称已完成。

---

## [D1-R-063] 15. 附录 A：开工前资产包总表

| 资产包 | 必须项 | 通过标准 |
|---|---|---|
| 上位包 | L0、裁决总表、README | 单一母版、单一裁决面、单一状态板 |
| 文档包 | D1-D14 | 每份文档职责唯一、无抢定义权 |
| contracts 包 | schemas / enums / rules / gates / api / ui / governance / release / exceptions / sales / testing | 每份文档都有唯一机器承接目录 |
| handoff 包 | stage1->2、2->3、3->4、4->5、5->6、6->7、7->8、8->9 | 每条 handoff 都有 schema、example、校验与阻断规则 |
| testing 包 | assertions、golden、regression、governance、release、handoff validation | 失败可直接阻断开工或发布 |
| governance 包 | field policy、coverage、public boundary、delivery matrix、release gates、approval chain、exception policy | 客户可见与对外边界可被脚本化阻断 |
| control 包 | owners、current task、roadmap、approval、exception、doctor、lint、drift check | 真实 owner、真实任务、真实状态、真实检查 |

## [D1-R-064] 16. 附录 B：单任务卡片模板

### [D1-R-065] 16.1 任务头

- 任务 ID：
- 所属批次：
- 所属阶段：
- 任务类型：文档 / contracts / handoff / testing / governance / control / code
- 上位依据：
- 目标资产：

### [D1-R-066] 16.2 必填判断

- 本次任务是否引入新对象：
- 本次任务是否引入新枚举：
- 本次任务是否影响 gate / release：
- 本次任务是否影响客户可见边界：
- 本次任务是否影响触达或自然人字段：
- 本次任务是否需要更新回归：
- 本次任务是否需要更新 control 面：

### [D1-R-067] 16.3 交付要求

- 修改文档：
- 修改 contracts：
- 修改 handoff：
- 修改 testing：
- 修改 governance：
- 修改 control：
- 风险说明：
- 下一任务：

## [D1-R-068] 17. 附录 C：禁止事项总表

在当前执行策略下，一律禁止：

- 平行重造第二套对象体系；
- 平行重造第二套能力边界；
- 平行重造第二套页面主判断；
- 在 D1-D14 未齐时宣称“全套准备完成”；
- 在 contracts / handoff / testing 未齐时进入正式业务代码；
- 用页面常量、接口临时字段、测试字典替代正式 contracts；
- 用聊天记录、口头说明、PR 备注替代正式语义；
- 用例外机制长期绕开治理门禁；
- 把受限能力、保留态能力、演示态能力、内部预览态能力写成对外正式完成态；
- 把 D 层或灰色来源包装成正式公开能力。

## [D1-R-069] 18. 附录 D：内部线索运营平台定位补表

本补表用于同步“内部线索运营平台”定位，不改写正文既有规则。

### D1-R-069-A 当前允许动作补充

- 文档修订；
- contracts / handoff / control 补齐；
- 全仓骨架；
- 最小实现设计；
- 受控实现；
- 线索包生成链路内测。

### D1-R-069-B 当前禁止动作补充

- 对外软件正式发布；
- 无门禁触达；
- 无审计外发线索包；
- 无实测宣称阶段 7-9 封板完成。

### D1-R-069-C 必须遵守的定位限制

- AI 不得把“内部可用”误写成“对外正式软件能力”；  
- AI 不得按多租户 SaaS 假设新增结构或能力口径。

---

## [D1-R-070] 19. 附录 E：自动化开发动作门禁与停机规则补表（新增）

本补表用于冻结自动化开发的动作级门禁、停机条件与任务包粒度，不改写正文既有执行顺序与边界裁决。

### D1-R-070-A 动作等级与允许方式

| action_class | 允许方式 | 适用范围 |
|---|---|---|
| `DIRECT_EDIT` | 直接改文件 | 文档补表（仅附录/补表）、control 资产 |
| `DRAFT_ONLY` | 仅草案/补丁 | contracts / handoff / testing / governance 机器资产 |
| `MANUAL_APPROVAL_REQUIRED` | 必须人工确认 | scripts 修改、`src/*`/`tests/*` 变更 |
| `BLOCKED` | 禁止自动推进 | 外部 release、真实触达/支付/交付、高限制字段外发 |

### D1-R-070-B 自动停机条件

| 触发条件 | 级别 | 动作 |
|---|---|---|
| `validate-contracts.ps1` / `run-governance-contracts.ps1` / `run-golden.ps1` / `check-release.ps1` 失败 | P0 | 立即停机转人工 |
| 触及支付/交付/触达执行 | P0 | 立即停机转人工 |
| 触及高限制字段外发 | P0 | 立即停机转人工 |
| external-facing changes | P0 | 立即停机转人工 |
| 同一脚本连续失败 >= 2 次 | P0 | 立即停机转人工 |

### D1-R-070-C 任务包范围规则

| 规则 | 要求 |
|---|---|
| 单批次主题 | 仅允许单一阶段或单一主题 |
| 路径范围 | 必须显式声明 `declared_changed_paths` / `allowed_modification_paths` / `forbidden_modification_paths` |
| contracts 变更 | 必须先同步 D 文档，并以草案/补丁形式输出 |

- 不再设置统一 `<=10` 文件这类仓库级硬上限；
- 是否拆包，主要由单主题要求、路径范围、review gate 与 stop conditions 共同决定。

### D1-R-070-D 机器承接位置

- 门禁表：`docs/自动化开发动作门禁表.md`  
- 行为矩阵：`control/automation_action_matrix.yaml`  
- 停机条件：`control/automation_stop_conditions.yaml`  
- 任务包规则：`control/automation_task_packet_rules.yaml`
- review gate matrix：`control/review_gate_matrix.yaml`
- handoff 依赖顺序：`handoff/dependency_order_matrix.json`
- 自动化检查脚本：`scripts/check-task-packet.ps1`、`scripts/check-handoff-dependencies.ps1`

### D1-R-070-E change class / review gate 冻结补表

| change_class | 正式含义 | 最低要求 |
|---|---|---|
| `LOW_RISK_DIRECT` | 低风险文档/控制面同步 | 可 direct edit，但仍需 task packet |
| `DRAFT_WITH_REVIEW` | 中风险 machine asset / scripts / tests 变更 | 可出 draft/patch；必须 human review |
| `MANDATORY_HUMAN_REVIEW` | 高风险 shared runtime / governance / release / Stage 8/9 / automation control 变更 | 必须 human review + owner signoff |
| `STOP_AND_ESCALATE` | 审批链/例外语义或其他必须停机的变更 | 自动化不得继续，立即转人工 |

### D1-R-070-F task packet 硬字段补表

| 字段 | 要求 |
|---|---|
| `objective` / `non_goals` | 明确任务目标与非目标 |
| `affected_stages` | 声明涉及阶段或跨阶段门禁面 |
| `declared_changed_paths` | 声明本批触及文件 |
| `allowed_modification_paths` / `forbidden_modification_paths` | 明确允许/禁止修改范围 |
| `impacted_assets` | 声明受影响 docs / control / contracts / scripts / tests |
| `required_scripts` / `stop_conditions` | 明确必跑脚本与停机条件 |
| `definition_of_done` / `deliverables` | 明确完成标准与产物清单 |
| `risk_level` / `change_class` / `change_domains` | 明确风险级别、change class 与命中域 |
| `human_review_required` / `owner_reviews_required` / `review_evidence` | 明确 human review 与 owner review 要求 |

### D1-R-070-G readiness / release 失败条件补表

| 失败条件 | 正式处理 |
|---|---|
| 缺 task packet 或关键字段缺失 | `check-automation-readiness` 失败 |
| declared `change_class` 低于 review gate matrix 计算结果 | `check-automation-readiness` / `check-release` 失败 |
| `MANDATORY_HUMAN_REVIEW` 缺 human review 或缺 required owner review | `check-automation-readiness` / `check-release` 失败 |
| 命中 `STOP_AND_ESCALATE` | 自动化停机转人工 |
| review gate 断言未进入 regression / release checklist | `check-release` 失败 |

### D1-R-070-H 受控路线图导航补表

| 项 | 要求 |
|---|---|
| 路线图角色 | `AX9S_开发执行路由图.md` 只负责执行导航，不得成为新的状态源或裁决源 |
| 状态源 | phase/readiness 以 `control/current_task.yaml`、`control/repo_status.md`、`control/milestone_status.yaml`、`文档与资产状态板.md` 为准 |
| 条件开工 | `正式业务代码开发开工裁决页.md` 只负责 `READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT` 的 conditional-go |
| 推进方式 | 任何路线图片段推进都必须先形成 `task packet`，再按 `change_class / review_gate / stop conditions` 执行 |
| 高风险段 | 触及 shared runtime / governance / release / Stage 8-9 高风险执行 / automation control 的路线图片段，最低 `MANDATORY_HUMAN_REVIEW` |
| blocked 红线 | external release、Stage 8 real execution、Stage 9 real payment-delivery、高限制字段放行，不得因路线图恢复而放宽 |

## [D1-R-071] 附：PTL-I100-OPEN-CAPABILITY-BASELINE 能力开放基线补表

本补表只同步执行口径，不改写 D1 正文既有任务包、review gate 或停机规则。

| 项 | D1 承接口径 |
|---|---|
| policy ref | `control/product_task_library.yaml#open_capability_policy` / `PTL-I100-OPEN-CAPABILITY-BASELINE` |
| 执行包原则 | 除自动退款执行和禁止的非公开/灰色能力外，产品必需能力都可进入 dedicated current_task 分包逐级开发；不得绕过当前 active packet。 |
| `blocked-by-default` | 表示 provider config、sandbox、approval、audit、operator action、field allowlist/masking、dedicated current_task 和验收未满足前不能 live，不表示永久不做。 |
| 三层验收 | 每个能力必须同时通过 engineering regression、capability state、product closure；最终闭环门为 `PTL-I100-118-full-product-operational-acceptance`。 |
| 自动退款边界 | 自动退款执行 excluded；退款只保留 `manual exception` / 人工异常记录、manual approval/audit 和 governed review。 |









## [D1-R-072] 附：PTL-I100-143E 自动运营与 source strategy 执行补表

本补表用于把最近升级的能力版图写入 Codex / AI 执行口径；不改写 D1 正文，只追加执行约束。

### D1-R-072-A 当前开发主线

Codex 后续不得把系统理解成“人工选 URL 后跑一条链”。当前主线必须表达为：

1. 系统先做市场扫描和机会发现；
2. 系统自动选择 source blueprint 和公开源组合；
3. Stage2 只抓公开可查、allowlisted、可审计来源；
4. Stage3/4/5 形成可回放的候选字段、公开核验和规则证据；
5. Stage6 判断异议价值、证据强度、泄露风险和商业钩子资格；
6. Stage7 判断真实买家、购买动机、购买能力、报价和销售优先级；
7. Stage8/9 只能在审批、审计、provider config、operator action 和验收后进入受控执行 readback。

### D1-R-072-B source strategy 执行约束

| 项 | 执行要求 |
|---|---|
| 全国聚合平台 | 只能作为一级发现、去重和补充查询面；不得当作全量实时源。 |
| 北京 | 仅可作为技术回归和页面可达性样本；不得作为首批商业试点、销售话术样本或客户可见案例。 |
| 首批省级试点 | 四川、江苏、浙江、山东、广东、湖北。 |
| 城市适配 | 仅当省级平台存在详情/附件缺失、更新滞后、监管投诉/备案证据在城市站、高价值项目仅城市/代理/招标人站可见，或省级 portal 为 SPA/弱正文时触发。 |
| 禁止方式 | 禁止一次性铺全国城市，禁止手工 URL 选择作为主流程，禁止用政治或不可核验判断作为 source strategy reason。 |

### D1-R-072-C Codex 停机条件

若任务需要把北京改成首批商业试点、把全国聚合写成全量实时、引入任意 crawler / 登录 / 验证码 / 反爬绕过、或把 LLM 输出当事实/法律结论/客户结论，必须停机汇报。
