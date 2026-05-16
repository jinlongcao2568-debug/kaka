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

from storage.guangdong_ygp_city_coverage_closeout import (  # noqa: E402
    build_guangdong_ygp_city_coverage_closeout,
)


CITY_CODES = (
    "440200",
    "440700",
    "440800",
    "440900",
    "441200",
    "441300",
    "441400",
    "441500",
    "441600",
    "441700",
    "441800",
    "441900",
    "442000",
    "445100",
    "445200",
    "445300",
)


class GuangdongYgpCityCoverageCloseoutTests(unittest.TestCase):
    def test_16_cities_all_enter_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertTrue(result["safe_to_execute"])
            records = result["manifest"]["city_coverage_records"]
            self.assertEqual(len(records), 16)
            self.assertEqual({record["city_code"] for record in records}, set(CITY_CODES))
            self.assertTrue((root / "out" / "guangdong-ygp-city-coverage-closeout-v1.json").exists())
            self.assertTrue((root / "out" / "ygp-city-coverage-table.json").exists())

    def test_plan_signature_accepts_positional_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = build_guangdong_ygp_city_coverage_closeout(
                root / "city-discovery",
                root / "download",
                root / "mini",
                root / "oversize",
                root / "p13b-expansion",
                root / "out",
                "2026-05-16T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["city_count"], 16)

    def test_recent_07_cities_enter_expected_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(_record(result, "440200")["city_coverage_state"], "YGP_CITY_COVERAGE_READY_FOR_P13B")
            self.assertEqual(_record(result, "440800")["city_coverage_state"], "YGP_CITY_COVERAGE_READY_WITH_BACKLOG")
            self.assertEqual(_record(result, "441800")["city_coverage_state"], "YGP_CITY_COVERAGE_NO_PUBLIC_ATTACHMENT_REVIEW")
            self.assertEqual(_record(result, "442000")["city_coverage_state"], "YGP_CITY_COVERAGE_PARTIAL_REVIEW")

    def test_no_recent_city_keeps_empty_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record(result, "441300")
            self.assertFalse(record["has_recent_07"])
            self.assertEqual(record["project_id"], "")
            self.assertEqual(record["city_coverage_state"], "YGP_CITY_COVERAGE_NO_RECENT_07")

    def test_oversize_and_limit_deferred_are_not_real_download_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record(result, "440800")
            self.assertEqual(record["oversize_queue_count"], 1)
            self.assertEqual(record["limit_deferred_queue_count"], 1)
            self.assertEqual(record["real_download_failure_count"], 0)
            self.assertEqual(result["summary"]["real_download_failure_count"], 0)

    def test_no_public_attachment_is_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record(result, "441800")
            self.assertTrue(record["no_public_attachment"])
            self.assertEqual(record["city_coverage_state"], "YGP_CITY_COVERAGE_NO_PUBLIC_ATTACHMENT_REVIEW")
            self.assertNotEqual(record["city_coverage_state"], "YGP_CITY_COVERAGE_BLOCKED")

    def test_non_hard_review_rows_do_not_enter_blocker_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            blocker_city_codes = {record["city_code"] for record in result["manifest"]["city_blocker_records"]}
            self.assertNotIn("440800", blocker_city_codes)
            self.assertNotIn("441800", blocker_city_codes)
            self.assertNotIn("441300", blocker_city_codes)

    def test_p13b_ready_project_count_comes_from_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(result["summary"]["p13b_ready_project_count"], 3)
            self.assertEqual(result["summary"]["p13b_overlap_input_count"], 4)
            self.assertEqual(_record(result, "440200")["p13b_overlap_input_count"], 2)
            self.assertTrue((root / "out" / "ygp-p13b-ready-project-table.json").exists())

    def test_p13b_ready_is_from_ready_task_not_overlap_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)
            expansion_path = root / "p13b-expansion" / "p13b-ygp-original-readback-expansion-v1.json"
            expansion = json.loads(expansion_path.read_text(encoding="utf-8"))
            expansion["manifest"]["overlap_triage_input_records"].append(_overlap_input("442000", "广东戊公司"))
            _write_json(expansion_path, expansion)

            result = _build(root)

            record = _record(result, "442000")
            self.assertFalse(record["p13b_ready"])
            self.assertFalse(record["p13b_input_ready"])
            self.assertEqual(record["city_coverage_state"], "YGP_CITY_COVERAGE_PARTIAL_REVIEW")
            self.assertEqual(result["summary"]["p13b_ready_project_count"], 3)
            self.assertEqual(result["summary"]["p13b_overlap_input_count"], 5)

    def test_fake_attachment_count_is_zero_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(result["summary"]["fake_attachment_count"], 0)

    def test_safety_fields_are_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            safety = result["manifest"]["safety"]
            self.assertFalse(safety["network_enabled"])
            self.assertFalse(safety["download_enabled"])
            self.assertFalse(safety["parse_enabled"])
            self.assertFalse(safety["customer_visible_allowed"])
            self.assertTrue(safety["no_legal_conclusion"])
            self.assertFalse(safety["stage4_live_executed"])
            self.assertEqual(safety["flow_08_default_downloaded_count"], 0)
            self.assertFalse(result["summary"]["stage4_live_executed"])
            self.assertEqual(result["summary"]["flow_08_default_downloaded_count"], 0)

    def test_forbidden_terms_scan_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(result["summary"]["forbidden_term_scan_state"], "PASS")
            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "确认本人", "是不是本人", "在建冲突成立", "违法成立", "造假成立"):
                self.assertNotIn(term, text)


def _build(root: Path) -> dict[str, Any]:
    return build_guangdong_ygp_city_coverage_closeout(
        city_discovery_root=root / "city-discovery",
        download_root=root / "download",
        mini_closeout_root=root / "mini",
        oversize_policy_root=root / "oversize",
        p13b_ygp_expansion_root=root / "p13b-expansion",
        output_root=root / "out",
        created_at="2026-05-16T00:00:00+08:00",
    )


def _record(result: Mapping[str, Any], city_code: str) -> Mapping[str, Any]:
    return next(record for record in result["manifest"]["city_coverage_records"] if record["city_code"] == city_code)


def _write_fixture(root: Path) -> None:
    for path in ("mini", "oversize", "p13b-expansion", "city-discovery", "download"):
        (root / path).mkdir(parents=True, exist_ok=True)
    city_records = [_mini_record(city) for city in CITY_CODES]
    by_city = {record["city_code"]: record for record in city_records}
    by_city["441300"].update(
        {
            "has_recent_07": False,
            "project_id": "",
            "project_name": "",
            "source_url": "",
            "flow_bucket_count": 0,
            "detail_readback_ready_count": 0,
            "evidence_package_readiness_state": "YGP_EVIDENCE_MINI_NO_RECENT_07",
        }
    )
    by_city["440800"].update(
        {
            "evidence_package_readiness_state": "YGP_EVIDENCE_MINI_READY_WITH_OVERSIZE_BACKLOG",
            "city_closeout_state": "YGP_CITY_ATTACHMENT_POLICY_DEFERRED",
            "oversize_queue_count": 1,
            "limit_deferred_queue_count": 1,
            "failure_taxonomy_counts": {"OVERSIZE_DEFERRED_BY_POLICY": 1, "DEFERRED_BY_YGP_DOWNLOAD_LIMIT": 1},
        }
    )
    by_city["441800"].update(
        {
            "evidence_package_readiness_state": "YGP_EVIDENCE_MINI_NO_PUBLIC_ATTACHMENT_REVIEW",
            "city_closeout_state": "YGP_CITY_NO_PUBLIC_ATTACHMENT_REVIEW",
            "listed_attachment_count": 0,
            "download_attempted_count": 0,
            "attachment_snapshot_count": 0,
            "attachment_snapshot_success_rate": 0.0,
            "failure_taxonomy_counts": {"ygp_no_public_attachment_link_found": 1},
        }
    )
    by_city["442000"].update(
        {
            "evidence_package_readiness_state": "YGP_EVIDENCE_MINI_READY_FOR_P13B",
            "city_closeout_state": "YGP_CITY_EVIDENCE_MINI_READY",
        }
    )
    _write_json(
        root / "mini" / "ygp-evidence-mini-closeout-v2.json",
        {
            "manifest": {"manifest_version": 2, "city_project_records": city_records},
            "summary": {"city_count": 16, "real_download_failure_count": 0, "fake_attachment_count": 0},
        },
    )
    _write_json(root / "mini" / "ygp-city-project-table.json", {"records": city_records, "summary": {}})
    _write_json(
        root / "oversize" / "ygp-oversize-policy-v1.json",
        {
            "manifest": {
                "oversize_attachment_queue": [
                    _oversize_record("440800", "OVERSIZE_QUEUE_READY"),
                    _oversize_record("440800", "LIMIT_DEFERRED_QUEUE_READY"),
                ]
            },
            "summary": {"real_download_failure_count": 0, "fake_attachment_count": 0},
        },
    )
    _write_json(
        root / "p13b-expansion" / "p13b-ygp-original-readback-expansion-v1.json",
        {
            "manifest": {
                "task_records": [
                    _p13b_task("440200", "P13B_YGP_ORIGINAL_READBACK_READY"),
                    _p13b_task("440800", "P13B_YGP_BACKLOG_TRACKED_READY"),
                    _p13b_task("441800", "P13B_YGP_NO_PUBLIC_ATTACHMENT_BUT_DETAIL_READY"),
                    _p13b_task("442000", "P13B_YGP_FIELD_PARTIAL_REVIEW"),
                ],
                "overlap_triage_input_records": [
                    _overlap_input("440200", "广东甲公司"),
                    _overlap_input("440200", "广东乙公司"),
                    _overlap_input("440800", "广东丙公司"),
                    _overlap_input("441800", "广东丁公司"),
                ],
            },
            "summary": {"task_count": 4, "overlap_triage_input_count": 4},
        },
    )
    _write_json(
        root / "city-discovery" / "guangdong-ygp-city-discovery-v1.json",
        {"manifest": {"city_codes": list(CITY_CODES), "ygp_city_search_records": []}, "summary": {}},
    )
    _write_json(
        root / "download" / "ygp-full-chain-manifest.json",
        {"manifest": {"items": [], "project_sample_items": []}, "summary": {}},
    )


def _mini_record(city_code: str) -> dict[str, Any]:
    project_id = f"PROJ-CN-GD-YGP-{city_code}-PC-{city_code}"
    return {
        "city_code": city_code,
        "has_recent_07": True,
        "project_id": project_id,
        "project_name": f"{city_code}测试项目",
        "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{city_code}",
        "flow_bucket_count": 12,
        "present_flow_nos": ["03", "05", "07"],
        "detail_readback_ready_count": 3,
        "listed_attachment_count": 1,
        "download_attempted_count": 1,
        "attachment_snapshot_count": 1,
        "attachment_snapshot_success_rate": 1.0,
        "fake_attachment_count": 0,
        "oversize_queue_count": 0,
        "limit_deferred_queue_count": 0,
        "real_download_failure_count": 0,
        "flow_08_default_downloaded": False,
        "stage4_live_executed": False,
        "evidence_package_readiness_state": "YGP_EVIDENCE_MINI_READY_FOR_P13B",
        "city_closeout_state": "YGP_CITY_EVIDENCE_MINI_READY",
        "failure_taxonomy_counts": {},
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _oversize_record(city_code: str, policy_state: str) -> dict[str, Any]:
    return {
        "city_code": city_code,
        "project_id": f"PROJ-CN-GD-YGP-{city_code}-PC-{city_code}",
        "policy_state": policy_state,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _p13b_task(city_code: str, state: str) -> dict[str, Any]:
    return {
        "city_code": city_code,
        "project_id": f"PROJ-CN-GD-YGP-{city_code}-PC-{city_code}",
        "project_name": f"{city_code}测试项目",
        "p13b_ygp_original_readback_state": state,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _overlap_input(city_code: str, company: str) -> dict[str, Any]:
    return {
        "city_code": city_code,
        "project_id": f"PROJ-CN-GD-YGP-{city_code}-PC-{city_code}",
        "candidate_company_name": company,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
