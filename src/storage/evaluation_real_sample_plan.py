from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.evaluation_corpus import EvaluationCorpusSeed, default_evaluation_seed_path, load_evaluation_corpus_seeds


EVALUATION_REAL_PROJECT_SAMPLE_PLAN_OBJECT_TYPE = "evaluation_real_project_sample_plan_manifest"
EVALUATION_REAL_PROJECT_SAMPLE_PLAN_VERSION = 1
EVALUATION_REAL_PROJECT_SAMPLE_PLAN_RULESET_ID = "evaluation-real-project-sample-plan-v1"
EVALUATION_REAL_PROJECT_SAMPLE_PLAN_ADAPTER_ID = "evaluation-real-sample-plan-builder"

DEFAULT_TARGETS_PATH = Path("contracts") / "evaluation" / "evaluation_real_project_sample_targets.json"

PLAN_READY = "SAMPLE_TARGET_PLANNED"
BLOCKED_PROFILE_MISSING = "REVIEW_BLOCKED_PROFILE_MISSING"
BLOCKED_INVALID_TARGET = "REVIEW_BLOCKED_INVALID_TARGET"

DOCUMENT_KINDS = frozenset(
    {
        "tender_file",
        "candidate_notice",
        "award_result",
        "clarification",
        "failed_bid_notice",
        "complaint_decision",
        "flow_or_re_tender_notice",
        "official_case",
    }
)


@dataclass(frozen=True)
class RealProjectSampleTarget:
    target_id: str
    jurisdiction: str
    platform_name: str
    entry_seed_id: str
    required_fetch_profile_id_optional: str | None
    source_family: str
    project_type: str
    document_kind: str
    target_count: int
    selection_filters: list[str]

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RealProjectSamplePlanItem:
    target_id: str
    jurisdiction: str
    platform_name: str
    entry_seed_id: str
    entry_seed_present: bool
    entry_seed_fetch_profile_id_optional: str | None
    required_fetch_profile_id_optional: str | None
    profile_available: bool
    source_family: str
    project_type: str
    document_kind: str
    target_count: int
    selection_filters: list[str]
    plan_state: str
    review_reasons: list[str]
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True
    download_enabled: bool = False
    fetch_public_urls_enabled: bool = False
    stage4_public_evidence_readback_generation_enabled: bool = False
    stage5_rule_execution_enabled: bool = False

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_evaluation_real_project_sample_targets_path() -> Path:
    return DEFAULT_TARGETS_PATH


def build_evaluation_real_sample_plan(
    *,
    targets_json: str | Path | None = None,
    seed_json: str | Path | None = None,
    database_url: str | None = None,
    target_backend: str = "postgresql",
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    targets_path = Path(targets_json) if targets_json is not None else default_evaluation_real_project_sample_targets_path()
    seed_path = Path(seed_json) if seed_json is not None else default_evaluation_seed_path()
    blocking_reasons = _initial_blocking_reasons(
        targets_path=targets_path,
        seed_path=seed_path,
        execute=execute,
        database_url=database_url,
    )

    targets_payload: dict[str, Any] = {}
    targets: list[RealProjectSampleTarget] = []
    seeds: list[EvaluationCorpusSeed] = []
    if targets_path.exists():
        try:
            targets_payload = _load_targets_payload(targets_path)
            targets = _load_targets(targets_payload)
        except Exception as exc:
            blocking_reasons.append(f"evaluation_real_sample_targets_load_failed:{exc}")
    if seed_path.exists():
        try:
            seeds = load_evaluation_corpus_seeds(seed_path)
        except Exception as exc:
            blocking_reasons.append(f"evaluation_seed_load_failed:{exc}")
    if not targets:
        blocking_reasons.append("evaluation_real_sample_targets_empty")
    if not seeds:
        blocking_reasons.append("evaluation_seed_empty")

    items = build_plan_items(targets=targets, seeds=seeds)
    manifest = build_plan_manifest(
        targets_payload=targets_payload,
        items=items,
        targets_path=targets_path,
        seed_path=seed_path,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created,
    )
    result = {
        "real_sample_plan_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": manifest["summary"],
        "execution": {
            "executed": False,
            "target_mutation_enabled": False,
            "database_write_enabled": False,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
    }
    if execute:
        if blocking_reasons:
            raise RuntimeError("evaluation real sample plan is not safe to execute: " + ", ".join(blocking_reasons))
        settings = Settings(
            storage_backend=target_backend,
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
        )
        session = DatabaseSession(settings=settings)
        try:
            with session.bulk_write():
                session.upsert_record(_plan_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_evaluation_real_project_sample_plan_manifest_count": 1,
                "download_enabled": False,
                "fetch_public_urls_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        finally:
            session.close()
    return result


def build_plan_items(
    *,
    targets: Iterable[RealProjectSampleTarget],
    seeds: Iterable[EvaluationCorpusSeed],
) -> list[RealProjectSamplePlanItem]:
    seed_by_id = {seed.seed_id: seed for seed in seeds}
    items: list[RealProjectSamplePlanItem] = []
    for target in targets:
        seed = seed_by_id.get(target.entry_seed_id)
        seed_profile = seed.fetch_profile_id_optional if seed else None
        reasons: list[str] = []
        state = PLAN_READY
        if target.document_kind not in DOCUMENT_KINDS:
            state = BLOCKED_INVALID_TARGET
            reasons.append("invalid_document_kind")
        if target.target_count <= 0:
            state = BLOCKED_INVALID_TARGET
            reasons.append("target_count_must_be_positive")
        if seed is None:
            state = BLOCKED_PROFILE_MISSING
            reasons.append("entry_seed_missing")
        elif not seed_profile:
            state = BLOCKED_PROFILE_MISSING
            reasons.append("entry_seed_fetch_profile_missing")
        elif target.required_fetch_profile_id_optional and seed_profile != target.required_fetch_profile_id_optional:
            state = BLOCKED_PROFILE_MISSING
            reasons.append("required_fetch_profile_mismatch")
        profile_available = bool(seed_profile) and (
            not target.required_fetch_profile_id_optional or seed_profile == target.required_fetch_profile_id_optional
        )
        items.append(
            RealProjectSamplePlanItem(
                target_id=target.target_id,
                jurisdiction=target.jurisdiction,
                platform_name=target.platform_name,
                entry_seed_id=target.entry_seed_id,
                entry_seed_present=seed is not None,
                entry_seed_fetch_profile_id_optional=seed_profile,
                required_fetch_profile_id_optional=target.required_fetch_profile_id_optional,
                profile_available=profile_available,
                source_family=target.source_family,
                project_type=target.project_type,
                document_kind=target.document_kind,
                target_count=target.target_count,
                selection_filters=list(target.selection_filters),
                plan_state=state,
                review_reasons=reasons,
                review_required=True,
                customer_visible_allowed=False,
                no_legal_conclusion=True,
                download_enabled=False,
                fetch_public_urls_enabled=False,
                stage4_public_evidence_readback_generation_enabled=False,
                stage5_rule_execution_enabled=False,
            )
        )
    return items


def build_plan_manifest(
    *,
    targets_payload: Mapping[str, Any],
    items: list[RealProjectSamplePlanItem],
    targets_path: Path,
    seed_path: Path,
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    item_payloads = [item.as_payload() for item in items]
    fingerprint = _fingerprint(
        {
            "target_set_id": targets_payload.get("target_set_id"),
            "items": item_payloads,
        }
    )
    manifest = {
        "manifest_version": EVALUATION_REAL_PROJECT_SAMPLE_PLAN_VERSION,
        "ruleset_id": EVALUATION_REAL_PROJECT_SAMPLE_PLAN_RULESET_ID,
        "adapter_id": EVALUATION_REAL_PROJECT_SAMPLE_PLAN_ADAPTER_ID,
        "manifest_id": f"EVALUATION-REAL-PROJECT-SAMPLE-PLAN-{fingerprint[:16]}",
        "manifest_kind": EVALUATION_REAL_PROJECT_SAMPLE_PLAN_OBJECT_TYPE,
        "created_at": created_at,
        "target_set_id": str(targets_payload.get("target_set_id") or ""),
        "targets_path": str(targets_path),
        "seed_path": str(seed_path),
        "database_url_redacted": _redact_database_url(database_url),
        "target_storage_backend": target_backend,
        "plan_fingerprint": fingerprint,
        "minimum_total_sample_goal": _int_value(targets_payload.get("minimum_total_sample_goal"), default=50),
        "items": item_payloads,
        "sample_items": item_payloads[:80],
        "summary": _summary(items),
        "safety": _safety(),
    }
    manifest["manifest_sha256"] = _manifest_sha256(manifest)
    return manifest


def _load_targets_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("evaluation real project sample targets must be a JSON object")
    return dict(payload)


def _load_targets(payload: Mapping[str, Any]) -> list[RealProjectSampleTarget]:
    raw_items = payload.get("targets")
    if not isinstance(raw_items, list):
        return []
    targets: list[RealProjectSampleTarget] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            continue
        target_id = str(raw.get("target_id") or f"REAL-SAMPLE-TARGET-{index + 1:03d}")
        if target_id in seen_ids:
            continue
        seen_ids.add(target_id)
        targets.append(
            RealProjectSampleTarget(
                target_id=target_id,
                jurisdiction=str(raw.get("jurisdiction") or "CN"),
                platform_name=str(raw.get("platform_name") or ""),
                entry_seed_id=str(raw.get("entry_seed_id") or ""),
                required_fetch_profile_id_optional=_text(raw.get("required_fetch_profile_id_optional")),
                source_family=str(raw.get("source_family") or "local_public_resource_trading_center"),
                project_type=str(raw.get("project_type") or "construction"),
                document_kind=str(raw.get("document_kind") or ""),
                target_count=_int_value(raw.get("target_count"), default=1),
                selection_filters=_string_list(raw.get("selection_filters")),
            )
        )
    return targets


def _plan_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    manifest_id = str(manifest["manifest_id"])
    return PersistedRecord(
        object_type=EVALUATION_REAL_PROJECT_SAMPLE_PLAN_OBJECT_TYPE,
        record_id=manifest_id,
        stage_scope=0,
        project_id=None,
        object_refs={
            "manifest_id": manifest_id,
            "target_set_id": str(manifest.get("target_set_id") or ""),
        },
        decision_states={"evaluation_real_project_sample_plan_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest.get("manifest_sha256") or "")},
        governed_state={
            "primary_status": "EVALUATION_REAL_PROJECT_SAMPLE_PLAN_READY",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at or build_persisted_at(),
    )


def _summary(items: list[RealProjectSamplePlanItem]) -> dict[str, Any]:
    return {
        "target_bucket_count": len(items),
        "requested_sample_goal_count": sum(item.target_count for item in items),
        "planned_sample_goal_count": sum(item.target_count for item in items if item.plan_state == PLAN_READY),
        "blocked_sample_goal_count": sum(item.target_count for item in items if item.plan_state != PLAN_READY),
        "plan_state_counts": _counts(item.plan_state for item in items),
        "jurisdiction_bucket_counts": _counts(item.jurisdiction for item in items),
        "jurisdiction_sample_goal_counts": _sum_counts((item.jurisdiction, item.target_count) for item in items),
        "document_kind_bucket_counts": _counts(item.document_kind for item in items),
        "document_kind_sample_goal_counts": _sum_counts((item.document_kind, item.target_count) for item in items),
        "entry_seed_missing_count": sum(1 for item in items if not item.entry_seed_present),
        "profile_missing_count": sum(1 for item in items if item.entry_seed_present and not item.profile_available),
        "download_enabled": False,
        "fetch_public_urls_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
    }


def _initial_blocking_reasons(
    *,
    targets_path: Path,
    seed_path: Path,
    execute: bool,
    database_url: str | None,
) -> list[str]:
    reasons: list[str] = []
    if not targets_path.exists():
        reasons.append("evaluation_real_sample_targets_file_missing")
    if not seed_path.exists():
        reasons.append("evaluation_seed_file_missing")
    if execute and not database_url:
        reasons.append("database_url_required_for_execute")
    return reasons


def _safety() -> dict[str, Any]:
    return {
        "external_service_connection_enabled": False,
        "download_enabled": False,
        "fetch_public_urls_enabled": False,
        "login_required_fetch_enabled": False,
        "captcha_resolution_enabled": False,
        "hidden_api_call_enabled": False,
        "bulk_ocr_enabled": False,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "large_object_blob_database_import_enabled": False,
    }


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _sum_counts(values: Iterable[tuple[str, int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, count in values:
        result[key] = result.get(key, 0) + count
    return dict(sorted(result.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})


def _redact_database_url(database_url: str | None) -> str:
    if not database_url or "://" not in database_url or "@" not in database_url:
        return database_url or ""
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build evaluation real project sample planning manifest.")
    parser.add_argument("--targets-json", default=str(default_evaluation_real_project_sample_targets_path()))
    parser.add_argument("--seed-json", default=str(default_evaluation_seed_path()))
    parser.add_argument("--database-url")
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evaluation_real_sample_plan(
        targets_json=args.targets_json,
        seed_json=args.seed_json,
        database_url=args.database_url,
        target_backend=args.target_backend,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"evaluation real sample plan {result['real_sample_plan_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BLOCKED_PROFILE_MISSING",
    "EVALUATION_REAL_PROJECT_SAMPLE_PLAN_OBJECT_TYPE",
    "PLAN_READY",
    "build_evaluation_real_sample_plan",
    "build_plan_items",
]
