from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.document_extraction import extract_document_text, extract_responsible_person_fields
from stage4_verification.local_job_queue import EXHAUSTED, Stage4LocalJobQueue
from stage4_verification.provider_handlers import (
    PENDING_IMPLEMENTATION_REVIEW,
    build_stage4_provider_handlers,
    run_jzsc_identity_provider_task,
)
from stage4_verification.provider_registry import (
    CONSTRUCTION_PERMIT,
    JZSC_PERSON_IDENTITY,
    PROJECT_MANAGER_CHANGE,
    SUPPLIER_QUALIFICATION_CREDIT,
    GUANGDONG_THREE_LIBRARY,
    build_stage4_provider_plan,
)
from stage4_verification.service import Stage4Service


class Stage4ProviderQueueDocumentToolsTests(unittest.TestCase):
    def test_provider_plan_routes_construction_to_identity_and_local_conflict_sources(self) -> None:
        plan = build_stage4_provider_plan(
            opportunity_priority_class="A_HIGH_CONSTRUCTION_EPC",
            candidate_company_name="广东测试建设有限公司",
            responsible_person_name="张三",
            certificate_no="粤244202520260001",
        )

        provider_ids = [task["provider_id"] for task in plan["tasks"]]
        self.assertEqual(provider_ids[0], JZSC_PERSON_IDENTITY)
        self.assertIn(CONSTRUCTION_PERMIT, provider_ids)
        self.assertIn(PROJECT_MANAGER_CHANGE, provider_ids)
        self.assertFalse(plan["policy"]["jzsc_project_records_used_for_performance_conflict"])
        self.assertTrue(plan["policy"]["not_found_is_review_not_negative_fact"])

    def test_provider_plan_routes_supplier_class_away_from_project_manager_conflict(self) -> None:
        plan = build_stage4_provider_plan(
            opportunity_priority_class="D_LOW_SUPPLIER_SERVICE",
            candidate_company_name="广东测试设备有限公司",
        )

        provider_ids = [task["provider_id"] for task in plan["tasks"]]
        self.assertEqual(provider_ids, ["PENALTY_CREDIT", SUPPLIER_QUALIFICATION_CREDIT])
        self.assertTrue(all(not task["use_for_performance_conflict"] for task in plan["tasks"]))

    def test_local_job_queue_runs_handler_and_exhausts_missing_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            queue = Stage4LocalJobQueue(Path(tmp_dir) / "jobs.json")
            ok_job = queue.enqueue(
                provider_id=JZSC_PERSON_IDENTITY,
                payload={"target": {"candidate_company_name": "Alpha"}},
                max_attempts=2,
            )
            missing_job = queue.enqueue(
                provider_id="MISSING_PROVIDER",
                payload={"target": {"candidate_company_name": "Beta"}},
                max_attempts=2,
            )

            result = queue.run_due_jobs(
                {
                    JZSC_PERSON_IDENTITY: lambda payload: {
                        "verification_result": "MATCHED",
                        "payload": dict(payload),
                    }
                },
                limit=5,
            )

            jobs = {job["job_id"]: job for job in queue.list_jobs()}
            self.assertEqual(result["processed_count"], 2)
            self.assertEqual(jobs[ok_job["job_id"]]["status"], "SUCCEEDED")
            self.assertEqual(jobs[missing_job["job_id"]]["status"], EXHAUSTED)

    def test_jzsc_provider_handler_reuses_matched_stage4_record_without_project_conflict(self) -> None:
        result = run_jzsc_identity_provider_task(
            {
                "provider_id": JZSC_PERSON_IDENTITY,
                "provider_role": "person_company_certificate_identity",
                "target": {
                    "candidate_company_name": "广州市第四装修有限公司",
                    "responsible_person_name": "刘菊花",
                },
                "source_stage4_jzsc_record": {
                    "idx": 8,
                    "type": "A_HIGH_CONSTRUCTION_EPC",
                    "title": "测试工程施工中标候选人公示",
                    "notice_url": "https://example.invalid/notice.html",
                    "normalized_stage4_outcome": "JZSC_PERSON_COMPANY_CERT_MATCHED",
                    "matched_company_name": "广州市第四装修有限公司",
                    "matched_company_public_id": "002105291321970990",
                    "jzsc_registered_unit": "广州市第四装修有限公司",
                    "jzsc_certificate_no": "粤2442015201504119",
                    "person_public_id": "002303160128481746",
                    "personnel_detail_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=002303160128481746",
                    "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/person",
                },
            }
        )

        self.assertEqual(result["verification_result"], "MATCHED")
        self.assertEqual(result["identity_fields"]["certificate_no"], "粤2442015201504119")
        self.assertFalse(result["policy"]["use_for_performance_conflict"])
        self.assertFalse(result["customer_sellable_evidence_ready"])

    def test_default_provider_handlers_do_not_fake_local_source_success_without_live_opt_in(self) -> None:
        handlers = build_stage4_provider_handlers()
        result = handlers[GUANGDONG_THREE_LIBRARY](
            {
                "provider_id": GUANGDONG_THREE_LIBRARY,
                "target": {
                    "candidate_company_name": "广东测试建设有限公司",
                    "responsible_person_name": "张三",
                },
            }
        )

        self.assertEqual(result["provider_result_state"], PENDING_IMPLEMENTATION_REVIEW)
        self.assertEqual(result["verification_result"], "REVIEW_REQUIRED")
        self.assertIn("live_gdcic_adapter_not_enabled", result["review_reasons"])

    def test_gdcic_provider_handler_can_use_authorized_http_getter_when_enabled(self) -> None:
        def fake_get_json(url: str, params: dict[str, str]) -> dict[str, object]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            if endpoint == "/openplatform/project/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [
                        {
                            "projectName": "广东市政道路工程",
                            "projectCode": "4401002605010001",
                        }
                    ],
                }
            if endpoint == "/openplatform/memberInvolvedProject/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [
                        {
                            "projectName": "广东市政道路工程",
                            "projectCode": params.get("projectCode"),
                            "memberName": "张三",
                            "orgName": "广东测试建设有限公司",
                            "position": "项目经理",
                        }
                    ],
                }
            return {"msg": "success", "code": 0, "total": 0, "rows": []}

        handlers = build_stage4_provider_handlers(
            enable_live_gdcic=True,
            http_get_json=fake_get_json,
        )
        result = handlers[GUANGDONG_THREE_LIBRARY](
            {
                "provider_id": GUANGDONG_THREE_LIBRARY,
                "target": {
                    "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
                    "candidate_company_name": "广东测试建设有限公司",
                    "responsible_person_name": "张三",
                },
                "source_stage4_jzsc_record": {
                    "idx": 1,
                    "type": "A_HIGH_CONSTRUCTION_EPC",
                    "title": "广东市政道路工程中标候选人公示",
                    "notice_url": "https://example.invalid/notice.html",
                },
            }
        )

        self.assertEqual(result["verification_result"], "MATCHED")
        self.assertEqual(
            result["responsible_role_identity_completion"]["completion_state"],
            "RESPONSIBLE_ROLE_CANDIDATE_FOUND",
        )

    def test_document_text_field_extraction_finds_role_name_and_certificate(self) -> None:
        fields = extract_responsible_person_fields(
            "拟派项目经理：陈丽丽 二级建造师注册证书（市政公用工程）/粤244202520260001",
            opportunity_priority_class="A_HIGH_CONSTRUCTION_EPC",
        )

        self.assertEqual(fields["extraction_state"], "FIELDS_EXTRACTED")
        self.assertEqual(fields["primary_responsible_person_name"], "陈丽丽")
        self.assertEqual(fields["primary_responsible_role"], "project_manager_name")
        self.assertIn("244202520260001", fields["primary_certificate_no_optional"])

    def test_suffixless_pdf_snapshot_is_detected_by_magic_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "content-addressed-object"
            path.write_bytes(b"%PDF-1.4\n% suffixless test object\n")

            result = extract_document_text(path, max_pages=1)

            self.assertNotIn("unsupported_document_suffix:<none>", result["failure_reasons"])
            self.assertTrue(any("pymupdf" in reason or "pdfplumber" in reason for reason in result["failure_reasons"]))

    def test_stage4_service_exposes_provider_plan_and_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = Stage4Service()
            plan = service.build_stage4_provider_plan(
                opportunity_priority_class="B_HIGH_SUPERVISION",
                candidate_company_name="广东监理有限公司",
                responsible_person_name="李四",
            )
            queued = service.enqueue_stage4_provider_plan_jobs(
                plan,
                queue_path=str(Path(tmp_dir) / "jobs.json"),
                max_attempts=5,
            )

            self.assertGreaterEqual(len(plan["tasks"]), 1)
            self.assertEqual(queued["enqueued_count"], len(plan["tasks"]))
            self.assertTrue(Path(queued["queue_path"]).exists())

    def test_stage4_service_runs_default_provider_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = Stage4Service()
            queue_path = str(Path(tmp_dir) / "jobs.json")
            plan = service.build_stage4_provider_plan(
                opportunity_priority_class="A_HIGH_CONSTRUCTION_EPC",
                candidate_company_name="广东测试建设有限公司",
                responsible_person_name="张三",
            )
            service.enqueue_stage4_provider_plan_jobs(plan, queue_path=queue_path)
            result = service.run_stage4_local_provider_jobs(queue_path=queue_path, limit=20)

            self.assertGreaterEqual(result["processed_count"], 1)
            self.assertTrue(
                all(job["status"] == "SUCCEEDED" for job in result["processed_jobs"])
            )


if __name__ == "__main__":
    unittest.main()
