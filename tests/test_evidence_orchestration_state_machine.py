from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.evidence_orchestration_state_machine import build_evidence_orchestration_state  # noqa: E402


class EvidenceOrchestrationStateMachineTests(unittest.TestCase):
    def test_builds_ready_p13b_and_design_defer_states_without_p13b_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_count"], 3)
            self.assertEqual(summary["ready_for_p13b_project_count"], 2)
            self.assertEqual(
                summary["evidence_state_counts"],
                {
                    "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER": 1,
                    "READY_FOR_P13B_DATA_GGZY": 2,
                },
            )
            adapter_jobs = json.loads((root / "out" / "adapter-job-table.json").read_text(encoding="utf-8"))
            self.assertEqual(adapter_jobs["summary"]["job_type_counts"]["data_ggzy_company_history_overlap_triage"], 2)
            self.assertEqual(adapter_jobs["summary"]["job_type_counts"]["design_survey_responsible_adapter_plan"], 1)
            design_job = next(
                job
                for job in adapter_jobs["records"]
                if job["job_type"] == "design_survey_responsible_adapter_plan"
            )
            self.assertEqual(
                design_job["recommended_script"],
                "scripts/build-design-survey-responsible-adapter-plan-v1.ps1",
            )
            self.assertTrue(
                design_job["adapter_scope_guardrails"]["does_not_apply_construction_project_manager_release_rule"]
            )
            self.assertTrue((root / "out" / "stage6-fact-package-readiness-table.json").exists())
            batch_triage = json.loads((root / "out" / "batch-triage-table.json").read_text(encoding="utf-8"))
            self.assertEqual(
                batch_triage["summary"]["batch_triage_bucket_counts"],
                {
                    "RUN_DESIGN_SURVEY_RESPONSIBLE_ADAPTER_PLAN": 1,
                    "RUN_P13B_COMPANY_HISTORY": 2,
                },
            )
            self.assertEqual(summary["batch_triage_record_count"], 3)
            self.assertEqual(summary["continue_internal_project_count"], 3)

    def test_p13b_backtrace_required_becomes_original_notice_adapter_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_backtrace_required(p13b_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            self.assertEqual(by_project["PROJ-CN-GD-JG2026-11398-002"]["evidence_state"], "P13B_ORIGINAL_BACKTRACE_REQUIRED")
            self.assertEqual(by_project["PROJ-CN-GD-JG2026-11398-002"]["evidence_grade"], "PENDING_ORIGINAL_BACKTRACE")
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["batch_triage_bucket"],
                "CONTINUE_ORIGINAL_BACKTRACE",
            )
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["commercial_decision_state"],
                "CONTINUE_INTERNAL_EVIDENCE_RUN",
            )
            adapter_jobs = result["manifest"]["adapter_job_table"]["records"]
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11398-002"
                    and job["job_type"] == "p13b_original_notice_backtrace"
                    for job in adapter_jobs
                )
            )

    def test_design_survey_adapter_plan_promotes_project_to_stage4_inputs_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            design = by_project["PROJ-CN-GD-JG2026-11327"]
            self.assertEqual(design["evidence_state"], "DESIGN_SURVEY_STAGE4_INPUTS_READY")
            self.assertEqual(design["evidence_grade"], "PENDING_DESIGN_SURVEY_STAGE4")
            self.assertEqual(design["design_survey_adapter_counts"]["design_survey_plan_stage4_input_count"], 2)
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11327"]["batch_triage_bucket"],
                "RUN_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS",
            )
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11327"
                    and job["job_type"] == "design_survey_stage4_person_company_certificate_execution"
                    for job in result["manifest"]["adapter_job_table"]["records"]
                )
            )

    def test_design_survey_stage4_dry_run_keeps_provider_tasks_ready_not_identity_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_execution(stage4_root, resolved=False)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            design = by_project["PROJ-CN-GD-JG2026-11327"]
            self.assertEqual(design["evidence_state"], "DESIGN_SURVEY_STAGE4_PROVIDER_TASKS_READY")
            self.assertEqual(design["recommended_next_action"], "execute_design_survey_stage4_provider_tasks")
            self.assertEqual(design["design_survey_adapter_counts"]["design_survey_stage4_queued_not_executed_count"], 2)
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11327"]["batch_triage_bucket"],
                "EXECUTE_DESIGN_SURVEY_STAGE4_PROVIDER_TASKS",
            )

    def test_design_survey_stage4_resolved_identity_becomes_internal_review_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_execution(stage4_root, resolved=True)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            design = by_project["PROJ-CN-GD-JG2026-11327"]
            self.assertEqual(design["evidence_state"], "DESIGN_SURVEY_RESPONSIBLE_IDENTITY_MATCH_READY")
            self.assertEqual(design["stage6_fact_package_state"], "REVIEW_FACT_PACKAGE_READY")
            self.assertEqual(result["summary"]["design_survey_identity_match_project_count"], 1)
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11327"]["commercial_decision_state"],
                "CONTINUE_INTERNAL_REVIEW_OR_STAGE6_FACT_PACKAGE",
            )

    def test_design_survey_flow08_readback_consumed_after_stage4_flow08_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            flow08_root = root / "design-flow08"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_flow08_required(stage4_root)
            _write_design_survey_flow08_readback(flow08_root, fetched=True)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_flow08_readback_root=flow08_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            design = by_project["PROJ-CN-GD-JG2026-11327"]
            self.assertEqual(
                design["evidence_state"],
                "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_FETCHED_PARSE_PENDING",
            )
            self.assertEqual(
                design["recommended_next_action"],
                "run_targeted_stage4_attachment_document_parse_for_design_survey_identity",
            )
            self.assertEqual(design["design_survey_adapter_counts"]["design_survey_flow08_target_attachment_fetched_count"], 1)
            jobs = result["manifest"]["adapter_job_table"]["records"]
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11327"
                    and job["job_type"] == "design_survey_flow08_target_attachment_parse"
                    and job["recommended_script"] == "scripts/build-design-survey-flow08-target-attachment-parse-v1.ps1"
                    for job in jobs
                )
            )

    def test_design_survey_flow08_attachment_parse_fields_becomes_stage4_replay_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            flow08_root = root / "design-flow08"
            parse_root = root / "design-flow08-parse"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_flow08_required(stage4_root)
            _write_design_survey_flow08_readback(flow08_root, fetched=True)
            _write_design_survey_flow08_attachment_parse(parse_root, state="TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED")

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_flow08_readback_root=flow08_root,
                design_survey_flow08_attachment_parse_root=parse_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            design = by_project["PROJ-CN-GD-JG2026-11327"]
            self.assertEqual(
                design["evidence_state"],
                "DESIGN_SURVEY_FLOW08_IDENTITY_FIELDS_EXTRACTED_REVIEW_READY",
            )
            self.assertEqual(
                design["recommended_next_action"],
                "build_design_survey_flow08_stage4_inputs_from_extracted_fields",
            )
            self.assertEqual(
                design["design_survey_adapter_counts"]["design_survey_flow08_field_extracted_record_count"],
                1,
            )
            jobs = result["manifest"]["adapter_job_table"]["records"]
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11327"
                    and job["job_type"] == "design_survey_flow08_build_stage4_inputs"
                    and job["recommended_script"] == "scripts/build-design-survey-flow08-stage4-inputs-v1.ps1"
                    for job in jobs
                )
            )

    def test_design_survey_flow08_person_dossier_parse_becomes_stage4_replay_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            flow08_root = root / "design-flow08"
            parse_root = root / "design-flow08-parse"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_flow08_required(stage4_root)
            _write_design_survey_flow08_readback(flow08_root, fetched=True)
            _write_design_survey_flow08_attachment_parse(parse_root, state="TARGET_ATTACHMENT_PERSON_DOSSIER_EXTRACTED")

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_flow08_readback_root=flow08_root,
                design_survey_flow08_attachment_parse_root=parse_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            design = _records_by_project(result["manifest"]["evidence_state_table"]["records"])[
                "PROJ-CN-GD-JG2026-11327"
            ]
            self.assertEqual(design["evidence_state"], "DESIGN_SURVEY_FLOW08_IDENTITY_FIELDS_EXTRACTED_REVIEW_READY")
            self.assertEqual(
                design["recommended_next_action"],
                "build_design_survey_flow08_stage4_inputs_from_person_dossier",
            )

    def test_flow08_stage4_jzsc_unresolved_routes_to_public_registry_fallback_not_flow08_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_public_registry_fallback_required(stage4_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            design = _records_by_project(result["manifest"]["evidence_state_table"]["records"])[
                "PROJ-CN-GD-JG2026-11327"
            ]
            self.assertEqual(design["evidence_state"], "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED")
            self.assertEqual(
                design["recommended_next_action"],
                "run_design_survey_natural_resource_or_local_public_registry_fallback",
            )
            jobs = result["manifest"]["adapter_job_table"]["records"]
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11327"
                    and job["job_type"] == "design_survey_public_registry_fallback_plan"
                    and job["recommended_script"] == "scripts/build-design-survey-public-registry-fallback-v1.ps1"
                    for job in jobs
                )
            )

    def test_design_survey_public_registry_fallback_output_advances_to_tasks_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            public_registry_root = root / "public-registry"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_public_registry_fallback_required(stage4_root)
            _write_design_survey_public_registry_fallback(public_registry_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_public_registry_fallback_root=public_registry_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            design = _records_by_project(result["manifest"]["evidence_state_table"]["records"])[
                "PROJ-CN-GD-JG2026-11327"
            ]
            self.assertEqual(design["evidence_state"], "DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY")
            self.assertEqual(
                design["recommended_next_action"],
                "execute_registered_surveyor_public_registry_readback_or_manual_public_snapshot",
            )
            self.assertEqual(design["design_survey_adapter_counts"]["design_survey_public_registry_task_count"], 1)

    def test_design_survey_flow08_attachment_parse_ocr_required_stays_continuable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            flow08_root = root / "design-flow08"
            parse_root = root / "design-flow08-parse"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_flow08_required(stage4_root)
            _write_design_survey_flow08_readback(flow08_root, fetched=True)
            _write_design_survey_flow08_attachment_parse(parse_root, state="TARGET_ATTACHMENT_OCR_REQUIRED")

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_flow08_readback_root=flow08_root,
                design_survey_flow08_attachment_parse_root=parse_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            design = by_project["PROJ-CN-GD-JG2026-11327"]
            self.assertEqual(design["evidence_state"], "DESIGN_SURVEY_FLOW08_TARGET_ATTACHMENT_OCR_REQUIRED")
            self.assertEqual(design["recommended_next_action"], "rerun_design_survey_flow08_target_attachment_parse_with_ocr")
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11327"]["batch_triage_bucket"],
                "CONTINUE_DESIGN_SURVEY_FLOW08_READBACK",
            )
            self.assertTrue(batch_by_project["PROJ-CN-GD-JG2026-11327"]["continue_allowed"])

    def test_design_survey_flow08_attachment_parse_ocr_language_blocker_creates_retry_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            design_plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            flow08_root = root / "design-flow08"
            parse_root = root / "design-flow08-parse"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_design_survey_adapter_plan(design_plan_root)
            _write_design_survey_stage4_flow08_required(stage4_root)
            _write_design_survey_flow08_readback(flow08_root, fetched=True)
            _write_design_survey_flow08_attachment_parse(parse_root, state="TARGET_ATTACHMENT_OCR_LANGUAGE_UNAVAILABLE")

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                design_survey_adapter_plan_root=design_plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_flow08_readback_root=flow08_root,
                design_survey_flow08_attachment_parse_root=parse_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            design = by_project["PROJ-CN-GD-JG2026-11327"]
            self.assertEqual(design["evidence_state"], "D_DESIGN_SURVEY_FLOW08_OCR_RUNTIME_BLOCKED")
            self.assertEqual(design["recommended_next_action"], "install_chinese_ocr_language_pack_or_manual_ocr_readback")
            jobs = result["manifest"]["adapter_job_table"]["records"]
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11327"
                    and job["job_type"] == "design_survey_flow08_ocr_runtime_fix_and_retry"
                    for job in jobs
                )
            )

    def test_data_ggzy_direct_overlap_creates_a_signal_and_release_probe_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_direct_a_signal(p13b_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "A_STRONG_TIME_OVERLAP_SIGNAL_READY")
            self.assertEqual(rqsg2["evidence_grade"], "A_STRONG_SIGNAL")
            self.assertEqual(rqsg2["stage6_fact_package_state"], "A_STRONG_SIGNAL_FACT_PACKAGE_READY")
            self.assertTrue(rqsg2["release_evidence_probe_required"])
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["batch_triage_bucket"],
                "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE",
            )
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["commercial_decision_state"],
                "PROMOTE_TO_STAGE6_FACT_PACKAGE_AND_STAGE7_GOVERNED_PREVIEW",
            )
            self.assertTrue(batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["stage7_commercial_input_allowed"])
            fact_rows = result["manifest"]["stage6_fact_package_readiness_table"]["records"]
            fact = _records_by_project(fact_rows)["PROJ-CN-GD-JG2026-11398-002"]
            self.assertTrue(fact["stage7_commercial_input_allowed"])
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11398-002"
                    and job["job_type"] == "release_evidence_regional_adapter_plan"
                    for job in result["manifest"]["adapter_job_table"]["records"]
                )
            )

    def test_original_notice_overlap_upgrades_backtrace_to_a_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_backtrace_required(p13b_root)
            _write_original_notice_a_signal(original_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "A_STRONG_TIME_OVERLAP_SIGNAL_READY")
            self.assertEqual(rqsg2["evidence_signal_source"], "ORIGINAL_NOTICE_BACKTRACE")
            self.assertIn("project_manager_change_notice", rqsg2["release_evidence_source_targets"])

    def test_multiple_original_notice_roots_are_merged_for_incremental_batch_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            blocked_original_root = root / "original-blocked"
            a_signal_original_root = root / "original-a"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_backtrace_required(p13b_root)
            _write_original_notice_browser_blocked(blocked_original_root)
            _write_original_notice_a_signal(a_signal_original_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=f"{blocked_original_root};{a_signal_original_root}",
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "A_STRONG_TIME_OVERLAP_SIGNAL_READY")
            self.assertEqual(rqsg2["evidence_signal_source"], "ORIGINAL_NOTICE_BACKTRACE")
            self.assertIn(
                "original-blocked",
                result["manifest"]["source_original_notice_backtrace_json"],
            )
            self.assertIn(
                "original-a",
                result["manifest"]["source_original_notice_backtrace_json"],
            )

    def test_partial_live_backtrace_deferred_by_budget_stays_pending_not_d_grade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_two_backtrace_required(p13b_root)
            _write_original_notice_partial_deferred(original_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "P13B_ORIGINAL_BACKTRACE_REQUIRED")
            self.assertEqual(rqsg2["evidence_grade"], "PENDING_ORIGINAL_BACKTRACE")
            self.assertEqual(rqsg2["recommended_next_action"], "continue_p13b_original_notice_backtrace")
            self.assertIn("original_notice_backtrace_budget_deferred_or_incomplete", rqsg2["review_reasons"])
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["batch_triage_bucket"],
                "CONTINUE_ORIGINAL_BACKTRACE",
            )
            self.assertTrue(batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["continue_allowed"])

    def test_browser_readback_blocker_keeps_d_state_retry_reason_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_backtrace_required(p13b_root)
            _write_original_notice_browser_blocked(original_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertEqual(rqsg2["recommended_next_action"], "manual_review_or_retry_blocked_original_notice_backtrace")
            self.assertIn("original_notice_backtrace_blocked_or_source_unsupported", rqsg2["review_reasons"])
            batch_by_project = _records_by_project(result["manifest"]["batch_triage_table"]["records"])
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["batch_triage_bucket"],
                "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            )
            self.assertEqual(
                batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["commercial_decision_state"],
                "KEEP_INTERNAL_REVIEW_OR_MANUAL_RESOLVE",
            )
            self.assertFalse(batch_by_project["PROJ-CN-GD-JG2026-11398-002"]["continue_allowed"])


def _write_stage16_storage(path: Path) -> None:
    candidates = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "project_name": "RQSG2中标候选人公示",
            "source_url": "https://example.test/rqsg2.html",
            "candidate_company": "（主）中国化学工程第六建设有限公司,（成）中国市政工程华北设计研究总院有限公司",
            "primary_responsible_person_name": "曾凡伟",
            "project_manager_name": "曾凡伟",
            "project_manager_certificate_no": "",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-001",
            "project_name": "RQSG1中标候选人公示",
            "source_url": "https://example.test/rqsg1.html",
            "candidate_company": "（主）上海能源建设集团有限公司,（成）上海能源建设工程设计研究有限公司",
            "primary_responsible_person_name": "王杰",
            "project_manager_name": "王杰",
            "project_manager_certificate_no": "22ZEZACJ0034",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "project_name": "规划测绘项目中标候选人公示",
            "source_url": "https://example.test/design.html",
            "candidate_company": "(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司",
            "primary_responsible_person_name": "胡昌华",
            "project_manager_name": "",
            "project_manager_certificate_no": "",
            "engineering_work_lane": "survey_design",
            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
    ]
    closed = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": True,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "REVIEW",
            },
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-001",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        },
    ]
    payload = {
        "operator_actions": {
            "operator-autonomous-opportunity-search-runs": [
                {
                    "object_refs": {
                        "candidate_options_json": json.dumps(candidates, ensure_ascii=False),
                        "closed_loop_results_json": json.dumps(closed, ensure_ascii=False),
                    }
                }
            ]
        }
    }
    _write_json(path, payload)


def _write_company_first_inputs(path: Path) -> None:
    _write_json(
        path,
        {
            "items": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-11398-002",
                    "project_name": "RQSG2中标候选人公示",
                    "candidate_company_name": "中国化学工程第六建设有限公司",
                    "candidate_group_id": "CANDIDATE-GROUP-JG2026-11398-002-COMPANY-FIRST-1",
                    "candidate_group_members": ["中国化学工程第六建设有限公司", "中国市政工程华北设计研究总院有限公司"],
                    "responsible_person_name": "曾凡伟",
                    "certificate_no": "鄂1422014201516008",
                    "person_public_id_optional": "002303160131952780",
                }
            ]
        },
    )


def _write_p13b_backtrace_required(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目",
                        "original_notice_url": "https://example.test/history.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    }
                ],
                "manual_original_url_backtrace_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目",
                        "original_notice_url": "https://example.test/history.html",
                    }
                ],
            }
        },
    )


def _write_p13b_direct_a_signal(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "matched_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目",
                        "historical_project_area_code": "襄阳市",
                        "extracted_period_text": "2025-08-01至2026-08-01",
                        "overlap_signal_state": "OVERLAP_SIGNAL_REVIEW_REQUIRED",
                    }
                ]
            }
        },
    )


def _write_p13b_two_backtrace_required(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目一",
                        "original_notice_url": "https://example.test/history-1.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目二",
                        "original_notice_url": "https://example.test/history-2.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
                ]
            }
        },
    )


def _write_original_notice_a_signal(root: Path) -> None:
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_fetch_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                    }
                ],
                "original_notice_overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "matched_person_names": ["曾凡伟"],
                        "historical_project_area_code": "襄阳市",
                        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED",
                        "release_evidence_probe_triggered": True,
                    }
                ],
                "manual_release_evidence_probe_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "matched_person_names": ["曾凡伟"],
                        "historical_project_area_code": "襄阳市",
                        "release_evidence_source_targets": [
                            "construction_permit",
                            "contract_public_info",
                            "completion_filing",
                            "project_manager_change_notice",
                        ],
                    }
                ],
            }
        },
    )


def _write_original_notice_partial_deferred(root: Path) -> None:
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_fetch_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCH_BLOCKED",
                        "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                        "blocker_taxonomy": ["max_live_original_notices_deferred"],
                    },
                ],
                "original_notice_overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                        "release_evidence_probe_triggered": False,
                    }
                ],
                "manual_release_evidence_probe_table": [],
            }
        },
    )


def _write_original_notice_browser_blocked(root: Path) -> None:
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_fetch_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                    }
                ],
                "original_notice_extraction_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "original_notice_extraction_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                        "blocker_taxonomy": [
                            "original_notice_person_period_not_extracted_review",
                            "original_notice_browser_readback_required",
                        ],
                    }
                ],
                "original_notice_overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                        "release_evidence_probe_triggered": False,
                    }
                ],
                "manual_release_evidence_probe_table": [],
            }
        },
    )


def _write_design_survey_adapter_plan(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    companies = ["广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"]
    stage4_items = [
        {
            "stage4_input_id": f"DESIGN-SURVEY-STAGE4-{index}",
            "project_id": project_id,
            "project_name": "规划测绘项目中标候选人公示",
            "candidate_company_name": company,
            "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
            "candidate_group_order": str(index),
            "candidate_group_members": companies,
            "candidate_group_match_mode": "ANY_CONSORTIUM_MEMBER",
            "consortium_member_role": "lead" if index == 1 else "member",
            "responsible_person_name": "胡昌华",
            "responsible_role": "survey_design_project_lead",
            "certificate_no": "",
            "person_public_id_optional": "",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for index, company in enumerate(companies, start=1)
    ]
    _write_json(
        root / "design-survey-responsible-adapter-plan-v1.json",
        {
            "manifest": {
                "project_table": {
                    "records": [
                        {
                            "design_survey_project_id": "DESIGN-SURVEY-PROJECT-1",
                            "project_id": project_id,
                            "project_name": "规划测绘项目中标候选人公示",
                            "candidate_group_members": companies,
                            "responsible_person_name": "胡昌华",
                            "responsible_role": "survey_design_project_lead",
                            "engineering_work_lane": "survey_design",
                            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
                            "adapter_readiness_state": "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN",
                            "review_reasons": [],
                            "customer_visible_allowed": False,
                            "no_legal_conclusion": True,
                        }
                    ]
                },
                "stage4_candidate_verification_inputs": {
                    "items": stage4_items,
                    "summary": {"stage4_input_count": len(stage4_items)},
                },
                "design_survey_verification_task_table": {
                    "records": [
                        {
                            "design_survey_verification_task_id": "DESIGN-SURVEY-TASK-1",
                            "project_id": project_id,
                            "task_type": "DESIGN_SURVEY_PERSON_COMPANY_CERTIFICATE_MATCH",
                            "execution_state": "PLAN_ONLY_NOT_EXECUTED",
                        },
                        {
                            "design_survey_verification_task_id": "DESIGN-SURVEY-TASK-2",
                            "project_id": project_id,
                            "task_type": "CURRENT_PROJECT_DESIGN_SURVEY_SERVICE_CLOCK",
                            "execution_state": "PLAN_ONLY_NOT_EXECUTED",
                        },
                    ]
                },
            }
        },
    )


def _write_design_survey_stage4_execution(root: Path, *, resolved: bool) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    companies = ["广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"]
    if resolved:
        items = [
            {
                "job_id": "STAGE4-INPUT-JOB-1",
                "project_id": project_id,
                "candidate_company_name": companies[0],
                "responsible_person_name": "胡昌华",
                "certificate_no": "粤测绘-001",
                "person_public_id_optional": "DESIGN-PERSON-001",
                "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
                "stage4_execution_state": "EXECUTED",
                "identity_resolution_state": "MATCHED_PERSON_COMPANY",
                "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
                "candidate_group_resolution_state": "RESOLVED_BY_THIS_MEMBER",
                "fail_closed_reasons": [],
            },
            {
                "job_id": "STAGE4-INPUT-JOB-2",
                "project_id": project_id,
                "candidate_company_name": companies[1],
                "responsible_person_name": "胡昌华",
                "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
                "stage4_execution_state": "EXECUTED",
                "identity_resolution_state": "GROUP_ALREADY_RESOLVED",
                "supplement_after_execution_state": "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED",
                "candidate_group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER",
                "fail_closed_reasons": [],
            },
        ]
    else:
        items = [
            {
                "job_id": f"STAGE4-INPUT-JOB-{index}",
                "project_id": project_id,
                "candidate_company_name": company,
                "responsible_person_name": "胡昌华",
                "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
                "stage4_execution_state": "QUEUED_NOT_EXECUTED",
                "identity_resolution_state": "NOT_RUN",
                "supplement_after_execution_state": "COMPANY_FIRST_PROVIDER_TASKS_READY",
                "candidate_group_resolution_state": "PENDING_EXECUTION",
                "fail_closed_reasons": [],
            }
            for index, company in enumerate(companies, start=1)
        ]
    _write_json(
        root / "company-first-stage4-execution.json",
        {
            "manifest": {
                "items": items,
                "stage4_candidate_verification_inputs": {"items": []},
                "summary": {
                    "project_count": 1,
                    "job_count": len(items),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
            }
        },
    )


def _write_design_survey_stage4_flow08_required(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    companies = ["广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"]
    items = [
        {
            "job_id": f"STAGE4-INPUT-JOB-{index}",
            "project_id": project_id,
            "candidate_company_name": company,
            "responsible_person_name": "胡昌华",
            "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
            "candidate_group_members": companies,
            "stage4_execution_state": "FAIL_CLOSED",
            "identity_resolution_state": "NO_MATCH",
            "supplement_after_execution_state": "FLOW_08_TARGETED_PARSE_REQUIRED",
            "flow_08_targeted_parse_required": True,
            "candidate_group_resolution_state": "UNRESOLVED_NO_MEMBER_MATCHED",
            "fail_closed_reasons": ["project_manager_not_found_by_company_name_person_name_after_1_attempts"],
        }
        for index, company in enumerate(companies, start=1)
    ]
    _write_json(
        root / "company-first-stage4-execution.json",
        {
            "manifest": {
                "items": items,
                "stage4_candidate_verification_inputs": {"items": []},
                "summary": {"project_count": 1, "job_count": len(items)},
            }
        },
    )


def _write_design_survey_stage4_public_registry_fallback_required(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    items = [
        {
            "job_id": "STAGE4-FLOW08-INPUT-JOB-1",
            "project_id": project_id,
            "candidate_company_name": "广州市城市规划勘测设计研究院有限公司",
            "responsible_person_name": "胡昌华",
            "candidate_group_id": "CANDIDATE-GROUP-JG2026-11327-DESIGN-SURVEY-1",
            "source_probe_adapter_id": "design-survey-flow08-stage4-inputs-v1",
            "stage4_execution_state": "FAIL_CLOSED",
            "identity_resolution_state": "UNKNOWN",
            "supplement_after_execution_state": "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
            "flow_08_targeted_parse_required": False,
            "candidate_group_resolution_state": "UNRESOLVED_NO_MEMBER_MATCHED",
            "fail_closed_reasons": ["project_manager_not_found_by_company_name_person_name_after_1_attempts"],
        }
    ]
    _write_json(
        root / "company-first-stage4-execution.json",
        {
            "manifest": {
                "items": items,
                "stage4_candidate_verification_inputs": {"items": []},
                "summary": {"project_count": 1, "job_count": len(items)},
            }
        },
    )


def _write_design_survey_flow08_readback(root: Path, *, fetched: bool) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    state = "FLOW08_TARGET_ATTACHMENT_FETCHED" if fetched else "FLOW08_TARGET_ATTACHMENT_BOUND_DOWNLOAD_DEFERRED"
    attachment_fetch_state = "FETCHED" if fetched else ""
    attachment = {
        "project_id": project_id,
        "target_attachment_match_state": "TARGET_CANDIDATE_ATTACHMENT_BOUND",
        "attachment_fetch_state": attachment_fetch_state,
        "attachment_url": "https://jsgc.gzggzy.cn/download?AttachGuid=union",
    }
    _write_json(
        root / "design-survey-flow08-targeted-readback-v1.json",
        {
            "manifest": {
                "flow08_targeted_readback_table": {
                    "records": [
                        {
                            "project_id": project_id,
                            "flow08_readback_state": state,
                            "target_attachment_match_state": "TARGET_CANDIDATE_ATTACHMENT_BOUND",
                            "target_attachment_records": [attachment],
                        }
                    ]
                },
                "target_attachment_table": {"records": [attachment]},
            }
        },
    )


def _write_design_survey_flow08_attachment_parse(root: Path, *, state: str) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    record = {
        "target_attachment_parse_id": "DESIGN-SURVEY-FLOW08-PARSE-1",
        "target_attachment_id": "DESIGN-SURVEY-FLOW08-ATTACH-1",
        "project_id": project_id,
        "project_name": "规划测绘项目中标候选人公示",
        "candidate_company_text": "(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司",
        "responsible_person_name": "胡昌华",
        "attachment_url": "https://jsgc.gzggzy.cn/download?AttachGuid=union",
        "attachment_snapshot_id_optional": "SNAP-ATTACH",
        "attachment_parse_state": state,
        "extracted_fields": {
            "extraction_state": "FIELDS_EXTRACTED"
            if state == "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
            else "NO_RESPONSIBLE_PERSON_FIELD_FOUND",
            "primary_responsible_person_name": "胡昌华"
            if state == "TARGET_ATTACHMENT_TEXT_FIELDS_EXTRACTED"
            else "",
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_json(
        root / "design-survey-flow08-target-attachment-parse-v1.json",
        {
            "manifest": {
                "target_attachment_parse_table": {
                    "records": [record],
                    "summary": {
                        "target_attachment_parse_record_count": 1,
                        "attachment_parse_state_counts": {state: 1},
                    },
                }
            }
        },
    )


def _write_design_survey_public_registry_fallback(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    task = {
        "public_registry_task_id": "DESIGN-SURVEY-PUBLIC-REG-TASK-1",
        "project_id": project_id,
        "project_name": "规划测绘项目中标候选人公示",
        "candidate_company_name": "广州市城市规划勘测设计研究院有限公司",
        "responsible_person_name": "胡昌华",
        "task_type": "NATURAL_RESOURCE_REGISTERED_SURVEYOR_PERSON_COMPANY_MATCH",
        "task_state": "PLAN_ONLY_ENTRY_NEEDS_LIVE_VERIFY",
        "provider_id": "NATURAL_RESOURCE_REGISTERED_SURVEYOR",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    target = {
        "public_registry_target_id": "DESIGN-SURVEY-PUBLIC-REG-TARGET-1",
        "project_id": project_id,
        "project_name": "规划测绘项目中标候选人公示",
        "candidate_company_name": "广州市城市规划勘测设计研究院有限公司",
        "responsible_person_name": "胡昌华",
        "target_readiness_state": "READY_FOR_REGISTERED_SURVEYOR_PUBLIC_REGISTRY",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_json(
        root / "design-survey-public-registry-fallback-v1.json",
        {
            "manifest": {
                "public_registry_target_table": {
                    "records": [target],
                    "summary": {"target_record_count": 1},
                },
                "public_registry_task_table": {
                    "records": [task],
                    "summary": {"task_count": 1},
                },
                "stage4_provider_jobs": {
                    "jobs": [
                        {
                            "job_id": "STAGE4-PUBLIC-REG-JOB-1",
                            "provider_id": "NATURAL_RESOURCE_REGISTERED_SURVEYOR",
                            "payload": {"source_probe_item": {"project_id": project_id}},
                            "status": "QUEUED_NOT_EXECUTED",
                        }
                    ]
                },
            }
        },
    )


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
