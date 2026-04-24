import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "control" / "product_doc_runtime_coverage_ledger.yaml"

REQUIRED_CLASSIFICATIONS = {
    "INTERNAL_IMPLEMENTED",
    "TEST_COVERED",
    "RESERVED_NOT_LIVE",
    "BLOCKED_BY_GOVERNANCE",
    "MISSING_RUNTIME",
    "MISSING_TEST",
}

REQUIRED_FIELDS = {
    "capability_id",
    "doc_refs",
    "runtime_refs",
    "test_refs",
    "classification",
    "evidence_summary",
    "recommended_followup_packet",
}

REQUIRED_SCOPE_GROUPS = {
    "Stage1-5 source/rule/evidence",
    "Stage6 review/workbench",
    "Stage7 saleability/price/competitor",
    "Stage8 contact/compliance/outreach preview",
    "Stage9 order/payment/delivery/refund/writeback",
    "storage/bootstrap/transport",
    "external/live redlines",
}


def _load_ledger():
    with LEDGER_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _path_from_ref(reference):
    return reference.split("::", 1)[0].split("#", 1)[0]


class ProductDocRuntimeCoverageLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = _load_ledger()
        cls.capabilities = cls.ledger["capabilities"]

    def test_ledger_has_required_top_level_contract(self):
        self.assertEqual(
            self.ledger["ledger_id"],
            "PTL-I100-107C_PRODUCT_DOC_RUNTIME_COVERAGE_LEDGER",
        )
        self.assertEqual(
            set(self.ledger["classification_vocabulary"]),
            REQUIRED_CLASSIFICATIONS,
        )
        self.assertGreaterEqual(len(self.capabilities), 20)

    def test_every_capability_has_required_machine_readable_fields(self):
        seen_ids = set()
        for capability in self.capabilities:
            self.assertTrue(REQUIRED_FIELDS.issubset(capability), capability)
            capability_id = capability["capability_id"]
            self.assertNotIn(capability_id, seen_ids)
            seen_ids.add(capability_id)

            for list_field in ("doc_refs", "runtime_refs", "test_refs", "classification"):
                self.assertIsInstance(capability[list_field], list)
                self.assertTrue(capability[list_field], capability_id)

            self.assertTrue(capability["evidence_summary"].strip(), capability_id)
            self.assertTrue(
                capability["recommended_followup_packet"].strip(),
                capability_id,
            )
            self.assertTrue(
                set(capability["classification"]).issubset(REQUIRED_CLASSIFICATIONS),
                capability_id,
            )

    def test_classification_counts_match_capability_rows(self):
        computed = {classification: 0 for classification in REQUIRED_CLASSIFICATIONS}
        for capability in self.capabilities:
            for classification in capability["classification"]:
                computed[classification] += 1

        self.assertEqual(self.ledger["classification_counts"], computed)
        for classification in REQUIRED_CLASSIFICATIONS:
            self.assertGreater(computed[classification], 0, classification)

    def test_required_scope_groups_are_covered(self):
        covered = {capability["scope_group"] for capability in self.capabilities}
        self.assertTrue(REQUIRED_SCOPE_GROUPS.issubset(covered))

    def test_external_or_live_capabilities_are_not_marked_internal_implemented(self):
        for capability in self.capabilities:
            if capability.get("external_or_live_capability"):
                self.assertNotIn(
                    "INTERNAL_IMPLEMENTED",
                    capability["classification"],
                    capability["capability_id"],
                )

    def test_missing_runtime_or_test_rows_have_followup_packets(self):
        missing_classifications = {"MISSING_RUNTIME", "MISSING_TEST"}
        for capability in self.capabilities:
            if missing_classifications.intersection(capability["classification"]):
                followup = capability["recommended_followup_packet"]
                self.assertTrue(followup.startswith("PTL-I100-"), capability["capability_id"])
                self.assertNotIn("TODO", followup.upper(), capability["capability_id"])
                self.assertNotEqual(
                    followup,
                    "PTL-I100-107C_NO_FOLLOWUP_LEDGER_BASELINE",
                    capability["capability_id"],
                )

    def test_internal_implemented_capabilities_are_test_covered(self):
        for capability in self.capabilities:
            if "INTERNAL_IMPLEMENTED" in capability["classification"]:
                self.assertIn(
                    "TEST_COVERED",
                    capability["classification"],
                    capability["capability_id"],
                )

    def test_stage6_private_supplement_impact_runtime_readback_is_closed(self):
        capability = next(
            item
            for item in self.capabilities
            if item["capability_id"] == "STAGE6_PRIVATE_SUPPLEMENT_IMPACT"
        )

        self.assertIn("INTERNAL_IMPLEMENTED", capability["classification"])
        self.assertIn("TEST_COVERED", capability["classification"])
        self.assertIn("RESERVED_NOT_LIVE", capability["classification"])
        self.assertNotIn("MISSING_RUNTIME", capability["classification"])
        self.assertIn(
            "src/storage/repository_bundle_io.py",
            capability["runtime_refs"],
        )
        self.assertIn(
            "tests/test_internal_repository_boundary.py::test_stage6_private_supplement_carrier_persists_and_hydrates",
            capability["test_refs"],
        )
        self.assertIn("runtime/readback", capability["evidence_summary"])

    def test_stage1_6_full_api_transport_orchestration_runtime_is_closed(self):
        capability = next(
            item
            for item in self.capabilities
            if item["capability_id"] == "STAGE1_6_FULL_API_TRANSPORT_AND_ORCHESTRATION"
        )

        self.assertIn("INTERNAL_IMPLEMENTED", capability["classification"])
        self.assertIn("TEST_COVERED", capability["classification"])
        self.assertIn("RESERVED_NOT_LIVE", capability["classification"])
        self.assertNotIn("MISSING_RUNTIME", capability["classification"])
        self.assertIn("src/api/deps.py", capability["runtime_refs"])
        self.assertIn("src/api/routes/stage6.py", capability["runtime_refs"])
        self.assertIn(
            "tests/test_api_transport_bootstrap.py::test_stage1_to_stage6_internal_orchestration_runs_repository_backed_readback",
            capability["test_refs"],
        )
        self.assertIn(
            "tests/test_api_transport_bootstrap.py::test_stage1_to_stage6_internal_orchestration_rejects_live_payloads",
            capability["test_refs"],
        )
        self.assertIn("sanitized/offline", capability["evidence_summary"])
        self.assertIn("controlled-unavailable", capability["evidence_summary"])

    def test_referenced_files_exist_for_audit_evidence(self):
        for capability in self.capabilities:
            for field_name in ("doc_refs", "runtime_refs", "test_refs"):
                for reference in capability[field_name]:
                    path_text = _path_from_ref(reference)
                    path = REPO_ROOT / path_text
                    self.assertTrue(
                        path.exists(),
                        f"{capability['capability_id']} references missing {field_name}: {reference}",
                    )


if __name__ == "__main__":
    unittest.main()
