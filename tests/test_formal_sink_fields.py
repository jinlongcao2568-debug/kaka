from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from helpers import load_fixture, load_repo_json
from shared.pipeline import run_internal_chain


FORMAL_SINK_FIELDS = {
    "value": {
        "project_fact": ["project_value_score_optional"],
        "saleable_opportunity": ["opportunity_value_score_optional"],
    },
    "price": {
        "bidder_candidate": [
            "normalized_price_amount_optional",
            "price_conflict_gate_status_optional",
        ],
    },
    "confidence": {
        "challenger_candidate_profile": ["confidence_score_optional"],
    },
    "clock": {
        "clock_chain_profile": [
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ],
    },
}


class TestFormalSinkFields(unittest.TestCase):
    def setUp(self) -> None:
        self.schema_catalog = load_repo_json("contracts/schemas/schema_catalog.json")
        self.h06 = load_repo_json("handoff/stage6_to_stage7/contract.json")
        self.h07 = load_repo_json("handoff/stage7_to_stage8/contract.json")

    def _catalog_entry(self, object_name: str) -> dict[str, object]:
        for entry in self.schema_catalog["schemas"]:
            if entry["object"] == object_name:
                return entry
        self.fail(f"schema_catalog missing {object_name}")

    def test_formal_sink_fields_exist_in_schema_and_catalog(self) -> None:
        for object_name, fields in {
            object_name: fields
            for field_group in FORMAL_SINK_FIELDS.values()
            for object_name, fields in field_group.items()
        }.items():
            schema = load_repo_json(f"contracts/schemas/{object_name}.schema.json")
            catalog_entry = self._catalog_entry(object_name)
            optional_fields = set(catalog_entry.get("optional", []))
            required_fields = set(catalog_entry.get("required", []))
            schema_fields = set(schema["properties"])

            for field_name in fields:
                self.assertIn(field_name, schema_fields, f"{object_name}.{field_name}")
                self.assertIn(field_name, optional_fields | required_fields, f"{object_name}.{field_name}")

    def test_h06_and_h07_carry_formal_sink_optional_payload(self) -> None:
        h06_fields = set(self.h06["optional_payload_fields"])
        h07_fields = set(self.h07["optional_payload_fields"])

        for field_name in (
            "project_value_score_optional",
            "normalized_price_amount_optional",
            "price_conflict_gate_status_optional",
            "confidence_score_optional",
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, h06_fields)

        for field_name in (
            "project_value_score_optional",
            "opportunity_value_score_optional",
            "normalized_price_amount_optional",
            "price_conflict_gate_status_optional",
            "confidence_score_optional",
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, h07_fields)

    def test_stage7_projects_value_price_confidence_and_clock_sinks(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "normalized_price_amount_optional": 8_000_000,
                "price_conflict_gate_status_optional": "PASS",
                "current_action_start_at_optional": "2026-04-17T00:00:00Z",
                "current_action_deadline_at_optional": "2026-04-20T00:00:00Z",
            }
        )

        result = run_internal_chain(payload)
        stage7 = result["stage7"]
        opportunity = stage7.record("saleable_opportunity")
        offer = stage7.record("offer_recommendation")
        trace = stage7.inputs["stage7_resolution_trace"]["formal_sink_projection"]
        opportunity_policy_trace = stage7.inputs["stage7_resolution_trace"]["opportunity_policy"]
        price_trace = stage7.inputs["stage7_resolution_trace"]["price_resolution"]

        self.assertIsInstance(opportunity.get("opportunity_value_score_optional"), int)
        self.assertEqual(opportunity.get("opportunity_value_score_optional"), trace["opportunity_value_score_optional"])
        self.assertNotEqual(opportunity.get("expected_close_days_band"), "UNKNOWN")
        self.assertNotEqual(opportunity.get("expected_delivery_cost_band"), "UNKNOWN")
        self.assertEqual(opportunity.get("expected_close_days_band"), opportunity_policy_trace["expected_close_days_band"])
        self.assertEqual(opportunity.get("expected_delivery_cost_band"), opportunity_policy_trace["expected_delivery_cost_band"])
        self.assertEqual(offer.get("why_recommended"), opportunity_policy_trace["why_recommended"])
        self.assertIsInstance(trace["project_value_score_optional"], int)
        self.assertEqual(trace["normalized_price_amount_optional"], 8_000_000)
        self.assertEqual(trace["price_conflict_gate_status_optional"], "PASS")
        self.assertEqual(price_trace["policy_id"], "price_candidate_merge_v2")
        self.assertEqual(price_trace["selected_source_type"], "H06_FORMAL_SINK")
        self.assertEqual(price_trace["normalized_currency"], "CNY")
        self.assertEqual(price_trace["normalized_tax_basis"], "EX_TAX")
        self.assertEqual(price_trace["normalized_unit_basis"], "TOTAL_AMOUNT")
        self.assertEqual(price_trace["selected_scope_key"], "GLOBAL")
        self.assertEqual(price_trace["selected_candidate_trace"]["freshness_score"], 100)
        self.assertIsInstance(trace["confidence_score_optional"], int)
        self.assertEqual(trace["current_action_start_at_optional"], "2026-04-17T00:00:00Z")
        self.assertEqual(trace["current_action_deadline_at_optional"], "2026-04-20T00:00:00Z")

        for field_name, expected_value in trace.items():
            self.assertEqual(stage7.handoff[field_name], expected_value, field_name)
            self.assertEqual(stage7.inputs[field_name], expected_value, field_name)

    def test_stage8_consumes_h07_formal_sink_trace_without_new_collection(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "normalized_price_amount_optional": 8_000_000,
                "current_action_start_at_optional": "2026-04-17T00:00:00Z",
                "current_action_deadline_at_optional": "2026-04-20T00:00:00Z",
            }
        )

        result = run_internal_chain(payload)
        stage7_trace = result["stage7"].inputs["stage7_resolution_trace"]["formal_sink_projection"]
        stage8_trace = result["stage8"].inputs["stage8_resolution_trace"]["formal_sink_consumption"]

        self.assertEqual(stage8_trace, stage7_trace)
        self.assertNotIn("challenger_candidate_collection", result["stage7"].records)
        self.assertNotIn("challenger_candidate_collection", result["stage8"].records)


if __name__ == "__main__":
    unittest.main()
