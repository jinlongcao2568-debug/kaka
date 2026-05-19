from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


EVIDENCE_STAGE6_FACT_PACKAGE_KIND = "evidence_stage6_fact_package_v1_manifest"
EVIDENCE_STAGE6_FACT_PACKAGE_VERSION = 1
EVIDENCE_STAGE6_FACT_PACKAGE_ADAPTER_ID = "evidence-stage6-fact-package-v1"

DEFAULT_BATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/evidence-stage6-fact-package-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

STAGE6_INTAKE_DEFERRED = "DEFER_UNTIL_EVIDENCE_CONTINUED"
STAGE6_FACT_PACKAGE_READY = "STAGE6_FACT_PACKAGE_READY"
STAGE6_REVIEW_PACKAGE_READY = "STAGE6_REVIEW_PACKAGE_READY"


def build_evidence_stage6_fact_package(
    *,
    batch_closeout_json: str | Path | None = None,
    batch_closeout_root: str | Path = DEFAULT_BATCH_CLOSEOUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    closeout_path = Path(batch_closeout_json) if batch_closeout_json else Path(batch_closeout_root) / "evidence-batch-closeout-v1.json"
    closeout_payload = _load_json(closeout_path, blocking_reasons, "evidence_batch_closeout_missing_or_invalid")
    closeout_manifest = _source_manifest(closeout_payload)
    closeout_records = [
        dict(record)
        for record in _list(closeout_manifest.get("closeout_records"))
        if isinstance(record, Mapping)
    ]
    if closeout_payload and not closeout_records:
        blocking_reasons.append("evidence_batch_closeout_records_missing")

    stage6_intake_records = [_stage6_intake_record(record, created_at=created) for record in closeout_records]
    package_input_records = [
        record
        for record in closeout_records
        if _stage6_intake_state(record) != STAGE6_INTAKE_DEFERRED
    ]
    project_fact_records = [_project_fact_record(record) for record in package_input_records]
    report_records = [_report_record(record, output_root=out_dir) for record in package_input_records]
    review_queue_records = [_review_queue_record(record) for record in package_input_records]
    legal_action_records = [_legal_action_record(record) for record in package_input_records]
    review_action_plan_records = [_review_action_plan_record(record) for record in package_input_records]
    internal_pack_records = [
        _internal_pack_record(record, output_root=out_dir, created_at=created) for record in package_input_records
    ]
    stage7_preview_seed_records = [
        _stage7_preview_seed_record(record)
        for record in package_input_records
        if _is_stage7_preview_seed(record)
    ]

    _write_project_package_files(
        out_dir=out_dir,
        internal_pack_records=internal_pack_records,
        project_fact_records=project_fact_records,
        report_records=report_records,
        review_queue_records=review_queue_records,
        legal_action_records=legal_action_records,
        review_action_plan_records=review_action_plan_records,
    )
    summary = _summary(
        closeout_records=closeout_records,
        stage6_intake_records=stage6_intake_records,
        project_fact_records=project_fact_records,
        review_queue_records=review_queue_records,
        review_action_plan_records=review_action_plan_records,
        internal_pack_records=internal_pack_records,
        stage7_preview_seed_records=stage7_preview_seed_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": EVIDENCE_STAGE6_FACT_PACKAGE_VERSION,
        "manifest_kind": EVIDENCE_STAGE6_FACT_PACKAGE_KIND,
        "adapter_id": EVIDENCE_STAGE6_FACT_PACKAGE_ADAPTER_ID,
        "pipeline_stage": "EvidenceStage6FactPackageV1",
        "manifest_id": f"EVIDENCE-STAGE6-FACT-PACKAGE-{_fingerprint({'summary': summary, 'facts': project_fact_records})[:16]}",
        "created_at": created,
        "source_batch_closeout_json": str(closeout_path),
        "source_batch_closeout_manifest_id": str(closeout_manifest.get("manifest_id") or ""),
        "stage6_intake_table": {"records": stage6_intake_records, "summary": _counts_table(stage6_intake_records, "stage6_intake_state")},
        "project_fact_table": {"records": project_fact_records},
        "report_record_table": {"records": report_records},
        "review_queue_table": {"records": review_queue_records},
        "legal_action_recommendation_table": {"records": legal_action_records},
        "stage6_review_action_plan_table": {"records": review_action_plan_records},
        "internal_evidence_pack_table": {"records": internal_pack_records},
        "stage7_governed_preview_seed_table": {"records": stage7_preview_seed_records},
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "stage7_to_stage9_live_execution_enabled": False,
            "formal_customer_delivery_enabled": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "evidence_stage6_fact_package_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(
        out_dir=out_dir,
        result=result,
        stage6_intake_records=stage6_intake_records,
        project_fact_records=project_fact_records,
        report_records=report_records,
        review_queue_records=review_queue_records,
        legal_action_records=legal_action_records,
        review_action_plan_records=review_action_plan_records,
        internal_pack_records=internal_pack_records,
        stage7_preview_seed_records=stage7_preview_seed_records,
    )
    return result


def _stage6_intake_record(record: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    state = _stage6_intake_state(record)
    return {
        "stage6_intake_id": _stable_id("STAGE6-INTAKE", record.get("project_id"), record.get("closeout_state")),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "closeout_state": str(record.get("closeout_state") or ""),
        "evidence_state": str(record.get("evidence_state") or ""),
        "evidence_grade": str(record.get("evidence_grade") or ""),
        "stage6_fact_package_state": str(record.get("stage6_fact_package_state") or ""),
        "stage6_ready": bool(record.get("stage6_ready")),
        "stage7_commercial_input_allowed": bool(record.get("stage7_commercial_input_allowed")),
        "stage6_intake_state": state,
        "recommended_next_action": _stage6_intake_next_action(record, state),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _stage6_intake_state(record: Mapping[str, Any]) -> str:
    if not bool(record.get("stage6_ready")):
        return STAGE6_INTAKE_DEFERRED
    if str(record.get("closeout_state") or "") == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW":
        return STAGE6_FACT_PACKAGE_READY
    return STAGE6_REVIEW_PACKAGE_READY


def _stage6_intake_next_action(record: Mapping[str, Any], state: str) -> str:
    if state == STAGE6_INTAKE_DEFERRED:
        return str(record.get("next_action_label") or "continue_upstream_evidence_run")
    if state == STAGE6_FACT_PACKAGE_READY:
        return "build_internal_fact_package_and_governed_stage7_preview_seed"
    return "build_internal_review_package_and_review_queue"


def _project_fact_record(record: Mapping[str, Any]) -> dict[str, Any]:
    closeout_state = str(record.get("closeout_state") or "")
    promote = closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW"
    d_or_park = closeout_state in {"PARK_D_INSUFFICIENT_OR_BLOCKED", "PARK_NO_CLEARANCE_CLAIM"}
    sale_gate_status = "REVIEW" if promote else "HOLD"
    evidence_gate_status = "REVIEW"
    if d_or_park:
        evidence_gate_status = "BLOCK"
    risk_summary = _dedupe(
        [
            str(record.get("evidence_state") or ""),
            str(record.get("batch_stop_reason") or ""),
            *_list(record.get("review_reasons")),
        ]
    )[:12]
    clue_summary = _dedupe(
        [
            str(record.get("evidence_signal_source") or ""),
            str(record.get("evidence_grade") or ""),
            str(record.get("batch_triage_bucket") or ""),
        ]
    )
    return {
        "project_fact_id": _stable_id("PF", record.get("project_id"), record.get("closeout_state")),
        "project_id": str(record.get("project_id") or ""),
        "sale_gate_status": sale_gate_status,
        "rule_gate_status": "REVIEW",
        "evidence_gate_status": evidence_gate_status,
        "rule_hit_summary": [str(record.get("batch_triage_bucket") or "STAGE6_REVIEW_REQUIRED")],
        "clue_summary": clue_summary,
        "risk_summary": risk_summary,
        "coverage_sellable_state": "RESTRICTED_INTERNAL_PREVIEW" if promote else "INTERNAL_REVIEW_ONLY",
        "delivery_risk_state": "REVIEW_REQUIRED" if promote else "EVIDENCE_GAP_REVIEW",
        "manual_override_status": "REQUIRED",
        "real_competitor_count": 0,
        "serviceable_competitor_count": 0,
        "competitor_quality_grade": "D",
        "primary_evidence_topic_code": _primary_topic_code(record),
        "resolved_evidence_topic_codes": [_primary_topic_code(record)],
        "project_value_score_optional": 70 if promote else 35,
    }


def _report_record(record: Mapping[str, Any], *, output_root: Path) -> dict[str, Any]:
    project_id = str(record.get("project_id") or "")
    project_dir = _project_output_dir(output_root, project_id)
    return {
        "report_id": _stable_id("RPT", project_id, record.get("closeout_state")),
        "project_id": project_id,
        "brief_path": str(project_dir / "stage6-internal-brief.json"),
        "evidence_pack_path": str(project_dir / "stage6-internal-evidence-pack.json"),
        "review_summary_path": str(project_dir / "stage6-review-summary.json"),
        "review_summary_markdown_path": str(project_dir / "stage6-review-summary.md"),
        "review_action_plan_path": str(project_dir / "stage6-review-action-plan.json"),
        "objection_draft_path": "",
        "review_task_status": "OPEN",
        "report_status": "READY",
        "review_lane": _review_lane(record),
        "review_sla_due_at": "",
        "minimum_release_level": "INTERNAL_ONLY",
    }


def _review_queue_record(record: Mapping[str, Any]) -> dict[str, Any]:
    review_reasons = _dedupe([*_list(record.get("review_reasons")), str(record.get("batch_stop_reason") or "")])
    return {
        "queue_profile_id": _stable_id("RQ", record.get("project_id"), record.get("closeout_state")),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "review_lane": _review_lane(record),
        "review_task_status": "OPEN",
        "review_priority_score": _review_priority(record),
        "review_queue_bucket": _review_bucket(record),
        "review_reasons": review_reasons,
        "recommended_next_action": _review_next_action(record),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _legal_action_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "action_id": _stable_id("LAR", record.get("project_id"), record.get("closeout_state")),
        "project_id": str(record.get("project_id") or ""),
        "action_family": "REVIEW_ONLY",
        "applicable_regime": "UNKNOWN",
        "competent_authority_scope": "PROCUREMENT_AUTHORITY_OR_PROJECT_LOCAL_AUTHORITY_REVIEW",
        "window_status": "REVIEW_REQUIRED",
        "basis_summary": str(record.get("evidence_state") or record.get("closeout_state") or ""),
        "blocking_reasons": _dedupe([*_list(record.get("review_reasons")), str(record.get("batch_stop_reason") or "")]),
        "recommended_next_step": _review_next_action(record),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _review_action_plan_record(record: Mapping[str, Any]) -> dict[str, Any]:
    topic_code = _primary_topic_code(record)
    review_lane = _review_lane(record)
    action_family = _review_action_family(record, topic_code)
    action_items = _review_action_items(record, topic_code, action_family)
    automated_dispatch_allowed = _automated_dispatch_allowed(record, action_family)
    return {
        "review_action_plan_id": _stable_id("S6-RAP", record.get("project_id"), record.get("closeout_state")),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "review_action_plan_state": "INTERNAL_ACTION_PLAN_READY",
        "review_lane": review_lane,
        "review_queue_bucket": _review_bucket(record),
        "review_priority_score": _review_priority(record),
        "primary_evidence_topic_code": topic_code,
        "action_family": action_family,
        "target_adapter_scope": _review_target_adapter_scope(record, topic_code, action_family),
        "target_source_scope": _review_target_source_scope(record, topic_code, action_family),
        "regional_routing_policy": _review_regional_routing_policy(topic_code, action_family),
        "action_items": action_items,
        "completion_criteria": _review_completion_criteria(record, topic_code, action_family),
        "automated_dispatch_allowed": automated_dispatch_allowed,
        "dispatch_block_reason": "" if automated_dispatch_allowed else _dispatch_block_reason(record, action_family),
        "blocked_or_not_found_policy": "record_as_evidence_gap_or_source_blocker_not_clearance",
        "acceptable_terminal_states": ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER", "REVIEW_REQUIRED"],
        "source_refs": dict(record.get("source_refs") or {}),
        "continuation_lineage": dict(record.get("continuation_lineage") or {}),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "formal_customer_delivery_ready": False,
    }


def _internal_pack_record(record: Mapping[str, Any], *, output_root: Path, created_at: str) -> dict[str, Any]:
    project_id = str(record.get("project_id") or "")
    project_dir = _project_output_dir(output_root, project_id)
    return {
        "internal_evidence_pack_id": _stable_id("IEP", project_id, record.get("closeout_state")),
        "project_id": project_id,
        "project_name": str(record.get("project_name") or ""),
        "package_scope": "INTERNAL_STAGE6_REVIEW_PACKAGE",
        "brief_path": str(project_dir / "stage6-internal-brief.json"),
        "evidence_pack_path": str(project_dir / "stage6-internal-evidence-pack.json"),
        "closeout_state": str(record.get("closeout_state") or ""),
        "evidence_state": str(record.get("evidence_state") or ""),
        "evidence_grade": str(record.get("evidence_grade") or ""),
        "evidence_signal_source": str(record.get("evidence_signal_source") or ""),
        "stage6_intake_state": _stage6_intake_state(record),
        "candidate_group_members": _list(record.get("candidate_group_members")),
        "responsible_person_name": str(record.get("responsible_person_name") or ""),
        "review_reasons": _dedupe([*_list(record.get("review_reasons")), str(record.get("batch_stop_reason") or "")]),
        "signal_counts": dict(record.get("signal_counts") or {}),
        "design_survey_adapter_counts": dict(record.get("design_survey_adapter_counts") or {}),
        "evidence_artifacts": _list(record.get("evidence_artifacts")),
        "source_refs": dict(record.get("source_refs") or {}),
        "continuation_lineage": dict(record.get("continuation_lineage") or {}),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "raw_blob_exported": False,
        "formal_customer_delivery_ready": False,
    }


def _stage7_preview_seed_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stage7_preview_seed_id": _stable_id("S7-SEED", record.get("project_id"), record.get("closeout_state")),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "project_fact_id": _stable_id("PF", record.get("project_id"), record.get("closeout_state")),
        "report_record_id": _stable_id("RPT", record.get("project_id"), record.get("closeout_state")),
        "preview_seed_state": "RESTRICTED_GOVERNED_PREVIEW_SEED",
        "formal_h06_handoff_ready": False,
        "formal_h06_blockers": [
            "real_competitor_profile_missing",
            "buyer_fit_missing",
            "external_release_not_enabled",
        ],
        "recommended_next_action": "identify_real_competitor_and_buyer_fit_before_formal_stage7",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _is_stage7_preview_seed(record: Mapping[str, Any]) -> bool:
    return (
        str(record.get("closeout_state") or "") == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW"
        and bool(record.get("stage7_commercial_input_allowed"))
    )


def _write_project_package_files(
    *,
    out_dir: Path,
    internal_pack_records: list[Mapping[str, Any]],
    project_fact_records: list[Mapping[str, Any]],
    report_records: list[Mapping[str, Any]],
    review_queue_records: list[Mapping[str, Any]],
    legal_action_records: list[Mapping[str, Any]],
    review_action_plan_records: list[Mapping[str, Any]],
) -> None:
    facts = _records_by_project(project_fact_records)
    reports = _records_by_project(report_records)
    queues = _records_by_project(review_queue_records)
    actions = _records_by_project(legal_action_records)
    action_plans = _records_by_project(review_action_plan_records)
    for pack in internal_pack_records:
        project_id = str(pack.get("project_id") or "")
        project_dir = _project_output_dir(out_dir, project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        evidence_artifacts = [
            artifact for artifact in _list(pack.get("evidence_artifacts")) if isinstance(artifact, Mapping)
        ]
        action_plan = action_plans.get(project_id, {})
        manual_hold = _manual_hold_record(pack=pack, review_action_plan=action_plan)
        brief = {
            "project_id": project_id,
            "project_name": str(pack.get("project_name") or ""),
            "package_scope": pack.get("package_scope"),
            "review_summary_path": reports.get(project_id, {}).get("review_summary_path", ""),
            "review_summary_markdown_path": reports.get(project_id, {}).get("review_summary_markdown_path", ""),
            "review_action_plan_path": reports.get(project_id, {}).get("review_action_plan_path", ""),
            "closeout_state": pack.get("closeout_state"),
            "evidence_state": pack.get("evidence_state"),
            "evidence_grade": pack.get("evidence_grade"),
            "evidence_artifact_count": len(evidence_artifacts),
            "evidence_artifact_types": _dedupe(
                artifact.get("evidence_artifact_type") for artifact in evidence_artifacts
            ),
            "review_lane": queues.get(project_id, {}).get("review_lane", ""),
            "recommended_next_action": actions.get(project_id, {}).get("recommended_next_step", ""),
            "review_action_plan_state": action_plan.get("review_action_plan_state", ""),
            "review_action_family": action_plan.get("action_family", ""),
            "manual_hold_state": manual_hold.get("manual_hold_state", ""),
            "manual_hold_reason": manual_hold.get("manual_hold_reason", ""),
            "manual_hold_reopen_conditions": _list(manual_hold.get("reopen_conditions")),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
        review_summary = _review_summary_record(
            pack=pack,
            project_fact=facts.get(project_id, {}),
            report=reports.get(project_id, {}),
            review_queue=queues.get(project_id, {}),
            legal_action=actions.get(project_id, {}),
            review_action_plan=action_plan,
            evidence_artifacts=evidence_artifacts,
        )
        evidence_pack = {
            "project_id": project_id,
            "project_fact": facts.get(project_id, {}),
            "report_record": reports.get(project_id, {}),
            "review_queue": queues.get(project_id, {}),
            "legal_action_recommendation": actions.get(project_id, {}),
            "stage6_review_action_plan": action_plan,
            "internal_evidence_pack": dict(pack),
            "manual_hold": manual_hold,
            "review_summary": review_summary,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
        _write_json(project_dir / "stage6-internal-brief.json", brief)
        _write_json(project_dir / "stage6-internal-evidence-pack.json", evidence_pack)
        _write_json(project_dir / "stage6-review-action-plan.json", action_plan)
        _write_json(project_dir / "stage6-review-summary.json", review_summary)
        (project_dir / "stage6-review-summary.md").write_text(
            _review_summary_markdown(review_summary),
            encoding="utf-8",
        )


def _review_summary_record(
    *,
    pack: Mapping[str, Any],
    project_fact: Mapping[str, Any],
    report: Mapping[str, Any],
    review_queue: Mapping[str, Any],
    legal_action: Mapping[str, Any],
    review_action_plan: Mapping[str, Any],
    evidence_artifacts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    manual_hold = _manual_hold_record(pack=pack, review_action_plan=review_action_plan)
    return {
        "review_summary_state": "INTERNAL_REVIEW_SUMMARY_READY",
        "project_id": str(pack.get("project_id") or ""),
        "project_name": str(pack.get("project_name") or ""),
        "review_lane": str(review_queue.get("review_lane") or ""),
        "review_queue_bucket": str(review_queue.get("review_queue_bucket") or ""),
        "evidence_state": str(pack.get("evidence_state") or ""),
        "evidence_grade": str(pack.get("evidence_grade") or ""),
        "evidence_signal_source": str(pack.get("evidence_signal_source") or ""),
        "sale_gate_status": str(project_fact.get("sale_gate_status") or ""),
        "rule_gate_status": str(project_fact.get("rule_gate_status") or ""),
        "evidence_gate_status": str(project_fact.get("evidence_gate_status") or ""),
        "coverage_sellable_state": str(project_fact.get("coverage_sellable_state") or ""),
        "delivery_risk_state": str(project_fact.get("delivery_risk_state") or ""),
        "responsible_person_name": str(pack.get("responsible_person_name") or ""),
        "candidate_group_members": _list(pack.get("candidate_group_members")),
        "review_reasons": _list(review_queue.get("review_reasons") or pack.get("review_reasons")),
        "recommended_next_action": str(
            review_queue.get("recommended_next_action")
            or legal_action.get("recommended_next_step")
            or ""
        ),
        "review_action_plan_state": str(review_action_plan.get("review_action_plan_state") or ""),
        "review_action_family": str(review_action_plan.get("action_family") or ""),
        "review_action_plan_path": str(report.get("review_action_plan_path") or ""),
        "manual_hold": manual_hold,
        "manual_hold_state": str(manual_hold.get("manual_hold_state") or ""),
        "manual_hold_reason": str(manual_hold.get("manual_hold_reason") or ""),
        "manual_hold_reopen_conditions": _list(manual_hold.get("reopen_conditions")),
        "operator_decision_options": _list(manual_hold.get("operator_decision_options")),
        "review_action_items": [
            _review_action_item_summary(item)
            for item in _list(review_action_plan.get("action_items"))
            if isinstance(item, Mapping)
        ],
        "review_completion_criteria": _list(review_action_plan.get("completion_criteria")),
        "evidence_artifact_count": len(evidence_artifacts),
        "evidence_artifacts": [_review_artifact_summary(artifact) for artifact in evidence_artifacts[:10]],
        "source_refs": dict(pack.get("source_refs") or {}),
        "review_summary_path": str(report.get("review_summary_path") or ""),
        "review_summary_markdown_path": str(report.get("review_summary_markdown_path") or ""),
        "review_checklist": _review_checklist(pack, evidence_artifacts, manual_hold),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "raw_blob_exported": False,
        "formal_customer_delivery_ready": False,
    }


def _review_action_item_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "action_item_id": str(item.get("action_item_id") or ""),
        "order": int(item.get("order") or 0),
        "action_label": str(item.get("action_label") or ""),
        "manual_review_required": bool(item.get("manual_review_required")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _review_artifact_summary(artifact: Mapping[str, Any]) -> dict[str, Any]:
    identity_fields = artifact.get("identity_fields") if isinstance(artifact.get("identity_fields"), Mapping) else {}
    return {
        "evidence_artifact_type": str(artifact.get("evidence_artifact_type") or ""),
        "provider_id": str(artifact.get("provider_id") or ""),
        "provider_result_state": str(artifact.get("provider_result_state") or ""),
        "readback_state": str(artifact.get("readback_state") or ""),
        "verification_result": str(artifact.get("verification_result") or ""),
        "identity_resolution_state": str(artifact.get("identity_resolution_state") or ""),
        "responsible_person_name": str(artifact.get("responsible_person_name") or ""),
        "candidate_company_name": str(artifact.get("candidate_company_name") or ""),
        "registered_unit_match_scope": str(artifact.get("registered_unit_match_scope") or ""),
        "matched_candidate_group_member_name": str(artifact.get("matched_candidate_group_member_name") or ""),
        "person_name": str(identity_fields.get("person_name") or ""),
        "registered_unit_name": str(identity_fields.get("registered_unit_name") or ""),
        "certificate_no_or_registration_no": str(identity_fields.get("certificate_no_or_registration_no") or ""),
        "registration_status": str(identity_fields.get("registration_status") or ""),
        "source_url": str(artifact.get("source_url") or ""),
        "source_snapshot_ref": str(artifact.get("source_snapshot_ref") or ""),
        "source_snapshot_sha256": str(artifact.get("source_snapshot_sha256") or ""),
        "redacted_text_probe": str(artifact.get("redacted_text_probe") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _manual_hold_record(*, pack: Mapping[str, Any], review_action_plan: Mapping[str, Any]) -> dict[str, Any]:
    dispatch_block_reason = str(review_action_plan.get("dispatch_block_reason") or "").strip()
    automated_dispatch_allowed = bool(review_action_plan.get("automated_dispatch_allowed", True))
    terminal_no_delta = (
        _is_terminal_source_gap_no_delta(pack)
        or dispatch_block_reason == "terminal_source_gap_no_delta_manual_review_only"
    )
    if terminal_no_delta:
        return {
            "manual_hold_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
            "manual_hold_reason": "terminal_source_gap_no_delta_manual_review_only",
            "automated_dispatch_allowed": False,
            "reopen_conditions": [
                "new_official_original_notice_source_or_snapshot_available",
                "operator_confirms_manual_retry_scope_and_budget",
                "new_release_evidence_source_or_project_local_authority_path_available",
                "prior_blocker_resolved_without_clearance_claim",
            ],
            "operator_decision_options": [
                "KEEP_MANUAL_HOLD",
                "REOPEN_WITH_NEW_SOURCE",
                "CLOSE_AS_D_EVIDENCE_INSUFFICIENT_INTERNAL_ONLY",
            ],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
    if not automated_dispatch_allowed:
        return {
            "manual_hold_state": "MANUAL_ONLY_ACTION_PLAN",
            "manual_hold_reason": dispatch_block_reason or "action_plan_marked_manual_only",
            "automated_dispatch_allowed": False,
            "reopen_conditions": ["operator_updates_action_plan_to_allow_controlled_dispatch"],
            "operator_decision_options": ["KEEP_MANUAL_HOLD", "REOPEN_WITH_OPERATOR_OVERRIDE"],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
    return {
        "manual_hold_state": "AUTOMATED_DISPATCH_ALLOWED",
        "manual_hold_reason": "",
        "automated_dispatch_allowed": True,
        "reopen_conditions": [],
        "operator_decision_options": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _review_checklist(
    pack: Mapping[str, Any],
    evidence_artifacts: list[Mapping[str, Any]],
    manual_hold: Mapping[str, Any],
) -> list[str]:
    checks = [
        "review_current_candidate_binding_and_stage3_fields",
        "keep_internal_only_until_manual_review_completes",
        "do_not_treat_missing_query_as_clearance",
    ]
    if evidence_artifacts:
        checks.extend(
            [
                "verify_artifact_source_url_snapshot_ref_and_hash",
                "verify_person_company_certificate_fields_against_candidate_group",
            ]
        )
    if str(pack.get("evidence_state") or "").startswith("D_"):
        checks.append("record_source_blocker_or_missing_field_before_retry")
    if str(manual_hold.get("manual_hold_state") or "") == "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH":
        checks.extend(
            [
                "confirm_terminal_source_gap_lineage_before_closing_auto_loop",
                "require_new_source_or_operator_override_before_retry",
                "record_manual_hold_decision_without_clearance_claim",
            ]
        )
    return _dedupe(checks)


def _review_summary_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage6 Internal Review Summary",
        "",
        f"Project ID: {summary.get('project_id') or ''}",
        f"Project Name: {summary.get('project_name') or ''}",
        f"Review Lane: {summary.get('review_lane') or ''}",
        f"Evidence State: {summary.get('evidence_state') or ''}",
        f"Evidence Grade: {summary.get('evidence_grade') or ''}",
        f"Responsible Person: {summary.get('responsible_person_name') or ''}",
        f"Recommended Next Action: {summary.get('recommended_next_action') or ''}",
        f"Review Action Family: {summary.get('review_action_family') or ''}",
        f"Manual Hold State: {summary.get('manual_hold_state') or ''}",
        f"Manual Hold Reason: {summary.get('manual_hold_reason') or ''}",
        "",
        "Safety Boundary:",
        f"Customer Visible Allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"No Legal Conclusion: {str(bool(summary.get('no_legal_conclusion'))).lower()}",
        f"Query Miss Is Not Clearance: {str(bool(summary.get('query_miss_is_not_clearance'))).lower()}",
        "",
        "Evidence Artifacts:",
    ]
    artifacts = [artifact for artifact in _list(summary.get("evidence_artifacts")) if isinstance(artifact, Mapping)]
    if not artifacts:
        lines.append("- none")
    for index, artifact in enumerate(artifacts, start=1):
        lines.append(
            "- "
            + f"{index}. {artifact.get('evidence_artifact_type') or ''}; "
            + f"verification={artifact.get('verification_result') or ''}; "
            + f"person={artifact.get('person_name') or artifact.get('responsible_person_name') or ''}; "
            + f"registered_unit={artifact.get('registered_unit_name') or ''}; "
            + f"certificate={artifact.get('certificate_no_or_registration_no') or ''}; "
            + f"match_scope={artifact.get('registered_unit_match_scope') or ''}; "
            + f"snapshot_sha256={artifact.get('source_snapshot_sha256') or ''}"
        )
    manual_hold = summary.get("manual_hold") if isinstance(summary.get("manual_hold"), Mapping) else {}
    if str(manual_hold.get("manual_hold_state") or "") in {
        "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
        "MANUAL_ONLY_ACTION_PLAN",
    }:
        lines.extend(["", "Manual Hold:"])
        lines.append(f"- State: {manual_hold.get('manual_hold_state') or ''}")
        lines.append(f"- Reason: {manual_hold.get('manual_hold_reason') or ''}")
        lines.append(f"- Automated Dispatch Allowed: {str(bool(manual_hold.get('automated_dispatch_allowed'))).lower()}")
        lines.append("- Reopen Conditions:")
        for item in _list(manual_hold.get("reopen_conditions")):
            lines.append(f"- {item}")
        lines.append("- Operator Decision Options:")
        for item in _list(manual_hold.get("operator_decision_options")):
            lines.append(f"- {item}")
    lines.extend(["", "Review Action Plan:"])
    action_items = [item for item in _list(summary.get("review_action_items")) if isinstance(item, Mapping)]
    if not action_items:
        lines.append("- none")
    for item in action_items:
        lines.append(
            "- "
            + f"{item.get('order') or 0}. {item.get('action_label') or ''}; "
            + f"manual_review={str(bool(item.get('manual_review_required'))).lower()}"
        )
    lines.extend(["", "Completion Criteria:"])
    criteria = _list(summary.get("review_completion_criteria"))
    if not criteria:
        lines.append("- none")
    for item in criteria:
        lines.append(f"- {item}")
    lines.extend(["", "Review Checklist:"])
    for item in _list(summary.get("review_checklist")):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _summary(
    *,
    closeout_records: list[Mapping[str, Any]],
    stage6_intake_records: list[Mapping[str, Any]],
    project_fact_records: list[Mapping[str, Any]],
    review_queue_records: list[Mapping[str, Any]],
    review_action_plan_records: list[Mapping[str, Any]],
    internal_pack_records: list[Mapping[str, Any]],
    stage7_preview_seed_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    intake_counts = _counts(record.get("stage6_intake_state") for record in stage6_intake_records)
    review_lane_counts = _counts(record.get("review_lane") for record in review_queue_records)
    review_action_family_counts = _counts(record.get("action_family") for record in review_action_plan_records)
    return {
        "stage6_fact_package_state": "EVIDENCE_STAGE6_FACT_PACKAGE_READY" if not blocking_reasons else "EVIDENCE_STAGE6_INPUT_BLOCKED",
        "input_closeout_project_count": len(closeout_records),
        "stage6_intake_record_count": len(stage6_intake_records),
        "stage6_intake_state_counts": intake_counts,
        "project_fact_count": len(project_fact_records),
        "report_record_count": len(project_fact_records),
        "review_queue_count": len(review_queue_records),
        "review_action_plan_count": len(review_action_plan_records),
        "internal_evidence_pack_count": len(internal_pack_records),
        "stage7_preview_seed_count": len(stage7_preview_seed_records),
        "formal_h06_handoff_ready_count": 0,
        "review_lane_counts": review_lane_counts,
        "review_action_family_counts": review_action_family_counts,
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "formal_customer_delivery_ready": False,
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(
    *,
    out_dir: Path,
    result: dict[str, Any],
    stage6_intake_records: list[Mapping[str, Any]],
    project_fact_records: list[Mapping[str, Any]],
    report_records: list[Mapping[str, Any]],
    review_queue_records: list[Mapping[str, Any]],
    legal_action_records: list[Mapping[str, Any]],
    review_action_plan_records: list[Mapping[str, Any]],
    internal_pack_records: list[Mapping[str, Any]],
    stage7_preview_seed_records: list[Mapping[str, Any]],
) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *list(result.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    _write_json(out_dir / "stage6-intake-table.json", {"summary": result["summary"], "records": stage6_intake_records})
    _write_json(out_dir / "project-fact-table.json", {"summary": result["summary"], "records": project_fact_records})
    _write_json(out_dir / "report-record-table.json", {"summary": result["summary"], "records": report_records})
    _write_json(out_dir / "review-queue-table.json", {"summary": result["summary"], "records": review_queue_records})
    _write_json(out_dir / "legal-action-recommendation-table.json", {"summary": result["summary"], "records": legal_action_records})
    _write_json(out_dir / "stage6-review-action-plan-table.json", {"summary": result["summary"], "records": review_action_plan_records})
    _write_json(out_dir / "internal-evidence-pack-table.json", {"summary": result["summary"], "records": internal_pack_records})
    _write_json(out_dir / "stage7-governed-preview-seed-table.json", {"summary": result["summary"], "records": stage7_preview_seed_records})
    _write_json(out_dir / "stage6-fact-package-v1.json", result)


def _primary_topic_code(record: Mapping[str, Any]) -> str:
    lane = str(record.get("engineering_work_lane") or "")
    if "survey" in lane or "design" in lane:
        return "DESIGN_SURVEY_RESPONSIBLE_PERSON_IDENTITY"
    return "P13B_RESPONSIBLE_PERSON_RELEASE"


def _review_lane(record: Mapping[str, Any]) -> str:
    closeout_state = str(record.get("closeout_state") or "")
    if closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW":
        return "A_SIGNAL_RELEASE_EVIDENCE_REVIEW"
    if closeout_state == "PARK_D_INSUFFICIENT_OR_BLOCKED":
        return "D_EVIDENCE_GAP_REVIEW"
    if closeout_state == "PARK_NO_CLEARANCE_CLAIM":
        return "LOW_VALUE_PARK_REVIEW"
    if closeout_state == "DEFER_NON_MAINLINE_OR_SCOPE":
        return "NON_MAINLINE_ADAPTER_REVIEW"
    return "GENERAL_STAGE6_REVIEW"


def _review_bucket(record: Mapping[str, Any]) -> str:
    closeout_state = str(record.get("closeout_state") or "")
    if closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW":
        return "RELEASE_EVIDENCE_AND_STAGE7_PREVIEW_PREP"
    if closeout_state == "PARK_D_INSUFFICIENT_OR_BLOCKED":
        return "EVIDENCE_GAP_OR_SOURCE_BLOCKER_REVIEW"
    return "INTERNAL_FACT_REVIEW"


def _review_priority(record: Mapping[str, Any]) -> int:
    closeout_state = str(record.get("closeout_state") or "")
    if closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW":
        return 90
    if closeout_state == "PARK_D_INSUFFICIENT_OR_BLOCKED":
        return 55
    return 45


def _review_next_action(record: Mapping[str, Any]) -> str:
    closeout_state = str(record.get("closeout_state") or "")
    if closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW":
        return "run_targeted_release_evidence_review_then_prepare_governed_stage7_preview"
    if _is_terminal_source_gap_no_delta(record):
        return "park_manual_review_until_new_source_or_operator_override_without_clearance_claim"
    if closeout_state == "PARK_D_INSUFFICIENT_OR_BLOCKED":
        return "manual_review_or_retry_source_without_clearance_claim"
    if closeout_state == "PARK_NO_CLEARANCE_CLAIM":
        return "park_or_manual_review_without_clearance_claim"
    return str(record.get("next_action_label") or "manual_review")


def _review_action_family(record: Mapping[str, Any], topic_code: str) -> str:
    closeout_state = str(record.get("closeout_state") or "")
    artifacts = [artifact for artifact in _list(record.get("evidence_artifacts")) if isinstance(artifact, Mapping)]
    if closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW":
        return "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW"
    if closeout_state == "PARK_D_INSUFFICIENT_OR_BLOCKED":
        return "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW"
    if topic_code == "DESIGN_SURVEY_RESPONSIBLE_PERSON_IDENTITY" or any(
        str(artifact.get("evidence_artifact_type") or "") == "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK"
        for artifact in artifacts
    ):
        return "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW"
    if closeout_state == "PARK_NO_CLEARANCE_CLAIM":
        return "PARKED_LOW_CONFIDENCE_INTERNAL_REVIEW"
    return "GENERAL_STAGE6_INTERNAL_REVIEW"


def _review_target_adapter_scope(record: Mapping[str, Any], topic_code: str, action_family: str) -> str:
    if action_family == "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW":
        return "ReleaseEvidenceAdapterPlanV1 + jurisdiction_release_adapter_registry"
    if action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW":
        return "OriginalNoticeTaskTriageV1 + official_direct_html_or_attachment_readback"
    if action_family == "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW":
        return "DesignSurveyPublicRegistryReadback + natural_resources_public_registry_adapter"
    if topic_code == "P13B_RESPONSIBLE_PERSON_RELEASE":
        return "EvidenceBatchCloseoutV1/manual_review"
    return "Stage6FactPackageV1/manual_review"


def _review_target_source_scope(record: Mapping[str, Any], topic_code: str, action_family: str) -> list[str]:
    if action_family == "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW":
        return [
            "data.ggzy.gov.cn_bid_show_confirmed_signal",
            "historical_overlap_project_local_housing_construction_or_competent_authority_public_source",
            "construction_permit_completion_acceptance_project_manager_change_contract_performance_public_records",
        ]
    if action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW":
        return [
            "official_original_notice_url_or_attachment_snapshot",
            "official_direct_html_when_available",
            "ygp_readback_only_when_city_mapping_is_applicable",
        ]
    if action_family == "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW":
        return [
            "registered_surveyor_or_natural_resources_public_registry_snapshot",
            "candidate_group_member_binding_and_certificate_fields",
            "prior_design_survey_award_history_when_service_clock_needs_review",
        ]
    return ["stage6_internal_review_sources"]


def _review_regional_routing_policy(topic_code: str, action_family: str) -> str:
    if action_family == "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW":
        return "route_by_historical_overlap_project_jurisdiction_no_guangdong_fallback_for_non_guangdong"
    if action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW":
        return "route_by_original_notice_source_and_project_city_when_available"
    if action_family == "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW":
        return "route_by_profession_registry_and_candidate_project_region_not_siku_only"
    return "route_by_project_region_or_manual_review"


def _review_action_items(record: Mapping[str, Any], topic_code: str, action_family: str) -> list[dict[str, Any]]:
    project_id = str(record.get("project_id") or "")
    responsible_person = str(record.get("responsible_person_name") or "")
    if action_family == "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW":
        labels = [
            "confirm_current_candidate_person_company_binding_from_stage3",
            "review_data_ggzy_bid_show_person_and_time_window_overlap",
            "query_release_evidence_only_in_historical_overlap_project_local_public_source",
            "prepare_governed_stage7_preview_only_after_manual_internal_review",
        ]
    elif action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW":
        if _is_terminal_source_gap_no_delta(record):
            labels = [
                "inspect_terminal_original_notice_source_gap_lineage",
                "record_manual_review_hold_without_clearance_claim",
                "do_not_auto_retry_until_new_source_or_operator_override",
            ]
        else:
            labels = [
                "inspect_original_notice_readback_blocker_or_missing_fields",
                "retry_official_direct_html_or_attachment_readback_with_small_budget",
                "record_blocked_or_missing_source_as_evidence_gap_without_clearance_claim",
            ]
    elif action_family == "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW":
        labels = [
            "verify_public_registry_snapshot_hash_and_redacted_readback",
            "review_registered_unit_match_scope_against_candidate_group",
            "plan_qualification_service_clock_and_current_assignment_review",
        ]
    else:
        labels = [
            "review_stage6_fact_record_and_source_refs",
            "decide_manual_hold_or_next_adapter_task",
        ]
    return [
        {
            "action_item_id": _stable_id("S6-RAP-ITEM", project_id, label),
            "order": index,
            "action_label": label,
            "responsible_person_name": responsible_person,
            "manual_review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
        for index, label in enumerate(labels, start=1)
    ]


def _review_completion_criteria(record: Mapping[str, Any], topic_code: str, action_family: str) -> list[str]:
    if action_family == "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW":
        return [
            "stage3_candidate_binding_reviewed",
            "historical_overlap_project_window_reviewed",
            "release_evidence_adapter_terminal_state_recorded",
            "source_url_snapshot_ref_and_hash_recorded",
            "manual_reviewer_keeps_internal_only_boundary",
        ]
    if action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW":
        if _is_terminal_source_gap_no_delta(record):
            return [
                "terminal_source_gap_lineage_recorded",
                "manual_review_or_new_source_override_required_before_retry",
                "blocked_or_missing_fields_do_not_unlock_clearance",
            ]
        return [
            "original_notice_retry_attempt_or_blocker_recorded",
            "person_and_period_field_presence_recorded",
            "blocked_or_missing_fields_do_not_unlock_clearance",
        ]
    if action_family == "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW":
        return [
            "public_registry_snapshot_ref_and_hash_reviewed",
            "registered_unit_match_scope_reviewed",
            "qualification_or_service_clock_followup_task_recorded_when_needed",
        ]
    return ["manual_review_decision_recorded"]


def _automated_dispatch_allowed(record: Mapping[str, Any], action_family: str) -> bool:
    if action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW" and _is_terminal_source_gap_no_delta(record):
        return False
    return action_family in {
        "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
        "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW",
        "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW",
    }


def _dispatch_block_reason(record: Mapping[str, Any], action_family: str) -> str:
    if action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW" and _is_terminal_source_gap_no_delta(record):
        return "terminal_source_gap_no_delta_manual_review_only"
    return "action_family_not_automated_dispatchable"


def _is_terminal_source_gap_no_delta(record: Mapping[str, Any]) -> bool:
    if str(record.get("closeout_state") or "") != "PARK_D_INSUFFICIENT_OR_BLOCKED":
        return False
    if int(record.get("pending_adapter_job_count") or 0) > 0:
        return False
    lineage = record.get("continuation_lineage") if isinstance(record.get("continuation_lineage"), Mapping) else {}
    final_action = str(lineage.get("final_original_backtrace_continuation_recommended_next_action") or "").strip()
    if final_action != "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM":
        return False
    return int(lineage.get("state_after_adapter_job_count") or 0) == 0


def _project_output_dir(output_root: Path, project_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", project_id or "UNKNOWN")
    return output_root / "packages" / safe_id


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out[project_id] = record
    return out


def _counts_table(records: list[Mapping[str, Any]], field_name: str) -> dict[str, Any]:
    return {
        "record_count": len(records),
        f"{field_name}_counts": _counts(record.get(field_name) for record in records),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blocking_reasons.append(missing_reason)
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage6 fact/review package from EvidenceBatchCloseout v1.")
    parser.add_argument("--batch-closeout-json", default="")
    parser.add_argument("--batch-closeout-root", default=str(DEFAULT_BATCH_CLOSEOUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evidence_stage6_fact_package(
        batch_closeout_json=args.batch_closeout_json or None,
        batch_closeout_root=args.batch_closeout_root,
        output_root=args.output_root,
        created_at=args.created_at or None,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVIDENCE_STAGE6_FACT_PACKAGE_KIND",
    "build_evidence_stage6_fact_package",
]
