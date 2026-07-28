from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storage.product_value_acceptance import (
    OBSERVED,
    WITHHELD_INVALID_COHORT,
    WITHHELD_MISSING_INPUT,
    build_product_value_acceptance,
    build_product_value_acceptance_from_files,
)


def clean_scoreboard() -> dict:
    return {
        "scoreboard_kind": "stage1_6_sellable_scoreboard_v1",
        "scoreboard_version": 1,
        "scoreboard": {
            "candidate_count": 3,
            "input_mode": "CLEAN_BATCH_OR_DIRECT_STAGE1_6",
            "denominator_kind": "REAL_PUBLIC_CANDIDATES",
            "clean_batch_comparable": True,
            "projection_or_merge_state": "CLEAN_BATCH_OR_DIRECT_STAGE1_6",
            "stage4_matched_task_count": 12,
        },
        "project_rows": [
            {
                "project_id": "PROJ-1",
                "stage4_adapter_result_state_counts": {"MATCHED": 10},
                "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                "stage7_commercial_input_allowed": False,
            },
            {
                "project_id": "PROJ-2",
                "stage4_adapter_result_state_counts": {"MATCHED": 2},
                "limited_sellable_review_candidate_state": "NOT_READY",
                "stage7_commercial_input_allowed": True,
            },
            {
                "project_id": "PROJ-3",
                "stage4_adapter_result_state_counts": {"NOT_FOUND": 4},
                "limited_sellable_review_candidate_state": "NOT_READY",
                "stage7_commercial_input_allowed": False,
            },
        ],
    }


def complete_observations() -> dict:
    return {
        "observation_window": {
            "batch_id": "BATCH-1",
            "started_at": "2026-07-20T08:00:00+08:00",
            "ended_at": "2026-07-20T12:00:00+08:00",
        },
        "discovery": {
            "batch_id": "BATCH-1",
            "observed_at": "2026-07-20T09:00:00+08:00",
            "source_item_count": 5,
            "discovered_candidate_count": 3,
            "source_refs": ["RUN-REAL-1"],
            "discovery_observation_complete": True,
        },
        "evidence_bundle_observation_window_complete": True,
        "evidence_bundles": [
            {
                "schema_version": "1",
                "project_id": "PROJ-1",
                "opportunity_id": "OPP-1",
                "generated_at": "2026-07-20T10:50:00+08:00",
                "sku": {"sku_code": "SKU-B"},
                "issuance_control": {
                    "bundle_state": "INTERNAL_REVIEW_BUNDLE_READY",
                    "manual_signoff_state": "READY_FOR_HUMAN_SIGNOFF",
                },
            },
            {
                "manifest": {
                    "schema_version": "1",
                    "project_id": "PROJ-2",
                    "opportunity_id": "OPP-2",
                    "generated_at": "2026-07-20T10:55:00+08:00",
                    "sku": {"sku_code": "SKU-B"},
                    "issuance_control": {
                        "bundle_state": "INTERNAL_REVIEW_BUNDLE_READY",
                        "manual_signoff_state": "BLOCKED_BEFORE_HUMAN_SIGNOFF",
                    },
                }
            },
        ],
        "human_review_observation_window_complete": True,
        "human_review_logs": [
            {
                "work_log_id": "WORK-1",
                "project_id": "PROJ-1",
                "operator_id": "OPERATOR-A",
                "activity_kind": "HUMAN_REVIEW",
                "started_at": "2026-07-20T10:00:00+08:00",
                "ended_at": "2026-07-20T10:30:00+08:00",
                "source_ref": "ACTION-1",
            },
            {
                "work_log_id": "WORK-2",
                "project_id": "PROJ-2",
                "operator_id": "OPERATOR-A",
                "activity_kind": "HUMAN_REVIEW",
                "started_at": "2026-07-20T10:30:00+08:00",
                "ended_at": "2026-07-20T10:45:00+08:00",
                "source_ref": "ACTION-2",
            },
        ],
        "outcome_observation_window_complete": True,
        "opportunity_outcomes": [
            {
                "outcome_event_id": "OUTCOME-1",
                "project_id": "PROJ-1",
                "opportunity_id": "OPP-1",
                "outcome_family": "WON",
                "outcome_reason_tags": ["DELIVERED_ACK"],
                "written_back_at": "2026-07-20T11:00:00+08:00",
                "governed_execution_mode": "PRIVATE_PILOT_LIVE",
                "value_observation": {
                    "real_customer_confirmed": True,
                    "confirmation_ref": "CUSTOMER-ACK-1",
                },
            },
            {
                "outcome_event_id": "OUTCOME-2",
                "project_id": "PROJ-2",
                "opportunity_id": "OPP-2",
                "outcome_family": "LOST",
                "outcome_reason_tags": ["PRICE_REJECTED"],
                "written_back_at": "2026-07-20T11:05:00+08:00",
                "governed_execution_mode": "PRIVATE_PILOT_LIVE",
                "value_observation": {
                    "real_customer_confirmed": True,
                    "confirmation_ref": "CRM-DECISION-2",
                },
            },
        ],
        "payment_observation_window_complete": True,
        "payment_records": [
            {
                "payment_id": "PAY-1",
                "project_id": "PROJ-1",
                "refund_state": "NOT_REQUESTED",
                "written_back_at": "2026-07-20T11:10:00+08:00",
                "governed_execution_mode": "PRIVATE_PILOT_LIVE",
                "value_observation": {
                    "real_customer_confirmed": True,
                    "confirmation_ref": "PAYMENT-LEDGER-1",
                },
            },
            {
                "payment_id": "PAY-2",
                "project_id": "PROJ-2",
                "refund_state": "COMPLETED",
                "payment_exception_family_optional": "REFUND_COMPLETED",
                "payment_exception_reason_tags_optional": ["DELIVERY_REJECTED"],
                "written_back_at": "2026-07-20T11:20:00+08:00",
                "governed_execution_mode": "PRIVATE_PILOT_LIVE",
                "value_observation": {
                    "real_customer_confirmed": True,
                    "confirmation_ref": "REFUND-LEDGER-2",
                },
            },
        ],
    }


class ProductValueAcceptanceTests(unittest.TestCase):
    def test_discovery_can_be_derived_from_matching_real_run_result(self) -> None:
        run_result = {
            "real_candidate_discovery": {
                "discovery_run_id": "REAL-RUN-1",
                "discovery_state": "COMPLETED",
                "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
                "evaluation_corpus_mode": False,
                "candidate_count": 3,
                "stage1_6_validation_caps": {"candidate_limit_truncated_count": 7},
                "candidate_discovery_diagnostics": {"link_item_count": 10, "accepted_candidate_count": 10},
                "profile_reports": [{"snapshot_id_optional": "SNAPSHOT-1"}],
                "candidates": [
                    {"project_id": f"PROJ-{index}", "discovered_at": "2026-07-20T09:00:00+08:00"}
                    for index in range(1, 4)
                ],
            },
            "stage1_6_validation_ledger": {
                "stage_counts": [{"stage": 1, "input_count": 10, "effective_count": 3}]
            },
        }

        report = build_product_value_acceptance(clean_scoreboard(), run_result_payload=run_result)

        discovery = report["metrics"]["discovery_rate"]
        self.assertEqual(discovery["state"], OBSERVED)
        self.assertEqual(discovery["numerator"], 3)
        self.assertEqual(discovery["denominator"], 10)
        self.assertEqual(discovery["value"], 0.3)
        self.assertEqual(discovery["prelimit_candidate_discovery_rate"], 1.0)
        self.assertEqual(discovery["candidate_limit_truncated_count"], 7)
        self.assertEqual(report["observation_summary"]["observation_window"]["batch_id"], "REAL-RUN-1")

    def test_clean_batch_uses_unique_projects_and_fixed_denominator(self) -> None:
        report = build_product_value_acceptance(
            clean_scoreboard(),
            observations=complete_observations(),
            scoreboard_ref="clean-scoreboard.json",
            created_at="2026-07-20T12:00:00+08:00",
        )

        self.assertEqual(report["report_state"], "FULLY_OBSERVED")
        self.assertEqual(report["acceptance_decision"], "READY_FOR_THRESHOLD_DECISION")
        self.assertEqual(report["metrics"]["discovery_rate"]["value"], 0.6)
        self.assertEqual(report["metrics"]["stage4_ready_rate"]["numerator"], 2)
        self.assertEqual(report["metrics"]["stage4_ready_rate"]["denominator"], 3)
        self.assertEqual(report["metrics"]["stage4_ready_rate"]["value"], 0.6667)
        self.assertEqual(report["metrics"]["reviewable_rate"]["value"], 0.6667)
        self.assertEqual(report["metrics"]["evidence_bundle_rate"]["value"], 0.6667)
        self.assertEqual(report["metrics"]["evidence_bundle_rate"]["human_signoff_ready_rate"], 0.3333)
        self.assertEqual(report["metrics"]["human_review_minutes"]["value"], 45.0)
        self.assertEqual(report["metrics"]["final_adoption"]["value"], 0.3333)
        self.assertEqual(report["metrics"]["final_adoption"]["outcome_reason_counts"]["PRICE_REJECTED"], 1)
        self.assertEqual(report["metrics"]["refund"]["value"], 0.3333)
        self.assertEqual(report["metrics"]["refund"]["refund_reason_counts"]["REFUND_COMPLETED"], 1)
        self.assertFalse(report["safety"]["task_count_used_as_project_denominator"])
        self.assertEqual(len(report["report_sha256"]), 64)

    def test_missing_observations_are_withheld_not_zero(self) -> None:
        report = build_product_value_acceptance(clean_scoreboard(), created_at="2026-07-20T12:00:00+08:00")

        self.assertEqual(report["report_state"], "PARTIALLY_OBSERVED")
        self.assertEqual(report["metrics"]["stage4_ready_rate"]["state"], OBSERVED)
        self.assertEqual(report["metrics"]["stage4_ready_rate"]["value"], 0.6667)
        for name in ("discovery_rate", "evidence_bundle_rate", "human_review_minutes", "final_adoption", "refund"):
            self.assertEqual(report["metrics"][name]["state"], WITHHELD_MISSING_INPUT)
            self.assertIsNone(report["metrics"][name]["value"])

    def test_followup_projection_and_legacy_lineage_are_rejected(self) -> None:
        payload = clean_scoreboard()
        payload["scoreboard"].update(
            {
                "input_mode": "FOLLOWUP_OR_MERGED_PROJECTION",
                "denominator_kind": "FOLLOWUP_PROJECT_ROWS",
                "clean_batch_comparable": False,
                "projection_or_merge_state": "FOLLOWUP_OR_MERGED_PROJECTION",
            }
        )
        report = build_product_value_acceptance(payload, observations=complete_observations())
        self.assertEqual(report["report_state"], "BLOCKED_INVALID_COHORT")
        self.assertEqual(report["metrics"]["stage4_ready_rate"]["state"], WITHHELD_INVALID_COHORT)
        self.assertFalse(report["safety"]["followup_or_projection_accepted"])

        legacy = clean_scoreboard()
        for field in ("input_mode", "denominator_kind", "clean_batch_comparable", "projection_or_merge_state"):
            legacy["scoreboard"].pop(field)
        legacy_report = build_product_value_acceptance(legacy)
        self.assertEqual(legacy_report["cohort"]["gate"]["state"], "BLOCKED")

    def test_real_customer_confirmation_and_work_log_overlap_fail_closed(self) -> None:
        observations = complete_observations()
        observations["opportunity_outcomes"][0]["governed_execution_mode"] = "INTERNAL_GOVERNED_PREVIEW"
        with self.assertRaisesRegex(ValueError, "cannot count as real customer observation"):
            build_product_value_acceptance(clean_scoreboard(), observations=observations)

        observations = complete_observations()
        observations["human_review_logs"][1]["started_at"] = "2026-07-20T10:15:00+08:00"
        with self.assertRaisesRegex(ValueError, "overlapping human review intervals"):
            build_product_value_acceptance(clean_scoreboard(), observations=observations)

    def test_file_entrypoint_writes_replayable_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scoreboard_path = root / "scoreboard.json"
            observations_path = root / "observations.json"
            output_path = root / "report.json"
            scoreboard_path.write_text(json.dumps(clean_scoreboard()), encoding="utf-8")
            observations_path.write_text(json.dumps(complete_observations()), encoding="utf-8")

            report = build_product_value_acceptance_from_files(
                scoreboard_json=scoreboard_path,
                observations_json=observations_path,
                output_json=output_path,
                created_at="2026-07-20T12:00:00+08:00",
            )

            self.assertTrue(output_path.exists())
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["report_sha256"], report["report_sha256"])

    def test_zero_candidate_discovery_is_observed_and_downstream_is_not_applicable(self) -> None:
        payload = clean_scoreboard()
        payload["scoreboard"]["candidate_count"] = 0
        payload["scoreboard"]["denominator_kind"] = "NO_CANDIDATES"
        payload["project_rows"] = []
        observations = {
            "observation_window": {
                "batch_id": "EMPTY-BATCH",
                "started_at": "2026-07-20T08:00:00+08:00",
                "ended_at": "2026-07-20T09:00:00+08:00",
            },
            "discovery": {
                "batch_id": "EMPTY-BATCH",
                "observed_at": "2026-07-20T08:55:00+08:00",
                "source_item_count": 25,
                "discovered_candidate_count": 0,
                "source_refs": ["RUN-EMPTY-1"],
                "discovery_observation_complete": True,
            },
        }

        report = build_product_value_acceptance(payload, observations=observations)

        self.assertEqual(report["report_state"], "NO_CANDIDATES_OBSERVED")
        self.assertEqual(report["metrics"]["discovery_rate"]["state"], OBSERVED)
        self.assertEqual(report["metrics"]["discovery_rate"]["value"], 0.0)
        self.assertEqual(
            report["metrics"]["stage4_ready_rate"]["state"],
            "NOT_APPLICABLE_NO_CANDIDATES",
        )


if __name__ == "__main__":
    unittest.main()
