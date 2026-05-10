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

from storage.guangzhou_post_candidate_acceptance_report import (  # noqa: E402
    PARTIAL_REVIEW_REQUIRED,
    SAMPLE_READY,
    build_guangzhou_post_candidate_acceptance_report,
)


CONTRACT_PATH = ROOT / "contracts" / "evaluation" / "guangzhou_12_flow_golden_projects.json"


class TestGuangzhouPostCandidateAcceptanceReport(unittest.TestCase):
    def test_acceptance_report_enforces_jg2026_10815_golden_flow_counts(self) -> None:
        contract = _load_contract()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(
                root,
                audit_items=[
                    _golden_project_audit(contract),
                    *[_ordinary_project_audit(index) for index in range(2, 21)],
                ],
                challenge_failed_count=0,
            )

            result = build_guangzhou_post_candidate_acceptance_report(
                output_root=root,
                golden_contract_json=CONTRACT_PATH,
                created_at="2026-05-10T00:00:00+08:00",
            )

        self.assertEqual(result["summary"]["batch_acceptance_state"], SAMPLE_READY)
        self.assertTrue(result["summary"]["golden_acceptance_passed"])
        golden = result["manifest"]["golden_project_results"][0]
        self.assertEqual(golden["golden_acceptance_state"], "GOLDEN_ACCEPTED")
        self.assertEqual(golden["failed_assertions"], [])
        project = next(
            item
            for item in result["manifest"]["project_reports"]
            if item["project_id"] == "PROJ-CN-GD-JG2026-10815"
        )
        by_flow = {item["flow_no"]: item for item in project["flow_matrix"]}
        self.assertEqual(by_flow["03"]["detail_count"], 2)
        self.assertEqual(by_flow["03"]["attachment_count"], 20)
        self.assertEqual(by_flow["05"]["detail_count"], 1)
        self.assertEqual(by_flow["06"]["attachment_count"], 2)
        self.assertEqual(by_flow["08"]["attachment_count"], 3)
        self.assertIn(
            "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260510/63ed1d0a-cf91-4c8c-ba5f-cb4b74176e7a_tb.html",
            project["verification_urls"]["all_urls"],
        )
        self.assertTrue(project["per_project_file_inventory"])
        self.assertFalse(result["manifest"]["customer_visible_allowed"])

    def test_missing_flow_and_challenge_failure_are_manual_review_signals(self) -> None:
        contract = _load_contract()
        broken = _golden_project_audit(contract)
        broken["guangzhou_flow_inventory"] = [
            item
            for item in broken["guangzhou_flow_inventory"]
            if item["flow_no"] not in {"05", "08"}
        ]
        broken["guangzhou_flow_modules_present"] = [
            item
            for item in broken["guangzhou_flow_modules_present"]
            if item["flow_no"] not in {"05", "08"}
        ]
        broken["guangzhou_flow_modules_missing"].extend(
            [
                {"flow_no": "05", "flow_title": "开标信息", "document_kind": "opening_info"},
                {
                    "flow_no": "08",
                    "flow_title": "投标(资格预审申请)文件公开",
                    "document_kind": "bid_file_publicity",
                },
            ]
        )
        broken["backtrace_stage_attempts"].append(
            {
                "document_kind": "opening_info",
                "target_id": "GZ-BROKEN-OPENING",
                "source_url": "",
                "target_execution_state": "DISCOVERY_NO_MATCH_REVIEW",
                "failure_taxonomy": ["discovery_no_match"],
                "guangzhou_flow_no": "05",
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, audit_items=[broken], challenge_failed_count=1)

            result = build_guangzhou_post_candidate_acceptance_report(
                output_root=root,
                golden_contract_json=CONTRACT_PATH,
                created_at="2026-05-10T00:00:00+08:00",
            )

        self.assertEqual(result["summary"]["batch_acceptance_state"], PARTIAL_REVIEW_REQUIRED)
        self.assertFalse(result["summary"]["golden_acceptance_passed"])
        self.assertGreater(result["summary"]["manual_check_recommended_count"], 0)
        manual_text = json.dumps(result["manifest"]["manual_check_recommended_items"], ensure_ascii=False)
        self.assertIn("important_flow_missing:05", manual_text)
        self.assertIn("golden_acceptance_failed", manual_text)


def _load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _write_inputs(root: Path, *, audit_items: list[dict[str, Any]], challenge_failed_count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run-manifest.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "manifest_id": "GZ-ACCEPTANCE-TEST",
                    "summary": {
                        "project_sample_count": len(audit_items),
                        "selected_post_candidate_entry_count": len(audit_items),
                    },
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "project-file-audit.json").write_text(
        json.dumps({"manifest": {"items": audit_items}, "summary": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "challenge-stability-report.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "summary": {
                        "challenge_resolved_count": 28,
                        "challenge_failed_count": challenge_failed_count,
                        "failure_taxonomy_counts": {"guangzhou_epoint_challenge_failed": challenge_failed_count}
                        if challenge_failed_count
                        else {},
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _golden_project_audit(contract: Mapping[str, Any]) -> dict[str, Any]:
    project = contract["projects"][0]
    inventory: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    file_index = 0
    for expectation in project["flow_expectations"]:
        flow_no = str(expectation["flow_no"])
        flow_title = str(expectation["flow_title"])
        document_kind = str(expectation["document_kind"])
        for detail_index, detail in enumerate(expectation["details"], start=1):
            file_index += 1
            detail_url = str(detail["source_url"])
            inventory.append(
                {
                    "flow_no": flow_no,
                    "flow_title": flow_title,
                    "file_id": f"DETAIL-{file_index:03d}",
                    "file_role": "detail",
                    "snapshot_id": f"SNAP-DETAIL-{flow_no}-{detail_index}",
                    "source_url": detail_url,
                    "parent_source_url": "",
                    "published_date": detail["published_date"],
                    "copied_file_path": f"C:/tmp/{flow_no}/detail-{detail_index}.html",
                    "replayable": True,
                }
            )
            files.append(
                {
                    "project_id": project["project_id"],
                    "guangzhou_flow_no": flow_no,
                    "guangzhou_flow_title": flow_title,
                    "parent_published_at": detail["published_date"],
                    "source_url": detail_url,
                    "snapshot_id": f"SNAP-DETAIL-{flow_no}-{detail_index}",
                    "file_path": f"C:/tmp/{flow_no}/detail-{detail_index}.html",
                    "file_role": "detail",
                    "download_state": "DOWNLOADED_REPLAYABLE",
                    "parse_state": "PARSED",
                }
            )
            for attach_index in range(1, int(detail["expected_attachment_count"]) + 1):
                file_index += 1
                attachment_url = f"{detail_url}?attachment={attach_index}"
                inventory.append(
                    {
                        "flow_no": flow_no,
                        "flow_title": flow_title,
                        "file_id": f"ATTACH-{file_index:03d}",
                        "file_role": "attachment",
                        "snapshot_id": f"SNAP-ATTACH-{flow_no}-{detail_index}-{attach_index}",
                        "source_url": attachment_url,
                        "parent_source_url": detail_url,
                        "published_date": detail["published_date"],
                        "copied_file_path": f"C:/tmp/{flow_no}/attachment-{detail_index}-{attach_index}.pdf",
                        "replayable": True,
                    }
                )
                files.append(
                    {
                        "project_id": project["project_id"],
                        "guangzhou_flow_no": flow_no,
                        "guangzhou_flow_title": flow_title,
                        "parent_published_at": detail["published_date"],
                        "source_url": attachment_url,
                        "snapshot_id": f"SNAP-ATTACH-{flow_no}-{detail_index}-{attach_index}",
                        "file_path": f"C:/tmp/{flow_no}/attachment-{detail_index}-{attach_index}.pdf",
                        "file_role": "attachment",
                        "download_state": "DOWNLOADED_REPLAYABLE",
                        "parse_state": "PARSED",
                    }
                )
    return {
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "source_profile_ids": [contract["source_profile_id"]],
        "document_kinds": ["tender_file", "opening_info", "qualification_review_result", "candidate_notice", "bid_file_publicity"],
        "post_candidate_entry_state": "POST_CANDIDATE_ENTRY_PRESENT",
        "backtrace_completeness_state": "BACKTRACE_PARTIAL",
        "guangzhou_flow_completeness_state": "GUANGZHOU_FLOW_PARTIAL",
        "guangzhou_flow_modules_present": [
            module
            for module in contract["flow_modules"]
            if module["flow_no"] in project["expected_present_flow_nos"]
        ],
        "guangzhou_flow_modules_missing": [
            module
            for module in contract["flow_modules"]
            if module["flow_no"] in project["expected_missing_flow_nos"]
        ],
        "guangzhou_flow_inventory": inventory,
        "detail_file_count": project["expected_detail_count"],
        "attachment_file_count": project["expected_attachment_count"],
        "replayable_file_count": project["expected_replayable_file_count"],
        "download_completeness_state": "DOWNLOAD_COMPLETE",
        "parse_completeness_state": "PARSE_COMPLETE",
        "ready_for_tailored_analysis": True,
        "verification_urls": {
            "project_source_urls": [
                detail["source_url"]
                for expectation in project["flow_expectations"]
                for detail in expectation["details"]
            ],
            "attachment_snapshot_urls": [
                item["source_url"]
                for item in inventory
                if item["file_role"] == "attachment"
            ],
        },
        "file_inventory": files,
        "backtrace_stage_attempts": [],
        "failure_reasons": [],
    }


def _ordinary_project_audit(index: int) -> dict[str, Any]:
    return {
        "project_id": f"PROJ-CN-GD-JG2026-ORD-{index:03d}",
        "project_name": f"广州普通候选后项目{index}",
        "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
        "document_kinds": ["candidate_notice", "tender_file"],
        "post_candidate_entry_state": "POST_CANDIDATE_ENTRY_PRESENT",
        "backtrace_completeness_state": "BACKTRACE_PARTIAL",
        "guangzhou_flow_completeness_state": "GUANGZHOU_FLOW_PARTIAL",
        "guangzhou_flow_modules_present": [],
        "guangzhou_flow_modules_missing": [],
        "guangzhou_flow_inventory": [
            {
                "flow_no": "07",
                "flow_title": "中标候选人公示",
                "file_role": "detail",
                "source_url": f"https://example.test/{index}/candidate.html",
                "published_date": "2026-05-10",
                "replayable": True,
            }
        ],
        "detail_file_count": 1,
        "attachment_file_count": 0,
        "replayable_file_count": 1,
        "download_completeness_state": "DOWNLOAD_COMPLETE",
        "parse_completeness_state": "PARSE_COMPLETE",
        "ready_for_tailored_analysis": True,
        "verification_urls": {"project_source_urls": [f"https://example.test/{index}/candidate.html"]},
        "file_inventory": [],
        "backtrace_stage_attempts": [],
        "failure_reasons": [],
    }


if __name__ == "__main__":
    unittest.main()
