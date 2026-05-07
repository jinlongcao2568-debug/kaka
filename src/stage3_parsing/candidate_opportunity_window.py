from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage3_parsing.evaluation_profiles import EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE
from storage.db import DatabaseSession, PersistedRecord


CANDIDATE_OPPORTUNITY_WINDOW_MANIFEST_OBJECT_TYPE = "candidate_opportunity_window_manifest"
CANDIDATE_OPPORTUNITY_WINDOW_VERSION = 1
CANDIDATE_OPPORTUNITY_WINDOW_RULESET_ID = "candidate-opportunity-window-v1"
CANDIDATE_OPPORTUNITY_WINDOW_ADAPTER_ID = "candidate-opportunity-window-builder"

WINDOW_REVIEW_READY = "WINDOW_REVIEW_READY"
WINDOW_REVIEW_ONLY = "WINDOW_REVIEW_ONLY"
WINDOW_BLOCKED_INSUFFICIENT_CANDIDATES = "WINDOW_BLOCKED_INSUFFICIENT_CANDIDATES"

VALUE_TIMER_ACTIVE = "OBJECTION_WINDOW_ACTIVE"
VALUE_TIMER_EXPIRED = "OBJECTION_WINDOW_EXPIRED"
VALUE_TIMER_UNKNOWN = "OBJECTION_WINDOW_UNKNOWN"
VALUE_TIMER_NO_COUNTDOWN_SINGLE_WINNER = "NO_COUNTDOWN_SINGLE_WINNER"

PRIORITY_HIGH = "P1_HIGH"
PRIORITY_MEDIUM = "P2_MEDIUM"
PRIORITY_LOW = "P3_LOW"


@dataclass(frozen=True)
class CandidateOpportunityWindowItem:
    seed_id: str
    source_url: str
    document_kind: str
    snapshot_id_optional: str | None
    candidate_selection_mode: str
    candidate_rows: list[dict[str, Any]]
    candidate_count_optional: int | None
    objection_window_optional: str | None
    window_state: str
    review_priority: str
    value_timer_state: str
    candidate_field_completeness: dict[str, Any]
    review_required: bool = True
    review_reasons: list[str] = field(default_factory=list)
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True
    sales_action_enabled: bool = False
    stage4_public_evidence_readback_generation_enabled: bool = False
    stage5_rule_execution_enabled: bool = False

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def build_candidate_opportunity_windows(
    *,
    database_url: str,
    target_backend: str = "postgresql",
    object_storage_path: str | Path | None = None,
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    object_root = Path(object_storage_path) if object_storage_path is not None else default_object_storage_path()
    settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_root),
    )
    session = DatabaseSession(settings=settings)
    try:
        profile_record = _latest_record(session.list_records(EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE))
        blocking_reasons = _blocking_reasons(profile_record=profile_record)
        profile_payload = dict(profile_record.payload) if profile_record else {}
        items = build_window_items(
            profile_items=list(profile_payload.get("items") or []),
            reference_date=_date_from_iso(created),
        )
        manifest = build_window_manifest(
            items=items,
            evaluation_stage3_profile_manifest_id=str(profile_payload.get("manifest_id") or ""),
            database_url=database_url,
            target_backend=target_backend,
            object_storage_path=object_root,
            created_at=created,
        )
        result = {
            "window_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "manifest": manifest,
            "summary": manifest["summary"],
            "execution": {
                "executed": False,
                "target_mutation_enabled": False,
                "database_write_enabled": False,
                "sales_action_enabled": False,
                "customer_report_generation_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
                "large_object_blob_database_import_enabled": False,
            },
        }
        if execute and not blocking_reasons:
            with session.bulk_write():
                session.upsert_record(_window_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_candidate_opportunity_window_manifest_count": 1,
                "sales_action_enabled": False,
                "customer_report_generation_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        return result
    finally:
        session.close()


def build_window_items(
    *,
    profile_items: Iterable[Mapping[str, Any]],
    reference_date: date,
) -> list[CandidateOpportunityWindowItem]:
    items: list[CandidateOpportunityWindowItem] = []
    for raw_item in profile_items:
        item = dict(raw_item)
        document_kind = str(item.get("document_kind") or "")
        if document_kind in {"official_basis", "local_method"}:
            continue
        candidate_profile = dict(item.get("candidate_set_profile") or {})
        mode = str(candidate_profile.get("candidate_selection_mode") or "unknown")
        candidate_rows = _candidate_rows(candidate_profile.get("candidate_rows"))
        candidate_count = _candidate_count(candidate_profile=candidate_profile, candidate_rows=candidate_rows)
        objection_window = _text(candidate_profile.get("objection_window_optional"))
        timer_state = _value_timer_state(
            objection_window=objection_window,
            candidate_selection_mode=mode,
            document_kind=str(item.get("document_kind") or ""),
            reference_date=reference_date,
        )
        completeness = _candidate_field_completeness(candidate_rows)
        window_state, reasons = _window_decision(
            snapshot_id=_text(item.get("snapshot_id_optional")),
            candidate_selection_mode=mode,
            candidate_rows=candidate_rows,
            candidate_count=candidate_count,
            objection_window=objection_window,
            value_timer_state=timer_state,
            document_kind=str(item.get("document_kind") or ""),
        )
        priority = _review_priority(
            window_state=window_state,
            candidate_selection_mode=mode,
            candidate_count=candidate_count,
            value_timer_state=timer_state,
            completeness=completeness,
        )
        items.append(
            CandidateOpportunityWindowItem(
                seed_id=str(item.get("seed_id") or ""),
                source_url=str(item.get("source_url") or ""),
                document_kind=document_kind,
                snapshot_id_optional=_text(item.get("snapshot_id_optional")),
                candidate_selection_mode=mode,
                candidate_rows=candidate_rows,
                candidate_count_optional=candidate_count,
                objection_window_optional=objection_window,
                window_state=window_state,
                review_priority=priority,
                value_timer_state=timer_state,
                candidate_field_completeness=completeness,
                review_required=True,
                review_reasons=reasons,
                customer_visible_allowed=False,
                no_legal_conclusion=True,
                sales_action_enabled=False,
                stage4_public_evidence_readback_generation_enabled=False,
                stage5_rule_execution_enabled=False,
            )
        )
    return items


def build_window_manifest(
    *,
    items: list[CandidateOpportunityWindowItem],
    evaluation_stage3_profile_manifest_id: str,
    database_url: str,
    target_backend: str,
    object_storage_path: Path,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "manifest_version": CANDIDATE_OPPORTUNITY_WINDOW_VERSION,
            "ruleset_id": CANDIDATE_OPPORTUNITY_WINDOW_RULESET_ID,
            "evaluation_stage3_profile_manifest_id": evaluation_stage3_profile_manifest_id,
            "items": [
                {
                    "seed_id": item.seed_id,
                    "snapshot_id_optional": item.snapshot_id_optional,
                    "candidate_selection_mode": item.candidate_selection_mode,
                    "candidate_count_optional": item.candidate_count_optional,
                    "objection_window_optional": item.objection_window_optional,
                    "window_state": item.window_state,
                    "review_priority": item.review_priority,
                    "value_timer_state": item.value_timer_state,
                }
                for item in items
            ],
        }
    )
    manifest_id = f"CANDIDATE-OPPORTUNITY-WINDOW-{fingerprint[:16]}"
    payload = {
        "manifest_version": CANDIDATE_OPPORTUNITY_WINDOW_VERSION,
        "ruleset_id": CANDIDATE_OPPORTUNITY_WINDOW_RULESET_ID,
        "adapter_id": CANDIDATE_OPPORTUNITY_WINDOW_ADAPTER_ID,
        "manifest_id": manifest_id,
        "window_manifest_id": manifest_id,
        "created_at": created_at,
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "object_storage_path": str(object_storage_path),
        "evaluation_stage3_profile_manifest_id": evaluation_stage3_profile_manifest_id,
        "window_fingerprint": fingerprint,
        "summary": _summary(items),
        "items": [item.as_payload() for item in items],
        "sample_items": [item.as_payload() for item in items[:50]],
        "safety": _safety(),
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _window_decision(
    *,
    snapshot_id: str | None,
    candidate_selection_mode: str,
    candidate_rows: list[dict[str, Any]],
    candidate_count: int | None,
    objection_window: str | None,
    value_timer_state: str,
    document_kind: str,
) -> tuple[str, list[str]]:
    reasons = ["candidate_opportunity_window_review_required"]
    if not snapshot_id:
        reasons.append("snapshot_id_missing")
    if document_kind == "award_result" or candidate_selection_mode == "single_winner":
        reasons.append("single_winner_or_award_result_no_preaward_countdown")
        return WINDOW_REVIEW_ONLY, list(dict.fromkeys(reasons))
    if not candidate_rows or (candidate_count is not None and candidate_count < 2):
        reasons.append("candidate_rows_insufficient")
        return WINDOW_BLOCKED_INSUFFICIENT_CANDIDATES, list(dict.fromkeys(reasons))
    if candidate_count is None:
        reasons.append("candidate_count_unresolved")
    if not objection_window:
        reasons.append("objection_window_missing")
        return WINDOW_REVIEW_ONLY, list(dict.fromkeys(reasons))
    if value_timer_state == VALUE_TIMER_EXPIRED:
        reasons.append("objection_window_expired")
        return WINDOW_REVIEW_ONLY, list(dict.fromkeys(reasons))
    if candidate_selection_mode not in {"ranked_candidates", "unranked_candidates", "bid_separation_candidates"}:
        reasons.append("candidate_selection_mode_not_actionable")
        return WINDOW_REVIEW_ONLY, list(dict.fromkeys(reasons))
    return WINDOW_REVIEW_READY, list(dict.fromkeys(reasons))


def _review_priority(
    *,
    window_state: str,
    candidate_selection_mode: str,
    candidate_count: int | None,
    value_timer_state: str,
    completeness: Mapping[str, Any],
) -> str:
    if window_state != WINDOW_REVIEW_READY:
        return PRIORITY_LOW
    score = 0
    if candidate_selection_mode == "ranked_candidates":
        score += 3
    elif candidate_selection_mode in {"bid_separation_candidates", "unranked_candidates"}:
        score += 2
    if value_timer_state == VALUE_TIMER_ACTIVE:
        score += 3
    if candidate_count and candidate_count >= 2:
        score += 2
    if int(completeness.get("rows_with_project_manager_or_cert_count") or 0) > 0:
        score += 1
    if int(completeness.get("rows_with_price_or_score_count") or 0) > 0:
        score += 1
    if score >= 9:
        return PRIORITY_HIGH
    if score >= 6:
        return PRIORITY_MEDIUM
    return PRIORITY_LOW


def _value_timer_state(
    *,
    objection_window: str | None,
    candidate_selection_mode: str,
    document_kind: str,
    reference_date: date,
) -> str:
    if document_kind == "award_result" or candidate_selection_mode == "single_winner":
        return VALUE_TIMER_NO_COUNTDOWN_SINGLE_WINNER
    if not objection_window:
        return VALUE_TIMER_UNKNOWN
    dates = _dates_from_text(objection_window)
    if not dates:
        return VALUE_TIMER_UNKNOWN
    end_date = dates[-1]
    return VALUE_TIMER_ACTIVE if reference_date <= end_date else VALUE_TIMER_EXPIRED


def _candidate_field_completeness(candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows_with_pm_or_cert = sum(
        1 for row in candidate_rows if row.get("project_manager_optional") or row.get("certificate_no_optional")
    )
    rows_with_price_or_score = sum(
        1 for row in candidate_rows if row.get("bid_price_optional") or row.get("total_score_optional")
    )
    return {
        "candidate_row_count": len(candidate_rows),
        "rows_with_project_manager_or_cert_count": rows_with_pm_or_cert,
        "rows_with_price_or_score_count": rows_with_price_or_score,
        "field_complete_for_priority": bool(candidate_rows and rows_with_pm_or_cert and rows_with_price_or_score),
    }


def _candidate_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in list(value or []):
        if not isinstance(raw, Mapping):
            continue
        row = {
            "candidate_name": _limit_text(_text(raw.get("candidate_name")), limit=200),
            "candidate_rank_optional": raw.get("candidate_rank_optional"),
            "bid_price_optional": _limit_text(_text(raw.get("bid_price_optional")), limit=120),
            "total_score_optional": _limit_text(_text(raw.get("total_score_optional")), limit=80),
            "project_manager_optional": _limit_text(_text(raw.get("project_manager_optional")), limit=120),
            "certificate_no_optional": _limit_text(_text(raw.get("certificate_no_optional")), limit=120),
            "match_basis": _text(raw.get("match_basis")) or "profile_candidate_row",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        if row["candidate_name"]:
            rows.append(row)
    return rows[:20]


def _candidate_count(*, candidate_profile: Mapping[str, Any], candidate_rows: list[dict[str, Any]]) -> int | None:
    raw_count = candidate_profile.get("candidate_count_optional")
    try:
        count = int(raw_count) if raw_count not in (None, "") else None
    except (TypeError, ValueError):
        count = None
    if count is None and candidate_rows:
        return len(candidate_rows)
    return count


def _window_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=CANDIDATE_OPPORTUNITY_WINDOW_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=3,
        project_id=None,
        object_refs={
            "evaluation_stage3_profile_manifest_id": str(manifest["evaluation_stage3_profile_manifest_id"]),
        },
        decision_states={"candidate_opportunity_window_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "CANDIDATE_OPPORTUNITY_WINDOW_READY",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "sales_action_enabled": False,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _summary(items: list[CandidateOpportunityWindowItem]) -> dict[str, Any]:
    return {
        "window_item_count": len(items),
        "window_state_counts": _counts(item.window_state for item in items),
        "review_priority_counts": _counts(item.review_priority for item in items),
        "value_timer_state_counts": _counts(item.value_timer_state for item in items),
        "candidate_selection_mode_counts": _counts(item.candidate_selection_mode for item in items),
        "review_ready_count": sum(1 for item in items if item.window_state == WINDOW_REVIEW_READY),
        "blocked_insufficient_candidate_count": sum(
            1 for item in items if item.window_state == WINDOW_BLOCKED_INSUFFICIENT_CANDIDATES
        ),
        "sales_action_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "large_object_blob_database_import_enabled": False,
    }


def _safety() -> dict[str, Any]:
    return {
        "external_service_connection_enabled": False,
        "download_enabled": False,
        "sales_action_enabled": False,
        "customer_report_generation_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "large_object_blob_database_import_enabled": False,
    }


def _blocking_reasons(*, profile_record: PersistedRecord | None) -> list[str]:
    return ["evaluation_stage3_profile_manifest_missing"] if profile_record is None else []


def _latest_record(records: list[PersistedRecord]) -> PersistedRecord | None:
    if not records:
        return None
    return sorted(
        records,
        key=lambda row: (
            str(row.payload.get("created_at") or ""),
            row.persisted_at,
            row.record_id,
        ),
    )[-1]


def _dates_from_text(value: str) -> list[date]:
    dates: list[date] = []
    for match in re.finditer(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", value):
        try:
            dates.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    return dates


def _date_from_iso(value: str) -> date:
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return datetime.now(timezone.utc).date()


def _text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return str(value)


def _limit_text(value: str | None, *, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:limit]


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build candidate opportunity window manifests.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--object-storage-path", default=str(default_object_storage_path()))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_candidate_opportunity_windows(
        database_url=args.database_url,
        target_backend=args.target_backend,
        object_storage_path=args.object_storage_path,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"candidate opportunity windows {result['window_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANDIDATE_OPPORTUNITY_WINDOW_MANIFEST_OBJECT_TYPE",
    "WINDOW_BLOCKED_INSUFFICIENT_CANDIDATES",
    "WINDOW_REVIEW_ONLY",
    "WINDOW_REVIEW_READY",
    "build_candidate_opportunity_windows",
    "build_window_items",
]
