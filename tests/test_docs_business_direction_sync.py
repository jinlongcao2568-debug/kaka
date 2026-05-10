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


def test_source_route_spec_locks_post_candidate_backtrace_and_ygp_quarantine() -> None:
    text = _read(DOCS / "专题_来源覆盖与采集路由规范.md")

    assert "POST_CANDIDATE_EVIDENCE_PACK" in text
    assert "候选公示/评标结果/中标结果/开标记录" in text
    assert "回溯同一项目全流程材料" in text
    assert "招标文件" in text and "答疑澄清" in text and "投标文件公开" in text
    assert "PRE_BID_PREDICTION" in text
    assert "GUANGDONG-YGP-PROVINCE-TRADING-LIST" in text
    assert "继续隔离" in text
    assert "tender_file" in text and "smoke" in text


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


def test_ax9s_runbook_states_post_candidate_mainline_and_tender_file_smoke_boundary() -> None:
    text = _read(DOCS / "AX9S_实战运行图纸与验收契约.md")

    assert "默认业务入口" in text
    assert "核心商业主线是候选公示后证据包分析" in text
    assert "中标候选人公示、评标结果、开标记录、中标结果" in text
    assert "回溯同一项目" in text
    assert "辅助产品线是投前预测分析" in text
    assert "tender_file" in text and "不是最终业务入口" in text
    assert "只验证文件链路" in text


def test_status_board_records_p0_sync_boundary() -> None:
    text = _read(DOCS / "文档与资产状态板.md")

    assert "P0 文档方向同步说明" in text
    assert "POST_CANDIDATE_EVIDENCE_PACK" in text
    assert "PRE_BID_PREDICTION" in text
    assert "tender_file" in text and "最终业务入口" in text
    assert "YGP" in text and "继续隔离" in text
