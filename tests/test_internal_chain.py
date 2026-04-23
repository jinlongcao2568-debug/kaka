from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import (
    extract_service_record_dependencies,
    load_fixture,
    load_repo_json,
    run_internal_chain_to_stage7,
)
from shared.contracts_runtime import ContractRecord, ContractStore, StageBundle
from shared.pipeline import run_internal_chain
from stage1_tasking.service import Stage1Service
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage8_outreach.service import Stage8Service
from stage9_delivery.service import Stage9Service
from storage import hydrate_stage_bundle, persist_stage_bundle, reset_default_storage


VERTICAL_SLICE_FIXTURE = "stage1_to_stage5_real_source_vertical_slice_proc_national_html.json"


class TestInternalChain(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ContractStore.default()
        self.contracts = {
            1: load_repo_json("handoff/stage1_to_stage2/contract.json"),
            2: load_repo_json("handoff/stage2_to_stage3/contract.json"),
            3: load_repo_json("handoff/stage3_to_stage4/contract.json"),
            4: load_repo_json("handoff/stage4_to_stage5/contract.json"),
            5: load_repo_json("handoff/stage5_to_stage6/contract.json"),
            6: load_repo_json("handoff/stage6_to_stage7/contract.json"),
            7: load_repo_json("handoff/stage7_to_stage8/contract.json"),
            8: load_repo_json("handoff/stage8_to_stage9/contract.json"),
        }
        self.integration_rows = {
            row["contractId"]: row for row in load_repo_json("handoff/integration_matrix.json")["rows"]
        }

    def _assert_h08_payload_ready(self, payload: dict[str, object]) -> None:
        missing_fields = [
            field_name
            for field_name in self.contracts[8]["required_payload_fields"]
            if field_name not in payload
        ]
        self.assertFalse(missing_fields, f"H-08 payload missing required fields: {missing_fields}")

    def _build_stage8_bundle(self, payload: dict[str, object] | None = None) -> StageBundle:
        result = run_internal_chain(payload or load_fixture("internal_chain_happy.json"))
        return result["stage8"]

    def test_happy_path_stage4_to_stage7_formal_outputs(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))

        stage1 = result["stage1"]
        self.assertEqual(
            set(stage1.records.keys()),
            {
                "task_execution_context",
                "project_identity_strategy",
                "clock_strategy_profile",
                "execution_context",
            },
        )
        self.assertEqual(stage1.handoff.get("default_route"), "LIST_TO_DETAIL")
        self.assertEqual(stage1.handoff.get("source_registry_id"), "SRC-REG-PROC-NATIONAL-HTML")
        self.assertEqual(stage1.handoff.get("route_policy_id"), "ROUTE-PROC-NOTICE-001")

        stage2 = result["stage2"]
        self.assertEqual(
            set(stage2.records.keys()),
            {
                "public_chain",
                "clock_chain_profile",
                "notice_version_chain",
                "fixation_bundle",
            },
        )
        self.assertEqual(stage2.record("fixation_bundle").get("carrier_type"), "HTML_PAGE")
        self.assertEqual(stage2.record("clock_chain_profile").get("clock_conflict_state"), "CONSISTENT")
        self.assertEqual(stage2.handoff.get("fixation_bundle_id"), stage2.record("fixation_bundle").get("fixation_bundle_id"))
        self.assertEqual(stage2.handoff.get("source_registry_id"), "SRC-REG-PROC-NATIONAL-HTML")
        self.assertEqual(stage2.handoff.get("route_policy_id"), "ROUTE-PROC-NOTICE-001")
        self.assertEqual(stage2.handoff.get("fallback_route"), "DETAIL_DIRECT")
        self.assertEqual(stage2.handoff.get("route_decision_state"), "ALLOW")
        self.assertEqual(stage2.handoff.get("route_review_reasons"), [])
        self.assertEqual(stage2.handoff.get("winning_version_resolution_rule_id"), "VERSION-PROC-NOTICE-001")
        self.assertEqual(stage2.handoff.get("version_conflict_state"), "CONSISTENT")
        self.assertEqual(stage2.handoff.get("clock_resolution_rule_id"), "CLOCK-DEFAULT")

        stage3 = result["stage3"]
        self.assertEqual(
            set(stage3.records.keys()),
            {
                "field_lineage_record",
                "project_base",
                "bidder_candidate",
                "project_manager",
            },
        )
        self.assertEqual(stage3.handoff.get("fixation_bundle_id"), stage2.record("fixation_bundle").get("fixation_bundle_id"))
        self.assertEqual(stage3.handoff.get("source_registry_id"), stage2.handoff.get("source_registry_id"))
        self.assertEqual(stage3.handoff.get("route_policy_id"), stage2.handoff.get("route_policy_id"))
        self.assertEqual(stage3.handoff.get("route_decision_state"), stage2.handoff.get("route_decision_state"))
        self.assertEqual(stage3.handoff.get("winning_version_resolution_rule_id"), stage2.handoff.get("winning_version_resolution_rule_id"))
        self.assertEqual(stage3.handoff.get("clock_resolution_rule_id"), stage2.handoff.get("clock_resolution_rule_id"))
        project_id = stage3.record("project_base").get("project_id")
        self.assertEqual(stage3.record("project_base").get("stage3_truth_layer_ref_optional"), f"ST3TL-{project_id}")
        self.assertEqual(stage3.record("project_base").get("field_lineage_collection_ref_optional"), f"LINEAGE-{project_id}")
        self.assertEqual(stage3.record("project_base").get("bidder_candidate_collection_ref_optional"), f"CSET-{project_id}")
        self.assertEqual(stage3.record("project_base").get("stage3_review_path_ref_optional"), "STAGE3_READY_FOR_STAGE4")
        self.assertEqual(stage3.record("field_lineage_record").get("normalized_value_ref_optional"), "project_base.project_name")
        self.assertEqual(stage3.record("field_lineage_record").get("review_path_optional"), "STAGE3_READY_FOR_STAGE4")
        self.assertEqual(stage3.record("field_lineage_record").get("candidate_collection_ref_optional"), f"CSET-{project_id}")
        self.assertEqual(stage3.record("bidder_candidate").get("candidate_collection_ref_optional"), f"CSET-{project_id}")
        self.assertEqual(
            stage3.record("bidder_candidate").get("candidate_source_lineage_ids_optional"),
            [stage3.record("field_lineage_record").get("field_lineage_id")],
        )
        self.assertEqual(stage3.inputs.get("stage3_truth_layer_ref_optional"), f"ST3TL-{project_id}")
        self.assertEqual(stage3.inputs.get("candidate_collection_ref_optional"), f"CSET-{project_id}")
        self.assertEqual(stage3.inputs.get("route_policy_id"), stage2.handoff.get("route_policy_id"))

        stage4 = result["stage4"]
        self.assertEqual(
            set(stage4.records.keys()),
            {
                "public_attack_surface",
                "focus_bidder_verification_profile",
                "pseudo_competitor_signal_set",
                "evidence_grade_profile",
            },
        )
        self.assertEqual(
            stage4.record("focus_bidder_verification_profile").get("verification_state"), "PASS"
        )
        self.assertEqual(stage4.record("pseudo_competitor_signal_set").get("confidence_band"), "MEDIUM")
        for field_name in (
            "project_id",
            "focus_bidder_id",
            "public_attack_surface_id",
            "verification_profile_id",
            "evidence_grade_profile_id",
            "public_capability_tier",
            "verification_state",
            "external_use_grade",
            "cross_check_state",
            "fixation_status",
            "provenance_chain_status",
            "retrieval_readiness_status",
            "lineage_status",
            "conflict_state",
            "pseudo_competitor_signal_set_id",
            "confidence_band",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
        ):
            self.assertIn(field_name, self.contracts[4]["required_payload_fields"])
            self.assertIn(field_name, stage4.handoff)
            self.assertIn(field_name, stage4.inputs)
        self.assertEqual(
            stage4.handoff.get("verification_state"),
            stage4.record("focus_bidder_verification_profile").get("verification_state"),
        )
        self.assertEqual(
            stage4.handoff.get("cross_check_state"),
            stage4.record("evidence_grade_profile").get("cross_check_state"),
        )
        self.assertEqual(
            stage4.handoff.get("public_attack_surface_id"),
            stage4.record("public_attack_surface").get("public_attack_surface_id"),
        )
        self.assertEqual(
            stage4.handoff.get("verification_profile_id"),
            stage4.record("focus_bidder_verification_profile").get("verification_profile_id"),
        )
        self.assertEqual(
            stage4.handoff.get("evidence_grade_profile_id"),
            stage4.record("evidence_grade_profile").get("evidence_grade_profile_id"),
        )
        self.assertEqual(stage4.handoff.get("lineage_status"), "NORMALIZED")
        self.assertEqual(stage4.handoff.get("conflict_state"), "CONSISTENT")
        for field_name in (
            "fallback_route",
            "route_decision_state",
            "route_review_reasons",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
        ):
            self.assertEqual(stage4.handoff.get(field_name), stage3.handoff.get(field_name), field_name)
        public_refs = stage4.record("public_attack_surface").get("public_supporting_refs")
        self.assertIn("STAGE3_LINEAGE_STATUS:NORMALIZED", public_refs)
        self.assertIn("STAGE3_CONFLICT_STATE:CONSISTENT", public_refs)
        self.assertIn("STAGE3_REVIEW_PATH:STAGE3_READY_FOR_STAGE4", public_refs)
        self.assertIn(f"STAGE3_CANDIDATE_COLLECTION:CSET-{project_id}", public_refs)
        self.assertEqual(
            stage4.record("focus_bidder_verification_profile").get("relation_conflict_state"),
            "CONSISTENT",
        )
        self.assertIn(
            "STAGE3_LINEAGE_NORMALIZED",
            stage4.record("pseudo_competitor_signal_set").get("signal_tags"),
        )
        self.assertIn(
            "stage3_conflict=CONSISTENT",
            stage4.record("pseudo_competitor_signal_set").get("explanation"),
        )
        self.assertEqual(stage4.record("evidence_grade_profile").get("cross_check_state"), "PASS")

        stage5 = result["stage5"]
        self.assertEqual(
            set(stage5.records.keys()),
            {"evidence", "rule_hit", "rule_gate_decision", "evidence_gate_decision"},
        )
        self.assertEqual(stage5.record("evidence").get("retrieval_readiness_status"), "READY")
        self.assertEqual(stage5.record("rule_hit").get("rule_hit_state"), "CONFIRMED")
        for field_name in (
            "project_id",
            "focus_bidder_id",
            "public_attack_surface_id",
            "verification_profile_id",
            "evidence_grade_profile_id",
            "public_capability_tier",
            "verification_state",
            "external_use_grade",
            "cross_check_state",
            "fixation_status",
            "provenance_chain_status",
            "retrieval_readiness_status",
            "lineage_status",
            "conflict_state",
            "pseudo_competitor_signal_set_id",
            "confidence_band",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
        ):
            self.assertIn(field_name, self.contracts[4]["required_payload_fields"])
            self.assertIn(field_name, stage5.inputs)
            self.assertEqual(stage5.inputs.get(field_name), stage4.handoff.get(field_name))
        for field_name in (
            "rule_hit_id",
            "rule_hit_state",
            "evidence_id",
            "rule_gate_decision_id",
            "evidence_gate_decision_id",
            "rule_gate_status",
            "evidence_gate_status",
            "coverage_sellable_state",
            "delivery_risk_state",
        ):
            self.assertIn(field_name, self.contracts[5]["required_payload_fields"])
            self.assertIn(field_name, stage5.handoff)
            self.assertIn(field_name, stage5.inputs)
        self.assertEqual(
            stage5.handoff.get("rule_gate_decision_id"),
            stage5.record("rule_gate_decision").get("gate_id"),
        )
        self.assertEqual(
            stage5.handoff.get("evidence_gate_decision_id"),
            stage5.record("evidence_gate_decision").get("gate_id"),
        )
        self.assertEqual(stage5.handoff.get("rule_hit_state"), stage5.record("rule_hit").get("rule_hit_state"))
        self.assertEqual(stage5.handoff.get("lineage_status"), stage4.handoff.get("lineage_status"))
        self.assertEqual(stage5.handoff.get("conflict_state"), stage4.handoff.get("conflict_state"))

        stage6 = result["stage6"]
        self.assertEqual(
            set(stage6.records.keys()),
            {
                "project_fact",
                "legal_action_recommendation",
                "review_queue_profile",
                "report_record",
                "challenger_candidate_profile",
            },
        )
        self.assertEqual(stage6.record("project_fact").get("sale_gate_status"), "OPEN")
        self.assertEqual(stage6.record("report_record").get("report_status"), "ISSUED")
        self.assertEqual(
            stage6.record("legal_action_recommendation").get("action_family"), "OBJECTION_PREP"
        )
        self.assertEqual(stage6.record("project_fact").get("clue_summary"), [])
        self.assertEqual(stage6.record("project_fact").get("risk_summary"), [])
        self.assertIn("confidence_score_optional", stage6.handoff)
        self.assertEqual(
            stage6.record("project_fact").get("competitor_quality_grade"),
            stage6.handoff.get("competitor_quality_grade"),
        )
        self.assertEqual(stage6.record("review_queue_profile").get("review_lane"), "STANDARD")
        self.assertEqual(stage6.record("review_queue_profile").get("review_priority_score"), 46)
        self.assertEqual(stage6.record("review_queue_profile").get("review_queue_bucket"), "NORMAL")

        stage7 = result["stage7"]
        self.assertEqual(
            set(stage7.records.keys()),
            {
                "multi_competitor_collection",
                "legal_action_actor_profile",
                "procurement_decision_actor_profile",
                "buyer_fit",
                "challenger_buyer_fit",
                "sales_lead",
                "offer_recommendation",
                "saleable_opportunity",
            },
        )
        opportunity = stage7.record("saleable_opportunity")
        self.assertEqual(opportunity.get("saleability_status"), "QUALIFIED")
        self.assertEqual(opportunity.get("buyer_fit_id"), stage7.record("buyer_fit").get("buyer_fit_id"))
        self.assertIn("BUYER_FIT_SCORECARD", stage7.record("buyer_fit").get("fit_reason_tags"))
        self.assertIn("CHALLENGER_BUYER_FIT_SCORECARD", stage7.record("challenger_buyer_fit").get("fit_reason_tags"))
        self.assertIn("LEAD_VALUE_MODEL", stage7.record("sales_lead").get("lead_reason_summary"))
        self.assertIn("OPPORTUNITY_VALUE_MODEL", opportunity.get("major_value_points"))
        self.assertEqual(
            opportunity.get("challenger_profile_id"),
            stage6.record("challenger_candidate_profile").get("challenger_profile_id"),
        )
        self.assertEqual(
            stage7.record("legal_action_actor_profile").get("action_family_scope"),
            stage6.record("legal_action_recommendation").get("action_family"),
        )
        self.assertEqual(
            stage7.record("multi_competitor_collection").get("selection_trace").get("selection_policy_id"),
            "stage7_multi_competitor_resolution_v1",
        )

    def test_review_block_paths_stage4_to_stage7(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture("internal_chain_block.json"))

        stage4 = result["stage4"]
        self.assertEqual(stage4.record("public_attack_surface").get("verification_state"), "REVIEW")
        self.assertEqual(stage4.record("pseudo_competitor_signal_set").get("confidence_band"), "LOW")

        stage5 = result["stage5"]
        self.assertIn("review_request", stage5.records)
        self.assertEqual(stage5.record("review_request").get("missing_condition_family"), "MISSING_EVIDENCE")
        self.assertEqual(stage5.record("rule_hit").get("rule_hit_state"), "REVIEW_REQUIRED")
        self.assertIn("review_request_id", self.contracts[5]["optional_payload_fields"])
        self.assertEqual(
            stage5.handoff.get("review_request_id"),
            stage5.record("review_request").get("review_request_id"),
        )
        self.assertEqual(
            stage5.handoff.get("missing_condition_family"),
            stage5.record("review_request").get("missing_condition_family"),
        )
        self.assertEqual(stage5.handoff.get("review_lane"), stage5.record("review_request").get("review_lane"))

        stage6 = result["stage6"]
        self.assertEqual(stage6.record("project_fact").get("sale_gate_status"), "REVIEW")
        self.assertEqual(stage6.record("report_record").get("report_status"), "REVOKED")
        self.assertEqual(
            stage6.record("legal_action_recommendation").get("action_family"), "REVIEW_ONLY"
        )
        self.assertEqual(
            stage6.inputs.get("linked_review_request_id_optional"),
            stage5.handoff.get("review_request_id"),
        )
        self.assertEqual(
            stage6.handoff.get("linked_review_request_id_optional"),
            stage5.handoff.get("review_request_id"),
        )
        self.assertEqual(
            stage6.record("review_queue_profile").get("review_lane"),
            stage5.handoff.get("review_lane"),
        )
        self.assertEqual(
            stage6.inputs.get("stage6_review_report_trace", {})
            .get("h05_authority_snapshot", {})
            .get("linked_review_request_id_optional"),
            stage5.handoff.get("review_request_id"),
        )

        stage7 = result["stage7"]
        self.assertEqual(stage7.record("sales_lead").get("lead_status"), "REVIEW")
        self.assertEqual(stage7.record("saleable_opportunity").get("saleability_status"), "BLOCKED")
        self.assertEqual(stage7.handoff.get("sale_gate_status"), stage6.handoff.get("sale_gate_status"))
        self.assertEqual(stage7.handoff.get("report_status"), stage6.handoff.get("report_status"))
        self.assertEqual(stage7.handoff.get("review_lane_optional"), stage6.handoff.get("review_lane"))
        self.assertEqual(
            stage7.handoff.get("linked_review_request_id_optional"),
            stage6.handoff.get("linked_review_request_id_optional"),
        )
        self.assertEqual(
            stage7.handoff.get("missing_condition_family_optional"),
            stage6.handoff.get("missing_condition_family_optional"),
        )
        self.assertEqual(
            stage7.inputs.get("stage7_resolution_trace", {})
            .get("review_gate_report_constraints", {})
            .get("linked_review_request_id_optional"),
            stage6.handoff.get("linked_review_request_id_optional"),
        )
        self.assertEqual(
            stage7.record("legal_action_actor_profile").get("actionability_state"), "REVIEW_REQUIRED"
        )

    def test_handoff_producer_sets_cover_service_outputs(self) -> None:
        happy = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        blocked = run_internal_chain_to_stage7(load_fixture("internal_chain_block.json"))

        stage_contract_map = {
            "stage1": self.contracts[1],
            "stage2": self.contracts[2],
            "stage3": self.contracts[3],
            "stage4": self.contracts[4],
            "stage5": self.contracts[5],
            "stage6": self.contracts[6],
            "stage7": self.contracts[7],
        }

        for stage_key, contract in stage_contract_map.items():
            declared = set(contract["producer_objects"])
            self.assertTrue(set(happy[stage_key].records.keys()).issubset(declared))
            self.assertTrue(set(blocked[stage_key].records.keys()).issubset(declared))

        self.assertIn("review_request", blocked["stage5"].records)
        self.assertNotIn("review_request", happy["stage5"].records)

    def test_stage3_truth_layer_handoff_requires_lineage_state_for_stage4(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture(VERTICAL_SLICE_FIXTURE))
        stage2 = result["stage2"]
        stage3 = result["stage3"]
        h03 = self.contracts[3]

        for field_name in (
            "lineage_status",
            "conflict_state",
            "fixation_bundle_id",
            "source_registry_id",
            "route_policy_id",
            "fallback_route",
            "route_decision_state",
            "route_review_reasons",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
            "stage3_review_path_ref_optional",
        ):
            self.assertIn(field_name, h03["required_payload_fields"])
            self.assertIn(field_name, h03["consumer_runtime_required_fields"])
        for field_name in (
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, h03["optional_payload_fields"])

        validation = self.store.evaluate_handoff_consumer(
            producer_bundle=stage3,
            consumer_stage=4,
        )
        self.assertEqual(validation.decision_state, "ALLOW")
        self.assertEqual(stage3.handoff.get("fallback_route"), stage2.handoff.get("fallback_route"))
        self.assertEqual(stage3.handoff.get("clock_precedence_rule_id"), stage2.handoff.get("clock_precedence_rule_id"))
        self.assertEqual(
            stage3.handoff.get("current_action_start_at_optional"),
            stage2.handoff.get("current_action_start_at_optional"),
        )
        self.assertEqual(
            stage3.handoff.get("current_action_deadline_at_optional"),
            stage2.handoff.get("current_action_deadline_at_optional"),
        )
        for field_name in h03["required_payload_fields"]:
            resolved = stage3.handoff.get(field_name, stage3.inputs.get(field_name))
            if resolved in (None, ""):
                resolved = next(
                    (
                        record.get(field_name)
                        for record in stage3.records.values()
                        if record.get(field_name) not in (None, "")
                    ),
                    None,
                )
            self.assertIsNotNone(resolved, field_name)

        lineage_data = dict(stage3.record("field_lineage_record").data)
        lineage_data.pop("lineage_status")
        broken_bundle = StageBundle(
            stage=3,
            records={
                **stage3.records,
                "field_lineage_record": ContractRecord(
                    object_type="field_lineage_record",
                    data=lineage_data,
                ),
            },
            handoff={
                key: value
                for key, value in stage3.handoff.items()
                if key != "lineage_status"
            },
            trace_rules=list(stage3.trace_rules),
            inputs={
                key: value
                for key, value in stage3.inputs.items()
                if key != "lineage_status"
            },
        )
        broken_validation = self.store.evaluate_handoff_consumer(
            producer_bundle=broken_bundle,
            consumer_stage=4,
        )
        self.assertEqual(broken_validation.decision_state, "BLOCK")
        self.assertIn("lineage_status", broken_validation.reasons[0])

    def test_stage3_review_path_materializes_when_lineage_is_unresolved(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["flags"] = {"missing_source": True}

        result = run_internal_chain_to_stage7(payload)
        stage3 = result["stage3"]

        self.assertEqual(stage3.record("project_base").get("stage3_review_path_ref_optional"), "STAGE3_REVIEW_REQUIRED")
        self.assertEqual(stage3.record("field_lineage_record").get("review_path_optional"), "STAGE3_REVIEW_REQUIRED")
        self.assertEqual(
            stage3.record("field_lineage_record").get("unresolved_reason_optional"),
            "missing_source_slice_or_normalization_rule",
        )
        self.assertEqual(
            stage3.record("bidder_candidate").get("candidate_review_path_optional"),
            "STAGE3_REVIEW_REQUIRED",
        )

    def test_stage2_projects_h02_optional_precedence_fields(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture(VERTICAL_SLICE_FIXTURE))
        stage2 = result["stage2"]
        h02 = self.contracts[2]

        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "route_decision_state",
            "route_review_reasons",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_precedence_rule_id",
            "clock_resolution_rule_id",
            "clock_conflict_state",
            "collection_state",
        ):
            self.assertIn(field_name, h02["required_payload_fields"])
            self.assertIn(field_name, stage2.handoff)
            self.assertIn(field_name, stage2.inputs)

        for field_name in (
            "fallback_route",
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, h02["optional_payload_fields"])
            self.assertIn(field_name, stage2.handoff)

        self.assertEqual(stage2.handoff.get("source_registry_id"), "SRC-REG-PROC-NATIONAL-HTML")
        self.assertEqual(stage2.handoff.get("route_policy_id"), "ROUTE-PROC-NOTICE-001")
        self.assertEqual(stage2.handoff.get("fallback_route"), "DETAIL_DIRECT")
        self.assertEqual(stage2.handoff.get("route_decision_state"), "ALLOW")
        self.assertEqual(stage2.handoff.get("route_review_reasons"), [])
        self.assertEqual(stage2.handoff.get("winning_version_resolution_rule_id"), "VERSION-PROC-NOTICE-001")
        self.assertEqual(stage2.handoff.get("version_conflict_state"), "CONSISTENT")
        self.assertEqual(stage2.handoff.get("clock_precedence_rule_id"), "CLOCK-PROC-NOTICE-001")
        self.assertEqual(stage2.handoff.get("clock_resolution_rule_id"), "CLOCK-DEFAULT")
        self.assertEqual(stage2.handoff.get("clock_conflict_state"), "CONSISTENT")
        self.assertEqual(stage2.handoff.get("collection_state"), "PARSED")
        self.assertEqual(stage2.handoff.get("current_action_start_at_optional"), "2026-04-14T00:00:00Z")
        self.assertEqual(stage2.handoff.get("current_action_deadline_at_optional"), "2026-04-24T23:59:59Z")
        self.assertIn("consumer_obligations", h02)
        self.assertIn("consumer_must_not_recompute_fields", h02)
        self.assertEqual(stage2.inputs.get("version_precedence_source"), "source_registry")
        self.assertEqual(stage2.inputs.get("version_conflict_state"), "CONSISTENT")
        self.assertEqual(stage2.inputs.get("clock_precedence_source"), "h01_authority")
        stage2_trace = stage2.inputs.get("stage12_extractor_trace", {}).get("stage2", {})
        self.assertEqual(stage2_trace.get("source_registry_id_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("route_policy_id_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("default_route_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("fallback_route_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("clock_resolution_rule_id_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("clock_precedence_rule_id_source"), "h01_authority")

    def test_stage2_consumes_h01_authority_over_payload_overrides(self) -> None:
        stage1 = Stage1Service().run(load_fixture(VERTICAL_SLICE_FIXTURE))
        conflicted = StageBundle(
            stage=1,
            records=dict(stage1.records),
            handoff=dict(stage1.handoff),
            trace_rules=list(stage1.trace_rules),
            inputs={
                **stage1.inputs,
                "source_registry_id": "SRC-REG-PROC-CITY-PDF",
                "route_policy_id": "ROUTE-PROC-ATTACHMENT-001",
                "default_route": "ATTACHMENT_FIRST",
                "fallback_route": "SEMI_MANUAL",
                "clock_resolution_rule_id": "CLOCK-OVERRIDE",
                "clock_precedence_rule_id": "CLOCK-PROC-ATTACHMENT-001",
            },
        )

        stage2 = Stage2Service().run(conflicted)

        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "default_route",
            "fallback_route",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ):
            self.assertEqual(stage2.inputs.get(field_name), stage1.handoff.get(field_name), field_name)
        public_chain = stage2.record("public_chain")
        clock_chain = stage2.record("clock_chain_profile")
        self.assertEqual(public_chain.get("source_registry_id"), stage1.handoff.get("source_registry_id"))
        self.assertEqual(public_chain.get("route_policy_id"), stage1.handoff.get("route_policy_id"))
        self.assertEqual(public_chain.get("default_route"), stage1.handoff.get("default_route"))
        self.assertEqual(public_chain.get("fallback_route"), stage1.handoff.get("fallback_route"))
        self.assertEqual(clock_chain.get("clock_resolution_rule_id"), stage1.handoff.get("clock_resolution_rule_id"))
        self.assertEqual(stage2.handoff.get("clock_precedence_rule_id"), stage1.handoff.get("clock_precedence_rule_id"))

        stage2_trace = stage2.inputs.get("stage12_extractor_trace", {}).get("stage2", {})
        self.assertEqual(stage2_trace.get("default_route_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("fallback_route_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("clock_precedence_rule_id_source"), "h01_authority")

    def test_stage3_routes_h02_authority_gaps_or_conflicts_to_review_or_block(self) -> None:
        stage1 = Stage1Service().run(load_fixture("internal_chain_happy.json"))
        stage2 = Stage2Service().run(stage1)
        conflicted_stage2 = StageBundle(
            stage=2,
            records={
                **stage2.records,
                "notice_version_chain": ContractRecord(
                    object_type="notice_version_chain",
                    data={
                        **stage2.record("notice_version_chain").data,
                        "winning_version_resolution_rule_id": "VERSION-CONFLICT",
                    },
                ),
                "clock_chain_profile": ContractRecord(
                    object_type="clock_chain_profile",
                    data={
                        **stage2.record("clock_chain_profile").data,
                        "clock_resolution_rule_id": "CLOCK-CONFLICT",
                    },
                ),
            },
            handoff={
                key: value
                for key, value in stage2.handoff.items()
                if key not in {"fixation_bundle_id", "route_decision_state", "route_review_reasons"}
            },
            trace_rules=list(stage2.trace_rules),
            inputs={
                **stage2.inputs,
                "source_registry_id": "SRC-REG-PROC-CITY-PDF",
                "route_policy_id": "ROUTE-PROC-CITY-OVERRIDE",
                "winning_version_resolution_rule_id": "VERSION-OVERRIDE",
                "clock_resolution_rule_id": "CLOCK-OVERRIDE",
            },
        )

        stage3 = Stage3Service().run(conflicted_stage2)

        self.assertEqual(stage3.handoff.get("route_decision_state"), "BLOCK")
        self.assertEqual(stage3.record("project_base").get("public_chain_status"), "BROKEN")
        self.assertEqual(stage3.record("project_base").get("stage3_review_path_ref_optional"), "STAGE3_REVIEW_REQUIRED")
        self.assertEqual(stage3.record("field_lineage_record").get("lineage_status"), "UNVERIFIED")
        self.assertEqual(stage3.record("field_lineage_record").get("conflict_state"), "UNRESOLVED")
        for reason in (
            "missing_h02_handoff_field:fixation_bundle_id",
            "missing_h02_handoff_field:route_decision_state",
            "missing_h02_handoff_field:route_review_reasons",
            "h02_authority_conflict:winning_version_resolution_rule_id",
            "h02_authority_conflict:clock_resolution_rule_id",
        ):
            self.assertIn(reason, stage3.handoff.get("route_review_reasons"))

    def test_stage2_routes_h01_route_mismatch_to_review_path(self) -> None:
        stage1 = Stage1Service().run(load_fixture("internal_chain_happy.json"))
        mismatched = StageBundle(
            stage=1,
            records=dict(stage1.records),
            handoff={
                **stage1.handoff,
                "default_route": "ATTACHMENT_FIRST",
                "fallback_route": "SEMI_MANUAL",
            },
            trace_rules=list(stage1.trace_rules),
            inputs=dict(stage1.inputs),
        )

        stage2 = Stage2Service().run(mismatched)

        self.assertEqual(stage2.handoff.get("route_decision_state"), "REVIEW")
        self.assertEqual(stage2.handoff.get("collection_state"), "REVIEW_REQUIRED")
        self.assertIn("default_route_mismatch_requires_review", stage2.handoff.get("route_review_reasons"))
        self.assertIn("fallback_route_mismatch_requires_review", stage2.handoff.get("route_review_reasons"))

    def test_stage2_routes_missing_h01_clock_authority_to_review_path(self) -> None:
        stage1 = Stage1Service().run(load_fixture("internal_chain_happy.json"))
        missing_clock_authority = StageBundle(
            stage=1,
            records=dict(stage1.records),
            handoff={
                key: value
                for key, value in stage1.handoff.items()
                if key not in {"clock_resolution_rule_id", "clock_precedence_rule_id"}
            },
            trace_rules=list(stage1.trace_rules),
            inputs=dict(stage1.inputs),
        )

        stage2 = Stage2Service().run(missing_clock_authority)

        self.assertEqual(stage2.handoff.get("route_decision_state"), "REVIEW")
        self.assertEqual(stage2.handoff.get("collection_state"), "REVIEW_REQUIRED")
        self.assertIn(
            "missing_h01_authority_field:clock_resolution_rule_id",
            stage2.handoff.get("route_review_reasons"),
        )
        self.assertIn(
            "missing_h01_authority_field:clock_precedence_rule_id",
            stage2.handoff.get("route_review_reasons"),
        )

    def test_consumer_dependency_sets_align_with_integration_matrix(self) -> None:
        expected = {
            "H-01-STAGE1-TO-STAGE2": sorted(
                self.integration_rows["H-01-STAGE1-TO-STAGE2"]["criticalObjects"]
            ),
            "H-02-STAGE2-TO-STAGE3": sorted(
                self.integration_rows["H-02-STAGE2-TO-STAGE3"]["criticalObjects"]
            ),
            "H-03-STAGE3-TO-STAGE4": sorted(
                self.integration_rows["H-03-STAGE3-TO-STAGE4"]["criticalObjects"]
            ),
            "H-04-STAGE4-TO-STAGE5": sorted(
                self.integration_rows["H-04-STAGE4-TO-STAGE5"]["criticalObjects"]
            ),
            "H-05-STAGE5-TO-STAGE6": sorted(
                self.integration_rows["H-05-STAGE5-TO-STAGE6"]["criticalObjects"]
            ),
            "H-06-STAGE6-TO-STAGE7": sorted(
                self.integration_rows["H-06-STAGE6-TO-STAGE7"]["criticalObjects"]
            ),
            "H-07-STAGE7-TO-STAGE8": sorted(
                self.integration_rows["H-07-STAGE7-TO-STAGE8"]["criticalObjects"]
            ),
            "H-08-STAGE8-TO-STAGE9": sorted(
                self.integration_rows["H-08-STAGE8-TO-STAGE9"]["criticalObjects"]
            ),
        }
        actual = {
            "H-01-STAGE1-TO-STAGE2": extract_service_record_dependencies(
                "src/stage2_ingestion/service.py"
            ),
            "H-02-STAGE2-TO-STAGE3": extract_service_record_dependencies(
                "src/stage3_parsing/service.py"
            ),
            "H-03-STAGE3-TO-STAGE4": extract_service_record_dependencies(
                "src/stage4_verification/service.py"
            ),
            "H-04-STAGE4-TO-STAGE5": extract_service_record_dependencies(
                "src/stage5_rules_evidence/service.py"
            ),
            "H-05-STAGE5-TO-STAGE6": extract_service_record_dependencies(
                "src/stage6_fact_review/service.py"
            ),
            "H-06-STAGE6-TO-STAGE7": extract_service_record_dependencies(
                "src/stage7_sales/service.py"
            ),
            "H-07-STAGE7-TO-STAGE8": extract_service_record_dependencies(
                "src/stage8_outreach/service.py"
            ),
            "H-08-STAGE8-TO-STAGE9": extract_service_record_dependencies(
                "src/stage9_delivery/service.py"
            ),
        }
        self.assertEqual(actual, expected)

    def test_stage6_to_stage7_minimal_chain(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        handoff = result["stage6"].handoff
        for field_name in self.contracts[6]["required_payload_fields"]:
            self.assertIn(field_name, handoff)
        for field_name in (
            "project_fact_id",
            "review_queue_profile_id",
            "review_lane",
            "report_record_id",
            "challenger_candidate_profile_id",
            "saleability_status",
        ):
            self.assertIn(field_name, self.contracts[6]["required_payload_fields"])
            self.assertIn(field_name, self.contracts[6]["minimum_producer_fields"])
            self.assertIn(field_name, self.contracts[6]["consumer_runtime_required_fields"])
            self.assertIn(field_name, self.contracts[6]["consumer_must_not_recompute_fields"])
        self.assertIn("consumer_obligations", self.contracts[6])
        self.assertIn("consumer_must_not_recompute_fields", self.contracts[6])
        for field_name in (
            "sale_gate_status",
            "competitor_quality_grade",
            "window_status",
            "report_status",
            "review_task_status",
            "action_family",
            "challenger_profile_id",
        ):
            self.assertIn(field_name, self.contracts[6]["consumer_must_not_recompute_fields"])
        for field_name in (
            "review_priority_score",
            "review_queue_bucket",
            "window_risk_level",
            "commercial_urgency_level",
            "report_id",
            "minimum_release_level",
            "confidence_score_optional",
        ):
            self.assertIn(field_name, self.contracts[6]["optional_payload_fields"])
            self.assertIn(field_name, handoff)
            self.assertIn(field_name, result["stage6"].inputs)
        self.assertEqual(handoff["project_fact_id"], result["stage6"].record("project_fact").get("project_fact_id"))
        self.assertEqual(
            handoff["review_queue_profile_id"],
            result["stage6"].record("review_queue_profile").get("queue_profile_id"),
        )
        self.assertEqual(handoff["report_record_id"], result["stage6"].record("report_record").get("report_id"))
        self.assertEqual(
            handoff["challenger_candidate_profile_id"],
            result["stage6"].record("challenger_candidate_profile").get("challenger_profile_id"),
        )
        self.assertEqual(handoff["saleability_status"], "CANDIDATE")

        stage7_outputs = set(result["stage7"].records.keys())
        self.assertEqual(stage7_outputs, set(self.contracts[6]["consumer_objects"]))
        self.assertEqual(result["stage7"].record("buyer_fit").get("buyer_type"), "GOVERNMENT")
        self.assertEqual(
            result["stage7"].record("procurement_decision_actor_profile").get("actor_role_cluster"),
            "PROCUREMENT_DECISION",
        )
        self.assertEqual(
            result["stage7"].record("legal_action_actor_profile").get("actor_org_name"),
            handoff["legal_action_actor_org_name_seed"],
        )
        self.assertEqual(
            result["stage7"].record("procurement_decision_actor_profile").get("actor_org_name"),
            handoff["procurement_decision_actor_org_name_seed"],
        )
        self.assertEqual(
            result["stage7"].record("buyer_fit").get("buyer_type"),
            handoff["buyer_type_hint"],
        )

    def test_stage6_supplement_reference_stays_out_of_stage7_formal_surface(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_block.json"))
        payload.update(
            {
                "supplement_material_family": "MISSING_ATTACHMENT_BACKFILL",
                "supplement_source_owner": "MANUAL_REVIEW",
            }
        )
        result = run_internal_chain_to_stage7(payload)
        stage6 = result["stage6"]
        stage7 = result["stage7"]

        self.assertIn("private_supplement_record_optional", stage6.inputs)
        self.assertEqual(
            stage6.handoff.get("private_supplement_release_state_optional"),
            "REVIEW_ELIGIBLE",
        )
        self.assertNotIn("private_supplement_record", stage7.records)
        self.assertNotIn("private_supplement_record_id_optional", stage7.handoff)

    def test_stage6_hold_state_when_report_not_issued(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["flags"] = {}

        result = run_internal_chain_to_stage7(payload)
        stage6 = result["stage6"]
        stage7 = result["stage7"]

        self.assertEqual(stage6.record("project_fact").get("sale_gate_status"), "HOLD")
        self.assertEqual(stage6.record("report_record").get("report_status"), "READY")
        self.assertEqual(stage6.record("legal_action_recommendation").get("action_family"), "REVIEW_ONLY")
        self.assertEqual(stage7.record("sales_lead").get("lead_status"), "REVIEW")
        self.assertEqual(stage7.record("saleable_opportunity").get("saleability_status"), "RESTRICTED")

    def test_stage6_review_queue_uses_window_formula_for_urgent_window(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "commercial_urgency_level": "HIGH",
                "current_action_deadline_at_optional": "2026-04-20T00:00:00Z",
            }
        )

        result = run_internal_chain_to_stage7(payload)
        stage6 = result["stage6"]

        self.assertEqual(stage6.record("legal_action_recommendation").get("window_status"), "ACTIONABLE")
        self.assertEqual(stage6.record("review_queue_profile").get("review_lane"), "HIGH_PRIORITY")
        self.assertEqual(stage6.record("review_queue_profile").get("review_priority_score"), 73)
        self.assertEqual(stage6.record("review_queue_profile").get("review_queue_bucket"), "HIGH")
        self.assertEqual(stage6.inputs.get("window_urgency_score"), 80)

    def test_stage7_blocks_when_stage6_formal_seed_inputs_are_missing(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        broken_bundle = StageBundle(
            stage=6,
            records=dict(result["stage6"].records),
            handoff={
                key: value
                for key, value in result["stage6"].handoff.items()
                if key not in {"legal_action_actor_org_name_seed", "buyer_type_hint"}
            },
            trace_rules=list(result["stage6"].trace_rules),
            inputs={
                key: value
                for key, value in result["stage6"].inputs.items()
                if key not in {"legal_action_actor_org_name_seed", "buyer_type_hint"}
            },
        )
        validation = self.store.evaluate_handoff_consumer(
            producer_bundle=broken_bundle,
            consumer_stage=7,
        )
        self.assertEqual(validation.decision_state, "BLOCK")

    def test_stage7_to_stage8_minimal_chain(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        handoff = result["stage7"].handoff
        for field_name in self.contracts[7]["required_payload_fields"]:
            self.assertIn(field_name, handoff)

        critical_objects = set(self.integration_rows["H-07-STAGE7-TO-STAGE8"]["criticalObjects"])
        self.assertTrue(critical_objects.issubset(set(result["stage7"].records.keys())))
        self.assertEqual(
            extract_service_record_dependencies("src/stage8_outreach/service.py"),
            sorted(critical_objects),
        )
        self.assertEqual(
            handoff["commercial_urgency_level_optional"],
            result["stage7"].inputs["commercial_urgency_level_optional"],
        )
        self.assertEqual(
            handoff["role_cluster"],
            result["stage7"].record("procurement_decision_actor_profile").get("actor_role_cluster"),
        )

    def test_stage7_persistence_refs_align_with_formal_outputs(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        collection = stage7.record("multi_competitor_collection")

        self.assertEqual(
            stage7.inputs.get("offer_recommendation_id"),
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertEqual(
            stage7.inputs.get("buyer_fit_id"),
            stage7.record("buyer_fit").get("buyer_fit_id"),
        )
        self.assertEqual(
            stage7.inputs.get("legal_action_actor_id"),
            stage7.record("legal_action_actor_profile").get("actor_id"),
        )
        self.assertEqual(
            stage7.inputs.get("procurement_decision_actor_id"),
            stage7.record("procurement_decision_actor_profile").get("actor_id"),
        )
        self.assertEqual(
            stage7.inputs.get("multi_competitor_collection_id_optional"),
            collection.get("multi_competitor_collection_id"),
        )
        self.assertEqual(
            stage7.inputs.get("winning_competitor_candidate_id_optional"),
            stage7.handoff.get("winning_competitor_candidate_id_optional"),
        )
        self.assertEqual(
            stage7.inputs.get("winning_challenger_profile_id_optional"),
            stage7.record("saleable_opportunity").get("challenger_profile_id"),
        )

    def test_stage8_blocks_when_stage7_required_fields_are_missing(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        broken_bundle = StageBundle(
            stage=7,
            records=dict(result["stage7"].records),
            handoff={
                key: value
                for key, value in result["stage7"].handoff.items()
                if key not in {"channel_policy_status", "commercial_urgency_level_optional"}
            },
            trace_rules=list(result["stage7"].trace_rules),
            inputs={
                key: value
                for key, value in result["stage7"].inputs.items()
                if key not in {"channel_policy_status", "commercial_urgency_level_optional"}
            },
        )
        validation = self.store.evaluate_handoff_consumer(
            producer_bundle=broken_bundle,
            consumer_stage=8,
        )
        self.assertEqual(validation.decision_state, "BLOCK")

    def test_stage8_prefers_h07_authoritative_fields_over_shadow_inputs(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        shadow_inputs = dict(stage7.inputs)
        shadow_inputs.update(
            {
                "source_family": "ENTERPRISE_REGISTRY",
                "channel_family": "PERSONAL_PHONE",
                "channel_policy_status": "BLOCK",
                "contact_validity_status": "INVALID",
                "contact_legal_basis": "CUSTOMER_AUTHORIZED_CONTACT",
                "reasonable_expectation_status": "UNREASONABLE",
                "frequency_policy_state": "BLOCK",
                "opt_out_state": "OPTED_OUT",
                "quiet_hours_policy_state": "BLOCK",
                "commercial_urgency_level_optional": "LOW",
                "role_cluster": "LEGAL_ACTION",
            }
        )
        bundle = StageBundle(
            stage=7,
            records=dict(stage7.records),
            handoff=dict(stage7.handoff),
            trace_rules=list(stage7.trace_rules),
            inputs=shadow_inputs,
        )

        stage8 = Stage8Service().run(bundle)
        contact_target = stage8.record("contact_target")
        contact_collection = stage8.inputs["contact_candidate_collection_snapshot"]
        winning_candidate = contact_collection["candidate_list"][0]
        authoritative_fields = (
            "source_family",
            "channel_family",
            "channel_policy_status",
            "contact_validity_status",
            "contact_legal_basis",
            "reasonable_expectation_status",
            "frequency_policy_state",
            "opt_out_state",
            "quiet_hours_policy_state",
            "role_cluster",
        )

        for field_name in authoritative_fields:
            with self.subTest(field_name=field_name):
                self.assertEqual(stage8.inputs.get(field_name), stage7.handoff.get(field_name))
                self.assertEqual(contact_target.get(field_name), stage7.handoff.get(field_name))
                if field_name in {"source_family", "channel_family", "role_cluster"}:
                    observed_value = winning_candidate.get(field_name)
                else:
                    observed_value = winning_candidate.get("contactability_snapshot", {}).get(field_name)
                self.assertEqual(observed_value, stage7.handoff.get(field_name))

        self.assertEqual(
            stage8.inputs.get("commercial_urgency_level_optional"),
            stage7.handoff.get("commercial_urgency_level_optional"),
        )
        self.assertEqual(
            contact_collection.get("multi_competitor_collection_id"),
            stage7.handoff.get("multi_competitor_collection_id_optional"),
        )
        self.assertEqual(
            stage8.inputs.get("winning_competitor_candidate_id_optional"),
            stage7.handoff.get("winning_competitor_candidate_id_optional"),
        )
        self.assertEqual(
            stage8.inputs.get("winning_challenger_profile_id_optional"),
            stage7.handoff.get("winning_challenger_profile_id_optional"),
        )

    def test_stage8_rejects_shadow_winner_refs_outside_h07_formal_carrier(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        shadow_inputs = dict(stage7.inputs)
        shadow_inputs.update(
            {
                "multi_competitor_collection_id_optional": "MCC-DIRECT-OVERRIDE",
                "winning_competitor_candidate_id_optional": "COMP-DIRECT-OVERRIDE",
                "winning_challenger_profile_id_optional": "CHAL-DIRECT-OVERRIDE",
            }
        )
        bundle = StageBundle(
            stage=7,
            records=dict(stage7.records),
            handoff=dict(stage7.handoff),
            trace_rules=list(stage7.trace_rules),
            inputs=shadow_inputs,
        )

        with self.assertRaisesRegex(ValueError, "must-not-recompute conflicts"):
            Stage8Service().run(bundle)

    def test_stage8_to_stage9_payload_and_producer_set_closure(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]

        self.assertTrue(set(self.contracts[8]["producer_objects"]).issubset(set(stage8.records.keys())))
        self.assertIn("contact_candidate_collection_snapshot", stage8.inputs)
        self.assertIn("contact_selection_trace_snapshot", stage8.inputs)
        self._assert_h08_payload_ready(stage8.handoff)
        self._assert_h08_payload_ready(stage8.inputs)

        saleable_opportunity = stage8.record("saleable_opportunity")
        contact_target = stage8.record("contact_target")
        outreach_plan = stage8.record("outreach_plan")
        touch_record = stage8.record("touch_record")
        expected_projection = {
            "opportunity_id": saleable_opportunity.get("opportunity_id"),
            "touch_record_id": touch_record.get("touch_record_id"),
            "response_status": touch_record.get("response_status"),
            "saleability_status": saleable_opportunity.get("saleability_status"),
            "crm_owner_state": saleable_opportunity.get("crm_owner_state"),
        }
        for field_name, expected_value in expected_projection.items():
            self.assertEqual(stage8.handoff.get(field_name), expected_value, field_name)
            self.assertEqual(stage8.inputs.get(field_name), expected_value, field_name)
        self.assertEqual(contact_target.get("opportunity_id"), saleable_opportunity.get("opportunity_id"))
        self.assertEqual(outreach_plan.get("requested_delivery_surface"), "INTERNAL_OPERATIONS")
        self.assertEqual(outreach_plan.get("projection_mode"), "INTERNAL_GOVERNED_PREVIEW")

    def test_stage8_failure_path_persists_writeback_fields(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"response_status": "WRONG_ROLE"})

        result = run_internal_chain(payload)
        stage8 = result["stage8"]
        touch_record = stage8.record("touch_record")

        self.assertEqual(touch_record.get("next_step_optional"), "RESELECT_CONTACT")
        self.assertEqual(touch_record.get("feedback_reason"), "WRONG_ROLE")
        self.assertIsNotNone(touch_record.get("written_back_at_optional"))
        self.assertEqual(
            touch_record.get("writeback_targets"),
            ["contact_target", "saleable_opportunity", "project_fact"],
        )
        self.assertEqual(stage8.handoff.get("touch_record_id"), touch_record.get("touch_record_id"))
        self.assertEqual(stage8.inputs.get("written_back_at_optional"), touch_record.get("written_back_at_optional"))

    def test_stage8_quiet_hours_schedule_path_keeps_candidate_preview(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"quiet_hours_policy_state": "BLOCK"})

        stage8 = run_internal_chain(payload)["stage8"]
        contact_target = stage8.record("contact_target")
        outreach_plan = stage8.record("outreach_plan")
        touch_record = stage8.record("touch_record")

        self.assertEqual(contact_target.get("contact_target_status"), "ELIGIBLE")
        self.assertFalse(contact_target.get("requires_manual_review"))
        self.assertEqual(outreach_plan.get("plan_status"), "SCHEDULED")
        self.assertEqual(touch_record.get("touch_record_state"), "CREATED")
        self.assertEqual(
            outreach_plan.get("governed_metadata", {}).get("candidate_compliance_decision"),
            "ALLOW_PREVIEW",
        )
        self.assertEqual(
            outreach_plan.get("governed_metadata", {}).get("execution_compliance_decision"),
            "SCHEDULED",
        )

    def test_h08_payload_missing_required_field_fails_assertion(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        broken_payload = dict(result["stage8"].handoff)
        broken_payload.pop("crm_owner_state")

        with self.assertRaises(AssertionError):
            self._assert_h08_payload_ready(broken_payload)

    def test_stage9_consumes_h08_records_and_fields(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        stage9 = result["stage9"]

        opportunity = stage8.record("saleable_opportunity")
        touch_record = stage8.record("touch_record")
        order_record = stage9.record("order_record")
        governance_feedback = stage9.record("governance_feedback_event")
        outcome = stage9.record("opportunity_outcome_event")

        self.assertEqual(order_record.get("opportunity_id"), opportunity.get("opportunity_id"))
        self.assertEqual(order_record.get("commercial_status"), "PENDING_APPROVAL")
        self.assertEqual(order_record.get("order_status"), "PENDING_APPROVAL")
        self.assertEqual(order_record.get("touch_record_id"), touch_record.get("touch_record_id"))
        self.assertEqual(order_record.get("plan_status"), stage8.handoff.get("plan_status"))
        self.assertEqual(order_record.get("touch_record_state"), touch_record.get("touch_record_state"))
        self.assertEqual(order_record.get("governed_execution_mode"), "INTERNAL_GOVERNED")
        self.assertFalse(order_record.get("governed_metadata").get("live_execution_enabled"))
        self.assertEqual(governance_feedback.get("trigger_type"), "APPROVAL_MISSING")
        trigger_summary = governance_feedback.get("trigger_summary")
        self.assertIn(opportunity.get("opportunity_id"), trigger_summary)
        self.assertIn(touch_record.get("touch_record_id"), trigger_summary)
        self.assertIn(touch_record.get("response_status"), trigger_summary)
        self.assertIn(opportunity.get("saleability_status"), trigger_summary)
        self.assertIn(opportunity.get("crm_owner_state"), trigger_summary)
        self.assertEqual(governance_feedback.get("feedback_reason"), touch_record.get("feedback_reason"))
        self.assertEqual(
            governance_feedback.get("written_back_at_optional"),
            touch_record.get("written_back_at_optional"),
        )
        self.assertEqual(outcome.get("outcome_family"), "CONTACT_FAILED")
        self.assertEqual(outcome.get("outcome_reason_tags"), ["NO_RESPONSE"])
        self.assertEqual(outcome.get("contact_failure_state"), touch_record.get("response_status"))
        self.assertEqual(outcome.get("feedback_reason"), touch_record.get("feedback_reason"))
        self.assertEqual(outcome.get("trigger_type"), governance_feedback.get("trigger_type"))
        self.assertEqual(
            stage9.record("payment_record").get("written_back_at_optional"),
            touch_record.get("written_back_at_optional"),
        )
        self.assertEqual(
            stage9.record("delivery_record").get("written_back_at_optional"),
            touch_record.get("written_back_at_optional"),
        )
        self.assertEqual(
            stage9.inputs.get("outcome_writeback_targets"),
            ["contact_target", "saleable_opportunity"],
        )
        self.assertEqual(
            stage9.inputs.get("governance_writeback_targets_optional"),
            ["order_record", "payment_record"],
        )
        self.assertEqual(
            stage9.inputs.get("effective_writeback_targets"),
            [
                "contact_target",
                "saleable_opportunity",
                "order_record",
                "payment_record",
            ],
        )
        self.assertEqual(outcome.get("writeback_targets"), ["contact_target", "saleable_opportunity"])

    def test_stage9_response_and_saleability_do_not_create_service_lifecycle_defaults(self) -> None:
        connected_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        connected_payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "CONNECTED",
            }
        )
        connected_result = run_internal_chain(connected_payload)
        self.assertEqual(
            connected_result["stage9"].record("order_record").get("order_status"),
            "DRAFT",
        )
        self.assertEqual(
            connected_result["stage9"].record("delivery_record").get("delivery_status"),
            "NOT_READY",
        )
        self.assertEqual(
            connected_result["stage9"].record("opportunity_outcome_event").get("outcome_family"),
            "WON",
        )
        self.assertEqual(
            connected_result["stage9"].record("governance_feedback_event").get("trigger_type"),
            "OTHER",
        )

        wrong_role_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        wrong_role_payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "WRONG_ROLE",
            }
        )
        wrong_role_result = run_internal_chain(wrong_role_payload)
        self.assertEqual(
            wrong_role_result["stage9"].record("order_record").get("order_status"),
            "ON_HOLD",
        )
        self.assertEqual(
            wrong_role_result["stage9"].record("delivery_record").get("delivery_status"),
            "RELEASE_BLOCKED",
        )
        self.assertEqual(
            wrong_role_result["stage9"].record("opportunity_outcome_event").get("outcome_family"),
            "CONTACT_FAILED",
        )
        self.assertEqual(
            wrong_role_result["stage9"].record("opportunity_outcome_event").get("contact_failure_state"),
            "WRONG_ROLE",
        )
        self.assertEqual(
            wrong_role_result["stage9"].record("governance_feedback_event").get("trigger_type"),
            "APPROVAL_MISSING",
        )

        blocked_result = run_internal_chain(load_fixture("internal_chain_block.json"))
        self.assertEqual(
            blocked_result["stage9"].record("order_record").get("order_status"),
            "ON_HOLD",
        )
        self.assertEqual(
            blocked_result["stage9"].record("delivery_record").get("delivery_status"),
            "RELEASE_BLOCKED",
        )
        self.assertEqual(
            blocked_result["stage9"].record("governance_feedback_event").get("trigger_type"),
            "EVIDENCE_INSUFFICIENT",
        )
        self.assertEqual(blocked_result["stage9"].inputs.get("order_status"), "ON_HOLD")
        self.assertEqual(blocked_result["stage9"].inputs.get("delivery_status"), "RELEASE_BLOCKED")

    def test_stage9_partial_payment_keeps_legacy_targets_clean_and_precise_exception_family(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"payment_status": "PARTIALLY_PAID"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "PARTIAL_PAYMENT",
        )
        self.assertEqual(stage9.record("opportunity_outcome_event").get("outcome_family"), "LOST")
        self.assertEqual(
            stage9.inputs.get("payment_exception_writeback_targets_optional"),
            ["saleable_opportunity", "project_fact"],
        )
        self.assertEqual(
            stage9.inputs.get("effective_writeback_targets"),
            [
                "project_fact",
                "saleable_opportunity",
                "delivery_record",
                "release_gates",
            ],
        )
        self.assertNotIn("buyer_fit", stage9.inputs.get("effective_writeback_targets"))
        self.assertEqual(
            stage9.inputs.get("writeback_target_sources", {}).get("project_fact"),
            ["outcome_taxonomy", "payment_exception"],
        )
        self.assertEqual(
            stage9.inputs.get("payment_exception_match_trace_optional", {}).get("exception_family"),
            "PARTIAL_PAYMENT",
        )
        self.assertEqual(
            stage9.inputs.get("payment_exception_match_trace_optional", {}).get("coarse_outcome_family"),
            "LOST",
        )

    def test_stage9_false_positive_feedback_loop_keeps_advisory_targets_out_of_base_outcome_targets(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "outcome_family": "FALSE_POSITIVE",
                "outcome_reason_tags": ["FACT_CONFLICT"],
                "is_false_positive": True,
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(stage9.inputs.get("outcome_writeback_targets"), ["project_fact"])
        self.assertEqual(
            set(stage9.inputs.get("upstream_feedback_advisory_targets", [])),
            {"buyer_fit", "challenger_candidate_profile"},
        )
        self.assertEqual(
            stage9.inputs.get("writeback_target_sources", {}).get("buyer_fit"),
            ["upstream_feedback_loop"],
        )
        self.assertEqual(
            stage9.inputs.get("writeback_target_sources", {}).get("challenger_candidate_profile"),
            ["upstream_feedback_loop"],
        )

    def test_stage9_opportunity_changed_review_path_keeps_targets_scoped(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"response_status": "OPPORTUNITY_CHANGED"})

        result = run_internal_chain(payload)
        stage8 = result["stage8"]
        stage9 = result["stage9"]
        touch_record = stage8.record("touch_record")
        outcome = stage9.record("opportunity_outcome_event")
        governance = stage9.record("governance_feedback_event")

        self.assertEqual(touch_record.get("feedback_reason"), "OPPORTUNITY_CHANGED")
        self.assertEqual(touch_record.get("next_step_optional"), "REVIEW_STAGE6_7")
        self.assertEqual(touch_record.get("writeback_targets"), ["project_fact", "saleable_opportunity"])
        self.assertEqual(outcome.get("feedback_reason"), touch_record.get("feedback_reason"))
        self.assertEqual(governance.get("feedback_reason"), touch_record.get("feedback_reason"))
        self.assertEqual(stage9.inputs.get("outcome_writeback_targets"), ["project_fact", "saleable_opportunity"])
        self.assertEqual(stage9.inputs.get("governance_writeback_targets_optional"), ["order_record", "payment_record"])
        self.assertEqual(
            stage9.inputs.get("effective_writeback_targets"),
            ["project_fact", "saleable_opportunity", "order_record", "payment_record"],
        )
        self.assertEqual(stage9.inputs.get("upstream_feedback_projected_targets"), [])
        self.assertEqual(stage9.inputs.get("upstream_feedback_advisory_targets"), [])
        self.assertEqual(
            stage9.inputs.get("writeback_target_sources", {}).get("project_fact"),
            ["outcome_taxonomy"],
        )
        self.assertEqual(
            stage9.inputs.get("writeback_target_sources", {}).get("order_record"),
            ["governance_taxonomy"],
        )

    def test_stage9_delivery_exception_trace_exposes_matched_rule_and_family_semantics(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"archival_status": "ARCHIVE_EXCEPTION"})

        stage9 = run_internal_chain(payload)["stage9"]

        self.assertEqual(
            stage9.record("delivery_record").get("delivery_exception_family_optional"),
            "ARCHIVE_FAILURE",
        )
        self.assertEqual(
            stage9.inputs.get("delivery_exception_match_trace_optional", {}).get("exception_family"),
            "ARCHIVE_FAILURE",
        )
        self.assertEqual(
            stage9.inputs.get("delivery_exception_match_trace_optional", {}).get("governance_trigger"),
            "ARCHIVE_FAILURE",
        )

    def test_stage9_missing_upstream_contract_data_fails(self) -> None:
        stage8 = self._build_stage8_bundle()
        service = Stage9Service()

        missing_opportunity_bundle = StageBundle(
            stage=8,
            records={key: value for key, value in stage8.records.items() if key != "saleable_opportunity"},
            handoff=dict(stage8.handoff),
            trace_rules=list(stage8.trace_rules),
            inputs=dict(stage8.inputs),
        )
        with self.assertRaisesRegex(ValueError, "saleable_opportunity"):
            service.run(missing_opportunity_bundle)

        missing_handoff_field_bundle = StageBundle(
            stage=8,
            records=dict(stage8.records),
            handoff={key: value for key, value in stage8.handoff.items() if key != "crm_owner_state"},
            trace_rules=list(stage8.trace_rules),
            inputs=dict(stage8.inputs),
        )
        with self.assertRaisesRegex(ValueError, "complete H-08 payload fields"):
            service.run(missing_handoff_field_bundle)

    def test_stage9_rejects_scattered_input_overrides_for_h08_authority(self) -> None:
        stage8 = self._build_stage8_bundle()
        scattered_inputs = dict(stage8.inputs)
        scattered_inputs.update(
            {
                "response_status": "CONNECTED",
                "saleability_status": "BLOCKED",
                "crm_owner_state": "ASSIGNED",
            }
        )
        conflicting_bundle = StageBundle(
            stage=8,
            records=dict(stage8.records),
            handoff=dict(stage8.handoff),
            trace_rules=list(stage8.trace_rules),
            inputs=scattered_inputs,
        )

        with self.assertRaisesRegex(ValueError, "must-not-recompute conflicts"):
            Stage9Service().run(conflicting_bundle)

    def test_stage9_h08_optional_fields_do_not_fallback_to_scattered_inputs(self) -> None:
        stage8 = self._build_stage8_bundle()
        service = Stage9Service()
        handoff_without_optional = {
            key: value
            for key, value in stage8.handoff.items()
            if key not in Stage9Service.H08_OPTIONAL_FIELDS
        }
        scattered_inputs = dict(stage8.inputs)
        scattered_inputs.update(
            {
                "plan_status": "BLOCKED",
                "touch_record_state": "CANCELLED",
                "written_back_at_optional": "1999-01-01T00:00:00Z",
                "governance_decision_state": "BLOCK",
                "permission_decision_state": "BLOCK",
                "semantic_decision_state": "BLOCK",
            }
        )
        stripped_bundle = StageBundle(
            stage=8,
            records=dict(stage8.records),
            handoff=handoff_without_optional,
            trace_rules=list(stage8.trace_rules),
            inputs=scattered_inputs,
        )

        stage9 = service.run(stripped_bundle)
        order_record = stage9.record("order_record")

        self.assertEqual(order_record.get("plan_status"), "DRAFT")
        self.assertEqual(order_record.get("touch_record_state"), "CREATED")
        self.assertEqual(order_record.get("governance_decision_state"), "ALLOW")
        self.assertIsNone(stage9.inputs.get("written_back_at_optional"))
        self.assertNotEqual(
            stage9.record("payment_record").get("written_back_at_optional"),
            "1999-01-01T00:00:00Z",
        )
        self.assertEqual(stage9.inputs.get("commercial_status"), "PENDING_APPROVAL")
        self.assertEqual(stage9.inputs.get("order_status"), "PENDING_APPROVAL")
        self.assertEqual(stage9.inputs.get("delivery_status"), "NOT_READY")
        self.assertEqual(stage9.inputs.get("trigger_type"), "APPROVAL_MISSING")
        self.assertEqual(stage9.inputs.get("outcome_family"), "CONTACT_FAILED")
        self.assertEqual(stage9.inputs.get("outcome_reason_tags"), ["NO_RESPONSE"])
        self.assertEqual(
            stage9.inputs.get("h08_workflow_fallback_trace", {}).get("trigger_rule_id_optional"),
            "TRIGGER-APPROVAL-MISSING-PLAN",
        )
        self.assertEqual(
            stage9.inputs.get("h08_workflow_fallback_trace", {}).get("lifecycle_rule_id_optional"),
            "STATUS-OWNER-UNASSIGNED",
        )

    def test_stage9_repository_readback_preserves_writeback_carrier_only(self) -> None:
        reset_default_storage()
        stage9 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage9"]

        persist_stage_bundle(stage9)
        hydrated = hydrate_stage_bundle(
            "stage9",
            {"opportunity_id": stage9.record("order_record").get("opportunity_id")},
        )

        self.assertIsNotNone(hydrated)
        self.assertEqual(
            hydrated.inputs.get("resolved_effective_writeback_targets"),
            stage9.inputs.get("resolved_effective_writeback_targets"),
        )
        self.assertEqual(
            hydrated.inputs.get("writeback_target_contracts"),
            stage9.inputs.get("writeback_target_contracts"),
        )
        self.assertEqual(
            hydrated.inputs.get("writeback_target_sources"),
            stage9.inputs.get("writeback_target_sources"),
        )
        self.assertEqual(
            hydrated.record("order_record").get("order_status"),
            stage9.record("order_record").get("order_status"),
        )

    def test_superseded_paths_stage4_to_stage7(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["flags"] = {"report_superseded": True, "rule_superseded": True}
        result = run_internal_chain_to_stage7(payload)

        stage5 = result["stage5"]
        self.assertEqual(stage5.record("rule_hit").get("rule_hit_state"), "SUPERSEDED")
        self.assertIn("review_request", stage5.records)

        stage6 = result["stage6"]
        self.assertEqual(stage6.record("report_record").get("report_status"), "REVOKED")
        self.assertEqual(stage6.record("report_record").get("review_task_status"), "SUPERSEDED")
        self.assertEqual(
            stage6.record("legal_action_recommendation").get("action_family"), "REVIEW_ONLY"
        )


if __name__ == "__main__":
    unittest.main()
