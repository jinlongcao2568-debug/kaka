from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


TERMINAL_RELEASE_EVIDENCE_ABCD_GRADES = {
    "B_ENHANCEMENT_OFFICIAL_READBACK",
    "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
    "D_INSUFFICIENT_OR_BLOCKED_READBACK",
}

TERMINAL_FIELD_ADAPTER_STATES = {"MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"}
RELEASE_EVIDENCE_TERMINAL_FIELD_ADAPTER_STATES = {"MATCHED"}

P13B_CLOSEOUT_PROJECT_STATES = {
    "OVERLAP_SIGNAL_REVIEW_REQUIRED",
    "ORIGINAL_NOTICE_READBACK_REQUIRED",
    "SOURCE_LIMIT_DEFERRED",
    "YGP_READBACK_BLOCKED_OR_UNSUPPORTED",
    "NO_OVERLAP_SIGNAL_REVIEW",
}

TERMINAL_BATCH_CLOSEOUT_STATES = {
    "PARK_D_INSUFFICIENT_OR_BLOCKED",
    "PARK_NO_CLEARANCE_CLAIM",
    "DEFER_NON_MAINLINE_OR_SCOPE",
}

TERMINAL_ORIGINAL_BACKTRACE_NEXT_ACTION = "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM"
ORIGINAL_READBACK_PROJECTION_ONLY_TERMINAL_STATES = {
    "RELEASE_EVIDENCE_READY",
    "TARGETED_PERSON_READBACK_REQUIRED",
    "TARGETED_YGP_READBACK_REQUIRED",
    "ROUTE_SPECIFIC_READBACK_REQUIRED",
    "PARK_DIFFERENT_PERSON_WITH_PERIOD",
    "PARK_DIFFERENT_PERSON_NO_PERIOD",
    "LOW_VALUE_COMPANY_ONLY_REVIEW",
    "PARK_NO_EXTRACTED_MATCH_FIELDS",
    "PARK_TARGETED_PERSON_NOT_FOUND",
    "PARK_LOW_VALUE_REVIEW",
}

TERMINAL_MARKER_STATES = (
    TERMINAL_RELEASE_EVIDENCE_ABCD_GRADES
    | TERMINAL_FIELD_ADAPTER_STATES
    | P13B_CLOSEOUT_PROJECT_STATES
    | TERMINAL_BATCH_CLOSEOUT_STATES
    | {
        "TERMINAL_CLOSEOUT_RECORDED",
        "TERMINAL_BACKFILL_RECORDED",
        "TERMINAL_CLOSEOUT_BACKFILLED",
        "TERMINAL_WORKER_RESULT_RECORDED",
        "RELEASE_FIELD_QUERY_REVIEW_READY",
        "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
        "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
        "RELEASE_FIELD_QUERY_AUTHORIZATION_HOLD",
        "RELEASE_EVIDENCE_READY",
        "DONE",
        "CLOSED",
        "REVIEW_READY",
        "PACKAGE_READY",
    }
)

RUNTIME_BLOCKER_SUBQUEUE_ROUTE_ORDER = (
    "browser_worker",
    "fallback_source",
    "retry",
    "manual_hold",
    "suspend_dead_letter",
    "operator_action",
)


def closeout_precedence_for_record(
    record: Mapping[str, Any],
    *,
    task_scope: str,
    task_type: str = "",
) -> dict[str, Any]:
    scope = _canonical_scope(task_scope)
    marker = _explicit_marker(record, task_scope=scope)
    if marker:
        return _decision(
            record,
            task_scope=scope,
            task_type=task_type,
            marker=marker,
            reason=str(marker.get("suppression_reason") or "terminal_closeout_marker_present"),
            runtime_layer=str(marker.get("runtime_layer") or "controller decision"),
        )

    if scope == "release_evidence_query":
        grade = str(record.get("downstream_release_evidence_abcd_grade") or "").strip()
        if grade in TERMINAL_RELEASE_EVIDENCE_ABCD_GRADES:
            return _decision(
                record,
                task_scope=scope,
                task_type=task_type,
                marker={
                    "terminal_marker_type": "release_evidence_downstream_abcd_grade",
                    "terminal_grade": grade,
                    "terminal_state": grade,
                    "runtime_layer": "closeout",
                },
                reason="release_evidence_query_terminal_downstream_grade_present",
                runtime_layer="closeout",
            )
        adapter_state = str(record.get("adapter_result_state") or "").strip()
        if adapter_state in RELEASE_EVIDENCE_TERMINAL_FIELD_ADAPTER_STATES and _is_release_evidence_record(record):
            return _decision(
                record,
                task_scope=scope,
                task_type=task_type,
                marker={
                    "terminal_marker_type": "release_evidence_adapter_result_state",
                    "terminal_state": adapter_state,
                    "runtime_layer": "worker execution",
                },
                reason="release_evidence_query_terminal_adapter_state_present",
                runtime_layer="worker execution",
            )

    if scope == "p13b_follow_up":
        p13b_state = str(record.get("project_overlap_triage_state") or "").strip()
        if p13b_state in P13B_CLOSEOUT_PROJECT_STATES:
            return _decision(
                record,
                task_scope=scope,
                task_type=task_type,
                marker={
                    "terminal_marker_type": "p13b_operational_closeout_project_state",
                    "terminal_state": p13b_state,
                    "runtime_layer": "closeout",
                },
                reason="p13b_operational_closeout_marker_present",
                runtime_layer="closeout",
            )

    if scope == "original_readback" and _is_terminal_original_backtrace_no_delta(record):
        return _decision(
            record,
            task_scope=scope,
            task_type=task_type,
            marker={
                "terminal_marker_type": "original_backtrace_continuation_no_delta",
                "terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                "runtime_layer": "closeout",
            },
            reason="terminal_source_gap_no_delta_manual_review_only",
            runtime_layer="closeout",
        )

    closeout_state = str(record.get("closeout_state") or "").strip()
    if closeout_state in TERMINAL_BATCH_CLOSEOUT_STATES and scope in {
        "project",
        "stage4_field_task",
    }:
        return _decision(
            record,
            task_scope=scope,
            task_type=task_type,
            marker={
                "terminal_marker_type": "evidence_batch_closeout_state",
                "terminal_state": closeout_state,
                "runtime_layer": "closeout",
            },
            reason="evidence_batch_terminal_closeout_state_present",
            runtime_layer="closeout",
        )

    return {
        "closeout_precedence_state": "NO_TERMINAL_CLOSEOUT_MARKER",
        "should_suppress_dispatch": False,
        "task_scope": scope,
        "task_type": task_type,
        "terminal_marker": {},
        "suppression_reason": "",
        "runtime_layer": "",
        "next_action": "",
        "operator_next_action": "",
        "retry_policy": "",
        "required_input": [],
        "reopen_conditions": [],
        "subqueue_routes": [],
    }


def closeout_precedence_decision(
    record: Mapping[str, Any],
    *,
    task_family: str = "",
    runtime_layer: str = "",
) -> dict[str, Any]:
    action_family = str(record.get("action_family") or "")
    dispatch_task_type = str(record.get("dispatch_task_type") or record.get("next_task_type") or "")
    explicit_task_family = str(task_family or record.get("runtime_task_family") or "").strip()
    requested_scope = _canonical_scope(
        explicit_task_family
        or _scope_for_action_family(action_family or dispatch_task_type)
    )
    if not explicit_task_family and _record_has_p13b_followup_terminal_signal(record):
        requested_scope = "p13b_follow_up"
    matched_markers = _matching_runtime_markers(record, requested_scope)
    if matched_markers:
        marker = dict(matched_markers[0])
        marker_state = str(marker.get("marker_state") or marker.get("terminal_state") or "")
        decision = _decision(
            record,
            task_scope=requested_scope,
            task_type=action_family or dispatch_task_type,
            marker={
                **marker,
                "terminal_marker_type": str(marker.get("terminal_marker_type") or "runtime_closeout_marker"),
                "terminal_state": marker_state,
                "runtime_layer": runtime_layer or str(marker.get("runtime_layer") or "controller decision"),
            },
            reason="terminal_closeout_or_backfill_marker_present",
            runtime_layer=runtime_layer or str(marker.get("runtime_layer") or "controller decision"),
        )
        operator_next_action = _runtime_marker_operator_next_action(requested_scope, marker_state)
        decision.update(
            {
                "closeout_precedence_state": "SUPPRESS_TERMINAL_CLOSEOUT",
                "matched_marker_count": len(matched_markers),
                "matched_markers": matched_markers,
                "suppressed_dispatch": True,
                "blocker_taxonomy": _dedupe(
                    [
                        *[blocker for item in matched_markers for blocker in _list(item.get("blocker_taxonomy"))],
                        "terminal_closeout_or_backfill_marker_present",
                    ]
                ),
                "operator_next_action": operator_next_action,
                "next_action": operator_next_action,
            }
        )
        return decision

    decision = closeout_precedence_for_record(
        record,
        task_scope=requested_scope,
        task_type=action_family or dispatch_task_type,
    )
    if runtime_layer and decision.get("should_suppress_dispatch"):
        decision = dict(decision)
        decision["runtime_layer"] = runtime_layer
    decision["suppressed_dispatch"] = bool(decision.get("should_suppress_dispatch"))
    decision["matched_marker_count"] = 1 if decision["suppressed_dispatch"] else 0
    decision["matched_markers"] = [dict(decision.get("terminal_marker") or {})] if decision["suppressed_dispatch"] else []
    decision["blocker_taxonomy"] = [str(decision.get("suppression_reason") or "")] if decision["suppressed_dispatch"] else []
    if not decision["suppressed_dispatch"]:
        decision["closeout_precedence_state"] = "ALLOW_DISPATCH_NO_TERMINAL_MARKER"
    return decision


def closeout_precedence_summary(decisions: Iterable[Any]) -> dict[str, Any]:
    rows = [dict(item) for item in decisions if isinstance(item, Mapping)]
    suppressed = [row for row in rows if bool(row.get("suppressed_dispatch") or row.get("should_suppress_dispatch"))]
    return {
        "closeout_precedence_decision_count": len(rows),
        "closeout_precedence_suppressed_count": len(suppressed),
        "terminal_closeout_suppressed_dispatch_count": len(suppressed),
        "closeout_precedence_state_counts": counts(row.get("closeout_precedence_state") for row in rows),
        "terminal_closeout_suppression_reason_counts": counts(row.get("suppression_reason") for row in suppressed),
        "runtime_layer_counts": counts(row.get("runtime_layer") for row in suppressed),
        "closeout_precedence_blocker_taxonomy_counts": counts(
            blocker for row in suppressed for blocker in _list(row.get("blocker_taxonomy"))
        ),
    }


def blocker_ledger_record(
    record: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    ledger_scope: str,
) -> dict[str, Any]:
    project_id = str(record.get("project_id") or "")
    task_id = _task_id(record)
    reason = str(decision.get("suppression_reason") or "terminal_closeout_marker_present")
    runtime_layer = str(decision.get("runtime_layer") or "controller decision")
    return {
        "blocker_ledger_id": _stable_id("RUNTIME-BLOCKER", ledger_scope, project_id, task_id, reason),
        "ledger_scope": ledger_scope,
        "project_id": project_id,
        "project_name": str(record.get("project_name") or ""),
        "task_id": task_id,
        "task_scope": str(decision.get("task_scope") or ""),
        "task_type": str(decision.get("task_type") or ""),
        "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
        "blocker_reason": reason,
        "runtime_layer": runtime_layer,
        "required_input": list(decision.get("required_input") or []),
        "retry_policy": str(decision.get("retry_policy") or ""),
        "reopen_conditions": list(decision.get("reopen_conditions") or []),
        "operator_next_action": str(decision.get("operator_next_action") or ""),
        "next_action": str(decision.get("next_action") or ""),
        "terminal_marker": dict(decision.get("terminal_marker") or {}),
        "subqueue_routes": _closeout_precedence_subqueue_routes(decision),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _closeout_precedence_subqueue_routes(decision: Mapping[str, Any]) -> list[str]:
    task_scope = str(decision.get("task_scope") or "")
    terminal_marker = (
        decision.get("terminal_marker") if isinstance(decision.get("terminal_marker"), Mapping) else {}
    )
    terminal_state = str(
        terminal_marker.get("terminal_state") or terminal_marker.get("terminal_grade") or ""
    ).strip()
    if task_scope == "release_evidence_query" and (
        terminal_state in {
            "MATCHED",
            "REVIEW_READY",
            "RELEASE_FIELD_QUERY_REVIEW_READY",
            "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
        }
        or terminal_state.startswith(("B_", "C_"))
    ):
        return ["manual_hold", "operator_action"]
    return []


def runtime_blocker_record_subqueues(record: Mapping[str, Any]) -> list[str]:
    explicit_routes = _explicit_runtime_blocker_routes(record)
    if explicit_routes:
        return _ordered_subqueues(explicit_routes)
    state = str(record.get("blocker_state") or "")
    layer = str(record.get("runtime_layer") or "")
    reason = str(record.get("blocker_reason") or "")
    retry_policy = str(record.get("retry_policy") or "")
    action = str(record.get("operator_next_action") or record.get("next_action") or "")
    required_inputs = " ".join(str(item or "") for item in _list(record.get("required_input")))
    reopen_conditions = " ".join(str(item or "") for item in _list(record.get("reopen_conditions")))
    haystack = " ".join([state, layer, reason, retry_policy, action, required_inputs, reopen_conditions]).lower()
    routes: list[str] = []
    if "browser" in haystack or "login_or_sso" in haystack or "authorized_session" in haystack:
        routes.append("browser_worker")
    if "fallback" in haystack or "not_found" in state.lower() or "source_blocked" in state.lower():
        routes.append("fallback_source")
    if retry_policy.startswith("retry_") or "same_session_retry" in haystack or "operator_retry_budget" in haystack:
        routes.append("retry")
    if (
        state == "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH"
        or retry_policy.startswith("manual_reopen")
        or retry_policy.startswith("do_not_retry")
        or "manual_hold" in haystack
        or "manual_review" in haystack
    ):
        routes.append("manual_hold")
    if state == "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH" or "dead_letter" in haystack or "suspend" in haystack:
        routes.append("suspend_dead_letter")
    if action:
        routes.append("operator_action")
    return _ordered_subqueues(routes)


def is_original_readback_projection_only_terminal_state(state: str) -> bool:
    return str(state or "").strip() in ORIGINAL_READBACK_PROJECTION_ONLY_TERMINAL_STATES


def _explicit_runtime_blocker_routes(record: Mapping[str, Any]) -> list[str]:
    routes: list[str] = []
    explicit_route = str(record.get("subqueue_route") or "").strip()
    if explicit_route:
        routes.append(explicit_route)
    for item in _list(record.get("subqueue_routes")):
        route = str(item or "").strip()
        if route:
            routes.append(route)
    return _ordered_subqueues(routes)


def runtime_blocker_subqueue_routes(records: Iterable[Mapping[str, Any]]) -> list[str]:
    routes: list[str] = []
    for record in records:
        if isinstance(record, Mapping):
            routes.extend(runtime_blocker_record_subqueues(record))
    return _ordered_subqueues(routes)


def build_runtime_blocker_next_subqueue_table(
    project_status_records: Iterable[Mapping[str, Any]],
    *,
    source_status_table_ref: str = "",
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for status_record in project_status_records:
        if not isinstance(status_record, Mapping):
            continue
        for blocker in _list(status_record.get("runtime_blocker_ledger_records")):
            if not isinstance(blocker, Mapping) or not blocker:
                continue
            for route in runtime_blocker_record_subqueues(blocker):
                records.append(
                    _runtime_blocker_next_subqueue_record(
                        status_record,
                        blocker,
                        route=route,
                        source_status_table_ref=source_status_table_ref,
                    )
                )
    return {
        "table_kind": "runtime_blocker_next_subqueue_table_v1",
        "source_status_table_ref": source_status_table_ref,
        "summary": {
            "next_subqueue_record_count": len(records),
            "subqueue_route_counts": counts(record.get("subqueue_route") for record in records),
            "subqueue_state_counts": counts(record.get("subqueue_state") for record in records),
            "runtime_layer_counts": counts(record.get("runtime_layer") for record in records),
            "required_input_counts": counts(
                required_input
                for record in records
                for required_input in _list(record.get("required_input"))
            ),
            "retry_policy_counts": counts(record.get("retry_policy") for record in records),
            "operator_next_action_counts": counts(record.get("operator_next_action") for record in records),
        },
        "records": records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def build_runtime_blocker_subqueue_controller_table(
    next_subqueue_table: Mapping[str, Any] | None,
    *,
    source_next_subqueue_ref: str = "",
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    source = dict(next_subqueue_table or {})
    for raw in _list(source.get("records")):
        if not isinstance(raw, Mapping) or not raw:
            continue
        route = str(raw.get("subqueue_route") or "").strip()
        if not route:
            continue
        records.append(
            _runtime_blocker_controller_queue_record(
                raw,
                route=route,
                source_next_subqueue_ref=source_next_subqueue_ref,
            )
        )
    return {
        "table_kind": "runtime_blocker_subqueue_controller_table_v1",
        "source_next_subqueue_ref": source_next_subqueue_ref,
        "summary": {
            "controller_queue_record_count": len(records),
            "subqueue_route_counts": counts(record.get("subqueue_route") for record in records),
            "controller_route_state_counts": counts(record.get("controller_route_state") for record in records),
            "controller_next_action_counts": counts(record.get("controller_next_action") for record in records),
            "dispatch_worker_family_counts": counts(record.get("dispatch_worker_family") for record in records),
            "automated_worker_dispatch_allowed_count": sum(
                1 for record in records if bool(record.get("automated_worker_dispatch_allowed"))
            ),
            "required_input_counts": counts(
                required_input
                for record in records
                for required_input in _list(record.get("required_input"))
            ),
        },
        "records": records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def build_runtime_blocker_controller_dispatch_table(
    controller_table: Mapping[str, Any] | None,
    *,
    output_root: str = "",
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    source = dict(controller_table or {})
    for raw in _list(source.get("records")):
        if not isinstance(raw, Mapping) or not raw:
            continue
        records.append(_runtime_blocker_controller_dispatch_record(raw, output_root=output_root))
    return {
        "table_kind": "runtime_blocker_controller_dispatch_task_table_v1",
        "source_controller_table_ref": str(source.get("source_next_subqueue_ref") or ""),
        "summary": {
            "controller_dispatch_task_count": len(records),
            "dispatch_readiness_state_counts": counts(record.get("dispatch_readiness_state") for record in records),
            "dispatch_route_counts": counts(record.get("dispatch_route") for record in records),
            "dispatch_worker_family_counts": counts(record.get("dispatch_worker_family") for record in records),
            "ready_for_controlled_worker_dispatch_count": sum(
                1
                for record in records
                if record.get("dispatch_readiness_state") == "READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH"
            ),
            "manual_hold_or_operator_action_count": sum(
                1
                for record in records
                if record.get("dispatch_readiness_state")
                in {
                    "MANUAL_HOLD_RECORDED_NO_WORKER_DISPATCH",
                    "OPERATOR_ACTION_RECORDED_NO_WORKER_DISPATCH",
                    "SUSPEND_DEAD_LETTER_RECORDED_NO_WORKER_DISPATCH",
                }
            ),
            "blocking_reason_counts": counts(
                reason
                for record in records
                for reason in _list(record.get("dispatch_blocking_reasons"))
            ),
        },
        "records": records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def p13b_project_terminal_marker(record: Mapping[str, Any]) -> dict[str, Any]:
    decision = closeout_precedence_for_record(record, task_scope="p13b_follow_up")
    return dict(decision.get("terminal_marker") or {}) if decision.get("should_suppress_dispatch") else {}


def release_field_query_terminal_marker(record: Mapping[str, Any]) -> dict[str, Any]:
    decision = closeout_precedence_for_record(record, task_scope="release_evidence_query")
    return dict(decision.get("terminal_marker") or {}) if decision.get("should_suppress_dispatch") else {}


def _decision(
    record: Mapping[str, Any],
    *,
    task_scope: str,
    task_type: str,
    marker: Mapping[str, Any],
    reason: str,
    runtime_layer: str,
) -> dict[str, Any]:
    marker_copy = dict(marker)
    marker_copy.setdefault("project_id", str(record.get("project_id") or ""))
    marker_copy.setdefault("project_name", str(record.get("project_name") or ""))
    marker_copy.setdefault("task_id", _task_id(record))
    return {
        "closeout_precedence_state": "SUPPRESS_DUPLICATE_WORKER_DISPATCH",
        "should_suppress_dispatch": True,
        "task_scope": task_scope,
        "task_type": task_type,
        "terminal_marker": marker_copy,
        "suppression_reason": reason,
        "runtime_layer": runtime_layer,
        "next_action": _next_action(task_scope, reason, marker_copy),
        "operator_next_action": _operator_next_action(task_scope, reason, marker_copy),
        "retry_policy": _retry_policy(reason, marker_copy),
        "required_input": _required_input(task_scope, reason, marker_copy),
        "reopen_conditions": _reopen_conditions(task_scope, reason, marker_copy),
        "blocker_taxonomy": _dedupe([*_list(marker_copy.get("blocker_taxonomy")), reason]),
        "marker_source_refs": [
            {
                "source_ref": str(marker_copy.get("source_ref") or marker_copy.get("terminal_marker_type") or ""),
                "artifact_ref": str(marker_copy.get("artifact_ref") or marker_copy.get("source_json") or ""),
            }
        ],
        "operator_projection": {
            "projection_state": "MANUAL_HOLD_OR_STATUS_PROJECTION",
            "owner_status": "terminal_closeout_recorded_no_duplicate_dispatch",
            "owner_next_action": _operator_next_action(task_scope, reason, marker_copy),
            "raw_json_required_for_next_step": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _explicit_marker(record: Mapping[str, Any], *, task_scope: str = "") -> dict[str, Any]:
    for key in (
        "terminal_closeout_marker",
        "closeout_precedence_marker",
        "terminal_dispatch_suppression_marker",
    ):
        marker = _first_matching_marker(record.get(key), task_scope=task_scope, source_ref=key)
        if marker:
            return marker
    for key in (
        "terminal_closeout_markers",
        "runtime_closeout_markers",
        "closeout_backfill_markers",
        "terminal_backfill_markers",
    ):
        marker = _first_matching_marker(record.get(key), task_scope=task_scope, source_ref=key)
        if marker:
            return marker
    source_refs = record.get("source_refs") if isinstance(record.get("source_refs"), Mapping) else {}
    for key in (
        "terminal_closeout_markers",
        "runtime_closeout_markers",
        "closeout_backfill_markers",
        "terminal_backfill_markers",
    ):
        marker = _first_matching_marker(source_refs.get(key), task_scope=task_scope, source_ref=f"source_refs.{key}")
        if marker:
            return marker
    state = str(record.get("terminal_closeout_state") or "").strip()
    if state and _is_terminal_state_for_scope(task_scope, state):
        return {
            "terminal_marker_type": "explicit_terminal_closeout_state",
            "terminal_state": state,
            "runtime_layer": str(record.get("terminal_closeout_runtime_layer") or "closeout"),
            "source_ref": "terminal_closeout_state",
        }
    scoped_states = {
        "p13b_follow_up": ("p13b_followup_terminal_state", "p13b_terminal_closeout_state"),
        "original_readback": ("original_readback_terminal_state", "original_notice_readback_terminal_state"),
        "release_evidence_query": (
            "release_evidence_query_terminal_state",
            "release_field_query_terminal_state",
            "release_field_query_state",
        ),
    }
    for key in scoped_states.get(task_scope, ()):
        state = str(record.get(key) or "").strip()
        if state and _is_terminal_state_for_scope(task_scope, state):
            return {
                "terminal_marker_type": key,
                "terminal_state": state,
                "runtime_layer": "closeout",
                "source_ref": key,
            }
    return {}


def _matching_runtime_markers(record: Mapping[str, Any], task_scope: str) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for key in (
        "terminal_closeout_markers",
        "runtime_closeout_markers",
        "closeout_backfill_markers",
        "terminal_backfill_markers",
    ):
        markers.extend(_all_matching_markers(record.get(key), task_scope=task_scope, source_ref=key))
    source_refs = record.get("source_refs") if isinstance(record.get("source_refs"), Mapping) else {}
    for key in (
        "terminal_closeout_markers",
        "runtime_closeout_markers",
        "closeout_backfill_markers",
        "terminal_backfill_markers",
    ):
        markers.extend(_all_matching_markers(source_refs.get(key), task_scope=task_scope, source_ref=f"source_refs.{key}"))
    return markers


def _record_has_p13b_followup_terminal_signal(record: Mapping[str, Any]) -> bool:
    for key in ("p13b_followup_terminal_state", "p13b_terminal_closeout_state"):
        if str(record.get(key) or "").strip():
            return True
    if str(record.get("project_overlap_triage_state") or "").strip() in P13B_CLOSEOUT_PROJECT_STATES:
        return True
    for key in (
        "terminal_closeout_markers",
        "runtime_closeout_markers",
        "closeout_backfill_markers",
        "terminal_backfill_markers",
    ):
        if _all_matching_markers(record.get(key), task_scope="p13b_follow_up", source_ref=key):
            return True
    source_refs = record.get("source_refs") if isinstance(record.get("source_refs"), Mapping) else {}
    for key in (
        "terminal_closeout_markers",
        "runtime_closeout_markers",
        "closeout_backfill_markers",
        "terminal_backfill_markers",
    ):
        if _all_matching_markers(source_refs.get(key), task_scope="p13b_follow_up", source_ref=f"source_refs.{key}"):
            return True
    return False


def _all_matching_markers(value: Any, *, task_scope: str, source_ref: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, Mapping) and not any(
        key in value for key in ("task_family", "task_scope", "marker_state", "terminal_state", "state")
    ):
        iterable = [
            {"task_family": key, **(dict(item) if isinstance(item, Mapping) else {"marker_state": item})}
            for key, item in value.items()
        ]
    else:
        iterable = _list(value)
    for raw in iterable:
        marker = _first_matching_marker(raw, task_scope=task_scope, source_ref=source_ref)
        if marker:
            rows.append(marker)
    return rows


def _first_matching_marker(value: Any, *, task_scope: str, source_ref: str) -> dict[str, Any]:
    for raw in _list(value):
        if not isinstance(raw, Mapping) or not raw:
            continue
        marker = dict(raw)
        marker.setdefault("source_ref", source_ref)
        if not _marker_matches_scope(marker, task_scope):
            continue
        marker_state = str(
            marker.get("terminal_state")
            or marker.get("marker_state")
            or marker.get("closeout_state")
            or marker.get("result_state")
            or marker.get("state")
            or ""
        ).strip()
        if marker_state and not _marker_state_suppresses_dispatch(
            task_scope,
            marker_state,
            source_ref=source_ref,
        ):
            continue
        if _marker_is_terminal(marker, task_scope=task_scope) or source_ref in {
            "terminal_closeout_marker",
            "closeout_precedence_marker",
            "terminal_dispatch_suppression_marker",
        }:
            marker.setdefault(
                "terminal_state",
                str(marker.get("marker_state") or marker.get("state") or "TERMINAL_CLOSEOUT_RECORDED"),
            )
            marker.setdefault("terminal_marker_type", str(marker.get("marker_type") or source_ref))
            return marker
    return {}


def _marker_matches_scope(marker: Mapping[str, Any], task_scope: str) -> bool:
    raw_scope = str(
        marker.get("task_scope")
        or marker.get("task_family")
        or marker.get("worker_family")
        or marker.get("runtime_task_family")
        or marker.get("dispatch_task_type")
        or ""
    ).strip()
    if not raw_scope:
        return True
    marker_scope = _canonical_scope(raw_scope)
    if marker_scope in {"*", "any"}:
        return True
    if marker_scope == task_scope:
        return True
    if marker_scope == "release_evidence_query" and task_scope == "stage4_field_task":
        return True
    return False


def _marker_is_terminal(marker: Mapping[str, Any], *, task_scope: str = "") -> bool:
    state = str(
        marker.get("terminal_state")
        or marker.get("marker_state")
        or marker.get("closeout_state")
        or marker.get("result_state")
        or marker.get("state")
        or ""
    ).strip()
    source_ref = str(marker.get("source_ref") or "")
    if bool(marker.get("terminal") or marker.get("terminal_closeout") or marker.get("backfilled")):
        return True if not state else _marker_state_suppresses_dispatch(task_scope, state, source_ref=source_ref)
    return _marker_state_suppresses_dispatch(task_scope, state, source_ref=source_ref)


def _marker_state_suppresses_dispatch(task_scope: str, state: str, *, source_ref: str = "") -> bool:
    terminal_state = str(state or "").strip()
    if not terminal_state:
        return False
    if (
        task_scope == "release_evidence_query"
        and terminal_state == "NOT_FOUND"
        and str(source_ref or "").endswith("terminal_closeout_markers")
    ):
        return True
    return _is_terminal_state_for_scope(task_scope, terminal_state)


def _is_terminal_state_for_scope(task_scope: str, state: str) -> bool:
    terminal_state = str(state or "").strip()
    if not terminal_state:
        return False
    if task_scope == "original_readback":
        return terminal_state != "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT"
    if task_scope == "release_evidence_query" and terminal_state in {
        "BLOCKED",
        "NEEDS_BROWSER",
        "NOT_FOUND",
        "RELEASE_FIELD_QUERY_AUTHORIZATION_HOLD",
        "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
        "RELEASE_FIELD_QUERY_RESULT_MISSING",
        "RELEASE_FIELD_QUERY_NO_PROJECT_TASKS",
        "PENDING",
        "NO_PROJECT_TASKS",
    }:
        return False
    return terminal_state in TERMINAL_MARKER_STATES


def _is_release_evidence_record(record: Mapping[str, Any]) -> bool:
    return bool(
        str(record.get("release_evidence_target_type") or "").strip()
        or str(record.get("p13b_release_evidence_probe_task_id") or "").strip()
        or str(record.get("release_evidence_adapter_task_id") or "").strip()
        or str(record.get("input_source_kind") or "").strip()
        in {"p13b_release_evidence_probe_task", "release_evidence_adapter_plan_task"}
    )


def _is_terminal_original_backtrace_no_delta(record: Mapping[str, Any]) -> bool:
    if str(record.get("closeout_state") or "") != "PARK_D_INSUFFICIENT_OR_BLOCKED":
        return False
    if int(record.get("pending_adapter_job_count") or 0) > 0:
        return False
    lineage = record.get("continuation_lineage") if isinstance(record.get("continuation_lineage"), Mapping) else {}
    if str(lineage.get("final_original_backtrace_continuation_recommended_next_action") or "").strip() != TERMINAL_ORIGINAL_BACKTRACE_NEXT_ACTION:
        return False
    return int(lineage.get("state_after_adapter_job_count") or 0) == 0


def _canonical_scope(scope: str) -> str:
    normalized = str(scope or "").strip().lower().replace("-", "_")
    aliases = {
        "any": "any",
        "*": "*",
        "field_query": "release_evidence_query",
        "release_field_query": "release_evidence_query",
        "release_evidence": "release_evidence_query",
        "release_evidence_adapter": "release_evidence_query",
        "release_evidence_adapter_plan": "release_evidence_query",
        "stage4_release_field_query": "release_evidence_query",
        "p13b": "p13b_follow_up",
        "p13b_followup": "p13b_follow_up",
        "p13b_follow_up": "p13b_follow_up",
        "p13b_continuation": "p13b_follow_up",
        "p13b_company_history": "p13b_follow_up",
        "original_readback": "original_readback",
        "original_notice_readback": "original_readback",
        "original_notice": "original_readback",
    }
    return aliases.get(normalized, normalized or "project")


def _scope_for_action_family(action_family: str) -> str:
    if action_family in {
        "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
        "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
        "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE",
        "RUN_RELEASE_EVIDENCE_FIELD_QUERY",
    }:
        return "release_evidence_query"
    if action_family == "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW":
        return "original_readback"
    if action_family == "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW":
        return "stage4_field_task"
    return "project"


def _next_action(task_scope: str, reason: str, marker: Mapping[str, Any]) -> str:
    terminal_state = str(marker.get("terminal_state") or marker.get("terminal_grade") or "")
    if task_scope == "release_evidence_query":
        if terminal_state.startswith(("B_", "C_")):
            return "project_terminal_release_field_readback_to_stage6_review_projection"
        if terminal_state.startswith("D_") or terminal_state in {"BLOCKED", "NOT_FOUND", "NEEDS_BROWSER"}:
            return "project_terminal_release_field_gap_to_manual_hold_retry_or_browser_worker"
        return "project_release_evidence_query_terminal_projection"
    if task_scope == "p13b_follow_up":
        if terminal_state == "OVERLAP_SIGNAL_REVIEW_REQUIRED":
            return "consume_existing_p13b_closeout_and_route_release_evidence_query"
        if terminal_state == "ORIGINAL_NOTICE_READBACK_REQUIRED":
            return "consume_existing_p13b_closeout_and_route_original_readback"
        if terminal_state == "SOURCE_LIMIT_DEFERRED":
            return "suspend_until_operator_increases_p13b_budget"
        return "project_p13b_terminal_projection_or_manual_hold"
    if task_scope == "original_readback":
        return "manual_review_or_new_source_override_required_before_retry"
    return "project_status_projection_without_duplicate_worker_dispatch"


def _operator_next_action(task_scope: str, reason: str, marker: Mapping[str, Any]) -> str:
    terminal_state = str(marker.get("terminal_state") or marker.get("terminal_grade") or "")
    if task_scope == "release_evidence_query" and terminal_state == "NEEDS_BROWSER":
        return "operator_provides_authorized_browser_session_or_keeps_manual_hold"
    if task_scope == "release_evidence_query" and terminal_state.startswith("D_"):
        return "operator_reviews_source_gap_or_approves_retry_scope_without_clearance_claim"
    if task_scope == "p13b_follow_up" and terminal_state == "SOURCE_LIMIT_DEFERRED":
        return "operator_confirms_higher_budget_before_retry"
    if task_scope == "original_readback":
        return "operator_adds_new_official_original_source_or_confirms_manual_retry_scope"
    return "operator_reviews_terminal_projection_before_reopen"


def _runtime_marker_operator_next_action(task_scope: str, terminal_state: str) -> str:
    state = str(terminal_state or "").strip()
    if task_scope == "original_readback":
        if state == "RELEASE_EVIDENCE_READY":
            return "build_release_evidence_regional_adapter_plan_without_duplicate_original_readback"
        if state == "TARGETED_PERSON_READBACK_REQUIRED":
            return "route_to_targeted_person_readback_without_duplicate_original_readback"
        if state in {"TARGETED_YGP_READBACK_REQUIRED", "ROUTE_SPECIFIC_READBACK_REQUIRED"}:
            return "route_to_route_specific_original_readback_without_duplicate_direct_backtrace"
        if state == "BLOCKED_OR_SOURCE_UNSUPPORTED":
            return "route_to_original_readback_blocker_ledger_or_operator_action"
        return "project_to_manual_hold_without_clearance_claim_or_duplicate_original_readback"
    if state in {"MATCHED", "REVIEW_READY", "RELEASE_FIELD_QUERY_REVIEW_READY", "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY"}:
        return "project_to_review_ready_status_projection_without_duplicate_dispatch"
    if state == "NOT_FOUND":
        return "record_not_found_status_projection_without_clearance_claim_or_duplicate_dispatch"
    if state in {"BLOCKED", "NEEDS_BROWSER", "RELEASE_FIELD_QUERY_AUTHORIZATION_HOLD"}:
        return "route_to_blocker_ledger_or_operator_action_without_duplicate_dispatch"
    if task_scope == "original_readback":
        return "operator_adds_new_official_original_source_or_confirms_manual_retry_scope"
    return "project_to_status_projection_or_manual_hold_without_duplicate_dispatch"


def _retry_policy(reason: str, marker: Mapping[str, Any]) -> str:
    terminal_state = str(marker.get("terminal_state") or marker.get("terminal_grade") or "")
    if terminal_state == "SOURCE_LIMIT_DEFERRED":
        return "retry_only_after_budget_increase_or_new_source"
    if terminal_state in {"NEEDS_BROWSER", "BLOCKED"} or "blocked" in reason.lower():
        return "retry_only_after_blocker_resolved_or_browser_worker_ready"
    if terminal_state.startswith("D_") or "no_delta" in reason:
        return "manual_reopen_requires_new_official_source_or_operator_budget"
    return "do_not_retry_same_worker_without_new_input_or_operator_override"


def _required_input(task_scope: str, reason: str, marker: Mapping[str, Any]) -> list[str]:
    terminal_state = str(marker.get("terminal_state") or marker.get("terminal_grade") or "")
    if terminal_state == "NEEDS_BROWSER":
        return ["authorized_browser_storage_state_or_same_session_browser_worker"]
    if terminal_state == "SOURCE_LIMIT_DEFERRED":
        return ["operator_retry_budget", "continuation_budget_reason"]
    if task_scope == "original_readback":
        return ["new_official_original_notice_source_or_snapshot", "operator_retry_scope"]
    if task_scope == "release_evidence_query" and terminal_state.startswith("D_"):
        return ["new_release_evidence_source_or_region_adapter", "operator_retry_scope"]
    return ["operator_override_reason_or_new_machine_readable_input"]


def _reopen_conditions(task_scope: str, reason: str, marker: Mapping[str, Any]) -> list[str]:
    return [
        "new_machine_readable_input_artifact_available",
        "prior_blocker_resolved_without_clearance_claim",
        "operator_override_records_scope_budget_and_reason",
    ]


def _task_id(record: Mapping[str, Any]) -> str:
    for key in (
        "field_query_task_id",
        "release_evidence_adapter_task_id",
        "p13b_release_evidence_probe_task_id",
        "original_notice_task_id",
        "dispatch_task_id",
        "review_action_plan_id",
        "closeout_id",
        "project_id",
    ):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return _stable_id("TASK", _stable_payload(record))


def _runtime_blocker_next_subqueue_record(
    status_record: Mapping[str, Any],
    blocker: Mapping[str, Any],
    *,
    route: str,
    source_status_table_ref: str,
) -> dict[str, Any]:
    project_id = str(status_record.get("project_id") or blocker.get("project_id") or "")
    project_name = str(status_record.get("project_name") or blocker.get("project_name") or "")
    blocker_id = str(blocker.get("blocker_ledger_id") or "")
    task_id = str(blocker.get("task_id") or "")
    required_input = _dedupe(_list(blocker.get("required_input")))
    operator_next_action = str(blocker.get("operator_next_action") or blocker.get("next_action") or "")
    return {
        "next_subqueue_record_id": _stable_id("RUNTIME-SUBQUEUE", route, project_id, blocker_id, task_id),
        "subqueue_route": route,
        "subqueue_state": _runtime_blocker_subqueue_state(
            route,
            required_input=required_input,
            operator_next_action=operator_next_action,
        ),
        "project_id": project_id,
        "project_name": project_name,
        "assigned_owner": str(status_record.get("assigned_owner") or ""),
        "assigned_owner_role": str(status_record.get("assigned_owner_role") or ""),
        "owner_assignment_source_ref": str(status_record.get("owner_assignment_source_ref") or ""),
        "loop_terminal_state": str(status_record.get("loop_terminal_state") or ""),
        "project_next_recommended_action": str(status_record.get("next_recommended_action") or ""),
        "release_field_query_state": str(status_record.get("release_field_query_state") or ""),
        "blocker_ledger_id": blocker_id,
        "blocker_state": str(blocker.get("blocker_state") or ""),
        "blocker_reason": str(blocker.get("blocker_reason") or ""),
        "runtime_layer": str(blocker.get("runtime_layer") or ""),
        "ledger_scope": str(blocker.get("ledger_scope") or ""),
        "source_ledger_scopes": _dedupe(_list(blocker.get("source_ledger_scopes"))),
        "source_blocker_ledger_ids": _dedupe(_list(blocker.get("source_blocker_ledger_ids"))),
        "task_scope": str(blocker.get("task_scope") or ""),
        "task_type": str(blocker.get("task_type") or ""),
        "task_id": task_id,
        "required_input": required_input,
        "retry_policy": str(blocker.get("retry_policy") or ""),
        "reopen_conditions": _dedupe(_list(blocker.get("reopen_conditions"))),
        "operator_next_action": operator_next_action,
        "next_action": operator_next_action or str(status_record.get("next_recommended_action") or ""),
        "input_artifact_refs": _runtime_blocker_subqueue_input_refs(status_record, blocker),
        "source_status_table_ref": source_status_table_ref,
        "controller_consumable": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _runtime_blocker_controller_queue_record(
    record: Mapping[str, Any],
    *,
    route: str,
    source_next_subqueue_ref: str,
) -> dict[str, Any]:
    source_id = str(record.get("next_subqueue_record_id") or "")
    required_input = _dedupe(_list(record.get("required_input")))
    controller_next_action = _controller_next_action(route)
    return {
        "controller_queue_record_id": _stable_id(
            "RUNTIME-CONTROLLER-QUEUE",
            source_next_subqueue_ref,
            source_id,
            route,
            record.get("project_id"),
        ),
        "source_next_subqueue_record_id": source_id,
        "source_next_subqueue_ref": source_next_subqueue_ref,
        "subqueue_route": route,
        "subqueue_state": str(record.get("subqueue_state") or ""),
        "controller_route_state": _controller_route_state(route),
        "controller_next_action": controller_next_action,
        "dispatch_worker_family": _dispatch_worker_family(route),
        "automated_worker_dispatch_allowed": _automated_worker_dispatch_allowed(route, record),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "assigned_owner": str(record.get("assigned_owner") or ""),
        "assigned_owner_role": str(record.get("assigned_owner_role") or ""),
        "owner_assignment_source_ref": str(record.get("owner_assignment_source_ref") or ""),
        "loop_terminal_state": str(record.get("loop_terminal_state") or ""),
        "project_next_recommended_action": str(record.get("project_next_recommended_action") or ""),
        "release_field_query_state": str(record.get("release_field_query_state") or ""),
        "blocker_ledger_id": str(record.get("blocker_ledger_id") or ""),
        "blocker_state": str(record.get("blocker_state") or ""),
        "blocker_reason": str(record.get("blocker_reason") or ""),
        "runtime_layer": str(record.get("runtime_layer") or ""),
        "ledger_scope": str(record.get("ledger_scope") or ""),
        "source_ledger_scopes": _dedupe(_list(record.get("source_ledger_scopes"))),
        "source_blocker_ledger_ids": _dedupe(_list(record.get("source_blocker_ledger_ids"))),
        "task_scope": str(record.get("task_scope") or ""),
        "task_type": str(record.get("task_type") or ""),
        "task_id": str(record.get("task_id") or ""),
        "required_input": required_input,
        "retry_policy": str(record.get("retry_policy") or ""),
        "reopen_conditions": _dedupe(_list(record.get("reopen_conditions"))),
        "operator_next_action": str(record.get("operator_next_action") or ""),
        "next_action": str(record.get("next_action") or controller_next_action),
        "input_artifact_refs": _dedupe(_list(record.get("input_artifact_refs"))),
        "controller_consumable": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _controller_route_state(route: str) -> str:
    states = {
        "browser_worker": "WAIT_FOR_BROWSER_WORKER_OR_AUTHORIZED_SESSION_INPUT",
        "fallback_source": "WAIT_FOR_FALLBACK_SOURCE_ADAPTER_PLAN",
        "retry": "WAIT_FOR_RETRY_REOPEN_INPUT_OR_BUDGET",
        "manual_hold": "MANUAL_HOLD_ROUTE_RECORDED",
        "suspend_dead_letter": "SUSPEND_DEAD_LETTER_ROUTE_RECORDED",
        "operator_action": "OPERATOR_ACTION_ROUTE_RECORDED",
    }
    return states.get(route, "UNKNOWN_SUBQUEUE_ROUTE_REVIEW_REQUIRED")


def _controller_next_action(route: str) -> str:
    actions = {
        "browser_worker": "route_to_browser_worker_when_authorized_session_or_same_session_input_available",
        "fallback_source": "route_to_fallback_source_planning_before_retry",
        "retry": "retry_only_after_reopen_conditions_and_required_inputs_are_met",
        "manual_hold": "keep_manual_hold_until_operator_reviews",
        "suspend_dead_letter": "keep_suspended_or_dead_letter_until_reopen_condition",
        "operator_action": "show_operator_action_in_projection",
    }
    return actions.get(route, "operator_reviews_unknown_subqueue_route")


def _dispatch_worker_family(route: str) -> str:
    families = {
        "browser_worker": "browser_worker",
        "fallback_source": "source_adapter",
        "retry": "retry_policy",
        "manual_hold": "manual_hold",
        "suspend_dead_letter": "suspend_dead_letter",
        "operator_action": "operator_action",
    }
    return families.get(route, "operator_review")


def _automated_worker_dispatch_allowed(route: str, record: Mapping[str, Any]) -> bool:
    if route in {"manual_hold", "suspend_dead_letter", "operator_action"}:
        return False
    if _list(record.get("required_input")):
        return False
    state = str(record.get("subqueue_state") or "")
    if "WAITING" in state or "REQUIRED" in state or "PENDING" in state:
        return False
    return route in {"browser_worker", "fallback_source", "retry"}


def _runtime_blocker_controller_dispatch_record(record: Mapping[str, Any], *, output_root: str) -> dict[str, Any]:
    route = str(record.get("subqueue_route") or "")
    worker_family = str(record.get("dispatch_worker_family") or _dispatch_worker_family(route))
    spec = _controller_dispatch_spec(route)
    blocking_reasons = _controller_dispatch_blocking_reasons(record, spec=spec)
    readiness_state = _controller_dispatch_readiness_state(record, spec=spec, blocking_reasons=blocking_reasons)
    output_dir = _controller_dispatch_output_root(record, route=route, output_root=output_root)
    fallback_artifact = _fallback_source_plan_expected_artifact(route)
    expected_artifact = str(spec.get("expected_output_artifact") or fallback_artifact)
    argv = (
        _controller_dispatch_argv(record, spec=spec, output_dir=output_dir)
        if readiness_state == "READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH"
        else []
    )
    return {
        "controller_dispatch_task_id": _stable_id(
            "RUNTIME-CONTROLLER-DISPATCH",
            record.get("controller_queue_record_id"),
            route,
            readiness_state,
        ),
        "source_controller_queue_record_id": str(record.get("controller_queue_record_id") or ""),
        "source_next_subqueue_record_id": str(record.get("source_next_subqueue_record_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "assigned_owner": str(record.get("assigned_owner") or ""),
        "assigned_owner_role": str(record.get("assigned_owner_role") or ""),
        "dispatch_route": route,
        "dispatch_worker_family": worker_family,
        "dispatch_readiness_state": readiness_state,
        "dispatch_blocking_reasons": blocking_reasons,
        "formal_entrypoint_id": _controller_dispatch_formal_entrypoint_id(route),
        "recommended_script": str(spec.get("script") or _fallback_source_plan_recommended_script(route)),
        "recommended_command_argv": argv,
        "recommended_command": _powershell_command(argv),
        "expected_output_artifact": expected_artifact,
        "expected_output_artifact_path": (
            str(Path(output_dir) / expected_artifact)
            if output_dir and expected_artifact
            else ""
        ),
        "plan_artifact_kind": "runtime_blocker_fallback_source_plan_v1" if route == "fallback_source" else "",
        "output_root": output_dir,
        "input_artifact_refs": _dedupe(_list(record.get("input_artifact_refs"))),
        "required_input": _dedupe(_list(record.get("required_input"))),
        "retry_policy": str(record.get("retry_policy") or ""),
        "reopen_conditions": _dedupe(_list(record.get("reopen_conditions"))),
        "operator_next_action": str(record.get("operator_next_action") or ""),
        "controller_next_action": str(record.get("controller_next_action") or ""),
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "live_execution_enabled": False,
        "requires_operator_action_before_live": True,
        "requires_operator_approval_before_execution": _controller_dispatch_requires_operator_approval(
            route=route,
            argv=argv,
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _controller_dispatch_spec(route: str) -> dict[str, str]:
    if route == "browser_worker":
        return {
            "script": "scripts/build-gdcic-browser-authorized-readback-v1.ps1",
            "expected_output_artifact": "gdcic-browser-authorized-readback-v1.json",
            "required_artifact_suffix": "release-evidence-adapter-plan-v1.json",
            "artifact_arg": "ReleaseEvidenceAdapterPlanJson",
        }
    return {}


def _controller_dispatch_formal_entrypoint_id(route: str) -> str:
    if route == "browser_worker":
        return "gdcic_browser_authorized_readback_builder"
    if route == "fallback_source":
        return "runtime_blocker_fallback_source_plan_builder"
    return ""


def _fallback_source_plan_expected_artifact(route: str) -> str:
    return "runtime-blocker-fallback-source-plan-v1.json" if route == "fallback_source" else ""


def _fallback_source_plan_recommended_script(route: str) -> str:
    return "storage.runtime_blocker_fallback_source_plan" if route == "fallback_source" else ""


def _controller_dispatch_requires_operator_approval(*, route: str, argv: list[str]) -> bool:
    if route == "browser_worker":
        return True
    return any(
        str(token or "").lower() in {
            "-enablelivepublicquery",
            "-enablelivebrowserexecution",
        }
        for token in argv
    )


def _controller_dispatch_blocking_reasons(record: Mapping[str, Any], *, spec: Mapping[str, str]) -> list[str]:
    route = str(record.get("subqueue_route") or "")
    if route in {"manual_hold", "suspend_dead_letter", "operator_action"}:
        return []
    if _list(record.get("required_input")):
        return ["required_input_missing_or_operator_action_pending"]
    if not spec:
        return ["no_allowlisted_worker_for_controller_route"]
    suffix = str(spec.get("required_artifact_suffix") or "")
    if suffix and not _first_input_artifact(record, suffix):
        return [f"{suffix}_input_ref_missing"]
    return []


def _controller_dispatch_readiness_state(
    record: Mapping[str, Any],
    *,
    spec: Mapping[str, str],
    blocking_reasons: list[str],
) -> str:
    route = str(record.get("subqueue_route") or "")
    if route == "manual_hold":
        return "MANUAL_HOLD_RECORDED_NO_WORKER_DISPATCH"
    if route == "suspend_dead_letter":
        return "SUSPEND_DEAD_LETTER_RECORDED_NO_WORKER_DISPATCH"
    if route == "operator_action":
        return "OPERATOR_ACTION_RECORDED_NO_WORKER_DISPATCH"
    if blocking_reasons:
        if route == "fallback_source":
            return "FALLBACK_SOURCE_PLAN_REQUIRED"
        if route == "retry":
            return "RETRY_REOPEN_INPUT_REQUIRED"
        return "BLOCKED_REQUIRED_INPUT_OR_WORKER_SPEC_MISSING"
    if not bool(record.get("automated_worker_dispatch_allowed")):
        return "ROUTE_RECORDED_NO_AUTOMATED_WORKER_DISPATCH"
    if spec:
        return "READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH"
    return "ROUTE_RECORDED_NO_ALLOWLISTED_WORKER"


def _controller_dispatch_argv(
    record: Mapping[str, Any],
    *,
    spec: Mapping[str, str],
    output_dir: str,
) -> list[str]:
    script = str(spec.get("script") or "")
    artifact_arg = str(spec.get("artifact_arg") or "")
    artifact = _first_input_artifact(record, str(spec.get("required_artifact_suffix") or ""))
    if not script or not artifact_arg or not artifact or not output_dir:
        return []
    return [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script,
        f"-{artifact_arg}",
        artifact,
        "-OutputRoot",
        output_dir,
    ]


def _controller_dispatch_output_root(record: Mapping[str, Any], *, route: str, output_root: str) -> str:
    if not output_root:
        return ""
    project_id = str(record.get("project_id") or "project").strip() or "project"
    safe_project_id = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in project_id)
    return str(Path(output_root) / route / safe_project_id)


def _first_input_artifact(record: Mapping[str, Any], suffix: str) -> str:
    expected = str(suffix or "").replace("\\", "/")
    for value in _list(record.get("input_artifact_refs")):
        text = str(value or "").strip()
        if text and (not expected or text.replace("\\", "/").endswith(expected)):
            return text
    return ""


def _powershell_command(argv: Iterable[Any]) -> str:
    return " ".join(_ps_quote_arg(str(part)) for part in argv)


def _ps_quote_arg(value: str) -> str:
    if not value:
        return "''"
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-,")
    if all(char in safe_chars for char in value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _runtime_blocker_subqueue_state(
    route: str,
    *,
    required_input: Iterable[Any],
    operator_next_action: str,
) -> str:
    inputs = [str(item or "").strip() for item in required_input if str(item or "").strip()]
    if route == "browser_worker":
        return "BROWSER_WORKER_WAITING_FOR_AUTHORIZED_SESSION" if inputs else "BROWSER_WORKER_READY"
    if route == "fallback_source":
        return "FALLBACK_SOURCE_REQUIRED"
    if route == "retry":
        return "RETRY_WAITING_FOR_REOPEN_INPUT" if inputs else "RETRY_READY_FOR_CONTROLLER"
    if route == "suspend_dead_letter":
        return "SUSPEND_OR_DEAD_LETTER_PENDING_REOPEN_INPUT"
    if route == "manual_hold":
        return "MANUAL_HOLD_PENDING_OPERATOR_REVIEW"
    if route == "operator_action" or operator_next_action:
        return "OPERATOR_ACTION_REQUIRED"
    if inputs:
        return "WAITING_FOR_REQUIRED_INPUT"
    return "READY_FOR_CONTROLLER_ROUTE"


def _runtime_blocker_subqueue_input_refs(
    status_record: Mapping[str, Any],
    blocker: Mapping[str, Any],
) -> list[str]:
    marker = blocker.get("terminal_marker") if isinstance(blocker.get("terminal_marker"), Mapping) else {}
    status_marker = (
        status_record.get("closeout_precedence_terminal_marker")
        if isinstance(status_record.get("closeout_precedence_terminal_marker"), Mapping)
        else {}
    )
    marker_source_refs = [
        item.get("artifact_ref")
        for item in _list(status_record.get("closeout_precedence_marker_source_refs"))
        if isinstance(item, Mapping)
    ]
    return _dedupe(
        [
            status_record.get("release_field_query_result_json"),
            blocker.get("artifact_ref"),
            marker.get("artifact_ref") if isinstance(marker, Mapping) else "",
            marker.get("source_json") if isinstance(marker, Mapping) else "",
            status_marker.get("artifact_ref") if isinstance(status_marker, Mapping) else "",
            status_marker.get("source_json") if isinstance(status_marker, Mapping) else "",
            *marker_source_refs,
        ]
    )


def _ordered_subqueues(routes: Iterable[Any]) -> list[str]:
    deduped = _dedupe(routes)
    order = {route: index for index, route in enumerate(RUNTIME_BLOCKER_SUBQUEUE_ROUTE_ORDER)}
    return sorted(deduped, key=lambda route: (order.get(route, len(order)), route))


def _stable_payload(record: Mapping[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _dedupe(values: Iterable[Any]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    iterable = (
        values
        if not isinstance(values, (str, bytes, Mapping))
        else _list(values)
    )
    for value in iterable:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def counts(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        out[text] = out.get(text, 0) + 1
    return dict(sorted(out.items()))


__all__ = [
    "TERMINAL_RELEASE_EVIDENCE_ABCD_GRADES",
    "RUNTIME_BLOCKER_SUBQUEUE_ROUTE_ORDER",
    "blocker_ledger_record",
    "build_runtime_blocker_controller_dispatch_table",
    "build_runtime_blocker_next_subqueue_table",
    "build_runtime_blocker_subqueue_controller_table",
    "closeout_precedence_decision",
    "closeout_precedence_for_record",
    "closeout_precedence_summary",
    "counts",
    "p13b_project_terminal_marker",
    "release_field_query_terminal_marker",
    "runtime_blocker_record_subqueues",
    "runtime_blocker_subqueue_routes",
]
