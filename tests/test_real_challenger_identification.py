from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture, run_internal_chain_to_stage7
from shared.pipeline import run_internal_chain
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from stage7_sales.service import Stage7Service
from test_stage5_rule_factory_expansion import _real_public_stage4_verification


def _real_challenger_payload() -> dict:
    payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
    payload["multi_competitor_candidate_pool"] = [
        {
            "candidate_id": "cand-second",
            "challenger_profile_id": "CHALT-PROJ-001-SECOND",
            "challenger_bidder_id": "BID-PROJ-001-SECOND",
            "challenger_name": "第二名竞争者",
            "candidate_position_label": "SECOND_CANDIDATE",
            "candidate_source_type": "second_rank",
            "confidence_score_optional": 96,
            "challenge_actionability_score": 96,
            "execution_readiness_score": 94,
            "purchase_capacity_score": 88,
            "subject_eligibility_state": "ELIGIBLE",
            "source_refs": ["stage5.rule_hit:PROC-001", "stage6.challenger_candidate_profile:second"],
        },
        {
            "candidate_id": "cand-third",
            "challenger_profile_id": "CHALT-PROJ-001-THIRD",
            "challenger_bidder_id": "BID-PROJ-001-THIRD",
            "challenger_name": "第三名竞争者",
            "candidate_position_label": "THIRD_CANDIDATE",
            "candidate_source_type": "third_rank",
            "confidence_score_optional": 86,
            "challenge_actionability_score": 82,
            "execution_readiness_score": 79,
            "purchase_capacity_score": 74,
            "subject_eligibility_state": "ELIGIBLE",
            "source_refs": ["stage5.rule_hit:PROC-002"],
        },
        {
            "candidate_id": "cand-rejected",
            "challenger_profile_id": "CHALT-PROJ-001-REJECTED",
            "challenger_bidder_id": "BID-PROJ-001-REJECTED",
            "challenger_name": "被否决投标人",
            "candidate_position_label": "OTHER",
            "candidate_source_type": "rejected_bidder",
            "confidence_score_optional": 77,
            "challenge_actionability_score": 75,
            "execution_readiness_score": 70,
            "purchase_capacity_score": 68,
            "subject_eligibility_state": "ELIGIBLE",
            "source_refs": ["stage6.internal_evidence:rejected-bidder"],
        },
        {
            "candidate_id": "cand-historical",
            "challenger_profile_id": "CHALT-PROJ-001-HIST",
            "challenger_bidder_id": "BID-PROJ-001-HIST",
            "challenger_name": "历史竞争企业",
            "candidate_position_label": "OTHER",
            "candidate_source_type": "historical_competitor",
            "confidence_score_optional": 72,
            "challenge_actionability_score": 70,
            "execution_readiness_score": 66,
            "purchase_capacity_score": 62,
            "subject_eligibility_state": "ELIGIBLE",
            "source_refs": ["stage6.internal_evidence:historical"],
        },
        {
            "candidate_id": "cand-regional",
            "challenger_profile_id": "CHALT-PROJ-001-REGION",
            "challenger_bidder_id": "BID-PROJ-001-REGION",
            "challenger_name": "同区域活跃企业",
            "candidate_position_label": "OTHER",
            "candidate_source_type": "regional_active_company",
            "confidence_score_optional": 68,
            "challenge_actionability_score": 65,
            "execution_readiness_score": 60,
            "purchase_capacity_score": 58,
            "subject_eligibility_state": "ELIGIBLE",
            "source_refs": ["stage6.internal_evidence:regional"],
        },
    ]
    return payload


class RealChallengerIdentificationTests(unittest.TestCase):
    def test_candidate_set_covers_required_real_challenger_types(self) -> None:
        stage7 = run_internal_chain_to_stage7(_real_challenger_payload())["stage7"]
        readback = stage7.inputs["stage7_resolution_trace"]["real_challenger_identification"]
        candidates = readback["candidate_set"]
        source_types = {candidate["candidate_source_type"] for candidate in candidates}

        self.assertTrue(
            {
                "second_rank",
                "third_rank",
                "rejected_bidder",
                "historical_competitor",
                "regional_active_company",
            }.issubset(source_types)
        )
        for candidate in candidates:
            for field_name in (
                "challenger_profile_id",
                "challenger_name",
                "name_optional",
                "candidate_source_type",
                "rank",
                "status",
                "subject_eligibility_state",
                "challenge_motivation_score",
                "purchase_capacity_score",
                "buyer_fit_score",
                "contactability_status",
                "recommended_offer_ref",
                "recommended_offer_summary",
                "sales_priority",
                "source_refs",
                "explainability_reasons",
            ):
                self.assertIn(field_name, candidate, field_name)

    def test_winning_selection_is_explainable_and_consumed_by_sales_objects(self) -> None:
        stage7 = run_internal_chain_to_stage7(_real_challenger_payload())["stage7"]
        readback = stage7.inputs["real_challenger_readback"]
        trace = readback["selection_trace"]
        winner = readback["winning_candidate"]

        self.assertEqual(winner["candidate_id"], "cand-second")
        self.assertEqual(trace["selected_candidate_id"], "cand-second")
        self.assertEqual(trace["selected_challenger_profile_id"], winner["challenger_profile_id"])
        self.assertIn("ranking_score desc", trace["tie_breaker"])
        self.assertIn("cand-second", trace["score_components"])
        self.assertTrue(trace["reject_skip_reasons"])
        self.assertEqual(
            stage7.record("saleable_opportunity").get("challenger_profile_id"),
            winner["challenger_profile_id"],
        )
        self.assertEqual(
            stage7.record("multi_competitor_collection").get("winning_challenger_profile_id"),
            winner["challenger_profile_id"],
        )
        self.assertIn("buyer_fit", trace["winning_consumed_by"])
        self.assertIn("sales_lead", trace["winning_consumed_by"])
        self.assertIn("offer_recommendation", trace["winning_consumed_by"])
        self.assertIn("saleable_opportunity", trace["winning_consumed_by"])

    def test_scores_contactability_offer_and_priority_are_readable(self) -> None:
        stage7 = run_internal_chain_to_stage7(_real_challenger_payload())["stage7"]
        winner = stage7.inputs["winning_real_challenger_candidate"]
        offer = stage7.record("offer_recommendation")

        self.assertEqual(winner["challenge_motivation_score"], 96)
        self.assertEqual(winner["purchase_capacity_score"], 88)
        self.assertEqual(
            winner["buyer_fit_score"],
            stage7.record("challenger_buyer_fit").get("fit_score"),
        )
        self.assertEqual(winner["contactability_status"], "INTERNAL_READY")
        self.assertIn(winner["sales_priority"], {"P1", "P2"})
        self.assertEqual(winner["recommended_offer_ref"], offer.get("offer_recommendation_id"))
        self.assertEqual(
            winner["recommended_offer_summary"]["offer_recommendation_state"],
            offer.get("offer_recommendation_state"),
        )
        self.assertIn("sales_priority=", ";".join(winner["explainability_reasons"]))

    def test_contactability_does_not_bypass_stage8_or_customer_visibility(self) -> None:
        stage7 = run_internal_chain_to_stage7(_real_challenger_payload())["stage7"]
        readback = stage7.inputs["real_challenger_readback"]
        boundary = readback["stage8_compliance_boundary"]
        isolation = readback["customer_visible_field_isolation"]

        self.assertTrue(boundary["stage7_contactability_is_readiness_only"])
        self.assertTrue(boundary["stage8_compliance_required_before_touch"])
        self.assertFalse(boundary["outbox_created"])
        self.assertFalse(boundary["real_touch_enabled"])
        self.assertFalse(boundary["crm_or_quote_provider_called"])
        self.assertFalse(isolation["customer_visible_enabled"])
        self.assertFalse(isolation["external_delivery_enabled"])
        self.assertTrue(isolation["notLegalConclusion"])
        for candidate in readback["candidate_set"]:
            self.assertFalse(candidate["customer_visible"])
            self.assertTrue(candidate["internal_sales_judgment_only"])
        self.assertNotIn("contact_target", stage7.records)

    def test_missing_subject_or_purchase_capacity_fails_closed_to_review(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["multi_competitor_candidate_pool"] = [
            {
                "candidate_id": "cand-missing-capacity",
                "challenger_profile_id": "CHALT-PROJ-001-MISSING",
                "challenger_bidder_id": "BID-PROJ-001-MISSING",
                "challenger_name": "缺主体与购买能力候选",
                "candidate_position_label": "SECOND_CANDIDATE",
                "candidate_source_type": "second_rank",
                "confidence_score_optional": 99,
                "challenge_actionability_score": 99,
                "execution_readiness_score": 99,
                "purchase_capacity_score": None,
                "subject_eligibility_state": "MISSING",
            }
        ]

        stage7 = run_internal_chain_to_stage7(payload)["stage7"]
        readback = stage7.inputs["real_challenger_readback"]
        winner = readback["winning_candidate"]
        joined_reasons = ";".join(readback["blocking_reasons"])

        self.assertEqual(winner["candidate_id"], "cand-missing-capacity")
        self.assertEqual(readback["real_challenger_decision_state"], "REVIEW")
        self.assertEqual(stage7.record("sales_lead").get("lead_status"), "REVIEW")
        self.assertEqual(stage7.record("saleable_opportunity").get("saleability_status"), "RESTRICTED")
        self.assertEqual(
            stage7.record("offer_recommendation").get("offer_recommendation_state"),
            "REVIEW_REQUIRED",
        )
        self.assertIn("subject_eligibility_state=MISSING", joined_reasons)
        self.assertIn("purchase_capacity_score=MISSING", joined_reasons)

    def test_real_public_stage6_product_package_enters_stage7_sales_and_leadpack_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            verification = _real_public_stage4_verification(tmp_dir=tmp_dir)
            base_stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
            stage5 = Stage5Service().run_public_verification_readback(
                base_stage4,
                verification,
                requested_rule_codes=["DOC-001"],
            )
            stage6 = Stage6Service().run_real_public_rule_evidence_readback(stage5)
            stage7 = Stage7Service().run_real_public_product_package_readback(stage6)

        summary = stage7.inputs[Stage7Service.REAL_PUBLIC_STAGE7_READBACK_KEY]
        leadpack = stage7.inputs["leadpack_delivery_package"]
        workbench = stage7.inputs["crm_quote_workbench"]

        self.assertEqual(summary, stage7.handoff[Stage7Service.REAL_PUBLIC_STAGE7_READBACK_KEY])
        self.assertEqual(summary["readback_state"], "READBACK_READY")
        self.assertEqual(summary["real_public_sales_package_chain_state"], "INTERNAL_READY")
        self.assertEqual(summary["stage6_product_package_readiness"], "INTERNAL_READY")
        self.assertEqual(summary["real_challenger_decision_state"], "ALLOW")
        self.assertEqual(
            summary["source_refs"]["stage6_real_public_rule_evidence_readback"]["verification_run_id"],
            verification["verification_run_id"],
        )
        self.assertEqual(
            summary["source_refs"]["stage6_real_public_rule_evidence_readback"]["source_snapshot_id"],
            verification["source_snapshot_id"],
        )
        self.assertEqual(summary["source_refs"]["leadpack_package_id"], leadpack["package_id"])
        self.assertEqual(summary["source_refs"]["crm_action_id"], workbench["crm_action_id"])
        self.assertEqual(summary["fail_closed_reasons"], [])
        self.assertIn("real_public_stage6_product_package", leadpack["source_object_refs"])
        self.assertFalse(summary["customer_visible_material_generated"])
        self.assertFalse(summary["customer_visible_enabled"])
        self.assertFalse(summary["external_delivery_enabled"])
        self.assertFalse(summary["crm_quote_provider_execution_enabled"])
        self.assertFalse(summary["stage8_stage9_execution_triggered"])
        self.assertFalse(leadpack["customer_visible_enabled"])
        self.assertFalse(leadpack["external_delivery_enabled"])
        self.assertFalse(workbench["approved_crm_quote_execution_enabled"])

    def test_real_public_stage6_review_package_fails_closed_before_stage7_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            verification = _real_public_stage4_verification(
                tmp_dir=tmp_dir,
                profile_id="BEIJING-PLATFORM-HOME",
                target_type="contract_public_info",
                identifier="CONTRACT-PUBLIC-STAGE7-142",
                target_identifier="",
            )
            base_stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
            stage5 = Stage5Service().run_public_verification_readback(
                base_stage4,
                verification,
                requested_rule_codes=["DOC-001"],
            )
            stage6 = Stage6Service().run_real_public_rule_evidence_readback(stage5)
            stage7 = Stage7Service().run_real_public_product_package_readback(stage6)

        summary = stage7.inputs[Stage7Service.REAL_PUBLIC_STAGE7_READBACK_KEY]
        self.assertEqual(summary["readback_state"], "REVIEW_REQUIRED")
        self.assertEqual(summary["real_public_sales_package_chain_state"], "REVIEW_REQUIRED")
        self.assertIn(
            "stage6_real_public_product_package_chain_state=REVIEW_REQUIRED",
            summary["fail_closed_reasons"],
        )
        self.assertIn("stage6_product_package_readiness=REVIEW_REQUIRED", summary["fail_closed_reasons"])
        self.assertFalse(summary["customer_visible_material_generated"])
        self.assertFalse(summary["external_delivery_enabled"])
        self.assertFalse(summary["crm_quote_provider_execution_enabled"])


if __name__ == "__main__":
    unittest.main()
