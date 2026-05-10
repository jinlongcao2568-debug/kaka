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

from shared.settings import Settings  # noqa: E402
from storage.db import DatabaseSession  # noqa: E402
from storage.professional_clean_project_archive import (  # noqa: E402
    build_professional_clean_project_archive_manifest,
)
from storage.repositories.object_storage_repo import ObjectStorageRepository  # noqa: E402


CONTRACT_PATH = ROOT / "contracts" / "evaluation" / "guangzhou_12_flow_golden_projects.json"


class TestGuangzhou12FlowGoldenContract(unittest.TestCase):
    def test_contract_pins_jg2026_10815_as_guangzhou_only_golden_sample(self) -> None:
        contract = _load_contract()
        project = contract["projects"][0]

        self.assertEqual(contract["scope"], "GUANGZHOU_YWTB_POST_CANDIDATE_BACKTRACE")
        self.assertEqual(contract["source_profile_id"], "GUANGZHOU-YWTB-CONSTRUCTION-LIST")
        self.assertIn("trade_purchasetoplen6.html", contract["official_entry_url"])
        self.assertEqual(project["project_code"], "JG2026-10815")
        self.assertEqual(project["expected_present_flow_nos"], ["03", "05", "06", "07", "08"])
        self.assertEqual(project["expected_missing_flow_nos"], ["01", "02", "04", "09", "10", "11", "12"])
        self.assertEqual(project["expected_attachment_count"], 28)
        self.assertFalse(contract["customer_visible_allowed"])
        self.assertTrue(contract["no_legal_conclusion"])

    def test_jg2026_10815_archive_keeps_flow_counts_dates_and_urls(self) -> None:
        contract = _load_contract()
        project = contract["projects"][0]
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            samples = _golden_samples(repo=repo, project=project, contract=contract)
            execution_path = Path(tmp_dir) / "run-manifest.json"
            output_root = Path(tmp_dir) / "archive"
            execution_path.write_text(
                json.dumps({"manifest": {"project_sample_items": samples}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = build_professional_clean_project_archive_manifest(
                real_sample_execution_manifest_json=execution_path,
                output_root=output_root,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            audit = result["manifest"]["items"][0]
            self.assertEqual(audit["project_id"], project["project_id"])
            self.assertEqual(audit["detail_file_count"], project["expected_detail_count"])
            self.assertEqual(audit["attachment_file_count"], project["expected_attachment_count"])
            self.assertEqual(audit["replayable_file_count"], project["expected_replayable_file_count"])
            self.assertEqual(
                [item["flow_no"] for item in audit["guangzhou_flow_modules_present"]],
                project["expected_present_flow_nos"],
            )
            self.assertEqual(
                [item["flow_no"] for item in audit["guangzhou_flow_modules_missing"]],
                project["expected_missing_flow_nos"],
            )

            by_flow = _flow_inventory_counts(audit["guangzhou_flow_inventory"])
            for expectation in project["flow_expectations"]:
                flow_no = expectation["flow_no"]
                self.assertIn(flow_no, by_flow)
                self.assertEqual(by_flow[flow_no]["details"], expectation["expected_detail_count"])
                self.assertEqual(by_flow[flow_no]["attachments"], expectation["expected_attachment_count"])
                for detail in expectation["details"]:
                    self.assertIn(detail["published_date"], by_flow[flow_no]["dates"])
                    self.assertIn(detail["source_url"], audit["verification_urls"]["project_source_urls"])

            self.assertGreaterEqual(by_flow["03"]["details"], 2)
            self.assertEqual(by_flow["03"]["attachments"], 20)
            for flow_no in project["must_have_flow_nos"]:
                self.assertIn(flow_no, by_flow)
            self.assertEqual(audit["post_candidate_entry_state"], "POST_CANDIDATE_ENTRY_PRESENT")
            self.assertEqual(audit["backtrace_completeness_state"], "BACKTRACE_PARTIAL")
            self.assertEqual(audit["guangzhou_flow_completeness_state"], "GUANGZHOU_FLOW_PARTIAL")

            project_dir = Path(audit["project_dir"])
            self.assertTrue((project_dir / "flow" / "flow-index.json").exists())
            self.assertTrue((project_dir / "03_招标公告_关联公告").exists())
            self.assertTrue((project_dir / "08_投标_资格预审申请_文件公开").exists())
            self.assertTrue(
                any(
                    item["flow_no"] == "03"
                    and item["published_date"] == "2026-03-17"
                    and "03_招标公告_关联公告" in item["primary_flow_directory"]
                    and Path(item["copied_file_path"]).exists()
                    for item in audit["guangzhou_flow_inventory"]
                )
            )
            self.assertTrue(
                any(
                    item["flow_no"] == "08"
                    and item["published_date"] == "2026-05-10"
                    and Path(item["copied_file_path"]).exists()
                    for item in audit["guangzhou_flow_inventory"]
                )
            )


def _load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _repo(tmp_dir: str) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(Path(tmp_dir) / "storage.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(Path(tmp_dir) / "objects"),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def _golden_samples(
    *,
    repo: ObjectStorageRepository,
    project: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    flow_code_by_no = {
        str(module["flow_no"]): str(module.get("flow_code") or "")
        for module in contract["flow_modules"]
    }
    samples: list[dict[str, Any]] = []
    for expectation in project["flow_expectations"]:
        flow_no = str(expectation["flow_no"])
        flow_title = str(expectation["flow_title"])
        document_kind = str(expectation["document_kind"])
        flow_code = flow_code_by_no.get(flow_no, "")
        for detail_index, detail in enumerate(expectation["details"], start=1):
            detail_snapshot_id = f"SNAP-{project['project_code']}-{flow_no}-D{detail_index}"
            source_url = str(detail["source_url"])
            _save_snapshot(
                repo,
                snapshot_id=detail_snapshot_id,
                data=f"<html><body>{project['project_name']} {flow_title}</body></html>".encode("utf-8"),
                content_type="text/html",
                source_url=source_url,
            )
            attachment_refs: list[dict[str, Any]] = []
            for attach_index in range(1, int(detail["expected_attachment_count"]) + 1):
                attachment_snapshot_id = (
                    f"SNAP-{project['project_code']}-{flow_no}-D{detail_index}-A{attach_index}"
                )
                attachment_url = f"{source_url}?mockAttachment={attach_index}"
                _save_snapshot(
                    repo,
                    snapshot_id=attachment_snapshot_id,
                    data=b"%PDF-1.4\n% golden fixture attachment\n",
                    content_type="application/pdf",
                    source_url=attachment_url,
                )
                attachment_refs.append(
                    {
                        "snapshot_id": attachment_snapshot_id,
                        "source_url": attachment_url,
                        "attachment_url": attachment_url,
                        "attachment_link_text": f"{flow_title}附件{attach_index}",
                        "attachment_role_type": "TENDER_FILE"
                        if document_kind == "tender_file"
                        else "POST_TENDER_ATTACHMENT",
                    }
                )
            samples.append(
                {
                    "target_id": f"GZ-GOLDEN-{project['project_code']}-{flow_no}-{detail_index}",
                    "parent_target_id": f"GZ-GOLDEN-{project['project_code']}-{flow_no}",
                    "candidate_key": f"{project['project_code']}-{flow_no}-{detail_index}",
                    "project_id": str(project["project_id"]),
                    "project_name": str(project["project_name"]),
                    "source_url": source_url,
                    "document_kind": document_kind,
                    "jurisdiction": "CN-GD",
                    "source_profile_id": contract["source_profile_id"],
                    "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
                    "document_completeness_state": "COMPLETE_WITH_ATTACHMENTS",
                    "notice_version_chain_state": "SUPPLEMENT_PRESENT"
                    if detail_index > 1 and document_kind == "tender_file"
                    else "NO_SUPPLEMENT_DETECTED",
                    "published_at_optional": detail["published_date"],
                    "source_project_code": str(project["project_code"]),
                    "project_match_key": str(project["project_code"]),
                    "matched_project_keys": [str(project["project_code"])],
                    "base_project_name": str(project["project_name"]),
                    "backtrace_query_variants": [str(project["project_code"]), str(project["project_name"])],
                    "backtrace_match_reason": "relation_guid_exact_match",
                    "guangzhou_flow_no": flow_no,
                    "guangzhou_flow_title": flow_title,
                    "guangzhou_flow_code": flow_code,
                    "guangzhou_flow_folder": f"{flow_no}_{flow_title}",
                    "source_text": f"{project['project_name']}\n{flow_title}\n资格条件\n评分办法\n技术参数",
                    "detail_snapshot_refs": [{"snapshot_id": detail_snapshot_id, "source_url": source_url}],
                    "attachment_snapshot_refs": attachment_refs,
                    "parse_summary": {
                        "stage3_parse_success_count": 1,
                        "stage3_parse_failed_count": 0,
                        "attachment_missing_review_count": 0,
                        "unknown_attachment_count": 0,
                        "text_probe": f"{project['project_name']}\n{flow_title}\n资格条件\n评分办法\n技术参数",
                    },
                    "failure_taxonomy": [],
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return samples


def _save_snapshot(
    repo: ObjectStorageRepository,
    *,
    snapshot_id: str,
    data: bytes,
    content_type: str,
    source_url: str,
) -> None:
    repo.save_snapshot(
        data,
        snapshot_id=snapshot_id,
        snapshot_kind="guangzhou_golden_test_snapshot",
        content_type=content_type,
        source_url_optional=source_url,
        source_family_optional="guangzhou_ywtb_golden",
        lineage_refs={"project_id": "PROJ-CN-GD-JG2026-10815"},
    )


def _flow_inventory_counts(items: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        flow_no = str(item.get("flow_no") or "")
        if not flow_no:
            continue
        bucket = result.setdefault(flow_no, {"details": 0, "attachments": 0, "dates": set()})
        if item.get("file_role") == "detail":
            bucket["details"] += 1
        if item.get("file_role") == "attachment":
            bucket["attachments"] += 1
        if item.get("published_date"):
            bucket["dates"].add(str(item["published_date"]))
    return result


if __name__ == "__main__":
    unittest.main()
