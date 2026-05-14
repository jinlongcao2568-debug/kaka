from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


GUANGZHOU_EVIDENCE_FIXATION_RECAPTURE_KIND = "guangzhou_evidence_fixation_recapture_v1_manifest"
GUANGZHOU_EVIDENCE_FIXATION_RECAPTURE_VERSION = 1
GUANGZHOU_EVIDENCE_FIXATION_RECAPTURE_ADAPTER_ID = "guangzhou-evidence-fixation-recapture-v1"

DEFAULT_BACKFILL_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-backfill-v1")
DEFAULT_INTERNAL_PACKAGE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-internal-evidence-package-manifest-p8-v1")
DEFAULT_FLOW_ROOT = Path("tmp/evaluation-real-samples/guangzhou-flowurl-analysis-72h-v1")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/guangzhou-download-human-v1")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v4-merged")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-recapture-v1")

FORBIDDEN_TERMS = ("是不是本人", "确认本人", "无风险", "无冲突", "在建冲突成立", "冲突成立", "造假成立", "违法成立")

FlowFetcher = Callable[[str], Mapping[str, Any]]


def build_guangzhou_evidence_fixation_recapture(
    *,
    backfill_root: str | Path = DEFAULT_BACKFILL_ROOT,
    internal_package_root: str | Path = DEFAULT_INTERNAL_PACKAGE_ROOT,
    flow_root: str | Path = DEFAULT_FLOW_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute: bool = False,
    flow_fetcher: FlowFetcher | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    backfill_dir = Path(backfill_root)
    package_dir = Path(internal_package_root)
    flow_dir = Path(flow_root)
    download_dir = Path(download_root)
    stage4_dir = Path(stage4_execution_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    backfill_manifest = _source_manifest(
        _load_json(backfill_dir / "evidence-fixation-backfill-v1.json", blocking_reasons, "backfill_manifest_missing")
    )
    package_manifest = _source_manifest(
        _load_json(package_dir / "internal-evidence-package-manifest-v1.json", blocking_reasons, "internal_package_missing")
    )
    flow_manifest = _source_manifest(_load_json(flow_dir / "run-manifest.json", blocking_reasons, "flow_run_manifest_missing"))
    _load_json_optional(download_dir / "download-probe-manifest.json")
    stage4_manifest = _source_manifest(
        _load_json(stage4_dir / "company-first-stage4-execution.json", blocking_reasons, "stage4_execution_missing")
    )

    source_records_by_id = {
        str(row.get("source_fixation_id") or ""): dict(row)
        for row in _list(package_manifest.get("source_fixation_records"))
        if isinstance(row, Mapping) and str(row.get("source_fixation_id") or "")
    }
    stage4_by_job = {
        str(item.get("job_id") or ""): dict(item)
        for item in _list(stage4_manifest.get("items"))
        if isinstance(item, Mapping) and str(item.get("job_id") or "")
    }
    recapture_candidates = [
        dict(row)
        for row in _list(backfill_manifest.get("backfill_records"))
        if isinstance(row, Mapping) and str(row.get("backfill_state") or "") == "UNFIXABLE_WITH_CURRENT_ARTIFACTS"
    ]
    repository = _repository(storage_path=out_dir / "recapture-storage.json", object_storage_path=out_dir / "objects") if execute else None
    records = [
        _recapture_record(
            candidate=row,
            source_record=source_records_by_id.get(str(row.get("source_fixation_id") or ""), {}),
            stage4_by_job=stage4_by_job,
            flow_manifest=flow_manifest,
            repository=repository,
            flow_fetcher=flow_fetcher,
            execute=execute,
            created_at=created,
        )
        for row in recapture_candidates
    ]
    summary = _summary(records=records, blocking_reasons=blocking_reasons, execute=execute)
    manifest = {
        "manifest_version": GUANGZHOU_EVIDENCE_FIXATION_RECAPTURE_VERSION,
        "manifest_kind": GUANGZHOU_EVIDENCE_FIXATION_RECAPTURE_KIND,
        "adapter_id": GUANGZHOU_EVIDENCE_FIXATION_RECAPTURE_ADAPTER_ID,
        "pipeline_stage": "GuangzhouEvidenceFixationRecaptureV1",
        "manifest_id": f"GUANGZHOU-EVIDENCE-FIXATION-RECAPTURE-{_fingerprint({'summary': summary, 'records': records})[:16]}",
        "created_at": created,
        "execute_enabled": bool(execute),
        "source_backfill_root": str(backfill_dir),
        "source_internal_package_root": str(package_dir),
        "source_flow_root": str(flow_dir),
        "source_download_root": str(download_dir),
        "source_stage4_execution_root": str(stage4_dir),
        "recapture_records": records,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "manifest_stores_raw_html_or_blob": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_evidence_fixation_recapture_mode": "EXECUTED" if execute else "PLAN_ONLY",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [f"forbidden_term_{idx}" for idx, term in enumerate(FORBIDDEN_TERMS, start=1) if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*blocking_reasons, *[f"forbidden_report_term:{code}" for code in forbidden_hits]]
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "evidence-fixation-recapture-v1.json").write_text(text, encoding="utf-8")
    return result


def _recapture_record(
    *,
    candidate: Mapping[str, Any],
    source_record: Mapping[str, Any],
    stage4_by_job: Mapping[str, Mapping[str, Any]],
    flow_manifest: Mapping[str, Any],
    repository: ObjectStorageRepository | None,
    flow_fetcher: FlowFetcher | None,
    execute: bool,
    created_at: str,
) -> dict[str, Any]:
    family = str(candidate.get("source_family") or source_record.get("source_family") or "")
    if family == "flow_url_manifest":
        return _flow_detail_recapture(
            candidate=candidate,
            source_record=source_record,
            flow_manifest=flow_manifest,
            repository=repository,
            flow_fetcher=flow_fetcher,
            execute=execute,
            created_at=created_at,
        )
    if family in {"stage4_company_personnel_readback", "stage4_personnel_project_readback"}:
        return _stage4_readback_recapture(
            candidate=candidate,
            source_record=source_record,
            stage4_by_job=stage4_by_job,
            execute=execute,
            created_at=created_at,
        )
    return _base_record(candidate, source_record, "UNSUPPORTED_RECAPTURE_FAMILY", execute=execute, failure_taxonomy=["unsupported_recapture_family"])


def _flow_detail_recapture(
    *,
    candidate: Mapping[str, Any],
    source_record: Mapping[str, Any],
    flow_manifest: Mapping[str, Any],
    repository: ObjectStorageRepository | None,
    flow_fetcher: FlowFetcher | None,
    execute: bool,
    created_at: str,
) -> dict[str, Any]:
    record = _base_record(candidate, source_record, "PLAN_ONLY_NOT_EXECUTED", execute=execute)
    record["recapture_task_type"] = "FLOW_DETAIL_RECAPTURE"
    if not execute:
        record["next_actions"] = ["EXECUTE_FLOW_DETAIL_RECAPTURE"]
        return record
    url = str(candidate.get("source_url") or source_record.get("source_url") or "")
    if not url:
        record.update({"recapture_state": "FLOW_DETAIL_RECAPTURE_BLOCKED", "failure_taxonomy": ["source_url_missing"]})
        return record
    try:
        fetched = dict(flow_fetcher(url) if flow_fetcher else _default_fetch_url(url))
        body = fetched.get("body_bytes") or b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        if not body:
            record.update({"recapture_state": "FLOW_DETAIL_RECAPTURE_BLOCKED", "failure_taxonomy": ["empty_response_body"]})
            return record
        sha256 = hashlib.sha256(body).hexdigest()
        snapshot_id = f"P9-FLOW-{sha256[:20]}"
        assert repository is not None
        manifest = repository.save_snapshot(
            body,
            snapshot_id=snapshot_id,
            snapshot_kind="guangzhou_flow_detail_recapture",
            content_type=str(fetched.get("content_type") or "text/html"),
            source_url_optional=url,
            source_family_optional="guangzhou_flow_url_manifest",
            lineage_refs={
                "project_id": str(candidate.get("project_id") or source_record.get("project_id") or ""),
                "source_fixation_id": str(candidate.get("source_fixation_id") or ""),
                "flow_no": str(candidate.get("flow_no") or source_record.get("flow_no") or ""),
            },
            created_at=created_at,
            adapter_id=GUANGZHOU_EVIDENCE_FIXATION_RECAPTURE_ADAPTER_ID,
            fetch_mode="p9_flow_detail_recapture",
            fetch_audit={"status_code": str(fetched.get("status_code") or ""), "route": str(fetched.get("route") or "urllib")},
        )
        record.update(
            {
                "recapture_state": "FLOW_DETAIL_RECAPTURED",
                "snapshot_id": manifest.snapshot_id,
                "readback_ref": manifest.replay_state,
                "sha256": manifest.sha256,
                "content_type": manifest.content_type,
                "byte_size": manifest.byte_size,
                "object_key": manifest.object_key,
                "route_attempts": [{"route": str(fetched.get("route") or "urllib"), "status_code": fetched.get("status_code", "")}],
                "failure_taxonomy": [],
            }
        )
        return record
    except Exception as exc:
        record.update(
            {
                "recapture_state": "FLOW_DETAIL_RECAPTURE_BLOCKED",
                "failure_taxonomy": [f"flow_detail_recapture_exception:{type(exc).__name__}"],
                "route_attempts": [{"route": "urllib", "error_type": type(exc).__name__}],
            }
        )
        return record


def _stage4_readback_recapture(
    *,
    candidate: Mapping[str, Any],
    source_record: Mapping[str, Any],
    stage4_by_job: Mapping[str, Mapping[str, Any]],
    execute: bool,
    created_at: str,
) -> dict[str, Any]:
    record = _base_record(candidate, source_record, "PLAN_ONLY_NOT_EXECUTED", execute=execute)
    record["recapture_task_type"] = "STAGE4_READBACK_RECAPTURE"
    if not execute:
        record["next_actions"] = ["EXECUTE_STAGE4_READBACK_RECAPTURE"]
        return record
    job_id = str(source_record.get("readback_ref") or candidate.get("readback_ref") or "")
    item = dict(stage4_by_job.get(job_id) or {})
    if not item:
        record.update({"recapture_state": "STAGE4_READBACK_RECAPTURE_BLOCKED", "failure_taxonomy": ["stage4_job_not_found_for_readback_ref"]})
        return record
    probe = _stage4_field_probe(item)
    readback_hash = _fingerprint({"field_evidence_probe": probe, "job_id": job_id, "created_at": created_at})
    record.update(
        {
            "recapture_state": "STAGE4_READBACK_RECAPTURED",
            "source_readback_url": str(item.get("company_personnel_source_url") or item.get("personnel_project_source_url") or source_record.get("source_url") or ""),
            "source_readback_sha256": readback_hash,
            "readback_payload_sha256": readback_hash,
            "field_evidence_probe": probe,
            "browser_route_attempts": _safe_route_attempts(item),
            "failure_taxonomy": [],
        }
    )
    return record


def _stage4_field_probe(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(item.get("job_id") or ""),
        "project_id": str(item.get("project_id") or ""),
        "candidate_group_id": str(item.get("candidate_group_id") or ""),
        "candidate_company_name": str(item.get("candidate_company_name") or ""),
        "responsible_person_name": str(item.get("responsible_person_name") or ""),
        "resolved_certificate_no_optional": str(item.get("resolved_certificate_no_optional") or ""),
        "registered_unit_name_optional": str(item.get("registered_unit_name_optional") or ""),
        "matched_company_name_optional": str(item.get("matched_company_name_optional") or ""),
        "company_personnel_source_url": str(item.get("company_personnel_source_url") or ""),
        "personnel_project_source_url": str(item.get("personnel_project_source_url") or ""),
        "stage4_execution_state": str(item.get("stage4_execution_state") or ""),
        "readback_state": str(item.get("readback_state") or ""),
    }


def _base_record(candidate: Mapping[str, Any], source_record: Mapping[str, Any], state: str, *, execute: bool, failure_taxonomy: list[str] | None = None) -> dict[str, Any]:
    return {
        "source_fixation_id": str(candidate.get("source_fixation_id") or source_record.get("source_fixation_id") or ""),
        "project_id": str(candidate.get("project_id") or source_record.get("project_id") or ""),
        "candidate_group_id": str(candidate.get("candidate_group_id") or source_record.get("candidate_group_id") or ""),
        "source_family": str(candidate.get("source_family") or source_record.get("source_family") or ""),
        "flow_no": str(candidate.get("flow_no") or source_record.get("flow_no") or ""),
        "source_url": str(candidate.get("source_url") or source_record.get("source_url") or ""),
        "readback_ref": str(source_record.get("readback_ref") or candidate.get("readback_ref") or ""),
        "recapture_state": state,
        "execute_enabled": bool(execute),
        "failure_taxonomy": list(failure_taxonomy or []),
        "route_attempts": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _default_fetch_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaEvidenceRecapture/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return {
                "status_code": getattr(response, "status", 200),
                "content_type": response.headers.get("Content-Type") or "application/octet-stream",
                "body_bytes": response.read(),
                "route": "urllib",
            }
    except urllib.error.HTTPError as exc:
        return {"status_code": exc.code, "content_type": exc.headers.get("Content-Type") or "", "body_bytes": exc.read(), "route": "urllib"}


def _summary(*, records: list[Mapping[str, Any]], blocking_reasons: list[str], execute: bool) -> dict[str, Any]:
    states = _counts(record.get("recapture_state") for record in records)
    families = _counts(record.get("source_family") for record in records)
    failures = _counts(reason for record in records for reason in _list(record.get("failure_taxonomy")))
    return {
        "recapture_state": "P9_RECAPTURE_EXECUTED" if execute and not blocking_reasons else ("P9_RECAPTURE_PLAN_READY" if not blocking_reasons else "P9_RECAPTURE_INPUT_BLOCKED"),
        "recapture_task_count": len(records),
        "flow_detail_recapture_task_count": sum(1 for record in records if record.get("recapture_task_type") == "FLOW_DETAIL_RECAPTURE"),
        "stage4_readback_recapture_task_count": sum(1 for record in records if record.get("recapture_task_type") == "STAGE4_READBACK_RECAPTURE"),
        "recapture_state_counts": states,
        "source_family_counts": families,
        "failure_taxonomy_counts": failures,
        "blocking_reasons": list(blocking_reasons),
        "execute_enabled": bool(execute),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _repository(*, storage_path: Path, object_storage_path: Path) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(storage_path),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_storage_path),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def _safe_route_attempts(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts = []
    for attempt in _list(item.get("browser_attempts")):
        if not isinstance(attempt, Mapping):
            continue
        attempts.append({key: attempt.get(key) for key in ("attempt_type", "result_count", "matched_count", "state", "error_type") if key in attempt})
    return attempts


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        blocking_reasons.append(f"{missing_reason}_invalid_json")
        return {}
    return data if isinstance(data, dict) else {}


def _load_json_optional(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else None
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload) if isinstance(payload, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangzhou evidence fixation recapture v1.")
    parser.add_argument("--backfill-root", default=str(DEFAULT_BACKFILL_ROOT))
    parser.add_argument("--internal-package-root", default=str(DEFAULT_INTERNAL_PACKAGE_ROOT))
    parser.add_argument("--flow-root", default=str(DEFAULT_FLOW_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = build_guangzhou_evidence_fixation_recapture(
        backfill_root=args.backfill_root,
        internal_package_root=args.internal_package_root,
        flow_root=args.flow_root,
        download_root=args.download_root,
        stage4_execution_root=args.stage4_execution_root,
        output_root=args.output_root,
        execute=args.execute,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
