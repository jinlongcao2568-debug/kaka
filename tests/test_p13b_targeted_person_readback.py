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

from storage.p13b_targeted_person_readback import build_p13b_targeted_person_readback  # noqa: E402


class P13BTargetedPersonReadbackTests(unittest.TestCase):
    def test_dry_run_builds_tasks_only_for_targeted_person_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            continuation_root = root / "continuation"
            _write_continuation(continuation_root)

            result = build_p13b_targeted_person_readback(
                continuation_root=continuation_root,
                output_root=root / "out",
                project_ids=["PROJ-1"],
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["targeted_person_task_count"], 1)
            self.assertEqual(result["summary"]["targeted_person_readback_count"], 0)
            task = result["manifest"]["targeted_person_readback_task_records"][0]
            self.assertEqual(task["responsible_person_names"], ["张三"])
            self.assertEqual(task["extracted_period_text"], "180日历天")

    def test_live_page_hit_marks_same_person_company_period_signal_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            continuation_root = root / "continuation"
            _write_continuation(continuation_root)

            def http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "status_code": 200,
                    "content_type": "text/html; charset=utf-8",
                    "url": url,
                    "body": "<html><body>中标人：广东甲公司。项目经理：张三。工期：180日历天。</body></html>",
                }

            result = build_p13b_targeted_person_readback(
                continuation_root=continuation_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_readbacks=1,
                created_at="2026-05-19T00:00:00+08:00",
                http_getter=http_getter,
            )

            self.assertEqual(result["summary"]["target_person_found_count"], 1)
            self.assertEqual(result["summary"]["same_person_company_period_signal_ready_count"], 1)
            record = result["manifest"]["targeted_person_readback_records"][0]
            self.assertEqual(record["targeted_person_readback_state"], "TARGETED_PERSON_FOUND_ON_DETAIL_PAGE")

    def test_target_attachment_parse_can_find_person(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            continuation_root = root / "continuation"
            _write_continuation(continuation_root)

            def http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "status_code": 200,
                    "content_type": "text/html; charset=utf-8",
                    "url": "https://example.test/detail.html",
                    "body": '<html><body>中标人：广东甲公司。工期：180日历天。<a href="/notice.pdf">中标结果公告.pdf</a></body></html>',
                }

            def binary_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "status_code": 200,
                    "content_type": "application/pdf",
                    "url": url,
                    "body": b"%PDF-fake",
                }

            def extractor(path: str | Path, **kwargs: Any) -> Mapping[str, Any]:
                return {
                    "sha256": "sha",
                    "extraction_methods": ["stub_pdf_text"],
                    "text": "项目经理：张三\n工期：180日历天",
                    "extracted_fields": {"extraction_state": "FIELDS_EXTRACTED"},
                    "failure_reasons": [],
                    "pages": [],
                }

            result = build_p13b_targeted_person_readback(
                continuation_root=continuation_root,
                output_root=root / "out",
                enable_live_public_query=True,
                download_target_attachments=True,
                max_live_readbacks=1,
                max_attachments_per_task=1,
                created_at="2026-05-19T00:00:00+08:00",
                http_getter=http_getter,
                binary_getter=binary_getter,
                document_extractor=extractor,
            )

            self.assertEqual(result["summary"]["attachment_candidate_count"], 1)
            self.assertEqual(result["summary"]["attachment_fetched_count"], 1)
            self.assertEqual(result["summary"]["target_person_found_count"], 1)
            self.assertEqual(result["summary"]["same_person_company_period_signal_ready_count"], 1)
            record = result["manifest"]["targeted_person_readback_records"][0]
            self.assertEqual(record["targeted_person_readback_state"], "TARGETED_PERSON_FOUND_IN_ATTACHMENT")


def _write_continuation(root: Path) -> None:
    payload = {
        "manifest": {
            "continuation_plan_records": [
                {
                    "original_notice_task_id": "TASK-1",
                    "project_id": "PROJ-1",
                    "candidate_company_name": "广东甲公司",
                    "responsible_person_names": ["张三"],
                    "bid_project_name": "历史工程",
                    "original_notice_url": "https://example.test/detail.html",
                    "bid_show_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
                    "extracted_period_text": "180日历天",
                    "candidate_company_matched": True,
                    "performance_period_present": True,
                    "continuation_state": "TARGETED_PERSON_READBACK_REQUIRED",
                },
                {
                    "original_notice_task_id": "TASK-2",
                    "project_id": "PROJ-1",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "original_notice_url": "https://example.test/park.html",
                    "continuation_state": "PARK_NO_EXTRACTED_MATCH_FIELDS",
                },
            ]
        }
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "p13b-original-backtrace-continuation-controller-v2.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
