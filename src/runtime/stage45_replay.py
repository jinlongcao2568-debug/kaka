from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from stage4_verification.blocker_taxonomy import classify_stage4_probe_result
from stage4_verification.public_evidence_readback import normalize_public_evidence_readbacks
from stage5_rules_evidence.rule_bundle_executor import RuleBundleExecutor
from storage.runtime_closeout_precedence import build_runtime_blocker_next_subqueue_table


REPLAY_ID = "stage45-runtime-sample-replay-v1"


def build_stage45_runtime_sample_replay(
    samples: Mapping[str, Any] | str | Path,
    *,
    created_at: str,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    payload = _load_samples(samples)
    stage4_probes = [dict(item) for item in _list(payload.get("stage4_probe_results")) if isinstance(item, Mapping)]
    readbacks = normalize_public_evidence_readbacks(payload.get("stage4_public_evidence_readbacks"))
    rule_codes = _str_list(payload.get("stage5_rule_codes")) or ["CREDIT-001", "REL-001", "ENG-001", "ENG-002", "PERF-001"]
    bundle_id = str(payload.get("bundle_id") or "stage45-runtime-sample-replay")

    stage4_records: list[dict[str, Any]] = []
    blocker_records: list[dict[str, Any]] = []
    operator_actions: list[dict[str, Any]] = []
    for index, probe in enumerate(stage4_probes, start=1):
        outcome = classify_stage4_probe_result(probe)
        record = _stage4_record(index=index, probe=probe, outcome=outcome, created_at=created_at)
        stage4_records.append(record)
        blocker = _blocker_ledger_record(record)
        if blocker:
            blocker_records.append(blocker)
            operator_actions.append(_operator_action_record(record, blocker, created_at=created_at))

    next_subqueue_table = build_runtime_blocker_next_subqueue_table(
        [_status_record_from_stage4(record, blocker_records) for record in stage4_records],
        source_status_table_ref=str(payload.get("source_ref") or REPLAY_ID),
    )
    stage5_execution = RuleBundleExecutor(rule_codes=rule_codes).execute(
        bundle_id=bundle_id,
        readbacks=readbacks,
    )
    stage5_calibration_samples = _stage5_calibration_sample_records(
        stage5_execution=stage5_execution,
        bundle_id=bundle_id,
        created_at=created_at,
    )
    summary = _summary(
        stage4_records=stage4_records,
        blocker_records=blocker_records,
        operator_actions=operator_actions,
        next_subqueue_table=next_subqueue_table,
        stage5_execution=stage5_execution,
        stage5_calibration_samples=stage5_calibration_samples,
        readback_count=len(readbacks),
    )
    manifest = {
        "manifest_kind": "stage45_runtime_sample_replay_v1",
        "replay_id": REPLAY_ID,
        "created_at": created_at,
        "stage4_probe_records": stage4_records,
        "stage4_runtime_blocker_ledger_records": blocker_records,
        "stage4_operator_action_records": operator_actions,
        "runtime_blocker_next_subqueue_table": next_subqueue_table,
        "stage5_rule_bundle_execution": stage5_execution,
        "stage5_calibration_sample_records": stage5_calibration_samples,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "runtime_replay_mode": "STAGE45_RUNTIME_SAMPLE_REPLAY",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    if output_root is not None:
        out_dir = Path(output_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "stage45-runtime-sample-replay-v1.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return result


def _stage4_record(
    *,
    index: int,
    probe: Mapping[str, Any],
    outcome: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    project_id = str(probe.get("project_id") or f"STAGE45-SAMPLE-{index}")
    return {
        "stage4_replay_record_id": _stable_id("STAGE45-REPLAY", project_id, index, outcome.get("verification_state")),
        "project_id": project_id,
        "project_name": str(probe.get("project_name") or ""),
        "probe_index": index,
        "probe_status": str(probe.get("probe_status") or probe.get("status") or ""),
        "verification_state": str(outcome.get("verification_state") or ""),
        "run_state": str(outcome.get("run_state") or ""),
        "blocker_ids": _str_list(outcome.get("blocker_ids")),
        "blocking_reasons": _str_list(outcome.get("blocking_reasons")),
        "authorization_readiness_state": str(outcome.get("authorization_readiness_state") or ""),
        "operator_next_action": str(outcome.get("operator_next_action") or ""),
        "evidence_refs": _str_list(outcome.get("evidence_refs")),
        "source_url": str(outcome.get("source_url") or ""),
        "source_snapshot_id": str(outcome.get("source_snapshot_id") or ""),
        "snapshot_hash": str(outcome.get("snapshot_hash") or ""),
        "query_miss_is_not_clearance": True,
        "clearance_allowed": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "created_at": created_at,
    }


def _blocker_ledger_record(record: Mapping[str, Any]) -> dict[str, Any]:
    blocker_ids = _str_list(record.get("blocker_ids"))
    if not blocker_ids:
        return {}
    blocker_state = _blocker_state(blocker_ids)
    return {
        "blocker_ledger_id": _stable_id("STAGE45-BLOCKER", record.get("stage4_replay_record_id"), blocker_state),
        "ledger_scope": "stage4_stage5_runtime_sample_replay",
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "task_id": str(record.get("stage4_replay_record_id") or ""),
        "task_scope": "stage4_verification",
        "task_type": "stage4_probe_result_replay",
        "blocker_state": blocker_state,
        "blocker_reason": _first_text(record.get("blocking_reasons")) or _first_text(blocker_ids),
        "runtime_layer": "controller decision:stage45_runtime_sample_replay",
        "required_input": _required_input(blocker_ids),
        "retry_policy": _retry_policy(blocker_ids),
        "reopen_conditions": [
            "new_public_readback_or_snapshot_available",
            "operator_override_records_scope_budget_and_reason",
        ],
        "operator_next_action": str(record.get("operator_next_action") or ""),
        "next_action": str(record.get("operator_next_action") or ""),
        "terminal_marker": {
            "stage4_replay_record_id": str(record.get("stage4_replay_record_id") or ""),
            "verification_state": str(record.get("verification_state") or ""),
            "query_miss_is_not_clearance": True,
        },
        "subqueue_routes": _subqueue_routes(blocker_ids),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _operator_action_record(record: Mapping[str, Any], blocker: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    return {
        "operator_action_id": _stable_id("STAGE45-OPERATOR-ACTION", blocker.get("blocker_ledger_id")),
        "project_id": str(record.get("project_id") or ""),
        "stage_id": "stage4_verification",
        "action_state": "OPERATOR_ACTION_REQUIRED",
        "operator_next_action": str(blocker.get("operator_next_action") or ""),
        "blocker_ledger_id": str(blocker.get("blocker_ledger_id") or ""),
        "required_input": _str_list(blocker.get("required_input")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "created_at": created_at,
    }


def _status_record_from_stage4(record: Mapping[str, Any], blockers: list[Mapping[str, Any]]) -> dict[str, Any]:
    project_id = str(record.get("project_id") or "")
    rows = [dict(blocker) for blocker in blockers if str(blocker.get("project_id") or "") == project_id]
    return {
        "project_id": project_id,
        "project_name": str(record.get("project_name") or ""),
        "assigned_owner": "卡卡罗特",
        "assigned_owner_role": "single_operator",
        "loop_terminal_state": str(record.get("run_state") or ""),
        "next_recommended_action": str(record.get("operator_next_action") or ""),
        "runtime_blocker_ledger_records": rows,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _summary(
    *,
    stage4_records: list[Mapping[str, Any]],
    blocker_records: list[Mapping[str, Any]],
    operator_actions: list[Mapping[str, Any]],
    next_subqueue_table: Mapping[str, Any],
    stage5_execution: Mapping[str, Any],
    stage5_calibration_samples: list[Mapping[str, Any]],
    readback_count: int,
) -> dict[str, Any]:
    return {
        "stage4_probe_replay_count": len(stage4_records),
        "stage4_verification_state_counts": _counts(record.get("verification_state") for record in stage4_records),
        "stage4_run_state_counts": _counts(record.get("run_state") for record in stage4_records),
        "stage4_blocker_ledger_count": len(blocker_records),
        "stage4_blocker_state_counts": _counts(record.get("blocker_state") for record in blocker_records),
        "operator_action_count": len(operator_actions),
        "authorization_readiness_state_counts": _counts(
            record.get("authorization_readiness_state") for record in stage4_records
        ),
        "runtime_blocker_next_subqueue_record_count": int(
            (next_subqueue_table.get("summary") or {}).get("next_subqueue_record_count") or 0
        ),
        "runtime_blocker_subqueue_route_counts": dict(
            (next_subqueue_table.get("summary") or {}).get("subqueue_route_counts") or {}
        ),
        "stage5_public_readback_count": readback_count,
        "stage5_executed_rule_codes": list(stage5_execution.get("executed_rule_codes") or []),
        "stage5_skipped_rule_codes": list(stage5_execution.get("skipped_rule_codes") or []),
        "stage5_missing_readback_count": int((stage5_execution.get("summary") or {}).get("missing_readback_count") or 0),
        "stage5_calibration_sample_count": len(stage5_calibration_samples),
        "stage5_calibration_truth_label_required_count": sum(
            1 for record in stage5_calibration_samples if bool(record.get("calibration_truth_label_required"))
        ),
        "stage5_abcd_calibration_counts": _counts(
            record.get("stage5_abcd_calibration_bucket") for record in stage5_calibration_samples
        ),
        "stage5_calibration_evidence_strength_counts": _counts(
            record.get("stage5_calibration_evidence_strength") for record in stage5_calibration_samples
        ),
        "stage5_calibration_review_family_counts": _counts(
            record.get("stage5_calibration_review_family") for record in stage5_calibration_samples
        ),
        "stage5_calibration_suggested_action_counts": _counts(
            record.get("suggested_calibration_action") for record in stage5_calibration_samples
        ),
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _stage5_calibration_sample_records(
    *,
    stage5_execution: Mapping[str, Any],
    bundle_id: str,
    created_at: str,
) -> list[dict[str, Any]]:
    calibration = (
        stage5_execution.get("stage5_abcd_calibration")
        if isinstance(stage5_execution.get("stage5_abcd_calibration"), Mapping)
        else {}
    )
    rows = [
        dict(row)
        for row in _list(calibration.get("calibration_rows"))
        if isinstance(row, Mapping)
    ]
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        rule_code = str(row.get("rule_code") or "")
        bucket = str(row.get("calibration_bucket") or row.get("calibration_review_bucket") or "")
        records.append(
            {
                "stage5_calibration_sample_id": _stable_id("STAGE45-STAGE5-CAL", bundle_id, rule_code, index),
                "bundle_id": str(bundle_id),
                "rule_code": rule_code,
                "stage5_rule_gate_status": str(row.get("gate_status") or ""),
                "stage5_evidence_gate_status": str(row.get("gate_status") or ""),
                "stage5_calibration_review_bucket": bucket,
                "stage5_abcd_calibration_bucket": bucket,
                "stage5_calibration_evidence_strength": str(row.get("calibration_evidence_strength") or ""),
                "stage5_calibration_review_family": str(row.get("calibration_review_family") or ""),
                "stage5_calibration_review_reasons": _str_list(row.get("calibration_reasons")),
                "calibration_truth_label_required": bool(row.get("truth_label_required")),
                "suggested_calibration_action": str(row.get("suggested_calibration_action") or ""),
                "readback_ids": _str_list(row.get("readback_ids")),
                "query_miss_is_not_clearance": bool(row.get("query_miss_is_not_clearance")),
                "no_clearance_without_public_readback": bool(row.get("no_clearance_without_public_readback")),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "created_at": created_at,
            }
        )
    return records


def _blocker_state(blocker_ids: list[str]) -> str:
    if "login_or_sso_required" in blocker_ids:
        return "STAGE4_LOGIN_OR_SSO_REQUIRED_OPERATOR_ACTION"
    if "needs_browser" in blocker_ids:
        return "STAGE4_NEEDS_BROWSER_WORKER_OR_OPERATOR_CAPTURE"
    if "source_not_found_not_clearance" in blocker_ids:
        return "STAGE4_NOT_FOUND_REVIEW_REQUIRED_NOT_CLEARANCE"
    if "source_blocked" in blocker_ids:
        return "STAGE4_SOURCE_BLOCKED_RETRY_OR_SUSPEND"
    return "STAGE4_REVIEW_REQUIRED"


def _subqueue_routes(blocker_ids: list[str]) -> list[str]:
    if "login_or_sso_required" in blocker_ids or "needs_browser" in blocker_ids:
        return ["browser_worker", "operator_action"]
    if "source_not_found_not_clearance" in blocker_ids:
        return ["fallback_source", "manual_hold", "operator_action"]
    if "source_blocked" in blocker_ids:
        return ["retry", "suspend_dead_letter", "operator_action"]
    return ["manual_hold", "operator_action"]


def _required_input(blocker_ids: list[str]) -> list[str]:
    if "login_or_sso_required" in blocker_ids:
        return ["authorized_browser_storage_state_or_user_data_dir"]
    if "needs_browser" in blocker_ids:
        return ["browser_worker_capture_or_operator_snapshot"]
    if "source_not_found_not_clearance" in blocker_ids:
        return ["fallback_source_or_more_precise_query_terms"]
    if "source_blocked" in blocker_ids:
        return ["retry_budget_or_source_unblock_signal"]
    return ["operator_review_result"]


def _retry_policy(blocker_ids: list[str]) -> str:
    if "source_not_found_not_clearance" in blocker_ids:
        return "retry_only_with_fallback_source_or_more_precise_identifiers"
    if "source_blocked" in blocker_ids:
        return "retry_only_after_blocker_resolved_or_suspend_dead_letter"
    if "login_or_sso_required" in blocker_ids or "needs_browser" in blocker_ids:
        return "retry_only_after_authorized_browser_or_capture_available"
    return "manual_reopen_requires_operator_scope"


def _load_samples(samples: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(samples, Mapping):
        return dict(samples)
    path = Path(samples)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _str_list(value: Any) -> list[str]:
    return [str(item) for item in _list(value) if str(item or "").strip()]


def _first_text(value: Any) -> str:
    for item in _list(value):
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["REPLAY_ID", "build_stage45_runtime_sample_replay"]
