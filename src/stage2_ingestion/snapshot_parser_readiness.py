from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage2_ingestion.snapshot_parser_comparison import build_stage2_snapshot_parser_comparison


STAGE2_SNAPSHOT_PARSER_READINESS_KIND = "stage2_snapshot_parser_readiness_v1"
STAGE2_SNAPSHOT_PARSER_READINESS_VERSION = "1.0"
DEFAULT_INPUT_PARENT = Path("tmp/evaluation-real-samples")
DEFAULT_OUTPUT_DIR = Path("tmp/evaluation-real-samples/stage2-snapshot-parser-readiness-v1")
DEFAULT_ROOT_PATTERN = "stage1-5-limit3-*"


def build_stage2_snapshot_parser_readiness(
    *,
    input_parent: str | Path = DEFAULT_INPUT_PARENT,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    root_pattern: str = DEFAULT_ROOT_PATTERN,
    max_snapshots_per_root: int = 200,
    include_empty_roots: bool = True,
) -> dict[str, Any]:
    parent = Path(input_parent)
    out = Path(output_dir)
    root_records: list[dict[str, Any]] = []
    for root in _discover_input_roots(parent, root_pattern=root_pattern):
        comparison = build_stage2_snapshot_parser_comparison(
            input_root=root,
            output_dir=out / "per-root" / root.name,
            max_snapshots=max_snapshots_per_root,
        )
        comparison_manifest = dict(comparison["manifest"])
        summary = dict(comparison_manifest.get("summary") or {})
        state = _readiness_state(summary)
        if not include_empty_roots and state == "NO_HTML_SNAPSHOTS_FOUND":
            continue
        root_records.append(
            {
                "input_root": str(root),
                "root_name": root.name,
                "readiness_state": state,
                "compared_snapshot_count": int(summary.get("compared_snapshot_count") or 0),
                "error_count": int(summary.get("error_count") or 0),
                "legacy_attachment_total": int(summary.get("legacy_attachment_total") or 0),
                "parser_attachment_total": int(summary.get("parser_attachment_total") or 0),
                "parser_extra_attachment_total": int(summary.get("parser_extra_attachment_total") or 0),
                "legacy_extra_attachment_total": int(summary.get("legacy_extra_attachment_total") or 0),
                "legacy_extra_strict_attachment_total": int(summary.get("legacy_extra_strict_attachment_total") or 0),
                "legacy_extra_navigation_candidate_total": int(summary.get("legacy_extra_navigation_candidate_total") or 0),
                "parser_field_candidate_total": int(summary.get("parser_field_candidate_total") or 0),
                "parser_table_total": int(summary.get("parser_table_total") or 0),
                "parser_table_row_total": int(summary.get("parser_table_row_total") or 0),
                "parser_table_label_value_pair_total": int(summary.get("parser_table_label_value_pair_total") or 0),
                "parser_table_candidate_row_signal_total": int(summary.get("parser_table_candidate_row_signal_total") or 0),
                "stage3_html_field_total": int(summary.get("stage3_html_field_total") or 0),
                "stage3_field_name_missing_from_parser_total": int(
                    summary.get("stage3_field_name_missing_from_parser_total") or 0
                ),
                "field_signal_snapshot_count": int(summary.get("field_signal_snapshot_count") or 0),
                "table_signal_snapshot_count": int(summary.get("table_signal_snapshot_count") or 0),
                "stage3_html_field_snapshot_count": int(summary.get("stage3_html_field_snapshot_count") or 0),
                "parser_backend_counts": dict(summary.get("parser_backend_counts") or {}),
                "quality_flag_counts": dict(summary.get("quality_flag_counts") or {}),
                "no_live_request_all_true": bool(summary.get("no_live_request_all_true")),
                "comparison_json_path": str(comparison["json_path"]),
                "comparison_markdown_path": str(comparison["markdown_path"]),
            }
        )

    manifest = _build_manifest(
        input_parent=parent,
        output_dir=out,
        root_pattern=root_pattern,
        max_snapshots_per_root=max_snapshots_per_root,
        root_records=root_records,
    )
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "stage2-snapshot-parser-readiness-v1.json"
    md_path = out / "stage2-snapshot-parser-readiness-v1.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(manifest), encoding="utf-8")
    return {
        "manifest": manifest,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }


def _discover_input_roots(parent: Path, *, root_pattern: str) -> list[Path]:
    if parent.is_file():
        return [parent]
    if not parent.exists():
        return []
    if (parent / "storage.json").exists():
        return [parent]
    return sorted([path for path in parent.iterdir() if path.is_dir() and path.match(root_pattern)], key=lambda item: item.name)


def _readiness_state(summary: Mapping[str, Any]) -> str:
    compared = int(summary.get("compared_snapshot_count") or 0)
    if compared <= 0:
        return "NO_HTML_SNAPSHOTS_FOUND"
    if int(summary.get("error_count") or 0) > 0:
        return "REVIEW_ERRORS"
    if not bool(summary.get("no_live_request_all_true")):
        return "REVIEW_LIVE_BOUNDARY"
    if int(summary.get("legacy_extra_strict_attachment_total") or 0) > 0:
        return "REVIEW_PARSER_MISSED_LEGACY_STRICT_ATTACHMENTS"
    if int(summary.get("parser_extra_attachment_total") or 0) > 0:
        return "REVIEW_PARSER_EXTRA_ATTACHMENT_CANDIDATES"
    if int(summary.get("legacy_extra_navigation_candidate_total") or 0) > 0:
        return "STABLE_FOR_REPLAY_WITH_LEGACY_NAVIGATION_DIFF"
    return "STABLE_FOR_REPLAY"


def _build_manifest(
    *,
    input_parent: Path,
    output_dir: Path,
    root_pattern: str,
    max_snapshots_per_root: int,
    root_records: list[dict[str, Any]],
) -> dict[str, Any]:
    state_counts = Counter(str(row.get("readiness_state") or "") for row in root_records)
    backend_counts: Counter[str] = Counter()
    for row in root_records:
        backend_counts.update({str(key): int(value) for key, value in dict(row.get("parser_backend_counts") or {}).items()})
    compared_roots = [row for row in root_records if int(row.get("compared_snapshot_count") or 0) > 0]
    stable_roots = [row for row in root_records if str(row.get("readiness_state") or "").startswith("STABLE_FOR_REPLAY")]
    review_roots = [row for row in root_records if str(row.get("readiness_state") or "").startswith("REVIEW_")]
    summary = {
        "input_parent": str(input_parent),
        "output_dir": str(output_dir),
        "root_pattern": root_pattern,
        "max_snapshots_per_root": max_snapshots_per_root,
        "root_count": len(root_records),
        "compared_root_count": len(compared_roots),
        "stable_root_count": len(stable_roots),
        "strict_stable_root_count": sum(1 for row in root_records if row.get("readiness_state") == "STABLE_FOR_REPLAY"),
        "stable_with_legacy_navigation_diff_root_count": sum(
            1 for row in root_records if row.get("readiness_state") == "STABLE_FOR_REPLAY_WITH_LEGACY_NAVIGATION_DIFF"
        ),
        "review_root_count": len(review_roots),
        "no_html_snapshot_root_count": sum(1 for row in root_records if row.get("readiness_state") == "NO_HTML_SNAPSHOTS_FOUND"),
        "compared_snapshot_total": sum(int(row.get("compared_snapshot_count") or 0) for row in root_records),
        "error_total": sum(int(row.get("error_count") or 0) for row in root_records),
        "legacy_attachment_total": sum(int(row.get("legacy_attachment_total") or 0) for row in root_records),
        "parser_attachment_total": sum(int(row.get("parser_attachment_total") or 0) for row in root_records),
        "parser_extra_attachment_total": sum(int(row.get("parser_extra_attachment_total") or 0) for row in root_records),
        "legacy_extra_attachment_total": sum(int(row.get("legacy_extra_attachment_total") or 0) for row in root_records),
        "legacy_extra_strict_attachment_total": sum(int(row.get("legacy_extra_strict_attachment_total") or 0) for row in root_records),
        "legacy_extra_navigation_candidate_total": sum(
            int(row.get("legacy_extra_navigation_candidate_total") or 0) for row in root_records
        ),
        "parser_field_candidate_total": sum(int(row.get("parser_field_candidate_total") or 0) for row in root_records),
        "parser_table_total": sum(int(row.get("parser_table_total") or 0) for row in root_records),
        "parser_table_row_total": sum(int(row.get("parser_table_row_total") or 0) for row in root_records),
        "parser_table_label_value_pair_total": sum(
            int(row.get("parser_table_label_value_pair_total") or 0) for row in root_records
        ),
        "parser_table_candidate_row_signal_total": sum(
            int(row.get("parser_table_candidate_row_signal_total") or 0) for row in root_records
        ),
        "stage3_html_field_total": sum(int(row.get("stage3_html_field_total") or 0) for row in root_records),
        "stage3_field_name_missing_from_parser_total": sum(
            int(row.get("stage3_field_name_missing_from_parser_total") or 0) for row in root_records
        ),
        "field_signal_snapshot_count": sum(int(row.get("field_signal_snapshot_count") or 0) for row in root_records),
        "table_signal_snapshot_count": sum(int(row.get("table_signal_snapshot_count") or 0) for row in root_records),
        "stage3_html_field_snapshot_count": sum(int(row.get("stage3_html_field_snapshot_count") or 0) for row in root_records),
        "readiness_state_counts": dict(sorted(state_counts.items())),
        "parser_backend_counts": dict(sorted(backend_counts.items())),
        "no_live_request_all_true": all(bool(row.get("no_live_request_all_true")) for row in compared_roots) if compared_roots else False,
        "readiness_state": "READY" if root_records else "NO_INPUT_ROOTS_FOUND",
    }
    manifest = {
        "manifest_version": STAGE2_SNAPSHOT_PARSER_READINESS_VERSION,
        "manifest_kind": STAGE2_SNAPSHOT_PARSER_READINESS_KIND,
        "manifest_id": "STAGE2-SNAPSHOT-PARSER-READINESS-" + _fingerprint({"summary": summary, "roots": root_records})[:16],
        "generated_at": utc_now_iso(),
        "summary": summary,
        "root_records": root_records,
        "review_root_records": review_roots,
        "safety_contract": {
            "parser_only": True,
            "no_live_request": True,
            "does_not_replace_snapshot_hash_readback": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "review_states_are_not_failures": True,
        },
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    return manifest


def _markdown_report(manifest: Mapping[str, Any]) -> str:
    summary = dict(manifest.get("summary") or {})
    lines = [
        "# Stage2 Snapshot Parser Readiness v1",
        "",
        "## Summary",
        "",
        f"- root_count: {summary.get('root_count')}",
        f"- compared_root_count: {summary.get('compared_root_count')}",
        f"- stable_root_count: {summary.get('stable_root_count')}",
        f"- strict_stable_root_count: {summary.get('strict_stable_root_count')}",
        f"- stable_with_legacy_navigation_diff_root_count: {summary.get('stable_with_legacy_navigation_diff_root_count')}",
        f"- review_root_count: {summary.get('review_root_count')}",
        f"- compared_snapshot_total: {summary.get('compared_snapshot_total')}",
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
        f"- readiness_state_counts: {json.dumps(summary.get('readiness_state_counts') or {}, ensure_ascii=False)}",
        "",
        "## Root Records",
        "",
        "| root | state | snapshots | legacy att | parser att | parser fields | tables | candidate rows | stage3 missing |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in list(manifest.get("root_records") or []):
        lines.append(
            "| {root} | {state} | {snapshots} | {legacy} | {parser} | {pfields} | {tables} | {crows} | {missing} |".format(
                root=_md(str(row.get("root_name") or "")),
                state=_md(str(row.get("readiness_state") or "")),
                snapshots=int(row.get("compared_snapshot_count") or 0),
                legacy=int(row.get("legacy_attachment_total") or 0),
                parser=int(row.get("parser_attachment_total") or 0),
                pfields=int(row.get("parser_field_candidate_total") or 0),
                tables=int(row.get("parser_table_total") or 0),
                crows=int(row.get("parser_table_candidate_row_signal_total") or 0),
                missing=int(row.get("stage3_field_name_missing_from_parser_total") or 0),
            )
        )
    return "\n".join(lines) + "\n"


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")[:180]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Stage2 Scrapling parser readiness across historical local snapshot runs.")
    parser.add_argument("--input-parent", default=str(DEFAULT_INPUT_PARENT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--root-pattern", default=DEFAULT_ROOT_PATTERN)
    parser.add_argument("--max-snapshots-per-root", type=int, default=200)
    parser.add_argument("--exclude-empty-roots", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage2_snapshot_parser_readiness(
        input_parent=args.input_parent,
        output_dir=args.output_dir,
        root_pattern=args.root_pattern,
        max_snapshots_per_root=args.max_snapshots_per_root,
        include_empty_roots=not args.exclude_empty_roots,
    )
    print(json.dumps({"json_path": result["json_path"], "markdown_path": result["markdown_path"], "summary": result["manifest"]["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
