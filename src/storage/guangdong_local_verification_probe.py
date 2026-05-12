from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGDONG_LOCAL_VERIFICATION_PROBE_KIND = "guangdong_local_verification_probe_v1_manifest"
GUANGDONG_LOCAL_VERIFICATION_PROBE_VERSION = 1
GUANGDONG_LOCAL_VERIFICATION_PROBE_ADAPTER_ID = "guangdong-local-verification-probe-v1-builder"

DEFAULT_ACTIVE_CONFLICT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-active-conflict-probe-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-local-verification-probe-v1")

GUANGDONG_LOCAL_SOURCE_PROFILE_IDS = {
    "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
    "GUANGDONG-GDCIC-HOME",
    "GUANGDONG-TZXM-HOME",
    "GUANGDONG-ZFCXJST-PENALTY-PUBLICITY",
    "GUANGDONG-CREDIT-GD-HOME",
    "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
}

IMPLEMENTED_SEPARATE_FIELD_ADAPTERS = {
    "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM": "guangdong_gdcic_query_probe_v1",
}

FORBIDDEN_TERMS = ("在建冲突成立", "无在建", "无冲突", "造假成立", "违法成立", "确认本人", "是不是本人")

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_guangdong_local_verification_probe(
    *,
    active_conflict_root: str | Path = DEFAULT_ACTIVE_CONFLICT_ROOT,
    active_conflict_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    source_profile_ids: list[str] | tuple[str, ...] | None = None,
    enable_live_reachability: bool = False,
    max_live_tasks: int | None = None,
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    active_dir = Path(active_conflict_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    active_path = (
        Path(active_conflict_json)
        if active_conflict_json
        else active_dir / "guangzhou-active-conflict-probe-v1.json"
    )
    blocking_reasons: list[str] = []
    active_manifest = _source_manifest(
        _load_json(active_path, blocking_reasons, "active_conflict_probe_missing")
    )
    selected_profiles = _normalize_filter(source_profile_ids)
    execution_mode = "LIVE_REACHABILITY_ATTEMPTED" if enable_live_reachability else "PLAN_ONLY_NOT_EXECUTED"
    query_task_records = _query_task_records_from_active_conflict(
        active_manifest,
        created_at=created,
        source_profile_ids=selected_profiles,
        enable_live_reachability=enable_live_reachability,
        max_live_tasks=max_live_tasks,
        http_getter=http_getter,
    )
    project_task_records = _project_task_records(query_task_records)
    manual_check_table = _manual_check_table(query_task_records)
    summary = _summary(
        query_task_records=query_task_records,
        project_task_records=project_task_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GUANGDONG_LOCAL_VERIFICATION_PROBE_VERSION,
        "manifest_kind": GUANGDONG_LOCAL_VERIFICATION_PROBE_KIND,
        "adapter_id": GUANGDONG_LOCAL_VERIFICATION_PROBE_ADAPTER_ID,
        "pipeline_stage": "GuangdongLocalVerificationProbeV1",
        "manifest_id": f"GUANGDONG-LOCAL-VERIFICATION-PROBE-{_fingerprint({'tasks': query_task_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_active_conflict_root": str(active_dir),
        "source_active_conflict_json": str(active_path),
        "execution_mode": execution_mode,
        "live_reachability_enabled": bool(enable_live_reachability),
        "max_live_tasks": max_live_tasks,
        "source_profile_ids": sorted(selected_profiles) if selected_profiles else "ALL_GUANGDONG_LOCAL_SOURCES",
        "project_task_records": project_task_records,
        "query_task_records": query_task_records,
        "manual_check_table": manual_check_table,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "network_enabled": bool(enable_live_reachability),
            "manifest_stores_raw_html_or_blob": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "no_no_risk_inference": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "guangdong_local_verification_probe_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *blocking_reasons,
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangdong-local-verification-probe-v1.json").write_text(text, encoding="utf-8")
    return result


def _query_task_records_from_active_conflict(
    active_manifest: Mapping[str, Any],
    *,
    created_at: str,
    source_profile_ids: set[str],
    enable_live_reachability: bool,
    max_live_tasks: int | None,
    http_getter: HttpGetter | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    live_attempted = 0
    reachability_cache: dict[str, dict[str, Any]] = {}
    for task in _list(active_manifest.get("task_records")):
        if not isinstance(task, Mapping):
            continue
        for source_entry in _guangdong_local_source_entries(task):
            profile_id = str(source_entry.get("source_profile_id") or "").upper()
            if source_profile_ids and profile_id not in source_profile_ids:
                continue
            if enable_live_reachability:
                cache_key = _source_cache_key(source_entry)
                if cache_key in reachability_cache:
                    readback = _copy_jsonable(reachability_cache[cache_key])
                    readback["reachability_cache_hit"] = True
                elif max_live_tasks is not None and live_attempted >= max_live_tasks:
                    readback = _live_deferred_readback(max_live_tasks)
                    reachability_cache[cache_key] = _copy_jsonable(readback)
                else:
                    live_attempted += 1
                    readback = _execute_live_reachability(source_entry, http_getter=http_getter)
                    reachability_cache[cache_key] = _copy_jsonable(readback)
            else:
                readback = _plan_only_readback(source_entry)
            records.append(
                {
                    "query_task_id": _stable_id(
                        "GD-LOCAL-VERIFY",
                        task.get("task_id"),
                        task.get("project_id"),
                        task.get("candidate_group_id"),
                        task.get("responsible_person_name"),
                        source_entry.get("source_profile_id"),
                    ),
                    "active_conflict_task_id": str(task.get("task_id") or ""),
                    "project_id": str(task.get("project_id") or ""),
                    "project_name": str(task.get("project_name") or ""),
                    "candidate_group_id": str(task.get("candidate_group_id") or ""),
                    "candidate_group_order": str(task.get("candidate_group_order") or ""),
                    "responsible_person_name": str(task.get("responsible_person_name") or ""),
                    "candidate_group_members": _list(task.get("candidate_group_members")),
                    "matched_company_names": _list(task.get("matched_company_names")),
                    "company_query_variants": _list(task.get("company_query_variants")),
                    "certificate_no": str(task.get("certificate_no") or ""),
                    "query_keywords": _list(task.get("query_keywords")),
                    "region_code": "CN-GD",
                    "region_name": "广东",
                    "source_profile_id": str(source_entry.get("source_profile_id") or ""),
                    "source_entry": source_entry,
                    "source_url": str(source_entry.get("source_url") or ""),
                    "official_reference_url": str(source_entry.get("official_reference_url") or source_entry.get("official_parent_url") or ""),
                    "source_family": str(source_entry.get("source_family") or ""),
                    "target_source_types": _list(source_entry.get("target_source_types")),
                    "query_params": _query_params(task, source_entry),
                    "field_adapter_status": _field_adapter_status(source_entry),
                    "execution_mode": (
                        "LIVE_REACHABILITY_ATTEMPTED"
                        if enable_live_reachability
                        else "PLAN_ONLY_NOT_EXECUTED"
                    ),
                    **readback,
                    "created_at": created_at,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return records


def _guangdong_local_source_entries(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for entry in _list(task.get("source_entries")):
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("source_profile_id") or "") in GUANGDONG_LOCAL_SOURCE_PROFILE_IDS:
            entries.append(dict(entry))
    return entries


def _query_params(task: Mapping[str, Any], source_entry: Mapping[str, Any]) -> dict[str, Any]:
    project_name = str(task.get("project_name") or "").strip()
    person = str(task.get("responsible_person_name") or "").strip()
    certificate_no = str(task.get("certificate_no") or "").strip()
    companies = _dedupe(
        [
            *_list(task.get("company_query_variants")),
            *_list(task.get("candidate_group_members")),
            *_list(task.get("matched_company_names")),
        ]
    )
    return {
        "projectId": str(task.get("project_id") or ""),
        "projectName": project_name,
        "companyName": _first_text(companies),
        "companyVariants": companies,
        "personName": person,
        "certificateNo": certificate_no,
        "sourceProfileId": str(source_entry.get("source_profile_id") or ""),
        "targetSourceTypes": _list(source_entry.get("target_source_types")),
        "keywords": _dedupe([project_name, *companies, person, certificate_no]),
    }


def _field_adapter_status(source_entry: Mapping[str, Any]) -> str:
    profile_id = str(source_entry.get("source_profile_id") or "")
    if profile_id in IMPLEMENTED_SEPARATE_FIELD_ADAPTERS:
        return f"IMPLEMENTED_SEPARATE:{IMPLEMENTED_SEPARATE_FIELD_ADAPTERS[profile_id]}"
    return "FIELD_ADAPTER_PENDING"


def _plan_only_readback(source_entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "query_probe_state": "PLAN_ONLY_NOT_EXECUTED",
        "reachability_diagnostic_state": "REACHABILITY_DIAGNOSTIC_NOT_RUN",
        "readback_ready": False,
        "readback_status_code": None,
        "field_summary": {},
        "route_attempts": [],
        "blocker_taxonomy": [],
        "next_adapter": str(source_entry.get("next_adapter") or ""),
    }


def _live_deferred_readback(max_live_tasks: int) -> dict[str, Any]:
    return {
        "query_probe_state": "LIVE_REACHABILITY_DEFERRED_BY_LIMIT",
        "reachability_diagnostic_state": "REACHABILITY_DIAGNOSTIC_DEFERRED",
        "readback_ready": False,
        "readback_status_code": None,
        "field_summary": {},
        "route_attempts": [],
        "blocker_taxonomy": ["guangdong_local_live_reachability_deferred_by_limit"],
        "diagnostic_message": f"max_live_tasks={max_live_tasks}",
    }


def _execute_live_reachability(
    source_entry: Mapping[str, Any],
    *,
    http_getter: HttpGetter | None,
) -> dict[str, Any]:
    source_url = str(source_entry.get("source_url") or "")
    parent_url = str(source_entry.get("official_parent_url") or "")
    reference_url = str(source_entry.get("official_reference_url") or "")
    attempts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for route_id, url in (
        ("source_url", source_url),
        ("official_parent_url", parent_url),
        ("official_reference_url", reference_url),
    ):
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        response = _safe_http_get(url, getter=http_getter)
        attempt = {
            "route_id": route_id,
            "url": url,
            "http_status": response.get("http_status"),
            "content_type": response.get("content_type"),
            "route_state": _route_state(response),
            "blocker_taxonomy": _route_blockers(response),
        }
        attempts.append(attempt)
        if attempt["route_state"] == "REACHABILITY_READY_PUBLIC_SOURCE":
            return {
                "query_probe_state": "REACHABILITY_READY_PUBLIC_SOURCE",
                "reachability_diagnostic_state": "PUBLIC_SOURCE_REACHABLE",
                "readback_ready": True,
                "readback_status_code": _int(response.get("http_status")),
                "field_summary": {
                    "source_page_reachable": True,
                    "content_type": str(response.get("content_type") or ""),
                    "text_probe_sha256": _sha256_text(str(response.get("text_probe") or "")),
                    "text_probe_length": len(str(response.get("text_probe") or "")),
                },
                "route_attempts": attempts,
                "blocker_taxonomy": [],
            }
    blockers = _dedupe(
        blocker for attempt in attempts for blocker in _list(attempt.get("blocker_taxonomy"))
    )
    return {
        "query_probe_state": "REVIEW_REQUIRED" if attempts else "FAIL_CLOSED_NO_ROUTE",
        "reachability_diagnostic_state": "PUBLIC_SOURCE_REVIEW_REQUIRED",
        "readback_ready": False,
        "readback_status_code": _first_int(attempt.get("http_status") for attempt in attempts),
        "field_summary": {},
        "route_attempts": attempts,
        "blocker_taxonomy": blockers or ["guangdong_local_source_reachability_not_verified"],
    }


def _safe_http_get(url: str, *, getter: HttpGetter | None) -> Mapping[str, Any]:
    if getter is not None:
        return getter(url, {})
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_http_timeout_seconds()) as response:  # noqa: S310
            body = response.read(4096)
            content_type = response.headers.get("Content-Type", "")
            return {
                "http_status": response.getcode(),
                "content_type": content_type,
                "text_probe": _decode_probe(body, content_type),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(2048) if hasattr(exc, "read") else b""
        return {
            "http_status": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "text_probe": _decode_probe(body, exc.headers.get("Content-Type", "") if exc.headers else ""),
        }
    except Exception as exc:  # pragma: no cover - platform/network errors vary.
        return {
            "http_status": None,
            "content_type": "",
            "text_probe": "",
            "transport_error": type(exc).__name__,
        }


def _route_state(response: Mapping[str, Any]) -> str:
    blockers = _route_blockers(response)
    if blockers:
        return "PUBLIC_SOURCE_BLOCKED"
    status = _int(response.get("http_status"))
    if 200 <= status < 400:
        return "REACHABILITY_READY_PUBLIC_SOURCE"
    return "PUBLIC_SOURCE_REVIEW_REQUIRED"


def _route_blockers(response: Mapping[str, Any]) -> list[str]:
    status = _int(response.get("http_status"))
    text = str(response.get("text_probe") or "")
    if response.get("transport_error"):
        return [f"guangdong_local_transport_error:{response.get('transport_error')}"]
    if status in {401, 403}:
        return ["guangdong_local_http_forbidden_or_login_required"]
    if status >= 500:
        return ["guangdong_local_source_server_error"]
    if _looks_like_captcha_or_login(text):
        return ["guangdong_local_captcha_or_login_required"]
    return []


def _looks_like_captcha_or_login(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in ("captcha", "验证码", "滑块", "请登录", "用户登录", "统一身份认证"))


def _project_task_records(query_task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for task in query_task_records:
        grouped.setdefault(str(task.get("project_id") or ""), []).append(task)
    records: list[dict[str, Any]] = []
    for project_id, tasks in grouped.items():
        records.append(
            {
                "project_id": project_id,
                "project_name": _first_text(task.get("project_name") for task in tasks),
                "query_task_ids": [str(task.get("query_task_id") or "") for task in tasks],
                "query_task_count": len(tasks),
                "source_profile_ids": _dedupe(task.get("source_profile_id") for task in tasks),
                "readback_ready_count": sum(1 for task in tasks if bool(task.get("readback_ready"))),
                "blocker_taxonomy_counts": _counts(
                    blocker for task in tasks for blocker in _list(task.get("blocker_taxonomy"))
                ),
                "probe_state": "READY" if tasks else "NO_GUANGDONG_LOCAL_TASKS",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _manual_check_table(query_task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "query_task_id": task.get("query_task_id"),
            "project_id": task.get("project_id"),
            "project_name": task.get("project_name"),
            "candidate_group_id": task.get("candidate_group_id"),
            "responsible_person_name": task.get("responsible_person_name"),
            "certificate_no": task.get("certificate_no"),
            "source_profile_id": task.get("source_profile_id"),
            "source_family": task.get("source_family"),
            "source_url": task.get("source_url"),
            "target_source_types": task.get("target_source_types"),
            "query_params": task.get("query_params"),
            "field_adapter_status": task.get("field_adapter_status"),
            "query_probe_state": task.get("query_probe_state"),
            "manual_check_state": "PENDING_PUBLIC_SOURCE_REVIEW",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for task in query_task_records
    ]


def _summary(
    *,
    query_task_records: list[Mapping[str, Any]],
    project_task_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    blockers = _counts(
        blocker for task in query_task_records for blocker in _list(task.get("blocker_taxonomy"))
    )
    return {
        "probe_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "execution_mode": execution_mode,
        "guangdong_local_verification_task_count": len(query_task_records),
        "project_count": len(project_task_records),
        "source_profile_task_counts": _counts(task.get("source_profile_id") for task in query_task_records),
        "source_family_task_counts": _counts(task.get("source_family") for task in query_task_records),
        "target_source_type_counts": _counts(
            source_type for task in query_task_records for source_type in _list(task.get("target_source_types"))
        ),
        "readback_ready_count": sum(1 for task in query_task_records if bool(task.get("readback_ready"))),
        "review_required_count": sum(1 for task in query_task_records if str(task.get("query_probe_state") or "") == "REVIEW_REQUIRED"),
        "fail_closed_count": sum(1 for task in query_task_records if str(task.get("query_probe_state") or "").startswith("FAIL_CLOSED")),
        "query_probe_state_counts": _counts(task.get("query_probe_state") for task in query_task_records),
        "blocker_taxonomy_counts": blockers,
        "field_adapter_status_counts": _counts(task.get("field_adapter_status") for task in query_task_records),
        "next_required_runtime_adapters": _dedupe(
            (task.get("source_entry") or {}).get("next_adapter")
            for task in query_task_records
            if isinstance(task.get("source_entry"), Mapping)
        ),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _source_cache_key(source_entry: Mapping[str, Any]) -> str:
    return "|".join([str(source_entry.get("source_profile_id") or ""), str(source_entry.get("source_url") or "")])


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _first_int(values: Iterable[Any]) -> int | None:
    for value in values:
        number = _int(value)
        if number:
            return number
    return None


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            counts[text] = counts.get(text, 0) + 1
    return counts


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _normalize_filter(values: Iterable[str] | None) -> set[str]:
    return {str(value or "").strip().upper() for value in (values or []) if str(value or "").strip()}


def _first_text(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _copy_jsonable(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, default=str))


def _sha256_text(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _decode_probe(body: bytes, content_type: str) -> str:
    if not body:
        return ""
    lowered = content_type.lower()
    encodings = ["gb18030", "utf-8"] if "charset=gb" in lowered else ["utf-8", "gb18030"]
    for encoding in encodings:
        try:
            return body.decode(encoding, errors="ignore")[:2000]
        except LookupError:
            continue
    return body.decode("utf-8", errors="ignore")[:2000]


def _http_timeout_seconds() -> int:
    try:
        return max(3, min(30, int(os.environ.get("KAKA_GD_LOCAL_HTTP_TIMEOUT_SECONDS", "8"))))
    except ValueError:
        return 8


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint([str(part or '') for part in parts])[:16]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangdong Local VerificationProbe v1.")
    parser.add_argument("--active-conflict-root", default=str(DEFAULT_ACTIVE_CONFLICT_ROOT))
    parser.add_argument("--active-conflict-json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--source-profile-ids", nargs="*", default=[])
    parser.add_argument("--enable-live-reachability", action="store_true")
    parser.add_argument("--max-live-tasks", type=int)
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangdong_local_verification_probe(
        active_conflict_root=args.active_conflict_root,
        active_conflict_json=args.active_conflict_json,
        output_root=args.output_root,
        source_profile_ids=args.source_profile_ids,
        enable_live_reachability=args.enable_live_reachability,
        max_live_tasks=args.max_live_tasks,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
