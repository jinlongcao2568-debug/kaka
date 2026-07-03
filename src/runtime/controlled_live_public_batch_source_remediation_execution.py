from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from runtime.controlled_live_public_batch_evidence_summary import (
    build_controlled_live_public_batch_evidence_summary,
)
from runtime.controlled_live_public_batch_source_remediation import (
    build_controlled_live_public_batch_source_remediation,
)
from runtime.controlled_live_public_batch_stage4_readback import (
    build_controlled_live_public_batch_stage4_readback,
)
from storage.evaluation_real_sample_execution import build_evaluation_real_sample_execution


CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_KIND = (
    "controlled_live_public_batch_source_remediation_execution_v1"
)
CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/controlled-live-public-batch-source-remediation-execution-v1"
)


def build_controlled_live_public_batch_source_remediation_execution(
    *,
    source_remediation_json: str | Path,
    targets_json: str | Path | None = None,
    seed_json: str | Path | None = None,
    target_backend: str = "json-file",
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    database_url: str | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute: bool = False,
    created_at: str | None = None,
    target_limit: int | None = None,
    per_target_candidate_limit: int = 1,
    professional_source_only: bool = False,
    enable_alternate_public_source: bool = False,
    discovery_service: Any | None = None,
    capture_service: Any | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    remediation_path = Path(source_remediation_json)
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    storage = Path(storage_path) if storage_path else output_dir / "storage.json"
    object_storage = Path(object_storage_path) if object_storage_path else output_dir / "objects"

    remediation_payload = _load_json(remediation_path)
    queue_records = _records(_mapping(remediation_payload.get("source_remediation_queue")).get("records"))
    group_records = _records(_mapping(remediation_payload.get("source_remediation_groups")).get("records"))
    requested_target_ids = _queued_target_ids(queue_records=queue_records, group_records=group_records)
    if target_limit is not None:
        requested_target_ids = requested_target_ids[: max(0, int(target_limit))]

    rerun_result: dict[str, Any] | None = None
    if requested_target_ids:
        rerun_result = build_evaluation_real_sample_execution(
            targets_json=targets_json,
            seed_json=seed_json,
            database_url=database_url,
            target_backend=target_backend,
            storage_path=storage,
            object_storage_path=object_storage,
            execute=execute,
            created_at=created,
            target_ids=requested_target_ids,
            per_target_candidate_limit=per_target_candidate_limit,
            professional_source_only=professional_source_only,
            discovery_service=discovery_service,
            capture_service=capture_service,
        )
    rerun_manifest_json = output_dir / "controlled-live-public-batch-source-remediation-rerun-manifest.json"
    post_run_outputs = _post_run_outputs(
        rerun_result=rerun_result,
        rerun_manifest_json=rerun_manifest_json,
        storage_path=storage,
        output_dir=output_dir,
        execute=execute,
        created_at=created,
    )
    alternate_run = _maybe_run_alternate_public_sources(
        queue_records=queue_records,
        group_records=group_records,
        rerun_result=rerun_result,
        source_remediation_post_run_outputs=post_run_outputs,
        output_dir=output_dir,
        execute=execute,
        enabled=enable_alternate_public_source,
        target_backend=target_backend,
        database_url=database_url,
        per_target_candidate_limit=per_target_candidate_limit,
        professional_source_only=professional_source_only,
        created_at=created,
        discovery_service=discovery_service,
        capture_service=capture_service,
    )

    summary = _summary(
        source_remediation_payload=remediation_payload,
        queue_records=queue_records,
        group_records=group_records,
        requested_target_ids=requested_target_ids,
        rerun_result=rerun_result,
        post_run_outputs=post_run_outputs,
        alternate_run=alternate_run,
        enable_alternate_public_source=enable_alternate_public_source,
        execute=execute,
    )
    result = {
        "manifest_kind": CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_KIND,
        "manifest_version": CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_VERSION,
        "adapter_id": "controlled-live-public-batch-source-remediation-execution-v1",
        "created_at": created,
        "source_remediation_json": str(remediation_path),
        "targets_json": str(targets_json or ""),
        "seed_json": str(seed_json or ""),
        "target_backend": target_backend,
        "storage_path": str(storage),
        "object_storage_path": str(object_storage),
        "execute": execute,
        "requested_target_ids": requested_target_ids,
        "rerun_manifest_json": str(rerun_manifest_json if rerun_result else ""),
        "post_run_outputs": post_run_outputs,
        "alternate_public_source_run": alternate_run,
        "summary": summary,
        "rerun_execution_manifest": _mapping(_mapping(rerun_result).get("manifest")),
        "alternate_public_source_execution_manifest": _mapping(
            _mapping(_mapping(alternate_run).get("execution_result")).get("manifest")
        ),
        "safety": _safety(execute=execute),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(
        output_dir / "controlled-live-public-batch-source-remediation-execution-v1.json",
        result,
    )
    (output_dir / "controlled-live-public-batch-source-remediation-execution-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _maybe_run_alternate_public_sources(
    *,
    queue_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
    rerun_result: Mapping[str, Any] | None,
    source_remediation_post_run_outputs: Mapping[str, Any],
    output_dir: Path,
    execute: bool,
    enabled: bool,
    target_backend: str,
    database_url: str | None,
    per_target_candidate_limit: int,
    professional_source_only: bool,
    created_at: str,
    discovery_service: Any | None,
    capture_service: Any | None,
) -> dict[str, Any]:
    if not enabled:
        return {
            "alternate_public_source_enabled": False,
            "alternate_public_source_execution_state": "NOT_ENABLED",
        }
    if not execute:
        return {
            "alternate_public_source_enabled": True,
            "alternate_public_source_execution_state": "NOT_RUN_DRY_RUN_ONLY",
        }
    if not _alternate_needed_after_rerun(
        rerun_result=rerun_result,
        source_remediation_post_run_outputs=source_remediation_post_run_outputs,
    ):
        return {
            "alternate_public_source_enabled": True,
            "alternate_public_source_execution_state": "NOT_REQUIRED_AFTER_PRIMARY_RERUN",
        }

    alternate_root = output_dir / "alternate-public-source"
    alternate_root.mkdir(parents=True, exist_ok=True)
    target_file, seed_file, target_ids = _write_alternate_source_target_files(
        queue_records=queue_records,
        group_records=group_records,
        output_dir=alternate_root,
    )
    if not target_ids:
        return {
            "alternate_public_source_enabled": True,
            "alternate_public_source_execution_state": "NO_ALTERNATE_PUBLIC_SOURCE_TARGETS",
        }
    storage_path = alternate_root / "storage.json"
    object_storage_path = alternate_root / "objects"
    execution_result = build_evaluation_real_sample_execution(
        targets_json=target_file,
        seed_json=seed_file,
        database_url=database_url,
        target_backend=target_backend,
        storage_path=storage_path,
        object_storage_path=object_storage_path,
        execute=True,
        created_at=created_at,
        target_ids=target_ids,
        per_target_candidate_limit=per_target_candidate_limit,
        professional_source_only=professional_source_only,
        discovery_service=discovery_service,
        capture_service=capture_service,
    )
    manifest_json = alternate_root / "controlled-live-public-batch-alternate-source-rerun-manifest.json"
    post_run_outputs = _post_run_outputs(
        rerun_result=execution_result,
        rerun_manifest_json=manifest_json,
        storage_path=storage_path,
        output_dir=alternate_root,
        execute=True,
        created_at=created_at,
    )
    summary = _mapping(_mapping(execution_result).get("summary"))
    state = (
        "ALTERNATE_PUBLIC_SOURCE_EXECUTED_WITH_SNAPSHOTS"
        if _int(summary.get("detail_snapshot_count")) > 0
        else "ALTERNATE_PUBLIC_SOURCE_EXECUTED_REVIEW_REQUIRED"
    )
    return {
        "alternate_public_source_enabled": True,
        "alternate_public_source_execution_state": state,
        "alternate_targets_json": str(target_file),
        "alternate_seed_json": str(seed_file),
        "alternate_requested_target_ids": target_ids,
        "alternate_manifest_json": str(manifest_json),
        "alternate_project_sample_count": _int(summary.get("project_sample_count")),
        "alternate_detail_snapshot_count": _int(summary.get("detail_snapshot_count")),
        "alternate_attachment_snapshot_count": _int(summary.get("attachment_snapshot_count")),
        "alternate_post_run_outputs": post_run_outputs,
        "execution_result": execution_result,
    }


def _alternate_needed_after_rerun(
    *,
    rerun_result: Mapping[str, Any] | None,
    source_remediation_post_run_outputs: Mapping[str, Any],
) -> bool:
    rerun_summary = _mapping(_mapping(_mapping(rerun_result).get("manifest")).get("summary"))
    return (
        _int(rerun_summary.get("project_sample_count")) > 0
        and _int(rerun_summary.get("detail_snapshot_count")) <= 0
        and _int(source_remediation_post_run_outputs.get("post_run_source_remediation_record_count")) > 0
    )


def _write_alternate_source_target_files(
    *,
    queue_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
    output_dir: Path,
) -> tuple[Path, Path, list[str]]:
    supported_profiles = _alternate_profiles(queue_records=queue_records, group_records=group_records)
    targets: list[dict[str, Any]] = []
    target_ids: list[str] = []
    for profile_id in supported_profiles:
        if profile_id != "GGZY-DEAL-LIST":
            continue
        for record in queue_records:
            alternate_route = _mapping(record.get("alternate_public_source_route"))
            if profile_id not in _string_list(alternate_route.get("alternate_source_profile_ids")):
                continue
            for variant in _alternate_query_variants(record):
                variant_id = str(variant.get("variant_id") or "query")
                target_fingerprint = _fingerprint(
                    {
                        "parent": record.get("parent_target_id"),
                        "kind": record.get("document_kind"),
                        "project": record.get("project_id"),
                        "variant": variant_id,
                    }
                )
                target_id = f"ALT-{profile_id}-{target_fingerprint[:12]}"
                if target_id in target_ids:
                    continue
                target_ids.append(target_id)
                targets.append(
                    {
                        "target_id": target_id,
                        "source_parent_target_id": str(record.get("parent_target_id") or ""),
                        "source_remediation_record_id": str(record.get("remediation_record_id") or ""),
                        "alternate_query_variant": variant_id,
                        "jurisdiction": str(record.get("jurisdiction") or "CN"),
                        "platform_name": "全国公共资源交易平台",
                        "entry_seed_id": "ENTRY-GGZY-DEAL-LIST",
                        "required_fetch_profile_id_optional": profile_id,
                        "source_family": "local_public_resource_trading_center",
                        "project_type": "construction",
                        "document_kind": str(record.get("document_kind") or "tender_file"),
                        "target_count": 1,
                        "selection_filters": _string_list(variant.get("selection_filters")),
                    }
                )
    target_file = output_dir / "alternate-public-source-targets.json"
    seed_file = output_dir / "alternate-public-source-seed.json"
    _write_json(
        target_file,
        {
            "target_version": 1,
            "target_set_id": "controlled-live-public-batch-alternate-public-source-targets-v1",
            "minimum_total_sample_goal": len(targets),
            "targets": targets,
            "target_policy": {
                "customer_visible_allowed": False,
                "payment_execution_enabled": False,
                "delivery_execution_enabled": False,
                "query_miss_is_not_clearance": True,
                "no_legal_conclusion": True,
            },
        },
    )
    _write_json(
        seed_file,
        {
            "sources": [
                {
                    "seed_id": "ENTRY-GGZY-DEAL-LIST",
                    "source_url": "https://www.ggzy.gov.cn/deal/dealList.html",
                    "source_family": "local_public_resource_trading_center",
                    "jurisdiction": "CN",
                    "project_type": "construction",
                    "document_kind": "tender_file",
                    "source_title": "全国公共资源交易平台交易公开",
                    "fetch_profile_id_optional": "GGZY-DEAL-LIST",
                    "seed_tags": ["real_public_entry", "fetchable", "national_entry", "alternate_public_source"],
                }
            ]
        },
    )
    return target_file, seed_file, target_ids


def _alternate_profiles(
    *,
    queue_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
) -> list[str]:
    profiles: list[str] = []
    for record in queue_records:
        profiles.extend(
            _string_list(_mapping(record.get("alternate_public_source_route")).get("alternate_source_profile_ids"))
        )
    for group in group_records:
        profiles.extend(_string_list(_mapping(group.get("recommended_execution")).get("alternate_source_profile_ids")))
    return _dedupe(profiles)


def _alternate_selection_filters(record: Mapping[str, Any]) -> list[str]:
    route_terms = _string_list(_mapping(record.get("alternate_public_source_route")).get("alternate_query_terms"))
    return _dedupe(
        [
            _region_term(record),
            *_public_query_terms(route_terms),
            *_public_query_terms([record.get("project_match_key"), record.get("project_name")]),
            "工程建设",
        ]
    )


def _alternate_query_variants(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [
        {
            "variant_id": "doc-kind-recent",
            "selection_filters": _alternate_selection_filters(record),
        }
    ]
    exact_terms = _alternate_find_text_terms(record)
    if exact_terms:
        title_term = exact_terms[0]
        variants.extend(
            [
                {
                    "variant_id": "title-30d",
                    "selection_filters": _ggzy_find_text_filters(record, title_term, window_days=30),
                },
                {
                    "variant_id": "title-90d",
                    "selection_filters": _ggzy_find_text_filters(record, title_term, window_days=90),
                },
            ]
        )
    if len(exact_terms) > 1:
        variants.append(
            {
                "variant_id": "core-title-90d",
                "selection_filters": _ggzy_find_text_filters(record, exact_terms[1], window_days=90),
            }
        )
    broad_terms = _broad_find_text_terms(exact_terms)
    if broad_terms:
        variants.extend(
            [
                {
                    "variant_id": "keyword-365d",
                    "selection_filters": _ggzy_find_text_filters(record, broad_terms[0], window_days=365),
                },
                {
                    "variant_id": "national-keyword-365d",
                    "selection_filters": _ggzy_find_text_filters(
                        record,
                        broad_terms[0],
                        window_days=365,
                        province_code="0",
                    ),
                },
            ]
        )
    return _dedupe_query_variants(variants)


def _ggzy_find_text_filters(
    record: Mapping[str, Any],
    find_text: str,
    *,
    window_days: int,
    province_code: str | None = None,
) -> list[str]:
    return _dedupe(
        [
            _region_term(record) if province_code != "0" else "",
            f"GGZY_FINDTXT:{find_text}",
            f"GGZY_WINDOW_DAYS:{window_days}",
            f"GGZY_PROVINCE_CODE:{province_code}" if province_code is not None else "",
            "工程建设",
        ]
    )


def _alternate_find_text_terms(record: Mapping[str, Any]) -> list[str]:
    route_terms = _string_list(_mapping(record.get("alternate_public_source_route")).get("alternate_query_terms"))
    raw_terms = [
        *_public_query_terms(route_terms),
        *_public_query_terms([record.get("project_match_key"), record.get("project_name")]),
    ]
    exact_terms: list[str] = []
    core_terms: list[str] = []
    for raw in raw_terms:
        cleaned = _clean_public_find_text(raw)
        if len(cleaned) >= 4:
            exact_terms.append(cleaned)
        core = _core_public_find_text(cleaned)
        if len(core) >= 4 and core != cleaned:
            core_terms.append(core)
    terms: list[str] = []
    for term in _dedupe(exact_terms[:1] + core_terms + exact_terms[1:]):
        terms.append(term)
        if len(terms) >= 2:
            break
    return terms


def _broad_find_text_terms(exact_terms: Iterable[str]) -> list[str]:
    broad_terms: list[str] = []
    for term in exact_terms:
        text = str(term or "").strip()
        for pattern in (
            r"^(.{4,}?)(?:\d+#)",
            r"^(.{4,}?)(?:综合楼|地下车库|住宅楼|监理|施工|设计|采购|项目)",
        ):
            match = re.search(pattern, text)
            if match:
                broad_terms.append(match.group(1).strip(" ，,。；;：:、"))
                break
    return sorted(_dedupe(term for term in broad_terms if len(term) >= 4), key=len)[:1]


def _clean_public_find_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[【\[].*?[】\]]", "", text).strip()
    text = re.sub(r"\s+", "", text)
    return text.strip(" ，,。；;：:")


def _core_public_find_text(value: str) -> str:
    text = str(value or "").strip()
    suffixes = (
        "公开招标公告",
        "招标公告",
        "中标候选人公示",
        "中标结果公告",
        "成交结果公告",
        "结果公告",
        "候选人公示",
        "公示",
        "公告",
    )
    for suffix in suffixes:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip(" ，,。；;：:")
    return text


def _dedupe_query_variants(variants: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []
    for variant in variants:
        filters = _string_list(variant.get("selection_filters"))
        key = tuple(filters)
        if not filters or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "variant_id": str(variant.get("variant_id") or f"query-{len(out) + 1}"),
                "selection_filters": filters,
            }
        )
    return out


def _region_term(record: Mapping[str, Any]) -> str:
    jurisdiction = str(record.get("jurisdiction") or "")
    return {
        "CN-SD": "山东",
        "CN-SH": "上海",
        "CN-GD": "广东",
        "CN-JS": "江苏",
        "CN-HB": "湖北",
        "CN-ZJ": "浙江",
        "CN-SC": "四川",
    }.get(jurisdiction, "")


def _public_query_terms(values: Iterable[Any]) -> list[str]:
    terms: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        upper = text.upper()
        if upper.startswith(("PROJ-", "REAL-", "ALT-", "CLPB-")):
            continue
        terms.append(text)
    return terms


def _post_run_outputs(
    *,
    rerun_result: Mapping[str, Any] | None,
    rerun_manifest_json: Path,
    storage_path: Path,
    output_dir: Path,
    execute: bool,
    created_at: str,
) -> dict[str, Any]:
    if not rerun_result:
        return {}
    _write_json(rerun_manifest_json, rerun_result)
    if not execute:
        return {
            "rerun_manifest_json": str(rerun_manifest_json),
            "post_run_evidence_generation_state": "NOT_RUN_DRY_RUN_ONLY",
        }

    evidence_root = output_dir / "evidence-summary"
    stage4_root = output_dir / "stage4-readback"
    source_remediation_root = output_dir / "source-remediation"
    evidence = build_controlled_live_public_batch_evidence_summary(
        real_sample_execution_json=rerun_manifest_json,
        storage_json=storage_path,
        output_root=evidence_root,
        created_at=created_at,
    )
    stage4 = build_controlled_live_public_batch_stage4_readback(
        evidence_summary_json=evidence_root / "controlled-live-public-batch-evidence-summary-v1.json",
        real_sample_execution_json=rerun_manifest_json,
        storage_json=storage_path,
        output_root=stage4_root,
        created_at=created_at,
    )
    source_remediation = build_controlled_live_public_batch_source_remediation(
        evidence_summary_json=evidence_root / "controlled-live-public-batch-evidence-summary-v1.json",
        real_sample_execution_json=rerun_manifest_json,
        stage4_readback_json=stage4_root / "controlled-live-public-batch-stage4-readback-v1.json",
        output_root=source_remediation_root,
        created_at=created_at,
    )
    return {
        "rerun_manifest_json": str(rerun_manifest_json),
        "post_run_evidence_generation_state": "GENERATED",
        "post_run_evidence_summary_json": str(evidence_root / "controlled-live-public-batch-evidence-summary-v1.json"),
        "post_run_stage4_readback_json": str(stage4_root / "controlled-live-public-batch-stage4-readback-v1.json"),
        "post_run_source_remediation_json": str(
            source_remediation_root / "controlled-live-public-batch-source-remediation-v1.json"
        ),
        "post_run_project_sample_count": _int(_mapping(evidence.get("summary")).get("project_sample_count")),
        "post_run_fixed_snapshot_sha256_count": _int(
            _mapping(evidence.get("summary")).get("fixed_snapshot_sha256_count")
        ),
        "post_run_stage4_all_required_readbacks_ready": bool(
            _mapping(stage4.get("summary")).get("stage4_all_required_readbacks_ready")
        ),
        "post_run_source_remediation_record_count": _int(
            _mapping(source_remediation.get("summary")).get("source_remediation_record_count")
        ),
        "post_run_source_remediation_closeout_state": str(
            _mapping(source_remediation.get("summary")).get("source_remediation_closeout_state") or ""
        ),
    }


def _queued_target_ids(
    *,
    queue_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
) -> list[str]:
    ids: list[Any] = []
    for group in group_records:
        recommended = _mapping(group.get("recommended_execution"))
        ids.extend(_string_list(recommended.get("blocked_parent_target_ids")))
    for record in queue_records:
        ids.extend(_string_list(record.get("minimum_rerun_target_ids")))
        ids.append(record.get("parent_target_id"))
    return _dedupe(ids)


def _summary(
    *,
    source_remediation_payload: Mapping[str, Any],
    queue_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
    requested_target_ids: list[str],
    rerun_result: Mapping[str, Any] | None,
    post_run_outputs: Mapping[str, Any],
    alternate_run: Mapping[str, Any],
    enable_alternate_public_source: bool,
    execute: bool,
) -> dict[str, Any]:
    rerun_manifest = _mapping(_mapping(rerun_result).get("manifest"))
    rerun_summary = _mapping(rerun_manifest.get("summary"))
    selected_target_ids = _string_list(rerun_manifest.get("selected_target_ids"))
    missing_target_ids = _string_list(rerun_manifest.get("missing_requested_target_ids"))
    state = _execution_state(
        requested_target_ids=requested_target_ids,
        selected_target_ids=selected_target_ids,
        rerun_summary=rerun_summary,
        execute=execute,
    )
    return {
        "source_remediation_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "source_remediation_manifest_sha256": str(source_remediation_payload.get("manifest_sha256") or ""),
        "source_remediation_record_count": len(queue_records),
        "source_remediation_group_count": len(group_records),
        "queued_blocked_parent_target_count": len(requested_target_ids),
        "requested_target_ids": requested_target_ids,
        "selected_target_ids": selected_target_ids,
        "missing_requested_target_ids": missing_target_ids,
        "rerun_target_execution_bucket_count": _int(rerun_summary.get("target_execution_bucket_count")),
        "rerun_project_sample_count": _int(rerun_summary.get("project_sample_count")),
        "rerun_detail_snapshot_count": _int(rerun_summary.get("detail_snapshot_count")),
        "rerun_attachment_snapshot_count": _int(rerun_summary.get("attachment_snapshot_count")),
        "rerun_stage3_parse_success_count": _int(rerun_summary.get("stage3_parse_success_count")),
        "rerun_stage3_parse_failed_count": _int(rerun_summary.get("stage3_parse_failed_count")),
        "rerun_target_execution_state_counts": _mapping(rerun_summary.get("execution_state_counts")),
        "rerun_coverage_quality_state": str(rerun_summary.get("coverage_quality_state") or ""),
        "source_remediation_execution_state": state,
        "post_run_evidence_generation_state": str(
            post_run_outputs.get("post_run_evidence_generation_state") or ""
        ),
        "post_run_evidence_summary_json": str(post_run_outputs.get("post_run_evidence_summary_json") or ""),
        "post_run_stage4_readback_json": str(post_run_outputs.get("post_run_stage4_readback_json") or ""),
        "post_run_source_remediation_json": str(post_run_outputs.get("post_run_source_remediation_json") or ""),
        "post_run_fixed_snapshot_sha256_count": _int(
            post_run_outputs.get("post_run_fixed_snapshot_sha256_count")
        ),
        "post_run_stage4_all_required_readbacks_ready": bool(
            post_run_outputs.get("post_run_stage4_all_required_readbacks_ready")
        ),
        "post_run_source_remediation_record_count": _int(
            post_run_outputs.get("post_run_source_remediation_record_count")
        ),
        "post_run_source_remediation_closeout_state": str(
            post_run_outputs.get("post_run_source_remediation_closeout_state") or ""
        ),
        "alternate_public_source_enabled": bool(enable_alternate_public_source),
        "alternate_public_source_execution_state": str(
            alternate_run.get("alternate_public_source_execution_state") or ""
        ),
        "alternate_requested_target_ids": _string_list(alternate_run.get("alternate_requested_target_ids")),
        "alternate_project_sample_count": _int(alternate_run.get("alternate_project_sample_count")),
        "alternate_detail_snapshot_count": _int(alternate_run.get("alternate_detail_snapshot_count")),
        "alternate_attachment_snapshot_count": _int(alternate_run.get("alternate_attachment_snapshot_count")),
        "alternate_manifest_json": str(alternate_run.get("alternate_manifest_json") or ""),
        "next_required_step": _next_required_step(
            state,
            post_run_outputs=post_run_outputs,
            alternate_run=alternate_run,
            enable_alternate_public_source=enable_alternate_public_source,
        ),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _execution_state(
    *,
    requested_target_ids: list[str],
    selected_target_ids: list[str],
    rerun_summary: Mapping[str, Any],
    execute: bool,
) -> str:
    if not requested_target_ids:
        return "NO_SOURCE_REMEDIATION_REQUIRED"
    if not selected_target_ids:
        return "SOURCE_REMEDIATION_TARGETS_NOT_FOUND"
    if not execute:
        return "SOURCE_REMEDIATION_RERUN_PLANNED"
    if _int(rerun_summary.get("detail_snapshot_count")) > 0:
        return "SOURCE_REMEDIATION_RERUN_EXECUTED_WITH_SNAPSHOTS"
    if _int(rerun_summary.get("project_sample_count")) > 0:
        return "SOURCE_REMEDIATION_RERUN_EXECUTED_REVIEW_REQUIRED"
    return "SOURCE_REMEDIATION_RERUN_EXECUTED_NO_SAMPLES"


def _next_required_step(
    state: str,
    *,
    post_run_outputs: Mapping[str, Any],
    alternate_run: Mapping[str, Any],
    enable_alternate_public_source: bool,
) -> str:
    alternate_state = str(alternate_run.get("alternate_public_source_execution_state") or "")
    if alternate_state == "ALTERNATE_PUBLIC_SOURCE_EXECUTED_WITH_SNAPSHOTS":
        return "review_alternate_public_source_evidence_before_gray_launch"
    if alternate_state == "ALTERNATE_PUBLIC_SOURCE_EXECUTED_REVIEW_REQUIRED":
        return "review_alternate_public_source_execution_result"
    if state == "NO_SOURCE_REMEDIATION_REQUIRED":
        return "gray_launch_review_if_other_gates_ready"
    if state == "SOURCE_REMEDIATION_RERUN_PLANNED":
        return "rerun_source_remediation_execution_with_execute"
    if state == "SOURCE_REMEDIATION_TARGETS_NOT_FOUND":
        return "repair_or_expand_evaluation_target_registry"
    if (
        state == "SOURCE_REMEDIATION_RERUN_EXECUTED_REVIEW_REQUIRED"
        and _int(post_run_outputs.get("post_run_source_remediation_record_count")) > 0
        and not enable_alternate_public_source
    ):
        return "execute_alternate_public_source_queries"
    if state == "SOURCE_REMEDIATION_RERUN_EXECUTED_WITH_SNAPSHOTS":
        if _int(post_run_outputs.get("post_run_source_remediation_record_count")) > 0:
            return "continue_source_remediation_queue"
        if bool(post_run_outputs.get("post_run_stage4_all_required_readbacks_ready")):
            return "human_gray_launch_review"
        return "rebuild_evidence_summary_stage4_and_source_remediation"
    return "review_source_remediation_execution_result"


def _safety(*, execute: bool) -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "download_enabled": bool(execute),
        "fetch_public_urls_enabled": bool(execute),
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "source_remediation_execution_enabled": bool(execute),
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Live Public Batch Source Remediation Execution",
        "",
        f"- source_remediation_execution_mode: {summary.get('source_remediation_execution_mode')}",
        f"- source_remediation_record_count: {summary.get('source_remediation_record_count')}",
        f"- source_remediation_group_count: {summary.get('source_remediation_group_count')}",
        f"- queued_blocked_parent_target_count: {summary.get('queued_blocked_parent_target_count')}",
        f"- selected_target_ids: {', '.join(_string_list(summary.get('selected_target_ids')))}",
        f"- missing_requested_target_ids: {', '.join(_string_list(summary.get('missing_requested_target_ids')))}",
        f"- rerun_project_sample_count: {summary.get('rerun_project_sample_count')}",
        f"- rerun_detail_snapshot_count: {summary.get('rerun_detail_snapshot_count')}",
        f"- source_remediation_execution_state: {summary.get('source_remediation_execution_state')}",
        f"- alternate_public_source_enabled: {str(bool(summary.get('alternate_public_source_enabled'))).lower()}",
        f"- alternate_public_source_execution_state: {summary.get('alternate_public_source_execution_state')}",
        f"- alternate_project_sample_count: {summary.get('alternate_project_sample_count')}",
        f"- alternate_detail_snapshot_count: {summary.get('alternate_detail_snapshot_count')}",
        f"- next_required_step: {summary.get('next_required_step')}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- query_miss_is_not_clearance: {str(bool(summary.get('query_miss_is_not_clearance'))).lower()}",
        "",
    ]
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) and isinstance(value.get("records"), list):
        value = value.get("records")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return [str(item) for item in value if str(item or "")]
    return [str(value)] if str(value or "") else []


def _dedupe(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-remediation-json", required=True)
    parser.add_argument("--targets-json", default="")
    parser.add_argument("--seed-json", default="")
    parser.add_argument("--target-backend", default="json-file")
    parser.add_argument("--storage-path", default="")
    parser.add_argument("--object-storage-path", default="")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--target-limit", type=int, default=None)
    parser.add_argument("--per-target-candidate-limit", type=int, default=1)
    parser.add_argument("--professional-source-only", action="store_true")
    parser.add_argument("--enable-alternate-public-source", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_controlled_live_public_batch_source_remediation_execution(
        source_remediation_json=args.source_remediation_json,
        targets_json=args.targets_json or None,
        seed_json=args.seed_json or None,
        target_backend=args.target_backend,
        storage_path=args.storage_path or None,
        object_storage_path=args.object_storage_path or None,
        database_url=args.database_url or None,
        output_root=args.output_root,
        target_limit=args.target_limit,
        per_target_candidate_limit=args.per_target_candidate_limit,
        professional_source_only=args.professional_source_only,
        enable_alternate_public_source=args.enable_alternate_public_source,
        execute=args.execute,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
