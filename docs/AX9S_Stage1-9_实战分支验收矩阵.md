# AX9S Stage1-9 实战分支验收矩阵

**版本**: 2026-05-01 v1

**定位**
- 本文件是 `docs/AX9S_实战运行图纸与验收契约.md` 的 L2/L3 操作级矩阵。
- 本文件用于逐阶段验证、验收和修复，不用于替代 `docs/L0.md`、D2-D14、`handoff/stage_handoff_catalog.json`、`control/product_runtime_architecture_map.yaml`。
- 后续修复必须按本矩阵逐条落地；如果矩阵与真实页面、代码、法规边界冲突，先修正矩阵，再修代码。

## 0. 可信等级和实现状态

### 0.1 可信等级

| 等级 | 含义 | 能否直接作为代码硬规则 |
| --- | --- | --- |
| `AUTHORITY` | L0/D 文档、handoff、contract 明确要求 | 可以 |
| `CODE_CONFIRMED` | 当前代码已存在对应入口或逻辑 | 可以，但要验证行为 |
| `REPO_RECORDED_PAGE_OBSERVATION` | 仓库资产记录过浏览器/运行时观察 | 只能作为已有观察，需复测 |
| `USER_FIELD_EXPERIENCE` | owner 实战经验 | 不能直接写死，先转成待验证规则 |
| `PRODUCT_HYPOTHESIS` | 产品上合理但未被真实页面/代码证明 | 不能直接写死 |
| `TO_VERIFY` | 待真实页面、样本或代码验证 | 不能作为 PASS 条件 |

### 0.2 实现状态

| 状态 | 含义 |
| --- | --- |
| `IMPLEMENTED` | 当前代码已实现并有测试或运行读回 |
| `PARTIAL` | 有基础对象/入口，但链路不完整 |
| `MISSING` | 未实现 |
| `NEEDS_REAL_PAGE_VERIFY` | 需要用真实页面验证搜索、翻页、字段和失败形态 |
| `NEEDS_TEST` | 需要补测试 |

## 1. Stage1 市场扫描与来源蓝图

| 分支 | 具体动作 | 关键字段/对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 | 代码入口 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 输入归一 | 地区多选、项目类型多选、金额区间、关键词、时间窗口归一 | `region_codes`, `project_types`, `amount_min/max`, `now` | 支持多地区多类型批量运行 | 输入缺失进入默认或 review，不得静默造样本 | `IMPLEMENTED` | `CODE_CONFIRMED` | `operator_customer_access.py::run_operator_autonomous_opportunity_search` |
| 来源蓝图 | 按地区/类型/金额选择省级平台、全国聚合、核验源、信用源、地方住建源 | source blueprint, capture plan | 明确为什么选或跳过每个来源 | 全国聚合不得被当成全量实时源 | `PARTIAL` | `AUTHORITY` | `stage1_tasking/source_blueprint.py` |
| 真实候选发现 | 从真实公开列表页/API 获取候选 | `notice_candidates`, source URL, profile id | 候选可链接、可审计、有来源 profile；金额、项目类型、发布时间只打复核标签，不在发现阶段源头删除 | 无候选返回 `NO_CANDIDATES`，不得合成机会；导航、模板、废标/终止等明确无效链接可剔除 | `PARTIAL` | `CODE_CONFIRMED` | `RealPublicCandidateDiscoveryService` |
| 候选批量分流 | 对所有候选按地区、类型、金额、公告阶段、时间窗口评分并分流 | selected/skipped/review candidates | 通过者批量入后续链路；真实公开候选遇到金额/窗口/类型不确定或不匹配时进入 REVIEW，不直接源头丢弃 | 不能固定挑 1 个迎合结果；只有明确非项目公告、重复、废标/终止才可跳过 | `PARTIAL` | `CODE_CONFIRMED` | `Stage1MarketScanEngine` |
| 试点地区覆盖 | SC/JS/ZJ/SD/GD/HB 本地 profile 分别运行 | region adapter, profile id | 每省显示真实实现状态 | SD/HB 不得显示为与 GD/JS/ZJ/SC 同等可跑 | `PARTIAL` | `CODE_CONFIRMED` | `region_adapters.py` |
| 运行持久化 | 保存搜索条件、候选、选择、失败原因 | search run record | 刷新后可读回 | 页面内存丢失不得作为正式记录 | `PARTIAL` | `CODE_CONFIRMED` | `OperatorActionRepository` |

**Stage1 下一步修复优先级**
- 补 SD/HB 候选发现器。
- 对每个地区运行返回结构做真实样本测试。
- 搜索结果状态拆成候选已进料、需复核、受限可售、正式可售、客户交付就绪。

## 2. Stage2 公开采集、快照和时钟版本

| 分支 | 具体动作 | 关键字段/对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 | 代码入口 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 列表入口抓取 | 访问省级列表页或公开接口，保存入口快照/运行记录 | entry snapshot, source profile | 入口公开可访问，可回放 | SPA 壳、验证码、412/521、限流进入 fail-closed/readback | `PARTIAL` | `CODE_CONFIRMED` | `real_public_url_fetcher.py` |
| 详情页抓取 | 对候选详情 URL 抓取 HTML/API detail | detail snapshot id | 详情快照与候选一一对应 | 详情无法抓取不得伪造成已解析正文 | `PARTIAL` | `CODE_CONFIRMED` | `RealCandidateStage2CaptureService` |
| 附件抓取 | 发现并抓取 PDF/DOC/XLS/ZIP 等公告附件 | attachment snapshot ids | 附件原文可回放、有 hash/来源 | 附件缺失进入 review，不得用截图替代 | `PARTIAL` | `CODE_CONFIRMED` | `fetch_attachment_original_link` |
| 时钟链 | 区分公告发布日期、发布时间、投标截止、异议截止、质疑截止、开标时间 | `clock_chain_profile`, deadline fields | 每个时间字段有标签来源和优先级 | 无明确截止标签只能 unknown/review | `PARTIAL` | `AUTHORITY` | `real_candidate_capture.py` |
| 版本链 | 识别变更、补遗、澄清、中标候选、中标结果、合同公告 | `notice_version_chain` | 有版本优先级和当前有效版本 | 版本冲突进入 review | `PARTIAL` | `AUTHORITY` | `Stage2Service` |
| challenge 处理 | 登录/验证码/风控/限流/SPA 壳分类 | challenge state | 自动化能力可作为目标；真实三方执行需授权和审计 | 不得把 challenge 当成功 | `PARTIAL` | `AUTHORITY` | `real_public_url_fetcher.py` |

**Stage2 严禁**
- 把公告发布日期或项目编号片段当异议截止。
- 把 SPA 壳、截图、OCR 摘要当正式原始载体。
- 抓不到附件时生成“附件已核验”结论。

## 3. Stage3 结构化解析和字段血缘

| 分支 | 具体动作 | 关键字段/对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 | 代码入口 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 项目基础解析 | 解析项目名、地区、类型、金额、公告阶段、采购/招标方式 | `project_base` | 字段有 source slice | 关键字段缺失进入 parser review | `PARTIAL` | `CODE_CONFIRMED` | `Stage3Service`, real parser |
| 候选/中标单位解析 | 解析第一候选、第二候选、排序、报价 | `bidder_candidate` | 候选集完整或明确不完整 | 只拿第一名但未说明候选集状态不得 PASS | `PARTIAL` | `AUTHORITY` | `Stage3Service` |
| 项目经理解析 | 解析姓名、注册专业、等级、单位、证书号/公开 ID、来源切片 | `project_manager` | 至少姓名 + 单位/证书/专业之一进入后续消歧 | 只有姓名也可进入 review，但不能 PASS | `PARTIAL` | `AUTHORITY` | `Stage3Service` |
| 字段血缘 | 每个字段保留 source file、slice、hash、locator、confidence | `field_lineage_record` | 可回到原始页面/附件 | 无血缘不得进入外部证据 | `PARTIAL` | `AUTHORITY` | `contracts/schemas/field_lineage_record.schema.json` |
| 解析置信度 | 低置信度、冲突字段、同名字段进入 review | confidence, parse warnings | 低置信不会升级事实 | 解析冲突不允许静默消解 | `PARTIAL` | `AUTHORITY` | real parser |
| 模型辅助 | LLM 只可辅助抽取/摘要，不做事实裁决 | model governance | 进入正式链路需 `model_governance_record` | 无治理记录不得入正式对象 | `PARTIAL` | `AUTHORITY` | D14 |

## 4. Stage4 公开核验策略和执行

Stage4/5 的更细操作规程见：`docs/AX9S_Stage4-5_核验与双闸门操作规程.md`。后续实现 Stage4/5 分支时，以该文件的核验单元、双闸门输出标准和 L4 测试验收表为直接执行面；若真实页面验证与该文件冲突，先修该文件，再修代码。

| 分支 | 具体动作 | 公开源/入口 | 关键字段/对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 | 代码入口 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 核验目标生成 | 从 Stage3 字段生成企业、人员、资质、信用、公告承诺链、许可、合同、竣工、项目经理变更、处罚风险目标 | 内部策略 | `verification_target_type`, `verification_chain_roles` | 目标、来源链角色和字段来源可回放 | 缺字段进入 strategy review | `PARTIAL` | `CODE_CONFIRMED` | `hard_defect_strategy.py` |
| 企业主体核验 | 先用候选/中标公司全称或统一信用代码查企业 | 四库一平台企业页、GSXT、地方住建 | `enterprise_public_record` | 企业主体匹配且来源公开 | 查不到不能说企业不存在，只能 review/换源 | `PARTIAL` | `AUTHORITY` | `PublicVerificationAdapter` |
| 企业资质核验 | 查资质类别、等级、有效期、证书状态 | 四库一平台、地方住建、公告附件 | `enterprise_qualification` | 资质满足招标要求且时间有效 | 资质字段缺失/过期/不匹配进入 review/block | `PARTIAL` | `AUTHORITY` | `hard_defect_strategy.py` |
| 项目经理企业内消歧 | 企业页进入注册人员/项目负责人列表，必要时翻页找姓名 | 四库企业人员列表、地方住建人员页 | `personnel_public_record` | 公司 + 姓名 + 证书/公开 ID/专业/等级匹配，且人员 carrier 必须 `MATCHED` / `review_required=false` / 有 URL 与 snapshot；企业内唯一匹配时派生证书编号给后续核验 | 只搜姓名、只看第一页、同名未消歧、注册单位冲突、缺快照或人员 carrier 为 REVIEW 不得 PASS | `PARTIAL` | `USER_FIELD_EXPERIENCE + CODE_CONFIRMED` | `active_conflict.py` 已生成企业优先 identity carrier；JZSC 渲染行 adapter 已覆盖匹配/同名 review/证书编号派生；JZSC 公司优先浏览器采集计划已固化；真实浏览器执行器待补 |
| 项目经理详情核验 | 打开人员详情，核对注册单位、证书号、专业、等级、注册状态、有效期 | 四库人员详情、地方住建人员详情 | personnel detail snapshot | 消除同名歧义并可回放 | 同名多、单位不符、证书不明进入 `AMBIGUOUS_PUBLIC_MATCH` | `PARTIAL` | `USER_FIELD_EXPERIENCE + CODE_CONFIRMED` | `manager_identity_resolution` 已禁止姓名泛搜作为最终证明；详情页抓取待补 |
| 注册时间/变更时间核验 | 比较注册时间、变更时间与投标截止、资格审查、中标候选公示时间 | 人员详情、变更记录、公告时钟链 | registration timeline | 时间覆盖关键节点 | 刚注册/晚于关键节点进入 Stage5 规则判断，不在 Stage4 下最终结论 | `PARTIAL` | `PRODUCT_HYPOTHESIS + CODE_CONFIRMED` | `registration_timeline_verification` 已进 Stage4 failure reasons；PM-001 requested rule binding 已补；真实页面字段待补 |
| 在建冲突核验 | 查该人员参与项目、企业项目、公告承诺、施工许可、合同、竣工/验收、项目经理变更状态 | 省市公共资源平台、地方住建施工许可/合同备案/竣工备案/项目经理变更公告、四库项目页 | `performance_public_record`, `construction_permit`, `contract_public_info`, `completion_filing`, `project_manager_change_notice` | 有项目和时间窗口可比较，项目记录绑定已消歧证书编号/人员公开 ID，且项目公开 carrier 为 `MATCHED` / 有 URL 与 snapshot；变更公告可切分责任窗口 | 无项目记录不等于无冲突；缺许可/合同/竣工/变更/快照或项目 carrier REVIEW 进入 review | `PARTIAL` | `CODE_CONFIRMED + AUTHORITY` | `active_conflict.py` 已消费冲突项目；JZSC 人员项目行 adapter 已生成项目/合同/竣工 carrier；多源链角色已进 strategy metadata；真实地方住建/变更发现器待补 |
| 信用处罚核验 | 查失信、处罚、经营异常、黑名单、质量安全处罚、投诉/监督决定 | 信用中国、中国执行信息公开网、GSXT、地方处罚公示 | `credit_penalty_blacklist`, `administrative_penalty_public_record`, `complaint_or_supervision_decision` | 公开记录可回放；处罚/投诉可形成风险线索和商业钩子 | 412/521/challenge fail-closed；主体不一致不得引用 | `PARTIAL` | `AUTHORITY` | `public_source_adapters.py` |
| 合同/许可/竣工/业绩核验 | 查施工许可、合同备案、竣工备案、消防/联合验收、业绩记录 | 地方住建、行政审批、四库项目、公共资源附件 | permit/contract/completion/performance carriers | 与项目、主体、人员身份和时间窗口匹配 | 缺页、主体不符、时间不明、无竣工释放证据进入 review | `PARTIAL` | `AUTHORITY` | `hard_defect_strategy.py` |
| 公开边界 | 只做公开核验，不做终局违法结论 | 所有公开源 | public boundary | `public_only=true`, `no_legal_conclusion=true` | 非公开/不可回放不得入正式链 | `IMPLEMENTED` | `CODE_CONFIRMED` | `verification.py` |

**Stage4 关键禁令**
- 不得只搜项目经理姓名后，因为同名太多就判定失败、无冲突或公司没有该项目经理。
- 不得只看企业人员第一页。
- 不得把搜索结果标题匹配当成正式人员核验。
- 不得把查不到记录当成负面事实；只能 review、换源、补证。
- 不得在 Stage4 下最终违法或可售结论，只能输出核验 carrier。

## 5. Stage5 规则证据双闸门

| 分支 | 规则意图 | 输入证据 | rule gate | evidence gate | REVIEW/BLOCK | 当前状态 | 可信等级 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 项目经理在建冲突 | 同一项目经理时间窗口冲突 | 人员详情、项目记录、合同/竣工、当前项目时钟 | 时间窗口重叠且身份消歧充分才命中 | 原始公开页、字段血缘、快照齐全 | 同名/时间/验收缺失 review | `PARTIAL` | `AUTHORITY` |
| 项目经理变更释放 | 公开变更是否切分责任窗口 | 项目经理变更公告、施工许可变更、原/新项目经理证书号 | 变更链公开、字段完整且与项目匹配才切分窗口 | 原始变更公示/许可变更可回放 | 缺证书/日期/项目匹配 review；不得假设释放 | `MISSING_RUNTIME` | `AUTHORITY + USER_FIELD_EXPERIENCE` |
| 注册时间异常 | 注册/变更时间晚于投标或资格关键节点 | 人员注册时间、变更时间、投标截止、资格审查时间 | 满足规则才命中 | 人员页和公告时钟均可回放 | 时间字段不明 review | `PARTIAL` | `PRODUCT_HYPOTHESIS + CODE_CONFIRMED` |
| 资质不匹配 | 企业资质类别/等级/有效期不满足公告 | 资质页、公告资质条款、字段血缘 | 不匹配才命中 | 资质和公告条款均有原始载体 | 条款解析不明 review | `PARTIAL` | `AUTHORITY` |
| 信用处罚/黑名单 | 主体存在失信、处罚、经营异常等 | 信用中国/执行信息/GSXT | 命中具体记录才命中 | 记录页可回放 | 站点阻断 fail-closed/review | `PARTIAL` | `AUTHORITY` |
| 业绩/履约异常 | 业绩、施工许可、合同、竣工、履约与要求不符 | 公共资源公告链、地方住建/行政审批、四库/附件 | 不符或缺关键证明才命中 | 证据链可回放 | 缺公开载体或无竣工释放链 review | `PARTIAL` | `AUTHORITY` |
| 程序时钟异常 | 公告、答疑、投标、异议等时钟冲突 | clock/version chain | 时钟冲突才命中 | 时钟字段有来源和标签 | 只凭自由文本不得 PASS | `PARTIAL` | `AUTHORITY` |
| 双门联动 | 规则门和证据门同时判断 | Stage4 carriers + Stage3 lineage | 规则明确 | 证据足够 | 任一 REVIEW/BLOCK 不得升级 | `IMPLEMENTED/PARTIAL` | `AUTHORITY` |

**Stage5 验收底线**
- `rule_gate_decision` 和 `evidence_gate_decision` 缺一不可。
- 证据不足不能靠规则强行 PASS。
- 规则不明确不能靠证据堆叠强行 PASS。
- REVIEW 仍可产生商业线索，但不得生成正式客户结论。

## 6. Stage6 统一事实、复核和报告

| 分支 | 具体动作 | 正式对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 | 代码入口 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 统一事实聚合 | 消费 Stage5 双门、review、证据等级，形成唯一事实中心 | `project_fact` | 下游只消费 `project_fact` | 缺双门或硬阻断不得成正式事实 | `PARTIAL` | `AUTHORITY` | `Stage6Service` |
| 复核队列 | 对证据不足、冲突、边界不清生成复核项 | `review_queue_profile` | review 原因明确 | review 不得被 UI 当成功 | `PARTIAL` | `CODE_CONFIRMED` | `Stage6Service` |
| 动作建议 | 形成 legal/action 类建议但不做终局法律结论 | `legal_action_recommendation` | 来源于 project_fact | 不得单独从规则生成 | `PARTIAL` | `AUTHORITY` | `Stage6Service` |
| 正式报告 | 形成内部报告和交付候选基础 | `report_record` | report status、release level 明确 | 未过 release 不得客户交付 | `PARTIAL` | `AUTHORITY` | `Stage6Service` |
| 真实竞争者基础 | 形成 challenger candidate | `challenger_candidate_profile` | 有受损关系、行动收益、窗口、主体动机 | 缺任一只能 review/候选 | `PARTIAL` | `AUTHORITY` | `Stage6Service` |
| real_public readback | 检查 Stage4 refs、公开边界、双门、product package | stage6 readback summary | `INTERNAL_READY` 才进 Stage7 real_public | 缺 Stage4 refs/双门 review | `IMPLEMENTED` | `CODE_CONFIRMED` | `run_real_public_rule_evidence_readback` |

## 7. Stage7 可售机会、买家适配和商业钩子

| 分支 | 具体动作 | 正式对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 |
| --- | --- | --- | --- | --- | --- | --- |
| 竞争者集合 | 从 Stage6 challenger 形成竞争者集合和 winner trace | `multi_competitor_collection` | winner 可回指 selection trace | 自由选择 challenger 不得 PASS | `PARTIAL` | `AUTHORITY` |
| 双 actor 拆分 | 区分法律行动主体和采购/决策主体 | `legal_action_actor_profile`, `procurement_decision_actor_profile` | 两者来源和差异明确 | 未拆分只能受限销售承接 | `PARTIAL` | `AUTHORITY` |
| 买家适配 | 计算买家动机、支付能力、窗口紧迫、行动能力 | `buyer_fit`, `challenger_buyer_fit` | 来源于 Stage6 formal fields | 自由打分不得 PASS | `PARTIAL` | `AUTHORITY` |
| 报价和交付形态 | 生成 offer、报价区间、交付形式 | `offer_recommendation` | 与证据强度、价值、成本对应 | 报价不能固定 1200/1800 万拟合 | `PARTIAL` | `PRODUCT_HYPOTHESIS` |
| 商业钩子 | 生成卖前可讲、不可讲、withheld fields | commercial hook/readiness | 不泄露完整证据链 | 泄露 source URL/full path/raw snapshot 不得过 | `PARTIAL` | `AUTHORITY` |
| 可售机会 | 形成受限/正式 `saleable_opportunity` | `saleable_opportunity` | 来自 project_fact + challenger + buyer fit + offer | 缺 Stage6 formal 不得生成正式机会 | `PARTIAL` | `AUTHORITY` |
| real_public readback | 检查 Stage6 ready、leadpack、commercial hook、真实竞争者状态 | stage7 readback summary | 可进入内部销售准备 | 缺任一 review | `IMPLEMENTED` | `CODE_CONFIRMED` |

## 8. Stage8 联系对象和触达计划

| 分支 | 具体动作 | 正式对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 |
| --- | --- | --- | --- | --- | --- | --- |
| 联系候选来源 | 从公开官网、授权信息、合规 CRM 得到联系人候选 | `contact_candidate_collection` | 来源可审计、role 清楚 | 非公开/非法采集/无审计 block | `PARTIAL` | `AUTHORITY` |
| 联系人合并消歧 | 合并官方电话、邮箱、部门、职位，处理冲突 | `contact_selection_trace` | 有 winner 和选择理由 | 无 trace 不得生成正式 contact_target | `PARTIAL` | `AUTHORITY` |
| 正式联系对象 | 形成最终联系目标 | `contact_target` | 消费 collection/trace 和 saleable opportunity | 不得直接吃散输入 | `PARTIAL` | `AUTHORITY` |
| 触达计划 | 生成渠道、频率、quiet hours、opt-out、模板 | `outreach_plan` | 审批/审计/provider 状态明确 | 真实触达缺审批 block | `PARTIAL` | `AUTHORITY` |
| 触达记录 | 保存预览、dry-run、审批状态或真实触达结果 | `touch_record` | 不伪装 live execution | provider 未放行不得真实发送 | `PARTIAL` | `AUTHORITY` |
| real_public readback | 证明没有真实 provider/send 执行，且可读回 | stage8 readback summary | 内部可观察 | 真实外发需另行放行 | `IMPLEMENTED` | `CODE_CONFIRMED` |

## 9. Stage9 订单、支付、交付和治理反馈

| 分支 | 具体动作 | 正式对象 | PASS | REVIEW/BLOCK | 当前状态 | 可信等级 |
| --- | --- | --- | --- | --- | --- | --- |
| 订单记录 | 由 Stage8 touch outcome 和机会状态生成订单候选 | `order_record` | 关联 opportunity/touch | 不得从 raw note 造订单 | `PARTIAL` | `AUTHORITY` |
| 支付记录 | 支付意向、收款、异常、退款状态 | `payment_record` | provider/sandbox/审批状态明确 | 自动退款执行 excluded | `PARTIAL` | `AUTHORITY` |
| 证据包交付 | 按 D6/D7 字段策略、水印、版本、release checklist 交付 | `delivery_record` | 字段 allowlist、watermark、audit 完整 | 内部预览不得客户交付 | `PARTIAL` | `AUTHORITY` |
| 下载审计 | 记录下载、访问控制、版本 hash | delivery/audit refs | 可追溯 | 无账号/审批不得真实客户下载 | `PARTIAL` | `AUTHORITY` |
| 结果回写 | 成交、拒绝、补证、退款、复购等治理反馈 | `opportunity_outcome_event`, `governance_feedback_event` | 回写不重算上游事实，只触发复核/再评分 | 不得绕过正式对象 | `PARTIAL` | `AUTHORITY` |
| real_public readback | 证明未执行真实支付、下载、退款、provider call | stage9 readback summary | 内部闭环可观察 | 真实动作需 operator action | `IMPLEMENTED` | `CODE_CONFIRMED` |

## 10. 业务实现路线分支

本节不是补充概念，而是规定后续代码应按什么业务路线跑。每条路线都必须能在 UI、日志、正式对象或测试里被观察。

### 10.1 Stage1 路线：从搜索条件到候选池

**正常路线**
1. Owner 选择地区、项目类型、金额区间、关键词和时间窗口。
2. 系统按地区展开 profile，不把全国聚合当唯一来源。
3. 每个地区分别产生候选列表。
4. 候选进入批量过滤，不固定挑一个结果。
5. 通过候选进入 Stage2；未通过候选保存 skipped reason。

**分支路线**
- 无候选：返回 `NO_CANDIDATES`，展示哪个地区、哪个来源、哪个条件导致无结果。
- 来源失败：返回 source diagnostics，不能生成样本机会。
- 多省多类型：每个省/类型分别保留 candidate group，后续可以批量推进。
- 金额缺失：候选进入 review，不因金额缺失直接丢弃高价值项目。

**补救路线**
- 若省级入口无结果，尝试本省其他公告栏目或全国聚合补充。
- 若接口失败，保留入口页面快照和失败类型，进入 Stage2/来源修复任务。

### 10.2 Stage2 路线：从候选到可回放公开载体

**正常路线**
1. 对候选详情页抓取 HTML/API detail。
2. 从详情页提取附件链接，抓 PDF/DOC/XLS/ZIP 原文。
3. 为列表、详情、附件分别保存 snapshot、hash、source URL、profile id。
4. 建立 clock chain 和 notice version chain。
5. 输出给 Stage3 parser。

**分支路线**
- 详情页是 SPA 壳：进入 browser/API/render route，不得当作正文解析。
- 附件缺失：候选可继续，但 evidence gate 不能直接 PASS。
- 验证码/限流/风控：记录 challenge state，进入自动化 challenge 路线或 review。
- 多版本公告：按变更/澄清/补遗/中标候选/中标结果建立版本优先级。

**补救路线**
- 详情页弱正文时，优先找同站 API、附件、打印页或公告正文接口。
- 附件下载失败时，记录 attachment failure，不得生成附件证据。

### 10.3 Stage3 路线：从公开载体到字段血缘

**正常路线**
1. 解析项目名、地区、项目类型、金额、公告阶段、投标/异议/开标时钟。
2. 解析候选/中标单位、报价、排名、联合体、否决投标信息。
3. 解析项目经理姓名、证书、注册专业、等级、注册单位、人员公开标识。
4. 给每个字段生成 source slice、hash、locator、confidence。
5. 输出 `project_base`、`bidder_candidate`、`project_manager`、`field_lineage_record`。

**分支路线**
- 只有项目经理姓名：允许进入 Stage4 review，但不能形成核验 PASS。
- 金额跨标段：按 lot/package 拆分，不能把总金额直接套到单标段。
- 多候选人：保留候选集合，不只拿第一名。
- 字段冲突：生成 conflict state，交给 Stage4/5，不在 parser 静默改写。

**补救路线**
- HTML 解析失败时尝试附件解析。
- 附件解析失败时保留 raw snapshot，进入人工/模型辅助抽取，但模型输出必须带治理记录。

### 10.4 Stage4 路线：从字段到公开核验 carrier

**正常路线**
1. 根据 Stage3 字段生成核验计划：企业、人员、资质、信用、许可、合同、竣工、业绩。
2. 企业核验优先：先定位候选/中标公司公开记录。
3. 项目经理核验走企业内人员列表和人员详情，不只搜姓名。
4. 资质核验对照公告资质条款和企业资质公开记录。
5. 信用核验走信用中国、执行信息、GSXT 等公开链。
6. 项目/业绩/在建核验走四库项目、企业业绩、地方住建许可/竣工/合同备案。
7. 每个核验动作输出 carrier 和 readback。

**分支路线**
- 企业未匹配：不能判定人员不存在，进入企业主体 review。
- 人员同名：必须用公司、证书、专业、等级、人员 ID 消歧。
- 人员公开记录未 `MATCHED` 或仍需 review：不得满足身份链，只能进入 `manager_personnel_public_record_unmatched_or_review_required`。
- 企业内人员唯一匹配后必须把证书编号或人员公开 ID 作为后续查询主键，合同/业绩/在建查询不得退回姓名泛搜。
- 人员刚注册/变更：不在 Stage4 下结论，输出注册时间 carrier 给 Stage5。
- 查不到在建项目：不能直接判定无冲突；若源不可查，进入 review。
- 官方源返回 SPA/412/521/challenge：fail closed，记录具体源和失败状态。

**补救路线**
- 四库不可抓时，走地方住建、公共资源附件、备案系统补充。
- 公司名模糊时，先用统一社会信用代码或中标公告主体字段消歧。
- 人员列表分页时必须翻页或调用等价公开接口，不能只看第一页。

### 10.5 Stage5 路线：从核验证据到双闸门

**正常路线**
1. 对 Stage4 carriers 生成规则候选。
2. `rule_gate_decision` 判断规则是否真的命中。
3. `evidence_gate_decision` 判断证据是否足够、可回放、字段血缘是否完整。
4. 两门都 PASS 才允许进入正式事实聚合。

**分支路线**
- 规则命中但证据不足：`REVIEW_REQUIRED`，不能自动升级。
- 证据充足但规则边界不清：`RULE_REVIEW_REQUIRED`。
- 任一关键原始载体缺失：`EVIDENCE_BLOCK` 或 review。
- 模型摘要不能替代任一闸门。

**补救路线**
- 缺项目经理时间窗口：回 Stage4 补合同/竣工/许可。
- 缺公告时钟：回 Stage2 补版本链和时钟链。
- 缺资质条款：回 Stage3 补公告附件解析。

### 10.6 Stage6 路线：从双门到统一事实

**正常路线**
1. 消费 Stage5 双门和 review request。
2. 形成唯一 `project_fact`。
3. 形成内部报告、动作建议、复核队列、真实竞争者候选。
4. 生成 product package readiness。

**分支路线**
- 双门 REVIEW：形成复核任务，不形成正式事实结论。
- 双门 BLOCK：停止正式机会升级。
- evidence weak：可以生成内部线索，但不得客户交付。

**补救路线**
- 将缺口拆回 Stage2/3/4/5 对应补证路线。
- owner 可以复核结果层，但不得改写 Stage3 字段真相或绕过硬门。

### 10.7 Stage7 路线：从统一事实到可售承接

**正常路线**
1. 基于 `project_fact` 形成竞争者集合。
2. 选择真实竞争者并保留 selection trace。
3. 拆分法律行动 actor 和采购/决策 actor。
4. 计算 buyer fit、challenger buyer fit。
5. 生成 offer、报价区间、交付形态。
6. 生成商业钩子、可讲/不可讲、withheld fields。
7. 形成受限或正式 `saleable_opportunity`。

**分支路线**
- D8-core 不完整：只能形成内部 sales lead 或受限机会。
- D8-plus 不完整：不能宣称完整销售推进。
- actor 未拆分：不能生成完整正式 `saleable_opportunity`。
- 证据强但泄密风险高：只生成卖前摘要，不暴露完整 source path。

**补救路线**
- 缺真实竞争者：回 Stage6/4 补核验。
- 缺买家动机：保留为线索，不做报价推进。
- 报价依据不足：保留报价草稿，不进入正式 offer。

### 10.8 Stage8 路线：从可售机会到触达准备

**正常路线**
1. 只消费 Stage7 formal/受限 saleable opportunity。
2. 从公开官网、授权信息或合规 CRM 形成联系人候选集合。
3. 合并消歧联系人，形成 selection trace。
4. 生成正式 `contact_target`。
5. 生成触达计划、话术模板、频率、quiet hours、opt-out。
6. 真实触达前必须有审批、审计、operator action 和 provider/sandbox 状态。

**分支路线**
- 联系来源不可审计：block。
- 候选联系人冲突：review。
- 只有自然人高限制字段：按高限制字段策略处理。
- provider 未接入：只允许 preview/dry-run，不允许 live send。

**补救路线**
- 优先找组织级联系方式，再考虑个人联系人。
- 联系人冲突时回到 source merge，不允许直接选一个。

### 10.9 Stage9 路线：从触达到成交交付治理

**正常路线**
1. 根据 Stage8 touch record 和 saleable opportunity 形成订单候选。
2. 支付、收款、发票、异常进入 provider/sandbox 或人工确认链。
3. 证据包按 D6/D7 字段策略生成客户版本。
4. 加水印、版本 hash、下载审计、访问控制。
5. 交付后生成 delivery record 和 governance feedback。

**分支路线**
- 未支付：不交付客户证据包。
- 支付异常：进入 payment exception。
- 客户下载未授权：block。
- 退款：自动退款执行保持排除。

**补救路线**
- 交付被拒收：记录原因，回 Stage6/7 修证据包或商业说明。
- 客户要求补证：生成 governance feedback，不直接改写原事实。

## 11. UI 和测试验收矩阵

| 验收项 | UI 必须显示 | 测试必须覆盖 | 当前状态 |
| --- | --- | --- | --- |
| 数据模式 | 真实候选、离线样本、显式候选、无候选 | 不同模式不会互相冒充 | `PARTIAL` |
| 阶段状态 | Stage1-9 每阶段 produced/effective/invalid/review | 真实候选和内部回归分开 | `PARTIAL` |
| 机会状态 | 线索、复核、受限可售、正式可售、客户交付就绪 | Stage1 selected 不等于 saleable | `PARTIAL` |
| 证据包状态 | 内部预览、受控交付候选、客户交付 ready | 内部预览不得客户 ready | `PARTIAL` |
| 核验失败 | 站点失败、验证码、SPA 壳、字段缺失、同名歧义 | fail-closed/review 不被当 PASS | `PARTIAL` |
| 真实来源覆盖 | 每省 profile、候选发现、详情、附件、失败原因 | SD/HB 不得假装同等可跑 | `PARTIAL` |

## 12. 推进方式

后续每一轮修复都按以下流程执行：

1. 选择一个分支，例如 `Stage4 项目经理企业内消歧`。
2. 用真实页面或受控样本验证查询方法、分页、字段、失败形态。
3. 若验证结果与矩阵冲突，先修矩阵。
4. 再改代码实现分支。
5. 增加最小测试，证明 PASS/REVIEW/BLOCK 都不乱跳。
6. 操作台展示该分支状态和缺口。
7. 再进入下一个分支。

最终目标不变：真实公开候选能进料、可解析、可核验、可形成可验证证据包和商业钩子，并在受控治理下交付。
