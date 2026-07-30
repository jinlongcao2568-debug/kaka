from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


QUEUE_KIND = "stage4_backfill_followup_queue_v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage4-backfill-followup-queue-v1")
DEFAULT_SCOREBOARD_JSON = Path(
    "tmp/evaluation-real-samples/stage1-6-sellable-rate-regression-live18-20260525-r2/scoreboard/stage1-6-sellable-scoreboard-v1.json"
)


def build_stage4_backfill_followup_queue(
    *,
    scoreboard_json: str | Path = DEFAULT_SCOREBOARD_JSON,
    scoreboard_comparison_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    scoreboard_path = Path(scoreboard_json)
    payload = _read_json(scoreboard_path)
    rows = payload.get("project_rows") if isinstance(payload.get("project_rows"), list) else []
    continuation_input_refs = _continuation_input_refs(payload, scoreboard_path)
    pressure_context_by_project = _pressure_context_by_project(
        continuation_input_refs.get("effective_pressure_root")
    )
    deepening_policy = _public_source_deepening_policy(
        scoreboard_path=scoreboard_path,
        comparison_json=scoreboard_comparison_json,
    )
    local_authority_context_by_project = _local_authority_readback_context_by_project(payload)
    source_artifact_refs = _source_artifact_refs(payload, scoreboard_path)
    records = [
        _followup_record(
            row,
            scoreboard_ref=str(scoreboard_path),
            deepening_policy=deepening_policy,
            pressure_context=pressure_context_by_project.get(str(row.get("project_id") or "").strip(), {}),
            local_authority_context=local_authority_context_by_project.get(
                str(row.get("project_id") or "").strip(),
                {},
            ),
            source_artifact_refs=source_artifact_refs,
        )
        for row in rows
        if isinstance(row, Mapping) and _needs_backfill_followup(row)
    ]
    result = {
        "queue_kind": QUEUE_KIND,
        "queue_version": 1,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_refs": {
            "scoreboard_json": str(scoreboard_path),
            "scoreboard_comparison_json": str(scoreboard_comparison_json or ""),
        },
        "continuation_input_refs": continuation_input_refs,
        "summary": _summary(records),
        "public_source_deepening_policy": deepening_policy,
        "next_regression_execution_plan": _next_regression_execution_plan(
            records,
            deepening_policy,
            continuation_input_refs=continuation_input_refs,
        ),
        "records": records,
        "safety": {
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "live_execution_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
    }
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "stage4-backfill-followup-queue-v1.json", result)
    _write_markdown(out_dir / "stage4-backfill-followup-queue-v1.md", result)
    return result


def _needs_backfill_followup(row: Mapping[str, Any]) -> bool:
    local_authority_counts = _local_authority_executed_counts(row)
    if _int(local_authority_counts.get("BLOCKED")) or _int(local_authority_counts.get("NOT_FOUND")):
        return True
    if _needs_official_readback_stage4_bridge_followup(row):
        return True
    if str(row.get("p13b_original_notice_readback_state") or "").upper() == "BLOCKED":
        return True
    if str(row.get("p13b_ygp_original_readback_state") or "").upper() == "YGP_BLOCKED":
        return True
    if str(row.get("stage5_operational_review_bucket") or "") in {
        "PUBLIC_SOURCE_BLOCKED_REVIEW",
        "ORIGINAL_NOTICE_BLOCKED_REVIEW",
        "YGP_READBACK_BLOCKED_REVIEW",
    }:
        return True
    return (
        str(row.get("stage4_project_code_backfill_state") or "")
        == "MISSING_PROJECT_CODE_BACKFILL_INPUT"
        and bool(str(row.get("stage4_project_code_backfill_gap_detail") or "").strip())
    )


def _needs_official_readback_stage4_bridge_followup(row: Mapping[str, Any]) -> bool:
    if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE":
        return False
    if str(row.get("stage5_operational_primary_track") or "") != "official_readback_ready":
        return False
    if _int(row.get("p13b_ygp_stage4_release_adapter_task_count")) > 0:
        return True
    if _int(row.get("p13b_ygp_stage4_backfill_ready_count")) > 0:
        return True
    return bool(_list(row.get("p13b_ygp_project_code_variants")) or _list(row.get("p13b_overlap_ygp_project_code_variants")))


def _followup_record(
    row: Mapping[str, Any],
    *,
    scoreboard_ref: str,
    deepening_policy: Mapping[str, Any],
    pressure_context: Mapping[str, Any],
    local_authority_context: Mapping[str, Any],
    source_artifact_refs: list[str],
) -> dict[str, Any]:
    project_id = str(row.get("project_id") or "").strip()
    detail = _followup_gap_detail(row)
    route = _followup_route(detail)
    deepening_recommended = bool(deepening_policy.get("public_source_deepening_recommended"))
    pressure_context = _merge_scoreboard_source_context(row, pressure_context)
    local_authority_context = _local_authority_region_context(row, pressure_context, local_authority_context)
    data_ggzy_bid_show_urls = _dedupe(_list(row.get("p13b_data_ggzy_bid_show_urls")))
    data_ggzy_original_notice_urls = _dedupe(_list(row.get("p13b_data_ggzy_original_notice_urls")))
    data_ggzy_readback_payload_sha256s = _dedupe(
        _list(row.get("p13b_data_ggzy_readback_payload_sha256s"))
    )
    ygp_source_urls = _dedupe(
        [
            *_list(row.get("p13b_ygp_source_urls")),
            *_list(row.get("p13b_ygp_original_notice_urls")),
        ]
    )
    ygp_readback_payload_sha256s = _dedupe(
        [
            *_list(row.get("p13b_ygp_readback_payload_sha256s")),
            *_list(row.get("p13b_ygp_record_payload_sha256s")),
        ]
    )
    source_refs = _dedupe(
        [
            *_list(pressure_context.get("candidate_notice_source_urls")),
            *_list(pressure_context.get("project_source_urls")),
            *data_ggzy_bid_show_urls,
            *data_ggzy_original_notice_urls,
            *ygp_source_urls,
        ]
    )
    return {
        "followup_record_id": _stable_id("STAGE4-BACKFILL-FOLLOWUP", project_id, detail),
        "project_id": project_id,
        "project_name": str(row.get("project_name") or ""),
        "stage4_project_code_backfill_state": str(row.get("stage4_project_code_backfill_state") or ""),
        "stage4_project_code_backfill_gap_detail": detail,
        "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
        "p13b_public_source_readback_state": str(row.get("p13b_public_source_readback_state") or ""),
        "p13b_original_notice_readback_state": str(row.get("p13b_original_notice_readback_state") or ""),
        "p13b_overlap_triage_state": str(row.get("p13b_overlap_triage_state") or ""),
        "candidate_companies": _dedupe(_list(pressure_context.get("candidate_companies"))),
        "responsible_person_names": _dedupe(_list(pressure_context.get("responsible_person_names"))),
        "candidate_notice_source_urls": _dedupe(_list(pressure_context.get("candidate_notice_source_urls"))),
        "project_source_urls": _dedupe(_list(pressure_context.get("project_source_urls"))),
        "data_ggzy_bid_show_urls": data_ggzy_bid_show_urls,
        "data_ggzy_original_notice_urls": data_ggzy_original_notice_urls,
        "data_ggzy_bid_show_record_ids": _dedupe(
            _list(row.get("p13b_data_ggzy_bid_show_record_ids"))
        ),
        "data_ggzy_readback_payload_sha256s": data_ggzy_readback_payload_sha256s,
        "data_ggzy_extracted_responsible_person_names": _dedupe(
            _list(row.get("p13b_data_ggzy_extracted_responsible_person_names"))
        ),
        "ygp_source_urls": ygp_source_urls,
        "ygp_readback_payload_sha256s": ygp_readback_payload_sha256s,
        "ygp_node_id_variants": _dedupe(_list(row.get("p13b_ygp_node_id_variants"))),
        "source_refs": source_refs,
        "artifact_refs": source_artifact_refs,
        "context_source": str(pressure_context.get("context_source") or ""),
        "local_authority_readback_context": dict(local_authority_context),
        "stage4_official_readback_context": _stage4_official_readback_context(row),
        "alternate_local_authority_source_candidates": _alternate_local_authority_source_candidates(
            row,
            local_authority_context,
        ),
        "followup_route": route,
        "followup_queue_state": _followup_queue_state(route),
        "worker_family": _worker_family(route),
        "public_source_fallback_sequence": _public_source_fallback_sequence(row, route),
        "required_input": _required_input(route),
        "recommended_next_action": _recommended_next_action(route),
        "execution_priority": _execution_priority(route, deepening_recommended=deepening_recommended),
        "public_source_deepening_recommended": deepening_recommended,
        "public_source_deepening_decision": str(deepening_policy.get("decision") or ""),
        "recommended_budget_focus": list(deepening_policy.get("recommended_budget_focus") or []),
        "input_artifact_refs": source_artifact_refs or [scoreboard_ref],
        "controller_consumable": True,
        "customer_visible_allowed": False,
        "live_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _local_authority_region_context(
    row: Mapping[str, Any],
    pressure_context: Mapping[str, Any],
    local_authority_context: Mapping[str, Any],
) -> dict[str, Any]:
    context = dict(local_authority_context)
    if str(context.get("local_authority_region_code") or "").strip():
        return context
    inferred = _infer_local_authority_region_from_context(row, pressure_context)
    if not inferred:
        return context
    context["local_authority_region_code"] = inferred["region_code"]
    context["local_authority_region_basis"] = inferred["basis"]
    context["local_authority_region_evidence"] = inferred["evidence"]
    context["recommended_next_action"] = "run_project_local_authority_source_after_region_resolution"
    context["customer_visible_allowed"] = False
    context["query_miss_is_not_clearance"] = True
    context["no_legal_conclusion"] = True
    return context


def _infer_local_authority_region_from_context(
    row: Mapping[str, Any],
    pressure_context: Mapping[str, Any],
) -> dict[str, str]:
    values = [
        str(row.get("project_name") or ""),
        *[str(item or "") for item in _list(pressure_context.get("candidate_notice_source_urls"))],
        *[str(item or "") for item in _list(pressure_context.get("project_source_urls"))],
    ]
    marker_map = {
        "ywtb.gzggzy.cn": ("CN-GD-GZ", "current_candidate_trade_platform_domain"),
        "gzggzy.cn": ("CN-GD-GZ", "current_candidate_trade_platform_domain"),
        "广州": ("CN-GD-GZ", "project_name_or_source_url_city_marker"),
        "黄埔": ("CN-GD-GZ", "project_name_or_source_url_city_marker"),
        "南沙": ("CN-GD-GZ", "project_name_or_source_url_city_marker"),
        "白云": ("CN-GD-GZ", "project_name_or_source_url_city_marker"),
        "荔湾": ("CN-GD-GZ", "project_name_or_source_url_city_marker"),
        "阳江": ("CN-GD-YJ", "project_name_or_source_url_city_marker"),
        "阳东": ("CN-GD-YJ", "project_name_or_source_url_city_marker"),
        "阳西": ("CN-GD-YJ", "project_name_or_source_url_city_marker"),
        "中山": ("CN-GD-ZS", "project_name_or_source_url_city_marker"),
    }
    for value in values:
        lowered = value.lower()
        for marker, (region_code, basis) in marker_map.items():
            if marker.lower() in lowered:
                return {"region_code": region_code, "basis": basis, "evidence": value}
    return {}


def _followup_gap_detail(row: Mapping[str, Any]) -> str:
    local_authority_counts = _local_authority_executed_counts(row)
    if _int(local_authority_counts.get("BLOCKED")):
        return "LOCAL_AUTHORITY_BLOCKED_RETRY_OR_ALTERNATE_SOURCE_REQUIRED"
    if _int(local_authority_counts.get("NOT_FOUND")):
        return "LOCAL_AUTHORITY_NOT_FOUND_DEEPENING_REQUIRED"
    if _needs_official_readback_stage4_bridge_followup(row):
        return "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED"
    public_readback_state = str(row.get("p13b_public_source_readback_state") or "")
    if public_readback_state == "LOCAL_AUTHORITY_BLOCKED_REVIEW":
        return "LOCAL_AUTHORITY_BLOCKED_RETRY_OR_ALTERNATE_SOURCE_REQUIRED"
    if public_readback_state == "LOCAL_AUTHORITY_NOT_FOUND_REVIEW":
        return "LOCAL_AUTHORITY_NOT_FOUND_DEEPENING_REQUIRED"
    detail = str(row.get("stage4_project_code_backfill_gap_detail") or "").strip()
    if detail:
        return detail
    if str(row.get("p13b_ygp_original_readback_state") or "").upper() == "YGP_BLOCKED":
        return "YGP_READBACK_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"
    if str(row.get("p13b_original_notice_readback_state") or "").upper() == "BLOCKED":
        return "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED"
    bucket = str(row.get("stage5_operational_review_bucket") or "")
    if bucket == "PUBLIC_SOURCE_BLOCKED_REVIEW":
        return "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"
    if bucket == "ORIGINAL_NOTICE_BLOCKED_REVIEW":
        return "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED"
    if bucket == "YGP_READBACK_BLOCKED_REVIEW":
        return "YGP_READBACK_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED"
    return ""


def _local_authority_executed_counts(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("p13b_local_authority_executed_readback_state_counts")
    return value if isinstance(value, Mapping) else {}


def _stage4_official_readback_context(row: Mapping[str, Any]) -> dict[str, Any]:
    data_ggzy_bid_show_urls = _dedupe(_list(row.get("p13b_data_ggzy_bid_show_urls")))
    data_ggzy_original_notice_urls = _dedupe(_list(row.get("p13b_data_ggzy_original_notice_urls")))
    data_ggzy_readback_payload_sha256s = _dedupe(
        _list(row.get("p13b_data_ggzy_readback_payload_sha256s"))
    )
    ygp_source_urls = _dedupe(
        [
            *_list(row.get("p13b_ygp_source_urls")),
            *_list(row.get("p13b_ygp_original_notice_urls")),
        ]
    )
    ygp_readback_payload_sha256s = _dedupe(
        [
            *_list(row.get("p13b_ygp_readback_payload_sha256s")),
            *_list(row.get("p13b_ygp_record_payload_sha256s")),
        ]
    )
    return {
        "stage4_official_readback_context_state": (
            "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED"
            if _needs_official_readback_stage4_bridge_followup(row)
            else "DATA_GGZY_READBACK_FIXED_STAGE4_BACKFILL_INPUT_READY"
            if data_ggzy_bid_show_urls or data_ggzy_original_notice_urls
            else ""
        ),
        "project_id": str(row.get("project_id") or ""),
        "project_name": str(row.get("project_name") or ""),
        "stage5_operational_primary_track": str(row.get("stage5_operational_primary_track") or ""),
        "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
        "p13b_overlap_triage_state": str(row.get("p13b_overlap_triage_state") or ""),
        "ygp_project_code_variants": _dedupe(
            [
                *_list(row.get("p13b_ygp_project_code_variants")),
                *_list(row.get("p13b_overlap_ygp_project_code_variants")),
            ]
        ),
        "ygp_biz_code_variants": _dedupe(
            [
                *_list(row.get("p13b_ygp_biz_code_variants")),
                *_list(row.get("p13b_overlap_ygp_biz_code_variants")),
            ]
        ),
        "ygp_site_code_variants": _dedupe(
            [
                *_list(row.get("p13b_ygp_site_code_variants")),
                *_list(row.get("p13b_overlap_ygp_site_code_variants")),
            ]
        ),
        "ygp_notice_id_variants": _dedupe(
            [
                *_list(row.get("p13b_ygp_notice_id_variants")),
                *_list(row.get("p13b_overlap_ygp_notice_id_variants")),
            ]
        ),
        "data_ggzy_bid_show_urls": data_ggzy_bid_show_urls,
        "data_ggzy_original_notice_urls": data_ggzy_original_notice_urls,
        "data_ggzy_bid_show_record_ids": _dedupe(
            _list(row.get("p13b_data_ggzy_bid_show_record_ids"))
        ),
        "data_ggzy_readback_payload_sha256s": data_ggzy_readback_payload_sha256s,
        "data_ggzy_extracted_responsible_person_names": _dedupe(
            _list(row.get("p13b_data_ggzy_extracted_responsible_person_names"))
        ),
        "ygp_source_urls": ygp_source_urls,
        "ygp_readback_payload_sha256s": ygp_readback_payload_sha256s,
        "ygp_node_id_variants": _dedupe(_list(row.get("p13b_ygp_node_id_variants"))),
        "stage4_public_identifier_backfill_source": str(row.get("stage4_public_identifier_backfill_source") or ""),
        "gdcic_project_code_route_allowed": False,
        "gdcic_route_block_reason": "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
        "recommended_next_action": "feed_public_identifier_to_release_evidence_adapter_before_limited_review",
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _merge_scoreboard_source_context(
    row: Mapping[str, Any],
    pressure_context: Mapping[str, Any],
) -> dict[str, Any]:
    context = dict(pressure_context)
    context["candidate_companies"] = _dedupe(
        [
            *_list(context.get("candidate_companies")),
            *_list(row.get("p13b_candidate_companies")),
        ]
    )
    context["responsible_person_names"] = _dedupe(
        [
            *_list(context.get("responsible_person_names")),
            *_list(row.get("p13b_responsible_person_names")),
        ]
    )
    context["candidate_notice_source_urls"] = _dedupe(
        [
            *_list(context.get("candidate_notice_source_urls")),
            *_list(row.get("p13b_candidate_notice_source_urls")),
            *_list(row.get("p13b_ygp_candidate_notice_source_urls")),
        ]
    )
    context["project_source_urls"] = _dedupe(
        [
            *_list(context.get("project_source_urls")),
            *_list(row.get("p13b_project_source_urls")),
            *_list(row.get("p13b_ygp_project_source_urls")),
        ]
    )
    if not str(context.get("context_source") or "") and any(
        context.get(key)
        for key in (
            "candidate_companies",
            "responsible_person_names",
            "candidate_notice_source_urls",
            "project_source_urls",
        )
    ):
        context["context_source"] = "stage1_6_scoreboard_p13b_public_source_readback"
    return context


def _source_artifact_refs(payload: Mapping[str, Any], scoreboard_path: Path) -> list[str]:
    input_refs = payload.get("input_refs") if isinstance(payload.get("input_refs"), Mapping) else {}
    return _dedupe(
        [
            str(scoreboard_path),
            input_refs.get("release_field_query_json"),
            input_refs.get("p13b_company_history_json"),
            input_refs.get("p13b_original_notice_backtrace_json"),
            input_refs.get("p13b_ygp_original_readback_json"),
            input_refs.get("p13b_overlap_triage_closeout_json"),
        ]
    )


def _local_authority_readback_context_by_project(scoreboard_payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    input_refs = scoreboard_payload.get("input_refs") if isinstance(scoreboard_payload.get("input_refs"), Mapping) else {}
    p13b_path = _first_existing_path(
        input_refs.get("p13b_company_history_json"),
        _prior_scoreboard_input_refs(input_refs).get("p13b_company_history_json"),
    )
    if not p13b_path:
        return {}
    payload = _read_json(p13b_path)
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    records = manifest.get("local_authority_source_readback_records")
    by_project: dict[str, dict[str, Any]] = {}
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        by_project[project_id] = {
            "local_authority_region_code": str(record.get("local_authority_region_code") or ""),
            "source_profile_id": str(record.get("source_profile_id") or ""),
            "source_name": str(record.get("source_name") or ""),
            "source_url": str(record.get("source_url") or ""),
            "local_authority_readback_state": str(record.get("local_authority_readback_state") or ""),
            "http_status_code": _int(record.get("http_status_code")),
            "match_basis": str(record.get("match_basis") or ""),
            "blocker_taxonomy": _list(record.get("blocker_taxonomy")),
            "recommended_next_action": str(record.get("recommended_next_action") or ""),
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return by_project


def _alternate_local_authority_source_candidates(
    row: Mapping[str, Any],
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    region_code = str(context.get("local_authority_region_code") or "").upper()
    project_id = str(row.get("project_id") or "")
    common = {
        "project_id": project_id,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    if region_code == "CN-GD-GZ":
        return [
            {
                **common,
                "candidate_source_id": "gz_zfcj_construction_permit_public_api",
                "source_name": "广州市住房和城乡建设局 / 建筑工程施工许可证公示信息",
                "source_url": "https://zfcj.gz.gov.cn/zfcj/gczlaq/constructionPermitInformation/",
                "api_url": "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/sgxkxxlb.ashx",
                "recommended_query_mode": "specific_project_or_company_keyword_search",
            },
            {
                **common,
                "candidate_source_id": "gz_zfcj_completion_acceptance_public_api",
                "source_name": "广州市住房和城乡建设局 / 工程竣工验收信息",
                "source_url": "https://zfcj.gz.gov.cn/zfcj/gczlaq/completionAcceptance/",
                "api_url": "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/gcjgysxxlb.ashx",
                "recommended_query_mode": "specific_project_or_company_keyword_search",
            },
            {
                **common,
                "candidate_source_id": "gz_zfcj_credit_double_publicity",
                "source_name": "广州市住房和城乡建设局 / 信用信息双公示",
                "source_url": "https://zfcj.gz.gov.cn/zfcj/xyxx/",
                "api_url": "",
                "recommended_query_mode": "specific_search_endpoint_or_manual_source_path",
            },
        ]
    if region_code == "CN-GD-YJ":
        return [
            {
                **common,
                "candidate_source_id": "yj_zjj_govinfo_public_index",
                "source_name": "阳江市住房和城乡建设局 / 政府信息公开",
                "source_url": "https://www.yangjiang.gov.cn/yjzjj/gkmlpt/index",
                "api_url": "",
                "recommended_query_mode": "retry_official_index_or_choose_specific_column",
            },
            {
                **common,
                "candidate_source_id": "yj_zjj_official_site_search",
                "source_name": "阳江市住房和城乡建设局 / 站内公开搜索",
                "source_url": "https://www.yangjiang.gov.cn/yjzjj/",
                "api_url": "",
                "recommended_query_mode": "specific_project_or_company_keyword_search",
            },
        ]
    return [
        {
            **common,
            "candidate_source_id": "local_authority_region_resolution_required",
            "source_name": "项目所在地住建或主管部门公开入口待识别",
            "source_url": "",
            "api_url": "",
            "recommended_query_mode": "resolve_historical_project_jurisdiction_before_retry",
        }
    ]


def _followup_route(detail: str) -> str:
    if detail == "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED":
        return "official_readback_ready_stage4_bridge_followup"
    if detail == "LOCAL_AUTHORITY_BLOCKED_RETRY_OR_ALTERNATE_SOURCE_REQUIRED":
        return "local_authority_blocked_retry_or_alternate_source"
    if detail == "LOCAL_AUTHORITY_NOT_FOUND_DEEPENING_REQUIRED":
        return "local_authority_not_found_specific_endpoint_or_manual_source"
    if detail == "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED":
        return "public_source_retry_then_local_authority_fallback"
    if detail == "YGP_READBACK_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED":
        return "ygp_retry_then_local_authority_fallback"
    if detail in {
        "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
        "ORIGINAL_NOTICE_NOT_FOUND_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
        "GDCIC_IDENTIFIER_UNRESOLVED_AFTER_PUBLIC_BACKFILL_REQUIRED",
    }:
        return "local_authority_fallback_source_planning"
    if detail == "ORIGINAL_NOTICE_OR_SOURCE_LIMIT_DEFERRED_RETRY_REQUIRED":
        return "original_notice_retry_then_local_authority_fallback"
    if detail == "PUBLIC_SOURCE_READBACK_NOT_RUN_REQUIRED":
        return "public_source_readback_required"
    return "operator_classify_backfill_gap"


def _followup_queue_state(route: str) -> str:
    if route == "operator_classify_backfill_gap":
        return "OPERATOR_CLASSIFICATION_REQUIRED"
    return "FOLLOWUP_SOURCE_PLAN_REQUIRED"


def _worker_family(route: str) -> str:
    if route == "operator_classify_backfill_gap":
        return "operator_action"
    return "source_adapter"


def _required_input(route: str) -> list[str]:
    if route == "official_readback_ready_stage4_bridge_followup":
        return ["p13b_ygp_or_public_identifier_backfill_task", "stage4_release_adapter_bridge_or_ygp_backfill_field_query_budget"]
    if route == "local_authority_blocked_retry_or_alternate_source":
        return ["alternate_project_local_authority_source_url_or_adapter", "retry_budget_with_timeout_blocker_capture"]
    if route == "local_authority_not_found_specific_endpoint_or_manual_source":
        return ["specific_project_local_authority_search_endpoint_or_manual_source_path"]
    if route == "public_source_retry_then_local_authority_fallback":
        return ["public_source_retry_budget_or_project_local_authority_adapter"]
    if route == "ygp_retry_then_local_authority_fallback":
        return ["ygp_retry_budget_or_project_local_authority_adapter"]
    if route == "original_notice_retry_then_local_authority_fallback":
        return ["original_notice_retry_budget_or_project_local_authority_adapter"]
    if route == "public_source_readback_required":
        return ["public_source_readback_budget"]
    if route == "operator_classify_backfill_gap":
        return ["operator_classification_reason"]
    return ["data_ggzy_bid_show_or_ygp_backfill_input", "project_local_authority_source_url_or_adapter"]


def _public_source_fallback_sequence(row: Mapping[str, Any], route: str) -> list[dict[str, Any]]:
    if route == "official_readback_ready_stage4_bridge_followup":
        return [
            _fallback_step("ygp_original_notice_readback", "read_ygp_original_notice_identifiers_for_p13b_or_stage4_bridge", row),
            _fallback_step("stage4_release_adapter_bridge", "feed_public_identifier_to_release_evidence_adapter_before_limited_review", row),
            _fallback_step("stage6_limited_sellable_projection", "project_b_or_c_official_readback_to_internal_limited_review", row),
        ]
    return [
        _fallback_step(
            "data_ggzy_company_history_search",
            "search_data_ggzy_company_history_before_local_authority_fallback",
            row,
        ),
        _fallback_step("data_ggzy_bid_list_pagination", "page_bid_list_with_bounded_budget", row),
        _fallback_step("data_ggzy_bid_show_readback", "read_bid_show_text_and_original_notice_url", row),
        _fallback_step("ygp_original_notice_readback", "read_ygp_original_notice_identifiers_for_p13b_or_stage4_bridge", row),
        _fallback_step(
            "project_local_authority_public_source",
            "query_historical_project_location_housing_or_supervisory_authority",
            row,
        ),
    ] if route != "operator_classify_backfill_gap" else []


def _fallback_step(source_kind: str, action: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "action": action,
        "project_id": str(row.get("project_id") or ""),
        "input_state": _fallback_input_state(source_kind, row),
        "gdcic_project_code_route_allowed": False,
        "gdcic_project_code_route_policy": "PUBLIC_SOURCE_IDENTIFIER_NOT_SENT_TO_GDCIC_UNLESS_EXPLICIT_PROVINCIAL_CODE",
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _fallback_input_state(source_kind: str, row: Mapping[str, Any]) -> str:
    if source_kind == "stage4_release_adapter_bridge":
        if _int(row.get("p13b_ygp_stage4_release_adapter_task_count")) > 0:
            return "P13B_RELEASE_ADAPTER_TASK_READY"
        if _int(row.get("p13b_ygp_stage4_backfill_ready_count")) > 0:
            return "YGP_STAGE4_BACKFILL_READY"
        return "PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE"
    if source_kind == "stage6_limited_sellable_projection":
        if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE":
            return "LIMITED_SELLABLE_REVIEW_ALREADY_PROJECTED"
        return "LIMITED_SELLABLE_REVIEW_PROJECTION_REQUIRED"
    if source_kind == "data_ggzy_bid_show_readback":
        if int(row.get("p13b_bid_show_original_notice_url_count") or 0) > 0:
            return "BID_SHOW_ORIGINAL_NOTICE_URL_PRESENT"
        if int(row.get("p13b_bid_show_responsible_person_present_count") or 0) > 0:
            return "BID_SHOW_RESPONSIBLE_PERSON_PRESENT"
    if source_kind == "ygp_original_notice_readback":
        if row.get("p13b_ygp_original_readback_state") == "YGP_READBACK_READY":
            return "YGP_READBACK_READY"
        if row.get("p13b_ygp_project_code_variants"):
            return "YGP_IDENTIFIER_PRESENT"
    if source_kind == "project_local_authority_public_source":
        return "LOCAL_AUTHORITY_FALLBACK_REQUIRED"
    return "INPUT_REQUIRED_OR_RETRY_WITH_BUDGET"


def _pressure_context_by_project(pressure_root: Any) -> dict[str, dict[str, Any]]:
    root = Path(str(pressure_root or ""))
    if not str(pressure_root or "").strip() or not root.exists():
        return {}
    plan = _read_json(root / "stage4-release-adapter-bridge-plan.json")
    contexts: dict[str, dict[str, Any]] = {}
    records = [
        *_list(plan.get("release_evidence_adapter_task_records")),
        *_list(plan.get("project_code_backfill_records")),
    ]
    for record in records:
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        query_params = record.get("query_params") if isinstance(record.get("query_params"), Mapping) else {}
        context = contexts.setdefault(
            project_id,
            {
                "candidate_companies": [],
                "responsible_person_names": [],
                "candidate_notice_source_urls": [],
                "project_source_urls": [],
                "context_source": "stage4_release_adapter_bridge_plan",
            },
        )
        context["candidate_companies"] = _dedupe(
            [
                *context.get("candidate_companies", []),
                record.get("candidate_company_name"),
                query_params.get("candidateCompanyName"),
                query_params.get("companyName"),
                *_list(query_params.get("companyVariants")),
            ]
        )
        context["responsible_person_names"] = _dedupe(
            [
                *context.get("responsible_person_names", []),
                record.get("raw_person_name"),
                *_list(record.get("matched_person_names")),
                query_params.get("personName"),
                query_params.get("projectManagerName"),
                query_params.get("rawPersonName"),
            ]
        )
        context["candidate_notice_source_urls"] = _dedupe(
            [
                *context.get("candidate_notice_source_urls", []),
                record.get("trigger_source_url"),
                query_params.get("triggerSourceUrl"),
            ]
        )
        context["project_source_urls"] = _dedupe(
            [
                *context.get("project_source_urls", []),
                record.get("trigger_source_url"),
                query_params.get("triggerSourceUrl"),
            ]
        )
    return contexts


def _recommended_next_action(route: str) -> str:
    actions = {
        "official_readback_ready_stage4_bridge_followup": "feed_public_identifier_to_release_evidence_adapter_before_limited_review",
        "local_authority_blocked_retry_or_alternate_source": "retry_blocked_local_authority_source_or_choose_alternate_official_entry_without_clearance_claim",
        "local_authority_not_found_specific_endpoint_or_manual_source": "keep_not_found_as_non_clearance_and_try_specific_search_endpoint_or_manual_source_path",
        "public_source_retry_then_local_authority_fallback": "retry_public_source_or_route_to_project_local_authority_without_clearance_claim",
        "local_authority_fallback_source_planning": "plan_project_local_authority_readback_without_treating_not_found_as_clearance",
        "original_notice_retry_then_local_authority_fallback": "retry_original_notice_or_route_to_project_local_authority_without_clearance_claim",
        "ygp_retry_then_local_authority_fallback": "retry_ygp_readback_or_route_to_project_local_authority_without_clearance_claim",
        "public_source_readback_required": "run_public_source_readback_before_any_clearance_claim",
        "operator_classify_backfill_gap": "operator_classifies_backfill_gap_before_retry",
    }
    return actions.get(route, "operator_reviews_stage4_backfill_gap")


def _execution_priority(route: str, *, deepening_recommended: bool) -> str:
    if route == "official_readback_ready_stage4_bridge_followup":
        return "HIGH_STAGE4_BRIDGE_PROMOTION" if deepening_recommended else "NORMAL_STAGE4_BRIDGE_PROMOTION"
    if not deepening_recommended:
        return "NORMAL"
    if route in {
        "local_authority_blocked_retry_or_alternate_source",
        "public_source_retry_then_local_authority_fallback",
        "original_notice_retry_then_local_authority_fallback",
        "ygp_retry_then_local_authority_fallback",
        "public_source_readback_required",
    }:
        return "HIGH_PUBLIC_SOURCE_DEEPENING"
    if route in {
        "local_authority_fallback_source_planning",
        "local_authority_not_found_specific_endpoint_or_manual_source",
    }:
        return "MEDIUM_LOCAL_AUTHORITY_FALLBACK"
    return "NORMAL_OPERATOR_REVIEW"


def _public_source_deepening_policy(
    *,
    scoreboard_path: Path,
    comparison_json: str | Path | None,
) -> dict[str, Any]:
    run_label = _run_label(scoreboard_path)
    default = {
        "run_label": run_label,
        "public_source_deepening_recommended": False,
        "decision": "NO_COMPARISON_RECOMMENDATION",
        "recommended_budget_focus": [],
        "comparison_json": str(comparison_json or ""),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    if not comparison_json:
        return default
    comparison_path = Path(comparison_json)
    comparison = _read_json(comparison_path)
    recommendations = comparison.get("public_source_deepening_recommendations")
    if not isinstance(recommendations, list):
        return default
    for recommendation in recommendations:
        if not isinstance(recommendation, Mapping):
            continue
        if str(recommendation.get("run_label") or "") != run_label:
            continue
        if str(recommendation.get("decision") or "") != "CONTINUE_PUBLIC_SOURCE_DEEPENING":
            continue
        return {
            "run_label": run_label,
            "previous_run_label": str(recommendation.get("previous_run_label") or ""),
            "public_source_deepening_recommended": True,
            "decision": "CONTINUE_PUBLIC_SOURCE_DEEPENING",
            "reason": str(recommendation.get("reason") or ""),
            "recommended_budget_focus": list(recommendation.get("recommended_budget_focus") or []),
            "comparison_json": str(comparison_path),
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "gdcic_project_code_digit_guessing_allowed": False,
        }
    return default


def _continuation_input_refs(payload: Mapping[str, Any], scoreboard_path: Path) -> dict[str, Any]:
    input_refs = payload.get("input_refs") if isinstance(payload.get("input_refs"), Mapping) else {}
    prior_input_refs = _prior_scoreboard_input_refs(input_refs)
    pressure_root = _root_with_required_sibling(
        input_refs,
        keys=["pressure_summary_json", "stage1_6_readiness_json", "stage1_6_gap_summary_json"],
        required_sibling="stage4-release-adapter-bridge-plan.json",
    ) or _root_with_required_sibling(
        prior_input_refs,
        keys=["pressure_summary_json", "stage1_6_readiness_json", "stage1_6_gap_summary_json"],
        required_sibling="stage4-release-adapter-bridge-plan.json",
    )
    release_field_query_root = _parent_if_file_exists(input_refs.get("release_field_query_json")) or _parent_if_file_exists(
        prior_input_refs.get("release_field_query_json")
    )
    supplemental_release_field_query_json = input_refs.get("supplemental_release_field_query_json")
    supplemental_release_field_query_root = _parent_if_file_exists(supplemental_release_field_query_json)
    gdcic_readback_root = _parent_if_file_exists(input_refs.get("gdcic_browser_authorized_readback_json"))
    stage6_status_root = _parent_if_file_exists(input_refs.get("stage6_status_json")) or _parent_if_file_exists(
        prior_input_refs.get("stage6_status_json")
    )
    return {
        "prior_scoreboard_json": str(scoreboard_path),
        "effective_pressure_root": pressure_root,
        "effective_release_field_query_root": release_field_query_root,
        "effective_supplemental_release_field_query_json": str(supplemental_release_field_query_json or ""),
        "effective_supplemental_release_field_query_root": supplemental_release_field_query_root,
        "effective_gdcic_browser_readback_root": gdcic_readback_root,
        "effective_stage6_status_root": stage6_status_root,
        "pressure_root_resolution_state": "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if pressure_root else "UNRESOLVED",
        "release_field_query_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if release_field_query_root else "UNRESOLVED"
        ),
        "supplemental_release_field_query_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if supplemental_release_field_query_root else "UNRESOLVED"
        ),
        "gdcic_browser_readback_root_resolution_state": (
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS" if gdcic_readback_root else "UNRESOLVED"
        ),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _prior_scoreboard_input_refs(input_refs: Mapping[str, Any]) -> Mapping[str, Any]:
    prior_scoreboard = str(input_refs.get("prior_scoreboard_json") or "").strip()
    if not prior_scoreboard:
        return {}
    payload = _read_json(Path(prior_scoreboard))
    refs = payload.get("input_refs") if isinstance(payload.get("input_refs"), Mapping) else {}
    return refs


def _root_with_required_sibling(input_refs: Mapping[str, Any], *, keys: list[str], required_sibling: str) -> str:
    for key in keys:
        root = _parent_if_file_exists(input_refs.get(key))
        if root and (Path(root) / required_sibling).exists():
            return root
    return ""


def _parent_if_file_exists(value: Any) -> str:
    path_text = str(value or "").strip()
    if not path_text:
        return ""
    path = Path(path_text)
    if path.exists() and path.is_file():
        return str(path.parent)
    return ""


def _first_existing_path(*values: Any) -> Path | None:
    for value in values:
        path_text = str(value or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if path.exists() and path.is_file():
            return path
    return None


def _summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "followup_record_count": len(records),
        "project_count": len({str(record.get("project_id") or "") for record in records if record.get("project_id")}),
        "followup_route_counts": _counts(record.get("followup_route") for record in records),
        "followup_queue_state_counts": _counts(record.get("followup_queue_state") for record in records),
        "gap_detail_counts": _counts(record.get("stage4_project_code_backfill_gap_detail") for record in records),
        "worker_family_counts": _counts(record.get("worker_family") for record in records),
        "execution_priority_counts": _counts(record.get("execution_priority") for record in records),
        "public_source_deepening_recommended_counts": _counts(
            str(bool(record.get("public_source_deepening_recommended"))).lower() for record in records
        ),
        "customer_visible_allowed": False,
        "live_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _next_regression_execution_plan(
    records: list[Mapping[str, Any]],
    deepening_policy: Mapping[str, Any],
    *,
    continuation_input_refs: Mapping[str, Any],
) -> dict[str, Any]:
    high_count = sum(
        1 for record in records if record.get("execution_priority") == "HIGH_PUBLIC_SOURCE_DEEPENING"
    )
    medium_count = sum(
        1 for record in records if record.get("execution_priority") == "MEDIUM_LOCAL_AUTHORITY_FALLBACK"
    )
    official_bridge_count = sum(
        1 for record in records if record.get("followup_route") == "official_readback_ready_stage4_bridge_followup"
    )
    target_project_ids = [
        str(record.get("project_id") or "")
        for record in records
        if record.get("followup_route") != "operator_classify_backfill_gap"
    ]
    if not records:
        return {
            "plan_state": "NO_FOLLOWUP_RECORDS",
            "target_project_ids": [],
            "recommended_parameter_overrides": {},
            "runner_entrypoint": "scripts/run-stage1-6-sellable-rate-regression-v1.ps1",
            "continuation_input_refs": dict(continuation_input_refs),
            "customer_visible_allowed": False,
            "live_execution_enabled_by_default": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
    plan_state = (
        "PUBLIC_SOURCE_DEEPENING_RUN_RECOMMENDED"
        if deepening_policy.get("public_source_deepening_recommended")
        else "FOLLOWUP_SOURCE_PLAN_ONLY"
    )
    p13b_company_budget = max(8, high_count * 3 + medium_count)
    original_notice_budget = max(12, high_count * 4 + medium_count * 2)
    ygp_notice_budget = max(8, high_count * 3)
    ygp_backfill_budget = max(8, high_count * 3, official_bridge_count + 3)
    return {
        "plan_state": plan_state,
        "runner_entrypoint": "scripts/run-stage1-6-sellable-rate-regression-v1.ps1",
        "continuation_input_refs": dict(continuation_input_refs),
        "target_project_ids": target_project_ids,
        "target_project_count": len(target_project_ids),
        "public_source_fallback_sequence": [
            "data_ggzy_company_history_search",
            "data_ggzy_bid_list_pagination",
            "data_ggzy_bid_show_readback",
            "ygp_original_notice_readback",
            "project_local_authority_public_source",
        ],
        "recommended_switches": [
            "RunP13BPublicSourceChain",
            "RunYgpBackfillFieldQuery",
            "RunStage6MergedProjection",
        ],
        "recommended_parameter_overrides": {
            "MaxLiveP13BCompanies": p13b_company_budget,
            "MaxBidRecordsPerCompany": 3,
            "MaxBidListPagesPerCompany": 2,
            "MaxLongTailBidShowsPerCompany": 1,
            "MaxLiveOriginalNotices": original_notice_budget,
            "MaxLiveYgpOriginalNotices": ygp_notice_budget,
            "MaxLiveYgpBackfillTasks": ygp_backfill_budget,
        },
        "operator_live_public_query_decision_required": True,
        "default_execution_mode": "PLAN_OR_EXISTING_ARTIFACT_REPLAY",
        "live_execution_enabled_by_default": False,
        "recommended_budget_focus": list(deepening_policy.get("recommended_budget_focus") or []),
        "safety_invariants": {
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "gdcic_project_code_digit_guessing_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
        },
    }


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in _list(values):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _stable_id(prefix: str, *parts: Any) -> str:
    import hashlib

    payload = json.dumps([str(part or "") for part in parts], ensure_ascii=False, sort_keys=True)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _run_label(path: Path) -> str:
    parts = list(path.parts)
    if "tmp" in parts and "evaluation-real-samples" in parts:
        idx = parts.index("evaluation-real-samples")
        if len(parts) > idx + 1:
            return parts[idx + 1]
    if path.parent.name == "scoreboard":
        return path.parent.parent.name
    return path.parent.name


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Stage4 Backfill Follow-up Queue v1",
        "",
        f"- followup_record_count: {summary.get('followup_record_count', 0)}",
        f"- gap_detail_counts: {json.dumps(summary.get('gap_detail_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- followup_route_counts: {json.dumps(summary.get('followup_route_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- execution_priority_counts: {json.dumps(summary.get('execution_priority_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- public_source_deepening_policy: {json.dumps(payload.get('public_source_deepening_policy', {}), ensure_ascii=False, sort_keys=True)}",
        f"- next_regression_execution_plan: {json.dumps(payload.get('next_regression_execution_plan', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "customer_visible_allowed=false; live_execution_enabled=false; query_miss_is_not_clearance=true; no_legal_conclusion=true",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scoreboard-json", default=str(DEFAULT_SCOREBOARD_JSON))
    parser.add_argument("--scoreboard-comparison-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_stage4_backfill_followup_queue(
        scoreboard_json=args.scoreboard_json,
        scoreboard_comparison_json=args.scoreboard_comparison_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result.get("summary") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
