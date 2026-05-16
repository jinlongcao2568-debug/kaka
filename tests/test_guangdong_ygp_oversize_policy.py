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

from storage.guangdong_ygp_oversize_policy import build_guangdong_ygp_oversize_policy  # noqa: E402


class GuangdongYgpOversizePolicyTests(unittest.TestCase):
    def test_oversize_deferred_enters_oversize_queue_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record_by_url(result, "https://example.test/oversize-known.pdf")
            self.assertEqual(record["policy_state"], "OVERSIZE_QUEUE_READY")
            self.assertEqual(record["defer_reason"], "OVERSIZE_DEFERRED_BY_POLICY")
            self.assertEqual(record["file_size_bytes"], 50 * 1024 * 1024)
            self.assertEqual(record["size_source"], "file_size_url")
            self.assertEqual(record["recommended_action"], "MANUAL_DOWNLOAD_APPROVAL_REQUIRED")

    def test_download_limit_deferred_enters_limit_queue_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record_by_url(result, "https://example.test/limit-deferred.pdf")
            self.assertEqual(record["policy_state"], "LIMIT_DEFERRED_QUEUE_READY")
            self.assertEqual(record["defer_reason"], "DEFERRED_BY_YGP_DOWNLOAD_LIMIT")
            self.assertEqual(record["size_source"], "unknown")

    def test_oversize_without_file_size_enters_size_unknown_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record_by_url(result, "https://example.test/oversize-unknown.pdf")
            self.assertEqual(record["policy_state"], "SIZE_UNKNOWN_REVIEW")
            self.assertIsNone(record["file_size_bytes"])
            self.assertEqual(record["size_source"], "unknown")

    def test_existing_snapshot_enters_already_captured_no_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record_by_url(result, "https://example.test/already-captured.pdf")
            self.assertEqual(record["policy_state"], "ALREADY_CAPTURED_NO_ACTION")
            self.assertEqual(record["existing_snapshot_id"], "SNAP-CAPTURED-1")
            self.assertEqual(record["recommended_action"], "NO_ACTION_EXISTING_SNAPSHOT_READY")

    def test_flow_08_register_only_is_not_default_download_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            record = _record_by_url(result, "https://example.test/flow08-register-only.zip")
            self.assertEqual(record["policy_state"], "NOT_DOWNLOAD_REQUIRED")
            self.assertEqual(record["flow_no"], "08")
            self.assertNotIn("NOT_DOWNLOAD_REQUIRED", result["summary"]["by_flow_counts"])
            self.assertEqual(result["summary"]["not_download_required_count"], 1)

    def test_output_does_not_contain_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_fixture(root)

            result = _build(root)

            self.assertEqual(result["summary"]["forbidden_term_scan_state"], "PASS")
            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "确认本人", "在建冲突成立", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _build(root: Path) -> dict[str, Any]:
    return build_guangdong_ygp_oversize_policy(
        download_root=root / "download",
        mini_closeout_root=root / "mini",
        output_root=root / "out",
        created_at="2026-05-16T00:00:00+08:00",
    )


def _record_by_url(result: Mapping[str, Any], url: str) -> Mapping[str, Any]:
    return next(record for record in result["manifest"]["oversize_attachment_queue"] if record["attachment_url"] == url)


def _write_fixture(root: Path) -> None:
    download = root / "download"
    mini = root / "mini"
    probe_dir = download / "projects" / "CN-GD" / "440800" / "PROJ-440800" / "07_candidate" / "2026-05-15_notice"
    probe_dir.mkdir(parents=True, exist_ok=True)
    mini.mkdir(parents=True, exist_ok=True)
    project_id = "PROJ-CN-GD-YGP-440800-PC440800"
    flow08_project_id = "PROJ-CN-GD-YGP-440800-PC440800-FLOW08"
    full_chain = {
        "manifest": {
            "items": [
                {
                    "project_id": project_id,
                    "city_code": "440800",
                    "flow_no": "07",
                    "flow_title": "中标候选人公示",
                    "failure_taxonomy": ["DEFERRED_BY_YGP_DOWNLOAD_LIMIT", "OVERSIZE_DEFERRED_BY_POLICY"],
                },
                {
                    "project_id": flow08_project_id,
                    "city_code": "440800",
                    "flow_no": "08",
                    "flow_title": "投标文件公开",
                    "failure_taxonomy": ["FLOW_08_REGISTER_ONLY_NOT_DOWNLOADED_BY_DEFAULT"],
                },
            ],
            "project_sample_items": [
                {
                    "project_id": project_id,
                    "project_name": "440800测试项目",
                    "city_code": "440800",
                    "guangdong_ygp_flow_no": "07",
                    "guangdong_ygp_flow_title": "中标候选人公示",
                    "source_url": "https://example.test/detail/440800",
                    "attachment_link_items": [
                        _attachment("oversize-known.pdf", "https://example.test/oversize-known.pdf", 50 * 1024 * 1024),
                        _attachment("oversize-unknown.pdf", "https://example.test/oversize-unknown.pdf"),
                        _attachment("limit-deferred.pdf", "https://example.test/limit-deferred.pdf"),
                        _attachment("already-captured.pdf", "https://example.test/already-captured.pdf"),
                    ],
                    "attachment_snapshot_refs": [
                        {
                            "snapshot_id": "SNAP-CAPTURED-1",
                            "attachment_url": "https://example.test/already-captured.pdf",
                            "source_url": "https://example.test/already-captured.pdf",
                        }
                    ],
                },
                {
                    "project_id": flow08_project_id,
                    "project_name": "440800投标文件公开",
                    "city_code": "440800",
                    "guangdong_ygp_flow_no": "08",
                    "guangdong_ygp_flow_title": "投标文件公开",
                    "source_url": "https://example.test/detail/440800/08",
                    "attachment_link_items": [
                        _attachment("flow08-register-only.zip", "https://example.test/flow08-register-only.zip", flow_no="08", flow_title="投标文件公开")
                    ],
                    "attachment_snapshot_refs": [],
                },
            ],
        },
        "summary": {"fake_attachment_count": 0},
        "execution": {"stage4_live_provider_enabled": False},
    }
    _write_json(download / "ygp-full-chain-manifest.json", full_chain)
    _write_json(
        download / "guangdong-ygp-batch-stability-closeout-v1.json",
        {"summary": {"download_required_failed_attempt_count": 0}},
    )
    _write_json(
        probe_dir / "download-probe.json",
        {
            "project_sample": full_chain["manifest"]["project_sample_items"][0],
            "download_attempts": [
                {
                    "project_id": project_id,
                    "city_code": "440800",
                    "flow_no": "07",
                    "download_url": "https://example.test/oversize-known.pdf",
                    "attachment_url": "https://example.test/oversize-known.pdf",
                    "attachment_name": "oversize-known.pdf",
                    "policy_deferred_reason": "OVERSIZE_DEFERRED_BY_POLICY",
                    "failure_taxonomy": ["OVERSIZE_DEFERRED_BY_POLICY"],
                    "file_size_bytes": 50 * 1024 * 1024,
                    "file_size_url": "https://example.test/size/oversize-known",
                    "download_diagnostics": {
                        "file_size": {
                            "file_size_state": "FILE_SIZE_READY",
                            "file_size_bytes": 50 * 1024 * 1024,
                            "file_size_url": "https://example.test/size/oversize-known",
                        }
                    },
                },
                {
                    "project_id": project_id,
                    "city_code": "440800",
                    "flow_no": "07",
                    "download_url": "https://example.test/oversize-unknown.pdf",
                    "attachment_url": "https://example.test/oversize-unknown.pdf",
                    "attachment_name": "oversize-unknown.pdf",
                    "policy_deferred_reason": "OVERSIZE_DEFERRED_BY_POLICY",
                    "failure_taxonomy": ["OVERSIZE_DEFERRED_BY_POLICY"],
                },
            ],
        },
    )
    _write_json(
        mini / "ygp-evidence-mini-closeout-v1.json",
        {"summary": {"real_download_failure_count": 0, "fake_attachment_count": 0}},
    )
    _write_json(mini / "ygp-city-project-table.json", {"records": []})


def _attachment(name: str, url: str, file_size_bytes: int | None = None, *, flow_no: str = "07", flow_title: str = "中标候选人公示") -> dict[str, Any]:
    payload = {
        "source_field": "noticeFileBOList",
        "file_name": name,
        "link_text": name,
        "download_url": url,
        "flow_no": flow_no,
        "flow_title": flow_title,
    }
    if file_size_bytes is not None:
        payload["file_size_bytes"] = file_size_bytes
        payload["file_size_url"] = f"https://example.test/size/{name}"
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
