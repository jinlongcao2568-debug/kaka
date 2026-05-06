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

from stage4_verification.guangzhou_stage4_review_matrix import (  # noqa: E402
    PRIORITY_REVIEW_IDXS,
    build_review_matrices,
    write_review_outputs,
)


ALL_IDXS = (1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18, 21, 23, 24, 26, 27, 28, 29)


def _trace_record(idx: int) -> dict[str, Any]:
    title = f"测试项目{idx}中标候选人公示"
    priority_class = "A_HIGH_CONSTRUCTION_EPC"
    if idx == 4:
        title = "测试项目4中标候选人及中标结果公示"
    if idx in (1, 21, 28):
        priority_class = "C_MEDIUM_DESIGN_SURVEY"
    return {
        "idx": idx,
        "type": priority_class,
        "type_label": "A 施工/EPC" if priority_class.startswith("A_") else "C 设计/勘察",
        "engineering_work_lane": "construction_or_epc" if priority_class.startswith("A_") else "survey_design",
        "title": title,
        "url": f"https://example.invalid/{idx}.html",
        "company": f"测试公司{idx}",
        "responsible_person": f"人员{idx}",
        "certificate_no": f"证书{idx}" if idx in (2, 9, 13, 16, 21, 28) else "",
        "source_dataset_name": "中标候选人公示",
        "source_trading_process": "03",
        "responsible_role_required": True,
        "attachment_link_count": 2,
        "attachment_snapshot_count": 0,
        "attachment_capture_statuses": {"DEGRADED": 2},
        "attachment_items": [
            {"name": "评标报告.pdf"},
            {"name": "中标候选人公示.pdf"},
        ],
    }


def _stage4_record(idx: int) -> dict[str, Any]:
    outcome = "JZSC_PERSON_COMPANY_CERT_MATCHED"
    if idx in (1, 2, 3, 4, 5, 7, 9, 13, 16):
        outcome = "COMPANY_MATCHED_PERSON_NOT_FOUND_REVIEW"
    if idx in (21, 28):
        outcome = "PERSON_FOUND_BUT_IDENTITY_REVIEW"
    return {
        "idx": idx,
        "type": _trace_record(idx)["type"],
        "title": _trace_record(idx)["title"],
        "notice_url": f"https://example.invalid/{idx}.html",
        "candidate_company": f"测试公司{idx}",
        "responsible_person": f"人员{idx}",
        "announcement_certificate_no": _trace_record(idx)["certificate_no"],
        "normalized_stage4_outcome": outcome,
        "matched_company_name": f"测试公司{idx}",
        "matched_company_public_id": f"QY{idx:03d}",
        "fail_closed_reasons": (
            ["project_manager_not_found_by_company_name_person_name_after_5_attempts"]
            if outcome == "COMPANY_MATCHED_PERSON_NOT_FOUND_REVIEW"
            else []
        ),
    }


def _job(
    idx: int,
    provider_id: str,
    *,
    verification: str = "REVIEW_REQUIRED",
    state: str = "READBACK_READY",
    review_reasons: list[str] | None = None,
    failure_reasons: list[str] | None = None,
    relevant_source_results: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "job_id": f"JOB-{idx}-{provider_id}",
        "provider_id": provider_id,
        "payload": {"provider_id": provider_id, "source_trace_record_idx": idx},
        "status": "SUCCEEDED",
        "result": {
            "provider_id": provider_id,
            "provider_result_state": state,
            "verification_result": verification,
            "review_reasons": review_reasons or [],
            "failure_reasons": failure_reasons or [],
            "relevant_source_results": list(relevant_source_results or []),
            "customer_sellable_evidence_ready": False,
        },
    }


def _fixture_payloads() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    trace = {"rows": [_trace_record(idx) for idx in ALL_IDXS]}
    merged = {"records": [_stage4_record(idx) for idx in ALL_IDXS]}
    retry = {"records": [_stage4_record(idx) for idx in PRIORITY_REVIEW_IDXS]}
    jobs: list[dict[str, Any]] = []
    for idx in ALL_IDXS:
        stage4 = _stage4_record(idx)
        jzsc_verification = (
            "MATCHED"
            if stage4["normalized_stage4_outcome"] == "JZSC_PERSON_COMPANY_CERT_MATCHED"
            else "REVIEW_REQUIRED"
        )
        jobs.append(_job(idx, "JZSC_PERSON_IDENTITY", verification=jzsc_verification))
        jobs.append(
            _job(
                idx,
                "GUANGDONG_THREE_LIBRARY",
                failure_reasons=["gdcic_project_code_not_resolved"],
            )
        )
        jobs.append(
            _job(
                idx,
                "LOCAL_HOUSING_CONSTRUCTION",
                state="PENDING_IMPLEMENTATION_REVIEW",
                review_reasons=["local_housing_construction_runtime_adapter_not_implemented"],
            )
        )
        if _trace_record(idx)["type"].startswith("A_"):
            jobs.append(
                _job(
                    idx,
                    "PROJECT_MANAGER_CHANGE",
                    state="PENDING_IMPLEMENTATION_REVIEW",
                    review_reasons=["project_manager_change_notice_runtime_adapter_not_implemented"],
                )
            )
    jobs.append(
        _job(
            4,
            "PENALTY_CREDIT",
            verification="PUBLIC_RECORD_FOUND_REVIEW",
            relevant_source_results=[
                {
                    "source_type": "complaint_or_supervision_decision",
                    "coverage_state": "COVERED",
                    "source_url": "https://example.invalid/risk",
                    "matched_records_preview": [
                        {
                            "id": "2041",
                            "projectName": "梅州市中医医院(田家炳医院)门诊综合大楼工程",
                            "entName": "广东省第一建筑工程有限公司",
                            "happenTime": "2021-08-04",
                            "publishTime": "2021-09-03",
                        }
                    ],
                }
            ],
        )
    )
    queue = {"jobs": jobs}
    return trace, merged, retry, queue


class GuangzhouStage4ReviewMatrixTests(unittest.TestCase):
    def test_builds_11_review_rows_and_22_blocker_rows(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()

        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        self.assertEqual(len(payloads["review_11"]["records"]), 11)
        self.assertEqual(len(payloads["blocker_22"]["records"]), 22)

        record_1 = next(record for record in payloads["review_11"]["records"] if record["idx"] == 1)
        self.assertEqual(
            record_1["candidate_scope_state"],
            "CANDIDATES_ONLY_FINAL_WINNER_NOT_CONFIRMED",
        )
        self.assertIn("JZSC_PERSON_IDENTITY_NOT_CLOSED", record_1["blocker_attribution"])
        self.assertIn("SYSTEM_GAP_RUNTIME_ADAPTER_NOT_IMPLEMENTED", record_1["blocker_attribution"])
        self.assertNotIn("SYSTEM_GAP_PROJECT_CODE_RESOLUTION", record_1["blocker_attribution"])
        self.assertEqual(
            record_1["gdcic_status"]["provider_applicability_state"],
            "APPLICABLE_IDENTITY_ONLY_PROJECT_RECORD_NOT_EXPECTED_YET_REVIEW",
        )
        self.assertEqual(
            record_1["project_manager_change_status"]["provider_applicability_state"],
            "NOT_EXPECTED_YET_REVIEW",
        )
        self.assertEqual(
            record_1["responsible_qualification_requirement_state"],
            "DESIGN_SURVEY_QUALIFICATION_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED",
        )

        record_4 = next(record for record in payloads["review_11"]["records"] if record["idx"] == 4)
        self.assertEqual(record_4["candidate_scope_state"], "CANDIDATE_AND_RESULT_PUBLICATION")
        self.assertIn("ENTERPRISE_RISK_PUBLIC_RECORD_REVIEW", record_4["blocker_attribution"])
        self.assertEqual(
            record_4["enterprise_risk_public_records"][0]["project_name"],
            "梅州市中医医院(田家炳医院)门诊综合大楼工程",
        )

    def test_extracts_method_from_available_text_without_using_attachment_names(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()
        trace["rows"][0]["evaluation_method"] = "综合评估法"
        trace["rows"][0]["determination_method"] = "评定分离"

        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        record = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 1)
        self.assertEqual(record["evaluation_method"], "综合评估法")
        self.assertEqual(record["determination_method"], "评定分离")

        record_2 = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 2)
        self.assertEqual(
            record_2["evaluation_method_state"],
            "ATTACHMENT_TEXT_NOT_AVAILABLE_REVIEW_REQUIRED",
        )

    def test_writes_outputs_and_markdown_uses_review_only_wording(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()
        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_review_outputs(
                review_payload=payloads["review_11"],
                blocker_payload=payloads["blocker_22"],
                review_jsonl=root / "review.jsonl",
                review_summary_json=root / "review.summary.json",
                review_markdown=root / "review.md",
                blocker_jsonl=root / "blocker.jsonl",
                blocker_summary_json=root / "blocker.summary.json",
                blocker_markdown=root / "blocker.md",
            )

            self.assertEqual(len((root / "review.jsonl").read_text(encoding="utf-8").splitlines()), 11)
            self.assertEqual(len((root / "blocker.jsonl").read_text(encoding="utf-8").splitlines()), 22)
            self.assertEqual(
                json.loads((root / "review.summary.json").read_text(encoding="utf-8"))["record_count"],
                11,
            )
            markdown = (root / "review.md").read_text(encoding="utf-8")
            for term in ("造假", "违法", "围标", "废标"):
                self.assertNotIn(term, markdown)
            self.assertIn("REVIEW 只进入内部复核", markdown)

    def test_runtime_adapter_gap_disappears_after_provider_is_wired(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()
        for job in queue["jobs"]:
            if job["provider_id"] in {"LOCAL_HOUSING_CONSTRUCTION", "PROJECT_MANAGER_CHANGE"}:
                job["result"]["provider_result_state"] = "READBACK_READY"
                job["result"]["review_reasons"] = [
                    f"{job['provider_id'].lower()}_public_record_not_matched_review"
                ]

        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        record = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 2)
        self.assertNotIn(
            "SYSTEM_GAP_RUNTIME_ADAPTER_NOT_IMPLEMENTED",
            record["blocker_attribution"],
        )
        self.assertIn("LOCAL_HOUSING_CONSTRUCTION_REVIEW_REQUIRED", record["blocker_attribution"])

    def test_gdcic_project_code_failures_are_classified(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()
        trace["rows"][1]["project_code"] = "GD-PROJECT-002"
        for job in queue["jobs"]:
            if job["provider_id"] == "GUANGDONG_THREE_LIBRARY" and job["payload"]["source_trace_record_idx"] == 2:
                job["result"]["failure_reasons"] = [
                    "gdcic_project_code_not_resolved",
                    "gdcic_project_code_not_resolved_after_project_name_candidate_queries",
                    "gdcic_project_lookup_empty_result",
                    "project_code_missing_from_query_context",
                ]

        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        record = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 2)
        self.assertIn("SYSTEM_GAP_PROJECT_CODE_RESOLUTION", record["blocker_attribution"])
        self.assertIn(
            "GDCIC_PROJECT_CODE_TITLE_CANDIDATES_NOT_MATCHED",
            record["blocker_attribution"],
        )
        self.assertIn("GDCIC_PROJECT_CODE_LOOKUP_EMPTY_RESULT", record["blocker_attribution"])
        self.assertIn(
            "GDCIC_PROJECT_CODE_MISSING_FROM_QUERY_CONTEXT",
            record["blocker_attribution"],
        )

    def test_certificate_requirement_routes_design_and_title_without_constructor_default(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()
        trace["rows"][0]["project_manager_certificate_type"] = "注册土木工程师（岩土）"
        trace["rows"][0]["project_manager_cert_specialty"] = "岩土"
        trace["rows"][20]["project_manager_professional_title"] = "高级工程师"

        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        record_1 = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 1)
        self.assertEqual(record_1["required_certificate_type"], "注册土木工程师（岩土）")
        self.assertEqual(record_1["required_specialty"], "岩土")
        self.assertEqual(record_1["certificate_verification_route"], "REGISTERED_ENGINEER_ROUTE_REVIEW_REQUIRED")
        self.assertIn("REGISTERED_ENGINEER_ROUTE_REVIEW_REQUIRED", record_1["blocker_attribution"])

        record_28 = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 28)
        self.assertEqual(record_28["required_title"], "高级工程师")
        self.assertEqual(record_28["certificate_verification_route"], "PROFESSIONAL_TITLE_REVIEW_REQUIRED")
        self.assertIn("PROFESSIONAL_TITLE_REVIEW_REQUIRED", record_28["blocker_attribution"])

    def test_attachment_qualification_blocks_clear_attachment_and_certificate_requirement_gaps(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()
        trace["rows"][0]["attachment_text_merge_state"] = "ATTACHMENT_TEXT_MERGED"
        trace["rows"][0]["attachment_text_parse_states"] = ["SNAP-1:WORD_DOCX:PARSED"]
        trace["rows"][0]["qualification_text_candidate_blocks"] = [
            "勘察负责人须具有注册土木工程师（岩土）资格，专业为岩土工程"
        ]

        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        record = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 1)
        self.assertEqual(record["attachment_text_state"], "ATTACHMENT_TEXT_AVAILABLE_FOR_EXTRACTION")
        self.assertEqual(record["required_certificate_type"], "注册土木工程师（岩土）")
        self.assertEqual(record["required_specialty"], "岩土")
        self.assertNotIn("ATTACHMENT_TEXT_NOT_AVAILABLE_REVIEW_REQUIRED", record["blocker_attribution"])
        self.assertNotIn("CERTIFICATE_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED", record["blocker_attribution"])

    def test_attachment_blocked_parse_state_is_specific_blocker(self) -> None:
        trace, merged, retry, queue = _fixture_payloads()
        trace["rows"][0]["attachment_text_merge_state"] = "ATTACHMENT_TEXT_NOT_EXTRACTED"
        trace["rows"][0]["attachment_text_parse_states"] = [
            "NO_SNAPSHOT:DEGRADED:CAPTCHA_MANUAL_REQUIRED"
        ]

        payloads = build_review_matrices(
            trace_payload=trace,
            merged_stage4_payload=merged,
            retry_stage4_payload=retry,
            provider_queue_payload=queue,
            generated_at="2026-05-06T00:00:00+00:00",
        )

        record = next(item for item in payloads["blocker_22"]["records"] if item["idx"] == 1)
        self.assertIn("ATTACHMENT_TEXT_NOT_AVAILABLE_REVIEW_REQUIRED", record["blocker_attribution"])
        self.assertIn(
            "ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED:CAPTCHA_MANUAL_REQUIRED",
            record["blocker_attribution"],
        )


if __name__ == "__main__":
    unittest.main()
