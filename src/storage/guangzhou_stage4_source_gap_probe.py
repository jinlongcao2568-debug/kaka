from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from api.routes.operator_customer_access import _stage4_responsible_role_writeback
from shared.settings import Settings
from shared.utils import utc_now_iso
from stage4_verification.guangdong_gdcic_openplatform import (
    query_guangdong_gdcic_openplatform_hard_defect_sources,
    query_guangdong_gdcic_openplatform_person_directory,
)
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


GUANGZHOU_STAGE4_SOURCE_GAP_PROBE_KIND = "guangzhou_stage4_source_gap_probe_v1_manifest"
GUANGZHOU_STAGE4_SOURCE_GAP_PROBE_VERSION = 1
GUANGZHOU_STAGE4_SOURCE_GAP_PROBE_ADAPTER_ID = "guangzhou-stage4-source-gap-probe-v1-builder"

DEFAULT_PRESSURE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-real-public-stage4-9-pressure-v1")
DEFAULT_RUN_RESULT_JSON = DEFAULT_PRESSURE_ROOT / "run-result.json"
DEFAULT_CANDIDATE_PRESSURE_JSON = DEFAULT_PRESSURE_ROOT / "candidate-pressure-table.json"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-stage4-source-gap-probe-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
JsonGetter = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


def build_guangzhou_stage4_source_gap_probe(
    *,
    run_result_json: str | Path = DEFAULT_RUN_RESULT_JSON,
    candidate_pressure_json: str | Path = DEFAULT_CANDIDATE_PRESSURE_JSON,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    http_get_json: JsonGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_result_path = Path(run_result_json)
    candidate_pressure_path = Path(candidate_pressure_json)

    blocking_reasons: list[str] = []
    run_result = _load_json(run_result_path, blocking_reasons, "run_result_missing")
    candidate_pressure = _load_json(candidate_pressure_path, blocking_reasons, "candidate_pressure_missing")
    candidates_by_project = {
        str(item.get("project_id") or ""): dict(item)
        for item in list(run_result.get("candidate_options") or [])
        if isinstance(item, Mapping) and str(item.get("project_id") or "").strip()
    }
    pressure_rows = [
        dict(item)
        for item in list(candidate_pressure.get("records") or [])
        if isinstance(item, Mapping)
    ]
    repository = _repository(out_dir)
    candidate_records = [
        _candidate_record(
            pressure_row=row,
            candidate=dict(candidates_by_project.get(str(row.get("project_id") or ""), {})),
            repository=repository,
            http_get_json=http_get_json,
            created_at=created,
        )
        for row in pressure_rows
    ]
    source_type_summary_records = _source_type_summary_records(candidate_records)
    summary = _summary(candidate_records, source_type_summary_records, blocking_reasons)
    manifest = {
        "manifest_version": GUANGZHOU_STAGE4_SOURCE_GAP_PROBE_VERSION,
        "manifest_kind": GUANGZHOU_STAGE4_SOURCE_GAP_PROBE_KIND,
        "adapter_id": GUANGZHOU_STAGE4_SOURCE_GAP_PROBE_ADAPTER_ID,
        "pipeline_stage": "GuangzhouStage4SourceGapProbeV1",
        "manifest_id": f"GUANGZHOU-STAGE4-SOURCE-GAP-{_fingerprint({'summary': summary, 'records': candidate_records})[:16]}",
        "created_at": created,
        "source_run_result_json": str(run_result_path),
        "source_candidate_pressure_json": str(candidate_pressure_path),
        "candidate_records": candidate_records,
        "source_type_summary_records": source_type_summary_records,
        "summary": summary,
        "safety": {
            "network_enabled": True,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_stage4_source_gap_probe_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _apply_forbidden_term_scan(result)
    _write_json(out_dir / "stage4-source-gap-probe-v1.json", result)
    _write_json(out_dir / "candidate-source-gap-table.json", {"summary": summary, "records": candidate_records})
    _write_json(out_dir / "source-type-summary.json", {"summary": summary, "records": source_type_summary_records})
    return result


def _candidate_record(
    *,
    pressure_row: Mapping[str, Any],
    candidate: Mapping[str, Any],
    repository: ObjectStorageRepository,
    http_get_json: JsonGetter | None,
    created_at: str,
) -> dict[str, Any]:
    probe_candidate = _probe_candidate(candidate, pressure_row)
    hard_defect = query_guangdong_gdcic_openplatform_hard_defect_sources(
        probe_candidate,
        repository=repository,
        http_get_json=http_get_json,
    )
    person_directory = query_guangdong_gdcic_openplatform_person_directory(
        probe_candidate,
        repository=repository,
        http_get_json=http_get_json,
    )
    source_type_details = _source_type_details(hard_defect, person_directory)
    writeback = _stage4_responsible_role_writeback(probe_candidate, hard_defect)
    hard_completion = dict(hard_defect.get("responsible_role_identity_completion") or {})
    person_directory_completion = dict(person_directory.get("responsible_role_identity_completion") or {})
    effective_completion = _effective_responsible_role_identity_completion(
        hard_completion=hard_completion,
        person_directory_completion=person_directory_completion,
    )
    query_error_source_types = sorted(
        {
            detail["source_type"]
            for detail in source_type_details
            if detail["query_error_count"] > 0
        }
    )
    empty_result_source_types = sorted(
        {
            detail["source_type"]
            for detail in source_type_details
            if detail["empty_result_count"] > 0
        }
    )
    same_company_candidate_found = (
        str(person_directory.get("identity_resolution_state") or "")
        == "LOCAL_DIRECTORY_SAME_COMPANY_PERSON_CANDIDATE_FOUND"
    )
    certificate_not_publicly_confirmed = bool(
        str(person_directory.get("certificate_verification_state") or "")
        and str(person_directory.get("certificate_verification_state") or "")
        != "ANNOUNCED_CERTIFICATE_NO_FOUND_IN_GDCIC_PERSON_DIRECTORY_ROWS"
    )
    effective_completion_state = str(effective_completion.get("completion_state") or "")
    stage4_writeback_state = str(writeback.get("writeback_state") or "")
    if (
        effective_completion_state == "RESPONSIBLE_ROLE_PERSON_DIRECTORY_ONLY_MATCH"
        and stage4_writeback_state == "RESPONSIBLE_ROLE_NOT_FOUND_IN_STAGE4_SOURCES"
    ):
        stage4_writeback_state = "RESPONSIBLE_ROLE_PERSON_DIRECTORY_ONLY_MATCH"
    recommended_next_action = (
        "apply_stage4_responsible_role_writeback_in_replay"
        if str(writeback.get("writeback_state") or "") == "RESPONSIBLE_ROLE_WRITEBACK_CANDIDATE_FROM_STAGE4_SOURCE"
        else "keep_company_first_and_review_certificate_visibility"
        if effective_completion_state == "RESPONSIBLE_ROLE_PERSON_DIRECTORY_ONLY_MATCH"
        or (same_company_candidate_found and certificate_not_publicly_confirmed)
        else "retry_source_query_or_keep_query_error_taxonomy"
        if query_error_source_types
        else "keep_internal_review_and_register_source_gap"
    )
    project_code_candidates = _string_list(hard_defect.get("project_code_candidates"))
    project_codes = _string_list(hard_defect.get("project_codes"))
    project_code_resolution_failure_reasons = _string_list(
        hard_defect.get("project_code_resolution_failure_reasons")
    )
    return {
        "project_id": str(candidate.get("project_id") or pressure_row.get("project_id") or ""),
        "project_name": str(candidate.get("project_name") or pressure_row.get("project_name") or ""),
        "source_url": str(candidate.get("source_url") or pressure_row.get("source_url") or ""),
        "candidate_company": str(probe_candidate.get("candidate_company") or ""),
        "candidate_company_members": _candidate_company_members(
            str(candidate.get("candidate_company") or pressure_row.get("candidate_company") or "")
        ),
        "project_manager_name": str(probe_candidate.get("project_manager_name") or ""),
        "primary_responsible_person_name": str(probe_candidate.get("primary_responsible_person_name") or ""),
        "project_manager_certificate_no": str(probe_candidate.get("project_manager_certificate_no") or ""),
        "covered_source_types": _string_list(hard_defect.get("covered_source_types")),
        "queried_source_types": _string_list(hard_defect.get("queried_source_types")),
        "project_code_candidates": project_code_candidates,
        "project_codes": project_codes,
        "project_code_resolution_failure_reasons": project_code_resolution_failure_reasons,
        "empty_result_source_types": empty_result_source_types,
        "query_error_source_types": query_error_source_types,
        "person_directory_same_company_candidate_found": same_company_candidate_found,
        "certificate_verification_state": str(person_directory.get("certificate_verification_state") or ""),
        "certificate_not_publicly_confirmed": certificate_not_publicly_confirmed,
        "responsible_role_identity_completion_state": effective_completion_state,
        "responsible_role_identity_candidates": [
            dict(item)
            for item in list(effective_completion.get("identity_candidates") or [])
            if isinstance(item, Mapping)
        ],
        "stage4_responsible_role_writeback_state": stage4_writeback_state,
        "replay_field_writeback": dict(writeback.get("writeback_fields") or {}),
        "replay_identifier_hints": {
            "project_code_candidates": project_code_candidates,
            "project_codes": project_codes,
            "person_directory_same_company_candidate_found": same_company_candidate_found,
            "certificate_verification_state": str(person_directory.get("certificate_verification_state") or ""),
            "stage4_responsible_role_writeback_state": stage4_writeback_state,
        },
        "hard_defect_readback_state": str(hard_defect.get("readback_state") or ""),
        "person_directory_readback_state": str(person_directory.get("readback_state") or ""),
        "source_type_details": source_type_details,
        "recommended_next_action": recommended_next_action,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _effective_responsible_role_identity_completion(
    *,
    hard_completion: Mapping[str, Any],
    person_directory_completion: Mapping[str, Any],
) -> dict[str, Any]:
    if str(hard_completion.get("completion_state") or "") == "RESPONSIBLE_ROLE_CANDIDATE_FOUND":
        return dict(hard_completion)
    if str(person_directory_completion.get("completion_state") or "") == "RESPONSIBLE_ROLE_PERSON_DIRECTORY_ONLY_MATCH":
        return dict(person_directory_completion)
    return dict(hard_completion)


def _probe_candidate(candidate: Mapping[str, Any], pressure_row: Mapping[str, Any]) -> dict[str, Any]:
    company_text = str(candidate.get("candidate_company") or pressure_row.get("candidate_company") or "").strip()
    company_members = _candidate_company_members(company_text)
    primary_company = company_members[0] if company_members else company_text
    return {
        **dict(candidate),
        "project_id": str(candidate.get("project_id") or pressure_row.get("project_id") or ""),
        "project_name": str(candidate.get("project_name") or pressure_row.get("project_name") or ""),
        "source_url": str(candidate.get("source_url") or pressure_row.get("source_url") or ""),
        "projectCode": str(candidate.get("projectCode") or pressure_row.get("projectCode") or ""),
        "project_code": str(candidate.get("project_code") or pressure_row.get("project_code") or ""),
        "gdcic_project_code": str(candidate.get("gdcic_project_code") or pressure_row.get("gdcic_project_code") or ""),
        "project_public_code": str(candidate.get("project_public_code") or pressure_row.get("project_public_code") or ""),
        "project_code_candidates": candidate.get("project_code_candidates") or pressure_row.get("project_code_candidates") or [],
        "candidate_company": primary_company,
        "winner_name": primary_company,
        "first_rank_company": primary_company,
        "project_manager_name": str(candidate.get("project_manager_name") or ""),
        "primary_responsible_person_name": str(
            candidate.get("primary_responsible_person_name") or candidate.get("project_manager_name") or ""
        ),
        "project_manager_certificate_no": str(candidate.get("project_manager_certificate_no") or ""),
        "certificate_no": str(candidate.get("project_manager_certificate_no") or ""),
    }


def _source_type_details(
    hard_defect: Mapping[str, Any],
    person_directory: Mapping[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for result in list(hard_defect.get("source_results") or []):
        if not isinstance(result, Mapping):
            continue
        source_type = str(result.get("source_type") or "")
        if not source_type:
            continue
        row = grouped.setdefault(
            source_type,
            {
                "source_type": source_type,
                "covered_count": 0,
                "queried_count": 0,
                "empty_result_count": 0,
                "query_error_count": 0,
            },
        )
        if str(result.get("coverage_state") or "") == "COVERED":
            row["covered_count"] += 1
        if str(result.get("readback_state") or "") == "READBACK_READY":
            row["queried_count"] += 1
        if any(str(reason).endswith("_empty_result") for reason in list(result.get("failure_reasons") or [])):
            row["empty_result_count"] += 1
        if str(result.get("readback_state") or "") == "FAIL_CLOSED_QUERY_ERROR":
            row["query_error_count"] += 1

    source_type = "local_person_directory"
    person_row = grouped.setdefault(
        source_type,
        {
            "source_type": source_type,
            "covered_count": 0,
            "queried_count": 0,
            "empty_result_count": 0,
            "query_error_count": 0,
        },
    )
    if str(person_directory.get("readback_state") or "") == "READBACK_READY":
        person_row["queried_count"] += 1
    if str(person_directory.get("identity_resolution_state") or "") == "LOCAL_DIRECTORY_SAME_COMPANY_PERSON_CANDIDATE_FOUND":
        person_row["covered_count"] += 1
    if str(person_directory.get("identity_resolution_state") or "") == "LOCAL_DIRECTORY_SAME_COMPANY_PERSON_NOT_FOUND":
        person_row["empty_result_count"] += 1
    if str(person_directory.get("readback_state") or "") == "FAIL_CLOSED_QUERY_ERROR":
        person_row["query_error_count"] += 1

    return sorted(grouped.values(), key=lambda item: item["source_type"])


def _source_type_summary_records(candidate_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in candidate_records:
        for detail in list(record.get("source_type_details") or []):
            if not isinstance(detail, Mapping):
                continue
            source_type = str(detail.get("source_type") or "")
            if not source_type:
                continue
            row = grouped.setdefault(
                source_type,
                {
                    "source_type": source_type,
                    "covered_candidate_count": 0,
                    "queried_candidate_count": 0,
                    "empty_result_candidate_count": 0,
                    "query_error_candidate_count": 0,
                    "project_ids": [],
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
            )
            project_id = str(record.get("project_id") or "")
            if _as_int(detail.get("covered_count")) > 0:
                row["covered_candidate_count"] += 1
            if _as_int(detail.get("queried_count")) > 0:
                row["queried_candidate_count"] += 1
            if _as_int(detail.get("empty_result_count")) > 0:
                row["empty_result_candidate_count"] += 1
            if _as_int(detail.get("query_error_count")) > 0:
                row["query_error_candidate_count"] += 1
            row["project_ids"] = _dedupe_strings([*list(row.get("project_ids") or []), project_id])
    return sorted(grouped.values(), key=lambda item: item["source_type"])


def _summary(
    candidate_records: list[Mapping[str, Any]],
    source_type_summary_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "candidate_count": len(candidate_records),
        "source_type_count": len(source_type_summary_records),
        "same_company_person_directory_found_count": sum(
            1 for record in candidate_records if record.get("person_directory_same_company_candidate_found")
        ),
        "responsible_role_identity_completion_state_counts": _counts(
            record.get("responsible_role_identity_completion_state") for record in candidate_records
        ),
        "stage4_responsible_role_writeback_state_counts": _counts(
            record.get("stage4_responsible_role_writeback_state") for record in candidate_records
        ),
        "certificate_verification_state_counts": _counts(
            record.get("certificate_verification_state") for record in candidate_records
        ),
        "project_code_resolution_failure_counts": _counts(
            reason
            for record in candidate_records
            for reason in _string_list(record.get("project_code_resolution_failure_reasons"))
        ),
        "query_error_source_type_count": sum(
            1 for record in source_type_summary_records if _as_int(record.get("query_error_candidate_count")) > 0
        ),
        "empty_result_source_type_count": sum(
            1 for record in source_type_summary_records if _as_int(record.get("empty_result_candidate_count")) > 0
        ),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _candidate_company_members(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[;；]", text)
    members: list[str] = []
    for part in parts:
        cleaned = re.sub(r"^\((?:主|成)\)", "", part.strip())
        cleaned = re.sub(r"^（(?:主|成)）", "", cleaned.strip())
        if cleaned and cleaned not in members:
            members.append(cleaned)
    return members


def _repository(output_root: Path) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(output_root / "source-gap-storage.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(output_root / "objects"),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _apply_forbidden_term_scan(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    target = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else payload
    if forbidden_hits:
        target["forbidden_term_scan_state"] = "FAIL"
        target["forbidden_term_hits"] = forbidden_hits
        payload["safe_to_execute"] = False
        payload["blocking_reasons"] = [
            *list(payload.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
    else:
        target["forbidden_term_scan_state"] = "PASS"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou Stage4 source gap probe.")
    parser.add_argument("--run-result-json", default=str(DEFAULT_RUN_RESULT_JSON))
    parser.add_argument("--candidate-pressure-json", default=str(DEFAULT_CANDIDATE_PRESSURE_JSON))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_stage4_source_gap_probe(
        run_result_json=args.run_result_json,
        candidate_pressure_json=args.candidate_pressure_json,
        output_root=args.output_root,
    )
    print(json.dumps(result if args.emit_json else result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
