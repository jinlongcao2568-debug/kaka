from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.evidence_verification_strategy import build_evidence_verification_strategy  # noqa: E402


class EvidenceVerificationStrategyTests(unittest.TestCase):
    def test_candidate_notice_zip_gets_project_manager_verification_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            output_root = root / "strategy"
            _write_download_manifest(input_root, flow_no="07", snapshot_id="ATT-07-ZIP", attachment_url="https://example.test/candidate.zip")

            result = build_evidence_verification_strategy(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            item = result["manifest"]["items"][0]
            self.assertEqual(item["extract_policy"], "TARGETED_EXTRACT")
            self.assertEqual(item["parse_policy"], "TEXT_PROBE")
            self.assertIn("project_manager_qualification", item["stage4_targets"])
            self.assertIn("certificate_no", item["target_fields"])
            self.assertEqual(result["summary"]["targeted_extract_count"], 1)
            self.assertTrue((output_root / "evidence-verification-strategy.json").exists())

    def test_adapter_validation_only_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            output_root = root / "strategy"
            _write_download_manifest(input_root, flow_no="03", adapter_validation_only=True)

            result = build_evidence_verification_strategy(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertFalse(item["verification_enabled"])
            self.assertEqual(item["extract_policy"], "SKIP")
            self.assertEqual(item["skip_reason"], "adapter_validation_only_not_evidence_package_input")

    def test_flow_08_defaults_to_register_only_until_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            output_root = root / "strategy"
            _write_download_manifest(
                input_root,
                flow_no="08",
                snapshot_id="ATT-08-ZIP",
                attachment_url="https://example.test/bid-publicity.zip",
            )

            result = build_evidence_verification_strategy(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["strategy_state"], "FLOW_08_REGISTER_ONLY")
            self.assertFalse(item["verification_enabled"])
            self.assertEqual(item["extract_policy"], "INVENTORY_ONLY")
            self.assertEqual(item["parse_policy"], "SKIP")
            self.assertEqual(
                item["skip_reason"],
                "flow_08_registered_only_until_stage4_or_public_registration_trigger",
            )

    def test_flow_08_targeted_parse_can_be_explicitly_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            output_root = root / "strategy"
            _write_download_manifest(
                input_root,
                flow_no="08",
                snapshot_id="ATT-08-ZIP",
                attachment_url="https://example.test/bid-publicity.zip",
                flow_08_targeted_parse_required=True,
            )

            result = build_evidence_verification_strategy(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["strategy_state"], "TARGETED_BID_PUBLICITY_SAMPLE_READY")
            self.assertTrue(item["verification_enabled"])
            self.assertEqual(item["parse_policy"], "TEXT_PROBE_THEN_TARGETED_DEEP_PARSE")


def _write_download_manifest(
    input_root: Path,
    *,
    flow_no: str,
    snapshot_id: str = "ATT-03-ZIP",
    attachment_url: str = "https://example.test/tender.zip",
    adapter_validation_only: bool = False,
    flow_08_targeted_parse_required: bool = False,
) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    sample = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "source_url": f"https://example.test/{flow_no}.html",
        "document_kind": "candidate_notice" if flow_no == "07" else "tender_file",
        "pipeline_stage": "DownloadProbe",
        "guangzhou_flow_no": flow_no,
        "guangzhou_flow_title": f"{flow_no}流程",
        "adapter_validation_only": adapter_validation_only,
        "flow_08_targeted_parse_required": flow_08_targeted_parse_required,
        "attachment_snapshot_refs": [
            {
                "snapshot_id": snapshot_id,
                "attachment_url": attachment_url,
                "source_url": attachment_url,
                "attachment_role_type": "CANDIDATE_NOTICE_ATTACHMENT" if flow_no == "07" else "TENDER_FILE",
                "attachment_link_text": Path(attachment_url).name,
                "content_type": "application/zip",
                "byte_size": 100,
            }
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload = {
        "manifest": {
            "manifest_kind": "evaluation_real_project_sample_execution_manifest",
            "source_input_root": str(input_root),
            "project_sample_items": [sample],
        }
    }
    (input_root / "download-probe-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
