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
        summaries.append(
            {
                "source_profile_id": GDCIC_SOURCE_PROFILE_ID,
                "source_name": "广东三库一平台公开源",
                "source_kind": "OFFICIAL_PUBLIC_SOURCE",
                "readback_ready_count": _int(gdcic_summary.get("gdcic_readback_ready_count")),
                "task_count": _int(gdcic_summary.get("gdcic_query_probe_task_count")),
                "probe_state_counts": dict(gdcic_summary.get("query_probe_state_counts") or {}),
                "blocker_taxonomy_counts": dict(gdcic_summary.get("gdcic_blocker_taxonomy_counts") or {}),
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
            "blocker_taxonomy_counts": dict(row.get("blocker_taxonomy_counts") or {}),
            "source_profile_ids": list(row.get("source_profile_ids") or []),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for row in project_records
    ]


def _source_closeout_state(readback_ready_count: int) -> str:
    return "OFFICIAL_SOURCE_READBACK_READY" if readback_ready_count > 0 else "OFFICIAL_SOURCE_REVIEW_REQUIRED"


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
