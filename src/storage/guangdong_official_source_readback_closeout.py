from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGDONG_OFFICIAL_SOURCE_READBACK_CLOSEOUT_KIND = "guangdong_official_source_readback_closeout_v1_manifest"
GUANGDONG_OFFICIAL_SOURCE_READBACK_CLOSEOUT_VERSION = 1
GUANGDONG_OFFICIAL_SOURCE_READBACK_CLOSEOUT_ADAPTER_ID = "guangdong-official-source-readback-closeout-v1"

DEFAULT_GDCIC_QUERY_PROBE_ROOT = Path("tmp/evaluation-real-samples/guangdong-gdcic-query-probe-v1-live-max12")
DEFAULT_EVIDENCE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-closeout-v1")
DEFAULT_GUANGDONG_LOCAL_FIELD_QUERY_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-field-query-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-official-source-readback-closeout-v1")

GDCIC_SOURCE_PROFILE_ID = "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"
FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "是不是本人", "造假成立")

PERSON_REGISTRATION_READBACK = "PERSON_REGISTRATION_READBACK"
COMPANY_PROJECT_READBACK = "COMPANY_PROJECT_READBACK"
CERTIFICATE_FIELD_READBACK = "CERTIFICATE_FIELD_READBACK"
EMPTY_PUBLIC_RESULT_REVIEW = "EMPTY_PUBLIC_RESULT_REVIEW"
BLOCKED_OR_CAPTCHA_REVIEW = "BLOCKED_OR_CAPTCHA_REVIEW"


def build_guangdong_official_source_readback_closeout(
    *,
    gdcic_query_probe_root: str | Path = DEFAULT_GDCIC_QUERY_PROBE_ROOT,
    gdcic_query_probe_json: str | Path | None = None,
    evidence_report_root: str | Path = DEFAULT_EVIDENCE_REPORT_ROOT,
    evidence_report_json: str | Path | None = None,
    guangdong_local_field_query_root: str | Path | None = DEFAULT_GUANGDONG_LOCAL_FIELD_QUERY_ROOT,
    guangdong_local_field_query_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    gdcic_dir = Path(gdcic_query_probe_root)
    evidence_dir = Path(evidence_report_root)
    local_field_dir = Path(guangdong_local_field_query_root) if guangdong_local_field_query_root else None
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    gdcic_path = Path(gdcic_query_probe_json) if gdcic_query_probe_json else gdcic_dir / "guangdong-gdcic-query-probe-v1.json"
    evidence_path = Path(evidence_report_json) if evidence_report_json else evidence_dir / "guangzhou-evidence-report-v1.json"
    local_field_path = (
        Path(guangdong_local_field_query_json)
        if guangdong_local_field_query_json
        else local_field_dir / "guangdong-local-field-query-probe-v1.json"
        if local_field_dir
        else None
    )

    gdcic_manifest = _source_manifest(_load_json(gdcic_path, blocking_reasons, "gdcic_query_probe_missing"))
    evidence_manifest = _source_manifest(_load_json(evidence_path, blocking_reasons, "evidence_report_missing"))
    local_field_manifest = _source_manifest(_load_json_optional(local_field_path))

    source_summaries = _source_summaries(gdcic_manifest, local_field_manifest)
    project_records = _project_records(
        evidence_manifest=evidence_manifest,
        gdcic_manifest=gdcic_manifest,
        local_field_manifest=local_field_manifest,
    )
    summary = _summary(
        source_summaries=source_summaries,
        project_records=project_records,
        blocking_reasons=blocking_reasons,
    )
    manual_check_table = _manual_check_table(project_records)
    project_gdcic_classification_records = [
        record
        for project in project_records
        for record in _list(project.get("gdcic_readback_classification_records"))
    ]
    manifest = {
        "manifest_version": GUANGDONG_OFFICIAL_SOURCE_READBACK_CLOSEOUT_VERSION,
        "manifest_kind": GUANGDONG_OFFICIAL_SOURCE_READBACK_CLOSEOUT_KIND,
        "adapter_id": GUANGDONG_OFFICIAL_SOURCE_READBACK_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "GuangdongOfficialSourceReadbackCloseoutV1",
        "manifest_id": f"GUANGDONG-OFFICIAL-SOURCE-READBACK-CLOSEOUT-{_fingerprint({'summary': summary, 'projects': project_records})[:16]}",
        "created_at": created,
        "source_gdcic_query_probe_root": str(gdcic_dir),
        "source_gdcic_query_probe_json": str(gdcic_path),
        "source_evidence_report_root": str(evidence_dir),
        "source_evidence_report_json": str(evidence_path),
        "source_guangdong_local_field_query_root_optional": str(local_field_dir or ""),
        "source_guangdong_local_field_query_json_optional": str(local_field_path or ""),
        "primary_source_profile_id": GDCIC_SOURCE_PROFILE_ID,
        "source_summaries": source_summaries,
        "project_records": project_records,
        "project_gdcic_classification_records": project_gdcic_classification_records,
        "manual_check_table": manual_check_table,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "manifest_stores_raw_html_or_blob": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangdong_official_source_readback_closeout_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*blocking_reasons, *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangdong-official-source-readback-closeout-v1.json").write_text(text, encoding="utf-8")
    return result


def _source_summaries(gdcic_manifest: Mapping[str, Any], local_field_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    gdcic_summary = dict(gdcic_manifest.get("summary") or {})
    if gdcic_manifest:
        gdcic_classification_records = [
            _gdcic_task_classification_record(task)
            for task in _list(gdcic_manifest.get("query_task_records"))
            if isinstance(task, Mapping)
        ]
        summaries.append(
            {
                "source_profile_id": GDCIC_SOURCE_PROFILE_ID,
                "source_name": "广东三库一平台公开源",
                "source_kind": "OFFICIAL_PUBLIC_SOURCE",
                "readback_ready_count": _int(gdcic_summary.get("gdcic_readback_ready_count")),
                "task_count": _int(gdcic_summary.get("gdcic_query_probe_task_count")),
                "probe_state_counts": dict(gdcic_summary.get("query_probe_state_counts") or {}),
                "blocker_taxonomy_counts": dict(gdcic_summary.get("gdcic_blocker_taxonomy_counts") or {}),
                "gdcic_readback_classification_counts": _classification_counts(gdcic_classification_records),
                "source_closeout_state": _source_closeout_state(_int(gdcic_summary.get("gdcic_readback_ready_count"))),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    local_summary = dict(local_field_manifest.get("summary") or {})
    if local_field_manifest:
        for profile_id, task_count in dict(local_summary.get("source_profile_task_counts") or {}).items():
            if str(profile_id) == GDCIC_SOURCE_PROFILE_ID and gdcic_manifest:
                continue
            summaries.append(
                {
                    "source_profile_id": str(profile_id),
                    "source_name": str(profile_id),
                    "source_kind": "OFFICIAL_PUBLIC_SOURCE",
                    "readback_ready_count": _local_readback_count_for_profile(local_field_manifest, str(profile_id)),
                    "task_count": _int(task_count),
                    "probe_state_counts": dict(local_summary.get("field_query_probe_state_counts") or {}),
                    "blocker_taxonomy_counts": dict(local_summary.get("blocker_taxonomy_counts") or {}),
                    "source_closeout_state": _source_closeout_state(_local_readback_count_for_profile(local_field_manifest, str(profile_id))),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return summaries


def _project_records(
    *,
    evidence_manifest: Mapping[str, Any],
    gdcic_manifest: Mapping[str, Any],
    local_field_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    project_ids = _project_ids(evidence_manifest, gdcic_manifest, local_field_manifest)
    records: list[dict[str, Any]] = []
    for project_id in project_ids:
        evidence_project = _first(_project_reports(evidence_manifest, project_id))
        gdcic_project = _first(_project_task_records(gdcic_manifest, project_id))
        gdcic_task_records = _gdcic_query_tasks_for_project(gdcic_manifest, project_id)
        gdcic_classification_records = [
            _gdcic_task_classification_record(task)
            for task in gdcic_task_records
        ]
        local_project = _first(_project_task_records(local_field_manifest, project_id))
        ready_count = _int(gdcic_project.get("readback_ready_count")) + _int(local_project.get("readback_ready_count"))
        blocker_counts = _merge_counts(
            dict(gdcic_project.get("blocker_taxonomy_counts") or {}),
            dict(local_project.get("blocker_taxonomy_counts") or {}),
        )
        records.append(
            {
                "project_id": project_id,
                "project_name": _first_text(
                    [
                        evidence_project.get("project_name"),
                        gdcic_project.get("project_name"),
                        local_project.get("project_name"),
                    ]
                ),
                "official_source_readback_state": _source_closeout_state(ready_count),
                "official_source_readback_ready_count": ready_count,
                "official_source_task_count": _int(gdcic_project.get("query_task_count")) + _int(local_project.get("field_query_task_count")),
                "source_profile_ids": _dedupe(
                    [
                        GDCIC_SOURCE_PROFILE_ID if gdcic_project else "",
                        *list(local_project.get("source_profile_ids") or []),
                    ]
                ),
                "gdcic_query_task_ids": list(gdcic_project.get("query_task_ids") or []),
                "gdcic_readback_classification_counts": _classification_counts(gdcic_classification_records),
                "gdcic_readback_classification_records": gdcic_classification_records,
                "local_field_query_task_ids": list(local_project.get("field_query_task_ids") or []),
                "blocker_taxonomy_counts": blocker_counts,
                "review_state": (
                    "OFFICIAL_SOURCE_READBACK_READY"
                    if ready_count > 0
                    else "OFFICIAL_SOURCE_REVIEW_REQUIRED"
                    if blocker_counts
                    else "OFFICIAL_SOURCE_TASK_ONLY_OR_NOT_APPLICABLE"
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _summary(
    *,
    source_summaries: list[Mapping[str, Any]],
    project_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    official_ready_count = sum(_int(row.get("readback_ready_count")) for row in source_summaries)
    project_ready_count = sum(1 for row in project_records if _int(row.get("official_source_readback_ready_count")) > 0)
    blocker_counts = _merge_counts(*(dict(row.get("blocker_taxonomy_counts") or {}) for row in source_summaries))
    classification_counts = _merge_counts(
        *(dict(row.get("gdcic_readback_classification_counts") or {}) for row in project_records)
    )
    closeout_state = (
        "INPUT_BLOCKED"
        if blocking_reasons
        else "P2_OFFICIAL_READBACK_READY"
        if official_ready_count > 0
        else "P2_OFFICIAL_READBACK_REVIEW_REQUIRED"
    )
    return {
        "p2_closeout_state": closeout_state,
        "closeout_state": closeout_state,
        "p2_ready": not blocking_reasons and official_ready_count > 0,
        "official_source_count": len(source_summaries),
        "official_source_readback_ready_count": official_ready_count,
        "official_source_project_ready_count": project_ready_count,
        "project_count": len(project_records),
        "source_profile_readback_ready_counts": {
            str(row.get("source_profile_id")): _int(row.get("readback_ready_count"))
            for row in source_summaries
        },
        "source_profile_task_counts": {
            str(row.get("source_profile_id")): _int(row.get("task_count"))
            for row in source_summaries
        },
        "source_profile_state_counts": _counts(row.get("source_closeout_state") for row in source_summaries),
        "gdcic_readback_classification_counts": classification_counts,
        "project_gdcic_classification_record_count": sum(
            len(_list(row.get("gdcic_readback_classification_records"))) for row in project_records
        ),
        "blocker_taxonomy_counts": blocker_counts,
        "query_miss_is_not_clearance": True,
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _manual_check_table(project_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "project_id": str(row.get("project_id") or ""),
            "project_name": str(row.get("project_name") or ""),
            "official_source_readback_state": str(row.get("official_source_readback_state") or ""),
            "official_source_readback_ready_count": _int(row.get("official_source_readback_ready_count")),
            "gdcic_readback_classification_counts": dict(row.get("gdcic_readback_classification_counts") or {}),
            "blocker_taxonomy_counts": dict(row.get("blocker_taxonomy_counts") or {}),
            "source_profile_ids": list(row.get("source_profile_ids") or []),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for row in project_records
    ]


def _source_closeout_state(readback_ready_count: int) -> str:
    return "OFFICIAL_SOURCE_READBACK_READY" if readback_ready_count > 0 else "OFFICIAL_SOURCE_REVIEW_REQUIRED"


def _gdcic_task_classification_record(task: Mapping[str, Any]) -> dict[str, Any]:
    field_summary = dict(task.get("field_summary") or {})
    blockers = _dedupe(
        [
            *_list(task.get("blocker_taxonomy")),
            *[
                blocker
                for route in _list(task.get("route_attempts"))
                if isinstance(route, Mapping)
                for blocker in _list(route.get("blocker_taxonomy"))
            ],
        ]
    )
    classifications: list[str] = []
    if _has_person_registration_readback(task):
        classifications.append(PERSON_REGISTRATION_READBACK)
    if _has_company_project_readback(task):
        classifications.append(COMPANY_PROJECT_READBACK)
    if _has_certificate_field_readback(task):
        classifications.append(CERTIFICATE_FIELD_READBACK)
    if _has_empty_public_result(task, blockers):
        classifications.append(EMPTY_PUBLIC_RESULT_REVIEW)
    if _has_blocked_or_captcha(task, blockers):
        classifications.append(BLOCKED_OR_CAPTCHA_REVIEW)
    if not classifications and not bool(task.get("readback_ready")):
        classifications.append(EMPTY_PUBLIC_RESULT_REVIEW)
    return {
        "query_task_id": str(task.get("query_task_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "project_name": str(task.get("project_name") or ""),
        "candidate_group_id": str(task.get("candidate_group_id") or ""),
        "responsible_person_name": str(task.get("responsible_person_name") or ""),
        "certificate_no": str(task.get("certificate_no") or ""),
        "readback_ready": bool(task.get("readback_ready")),
        "query_probe_state": str(task.get("query_probe_state") or ""),
        "classification_tags": classifications,
        "field_summary_probe": {
            "record_count": _int(field_summary.get("record_count")),
            "sample_project_names": _list(field_summary.get("sample_project_names"))[:3],
            "sample_company_names": _list(field_summary.get("sample_company_names"))[:3],
            "sample_person_names": _list(field_summary.get("sample_person_names"))[:3],
            "sample_certificate_nos": _list(field_summary.get("sample_certificate_nos"))[:3],
        },
        "route_classification_counts": _route_classification_counts(task),
        "blocker_taxonomy": blockers,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _classification_counts(records: list[Mapping[str, Any]]) -> dict[str, int]:
    return _counts(
        tag
        for record in records
        for tag in _list(record.get("classification_tags"))
    )


def _route_classification_counts(task: Mapping[str, Any]) -> dict[str, int]:
    tags: list[str] = []
    for route in _list(task.get("route_attempts")):
        if not isinstance(route, Mapping):
            continue
        route_summary = dict(route.get("field_summary") or {})
        route_id = str(route.get("route_id") or "")
        route_state = str(route.get("route_state") or "")
        route_blockers = _list(route.get("blocker_taxonomy"))
        if route_state == "READBACK_READY_PUBLIC_SOURCE" and (
            route_summary.get("sample_person_names")
            or route_summary.get("sample_id_card_hashes")
            or route_id.startswith("person_")
        ):
            tags.append(PERSON_REGISTRATION_READBACK)
        if route_state == "READBACK_READY_PUBLIC_SOURCE" and (
            route_summary.get("sample_project_names")
            or route_id.startswith("project_")
        ):
            tags.append(COMPANY_PROJECT_READBACK)
        if route_state == "READBACK_READY_PUBLIC_SOURCE" and route_summary.get("sample_certificate_nos"):
            tags.append(CERTIFICATE_FIELD_READBACK)
        if "gdcic_public_query_empty_review" in route_blockers or route_state == "REVIEW_REQUIRED":
            tags.append(EMPTY_PUBLIC_RESULT_REVIEW)
        if route_state.startswith("FAIL_CLOSED") or _has_blocker_marker(route_blockers):
            tags.append(BLOCKED_OR_CAPTCHA_REVIEW)
    return _counts(tags)


def _has_person_registration_readback(task: Mapping[str, Any]) -> bool:
    summary = dict(task.get("field_summary") or {})
    if bool(summary.get("sample_person_names")) or bool(summary.get("sample_id_card_hashes")):
        return bool(task.get("readback_ready"))
    for route in _list(task.get("route_attempts")):
        if not isinstance(route, Mapping):
            continue
        route_summary = dict(route.get("field_summary") or {})
        if str(route.get("route_state") or "") == "READBACK_READY_PUBLIC_SOURCE" and (
            route_summary.get("sample_person_names")
            or route_summary.get("sample_id_card_hashes")
            or str(route.get("route_id") or "").startswith("person_")
        ):
            return True
    return False


def _has_company_project_readback(task: Mapping[str, Any]) -> bool:
    summary = dict(task.get("field_summary") or {})
    if bool(summary.get("sample_project_names")):
        return bool(task.get("readback_ready"))
    for route in _list(task.get("route_attempts")):
        if not isinstance(route, Mapping):
            continue
        route_summary = dict(route.get("field_summary") or {})
        if str(route.get("route_state") or "") == "READBACK_READY_PUBLIC_SOURCE" and (
            route_summary.get("sample_project_names")
            or str(route.get("route_id") or "").startswith("project_")
        ):
            return True
    return False


def _has_certificate_field_readback(task: Mapping[str, Any]) -> bool:
    summary = dict(task.get("field_summary") or {})
    if bool(summary.get("sample_certificate_nos")):
        return bool(task.get("readback_ready"))
    for route in _list(task.get("route_attempts")):
        if not isinstance(route, Mapping):
            continue
        route_summary = dict(route.get("field_summary") or {})
        if str(route.get("route_state") or "") == "READBACK_READY_PUBLIC_SOURCE" and route_summary.get("sample_certificate_nos"):
            return True
    return False


def _has_empty_public_result(task: Mapping[str, Any], blockers: list[str]) -> bool:
    if "gdcic_public_query_empty_review" in blockers:
        return True
    return any(
        isinstance(route, Mapping) and str(route.get("route_state") or "") == "REVIEW_REQUIRED"
        for route in _list(task.get("route_attempts"))
    )


def _has_blocked_or_captcha(task: Mapping[str, Any], blockers: list[str]) -> bool:
    return _has_blocker_marker(blockers) or any(
        isinstance(route, Mapping) and str(route.get("route_state") or "").startswith("FAIL_CLOSED")
        for route in _list(task.get("route_attempts"))
    )


def _has_blocker_marker(blockers: Iterable[Any]) -> bool:
    marker_text = " ".join(str(item or "").lower() for item in blockers)
    return any(token in marker_text for token in ("captcha", "sso", "403", "503", "forbidden", "blocked", "server_error"))


def _local_readback_count_for_profile(manifest: Mapping[str, Any], profile_id: str) -> int:
    return sum(
        1
        for task in _list(manifest.get("field_task_records"))
        if isinstance(task, Mapping)
        and str(task.get("source_profile_id") or "") == profile_id
        and bool(task.get("readback_ready"))
    )


def _project_ids(*manifests: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for manifest in manifests:
        for key in ("project_reports", "project_task_records"):
            for row in _list(manifest.get(key)):
                if isinstance(row, Mapping):
                    ids.append(str(row.get("project_id") or ""))
    return _dedupe(ids)


def _project_reports(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in _list(manifest.get("project_reports"))
        if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id
    ]


def _project_task_records(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in _list(manifest.get("project_task_records"))
        if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id
    ]


def _gdcic_query_tasks_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in _list(manifest.get("query_task_records"))
        if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id
    ]


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _load_json_optional(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists() or path.is_dir():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _first(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(rows[0]) if rows else {}


def _first_text(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items()))


def _merge_counts(*items: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        for key, value in dict(item or {}).items():
            out[str(key)] = out.get(str(key), 0) + _int(value)
    return dict(sorted(out.items()))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangdong official source readback closeout v1.")
    parser.add_argument("--gdcic-query-probe-root", default=str(DEFAULT_GDCIC_QUERY_PROBE_ROOT))
    parser.add_argument("--gdcic-query-probe-json")
    parser.add_argument("--evidence-report-root", default=str(DEFAULT_EVIDENCE_REPORT_ROOT))
    parser.add_argument("--evidence-report-json")
    parser.add_argument("--guangdong-local-field-query-root", default=str(DEFAULT_GUANGDONG_LOCAL_FIELD_QUERY_ROOT))
    parser.add_argument("--guangdong-local-field-query-json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangdong_official_source_readback_closeout(
        gdcic_query_probe_root=args.gdcic_query_probe_root,
        gdcic_query_probe_json=args.gdcic_query_probe_json,
        evidence_report_root=args.evidence_report_root,
        evidence_report_json=args.evidence_report_json,
        guangdong_local_field_query_root=args.guangdong_local_field_query_root,
        guangdong_local_field_query_json=args.guangdong_local_field_query_json,
        output_root=args.output_root,
    )
    if args.emit_json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            "guangdong official source readback closeout built: "
            f"state={result['summary']['closeout_state']} "
            f"ready_count={result['summary']['official_source_readback_ready_count']}"
        )
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
