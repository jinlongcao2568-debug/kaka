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

from storage.guangdong_ygp_evidence_mini_closeout import (  # noqa: E402
    build_guangdong_ygp_evidence_mini_closeout,
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


class GuangdongYgpEvidenceMiniCloseoutTests(unittest.TestCase):
    def test_16_cities_all_enter_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertTrue(result["safe_to_execute"])
            records = result["manifest"]["city_project_records"]
            self.assertEqual(len(records), 16)
            self.assertEqual({record["city_code"] for record in records}, set(CITY_CODES))
            self.assertTrue((root / "out" / "ygp-evidence-mini-closeout-v1.json").exists())
            self.assertTrue((root / "out" / "ygp-city-project-table.json").exists())
            self.assertTrue((root / "out" / "ygp-download-stability-table.json").exists())
            self.assertTrue((root / "out" / "ygp-next-action-table.json").exists())

    def test_cities_with_07_have_project_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            records = result["manifest"]["city_project_records"]
            with_07 = [record for record in records if record["has_recent_07"]]
            self.assertEqual(len(with_07), 15)
            self.assertTrue(all(record["project_id"] for record in with_07))
            self.assertTrue(all(record["project_name"] for record in with_07))
            self.assertTrue(all(record["source_url"] for record in with_07))
            self.assertTrue(all(record["flow_bucket_count"] == 12 for record in with_07))

    def test_city_without_07_enters_no_recent_review_without_fake_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record(result, "441300")
            self.assertFalse(record["has_recent_07"])
            self.assertEqual(record["project_id"], "")
            self.assertEqual(record["project_name"], "")
            self.assertEqual(record["city_closeout_state"], "YGP_CITY_NO_RECENT_07_REVIEW")
            self.assertIn("no_supported_07_candidate", record["failure_taxonomy_counts"])

    def test_strategy_deferred_is_not_real_download_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record(result, "440800")
            self.assertEqual(record["city_closeout_state"], "YGP_CITY_ATTACHMENT_POLICY_DEFERRED")
            self.assertEqual(record["strategy_deferred_counts"], {"OVERSIZE_DEFERRED_BY_POLICY": 1})
            self.assertEqual(record["real_download_failure_count"], 0)
            self.assertEqual(result["summary"]["real_download_failure_count"], 0)

    def test_no_public_attachment_enters_review_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record(result, "441800")
            self.assertEqual(record["listed_attachment_count"], 0)
            self.assertEqual(record["city_closeout_state"], "YGP_CITY_NO_PUBLIC_ATTACHMENT_REVIEW")
            self.assertIn("ygp_no_public_attachment_link_found", record["failure_taxonomy_counts"])

    def test_flow_08_default_download_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(result["summary"]["flow_08_default_downloaded_count"], 0)
            self.assertTrue(all(not record["flow_08_default_downloaded"] for record in result["manifest"]["city_project_records"]))

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
    return build_guangdong_ygp_evidence_mini_closeout(
        city_discovery_root=root / "city-discovery-external",
        download_root=root / "download",
        output_root=root / "out",
        created_at="2026-05-16T00:00:00+08:00",
    )


def _record(result: Mapping[str, Any], city_code: str) -> Mapping[str, Any]:
    return next(record for record in result["manifest"]["city_project_records"] if record["city_code"] == city_code)


def _write_fixture(root: Path) -> None:
    download = root / "download"
    embedded_discovery = download / "city-discovery"
    flow_matrix_dir = embedded_discovery / "flow-matrix"
    external_discovery = root / "city-discovery-external"
    for path in (download, embedded_discovery, flow_matrix_dir, external_discovery):
        path.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    project_records: list[dict[str, Any]] = []
    flow_buckets: list[dict[str, Any]] = []
    search_records: list[dict[str, Any]] = []
    for city in CITY_CODES:
        search_records.append(
            {
                "city_code": city,
                "search_state": "YGP_CITY_SEARCH_READY",
                "blocker_taxonomy": [],
                "accepted_candidate_count": 0 if city == "441300" else 1,
            }
        )
        if city == "441300":
            continue
        project_code = f"PC-{city}"
        project_id = f"PROJ-CN-GD-YGP-{city}-{project_code}"
        failure_taxonomy: list[str] = []
        listed = 1
        attempted = 1
        snapshots = 1
        if city == "440800":
            listed = 2
            failure_taxonomy = ["OVERSIZE_DEFERRED_BY_POLICY"]
        if city == "441800":
            listed = 0
            attempted = 0
            snapshots = 0
            failure_taxonomy = ["ygp_no_public_attachment_link_found"]
        items.append(
            {
                "project_id": project_id,
                "project_name": f"{city}测试项目",
                "city_code": city,
                "flow_no": "07",
                "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{city}",
                "listed_attachment_count": listed,
                "download_attempted_count": attempted,
                "attachment_snapshot_count": snapshots,
                "failure_taxonomy": failure_taxonomy,
            }
        )
        samples.append(
            {
                "project_id": project_id,
                "project_name": f"{city}测试项目",
                "city_code": city,
                "project_code": project_code,
                "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{city}",
                "attachment_link_items": []
                if listed == 0
                else [
                    {
                        "source_field": "noticeFileBOList",
                        "file_name": "候选公示.pdf",
                        "download_url": f"https://ygp.gdzwfw.gov.cn/ggzy-portal/base/sys-file/download/v3/{city}?1",
                    }
                ],
            }
        )
        project_records.append(
            {
                "resolved_project_route": {"siteCode": city, "projectCode": project_code},
                "detail_readback_ready_count": 3,
                "project_readback_state": "YGP_FLOW_MATRIX_READY",
            }
        )
        for flow_no in [f"{index:02d}" for index in range(1, 13)]:
            flow_buckets.append(
                {
                    "site_code": city,
                    "project_code": project_code,
                    "flow_no": flow_no,
                    "flow_item_state": "YGP_FLOW_ITEM_PRESENT" if flow_no in {"03", "07"} else "YGP_FLOW_ITEM_NOT_PRESENT",
                }
            )

    _write_json(
        download / "ygp-full-chain-manifest.json",
        {
            "manifest": {
                "city_codes": list(CITY_CODES),
                "items": items,
                "project_sample_items": samples,
                "summary": {"batch_closeout_state": "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED"},
            },
            "summary": {
                "batch_closeout_state": "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED",
                "attachment_snapshot_success_rate": 1.0,
                "flow_08_register_only_count": 0,
            },
            "execution": {"stage4_live_provider_enabled": False},
        },
    )
    _write_json(
        download / "guangdong-ygp-batch-stability-closeout-v1.json",
        {"summary": {"batch_closeout_state": "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED", "stage4_execution_item_count": 0}},
    )
    discovery_payload = {"manifest": {"city_codes": list(CITY_CODES), "ygp_city_search_records": search_records}, "summary": {}}
    _write_json(embedded_discovery / "guangdong-ygp-city-discovery-v1.json", discovery_payload)
    _write_json(external_discovery / "guangdong-ygp-city-discovery-v1.json", discovery_payload)
    _write_json(
        flow_matrix_dir / "guangdong-ygp-flow-matrix-v1.json",
        {
            "manifest": {
                "ygp_project_records": project_records,
                "ygp_flow_bucket_records": flow_buckets,
            },
            "summary": {},
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
