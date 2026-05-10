from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage3_parsing.tailored_bid_signals import (  # noqa: E402
    build_tailored_bid_signal_profile,
    load_tailored_bid_signal_seed,
)


class TestTailoredBidSignalSeed(unittest.TestCase):
    def test_seed_loads_preserves_social_experience_and_guardrails(self) -> None:
        seed = load_tailored_bid_signal_seed()

        self.assertGreaterEqual(seed["signal_count"], 32)
        self.assertIn(
            "SOCIAL_EXPERIENCE",
            seed["source_class_policy"]["allowed_source_classes"],
        )
        sample_ids = set()
        for signal in seed["signals"]:
            sample_ids.add(signal["sample_id"])
            self.assertTrue(signal["keyword_patterns"])
            self.assertTrue(signal["index_targets"])
            self.assertIn(
                signal["signal_domain"],
                {
                    "TAILORED_COMPETITION",
                    "FATAL_REJECTION",
                    "ELECTRONIC_SUPERVISION",
                    "BID_SELECTION",
                    "REGIONAL_RULE_PROFILE",
                    "DOCUMENT_QUALITY",
                    "PRICE_PERFORMANCE",
                },
            )
            self.assertTrue(signal["observable_from"])
            self.assertIn(signal["source_confidence"], {"HIGH", "MEDIUM", "EXPERIENCE", "UNSTABLE"})
            self.assertTrue(signal["rule_gate_condition"])
            self.assertTrue(signal["evidence_gate_condition"])
            self.assertFalse(signal["customer_visible_allowed"])
            self.assertTrue(signal["no_legal_conclusion"])
            self.assertTrue(signal["source_classes"])
        self.assertEqual(len(sample_ids), len(seed["signals"]))
        self.assertIn("围标线索", seed["allowed_output_terms"])
        self.assertIn("串标线索", seed["allowed_output_terms"])
        self.assertIn("陪标线索", seed["allowed_output_terms"])

    def test_profile_hits_tailored_fatal_dark_bid_and_collusion_families(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {},
            text=(
                "采购文件要求厂家授权、原厂唯一授权、本地社保、本地服务网点、"
                "CMA检测报告、技术参数精确到小数、主观分45分、暗标不得出现公司名称、"
                "投标保证金、同一IP、同一CA、报价高度接近。"
            ),
        )

        families = set(profile["tailored_bid_signal_families"])
        self.assertGreaterEqual(profile["tailored_bid_index"], 41)
        self.assertTrue(profile["tailored_bid_stage5_review_required"])
        self.assertTrue(profile["tailored_bid_ai_review_required"])
        self.assertIn("authorization_binding", families)
        self.assertIn("local_protection", families)
        self.assertIn("technical_parameter_customization", families)
        self.assertIn("test_report_customization", families)
        self.assertIn("scoring_customization", families)
        self.assertIn("dark_bid_format_risk", families)
        self.assertIn("fatal_rejection_complexity", families)
        self.assertIn("collusion_trace", families)
        self.assertFalse(profile["customer_visible_allowed"])
        self.assertTrue(profile["no_legal_conclusion"])
        self.assertGreaterEqual(profile["fatal_rejection_complexity_index"], 21)
        self.assertIn("collusion_trace_index", profile["system_risk_indices"])
        self.assertEqual(profile["system_auto_judgement"]["judgement_state"], "RISK_CLUE_DETECTED")

    def test_bid_rigging_and_cover_bid_jargon_emit_separate_indices(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {"input_observable_from": ["complaint_case", "post_award_notice", "internal_material"]},
            text=(
                "投诉材料提到围标、串标、串通投标、轮流坐庄，"
                "并存在陪标、护航、凑三家、异常高价护航等报价陪跑线索。"
            ),
        )

        self.assertLess(profile["tailored_bid_index"], 21)
        self.assertGreaterEqual(profile["bid_rigging_index"], 21)
        self.assertGreaterEqual(profile["cover_bid_index"], 21)
        self.assertGreaterEqual(profile["collusion_trace_index"], 21)
        judgement = profile["system_auto_judgement"]
        self.assertEqual(judgement["judgement_state"], "RISK_CLUE_DETECTED")
        self.assertIn("围标线索", judgement["primary_allowed_terms"])
        self.assertIn("串标线索", judgement["primary_allowed_terms"])
        self.assertIn("陪标线索", judgement["primary_allowed_terms"])

    def test_plain_tender_file_does_not_weight_platform_metadata_collusion_terms(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {"document_kind": "tender_file"},
            text="普通招标文件正文里提到投标人不得围标、串标、同一IP、同一CA。",
        )

        self.assertGreater(profile["tailored_bid_signal_count"], 0)
        self.assertEqual(profile["bid_rigging_index"], 0)
        self.assertEqual(profile["electronic_supervision_index"], 0)
        self.assertTrue(profile["observable_mismatch_review_required"])
        self.assertIn("observable_mismatch", profile["system_index_weight_block_reasons"])

    def test_regional_profile_only_does_not_raise_tailored_index(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {},
            text="浙江暗标扣分制，文件属性、页码字体和技术标暗标格式要按地区模板检查。",
        )

        self.assertEqual(profile["tailored_bid_index"], 0)
        self.assertEqual(profile["tailored_bid_risk_level"], "NO_SIGNAL")
        self.assertFalse(profile["tailored_bid_stage5_review_required"])
        self.assertIn("REGIONAL_RULE_PROFILE", profile["tailored_bid_signal_domains"])
        self.assertGreater(profile["tailored_bid_sub_indices"]["dark_bid_format_risk_index"], 0)

    def test_fatal_rejection_only_keeps_sub_index_without_tailored_index(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {},
            text="投标保证金必须备注包号，保证金金额错误、到账晚或付款主体不一致可能废标。",
        )

        self.assertEqual(profile["tailored_bid_index"], 0)
        self.assertEqual(profile["tailored_bid_risk_level"], "NO_SIGNAL")
        self.assertFalse(profile["tailored_bid_stage5_review_required"])
        self.assertIn("FATAL_REJECTION", profile["tailored_bid_signal_domains"])
        self.assertGreater(profile["tailored_bid_sub_indices"]["fatal_rejection_complexity_index"], 0)

    def test_electronic_supervision_signal_requires_platform_or_internal_observable(self) -> None:
        text = "平台提示多家公司同一IP、同一CA、同一MAC地址，上传解密时间异常接近。"
        profile = build_tailored_bid_signal_profile({}, text=text)

        self.assertEqual(profile["tailored_bid_index"], 0)
        self.assertTrue(profile["observable_mismatch_review_required"])
        hit = next(
            item
            for item in profile["signal_hits"]
            if item["signal_domain"] == "ELECTRONIC_SUPERVISION"
        )
        self.assertTrue(hit["observable_mismatch_review_required"])
        self.assertEqual(hit["observable_from"], ["platform_metadata", "internal_material", "complaint_case"])

        platform_profile = build_tailored_bid_signal_profile(
            {"input_observable_from": ["platform_metadata"]},
            text=text,
        )
        self.assertEqual(platform_profile["tailored_bid_index"], 0)
        self.assertFalse(platform_profile["observable_mismatch_review_required"])

    def test_counter_reason_lowers_weight_but_keeps_hit_record(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {},
            text="投标人须提供ISO9001三体系证书，本项目依法必须强制认证并涉及医疗器械注册证。",
        )

        hit = next(
            item
            for item in profile["signal_hits"]
            if item["sample_id"] == "TAILORED-SIGNAL-0001"
        )
        self.assertTrue(hit["counter_reason_markers"])
        self.assertLess(hit["applied_weight"], hit["base_weight"])
        self.assertGreaterEqual(profile["counter_reason_count"], 1)

    def test_document_section_slices_extract_major_tender_sections(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {"document_kind": "tender_file"},
            text=(
                "资格条件\n投标人须提供厂家授权、本地社保。\n"
                "评分办法\n技术方案主观分45分。\n"
                "技术参数\n设备技术参数精确到小数，并提供CMA检测报告。\n"
                "废标条款\n投标保证金错误视为无效投标。\n"
                "合同条款\n付款时提交验收材料。"
            ),
        )

        section_profile = profile["document_section_profile"]
        self.assertEqual(section_profile["profile_state"], "SECTION_SLICED")
        self.assertGreaterEqual(section_profile["section_slice_count"], 5)
        for section_type in ("资格条件", "评分办法", "技术参数", "废标条款", "合同付款"):
            self.assertIn(section_type, section_profile["section_slice_types"])
        self.assertTrue(profile["document_section_slices"])
        self.assertIn("text_sha256", profile["document_section_slices"][0])
        self.assertFalse(profile["document_section_slices"][0]["customer_visible"])

    def test_qualification_candidate_blocks_feed_qualification_section_slice(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {
                "document_kind": "tender_file",
                "qualification_text_candidate_blocks": ["投标人须提供厂家授权、本地社保。"],
            }
        )

        self.assertGreaterEqual(profile["tailored_bid_index"], 21)
        self.assertIn("资格条件", profile["document_section_profile"]["section_slice_types"])
        self.assertTrue(
            any(
                hit["section_match_state"] == "EXPECTED_SECTION_MATCH"
                and "资格条件" in hit["matched_document_sections"]
                for hit in profile["signal_hits"]
            )
        )

    def test_contract_and_clarification_sections_block_formal_tailored_weight(self) -> None:
        contract_profile = build_tailored_bid_signal_profile(
            {"document_kind": "tender_file"},
            text="合同条款\n付款时提供厂家授权、本地社保、同类业绩。",
        )
        clarification_profile = build_tailored_bid_signal_profile(
            {"document_kind": "tender_file"},
            text="附件\n澄清文件提到技术参数精确到小数、CMA检测报告。",
        )

        self.assertEqual(contract_profile["tailored_bid_index"], 0)
        self.assertIn("section_guardrail=合同付款", contract_profile["formal_index_weight_block_reasons"])
        self.assertTrue(
            all(hit["tailored_index_weight"] == 0 for hit in contract_profile["signal_hits"])
        )
        self.assertEqual(clarification_profile["tailored_bid_index"], 0)
        self.assertIn(
            "section_guardrail=附件补遗",
            clarification_profile["formal_index_weight_block_reasons"],
        )
        self.assertTrue(
            all(hit["tailored_index_weight"] == 0 for hit in clarification_profile["signal_hits"])
        )

    def test_scoring_and_technical_sections_keep_expected_weights(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {"document_kind": "tender_file"},
            text=(
                "评分办法\n技术方案主观分45分，评分锁。\n"
                "技术参数\n设备技术参数精确到小数，并提供CMA检测报告。"
            ),
        )

        self.assertGreaterEqual(profile["tailored_bid_index"], 41)
        families = {
            hit["signal_family"]: hit
            for hit in profile["signal_hits"]
            if hit["signal_family"] in {"scoring_customization", "technical_parameter_customization"}
        }
        self.assertEqual(families["scoring_customization"]["section_match_state"], "EXPECTED_SECTION_MATCH")
        self.assertEqual(
            families["technical_parameter_customization"]["section_match_state"],
            "EXPECTED_SECTION_MATCH",
        )
        self.assertFalse(profile["formal_index_weight_block_reasons"])

    def test_candidate_notice_hits_are_kept_but_do_not_raise_formal_tailored_index(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {"document_kind": "candidate_notice"},
            text="中标候选人公示显示项目经理、人员业绩、同类业绩、本地社保等后验信息。",
        )

        self.assertGreater(profile["tailored_bid_signal_count"], 0)
        self.assertEqual(profile["tailored_bid_index"], 0)
        self.assertEqual(profile["tailored_bid_risk_level"], "NO_SIGNAL")
        self.assertTrue(profile["tailored_bid_stage5_review_required"])
        self.assertGreater(profile["formal_index_weight_blocked_count"], 0)
        self.assertIn("observable_mismatch", profile["formal_index_weight_block_reasons"])
        self.assertIn(
            "auxiliary_document_kind=candidate_notice",
            profile["formal_index_weight_block_reasons"],
        )
        hit = next(
            item
            for item in profile["signal_hits"]
            if item["signal_family"] == "performance_personnel_binding"
        )
        self.assertEqual(hit["tailored_index_weight"], 0)
        self.assertTrue(hit["formal_index_weight_blocked"])

    def test_opening_and_clarification_text_keeps_hits_without_raising_tailored_index(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {
                "document_kind": "tender_file",
                "notice_version_chain_state": "CLARIFICATION_OR_ADDENDUM_PRESENT",
            },
            text="开标记录和澄清文件提到ISO证书、暗标格式、投标保证金等事项。",
        )

        self.assertGreater(profile["tailored_bid_signal_count"], 0)
        self.assertEqual(profile["tailored_bid_index"], 0)
        self.assertEqual(profile["tailored_bid_risk_level"], "NO_SIGNAL")
        self.assertIn(
            "notice_version_chain_state=CLARIFICATION_OR_ADDENDUM_PRESENT",
            profile["formal_index_weight_block_reasons"],
        )
        self.assertIn(
            "non_primary_text_marker=开标记录",
            profile["formal_index_weight_block_reasons"],
        )
        self.assertGreater(profile["tailored_bid_sub_indices"]["qualification_customization_index"], 0)

    def test_post_tender_attachment_markers_do_not_raise_tailored_index(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {"document_kind": "tender_file"},
            text="评标报告和中标候选人公示提到厂家授权、本地社保、同类业绩等后验信息。",
        )

        self.assertGreater(profile["tailored_bid_signal_count"], 0)
        self.assertEqual(profile["tailored_bid_index"], 0)
        self.assertEqual(profile["tailored_bid_risk_level"], "NO_SIGNAL")
        self.assertIn(
            "non_primary_text_marker=评标报告",
            profile["formal_index_weight_block_reasons"],
        )
        self.assertIn(
            "non_primary_text_marker=中标候选人公示",
            profile["formal_index_weight_block_reasons"],
        )

    def test_partial_attachment_evidence_keeps_review_without_increasing_index(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {
                "document_kind": "tender_file",
                "document_completeness_state": "PARTIAL_REVIEW_REQUIRED",
                "attachment_missing_review_count": 1,
            },
            text="招标文件片段要求厂家授权、本地社保、CMA检测报告、技术参数精确到小数。",
        )

        self.assertGreater(profile["tailored_bid_signal_count"], 0)
        self.assertEqual(profile["tailored_bid_index"], 0)
        self.assertEqual(profile["tailored_bid_risk_level"], "NO_SIGNAL")
        self.assertEqual(profile["evidence_state"], "PARTIAL_EVIDENCE_REVIEW")
        self.assertTrue(profile["tailored_bid_stage5_review_required"])
        self.assertTrue(profile["tailored_bid_ai_review_required"])
        self.assertIn(
            "document_completeness_state=PARTIAL_REVIEW_REQUIRED",
            profile["formal_index_weight_block_reasons"],
        )
        self.assertIn("attachment_missing_review_count>0", profile["formal_index_weight_block_reasons"])

    def test_ocr_or_attachment_blocker_reports_insufficient_evidence(self) -> None:
        profile = build_tailored_bid_signal_profile(
            {"ocr_state": "OCR_REQUIRED", "attachment_ocr_required_count": 1},
            text="",
        )

        self.assertEqual(profile["tailored_bid_risk_level"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(profile["evidence_state"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(profile["tailored_bid_stage5_review_required"])
        self.assertTrue(profile["tailored_bid_ai_review_required"])


if __name__ == "__main__":
    unittest.main()
