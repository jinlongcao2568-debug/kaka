from __future__ import annotations

import json
import hashlib
import sys
import unittest
import copy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.contract_loader import load_contract
from shared.model_quality_evaluation import (
    MODEL_QUALITY_GOLDEN_REF,
    build_model_cost_observation,
    build_real_provider_quality_request_documents,
    compare_model_quality_reports,
    evaluate_real_provider_results,
    run_offline_model_quality_goldens,
)


def _real_result(case: dict, defaults: dict, latency_ms: float = 1000.0) -> dict:
    case_id = str(case["case_id"])
    request_document = {
        "task_kind": case["task_kind"],
        "input_data_classification": defaults["input_data_classification"],
        "sanitized_input": case["sanitized_input"],
        "source_refs": case["source_refs"],
    }
    request_sha256 = hashlib.sha256(
        json.dumps(
            request_document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "case_id": case_id,
        "result": {
            "execution_state": "COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED",
            "provider_id": "openai_responses",
            "model": "approved-shadow-model-v1",
            "provider_response_id": f"resp-{case_id}",
            "governance": {"shadow_audit_ref": "MODEL-SHADOW-AUDIT-001"},
            "trace": {
                "request_sha256": request_sha256,
                "source_refs": list(case["source_refs"]),
                "prompt_template_id": defaults["prompt_template_id"],
                "prompt_template_version": defaults["prompt_template_version"],
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "latency_ms": latency_ms,
                "attempts_executed": 1,
                "external_network_call_executed": True,
                "execution_evidence_kind": "EXTERNAL_PROVIDER_SHADOW",
                "raw_prompt_persisted": False,
                "raw_provider_response_persisted": False,
            },
        },
        "human_review": {
            "accepted": True,
            "hallucination_found": False,
            "boundary_leak_found": False,
            "prohibited_conclusion_found": False,
            "reviewer_ref": "REVIEW-AUDIT-001",
        },
    }


def _pricing() -> dict:
    return {
        "snapshot_id": "PRICE-APPROVED-001",
        "provider_id": "openai_responses",
        "model": "approved-shadow-model-v1",
        "currency": "USD",
        "input_per_million_tokens": "2.0",
        "output_per_million_tokens": "8.0",
        "effective_at": "2026-07-20T00:00:00Z",
        "approval_ref": "PRICING-AUDIT-001",
    }


class ModelQualityEvaluationTests(unittest.TestCase):
    def test_real_quality_request_documents_are_complete_and_hash_bound(self) -> None:
        documents = build_real_provider_quality_request_documents()

        self.assertEqual(len(documents), 12)
        self.assertEqual(len({item["case_id"] for item in documents}), 12)
        self.assertEqual(
            {item["request"]["task_kind"] for item in documents},
            {"CANDIDATE_EXTRACTION", "EVIDENCE_SUMMARY", "REVIEW_EXPLANATION", "DRAFT_COPY"},
        )
        for item in documents:
            self.assertEqual(len(item["request_sha256"]), 64)
            self.assertTrue(item["request"]["source_refs"])
            self.assertTrue(item["manual_checks"])

    def test_offline_goldens_cover_success_fallback_and_security_fail_closed(self) -> None:
        report = run_offline_model_quality_goldens()

        self.assertEqual(report["summary"]["case_count"], 10)
        self.assertEqual(report["summary"]["passed_count"], 10)
        self.assertEqual(report["summary"]["offline_gate_status"], "PASSED")
        self.assertEqual(report["summary"]["fallback_case_count"], 8)
        self.assertEqual(report["summary"]["fail_closed_case_count"], 1)
        self.assertEqual(report["summary"]["external_provider_call_count"], 0)
        self.assertEqual(
            report["release_decision"]["real_provider_shadow_gate"],
            "BLOCKED_EXTERNAL_NO_REAL_PROVIDER_RESULTS",
        )
        encoded = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("test-placeholder-must-not-send", encoded)
        self.assertNotIn("HALLUCINATED-SOURCE", encoded)
        self.assertFalse(report["release_decision"]["customer_visible_enabled"])
        self.assertFalse(report["release_decision"]["formal_fact_write_enabled"])

    def test_cost_is_withheld_without_usage_or_verified_pricing(self) -> None:
        golden = load_contract(MODEL_QUALITY_GOLDEN_REF)
        external_result = _real_result(
            golden["real_quality_cases"][0], golden["real_quality_case_defaults"]
        )["result"]
        no_price = build_model_cost_observation(external_result)
        self.assertEqual(no_price["state"], "WITHHELD_NO_VERIFIED_PRICING_SNAPSHOT")
        self.assertIsNone(no_price["amount"])

        calculated = build_model_cost_observation(external_result, _pricing())
        self.assertEqual(calculated["state"], "CALCULATED_FROM_VERIFIED_PRICING_SNAPSHOT")
        self.assertEqual(calculated["amount"], "0.000600")
        self.assertEqual(calculated["currency"], "USD")

        replay = dict(external_result)
        replay["trace"] = {**external_result["trace"], "external_network_call_executed": False}
        replay_cost = build_model_cost_observation(replay, _pricing())
        self.assertEqual(replay_cost["state"], "NOT_APPLICABLE_OFFLINE_OR_NON_EXTERNAL_REPLAY")
        self.assertIsNone(replay_cost["amount"])

    def test_real_provider_gate_requires_all_goldens_human_review_trace_and_cost(self) -> None:
        golden = load_contract(MODEL_QUALITY_GOLDEN_REF)
        cases = [
            _real_result(item, golden["real_quality_case_defaults"])
            for item in golden["real_quality_cases"]
        ]

        report = evaluate_real_provider_results(cases, pricing_snapshot=_pricing())

        self.assertEqual(report["metrics"]["case_count"], 12)
        self.assertEqual(report["metrics"]["manual_acceptance_rate"], 1.0)
        self.assertEqual(report["metrics"]["trace_completeness_rate"], 1.0)
        self.assertEqual(report["metrics"]["hallucination_rate"], 0.0)
        self.assertEqual(report["metrics"]["verified_cost_case_count"], 12)
        self.assertEqual(report["metrics"]["total_verified_cost_amount"], "0.007200")
        self.assertEqual(report["metrics"]["verified_cost_currency"], "USD")
        self.assertTrue(all(report["threshold_checks"].values()))
        self.assertEqual(
            report["release_decision"]["internal_shadow_quality_gate"], "PASSED"
        )
        self.assertTrue(report["release_decision"]["controlled_opening_still_required"])
        self.assertFalse(report["release_decision"]["customer_visible_enabled"])

        one_fallback = copy.deepcopy(cases)
        one_fallback[0]["result"]["execution_state"] = (
            "FALLBACK_DETERMINISTIC_REVIEW_REQUIRED"
        )
        one_fallback[0]["result"]["provider_response_id"] = ""
        one_fallback[0]["result"]["failure"] = {"category": "PROVIDER_TIMEOUT"}
        one_fallback[0]["result"]["trace"].update(
            {"input_tokens": None, "output_tokens": None, "total_tokens": None}
        )
        one_fallback[0]["human_review"]["accepted"] = False
        fallback_report = evaluate_real_provider_results(
            one_fallback, pricing_snapshot=_pricing()
        )
        self.assertEqual(fallback_report["metrics"]["provider_failure_rate"], 0.083333)
        self.assertEqual(fallback_report["metrics"]["verified_cost_case_count"], 11)
        self.assertTrue(all(fallback_report["threshold_checks"].values()))
        self.assertEqual(
            fallback_report["release_decision"]["internal_shadow_quality_gate"],
            "PASSED",
        )

        without_price = evaluate_real_provider_results(cases)
        self.assertFalse(without_price["threshold_checks"]["verified_cost_coverage"])
        self.assertEqual(
            without_price["release_decision"]["internal_shadow_quality_gate"], "BLOCKED"
        )

        tampered = copy.deepcopy(cases)
        tampered[0]["result"]["trace"]["request_sha256"] = "0" * 64
        tampered_report = evaluate_real_provider_results(
            tampered, pricing_snapshot=_pricing()
        )
        self.assertLess(tampered_report["metrics"]["trace_completeness_rate"], 1.0)
        self.assertFalse(
            tampered_report["threshold_checks"]["trace_completeness_rate"]
        )
        self.assertEqual(
            tampered_report["release_decision"]["internal_shadow_quality_gate"],
            "BLOCKED",
        )

    def test_version_regression_blocks_quality_or_latency_drop(self) -> None:
        baseline = {
            "golden_version": "1.0.0",
            "metrics": {
                "manual_acceptance_rate": 1.0,
                "trace_completeness_rate": 1.0,
                "hallucination_rate": 0.0,
                "boundary_leak_rate": 0.0,
                "p95_latency_ms": 1000.0,
            },
        }
        current = {
            "golden_version": "1.0.0",
            "metrics": {
                "manual_acceptance_rate": 0.9,
                "trace_completeness_rate": 1.0,
                "hallucination_rate": 0.1,
                "boundary_leak_rate": 0.0,
                "p95_latency_ms": 1400.0,
            },
        }

        result = compare_model_quality_reports(current, baseline)

        self.assertTrue(result["blocks_change"])
        self.assertEqual(result["state"], "BLOCKED_REGRESSION")
        self.assertIn("manual_acceptance_regressed", result["reasons"])
        self.assertIn("hallucination_rate_regressed", result["reasons"])
        self.assertIn("p95_latency_regressed", result["reasons"])


if __name__ == "__main__":
    unittest.main()
