from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage3_parsing import markitdown_adapter  # noqa: E402
from storage.guangzhou_parse_probe import build_guangzhou_parse_probe  # noqa: E402


class GuangzhouParseProbeTests(unittest.TestCase):
    def test_parse_probe_uses_markitdown_and_section_slices_without_graph_or_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            output_root = root / "parse"
            _write_download_manifest(input_root)
            text = "\n".join(
                [
                    "一、资格条件",
                    "投标人须提供厂家授权和本地社保。",
                    "二、评分办法",
                    "技术方案主观分占比较高。",
                    "三、技术参数",
                    "检测报告参数组合要求。",
                ]
            )
            repo = FakeReplayRepository(
                {
                    "ATT-03-1": _replay("ATT-03-1", b"%PDF fake", "application/pdf"),
                }
            )
            with patch(
                "storage.guangzhou_parse_probe.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_sha256="text-sha",
                    text_length=len(text),
                    text_probe=text,
                ),
            ) as convert:
                result = build_guangzhou_parse_probe(
                    input_root=input_root,
                    output_root=output_root,
                    project_ids=["JG2026-10815"],
                    flow_nos=["03"],
                    execute=True,
                    object_repository=repo,
                    created_at="2026-05-10T00:00:00+08:00",
                )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["parse_success_count"], 1)
            self.assertEqual(result["summary"]["markitdown_state_counts"][markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED], 1)
            item = result["manifest"]["items"][0]
            self.assertEqual(item["parse_state"], "PARSED_TEXT_PROBE")
            self.assertEqual(item["parse_depth_executed"], "SECTION_PARSE")
            self.assertEqual(item["section_flags"]["section_analysis_state"], "SECTION_CORE_READY")
            self.assertGreaterEqual(item["tailored_signal_profile_summary"]["tailored_bid_signal_count"], 1)
            self.assertFalse(result["manifest"]["safety"]["graphify_enabled"])
            self.assertFalse(result["manifest"]["safety"]["mempalace_enabled"])
            self.assertFalse(result["manifest"]["safety"]["llm_execution_enabled"])
            self.assertTrue((output_root / "parse-probe-manifest.json").exists())
            self.assertTrue(list((output_root / "projects" / "CN-GD").glob("**/parsed/parse-summary.json")))
            convert.assert_called_once()

    def test_bid_file_publicity_is_target_parsed_when_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_download_manifest(input_root, flow_no="08", snapshot_id="ATT-08-1")
            text = "投标文件公开：项目负责人：李四 证书编号：粤1442020202100002"
            with patch(
                "storage.guangzhou_parse_probe.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_sha256="flow08-text-sha",
                    text_length=len(text),
                    text_probe=text,
                ),
            ) as convert:
                result = build_guangzhou_parse_probe(
                    input_root=input_root,
                    output_root=root / "parse",
                    project_ids=["JG2026-10815"],
                    flow_nos=["08"],
                    execute=True,
                    object_repository=FakeReplayRepository(
                        {"ATT-08-1": _replay("ATT-08-1", b"%PDF public", "application/pdf")}
                    ),
                    created_at="2026-05-10T00:00:00+08:00",
                )

            self.assertEqual(result["summary"]["parse_skipped_file_count"], 0)
            self.assertEqual(result["summary"]["parse_success_count"], 1)
            self.assertEqual(result["manifest"]["items"][0]["parse_state"], "PARSED_TEXT_PROBE")
            convert.assert_called_once()

    def test_large_candidate_attachment_is_parsed_instead_of_deferred_by_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_download_manifest(
                input_root,
                flow_no="07",
                snapshot_id="ATT-07-LARGE",
                attachment_url="https://example.test/files/company-bid.pdf",
                byte_size=65_000_000,
            )
            text = "中标候选人：广州测试有限公司\n项目负责人：张三\n证书编号：粤1442020202100001"
            with patch(
                "storage.guangzhou_parse_probe.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_sha256="large-text-sha",
                    text_length=len(text),
                    text_probe=text,
                ),
            ) as convert:
                result = build_guangzhou_parse_probe(
                    input_root=input_root,
                    output_root=root / "parse",
                    project_ids=["JG2026-10815"],
                    flow_nos=["07"],
                    execute=True,
                    object_repository=FakeReplayRepository(
                        {"ATT-07-LARGE": _replay("ATT-07-LARGE", b"%PDF large candidate", "application/pdf")}
                    ),
                    created_at="2026-05-10T00:00:00+08:00",
                )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["parse_state"], "PARSED_TEXT_PROBE")
            self.assertEqual(item["markitdown_state"], markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED)
            self.assertEqual(result["summary"]["parse_skipped_file_count"], 0)
            self.assertNotIn("large_attachment_targeted_parse_deferred", result["summary"]["parse_failure_taxonomy_counts"])
            convert.assert_called_once()

    def test_snapshot_readback_failure_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_download_manifest(input_root)
            result = build_guangzhou_parse_probe(
                input_root=input_root,
                output_root=root / "parse",
                project_ids=["JG2026-10815"],
                flow_nos=["03"],
                execute=True,
                object_repository=FakeReplayRepository(
                    {"ATT-03-1": {"snapshot_id": "ATT-03-1", "replayable": False, "readback_state": "MISSING_OBJECT"}}
                ),
                created_at="2026-05-10T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["parse_state"], "SNAPSHOT_READBACK_FAILED")
            self.assertEqual(item["snapshot_readback_failure"], "MISSING_OBJECT")
            self.assertEqual(result["summary"]["snapshot_readback_failure_counts"]["MISSING_OBJECT"], 1)

    def test_zip_attachment_records_inventory_and_defers_deep_extract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_download_manifest(input_root, snapshot_id="ATT-ZIP-1", attachment_url="https://example.test/files/tender.zip")
            with patch("storage.guangzhou_parse_probe.markitdown_adapter.convert_bytes_to_markdown_text") as convert:
                result = build_guangzhou_parse_probe(
                    input_root=input_root,
                    output_root=root / "parse",
                    project_ids=["JG2026-10815"],
                    flow_nos=["03"],
                    execute=True,
                    object_repository=FakeReplayRepository(
                        {"ATT-ZIP-1": _replay("ATT-ZIP-1", _zip_bytes(), "application/zip")}
                    ),
                    created_at="2026-05-10T00:00:00+08:00",
                )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["parse_state"], "ARCHIVE_INVENTORY_ONLY")
            self.assertEqual(item["archive_inventory"]["member_count"], 1)
            self.assertIn("招标文件.pdf", item["archive_inventory"]["member_name_probes"])
            convert.assert_not_called()

    def test_docx_zip_container_is_parsed_as_document_not_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            _write_download_manifest(input_root, snapshot_id="ATT-DOCX-1", attachment_url="https://example.test/files/tender.docx")
            text = "资格条件：项目负责人须具备注册证书。评分办法：综合评估法。"
            with patch(
                "storage.guangzhou_parse_probe.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_sha256="docx-text-sha",
                    text_length=len(text),
                    text_probe=text,
                ),
            ) as convert:
                result = build_guangzhou_parse_probe(
                    input_root=input_root,
                    output_root=root / "parse",
                    project_ids=["JG2026-10815"],
                    flow_nos=["03"],
                    execute=True,
                    object_repository=FakeReplayRepository(
                        {
                            "ATT-DOCX-1": _replay(
                                "ATT-DOCX-1",
                                _zip_bytes(),
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            )
                        }
                    ),
                    created_at="2026-05-10T00:00:00+08:00",
                )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["parse_state"], "PARSED_TEXT_PROBE")
            self.assertNotIn("archive_inventory", item)
            convert.assert_called_once()

    def test_archive_child_snapshot_generates_stage4_verification_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            archive_root = root / "archive"
            output_root = root / "parse"
            _write_download_manifest(input_root, flow_no="03", snapshot_id="ATT-03-1")
            _write_archive_extract_manifest(archive_root)
            text = "\n".join(
                [
                    "第一中标候选人：广州第一建筑有限公司",
                    "项目负责人：张三",
                    "证书编号：粤1442020202100001",
                    "投标报价：1234.56万元",
                    "评标办法：综合评估法",
                ]
            )
            repo = FakeReplayRepository(
                {
                    "CHILD-07-1": _replay("CHILD-07-1", b"%PDF candidate child", "application/pdf"),
                }
            )
            with patch(
                "storage.guangzhou_parse_probe.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_sha256="child-text-sha",
                    text_length=len(text),
                    text_probe=text,
                ),
            ):
                result = build_guangzhou_parse_probe(
                    input_root=input_root,
                    output_root=output_root,
                    archive_extract_root=archive_root,
                    project_ids=["JG2026-10815"],
                    flow_nos=["07"],
                    execute=True,
                    object_repository=repo,
                    created_at="2026-05-10T00:00:00+08:00",
                )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["parse_success_count"], 1)
            stage4_inputs = result["manifest"]["stage4_candidate_verification_inputs"]
            self.assertEqual(stage4_inputs["summary"]["stage4_input_count"], 1)
            stage4_item = stage4_inputs["items"][0]
            self.assertEqual(stage4_item["candidate_company_name"], "广州第一建筑有限公司")
            self.assertEqual(stage4_item["project_manager_name"], "张三")
            self.assertEqual(stage4_item["project_manager_certificate_no"], "粤1442020202100001")
            self.assertEqual(stage4_item["recommended_stage4_route"], "JZSC_COMPANY_FIRST_PROJECT_MANAGER")
            self.assertTrue((output_root / "stage4_candidate_verification_inputs.json").exists())

    def test_candidate_notice_table_row_extracts_manager_and_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "download"
            output_root = root / "parse"
            _write_download_manifest(
                input_root,
                flow_no="07",
                snapshot_id="ATT-07-1",
                attachment_url="https://example.test/files/candidate.pdf",
            )
            text = "1 广州珠江监理咨询集团有限公司 91440101190668588M 1 1974252.50元 张合力 监理工程师/44012765"
            repo = FakeReplayRepository({"ATT-07-1": _replay("ATT-07-1", b"%PDF candidate", "application/pdf")})
            with patch(
                "storage.guangzhou_parse_probe.markitdown_adapter.convert_bytes_to_markdown_text",
                return_value=markitdown_adapter.MarkItDownText(
                    text=text,
                    state=markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED,
                    text_sha256="candidate-text-sha",
                    text_length=len(text),
                    text_probe=text,
                ),
            ):
                result = build_guangzhou_parse_probe(
                    input_root=input_root,
                    output_root=output_root,
                    project_ids=["JG2026-10815"],
                    flow_nos=["07"],
                    execute=True,
                    object_repository=repo,
                    created_at="2026-05-10T00:00:00+08:00",
                )

            stage4_item = result["manifest"]["stage4_candidate_verification_inputs"]["items"][0]
            self.assertEqual(stage4_item["candidate_company_name"], "广州珠江监理咨询集团有限公司")
            self.assertEqual(stage4_item["project_manager_name"], "张合力")
            self.assertEqual(stage4_item["project_manager_certificate_no"], "44012765")
            self.assertEqual(stage4_item["recommended_stage4_route"], "JZSC_COMPANY_FIRST_PROJECT_MANAGER")


class FakeReplayRepository:
    def __init__(self, snapshots: dict[str, dict]) -> None:
        self.snapshots = snapshots

    def replay_snapshot(self, snapshot_id: str) -> dict:
        return dict(
            self.snapshots.get(
                snapshot_id,
                {"snapshot_id": snapshot_id, "replayable": False, "readback_state": "MISSING_MANIFEST"},
            )
        )


def _write_download_manifest(
    input_root: Path,
    *,
    flow_no: str = "03",
    snapshot_id: str = "ATT-03-1",
    attachment_url: str = "https://example.test/files/tender.pdf",
    byte_size: int = 1024,
) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    project_id = "PROJ-CN-GD-JG2026-10815"
    sample = {
        "target_id": f"DOWNLOAD-PROBE-{flow_no}",
        "parent_target_id": "GUANGZHOU-DOWNLOAD-PROBE-V1",
        "candidate_key": f"STRATEGY-{flow_no}",
        "project_id": project_id,
        "project_name": "广州测试项目",
        "source_url": f"https://example.test/{flow_no}.html",
        "document_kind": "bid_file_publicity" if flow_no == "08" else "tender_file",
        "jurisdiction": "CN-GD",
        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        "pipeline_stage": "DownloadProbe",
        "guangzhou_flow_no": flow_no,
        "guangzhou_flow_title": f"{flow_no}流程",
        "guangzhou_flow_folder": str(input_root / "projects" / "CN-GD" / project_id / f"{flow_no}_流程" / "2026-05-10_广州测试项目"),
        "attachment_snapshot_refs": [
            {
                "snapshot_id": snapshot_id,
                "attachment_url": attachment_url,
                "source_url": attachment_url,
                "parent_source_url": f"https://example.test/{flow_no}.html",
                "attachment_role_type": "BID_FILE_PUBLICITY_SAMPLE" if flow_no == "08" else "TENDER_FILE",
                "attachment_link_text": Path(attachment_url).name,
                "content_type": "application/zip" if attachment_url.endswith(".zip") else "application/pdf",
                "byte_size": byte_size,
            }
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload = {
        "manifest": {
            "manifest_kind": "evaluation_real_project_sample_execution_manifest",
            "sub_kind": "guangzhou_download_probe_manifest",
            "pipeline_stage": "DownloadProbe",
            "project_sample_items": [sample],
            "items": [],
        }
    }
    (input_root / "download-probe-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_archive_extract_manifest(archive_root: Path) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    project_id = "PROJ-CN-GD-JG2026-10815"
    child_ref = {
        "snapshot_id": "CHILD-07-1",
        "child_snapshot_id": "CHILD-07-1",
        "parent_archive_snapshot_id": "ATT-07-ZIP",
        "archive_inner_path": "候选人公示.pdf",
        "source_url": "https://example.test/candidate.zip",
        "attachment_url": "https://example.test/candidate.zip",
        "attachment_link_text": "候选人公示.pdf",
        "attachment_role_type": "CANDIDATE_NOTICE_ATTACHMENT",
        "content_type": "application/pdf",
        "target_fields": ["candidate_company", "project_manager_name", "certificate_no", "bid_price"],
        "stage4_targets": ["project_manager_qualification", "candidate_verification"],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    sample = {
        "target_id": "ARCHIVE-EXTRACT-07-001",
        "parent_target_id": "GUANGZHOU-ARCHIVE-EXTRACT-PROBE-V1",
        "candidate_key": "EVIDENCE-STRATEGY-07-001",
        "project_id": project_id,
        "project_name": "广州测试项目",
        "source_url": "https://example.test/07.html",
        "document_kind": "candidate_notice",
        "jurisdiction": "CN-GD",
        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        "pipeline_stage": "ArchiveExtractProbe",
        "guangzhou_flow_no": "07",
        "guangzhou_flow_title": "中标候选人公示",
        "guangzhou_flow_folder": str(archive_root / "projects" / "CN-GD" / project_id / "07_中标候选人公示" / "2026-05-10_广州测试项目"),
        "parent_archive_snapshot_id": "ATT-07-ZIP",
        "archive_extract_state": "TARGETED_CHILD_SNAPSHOTS_CAPTURED",
        "attachment_snapshot_refs": [child_ref],
        "child_snapshot_refs": [child_ref],
        "child_snapshot_count": 1,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_archive_extract_probe_manifest",
            "pipeline_stage": "ArchiveExtractProbe",
            "project_sample_items": [sample],
            "items": [],
        }
    }
    (archive_root / "archive-extract-probe-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _replay(snapshot_id: str, data: bytes, content_type: str) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "replayable": True,
        "readback_state": "READBACK_READY",
        "content_type": content_type,
        "byte_size": len(data),
        "sha256": "sha",
        "bytes": data,
        "object_key": f"objects/{snapshot_id}",
        "manifest": {"source_url_optional": "https://example.test/file.pdf", "lineage_refs": {"project_id": "PROJ"}},
    }


def _zip_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("招标文件.pdf", b"%PDF fake")
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
