from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage2_ingestion.playwright_challenge_resolver import (
    CHALLENGE_DETAIL_BROWSER_MAX_ROUTE_ATTEMPTS,
    CHALLENGE_JIGSAW_MAX_ATTEMPTS,
    CHALLENGE_MAX_DOWNLOAD_BYTES,
    CHALLENGE_OCR_MAX_ATTEMPTS,
    CHALLENGE_PROXY_POOL_MAX_SIZE,
)
from stage2_ingestion.real_public_url_fetcher import (
    _attachment_content_is_supported,
    _attachment_support_decision,
    _document_capture_support_decision,
    real_public_capture_support_policy,
)


STAGE2_CAPTURE_SUPPORT_AUDIT_KIND = "stage2_capture_support_audit_v1_manifest"
DEFAULT_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/stage2-capture-support-audit-v1"
)


def build_stage2_capture_support_audit(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    policy = real_public_capture_support_policy()
    cases = _support_cases()
    failed_cases = [case["case_id"] for case in cases if not case["passed"]]
    summary = {
        "audit_state": "PASSED" if not failed_cases else "FAILED",
        "case_count": len(cases),
        "passed_case_count": len(cases) - len(failed_cases),
        "failed_case_count": len(failed_cases),
        "failed_cases": failed_cases,
        "terminal_state_counts": _counts(
            str(case["actual"].get("terminal_state") or "")
            for case in cases
            if isinstance(case.get("actual"), Mapping)
            and case["actual"].get("terminal_state")
        ),
        "registered_entry_profile_count": len(
            policy["registered_entry_profile_ids"]
        ),
        "registered_attachment_profile_count": len(
            policy["registered_attachment_profile_ids"]
        ),
        "scope_boundary": (
            "Offline policy and controlled classifier audit only. Registered sources are "
            "eligible for bounded attempts, not guaranteed reachable or parseable."
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_kind": STAGE2_CAPTURE_SUPPORT_AUDIT_KIND,
        "manifest_version": 1,
        "created_at": created,
        "capture_support_policy": policy,
        "browser_runtime_budgets": {
            "ocr_attempts_max": CHALLENGE_OCR_MAX_ATTEMPTS,
            "jigsaw_attempts_max": CHALLENGE_JIGSAW_MAX_ATTEMPTS,
            "detail_browser_route_attempts_max": (
                CHALLENGE_DETAIL_BROWSER_MAX_ROUTE_ATTEMPTS
            ),
            "proxy_pool_size_max": CHALLENGE_PROXY_POOL_MAX_SIZE,
            "download_bytes_max": CHALLENGE_MAX_DOWNLOAD_BYTES,
        },
        "case_results": cases,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "browser_launched": False,
            "live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    result = {
        "stage2_capture_support_audit_mode": "EXECUTED_OFFLINE",
        "audit_passed": not failed_cases,
        "manifest": manifest,
        "summary": summary,
    }
    (out_root / "stage2-capture-support-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "summary.md").write_text(
        _markdown_summary(summary, policy),
        encoding="utf-8",
    )
    return result


def _support_cases() -> list[dict[str, Any]]:
    document_cases = [
        (
            "document_replayable_ready",
            _document_capture_support_decision(
                status="FETCHED",
                degraded_reasons=[],
                failure_taxonomy=None,
                snapshot_replayable=True,
                browser_resolution_available=False,
            ),
            {"support_state": "SUPPORTED_REPLAYABLE", "terminal_state": "READY"},
        ),
        (
            "document_spa_shell_blocked",
            _document_capture_support_decision(
                status="DEGRADED",
                degraded_reasons=["visible_entry_markers_missing"],
                failure_taxonomy={
                    "failure_class": "PUBLIC_ENTRY_MARKERS_MISSING_OR_SPA_SHELL",
                    "retryable": False,
                },
                snapshot_replayable=False,
                browser_resolution_available=False,
            ),
            {
                "support_state": "BLOCKED_DYNAMIC_OR_SPA_SHELL",
                "terminal_state": "BLOCKED",
                "browser_escalation_allowed": False,
            },
        ),
        (
            "document_challenge_without_resolver_blocked",
            _document_capture_support_decision(
                status="AUTOMATED_CHALLENGE_RESOLUTION_PENDING",
                degraded_reasons=["controlled_challenge_body_pattern:验证码"],
                failure_taxonomy={
                    "failure_class": "CONTROLLED_CHALLENGE_BODY_PATTERN"
                },
                snapshot_replayable=False,
                browser_resolution_available=False,
            ),
            {
                "support_state": "BLOCKED_CHALLENGE_OR_SESSION",
                "terminal_state": "BLOCKED",
                "browser_escalation_allowed": False,
            },
        ),
        (
            "document_transport_timeout_retryable",
            _document_capture_support_decision(
                status="DEGRADED",
                degraded_reasons=["fetch_failed"],
                failure_taxonomy={"failure_class": "TIMEOUT", "retryable": True},
                snapshot_replayable=False,
                browser_resolution_available=False,
            ),
            {
                "support_state": "RETRYABLE_FETCH_FAILURE",
                "terminal_state": "RETRYABLE",
                "retry_allowed": True,
            },
        ),
        (
            "document_oversized_unsupported",
            _document_capture_support_decision(
                status="DEGRADED",
                degraded_reasons=["response_body_too_large"],
                failure_taxonomy=None,
                snapshot_replayable=False,
                browser_resolution_available=False,
            ),
            {
                "support_state": "UNSUPPORTED_RESPONSE_SIZE",
                "terminal_state": "UNSUPPORTED",
            },
        ),
    ]
    attachment_cases = [
        (
            "attachment_replayable_ready",
            _attachment_support_decision(
                status="FETCHED",
                degraded_reasons=[],
                attachment_failure_taxonomy=[],
                attachment_blocker_class="",
                snapshot_replayable=True,
            ),
            {"support_state": "SUPPORTED_REPLAYABLE", "terminal_state": "READY"},
        ),
        (
            "attachment_captured_without_snapshot_review",
            _attachment_support_decision(
                status="FETCHED",
                degraded_reasons=[],
                attachment_failure_taxonomy=[],
                attachment_blocker_class="",
                snapshot_replayable=False,
            ),
            {
                "support_state": "SUPPORTED_CAPTURED_NOT_PERSISTED",
                "terminal_state": "REVIEW",
                "downstream_use_allowed": False,
            },
        ),
        (
            "attachment_timeout_retryable",
            _attachment_support_decision(
                status="DEGRADED",
                degraded_reasons=["fetch_failed"],
                attachment_failure_taxonomy=["TIMEOUT", "attachment_fetch_failed"],
                attachment_blocker_class="",
                snapshot_replayable=False,
            ),
            {
                "support_state": "RETRYABLE_FETCH_FAILURE",
                "terminal_state": "RETRYABLE",
                "retry_allowed": True,
            },
        ),
        (
            "attachment_challenge_blocked_with_single_opt_in_route",
            _attachment_support_decision(
                status="DEGRADED",
                degraded_reasons=["html_body_not_attachment"],
                attachment_failure_taxonomy=["attachment_captcha_required"],
                attachment_blocker_class="CAPTCHA_MANUAL_REQUIRED",
                snapshot_replayable=False,
            ),
            {
                "support_state": "BLOCKED_ATTACHMENT_CHALLENGE",
                "terminal_state": "BLOCKED",
                "browser_escalation_allowed": True,
            },
        ),
        (
            "attachment_unsupported_mime_terminal",
            _attachment_support_decision(
                status="DEGRADED",
                degraded_reasons=["unsupported_attachment_content_type"],
                attachment_failure_taxonomy=["attachment_unsupported_content_type"],
                attachment_blocker_class="",
                snapshot_replayable=False,
            ),
            {
                "support_state": "UNSUPPORTED_CONTENT_TYPE",
                "terminal_state": "UNSUPPORTED",
                "browser_escalation_allowed": False,
            },
        ),
        (
            "attachment_oversized_terminal",
            _attachment_support_decision(
                status="DEGRADED",
                degraded_reasons=["response_body_too_large"],
                attachment_failure_taxonomy=["response_body_too_large"],
                attachment_blocker_class="",
                snapshot_replayable=False,
            ),
            {
                "support_state": "UNSUPPORTED_RESPONSE_SIZE",
                "terminal_state": "UNSUPPORTED",
                "browser_escalation_allowed": False,
            },
        ),
    ]
    results = [
        _case_result(case_id, actual, expected)
        for case_id, actual, expected in [*document_cases, *attachment_cases]
    ]
    mime_actual = {
        "misleading_pdf_filename_with_image_mime_supported": (
            _attachment_content_is_supported(
                content=b"\x89PNG\r\n\x1a\nnot-a-pdf",
                content_type="image/png",
                filename="misleading.pdf",
                allow_plain_html_attachment=False,
            )
        )
    }
    results.append(
        _case_result(
            "misleading_filename_does_not_override_explicit_mime",
            mime_actual,
            {"misleading_pdf_filename_with_image_mime_supported": False},
        )
    )
    return results


def _case_result(
    case_id: str,
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    return {
        "case_id": case_id,
        "expected": dict(expected),
        "actual": dict(actual),
        "mismatches": mismatches,
        "passed": not mismatches,
    }


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _markdown_summary(
    summary: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> str:
    return "\n".join(
        [
            "# Stage2 capture support audit",
            "",
            f"- Audit state: `{summary['audit_state']}`",
            f"- Cases: `{summary['passed_case_count']}/{summary['case_count']}` passed",
            f"- Entry max bytes: `{policy['entry_max_response_bytes']}`",
            f"- Detail max bytes: `{policy['detail_max_response_bytes']}`",
            f"- Attachment max bytes: `{policy['attachment_max_response_bytes']}`",
            f"- Registered entry profiles: `{summary['registered_entry_profile_count']}`",
            f"- Registered attachment profiles: `{summary['registered_attachment_profile_count']}`",
            "- Browser resolution default: disabled; challenge resolution requires explicit opt-in.",
            "- Unsupported content or size: no browser escalation.",
            "- Boundary: registration is an allowlist, not a reachability or parseability guarantee.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build offline Stage2 capture support audit")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()
    result = build_stage2_capture_support_audit(output_root=args.output_root)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
