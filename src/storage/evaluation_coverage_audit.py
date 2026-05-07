from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.evaluation_corpus import (
    EvaluationCorpusSeed,
    default_evaluation_seed_path,
    load_evaluation_corpus_seeds,
    probe_evaluation_text,
)


EVALUATION_SEED_COVERAGE_AUDIT_OBJECT_TYPE = "evaluation_seed_coverage_audit_manifest"
EVALUATION_COVERAGE_AUDIT_VERSION = 1
EVALUATION_COVERAGE_RULESET_ID = "evaluation-seed-coverage-audit-v1"
EVALUATION_COVERAGE_ADAPTER_ID = "evaluation-coverage-audit-builder"

DEFAULT_REQUIREMENTS_PATH = Path("contracts") / "evaluation" / "evaluation_coverage_requirements.json"


@dataclass(frozen=True)
class SeedClassification:
    seed_id: str
    source_url: str
    source_family: str
    jurisdiction: str
    document_kind: str
    seed_tags: list[str]
    evaluation_method_family: str
    candidate_selection_mode: str
    has_dark_bid_requirement: bool
    has_bright_bid_requirement: bool
    candidate_rows_count: int
    candidate_count_optional: int | None
    objection_window_optional: str | None
    fairness_signal_types: list[str]
    source_role: str

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CoverageItem:
    requirement_id: str
    dimension: str
    coverage_state: str
    matched_seed_count: int
    minimum_seed_count: int
    covered_values: list[str]
    missing_values: list[str]
    matched_seed_ids: list[str]
    basis_refs: list[str]
    gap_action: str
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_evaluation_coverage_requirements_path() -> Path:
    return DEFAULT_REQUIREMENTS_PATH


def build_evaluation_coverage_audit(
    *,
    seed_json: str | Path | None = None,
    requirements_json: str | Path | None = None,
    database_url: str | None = None,
    target_backend: str = "postgresql",
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    seed_path = Path(seed_json) if seed_json is not None else default_evaluation_seed_path()
    requirements_path = Path(requirements_json) if requirements_json is not None else default_evaluation_coverage_requirements_path()
    blocking_reasons = _initial_blocking_reasons(
        seed_path=seed_path,
        requirements_path=requirements_path,
        execute=execute,
        database_url=database_url,
    )

    seeds: list[EvaluationCorpusSeed] = []
    requirements_payload: dict[str, Any] = {}
    if seed_path.exists():
        try:
            seeds = load_evaluation_corpus_seeds(seed_path)
        except Exception as exc:
            blocking_reasons.append(f"evaluation_seed_load_failed:{exc}")
    if requirements_path.exists():
        try:
            requirements_payload = _load_requirements(requirements_path)
        except Exception as exc:
            blocking_reasons.append(f"evaluation_coverage_requirements_load_failed:{exc}")
    if not seeds:
        blocking_reasons.append("evaluation_seed_empty")
    requirements = _requirement_items(requirements_payload)
    if not requirements:
        blocking_reasons.append("evaluation_coverage_requirements_empty")

    classifications = [_classify_seed(seed) for seed in seeds]
    coverage_items = build_coverage_items(
        classifications=classifications,
        requirements=requirements,
    )
    manifest = build_coverage_manifest(
        classifications=classifications,
        coverage_items=coverage_items,
        requirements_payload=requirements_payload,
        seed_path=seed_path,
        requirements_path=requirements_path,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created,
    )
    result = {
        "coverage_audit_mode": "EXECUTED" if execute else "DRY_RUN",
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
            raise RuntimeError("evaluation coverage audit is not safe to execute: " + ", ".join(blocking_reasons))
        settings = Settings(
            storage_backend=target_backend,
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
        )
        session = DatabaseSession(settings=settings)
        try:
            with session.bulk_write():
                session.upsert_record(_coverage_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_evaluation_seed_coverage_audit_manifest_count": 1,
                "download_enabled": False,
                "fetch_public_urls_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        finally:
            session.close()
    return result


def build_coverage_items(
    *,
    classifications: Iterable[SeedClassification],
    requirements: Iterable[Mapping[str, Any]],
) -> list[CoverageItem]:
    classified = list(classifications)
    items: list[CoverageItem] = []
    for raw_requirement in requirements:
        requirement = dict(raw_requirement)
        matched = _matched_classifications(classified, requirement)
        covered_values, missing_values = _value_coverage(matched, requirement)
        minimum = _int_value(requirement.get("minimum_seed_count"), default=1)
        if not matched:
            state = "MISSING"
        elif len(matched) < minimum or missing_values:
            state = "PARTIAL"
        else:
            state = "COVERED"
        items.append(
            CoverageItem(
                requirement_id=str(requirement.get("requirement_id") or ""),
                dimension=str(requirement.get("dimension") or ""),
                coverage_state=state,
                matched_seed_count=len(matched),
                minimum_seed_count=minimum,
                covered_values=covered_values,
                missing_values=missing_values,
                matched_seed_ids=[item.seed_id for item in matched],
                basis_refs=_string_list(requirement.get("basis_refs")),
                gap_action=str(requirement.get("gap_action") or ""),
                review_required=True,
                customer_visible_allowed=False,
                no_legal_conclusion=True,
            )
        )
    return items


def build_coverage_manifest(
    *,
    classifications: list[SeedClassification],
    coverage_items: list[CoverageItem],
    requirements_payload: Mapping[str, Any],
    seed_path: Path,
    requirements_path: Path,
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    items = [item.as_payload() for item in coverage_items]
    classified_payload = [item.as_payload() for item in classifications]
    fingerprint = _fingerprint(
        {
            "requirements_id": requirements_payload.get("requirements_id"),
            "coverage_items": items,
            "seed_classifications": classified_payload,
        }
    )
    manifest = {
        "manifest_version": EVALUATION_COVERAGE_AUDIT_VERSION,
        "ruleset_id": EVALUATION_COVERAGE_RULESET_ID,
        "adapter_id": EVALUATION_COVERAGE_ADAPTER_ID,
        "manifest_id": f"EVALUATION-SEED-COVERAGE-AUDIT-{fingerprint[:16]}",
        "manifest_kind": EVALUATION_SEED_COVERAGE_AUDIT_OBJECT_TYPE,
        "created_at": created_at,
        "seed_path": str(seed_path),
        "requirements_path": str(requirements_path),
        "requirements_id": str(requirements_payload.get("requirements_id") or ""),
        "database_url_redacted": _redact_database_url(database_url),
        "target_storage_backend": target_backend,
        "coverage_fingerprint": fingerprint,
        "basis_sources": list(requirements_payload.get("basis_sources") or []),
        "items": items,
        "gap_items": [item for item in items if item["coverage_state"] != "COVERED"],
        "sample_seed_classifications": classified_payload[:80],
        "summary": _summary(classifications=classifications, coverage_items=coverage_items),
        "safety": _safety(),
    }
    manifest["manifest_sha256"] = _manifest_sha256(manifest)
    return manifest


def _classify_seed(seed: EvaluationCorpusSeed) -> SeedClassification:
    probe = probe_evaluation_text(seed=seed, text=seed.probe_text_optional)
    tags = list(dict.fromkeys(str(tag) for tag in seed.seed_tags))
    return SeedClassification(
        seed_id=seed.seed_id,
        source_url=seed.source_url,
        source_family=seed.source_family,
        jurisdiction=seed.jurisdiction,
        document_kind=seed.document_kind,
        seed_tags=tags,
        evaluation_method_family=probe.evaluation_method_family,
        candidate_selection_mode=probe.candidate_selection_mode,
        has_dark_bid_requirement=probe.has_dark_bid_requirement,
        has_bright_bid_requirement=probe.has_bright_bid_requirement,
        candidate_rows_count=len(probe.candidate_rows_probe_summary),
        candidate_count_optional=probe.candidate_count_optional,
        objection_window_optional=probe.objection_window_optional,
        fairness_signal_types=list(probe.fairness_signal_types),
        source_role=_source_role(seed),
    )


def _matched_classifications(
    classifications: list[SeedClassification],
    requirement: Mapping[str, Any],
) -> list[SeedClassification]:
    match = requirement.get("match")
    if not isinstance(match, Mapping):
        match = {}
    document_kinds = set(_string_list(match.get("document_kinds")))
    source_families = set(_string_list(match.get("source_families")))
    seed_tags = set(_string_list(match.get("seed_tags")))
    matched: list[SeedClassification] = []
    for item in classifications:
        if document_kinds and item.document_kind not in document_kinds:
            continue
        if source_families and item.source_family not in source_families:
            continue
        if seed_tags and not seed_tags.intersection(item.seed_tags):
            continue
        matched.append(item)
    if document_kinds or source_families or seed_tags:
        return matched
    return list(classifications)


def _value_coverage(
    matched: list[SeedClassification],
    requirement: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    if "required_jurisdictions" in requirement:
        return _compare_required_values(_string_list(requirement["required_jurisdictions"]), {item.jurisdiction for item in matched})
    if "required_tags_or_families" in requirement:
        observed: set[str] = set()
        for item in matched:
            observed.update(item.seed_tags)
            observed.add(item.evaluation_method_family)
        return _compare_required_values(_string_list(requirement["required_tags_or_families"]), observed)
    if "required_tags_or_modes" in requirement:
        observed = set()
        for item in matched:
            observed.update(item.seed_tags)
            observed.add(item.candidate_selection_mode)
        return _compare_required_values(_string_list(requirement["required_tags_or_modes"]), observed)
    if "required_document_kinds" in requirement:
        return _compare_required_values(_string_list(requirement["required_document_kinds"]), {item.document_kind for item in matched})
    if "required_tags_or_markers" in requirement:
        observed = set()
        for item in matched:
            observed.update(item.seed_tags)
            observed.update(item.fairness_signal_types)
            if item.has_dark_bid_requirement:
                observed.add("dark_bid")
            if item.has_bright_bid_requirement:
                observed.add("bright_bid")
            if item.document_kind == "clarification":
                observed.add("clarification")
        return _compare_required_values(_string_list(requirement["required_tags_or_markers"]), observed)
    return [], []


def _compare_required_values(required: list[str], observed: set[str]) -> tuple[list[str], list[str]]:
    covered = [value for value in required if value in observed]
    missing = [value for value in required if value not in observed]
    return covered, missing


def _summary(
    *,
    classifications: list[SeedClassification],
    coverage_items: list[CoverageItem],
) -> dict[str, Any]:
    return {
        "seed_count": len(classifications),
        "requirement_count": len(coverage_items),
        "covered_count": sum(1 for item in coverage_items if item.coverage_state == "COVERED"),
        "partial_count": sum(1 for item in coverage_items if item.coverage_state == "PARTIAL"),
        "missing_count": sum(1 for item in coverage_items if item.coverage_state == "MISSING"),
        "gap_count": sum(1 for item in coverage_items if item.coverage_state != "COVERED"),
        "official_basis_count": sum(1 for item in classifications if item.document_kind == "official_basis"),
        "local_method_count": sum(1 for item in classifications if item.document_kind == "local_method"),
        "real_public_entry_count": sum(1 for item in classifications if "real_public_entry" in item.seed_tags),
        "real_project_sample_seed_count": sum(1 for item in classifications if "real_project_sample" in item.seed_tags),
        "document_kind_counts": _counts(item.document_kind for item in classifications),
        "jurisdiction_counts": _counts(item.jurisdiction for item in classifications),
        "evaluation_method_family_counts": _counts(item.evaluation_method_family for item in classifications),
        "candidate_selection_mode_counts": _counts(item.candidate_selection_mode for item in classifications),
        "coverage_state_counts": _counts(item.coverage_state for item in coverage_items),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _coverage_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    manifest_id = str(manifest["manifest_id"])
    return PersistedRecord(
        object_type=EVALUATION_SEED_COVERAGE_AUDIT_OBJECT_TYPE,
        record_id=manifest_id,
        stage_scope=0,
        project_id=None,
        object_refs={"manifest_id": manifest_id, "requirements_id": str(manifest.get("requirements_id") or "")},
        decision_states={"evaluation_seed_coverage_audit_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest.get("manifest_sha256") or "")},
        governed_state={
            "primary_status": "EVALUATION_SEED_COVERAGE_AUDIT_READY",
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


def _load_requirements(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("evaluation coverage requirements must be a JSON object")
    return dict(payload)


def _requirement_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = payload.get("requirements")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _initial_blocking_reasons(
    *,
    seed_path: Path,
    requirements_path: Path,
    execute: bool,
    database_url: str | None,
) -> list[str]:
    reasons: list[str] = []
    if not seed_path.exists():
        reasons.append("evaluation_seed_file_missing")
    if not requirements_path.exists():
        reasons.append("evaluation_coverage_requirements_file_missing")
    if execute and not database_url:
        reasons.append("database_url_required_for_execute")
    return reasons


def _source_role(seed: EvaluationCorpusSeed) -> str:
    tags = set(seed.seed_tags)
    if seed.document_kind == "official_basis":
        return "official_basis"
    if seed.document_kind == "local_method":
        return "local_method"
    if "real_public_entry" in tags:
        return "real_public_entry"
    if "real_project_sample" in tags:
        return "real_project_sample"
    if urlsplit(seed.source_url).hostname == "example.invalid" or seed.source_family == "offline_seed_sample":
        return "offline_probe_sample"
    return "public_sample"


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
    parser = argparse.ArgumentParser(description="Audit evaluation corpus seed coverage against machine requirements.")
    parser.add_argument("--seed-json", default=str(default_evaluation_seed_path()))
    parser.add_argument("--requirements-json", default=str(default_evaluation_coverage_requirements_path()))
    parser.add_argument("--database-url")
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evaluation_coverage_audit(
        seed_json=args.seed_json,
        requirements_json=args.requirements_json,
        database_url=args.database_url,
        target_backend=args.target_backend,
        execute=args.execute,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"evaluation coverage audit {result['coverage_audit_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVALUATION_SEED_COVERAGE_AUDIT_OBJECT_TYPE",
    "build_coverage_items",
    "build_evaluation_coverage_audit",
    "default_evaluation_coverage_requirements_path",
]
