from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


CHALLENGE_STABILITY_REPORT_VERSION = 1
CHALLENGE_STABILITY_REPORT_ADAPTER_ID = "challenge-stability-report-builder"
CHALLENGE_STABILITY_REPORT_OBJECT_TYPE = "challenge_stability_report"

STABLE = "STABLE"
PARTIAL = "PARTIAL"
CLASSIFIED_ONLY = "CLASSIFIED_ONLY"
DIRECT_FETCH_OK_NOT_CHALLENGE = "DIRECT_FETCH_OK_NOT_CHALLENGE"
NO_REAL_COVERAGE = "NO_REAL_COVERAGE"
NO_ATTACHMENT_SIGNAL = "NO_ATTACHMENT_SIGNAL"


def build_challenge_stability_report(
    *,
    real_sample_execution_manifest_json: str | Path,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    path = Path(real_sample_execution_manifest_json)
    payload = _load_json(path)
    manifest = _source_manifest(payload)
    samples = [
        dict(item)
        for item in list(manifest.get("project_sample_items") or [])
        if isinstance(item, Mapping)
    ]
    target_items = [
        dict(item)
        for item in list(manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]
    profiles = sorted(
        {
            str(item.get("source_profile_id") or "")
            for item in [*target_items, *samples]
            if str(item.get("source_profile_id") or "")
        }
    )
    platform_reports = [
        _platform_report(profile_id, target_items=target_items, samples=samples)
        for profile_id in profiles
    ]
    summary = {
        "platform_count": len(platform_reports),
        "grade_counts": _counts(str(item.get("stability_grade") or "") for item in platform_reports),
        "project_sample_count": len(samples),
        "detail_snapshot_count": sum(_int(item.get("detail_snapshot_count")) for item in samples),
        "attachment_snapshot_count": sum(_int(item.get("attachment_snapshot_count")) for item in samples),
        "challenge_attempted_count": sum(_int(item.get("challenge_attempted_count")) for item in platform_reports),
        "challenge_resolved_count": sum(_int(item.get("challenge_resolved_count")) for item in platform_reports),
        "challenge_failed_count": sum(_int(item.get("challenge_failed_count")) for item in platform_reports),
        "failure_taxonomy_counts": _counts(
            value
            for item in platform_reports
            for value in list(item.get("failure_taxonomy") or [])
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return {
        "challenge_stability_report_mode": "DRY_RUN",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": {
            "manifest_version": CHALLENGE_STABILITY_REPORT_VERSION,
            "manifest_kind": CHALLENGE_STABILITY_REPORT_OBJECT_TYPE,
            "adapter_id": CHALLENGE_STABILITY_REPORT_ADAPTER_ID,
            "manifest_id": f"CHALLENGE-STABILITY-{_hashish(path)}",
            "created_at": created,
            "source_real_sample_execution_manifest_id": str(manifest.get("manifest_id") or ""),
            "source_real_sample_execution_manifest_path": str(path),
            "platform_reports": platform_reports,
            "summary": summary,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "summary": summary,
    }


def _platform_report(
    profile_id: str,
    *,
    target_items: list[Mapping[str, Any]],
    samples: list[Mapping[str, Any]],
) -> dict[str, Any]:
    profile_targets = [item for item in target_items if str(item.get("source_profile_id") or "") == profile_id]
    profile_samples = [item for item in samples if str(item.get("source_profile_id") or "") == profile_id]
    failure_taxonomy = _dedupe(
        str(value)
        for item in [*profile_targets, *profile_samples]
        for value in list(item.get("failure_taxonomy") or [])
        if str(value or "")
    )
    diagnostics = [
        dict(row)
        for item in profile_samples
        for row in list(item.get("challenge_diagnostics") or [])
        if isinstance(row, Mapping)
    ]
    attempted = sum(1 for row in diagnostics if bool(row.get("attempted")) or str(row.get("state") or ""))
    resolved = sum(1 for row in diagnostics if str(row.get("state") or "") == "RESOLVED_AND_SNAPSHOT_CAPTURED")
    failed = sum(1 for row in diagnostics if str(row.get("state") or "").startswith("FAILED_CLOSED"))
    detail_count = sum(_int(item.get("detail_snapshot_count")) for item in profile_samples)
    attachment_count = sum(_int(item.get("attachment_snapshot_count")) for item in profile_samples)
    classified = _has_challenge_classification(failure_taxonomy)
    grade = _grade(
        project_count=len(profile_samples),
        detail_count=detail_count,
        attachment_count=attachment_count,
        attempted=attempted,
        resolved=resolved,
        failed=failed,
        classified=classified,
    )
    return {
        "source_profile_id": profile_id,
        "target_bucket_count": len(profile_targets),
        "target_ids": [str(item.get("target_id") or "") for item in profile_targets],
        "project_sample_count": len(profile_samples),
        "detail_snapshot_count": detail_count,
        "attachment_snapshot_count": attachment_count,
        "challenge_attempted_count": attempted,
        "challenge_resolved_count": resolved,
        "challenge_failed_count": failed,
        "stability_grade": grade,
        "failure_taxonomy": failure_taxonomy,
        "failure_taxonomy_counts": _counts(failure_taxonomy),
        "challenge_diagnostics_preview": diagnostics[:12],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _grade(
    *,
    project_count: int,
    detail_count: int,
    attachment_count: int,
    attempted: int,
    resolved: int,
    failed: int,
    classified: bool,
) -> str:
    if project_count <= 0:
        return NO_REAL_COVERAGE
    if resolved > 0 and failed == 0:
        return STABLE
    if resolved > 0 or attempted > 0:
        return PARTIAL
    if classified:
        return CLASSIFIED_ONLY
    if attachment_count > 0 or detail_count > 0:
        return DIRECT_FETCH_OK_NOT_CHALLENGE
    return NO_ATTACHMENT_SIGNAL


def _has_challenge_classification(values: Iterable[str]) -> bool:
    text = "\n".join(str(value or "") for value in values).lower()
    return any(
        token in text
        for token in (
            "controlled_challenge",
            "captcha",
            "login",
            "session",
            "请登录",
            "resolver_error",
            "automated_challenge_resolution_state",
            "attachment_captcha_required",
            "attachment_login_required",
        )
    )


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("challenge stability input must be a JSON object")
    return dict(data)


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _hashish(path: Path) -> str:
    text = str(path.resolve() if path.exists() else path)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build challenge stability report from real sample execution manifest.")
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_challenge_stability_report(
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "challenge stability report "
            f"{result['challenge_stability_report_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CLASSIFIED_ONLY",
    "DIRECT_FETCH_OK_NOT_CHALLENGE",
    "NO_ATTACHMENT_SIGNAL",
    "NO_REAL_COVERAGE",
    "PARTIAL",
    "STABLE",
    "build_challenge_stability_report",
]
