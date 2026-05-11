from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_DOWNLOAD_REPAIR_MANIFEST_KIND = "guangzhou_download_repair_merged_manifest"
GUANGZHOU_DOWNLOAD_REPAIR_SEGMENT_KIND = "guangzhou_download_repair_segment_manifest"
GUANGZHOU_DOWNLOAD_REPAIR_VERSION = 1
GUANGZHOU_DOWNLOAD_REPAIR_ADAPTER_ID = "guangzhou-download-repair-v2-runner"


def build_download_repair_segment_manifest(
    *,
    segment_root: str | Path,
    flow_no: str,
    output_json: str | Path | None = None,
    timeout_interrupted: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    root = Path(segment_root)
    payload, source_path, source_state = _load_segment_source(root)
    manifest = _source_manifest(payload)
    summary = dict(manifest.get("summary") or {})
    segment_state = _segment_state(source_state=source_state, timeout_interrupted=timeout_interrupted, summary=summary)
    result = {
        "manifest_version": GUANGZHOU_DOWNLOAD_REPAIR_VERSION,
        "manifest_kind": GUANGZHOU_DOWNLOAD_REPAIR_SEGMENT_KIND,
        "adapter_id": GUANGZHOU_DOWNLOAD_REPAIR_ADAPTER_ID,
        "pipeline_stage": "DownloadRepairSegment",
        "created_at": created,
        "flow_no": _flow_no(flow_no),
        "segment_root": str(root),
        "source_manifest_path": str(source_path) if source_path else "",
        "source_manifest_state": source_state,
        "segment_state": segment_state,
        "timeout_interrupted": bool(timeout_interrupted),
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    result["manifest_id"] = f"GUANGZHOU-DOWNLOAD-REPAIR-SEGMENT-{_fingerprint(result)[:16]}"
    out = Path(output_json) if output_json else root / "download-repair-segment-manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_download_repair_merged_manifest(
    *,
    output_root: str | Path,
    segment_roots: list[str | Path],
    output_json: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    segment_records: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    max_flowurl_project_count = 0
    for raw_root in segment_roots:
        root = Path(raw_root)
        segment, payload = _load_or_build_segment(root)
        segment_records.append(segment)
        manifest = _source_manifest(payload)
        summary = dict(manifest.get("summary") or {})
        max_flowurl_project_count = max(max_flowurl_project_count, _int(summary.get("flowurl_project_count")))
        items.extend([dict(item) for item in list(manifest.get("items") or []) if isinstance(item, Mapping)])
        samples.extend([dict(item) for item in list(manifest.get("project_sample_items") or []) if isinstance(item, Mapping)])
    summary = _merged_summary(
        flow_items=items,
        project_samples=samples,
        segment_records=segment_records,
        flowurl_project_count=max_flowurl_project_count,
    )
    manifest = {
        "manifest_version": GUANGZHOU_DOWNLOAD_REPAIR_VERSION,
        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
        "sub_kind": GUANGZHOU_DOWNLOAD_REPAIR_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_DOWNLOAD_REPAIR_ADAPTER_ID,
        "pipeline_stage": "DownloadProbe",
        "created_at": created,
        "execution_mode": "MERGED_SEGMENTS",
        "segment_records": segment_records,
        "items": items,
        "sample_items": items[:80],
        "project_sample_items": samples,
        "project_sample_preview_items": samples[:80],
        "storage_path_optional": str(out_root / "storage.json"),
        "object_storage_path_optional": str(out_root / "objects"),
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_id"] = f"GUANGZHOU-DOWNLOAD-REPAIR-MERGED-{_fingerprint({'summary': summary, 'segments': segment_records})[:16]}"
    result = {
        "guangzhou_download_repair_mode": "MERGED",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
    }
    target = Path(output_json) if output_json else out_root / "download-repair-merged-manifest.json"
    _merge_segment_replay_store(output_root=out_root, segment_roots=[Path(root) for root in segment_roots])
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # Compatibility alias for ParseProbe and existing readiness callers.
    (out_root / "download-probe-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _merge_segment_replay_store(*, output_root: Path, segment_roots: list[Path]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    merged_storage: dict[str, Any] = {
        "storage_version": 1,
        "tables": {},
        "stage_states": {},
        "work_items": {},
        "operator_actions": {},
        "worker_queue_items": {},
        "worker_queue_events": {},
    }
    for root in segment_roots:
        _merge_storage_json(merged_storage, root / "storage.json")
        _copy_object_store(root / "objects", output_root / "objects")
    (output_root / "storage.json").write_text(
        json.dumps(merged_storage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _merge_storage_json(merged_storage: dict[str, Any], source_path: Path) -> None:
    if not source_path.exists():
        return
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception:
        return
    for table_name, records in dict(source.get("tables") or {}).items():
        if not isinstance(records, Mapping):
            continue
        merged_table = merged_storage.setdefault("tables", {}).setdefault(str(table_name), {})
        for record_id, record in records.items():
            if isinstance(record, Mapping):
                merged_table[str(record_id)] = dict(record)
    for section in (
        "stage_states",
        "work_items",
        "operator_actions",
        "worker_queue_items",
        "worker_queue_events",
    ):
        records = source.get(section)
        if isinstance(records, Mapping):
            merged_section = merged_storage.setdefault(section, {})
            for record_id, record in records.items():
                if isinstance(record, Mapping):
                    merged_section[str(record_id)] = dict(record)


def _copy_object_store(source_root: Path, target_root: Path) -> None:
    if not source_root.exists():
        return
    for source_file in source_root.rglob("*"):
        if not source_file.is_file():
            continue
        relative = source_file.relative_to(source_root)
        target_file = target_root / relative
        if target_file.exists():
            continue
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


def _load_or_build_segment(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    segment_path = root / "download-repair-segment-manifest.json"
    if segment_path.exists():
        segment = _load_json(segment_path)
    else:
        segment = build_download_repair_segment_manifest(segment_root=root, flow_no=_flow_no_from_root(root))
    payload, _, _ = _load_segment_source(root)
    return segment, payload


def _load_segment_source(root: Path) -> tuple[dict[str, Any], Path | None, str]:
    final_path = root / "download-probe-manifest.json"
    partial_path = root / "download-probe-manifest.partial.json"
    if final_path.exists():
        return _load_json(final_path), final_path, "FINAL"
    if partial_path.exists():
        return _load_json(partial_path), partial_path, "PARTIAL"
    return {"manifest": {"items": [], "project_sample_items": [], "summary": {}}}, None, "MISSING"


def _segment_state(*, source_state: str, timeout_interrupted: bool, summary: Mapping[str, Any]) -> str:
    if timeout_interrupted:
        return "TIMEOUT_INTERRUPTED"
    if source_state == "MISSING":
        return "FAILED_FINAL"
    if source_state == "PARTIAL":
        return "PARTIAL"
    failures = dict(summary.get("failure_taxonomy_counts") or {})
    if failures:
        return "FAILED_RETRYABLE"
    return "CAPTURED"


def _merged_summary(
    *,
    flow_items: list[Mapping[str, Any]],
    project_samples: list[Mapping[str, Any]],
    segment_records: list[Mapping[str, Any]],
    flowurl_project_count: int,
) -> dict[str, Any]:
    download_attempted_count = sum(_int(item.get("download_attempted_count")) for item in flow_items)
    attachment_snapshot_count = sum(_int(item.get("attachment_snapshot_count")) for item in project_samples)
    unique_projects = {str(item.get("project_id") or "") for item in project_samples if item.get("project_id")}
    timeout_count = sum(1 for item in segment_records if item.get("segment_state") == "TIMEOUT_INTERRUPTED")
    partial_count = sum(1 for item in segment_records if item.get("segment_state") in {"PARTIAL", "TIMEOUT_INTERRUPTED"})
    return {
        "download_probe_state": "READY" if not timeout_count else "PARTIAL_REVIEW_REQUIRED",
        "flow_item_count": len(flow_items),
        "project_sample_count": len(project_samples),
        "unique_project_count": len(unique_projects),
        "flowurl_project_count": flowurl_project_count or len(unique_projects),
        "download_probe_project_count": len(unique_projects),
        "detail_snapshot_count": sum(_int(item.get("detail_snapshot_count")) for item in project_samples),
        "attachment_snapshot_count": attachment_snapshot_count,
        "listed_attachment_count": sum(_int(item.get("listed_attachment_count")) for item in flow_items),
        "download_attempted_count": download_attempted_count,
        "attachment_snapshot_success_rate": _rate(attachment_snapshot_count, download_attempted_count),
        "deferred_attachment_count": sum(_int(item.get("deferred_attachment_count")) for item in flow_items),
        "flow_no_counts": _counts(str(item.get("flow_no") or "") for item in flow_items),
        "failure_taxonomy_counts": _counts(
            reason
            for item in [*flow_items, *project_samples]
            for reason in list(item.get("failure_taxonomy") or [])
        ),
        "detail_transport_failure_matrix": _detail_transport_failure_matrix(project_samples),
        "segment_state_counts": _counts(str(item.get("segment_state") or "") for item in segment_records),
        "timeout_interrupted_count": timeout_count,
        "partial_segment_count": partial_count,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _detail_transport_failure_matrix(project_samples: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sample in project_samples:
        attempts = [
            dict(item)
            for item in list(sample.get("detail_transport_attempts") or [])
            if isinstance(item, Mapping)
        ]
        failures = [
            str(reason)
            for reason in list(sample.get("failure_taxonomy") or [])
            if str(reason or "").startswith("detail_")
            or str(reason or "").startswith("direct_fetch:")
            or str(reason or "") == "CONTROLLED_CHALLENGE_RESOLVER_ERROR"
        ]
        if not attempts and not failures:
            continue
        out.append(
            {
                "project_id": str(sample.get("project_id") or ""),
                "project_name": str(sample.get("project_name") or ""),
                "flow_no": str(sample.get("guangzhou_flow_no") or sample.get("flow_no") or ""),
                "source_url": str(sample.get("source_url") or ""),
                "target_execution_state": str(sample.get("target_execution_state") or ""),
                "failure_taxonomy": list(dict.fromkeys(failures)),
                "detail_transport_attempts": attempts,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return out


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get("manifest")
    return dict(nested if isinstance(nested, Mapping) else payload)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _flow_no(value: Any) -> str:
    text = str(value or "").strip()
    if text.isdigit() and len(text) == 1:
        return f"0{text}"
    return text


def _flow_no_from_root(root: Path) -> str:
    text = root.name.lower().replace("flow-", "")
    return _flow_no(text)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            out[text] = out.get(text, 0) + 1
    return dict(sorted(out.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou DownloadRepair v2 manifests.")
    parser.add_argument("--mode", choices={"segment", "merge"}, required=True)
    parser.add_argument("--segment-root")
    parser.add_argument("--flow-no", default="")
    parser.add_argument("--timeout-interrupted", action="store_true")
    parser.add_argument("--segment-roots", default="")
    parser.add_argument("--output-root")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.mode == "segment":
        result = build_download_repair_segment_manifest(
            segment_root=args.segment_root,
            flow_no=args.flow_no,
            output_json=args.output_json,
            timeout_interrupted=args.timeout_interrupted,
        )
    else:
        roots = [item.strip() for item in str(args.segment_roots or "").split(",") if item.strip()]
        result = build_download_repair_merged_manifest(
            output_root=args.output_root,
            segment_roots=roots,
            output_json=args.output_json,
        )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"guangzhou download repair {args.mode} built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
