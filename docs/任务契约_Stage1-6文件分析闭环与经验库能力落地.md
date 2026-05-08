# 任务契约：Stage1-6 文件分析闭环与经验库能力落地

| 字段 | 值 |
|---|---|
| 文档定位 | 防漂移任务契约 / Stage1-6 文件分析闭环落地顺序 |
| 当前状态 | P4_STAGE16_B7_REAL_SAMPLE_EXECUTION_FIRST_CUT_IMPLEMENTED |
| 主输入 | `docs/专题_投前预测评审风控规则救济与履约结算经验库草案.md` |
| 承载链路 | Stage1 -> Stage2 -> Stage3 -> Stage4 -> Stage5 -> Stage6 |
| 机器镜像 | `control/stage16_file_analysis_task_contract.yaml` |
| 不替代 | `control/current_task.yaml`、正式 D2/D3/D13、contracts、release gate |
| 冲突处理 | 本文件为当前唯一人类可读任务契约；旧专题契约已删除，不再作为引用面 |

## 1. 总目标

先把 Stage1-6 跑成稳定的文件分析闭环：

`候选发现 -> 公开页面/附件快照 -> 文件解析和字段血缘 -> 公开核验 carrier -> 规则门/证据门 -> Stage6 事实报告和复核队列`

经验库草案是能力池，不是单阶段需求。当前开发优先把能进入公开证据链的能力落到 Stage1-6；内部投标文件 QA、规则救济与履约结算已作为内部复核第一刀接入，但不进入公开证据主链，也不输出法律、监管处罚或付款违约结论。

## 2. 防漂移硬规则

1. 继续使用 Stage1-9 主链，不新造第二套阶段体系。
2. 本文件只约束开发顺序和验收边界，不作为动态项目状态源。
3. 经验库草案先作为候选规则池，不直接升级为正式 D2/D3 规则源。
4. Stage2 必须保留附件、hash、来源 URL、版本链、下载失败原因和快照回放能力。
5. Stage3 只做解析、归一和字段血缘，不输出违法、内定、必废标等结论。
6. Stage4 只生成公开核验 carrier/readback，不能直接变成正式结论。
7. Stage5 必须区分 `rule_gate_decision` 和 `evidence_gate_decision`，字段命中不等于风险成立。
8. Stage6 才能形成统一 `project_fact`、复核队列、风险报告和给 Stage7 的商业钩子输入。
9. Stage7-10 能力不得反向污染 Stage1-6 完成标准。
10. 新增正式字段、对象、枚举、schema、migration、规则码或跨阶段机器契约前，必须先定位现有 contracts、tests、scripts 和调用链。
11. 对外触达、支付、交付、退款、线索包外发、客户下载仍受 release checklist、审批链、审计链和 operator action 约束。

## 3. 批次顺序

| 批次 | 名称 | 主阶段 | 优先级 | 完成后得到什么 |
|---|---|---:|---|---|
| 0 | 经验库到现有系统映射基线 | Stage1-6 | P0 | 入口、调用链、对象、样本、脚本和缺口表 |
| 1 | 两法体系分流器 | Stage1-3/6 | P0 | 法律体系、采购类别、采购方式、监管和救济路径候选 |
| 2 | 公告前机会与政策规则层 | Stage1-3/6 | P0 | 采购意向、招标计划、政策规则、地区画像、来源质量 |
| 3 | AI 情报采集与项目档案 | Stage1-3/7 | P0 | 项目档案、来源质量、分类标签、时间节点链 |
| 4 | 文件完整性、版本链与字段血缘 | Stage2-3 | P0 | 附件归档、文件解析、字段血缘、失败分类 |
| 5 | 主线风险能力层 | Stage3-6/7 | P1 | 项目筛选、控标预测、自评分基础、废标红线 |
| 6 | 公开核验、双闸门与 Stage6 报告 | Stage4-6 | P1 | 公开证据、规则门、证据门、复核队列、报告 |
| 7 | 复盘样本库 | Stage1-6 | P1 | 中标、废标、投诉、流标、官方案例回归样本 |
| 8 | 报价履约与异常低价 | Stage3-6/9 | P2 | 低价、不平衡报价、付款和履约风险 |
| 9 | 投标文件内审增强 | Stage3/6/增强模块 | P3 | 暗标、正偏离、授权签章、声明函、税率审计、电子标制作环境 |
| 10 | 规则救济与履约结算 | Stage3/6/7/9 扩展 | P3 | 异议质疑投诉、合同加码、结算审计、付款救济 |

当前已推进 **第 0 到第 10 批** 的第一刀。第 10 批只作为内部复核 profile/trace，不抢 Stage5 正式规则和客户可见结论。

### 3.1 当前实施状态

| 批次 | 当前状态 | 说明 |
|---:|---|---|
| 0 | 已完成第一刀 | 已补能力到代码、数据载体、缺口和验证命令的映射基线 |
| 1 | 已完成第一刀 | 已有两法体系、资金来源、监管路径和救济路径候选；后续补真实样本和细分规则 |
| 2 | 已完成第一刀 | 已有公告前线索、来源渠道、生命周期和来源质量候选；政策规则细化后续接入 |
| 3 | 已完成第一刀 | 已建立内部项目档案 trace，不替代原始证据 |
| 4 | 已完成第一刀 | 已补附件语义角色、下载归档摘要和版本链状态 |
| 5 | 已完成第一刀 | 已有项目筛选、控标预测、自评分和废标红线内部候选 profile/trace |
| 6 | 已完成第一刀 | 已在 Stage6 内部 trace 中收束公开核验读回、双闸门、B5 profile、报告和复核队列摘要 |
| 7 | 已完成执行第一刀 | 已接入现有 `evaluation_corpus`，补离线探针、覆盖审计和真实项目快照受控执行 runner；后续补覆盖率、质量评分和更多站点 |
| 8 | 已完成第一刀 | 已在主线内部 profile/trace 中补异常低价、不平衡报价、付款履约复核线索 |
| 9 | 已完成第一刀 | 已有内部投标文件 QA profile/trace；只做内部复核，不进入公开证据主链 |
| 10 | 已完成第一刀 | 已有规则救济、资格合法性、合同程序、结算审计、履约付款和专项监督内部 profile/trace；不做法律或付款违约定性 |

## 4. 能力矩阵

能力矩阵用于防止“看到一个能力就马上开发”。每个能力必须先落到阶段、输入证据、候选输出和当前优先级，再决定是否进入代码。

| 能力块 | 对应批次 | 主阶段 | 当前定位 | 主要输入 | 候选输出 | 当前是否主线 |
|---|---:|---|---|---|---|---|
| 两法体系分流器 | 1 | Stage1-3/6 | 所有规则判断的前置分类 | 公告标题、采购方式、资金来源、采购人/招标人、平台类型、附件文本 | `procurement_regime`、`procurement_category`、`legal_system_type_candidate`、`fund_source_type`、`regulator_route_candidate`、`remedy_path_candidate` | 是，P0 |
| 公告前机会层 | 2 | Stage1-3/6 | 把机会发现提前到采购意向、招标计划、提前公示 | 采购意向、招标计划、重大项目清单、审批/用地/规划、新闻、设计/咨询中标 | `pre_notice_type`、`source_channel_type`、`project_lifecycle_stage`、`source_quality_score` | 是，P0 |
| 公平竞争审查层 | 2 | Stage3-6 | 控标预测和救济判断的政策规则线索 | 资格条件、评分办法、区域/所有制/产地限制、指定工具或本地化要求 | `fair_competition_barrier_type`、`policy_rule_signal`、review 建议 | 是，P0/P1 |
| 需求管理控标层 | 2 | Stage3-6 | 控标源头识别 | 采购需求、需求调查要求、参数量化、同类业绩数量、创新产品限制 | `policy_rule_signal`、`tailored_bid_risk_level`、需求补证建议 | 是，P1 |
| 地区规则画像 | 2 | Stage1-6 | 工作量和规则侧重点画像 | 地方平台规则、历史样本、地区暗标/低价/细则/机器评标特征 | `regional_bid_rule_type`、地区工作量提示、复核建议 | 是，P1 |
| AI 机器审查适配 | 2/9 | Stage3-6 / 增强模块 | 官方政策和公开平台检测进主链；投标文件自查作为内部增强 | 官方 AI 政策、平台检测规则、招标文件检测项、投标文件结构化程度 | `ai_review_readability`、`machine_detectable_similarity`、`ai_bid_file_check_result`、`structured_response_score` | 主链只接政策/平台规则；自查只做内部 QA |
| 项目来源库 | 3 | Stage1-3/7 | 多渠道线索池 | 招标网站、政府采购网、公共资源、发改/住建/自然资源、土地、行业平台、上下游线索 | `source_channel_type`、`source_quality_score`、`project_lifecycle_stage` | 是，P0 |
| AI 采集与项目档案 | 3 | Stage1-3/7 | 内部情报整理，不替代证据 | 统一字段模板、来源 URL、快照、项目分类、业主/代理/对手/时间节点 | `project_intelligence_folder`、`project_category_taxonomy`、`owner_actor_profile`、`agency_actor`、`competitor_history_profile`、`project_timeline_chain` | 是，P0 |
| 文件完整性与版本链 | 4 | Stage2-3 | 文件分析闭环的底座 | 公告详情页、附件、补遗答疑、候选公示、评标报告、图纸清单 | `attachment_snapshot_refs`、`document_completeness_state`、`notice_version_chain`、`download_archive_manifest` | 是，P0 |
| 字段解析与血缘 | 4 | Stage3 | 所有风险字段的证据来源 | HTML/PDF/Word/Excel/OCR 文本、页码、文本切片、置信度 | `field_lineage_record`、`parsed_fields`、`parse_state`、`parse_error_taxonomy` | 是，P0 |
| 项目筛选与盲投运营 | 5 | Stage3-6/7 | 内部投入产出和胜率风险分层 | 项目金额、地区、采购方式、主客观分、价格分、付款、重招/流标、团队产能 | `bid_selection_score`、`blind_bid_pipeline_stage`、投入产出建议 | 是，P1 |
| 控标预测 | 5 | Stage3-6/7 | 公开文件中的疑似指向性线索 | 参数、资质、业绩、人员、厂家授权、ISO/CMA、现场踏勘、本地服务、评分细则 | `tailored_bid_risk_level`、`qualification_clause_hits`、控标线索说明 | 是，P1 |
| 自评分 | 5 | Stage3-6/7 | 基于我方材料库的内部预测 | 评分办法、我方资质/业绩/人员/方案/报价、证明材料 | `self_score_forecast`、`evaluation_method_profile`、材料缺口 | 是，P1 |
| 废标红线 | 5 | Stage3-6 | 实质性响应和无效风险识别 | 资格审查表、符合性审查表、星号条款、签章格式、保证金、有效期、二次报价规则 | `fatal_rejection_risk_hits`、废标/扣分/澄清/争议分类 | 是，P1 |
| 公开核验与双闸门 | 6 | Stage4-6 | 把规则命中变成可复核事实 | 公开查询、附件 readback、项目经理/资质/信用/业绩核验、规则命中 | `public_evidence_readback`、`rule_gate_decision`、`evidence_gate_decision`、`review_request` | 是，P1 |
| Stage6 报告与复核队列 | 6 | Stage6 | 对内事实报告和 Stage7 输入 | Stage4 carrier、Stage5 双闸门、证据缺口、人工复核意见 | `project_fact`、`review_queue_profile`、`report_record`、`challenger_candidate_profile` | 是，P1 |
| 复盘样本库 | 7 | Stage1-6 | 回归和规则校准 | 中标、废标、投诉、流标、官方案例、地区规则样本 | `evaluation_corpus`、`golden_samples`、规则校准样本 | 可同步准备，不阻塞 |
| 报价履约与异常低价 | 8 | Stage3-6/9 | 价格和履约风险扩展 | 报价、成本、低价审查记录、付款条款、工程清单、结算资料 | `price_performance_risk_profile`、`abnormal_low_price_trigger`、`cost_breakdown_ready`、`low_price_review_record`、付款风险提示 | 已完成第一刀 |
| 投标文件内审增强 | 9 | Stage3/Stage6/增强模块 | 投标人内部标书 QA | 内部标书、暗标格式、正偏离、授权签章、声明函、税率审计、电子标制作环境、AI 可读性 | `bid_document_internal_qa_profile`、`dark_bid_risk_hits`、`positive_deviation_quality_state`、`authorization_signature_risk_hits`、`declaration_form_risk_hits`、`financial_tax_audit_risk_hits`、`electronic_bid_environment_risk_hits`、`ai_review_readability` | 已完成第一刀，内部增强 |
| 规则救济与履约结算 | 10 | Stage3/6/7/9 扩展 | 程序保护、合同和结算风险内部复核 | 公告/招标文件、质疑/异议材料、合同、验收、付款、签证变更、审计资料、专项整治公告 | `remedy_performance_settlement_profile`、`remedy_window_state`、`challenge_evidence_chain_state`、`qualification_legality_risk_hits`、`post_award_contract_risk_hits`、`settlement_audit_risk_hits`、`payment_term_violation`、`whistleblower_reward_policy_signal` | 已完成第一刀，内部复核 |

当前开发判断：

1. **必须先做**：第 0 到第 4 批。没有映射、两法分流、公告前线索、项目档案和文件血缘，后面所有风险判断都会漂。
2. **随后做完整主链**：第 5 到第 6 批。项目筛选、控标预测、自评分、废标红线必须经过公开核验和双闸门，最终落到 Stage6 报告。
3. **已同步沉淀样本执行第一刀**：第 7 批。样本库服务回归，不改变当前产品完成标准；真实快照已具备受控执行、解析和审计 manifest 闭环。
4. **内部增强已接入**：第 9、10 批已完成第一刀，但只作为内部 QA/复核 profile，不作为 Stage1-6 公开文件分析闭环的前置完成条件，也不进入 Stage5 正式规则。

## 5. Stage4-5 规则化边界

不是所有经验库能力都能直接变成 Stage5 规则。进入规则层前必须先判断它属于“前置分类/字段”“Stage4 核验 carrier”还是“Stage5 规则”。

### 5.1 规则化准入标准

能力要进入 Stage5 规则，必须同时满足：

- 有明确触发条件：能写成可判断的字段、阈值、条款命中或状态组合。
- 有公开证据：来自公告、招标文件、补遗答疑、公开平台、官方政策或已固定附件。
- 有字段血缘：能回链到 `source_url`、snapshot/hash、附件页码、文本切片或公开核验 readback。
- 有规则依据：正式法规、公开平台规则、项目文件条款或稳定内部治理规则；非正式经验只能作为弱线索。
- 有保守输出：只输出 `CLUE`、`OBSERVATION`、`REVIEW_REQUEST`、`PASS/REVIEW/BLOCK` 等内部状态，不输出违法、内定、犯罪、必废标等定性。
- 可过双闸门：`rule_gate_decision` 判断规则前提是否成立，`evidence_gate_decision` 判断证据是否足够、可审计、可回放。

不满足以上条件的能力，只能先做候选字段、画像、watchlist、review 提示或后置增强能力。

### 5.2 三类能力分流

| 类型 | 进入阶段 | 处理方式 | 代表能力 | 是否进入 Stage5 规则 |
|---|---|---|---|---|
| 前置分类/字段 | Stage1-3 | 作为后续规则适用条件、画像或关注池 | 两法分流、公告前机会、项目来源库、AI 项目档案、地区画像 | 不直接进入 |
| Stage4 核验 carrier | Stage4 | 生成公开核验 readback，给 Stage5 消费 | 项目经理、资质、信用、业绩、主体信息、公开文件引用 | 不直接定性，作为规则输入 |
| Stage5 规则 | Stage5 | 生成 `rule_hit`、`rule_gate_decision`、`evidence_gate_decision`、`review_request` | 证据完整性、两法适用门、资格/项目经理、废标红线、控标弱规则、公平竞争 review | 可以进入 |
| Stage6 报告 | Stage6 | 汇总事实、风险摘要、复核队列和补证建议 | `project_fact`、`review_queue_profile`、`report_record` | 消费规则结果 |
| 后置增强 | Stage3/6 内部 QA、Stage7-10 或增强模块 | 保留接口意识，不作为当前闭环前置 | 暗标、签章、声明函、电子监管、合同付款、结算审计、救济时钟 | 不进入 Stage5 正式规则 |

### 5.3 第一批规则化范围

第一批只允许规则化以下五类，避免范围失控：

| 规则化能力 | 规则定位 | Stage4 输入 | Stage5 输出边界 |
|---|---|---|---|
| 证据完整性规则 | 证据门底座 | 附件、hash、版本链、字段血缘、readback | 证据不足时 `REVIEW` 或 `BLOCK`，不产出业务定性 |
| 两法适用门规则 | 规则适用前置 | 法律体系、采购方式、资金来源、监管路径候选 | 制度不明时阻止套用具体规则，进入 review |
| 项目经理/资格核验规则 | 资格/人员风险 | 项目经理、证书、资质、信用、业绩公开核验 | 输出资格/人员疑点或材料缺口，不写违规成立 |
| 废标红线规则 | 实质性响应风险 | 资格审查表、符合性审查表、星号条款、保证金、有效期、二次报价 | 区分一票否决、扣分、澄清、形式瑕疵、争议项 |
| 控标/限制竞争弱规则 | 疑似指向性线索 | 厂家授权、ISO/CMA、现场踏勘、本地服务、本地业绩、特定证书、参数细化 | 只输出疑似指向性/建议复核/质疑评估 |

这五类规则必须先有 Stage4 carrier 或 Stage3 字段血缘，不能从模型摘要或人工判断直接生成 `rule_hit`。

### 5.4 暂不规则化能力

以下能力暂不进入 Stage1-6 当前规则主线：

- 暗标、正偏离、授权签章、声明函、税率审计、电子监管、制作环境隔离：属于投标文件内审增强，依赖投标人内部材料；B9 只做内部 QA profile/trace，不进入 Stage5 正式规则。
- 完整异议质疑投诉、合同加码、验收授权、付款、结算审计：B10 已做内部复核第一刀；正式规则化、期限计算、材料真实性核验和客户可见表达仍后置。
- 地区好投/难投、内幕关系、内定结论、刑事定性：不得作为规则输出。
- AI 生成判断、评论区、非正式经验材料：只能作为关键词、弱线索或 review 提示。

## 6. 第 0 批：映射基线

目标：先把经验库能力和现有系统接上，不急着写大功能。

必须完成：

- 定位 Stage1 候选发现、真实样本入口和 fixture 来源。
- 定位 Stage2 附件发现、下载、归档、challenge 处理、失败分类入口。
- 定位 Stage3 HTML/PDF/Word/Excel/OCR 解析和字段血缘入口。
- 定位 Stage4 项目经理/负责人、资质、信用、业绩、附件证据 carrier。
- 定位 Stage5 规则门、证据门、review request。
- 定位 Stage6 `project_fact`、报告、复核队列。
- 列出现有脚本和最小验证命令，优先复用 `scripts/`。

完成标准：

- 形成“能力 -> 阶段 -> 现有代码/契约 -> 缺口 -> 验证命令”的映射表。
- 说明哪些能力是现有主链细化，哪些是新增能力候选。
- 不新增正式 schema/枚举/规则码。

### 6.1 第一刀映射基线表

| 能力 | 阶段 | 现有入口 | 数据载体 | 已实现状态 | 缺口 | 最小验证命令 |
|---|---|---|---|---|---|---|
| 两法体系分流器 | Stage1-3/6 | `src/stage1_tasking/extractors.py`、`src/stage1_tasking/service.py`、`src/stage3_parsing/real_parser.py` | `legal_system_type_candidate`、`fund_source_type`、`regulator_route_candidate` | 已完成第一刀 | 继续补真实平台样本和细分救济路径校准 | `python -m unittest tests.test_stage1_legal_system_classifier tests.test_stage12_extractors -v` |
| 公告前机会与政策规则层 | Stage1-3/6 | `src/stage1_tasking/extractors.py`、`src/stage2_ingestion/real_candidate_capture.py`、`src/stage6_fact_review/service.py` | `pre_notice_type`、`source_channel_type`、`project_lifecycle_stage`、`source_quality_score` | 已完成第一刀 | 政策规则仍是候选线索，后续再规则化 | `python -m unittest tests.test_stage1_legal_system_classifier tests.test_stage12_extractors -v` |
| AI 情报采集与项目档案 | Stage1-3/6 | `src/stage3_parsing/real_parser.py`、`src/stage6_fact_review/service.py` | `project_intelligence_folder`、`project_intelligence_state`、`project_intelligence_missing_reasons` | 已完成第一刀 | 只用公开字段形成内部档案，不补造业主、代理或对手事实 | `python -m unittest tests.test_stage2_real_candidate_capture tests.test_stage3_real_parser -v` |
| 文件完整性与版本链 | Stage2-3/6 | `src/stage2_ingestion/real_candidate_capture.py`、`src/stage3_parsing/real_parser.py`、`src/stage6_fact_review/service.py` | `document_completeness_state`、`download_archive_manifest`、`attachment_role_type`、`notice_version_chain_state` | 已完成第一刀 | 真实站点下载失败和 `OCR_REQUIRED` 继续 review | `python -m unittest tests.test_stage2_real_candidate_capture tests.test_stage3_real_parser -v` |
| 主线风险能力层 | Stage3-6 | `src/stage3_parsing/mainline_risk.py`、`src/stage6_fact_review/service.py` | `mainline_risk_profile`、`bid_selection_state`、`tailored_bid_risk_level`、`fatal_rejection_risk_hits` | 已完成第一刀 | 自评分缺我方材料不运行；控标只输出弱线索 | `python -m unittest tests.test_stage56_evaluators tests.test_stage5_rule_factory_expansion -v` |
| 公开核验、双闸门与 Stage6 报告 | Stage4-6 | `src/stage6_fact_review/fact_aggregator.py`、`src/stage6_fact_review/service.py` | `stage6_real_public_rule_evidence_readback_summary`、`stage16_file_analysis_report_profile`、`stage16_b6_closure_profile` | 已完成第一刀 | 客户报告产品化仍后置 | `python -m unittest tests.test_stage56_evaluators tests.test_stage6_product_package_hardening -v` |
| 复盘样本库 | Stage1-6 | `contracts/evaluation/evaluation_corpus_seed.json`、`contracts/evaluation/evaluation_coverage_requirements.json`、`src/storage/evaluation_corpus.py`、`src/storage/evaluation_coverage_audit.py`、`src/storage/evaluation_real_sample_execution.py`、`src/stage1_tasking/real_candidate_discovery.py`、`src/stage2_ingestion/real_candidate_capture.py`、`src/stage3_parsing/evaluation_profiles.py` | `evaluation_corpus`、`evaluation_parse_probe_manifest`、`evaluation_seed_coverage_audit_manifest`、`evaluation_stage3_profile_manifest`、`evaluation_real_project_sample_plan_manifest`、`evaluation_real_project_sample_execution_manifest` | 已完成执行第一刀 | 真实快照受控执行第一刀完成；后续补覆盖率、质量评分和更多站点 | `python -m unittest tests.test_evaluation_real_sample_plan tests.test_evaluation_real_sample_execution tests.test_stage1_real_candidate_discovery tests.test_stage2_real_candidate_capture -v` |
| 报价履约与异常低价 | Stage3/6 | `src/stage3_parsing/mainline_risk.py`、`src/stage6_fact_review/fact_aggregator.py` | `price_performance_risk_profile`、`payment_risk_level`、`abnormal_low_price_trigger`、`unbalanced_bid_risk_hits`、`cost_breakdown_ready`、`low_price_review_record` | 已完成第一刀 | 只做公开文本内部复核线索；正式规则化、成本材料和客户可见报告后续推进 | `python -m unittest tests.test_stage1_legal_system_classifier tests.test_stage56_evaluators -v` |
| 投标文件内审增强 | Stage3/6/增强模块 | `src/stage3_parsing/bid_document_qa.py`、`src/stage3_parsing/service.py`、`src/stage6_fact_review/fact_aggregator.py` | `bid_document_internal_qa_profile`、`dark_bid_risk_hits`、`positive_deviation_quality_state`、`authorization_signature_risk_hits`、`declaration_form_risk_hits`、`financial_tax_audit_risk_hits`、`electronic_bid_environment_risk_hits`、`ai_review_readability` | 已完成第一刀 | 只消费内部投标文件文本，不进入公开证据主链，不生成客户可见废标或违法结论 | `python -m unittest tests.test_stage1_legal_system_classifier tests.test_stage56_evaluators -v` |
| 规则救济与履约结算 | Stage3/6/7/9 | `src/stage3_parsing/remedy_performance.py`、`src/stage3_parsing/service.py`、`src/stage6_fact_review/fact_aggregator.py` | `remedy_performance_settlement_profile`、`remedy_window_state`、`challenge_evidence_chain_state`、`qualification_legality_risk_hits`、`post_award_contract_risk_hits`、`settlement_audit_risk_hits`、`payment_term_violation`、`whistleblower_reward_policy_signal` | 已完成第一刀 | 只做救济、合同、结算、付款和监督内部复核线索；正式规则化和客户可见表达后续评估 | `python -m unittest tests.test_stage1_legal_system_classifier tests.test_stage56_evaluators tests.test_stage16_file_analysis_task_contract -v` |

## 7. 第 1 批：两法体系分流器

目标：所有后续规则判断前，先判断项目适用的制度路径。

候选输出：

- `procurement_regime`
- `procurement_category`
- `legal_system_type_candidate`
- `fund_source_type`
- `regulator_route_candidate`
- `remedy_path_candidate`

完成标准：

- 能区分政府采购法体系、招标投标法体系、政府采购工程、国企/平台采购、混合/未知场景。
- `legal_system_type_candidate` 只是辅助标签，不替代 D2/D13 正式字段。
- 制度不明时输出 review 或补证建议，不套用单一招投标规则。
- 救济路径区分政府采购质疑/投诉与招标投标异议/投诉。

## 8. 第 2 批：公告前机会与政策规则层

目标：把项目发现提前到采购意向、招标计划、提前公示和政策规则线索。

候选输出：

- `pre_notice_type`
- `source_channel_type`
- `project_lifecycle_stage`
- `policy_rule_signal`
- `fair_competition_barrier_type`
- `regional_bid_rule_type`
- `source_quality_score`

完成标准：

- 采购意向、招标计划、招标文件提前公示只进入关注池，不写成确定项目。
- 重大项目清单、审批/用地/规划、土地、新闻、设计/咨询中标、行业官网只能作为公告前线索。
- 公平竞争、需求管理、本国产品政策、远程异地评标、AI机器审查必须有正式政策或公开平台规则回链。
- 地区画像只能表达“历史样本或平台规则显示某类侧重点”，不得写成地区好投/难投。

## 9. 第 3 批：AI 情报采集与项目档案

目标：用 AI 辅助收集、清洗、分类和整理，不替代判断。

候选输出：

- `project_intelligence_folder`
- `project_category_taxonomy`
- `owner_actor_profile`
- `agency_actor`
- `competitor_history_profile`
- `project_timeline_chain`
- `followup_record_state`

完成标准：

- AI 输出必须保留 `source_url`、快照或字段血缘。
- 项目档案至少包含基础信息、人员信息、竞争情报、时间节点和跟进记录。
- 圈子、社群、评论区、非正式经验材料只能作为弱线索或关键词来源。
- 不把 AI 生成表格当作原始证据。

## 10. 第 4 批：文件完整性、版本链与字段血缘

目标：既然为了项目经理要下载文件，就把文件变成全链路证据资产。

候选输出：

- `attachment_snapshot_refs`
- `document_completeness_state`
- `notice_version_chain`
- `download_archive_manifest`
- `field_lineage_record`
- `parsed_fields`
- `parse_state`
- `parse_error_taxonomy`

完成标准：

- 能识别详情页附件，并区分招标文件、答疑、补遗、评标报告、候选公示、图纸/清单等类别。
- 每个附件记录 hash、来源 URL、下载时间、文件名、content-type、项目和公告版本绑定关系。
- PDF、Word、Excel、HTML 进入统一解析流程；扫描件进入 `OCR_REQUIRED` 或受控 OCR 流程。
- 字段可回链到附件、页码、文本切片和置信度。
- 下载或解析失败必须有原因分类，不假装成功。

## 11. 第 5 批：主线风险能力层

目标：从下载文件中抽取可用于投前判断的公开风险结构。

候选输出：

- `bid_selection_score`
- `tailored_bid_risk_level`
- `qualification_clause_hits`
- `evaluation_method_profile`
- `fatal_rejection_risk_hits`
- `abnormal_low_price_trigger`
- `self_score_forecast`
- `blind_bid_pipeline_stage`

完成标准：

- 项目筛选不得承诺中标率，只能给内部投入产出和风险分层。
- 控标预测只能输出疑似指向性、排他性、资料不对称或市场替代性线索。
- 自评分必须基于我方材料库或明确内部输入；没有材料证据不得假算得分。
- 废标红线区分一票否决、扣分、澄清补正、形式瑕疵和事后争议难度。
- 项目经理/负责人抽取、资格/信用/业绩材料继续作为核心输入。
- 评分办法至少拆出商务分、技术分、价格分、主观分、客观分。

## 12. 第 6 批：公开核验、双闸门与 Stage6 报告

目标：把 Stage4/5 的核验和规则结果收束成 Stage6 可读报告。

候选输出：

- `public_evidence_readback`
- `focus_bidder_verification_profile`
- `rule_hit`
- `rule_gate_decision`
- `evidence_gate_decision`
- `review_request`
- `project_fact`
- `review_queue_profile`
- `report_record`
- `legal_action_recommendation`
- `challenger_candidate_profile`

完成标准：

- 公开核验 carrier 可回放。
- Stage5 同时给出规则门和证据门结果。
- Stage6 汇总成统一事实、风险摘要、复核队列和补证建议。
- 报告表达保守：使用“疑似”“建议核查”“证据不足”“进入人工复核”，不写死违法、内定、必废标。
- 可为 Stage7 提供商业钩子输入，但不执行真实触达。

## 13. 后置批次边界

第 7 到第 10 批不是 Stage1-6 文件分析闭环的完成前置条件。

- 第 7 批：复盘样本库已完成真实快照受控执行第一刀，不阻塞第 1 到第 6 批；后续补覆盖率、质量评分和更多站点。
- 第 8 批：报价履约与异常低价已完成第一刀；当前只识别公开文本复核线索，成本材料和正式规则化后续推进。
- 第 9 批：投标文件内审增强已完成第一刀，只做内部 QA profile/trace，依赖投标人内部标书材料，不进入公开证据主链。
- 第 10 批：规则救济与履约结算已完成第一刀，当前只做公开文本和可选内部材料的复核线索；正式法律规则化、合同履约材料核验和客户可见表达后续评估。

## 14. 每批通用验收

每一批完成前至少满足：

- 有对应测试或最小验证命令。
- 有正向样本、缺失样本、冲突样本或 review 样本之一。
- 字段或风险结果有来源、血缘或 readback。
- 失败路径不静默通过。
- 不改变对外/live、触达、支付、交付、退款边界。
- `git diff --check` 通过。

## 15. 当前默认下一步

默认下一步推进 **B4 附件/OCR 稳定性增强，或 B5/B8/B10 正式规则化评估**：如果继续补主链稳定性，优先强化真实附件下载失败、扫描件、OCR_REQUIRED 和版本链质量；如果继续能力产品化，再评估主线风控、报价履约、救济结算中哪些线索可以进入 Stage4/5 双闸门正式规则。

除非人类明确要求，否则不要跳到真实触达交付、对外发布、支付、自动退款或客户可见结论。
