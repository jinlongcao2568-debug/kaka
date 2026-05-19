from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.request import Request, urlopen

from shared.utils import utc_now_iso
from stage4_verification.natural_resource_registered_surveyor import (
    run_natural_resource_registered_surveyor_provider_task,
)
from stage4_verification.provider_registry import NATURAL_RESOURCE_REGISTERED_SURVEYOR


DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_KIND = "design_survey_public_registry_readback_v1_manifest"
DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_VERSION = 1
DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ID = "design-survey-public-registry-readback-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/design-survey-public-registry-readback-v1")


def build_design_survey_public_registry_readback(
    *,
    public_registry_fallback_json: str | Path | None = None,
    public_registry_fallback_root: str | Path | None = None,
    provider_jobs_json: str | Path | None = None,
    snapshot_html_path: str | Path | None = None,
    snapshot_html_root: str | Path | None = None,
    snapshot_json: str | Path | None = None,
    execute_live_entry_readback: bool = False,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    fallback_manifest = _optional_manifest(
        explicit_json=public_registry_fallback_json,
        root=public_registry_fallback_root,
        default_file_name="design-survey-public-registry-fallback-v1.json",
    )
    jobs_payload = _load_json(Path(provider_jobs_json)) if provider_jobs_json else {}
    jobs = _provider_jobs(jobs_payload) or _provider_jobs(fallback_manifest)
    if not jobs:
        blocking_reasons.append("public_registry_provider_jobs_missing")

    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    snapshot_records = _snapshot_records(
        snapshot_html_path=snapshot_html_path,
        snapshot_html_root=snapshot_html_root,
        snapshot_json=snapshot_json,
    )

    readback_records: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []
    for job in jobs:
        if str(job.get("provider_id") or "") != NATURAL_RESOURCE_REGISTERED_SURVEYOR:
            skipped_records.append(_skipped_record(job, "not_natural_resource_registered_surveyor_job", created_at=created))
            continue
        project_id = _job_project_id(job)
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue
        snapshot = _snapshot_for_job(job, snapshot_records)
        result = run_natural_resource_registered_surveyor_provider_task(
            dict(job.get("payload") or {}),
            snapshot_html=str(snapshot.get("html") or "") or None,
            snapshot_source_url=str(snapshot.get("source_url") or ""),
            snapshot_ref=str(snapshot.get("snapshot_ref") or ""),
            enable_live_entry_readback=execute_live_entry_readback,
            http_get_text=_http_get_text if execute_live_entry_readback else None,
        )
        readback_records.append(_readback_record(job, provider_result=result, snapshot=snapshot, created_at=created))

    readback_table = {
        "summary": _readback_summary(readback_records),
        "records": readback_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = {
        **readback_table["summary"],
        "skipped_record_count": len(skipped_records),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_version": DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_VERSION,
        "manifest_kind": DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_KIND,
        "adapter_id": DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ID,
        "pipeline_stage": "DesignSurveyPublicRegistryReadbackV1",
        "manifest_id": f"DESIGN-SURVEY-PUBLIC-REG-READBACK-{_fingerprint({'summary': summary, 'records': readback_records})[:16]}",
        "created_at": created,
        "source_public_registry_fallback_json": _manifest_source_path(
            public_registry_fallback_json,
            public_registry_fallback_root,
            "design-survey-public-registry-fallback-v1.json",
        ),
        "source_provider_jobs_json": str(provider_jobs_json or ""),
        "source_snapshot_html_path": str(snapshot_html_path or ""),
        "source_snapshot_html_root": str(snapshot_html_root or ""),
        "source_snapshot_json": str(snapshot_json or ""),
        "execute_live_entry_readback": bool(execute_live_entry_readback),
        "public_registry_readback_table": readback_table,
        "skipped_records": skipped_records,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": bool(execute_live_entry_readback),
            "person_search_live_adapter_enabled": False,
            "manual_public_snapshot_supported": True,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "design_survey_public_registry_readback_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "design-survey-public-registry-readback-v1.json", result)
    _write_json(out_dir / "design-survey-public-registry-readback-table.json", readback_table)
    return result


def _readback_record(
    job: Mapping[str, Any],
    *,
    provider_result: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
    target = provider_result.get("target") if isinstance(provider_result.get("target"), Mapping) else {}
    project_id = _job_project_id(job)
    source_probe = payload.get("source_probe_item") if isinstance(payload.get("source_probe_item"), Mapping) else {}
    return {
        "public_registry_readback_id": _stable_id(
            "DESIGN-SURVEY-PUBLIC-REG-READBACK",
            job.get("job_id"),
            project_id,
            target.get("candidate_company_name"),
            target.get("responsible_person_name"),
        ),
        "source_job_id": job.get("job_id", ""),
        "project_id": project_id,
        "project_name": str(source_probe.get("project_name") or ""),
        "provider_id": provider_result.get("provider_id", ""),
        "provider_result_state": provider_result.get("provider_result_state", ""),
        "readback_state": provider_result.get("readback_state", ""),
        "verification_result": provider_result.get("verification_result", ""),
        "identity_resolution_state": provider_result.get("identity_resolution_state", ""),
        "candidate_company_name": target.get("candidate_company_name", ""),
        "responsible_person_name": target.get("responsible_person_name", ""),
        "certificate_no_optional": target.get("certificate_no_optional", ""),
        "identity_fields": dict(provider_result.get("identity_fields") or {}),
        "public_registry_readback": dict(provider_result.get("public_registry_readback") or {}),
        "source_refs": list(provider_result.get("source_refs") or []),
        "source_snapshot_ref": snapshot.get("snapshot_ref", ""),
        "source_snapshot_path": snapshot.get("snapshot_path", ""),
        "source_snapshot_sha256": snapshot.get("snapshot_sha256", ""),
        "failure_reasons": list(provider_result.get("failure_reasons") or []),
        "review_reasons": list(provider_result.get("review_reasons") or []),
        "policy": dict(provider_result.get("policy") or {}),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _readback_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "readback_record_count": len(records),
        "project_count": len({record.get("project_id") for record in records}),
        "provider_result_state_counts": _counts(record.get("provider_result_state") for record in records),
        "readback_state_counts": _counts(record.get("readback_state") for record in records),
        "verification_result_counts": _counts(record.get("verification_result") for record in records),
        "matched_count": sum(1 for record in records if record.get("verification_result") == "MATCHED"),
        "review_required_count": sum(1 for record in records if record.get("verification_result") == "REVIEW_REQUIRED"),
        "snapshot_supplied_count": sum(1 for record in records if str(record.get("source_snapshot_sha256") or "")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _snapshot_records(
    *,
    snapshot_html_path: str | Path | None,
    snapshot_html_root: str | Path | None,
    snapshot_json: str | Path | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if snapshot_json:
        payload = _load_json(Path(snapshot_json))
        raw_records = (payload.get("snapshots") or payload.get("records")) if isinstance(payload, Mapping) else []
        for record in raw_records if isinstance(raw_records, list) else []:
            if isinstance(record, Mapping):
                records.append(_snapshot_record_from_payload(record))
    if snapshot_html_path:
        path = Path(snapshot_html_path)
        html = _read_text(path)
        if html:
            records.append(_snapshot_record(html=html, snapshot_path=path, source_url="", snapshot_ref=path.stem))
    if snapshot_html_root:
        root = Path(snapshot_html_root)
        for path in sorted([*root.glob("*.html"), *root.glob("*.htm"), *root.glob("*.txt")]):
            html = _read_text(path)
            if html:
                records.append(_snapshot_record(html=html, snapshot_path=path, source_url="", snapshot_ref=path.stem))
    return records


def _snapshot_for_job(job: Mapping[str, Any], snapshots: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        return {}
    payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
    target = payload.get("target") if isinstance(payload.get("target"), Mapping) else {}
    source_task = payload.get("source_public_registry_task") if isinstance(payload.get("source_public_registry_task"), Mapping) else {}
    query_fields = source_task.get("query_fields") if isinstance(source_task.get("query_fields"), Mapping) else {}
    keys = {
        _clean_key(job.get("job_id")),
        _clean_key(source_task.get("public_registry_task_id")),
        _clean_key(_job_project_id(job)),
        _clean_key(target.get("candidate_company_name")),
        _clean_key(query_fields.get("registered_unit_or_candidate_company")),
        _clean_key(target.get("responsible_person_name") or query_fields.get("person_name")),
    }
    exact = [
        snapshot
        for snapshot in snapshots
        if _clean_key(snapshot.get("job_id")) in keys
        or _clean_key(snapshot.get("public_registry_task_id")) in keys
        or _clean_key(snapshot.get("project_id")) in keys
    ]
    if exact:
        return dict(exact[0])
    for snapshot in snapshots:
        name = _clean_key(snapshot.get("snapshot_ref") or snapshot.get("snapshot_path"))
        if any(key and key in name for key in keys):
            return dict(snapshot)
    return dict(snapshots[0]) if len(snapshots) == 1 else {}


def _snapshot_record_from_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    html = str(record.get("html") or record.get("body") or record.get("text") or "")
    return {
        **dict(record),
        "html": html,
        "snapshot_sha256": _sha256(html),
        "snapshot_ref": str(record.get("snapshot_ref") or record.get("snapshot_id") or ""),
        "source_url": str(record.get("source_url") or ""),
    }


def _snapshot_record(*, html: str, snapshot_path: Path, source_url: str, snapshot_ref: str) -> dict[str, Any]:
    return {
        "html": html,
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": _sha256(html),
        "snapshot_ref": snapshot_ref,
        "source_url": source_url,
    }


def _provider_jobs(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    if isinstance(payload.get("manifest"), Mapping):
        return _provider_jobs(payload["manifest"])
    jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
    if jobs:
        return [dict(job) for job in jobs if isinstance(job, Mapping)]
    nested = payload.get("stage4_provider_jobs") if isinstance(payload.get("stage4_provider_jobs"), Mapping) else {}
    jobs = nested.get("jobs") if isinstance(nested.get("jobs"), list) else []
    return [dict(job) for job in jobs if isinstance(job, Mapping)]


def _job_project_id(job: Mapping[str, Any]) -> str:
    payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
    source_probe = payload.get("source_probe_item") if isinstance(payload.get("source_probe_item"), Mapping) else {}
    return str(job.get("project_id") or source_probe.get("project_id") or "").strip()


def _skipped_record(job: Mapping[str, Any], reason: str, *, created_at: str) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id", ""),
        "provider_id": job.get("provider_id", ""),
        "skip_reason": reason,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _optional_manifest(
    *,
    explicit_json: str | Path | None,
    root: str | Path | None,
    default_file_name: str,
) -> dict[str, Any]:
    path = Path(explicit_json) if explicit_json else (Path(root) / default_file_name if root else None)
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        return {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    return dict(manifest)


def _manifest_source_path(explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> str:
    if explicit_json:
        return str(explicit_json)
    if root:
        return str(Path(root) / default_file_name)
    return ""


def _http_get_text(url: str, headers: Mapping[str, str]) -> str:
    request = Request(url, headers=dict(headers or {}))
    with urlopen(request, timeout=20) as response:  # noqa: S310 - explicit operator opt-in public readback.
        return response.read().decode("utf-8", errors="replace")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="gb18030", errors="replace")
    except OSError:
        return ""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"JG\d{4}-\d+(?:-\d+)?", text)
    if match:
        return match.group(0)
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _clean_key(value: Any) -> str:
    return re.sub(r"\W+", "", str(value or "").lower())


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint(parts)[:20]}"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _sha256(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _parse_project_ids(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；\s]+", value or "") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute design/survey registered-surveyor public-registry readback.")
    parser.add_argument("--public-registry-fallback-json", default="")
    parser.add_argument("--public-registry-fallback-root", default="")
    parser.add_argument("--provider-jobs-json", default="")
    parser.add_argument("--snapshot-html-path", default="")
    parser.add_argument("--snapshot-html-root", default="")
    parser.add_argument("--snapshot-json", default="")
    parser.add_argument("--execute-live-entry-readback", action="store_true")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args(argv)

    result = build_design_survey_public_registry_readback(
        public_registry_fallback_json=args.public_registry_fallback_json or None,
        public_registry_fallback_root=args.public_registry_fallback_root or None,
        provider_jobs_json=args.provider_jobs_json or None,
        snapshot_html_path=args.snapshot_html_path or None,
        snapshot_html_root=args.snapshot_html_root or None,
        snapshot_json=args.snapshot_json or None,
        execute_live_entry_readback=bool(args.execute_live_entry_readback),
        output_root=args.output_root,
        project_ids=_parse_project_ids(args.project_ids),
        created_at=args.created_at or None,
    )
    if args.output_json:
        _write_json(Path(args.output_json), result)
    if args.emit_json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "output_root": str(args.output_root),
                    "safe_to_execute": result["safe_to_execute"],
                    "summary": result["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ID",
    "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_KIND",
    "build_design_survey_public_registry_readback",
]
