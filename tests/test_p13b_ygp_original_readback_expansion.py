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

from storage.p13b_ygp_original_readback_expansion import (  # noqa: E402
    build_p13b_ygp_original_readback_expansion,
)


class P13BYgpOriginalReadbackExpansionTests(unittest.TestCase):
    def test_ready_for_p13b_city_enters_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertTrue(result["safe_to_execute"])
            task = _task(result, "440200")
            self.assertEqual(task["p13b_ygp_original_readback_state"], "P13B_YGP_ORIGINAL_READBACK_READY")
            self.assertIn("广东甲公司", task["candidate_company_candidates"])

    def test_ready_with_oversize_backlog_enters_task_with_backlog_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            task = _task(result, "440800")
            self.assertTrue(task["backlog_tracked"])
            self.assertEqual(task["p13b_ygp_original_readback_state"], "P13B_YGP_BACKLOG_TRACKED_READY")

    def test_no_recent_07_does_not_enter_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            city_codes = {task["city_code"] for task in result["manifest"]["task_records"]}
            self.assertNotIn("441300", city_codes)
            not_selected = {record["city_code"]: record for record in result["manifest"]["not_selected_records"]}
            self.assertEqual(not_selected["441300"]["p13b_ygp_original_readback_state"], "P13B_YGP_NOT_SELECTED")

    def test_no_public_attachment_enters_only_when_detail_fields_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(
                _task(result, "441800")["p13b_ygp_original_readback_state"],
                "P13B_YGP_NO_PUBLIC_ATTACHMENT_BUT_DETAIL_READY",
            )
            city_codes = {task["city_code"] for task in result["manifest"]["task_records"]}
            self.assertNotIn("445100", city_codes)

    def test_extracts_company_person_certificate_price_rank_period_and_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            task = _task(result, "440200")
            self.assertIn("广东甲公司", task["candidate_company_candidates"])
            self.assertIn("张三", task["responsible_person_candidates"])
            self.assertIn("粤244000000001", task["certificate_no_candidates"])
            self.assertIn("123456.78", task["bid_price_candidates"])
            self.assertIn("第一中标候选人", task["rank_candidates"])
            self.assertIn("365日历天", task["service_period_text"])
            self.assertEqual(task["publish_date"], "2026-05-15 10:00:00")

    def test_outputs_overlap_triage_input_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            overlap = result["manifest"]["overlap_triage_input_records"]
            self.assertGreaterEqual(len(overlap), 3)
            self.assertTrue((root / "out" / "p13b-ygp-overlap-triage-input-table.json").exists())
            self.assertTrue(any(record["candidate_company_name"] == "广东甲公司" for record in overlap))

    def test_forbidden_terms_scan_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(result["summary"]["forbidden_term_scan_state"], "PASS")
            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "确认本人", "在建冲突成立", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _build(root: Path) -> dict[str, Any]:
    return build_p13b_ygp_original_readback_expansion(
        mini_closeout_root=root / "mini",
        city_discovery_root=root / "city-discovery",
        download_root=root / "download",
        output_root=root / "out",
        created_at="2026-05-16T00:00:00+08:00",
    )


def _task(result: Mapping[str, Any], city_code: str) -> Mapping[str, Any]:
    return next(record for record in result["manifest"]["task_records"] if record["city_code"] == city_code)


def _write_fixture(root: Path) -> None:
    mini = root / "mini"
    download = root / "download"
    city_discovery = root / "city-discovery"
    mini.mkdir(parents=True, exist_ok=True)
    download.mkdir(parents=True, exist_ok=True)
    city_discovery.mkdir(parents=True, exist_ok=True)

    records = [
        _mini_record("440200", "YGP_EVIDENCE_MINI_READY_FOR_P13B"),
        _mini_record("440800", "YGP_EVIDENCE_MINI_READY_WITH_OVERSIZE_BACKLOG", oversize_queue_count=1),
        _mini_record("441300", "YGP_EVIDENCE_MINI_NO_RECENT_07", has_recent_07=False),
        _mini_record("441800", "YGP_EVIDENCE_MINI_NO_PUBLIC_ATTACHMENT_REVIEW"),
        _mini_record("445100", "YGP_EVIDENCE_MINI_NO_PUBLIC_ATTACHMENT_REVIEW"),
    ]
    _write_json(
        mini / "ygp-evidence-mini-closeout-v2.json",
        {
            "manifest": {
                "manifest_version": 2,
                "city_project_records": records,
            },
            "summary": {"real_download_failure_count": 0},
        },
    )
    _write_json(
        city_discovery / "guangdong-ygp-city-discovery-v1.json",
        {"manifest": {"city_codes": ["440200", "440800", "441300", "441800", "445100"]}, "summary": {}},
    )

    samples = [
        _sample(root, "440200", "中标候选人：广东甲公司。项目负责人：张三。证书编号：粤244000000001。投标报价（元）：123456.78。第一中标候选人。服务期：365日历天。公告日期：2026-05-15", "2026-05-15 10:00:00"),
        _sample(root, "440800", "中标人：广东乙公司。总监理工程师：李四。注册编号:44012345。工期：180日历天。", "2026-05-15 11:00:00"),
        _sample(root, "441800", "定标候选人：广东丙公司。姓名：王五。注册编号：粤144000000002。服务期：90日历天。", "2026-05-15 12:00:00"),
        _sample(root, "445100", "公告内容：详见交易平台公开信息。", "2026-05-15 13:00:00"),
    ]
    _write_json(
        download / "ygp-full-chain-manifest.json",
        {
            "manifest": {
                "project_sample_items": samples,
            },
            "summary": {},
        },
    )


def _mini_record(
    city_code: str,
    readiness_state: str,
    *,
    has_recent_07: bool = True,
    oversize_queue_count: int = 0,
) -> dict[str, Any]:
    project_id = f"PROJ-CN-GD-YGP-{city_code}-PC-{city_code}" if has_recent_07 else ""
    return {
        "city_code": city_code,
        "has_recent_07": has_recent_07,
        "project_id": project_id,
        "project_name": f"{city_code}测试项目" if has_recent_07 else "",
        "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{city_code}" if has_recent_07 else "",
        "present_flow_nos": ["03", "05", "07"] if has_recent_07 else [],
        "evidence_package_readiness_state": readiness_state,
        "oversize_queue_count": oversize_queue_count,
        "limit_deferred_queue_count": 0,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _sample(root: Path, city_code: str, text: str, published_at: str) -> dict[str, Any]:
    project_id = f"PROJ-CN-GD-YGP-{city_code}-PC-{city_code}"
    detail_path = root / "download" / "projects" / city_code / "detail.json"
    detail_payload = {
        "project_id": project_id,
        "project_name": f"{city_code}测试项目",
        "city_code": city_code,
        "flow_no": "07",
        "flow_title": "中标候选人公示",
        "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{city_code}",
        "notice_title": f"{city_code}测试项目中标候选人公示",
        "published_at": published_at,
        "text_probe": text,
        "text_probe_sha256": "detail-text-hash",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    _write_json(detail_path, detail_payload)
    return {
        "target_id": f"YGP-{city_code}-07",
        "source_profile_id": "GUANGDONG-YGP-FULL-CHAIN",
        "project_id": project_id,
        "project_name": f"{city_code}测试项目",
        "city_code": city_code,
        "project_code": f"PC-{city_code}",
        "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{city_code}",
        "guangdong_ygp_flow_no": "07",
        "guangdong_ygp_flow_title": "中标候选人公示",
        "detail_snapshot_refs": [
            {
                "snapshot_id": f"YGP-DETAIL-{city_code}",
                "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{city_code}",
                "guangdong_ygp_flow_no": "07",
                "sha256": f"sha-{city_code}",
                "readback_state": "READBACK_READY",
                "local_path": str(detail_path),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
