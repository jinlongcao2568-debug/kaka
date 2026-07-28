from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from shared.utils import utc_now_iso
from stage2_ingestion.real_public_url_fetcher import (
    REAL_PUBLIC_ATTACHMENT_PROFILES,
    REAL_PUBLIC_ENTRY_PROFILES,
    REAL_PUBLIC_ENTRY_PROFILE_BY_ID,
    real_public_capture_support_policy,
)


REAL_PUBLIC_SOURCE_COVERAGE_FRESHNESS_KIND = (
    "real_public_source_coverage_freshness_v1_manifest"
)
SOURCE_FRESH_MAX_AGE_HOURS = 24
SOURCE_AGING_MAX_AGE_HOURS = 72
DEFAULT_RUN_MANIFEST = Path(
    "tmp/evaluation-real-samples/controlled-live-public-batch-20260703-auto-v2/"
    "run-manifest.json"
)
DEFAULT_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/real-public-source-coverage-freshness-v1"
)


def build_real_public_source_coverage_freshness_report(
    *,
    run_manifest_json: str | Path = DEFAULT_RUN_MANIFEST,
    storage_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    created_dt = _parse_time(created)
    run_path = Path(run_manifest_json)
    run_payload = _load_json(run_path)
    manifest = _mapping(run_payload.get("manifest"))
    execution = _mapping(run_payload.get("execution"))
    run_created_at = str(manifest.get("created_at") or "")
    real_observation_valid = bool(
        str(run_payload.get("real_sample_execution_mode") or "") == "EXECUTED"
        and bool(run_payload.get("execute"))
        and bool(execution.get("executed"))
        and bool(execution.get("fetch_public_urls_enabled"))
    )
    resolved_storage_path = _resolve_storage_path(
        explicit=storage_json,
        execution=execution,
        run_path=run_path,
    )
    storage_payload = _load_json(resolved_storage_path) if resolved_storage_path else {}
    snapshot_rows = _snapshot_rows(storage_payload) if real_observation_valid else []
    items = [
        dict(item)
        for item in list(manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]
    items = items if real_observation_valid else []

    source_rows = [
        _source_row(
            profile_id=profile.profile_id,
            profile_url=profile.url,
            site_name=profile.site_name,
            source_family=profile.source_family,
            items=[
                item
                for item in items
                if str(item.get("source_profile_id") or "") == profile.profile_id
            ],
            snapshots=[
                row
                for row in snapshot_rows
                if str(row.get("source_profile_id") or "") == profile.profile_id
            ],
            created_dt=created_dt,
            real_observation_valid=real_observation_valid,
            run_created_at=run_created_at,
        )
        for profile in REAL_PUBLIC_ENTRY_PROFILES
    ]
    observed_profile_ids = {
        str(item.get("source_profile_id") or "") for item in items
    }
    unknown_observed_profiles = sorted(
        profile_id
        for profile_id in observed_profile_ids
        if profile_id and profile_id not in REAL_PUBLIC_ENTRY_PROFILE_BY_ID
    )
    summary = _summary(
        source_rows,
        items=items,
        real_observation_valid=real_observation_valid,
        unknown_observed_profiles=unknown_observed_profiles,
    )
    policy = real_public_capture_support_policy()
    report_manifest = {
        "manifest_kind": REAL_PUBLIC_SOURCE_COVERAGE_FRESHNESS_KIND,
        "manifest_version": 1,
        "created_at": created,
        "input_run_manifest_path": str(run_path),
        "input_run_manifest_sha256": _file_sha256(run_path),
        "input_storage_path_optional": str(resolved_storage_path)
        if resolved_storage_path
        else None,
        "input_storage_sha256_optional": _file_sha256(resolved_storage_path)
        if resolved_storage_path
        else None,
        "source_run_manifest_id": str(manifest.get("manifest_id") or ""),
        "source_run_created_at": run_created_at,
        "real_observation_valid": real_observation_valid,
        "freshness_policy": {
            "fresh_max_age_hours": SOURCE_FRESH_MAX_AGE_HOURS,
            "aging_max_age_hours": SOURCE_AGING_MAX_AGE_HOURS,
            "stale_after_hours": SOURCE_AGING_MAX_AGE_HOURS,
            "external_claim_requires_fresh_observation": True,
            "timestamp_preference": [
                "snapshot.fetched_at_optional",
                "snapshot.captured_at_optional",
                "snapshot.created_at",
                "run_manifest.created_at_proxy",
            ],
        },
        "coverage_contract": {
            "registered_entry_profile_count": len(REAL_PUBLIC_ENTRY_PROFILES),
            "registered_attachment_profile_count": len(
                REAL_PUBLIC_ATTACHMENT_PROFILES
            ),
            "registered_entry_profile_ids": policy[
                "registered_entry_profile_ids"
            ],
            "list_coverage_basis": "target query bucket attempted in the input run",
            "detail_coverage_basis": (
                "unique detail snapshot refs divided by discovery candidates"
            ),
            "attachment_coverage_basis": (
                "target buckets with at least one attachment snapshot divided by target "
                "buckets where an attachment was expected, discovered, or blocked"
            ),
            "blocked_rate_basis": (
                "target buckets with technical source/download blockers divided by "
                "attempted target buckets"
            ),
            "no_match_interpretation": (
                "NO_MATCH_IN_OBSERVED_QUERY_SCOPE; never proof that no opportunity exists"
            ),
        },
        "source_rows": source_rows,
        "unknown_observed_profile_ids": unknown_observed_profiles,
        "summary": summary,
        "external_claim_boundary": {
            "allowed_scope": (
                "Only a registered source profile and its explicit observation window may "
                "be described when external_claim_eligible=true."
            ),
            "forbidden_claims": [
                "all public sources are covered",
                "source is currently reachable when freshness is AGING/STALE/UNKNOWN",
                "zero matches means no opportunity exists",
                "missing detail or attachment means the source has no such document",
            ],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "network_enabled": False,
            "browser_launched": False,
            "live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    report_manifest["manifest_sha256"] = _fingerprint(report_manifest)
    result = {
        "real_public_source_coverage_freshness_mode": "EXECUTED_OFFLINE",
        "safe_to_execute": bool(run_payload),
        "report_valid": bool(run_payload) and not unknown_observed_profiles,
        "manifest": report_manifest,
        "summary": summary,
    }
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "real-public-source-coverage-freshness-v1.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "source-coverage-table.json").write_text(
        json.dumps(
            {
                "manifest_kind": "real_public_source_coverage_table_v1",
                "created_at": created,
                "source_rows": source_rows,
                "summary": summary,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_root / "summary.md").write_text(
        _markdown_summary(summary, run_created_at=run_created_at),
        encoding="utf-8",
    )
    return result


def _source_row(
    *,
    profile_id: str,
    profile_url: str,
    site_name: str,
    source_family: str,
    items: list[Mapping[str, Any]],
    snapshots: list[Mapping[str, Any]],
    created_dt: datetime,
    real_observation_valid: bool,
    run_created_at: str,
) -> dict[str, Any]:
    target_count = len(items)
    discovery_candidate_count = sum(
        _int(item.get("discovery_candidate_count")) for item in items
    )
    detail_snapshot_refs = [
        str(ref.get("snapshot_id") or "")
        for item in items
        for ref in list(item.get("detail_snapshot_refs") or [])
        if isinstance(ref, Mapping) and ref.get("snapshot_id")
    ]
    detail_snapshot_ids = set(detail_snapshot_refs)
    attachment_snapshot_ids = {
        str(ref.get("snapshot_id") or "")
        for item in items
        for ref in list(item.get("attachment_snapshot_refs") or [])
        if isinstance(ref, Mapping) and ref.get("snapshot_id")
    }
    no_match_target_count = sum(
        str(item.get("target_execution_state") or "")
        == "DISCOVERY_NO_MATCH_REVIEW"
        for item in items
    )
    blocked_target_count = sum(_item_has_technical_blocker(item) for item in items)
    attachment_expected_items = [item for item in items if _attachment_expected(item)]
    attachment_covered_target_count = sum(
        bool(list(item.get("attachment_snapshot_refs") or []))
        for item in attachment_expected_items
    )
    snapshot_counts = Counter(
        str(snapshot.get("snapshot_layer") or "unknown") for snapshot in snapshots
    )
    latest_by_layer = {
        layer: _latest_time(
            str(snapshot.get("captured_at") or "")
            for snapshot in snapshots
            if snapshot.get("snapshot_layer") == layer
        )
        for layer in ("list", "detail", "attachment")
    }
    last_success_at = _latest_time(
        str(snapshot.get("captured_at") or "") for snapshot in snapshots
    )
    timestamp_basis = "snapshot_manifest_exact"
    if not last_success_at and target_count and real_observation_valid:
        last_success_at = run_created_at
        timestamp_basis = "run_manifest_created_at_proxy"
    observed_times = [
        str(snapshot.get("captured_at") or "")
        for snapshot in snapshots
        if snapshot.get("captured_at")
    ]
    if not observed_times and target_count and run_created_at:
        observed_times = [run_created_at]
    window_start = _earliest_time(observed_times)
    window_end = _latest_time(observed_times)
    freshness = _freshness(last_success_at, created_dt=created_dt)
    if not real_observation_valid:
        coverage_state = "DRY_RUN_NOT_OBSERVED"
    elif not target_count:
        coverage_state = "NOT_OBSERVED_IN_INPUT_WINDOW"
    elif blocked_target_count:
        coverage_state = "PARTIAL_OR_BLOCKED"
    elif no_match_target_count == target_count:
        coverage_state = "OBSERVED_NO_MATCH_IN_QUERY_SCOPE"
    elif discovery_candidate_count and len(detail_snapshot_refs) >= discovery_candidate_count:
        coverage_state = "COVERED_WITH_DETAIL_SNAPSHOTS"
    else:
        coverage_state = "PARTIAL_REVIEW_REQUIRED"
    detail_coverage_rate = _ratio(
        min(len(detail_snapshot_refs), discovery_candidate_count),
        discovery_candidate_count,
    )
    attachment_coverage_rate = _ratio(
        attachment_covered_target_count,
        len(attachment_expected_items),
    )
    blocked_rate = _ratio(blocked_target_count, target_count)
    external_claim_eligible = bool(
        real_observation_valid
        and target_count
        and freshness["freshness_state"] == "FRESH"
        and coverage_state
        in {
            "COVERED_WITH_DETAIL_SNAPSHOTS",
            "OBSERVED_NO_MATCH_IN_QUERY_SCOPE",
        }
    )
    return {
        "source_profile_id": profile_id,
        "registered": True,
        "source_url": profile_url,
        "source_host": (urlsplit(profile_url).hostname or "").lower(),
        "site_name": site_name,
        "source_family": source_family,
        "coverage_state": coverage_state,
        "observation_window_start": window_start,
        "observation_window_end": window_end,
        "last_success_at": last_success_at,
        "last_success_timestamp_basis": timestamp_basis if last_success_at else None,
        "last_list_success_at": latest_by_layer["list"],
        "last_detail_success_at": latest_by_layer["detail"],
        "last_attachment_success_at": latest_by_layer["attachment"],
        **freshness,
        "list_coverage": {
            "target_query_bucket_count": target_count,
            "list_snapshot_count": snapshot_counts.get("list", 0),
            "discovery_candidate_count": discovery_candidate_count,
            "no_match_target_count": no_match_target_count,
            "no_match_interpretation": (
                "NO_MATCH_IN_OBSERVED_QUERY_SCOPE"
                if no_match_target_count
                else "NOT_APPLICABLE"
            ),
        },
        "detail_coverage": {
            "expected_candidate_count": discovery_candidate_count,
            "captured_detail_ref_count": len(detail_snapshot_refs),
            "captured_unique_detail_snapshot_count": len(detail_snapshot_ids),
            "storage_detail_snapshot_count": snapshot_counts.get("detail", 0),
            "coverage_rate": detail_coverage_rate,
            "coverage_rate_state": "MEASURED"
            if detail_coverage_rate is not None
            else "NOT_APPLICABLE_NO_DISCOVERY_CANDIDATES",
        },
        "attachment_coverage": {
            "expected_or_discovered_target_count": len(attachment_expected_items),
            "covered_target_count": attachment_covered_target_count,
            "captured_unique_attachment_snapshot_count": len(
                attachment_snapshot_ids
            ),
            "storage_attachment_snapshot_count": snapshot_counts.get(
                "attachment", 0
            ),
            "coverage_rate": attachment_coverage_rate,
            "coverage_rate_state": "MEASURED_AT_TARGET_BUCKET_LEVEL"
            if attachment_coverage_rate is not None
            else "NOT_APPLICABLE_NO_ATTACHMENT_EXPECTATION_OR_SIGNAL",
        },
        "blocker_metrics": {
            "blocked_target_count": blocked_target_count,
            "attempted_target_count": target_count,
            "blocked_rate": blocked_rate,
            "failure_taxonomy_counts": dict(
                sorted(
                    Counter(
                        str(reason)
                        for item in items
                        for reason in list(item.get("failure_taxonomy") or [])
                        if str(reason or "").strip()
                    ).items()
                )
            ),
        },
        "external_claim_eligible": external_claim_eligible,
        "external_claim_state": (
            "REGISTERED_FRESH_WINDOW_ONLY"
            if external_claim_eligible
            else _external_claim_denial_state(
                real_observation_valid=real_observation_valid,
                target_count=target_count,
                freshness_state=str(freshness["freshness_state"]),
                coverage_state=coverage_state,
            )
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _snapshot_rows(storage_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    tables = _mapping(storage_payload.get("tables"))
    manifests = _mapping(tables.get("evidence_snapshot_manifest"))
    rows: list[dict[str, Any]] = []
    for stored in manifests.values():
        if not isinstance(stored, Mapping):
            continue
        payload = _mapping(stored.get("payload"))
        snapshot_kind = str(payload.get("snapshot_kind") or "")
        layer = _snapshot_layer(snapshot_kind)
        if not layer:
            continue
        profile_id = _snapshot_profile_id(payload)
        if not profile_id:
            continue
        captured_at = str(
            payload.get("fetched_at_optional")
            or payload.get("captured_at_optional")
            or payload.get("created_at")
            or ""
        )
        rows.append(
            {
                "snapshot_id": str(payload.get("snapshot_id") or ""),
                "source_profile_id": profile_id,
                "snapshot_layer": layer,
                "captured_at": captured_at,
                "source_url": str(payload.get("source_url_optional") or ""),
                "replay_state": str(payload.get("replay_state") or ""),
            }
        )
    return rows


def _snapshot_profile_id(payload: Mapping[str, Any]) -> str:
    lineage = _mapping(payload.get("lineage_refs"))
    raw = _mapping(payload.get("raw_snapshot_metadata"))
    direct = str(
        lineage.get("entry_profile_id")
        or raw.get("entry_profile_id")
        or ""
    )
    if direct in REAL_PUBLIC_ENTRY_PROFILE_BY_ID:
        return direct
    attachment_profile = str(
        lineage.get("attachment_profile_id")
        or raw.get("attachment_profile_id")
        or ""
    )
    for profile_id in sorted(REAL_PUBLIC_ENTRY_PROFILE_BY_ID, key=len, reverse=True):
        if attachment_profile.startswith(f"{profile_id}-SAME-SITE-ATTACH-"):
            return profile_id
    source_host = (
        urlsplit(str(payload.get("source_url_optional") or "")).hostname or ""
    ).lower()
    host_matches = [
        profile.profile_id
        for profile in REAL_PUBLIC_ENTRY_PROFILES
        if (urlsplit(profile.url).hostname or "").lower() == source_host
    ]
    return host_matches[0] if len(host_matches) == 1 else ""


def _snapshot_layer(snapshot_kind: str) -> str:
    lowered = snapshot_kind.lower()
    if "entry" in lowered:
        return "list"
    if "detail" in lowered:
        return "detail"
    if "attachment" in lowered:
        return "attachment"
    return ""


def _attachment_expected(item: Mapping[str, Any]) -> bool:
    if str(item.get("document_kind") or "") == "tender_file":
        return True
    if list(item.get("attachment_snapshot_refs") or []):
        return True
    parse_summary = _mapping(item.get("parse_summary"))
    if _int(parse_summary.get("attachment_missing_review_count")) > 0:
        return True
    return any(
        "attachment" in str(reason or "").lower()
        for reason in list(item.get("failure_taxonomy") or [])
    )


def _item_has_technical_blocker(item: Mapping[str, Any]) -> bool:
    state = str(item.get("target_execution_state") or "")
    if state == "CAPTURE_PARTIAL_REVIEW":
        return True
    blocker_tokens = (
        "captcha",
        "failed_closed",
        "http_status",
        "detail_capture_failure",
        "variant_exhausted",
        "unsupported_content_type",
        "route_missing",
        "timeout",
        "login",
        "blocked",
    )
    return any(
        any(token in str(reason or "").lower() for token in blocker_tokens)
        for reason in list(item.get("failure_taxonomy") or [])
    )


def _freshness(last_success_at: str | None, *, created_dt: datetime) -> dict[str, Any]:
    observed = _parse_time(last_success_at)
    if observed is None or created_dt is None:
        return {"freshness_state": "UNKNOWN", "freshness_age_hours": None}
    age_hours = max(0.0, (created_dt - observed).total_seconds() / 3600)
    if age_hours <= SOURCE_FRESH_MAX_AGE_HOURS:
        state = "FRESH"
    elif age_hours <= SOURCE_AGING_MAX_AGE_HOURS:
        state = "AGING"
    else:
        state = "STALE"
    return {
        "freshness_state": state,
        "freshness_age_hours": round(age_hours, 3),
    }


def _summary(
    source_rows: list[Mapping[str, Any]],
    *,
    items: list[Mapping[str, Any]],
    real_observation_valid: bool,
    unknown_observed_profiles: list[str],
) -> dict[str, Any]:
    observed = [row for row in source_rows if row["list_coverage"]["target_query_bucket_count"]]
    detail_expected = sum(
        _int(row["detail_coverage"]["expected_candidate_count"]) for row in source_rows
    )
    detail_captured = sum(
        _int(row["detail_coverage"]["captured_detail_ref_count"])
        for row in source_rows
    )
    detail_unique = sum(
        _int(row["detail_coverage"]["captured_unique_detail_snapshot_count"])
        for row in source_rows
    )
    attachment_expected = sum(
        _int(row["attachment_coverage"]["expected_or_discovered_target_count"])
        for row in source_rows
    )
    attachment_covered = sum(
        _int(row["attachment_coverage"]["covered_target_count"])
        for row in source_rows
    )
    blocked_targets = sum(
        _int(row["blocker_metrics"]["blocked_target_count"]) for row in source_rows
    )
    attempted_targets = sum(
        _int(row["blocker_metrics"]["attempted_target_count"]) for row in source_rows
    )
    return {
        "report_state": "VALID_REAL_OBSERVATION"
        if real_observation_valid and not unknown_observed_profiles
        else "DRY_RUN_OR_INVALID_OBSERVATION",
        "real_observation_valid": real_observation_valid,
        "registered_source_count": len(source_rows),
        "observed_registered_source_count": len(observed),
        "unobserved_registered_source_count": len(source_rows) - len(observed),
        "unknown_observed_profile_count": len(unknown_observed_profiles),
        "coverage_state_counts": dict(
            sorted(Counter(str(row["coverage_state"]) for row in source_rows).items())
        ),
        "freshness_state_counts": dict(
            sorted(Counter(str(row["freshness_state"]) for row in source_rows).items())
        ),
        "external_claim_eligible_source_count": sum(
            bool(row["external_claim_eligible"]) for row in source_rows
        ),
        "target_query_bucket_count": len(items),
        "discovery_candidate_count": sum(
            _int(item.get("discovery_candidate_count")) for item in items
        ),
        "no_match_target_count": sum(
            str(item.get("target_execution_state") or "")
            == "DISCOVERY_NO_MATCH_REVIEW"
            for item in items
        ),
        "detail_expected_candidate_count": detail_expected,
        "detail_captured_ref_count": detail_captured,
        "detail_captured_unique_snapshot_count": detail_unique,
        "detail_coverage_rate": _ratio(detail_captured, detail_expected),
        "attachment_expected_or_discovered_target_count": attachment_expected,
        "attachment_covered_target_count": attachment_covered,
        "attachment_target_coverage_rate": _ratio(
            attachment_covered, attachment_expected
        ),
        "blocked_target_count": blocked_targets,
        "blocked_target_rate": _ratio(blocked_targets, attempted_targets),
        "not_found_clearance_allowed": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _external_claim_denial_state(
    *,
    real_observation_valid: bool,
    target_count: int,
    freshness_state: str,
    coverage_state: str,
) -> str:
    if not real_observation_valid:
        return "DENIED_DRY_RUN_OR_INVALID_OBSERVATION"
    if not target_count:
        return "DENIED_NOT_OBSERVED_IN_WINDOW"
    if freshness_state != "FRESH":
        return f"DENIED_FRESHNESS_{freshness_state}"
    return f"DENIED_COVERAGE_{coverage_state}"


def _resolve_storage_path(
    *,
    explicit: str | Path | None,
    execution: Mapping[str, Any],
    run_path: Path,
) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    configured = str(execution.get("storage_path_optional") or "").strip()
    if configured:
        configured_path = Path(configured)
        candidates.append(configured_path)
        candidates.append(run_path.parent / configured_path.name)
    candidates.append(run_path.parent / "storage.json")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _latest_time(values: Iterable[str]) -> str | None:
    parsed = [(value, _parse_time(value)) for value in values if value]
    parsed = [(value, dt) for value, dt in parsed if dt is not None]
    return max(parsed, key=lambda item: item[1])[0] if parsed else None


def _earliest_time(values: Iterable[str]) -> str | None:
    parsed = [(value, _parse_time(value)) for value in values if value]
    parsed = [(value, dt) for value, dt in parsed if dt is not None]
    return min(parsed, key=lambda item: item[1])[0] if parsed else None


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _markdown_summary(summary: Mapping[str, Any], *, run_created_at: str) -> str:
    return "\n".join(
        [
            "# Real public source coverage and freshness",
            "",
            f"- Report state: `{summary['report_state']}`",
            f"- Source run created at: `{run_created_at or 'UNKNOWN'}`",
            f"- Registered sources observed: `{summary['observed_registered_source_count']}/{summary['registered_source_count']}`",
            f"- Detail coverage: `{summary['detail_captured_ref_count']}/{summary['detail_expected_candidate_count']}` target refs; `{summary['detail_captured_unique_snapshot_count']}` unique snapshots",
            f"- Attachment target coverage: `{summary['attachment_covered_target_count']}/{summary['attachment_expected_or_discovered_target_count']}`",
            f"- Blocked target rate: `{summary['blocked_target_rate']}`",
            f"- Fresh external-claim-eligible sources: `{summary['external_claim_eligible_source_count']}`",
            "- Zero matches mean only NO_MATCH_IN_OBSERVED_QUERY_SCOPE, never no opportunity.",
            "- External claims are limited to registered sources and explicit fresh observation windows.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build offline real-public source coverage and freshness report"
    )
    parser.add_argument("--run-manifest", default=str(DEFAULT_RUN_MANIFEST))
    parser.add_argument("--storage-json", default=None)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()
    result = build_real_public_source_coverage_freshness_report(
        run_manifest_json=args.run_manifest,
        storage_json=args.storage_json,
        output_root=args.output_root,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["report_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
