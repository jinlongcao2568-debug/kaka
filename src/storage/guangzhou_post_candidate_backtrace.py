from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.evaluation_corpus import default_evaluation_seed_path
from storage.evaluation_real_sample_execution import build_evaluation_real_sample_execution
from storage.evaluation_real_sample_plan import default_evaluation_real_project_sample_targets_path
from storage.professional_clean_project_archive import build_professional_clean_project_archive_manifest


GUANGZHOU_POST_CANDIDATE_BACKTRACE_MANIFEST_KIND = "guangzhou_post_candidate_backtrace_manifest"
GUANGZHOU_POST_CANDIDATE_BACKTRACE_VERSION = 1
GUANGZHOU_POST_CANDIDATE_BACKTRACE_ADAPTER_ID = "guangzhou-post-candidate-backtrace-v1-runner"

GUANGZHOU_PROFILE_ID = "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
ENTRY_TARGET_IDS = ("REAL-GD-CANDIDATE-001", "REAL-GD-AWARD-001")
CORE_BACKTRACE_DOCUMENT_KINDS = ("tender_file", "candidate_notice", "award_result")
BACKTRACE_STAGE_FILTERS = {
    "tender_file": ["工程建设", "招标公告", "含招标文件或附件", "BACKTRACE_STAGE:tender_file"],
    "candidate_notice": ["工程建设", "中标候选人公示", "BACKTRACE_STAGE:candidate_notice"],
    "award_result": ["工程建设", "中标结果公告", "BACKTRACE_STAGE:award_result"],
}


def build_guangzhou_post_candidate_backtrace(
    *,
    output_root: str | Path,
    targets_json: str | Path | None = None,
    seed_json: str | Path | None = None,
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    target_backend: str = "json-file",
    execute: bool = False,
    per_target_candidate_limit: int = 3,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    storage = Path(storage_path) if storage_path else root / "storage.json"
    object_storage = Path(object_storage_path) if object_storage_path else root / "objects"
    storage.parent.mkdir(parents=True, exist_ok=True)
    object_storage.mkdir(parents=True, exist_ok=True)
    seed_path = Path(seed_json) if seed_json else default_evaluation_seed_path()
    base_targets_path = Path(targets_json) if targets_json else default_evaluation_real_project_sample_targets_path()

    entry_result = build_evaluation_real_sample_execution(
        targets_json=base_targets_path,
        seed_json=seed_path,
        target_backend=target_backend,
        storage_path=storage,
        object_storage_path=object_storage,
        execute=execute,
        target_ids=list(ENTRY_TARGET_IDS),
        per_target_candidate_limit=max(1, per_target_candidate_limit),
        professional_source_only=True,
        created_at=created,
    )
    entry_manifest = _source_manifest(entry_result)
    entry_samples = _project_samples(entry_manifest)
    selected_entries = _select_post_candidate_entries(entry_samples, limit=per_target_candidate_limit)
    backtrace_targets = _backtrace_targets_for_entries(selected_entries)
    backtrace_targets_path = root / "backtrace-targets.json"
    backtrace_targets_path.write_text(
        json.dumps(backtrace_targets, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    backtrace_result: dict[str, Any] = {
        "real_sample_execution_mode": "SKIPPED",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": {
            "items": [],
            "project_sample_items": [],
            "summary": {},
        },
        "summary": {},
    }
    if backtrace_targets["targets"]:
        backtrace_result = build_evaluation_real_sample_execution(
            targets_json=backtrace_targets_path,
            seed_json=seed_path,
            target_backend=target_backend,
            storage_path=storage,
            object_storage_path=object_storage,
            execute=execute,
            target_ids=[str(item.get("target_id") or "") for item in backtrace_targets["targets"]],
            per_target_candidate_limit=1,
            professional_source_only=True,
            created_at=created,
        )
    backtrace_manifest = _source_manifest(backtrace_result)

    selected_project_keys = {_project_match_key(entry) for entry in selected_entries if _project_match_key(entry)}
    selected_entry_samples = [
        sample
        for sample in _project_samples(entry_manifest)
        if _project_match_key(sample) in selected_project_keys
    ]
    raw_project_samples = [
        *selected_entry_samples,
        *_project_samples(backtrace_manifest),
    ]
    items = [
        *_target_items(entry_manifest),
        *_target_items(backtrace_manifest),
    ]
    project_samples = _annotate_project_samples(raw_project_samples, target_items=items)
    summary = _summary(project_samples=project_samples, items=items, selected_entries=selected_entries)
    manifest = {
        "manifest_version": GUANGZHOU_POST_CANDIDATE_BACKTRACE_VERSION,
        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
        "sub_kind": GUANGZHOU_POST_CANDIDATE_BACKTRACE_MANIFEST_KIND,
        "adapter_id": GUANGZHOU_POST_CANDIDATE_BACKTRACE_ADAPTER_ID,
        "manifest_id": f"GUANGZHOU-POST-CANDIDATE-BACKTRACE-{_fingerprint({'samples': project_samples, 'items': items})[:16]}",
        "created_at": created,
        "execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "target_storage_backend": target_backend,
        "source_profile_id": GUANGZHOU_PROFILE_ID,
        "entry_target_ids": list(ENTRY_TARGET_IDS),
        "selected_post_candidate_entry_count": len(selected_entries),
        "backtrace_targets_json": str(backtrace_targets_path),
        "items": items,
        "sample_items": items[:80],
        "project_sample_items": project_samples,
        "project_sample_preview_items": project_samples[:80],
        "summary": summary,
        "coverage_quality_summary": {
            "coverage_quality_state": _coverage_state(project_samples),
            "failure_taxonomy_counts": _counts(
                reason
                for sample in project_samples
                for reason in list(sample.get("failure_taxonomy") or [])
            ),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "external_service_connection_enabled": execute,
            "download_enabled": execute,
            "fetch_public_urls_enabled": execute,
            "login_required_fetch_enabled": False,
            "ca_certificate_required_fetch_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_post_candidate_backtrace_mode": "EXECUTED" if execute else "DRY_RUN",
        "real_sample_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "safe_to_execute": bool(entry_result.get("safe_to_execute")) and bool(backtrace_result.get("safe_to_execute")),
        "blocking_reasons": _dedupe_strings(
            [
                *list(entry_result.get("blocking_reasons") or []),
                *list(backtrace_result.get("blocking_reasons") or []),
            ]
        ),
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": execute,
            "download_enabled": execute,
            "fetch_public_urls_enabled": execute,
            "storage_path_optional": str(storage),
            "object_storage_path_optional": str(object_storage),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }

    run_manifest_path = root / "run-manifest.json"
    run_manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    build_professional_clean_project_archive_manifest(
        real_sample_execution_manifest_json=run_manifest_path,
        output_root=root,
        storage_path=storage,
        object_storage_path=object_storage,
    )
    return result


def _source_manifest(result: Mapping[str, Any]) -> dict[str, Any]:
    manifest = result.get("manifest")
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return {}


def _project_samples(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(manifest.get("project_sample_items") or [])
        if isinstance(item, Mapping)
        and str(item.get("source_profile_id") or "") == GUANGZHOU_PROFILE_ID
    ]


def _target_items(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(manifest.get("items") or [])
        if isinstance(item, Mapping)
        and (
            str(item.get("source_profile_id") or "") == GUANGZHOU_PROFILE_ID
            or str(item.get("required_fetch_profile_id_optional") or "") == GUANGZHOU_PROFILE_ID
        )
    ]


def _select_post_candidate_entries(samples: list[Mapping[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        if str(sample.get("document_kind") or "") not in {"candidate_notice", "award_result"}:
            continue
        key = _project_match_key(sample)
        if not key:
            continue
        grouped.setdefault(key, []).append(sample)
    seen: set[str] = set()
    for key, project_samples in grouped.items():
        if not key or key in seen:
            continue
        seen.add(key)
        row = dict(project_samples[0])
        row["present_document_kinds"] = _dedupe_strings(
            str(sample.get("document_kind") or "") for sample in project_samples
        )
        row["entry_source_urls"] = _dedupe_strings(str(sample.get("source_url") or "") for sample in project_samples)
        selected.append(row)
        if len(selected) >= max(1, limit):
            break
    return selected


def _backtrace_targets_for_entries(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        project_code = str(entry.get("source_project_code") or "").strip()
        project_name = str(entry.get("project_name") or "").strip()
        match_key = _project_match_key(entry)
        base_project_name = _base_guangzhou_project_name(project_name)
        query_variants = _backtrace_query_variants(entry, base_project_name=base_project_name)
        present_document_kinds = set(str(kind) for kind in list(entry.get("present_document_kinds") or []))
        suffix = _slug(project_code or match_key or f"PROJECT-{index}")[:36]
        for document_kind in CORE_BACKTRACE_DOCUMENT_KINDS:
            if document_kind in present_document_kinds:
                continue
            target_id = f"GZ-BACKTRACE-{suffix}-{_document_kind_suffix(document_kind)}"
            filters = [
                *BACKTRACE_STAGE_FILTERS[document_kind],
                f"BACKTRACE_PROJECT_KEY:{match_key}",
            ]
            if project_code:
                filters.append(f"BACKTRACE_PROJECT_CODE:{project_code}")
            if project_name:
                filters.append(f"BACKTRACE_PROJECT_NAME:{project_name}")
            if base_project_name:
                filters.append(f"BACKTRACE_BASE_PROJECT_NAME:{base_project_name}")
            for variant in query_variants:
                filters.append(f"BACKTRACE_QUERY_VARIANT:{variant}")
            targets.append(
                {
                    "target_id": target_id,
                    "jurisdiction": "CN-GD",
                    "platform_name": "广州交易集团",
                    "entry_seed_id": "ENTRY-GUANGZHOU-YWTB",
                    "required_fetch_profile_id_optional": GUANGZHOU_PROFILE_ID,
                    "source_family": "local_public_resource_trading_center",
                    "project_type": "construction",
                    "document_kind": document_kind,
                    "target_count": 1,
                    "selection_filters": filters,
                    "base_project_name": base_project_name,
                    "backtrace_query_variants": query_variants,
                }
            )
    return {
        "target_version": 1,
        "target_set_id": "guangzhou-post-candidate-backtrace-v1",
        "minimum_total_sample_goal": len(targets),
        "created_from": "POST_CANDIDATE_BACKTRACE_V1",
        "target_policy": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "do_not_fabricate_project_urls": True,
        },
        "targets": targets,
    }


def _annotate_project_samples(
    samples: list[Mapping[str, Any]],
    *,
    target_items: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault(str(sample.get("project_id") or sample.get("target_id") or ""), []).append(sample)
    annotated: list[dict[str, Any]] = []
    target_items = list(target_items or [])
    for project_samples in grouped.values():
        document_kinds = {str(sample.get("document_kind") or "") for sample in project_samples}
        missing = [kind for kind in CORE_BACKTRACE_DOCUMENT_KINDS if kind not in document_kinds]
        post_state = (
            "POST_CANDIDATE_ENTRY_PRESENT"
            if document_kinds & {"candidate_notice", "award_result"}
            else "POST_CANDIDATE_ENTRY_MISSING"
        )
        backtrace_state = "BACKTRACE_CORE_COMPLETE" if not missing else "BACKTRACE_PARTIAL"
        project_keys = {
            key
            for sample in project_samples
            for key in [
                _project_match_key(sample),
                str(sample.get("source_project_code") or ""),
                str(sample.get("project_match_key") or ""),
            ]
            if key
        }
        base_project_names = _dedupe_strings(
            str(sample.get("base_project_name") or "") for sample in project_samples
        )
        query_variants = _dedupe_strings(
            value
            for sample in project_samples
            for value in list(sample.get("backtrace_query_variants") or [])
        )
        match_reasons = _dedupe_strings(
            str(sample.get("backtrace_match_reason") or "") for sample in project_samples
        )
        attempts = [
            {
                "document_kind": str(sample.get("document_kind") or ""),
                "target_id": str(sample.get("parent_target_id") or sample.get("target_id") or ""),
                "source_url": str(sample.get("source_url") or ""),
                "target_execution_state": str(sample.get("target_execution_state") or ""),
                "detail_snapshot_count": _int(sample.get("detail_snapshot_count")),
                "attachment_snapshot_count": _int(sample.get("attachment_snapshot_count")),
                "failure_taxonomy": list(sample.get("failure_taxonomy") or []),
                "base_project_name": str(sample.get("base_project_name") or ""),
                "backtrace_query_variants": list(sample.get("backtrace_query_variants") or []),
                "backtrace_match_reason": str(sample.get("backtrace_match_reason") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            for sample in project_samples
        ]
        attempt_keys = {(attempt["target_id"], attempt["document_kind"], attempt["source_url"]) for attempt in attempts}
        for target_item in target_items:
            target_key = _target_item_project_key(target_item)
            if not target_key or target_key not in project_keys:
                continue
            target_base_project_name = str(
                target_item.get("base_project_name") or _target_item_filter_value(target_item, "BACKTRACE_BASE_PROJECT_NAME:")
            )
            target_query_variants = list(target_item.get("backtrace_query_variants") or []) or _target_item_query_variants(
                target_item
            )
            attempt = {
                "document_kind": str(target_item.get("document_kind") or ""),
                "target_id": str(target_item.get("target_id") or ""),
                "source_url": "",
                "target_execution_state": str(target_item.get("target_execution_state") or ""),
                "detail_snapshot_count": _int(target_item.get("detail_snapshot_count")),
                "attachment_snapshot_count": _int(target_item.get("attachment_snapshot_count")),
                "failure_taxonomy": list(target_item.get("failure_taxonomy") or []),
                "base_project_name": target_base_project_name,
                "backtrace_query_variants": target_query_variants,
                "backtrace_match_reason": str(target_item.get("backtrace_match_reason") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            key = (attempt["target_id"], attempt["document_kind"], attempt["source_url"])
            if key in attempt_keys:
                continue
            attempt_keys.add(key)
            attempts.append(attempt)
        for sample in project_samples:
            row = dict(sample)
            row["post_candidate_entry_state"] = post_state
            row["backtrace_stage_attempts"] = attempts
            row["matched_project_keys"] = _dedupe_strings(
                [
                    *list(row.get("matched_project_keys") or []),
                    row.get("source_project_code"),
                    row.get("project_match_key"),
                    _project_match_key(row),
                ]
            )
            row["base_project_name"] = str(
                row.get("base_project_name") or (base_project_names[0] if base_project_names else "")
            )
            row["backtrace_query_variants"] = _dedupe_strings(
                [
                    *list(row.get("backtrace_query_variants") or []),
                    *query_variants,
                ]
            )
            row["backtrace_match_reason"] = str(
                row.get("backtrace_match_reason") or (match_reasons[0] if match_reasons else "")
            )
            row["missing_stage_kinds"] = missing
            row["backtrace_completeness_state"] = backtrace_state
            annotated.append(row)
    return annotated


def _target_item_project_key(target_item: Mapping[str, Any]) -> str:
    for value in list(target_item.get("selection_filters") or []):
        text = str(value or "")
        if text.startswith("BACKTRACE_PROJECT_CODE:") or text.startswith("BACKTRACE_PROJECT_KEY:"):
            return text.split(":", 1)[1].strip()
    return ""


def _target_item_filter_value(target_item: Mapping[str, Any], prefix: str) -> str:
    for value in list(target_item.get("selection_filters") or []):
        text = str(value or "")
        if text.startswith(prefix):
            return text.split(":", 1)[1].strip()
    return ""


def _target_item_query_variants(target_item: Mapping[str, Any]) -> list[str]:
    return _dedupe_strings(
        str(value or "").split(":", 1)[1].strip()
        for value in list(target_item.get("selection_filters") or [])
        if str(value or "").startswith("BACKTRACE_QUERY_VARIANT:")
    )


def _backtrace_query_variants(entry: Mapping[str, Any], *, base_project_name: str = "") -> list[str]:
    candidates: list[str] = []
    candidates.extend(str(value or "") for value in list(entry.get("backtrace_query_variants") or []))
    candidates.extend(
        [
            str(entry.get("source_project_code") or ""),
            str(entry.get("project_match_key") or ""),
            base_project_name,
            str(entry.get("project_name") or ""),
            _remove_parenthetical_text(base_project_name),
            _short_project_query(base_project_name),
        ]
    )
    return _dedupe_strings(value for value in candidates if str(value or "").strip())[:8]


def _base_guangzhou_project_name(value: Any) -> str:
    text = str(value or "").strip()
    for marker in (
        "中标候选人公示",
        "中标结果公告",
        "中标结果",
        "中标信息",
        "招标公告",
        "重新招标公告",
        "变更公告",
        "补充公告",
        "答疑公告",
        "澄清公告",
        "投标文件公开",
        "开标记录",
    ):
        text = text.replace(marker, "")
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _remove_parenthetical_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[（(][^（）()]{1,40}[）)]", "", text)
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _short_project_query(value: Any) -> str:
    text = _remove_parenthetical_text(value)
    text = re.sub(r"(第[一二三四五六七八九十0-9]+次|标段[一二三四五六七八九十0-9]+|第[一二三四五六七八九十0-9]+标段)", "", text)
    text = re.sub(r"(工程监理服务|设计施工总承包|勘察设计施工总承包及运营|施工总承包|工程施工|施工|监理服务)$", "", text)
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _summary(
    *,
    project_samples: list[Mapping[str, Any]],
    items: list[Mapping[str, Any]],
    selected_entries: list[Mapping[str, Any]],
) -> dict[str, Any]:
    project_ids = {str(sample.get("project_id") or "") for sample in project_samples if str(sample.get("project_id") or "")}
    return {
        "target_execution_bucket_count": len(items),
        "project_sample_count": len(project_samples),
        "unique_project_count": len(project_ids),
        "selected_post_candidate_entry_count": len(selected_entries),
        "project_sample_document_kind_counts": _counts(str(sample.get("document_kind") or "") for sample in project_samples),
        "post_candidate_entry_state_counts": _counts(str(sample.get("post_candidate_entry_state") or "") for sample in project_samples),
        "backtrace_completeness_state_counts": _counts(str(sample.get("backtrace_completeness_state") or "") for sample in project_samples),
        "detail_snapshot_count": sum(_int(sample.get("detail_snapshot_count")) for sample in project_samples),
        "attachment_snapshot_count": sum(_int(sample.get("attachment_snapshot_count")) for sample in project_samples),
        "failure_taxonomy_counts": _counts(
            reason
            for sample in project_samples
            for reason in list(sample.get("failure_taxonomy") or [])
        ),
        "backtrace_match_reason_counts": _counts(str(sample.get("backtrace_match_reason") or "") for sample in project_samples),
        "download_enabled": True,
        "fetch_public_urls_enabled": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _coverage_state(project_samples: list[Mapping[str, Any]]) -> str:
    if not project_samples:
        return "NO_REAL_SNAPSHOT_CAPTURED_REVIEW"
    if any(_int(sample.get("detail_snapshot_count")) > 0 for sample in project_samples):
        return "PARTIAL_REAL_SNAPSHOT_COVERAGE_REVIEW"
    return "NO_REAL_SNAPSHOT_CAPTURED_REVIEW"


def _project_match_key(sample: Mapping[str, Any]) -> str:
    for value in (
        sample.get("source_project_code"),
        sample.get("project_match_key"),
        sample.get("project_id"),
        sample.get("project_name"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _document_kind_suffix(document_kind: str) -> str:
    return {
        "tender_file": "TENDER",
        "candidate_notice": "CANDIDATE",
        "award_result": "AWARD",
    }.get(document_kind, _slug(document_kind))


def _slug(value: Any) -> str:
    text = str(value or "").strip()
    token = "".join(char.upper() if char.isascii() and char.isalnum() else "-" for char in text)
    token = "-".join(part for part in token.split("-") if part)
    return token or f"H{_fingerprint(text)[:12].upper()}"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _dedupe_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou post-candidate backtrace v1.")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--targets-json")
    parser.add_argument("--seed-json")
    parser.add_argument("--storage-path")
    parser.add_argument("--object-storage-path")
    parser.add_argument("--target-backend", default="json-file")
    parser.add_argument("--per-target-candidate-limit", type=int, default=3)
    parser.add_argument("--output-json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_post_candidate_backtrace(
        output_root=args.output_root,
        targets_json=args.targets_json,
        seed_json=args.seed_json,
        storage_path=args.storage_path,
        object_storage_path=args.object_storage_path,
        target_backend=args.target_backend,
        execute=args.execute,
        per_target_candidate_limit=args.per_target_candidate_limit,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "run-manifest.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "guangzhou post-candidate backtrace "
            f"{result['guangzhou_post_candidate_backtrace_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())
