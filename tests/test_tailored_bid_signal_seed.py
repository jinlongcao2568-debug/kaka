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
