from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.jzsc_personnel import (
    AMBIGUOUS_PUBLIC_MATCH,
    REGISTERED_UNIT_CONFLICT,
    SOURCE_SNAPSHOT_MISSING,
    build_jzsc_company_first_capture_plan,
    build_jzsc_company_personnel_resolution_carrier,
    build_jzsc_personnel_list_carrier,
    build_jzsc_personnel_project_conflict_records,
    parse_jzsc_personnel_project_rows,
    parse_jzsc_personnel_rows,
)
from stage4_verification.service import Stage4Service
from shared.settings import Settings
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


RENDERED_PERSONNEL_ROWS = [
    "1 郭敏锋 350600**********39 注册监理工程师 35014418",
    "2 郭敏锋 350600**********39 二级注册建造师 闽2352012201356897",
    "5 陈庆丽 372929**********69 一级注册建造师 鲁1372017201820810",
    "6 仓强芝 320923**********30 注册电气工程师（供配电） 3202873-DG009",
]

RENDERED_COMPANY_PERSONNEL_ROWS = [
    {
        "row_text": "1 陈庆丽 372929**********69 一级注册建造师 鲁1372017201820810",
        "detail_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
        "person_public_id": "person-chen-qingli",
        "registered_unit_name": "Alpha Construction Co",
        "registration_at": "2025-01-01",
        "certificate_valid_until": "2027-12-31",
    }
]

RENDERED_PERSONNEL_PROJECT_ROWS = [
    {
        "row_no": 1,
        "project_id": "PRJ-JZSC-CONFLICT-001",
        "project_name": "Earlier public bridge project",
        "registered_unit_name": "Alpha Construction Co",
        "project_manager_name": "陈庆丽",
        "registration_no": "鲁1372017201820810",
        "contract_start_at": "2026-03-01",
        "contract_end_at": "2026-08-31",
        "completion_acceptance_status": "NO_PUBLIC_COMPLETION_ACCEPTANCE_PROOF",
        "detail_url": "https://jzsc.mohurd.gov.cn/data/project/detail?id=conflict-001",
    }
]


def _registered_unit_carrier() -> dict[str, object]:
    return {
        "verification_run_id": "ST4PV-JZSC-UNIT",
        "verification_target_type": "enterprise_public_record",
        "verification_role": "registered_unit_verification",
        "source_snapshot_id": "SNAP-JZSC-UNIT",
        "source_url": "https://jzsc.mohurd.gov.cn/data/company",
        "public_visibility_state": "PUBLIC_VISIBLE",
        "verification_provider": "stage4-public-verification-readback",
        "verification_result": "MATCHED",
        "evidence_grade": "PUBLIC_RENDERED_TABLE_FIELD_MATCH",
        "confidence": 0.92,
        "review_required": False,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "source_refs": [
            {
                "source_url": "https://jzsc.mohurd.gov.cn/data/company",
                "source_snapshot_id": "SNAP-JZSC-UNIT",
                "public_visibility_state": "PUBLIC_VISIBLE",
            }
        ],
        "snapshot_refs": [{"snapshot_id": "SNAP-JZSC-UNIT", "replayable": True}],
    }


def _object_storage_repo(tmp_dir: str) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(Path(tmp_dir) / "jzsc-browser-executor.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(Path(tmp_dir) / "objects"),
    )
    return ObjectStorageRepository(
        session=DatabaseSession(settings=settings),
        settings=settings,
    )


def _parsed_jzsc_current_context() -> dict[str, object]:
    return {
        "parse_run_id": "PARSE-JZSC-BROWSER-EXECUTOR",
        "snapshot_id": "SNAP-JZSC-BROWSER-CURRENT",
        "source_url": "https://example.invalid/current-notice.html",
        "lineage_status": "NORMALIZED",
        "conflict_state": "CONSISTENT",
        "current_project_time_window": {
            "start_at": "2026-05-01",
            "end_at": "2026-10-01",
        },
        "parsed_fields": [
            {
                "field_name": "current_project_id",
                "field_value_optional": "PRJ-JZSC-CURRENT",
                "source_file_ref": "SNAP-JZSC-BROWSER-CURRENT",
                "source_slice_sha256": "SHA-JZSC-BROWSER-CURRENT",
                "confidence": 0.91,
            },
            {
                "field_name": "current_project_name",
                "field_value_optional": "Current public project",
                "source_file_ref": "SNAP-JZSC-BROWSER-CURRENT",
                "source_slice_sha256": "SHA-JZSC-BROWSER-NAME",
                "confidence": 0.91,
            },
            {
                "field_name": "candidate_company_name",
                "field_value_optional": "Alpha Construction Co",
                "source_file_ref": "SNAP-JZSC-BROWSER-CURRENT",
                "source_slice_sha256": "SHA-JZSC-BROWSER-COMPANY",
                "confidence": 0.91,
            },
            {
                "field_name": "project_manager_name",
                "field_value_optional": "陈庆丽",
                "source_file_ref": "SNAP-JZSC-BROWSER-CURRENT",
                "source_slice_sha256": "SHA-JZSC-BROWSER-PM",
                "confidence": 0.91,
            },
        ],
    }


class Stage4JzscPersonnelAdapterTests(unittest.TestCase):
    def test_company_first_capture_plan_requires_browser_and_stable_identifier_route(self) -> None:
        plan = build_jzsc_company_first_capture_plan(
            target_company_name="Alpha Construction Co",
            target_project_manager_name="陈庆丽",
        )

        self.assertEqual(
            plan["capture_plan_type"],
            "JZSC_COMPANY_FIRST_PROJECT_MANAGER_VERIFICATION",
        )
        self.assertTrue(plan["browser_required"])
        self.assertTrue(plan["automated_challenge_resolution_first"])
        self.assertFalse(plan["resume_requires_human_input"])
        self.assertEqual(
            plan["stable_identity_key_policy"]["company_first_required"],
            True,
        )
        self.assertFalse(
            plan["stable_identity_key_policy"]["broad_name_search_allowed_as_final_proof"]
        )
        self.assertIn("name_only_match_cannot_pass", plan["fail_closed_conditions"])
        self.assertIn(
            "capture_registered_personnel_rows",
            {step["step_id"] for step in plan["capture_steps"]},
        )
        self.assertIn(
            "capture_personnel_project_rows",
            {step["step_id"] for step in plan["capture_steps"]},
        )

    def test_parse_browser_rendered_personnel_rows(self) -> None:
        rows = parse_jzsc_personnel_rows(RENDERED_PERSONNEL_ROWS)

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[2]["person_name"], "陈庆丽")
        self.assertEqual(rows[2]["registration_category"], "一级注册建造师")
        self.assertEqual(rows[2]["registration_no"], "鲁1372017201820810")
        self.assertEqual(rows[3]["registration_category"], "注册电气工程师（供配电）")

    def test_same_name_without_registration_identifier_fails_to_review(self) -> None:
        carrier = build_jzsc_personnel_list_carrier(
            RENDERED_PERSONNEL_ROWS,
            target_name="郭敏锋",
            source_url="https://jzsc.mohurd.gov.cn/data/person",
            source_snapshot_id="SNAP-JZSC-PERSON-001",
        )

        self.assertEqual(carrier["verification_result"], "REVIEW_REQUIRED")
        self.assertEqual(carrier["failure_reason_optional"], AMBIGUOUS_PUBLIC_MATCH)
        self.assertTrue(carrier["review_required"])
        self.assertEqual(len(carrier["matched_personnel_rows"]), 2)

    def test_registration_identifier_match_feeds_active_conflict_identity_resolution(self) -> None:
        personnel_carrier = build_jzsc_personnel_list_carrier(
            RENDERED_PERSONNEL_ROWS,
            target_name="陈庆丽",
            target_identifier="鲁1372017201820810",
            source_url="https://jzsc.mohurd.gov.cn/data/person",
            source_snapshot_id="SNAP-JZSC-PERSON-002",
        )

        active_conflict = Stage4Service().evaluate_project_manager_active_conflict(
            {
                "parsed_fields": [
                    {
                        "field_name": "current_project_id",
                        "field_value_optional": "PRJ-JZSC-CURRENT",
                    },
                    {
                        "field_name": "current_project_name",
                        "field_value_optional": "Current public project",
                    },
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                    },
                    {
                        "field_name": "project_manager_public_identifier_optional",
                        "field_value_optional": "鲁1372017201820810",
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            public_verification_carriers=[personnel_carrier, _registered_unit_carrier()],
            possible_conflicting_projects=[
                {
                    "project_id": "PRJ-JZSC-CONFLICT",
                    "project_name": "Earlier public project",
                    "registered_unit_name": "Alpha Construction Co",
                    "project_manager_name": "陈庆丽",
                    "project_manager_public_identifier_optional": "鲁1372017201820810",
                    "contract_time_window": {
                        "start_at": "2026-03-01",
                        "end_at": "2026-08-31",
                    },
                    "completion_acceptance_status": "NO_PUBLIC_COMPLETION_ACCEPTANCE_PROOF",
                    "verification_carriers": [personnel_carrier],
                }
            ],
        )

        self.assertEqual(personnel_carrier["verification_result"], "MATCHED")
        self.assertEqual(
            active_conflict["manager_identity_resolution"]["resolution_state"],
            "MATCHED",
        )
        self.assertTrue(active_conflict["same_name_disambiguation"]["public_identifier_match"])
        self.assertEqual(active_conflict["overlap_judgement"], "OVERLAP_RISK")

    def test_missing_source_snapshot_keeps_personnel_carrier_in_review(self) -> None:
        personnel_carrier = build_jzsc_personnel_list_carrier(
            RENDERED_PERSONNEL_ROWS,
            target_name="陈庆丽",
            target_identifier="鲁1372017201820810",
            source_url="https://jzsc.mohurd.gov.cn/data/person",
            source_snapshot_id="",
        )

        active_conflict = Stage4Service().evaluate_project_manager_active_conflict(
            {
                "parsed_fields": [
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            public_verification_carriers=[personnel_carrier, _registered_unit_carrier()],
            possible_conflicting_projects=[],
        )

        self.assertEqual(personnel_carrier["verification_result"], "REVIEW_REQUIRED")
        self.assertTrue(personnel_carrier["review_required"])
        self.assertIn(SOURCE_SNAPSHOT_MISSING, personnel_carrier["failure_reasons"])
        self.assertEqual(
            active_conflict["manager_identity_resolution"]["resolution_state"],
            "REVIEW",
        )
        self.assertIn(
            "manager_personnel_public_record_unmatched_or_review_required",
            active_conflict["failure_reasons"],
        )

    def test_company_first_unique_personnel_row_derives_certificate_identifier(self) -> None:
        personnel_carrier = build_jzsc_company_personnel_resolution_carrier(
            RENDERED_COMPANY_PERSONNEL_ROWS,
            target_company_name="Alpha Construction Co",
            target_name="陈庆丽",
            source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-001",
        )

        self.assertEqual(personnel_carrier["verification_result"], "MATCHED")
        self.assertFalse(personnel_carrier["review_required"])
        self.assertEqual(
            personnel_carrier["project_manager_public_identifier_optional"],
            "鲁1372017201820810",
        )
        self.assertEqual(
            personnel_carrier["personnel_detail_url_optional"],
            "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
        )
        self.assertTrue(
            personnel_carrier["identifier_resolution"]["derived_identifier_from_matched_row"]
        )

    def test_company_first_registered_unit_conflict_forces_review(self) -> None:
        personnel_carrier = build_jzsc_company_personnel_resolution_carrier(
            [
                {
                    "row_text": "1 陈庆丽 372929**********69 一级注册建造师 鲁1372017201820810",
                    "registered_unit_name": "Different Construction Co",
                }
            ],
            target_company_name="Alpha Construction Co",
            target_name="陈庆丽",
            source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-UNIT-MISMATCH",
        )

        self.assertEqual(personnel_carrier["verification_result"], "REVIEW_REQUIRED")
        self.assertTrue(personnel_carrier["review_required"])
        self.assertIn(REGISTERED_UNIT_CONFLICT, personnel_carrier["failure_reasons"])
        self.assertEqual(
            personnel_carrier["identifier_resolution"]["failure_reason_optional"],
            REGISTERED_UNIT_CONFLICT,
        )

    def test_company_first_certificate_identifier_flows_into_active_conflict_and_strategy(self) -> None:
        personnel_carrier = build_jzsc_company_personnel_resolution_carrier(
            RENDERED_COMPANY_PERSONNEL_ROWS,
            target_company_name="Alpha Construction Co",
            target_name="陈庆丽",
            source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-002",
        )
        parsed_context = {
            "parse_run_id": "PARSE-JZSC-COMPANY-FIRST",
            "snapshot_id": "SNAP-JZSC-CURRENT-NOTICE",
            "source_url": "https://example.invalid/current-notice.html",
            "lineage_status": "NORMALIZED",
            "conflict_state": "CONSISTENT",
            "parsed_fields": [
                {
                    "field_name": "current_project_id",
                    "field_value_optional": "PRJ-JZSC-CURRENT",
                    "source_file_ref": "SNAP-JZSC-CURRENT-NOTICE",
                    "source_slice_sha256": "SHA-CURRENT-ID",
                    "confidence": 0.91,
                },
                {
                    "field_name": "current_project_name",
                    "field_value_optional": "Current public project",
                    "source_file_ref": "SNAP-JZSC-CURRENT-NOTICE",
                    "source_slice_sha256": "SHA-CURRENT-NAME",
                    "confidence": 0.91,
                },
                {
                    "field_name": "candidate_company_name",
                    "field_value_optional": "Alpha Construction Co",
                    "source_file_ref": "SNAP-JZSC-CURRENT-NOTICE",
                    "source_slice_sha256": "SHA-COMPANY",
                    "confidence": 0.91,
                },
                {
                    "field_name": "project_manager_name",
                    "field_value_optional": "陈庆丽",
                    "source_file_ref": "SNAP-JZSC-CURRENT-NOTICE",
                    "source_slice_sha256": "SHA-PM-NAME",
                    "confidence": 0.91,
                },
            ],
            "current_project_time_window": {
                "start_at": "2026-05-01",
                "end_at": "2026-10-01",
            },
        }

        active_conflict = Stage4Service().evaluate_project_manager_active_conflict(
            parsed_context,
            public_verification_carriers=[personnel_carrier, _registered_unit_carrier()],
            possible_conflicting_projects=[
                {
                    "project_id": "PRJ-JZSC-CONFLICT",
                    "project_name": "Earlier public project",
                    "registered_unit_name": "Alpha Construction Co",
                    "project_manager_name": "陈庆丽",
                    "project_manager_public_identifier_optional": "鲁1372017201820810",
                    "contract_time_window": {
                        "start_at": "2026-03-01",
                        "end_at": "2026-08-31",
                    },
                    "completion_acceptance_status": "NO_PUBLIC_COMPLETION_ACCEPTANCE_PROOF",
                    "verification_carriers": [personnel_carrier],
                }
            ],
        )
        strategy = Stage4Service().build_evidence_risk_hard_defect_strategy(
            parsed_context,
            existing_public_verification_carriers=[personnel_carrier],
        )

        self.assertEqual(
            active_conflict["project_manager"]["project_manager_public_identifier_optional"],
            "鲁1372017201820810",
        )
        self.assertEqual(
            active_conflict["manager_identity_resolution"]["resolved_public_identifier_source"],
            "matched_enterprise_personnel_public_record",
        )
        self.assertTrue(active_conflict["same_name_disambiguation"]["public_identifier_match"])
        self.assertNotIn("same_name_not_disambiguated", strategy["fail_closed_reasons"])
        target_by_type = {
            item["verification_target_type"]: item
            for item in strategy["verification_targets"]
        }
        self.assertEqual(
            target_by_type["personnel_public_record"]["target_identifier"],
            "鲁1372017201820810",
        )
        self.assertEqual(
            target_by_type["performance_public_record"]["target_identifier"],
            "鲁1372017201820810",
        )

    def test_personnel_project_rows_build_conflict_records_for_active_conflict(self) -> None:
        personnel_carrier = build_jzsc_company_personnel_resolution_carrier(
            RENDERED_COMPANY_PERSONNEL_ROWS,
            target_company_name="Alpha Construction Co",
            target_name="陈庆丽",
            source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-003",
        )
        project_rows = parse_jzsc_personnel_project_rows(RENDERED_PERSONNEL_PROJECT_ROWS)
        conflict_records = build_jzsc_personnel_project_conflict_records(
            RENDERED_PERSONNEL_PROJECT_ROWS,
            project_manager_name="陈庆丽",
            project_manager_identifier="鲁1372017201820810",
            registered_unit_name="Alpha Construction Co",
            source_url="https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
            source_snapshot_id="SNAP-JZSC-PERSON-PROJECTS-001",
        )

        self.assertEqual(project_rows[0]["project_name"], "Earlier public bridge project")
        self.assertEqual(
            conflict_records[0]["verification_carriers"][0]["verification_target_type"],
            "performance_public_record",
        )
        self.assertEqual(
            conflict_records[0]["verification_carriers"][1]["verification_target_type"],
            "contract_public_info",
        )
        self.assertEqual(
            conflict_records[0]["verification_carriers"][2]["verification_target_type"],
            "completion_filing",
        )

        active_conflict = Stage4Service().evaluate_project_manager_active_conflict(
            {
                "parsed_fields": [
                    {
                        "field_name": "current_project_id",
                        "field_value_optional": "PRJ-JZSC-CURRENT",
                    },
                    {
                        "field_name": "current_project_name",
                        "field_value_optional": "Current public project",
                    },
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            public_verification_carriers=[personnel_carrier, _registered_unit_carrier()],
            possible_conflicting_projects=conflict_records,
        )

        self.assertEqual(active_conflict["overlap_judgement"], "OVERLAP_RISK")
        self.assertTrue(active_conflict["same_name_disambiguation"]["public_identifier_match"])
        self.assertTrue(active_conflict["possible_conflicting_projects"][0]["overlap_with_current"])
        self.assertTrue(active_conflict["possible_conflicting_projects"][0]["public_evidence_refs"])

    def test_personnel_project_rows_without_snapshot_do_not_become_matched_evidence(self) -> None:
        personnel_carrier = build_jzsc_company_personnel_resolution_carrier(
            RENDERED_COMPANY_PERSONNEL_ROWS,
            target_company_name="Alpha Construction Co",
            target_name="陈庆丽",
            source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-005",
        )
        conflict_records = build_jzsc_personnel_project_conflict_records(
            RENDERED_PERSONNEL_PROJECT_ROWS,
            project_manager_name="陈庆丽",
            project_manager_identifier="鲁1372017201820810",
            registered_unit_name="Alpha Construction Co",
            source_url="https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
            source_snapshot_id="",
        )

        carrier_results = [
            carrier["verification_result"]
            for carrier in conflict_records[0]["verification_carriers"]
        ]
        self.assertEqual(carrier_results, ["REVIEW_REQUIRED"] * 3)
        self.assertIn(
            SOURCE_SNAPSHOT_MISSING,
            conflict_records[0]["verification_carriers"][0]["failure_reasons"],
        )
        active_conflict = Stage4Service().evaluate_project_manager_active_conflict(
            {
                "parsed_fields": [
                    {
                        "field_name": "current_project_id",
                        "field_value_optional": "PRJ-JZSC-CURRENT",
                    },
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            public_verification_carriers=[personnel_carrier, _registered_unit_carrier()],
            possible_conflicting_projects=conflict_records,
        )

        self.assertEqual(active_conflict["overlap_judgement"], "REVIEW_REQUIRED")
        self.assertFalse(active_conflict["possible_conflicting_projects"][0]["public_evidence_refs"])
        self.assertIn(
            "conflicting_project_public_record_unmatched_or_review_required",
            active_conflict["failure_reasons"],
        )

    def test_stage4_service_company_first_readback_builds_strategy_and_conflict_bundle(self) -> None:
        result = Stage4Service().build_jzsc_project_manager_company_first_readback(
            {
                "parse_run_id": "PARSE-JZSC-COMPANY-FIRST-SERVICE",
                "snapshot_id": "SNAP-JZSC-CURRENT-NOTICE-SERVICE",
                "source_url": "https://example.invalid/current-notice.html",
                "lineage_status": "NORMALIZED",
                "conflict_state": "CONSISTENT",
                "parsed_fields": [
                    {
                        "field_name": "current_project_id",
                        "field_value_optional": "PRJ-JZSC-CURRENT",
                        "source_file_ref": "SNAP-JZSC-CURRENT-NOTICE-SERVICE",
                        "source_slice_sha256": "SHA-CURRENT-ID",
                        "confidence": 0.91,
                    },
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                        "source_file_ref": "SNAP-JZSC-CURRENT-NOTICE-SERVICE",
                        "source_slice_sha256": "SHA-COMPANY",
                        "confidence": 0.91,
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                        "source_file_ref": "SNAP-JZSC-CURRENT-NOTICE-SERVICE",
                        "source_slice_sha256": "SHA-PM-NAME",
                        "confidence": 0.91,
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            target_company_name="Alpha Construction Co",
            target_project_manager_name="陈庆丽",
            rendered_company_personnel_rows=RENDERED_COMPANY_PERSONNEL_ROWS,
            company_personnel_source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            company_personnel_source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-004",
            rendered_personnel_project_rows=RENDERED_PERSONNEL_PROJECT_ROWS,
            personnel_project_source_url="https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
            personnel_project_source_snapshot_id="SNAP-JZSC-PERSON-PROJECTS-002",
            base_public_verification_carriers=[_registered_unit_carrier()],
        )

        self.assertEqual(result["route"], "JZSC_COMPANY_FIRST_PROJECT_MANAGER")
        self.assertEqual(result["resolved_public_identifier_optional"], "鲁1372017201820810")
        self.assertEqual(
            result["capture_plan"]["capture_plan_type"],
            "JZSC_COMPANY_FIRST_PROJECT_MANAGER_VERIFICATION",
        )
        self.assertTrue(result["capture_plan"]["browser_required"])
        self.assertEqual(result["personnel_carrier"]["verification_result"], "MATCHED")
        self.assertEqual(len(result["conflict_records"]), 1)
        self.assertEqual(
            result["project_manager_active_conflict"]["overlap_judgement"],
            "OVERLAP_RISK",
        )
        self.assertEqual(
            result["project_manager_active_conflict_readback"]["readback_state"],
            "READBACK_READY",
        )
        target_by_type = {
            item["verification_target_type"]: item
            for item in result["evidence_risk_hard_defect_strategy"]["verification_targets"]
        }
        self.assertEqual(
            target_by_type["contract_public_info"]["target_identifier"],
            "鲁1372017201820810",
        )

    def test_stage4_rendered_adapter_entrypoint_builds_readback_from_captured_rows(self) -> None:
        result = Stage4Service().run_jzsc_company_first_rendered_readback(
            {
                "parse_run_id": "PARSE-JZSC-RENDERED-ADAPTER",
                "snapshot_id": "SNAP-JZSC-CURRENT-NOTICE-ADAPTER",
                "source_url": "https://example.invalid/current-notice.html",
                "lineage_status": "NORMALIZED",
                "conflict_state": "CONSISTENT",
                "parsed_fields": [
                    {
                        "field_name": "current_project_id",
                        "field_value_optional": "PRJ-JZSC-CURRENT",
                    },
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            target_company_name="Alpha Construction Co",
            target_project_manager_name="陈庆丽",
            rendered_company_personnel_rows=RENDERED_COMPANY_PERSONNEL_ROWS,
            company_personnel_source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            company_personnel_source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-ADAPTER",
            rendered_personnel_project_rows=RENDERED_PERSONNEL_PROJECT_ROWS,
            personnel_project_source_url="https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
            personnel_project_source_snapshot_id="SNAP-JZSC-PERSON-PROJECTS-ADAPTER",
            base_public_verification_carriers=[_registered_unit_carrier()],
        )

        self.assertEqual(result["adapter_id"], "stage4.jzsc_company_first_rendered.v1")
        self.assertEqual(result["adapter_state"], "READBACK_READY")
        self.assertEqual(result["identity_resolution_state"], "MATCHED")
        self.assertEqual(result["fail_closed_reasons"], [])
        self.assertEqual(result["rendered_company_personnel_row_count"], 1)
        self.assertEqual(result["rendered_personnel_project_row_count"], 1)
        self.assertEqual(result["personnel_carrier"]["verification_result"], "MATCHED")
        self.assertEqual(
            result["project_manager_active_conflict"]["overlap_judgement"],
            "OVERLAP_RISK",
        )
        self.assertFalse(result["customer_sellable_evidence_ready"])
        self.assertTrue(result["no_name_only_final_proof"])

    def test_stage4_browser_executor_persists_rendered_rows_and_builds_readback(self) -> None:
        def fake_browser_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            self.assertEqual(
                capture_plan["capture_plan_type"],
                "JZSC_COMPANY_FIRST_PROJECT_MANAGER_VERIFICATION",
            )
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
                "personnel_project_source_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
                "rendered_company_personnel_rows": RENDERED_COMPANY_PERSONNEL_ROWS,
                "rendered_personnel_project_rows": RENDERED_PERSONNEL_PROJECT_ROWS,
                "failure_reasons": [],
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _object_storage_repo(tmp_dir)
            result = Stage4Service().run_jzsc_company_first_browser_execution(
                _parsed_jzsc_current_context(),
                target_company_name="Alpha Construction Co",
                target_project_manager_name="陈庆丽",
                repository=repo,
                browser_runner=fake_browser_runner,
                base_public_verification_carriers=[_registered_unit_carrier()],
            )
            company_snapshot = result["company_personnel_source_snapshot_id"]
            project_snapshot = result["personnel_project_source_snapshot_id"]
            self.assertTrue(repo.replay_snapshot(company_snapshot)["replayable"])
            self.assertTrue(repo.replay_snapshot(project_snapshot)["replayable"])

        self.assertEqual(result["adapter_id"], "stage4.jzsc_company_first_browser_executor.v1")
        self.assertEqual(result["executor_state"], "READBACK_READY")
        self.assertEqual(result["identity_resolution_state"], "MATCHED")
        self.assertEqual(result["personnel_carrier"]["verification_result"], "MATCHED")
        self.assertEqual(
            result["resolved_public_identifier_optional"],
            "鲁1372017201820810",
        )
        self.assertEqual(result["rendered_company_personnel_row_count"], 1)
        self.assertEqual(result["rendered_personnel_project_row_count"], 1)

    def test_stage4_browser_executor_fails_closed_without_rendered_rows(self) -> None:
        def fake_blocked_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": str(capture_plan.get("entry_url") or ""),
                "rendered_company_personnel_rows": [],
                "failure_reasons": ["challenge_unresolved_before_capture"],
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = Stage4Service().run_jzsc_company_first_browser_execution(
                _parsed_jzsc_current_context(),
                target_company_name="Alpha Construction Co",
                target_project_manager_name="陈庆丽",
                repository=_object_storage_repo(tmp_dir),
                browser_runner=fake_blocked_runner,
            )

        self.assertEqual(result["executor_state"], "FAIL_CLOSED")
        self.assertEqual(result["readback_state"], "REVIEW_REQUIRED")
        self.assertFalse(result["customer_sellable_evidence_ready"])
        self.assertIn("challenge_unresolved_before_capture", result["fail_closed_reasons"])
        self.assertIn("rendered_company_personnel_rows_missing", result["fail_closed_reasons"])

    def test_stage4_rendered_adapter_fails_closed_when_personnel_rows_missing(self) -> None:
        result = Stage4Service().run_jzsc_company_first_rendered_readback(
            {
                "parse_run_id": "PARSE-JZSC-MISSING-ROWS",
                "parsed_fields": [
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                    },
                ],
            },
            target_company_name="Alpha Construction Co",
            target_project_manager_name="陈庆丽",
            rendered_company_personnel_rows=[],
            company_personnel_source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            company_personnel_source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-MISSING",
        )

        self.assertEqual(result["adapter_state"], "FAIL_CLOSED")
        self.assertEqual(result["readback_state"], "REVIEW_REQUIRED")
        self.assertEqual(result["identity_resolution_state"], "NOT_RUN_FAIL_CLOSED")
        self.assertIn("rendered_personnel_rows_missing", result["fail_closed_reasons"])
        self.assertEqual(result["conflict_records"], [])
        self.assertEqual(result["evidence_risk_hard_defect_strategy"], {})
        self.assertFalse(result["customer_sellable_evidence_ready"])

    def test_stage4_rendered_adapter_requires_project_snapshot_for_project_rows(self) -> None:
        result = Stage4Service().run_jzsc_company_first_rendered_readback(
            {
                "parse_run_id": "PARSE-JZSC-PROJECT-SNAPSHOT-MISSING",
                "parsed_fields": [
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "陈庆丽",
                    },
                ],
            },
            target_company_name="Alpha Construction Co",
            target_project_manager_name="陈庆丽",
            rendered_company_personnel_rows=RENDERED_COMPANY_PERSONNEL_ROWS,
            company_personnel_source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            company_personnel_source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-OK",
            rendered_personnel_project_rows=RENDERED_PERSONNEL_PROJECT_ROWS,
        )

        self.assertEqual(result["adapter_state"], "FAIL_CLOSED")
        self.assertIn(
            "personnel_project_source_url_missing_for_project_rows",
            result["fail_closed_reasons"],
        )
        self.assertIn(
            "personnel_project_source_snapshot_missing_for_project_rows",
            result["fail_closed_reasons"],
        )
        self.assertEqual(result["conflict_records"], [])

    def test_stage4_rendered_adapter_keeps_same_name_ambiguity_in_review(self) -> None:
        result = Stage4Service().run_jzsc_company_first_rendered_readback(
            {
                "parse_run_id": "PARSE-JZSC-AMBIGUOUS",
                "parsed_fields": [
                    {
                        "field_name": "current_project_id",
                        "field_value_optional": "PRJ-JZSC-CURRENT",
                    },
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "郭敏锋",
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
            },
            target_company_name="Alpha Construction Co",
            target_project_manager_name="郭敏锋",
            rendered_company_personnel_rows=RENDERED_PERSONNEL_ROWS,
            company_personnel_source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
            company_personnel_source_snapshot_id="SNAP-JZSC-COMPANY-PERSONNEL-AMBIGUOUS",
        )

        self.assertEqual(result["adapter_state"], "READBACK_READY")
        self.assertEqual(result["identity_resolution_state"], "REVIEW_REQUIRED")
        self.assertEqual(result["personnel_carrier"]["verification_result"], "REVIEW_REQUIRED")
        self.assertEqual(
            result["personnel_carrier"]["failure_reason_optional"],
            AMBIGUOUS_PUBLIC_MATCH,
        )
        self.assertIn(
            "manager_personnel_public_record_unmatched_or_review_required",
            result["project_manager_active_conflict"]["failure_reasons"],
        )

    def test_ambiguous_rendered_personnel_row_does_not_satisfy_identity_resolution(self) -> None:
        personnel_carrier = build_jzsc_personnel_list_carrier(
            RENDERED_PERSONNEL_ROWS,
            target_name="郭敏锋",
            source_url="https://jzsc.mohurd.gov.cn/data/person",
            source_snapshot_id="SNAP-JZSC-PERSON-003",
        )

        active_conflict = Stage4Service().evaluate_project_manager_active_conflict(
            {
                "parsed_fields": [
                    {
                        "field_name": "current_project_id",
                        "field_value_optional": "PRJ-JZSC-CURRENT",
                    },
                    {
                        "field_name": "current_project_name",
                        "field_value_optional": "Current public project",
                    },
                    {
                        "field_name": "candidate_company_name",
                        "field_value_optional": "Alpha Construction Co",
                    },
                    {
                        "field_name": "project_manager_name",
                        "field_value_optional": "郭敏锋",
                    },
                ],
                "current_project_time_window": {
                    "start_at": "2026-05-01",
                    "end_at": "2026-10-01",
                },
                "project_manager_registration_at": "2025-01-01",
            },
            public_verification_carriers=[personnel_carrier, _registered_unit_carrier()],
            possible_conflicting_projects=[],
        )

        self.assertEqual(personnel_carrier["verification_result"], "REVIEW_REQUIRED")
        self.assertEqual(
            active_conflict["manager_identity_resolution"]["resolution_state"],
            "REVIEW",
        )
        self.assertFalse(
            active_conflict["manager_identity_resolution"]["personnel_record_verified"]
        )
        self.assertIn(
            "manager_personnel_public_record_unmatched_or_review_required",
            active_conflict["failure_reasons"],
        )
        self.assertIn(
            "enterprise_personnel_record_unmatched_or_review_required",
            active_conflict["manager_identity_resolution"]["failure_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
