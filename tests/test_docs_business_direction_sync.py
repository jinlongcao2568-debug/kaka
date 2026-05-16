from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ARCHIVE_NON_CURRENT = ROOT / "archive" / "non_current_docs"
CONTRACT_REF = "contracts/evaluation/business_direction_strategy_contract.json"
HUMAN_REF = "docs/业务方向_候选公示后证据包与投前预测双线契约.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_p0_entry_docs_reference_business_direction_contracts() -> None:
    paths = [
        DOCS / "专题_Stage1-2_来源覆盖与采集路由.md",
        DOCS / "专题_规则经验库候选池_投前评审履约.md",
        DOCS / "AX9S_产品主图与验收总则.md",
        DOCS / "文档与资产状态板.md",
    ]

    for path in paths:
        text = _read(path)
        assert HUMAN_REF in text or CONTRACT_REF in text, path


def test_ax9s_product_map_locks_sku_design_decisions() -> None:
    text = _read(DOCS / "AX9S_产品主图与验收总则.md")

    assert "业务证据 SKU" in text
    assert "LeadPack SKU-A/B/C" in text
    assert "程序时间线/公示流程缺陷包" in text
    assert "竞争格局/陪标围标线索包" in text
    assert "社保造假" in text
    assert "不单独作为首批 SKU" in text
    assert "证书/注册单位/时间异常包 -> 负责人未释放/履约冲突宽筛" in text
    assert "负责人未释放深查只在宽筛命中同人/同主体/时间窗口疑似重叠后触发" in text
    assert "这条链不得默认全量下载 01-12，也不得默认解析 `08`" in text


def test_stage19_l2_blueprint_locks_subfunnel_guardrails() -> None:
    text = _read(DOCS / "AX9S_Stage1-9_执行矩阵与子漏斗.md")

    assert "Stage1-9 子漏斗图纸总览" in text
    assert "Stage1 候选池" in text
    assert "Stage2 公开载体" in text
    assert "Stage2.5 AnalysisStrategyPlan" in text
    assert "Stage3 字段血缘" in text
    assert "Stage4 公开核验" in text
    assert "Stage5 双闸门" in text
    assert "Stage6 project_fact" in text
    assert "Stage7 商业钩子" in text
    assert "Stage8 触达准备" in text
    assert "Stage9 交付治理" in text
    assert "REVIEW/BLOCK 补证回退" in text
    assert "AnalysisStrategyPlan 硬闸门" in text
    assert "当前项目 07 入池后的 01-12" in text
    assert "历史项目定向找负责人、工期、释放证据" in text
    assert "Stage8/9 不代表自动外发" in text
    assert "业务证据 SKU 决定 Stage1-6 证据路线" in text
    assert "`LeadPack SKU-A/B/C` 只决定 Stage7 后商业包装" in text


def test_docs_default_read_order_downranks_historical_noise() -> None:
    readme = _read(ROOT / "README.md")
    status_board = _read(DOCS / "文档与资产状态板.md")
    sync_plan = _read(ARCHIVE_NON_CURRENT / "文档方向同步与合并治理计划.md")
    start_checklist = _read(ARCHIVE_NON_CURRENT / "开工前总清单.md")
    conditional_go = _read(ARCHIVE_NON_CURRENT / "正式业务代码开发开工裁决页.md")
    task_packet_template = _read(ARCHIVE_NON_CURRENT / "自动开发任务包模板.md")

    assert "默认不要遍历 `docs/` 全部文件" in readme
    assert "当前默认读序与非默认入口" in status_board
    assert "HISTORICAL_PRE_START_REFERENCE" in status_board
    assert "HISTORICAL_CONDITIONAL_GO_SNAPSHOT" in status_board
    assert "MERGED_REFERENCE" in status_board
    assert "TASK_PACKET_TEMPLATE_ONLY" in status_board
    assert "AUXILIARY_RULE_CANDIDATE_POOL" in status_board

    assert "MERGED_REFERENCE" in sync_plan
    assert "普通开发不要把本文件当默认入口" in sync_plan
    assert "direct-dev" in start_checklist
    assert "普通开发不要把本文件当默认入口" in start_checklist
    assert "HISTORICAL_CONDITIONAL_GO_SNAPSHOT" in conditional_go
    assert "不是当前仓库总体 readiness 的唯一状态源" in conditional_go
    assert "TASK_PACKET_TEMPLATE_ONLY" in task_packet_template
    assert "普通 `DIRECT_DEV_DEFAULT` 开发不需要读取或填写本模板" in task_packet_template


def test_ax9s_topic_docs_lock_single_source_ownership() -> None:
    readme = _read(ROOT / "README.md")
    status_board = _read(DOCS / "文档与资产状态板.md")

    assert "AX9S / 专题文档单源归属表" in readme
    assert "AX9S / 专题文档单源归属表" in status_board
    assert "L1 产品主图 / 总口径 / 当前能力快照" in status_board
    assert "L2 执行矩阵 / 子漏斗 / PASS-REVIEW-BLOCK" in status_board
    assert "L3 Stage4/5 专项 SOP" in status_board
    assert "导航资产 / 当前主线顺序图" in status_board
    assert "历史设计稿 / 143D 设计依据" in status_board
    assert "Stage1-2 权威专题" in status_board
    assert "规则候选池 / 字段候选池 / 表达模板库" in status_board
    assert "Stage4/5 内容所有权固定为" in status_board
    assert "L1 只保留摘要口径" in status_board
    assert "L2 只保留 PASS/REVIEW/BLOCK 与补证回退" in status_board
    assert "L3 才维护核验和双闸门操作细节" in status_board
    assert "本轮不改名" in status_board


def test_docs_final_closeout_audit_records_entrypoints_and_no_backslide() -> None:
    text = _read(DOCS / "文档与资产状态板.md")

    assert "第五次最终收口审计完成说明" in text
    assert "文档入口" in text
    assert "旧引用" in text
    assert "默认读序" in text
    assert "剩余重复内容" in text
    assert "旧文件名和历史默认入口不得回流" in text
    assert "archive 只作历史参考" in text
    assert "导航图只作导航提示" in text
    assert "Stage4/5 细节归 L3" in text
    assert "投前专题默认只读 0.1 三表入口" in text
    assert "产品总图归 L1" in text
    assert "验收回退归 L2" in text
    assert "规则候选归专题" in text


def test_ax9s_l1_absorbs_historical_high_value_content() -> None:
    text = _read(DOCS / "AX9S_产品主图与验收总则.md")

    assert "系统执行大脑摘要" in text
    assert "商业钩子线索与披露层级" in text
    assert "高维剩余缺口评估" in text
    assert "卖前给价值感，不给可复现路径" in text
    assert "全国聚合平台只作为一级发现" in text
    assert "北京不进入首批商业线索试点" in text


def test_ax9s_l2_absorbs_source_strategy_and_rule_pool_high_value_content() -> None:
    text = _read(DOCS / "AX9S_Stage1-9_执行矩阵与子漏斗.md")

    assert "Stage1-2 authority 字段与状态机落点" in text
    assert "source_family" in text
    assert "platform_level" in text
    assert "carrier_type" in text
    assert "collection_state" in text
    assert "fallback taxonomy" in text
    assert "deadline provenance" in text
    assert "authoritative baseline" in text
    assert "adapter-ready producer" in text
    assert "防漂移硬规则" in text
    assert "批次顺序" in text
    assert "两法体系分流器" in text
    assert "项目筛选" in text
    assert "控标预测" in text
    assert "自评分" in text
    assert "废标红线" in text
    assert "机器可分析字段候选" in text
    assert "证据等级建议" in text
    assert "风险表达模板" in text


def test_source_route_spec_locks_post_candidate_backtrace_and_guangzhou_primary_source() -> None:
    text = _read(DOCS / "专题_Stage1-2_来源覆盖与采集路由.md")

    assert "POST_CANDIDATE_EVIDENCE_PACK" in text
    assert "近期 `07 中标候选人公示`" in text
    assert "工作日 72 小时内" in text
    assert "30 天作为默认生产入口窗口" in text
    assert "不再作为默认商业入口" in text
    assert "回溯同一项目全流程材料" in text
    assert "招标文件" in text and "答疑澄清" in text and "投标文件公开" in text
    assert "PRE_BID_PREDICTION" in text
    assert "`02 招标文件公示`" in text and "`03 招标公告/关联公告`" in text and "`04 澄清答疑`" in text
    assert "PREDICTION_BEFORE_CLARIFICATION" in text
    assert "PREDICTION_RECALC_REQUIRED" in text
    assert "05 开标信息" in text
    assert "投前预测" in text and "不再卖" in text or "不得继续把该项目送入投前预测" in text
    assert "11 合同信息公开" in text and "12 项目异常" in text
    assert "缺 11/12 不能算当前销售窗口失败" in text
    assert "detail_transport_blocked" in text and "attachment_challenge_required" in text
    assert "AnalysisStrategyPlan v1" in text
    assert "广东工程建设现行来源只保留广州交易集团" in text
    assert "tender_file" in text and "smoke" in text
    assert "广州 `01-12` 流程接口覆盖是适配器验证" in text


def test_pre_bid_topic_is_secondary_rule_pool_and_forbids_post_candidate_outputs() -> None:
    text = _read(DOCS / "专题_规则经验库候选池_投前评审履约.md")

    assert "三表入口" in text
    assert "默认阅读只看 `0.1 三表入口`" in text
    assert "规则候选索引表" in text
    assert "字段候选表" in text
    assert "风险表达与证据等级表" in text
    assert "候选能力" in text
    assert "对应详细章节" in text
    assert "正式落点" in text
    assert "禁止越界" in text
    assert "字段组" in text
    assert "代表字段" in text
    assert "未来落点" in text
    assert "当前状态" in text
    assert "证据等级" in text
    assert "允许表达" in text
    assert "禁止表达" in text
    assert "进入 Stage5/6 条件" in text
    assert "字段候选，不是正式 D2 字段" in text
    assert "长章节是候选明细和历史规则材料" in text
    assert "辅助产品线" in text
    assert "规则候选池" in text
    assert "字段候选池" in text
    assert "表达模板库" in text
    assert "不是当前主线说明书" in text
    assert "主线能力层" in text
    assert "只表示投前预测线内部优先落地的能力层" in text
    assert "候选人核查结论" in text
    assert "真实竞争者结论" in text
    assert "陪标组合结论" in text
    assert "不能输出" in text
    assert "PRE_BID_NOT_ELIGIBLE_OPENING_STARTED" in text
    assert "PRE_BID_NOT_ELIGIBLE_DEADLINE_PASSED" in text
    assert "PREDICTION_BEFORE_CLARIFICATION" in text
    assert "PREDICTION_RECALC_REQUIRED" in text
    assert "AnalysisStrategyPlan v1" in text


def test_ax9s_runbook_states_post_candidate_mainline_and_tender_file_smoke_boundary() -> None:
    text = _read(DOCS / "AX9S_产品主图与验收总则.md")

    assert "默认业务入口" in text
    assert "核心商业主线是候选公示后证据包分析" in text
    assert "近期 `07 中标候选人公示`" in text
    assert "不是默认入口" in text
    assert "缺 11/12 不阻断当前证据包销售窗口" in text
    assert "回溯同一项目" in text
    assert "辅助产品线是投前预测分析" in text
    assert "05 开标信息" in text
    assert "AnalysisStrategyPlan v1" in text
    assert "tender_file" in text and "不是最终业务入口" in text
    assert "只验证文件链路" in text
    assert "总则级契约摘要" in text
    assert "Stage4/5 公开核验和双闸门操作细节" in text
    assert "AX9S_Stage4-5_核验双闸门SOP.md" in text
    assert "Stage4 项目经理核验操作图纸" not in text


def test_status_board_records_p0_sync_boundary() -> None:
    text = _read(DOCS / "文档与资产状态板.md")

    assert "第三次高价值内容吸收完成说明" in text
    assert "高价值内容吸收批" in text
    assert "docs/专题_Stage1-2_来源覆盖与采集路由.md" in text
    assert "docs/专题_规则经验库候选池_投前评审履约.md" in text
    assert "archive/non_current_docs/AX9S_历史设计_自动运营与商业钩子.md" in text
    assert "docs/任务契约_Stage1-6文件分析闭环与经验库能力落地.md" in text
    assert "formal route / 历史导航分层 / controlled-opening" in text
    assert "不再作为产品图纸正文来源" in text
    assert "默认读序不变" in text
    assert "第四次投前专题三表拆轻完成说明" in text
    assert "默认只读 `0.1 三表入口`" in text
    assert "规则候选索引表" in text
    assert "字段候选表" in text
    assert "风险表达与证据等级表" in text
    assert "开发具体规则时再读对应明细章节" in text

    assert "P0 文档方向同步说明" in text
    assert "POST_CANDIDATE_EVIDENCE_PACK" in text
    assert "PRE_BID_PREDICTION" in text
    assert "tender_file" in text and "最终业务入口" in text
    assert "广东只保留广州交易集团主源" in text
    assert "AnalysisStrategyPlan v1" in text
    assert "近期 07 中标候选人公示" in text
    assert "预澄清半成品预测" in text
    assert "缺 11/12 不阻断当前证据包销售窗口" in text
    assert "05 开标信息" in text
    assert "适配器验证" in text
    assert "公开注册信息匹配同步说明" in text
    assert "EvidenceReport v1 同步说明" in text
    assert "默认不下载、不解析 `08 投标文件公开`" in text
    assert "核验线索/证据、过程稳定性、优化建议" in text
    assert "不得写“是不是本人”" in text
    assert "四库/JZSC 只作为公开注册信息" in text
    assert "不能作为实时在建冲突唯一依据" in text
    assert "GuangdongLocalVerificationProbe v1 同步说明" in text
    assert "广东核验不限定广州市" in text
    assert "入口可达不等于字段核验成功" in text
    assert "项目负责人未释放证据链同步说明" in text
    assert "早期研究报告吸收同步说明" in text
    assert "不新增独立吸收清单文档" in text
    assert "来源 URL" in text
    assert "采集时间" in text
    assert "SHA-256/hash" in text
    assert "脱敏日志" in text
    assert "可信时间戳" in text
    assert "白标协作" in text
    assert "SaaS 后置" in text
    assert "跨项目关系图谱" in text
    assert "文件相似度" in text
    assert "报价异常" in text
    assert "下一阶段执行计划同步说明" in text
    assert "P13B_EXTERNAL_AWARD_OVERLAP_TRIAGE_V1" in text
    assert "负责人未释放/履约重叠宽筛" in text
    assert "机器追踪 ID" in text
    assert "P12_GUANGZHOU_10_PROJECT_VALUE_CLOSEOUT_V1" in text
    assert "P13A 已修复 `JG2026-11215`" in text
    assert "10 项目、26 个真实候选组、流程阻断 0、08 定向解析 0" in text
    assert "PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE" in text
    assert "data.ggzy.gov.cn" in text
    assert "主体成交查询" in text
    assert "bid_list" in text and "bid_show" in text
    assert "原文链接" in text
    assert "YGP" in text
    assert "原文 readback" in text
    assert "不恢复为广州主采集源" in text
    assert "YGP CityDiscovery v1" in text
    assert "YGP_FULL_CHAIN_VERIFICATION_V1" in text
    assert "YGP DownloadProbe v1" in text
    assert "GuangdongYgpBatchStabilityCloseout v1" in text
    assert "search/v2/items" in text
    assert "noticeSecondType" in text and "tradingProcess" in text and "regionCode" in text
    assert "项目流程矩阵" in text
    assert "nodeList" in text
    assert "detail" in text
    assert "dsList" in text
    assert "广州交易集团独立适配" in text
    assert "深圳公共资源交易中心独立适配" in text
    assert "广东其他城市" in text
    assert "旧 `dealList_find.jsp` 不作为该宽筛的公司历史中标主入口" in text
    assert "不得写排除结论" in text
    assert "P11_GUANGZHOU_10_PROJECT_STABILITY_V1" in text
    assert "P10_P9_AWARE_READABLE_CLOSEOUT_V1" in text
    assert "P9_EVIDENCE_FIXATION_RECAPTURE_V1" in text
    assert "EvidenceReport 使用 `NoDefaultOptionalRoots`" in text
    assert "P11_PARTIAL_SOURCE_COVERAGE" in text
    assert "旧项目或假样本补齐" in text
    assert "官方源 readback 不作为 P11 成败硬门槛" in text
    assert "project-value-table" in text
    assert "candidate-group-verification-table" in text
    assert "delivery-gap-table" in text
    assert "不扩 20/50" in text
    assert "customer_delivery_ready=false" in text
    assert "RESERVED_NOT_IMPLEMENTED" in text
    assert "非承包方原因停工超过 120 天" in text
    assert "安全生产标准化考评结果告知书" in text
    assert "在建冲突成立" in text
    assert "无在建" in text and "无风险" in text


def test_business_direction_doc_contains_final_analysis_strategy_rules() -> None:
    text = _read(DOCS / "业务方向_候选公示后证据包与投前预测双线契约.md")

    assert "AnalysisStrategyPlan v1" in text
    assert "候选公示后主线不是“少解析”" in text
    assert "工作日 72 小时内" in text
    assert "不得把 30 天作为默认生产入口窗口" in text
    assert "真实买家线索" in text
    assert "`07 中标候选人公示`" in text
    assert "`02 招标文件公示`" in text
    assert "PREDICTION_BEFORE_CLARIFICATION" in text
    assert "PREDICTION_RECALC_REQUIRED" in text
    assert "缺 11/12 不应算作当前销售窗口的回溯失败" in text
    assert "ResponsiblePersonEarlyProbe v1" in text
    assert "候选组" in text
    assert "不得跨候选行混配" in text
    assert "联合体成员" in text
    assert "公司优先补证" in text
    assert "姓名枚举兜底" in text
    assert "`08 投标文件公开` 默认只登记存在、URL、附件清单和后续可解析目标" in text
    assert "只有 `FLOW_08_TARGETED_PARSE_REQUIRED`、公开注册信息不匹配、缺证书号、证书类别/专业不足或需核对 `08` 声明业绩" in text
    assert "`08 投标文件公开` 默认只登记存在、URL、附件清单和后续可解析目标" in text
    assert "`EvidenceReport v1` 三类输出" in text
    assert "核验线索/证据" in text
    assert "过程稳定性" in text
    assert "优化建议" in text
    assert "正式证据固化与交付边界" in text
    assert "事实、线索、证据、反向解释和建议核验事项" in text
    assert "来源 URL" in text
    assert "采集时间" in text
    assert "脚本版本" in text
    assert "SHA-256/hash" in text
    assert "脱敏日志" in text
    assert "可信时间戳" in text
    assert "收费举报人路线" in text
    assert "付费沉默" in text
    assert "AI 只用于抽取" in text
    assert "跨项目关系图谱" in text
    assert "投标文件相似度" in text
    assert "报价异常" in text
    assert "`ActiveConflictProbe v1` 第一版只生成外部核验任务清单" in text
    assert "不能固定广东" in text
    assert "浙江、四川、江苏、湖北、山东、湖南、河南" in text
    assert "PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED" in text
    assert "MajorRegionQueryProbe v1" in text
    assert "GuangdongLocalVerificationProbe v1" in text
    assert "广东核验不限定广州市" in text
    assert "入口页可达" in text
    assert "不得因为公司优先补证未命中就直接写“冲突成立”" in text
    assert "公开注册信息匹配" in text
    assert "不得写“核实是不是本人”" in text
    assert "四库/JZSC 的项目业绩信息只用于辅助核对 `08 投标文件公开`" in text
    assert "不能把“四库未出现”单独写成业绩造假或在建冲突" in text
    assert "在建/履约冲突不以四库作为唯一实时依据" in text
    assert "PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE" in text
    assert "负责人未释放/履约重叠宽筛" in text
    assert "内部历史代号 `P13B`" in text
    assert "data.ggzy.gov.cn" in text
    assert "主体成交查询" in text
    assert "bid_show" in text
    assert "原文链接" in text
    assert "该阶段不是全量下载 01-12，也不是默认解析 `08`" in text
    assert "可能包含项目负责人、工期/服务期、合同履行期限、中标日期或释放证据" in text
    assert "不得一开始全省施工许可、竣工、合同备案全量扫描" in text
    assert "也不得为该宽筛默认全量下载 01-12" in text
    assert "未发现公开重叠线索/需复核/源阻断" in text
    assert "单一路线失败不能直接进入 `08` 或冲突结论" in text
    assert "项目负责人未释放 / 在建履约冲突官方证据链" in text
    assert "非承包方原因导致工程停工超过 120 天" in text
    assert "建筑施工项目安全生产标准化考评结果告知书" in text
    assert "STRONG_REPLAYABLE_CLUE" in text
    assert "MEDIUM_REVIEW_CLUE" in text
    assert "INSUFFICIENT_EVIDENCE" in text
    assert "异议/投诉证据包" in text
    assert "不得输出“在建冲突成立”" in text
    assert "PRE_BID_NOT_ELIGIBLE_OPENING_STARTED" in text
    assert "PRE_BID_NOT_ELIGIBLE_DEADLINE_PASSED" in text
    assert "PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE" in text
    assert "PRE_BID_LIMITED_FAST_REVIEW" in text
    assert "168 小时以上" in text
    assert "不足 72 小时" in text
    assert "05 开标信息" in text and "投前预测已经来不及" in text
    assert "广州 01-12 流程扫描是“适配器和接口形态验证”" in text


def test_top_level_docs_contain_final_strategy_guardrails() -> None:
    readme = _read(ROOT / "README.md")
    agents = _read(ROOT / "AGENTS.md")

    for text in (readme, agents):
        assert "AnalysisStrategyPlan v1" in text
        assert "ResponsiblePersonEarlyProbe v1" in text
        assert "联合体" in text
        assert "公司优先补证" in text
        assert "姓名枚举兜底" in text
        assert "工作日 72 小时内" in text
        assert "05 开标信息" in text
        assert "投前预测" in text
        assert "候选公示后证据包" in text
        assert "近期 `07 中标候选人公示`" in text or "近期 07 中标候选人公示" in text
        assert "缺 11/12 不阻断当前证据包销售窗口" in text
        assert "公开注册信息" in text
        assert "是不是本人" in text
        assert "08" in text and ("不默认下载" in text or "不默认下载或解析" in text)
        assert "浙江、四川、江苏、湖北、山东、湖南、河南" in text
        assert "PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED" in text
        assert "MajorRegionQueryProbe v1" in text
        assert "GuangdongLocalVerificationProbe v1" in text
        assert "PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE" in text
        assert "data.ggzy.gov.cn" in text
        assert "YGP" in text
        assert "原文 readback" in text
        assert "YGP CityDiscovery v1" in text
        assert "YGP_FULL_CHAIN_VERIFICATION_V1" in text
        assert "search/v2/items" in text
        assert "广州主源仍" in text or "不恢复为广州主采集源" in text
        assert "项目流程矩阵" in text
        assert "nodeList" in text
        assert "detail" in text
        assert "dsList" in text
        assert "广东其他城市" in text
        assert "bid_show" in text
        assert "原文链接" in text
        assert "不得一开始全省施工许可、竣工、合同备案全量扫描" in text
        assert "项目负责人未释放" in text
        assert "缺竣工" in text
        assert "无在建" in text
        assert "无风险" in text
        assert "来源 URL" in text
        assert "采集时间" in text
        assert "SHA-256/hash" in text
        assert "脱敏日志" in text
        assert "可信时间戳" in text
        assert "收费举报" in text
        assert "付费沉默" in text
        assert "AI 一键定性" in text


def test_stage45_runbook_contains_responsible_person_early_probe_decision_tree() -> None:
    text = _read(DOCS / "AX9S_Stage4-5_核验双闸门SOP.md")

    assert "ResponsiblePersonEarlyProbe v1" in text
    assert "候选组" in text
    assert "任一成员" in text
    assert "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED" in text
    assert "NAME_ENUMERATION_FALLBACK_REQUIRED" in text
    assert "FLOW_08_TARGETED_PARSE_REQUIRED" in text
    assert "STRONG_CONFLICT_CLUE_AFTER_08" in text
    assert "INSUFFICIENT_EVIDENCE_AFTER_08" in text
    assert "姓名枚举只用于补证和消歧，不能单独 PASS" in text
    assert "不得直接判定冲突成立" in text
    assert "不得输出法律定性" in text
    assert "不判断自然人“是不是本人”" in text
    assert "姓名 + 公司/注册单位" in text
    assert "四库/JZSC 的人员项目页和企业项目页只能作为身份消歧" in text
    assert "不能作为实时在建冲突唯一依据" in text
    assert "浙江、四川、江苏、湖北、山东、湖南、河南" in text
    assert "PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED" in text
    assert "MajorRegionQueryProbe v1" in text
    assert "项目负责人释放证据链" in text
    assert "非承包方原因停工超过 120 天" in text
    assert "缺竣工、缺备案、缺变更或缺安全生产标准化考评释放材料" in text
    assert "异议/投诉证据包口径" in text
    assert "当前项目 07 证据" in text
    assert "来源 URL" in text
    assert "采集时间" in text
    assert "脚本版本" in text
    assert "snapshot/readback" in text
    assert "SHA-256/hash" in text
    assert "脱敏日志" in text
    assert "可信时间戳" in text
    assert "事实、线索、证据、反向解释和建议核验事项" in text
    assert "收费举报人" in text
    assert "付费沉默" in text
    assert "AI 一键定性" in text


def test_l2_matrix_keeps_stage45_at_matrix_level_and_points_to_sop() -> None:
    text = _read(DOCS / "AX9S_Stage1-9_执行矩阵与子漏斗.md")

    assert "Stage4/5 细节单源见 `docs/AX9S_Stage4-5_核验双闸门SOP.md`" in text
    assert "REVIEW/BLOCK 回退" in text
    assert "企业内唯一匹配后，后续查询必须改用证书编号或人员公开 ID" in text
    assert "闸门细项和释放证据规则以 SOP 为准" in text
    assert "四库不可抓时，走地方住建、公共资源附件、备案系统补充。" not in text
    assert "人员列表分页时必须翻页或调用等价公开接口，不能只看第一页。" not in text


def test_route_map_is_navigation_not_long_history_body() -> None:
    text = _read(DOCS / "AX9S_当前主线导航图.md")

    assert "| Stage | 看哪份主文档 | Handoff | 当前导航候选 |" in text
    assert "| 历史详单 |" in text
    assert "本导航图不再维护长历史清单" in text
    assert "## 2.1 Stage 1 任务编排与来源/路由治理" not in text
    assert "## 2.9 Stage 9 订单、支付、交付与治理反馈" not in text
    assert "PTL-I100-133A-real-public-entry-url-fetcher-and-allowlist" not in text
    assert "PTL-I100-139-real-public-parser-to-verification-pilot" not in text


def test_navigation_docs_do_not_drift_from_analysis_strategy_v1() -> None:
    paths = [
        DOCS / "AX9S_当前主线导航图.md",
        ARCHIVE_NON_CURRENT / "AX9S_历史设计_自动运营与商业钩子.md",
    ]

    for path in paths:
        text = _read(path)
        assert "AnalysisStrategyPlan v1" in text, path
        assert "05 开标信息" in text, path
        assert "投前预测" in text, path
        assert "候选后证据包" in text, path


def test_formal_docs_reference_final_bid_analysis_split() -> None:
    paths = [
        DOCS / "D3_正式规则码总表与判定说明书.md",
        DOCS / "D8_真实竞争者识别可售对象与销售推进规范.md",
        DOCS / "D11_测试验收与金标回归清单.md",
        DOCS / "D13_公开可查边界能力清单.md",
    ]

    for path in paths:
        text = _read(path)
        assert "05 开标信息" in text, path
        assert "投前预测" in text, path
        assert "候选后" in text or "候选公示后" in text, path

    assert "AnalysisStrategyPlan v1" in _read(DOCS / "D3_正式规则码总表与判定说明书.md")
    assert "AnalysisStrategyPlan v1" in _read(DOCS / "D11_测试验收与金标回归清单.md")
