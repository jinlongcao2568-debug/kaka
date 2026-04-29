from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings
from stage2_ingestion.public_source_adapters import (
    PublicSourceBoundaryError,
    PublicSourceTimeoutError,
    PublicSourceTransportError,
    PublicSourceTransportResponse,
    StaticPublicSourceTransport,
)
from stage2_ingestion.service import Stage2Service
from stage2_ingestion.source_validation import (
    VALIDATION_BUCKET_FAILING,
    VALIDATION_BUCKET_SUPPORTED,
    VALIDATION_BUCKET_SUSPENDED,
    VALIDATION_BUCKET_WEAK,
    build_blocked_validation_result,
    build_degraded_validation_result,
    build_source_coverage_report,
    build_supported_validation_result,
    build_validation_request,
    source_validation_samples,
)
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


class RealPublicSourceFieldValidationTests(unittest.TestCase):
    def _repo(self, tmp_dir: str) -> ObjectStorageRepository:
        settings = Settings(
            storage_backend="json-file",
            storage_path_optional=str(Path(tmp_dir) / "source-validation.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(Path(tmp_dir) / "objects"),
        )
        return ObjectStorageRepository(
            session=DatabaseSession(settings=settings),
            settings=settings,
        )

    def _run_sample_matrix(self) -> dict[str, object]:
        samples = source_validation_samples()
        response_map = {}
        for sample in samples:
            if sample.expected_bucket in {VALIDATION_BUCKET_SUPPORTED, VALIDATION_BUCKET_WEAK}:
                response_map[sample.source_url] = PublicSourceTransportResponse(
                    content=sample.content_bytes(),
                    content_type=sample.content_type,
                    status_code=200,
                )
            elif sample.expected_bucket == VALIDATION_BUCKET_FAILING:
                response_map[sample.source_url] = PublicSourceTransportError(
                    "controlled_manual_snapshot_unavailable"
                )
        transport = StaticPublicSourceTransport(response_map)
        results = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            stage2 = Stage2Service()
            stage3 = Stage3Service()
            stage4 = Stage4Service()
            for sample in samples:
                request = build_validation_request(sample)
                try:
                    capture = stage2.capture_public_source_snapshot(
                        request,
                        repository=repo,
                        transport=transport,
                    )
                except PublicSourceBoundaryError as exc:
                    results.append(
                        build_blocked_validation_result(
                            sample,
                            blocked_reason=exc.reason,
                            blocked_carrier=exc.carrier,
                        )
                    )
                    continue

                if capture.status == "DEGRADED":
                    results.append(build_degraded_validation_result(sample, capture=capture))
                    continue

                parsed = stage3.parse_raw_snapshot(capture.snapshot_id or "", repository=repo)
                verification = stage4.verify_public_parsed_carrier(
                    parsed,
                    target={
                        "verification_target_type": sample.target_type,
                        "target_identifier": sample.target_identifier,
                        "source_snapshot_id": capture.snapshot_id,
                    },
                    repository=repo,
                )
                results.append(
                    build_supported_validation_result(
                        sample,
                        capture=capture,
                        parsed_carrier=parsed,
                        verification_carrier=verification,
                    )
                )

        return build_source_coverage_report(results)

    def test_128_sample_matrix_covers_114a_to_114i_source_families(self) -> None:
        samples = source_validation_samples()
        supported = [
            sample
            for sample in samples
            if sample.expected_bucket == VALIDATION_BUCKET_SUPPORTED
        ]

        self.assertEqual(len(supported), 9)
        self.assertEqual(len({sample.source_family for sample in supported}), 9)
        self.assertTrue(
            all(sample.sample_mode == "CONTROLLED_MANUAL_PUBLIC_SNAPSHOT" for sample in samples)
        )
        self.assertTrue(
            all(sample.source_url.startswith(("https://public.example.local/", "sandbox://")) for sample in samples)
        )

    def test_128_runs_capture_parse_verify_and_reports_field_coverage(self) -> None:
        report = self._run_sample_matrix()

        self.assertEqual(report["sample_count"], 12)
        self.assertEqual(report["supported_source_family_count"], 9)
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_SUPPORTED], 9)
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_WEAK], 1)
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_FAILING], 1)
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_SUSPENDED], 1)
        self.assertEqual(
            report["field_coverage"]["supported_samples_with_required_fields"],
            9,
        )
        self.assertEqual(
            report["verification_coverage"]["matched_public_verification_count"],
            9,
        )
        for result in report["results"]:
            if result["observed_bucket"] == VALIDATION_BUCKET_SUPPORTED:
                self.assertTrue(result["snapshot_id_optional"])
                self.assertTrue(result["sha256_optional"])
                self.assertTrue(result["lineage_preserved"])
                self.assertEqual(result["parse_state"], "PARSED")
                self.assertEqual(result["verification_result"], "MATCHED")

    def test_128_weak_failing_and_suspended_sources_fail_closed_to_review(self) -> None:
        report = self._run_sample_matrix()
        by_bucket = {}
        for result in report["results"]:
            by_bucket.setdefault(result["observed_bucket"], []).append(result)

        weak = by_bucket[VALIDATION_BUCKET_WEAK][0]
        failing = by_bucket[VALIDATION_BUCKET_FAILING][0]
        suspended = by_bucket[VALIDATION_BUCKET_SUSPENDED][0]

        self.assertTrue(weak["review_required"])
        self.assertTrue(weak["fail_closed"])
        self.assertEqual(weak["parse_state"], "REVIEW_REQUIRED")
        self.assertTrue(failing["fail_closed"])
        self.assertEqual(failing["blocked_reason_optional"], "fetch_failed")
        self.assertTrue(suspended["fail_closed"])
        self.assertIn("blocked_visibility_state:CAPTCHA_REQUIRED", suspended["blocked_reason_optional"])
        self.assertTrue(all(result["no_broad_fallback"] for result in report["results"]))

    def test_128_report_and_controlled_opening_boundaries_are_recorded_in_control_surface(self) -> None:
        report_path = ROOT / "control/real_public_source_field_validation_report.yaml"
        report = yaml.safe_load(report_path.read_text(encoding="utf-8"))

        self.assertEqual(
            report["packet_ref"],
            "PTL-I100-128-real-public-source-field-validation-and-coverage",
        )
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(report["sample_mode"], "CONTROLLED_MANUAL_PUBLIC_SNAPSHOT")
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_SUPPORTED], 9)
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_WEAK], 1)
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_FAILING], 1)
        self.assertEqual(report["coverage_buckets"][VALIDATION_BUCKET_SUSPENDED], 1)
        self.assertFalse(report["controlled_opening_boundaries"]["private_or_gray_source_used"])
        self.assertFalse(report["controlled_opening_boundaries"]["uncontrolled_live_crawler_used"])
        self.assertFalse(report["controlled_opening_boundaries"]["real_provider_call_executed"])

    def test_128_timeout_degrades_without_live_retry_or_bypass(self) -> None:
        sample = next(
            sample
            for sample in source_validation_samples()
            if sample.sample_id == "S2-128-FAILING-TRANSPORT"
        )
        transport = StaticPublicSourceTransport(
            {sample.source_url: PublicSourceTimeoutError("controlled_timeout")}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            capture = Stage2Service().capture_public_source_snapshot(
                build_validation_request(sample),
                repository=self._repo(tmp_dir),
                transport=transport,
            )

        result = build_degraded_validation_result(sample, capture=capture).as_payload()
        self.assertEqual(capture.status, "DEGRADED")
        self.assertEqual(result["observed_bucket"], VALIDATION_BUCKET_FAILING)
        self.assertTrue(result["fail_closed"])
        self.assertTrue(result["no_broad_fallback"])


if __name__ == "__main__":
    unittest.main()
