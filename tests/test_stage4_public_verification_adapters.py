from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings
from stage2_ingestion.real_public_url_fetcher import (
    REAL_PUBLIC_ENTRY_PROFILE_BY_ID,
    RealPublicFetchResponse,
)
from stage2_ingestion.service import Stage2Service
from stage3_parsing.real_parser import UNVERIFIED_STATE
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage4_verification.verification import (
    AMBIGUOUS_PUBLIC_MATCH,
    MATCHED,
    PROVIDER_RESERVED_NOT_LIVE,
    PUBLIC_VERIFICATION_FAILURE_TAXONOMY,
    SNAPSHOT_NOT_REPLAYABLE,
    SOURCE_CONFLICT,
    SUPPORTED_PUBLIC_VERIFICATION_TARGET_TYPES,
    TARGET_IDENTIFIER_MISSING,
    WEAK_PUBLIC_EVIDENCE,
)
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


class Stage4PublicVerificationAdapterTests(unittest.TestCase):
    def _repo(self, tmp_dir: str) -> ObjectStorageRepository:
        settings = Settings(
            storage_backend="json-file",
            storage_path_optional=str(Path(tmp_dir) / "stage4-public-verification.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(Path(tmp_dir) / "objects"),
        )
        return ObjectStorageRepository(
            session=DatabaseSession(settings=settings),
            settings=settings,
        )

    def _carrier(
        self,
        *,
        repo: ObjectStorageRepository,
        snapshot_id: str,
        identifier: str,
        target_type: str,
        confidence: float = 0.91,
        visibility: str = "PUBLIC_VISIBLE",
        source_url: str = "https://example.invalid/public/record.html",
        review_required: bool = False,
    ) -> dict[str, object]:
        body = (
            f"<html><body><table><tr><td>{target_type}</td>"
            f"<td>{identifier}</td></tr></table></body></html>"
        ).encode("utf-8")
        repo.save_snapshot(
            body,
            snapshot_id=snapshot_id,
            snapshot_kind="stage2_public_source_snapshot",
            content_type="text/html",
            source_url_optional=source_url,
            source_family_optional="public_verification_fixture",
            source_visibility_state=visibility,
            raw_snapshot_metadata={
                "snapshot_id": snapshot_id,
                "source_url": source_url,
                "source_family": "public_verification_fixture",
                "source_registry_id": f"SRC-{target_type.upper()}",
                "source_visibility_state": visibility,
            },
            lineage_refs={
                "source_registry_id": f"SRC-{target_type.upper()}",
                "source_family": "public_verification_fixture",
            },
        )
        return {
            "parse_run_id": f"PARSE-{snapshot_id}",
            "snapshot_id": snapshot_id,
            "source_url": source_url,
            "source_family": "public_verification_fixture",
            "source_registry_id": f"SRC-{target_type.upper()}",
            "content_type": "text/html",
            "attachment_type": "HTML",
            "parser_family": "html",
            "parser_version": "stage3-real-parser-v1",
            "parser_mode": "DETERMINISTIC_READBACK",
            "parse_state": "PARSED",
            "verification_state": UNVERIFIED_STATE,
            "stage4_verification_required": True,
            "customer_visible": False,
            "parsed_fields": [
                {
                    "field_name": "public_identifier",
                    "field_value_optional": identifier,
                    "source_page_optional": None,
                    "source_file_ref": snapshot_id,
                    "source_slice": f"{target_type}: {identifier}",
                    "source_slice_sha256": f"SHA-{snapshot_id}",
                    "raw_text": f"{target_type}: {identifier}",
                    "locator": {"type": "unit_test"},
                    "confidence": confidence,
                    "parser_version": "stage3-real-parser-v1",
                    "review_required": review_required,
                    "parse_warnings": [],
                }
            ],
            "parser_audit": {"input_snapshot_id": snapshot_id},
            "parse_error_taxonomy": [],
            "review_required": review_required,
        }

    def _verify(
        self,
        *,
        repo: ObjectStorageRepository,
        carrier: dict[str, object],
        target_type: str,
        identifier: str,
        **target_overrides: object,
    ) -> dict[str, object]:
        target = {
            "verification_target_id": f"TARGET-{target_type}",
            "verification_target_type": target_type,
            "target_identifier": identifier,
        }
        target.update(target_overrides)
        return dict(
            Stage4Service().verify_public_parsed_carrier(
                carrier,
                target=target,
                repository=repo,
            )
        )

    def test_happy_carriers_cover_required_public_verification_directions(self) -> None:
        directions = (
            "enterprise_public_record",
            "personnel_public_record",
            "enterprise_qualification",
            "credit_penalty_blacklist",
            "construction_permit",
            "contract_public_info",
            "completion_filing",
            "performance_public_record",
        )
        self.assertEqual(set(directions), set(SUPPORTED_PUBLIC_VERIFICATION_TARGET_TYPES))

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            for index, target_type in enumerate(directions, start=1):
                with self.subTest(target_type=target_type):
                    identifier = f"PUBLIC-ID-{index:02d}"
                    carrier = self._carrier(
                        repo=repo,
                        snapshot_id=f"SNAP-ST4-{index:02d}",
                        identifier=identifier,
                        target_type=target_type,
                    )

                    result = self._verify(
                        repo=repo,
                        carrier=carrier,
                        target_type=target_type,
                        identifier=identifier,
                    )

                    self.assertEqual(result["verification_result"], MATCHED)
                    self.assertEqual(result["verification_target_type"], target_type)
                    self.assertEqual(result["input_parse_run_id"], carrier["parse_run_id"])
                    self.assertEqual(result["source_snapshot_id"], carrier["snapshot_id"])
                    self.assertEqual(result["source_url"], carrier["source_url"])
                    self.assertEqual(result["public_visibility_state"], "PUBLIC_VISIBLE")
                    self.assertEqual(result["verification_provider"], "stage4-public-verification-readback")
                    self.assertEqual(result["provider_version"], "stage4-public-verification-adapter-v1")
                    self.assertEqual(result["evidence_grade"], "PUBLIC_SNAPSHOT_FIELD_MATCH")
                    self.assertGreaterEqual(result["confidence"], 0.9)
                    self.assertFalse(result["review_required"])
                    self.assertTrue(result["public_only"])
                    self.assertFalse(result["customer_visible"])
                    self.assertTrue(result["no_legal_conclusion"])
                    self.assertIsNone(result["failure_reason_optional"])
                    self.assertEqual(result["parsed_field_refs"][0]["field_value_optional"], identifier)
                    self.assertEqual(result["source_refs"][0]["stage3_verification_state"], UNVERIFIED_STATE)
                    self.assertTrue(result["snapshot_refs"][0]["replayable"])
                    readback = Stage4Service().build_public_verification_readback(result)
                    self.assertEqual(readback["readback_state"], "READBACK_READY")
                    self.assertTrue(readback["replayable"])

    def test_real_public_stage3_parsed_carrier_enters_stage4_verification_readback(self) -> None:
        profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID["GGZY-DEAL-LIST"]
        html = _real_public_verification_html(
            profile_id=profile.profile_id,
            target_type="enterprise_public_record",
            identifier="REAL-PUBLIC-VERIFY-001",
        )
        transport = _FakeRealPublicFetchTransport(
            {
                profile.url: RealPublicFetchResponse(
                    url=profile.url,
                    status_code=200,
                    content=html,
                    content_type="text/html; charset=utf-8",
                    final_url=profile.url,
                    headers={"x-ax9s-fetch-transport": "unit_controlled_transport"},
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            stage2_carrier = Stage2Service().fetch_real_public_entry_url(
                profile.url,
                profile_id=profile.profile_id,
                repository=repo,
                transport=transport,
                lineage_refs={
                    "source_blueprint_batch_id": "PTL-I100-139",
                    "entry_profile_id": profile.profile_id,
                },
            )
            self.assertEqual(stage2_carrier["status"], "FETCHED")
            snapshot_id = stage2_carrier["snapshot_id_optional"]
            parsed = dict(Stage3Service().parse_raw_snapshot(snapshot_id, repository=repo))
            self.assertEqual(parsed["verification_state"], UNVERIFIED_STATE)
            self.assertFalse(parsed["customer_visible"])

            result = dict(
                Stage4Service().verify_public_parsed_carrier(
                    parsed,
                    target={
                        "verification_target_id": "TARGET-REAL-PUBLIC-001",
                        "verification_target_type": "enterprise_public_record",
                        "target_identifier": "REAL-PUBLIC-VERIFY-001",
                    },
                    repository=repo,
                )
            )

            self.assertEqual(result["verification_result"], MATCHED)
            self.assertEqual(result["input_parse_run_id"], parsed["parse_run_id"])
            self.assertEqual(result["source_snapshot_id"], snapshot_id)
            self.assertEqual(result["source_url"], profile.url)
            self.assertEqual(result["public_visibility_state"], "PUBLIC_VISIBLE")
            self.assertEqual(result["evidence_grade"], "PUBLIC_SNAPSHOT_FIELD_MATCH")
            self.assertGreaterEqual(result["confidence"], 0.8)
            self.assertFalse(result["review_required"])
            self.assertTrue(result["public_only"])
            self.assertFalse(result["customer_visible"])
            self.assertTrue(result["no_legal_conclusion"])
            self.assertTrue(result["snapshot_refs"][0]["replayable"])
            self.assertEqual(result["snapshot_refs"][0]["snapshot_id"], snapshot_id)
            parsed_ref = result["parsed_field_refs"][0]
            self.assertEqual(parsed_ref["field_value_optional"], "REAL-PUBLIC-VERIFY-001")
            self.assertEqual(parsed_ref["parser_version"], parsed["parser_version"])
            readback = Stage4Service().build_public_verification_readback(result)
            self.assertEqual(readback["readback_state"], "READBACK_READY")
            self.assertTrue(readback["replayable"])
            self.assertFalse(readback["customer_visible"])
            self.assertNotIn("rule_hit", result)
            self.assertNotIn("stage6_project_fact", result)
            self.assertNotIn("customer_material", result)

    def test_real_public_stage4_verification_fails_closed_for_missing_identifier(self) -> None:
        profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID["BEIJING-PLATFORM-HOME"]
        html = _real_public_verification_html(
            profile_id=profile.profile_id,
            target_type="contract_public_info",
            identifier="CONTRACT-PUBLIC-139",
        )
        transport = _FakeRealPublicFetchTransport(
            {
                profile.url: RealPublicFetchResponse(
                    url=profile.url,
                    status_code=200,
                    content=html,
                    content_type="text/html; charset=utf-8",
                    final_url=profile.url,
                    headers={"x-ax9s-fetch-transport": "unit_controlled_transport"},
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            stage2_carrier = Stage2Service().fetch_real_public_entry_url(
                profile.url,
                profile_id=profile.profile_id,
                repository=repo,
                transport=transport,
                lineage_refs={"source_blueprint_batch_id": "PTL-I100-139"},
            )
            parsed = dict(
                Stage3Service().parse_raw_snapshot(
                    stage2_carrier["snapshot_id_optional"],
                    repository=repo,
                )
            )
            result = dict(
                Stage4Service().verify_public_parsed_carrier(
                    parsed,
                    target={
                        "verification_target_id": "TARGET-MISSING-ID",
                        "verification_target_type": "contract_public_info",
                        "target_identifier": "",
                    },
                    repository=repo,
                )
            )

            self.assertEqual(result["failure_reason_optional"], TARGET_IDENTIFIER_MISSING)
            self.assertEqual(result["verification_result"], "REVIEW_REQUIRED")
            self.assertTrue(result["review_required"])
            self.assertFalse(result["customer_visible"])
            self.assertTrue(result["snapshot_refs"][0]["replayable"])
            readback = Stage4Service().build_public_verification_readback(result)
            self.assertEqual(readback["readback_state"], "READBACK_READY")

    def test_missing_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            carrier = {
                "parse_run_id": "PARSE-MISSING-SNAPSHOT",
                "snapshot_id": "SNAP-ST4-MISSING",
                "source_url": "https://example.invalid/public/missing.html",
                "verification_state": UNVERIFIED_STATE,
                "customer_visible": False,
                "parsed_fields": [
                    {
                        "field_name": "public_identifier",
                        "field_value_optional": "MISSING-SNAPSHOT-ID",
                        "source_file_ref": "SNAP-ST4-MISSING",
                        "source_slice": "identifier: MISSING-SNAPSHOT-ID",
                        "source_slice_sha256": "SHA-MISSING",
                        "confidence": 0.91,
                        "parser_version": "stage3-real-parser-v1",
                        "review_required": False,
                    }
                ],
            }

            result = self._verify(
                repo=repo,
                carrier=carrier,
                target_type="enterprise_public_record",
                identifier="MISSING-SNAPSHOT-ID",
            )

            self.assertEqual(result["failure_reason_optional"], SNAPSHOT_NOT_REPLAYABLE)
            self.assertEqual(result["verification_result"], "INSUFFICIENT_PUBLIC_EVIDENCE")
            self.assertEqual(result["evidence_grade"], "NO_REPLAYABLE_PUBLIC_SNAPSHOT")
            self.assertTrue(result["review_required"])
            self.assertTrue(result["snapshot_refs"][0]["no_broad_fallback"])

    def test_missing_identifier_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            carrier = self._carrier(
                repo=repo,
                snapshot_id="SNAP-ST4-NO-ID",
                identifier="EXISTING-ID",
                target_type="enterprise_public_record",
            )

            result = self._verify(
                repo=repo,
                carrier=carrier,
                target_type="enterprise_public_record",
                identifier="",
            )

            self.assertEqual(result["failure_reason_optional"], TARGET_IDENTIFIER_MISSING)
            self.assertEqual(result["verification_result"], "REVIEW_REQUIRED")
            self.assertTrue(result["review_required"])

    def test_ambiguous_conflicting_and_weak_evidence_degrade_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            ambiguous = self._carrier(
                repo=repo,
                snapshot_id="SNAP-ST4-AMBIG",
                identifier="AMBIG-ID",
                target_type="personnel_public_record",
            )
            conflict = self._carrier(
                repo=repo,
                snapshot_id="SNAP-ST4-CONFLICT",
                identifier="CONFLICT-ID",
                target_type="contract_public_info",
            )
            weak = self._carrier(
                repo=repo,
                snapshot_id="SNAP-ST4-WEAK",
                identifier="WEAK-ID",
                target_type="performance_public_record",
                confidence=0.61,
            )

            ambiguous_result = self._verify(
                repo=repo,
                carrier=ambiguous,
                target_type="personnel_public_record",
                identifier="AMBIG-ID",
                ambiguous_public_match=True,
            )
            conflict_result = self._verify(
                repo=repo,
                carrier=conflict,
                target_type="contract_public_info",
                identifier="CONFLICT-ID",
                source_conflict=True,
            )
            weak_result = self._verify(
                repo=repo,
                carrier=weak,
                target_type="performance_public_record",
                identifier="WEAK-ID",
            )

            self.assertEqual(ambiguous_result["failure_reason_optional"], AMBIGUOUS_PUBLIC_MATCH)
            self.assertEqual(ambiguous_result["verification_result"], "REVIEW_REQUIRED")
            self.assertEqual(conflict_result["failure_reason_optional"], SOURCE_CONFLICT)
            self.assertEqual(conflict_result["verification_result"], "CONFLICT")
            self.assertEqual(weak_result["failure_reason_optional"], WEAK_PUBLIC_EVIDENCE)
            self.assertEqual(weak_result["verification_result"], "INSUFFICIENT_PUBLIC_EVIDENCE")
            for result in (ambiguous_result, conflict_result, weak_result):
                self.assertTrue(result["review_required"])
                self.assertFalse(result["customer_visible"])
                self.assertTrue(result["no_legal_conclusion"])

    def test_reserved_provider_fails_closed_without_using_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            provider_requested = self._carrier(
                repo=repo,
                snapshot_id="SNAP-ST4-PROVIDER",
                identifier="PROVIDER-ID",
                target_type="enterprise_public_record",
            )

            provider_result = self._verify(
                repo=repo,
                carrier=provider_requested,
                target_type="enterprise_public_record",
                identifier="PROVIDER-ID",
                verification_provider="reserved-live-provider",
            )

            self.assertEqual(provider_result["failure_reason_optional"], PROVIDER_RESERVED_NOT_LIVE)
            self.assertEqual(provider_result["verification_provider"], "stage4-public-verification-readback")
            self.assertTrue(provider_result["review_required"])

    def test_stage4_adapter_keeps_parser_unverified_internal_only_and_does_not_import_stage5_to_9(self) -> None:
        for code in (
            SNAPSHOT_NOT_REPLAYABLE,
            "PARSED_FIELD_UNVERIFIED",
            TARGET_IDENTIFIER_MISSING,
            AMBIGUOUS_PUBLIC_MATCH,
            SOURCE_CONFLICT,
            WEAK_PUBLIC_EVIDENCE,
            PROVIDER_RESERVED_NOT_LIVE,
        ):
            self.assertIn(code, PUBLIC_VERIFICATION_FAILURE_TAXONOMY)

        service_text = (SRC / "stage4_verification" / "service.py").read_text(encoding="utf-8")
        verification_text = (SRC / "stage4_verification" / "verification.py").read_text(encoding="utf-8")
        combined = service_text + "\n" + verification_text
        for forbidden in (
            "stage5_rules_evidence",
            "stage6_fact_review",
            "stage7_sales",
            "stage8_outreach",
            "stage9_delivery",
        ):
            self.assertNotIn(forbidden, combined)


class _FakeRealPublicFetchTransport:
    def __init__(self, responses: dict[str, RealPublicFetchResponse]) -> None:
        self.responses = responses
        self.call_log: list[dict[str, object]] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        self.call_log.append(
            {
                "url": url,
                "timeout_seconds": timeout_seconds,
                "user_agent": user_agent,
            }
        )
        return self.responses[url]


def _real_public_verification_html(
    *,
    profile_id: str,
    target_type: str,
    identifier: str,
) -> bytes:
    profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id]
    markers = profile.visible_entry_markers or profile.lightweight_public_entry_markers
    if profile.lightweight_public_entry_markers and profile_id in {
        "JZSC-NATIONAL-HOME",
        "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
    }:
        markers = profile.lightweight_public_entry_markers
    marker_text = " ".join(markers)
    filler = "公开核验入口说明" * 80
    html = f"""
    <html>
      <head>
        <title>{profile.expected_title_contains} - {profile.site_name}</title>
        <meta name="description" content="{marker_text}">
      </head>
      <body>
        <h1>{profile.expected_title_contains}</h1>
        <p>{marker_text}</p>
        <p>{filler}</p>
        <table>
          <tr><th>项目名称</th><td>{identifier}</td></tr>
          <tr><th>招标人</th><td>{profile.site_name} 测试主体</td></tr>
          <tr><th>公告日期</th><td>2026-04-28</td></tr>
          <tr><th>{target_type}</th><td>{identifier}</td></tr>
        </table>
        <a href="{profile.sample_detail_url}">公开详情样例</a>
      </body>
    </html>
    """
    return html.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
