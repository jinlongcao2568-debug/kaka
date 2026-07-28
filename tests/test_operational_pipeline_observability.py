from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.operational_observability import load_operational_events, reset_operational_event_sinks
from stage2_ingestion.real_public_url_fetcher import (
    REAL_PUBLIC_ENTRY_PROFILE_BY_ID,
    RealPublicEntryFetcher,
    RealPublicFetchResponse,
)
from stage3_parsing.real_parser import Stage3RealParser
from stage7_sales.fixed_sku_evidence_bundle import build_fixed_sku_evidence_bundle
from storage.sqlalchemy_backend import SQLAlchemyStorageBackend


class _OneResponseTransport:
    def __init__(self, response: RealPublicFetchResponse) -> None:
        self.response = response

    def fetch(self, url: str, *, timeout_seconds: float, user_agent: str) -> RealPublicFetchResponse:
        del url, timeout_seconds, user_agent
        return self.response


class OperationalPipelineObservabilityTests(unittest.TestCase):
    def test_stage1_first_cold_import_does_not_cycle_through_runtime_package(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from stage1_tasking.source_blueprint import "
                    "Stage1SourceBlueprintOrchestrator; "
                    "from stage2_ingestion.real_public_url_fetcher import RealPublicEntryFetcher; "
                    "assert Stage1SourceBlueprintOrchestrator and RealPublicEntryFetcher"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_fetch_parse_database_and_delivery_events_share_one_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            event_path = Path(tmp_dir) / "runtime" / "events.jsonl"
            with patch.dict(
                os.environ,
                {
                    "KAKA_OBSERVABILITY_ENABLED": "true",
                    "KAKA_OBSERVABILITY_EVENT_PATH": str(event_path),
                    "KAKA_OBSERVABILITY_SERVICE_NAME": "pipeline-test",
                    "KAKA_OBSERVABILITY_STDOUT_ENABLED": "false",
                },
                clear=False,
            ):
                reset_operational_event_sinks()
                profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID["GGZY-DEAL-LIST"]
                title = profile.expected_title_contains or profile.site_name
                visible = " ".join(profile.visible_entry_markers)
                body = (
                    f"<html><head><title>{title}</title></head><body>{visible}"
                    + ("公开交易公告 " * 80)
                    + "</body></html>"
                ).encode("utf-8")
                fetch_carrier = RealPublicEntryFetcher(
                    transport=_OneResponseTransport(
                        RealPublicFetchResponse(
                            url=profile.url,
                            status_code=200,
                            content=body,
                            content_type="text/html; charset=utf-8",
                            final_url=profile.url,
                        )
                    )
                ).fetch_entry_url(profile.url, profile_id=profile.profile_id)

                parse_bytes = (
                    "<html><body><table><tr><th>项目名称</th>"
                    "<td>受控监控演练项目</td></tr></table></body></html>"
                ).encode("utf-8")
                parse_carrier = Stage3RealParser().parse_readback(
                    {
                        "replayable": True,
                        "snapshot_id": "SNAP-OPS004-DRILL",
                        "content_type": "text/html; charset=utf-8",
                        "bytes": parse_bytes,
                        "sha256": hashlib.sha256(parse_bytes).hexdigest(),
                        "manifest": {
                            "snapshot_id": "SNAP-OPS004-DRILL",
                            "source_url_optional": "https://example.gov.cn/notice/1",
                        },
                    }
                )

                backend = SQLAlchemyStorageBackend(
                    "sqlite:///:memory:",
                    storage_backend="sqlalchemy",
                )
                backend.close()

                bundle = build_fixed_sku_evidence_bundle(
                    {
                        "商机编号": "OPP-OPS004-DRILL",
                        "数据真实性边界": {"是否离线样本": True},
                        "公开来源验证": {"公开来源网址": ""},
                        "证据包": {"版本哈希": "sha256:" + "a" * 64},
                        "证据项清单": [],
                    },
                    approval_audit={
                        "审批对象版本一致": True,
                        "职责分离已满足": True,
                    },
                    generated_at="2026-07-20T00:00:00+00:00",
                )
                events = load_operational_events(event_path, limit=10_000)
                reset_operational_event_sinks()

        self.assertEqual(fetch_carrier["status"], "FETCHED")
        self.assertEqual(parse_carrier["parse_state"], "PARSED")
        self.assertEqual(
            bundle["manifest"]["issuance_control"]["manual_signoff_state"],
            "BLOCKED_BEFORE_HUMAN_SIGNOFF",
        )
        components = {str(event.get("component")) for event in events}
        self.assertTrue({"fetch", "parse", "database", "delivery"}.issubset(components))
        fetch_event = next(event for event in events if event.get("component") == "fetch")
        self.assertEqual(fetch_event["attributes"]["url_host"], "www.ggzy.gov.cn")
        self.assertNotIn(profile.url, str(fetch_event))
        database_events = [event for event in events if event.get("component") == "database"]
        self.assertTrue(any(event.get("operation") == "sql_statement" for event in database_events))
        self.assertTrue(any(event.get("operation") == "storage_initialize" for event in database_events))


if __name__ == "__main__":
    unittest.main()
