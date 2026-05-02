from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.active_conflict import (
    INSUFFICIENT_PUBLIC_EVIDENCE,
    OVERLAP_RISK,
    REVIEW_REQUIRED,
)
from stage4_verification.service import Stage4Service


def _parsed_context(
    *,
    project_id: str = "PRJ-CURRENT-001",
    project_name: str = "Current municipal road project",
    company_name: str = "Alpha Construction Co",
    manager_name: str = "Li Wei",
    public_identifier: str | None = "CERT-PM-001",
    current_window: dict[str, str] | None = None,
) -> dict[str, object]:
    fields = [
        ("current_project_id", project_id),
        ("current_project_name", project_name),
        ("candidate_company_name", company_name),
        ("project_manager_name", manager_name),
    ]
    if public_identifier is not None:
        fields.append(("project_manager_public_identifier_optional", public_identifier))
    return {
        "parsed_fields": [
            {
                "field_name": name,
                "field_value_optional": value,
                "confidence": 0.91,
                "source_file_ref": "SNAP-STAGE3-CURRENT",
                "source_slice_sha256": f"SHA-{name}",
            }
            for name, value in fields
        ],
        "current_project_time_window": current_window
        or {"start_at": "2026-05-01", "end_at": "2026-10-01"},
    }


def _carrier(
    name: str,
    target_type: str,
    *,
    role: str | None = None,
    visibility: str = "PUBLIC_VISIBLE",
    result: str = "MATCHED",
    grade: str = "PUBLIC_SNAPSHOT_FIELD_MATCH",
    confidence: float = 0.92,
    provider: str = "stage4-public-verification-readback",
    review_required: bool = False,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    source_url = f"https://example.invalid/public/{name}.html"
    snapshot_id = f"SNAP-{name.upper()}"
    carrier: dict[str, object] = {
        "verification_run_id": f"ST4PV-{name}",
        "verification_target_id": f"TARGET-{name}",
        "verification_target_type": target_type,
        "source_snapshot_id": snapshot_id,
        "source_url": source_url,
        "public_visibility_state": visibility,
        "verification_provider": provider,
        "verification_result": result,
        "evidence_grade": grade,
        "confidence": confidence,
        "review_required": review_required,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "source_refs": [
            {
                "source_url": source_url,
                "source_snapshot_id": snapshot_id,
                "public_visibility_state": visibility,
            }
        ],
        "snapshot_refs": [
            {
                "snapshot_id": snapshot_id,
                "replayable": True,
            }
        ],
    }
    if role is not None:
        carrier["verification_role"] = role
    if extra:
        carrier.update(extra)
    return carrier


def _base_carriers() -> list[dict[str, object]]:
    return [
        _carrier("manager-personnel", "personnel_public_record"),
        _carrier(
            "registered-unit",
            "enterprise_public_record",
            role="registered_unit_verification",
        ),
        _carrier("conflict-project", "performance_public_record"),
        _carrier("conflict-contract", "contract_public_info"),
        _carrier("conflict-permit", "construction_permit"),
        _carrier("conflict-completion", "completion_filing"),
    ]


def _conflict_project(
    *,
    company_name: str = "Alpha Construction Co",
    manager_name: str = "Li Wei",
    public_identifier: str | None = "CERT-PM-001",
    time_window: dict[str, str] | None = None,
    completion_status: str | None = "NO_PUBLIC_COMPLETION_ACCEPTANCE_PROOF",
    carriers: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    project: dict[str, object] = {
        "project_id": "PRJ-CONFLICT-001",
        "project_name": "Earlier bridge works",
        "registered_unit_name": company_name,
        "project_manager_name": manager_name,
        "contract_time_window": time_window
        if time_window is not None
        else {"start_at": "2026-03-01", "end_at": "2026-08-31"},
        "verification_carriers": carriers or _base_carriers()[2:],
    }
    if public_identifier is not None:
        project["project_manager_public_identifier_optional"] = public_identifier
    if completion_status is not None:
        project["completion_acceptance_status"] = completion_status
    return project


class ProjectManagerActiveConflictVerticalSliceTests(unittest.TestCase):
    def test_happy_path_outputs_overlap_risk_review_and_evidence_chain(self) -> None:
        service = Stage4Service()

        carrier = service.evaluate_project_manager_active_conflict(
            _parsed_context(),
            public_verification_carriers=_base_carriers(),
            possible_conflicting_projects=[_conflict_project()],
        )
        readback = service.build_project_manager_active_conflict_readback(carrier)

        self.assertEqual(carrier["overlap_judgement"], OVERLAP_RISK)
        self.assertTrue(carrier["review_required"])
        self.assertEqual(carrier["current_project"]["current_project_id"], "PRJ-CURRENT-001")
        self.assertEqual(carrier["candidate_company"]["candidate_company_name"], "Alpha Construction Co")
        self.assertEqual(carrier["project_manager"]["project_manager_name"], "Li Wei")
        self.assertTrue(carrier["public_evidence_chain"])
        self.assertEqual(
            set(carrier["public_evidence_chain"][0]),
            {
                "source_url",
                "source_snapshot_id",
                "verification_run_id",
                "verification_target_type",
                "evidence_grade",
                "confidence",
                "public_visibility_state",
            },
        )
        self.assertTrue(readback["project_timeline_evidence_refs"])
        self.assertIn(
            "contract_public_info",
            {
                ref["verification_target_type"]
                for ref in readback["project_timeline_evidence_refs"]
            },
        )
        self.assertTrue(carrier["same_name_disambiguation"]["registered_unit_match"])
        self.assertTrue(carrier["same_name_disambiguation"]["public_identifier_match"])
        self.assertEqual(
            carrier["manager_identity_resolution"]["resolution_route"],
            "ENTERPRISE_FIRST_PERSONNEL_DETAIL",
        )
        self.assertFalse(
            carrier["manager_identity_resolution"]["broad_name_search_allowed_as_final_proof"]
        )
        self.assertFalse(carrier["customer_visible"])
        self.assertTrue(carrier["no_legal_conclusion"])
        self.assertEqual(readback["readback_state"], "READBACK_READY")
        self.assertTrue(readback["replayable"])

    def test_same_name_fail_closed_without_unit_or_public_identifier_match(self) -> None:
        carrier = Stage4Service().evaluate_project_manager_active_conflict(
            _parsed_context(public_identifier=None),
            public_verification_carriers=_base_carriers(),
            possible_conflicting_projects=[
                _conflict_project(
                    company_name="Other Construction Co",
                    public_identifier=None,
                )
            ],
        )

        self.assertEqual(carrier["overlap_judgement"], REVIEW_REQUIRED)
        self.assertTrue(carrier["review_required"])
        disambiguation = carrier["same_name_disambiguation"]
        self.assertTrue(disambiguation["same_name_only"])
        self.assertFalse(disambiguation["registered_unit_match"])
        self.assertFalse(disambiguation["public_identifier_match"])
        self.assertTrue(disambiguation["public_identifier_missing"])
        self.assertIn("same_name_only_not_identity_conclusion", disambiguation["ambiguity_reason"])
        self.assertFalse(carrier["manager_identity_resolution"]["same_name_only_accepted"])

    def test_registration_timeline_after_current_project_start_requires_review(self) -> None:
        carriers = [
            _carrier(
                "manager-personnel",
                "personnel_public_record",
                extra={
                    "project_manager_registration_at": "2026-06-15",
                    "certificate_valid_until": "2026-07-01",
                },
            ),
            _carrier(
                "registered-unit",
                "enterprise_public_record",
                role="registered_unit_verification",
            ),
        ]

        carrier = Stage4Service().evaluate_project_manager_active_conflict(
            _parsed_context(current_window={"start_at": "2026-05-01", "end_at": "2026-10-01"}),
            public_verification_carriers=carriers,
            possible_conflicting_projects=[_conflict_project()],
        )

        timeline = carrier["registration_timeline_verification"]
        self.assertEqual(timeline["verification_scope"], "PROJECT_MANAGER_REGISTRATION_TIMELINE")
        self.assertEqual(timeline["registration_at"], "2026-06-15")
        self.assertEqual(timeline["certificate_valid_until"], "2026-07-01")
        self.assertEqual(timeline["verification_result"], "REVIEW")
        self.assertIn(
            "project_manager_registration_after_current_project_start",
            carrier["failure_reasons"],
        )
        self.assertIn(
            "project_manager_certificate_expires_before_current_project_end",
            carrier["failure_reasons"],
        )

    def test_missing_completion_acceptance_fails_closed_without_legal_conclusion(self) -> None:
        carrier = Stage4Service().evaluate_project_manager_active_conflict(
            _parsed_context(),
            public_verification_carriers=_base_carriers(),
            possible_conflicting_projects=[
                _conflict_project(completion_status=None)
            ],
        )

        self.assertEqual(carrier["overlap_judgement"], OVERLAP_RISK)
        self.assertTrue(carrier["review_required"])
        self.assertIn("completion_acceptance_status_missing", carrier["failure_reasons"])
        self.assertNotIn("conflict_confirmed", carrier)
        self.assertTrue(carrier["no_legal_conclusion"])

    def test_missing_conflict_time_window_returns_insufficient_public_evidence(self) -> None:
        carrier = Stage4Service().evaluate_project_manager_active_conflict(
            _parsed_context(),
            public_verification_carriers=_base_carriers(),
            possible_conflicting_projects=[
                _conflict_project(time_window={})
            ],
        )

        self.assertEqual(carrier["overlap_judgement"], INSUFFICIENT_PUBLIC_EVIDENCE)
        self.assertTrue(carrier["review_required"])
        self.assertIn("conflicting_project_time_window_missing", carrier["failure_reasons"])

    def test_live_provider_reference_fails_closed(self) -> None:
        live_provider_carriers = [
            _carrier("manager-personnel", "personnel_public_record"),
            _carrier(
                "registered-unit",
                "enterprise_public_record",
                role="registered_unit_verification",
                provider="reserved-live-provider",
            ),
        ]

        carrier = Stage4Service().evaluate_project_manager_active_conflict(
            _parsed_context(),
            public_verification_carriers=live_provider_carriers,
            possible_conflicting_projects=[_conflict_project(carriers=live_provider_carriers)],
        )

        self.assertEqual(carrier["overlap_judgement"], REVIEW_REQUIRED)
        self.assertTrue(carrier["review_required"])
        self.assertFalse(carrier["customer_visible"])

    def test_no_stage56_pollution_or_customer_visible_materials(self) -> None:
        carrier = Stage4Service().evaluate_project_manager_active_conflict(
            _parsed_context(),
            public_verification_carriers=_base_carriers(),
            possible_conflicting_projects=[_conflict_project()],
        )

        self.assertNotIn("rule_hit", carrier)
        self.assertNotIn("project_fact", carrier)
        self.assertFalse(carrier["customer_visible"])
        self.assertTrue(carrier["public_only"])
        self.assertTrue(carrier["no_legal_conclusion"])
        self.assertEqual(
            carrier["manual_review_recommendation"]["review_lane"],
            "PROJECT_MANAGER_ACTIVE_CONFLICT",
        )

    def test_new_active_conflict_module_is_registered(self) -> None:
        registry = yaml.safe_load(
            (ROOT / "control/product_module_registry.yaml").read_text(encoding="utf-8")
        )
        stage4 = {
            stage["stage_id"]: stage
            for stage in registry["stage_module_inventory"]
        }["stage4_verification"]
        public_slice = {
            item["slice_id"]: item
            for item in stage4["module_slices"]
        }["stage4.public_verification"]
        modules = {module["module_id"]: module for module in registry["modules"]}

        self.assertIn("src/stage4_verification/active_conflict.py", public_slice["current_files"])
        self.assertIn("src/stage4_verification/jzsc_personnel.py", public_slice["current_files"])
        self.assertIn("src/stage4_verification/verification_scope_policy.py", public_slice["current_files"])
        self.assertIn(
            "tests/test_project_manager_active_conflict_vertical_slice.py",
            public_slice["test_files"],
        )
        self.assertIn(
            "tests/test_stage4_jzsc_personnel_adapter.py",
            public_slice["test_files"],
        )
        self.assertIn(
            "tests/test_stage4_verification_scope_policy.py",
            public_slice["test_files"],
        )
        self.assertIn(
            "src/stage4_verification/active_conflict.py",
            modules["STAGE4-VERIFICATION-ATTACK-SURFACE"]["current_files"],
        )
        self.assertIn(
            "src/stage4_verification/jzsc_personnel.py",
            modules["STAGE4-VERIFICATION-ATTACK-SURFACE"]["current_files"],
        )
        self.assertIn(
            "src/stage4_verification/verification_scope_policy.py",
            modules["STAGE4-VERIFICATION-ATTACK-SURFACE"]["current_files"],
        )


if __name__ == "__main__":
    unittest.main()
