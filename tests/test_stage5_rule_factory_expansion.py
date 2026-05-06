from __future__ import annotations

import json
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

from helpers import load_fixture
from shared.settings import Settings
from shared.contracts_runtime import StageBundle
from shared.pipeline import run_internal_chain
from stage2_ingestion.real_public_url_fetcher import (
    REAL_PUBLIC_ENTRY_PROFILE_BY_ID,
    RealPublicFetchResponse,
)
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository
from stage5_rules_evidence.service import Stage5Service
from stage5_rules_evidence.rule_runner import evaluate_project_manager_qualification_rules


def load_rule_catalog() -> dict[str, object]:
    return json.loads((ROOT / "contracts/rules/rule_catalog.json").read_text(encoding="utf-8"))


def stage4_bundle_with_inputs(extra_inputs: dict[str, object]) -> StageBundle:
    stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
    return StageBundle(
        stage=4,
        records=dict(stage4.records),
        handoff=dict(stage4.handoff),
        trace_rules=list(stage4.trace_rules),
        inputs={**stage4.inputs, **extra_inputs},
    )


class _FakeRealPublicFetchTransport:
    def __init__(self, responses: dict[str, RealPublicFetchResponse]) -> None:
        self.responses = responses
        self.call_log: list[dict[str, object]] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        self.call_log.append(
            {
                "url": url,
                "timeout_seconds": timeout_seconds,
                "user_agent": user_agent,
            }
        )
        return self.responses[url]


def _real_public_rule_html(*, profile_id: str, target_type: str, identifier: str) -> bytes:
    profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id]
    marker_text = " ".join(profile.visible_entry_markers or profile.lightweight_public_entry_markers)
    filler = "公开规则证据入口" * 80
    html = f"""
    <html>
      <head>
        <title>{profile.expected_title_contains} - {profile.site_name}</title>
        <meta name="description" content="{marker_text}">
      </head>
      <body>
        <h1>{profile.expected_title_contains}</h1>
        <p>{marker_text}</p>
        <p>{filler}</p>
        <table>
          <tr><th>项目名称</th><td>{identifier}</td></tr>
          <tr><th>招标人</th><td>{profile.site_name} 测试主体</td></tr>
          <tr><th>公告日期</th><td>2026-04-28</td></tr>
          <tr><th>{target_type}</th><td>{identifier}</td></tr>
        </table>
        <a href="{profile.sample_detail_url}">公开详情样例</a>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _object_storage_repo(tmp_dir: str) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(Path(tmp_dir) / "stage5-real-public-rule.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(Path(tmp_dir) / "objects"),
    )
    return ObjectStorageRepository(
        session=DatabaseSession(settings=settings),
        settings=settings,
    )


def _real_public_stage4_verification(
    *,
    tmp_dir: str,
    profile_id: str = "GGZY-DEAL-LIST",
    target_type: str = "enterprise_public_record",
    identifier: str = "REAL-PUBLIC-STAGE5-001",
    target_identifier: str | None = None,
) -> dict[str, object]:
    profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id]
    html = _real_public_rule_html(
        profile_id=profile.profile_id,
        target_type=target_type,
        identifier=identifier,
    )
    transport = _FakeRealPublicFetchTransport(
        {
            profile.url: RealPublicFetchResponse(
                url=profile.url,
                status_code=200,
                content=html,
                content_type="text/html; charset=utf-8",
                final_url=profile.url,
                headers={"x-ax9s-fetch-transport": "unit_controlled_transport"},
            )
        }
    )
    repo = _object_storage_repo(tmp_dir)
    stage2_carrier = Stage2Service().fetch_real_public_entry_url(
        profile.url,
        profile_id=profile.profile_id,
        repository=repo,
        transport=transport,
        lineage_refs={
            "source_blueprint_batch_id": "PTL-I100-140",
            "entry_profile_id": profile.profile_id,
        },
    )
    parsed = dict(Stage3Service().parse_raw_snapshot(stage2_carrier["snapshot_id_optional"], repository=repo))
    return dict(
        Stage4Service().verify_public_parsed_carrier(
            parsed,
            target={
                "verification_target_id": f"TARGET-{target_type}-140",
                "verification_target_type": target_type,
                "target_identifier": identifier if target_identifier is None else target_identifier,
            },
            repository=repo,
        )
    )


class Stage5RuleFactoryExpansionTests(unittest.TestCase):
    def test_catalog_registers_stage5_factory_metadata(self) -> None:
        catalog = load_rule_catalog()
        factory = catalog["stage5_rule_factory"]
        bindings = factory["rule_bindings"]
        stage5_rules = [rule for rule in catalog["rules"] if rule.get("stage") == 5]

        self.assertEqual(catalog["version"], "0.1.7")
        self.assertEqual(factory["state"], "INTERNAL_READY")
        self.assertEqual(factory["runtime_entrypoint"], "RuleEvidenceEngine")
        self.assertEqual(factory["runtime_components"], ["RuleRunner", "EvidenceBuilder", "GateEvaluator"])
        self.assertEqual(factory["selection_policy"]["stage"], 5)
        self.assertEqual(factory["selection_policy"]["default_selection_limit"], 3)
        self.assertEqual(len(stage5_rules), 33)
        for rule in stage5_rules:
            self.assertTrue(rule["basis_refs"], rule["rule_code"])
            self.assertIn(
                rule["basis_verification_state"],
                {"VERIFIED", "INTERNAL_ONLY", "BASIS_MISSING", "HEURISTIC_ONLY", "DEPRECATED"},
            )
            self.assertTrue(rule["no_legal_conclusion"], rule["rule_code"])
        credit = next(rule for rule in stage5_rules if rule["rule_code"] == "CREDIT-001")
        attack = next(rule for rule in stage5_rules if rule["rule_code"] == "ATTACK-001")
        self.assertEqual(credit["basis_verification_state"], "BASIS_MISSING")
        self.assertEqual(credit["minimum_external_use_grade"], "E2_REVIEW_READY")
        self.assertFalse(credit["customer_visible_allowed"])
        self.assertEqual(attack["basis_verification_state"], "HEURISTIC_ONLY")
        self.assertFalse(attack["customer_visible_allowed"])
        for rule_code in (
            "PROC-001",
            "PROC-002",
            "DOC-001",
            "PM-001",
            "PM-002",
            "QUAL-PM-001",
            "QUAL-PM-002",
            "QUAL-PM-003",
            "QUAL-PM-004",
        ):
            binding = bindings[rule_code]
            self.assertTrue(binding["enabled"])
            self.assertEqual(binding["version"], "stage5-factory-v1")
            self.assertTrue(binding["dependency_fields"])
            self.assertTrue(binding["dependency_evidence"])
            self.assertTrue(binding["golden_case_refs"])
        self.assertTrue(factory["golden_cases"])

    def test_strict_basis_gate_degrades_missing_basis_rule_to_review(self) -> None:
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["CREDIT-001"],
                "stage5_basis_gate_mode": "STRICT",
            }
        )

        stage5 = Stage5Service().run(stage4)
        trace = stage5.inputs["stage5_rule_execution_trace"][0]

        self.assertEqual(stage5.inputs["stage5_rule_codes"], ["CREDIT-001"])
        self.assertEqual(trace["basis_verification_state"], "BASIS_MISSING")
        self.assertEqual(trace["basis_gate_status"], "REVIEW")
        self.assertTrue(any("basis verification state BASIS_MISSING" in reason for reason in trace["basis_gate_reasons"]))
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)

    def test_internal_only_rule_cannot_support_strict_customer_visible_gate(self) -> None:
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["GOV-001"],
                "stage5_basis_gate_mode": "STRICT",
            }
        )

        stage5 = Stage5Service().run(stage4)
        trace = stage5.inputs["stage5_rule_execution_trace"][0]

        self.assertEqual(trace["rule_code"], "GOV-001")
        self.assertEqual(trace["basis_verification_state"], "INTERNAL_ONLY")
        self.assertFalse(trace["customer_visible_allowed"])
        self.assertTrue(trace["no_legal_conclusion"])
        self.assertEqual(trace["basis_gate_status"], "REVIEW")
        self.assertTrue(any("internal-only basis" in reason for reason in trace["basis_gate_reasons"]))
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")

    def test_heuristic_only_rule_is_review_only_even_when_requested(self) -> None:
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["ATTACK-001"],
                "stage5_supported_upstream_objects": [
                    "public_attack_surface",
                    "bidder_candidate",
                ],
            }
        )

        stage5 = Stage5Service().run(stage4)
        trace = stage5.inputs["stage5_rule_execution_trace"][0]

        self.assertEqual(trace["rule_code"], "ATTACK-001")
        self.assertEqual(trace["basis_verification_state"], "HEURISTIC_ONLY")
        self.assertEqual(trace["basis_gate_status"], "REVIEW")
        self.assertFalse(trace["customer_visible_allowed"])
        self.assertTrue(any("heuristic-only rule is review-only" in reason for reason in trace["basis_gate_reasons"]))
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")

    def test_project_manager_qualification_helper_keeps_b_certificate_as_review_only(self) -> None:
        readback = evaluate_project_manager_qualification_rules(
            {
                "qualification_run_id": "PMQ-JG2026-11125-LIWEN",
                "announced_certificate_no": "贵1442020202102750",
                "safety_b_certificate_no": "水安B20250001645",
                "failure_reasons": [
                    "announced_certificate_no_not_found_in_same_company_personnel_rows",
                    "same_company_person_found_but_not_first_class_constructor",
                    "required_registration_profession_not_publicly_confirmed_in_captured_rows",
                ],
                "public_only": True,
                "customer_visible": False,
                "no_legal_conclusion": True,
            }
        )

        statuses = {entry["rule_code"]: entry["status"] for entry in readback["rule_results"]}
        self.assertEqual(statuses["QUAL-PM-001"], "NOT_CONFIRMED")
        self.assertEqual(statuses["QUAL-PM-002"], "NOT_CONFIRMED")
        self.assertEqual(statuses["QUAL-PM-003"], "NOT_CONFIRMED")
        self.assertEqual(statuses["QUAL-PM-004"], "REVIEW_REQUIRED")
        self.assertEqual(readback["overall_status"], "REVIEW_REQUIRED")
        self.assertTrue(readback["official_check_recommendations"])

    def test_project_manager_qualification_helper_marks_constructor_rules_not_applicable_for_design_registration(self) -> None:
        readback = evaluate_project_manager_qualification_rules(
            {
                "qualification_run_id": "PMQ-DESIGN-REGISTERED-ENGINEER",
                "announced_certificate_no": "AY244400001",
                "required_certificate_type": "注册土木工程师（岩土）",
                "required_registration_profession_publicly_confirmed": False,
                "announced_certificate_same_company_match": False,
                "public_only": True,
                "customer_visible": False,
                "no_legal_conclusion": True,
            }
        )

        statuses = {entry["rule_code"]: entry["status"] for entry in readback["rule_results"]}
        self.assertEqual(statuses["QUAL-PM-001"], "NOT_CONFIRMED")
        self.assertEqual(statuses["QUAL-PM-002"], "NOT_APPLICABLE")
        self.assertEqual(statuses["QUAL-PM-003"], "NOT_CONFIRMED")
        self.assertEqual(statuses["QUAL-PM-004"], "NOT_APPLICABLE")
        self.assertEqual(readback["overall_status"], "NOT_CONFIRMED")

    def test_catalog_aware_selection_execution_trace_and_coverage(self) -> None:
        stage5 = Stage5Service().run(run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"])

        selection_trace = stage5.inputs["stage5_rule_selection_trace"]
        execution_trace = stage5.inputs["stage5_rule_execution_trace"]
        coverage = stage5.inputs["stage5_rule_coverage_summary"]
        readback = stage5.inputs["stage5_rule_readback_summary"]

        self.assertEqual(stage5.inputs["stage5_rule_codes"], ["PROC-001", "PROC-002", "DOC-001"])
        self.assertEqual(
            [entry["rule_code"] for entry in execution_trace],
            ["PROC-001", "PROC-002", "DOC-001"],
        )
        selected = [entry for entry in selection_trace if entry["selected"]]
        self.assertEqual([entry["reason"] for entry in selected], ["selected_catalog_priority"] * 3)
        win_trace = next(entry for entry in selection_trace if entry["rule_code"] == "WIN-001")
        self.assertEqual(win_trace["reason"], "skipped_by_priority_limit")
        for entry in execution_trace:
            self.assertEqual(
                set(
                    [
                        "rule_code",
                        "rule_name",
                        "version",
                        "selected_reason",
                        "upstream_objects",
                        "dependency_fields",
                        "dependency_evidence",
                        "evidence_refs",
                        "confidence",
                        "rule_gate_status",
                        "rule_hit_state",
                        "blocking_reasons",
                    ]
                ).issubset(entry),
                True,
            )
            self.assertEqual(entry["rule_gate_status"], "PASS")
            self.assertEqual(entry["rule_hit_state"], "CONFIRMED")
            self.assertEqual(entry["evidence_refs"], [stage5.record("evidence").get("evidence_id")])
            self.assertGreaterEqual(entry["confidence"], 0.6)
            self.assertTrue(entry["golden_case_refs"])

        self.assertEqual(coverage["selected_count"], 3)
        self.assertGreater(coverage["skipped_count"], 0)
        self.assertGreaterEqual(coverage["disabled_count"], 0)
        self.assertGreater(coverage["unsupported_count"], 0)
        self.assertEqual(coverage["pass_count"], 3)
        self.assertEqual(coverage["review_count"], 0)
        self.assertEqual(coverage["block_count"], 0)
        self.assertEqual(readback["rule_gate_decision_id"], stage5.record("rule_gate_decision").get("gate_id"))
        self.assertEqual(readback["evidence_gate_decision_id"], stage5.record("evidence_gate_decision").get("gate_id"))
        self.assertTrue(readback["golden_case_refs"])

    def test_requested_116a_active_conflict_rule_degrades_to_review_with_evidence_binding(self) -> None:
        active_conflict_readback = {
            "readback_state": "READBACK_READY",
            "replayable": True,
            "fail_closed": False,
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
            "missing_required_fields": [],
            "active_conflict_run_id": "PMAC-RUN-001",
            "overlap_judgement": "OVERLAP_RISK",
            "review_required": True,
            "project_timeline_evidence_refs": [
                {
                    "verification_run_id": "ST4-PERMIT-001",
                    "verification_target_type": "construction_permit",
                    "source_snapshot_id": "SNAP-PERMIT-001",
                },
                {
                    "verification_run_id": "ST4-CONTRACT-001",
                    "verification_target_type": "contract_public_info",
                    "source_snapshot_id": "SNAP-CONTRACT-001",
                },
                {
                    "verification_run_id": "ST4-COMPLETION-001",
                    "verification_target_type": "completion_filing",
                    "source_snapshot_id": "SNAP-COMPLETION-001",
                },
            ],
            "risk_signal_evidence_refs": [
                {
                    "verification_run_id": "ST4-PENALTY-001",
                    "verification_target_type": "administrative_penalty_public_record",
                    "source_snapshot_id": "SNAP-PENALTY-001",
                }
            ],
        }
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["PM-002"],
                "stage5_supported_upstream_objects": [
                    "project_manager",
                    "focus_bidder_verification_profile",
                ],
                "project_manager_active_conflict_readback": active_conflict_readback,
            }
        )

        stage5 = Stage5Service().run(stage4)
        execution_trace = stage5.inputs["stage5_rule_execution_trace"]
        pm_trace = execution_trace[0]

        self.assertEqual(stage5.inputs["stage5_rule_codes"], ["PM-002"])
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "PASS")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertEqual(stage5.record("review_request").get("target_object_type"), "rule_hit")
        self.assertEqual(pm_trace["rule_code"], "PM-002")
        self.assertEqual(pm_trace["selected_reason"], "selected_requested_rule")
        self.assertIn("PMAC-RUN-001", pm_trace["dependency_evidence"])
        self.assertIn("ST4-PERMIT-001", pm_trace["dependency_evidence"])
        self.assertIn("SNAP-CONTRACT-001", pm_trace["dependency_evidence"])
        self.assertIn("ST4-COMPLETION-001", pm_trace["dependency_evidence"])
        self.assertIn("SNAP-PENALTY-001", pm_trace["dependency_evidence"])
        self.assertTrue(any("active conflict requires manual review" in reason for reason in pm_trace["blocking_reasons"]))
        self.assertTrue(pm_trace["review_request_target_selected"])
        self.assertNotIn("project_fact", stage5.records)

    def test_requested_registration_timeline_rule_uses_active_conflict_readback(self) -> None:
        active_conflict_readback = {
            "readback_state": "READBACK_READY",
            "replayable": True,
            "fail_closed": False,
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
            "missing_required_fields": [],
            "active_conflict_run_id": "PMAC-RUN-REG-001",
            "overlap_judgement": "NO_PUBLIC_OVERLAP_EVIDENCE",
            "review_required": True,
            "registration_timeline_verification": {
                "verification_scope": "PROJECT_MANAGER_REGISTRATION_TIMELINE",
                "registration_at": "2026-06-15",
                "certificate_valid_until": "2026-07-01",
                "verification_result": "REVIEW",
                "failure_reasons": [
                    "project_manager_registration_after_current_project_start",
                    "project_manager_certificate_expires_before_current_project_end",
                ],
                "review_required": True,
                "no_legal_conclusion": True,
            },
        }
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["PM-001"],
                "stage5_supported_upstream_objects": [
                    "project_manager",
                    "focus_bidder_verification_profile",
                ],
                "project_manager_active_conflict_readback": active_conflict_readback,
            }
        )

        stage5 = Stage5Service().run(stage4)
        pm_trace = stage5.inputs["stage5_rule_execution_trace"][0]

        self.assertEqual(stage5.inputs["stage5_rule_codes"], ["PM-001"])
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertIn("PMAC-RUN-REG-001", pm_trace["dependency_evidence"])
        self.assertIn("2026-06-15", pm_trace["dependency_evidence"])
        self.assertTrue(
            any(
                "registration timeline project_manager_registration_after_current_project_start"
                in reason
                for reason in pm_trace["blocking_reasons"]
            )
        )
        self.assertTrue(pm_trace["review_request_target_selected"])

    def test_missing_dependency_fails_closed_without_bypassing_gates(self) -> None:
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["PM-002"],
                "stage5_supported_upstream_objects": [
                    "project_manager",
                    "focus_bidder_verification_profile",
                ],
            }
        )

        stage5 = Stage5Service().run(stage4)
        pm_selection = next(
            entry for entry in stage5.inputs["stage5_rule_selection_trace"] if entry["rule_code"] == "PM-002"
        )
        pm_execution = stage5.inputs["stage5_rule_execution_trace"][0]

        self.assertEqual(pm_selection["reason"], "selected_requested_fail_closed")
        self.assertIn(
            "project_manager_active_conflict_readback.active_conflict_run_id",
            pm_selection["missing_dependency_fields"],
        )
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "PASS")
        self.assertIn("review_request", stage5.records)
        self.assertTrue(any("missing dependency fields" in reason for reason in pm_execution["blocking_reasons"]))
        self.assertGreaterEqual(stage5.inputs["stage5_rule_coverage_summary"]["missing_dependency_count"], 1)

    def test_requested_project_manager_qualification_rules_degrade_to_review(self) -> None:
        qualification_readback = {
            "qualification_run_id": "PMQ-JG2026-11125-ZHANGYINGANG",
            "announced_certificate_no": "云1532017201901042",
            "required_registration_category": "一级注册建造师",
            "required_registration_profession_keywords": ["水利水电工程", "水利工程"],
            "announced_certificate_same_company_match": False,
            "first_class_constructor_publicly_confirmed": False,
            "required_registration_profession_publicly_confirmed": False,
            "source_refs": [
                "ST4JZSC-ZHANGYINGANG",
                "GDGDCICPERSON-ZHANGYINGANG",
            ],
            "jzsc": {
                "verification_run_id": "ST4JZSC-ZHANGYINGANG",
                "failure_reasons": [
                    "announced_certificate_no_not_found_in_same_company_personnel_rows",
                    "required_registration_profession_not_publicly_confirmed_in_captured_rows",
                ],
            },
            "guangdong_three_library_person_directory": {
                "source_readback_id": "GDGDCICPERSON-ZHANGYINGANG",
                "failure_reasons": [
                    "gdcic_same_company_person_not_found",
                    "announced_certificate_no_not_found_in_gdcic_person_directory_rows",
                ],
            },
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
        }
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": [
                    "QUAL-PM-001",
                    "QUAL-PM-002",
                    "QUAL-PM-003",
                    "QUAL-PM-004",
                ],
                "stage5_supported_upstream_objects": [
                    "project_manager",
                    "focus_bidder_verification_profile",
                ],
                "project_manager_id_optional": "PM-ZHANGYINGANG",
                "project_manager_qualification_readback": qualification_readback,
            }
        )

        stage5 = Stage5Service().run(stage4)
        execution_trace = stage5.inputs["stage5_rule_execution_trace"]

        self.assertEqual(
            stage5.inputs["stage5_rule_codes"],
            ["QUAL-PM-001", "QUAL-PM-002", "QUAL-PM-003", "QUAL-PM-004"],
        )
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertTrue(
            any(
                "announced_certificate_no_not_found_in_same_company_personnel_rows"
                in reason
                for reason in execution_trace[0]["blocking_reasons"]
            )
        )
        self.assertIn("ST4JZSC-ZHANGYINGANG", execution_trace[0]["dependency_evidence"])
        self.assertIn("GDGDCICPERSON-ZHANGYINGANG", execution_trace[0]["dependency_evidence"])

    def test_version_conflict_fails_closed_to_review(self) -> None:
        stage4 = stage4_bundle_with_inputs(
            {
                "stage5_requested_rule_codes": ["PROC-001"],
                "stage5_rule_version_pins": {"PROC-001": "stage5-factory-v0"},
            }
        )

        stage5 = Stage5Service().run(stage4)
        proc_trace = stage5.inputs["stage5_rule_execution_trace"][0]
        coverage = stage5.inputs["stage5_rule_coverage_summary"]

        self.assertEqual(proc_trace["rule_code"], "PROC-001")
        self.assertEqual(proc_trace["selected_reason"], "selected_requested_fail_closed")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertTrue(any("version conflict expected" in reason for reason in proc_trace["blocking_reasons"]))
        self.assertGreaterEqual(coverage["version_conflict_count"], 1)

    def test_real_public_stage4_verification_readback_enters_stage5_rule_evidence_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            verification = _real_public_stage4_verification(tmp_dir=tmp_dir)
            base_stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]

            stage5 = Stage5Service().run_public_verification_readback(
                base_stage4,
                verification,
                requested_rule_codes=["DOC-001"],
            )

        self.assertEqual(verification["verification_result"], "MATCHED")
        self.assertEqual(stage5.inputs["stage5_rule_codes"], ["DOC-001"])
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "PASS")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "PASS")
        self.assertNotIn("review_request", stage5.records)
        self.assertNotIn("project_fact", stage5.records)
        self.assertNotIn("stage6_project_fact", stage5.records)
        self.assertNotIn("customer_material", stage5.inputs)

        rule_hit = stage5.record("rule_hit")
        source_refs = set(rule_hit.get("source_object_refs"))
        self.assertIn(verification["verification_run_id"], source_refs)
        self.assertIn(verification["source_snapshot_id"], source_refs)
        self.assertIn(verification["input_parse_run_id"], source_refs)
        self.assertFalse(stage5.inputs["stage4_public_verification_carrier"]["customer_visible"])

        readback = stage5.inputs["stage5_rule_readback_summary"]
        self.assertIn(verification["verification_run_id"], readback["stage4_public_verification_refs"])
        self.assertIn(verification["source_snapshot_id"], readback["stage4_public_verification_refs"])
        self.assertEqual(
            stage5.inputs["stage4_public_verification_readback_summary"]["readback_state"],
            "READBACK_READY",
        )
        self.assertTrue(stage5.inputs["stage4_public_verification_readback_summary"]["replayable"])

    def test_real_public_stage4_review_result_fails_closed_to_stage5_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            verification = _real_public_stage4_verification(
                tmp_dir=tmp_dir,
                profile_id="BEIJING-PLATFORM-HOME",
                target_type="contract_public_info",
                identifier="CONTRACT-PUBLIC-STAGE5-140",
                target_identifier="",
            )
            base_stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]

            stage5 = Stage5Service().run_public_verification_readback(
                base_stage4,
                verification,
                requested_rule_codes=["DOC-001"],
            )

        self.assertEqual(verification["verification_result"], "REVIEW_REQUIRED")
        self.assertTrue(verification["review_required"])
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "REVIEW")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertEqual(stage5.inputs["verification_state"], "REVIEW")
        self.assertTrue(
            any(
                "verification review" in reason
                for reason in stage5.inputs["stage5_rule_execution_trace"][0]["blocking_reasons"]
            )
        )
        self.assertIn(
            verification["verification_run_id"],
            stage5.inputs["stage5_rule_readback_summary"]["stage4_public_verification_refs"],
        )
        self.assertNotIn("project_fact", stage5.records)
        self.assertNotIn("stage6_project_fact", stage5.records)
        self.assertNotIn("customer_material", stage5.inputs)


if __name__ == "__main__":
    unittest.main()
