# 专题_投前预测_Stage1-9 全链规则与判定资料池

## 1. 文档定位

本文件是 Stage1-9 范围内唯一的**规则资料主文档**。

从现在开始，凡是你要找：

- Stage4-5 双闸门主规则资料
- 投前预测辅助线规则资料
- 增强模块 / 投标文件内审资料
- 历史长稿里还能复用的候选规则、字段候选、表达边界

统一只看这一个文件。

本文件的职责是：

- 承接 Stage1-9 全链路的规则资料、字段候选、证据等级和表达边界
- 按功能模块整理 Stage4-5 双闸门、投前预测辅助线、增强模块、Stage2-3 支撑和 Stage6-9 后置资料
- 明确哪些内容服务 Stage1-2、Stage3、Stage4-5、Stage6-9、投前辅助线、增强模块
- 给 `rule_basis_catalog`、`rule_catalog`、Stage5 tests、future bid-document review 和后续扩展模块提供唯一人类入口

本文件不是正式规则码总表，不直接替代：

- `contracts/rules/rule_basis_catalog.json`
- `contracts/rules/rule_catalog.json`
- `src/stage5_rules_evidence/*`
- `docs/AX9S_Stage4-5_核验双闸门SOP.md`

## 2. 使用方法

默认工作顺序固定为：

1. 先看 `docs/专题_Stage1-9_缺口收口与优先级清单.md`
   确认当前补哪个缺口
2. 再看 `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
   确认该缺口位于哪一个 Stage、怎么回退、怎么验收
3. 再看本文件
   抽对应功能模块的规则资料、字段候选、证据等级和表达边界
4. 做 Stage4/5 公开核验和双闸门细则时，再看 `docs/AX9S_Stage4-5_核验双闸门SOP.md`
5. 真正落代码时，再进入 `contracts/rules/*` 和 `src/stage5_rules_evidence/*`

## 3. 单源分工

| 文档 | 作用 | 不替代什么 |
|---|---|---|
| `docs/业务方向_候选公示后证据包与投前预测双线契约.md` | 双线业务方向、产品线边界、禁止输出 | 不展开 Stage1-9 工程资料细节 |
| `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | Stage1-9 主链、PASS/REVIEW/BLOCK、补证回退 | 不承接规则资料细项 |
| `docs/AX9S_Stage4-5_核验双闸门SOP.md` | Stage4-5 操作细则、公开核验、证据门和规则门 | 不承接跨 Stage1-9 的资料池归属 |
| `docs/专题_投前预测_Stage1-9 全链规则与判定资料池.md` | 唯一规则资料主文档 | 不替代 D2/D3 正式契约 |

## 4. Stage1-9 功能模块总览

| 模块 | 主要服务 Stage | 核心用途 | 当前边界 |
|---|---|---|---|
| Stage4-5 主规则模块 | Stage4-5 | 公开核验 carrier 输入、rule gate / evidence gate 规则资料 | 不直接生成正式违法或客户结论 |
| 投前预测辅助模块 | Stage1-3、Stage6 内部建议 | `PRE_BID_PREDICTION` 的前置分流、公告前机会、项目筛选、控标预测、自评分、废标风险 | 不是候选后证据包主线 |
| 增强模块 / 投标文件内审 | Stage3 内部 QA、future bid-document review | 暗标、正偏离、授权签章、声明函、税率审计、电子监管提醒 | 不直接混入当前公开证据主链 |
| Stage2-3 支撑模块 | Stage2-3 | 文件完整性、版本链、项目档案、资格/信用/业绩材料、AI 评标适配 | 只做输入和血缘，不做法律定性 |
| Stage6-9 后置模块 | Stage6-9 | 救济、合同、结算、付款、专项监督和后置治理资料 | 不反向污染 Stage4-5 正式结论 |

## 5. Stage4-5 主规则模块

### 5.1 主吸收范围

| 资料类别 | Stage4-5 用法 | 当前边界 |
|---|---|---|
| 两法体系分流器 | 判断政府采购 / 招标投标 / 混合路径，决定后续规则是否适用 | 不凭体系标签直接下风险结论 |
| 公平竞争审查 | 本地保护、区域壁垒、所有制/地区/产地区别待遇、指定平台工具 | 不直接写违法成立 |
| 需求管理控标 | 需求量化、需求调查、调查对象数量、同类业绩数量、创新产品门槛 | 需要条款原文和需求形成依据 |
| 政府采购本国产品政策 | 本国产品声明、成本占比、20% 价格评审优惠、虚假声明责任 | 只在政府采购产品场景触发 |
| 远程异地评标与组织性线索 | 主副场责任、专家库共享、系统风险、异常接触、利益输送迹象 | 只作组织性风险线索 |
| 控标预测与限制竞争 | 参数组合排他、厂家资料相似、授权/证书/踏勘门槛、交付期异常 | 不写控标成立 |
| 废标红线 | 实质性要求、签章授权、报价一致、声明函、社保、信用、同品牌有效竞争 | 必须区分废标、扣分、澄清、形式瑕疵 |
| 资格条件合法性 | 非必要证书、厂家授权、ISO/CMA、现场踏勘、实质性要求标识 | 需要规则依据和条款血缘 |
| 救济时钟与证据链 | 时钟、主体资格、证据链、前置程序、书面形式 | Stage5 只消费表达边界和证据要求 |
| 证据等级与表达模板 | 强/中/弱/阻断证据分层、允许表达和禁止表达 | 字段命中不等于证据足够 |

### 5.2 两法适用门

应吸收细项：

- 正式采购制度字段
- 法律体系
- 资金来源
- 监管机构
- 采购 / 招标方式
- 资格审查主体
- 提前发布类型
- 救济路径

候选字段：

- `procurement_regime`
- `procurement_category`
- `legal_system_type`
- `fund_source_type`
- `regulator_type`
- `qualification_reviewer`
- `pre_notice_type`

Stage5 用法：只作为适用门，不单独形成风险结论。

### 5.3 公平竞争 / 需求管理 / 政策规则

应吸收细项：

- 本地分支、本地纳税、本地社保、本地业绩、本地奖项、本地协会证书
- 所有制、地区、产地、品牌注册地差别待遇
- 指定交易工具、指定平台、指定机构
- 需求客观明确量化、需求调查触发、调查对象不少于 3 个、同类业绩数量限制、创新产品门槛
- 政府采购本国产品声明、成本占比、20% 价格评审优惠、虚假声明责任

候选字段：

- `fair_competition_barrier_type`
- `local_protection_signal`
- `ownership_discrimination_signal`
- `market_barrier_remedy_path`
- `demand_investigation_required`
- `demand_objective_quantified`
- `same_contract_count_limit_risk`
- `innovation_no_past_performance_rule`
- `domestic_product_declaration_required`
- `domestic_product_cost_ratio`
- `domestic_price_deduction_20pct`
- `false_declaration_liability`

Stage5 用法：进入弱规则和 `review_request`，不做违法定性。

### 5.4 远程异地评标与组织性线索

应吸收细项：

- 适用范围
- 主副场责任
- 专家库和评标工位共享
- 系统和数据安全
- 专家考核和回避
- 评审人员异常接触
- 利益输送迹象

候选字段：

- `remote_cross_region_eval_applicable`
- `main_sub_venue_responsibility`
- `expert_pool_shared_state`
- `remote_eval_system_failure_risk`
- `owner_representative_eval_risk`
- `expert_supplier_contact_signal`
- `illegal_benefit_transfer_signal`

Stage5 用法：组织性风险 review，不写犯罪或利益输送成立。

### 5.5 控标预测与限制竞争

应吸收细项：

- 资质、业绩、人员、检测报告、产品参数、服务网点组合后只剩少数供应商
- 参数与厂家官网、彩页、产品手册高度相似
- 兼容历史系统但不提供接口文档或开放标准
- 现场演示、样品、讲标分值过高且标准主观
- 交付期明显短于正常采购/生产周期
- 厂家授权、ISO、CMA、现场踏勘被设置为资格、实质性要求或高分项
- 工程类资质等级过高、项目经理/技术负责人条件过细、类似业绩限定过严、奖项/信用/本地荣誉过度加分
- 服务类团队配置过细、驻场/响应/本地服务能力过严、案例经验过细、证明材料多重叠加
- 暗标、盲评、远程异地、监管高压、对手废标概率、流标重招等缓释/变数信号

候选字段：

- `tailored_bid_risk_profile`
- `tailored_bid_risk_level`
- `tailored_bid_risk_hits`
- `restrictive_clause_hit_list`
- `restrictive_clause_locations`
- `market_substitutability_check`
- `market_substitutability_state`
- `suspicious_match_to_vendor_material`
- `public_attack_surface`

Stage5 用法：限制竞争弱线索，需要条款原文、市场可替代性和证据等级。

#### 5.5.1 通用控标信号

本节覆盖“投前萝卜标 / 控标 / 指向性 / 排他性 / 限制竞争预测”的通用高频信号。这里的结论只能进入 Stage3 条款命中、Stage5 review 和 Stage6 内部建议，不得直接输出“控标成立”“萝卜标成立”。

| 信号 | 风险解释 | 最低证据需求 | 当前落点 |
|---|---|---|---|
| 资质、业绩、人员、检测报告、产品参数、服务网点刚好只匹配某一家 | 排他性组合门槛 | 条款原文、市场供应商初筛、同类项目对比 | Stage3 条款抽取 -> Stage5 review |
| 单条参数合理，多条组合后只剩一两家可满足 | 组合型指向 | 参数组合、竞品可满足情况、市场可替代性 | Stage3 命中 -> Stage5 weak rule |
| 参数与厂家官网、彩页、产品手册高度相似 | 特定厂家指向 | 条款原文、厂家资料、相似片段 | Stage3 命中 -> Stage5 review |
| 要兼容历史系统但不提供接口文档或开放标准 | 资料不对称或历史供应商倾向 | 条款原文、接口开放情况、替代接入路径 | Stage3/5 |
| 现场演示、样品、讲标分值过高且标准主观 | 主观分放大特定供应商优势 | 评分项、权重、评分标准 | Stage3 提取 -> Stage6 内部建议 |
| 交付期明显短于正常采购/生产周期 | 预备货、预内定或排斥外部正常供应周期 | 交付期条款、正常周期对比、行业常识说明 | Stage5 review |
| 评分项集中匹配某供应商优势 | 得分点拆解式定向 | 评分细则、权重、竞品满足难度 | Stage3/5 |
| 非核心指标高分化、主观化 | 通过非关键指标做隐性定向 | 评分细则、技术必要性说明 | Stage5 review |
| 厂家授权被设置为资格、实质性要求或高分项且缺少替代路径 | 排他授权风险 | 条款原文、强制依据、替代证明路径 | Stage5 资格合法性 / 限制竞争 review |
| ISO、CMA、检测资质、行业证书与采购需求关联弱但权重高 | 非必要证书门槛 | 条款原文、证书与需求的关联性说明 | Stage5 review |
| 现场踏勘被设置为资格条件、实质性条件或加分条件 | 对外地供应商不利 | 条款原文、踏勘必要性、合规依据 | Stage5 review |

#### 5.5.2 分场景控标信号

**政府采购类信号**

| 信号 | 风险解释 | 证据需求 |
|---|---|---|
| 参数、检测报告、证书、品牌倾向过强 | 可能指向特定产品或供应商 | 条款原文、市场产品对比、厂家资料 |
| 售后网点、本地化要求异常 | 可能排斥外地供应商 | 条款必要性、项目服务半径说明 |
| 评分细则过细 | 可能把某家优势拆成得分点 | 评分项、权重、竞品可满足情况 |
| 固定机构检测报告 | 可能形成非必要门槛 | 法定强制性依据、替代机构可行性 |
| 厂家授权、ISO、CMA 等证明材料机械设为门槛 | 可能与采购需求无直接关系，或形成排他授权 | 项目必要性、强制依据、替代证明路径 |
| 现场踏勘与投标资格或得分挂钩 | 可能排斥无法到场或外地供应商 | 踏勘必要性、是否存在合规依据 |

**工程类信号**

| 信号 | 风险解释 | 证据需求 |
|---|---|---|
| 资质等级过高 | 可能超过项目实际需要 | 项目规模、法规资质要求、同类项目对比 |
| 项目经理 / 技术负责人条件过细 | 可能卡特定团队 | 证书、业绩、社保、在建条件 |
| 类似业绩限定过严 | 特定区域、特定类型、特定金额、特定时间组合 | 历史同类招标文件、市场供应商数量 |
| 奖项、信用评价、本地协会荣誉 | 可能形成区域保护或非必要加分 | 奖项权威性、必要性、可替代性 |
| EPC / 设计施工总承包 | 设计、初设、方案、技术路线可能提前绑定 | 初设来源、方案前置、评定分离机制 |

**服务类信号**

| 信号 | 风险解释 | 证据需求 |
|---|---|---|
| 团队配置过细 | 可能绑定特定服务商人员结构 | 人员必要性说明、同类服务对比 |
| 驻场、响应时间、本地服务能力过严 | 可能排斥非本地服务商 | 服务内容、响应半径、替代服务方式 |
| 案例经验要求过细 | 可能只匹配某供应商历史项目 | 业绩维度拆解、市场可满足情况 |
| 过往项目证明材料多重叠加 | 合同、发票、验收、用户证明全要可能形成高门槛 | 证明必要性和评分权重 |

#### 5.5.3 控标证据需求表

这部分解决“为什么命中了疑似控标，但还不能下更强结论”的问题。控标预测至少要把信号、证据和表达边界绑在一起。

| 风险簇 | 最低证据 | 补充证据 | 常见不足 | Stage 归属 |
|---|---|---|---|---|
| 参数定制 / 特定厂家指向 | 招标条款原文 | 厂家官网、彩页、产品手册、竞品对比 | 只有关键词，没有原文或市场对比 | Stage3 -> Stage5 |
| 限制竞争 / 区域壁垒 | 条款原文 | 条款必要性说明、服务半径、法规依据、替代路径 | 只有“感觉像”，没有必要性比对 | Stage3 -> Stage5 |
| 资格条件过严 | 条款原文 | 项目规模、法定资质要求、历史同类招标文件、供应商数量 | 只看到门槛高，没做同类对照 | Stage3 -> Stage5 |
| 评分细则定向 | 评分项、权重、打分规则 | 竞品满足难度、主观分比例、得分点分布 | 只说主观分高，没有拆权重 | Stage3 -> Stage6 |
| 本地化 / 服务能力门槛 | 本地服务、驻场、网点条款 | 服务范围、替代服务方式、履约必要性 | 只有“本地”字样，没有服务必要性分析 | Stage3 -> Stage5 |
| 工程/EPC 提前绑定 | 项目经理 / 技术负责人 / 资质 / 方案条款 | 初设来源、方案前置、评定分离信息 | 只有条件过细，没有上游方案来源 | Stage3 -> Stage5/6 |
| 异常短交付期 | 交付期条款 | 行业正常周期、生产周期、供应链解释 | 只说太短，没有行业基线 | Stage3 -> Stage5 |

#### 5.5.4 控标风险缓释与变数

疑似控标不等于必然放弃。系统必须同时识别“风险信号”和“变数信号”，避免把所有高风险项目都机械判为 `PASS` 或机械判为“不要投”。

| 变数信号 | 判断 | 产品动作 | Stage 归属 |
|---|---|---|---|
| 暗标、盲评、远程异地评标 | 身份和现场关系影响相对降低 | 风险适度缓释 | Stage6 内部建议 |
| 监管高压、投诉风险明显 | 过度定向条款更容易被关注 | 建议澄清或质疑评估 | Stage6 |
| 对手废标概率高 | 即使存在倾向，也可能因材料错误产生机会 | 联动废标红线 | Stage6 |
| 甲方内部意见可能不一致 | 定标和履约侧存在不确定性 | 不输出确定性结论 | Stage6 |
| 流标重招或二次招标 | 原有锁定结构可能松动 | 进入关注池 | Stage1 / Stage6 |

这部分建议和以下字段联动：

- `tailored_bid_risk_profile`
- `tailored_bid_risk_level`
- `tailored_bid_risk_hits`
- `restrictive_clause_hit_list`
- `restrictive_clause_locations`
- `market_substitutability_check`
- `market_substitutability_state`
- `suspicious_match_to_vendor_material`
- `public_attack_surface`

### 5.6 废标红线

应吸收细项：

- 废标条款、资格条款、评分办法、格式文件、答疑补遗
- 实质性要求、星号条款、不可偏离条款、符合性审查表、无效响应条款
- 法人章/法定代表人章、授权书、投标函、承诺书、报价表、偏离表
- 中小企业声明函、业绩材料、社保材料、信用查询、报价大小写/合计/税率
- 暗标身份痕迹、页数限制、页码规则、扫描件形式、证书有效期
- 同品牌/核心产品有效竞争家数、多标包连带否决、谈判/磋商二次报价、补遗公告、原件备查

候选字段：

- `fatal_rejection_checklist`
- `fatal_rejection_risk_hits`
- `substantive_requirement_map`
- `signature_seal_matrix`
- `format_requirement_checklist`
- `material_completeness_checklist`

Stage5 用法：必须区分废标 / 无效响应、扣分 / 不得分、澄清 / 补正、事后争议难度。

### 5.7 资格条件合法性

应吸收细项：

- 非必要证书作为资格条件
- 特定区域、特定行业经验
- 厂家授权作为资格、实质性要求或高分项
- ISO 三体系、CMA、检测资质、行业证书的项目关联性
- 现场踏勘作为资格条件、实质性条件或加分条件
- 实质性要求是否明确列入资格、符合性、星号、不可偏离或无效响应条款

候选字段：

- `qualification_legality_risk_hits`
- `manufacturer_authorization_risk_check`
- `certification_relevance_check`
- `substantive_requirement_map`

Stage5 用法：作为限制竞争 / 资格合法性 review，不直接写资格违法成立。

### 5.8 救济时钟与证据链

应吸收细项：

- 澄清、异议、质疑、投诉区分
- 期限起算点、主体资格、请求事项、证据链、证据具体性、前置步骤、书面形式、签字盖章
- 不予受理 vs 不成立、暂停效果差异、非中标候选人异常、招标文件歧义或前后矛盾
- 政府采购质疑 7 个工作日、答复 7 个工作日、投诉 15 个工作日、财政处理 30 个工作日
- 资格预审文件异议 2 日前、招标文件异议 10 日前、中标候选人公示不少于 3 日、工程招投标投诉通常 10 日内

候选字段：

- `remedy_window_state`
- `challenge_evidence_chain_state`
- `remedy_clock_rule_code`
- `remedy_deadline_date`
- `precondition_objection_required`
- `remedy_subject_standing_check`
- `evidence_specificity_level`
- `written_objection_formality`

Stage5/6 用法：Stage5 只消费证据等级和表达边界，Stage6 才形成救济评估。

时钟常量和规则码建议保留为预测判定层的独立常量，不作为普通业务字段混入对象层：

| 场景 | 规则码 / 时钟码 | 用法 |
|---|---|---|
| 政府采购质疑 | `GOV_PROC_CHALLENGE_7WD` | 质疑窗口判定 |
| 政府采购质疑答复 | `GOV_PROC_REPLY_7WD` | 答复时限判定 |
| 政府采购投诉 | `GOV_PROC_COMPLAINT_15WD` | 投诉窗口判定 |
| 财政部门投诉处理 | `GOV_PROC_COMPLAINT_HANDLE_30WD` | 处理时限判定 |
| 资格预审文件异议 | `TENDER_PREQUAL_OBJECTION_2D` | 资格预审异议窗口 |
| 招标文件异议 | `TENDER_FILE_OBJECTION_10D` | 招标文件异议窗口 |
| 中标候选人公示 | `CANDIDATE_PUBLICITY_MIN_3D` | 公示最短时限 |
| 工程招投标投诉 | `TENDER_COMPLAINT_10D` | 工程投诉窗口 |

补充字段建议：

- `document_conflict_remedy_hint`

## 6. 投前预测辅助模块

### 6.1 双线业务定位与输出边界

本模块是 `PRE_BID_PREDICTION` 投前预测线的辅助功能模块，不是当前主线说明书。当前招投标业务方向以：

- `docs/业务方向_候选公示后证据包与投前预测双线契约.md`
- `contracts/evaluation/business_direction_strategy_contract.json`

为准。

投前预测线可以输出：

- 控标风险线索
- 疑似定制标
- 限制竞争线索
- 废标风险
- 是否值得投
- 建议澄清 / 质疑 / 谨慎投

投前预测线不能输出：

- 候选人核查结论
- 真实竞争者结论
- 围标 / 串标 / 陪标组合结论
- 已内定、违法成立、控标成立、必然废标

兼容旧口径表述：不能输出候选人核查结论、真实竞争者结论、围标/串标/陪标组合结论。

### 6.2 流程与时钟门槛

投前预测必须先过流程和时钟门槛：

- 只适用于近期 `02 招标文件公示`、`03 招标公告/关联公告`、`04 答疑澄清/补遗` 且投标截止/开标未过的项目
- 若出现 `05 开标信息`，输出 `PRE_BID_NOT_ELIGIBLE_OPENING_STARTED`
- 若截止/开标已过，输出 `PRE_BID_NOT_ELIGIBLE_DEADLINE_PASSED`
- 只有 `02/03` 且无 `04` 时标记 `PREDICTION_BEFORE_CLARIFICATION`
- 后续出现澄清、答疑、补遗或补充文件时必须标记 `PREDICTION_RECALC_REQUIRED`
- 下载和解析仍必须先过 `AnalysisStrategyPlan v1`

### 6.3 三表入口

**规则候选索引表**

| 候选能力 | 当前定位 | 正式落点 | 禁止越界 |
|---|---|---|---|
| 两法体系分流器 | 投前线前置分类 | Stage1-3/6 前置分类、规则适用门 | 不凭体系标签直接下结论 |
| 公告前机会与政策规则 | 投前线 watchlist 和政策线索 | Stage1 watchlist、Stage3 条款字段、Stage5 弱规则候选 | 不把采购意向/计划当候选后证据包 |
| 项目筛选 / 控标预测 / 自评分 / 废标红线 | 投前线主线能力层 | Stage3 字段、Stage5 review、Stage6 内部建议 | 不写控标成立、必然废标、必然中标 |
| 文件内审增强 | 内部 QA / 增强能力层 | Stage3 parser、内部 QA profile | 不替代公开证据链 |
| 救济履约与结算后置能力 | 后置复核 / 后续扩展 | Stage6/7/9 后置复核 | 不输出监管处罚或付款违约定性 |

**字段候选表**

| 字段组 | 代表字段 | 当前定位 |
|---|---|---|
| 前置分流与公告前机会 | `procurement_regime`, `procurement_category`, `pre_notice_signal` | 字段候选，不是正式 D2 字段 |
| 政策规则与评审组织 | `fair_competition_barrier_type`, `remote_cross_region_eval_applicable` | 需公开条款血缘后再晋级 |
| 项目筛选与盲投运营 | `bid_selection_score`, `blind_bid_pipeline_stage` | 内部建议字段候选 |
| 标书评审与文件内审 | `fatal_rejection_risk_hits`, `ai_review_readability` | 内部 QA / 增强字段候选 |
| 救济与中标后风险 | `remedy_window_state`, `post_award_contract_risk_hits` | 后置复核字段候选 |

**风险表达与证据等级表**

| 证据等级 | 允许表达 | 禁止表达 | 进入 Stage5/6 条件 |
|---|---|---|---|
| 强证据候选 | 建议进入复核或质疑评估 | 违法成立、控标成立、必然废标 | 有来源 URL、snapshot/readback、字段血缘、双闸门 |
| 中等证据候选 | 建议补查或定向解析 | 已确认、已排除、无风险 | 关键字段可回放，缺口进入 review |
| 弱线索 | 疑似风险、建议核查 | 定性结论、客户可见硬伤 | 只进 watchlist 或内部 review |
| 阻断/未命中 | 源阻断、字段缺失、未命中需复核 | 未发现问题、没有风险 | 必须保留 taxonomy 和下一步建议 |

### 6.4 公告前机会与项目筛选

保留资料：

- 政府采购意向、招标计划、招标文件提前公示、采购意向到公告间隔
- 场内标、电子标、暗标 / 盲评、远程异地、大城市、本地小金额、流标重招、询价 / 谈判 / 磋商
- 主观分、客观分、价格空间、团队产能、投前反馈策略
- 专业招标网站、政府采购网、公共资源平台、重大项目清单、主管部门平台、土地招拍挂、地方新闻、设计院 / 咨询公司中标、行业官网、上下游反推、圈子弱线索

当前用途：

- watchlist
- 投 / 不投建议
- source intelligence
- 项目档案和跟进记录

这一层除了“是否进池”，还要补齐“为什么持续关注”和“为什么值得投 / 谨慎投 / 放弃”两种说明。

建议保留的预测聚合字段：

- `watchlist_reason`
- `prebid_roi_precheck`
- `prebid_selection_profile`
- `prebid_selection_score`
- `prebid_selection_reasons`

禁止越界：

- 不把采购意向 / 招标计划写成候选后证据
- 不承诺中标率
- 无公开回链不得进入正式证据链

### 6.5 自评分与投前辅助字段候选

保留资料：

- 资格 / 技术 / 商务 / 价格 / 政策加分拆解
- 我方材料库映射
- 同品牌核心产品
- 资格条件作为评分因素
- 评分项量化、评定分离、目录 / 页码 / 证据链导航

自评分不只是“能不能报名”，而是要回答 4 个问题：

1. 按评分办法拆开后，我方理论能拿多少分
2. 哪些分是确定分，哪些分依赖材料质量、主观分或报价策略
3. 即使能投，是否因为关键加分项拿不到而变成高概率陪跑
4. 评委阅读成本、目录结构、证据可达性是否会拖低主观分和确认速度

核心判断表：

| 规则 | 判断 | 产品动作 | Stage 归属 |
|---|---|---|---|
| 评分办法必须拆成资格、技术、商务、价格、政策加分 | 不能只看是否能报名 | 评分结构化 | Stage3 -> Stage6 |
| 评分项必须映射到我方材料库 | 有证据才算可拿分 | 自评分 | Stage6 |
| 理论能投但关键加分项拿不到 | 实际陪跑概率高 | 谨慎投 | Stage6 |
| 技术商务分高、价格分低 | 证据优势比低价更重要 | 强调材料准备 | Stage6 |
| 价格分高 | 需要精算价格策略 | 联动报价风险 | Stage6 |
| 小微企业预留、价格扣除、本国产品政策 | 中小企业机会 | 政策加分提示 | Stage6 |
| 同品牌 / 核心产品规则 | 影响有效竞争家数和候选资格 | 品牌有效投标人测算 | Stage3/6 |
| 资格条件被作为评分因素 | 可能重复放大资格门槛优势 | 评分合法性检查 | Stage5/6 |
| 评分因素未细化量化 | 会扩大裁量空间 | 评分量化检查 | Stage5/6 |
| 客观但不可量化指标作为评分项 | 更适合作为实质性要求 | 非量化评分风险 | Stage5/6 |
| 评定分离项目 | 不能只盯评标分，还要看定标因素 | 定标规则抽取 | Stage6 |
| 候选人不排序、票决法、集体议事法 | 价格、技术方案、信誉、团队实力仍可能改变结果 | 定标因素结构化 | Stage6 |
| 主副场、远程异地、双盲、专家抽取和回避规则 | 评审组织方式影响主观分波动 | 评审组织规则抽取 | Stage6 |
| 定标过程留痕、密封存档要求 | 事后争议看程序和记录 | 定标程序风险提示 | Stage6 |
| 评分项没有对应证明材料 | 理论响应不等于实际得分 | 材料缺口提示 | Stage6 |

评审端可读性表：

| 经验 | 判断 | 产品动作 |
|---|---|---|
| 专家先看目录和左侧导航 | 目录层级深、逻辑闭环会提高专业感 | 目录结构检查 |
| 专家只看打分点证书 | 无关证书、荣誉、简介价值低 | 证书与评分项映射 |
| 0.1 分、0.01 分都可能决定中标 | 小承诺、小证明、小正偏离不能忽略 | 得分细项提示 |
| 方案有关键词、图表、第一手资料、现场痛点、本地服务资源 | 能证明不是模板化响应 | 方案质量评分 |
| 评分项就是目录 | 小标题对应评分点，证明材料前置 | 得分点导航检查 |
| 每个得分点要有标题、响应、方案、证明、页码、附件索引 | 评委不应被迫在几百页里找证据 | 证据可达性检查 |
| 评分索引和响应页码 | 每个评分项应能快速定位到响应内容和证明材料页码 | 评分索引检查 |
| 证据链目录 | 合同、发票、验收、证书、检测报告等应按得分点组织 | 证据链目录检查 |
| 技术偏离定位 | 技术偏离、参数响应和正偏离证明要能被快速定位 | 技术定位检查 |
| 商务证明定位 | 业绩、人员、社保、信用、售后、本地服务证明要能被快速定位 | 商务定位检查 |
| 报价说明定位 | 总价、分项、折扣、税率、异常低价说明和成本证据要能被快速定位 | 报价定位检查 |
| 公司简介、无关荣誉和泛化模板堆砌 | 增加页数但不增加得分确定性 | 无效内容降权 |
| 采购人代表可能影响主观分 | 同一材料在不同评审组织下存在主观波动 | 评审端不确定性标记 |
| 专家可能先形成潜在中标候选，再回看材料确认 | 目录、首屏、关键词和核心证明会影响初始判断 | 首轮可读性检查 |
| 远程异地双盲下材料要能离开人独立得分 | 不能指望现场解释、关系沟通或代理引导 | 证据自解释检查 |
| 打分结束后通常以复核、质疑、投诉为主，不应指望重新认真打分 | 投前材料质量比事后解释更重要 | 事前复核优先 |

兼容旧口径字段：

- `bid_score_forecast`
- `winnability_band`
- `score_gap_reason`

当前优先使用字段：

- `self_score_forecast`
- `score_gap_reasons`
- `review_subjectivity_factors`
- `core_product_brand_map`
- `same_brand_effective_bidder_count`
- `same_brand_candidate_rule`
- `qualification_as_score_factor_risk`
- `score_factor_quantification_check`
- `non_quantifiable_score_item_risk`
- `score_index_completeness`
- `evidence_chain_navigation_score`
- `technical_deviation_locator_state`
- `commercial_evidence_locator_state`
- `price_explanation_locator_state`

候选字段：

- `pre_notice_signal`
- `procurement_intention_budget`
- `expected_procurement_time`
- `tender_plan_watchlist`
- `prebid_roi_precheck`
- `prebid_selection_profile`
- `prebid_selection_score`
- `prebid_selection_reasons`
- `watchlist_reason`
- `source_lead_time_band`
- `bid_selection_score`
- `bid_selection_reasons`
- `blind_bid_pipeline_stage`
- `bid_team_capacity`
- `document_feedback_strategy`
- `exposure_risk_before_bid`
- `tailored_bid_risk_level`
- `tailored_bid_risk_hits`
- `restrictive_clause_locations`
- `market_substitutability_state`
- `rebid_watchlist_state`
- `self_score_forecast`
- `review_subjectivity_factors`
- `core_product_brand_map`
- `same_brand_effective_bidder_count`
- `same_brand_candidate_rule`
- `qualification_as_score_factor_risk`
- `score_factor_quantification_check`
- `non_quantifiable_score_item_risk`
- `score_index_completeness`
- `evidence_chain_navigation_score`
- `technical_deviation_locator_state`
- `commercial_evidence_locator_state`
- `price_explanation_locator_state`
- `source_channel_type`
- `source_quality_score`
- `source_update_latency`
- `project_lifecycle_stage`
- `project_category_taxonomy`
- `project_intelligence_folder`
- `owner_actor_profile`
- `competent_department`
- `procurement_actor`
- `agency_actor`
- `competitor_history_profile`
- `incumbent_supplier_signal`
- `project_timeline_chain`
- `followup_record_state`
- `ai_collection_field_schema`
- `ai_collection_prompt_profile`
- `ai_output_format_profile`

## 7. 增强模块 / 投标文件内审

本模块承接 **增强模块 / bid-document review / internal QA** 的资料入口。

### 7.1 归属边界

| 能力 | 当前归属 |
|---|---|
| 暗标 | bid-document review / internal QA |
| 正偏离 | bid-document review / response-quality assistant |
| 授权签章 | bid-document review / compliance checklist |
| 声明函 | bid-document review / declaration checker |
| 税率审计 | internal finance / low-price review |
| 电子监管 | compliance reminder only |

这些能力当前**不能直接混入现有公开证据主链**。

### 7.2 暗标

重点资料：

- 版式风险
- 标点符号风险
- 页面元素风险
- 隐性痕迹
- 身份信息泄露
- 限页要求
- 暗标高分要素

未来落点：

- `dark_bid_format_check`
- `dark_bid_identity_trace_check`
- `document_metadata_risk_check`
- `dark_bid_quality_score`

### 7.3 正偏离

重点资料：

- 商务正偏离候选
- 技术正偏离候选
- 参数方向要求
- 证明材料要求

未来落点：

- `positive_deviation_quality_check`
- `positive_deviation_evidence_map`
- `parameter_direction_check`

### 7.4 授权签章

重点资料：

- 授权委托书风险
- 投标函和报价表一致性
- 其他签章材料风险
- 高危水印

未来落点：

- `authorization_signature_risk_hits`
- `bid_letter_price_consistency_state`
- `signature_seal_matrix`
- `watermark_risk_check`

### 7.5 声明函

重点资料：

- 中小企业声明函
- 本国产品 / 进口产品声明
- 其他承诺和声明

未来落点：

- `declaration_form_risk_hits`
- `sme_declaration_check`
- `domestic_product_declaration_check`

### 7.6 税率审计

重点资料：

- 税率一致性
- 审计报告一致性
- 异常低价说明和证据包
- 成本说明与履约能力边界

未来落点：

- `financial_tax_audit_risk_hits`
- `tax_rate_consistency_check`
- `audit_report_consistency_check`
- `abnormally_low_price_evidence_pack`
- `abnormal_low_price_trigger`
- `cost_breakdown_ready`
- `materials_labor_cost_evidence`
- `low_price_review_record`

### 7.7 电子监管

重点资料：

- 同源痕迹
- 制作环境隔离
- CA / 锁 / 账号独立性
- 清单软件与设备同源痕迹
- 技术文本相似性

未来落点：

- `electronic_bid_environment_risk_hits`
- `electronic_supervision_trace_risk`
- `submission_independence_checklist`
- `opening_process_reminder`
- `bid_environment_isolation_check`
- `ca_lock_usage_independence`
- `bill_quantity_software_trace_check`
- `print_scan_device_trace_check`
- `technical_text_similarity_check`

### 7.8 原稿检查项吸收表

| 能力 | 必须保留的检查项 | 当前字段候选 |
|---|---|---|
| 暗标 | 字体、字号、颜色、页边距、行间距、首行缩进、空行、标点符号、页眉页脚、页码、目录、图表对齐、隐藏目录、空格替代空字符、文件属性、人员姓名、企业名称、项目简称、水印、限页规则、暗标高分要素 | `dark_bid_format_check`, `dark_bid_identity_trace_check`, `document_metadata_risk_check`, `dark_bid_quality_score`, `page_limit_format_state` |
| 正偏离 | 有效期、工期、地点、售后、报价、团队、履约保证金、主体资格、权利义务、样品演示、性能、扩展性、安全性、生态性、合规性、国际化、用户体验、参数方向、证明材料 | `positive_deviation_quality_check`, `positive_deviation_evidence_map`, `parameter_direction_check`, `positive_deviation_quality_state` |
| 授权签章 | 人名章、授权事项、转委托权、授权期限、机打/抠图签名、真实签署过程、身份证附件、投标函模板、报价表一致、小数位、折扣金额化、工期/地点/税率/有效期一致、日历日/天、二次报价、盖章位置、保证金备注、查询件替代原始证书 | `authorization_signature_risk_hits`, `bid_letter_price_consistency_state`, `signature_seal_matrix`, `watermark_risk_check`, `bid_price_consistency_state` |
| 声明函 | 中小企业声明函标题、行业分类、从业人员、营业收入、资产总额、数据单位、划型结论、盖章主体、声明主体、联合体/分包/制造商主体、本国产品/进口产品声明、进口产品许可、国产进口混投、无诉讼/仲裁/重大违法、无行贿犯罪、信用/纳税/社保承诺、项目包号 | `declaration_form_risk_hits`, `sme_declaration_check`, `domestic_product_declaration_check` |
| 税率审计 | 税率和征收率、财务确认、报价表税率/分项/总价一致、审计报告签章、关键页、报表勾稽、二维码/验证码、异常指标、异常低价触发线、成本说明、证明材料、低价审查归档 | `financial_tax_audit_risk_hits`, `tax_rate_consistency_check`, `audit_report_consistency_check`, `abnormally_low_price_evidence_pack`, `abnormal_low_price_trigger`, `cost_breakdown_ready`, `materials_labor_cost_evidence`, `low_price_review_record` |
| 电子监管 | 机器码、MAC、硬盘序列号、文件创建标识码、报名/上传/解密 IP、上传时间、联系人雷同、同一电脑/IP/CA/手机号/邮箱、文件源和元数据相似、报价规律、保证金路径、关联公司、异标段同源、代做文件、同一造价咨询机构、CA/账号混用、清单软件、打印/扫描设备、技术文本相似 | `electronic_bid_environment_risk_hits`, `electronic_supervision_trace_risk`, `submission_independence_checklist`, `opening_process_reminder`, `bid_environment_isolation_check`, `ca_lock_usage_independence`, `bill_quantity_software_trace_check`, `print_scan_device_trace_check`, `technical_text_similarity_check` |

这些检查项只能用于：

- internal QA
- bid-document review
- 提交前合规检查
- 低价说明准备
- 电子监管风险提醒

不能用于：

- 规避监管建议
- 规避同源识别
- 绕过平台风控
- 把内部投标文件问题写成公开市场机会事实
- 未经治理直接升级成当前公开证据主链正式规则

## 8. Stage2-3 支撑模块

### 8.1 文件完整性与版本链

保留资料：

- 软件版文件、招标文件、附件、图纸、清单、答疑、补遗、澄清
- 关键附件缺失
- 公告 / 报名 / 投标 / 开标 / 救济时钟

当前用途：

- 文件完整性
- 版本链
- 角色识别
- 下载 / 解析失败 taxonomy

不得越界：

- 不因文件存在就全量深解析
- 不因详情页正文存在就当作完整招标文件正文

候选字段：

- `document_completeness_state`
- `notice_version_chain`
- `clock_chain_profile`
- `missing_attachment_review_request`

### 8.2 资格 / 信用 / 业绩材料

保留资料：

- 资质等级
- 项目经理 / 技术负责人
- 类似业绩
- 业绩时间口径
- 最终用户
- 母子公司 / 总分公司
- 合法分包 / 违法转包
- 社保
- 信用主体
- 无在建承诺
- 证照变更
- 保证金 / 有效期 / 联合体

当前用途：

- Stage3 字段抽取
- Stage4 carrier
- Stage5 review 输入

候选字段：

- `qualification_gap_profile`
- `supplier_material_gap_list`
- `credit_precheck_result`
- `performance_evidence_library`
- `certificate_validity_state`
- `performance_end_user_state`

### 8.3 AI评标与机器审查适配

保留资料：

- 标书可读性
- 结构化响应
- 机器可检测相似性
- AI 自查结果
- 评标报告核验提示

使用边界：

- 可作为 Stage3 parser / Stage5 review 资料
- 不得被写成“AI 已判定违规”

候选字段：

- `ai_review_readability`
- `machine_detectable_similarity`
- `ai_bid_file_check_result`
- `structured_response_score`

### 8.4 地区规则差异与地方画像

保留资料：

- 地区规则画像
- 暗标严格度
- 评分细节密度
- 低价敏感度
- 机器评审信号
- 地区工作量系数
- 地区专项整治强度

候选字段：

- `regional_rule_profile`
- `regional_bid_rule_type`
- `dark_bid_rule_strictness`
- `scoring_detail_density`
- `low_price_region_signal`
- `machine_eval_region_signal`
- `regional_workload_multiplier`
- `regional_enforcement_campaign_signal`

### 8.5 提交与开标流程

这部分不是控标识别，但会直接影响废标、无效响应和二次报价漏处理风险。它应该作为 Stage2-3 支撑模块保留，而不是散落到增强模块或临时操作备注里。

核心判断表：

| 规则 | 判断 | 产品动作 | Stage 归属 |
|---|---|---|---|
| 电子标提前一到两天上传 | 系统、CA、浏览器、驱动、网络、文件大小、签章和加密都可能出问题 | 上传时限提醒 | Stage2/3 |
| 用制作 / 上传环境参加开标 | 减少临时换电脑导致的 CA、驱动、浏览器问题 | 开标环境检查 | Stage2/3 |
| 竞争性磋商、竞争性谈判可能有二次报价 | 上传完不等于结束，漏报可能无效响应或价格分为零 | 二次报价提醒 | Stage3/6 |
| 线下开标资料要带齐 | 公章、身份证、授权委托书、CA、原件备查材料、备用电脑 | 现场清单 | Stage3 |
| 上传、签章、加密、解密记录要留存 | 便于事后复核系统异常或提交争议 | 操作留痕 | Stage2/3 |

当前保留资料：

- 上传前时限提醒
- 开标环境准备
- 二次报价节点
- 现场开标材料清单
- 签章 / 加密 / 解密留痕

候选字段：

- `submission_opening_risk_hits`
- `opening_material_checklist`
- `second_quote_reminder`

## 9. Stage6-9 后置模块

### 9.1 中标后合同与程序风险

保留资料：

- 中标后放弃、递补、不签合同、合同实质变更
- 履约保证金 / 保函
- 总公司中标分公司履约
- 交付后新增授权
- 验收加码
- 后置授权付款障碍

这部分虽然不是投前预测第一优先，但如果目标是“值不值得投”，就不能完全不看中标后的程序陷阱。

核心判断表：

| 场景 | 风险解释 | 产品动作 | Stage 归属 |
|---|---|---|---|
| 中标后放弃 | 影响信用、保证金和后续资格 | 程序风险提示 | Stage6/7 |
| 第二中标候选人递补 | 第一候选失效后，后续程序是否合法、是否有机会递补 | 递补机会和程序检查 | Stage6/7 |
| 合同实质性变更 | 评标结论和最终合同脱钩 | 合同变更风险提示 | Stage7/9 |
| 履约承诺与交付证据脱节 | 中标时承诺能做，实际交付和留痕跟不上 | 履约证据检查 | Stage7/9 |
| 后置授权 / 验收加码 | 交付后被追加授权、证明或本地经销商条件 | 验收卡点提示 | Stage7/9 |

候选字段：

- `post_award_contract_risk_hits`
- `post_award_authorization_gate`
- `acceptance_extra_condition_risk`
- `local_dealer_authorization_risk`
- `award_abandonment_risk_state`
- `second_ranked_supplier_procedure_state`
- `contract_change_substantiveness_check`
- `commitment_delivery_trace_check`

### 9.2 工程结算审计风险

保留资料：

- 不平衡报价
- 固定单价
- 过程资料
- 后补资料
- P 图 / 伪造资料红线

工程类预测不能只看中标概率。对工程项目，还要提前识别“中了以后是否会在结算阶段被打回去”的风险。

核心判断表：

| 场景 | 风险解释 | 产品动作 | Stage 归属 |
|---|---|---|---|
| 不平衡报价 | 评标阶段可能占优，但结算时因工程量变化被反噬 | 结算敏感性提示 | Stage6/7/9 |
| 固定单价合同 | 固定单价不等于无结算风险，仍要看清单偏差和审计口径 | 合同结算风险提示 | Stage7/9 |
| 过程资料不足 | 签证、变更、隐蔽工程、验收记录不足时，结算容易吃亏 | 过程证据提示 | Stage7/9 |
| 后补资料依赖强 | 说明履约阶段取证和归档压力高 | 资料完备性提示 | Stage7/9 |

候选字段：

- `settlement_audit_risk_hits`
- `process_evidence_completeness_state`
- `audit_as_settlement_basis_risk`
- `unbalanced_pricing_settlement_risk`

### 9.3 付款救济与异常低价

保留资料：

- 付款 30/60 日
- 第三方付款条件
- 非现金支付
- 审计作为结算依据
- 保证金形式
- 拖欠救济
- 异常低价触发线
- 成本说明
- 证明材料
- 低价审查归档

这部分当前建议拆成两层：

- 命中明细：`*_hits`
- 聚合判断：`*_profile`

核心判断表：

| 场景 | 风险解释 | 产品动作 | Stage 归属 |
|---|---|---|---|
| 价格策略本身有问题 | 明明靠价格吃单，却没有成本和让利逻辑 | 价格策略预警 | Stage6 |
| 付款条件恶化 | 账期、第三方付款、非现金支付会直接影响现金流 | 回款风险画像 | Stage6/7 |
| 低价能中但不赚钱 | 履约后利润、税费、人工、材料和回款打不过来 | 履约收益检查 | Stage6/7 |
| 异常低价审查被触发 | 要求书面说明和成本证明 | 低价审查准备 | Stage6 |

候选字段：

- `payment_term_violation`
- `third_party_payment_condition_risk`
- `guarantee_cash_only_risk`
- `arrears_complaint_path`
- `price_strategy_warning`
- `payment_risk_profile`
- `delivery_profitability_check`
- `abnormally_low_bid_explanation_required`
- `low_price_evidence_package`
- `quality_delivery_impact_check`
- `abnormal_low_price_trigger`
- `cost_breakdown_ready`
- `materials_labor_cost_evidence`
- `low_price_review_record`

### 9.4 复盘样本库与专项监督

保留资料：

- 驳回案例库
- 质疑条款库
- 对手得分历史
- 流标重招 watchlist
- 串通报价、围标陪标、买标卖标 / 黄牛掮客、参数定制、代理异常、专项整治地区、有奖举报政策

专项整治和举报监督不该只保留成背景说明。对预测产品来说，它们至少应形成“风险强化信号”，用来调整 watchlist 优先级和人工复核顺序。

候选字段：

- `rejection_case_library`
- `complaint_clause_library`
- `competitor_score_history`
- `rebid_watchlist_state`
- `bid_collusion_signal_type`
- `bid_broker_signal`
- `long_term_incumbent_signal`
- `parameter_tailoring_signal`
- `bid_traceability_risk`
- `whistleblower_reward_policy_signal`
- `special_rectification_signal`

## 10. 字段候选总索引

以下字段全部是候选字段，不等于 D2/D3 已正式落仓。

### 10.1 前置分流与公告前机会

- `procurement_regime`
- `procurement_category`
- `legal_system_type`
- `fund_source_type`
- `regulator_type`
- `pre_notice_type`
- `qualification_reviewer`
- `pre_notice_signal`
- `procurement_intention_budget`
- `expected_procurement_time`
- `tender_plan_watchlist`
- `source_channel_type`
- `source_lead_time_band`
- `project_lifecycle_stage`
- `source_quality_score`
- `source_update_latency`

### 10.2 政策规则与评审组织

- `fair_competition_barrier_type`
- `local_protection_signal`
- `ownership_discrimination_signal`
- `market_barrier_remedy_path`
- `demand_investigation_required`
- `demand_objective_quantified`
- `same_contract_count_limit_risk`
- `innovation_no_past_performance_rule`
- `domestic_product_declaration_required`
- `domestic_product_cost_ratio`
- `domestic_price_deduction_20pct`
- `false_declaration_liability`
- `remote_cross_region_eval_applicable`
- `main_sub_venue_responsibility`
- `expert_pool_shared_state`
- `remote_eval_system_failure_risk`
- `owner_representative_eval_risk`
- `expert_supplier_contact_signal`
- `illegal_benefit_transfer_signal`
- `regional_rule_profile`
- `regional_bid_rule_type`
- `dark_bid_rule_strictness`
- `scoring_detail_density`
- `low_price_region_signal`
- `machine_eval_region_signal`
- `regional_workload_multiplier`
- `regional_enforcement_campaign_signal`

### 10.3 项目筛选与项目档案

- `bid_selection_score`
- `bid_selection_reasons`
- `prebid_roi_precheck`
- `prebid_selection_profile`
- `prebid_selection_score`
- `prebid_selection_reasons`
- `watchlist_reason`
- `bid_score_forecast`
- `winnability_band`
- `score_gap_reason`
- `blind_bid_pipeline_stage`
- `bid_team_capacity`
- `document_feedback_strategy`
- `exposure_risk_before_bid`
- `tailored_bid_risk_level`
- `tailored_bid_risk_hits`
- `restrictive_clause_locations`
- `market_substitutability_state`
- `public_attack_surface`
- `evaluation_separation_state`
- `rebid_watchlist_state`
- `ai_collection_field_schema`
- `ai_collection_prompt_profile`
- `ai_output_format_profile`
- `project_category_taxonomy`
- `project_intelligence_folder`
- `owner_actor_profile`
- `competent_department`
- `procurement_actor`
- `agency_actor`
- `competitor_history_profile`
- `incumbent_supplier_signal`
- `project_timeline_chain`
- `followup_record_state`

### 10.4 标书评审与文件内审

- `ai_review_readability`
- `machine_detectable_similarity`
- `ai_bid_file_check_result`
- `structured_response_score`
- `self_score_forecast`
- `score_gap_reasons`
- `review_subjectivity_factors`
- `core_product_brand_map`
- `same_brand_effective_bidder_count`
- `same_brand_candidate_rule`
- `qualification_as_score_factor_risk`
- `score_factor_quantification_check`
- `non_quantifiable_score_item_risk`
- `score_index_completeness`
- `evidence_chain_navigation_score`
- `technical_deviation_locator_state`
- `commercial_evidence_locator_state`
- `price_explanation_locator_state`
- `document_completeness_state`
- `certificate_validity_state`
- `performance_end_user_state`
- `submission_opening_risk_hits`
- `opening_material_checklist`
- `second_quote_reminder`
- `fatal_rejection_risk_hits`
- `expert_review_risk_hits`
- `dark_bid_risk_hits`
- `page_limit_format_state`
- `positive_deviation_quality_state`
- `authorization_signature_risk_hits`
- `watermark_risk_hits`
- `bid_price_consistency_state`
- `declaration_form_risk_hits`
- `financial_tax_audit_risk_hits`

### 10.5 电子监管与制作环境

- `electronic_bid_environment_risk_hits`
- `electronic_supervision_trace_risk`
- `bid_environment_isolation_check`
- `ca_lock_usage_independence`
- `bill_quantity_software_trace_check`
- `print_scan_device_trace_check`
- `technical_text_similarity_check`

### 10.6 报价履约与异常低价

- `payment_risk_level`
- `abnormally_low_bid_explanation_required`
- `low_price_evidence_package`
- `quality_delivery_impact_check`
- `abnormal_low_price_trigger`
- `cost_breakdown_ready`
- `materials_labor_cost_evidence`
- `low_price_review_record`

### 10.7 救济与中标后风险

- `remedy_window_state`
- `challenge_evidence_chain_state`
- `remedy_standing_check`
- `evidence_specificity_level`
- `pre_complaint_step_done`
- `written_objection_formality`
- `remedy_clock_rule_code`
- `remedy_deadline_date`
- `precondition_objection_required`
- `document_conflict_remedy_hint`
- `qualification_legality_risk_hits`
- `subcontract_performance_validity_state`
- `post_award_contract_risk_hits`
- `post_award_authorization_gate`
- `acceptance_extra_condition_risk`
- `local_dealer_authorization_risk`
- `award_abandonment_risk_state`
- `second_ranked_supplier_procedure_state`
- `contract_change_substantiveness_check`
- `commitment_delivery_trace_check`
- `settlement_audit_risk_hits`
- `settlement_audit_risk_profile`
- `process_evidence_completeness_state`
- `payment_term_violation`
- `third_party_payment_condition_risk`
- `audit_as_settlement_basis_risk`
- `guarantee_cash_only_risk`
- `arrears_complaint_path`
- `payment_risk_profile`
- `price_strategy_warning`
- `delivery_profitability_check`
- `unbalanced_pricing_settlement_risk`

### 10.8 合规监督与专项整治

- `bid_collusion_signal_type`
- `bid_broker_signal`
- `long_term_incumbent_signal`
- `parameter_tailoring_signal`
- `bid_traceability_risk`
- `whistleblower_reward_policy_signal`
- `special_rectification_signal`

### 10.9 字段名统一建议表

如果这份文档继续作为“招投标预测”主资料文档，字段命名不建议无差别重写。更稳的做法是：

1. 先固定预测主语义
2. 再区分“正式字段”“兼容别名”“规则码/时钟码”
3. 运行时保留兼容别名，避免一次性打断现有链路

| 分类 | 当前名称 | 建议名称 | 动作 | 说明 |
|---|---|---|---|---|
| 保留 | `procurement_regime`, `procurement_category`, `fund_source_type` | 原样保留 | 不改 | 这些是跨 Stage 可复用的基础分类字段 |
| 保留 | `tailored_bid_risk_level`, `tailored_bid_risk_hits`, `restrictive_clause_locations`, `market_substitutability_state` | 原样保留 | 不改 | 已经贴近预测语义，改名收益不高 |
| 保留 | `submission_opening_risk_hits`, `opening_material_checklist`, `second_quote_reminder` | 原样保留 | 不改 | 语义已经清楚，且和提交流程直接对应 |
| 合并 | `project_selection_reasons`, `bid_selection_reasons` | `prebid_selection_reasons` | 新增主名，旧名保留别名 | 同一语义不应长期保留两套名字 |
| 合并 | `project_roi_precheck`, `bid_selection_profile`, `bid_selection_score` | `prebid_roi_precheck`, `prebid_selection_profile`, `prebid_selection_score` | 文档先统一建议，运行时后续兼容迁移 | 这组字段都属于投前筛选层，建议统一加 `prebid_` 前缀 |
| 合并 | `bid_score_forecast`, `self_score_forecast` | `prebid_score_forecast` | 新增主名，保留别名 | 预测产品里用 `prebid_score_forecast` 更明确 |
| 合并 | `score_gap_reason`, `score_gap_reasons` | `prebid_score_gap_reasons` | 新增主名，旧名兼容 | 单复数混用应该收口 |
| 合并 | `payment_risk_level`, `payment_risk_profile` | `payment_risk_profile` | 聚合层统一为 `profile` | `level` 更适合枚举值，不适合承接全部风险画像 |
| 保留 | `electronic_bid_environment_risk_hits`, `electronic_supervision_trace_risk`, `bid_environment_isolation_check` | 原样保留 | 不改 | 一个用于聚合命中，一个用于细分痕迹和环境隔离，不应互相替代 |
| 合并 | `settlement_audit_risk_hits`, `settlement_audit_risk_profile` | 两层并存 | 保留 `hits` + `profile` | 一个是命中明细，一个是聚合判断，不应硬并成一个 |
| 补齐 | `special_rectification_signal` | 原样保留 | 建议补入 | 专项整治是预测增强信号，不该缺席 |
| 规则码 | `QUAL-001`, `SCORE-001` | 维持规则码 | 不作为业务字段 | 应落到规则码表，不进业务字段集合 |
| 时钟码 | `GOV_PROC_*`, `TENDER_*`, `CANDIDATE_PUBLICITY_MIN_3D` | 维持时钟码 | 不作为业务字段 | 应落到救济时钟 / 时限常量层 |
| 正式对象 | `project_base`, `public_chain`, `rule_hit`, `project_fact`, `saleable_opportunity` | 维持对象名 | 不纳入预测字段层 | 它们是对象层，不是资料池字段层 |

当前建议优先级：

- 文档层立即统一：`prebid_selection_reasons`、`prebid_score_forecast`、`prebid_score_gap_reasons`
- 运行时延后兼容：`project_selection_reasons`、`bid_selection_reasons`、`self_score_forecast`
- 永不混入业务字段：`QUAL-001`、`SCORE-001`、`GOV_PROC_*`、`TENDER_*`

## 11. 证据等级与表达边界

| 证据等级 | 允许表达 | 禁止表达 | 进入 Stage5/6 条件 |
|---|---|---|---|
| 强证据候选 | 公开文件或官方 readback 命中，建议进入复核或质疑评估 | 违法成立、控标成立、必然废标 | 有来源 URL、snapshot/readback、字段血缘、双闸门 |
| 中等证据候选 | 多字段一致但缺关键原文，建议补查或定向解析 | 已确认、已排除、无风险 | 关键字段可回放，缺口进入 review queue |
| 弱线索 | 条款、关键词、经验规则提示疑似风险 | 定性结论、客户可见硬伤 | 只进入 watchlist 或内部 review |
| 阻断 / 未命中 | 源阻断、字段缺失、未命中需复核 | 未发现问题、没有风险 | 必须保留 taxonomy、访问路径和下一步补查建议 |

允许表达：

- 疑似风险
- 命中线索
- 建议核查
- 建议补证
- 建议澄清 / 异议 / 质疑评估
- 建议进入 review queue

禁止表达：

- 内定成立
- 控标成立
- 违法成立
- 必然废标
- 犯罪成立
- 监管处罚已确定
- 付款违约已成立

## 12. 按专题 / SKU 消费矩阵

| 业务证据专题 / SKU | 最该消费的资料类别 | 不应直接消费的内容 |
|---|---|---|
| 投前萝卜标 / 限制竞争预测包 | 两法分流、公告前机会、公平竞争、需求管理、本国产品政策、远程异地评标、项目筛选、控标预测、自评分、废标红线 | 负责人未释放深查、合同付款结算深水区 |
| 综合质疑证据包 | 公平竞争、限制竞争、废标红线、资格条件合法性、异议质疑投诉时钟与证据链、风险表达模板、证据等级建议 | 暗标 / 签章 / 税率等内部文件 QA |
| 证书 / 注册单位 / 时间异常包 | 企业资质、项目经理 / 技术负责人、证书有效期、社保、业绩时间口径、最终用户、母子 / 总分公司边界、信用主体矩阵 | 投前项目筛选和盲投产能 |
| 负责人未释放 / 履约冲突包 | 项目经理 / 技术负责人、无在建承诺、历史业绩、合同履约期限、验收 / 竣工 / 释放证据、后置授权卡点、合同程序风险 | 纯投前筛选和内部盲投经营资料 |
| 信用处罚 / 监管风险包 | 信用中国、严重违法失信、失信被执行人、重大税收违法、专项整治、代理异常、举报监督、围标串标线索 | 无公开回链的地区经验和弱线索 |
| 报价履约 / 异常低价包 | 异常低价触发线、成本证据包、低价审查记录、付款期限、第三方付款条件、不平衡报价、固定单价、结算审计 | 公开证据主链之外的内部规避型建议 |

## 13. 当前不做

- 不再把规则资料拆成多份现行入口
- 不直接把资料池文本抄成正式规则码
- 不绕过 Stage4 carrier、`rule_gate_decision`、`evidence_gate_decision`
- 不把纯投前 watchlist / 自评分 / 盲投运营直接混入 Stage4-5 正式规则资料
- 不把增强模块资料误写成当前公开证据主链已实现能力
- 不提供规避监管、规避同源识别或绕过平台风控的建议

## 14. 维护约定

以后补内容，统一补到本文件对应模块：

- Stage4-5 双闸门资料补到 `5.*`
- 投前预测辅助线资料补到 `6.*`
- 增强模块 / 投标文件内审资料补到 `7.*`
- Stage2-3 支撑资料补到 `8.*`
- Stage6-9 后置资料补到 `9.*`
- 字段候选补到 `10.*`
- 表达边界、证据等级和消费矩阵补到 `11-12`

不在现行区再新增平行规则资料文档。
