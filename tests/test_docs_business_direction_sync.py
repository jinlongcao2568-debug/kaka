from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CONTRACT_REF = "contracts/evaluation/business_direction_strategy_contract.json"
HUMAN_REF = "docs/业务方向_候选公示后证据包与投前预测双线契约.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_p0_entry_docs_reference_business_direction_contracts() -> None:
    paths = [
        DOCS / "专题_来源覆盖与采集路由规范.md",
        DOCS / "专题_投前预测评审风控规则救济与履约结算经验库草案.md",
        DOCS / "AX9S_实战运行图纸与验收契约.md",
        DOCS / "文档与资产状态板.md",
    ]

    for path in paths:
        text = _read(path)
        assert HUMAN_REF in text or CONTRACT_REF in text, path


def test_source_route_spec_locks_post_candidate_backtrace_and_guangzhou_primary_source() -> None:
    text = _read(DOCS / "专题_来源覆盖与采集路由规范.md")

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
    text = _read(DOCS / "专题_投前预测评审风控规则救济与履约结算经验库草案.md")

    assert "辅助产品线" in text
    assert "规则候选池" in text
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
    text = _read(DOCS / "AX9S_实战运行图纸与验收契约.md")

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


def test_status_board_records_p0_sync_boundary() -> None:
    text = _read(DOCS / "文档与资产状态板.md")

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
    assert "P7_INTERNAL_EVIDENCE_PACKAGE_MANIFEST_V1" in text
    assert "广州 5 项目 P1-P6 结果收口为内部证据包 manifest" in text
    assert "FIXATION_GAP_REVIEW" in text
    assert "customer_delivery_ready=false" in text
    assert "RESERVED_NOT_IMPLEMENTED" in text
    assert "广州 20 项目小批量稳定性验证" in text
    assert "浙江非广东省份 adapter" in text
    assert "跨项目异常能力" in text
    assert "不得在内部证据包 manifest 前启动图谱或 SaaS 主线" in text
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
    text = _read(DOCS / "AX9S_Stage4-5_核验与双闸门操作规程.md")

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


def test_navigation_docs_do_not_drift_from_analysis_strategy_v1() -> None:
    paths = [
        DOCS / "AX9S_开发执行路由图.md",
        DOCS / "AX9S_自动运营决策架构与商业钩子方案.md",
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
