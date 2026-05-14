from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_EVIDENCE_FIXATION_BACKFILL_KIND = "guangzhou_evidence_fixation_backfill_v1_manifest"
GUANGZHOU_EVIDENCE_FIXATION_BACKFILL_VERSION = 1
GUANGZHOU_EVIDENCE_FIXATION_BACKFILL_ADAPTER_ID = "guangzhou-evidence-fixation-backfill-v1"

DEFAULT_INTERNAL_EVIDENCE_PACKAGE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-internal-evidence-package-manifest-v1")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/guangzhou-download-human-v1")
DEFAULT_FLOW_ROOT = Path("tmp/evaluation-real-samples/guangzhou-flowurl-analysis-72h-v1")
DEFAULT_GDCIC_QUERY_PROBE_ROOT = Path("tmp/evaluation-real-samples/guangdong-gdcic-query-probe-v1-live-max12")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v4-merged")
DEFAULT_RECAPTURE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-recapture-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-backfill-v1")

FORBIDDEN_TERMS = ("是不是本人", "确认本人", "无风险", "无冲突", "在建冲突成立", "冲突成立", "造假成立", "违法成立")


def build_guangzhou_evidence_fixation_backfill(
    *,
    internal_evidence_package_root: str | Path = DEFAULT_INTERNAL_EVIDENCE_PACKAGE_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    flow_root: str | Path = DEFAULT_FLOW_ROOT,
    gdcic_query_probe_root: str | Path = DEFAULT_GDCIC_QUERY_PROBE_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    recapture_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
    gdcic_query_required: bool = True,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    package_dir = Path(internal_evidence_package_root)
    download_dir = Path(download_root)
    flow_dir = Path(flow_root)
    gdcic_dir = Path(gdcic_query_probe_root)
    stage4_dir = Path(stage4_execution_root)
    recapture_dir = Path(recapture_root) if recapture_root else None
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    package_manifest = _source_manifest(
        _load_json(package_dir / "internal-evidence-package-manifest-v1.json", blocking_reasons, "internal_evidence_package_missing")
    )
    download_manifest = _source_manifest(
        _load_json(download_dir / "download-probe-manifest.json", blocking_reasons, "download_probe_manifest_missing")
    )
    human_file_map = _load_json_optional(download_dir / "human-readable-file-map.json")
    flow_manifest = _source_manifest(_load_json(flow_dir / "run-manifest.json", blocking_reasons, "flow_run_manifest_missing"))
    gdcic_missing_reasons: list[str] = []
    gdcic_manifest = _source_manifest(
        _load_json(
            gdcic_dir / "guangdong-gdcic-query-probe-v1.json",
            blocking_reasons if gdcic_query_required else gdcic_missing_reasons,
            "gdcic_query_probe_missing",
        )
    )
    stage4_manifest = _source_manifest(
        _load_json(stage4_dir / "company-first-stage4-execution.json", blocking_reasons, "stage4_execution_missing")
    )
    recapture_manifest = _source_manifest(
        _load_json_optional(recapture_dir / "evidence-fixation-recapture-v1.json") if recapture_dir else {}
    )

    download_snapshot_index = _download_snapshot_index(download_manifest, human_file_map)
    gdcic_index = _gdcic_task_index(gdcic_manifest)
    stage4_index = _stage4_record_index(stage4_manifest)
    recapture_index = _recapture_record_index(recapture_manifest)
    source_records = [row for row in _list(package_manifest.get("source_fixation_records")) if isinstance(row, Mapping)]
    backfill_records = [
        _backfill_record(
            source_record=row,
            download_snapshot_index=download_snapshot_index,
            gdcic_index=gdcic_index,
            stage4_index=stage4_index,
            recapture_index=recapture_index,
        )
        for row in source_records
        if str(row.get("fixation_state") or "") != "FIXATION_COMPLETE"
    ]
    summary = _summary(backfill_records=backfill_records, blocking_reasons=blocking_reasons)
    if gdcic_missing_reasons:
        summary["gdcic_query_probe_optional_missing_reasons"] = gdcic_missing_reasons
        summary["gdcic_query_probe_is_not_backfill_gate"] = True
    manifest = {
        "manifest_version": GUANGZHOU_EVIDENCE_FIXATION_BACKFILL_VERSION,
        "manifest_kind": GUANGZHOU_EVIDENCE_FIXATION_BACKFILL_KIND,
        "adapter_id": GUANGZHOU_EVIDENCE_FIXATION_BACKFILL_ADAPTER_ID,
        "pipeline_stage": "GuangzhouEvidenceFixationBackfillV1",
        "manifest_id": f"GUANGZHOU-EVIDENCE-FIXATION-BACKFILL-{_fingerprint({'summary': summary, 'records': backfill_records})[:16]}",
        "created_at": created,
        "source_internal_evidence_package_root": str(package_dir),
        "source_download_root": str(download_dir),
        "source_flow_root": str(flow_dir),
        "source_gdcic_query_probe_root": str(gdcic_dir),
        "gdcic_query_required": gdcic_query_required,
        "source_stage4_execution_root": str(stage4_dir),
        "source_recapture_root": str(recapture_dir) if recapture_dir else "",
        "backfill_records": backfill_records,
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
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_evidence_fixation_backfill_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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
    (out_dir / "evidence-fixation-backfill-v1.json").write_text(text, encoding="utf-8")
    return result


def _backfill_record(
    *,
    source_record: Mapping[str, Any],
    download_snapshot_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    gdcic_index: Mapping[str, Mapping[str, Any]],
    stage4_index: Mapping[str, Mapping[str, Any]],
    recapture_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    family = str(source_record.get("source_family") or "")
    source_id = str(source_record.get("source_fixation_id") or "")
    recaptured = _recapture_backfill(source_record, recapture_index.get(source_id), source_id)
    if recaptured is not None:
        return recaptured
    if family in {"flow_url_manifest", "evidence_report_candidate_notice_url"}:
        return _download_backfill(source_record, download_snapshot_index, source_id)
    if family == "official_source_readback_summary":
        return _gdcic_backfill(source_record, gdcic_index, source_id)
    if family in {"stage4_company_personnel_readback", "stage4_personnel_project_readback"}:
        return _stage4_backfill(source_record, stage4_index, source_id)
    return _unfixable(source_record, source_id, "unsupported_source_family_for_backfill")


def _recapture_backfill(source_record: Mapping[str, Any], recapture_record: Mapping[str, Any] | None, source_id: str) -> dict[str, Any] | None:
    if not recapture_record:
        return None
    state = str(recapture_record.get("recapture_state") or "")
    if state == "FLOW_DETAIL_RECAPTURED":
        return _record(
            source_record=source_record,
            source_fixation_id=source_id,
            backfill_state="BACKFILLED_FROM_RECAPTURED_DETAIL_SNAPSHOT",
            backfill_classification="CONTENT_SNAPSHOT_HASH_BACKFILLED",
            backfilled_fields={
                "snapshot_id": str(recapture_record.get("snapshot_id") or ""),
                "readback_ref": str(recapture_record.get("readback_ref") or "READBACK_READY"),
                "sha256": str(recapture_record.get("sha256") or ""),
                "local_path": str(recapture_record.get("object_key") or ""),
                "content_type": str(recapture_record.get("content_type") or ""),
                "byte_size": _int(recapture_record.get("byte_size")),
            },
            remaining_gap_reasons=[],
            backfill_source_ref="guangzhou_evidence_fixation_recapture.flow_detail",
        )
    if state == "STAGE4_READBACK_RECAPTURED":
        readback_hash = str(recapture_record.get("source_readback_sha256") or recapture_record.get("readback_payload_sha256") or "")
        return _record(
            source_record=source_record,
            source_fixation_id=source_id,
            backfill_state="BACKFILLED_FROM_RECAPTURED_STAGE4_READBACK",
            backfill_classification="SOURCE_READBACK_HASH_BACKFILLED",
            backfilled_fields={
                "source_url": str(recapture_record.get("source_readback_url") or source_record.get("source_url") or ""),
                "readback_ref": str(recapture_record.get("readback_ref") or source_record.get("readback_ref") or ""),
                "sha256": readback_hash,
                "source_readback_sha256": readback_hash,
                "readback_payload_sha256": str(recapture_record.get("readback_payload_sha256") or readback_hash),
            },
            remaining_gap_reasons=[],
            backfill_source_ref="guangzhou_evidence_fixation_recapture.stage4_readback",
        )
    if "BLOCKED" in state:
        return _record(
            source_record=source_record,
            source_fixation_id=source_id,
            backfill_state="RECAPTURE_BLOCKED_CURRENT_ARTIFACT_GAP_CLASSIFIED",
            backfill_classification="CURRENT_ARTIFACT_GAP_CLASSIFIED",
            backfilled_fields={},
            remaining_gap_reasons=[*list(recapture_record.get("failure_taxonomy") or []), *_list(source_record.get("fixation_gap_reasons"))],
            backfill_source_ref="guangzhou_evidence_fixation_recapture.blocked",
        )
    return None


def _download_backfill(
    source_record: Mapping[str, Any],
    download_snapshot_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    source_id: str,
) -> dict[str, Any]:
    project_id = str(source_record.get("project_id") or "")
    flow_no = str(source_record.get("flow_no") or "")
    source_url = str(source_record.get("source_url") or "")
    match = download_snapshot_index.get((project_id, flow_no, source_url))
    if not match:
        return _unfixable(source_record, source_id, "missing_download_snapshot")
    return _record(
        source_record=source_record,
        source_fixation_id=source_id,
        backfill_state="BACKFILLED_FROM_DOWNLOAD_DETAIL_SNAPSHOT",
        backfill_classification="CONTENT_SNAPSHOT_HASH_BACKFILLED",
        backfilled_fields={
            "snapshot_id": str(match.get("snapshot_id") or ""),
            "readback_ref": str(match.get("readback_state") or "READBACK_READY"),
            "sha256": str(match.get("sha256") or ""),
            "local_path": str(match.get("human_readable_path") or match.get("local_path") or ""),
            "content_type": str(match.get("content_type") or ""),
            "byte_size": _int(match.get("byte_size")),
        },
        remaining_gap_reasons=[],
        backfill_source_ref="download_manifest_or_human_readable_file_map",
    )


def _gdcic_backfill(
    source_record: Mapping[str, Any],
    gdcic_index: Mapping[str, Mapping[str, Any]],
    source_id: str,
) -> dict[str, Any]:
    query_task_id = str(source_record.get("readback_ref") or "")
    match = gdcic_index.get(query_task_id)
    if not match:
        return _unfixable(source_record, source_id, "no_matching_query_task")
    record_hash = _fingerprint(match)
    return _record(
        source_record=source_record,
        source_fixation_id=source_id,
        backfill_state="BACKFILLED_FROM_GDCIC_QUERY_TASK",
        backfill_classification="READBACK_RECORD_HASH_BACKFILLED",
        backfilled_fields={
            "source_url": str(match.get("source_url") or "https://skypt.gdcic.net/openplatform/"),
            "readback_ref": query_task_id,
            "sha256": record_hash,
            "readback_record_sha256": record_hash,
            "query_params": dict(match.get("query_params") or {}),
        },
        remaining_gap_reasons=[],
        backfill_source_ref="guangdong_gdcic_query_probe.query_task_records",
    )


def _stage4_backfill(
    source_record: Mapping[str, Any],
    stage4_index: Mapping[str, Mapping[str, Any]],
    source_id: str,
) -> dict[str, Any]:
    snapshot_id = str(source_record.get("snapshot_id") or "")
    match = stage4_index.get(snapshot_id)
    if not match:
        return _unfixable(source_record, source_id, "stage4_snapshot_not_replayable")
    record_hash = _fingerprint(match)
    return _record(
        source_record=source_record,
        source_fixation_id=source_id,
        backfill_state="RECORD_HASH_BACKFILLED_CONTENT_HASH_NOT_AVAILABLE",
        backfill_classification="READBACK_RECORD_HASH_ONLY",
        backfilled_fields={
            "snapshot_id": snapshot_id,
            "readback_ref": str(match.get("job_id") or snapshot_id),
            "readback_record_sha256": record_hash,
            "sha256": "",
        },
        remaining_gap_reasons=["source_content_sha256_not_available_from_current_artifacts"],
        backfill_source_ref="company_first_stage4_execution.items",
    )


def _unfixable(source_record: Mapping[str, Any], source_id: str, reason: str) -> dict[str, Any]:
    return _record(
        source_record=source_record,
        source_fixation_id=source_id,
        backfill_state="UNFIXABLE_WITH_CURRENT_ARTIFACTS",
        backfill_classification="CURRENT_ARTIFACT_GAP_CLASSIFIED",
        backfilled_fields={},
        remaining_gap_reasons=[reason, *_list(source_record.get("fixation_gap_reasons"))],
        backfill_source_ref="",
    )


def _record(
    *,
    source_record: Mapping[str, Any],
    source_fixation_id: str,
    backfill_state: str,
    backfill_classification: str,
    backfilled_fields: Mapping[str, Any],
    remaining_gap_reasons: list[Any],
    backfill_source_ref: str,
) -> dict[str, Any]:
    payload = {
        "source_fixation_id": source_fixation_id,
        "project_id": str(source_record.get("project_id") or ""),
        "candidate_group_id": str(source_record.get("candidate_group_id") or ""),
        "source_family": str(source_record.get("source_family") or ""),
        "source_url": str(source_record.get("source_url") or backfilled_fields.get("source_url") or ""),
        "flow_no": str(source_record.get("flow_no") or ""),
        "original_gap_reasons": _list(source_record.get("fixation_gap_reasons")),
        "backfill_state": backfill_state,
        "backfill_classification": backfill_classification,
        "backfilled_fields": dict(backfilled_fields),
        "remaining_gap_reasons": [str(item) for item in remaining_gap_reasons if str(item or "")],
        "backfill_source_ref": backfill_source_ref,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload["backfill_record_id"] = f"BF-{_fingerprint(payload)[:16]}"
    return payload


def _download_snapshot_index(download_manifest: Mapping[str, Any], human_file_map: Any) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in _list(download_manifest.get("project_sample_items")):
        if not isinstance(item, Mapping):
            continue
        project_id = str(item.get("project_id") or "")
        flow_no = str(item.get("guangzhou_flow_no") or item.get("flow_no") or "")
        for ref in [*_list(item.get("detail_snapshot_refs")), *_list(item.get("attachment_snapshot_refs"))]:
            if not isinstance(ref, Mapping):
                continue
            source_url = str(ref.get("source_url") or ref.get("attachment_url") or "")
            if project_id and source_url:
                index[(project_id, flow_no, source_url)] = dict(ref)
    records = human_file_map if isinstance(human_file_map, list) else _list((human_file_map or {}).get("items"))
    for record in records:
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "")
        flow_no = str(record.get("flow_no") or "")
        for url_key in ("source_url", "attachment_url"):
            source_url = str(record.get(url_key) or "")
            if project_id and source_url:
                index.setdefault((project_id, flow_no, source_url), dict(record))
    return index


def _gdcic_task_index(gdcic_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("query_task_id") or ""): dict(item)
        for item in _list(gdcic_manifest.get("query_task_records"))
        if isinstance(item, Mapping) and str(item.get("query_task_id") or "")
    }


def _stage4_record_index(stage4_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for item in _list(stage4_manifest.get("items")):
        if not isinstance(item, Mapping):
            continue
        for key in ("company_personnel_source_snapshot_id", "personnel_project_source_snapshot_id"):
            snapshot_id = str(item.get(key) or "")
            if snapshot_id:
                out[snapshot_id] = dict(item)
    return out


def _recapture_record_index(recapture_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("source_fixation_id") or ""): dict(item)
        for item in _list(recapture_manifest.get("recapture_records"))
        if isinstance(item, Mapping) and str(item.get("source_fixation_id") or "")
    }


def _summary(*, backfill_records: list[Mapping[str, Any]], blocking_reasons: list[str]) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    remaining_gap_counts: dict[str, int] = {}
    for row in backfill_records:
        state_counts[str(row.get("backfill_state") or "")] = state_counts.get(str(row.get("backfill_state") or ""), 0) + 1
        class_counts[str(row.get("backfill_classification") or "")] = class_counts.get(str(row.get("backfill_classification") or ""), 0) + 1
        family_counts[str(row.get("source_family") or "")] = family_counts.get(str(row.get("source_family") or ""), 0) + 1
        for reason in _list(row.get("remaining_gap_reasons")):
            remaining_gap_counts[str(reason)] = remaining_gap_counts.get(str(reason), 0) + 1
    backfilled = sum(
        1
        for row in backfill_records
        if str(row.get("backfill_state") or "")
        in {
            "BACKFILLED_FROM_DOWNLOAD_DETAIL_SNAPSHOT",
            "BACKFILLED_FROM_GDCIC_QUERY_TASK",
            "BACKFILLED_FROM_RECAPTURED_DETAIL_SNAPSHOT",
            "BACKFILLED_FROM_RECAPTURED_STAGE4_READBACK",
        }
    )
    classified = sum(1 for row in backfill_records if str(row.get("backfill_state") or "") == "RECORD_HASH_BACKFILLED_CONTENT_HASH_NOT_AVAILABLE")
    unfixable = sum(1 for row in backfill_records if str(row.get("backfill_state") or "") == "UNFIXABLE_WITH_CURRENT_ARTIFACTS")
    return {
        "backfill_state": "P8_FIXATION_BACKFILL_READY" if not blocking_reasons else "P8_FIXATION_BACKFILL_INPUT_BLOCKED",
        "source_gap_record_count": len(backfill_records),
        "backfilled_record_count": backfilled,
        "classified_record_hash_only_count": classified,
        "unfixable_with_current_artifacts_count": unfixable,
        "backfill_state_counts": state_counts,
        "backfill_classification_counts": class_counts,
        "source_family_counts": family_counts,
        "remaining_gap_reason_counts": remaining_gap_counts,
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


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


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangzhou evidence fixation backfill v1.")
    parser.add_argument("--internal-evidence-package-root", default=str(DEFAULT_INTERNAL_EVIDENCE_PACKAGE_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--flow-root", default=str(DEFAULT_FLOW_ROOT))
    parser.add_argument("--gdcic-query-probe-root", default=str(DEFAULT_GDCIC_QUERY_PROBE_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--recapture-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--gdcic-query-optional", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = build_guangzhou_evidence_fixation_backfill(
        internal_evidence_package_root=args.internal_evidence_package_root,
        download_root=args.download_root,
        flow_root=args.flow_root,
        gdcic_query_probe_root=args.gdcic_query_probe_root,
        stage4_execution_root=args.stage4_execution_root,
        recapture_root=args.recapture_root or None,
        output_root=args.output_root,
        gdcic_query_required=not args.gdcic_query_optional,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
