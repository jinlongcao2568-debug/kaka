from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


CONTROLLED_LIVE_PUBLIC_BATCH_GRAY_LAUNCH_REVIEW_KIND = (
    "controlled_live_public_batch_gray_launch_review_v1"
)
CONTROLLED_LIVE_PUBLIC_BATCH_GRAY_LAUNCH_REVIEW_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/controlled-live-public-batch-gray-launch-review-v1")


def build_controlled_live_public_batch_gray_launch_review(
    *,
    closeout_json: str | Path | None = None,
    evidence_summary_json: str | Path | None = None,
    stage4_readback_json: str | Path | None = None,
    source_remediation_json: str | Path | None = None,
    source_remediation_execution_json: str | Path | None = None,
    run_manifest_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    gray_sample_goal_min: int = 100,
    gray_sample_goal_max: int = 200,
    operator_decision: str = "",
    operator_name: str = "",
    operator_decision_note: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    closeout_path = Path(closeout_json) if closeout_json else None
    evidence_path = Path(evidence_summary_json) if evidence_summary_json else None
    stage4_path = Path(stage4_readback_json) if stage4_readback_json else None
    remediation_path = Path(source_remediation_json) if source_remediation_json else None
    remediation_execution_path = (
        Path(source_remediation_execution_json) if source_remediation_execution_json else None
    )
    run_manifest_path = Path(run_manifest_json) if run_manifest_json else None

    closeout = _load_json(closeout_path)
    evidence_payload = _load_json(evidence_path)
    stage4_payload = _load_json(stage4_path)
    remediation_payload = _load_json(remediation_path)
    remediation_execution_payload = _load_json(remediation_execution_path)
    run_manifest_payload = _load_json(run_manifest_path)

    evidence_summary = _mapping(evidence_payload.get("summary"))
    stage4_summary = _mapping(stage4_payload.get("summary"))
    remediation_summary = _mapping(remediation_payload.get("summary"))
    remediation_execution_summary = _mapping(remediation_execution_payload.get("summary"))
    run_summary = _mapping(_mapping(run_manifest_payload.get("manifest") or run_manifest_payload).get("summary"))

    summary = _summary(
        closeout=closeout,
        evidence_summary=evidence_summary,
        stage4_summary=stage4_summary,
        remediation_summary=remediation_summary,
        remediation_execution_summary=remediation_execution_summary,
        run_summary=run_summary,
        gray_sample_goal_min=gray_sample_goal_min,
        gray_sample_goal_max=gray_sample_goal_max,
        operator_decision=operator_decision,
    )
    checklist = _checklist(summary)
    gray_run_plan = _gray_run_plan(
        summary,
        gray_sample_goal_min=gray_sample_goal_min,
        gray_sample_goal_max=gray_sample_goal_max,
    )
    result = {
        "manifest_kind": CONTROLLED_LIVE_PUBLIC_BATCH_GRAY_LAUNCH_REVIEW_KIND,
        "manifest_version": CONTROLLED_LIVE_PUBLIC_BATCH_GRAY_LAUNCH_REVIEW_VERSION,
        "adapter_id": "controlled-live-public-batch-gray-launch-review-v1",
        "created_at": created,
        "source_closeout_json": str(closeout_path or ""),
        "source_run_manifest_json": str(run_manifest_path or ""),
        "source_evidence_summary_json": str(evidence_path or ""),
        "source_stage4_readback_json": str(stage4_path or ""),
        "source_source_remediation_json": str(remediation_path or ""),
        "source_source_remediation_execution_json": str(remediation_execution_path or ""),
        "summary": summary,
        "gray_launch_checklist": {"records": checklist, "summary": _checklist_summary(checklist)},
        "operator_decision_record": _operator_decision_record(
            summary,
            operator_decision=operator_decision,
            operator_name=operator_name,
            operator_decision_note=operator_decision_note,
            created_at=created,
        ),
        "gray_run_plan": gray_run_plan,
        "safety": _safety(),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-live-public-batch-gray-launch-review-v1.json", result)
    (output_dir / "controlled-live-public-batch-gray-launch-review-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _summary(
    *,
    closeout: Mapping[str, Any],
    evidence_summary: Mapping[str, Any],
    stage4_summary: Mapping[str, Any],
    remediation_summary: Mapping[str, Any],
    remediation_execution_summary: Mapping[str, Any],
    run_summary: Mapping[str, Any],
    gray_sample_goal_min: int = 100,
    gray_sample_goal_max: int = 200,
    operator_decision: str = "",
) -> dict[str, Any]:
    execute = _first_bool(
        closeout.get("execute"),
        evidence_summary.get("source_execute"),
        run_summary.get("execute"),
    )
    sample_count = _first_int(
        closeout.get("sample_count"),
        evidence_summary.get("project_sample_count"),
        run_summary.get("project_sample_count"),
    )
    fixed_snapshot_count = _first_int(
        closeout.get("fixed_snapshot_sha256_count"),
        evidence_summary.get("fixed_snapshot_sha256_count"),
    )
    base_stage4_all_ready = _first_bool(
        closeout.get("stage4_all_required_readbacks_ready"),
        stage4_summary.get("stage4_all_required_readbacks_ready"),
    )
    post_run_stage4_all_ready = _first_known_bool(
        remediation_execution_summary.get("post_run_stage4_all_required_readbacks_ready"),
        closeout.get("post_run_stage4_all_required_readbacks_ready"),
    )
    final_stage4_all_ready = (
        post_run_stage4_all_ready if post_run_stage4_all_ready is not None else base_stage4_all_ready
    )
    source_remediation_initial_count = _first_int(
        closeout.get("source_remediation_record_count"),
        remediation_summary.get("source_remediation_record_count"),
    )
    post_run_source_remediation_count = _first_known_int(
        remediation_execution_summary.get("post_run_source_remediation_record_count"),
        closeout.get("post_run_source_remediation_record_count"),
    )
    final_source_remediation_count = (
        post_run_source_remediation_count
        if post_run_source_remediation_count is not None
        else source_remediation_initial_count
    )
    safety_boundary_closed = _safety_boundary_closed(closeout, evidence_summary, stage4_summary, remediation_summary)
    no_legal_conclusion = _first_bool(
        closeout.get("no_legal_conclusion"),
        evidence_summary.get("no_legal_conclusion"),
        stage4_summary.get("no_legal_conclusion"),
        True,
    )
    query_miss_is_not_clearance = _first_bool(
        closeout.get("query_miss_is_not_clearance"),
        evidence_summary.get("query_miss_is_not_clearance"),
        stage4_summary.get("query_miss_is_not_clearance"),
        True,
    )
    state = _eligibility_state(
        execute=execute,
        sample_count=sample_count,
        fixed_snapshot_count=fixed_snapshot_count,
        final_stage4_all_ready=final_stage4_all_ready,
        final_source_remediation_count=final_source_remediation_count,
        safety_boundary_closed=safety_boundary_closed,
        no_legal_conclusion=no_legal_conclusion,
        query_miss_is_not_clearance=query_miss_is_not_clearance,
    )
    ready = state == "READY_FOR_HUMAN_GRAY_LAUNCH_REVIEW"
    decision = _normalize_operator_decision(operator_decision)
    approved = ready and decision == "APPROVED"
    if not ready:
        approval_state = "NOT_REQUESTABLE"
    elif approved:
        approval_state = "APPROVED"
    elif decision in {"HOLD", "REJECTED"}:
        approval_state = decision
    else:
        approval_state = "WAITING_OPERATOR_APPROVAL"
    return {
        "gray_launch_review_state": state,
        "eligible_for_human_gray_launch_review": ready,
        "human_gray_launch_approval_state": approval_state,
        "approved_for_controlled_gray_execution": approved,
        "next_required_step": (
            "run_controlled_gray_public_source_batch"
            if approved
            else "record_operator_gray_launch_decision_then_run_controlled_gray_batch"
            if ready and approval_state == "WAITING_OPERATOR_APPROVAL"
            else "review_operator_gray_launch_decision"
            if ready
            else _next_required_step(state)
        ),
        "source_execute": execute,
        "project_sample_count": sample_count,
        "gray_sample_goal_min": max(1, int(gray_sample_goal_min)),
        "gray_sample_goal_max": max(max(1, int(gray_sample_goal_min)), int(gray_sample_goal_max)),
        "gray_sample_goal_state": _gray_sample_goal_state(
            sample_count,
            gray_sample_goal_min=max(1, int(gray_sample_goal_min)),
            gray_sample_goal_max=max(max(1, int(gray_sample_goal_min)), int(gray_sample_goal_max)),
        ),
        "gray_sample_goal_met": sample_count >= max(1, int(gray_sample_goal_min)),
        "fixed_snapshot_sha256_count": fixed_snapshot_count,
        "stage4_readback_required_sample_count": _first_int(
            closeout.get("stage4_evidence_readback_required_count"),
            stage4_summary.get("stage4_readback_required_sample_count"),
        ),
        "stage4_readback_ready_sample_count": _first_int(
            closeout.get("stage4_readback_ready_sample_count"),
            stage4_summary.get("stage4_readback_ready_sample_count"),
        ),
        "stage4_readback_missing_sample_count": _first_int(
            closeout.get("stage4_readback_missing_sample_count"),
            stage4_summary.get("stage4_readback_missing_sample_count"),
        ),
        "stage4_public_evidence_readback_count": _first_int(
            closeout.get("stage4_public_evidence_readback_count"),
            stage4_summary.get("stage4_public_evidence_readback_count"),
        ),
        "stage4_all_required_readbacks_ready": final_stage4_all_ready,
        "base_stage4_all_required_readbacks_ready": base_stage4_all_ready,
        "post_run_stage4_all_required_readbacks_ready": bool(post_run_stage4_all_ready)
        if post_run_stage4_all_ready is not None
        else False,
        "source_remediation_initial_record_count": source_remediation_initial_count,
        "source_remediation_final_record_count": final_source_remediation_count,
        "source_remediation_execution_state": str(
            remediation_execution_summary.get("source_remediation_execution_state")
            or closeout.get("source_remediation_execution_state")
            or ""
        ),
        "post_run_source_remediation_record_count": post_run_source_remediation_count
        if post_run_source_remediation_count is not None
        else 0,
        "partial_or_blocked_count": _first_int(
            closeout.get("partial_or_blocked_count"),
            _mapping(evidence_summary.get("public_source_outcome_counts")).get(
                "PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW"
            ),
        ),
        "no_match_count": _first_int(
            closeout.get("no_match_count"),
            _mapping(evidence_summary.get("public_source_outcome_counts")).get("PUBLIC_SOURCE_NO_MATCH_REVIEW"),
        ),
        "safety_boundary_closed": safety_boundary_closed,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": query_miss_is_not_clearance,
        "no_legal_conclusion": no_legal_conclusion,
        "public_release_allowed": False,
    }


def _eligibility_state(
    *,
    execute: bool,
    sample_count: int,
    fixed_snapshot_count: int,
    final_stage4_all_ready: bool,
    final_source_remediation_count: int,
    safety_boundary_closed: bool,
    no_legal_conclusion: bool,
    query_miss_is_not_clearance: bool,
) -> str:
    if not execute:
        return "NOT_READY_REAL_PUBLIC_EXECUTION_REQUIRED"
    if sample_count <= 0:
        return "NOT_READY_NO_REAL_PUBLIC_SAMPLES"
    if fixed_snapshot_count <= 0:
        return "NOT_READY_NO_FIXED_SNAPSHOT_HASHES"
    if not final_stage4_all_ready:
        return "NOT_READY_STAGE4_EVIDENCE_READBACK_REQUIRED"
    if final_source_remediation_count > 0:
        return "NOT_READY_SOURCE_REMEDIATION_REQUIRED"
    if not safety_boundary_closed:
        return "NOT_READY_SAFETY_BOUNDARY_OPEN"
    if not no_legal_conclusion or not query_miss_is_not_clearance:
        return "NOT_READY_BOUNDARY_SEMANTICS_REVIEW_REQUIRED"
    return "READY_FOR_HUMAN_GRAY_LAUNCH_REVIEW"


def _next_required_step(state: str) -> str:
    return {
        "NOT_READY_REAL_PUBLIC_EXECUTION_REQUIRED": "run_controlled_public_source_batch_with_execute",
        "NOT_READY_NO_REAL_PUBLIC_SAMPLES": "expand_or_fix_public_source_targets",
        "NOT_READY_NO_FIXED_SNAPSHOT_HASHES": "fix_evidence_snapshot_hashing",
        "NOT_READY_STAGE4_EVIDENCE_READBACK_REQUIRED": "run_stage4_evidence_readback_for_hashed_public_snapshots",
        "NOT_READY_SOURCE_REMEDIATION_REQUIRED": "execute_or_review_source_remediation_queue",
        "NOT_READY_SAFETY_BOUNDARY_OPEN": "close_customer_payment_delivery_release_flags_before_review",
        "NOT_READY_BOUNDARY_SEMANTICS_REVIEW_REQUIRED": "restore_no_clearance_and_no_legal_conclusion_boundaries",
    }.get(state, "review_gray_launch_package")


def _gray_sample_goal_state(
    sample_count: int,
    *,
    gray_sample_goal_min: int,
    gray_sample_goal_max: int,
) -> str:
    if sample_count <= 0:
        return "NO_GRAY_SAMPLE_COVERAGE"
    if sample_count >= gray_sample_goal_max:
        return "MEETS_GRAY_SAMPLE_TARGET_RANGE"
    if sample_count >= gray_sample_goal_min:
        return "MEETS_GRAY_SAMPLE_MINIMUM_GOAL"
    return "CATALOG_LIMITED_BELOW_GRAY_SAMPLE_GOAL"


def _checklist(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _item(
            "real_public_batch_executed",
            "Real public source batch executed",
            bool(summary.get("source_execute")) and _int(summary.get("project_sample_count")) > 0,
            f"sample_count={summary.get('project_sample_count')}",
        ),
        _item(
            "evidence_hashes_fixed",
            "Evidence snapshots have fixed hashes",
            _int(summary.get("fixed_snapshot_sha256_count")) > 0,
            f"fixed_snapshot_sha256_count={summary.get('fixed_snapshot_sha256_count')}",
        ),
        {
            "check_id": "gray_sample_goal_observed",
            "title": "Gray sample volume is observed against target",
            "state": "PASS" if bool(summary.get("gray_sample_goal_met")) else "WARN",
            "blocking": False,
            "evidence": (
                f"sample_count={summary.get('project_sample_count')} "
                f"goal={summary.get('gray_sample_goal_min')}-{summary.get('gray_sample_goal_max')} "
                f"state={summary.get('gray_sample_goal_state')}"
            ),
            "next_action": ""
            if bool(summary.get("gray_sample_goal_met"))
            else "expand_professional_public_source_target_catalog_or_accept_catalog_limited_gray_result",
        },
        _item(
            "stage4_readback_ready",
            "Stage4 evidence readback is complete",
            bool(summary.get("stage4_all_required_readbacks_ready")),
            f"missing={summary.get('stage4_readback_missing_sample_count')}",
        ),
        _item(
            "source_remediation_cleared",
            "Source remediation queue is cleared",
            _int(summary.get("source_remediation_final_record_count")) == 0,
            f"final_source_remediation_count={summary.get('source_remediation_final_record_count')}",
        ),
        _item(
            "customer_payment_delivery_closed",
            "Customer visible, payment, delivery, refund, and external send remain closed",
            bool(summary.get("safety_boundary_closed")),
            "customer_visible=false payment=false delivery=false automatic_refund=false",
        ),
        _item(
            "boundary_semantics_retained",
            "No-clearance and no-legal-conclusion boundaries are retained",
            bool(summary.get("query_miss_is_not_clearance")) and bool(summary.get("no_legal_conclusion")),
            "query miss is not clearance; no legal conclusion",
        ),
        {
            "check_id": "operator_gray_launch_approval",
            "title": "Operator records human gray launch decision",
            "state": "PASS"
            if bool(summary.get("approved_for_controlled_gray_execution"))
            else "WAITING_OPERATOR_APPROVAL"
            if str(summary.get("human_gray_launch_approval_state") or "") == "WAITING_OPERATOR_APPROVAL"
            else str(summary.get("human_gray_launch_approval_state") or "NOT_REQUESTABLE"),
            "blocking": not bool(summary.get("approved_for_controlled_gray_execution")),
            "evidence": str(summary.get("human_gray_launch_approval_state") or ""),
            "next_action": "record_operator_gray_launch_decision",
        },
    ]


def _item(check_id: str, title: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "title": title,
        "state": "PASS" if passed else "FAIL",
        "blocking": not passed,
        "evidence": evidence,
        "next_action": "" if passed else "repair_before_gray_review",
    }


def _checklist_summary(checklist: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = _counts(record.get("state") for record in checklist)
    blocking_fail_count = sum(
        1
        for record in checklist
        if bool(record.get("blocking")) and str(record.get("state") or "") == "FAIL"
    )
    return {
        "check_count": len(checklist),
        "state_counts": counts,
        "blocking_fail_count": blocking_fail_count,
        "waiting_operator_approval_count": counts.get("WAITING_OPERATOR_APPROVAL", 0),
    }


def _gray_run_plan(
    summary: Mapping[str, Any],
    *,
    gray_sample_goal_min: int,
    gray_sample_goal_max: int,
) -> dict[str, Any]:
    ready = bool(summary.get("eligible_for_human_gray_launch_review"))
    approved = bool(summary.get("approved_for_controlled_gray_execution"))
    return {
        "plan_id": "controlled-gray-public-source-batch-v1",
        "plan_state": (
            "APPROVED_FOR_CONTROLLED_GRAY_EXECUTION"
            if approved
            else "READY_AFTER_OPERATOR_APPROVAL"
            if ready
            else "BLOCKED_UNTIL_REVIEW_READY"
        ),
        "operator_approval_required": True,
        "public_source_only": True,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "sample_goal_min": max(1, int(gray_sample_goal_min)),
        "sample_goal_max": max(max(1, int(gray_sample_goal_min)), int(gray_sample_goal_max)),
        "recommended_command": (
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
            "scripts\\run-controlled-gray-public-orchestrator-v1.ps1 "
            "-OutputRoot tmp\\evaluation-real-samples\\controlled-gray-public-batch-segments-<yyyymmdd-HHMMSS> "
            "-PerTargetSampleGoal 12 -GroupBy target -TargetLimit 0 -PerTargetCandidateLimit 12 "
            "-SegmentTimeoutSeconds 900 -ProfessionalSourceOnly "
            "-Execute -AutoExecuteSourceRemediation"
        ),
        "stop_conditions": [
            "stage4_readback_missing_sample_count > 0",
            "source_remediation_final_record_count > 0 after auto remediation",
            "customer_visible/payment/delivery/external_send/automatic_refund flag becomes true",
            "new source profile returns login, SSO, captcha, or unresolved blocker without alternate route",
            "evidence hash generation fails for any captured public snapshot",
        ],
        "success_exit_criteria": [
            "100-200 controlled public-source samples reviewed or catalog-limited capacity documented",
            "all required Stage4 readbacks ready",
            "source remediation queue cleared or explicitly held for human review",
            "all safety flags remain closed",
            "operator records next decision: continue gray, expand sources, or hold",
        ],
    }


def _safety_boundary_closed(*sources: Mapping[str, Any]) -> bool:
    for source in sources:
        for key in (
            "customer_visible_allowed",
            "external_send_enabled",
            "payment_execution_enabled",
            "delivery_execution_enabled",
            "automatic_refund_enabled",
            "public_release_allowed",
        ):
            if _truthy(source.get(key)):
                return False
    return True


def _safety() -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "public_release_allowed": False,
        "operator_approval_required_before_gray_execution": True,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _operator_decision_record(
    summary: Mapping[str, Any],
    *,
    operator_decision: str,
    operator_name: str,
    operator_decision_note: str,
    created_at: str,
) -> dict[str, Any]:
    decision = _normalize_operator_decision(operator_decision)
    approval_state = str(summary.get("human_gray_launch_approval_state") or "")
    record = {
        "decision_record_id": _stable_id(
            "CLPB-GRAY-DECISION",
            summary.get("gray_launch_review_state"),
            approval_state,
            operator_name,
            operator_decision_note,
        ),
        "created_at": created_at,
        "operator_name": str(operator_name or ""),
        "operator_decision": decision,
        "operator_decision_note": str(operator_decision_note or ""),
        "approval_state": approval_state,
        "approved_for_controlled_gray_execution": bool(
            summary.get("approved_for_controlled_gray_execution")
        ),
        "scope": "controlled_gray_public_source_only",
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "public_release_allowed": False,
    }
    record["decision_record_sha256"] = _fingerprint(record)
    return record


def _normalize_operator_decision(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"APPROVED", "APPROVE", "ALLOW", "YES"}:
        return "APPROVED"
    if text in {"HOLD", "HELD", "PAUSE"}:
        return "HOLD"
    if text in {"REJECTED", "REJECT", "DENY", "DENIED", "NO"}:
        return "REJECTED"
    return "UNSPECIFIED"


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    checklist = _records(_mapping(result.get("gray_launch_checklist")).get("records"))
    plan = _mapping(result.get("gray_run_plan"))
    decision = _mapping(result.get("operator_decision_record"))
    lines = [
        "# Controlled Live Public Batch Gray Launch Review",
        "",
        f"- gray_launch_review_state: {summary.get('gray_launch_review_state')}",
        f"- eligible_for_human_gray_launch_review: {str(bool(summary.get('eligible_for_human_gray_launch_review'))).lower()}",
        f"- human_gray_launch_approval_state: {summary.get('human_gray_launch_approval_state')}",
        f"- approved_for_controlled_gray_execution: {str(bool(summary.get('approved_for_controlled_gray_execution'))).lower()}",
        f"- next_required_step: {summary.get('next_required_step')}",
        f"- project_sample_count: {summary.get('project_sample_count')}",
        f"- gray_sample_goal_state: {summary.get('gray_sample_goal_state')}",
        f"- fixed_snapshot_sha256_count: {summary.get('fixed_snapshot_sha256_count')}",
        f"- stage4_all_required_readbacks_ready: {str(bool(summary.get('stage4_all_required_readbacks_ready'))).lower()}",
        f"- source_remediation_final_record_count: {summary.get('source_remediation_final_record_count')}",
        f"- safety_boundary_closed: {str(bool(summary.get('safety_boundary_closed'))).lower()}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- payment_execution_enabled: {str(bool(summary.get('payment_execution_enabled'))).lower()}",
        f"- delivery_execution_enabled: {str(bool(summary.get('delivery_execution_enabled'))).lower()}",
        "",
        "## Operator Decision",
        f"- operator_decision: {decision.get('operator_decision')}",
        f"- approval_state: {decision.get('approval_state')}",
        f"- decision_record_sha256: {decision.get('decision_record_sha256')}",
        "",
        "## Checklist",
    ]
    for record in checklist:
        lines.append(f"- {record.get('state')}: {record.get('check_id')} - {record.get('evidence')}")
    lines.extend(
        [
            "",
            "## Gray Run Plan",
            f"- plan_state: {plan.get('plan_state')}",
            f"- sample_goal_min: {plan.get('sample_goal_min')}",
            f"- sample_goal_max: {plan.get('sample_goal_max')}",
            f"- recommended_command: `{plan.get('recommended_command')}`",
            "",
            "## Stop Conditions",
        ]
    )
    for item in _string_list(plan.get("stop_conditions")):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
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


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        json.dumps([str(part or "") for part in parts], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _first_int(*values: Any) -> int:
    for value in values:
        if value not in (None, ""):
            return _int(value)
    return 0


def _first_known_int(*values: Any) -> int | None:
    for value in values:
        if value not in (None, ""):
            return _int(value)
    return None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_bool(*values: Any) -> bool:
    for value in values:
        if value not in (None, ""):
            return _truthy(value)
    return False


def _first_known_bool(*values: Any) -> bool | None:
    for value in values:
        if value not in (None, ""):
            return _truthy(value)
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "enabled", "allow", "allowed"}


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closeout-json", default="")
    parser.add_argument("--evidence-summary-json", default="")
    parser.add_argument("--stage4-readback-json", default="")
    parser.add_argument("--source-remediation-json", default="")
    parser.add_argument("--source-remediation-execution-json", default="")
    parser.add_argument("--run-manifest-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--gray-sample-goal-min", type=int, default=100)
    parser.add_argument("--gray-sample-goal-max", type=int, default=200)
    parser.add_argument("--operator-decision", default="")
    parser.add_argument("--operator-name", default="")
    parser.add_argument("--operator-decision-note", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_controlled_live_public_batch_gray_launch_review(
        closeout_json=args.closeout_json or None,
        evidence_summary_json=args.evidence_summary_json or None,
        stage4_readback_json=args.stage4_readback_json or None,
        source_remediation_json=args.source_remediation_json or None,
        source_remediation_execution_json=args.source_remediation_execution_json or None,
        run_manifest_json=args.run_manifest_json or None,
        output_root=args.output_root,
        gray_sample_goal_min=args.gray_sample_goal_min,
        gray_sample_goal_max=args.gray_sample_goal_max,
        operator_decision=args.operator_decision,
        operator_name=args.operator_name,
        operator_decision_note=args.operator_decision_note,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
