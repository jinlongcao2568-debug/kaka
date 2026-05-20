from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from shared.utils import utc_now_iso
from stage2_ingestion.real_public_url_fetcher import (
    _decode_html,
    _discover_same_site_attachment_link_items,
    _discover_same_site_link_items,
)
from stage2_ingestion.scrapling_snapshot_parser import (
    build_scrapling_snapshot_parser_summary,
    parse_snapshot_html_with_scrapling,
)
from stage3_parsing.real_parser import Stage3RealParser


STAGE2_SNAPSHOT_PARSER_COMPARISON_KIND = "stage2_snapshot_parser_comparison_v1"
STAGE2_SNAPSHOT_PARSER_COMPARISON_VERSION = "1.0"
DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/stage1-5-limit3-p13b-live-new-strategy-v1")
DEFAULT_OUTPUT_DIR = Path("tmp/evaluation-real-samples/stage2-snapshot-parser-comparison-v1")
_GENERIC_BASELINE_ANNOUNCEMENT_TITLES = {
    "广州交易集团有限公司",
    "全国公共资源交易平台",
    "全国公共资源交易平台（广东省）",
}
_DATE_VALUE_RE = re.compile(r"\d{4}\s*(?:-|/|年)\s*\d{1,2}\s*(?:-|/|月)\s*\d{1,2}\s*(?:日)?")


def build_stage2_snapshot_parser_comparison(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    max_snapshots: int = 200,
    project_ids: Iterable[str] = (),
) -> dict[str, Any]:
    root = Path(input_root)
    out = Path(output_dir)
    selected_project_ids = {str(item).strip() for item in project_ids if str(item).strip()}
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_snapshot_keys: set[str] = set()

    for storage_path in _storage_json_paths(root):
        for manifest in _snapshot_manifests(storage_path):
            if len(records) >= max_snapshots:
                break
            if not _is_html_snapshot(manifest):
                continue
            project_id = str(dict(manifest.get("lineage_refs") or {}).get("project_id") or "")
            if selected_project_ids and project_id not in selected_project_ids:
                continue
            snapshot_id = str(manifest.get("snapshot_id") or "")
            object_key = str(manifest.get("object_key") or "")
            seen_key = str(manifest.get("sha256") or snapshot_id or object_key)
            if seen_key in seen_snapshot_keys:
                continue
            seen_snapshot_keys.add(seen_key)
            object_path = _resolve_object_path(storage_path=storage_path, object_key=object_key)
            if object_path is None:
                errors.append(
                    {
                        "storage_json_path": str(storage_path),
                        "snapshot_id": snapshot_id,
                        "object_key": object_key,
                        "state": "OBJECT_NOT_FOUND",
                    }
                )
                continue
            try:
                data = object_path.read_bytes()
                records.append(
                    _compare_snapshot(
                        manifest=manifest,
                        storage_path=storage_path,
                        object_path=object_path,
                        data=data,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive for historical snapshots
                errors.append(
                    {
                        "storage_json_path": str(storage_path),
                        "snapshot_id": snapshot_id,
                        "object_key": object_key,
                        "state": "COMPARE_FAILED",
                        "error_class": type(exc).__name__,
                        "error_detail": str(exc)[:500],
                    }
                )
        if len(records) >= max_snapshots:
            break

    manifest = _build_manifest(
        input_root=root,
        output_dir=out,
        records=records,
        errors=errors,
        max_snapshots=max_snapshots,
        project_ids=sorted(selected_project_ids),
    )
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "stage2-snapshot-parser-comparison-v1.json"
    md_path = out / "stage2-snapshot-parser-comparison-v1.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(manifest), encoding="utf-8")
    return {
        "manifest": manifest,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }


def _compare_snapshot(
    *,
    manifest: Mapping[str, Any],
    storage_path: Path,
    object_path: Path,
    data: bytes,
) -> dict[str, Any]:
    text = _decode_html(data)
    base_url = str(manifest.get("source_url_optional") or "")
    parsed_url = urlsplit(base_url)
    host = parsed_url.netloc.lower()
    legacy_detail_items = _discover_same_site_link_items(text, base_url=base_url, host=host) if host else []
    legacy_attachment_items = (
        _discover_same_site_attachment_link_items(text, base_url=base_url, host=host) if host else []
    )
    parser_readback = parse_snapshot_html_with_scrapling(
        text,
        base_url=base_url,
        keywords=[
            dict(manifest.get("lineage_refs") or {}).get("project_id"),
            manifest.get("source_family_optional"),
            base_url,
        ],
    )
    parser_summary = build_scrapling_snapshot_parser_summary(parser_readback)
    parser_field_records = [
        dict(item)
        for item in list(parser_readback.get("field_candidate_records") or [])
        if isinstance(item, Mapping)
    ]
    parser_table_records = [
        dict(item)
        for item in list(parser_readback.get("table_records") or [])
        if isinstance(item, Mapping)
    ]
    table_extraction_summary = dict(parser_readback.get("table_extraction_summary") or {})
    stage3_html_baseline = _stage3_html_baseline_fields(
        manifest=manifest,
        data=data,
    )

    legacy_attachment_urls = _urls(legacy_attachment_items)
    parser_attachment_urls = _urls(parser_readback.get("attachment_link_records") or [])
    legacy_detail_urls = _urls(legacy_detail_items)
    parser_same_site_urls = _urls(parser_readback.get("same_site_link_records") or [])
    attachment_intersection = sorted(set(legacy_attachment_urls) & set(parser_attachment_urls))
    same_site_intersection = sorted(set(legacy_detail_urls) & set(parser_same_site_urls))
    parser_extra_attachments = sorted(set(parser_attachment_urls) - set(legacy_attachment_urls))
    legacy_extra_attachments = sorted(set(legacy_attachment_urls) - set(parser_attachment_urls))
    legacy_extra_strict_attachments = [
        url for url in legacy_extra_attachments if _strict_attachment_signal(url, _text_for_url(legacy_attachment_items, url))
    ]
    legacy_extra_navigation_candidates = [
        url for url in legacy_extra_attachments if url not in set(legacy_extra_strict_attachments)
    ]
    quality_flags = _quality_flags(
        parser_summary=parser_summary,
        parser_extra_attachments=parser_extra_attachments,
        legacy_extra_strict_attachments=legacy_extra_strict_attachments,
        legacy_extra_navigation_candidates=legacy_extra_navigation_candidates,
        parser_attachment_urls=parser_attachment_urls,
        legacy_attachment_urls=legacy_attachment_urls,
    )
    field_signal_quality_flags = _field_signal_quality_flags(
        parser_summary=parser_summary,
        parser_field_records=parser_field_records,
        stage3_html_baseline=stage3_html_baseline,
    )
    quality_flags = list(dict.fromkeys([*quality_flags, *field_signal_quality_flags]))
    lineage_refs = dict(manifest.get("lineage_refs") or {})
    return {
        "snapshot_id": str(manifest.get("snapshot_id") or ""),
        "snapshot_kind": str(manifest.get("snapshot_kind") or ""),
        "project_id": str(lineage_refs.get("project_id") or ""),
        "flow_no": str(lineage_refs.get("flow_no") or ""),
        "purpose": str(lineage_refs.get("purpose") or ""),
        "source_url": base_url,
        "source_family": str(manifest.get("source_family_optional") or ""),
        "content_type": str(manifest.get("content_type") or ""),
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "storage_json_path": str(storage_path),
        "object_path": str(object_path),
        "object_key": str(manifest.get("object_key") or ""),
        "parser_summary": parser_summary,
        "parser_field_candidate_count": len(parser_field_records),
        "parser_field_candidate_field_counts": _field_name_counts(parser_field_records),
        "parser_field_candidate_records": parser_field_records[:30],
        "parser_table_count": int(table_extraction_summary.get("table_count") or 0),
        "parser_table_row_total": int(table_extraction_summary.get("table_row_total") or 0),
        "parser_table_label_value_pair_count": int(table_extraction_summary.get("label_value_pair_count") or 0),
        "parser_table_candidate_row_signal_count": int(table_extraction_summary.get("candidate_row_signal_count") or 0),
        "parser_table_kind_counts": dict(table_extraction_summary.get("table_kind_counts") or {}),
        "parser_table_records": parser_table_records[:20],
        "stage3_html_baseline": stage3_html_baseline,
        "stage3_html_field_count": len(list(stage3_html_baseline.get("field_records") or [])),
        "stage3_html_field_names": list(stage3_html_baseline.get("field_names") or []),
        "field_name_intersection": _field_name_intersection(parser_field_records, stage3_html_baseline),
        "stage3_field_names_missing_from_parser": _stage3_field_names_missing_from_parser(
            parser_field_records,
            stage3_html_baseline,
        ),
        "parser_extra_field_signal_names": _parser_extra_field_signal_names(
            parser_field_records,
            stage3_html_baseline,
        ),
        "legacy_same_site_link_count": len(legacy_detail_urls),
        "parser_same_site_link_count": len(parser_same_site_urls),
        "same_site_link_intersection_count": len(same_site_intersection),
        "parser_extra_same_site_link_count": len(set(parser_same_site_urls) - set(legacy_detail_urls)),
        "legacy_extra_same_site_link_count": len(set(legacy_detail_urls) - set(parser_same_site_urls)),
        "legacy_attachment_count": len(legacy_attachment_urls),
        "parser_attachment_count": len(parser_attachment_urls),
        "attachment_intersection_count": len(attachment_intersection),
        "parser_extra_attachment_count": len(parser_extra_attachments),
        "legacy_extra_attachment_count": len(legacy_extra_attachments),
        "legacy_extra_strict_attachment_count": len(legacy_extra_strict_attachments),
        "legacy_extra_navigation_candidate_count": len(legacy_extra_navigation_candidates),
        "parser_extra_attachment_urls": parser_extra_attachments[:20],
        "legacy_extra_attachment_urls": legacy_extra_attachments[:20],
        "legacy_extra_strict_attachment_urls": legacy_extra_strict_attachments[:20],
        "legacy_extra_navigation_candidate_urls": legacy_extra_navigation_candidates[:20],
        "parser_attachment_records": _records_for_urls(
            parser_readback.get("attachment_link_records") or [],
            parser_extra_attachments,
        )[:20],
        "legacy_attachment_records": _records_for_urls(
            legacy_attachment_items,
            legacy_extra_attachments,
        )[:20],
        "legacy_extra_strict_attachment_records": _records_for_urls(
            legacy_attachment_items,
            legacy_extra_strict_attachments,
        )[:20],
        "legacy_extra_navigation_candidate_records": _records_for_urls(
            legacy_attachment_items,
            legacy_extra_navigation_candidates,
        )[:20],
        "quality_flags": quality_flags,
        "no_live_request": bool(parser_readback.get("no_live_request")),
        "customer_visible_allowed": bool(parser_readback.get("customer_visible_allowed")),
        "no_legal_conclusion": bool(parser_readback.get("no_legal_conclusion")),
    }


def _build_manifest(
    *,
    input_root: Path,
    output_dir: Path,
    records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    max_snapshots: int,
    project_ids: list[str],
) -> dict[str, Any]:
    backend_counts = Counter(str((row.get("parser_summary") or {}).get("parser_backend") or "") for row in records)
    flag_counts: Counter[str] = Counter()
    for row in records:
        flag_counts.update(str(item) for item in list(row.get("quality_flags") or []))
    summary = {
        "input_root": str(input_root),
        "output_dir": str(output_dir),
        "max_snapshots": max_snapshots,
        "project_ids": project_ids,
        "compared_snapshot_count": len(records),
        "error_count": len(errors),
        "parser_backend_counts": dict(sorted(backend_counts.items())),
        "no_live_request_all_true": all(bool(row.get("no_live_request")) for row in records) if records else False,
        "customer_visible_allowed_any_true": any(bool(row.get("customer_visible_allowed")) for row in records),
        "no_legal_conclusion_all_true": all(bool(row.get("no_legal_conclusion")) for row in records) if records else False,
        "legacy_attachment_total": sum(int(row.get("legacy_attachment_count") or 0) for row in records),
        "parser_attachment_total": sum(int(row.get("parser_attachment_count") or 0) for row in records),
        "parser_extra_attachment_total": sum(int(row.get("parser_extra_attachment_count") or 0) for row in records),
        "legacy_extra_attachment_total": sum(int(row.get("legacy_extra_attachment_count") or 0) for row in records),
        "legacy_extra_strict_attachment_total": sum(int(row.get("legacy_extra_strict_attachment_count") or 0) for row in records),
        "legacy_extra_navigation_candidate_total": sum(int(row.get("legacy_extra_navigation_candidate_count") or 0) for row in records),
        "parser_field_candidate_total": sum(int(row.get("parser_field_candidate_count") or 0) for row in records),
        "parser_table_total": sum(int(row.get("parser_table_count") or 0) for row in records),
        "parser_table_row_total": sum(int(row.get("parser_table_row_total") or 0) for row in records),
        "parser_table_label_value_pair_total": sum(
            int(row.get("parser_table_label_value_pair_count") or 0) for row in records
        ),
        "parser_table_candidate_row_signal_total": sum(
            int(row.get("parser_table_candidate_row_signal_count") or 0) for row in records
        ),
        "stage3_html_field_total": sum(int(row.get("stage3_html_field_count") or 0) for row in records),
        "stage3_field_name_missing_from_parser_total": sum(
            len(list(row.get("stage3_field_names_missing_from_parser") or [])) for row in records
        ),
        "parser_extra_field_signal_name_total": sum(
            len(list(row.get("parser_extra_field_signal_names") or [])) for row in records
        ),
        "field_signal_snapshot_count": sum(
            1 for row in records if int(row.get("parser_field_candidate_count") or 0) > 0
        ),
        "table_signal_snapshot_count": sum(
            1 for row in records if int(row.get("parser_table_count") or 0) > 0
        ),
        "stage3_html_field_snapshot_count": sum(
            1 for row in records if int(row.get("stage3_html_field_count") or 0) > 0
        ),
        "parser_extra_attachment_snapshot_count": sum(
            1 for row in records if int(row.get("parser_extra_attachment_count") or 0) > 0
        ),
        "legacy_extra_attachment_snapshot_count": sum(
            1 for row in records if int(row.get("legacy_extra_attachment_count") or 0) > 0
        ),
        "legacy_extra_strict_attachment_snapshot_count": sum(
            1 for row in records if int(row.get("legacy_extra_strict_attachment_count") or 0) > 0
        ),
        "legacy_extra_navigation_candidate_snapshot_count": sum(
            1 for row in records if int(row.get("legacy_extra_navigation_candidate_count") or 0) > 0
        ),
        "quality_flag_counts": dict(sorted(flag_counts.items())),
        "comparison_state": "READY" if records else "NO_HTML_SNAPSHOTS_FOUND",
    }
    manifest = {
        "manifest_version": STAGE2_SNAPSHOT_PARSER_COMPARISON_VERSION,
        "manifest_kind": STAGE2_SNAPSHOT_PARSER_COMPARISON_KIND,
        "manifest_id": "STAGE2-SNAPSHOT-PARSER-COMPARISON-" + _fingerprint({"summary": summary, "records": records})[:16],
        "generated_at": utc_now_iso(),
        "summary": summary,
        "comparison_records": records,
        "error_records": errors,
        "safety_contract": {
            "parser_only": True,
            "no_live_request": True,
            "does_not_replace_snapshot_hash_readback": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "parser_extra_candidates_require_review": True,
        },
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    return manifest


def _markdown_report(manifest: Mapping[str, Any]) -> str:
    summary = dict(manifest.get("summary") or {})
    lines = [
        "# Stage2 Snapshot Parser Comparison v1",
        "",
        "## Summary",
        "",
        f"- compared_snapshot_count: {summary.get('compared_snapshot_count')}",
        f"- parser_backend_counts: {json.dumps(summary.get('parser_backend_counts') or {}, ensure_ascii=False)}",
        f"- legacy_attachment_total: {summary.get('legacy_attachment_total')}",
        f"- parser_attachment_total: {summary.get('parser_attachment_total')}",
        f"- parser_extra_attachment_total: {summary.get('parser_extra_attachment_total')}",
        f"- legacy_extra_attachment_total: {summary.get('legacy_extra_attachment_total')}",
        f"- legacy_extra_strict_attachment_total: {summary.get('legacy_extra_strict_attachment_total')}",
        f"- legacy_extra_navigation_candidate_total: {summary.get('legacy_extra_navigation_candidate_total')}",
        f"- parser_field_candidate_total: {summary.get('parser_field_candidate_total')}",
        f"- parser_table_total: {summary.get('parser_table_total')}",
        f"- parser_table_label_value_pair_total: {summary.get('parser_table_label_value_pair_total')}",
        f"- parser_table_candidate_row_signal_total: {summary.get('parser_table_candidate_row_signal_total')}",
        f"- stage3_html_field_total: {summary.get('stage3_html_field_total')}",
        f"- stage3_field_name_missing_from_parser_total: {summary.get('stage3_field_name_missing_from_parser_total')}",
        f"- no_live_request_all_true: {summary.get('no_live_request_all_true')}",
        "",
        "## Records",
        "",
        "| snapshot | project | legacy att | parser att | parser fields | tables | candidate rows | stage3 missing | flags |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in list(manifest.get("comparison_records") or []):
        lines.append(
            "| {snapshot} | {project} | {legacy} | {parser} | {pfields} | {tables} | {crows} | {missing} | {flags} |".format(
                snapshot=_md(str(row.get("snapshot_id") or "")),
                project=_md(str(row.get("project_id") or "")),
                legacy=int(row.get("legacy_attachment_count") or 0),
                parser=int(row.get("parser_attachment_count") or 0),
                pfields=int(row.get("parser_field_candidate_count") or 0),
                tables=int(row.get("parser_table_count") or 0),
                crows=int(row.get("parser_table_candidate_row_signal_count") or 0),
                missing=_md(",".join(str(item) for item in list(row.get("stage3_field_names_missing_from_parser") or []))),
                flags=_md(",".join(str(item) for item in list(row.get("quality_flags") or []))),
            )
        )
    return "\n".join(lines) + "\n"


def _storage_json_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() == ".json" else []
    if not root.exists():
        return []
    paths: list[Path] = []
    for path in root.rglob("*.json"):
        name = path.name.lower()
        if name == "storage.json" or name.endswith("-storage.json") or "storage" in name:
            paths.append(path)
    return sorted(paths, key=lambda item: str(item))


def _snapshot_manifests(storage_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(storage_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    table = ((payload.get("tables") or {}).get("evidence_snapshot_manifest") or {}) if isinstance(payload, Mapping) else {}
    manifests: list[dict[str, Any]] = []
    for record in table.values():
        if not isinstance(record, Mapping):
            continue
        manifest = record.get("payload")
        if isinstance(manifest, Mapping):
            manifests.append(dict(manifest))
    return manifests


def _is_html_snapshot(manifest: Mapping[str, Any]) -> bool:
    content_type = str(manifest.get("content_type") or "").lower()
    snapshot_kind = str(manifest.get("snapshot_kind") or "").lower()
    return "html" in content_type or snapshot_kind in {
        "real_public_detail_html_snapshot",
        "real_public_entry_html_snapshot",
        "public_source_html_snapshot",
    }


def _stage3_html_baseline_fields(*, manifest: Mapping[str, Any], data: bytes) -> dict[str, Any]:
    snapshot_id = str(manifest.get("snapshot_id") or "")
    content_type = str(manifest.get("content_type") or "text/html; charset=utf-8")
    sha256 = hashlib.sha256(data).hexdigest()
    try:
        carrier = Stage3RealParser().parse_readback(
            {
                "bytes": data,
                "content_type": content_type,
                "sha256": sha256,
                "manifest": dict(manifest),
                "replayable": True,
            }
        )
    except Exception as exc:  # pragma: no cover - comparison utility must not block attachment readiness
        return {
            "snapshot_id": snapshot_id,
            "parse_state": "STAGE3_BASELINE_FAILED",
            "field_records": [],
            "field_names": [],
            "error_class": type(exc).__name__,
            "error_detail": str(exc)[:500],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    field_records = [
        {
            "field_name": str(field.get("field_name") or ""),
            "field_value_optional": str(field.get("field_value_optional") or ""),
            "confidence": field.get("confidence"),
            "review_required": bool(field.get("review_required")),
            "source_slice": str(field.get("source_slice") or "")[:300],
            "locator": dict(field.get("locator") or {}),
        }
        for field in list(carrier.get("parsed_fields") or [])
        if isinstance(field, Mapping) and str(field.get("field_name") or "")
    ]
    return {
        "snapshot_id": snapshot_id,
        "parse_state": str(carrier.get("parse_state") or ""),
        "attachment_type": str(carrier.get("attachment_type") or ""),
        "field_records": field_records[:50],
        "field_names": sorted({record["field_name"] for record in field_records}),
        "parse_error_taxonomy": list(carrier.get("parse_error_taxonomy") or []),
        "review_required": bool(carrier.get("review_required")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _field_name_counts(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        field_name = str(record.get("field_name") or "")
        if field_name:
            counts[field_name] += 1
    return dict(sorted(counts.items()))


def _field_name_set(records: Iterable[Mapping[str, Any]]) -> set[str]:
    return {str(record.get("field_name") or "") for record in records if str(record.get("field_name") or "")}


def _stage3_field_name_set(stage3_html_baseline: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    field_records = list(stage3_html_baseline.get("field_records") or [])
    for record in field_records:
        if not isinstance(record, Mapping):
            continue
        field_name = str(record.get("field_name") or "")
        value = str(record.get("field_value_optional") or "").strip()
        if not _meaningful_stage3_baseline_field(field_name, value):
            continue
        if field_name == "announcement_title" and value in _GENERIC_BASELINE_ANNOUNCEMENT_TITLES:
            continue
        if field_name:
            names.add(field_name)
    if names or field_records:
        return names
    return {str(item) for item in list(stage3_html_baseline.get("field_names") or []) if str(item)}


def _meaningful_stage3_baseline_field(field_name: str, value: str) -> bool:
    if not value:
        return False
    if "{{" in value or "}}" in value:
        return False
    if field_name == "announcement_date" and not _DATE_VALUE_RE.search(value):
        return False
    return True


def _field_name_intersection(
    parser_field_records: Iterable[Mapping[str, Any]],
    stage3_html_baseline: Mapping[str, Any],
) -> list[str]:
    return sorted(_field_name_set(parser_field_records) & _stage3_field_name_set(stage3_html_baseline))


def _stage3_field_names_missing_from_parser(
    parser_field_records: Iterable[Mapping[str, Any]],
    stage3_html_baseline: Mapping[str, Any],
) -> list[str]:
    return sorted(_stage3_field_name_set(stage3_html_baseline) - _field_name_set(parser_field_records))


def _parser_extra_field_signal_names(
    parser_field_records: Iterable[Mapping[str, Any]],
    stage3_html_baseline: Mapping[str, Any],
) -> list[str]:
    return sorted(_field_name_set(parser_field_records) - _stage3_field_name_set(stage3_html_baseline))


def _field_signal_quality_flags(
    *,
    parser_summary: Mapping[str, Any],
    parser_field_records: list[Mapping[str, Any]],
    stage3_html_baseline: Mapping[str, Any],
) -> list[str]:
    flags: list[str] = []
    field_signal_summary = dict(parser_summary.get("field_signal_summary") or {})
    if parser_field_records:
        flags.append("FIELD_SIGNAL_CANDIDATES_FOUND")
    else:
        flags.append("NO_FIELD_SIGNAL_CANDIDATES")
    stage3_missing = _stage3_field_names_missing_from_parser(parser_field_records, stage3_html_baseline)
    stage3_fields = _stage3_field_name_set(stage3_html_baseline)
    if stage3_fields and not stage3_missing:
        flags.append("PARSER_FIELD_SIGNALS_COVER_STAGE3_FIELD_NAMES")
    elif stage3_missing:
        flags.append("STAGE3_FIELD_NAMES_NOT_COVERED_BY_PARSER_REQUIRE_REVIEW")
    if field_signal_summary.get("notice_stage_signal") in {"candidate_notice", "award_result", "tender_notice"}:
        flags.append("NOTICE_STAGE_SIGNAL_FOUND")
    if int(field_signal_summary.get("responsible_person_signal_count") or 0) > 0:
        flags.append("RESPONSIBLE_PERSON_SIGNAL_FOUND")
    if int(field_signal_summary.get("time_window_signal_count") or 0) > 0:
        flags.append("TIME_WINDOW_SIGNAL_FOUND")
    table_summary = dict(parser_summary.get("table_extraction_summary") or {})
    if int(table_summary.get("table_count") or 0) > 0:
        flags.append("TABLE_STRUCTURE_SIGNALS_FOUND")
    if int(table_summary.get("candidate_row_signal_count") or 0) > 0:
        flags.append("CANDIDATE_TABLE_ROW_SIGNALS_FOUND")
    return flags


def _resolve_object_path(*, storage_path: Path, object_key: str) -> Path | None:
    if not object_key:
        return None
    candidate_roots = [
        storage_path.parent / "objects",
        storage_path.parent,
        storage_path.parent.parent / "objects",
    ]
    for root in candidate_roots:
        candidate = root / Path(object_key.replace("\\", "/"))
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _urls(items: Iterable[Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _records_for_urls(items: Iterable[Any], urls: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(urls)
    records: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if url in wanted:
            records.append(dict(item))
    return records


def _text_for_url(items: Iterable[Any], url: str) -> str:
    for item in items:
        if isinstance(item, Mapping) and str(item.get("url") or "").strip() == url:
            return str(item.get("text") or "")
    return ""


def _strict_attachment_signal(url: str, link_text: str) -> bool:
    lowered = f"{url} {link_text}".lower()
    path = urlsplit(url).path.lower()
    return (
        path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"))
        or "downloadztbattach" in lowered
        or "/download" in lowered
        or "attachguid=" in lowered
        or "filecode=" in lowered
    )


def _quality_flags(
    *,
    parser_summary: Mapping[str, Any],
    parser_extra_attachments: list[str],
    legacy_extra_strict_attachments: list[str],
    legacy_extra_navigation_candidates: list[str],
    parser_attachment_urls: list[str],
    legacy_attachment_urls: list[str],
) -> list[str]:
    flags: list[str] = []
    if parser_summary.get("parser_backend") != "SCRAPLING_SELECTOR":
        flags.append("SCRAPLING_FALLBACK_USED")
    if parser_extra_attachments:
        flags.append("PARSER_EXTRA_ATTACHMENT_CANDIDATES_REQUIRE_REVIEW")
    if legacy_extra_strict_attachments:
        flags.append("LEGACY_STRICT_ATTACHMENT_MISSED_BY_PARSER_REQUIRE_REVIEW")
    if legacy_extra_navigation_candidates:
        flags.append("LEGACY_BROAD_NAVIGATION_CANDIDATES_NOT_COPIED")
    if not parser_attachment_urls and not legacy_attachment_urls:
        flags.append("NO_ATTACHMENT_CANDIDATES")
    if parser_attachment_urls == legacy_attachment_urls and parser_attachment_urls:
        flags.append("ATTACHMENT_CANDIDATES_STABLE")
    elif not parser_extra_attachments and not legacy_extra_strict_attachments and parser_attachment_urls:
        flags.append("STRICT_ATTACHMENT_CANDIDATES_STABLE")
    return flags


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")[:160]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare legacy Stage2 HTML link parsing with Scrapling parser-only readback.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-snapshots", type=int, default=200)
    parser.add_argument("--project-id", action="append", default=[])
    args = parser.parse_args(argv)
    result = build_stage2_snapshot_parser_comparison(
        input_root=args.input_root,
        output_dir=args.output_dir,
        max_snapshots=args.max_snapshots,
        project_ids=args.project_id,
    )
    print(json.dumps({"json_path": result["json_path"], "markdown_path": result["markdown_path"], "summary": result["manifest"]["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
