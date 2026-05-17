from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


PRODUCT_ANALYSIS_STRATEGY_PLAN_MANIFEST_KIND = "product_analysis_strategy_plan_manifest"
PRODUCT_ANALYSIS_STRATEGY_PLAN_VERSION = 1
PRODUCT_ANALYSIS_STRATEGY_PLAN_ADAPTER_ID = "product-analysis-strategy-plan-builder"
RUNTIME_PRODUCT_ANALYSIS_STRATEGY_SOURCE_KIND = "RUNTIME_FORMAL_STAGE2_SOURCE"

POST_CANDIDATE_EVIDENCE_PACK = "POST_CANDIDATE_EVIDENCE_PACK"
POST_OPENING_EVIDENCE_TRACK = "POST_OPENING_EVIDENCE_TRACK"
PRE_BID_PREDICTION = "PRE_BID_PREDICTION"
WATCHLIST_ONLY = "WATCHLIST_ONLY"
ADAPTER_VALIDATION_ONLY = "ADAPTER_VALIDATION_ONLY"

POST_CANDIDATE_READY = "POST_CANDIDATE_READY"
HISTORICAL_OR_LATE_STAGE_REVIEW = "HISTORICAL_OR_LATE_STAGE_REVIEW"
PRE_BID_NOT_ELIGIBLE_OPENING_STARTED = "PRE_BID_NOT_ELIGIBLE_OPENING_STARTED"
PRE_BID_NOT_ELIGIBLE_DEADLINE_PASSED = "PRE_BID_NOT_ELIGIBLE_DEADLINE_PASSED"
PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE = "PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE"
PRE_BID_STANDARD_PREDICTION_READY = "PRE_BID_STANDARD_PREDICTION_READY"
PRE_BID_LIMITED_FAST_REVIEW = "PRE_BID_LIMITED_FAST_REVIEW"
TIME_WINDOW_UNKNOWN_REVIEW = "TIME_WINDOW_UNKNOWN_REVIEW"
PREDICTION_BEFORE_CLARIFICATION = "PREDICTION_BEFORE_CLARIFICATION"
PREDICTION_AFTER_CLARIFICATION = "PREDICTION_AFTER_CLARIFICATION"

DOWNLOAD_SKIP = "SKIP"
PARSE_NONE = "NONE"
CN_TZ = timezone(timedelta(hours=8))

FLOW_MODULES = {
    "01": {"flow_title": "招标计划", "document_kind": "bid_plan"},
    "02": {"flow_title": "招标文件公示", "document_kind": "tender_file_publicity"},
    "03": {"flow_title": "招标公告/关联公告", "document_kind": "tender_file"},
    "04": {"flow_title": "澄清答疑", "document_kind": "clarification_notice"},
    "05": {"flow_title": "开标信息", "document_kind": "opening_info"},
    "06": {"flow_title": "资审结果公示", "document_kind": "qualification_review_result"},
    "07": {"flow_title": "中标候选人公示", "document_kind": "candidate_notice"},
    "08": {"flow_title": "投标(资格预审申请)文件公开", "document_kind": "bid_file_publicity"},
    "09": {"flow_title": "中标结果公示/公告", "document_kind": "award_result"},
    "10": {"flow_title": "中标信息", "document_kind": "award_info"},
    "11": {"flow_title": "合同信息公开", "document_kind": "contract_public_info"},
    "12": {"flow_title": "项目异常", "document_kind": "project_exception"},
}

DOCUMENT_KIND_TO_FLOW = {
    "bid_plan": "01",
    "tender_plan": "01",
    "procurement_intention": "01",
    "tender_file_publicity": "02",
    "tender_file": "03",
    "tender_notice": "03",
    "clarification_notice": "04",
    "clarification_or_addendum": "04",
    "opening_info": "05",
    "opening_record": "05",
    "qualification_review_result": "06",
    "qualification_pre_review": "06",
    "candidate_notice": "07",
    "evaluation_result": "07",
    "bid_file_publicity": "08",
    "award_result": "09",
    "award_notice": "09",
    "award_info": "10",
    "contract_public_info": "11",
    "project_exception": "12",
    "failed_bid_notice": "12",
}

POST_CANDIDATE_FALLBACK_POLICIES = {
    "01": {
        "download_policy": "METADATA_ONLY",
        "parse_depth": "METADATA_ONLY",
        "index_targets": ["watchlist_signal"],
    },
    "02": {
        "download_policy": "LIST_OR_DOWNLOAD_IF_DOCUMENT_PRESENT",
        "parse_depth": "TEXT_PROBE",
        "index_targets": ["document_completeness_gap"],
    },
    "09": {
        "download_policy": "LIST_OR_DOWNLOAD_IF_ATTACHMENT_PRESENT",
        "parse_depth": "TEXT_PROBE",
        "index_targets": ["candidate_verification", "sales_leadpack_handoff"],
    },
    "10": {
        "download_policy": "METADATA_ONLY",
        "parse_depth": "METADATA_ONLY",
        "index_targets": ["candidate_verification", "sales_leadpack_handoff"],
    },
    "11": {
        "download_policy": "METADATA_ONLY",
        "parse_depth": "METADATA_ONLY",
        "index_targets": ["contract_result_verification"],
    },
    "12": {
        "download_policy": "LIST_OR_DOWNLOAD_IF_PRESENT",
        "parse_depth": "TEXT_PROBE",
        "index_targets": ["procedure_abnormality_index"],
    },
}


def build_product_analysis_strategy_plan(
    *,
    real_sample_execution_manifest_json: str | Path,
    project_file_audit_json: str | Path | None = None,
    business_direction_contract_json: str | Path | None = None,
    output_json: str | Path | None = None,
    created_at: str | None = None,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    now_dt = _coerce_datetime(now) or _coerce_datetime(created) or datetime.now(tz=CN_TZ)
    run_path = Path(real_sample_execution_manifest_json)
    audit_path = Path(project_file_audit_json) if project_file_audit_json else None
    contract_path = (
        Path(business_direction_contract_json)
        if business_direction_contract_json
        else Path("contracts/evaluation/business_direction_strategy_contract.json")
    )
    blocking_reasons: list[str] = []
    run_payload = _load_json_optional(run_path, blocking_reasons, "real_sample_execution_manifest_missing")
    audit_payload = _load_json_optional(audit_path, blocking_reasons, "project_file_audit_missing") if audit_path else {}
    contract = _load_json_optional(contract_path, blocking_reasons, "business_direction_contract_missing")
    run_manifest = _source_manifest(run_payload)
    audit_manifest = _source_manifest(audit_payload)
    policy = contract.get("analysis_strategy_policy") if isinstance(contract.get("analysis_strategy_policy"), Mapping) else {}

    contexts = _project_contexts(run_manifest=run_manifest, audit_manifest=audit_manifest)
    project_strategy_items: list[dict[str, Any]] = []
    strategy_items: list[dict[str, Any]] = []
    for context in contexts:
        project_strategy = _project_strategy(context=context, now=now_dt)
        project_strategy_items.append(project_strategy)
        strategy_items.extend(
            _strategy_item(source=item, project_strategy=project_strategy, policy=policy)
            for item in context["items"]
        )

    summary = _summary(
        project_strategy_items=project_strategy_items,
        strategy_items=strategy_items,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": PRODUCT_ANALYSIS_STRATEGY_PLAN_VERSION,
        "manifest_kind": PRODUCT_ANALYSIS_STRATEGY_PLAN_MANIFEST_KIND,
        "adapter_id": PRODUCT_ANALYSIS_STRATEGY_PLAN_ADAPTER_ID,
        "manifest_id": f"PRODUCT-ANALYSIS-STRATEGY-{_fingerprint({'projects': project_strategy_items, 'items': strategy_items})[:16]}",
        "created_at": created,
        "now_reference_at": now_dt.isoformat(),
        "source_real_sample_execution_manifest_path": str(run_path),
        "source_project_file_audit_path": str(audit_path or ""),
        "business_direction_contract_path": str(contract_path),
        "strategy_policy_id": str(policy.get("policy_id") or "ANALYSIS-STRATEGY-PLAN-V1"),
        "strategy_policy_version": _int(policy.get("policy_version")) or 1,
        "project_strategy_items": project_strategy_items,
        "items": strategy_items,
        "sample_items": strategy_items[:80],
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "parse_enabled": False,
            "llm_execution_enabled": False,
            "database_write_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    result = {
        "product_analysis_strategy_plan_mode": "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    if output_json:
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_runtime_product_analysis_strategy_plan(
    *,
    public_chain: Mapping[str, Any],
    clock_chain_profile: Mapping[str, Any],
    notice_version_chain: Mapping[str, Any],
    fixation_bundle: Mapping[str, Any],
    inputs: Mapping[str, Any],
    business_direction_contract_json: str | Path | None = None,
    created_at: str | None = None,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    now_dt = _coerce_datetime(now) or _coerce_datetime(created) or datetime.now(tz=CN_TZ)
    contract_path = (
        Path(business_direction_contract_json)
        if business_direction_contract_json
        else Path("contracts/evaluation/business_direction_strategy_contract.json")
    )
    blocking_reasons: list[str] = []
    contract = _load_json_optional(contract_path, blocking_reasons, "business_direction_contract_missing")
    policy = contract.get("analysis_strategy_policy") if isinstance(contract.get("analysis_strategy_policy"), Mapping) else {}

    source_row = _runtime_source_row(
        public_chain=public_chain,
        clock_chain_profile=clock_chain_profile,
        notice_version_chain=notice_version_chain,
        fixation_bundle=fixation_bundle,
        inputs=inputs,
    )
    context = {
        "project_id": str(source_row.get("project_id") or ""),
        "project_name": str(source_row.get("project_name") or ""),
        "run_stage": str(source_row.get("pipeline_stage") or ""),
        "first": dict(source_row),
        "run_samples": [dict(source_row)],
        "audit_item": {},
        "items": [dict(source_row)],
    }
    project_strategy = _project_strategy(context=context, now=now_dt)
    strategy_item = _strategy_item(
        source=source_row,
        project_strategy=project_strategy,
        policy=policy,
    )

    if blocking_reasons:
        project_strategy["product_mode"] = WATCHLIST_ONLY
        project_strategy["strategy_state"] = TIME_WINDOW_UNKNOWN_REVIEW
        strategy_item.update(
            {
                "product_mode": WATCHLIST_ONLY,
                "strategy_state": TIME_WINDOW_UNKNOWN_REVIEW,
                "download_policy": DOWNLOAD_SKIP,
                "download_required": False,
                "parse_depth": PARSE_NONE,
                "parse_required": False,
                "llm_allowed": False,
                "llm_trigger_reasons": [],
                "skip_reason": blocking_reasons[0],
                "index_targets": [],
            }
        )

    if not str(strategy_item.get("flow_no") or "").strip() and not str(strategy_item.get("document_kind") or "").strip():
        project_strategy["product_mode"] = WATCHLIST_ONLY
        project_strategy["strategy_state"] = TIME_WINDOW_UNKNOWN_REVIEW
        strategy_item.update(
            {
                "product_mode": WATCHLIST_ONLY,
                "strategy_state": TIME_WINDOW_UNKNOWN_REVIEW,
                "download_policy": DOWNLOAD_SKIP,
                "download_required": False,
                "parse_depth": PARSE_NONE,
                "parse_required": False,
                "llm_allowed": False,
                "llm_trigger_reasons": [],
                "skip_reason": "analysis_strategy_missing_flow_or_document_kind",
                "index_targets": [],
            }
        )

    identity_payload = {
        "project_id": project_strategy.get("project_id"),
        "flow_no": strategy_item.get("flow_no"),
        "document_kind": strategy_item.get("document_kind"),
        "product_mode": strategy_item.get("product_mode"),
        "strategy_state": strategy_item.get("strategy_state"),
        "download_policy": strategy_item.get("download_policy"),
        "parse_depth": strategy_item.get("parse_depth"),
        "pipeline_stage": source_row.get("pipeline_stage"),
        "source_url": source_row.get("source_url"),
    }
    return {
        "analysis_strategy_plan_id": f"ANALYSIS-STRATEGY-{_fingerprint(identity_payload)[:16]}",
        "project_id": str(project_strategy.get("project_id") or ""),
        "product_mode": str(strategy_item.get("product_mode") or ""),
        "strategy_state": str(strategy_item.get("strategy_state") or ""),
        "flow_no": str(strategy_item.get("flow_no") or "UNKNOWN"),
        "document_kind": str(strategy_item.get("document_kind") or "UNKNOWN"),
        "download_policy": str(strategy_item.get("download_policy") or DOWNLOAD_SKIP),
        "download_required": bool(strategy_item.get("download_required")),
        "parse_depth": str(strategy_item.get("parse_depth") or PARSE_NONE),
        "parse_required": bool(strategy_item.get("parse_required")),
        "rules_first": bool(strategy_item.get("rules_first", True)),
        "llm_allowed": bool(strategy_item.get("llm_allowed")),
        "llm_trigger_reasons": [str(item) for item in list(strategy_item.get("llm_trigger_reasons") or [])],
        "skip_reason": str(strategy_item.get("skip_reason") or "NOT_SKIPPED"),
        "index_targets": [str(item) for item in list(strategy_item.get("index_targets") or [])],
        "adapter_validation_only": bool(strategy_item.get("adapter_validation_only")),
        "current_sales_window_entry_flow_no": str(
            strategy_item.get("current_sales_window_entry_flow_no")
            or project_strategy.get("current_sales_window_entry_flow_no")
            or "NOT_APPLICABLE"
        ),
        "pre_bid_clarification_state": str(
            strategy_item.get("pre_bid_clarification_state")
            or project_strategy.get("pre_bid_clarification_state")
            or "NOT_APPLICABLE"
        ),
        "prediction_recalc_required_on_new_flow_04": bool(
            strategy_item.get("prediction_recalc_required_on_new_flow_04")
            or project_strategy.get("prediction_recalc_required_on_new_flow_04")
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def build_runtime_analysis_strategy_h02_projection(
    analysis_strategy_plan: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "analysis_strategy_plan_id": str(
            analysis_strategy_plan.get("analysis_strategy_plan_id") or ""
        ),
        "analysis_strategy_product_mode": str(
            analysis_strategy_plan.get("product_mode") or ""
        ),
        "analysis_strategy_state": str(
            analysis_strategy_plan.get("strategy_state") or ""
        ),
        "analysis_strategy_flow_no": str(
            analysis_strategy_plan.get("flow_no") or ""
        ),
        "analysis_strategy_document_kind": str(
            analysis_strategy_plan.get("document_kind") or ""
        ),
        "analysis_strategy_download_policy": str(
            analysis_strategy_plan.get("download_policy") or DOWNLOAD_SKIP
        ),
        "analysis_strategy_parse_depth": str(
            analysis_strategy_plan.get("parse_depth") or PARSE_NONE
        ),
        "analysis_strategy_parse_required": bool(
            analysis_strategy_plan.get("parse_required")
        ),
        "analysis_strategy_rules_first": bool(
            analysis_strategy_plan.get("rules_first", True)
        ),
        "analysis_strategy_llm_allowed": bool(
            analysis_strategy_plan.get("llm_allowed")
        ),
        "analysis_strategy_skip_reason": str(
            analysis_strategy_plan.get("skip_reason") or ""
        ),
        "analysis_strategy_adapter_validation_only": bool(
            analysis_strategy_plan.get("adapter_validation_only")
        ),
        "analysis_strategy_index_targets": [
            str(item)
            for item in list(analysis_strategy_plan.get("index_targets") or [])
        ],
    }


def _project_contexts(*, run_manifest: Mapping[str, Any], audit_manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    run_stage = str(run_manifest.get("pipeline_stage") or "")
    sample_items = [
        dict(item)
        for item in list(run_manifest.get("project_sample_items") or [])
        if isinstance(item, Mapping)
    ]
    audit_items = [
        dict(item)
        for item in list(audit_manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]
    groups: dict[str, dict[str, Any]] = {}
    for sample in sample_items:
        project_id = _project_id(sample)
        context = groups.setdefault(project_id, _empty_context(sample, run_stage=run_stage))
        context["run_samples"].append(sample)
    for audit in audit_items:
        project_id = _project_id(audit)
        context = groups.setdefault(project_id, _empty_context(audit, run_stage=run_stage))
        context["audit_item"] = audit

    contexts: list[dict[str, Any]] = []
    for project_id, context in sorted(groups.items()):
        audit_item = context.get("audit_item") if isinstance(context.get("audit_item"), Mapping) else {}
        rows = _source_rows_from_audit(audit_item)
        if not rows:
            rows = [_source_row_from_sample(sample) for sample in context["run_samples"]]
        if not rows:
            rows = [_source_row_from_sample(context["first"])]
        for row in rows:
            row["project_id"] = str(row.get("project_id") or project_id)
            row["project_name"] = str(row.get("project_name") or context["project_name"])
            row["pipeline_stage"] = str(row.get("pipeline_stage") or run_stage)
            row["adapter_validation_only"] = _is_adapter_validation(row, run_stage=run_stage)
        context["items"] = rows
        contexts.append(context)
    return contexts


def _empty_context(sample: Mapping[str, Any], *, run_stage: str) -> dict[str, Any]:
    return {
        "project_id": _project_id(sample),
        "project_name": str(sample.get("project_name") or ""),
        "run_stage": run_stage,
        "first": dict(sample),
        "run_samples": [],
        "audit_item": {},
        "items": [],
    }


def _runtime_source_row(
    *,
    public_chain: Mapping[str, Any],
    clock_chain_profile: Mapping[str, Any],
    notice_version_chain: Mapping[str, Any],
    fixation_bundle: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    flow_no = _flow_no(inputs)
    document_kind = str(inputs.get("document_kind") or "").strip()
    if not document_kind and flow_no:
        document_kind = str(FLOW_MODULES.get(flow_no, {}).get("document_kind") or "")
    if not flow_no and document_kind:
        flow_no = DOCUMENT_KIND_TO_FLOW.get(document_kind, "")
    return {
        "source_kind": RUNTIME_PRODUCT_ANALYSIS_STRATEGY_SOURCE_KIND,
        "project_id": str(
            public_chain.get("project_id") or inputs.get("project_id") or ""
        ),
        "project_name": str(inputs.get("project_name") or ""),
        "flow_no": flow_no,
        "flow_title": str(
            inputs.get("flow_title")
            or inputs.get("guangzhou_flow_title")
            or FLOW_MODULES.get(flow_no, {}).get("flow_title")
            or ""
        ),
        "document_kind": document_kind,
        "file_role": str(inputs.get("file_role") or "detail"),
        "source_url": str(
            public_chain.get("announcement_url") or inputs.get("source_url") or ""
        ),
        "snapshot_id": str(
            inputs.get("source_document_ref")
            or fixation_bundle.get("fixation_bundle_id")
            or notice_version_chain.get("current_notice_version_id")
            or ""
        ),
        "published_date": _published_date(
            {
                "published_at_optional": public_chain.get("first_seen_at"),
                "published_at": public_chain.get("first_seen_at"),
            }
        ),
        "pipeline_stage": str(inputs.get("pipeline_stage") or ""),
        "sample_source_type": str(inputs.get("sample_source_type") or ""),
        "adapter_validation_only": bool(inputs.get("adapter_validation_only")),
        "target_id": str(inputs.get("target_id") or ""),
        "bid_deadline_at_optional": str(
            inputs.get("bid_deadline_at_optional")
            or inputs.get("bid_deadline_optional")
            or inputs.get("bid_deadline")
            or ""
        ),
        "opening_at_optional": str(
            inputs.get("opening_at_optional")
            or inputs.get("opening_time_optional")
            or ""
        ),
        "current_action_deadline_at_optional": str(
            inputs.get("current_action_deadline_at_optional")
            or inputs.get("current_action_deadline")
            or clock_chain_profile.get("current_action_deadline_at_optional")
            or ""
        ),
        "clock_chain_profile": dict(clock_chain_profile),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _source_rows_from_audit(audit_item: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(audit_item.get("guangzhou_flow_inventory") or []):
        if not isinstance(item, Mapping):
            continue
        rows.append(
            {
                "source_kind": "guangzhou_flow_inventory",
                "project_id": str(audit_item.get("project_id") or item.get("project_id") or ""),
                "project_name": str(audit_item.get("project_name") or item.get("project_name") or ""),
                "flow_no": _flow_no(item),
                "flow_title": str(item.get("flow_title") or item.get("guangzhou_flow_title") or ""),
                "document_kind": str(item.get("document_kind") or ""),
                "file_role": str(item.get("file_role") or ""),
                "source_url": str(item.get("source_url") or ""),
                "snapshot_id": str(item.get("snapshot_id") or ""),
                "published_date": _published_date(item),
                "failure_taxonomy": list(item.get("failure_taxonomy") or []),
                "download_state": str(item.get("download_state") or ""),
                "parse_state": str(item.get("parse_state") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    if rows:
        return rows
    for item in list(audit_item.get("file_inventory") or []):
        if not isinstance(item, Mapping):
            continue
        rows.append(
            {
                "source_kind": "file_inventory",
                "project_id": str(audit_item.get("project_id") or item.get("project_id") or ""),
                "project_name": str(audit_item.get("project_name") or item.get("project_name") or ""),
                "flow_no": _flow_no(item),
                "flow_title": str(item.get("flow_title") or item.get("guangzhou_flow_title") or ""),
                "document_kind": str(item.get("document_kind") or ""),
                "file_role": str(item.get("file_role") or ""),
                "source_url": str(item.get("source_url") or ""),
                "snapshot_id": str(item.get("snapshot_id") or ""),
                "published_date": _published_date(item),
                "download_state": str(item.get("download_state") or ""),
                "parse_state": str(item.get("parse_state") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _source_row_from_sample(sample: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_kind": "project_sample_item",
        "project_id": _project_id(sample),
        "project_name": str(sample.get("project_name") or ""),
        "target_id": str(sample.get("target_id") or sample.get("parent_target_id") or ""),
        "flow_no": _flow_no(sample),
        "flow_title": str(sample.get("guangzhou_flow_title") or ""),
        "document_kind": str(sample.get("document_kind") or ""),
        "file_role": "detail",
        "source_url": str(sample.get("source_url") or ""),
        "snapshot_id": str(sample.get("detail_snapshot_id") or ""),
        "published_date": _published_date(sample),
        "pipeline_stage": str(sample.get("pipeline_stage") or ""),
        "sample_source_type": str(sample.get("sample_source_type") or ""),
        "adapter_validation_only": bool(sample.get("adapter_validation_only")),
        "failure_taxonomy": list(sample.get("failure_taxonomy") or []),
        "bid_deadline_at_optional": str(sample.get("bid_deadline_at_optional") or ""),
        "opening_at_optional": str(sample.get("opening_at_optional") or ""),
        "current_action_deadline_at_optional": str(sample.get("current_action_deadline_at_optional") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_strategy(*, context: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    items = [item for item in list(context.get("items") or []) if isinstance(item, Mapping)]
    flow_nos = sorted({_flow_no(item) for item in items if _flow_no(item)})
    flow_set = set(flow_nos)
    all_adapter = bool(items) and all(_is_adapter_validation(item, run_stage=str(context.get("run_stage") or "")) for item in items)
    deadline = _deadline_for_project(context)
    hours_to_deadline = None
    if deadline:
        hours_to_deadline = round((deadline - now).total_seconds() / 3600, 2)
    pre_bid_clarification_state = ""
    prediction_recalc_required_on_new_flow_04 = False
    current_sales_window_entry_flow_no = ""
    if all_adapter:
        product_mode = ADAPTER_VALIDATION_ONLY
        strategy_state = ADAPTER_VALIDATION_ONLY
    elif "07" in flow_set:
        product_mode = POST_CANDIDATE_EVIDENCE_PACK
        strategy_state = POST_CANDIDATE_READY
        current_sales_window_entry_flow_no = "07"
    elif flow_set and flow_set.issubset({"09", "10", "11", "12"}):
        product_mode = POST_CANDIDATE_EVIDENCE_PACK
        strategy_state = HISTORICAL_OR_LATE_STAGE_REVIEW
    elif "05" in flow_set:
        product_mode = POST_OPENING_EVIDENCE_TRACK
        strategy_state = PRE_BID_NOT_ELIGIBLE_OPENING_STARTED
    elif flow_set and flow_set.issubset({"01"}):
        product_mode = WATCHLIST_ONLY
        strategy_state = WATCHLIST_ONLY
    elif {"02", "03", "04"} & flow_set and flow_set.issubset({"01", "02", "03", "04"}):
        product_mode, strategy_state = _pre_bid_strategy(deadline=deadline, hours_to_deadline=hours_to_deadline)
        pre_bid_clarification_state = _pre_bid_clarification_state(flow_set)
        prediction_recalc_required_on_new_flow_04 = pre_bid_clarification_state == PREDICTION_BEFORE_CLARIFICATION
    else:
        product_mode = WATCHLIST_ONLY
        strategy_state = TIME_WINDOW_UNKNOWN_REVIEW
    return {
        "project_strategy_id": f"STRATEGY-{_slug(context.get('project_id'))}",
        "project_id": str(context.get("project_id") or ""),
        "project_name": str(context.get("project_name") or ""),
        "product_mode": product_mode,
        "strategy_state": strategy_state,
        "flow_nos_present": flow_nos,
        "deadline_at_optional": deadline.isoformat() if deadline else "",
        "hours_to_deadline_optional": hours_to_deadline,
        "current_sales_window_entry_flow_no": current_sales_window_entry_flow_no,
        "late_stage_flows_required_for_recent_candidate": False,
        "late_stage_support_flow_nos": ["09", "10", "11", "12"],
        "pre_bid_clarification_state": pre_bid_clarification_state,
        "prediction_recalc_required_on_new_flow_04": prediction_recalc_required_on_new_flow_04,
        "item_count": len(items),
        "adapter_validation_only": all_adapter,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _pre_bid_strategy(*, deadline: datetime | None, hours_to_deadline: float | None) -> tuple[str, str]:
    if deadline is None or hours_to_deadline is None:
        return PRE_BID_PREDICTION, TIME_WINDOW_UNKNOWN_REVIEW
    if hours_to_deadline <= 0:
        return POST_OPENING_EVIDENCE_TRACK, PRE_BID_NOT_ELIGIBLE_DEADLINE_PASSED
    if hours_to_deadline >= 168:
        return PRE_BID_PREDICTION, PRE_BID_STANDARD_PREDICTION_READY
    if hours_to_deadline >= 72:
        return PRE_BID_PREDICTION, PRE_BID_LIMITED_FAST_REVIEW
    return POST_OPENING_EVIDENCE_TRACK, PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE


def _pre_bid_clarification_state(flow_set: set[str]) -> str:
    if "04" in flow_set:
        return PREDICTION_AFTER_CLARIFICATION
    if {"02", "03"} & flow_set:
        return PREDICTION_BEFORE_CLARIFICATION
    return ""


def _strategy_item(
    *,
    source: Mapping[str, Any],
    project_strategy: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    flow_no = _flow_no(source)
    product_mode = str(project_strategy.get("product_mode") or "")
    strategy_state = str(project_strategy.get("strategy_state") or "")
    flow_policy = _flow_policy(
        flow_no=flow_no,
        product_mode=product_mode,
        strategy_state=strategy_state,
        policy=policy,
        source=source,
    )
    llm_allowed = _llm_allowed(product_mode=product_mode, flow_policy=flow_policy)
    return {
        "strategy_item_id": f"STRATEGY-ITEM-{_fingerprint({'project': project_strategy.get('project_id'), 'flow': flow_no, 'url': source.get('source_url'), 'role': source.get('file_role')})[:16]}",
        "project_id": str(project_strategy.get("project_id") or source.get("project_id") or ""),
        "project_name": str(project_strategy.get("project_name") or source.get("project_name") or ""),
        "product_mode": product_mode,
        "strategy_state": strategy_state,
        "flow_no": flow_no,
        "flow_title": _flow_title(flow_no, source),
        "document_kind": str(source.get("document_kind") or FLOW_MODULES.get(flow_no, {}).get("document_kind") or ""),
        "file_role": str(source.get("file_role") or ""),
        "source_url": str(source.get("source_url") or ""),
        "snapshot_id": str(source.get("snapshot_id") or ""),
        "published_date": str(source.get("published_date") or ""),
        "current_sales_window_entry_flow_no": str(project_strategy.get("current_sales_window_entry_flow_no") or ""),
        "late_stage_flows_required_for_recent_candidate": bool(
            project_strategy.get("late_stage_flows_required_for_recent_candidate")
        ),
        "pre_bid_clarification_state": str(project_strategy.get("pre_bid_clarification_state") or ""),
        "prediction_recalc_required_on_new_flow_04": bool(
            project_strategy.get("prediction_recalc_required_on_new_flow_04")
        ),
        "download_policy": flow_policy["download_policy"],
        "download_required": _download_required(flow_policy["download_policy"]),
        "parse_depth": flow_policy["parse_depth"],
        "parse_required": _parse_required(flow_policy["parse_depth"], flow_policy["download_policy"]),
        "rules_first": True,
        "llm_allowed": llm_allowed,
        "llm_trigger_reasons": _llm_trigger_reasons(policy) if llm_allowed else [],
        "skip_reason": flow_policy["skip_reason"],
        "index_targets": list(flow_policy["index_targets"]),
        "adapter_validation_only": _is_adapter_validation(source, run_stage=str(source.get("pipeline_stage") or "")),
        "failure_taxonomy": list(source.get("failure_taxonomy") or []),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_policy(
    *,
    flow_no: str,
    product_mode: str,
    strategy_state: str,
    policy: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    if product_mode == ADAPTER_VALIDATION_ONLY:
        return _policy_row(DOWNLOAD_SKIP, PARSE_NONE, [], "adapter_validation_only_not_production_crawl_target")
    if product_mode == WATCHLIST_ONLY:
        if flow_no == "01":
            return _policy_row("METADATA_ONLY", "METADATA_ONLY", ["watchlist_signal"], "watchlist_only_no_download_parse")
        return _policy_row(DOWNLOAD_SKIP, PARSE_NONE, [], "watchlist_only_flow_not_actionable")
    if product_mode == PRE_BID_PREDICTION:
        if strategy_state == TIME_WINDOW_UNKNOWN_REVIEW:
            return _policy_row(DOWNLOAD_SKIP, PARSE_NONE, [], "time_window_unknown_review_before_pre_bid_sale")
        if flow_no not in {"02", "03", "04"}:
            return _policy_row(DOWNLOAD_SKIP, PARSE_NONE, [], "post_event_flow_not_allowed_for_pre_bid_prediction")
        row = _policy_lookup(policy.get("pre_bid_flow_policy"), flow_no)
        return _policy_from_contract_row(row, default_index_targets=["tailored_bid_prediction", "fatal_rejection_risk"])
    if product_mode == POST_OPENING_EVIDENCE_TRACK and strategy_state in {
        PRE_BID_NOT_ELIGIBLE_DEADLINE_PASSED,
        PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE,
    } and flow_no in {"02", "03", "04"}:
        return _policy_row(
            DOWNLOAD_SKIP,
            PARSE_NONE,
            [],
            "pre_bid_window_closed_wait_for_post_candidate_evidence_pack",
        )
    row = _policy_lookup(policy.get("post_candidate_flow_policy"), flow_no)
    if row:
        return _policy_from_contract_row(row)
    fallback = POST_CANDIDATE_FALLBACK_POLICIES.get(flow_no)
    if fallback:
        return _policy_from_contract_row(fallback)
    return _policy_row(DOWNLOAD_SKIP, PARSE_NONE, [], "flow_policy_missing_review")


def _policy_from_contract_row(
    row: Mapping[str, Any],
    *,
    default_index_targets: list[str] | None = None,
) -> dict[str, Any]:
    return _policy_row(
        str(row.get("download_policy") or DOWNLOAD_SKIP),
        str(row.get("parse_depth") or PARSE_NONE),
        list(row.get("index_targets") or default_index_targets or []),
        "",
    )


def _policy_row(download_policy: str, parse_depth: str, index_targets: list[str], skip_reason: str) -> dict[str, Any]:
    return {
        "download_policy": download_policy,
        "parse_depth": parse_depth,
        "index_targets": index_targets,
        "skip_reason": skip_reason,
    }


def _policy_lookup(rows: Any, flow_no: str) -> dict[str, Any]:
    for row in list(rows or []):
        if isinstance(row, Mapping) and str(row.get("flow_no") or "") == flow_no:
            return dict(row)
    return {}


def _llm_allowed(*, product_mode: str, flow_policy: Mapping[str, Any]) -> bool:
    if product_mode in {ADAPTER_VALIDATION_ONLY, WATCHLIST_ONLY}:
        return False
    if str(flow_policy.get("download_policy") or "") == DOWNLOAD_SKIP:
        return False
    return str(flow_policy.get("parse_depth") or "") in {
        "TEXT_PROBE",
        "SECTION_PARSE",
        "DEEP_PARSE",
        "TEXT_PROBE_THEN_TARGETED_DEEP_PARSE",
    }


def _llm_trigger_reasons(policy: Mapping[str, Any]) -> list[str]:
    llm_policy = policy.get("llm_trigger_policy") if isinstance(policy.get("llm_trigger_policy"), Mapping) else {}
    return [str(item) for item in list(llm_policy.get("trigger_when") or []) if str(item)]


def _deadline_for_project(context: Mapping[str, Any]) -> datetime | None:
    candidates: list[Any] = []
    for item in [context.get("first"), context.get("audit_item"), *list(context.get("run_samples") or []), *list(context.get("items") or [])]:
        if not isinstance(item, Mapping):
            continue
        candidates.extend(
            [
                item.get("bid_deadline_at_optional"),
                item.get("bid_deadline_optional"),
                item.get("bid_deadline"),
                item.get("opening_time_optional"),
                item.get("opening_at_optional"),
                item.get("current_action_deadline_at_optional"),
                item.get("current_action_deadline"),
            ]
        )
        clock = item.get("clock_chain_profile")
        if isinstance(clock, Mapping):
            candidates.extend([clock.get("current_action_deadline_at_optional"), clock.get("bid_deadline_at_optional")])
    for value in candidates:
        parsed = _coerce_datetime(value)
        if parsed:
            return parsed
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CN_TZ)
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CN_TZ)
        return parsed.astimezone(CN_TZ)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CN_TZ)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            day = datetime.strptime(text, fmt).date()
            return datetime.combine(day, time(23, 59, 59), tzinfo=CN_TZ)
        except ValueError:
            continue
    return None


def _summary(
    *,
    project_strategy_items: list[Mapping[str, Any]],
    strategy_items: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "analysis_plan_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "project_count": len(project_strategy_items),
        "strategy_item_count": len(strategy_items),
        "product_mode_counts": _counts(item.get("product_mode") for item in project_strategy_items),
        "strategy_state_counts": _counts(item.get("strategy_state") for item in project_strategy_items),
        "current_sales_window_entry_flow_no_counts": _counts(
            item.get("current_sales_window_entry_flow_no") for item in project_strategy_items
        ),
        "pre_bid_clarification_state_counts": _counts(
            item.get("pre_bid_clarification_state") for item in project_strategy_items
        ),
        "prediction_recalc_required_on_new_flow_04_count": sum(
            1 for item in project_strategy_items if bool(item.get("prediction_recalc_required_on_new_flow_04"))
        ),
        "download_policy_counts": _counts(item.get("download_policy") for item in strategy_items),
        "parse_depth_counts": _counts(item.get("parse_depth") for item in strategy_items),
        "llm_allowed_count": sum(1 for item in strategy_items if bool(item.get("llm_allowed"))),
        "adapter_validation_only_count": sum(1 for item in strategy_items if bool(item.get("adapter_validation_only"))),
        "download_required_count": sum(1 for item in strategy_items if bool(item.get("download_required"))),
        "parse_required_count": sum(1 for item in strategy_items if bool(item.get("parse_required"))),
        "skip_reason_counts": _counts(item.get("skip_reason") for item in strategy_items),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_id(item: Mapping[str, Any]) -> str:
    for key in ("project_id", "source_project_code", "project_match_key", "candidate_key"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return f"PROJECT-{_fingerprint(item)[:12]}"


def _flow_no(item: Mapping[str, Any]) -> str:
    explicit = str(item.get("flow_no") or item.get("guangzhou_flow_no") or "").strip()
    if explicit:
        return explicit.zfill(2)
    document_kind = str(item.get("document_kind") or "").strip()
    return DOCUMENT_KIND_TO_FLOW.get(document_kind, "")


def _flow_title(flow_no: str, item: Mapping[str, Any]) -> str:
    return str(item.get("flow_title") or item.get("guangzhou_flow_title") or FLOW_MODULES.get(flow_no, {}).get("flow_title") or "")


def _is_adapter_validation(item: Mapping[str, Any], *, run_stage: str) -> bool:
    return (
        bool(item.get("adapter_validation_only"))
        or run_stage == "AttachmentList"
        or str(item.get("pipeline_stage") or "") == "AttachmentList"
        or str(item.get("sample_source_type") or "") == "HUMAN_PROVIDED_FLOW_SEED"
        or str(item.get("usage_scope") or "") == "FLOW_INTERFACE_ADAPTER_VALIDATION_ONLY"
        or str(item.get("target_id") or "").startswith("GZ-FLOW-INTERFACE")
    )


def _download_required(download_policy: str) -> bool:
    return str(download_policy or "").startswith("DOWNLOAD_REQUIRED")


def _parse_required(parse_depth: str, download_policy: str) -> bool:
    if str(download_policy or "") == DOWNLOAD_SKIP:
        return False
    return str(parse_depth or "") in {"TEXT_PROBE", "SECTION_PARSE", "DEEP_PARSE", "TEXT_PROBE_THEN_TARGETED_DEEP_PARSE"}


def _published_date(item: Mapping[str, Any]) -> str:
    for key in ("published_date", "parent_published_at", "published_at_optional", "published_at"):
        text = str(item.get(key) or "")
        if len(text) >= 10:
            return text[:10]
    return ""


def _load_json_optional(path: Path | None, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        blocking_reasons.append(f"{missing_reason}:not_json_object")
        return {}
    return dict(data)


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _counts(values: Iterable[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _slug(value: Any) -> str:
    text = str(value or "").strip()
    token = "".join(char.upper() if char.isascii() and char.isalnum() else "-" for char in text)
    token = "-".join(part for part in token.split("-") if part)
    return token or f"H{_fingerprint(text)[:12].upper()}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build product analysis strategy plan v1.")
    parser.add_argument("--real-sample-execution-manifest-json", required=True)
    parser.add_argument("--project-file-audit-json")
    parser.add_argument("--business-direction-contract-json")
    parser.add_argument("--output-json")
    parser.add_argument("--created-at")
    parser.add_argument("--now")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_product_analysis_strategy_plan(
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
        project_file_audit_json=args.project_file_audit_json,
        business_direction_contract_json=args.business_direction_contract_json,
        output_json=args.output_json,
        created_at=args.created_at,
        now=args.now,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"product analysis strategy plan: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ADAPTER_VALIDATION_ONLY",
    "HISTORICAL_OR_LATE_STAGE_REVIEW",
    "POST_CANDIDATE_EVIDENCE_PACK",
    "POST_OPENING_EVIDENCE_TRACK",
    "PREDICTION_AFTER_CLARIFICATION",
    "PREDICTION_BEFORE_CLARIFICATION",
    "PRE_BID_PREDICTION",
    "PRODUCT_ANALYSIS_STRATEGY_PLAN_MANIFEST_KIND",
    "RUNTIME_PRODUCT_ANALYSIS_STRATEGY_SOURCE_KIND",
    "TIME_WINDOW_UNKNOWN_REVIEW",
    "WATCHLIST_ONLY",
    "build_product_analysis_strategy_plan",
    "build_runtime_analysis_strategy_h02_projection",
    "build_runtime_product_analysis_strategy_plan",
]
