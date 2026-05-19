from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_KIND = "stage6_review_action_dispatch_closeout_v1_manifest"
STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_VERSION = 1
STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_ADAPTER_ID = "stage6-review-action-dispatch-closeout-v1"

DEFAULT_DISPATCH_READBACK_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-readback-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-action-dispatch-closeout-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")


def build_stage6_review_action_dispatch_closeout(
    *,
    dispatch_readback_json: str | Path | None = None,
    dispatch_readback_root: str | Path = DEFAULT_DISPATCH_READBACK_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    readback_path = (
        Path(dispatch_readback_json)
        if dispatch_readback_json
        else Path(dispatch_readback_root) / "stage6-review-action-dispatch-readback-v1.json"
    )
    readback_payload = _load_json(readback_path, blocking_reasons, "stage6_review_action_dispatch_readback_missing_or_invalid")
    readback_manifest = _source_manifest(readback_payload)
    readback_records = [
        dict(record)
        for record in _list(
            (readback_manifest.get("dispatch_readback_table") or {}).get("records")
            if isinstance(readback_manifest.get("dispatch_readback_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    if readback_payload and not readback_records:
        blocking_reasons.append("stage6_review_dispatch_readback_records_missing")

    closeout_records = [_closeout_record(record, created_at=created) for record in readback_records]
    summary = _summary(closeout_records=closeout_records, blocking_reasons=blocking_reasons)
    manifest = {
        "manifest_version": STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_VERSION,
        "manifest_kind": STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_KIND,
        "adapter_id": STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewActionDispatchCloseoutV1",
        "manifest_id": f"STAGE6-REVIEW-ACTION-DISPATCH-CLOSEOUT-{_fingerprint({'summary': summary, 'records': closeout_records})[:16]}",
        "created_at": created,
        "source_dispatch_readback_json": str(readback_path),
        "source_dispatch_readback_manifest_id": str(readback_manifest.get("manifest_id") or ""),
        "dispatch_closeout_table": {"records": closeout_records, "summary": summary},
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "stage7_to_stage9_live_execution_enabled": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage6_review_action_dispatch_closeout_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, closeout_records)
    return result


def _closeout_record(record: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    readback_state = str(record.get("dispatch_readback_state") or "")
    closeout_state = _closeout_state(readback_state)
    return {
        "dispatch_closeout_id": _stable_id("S6-DISPATCH-CLOSEOUT", record.get("dispatch_readback_id"), closeout_state),
        "dispatch_readback_id": str(record.get("dispatch_readback_id") or ""),
        "dispatch_task_id": str(record.get("dispatch_task_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "dispatch_task_type": str(record.get("dispatch_task_type") or ""),
        "dispatch_readback_state": readback_state,
        "dispatch_closeout_state": closeout_state,
        "result_json_path": str(record.get("result_json_path") or ""),
        "result_json_exists": bool(record.get("result_json_exists")),
        "result_manifest_id": str(record.get("result_manifest_id") or ""),
        "result_blocking_reasons": _list(record.get("result_blocking_reasons")),
        "next_required_input_refs": _list(record.get("next_required_input_refs")),
        "next_recommended_action": _closeout_next_action(closeout_state),
        "ready_to_feed_back_to_evidence_state": closeout_state == "READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE",
        "kept_in_internal_review_only": closeout_state != "READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE",
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "created_at": created_at,
    }


def _closeout_state(readback_state: str) -> str:
    if readback_state == "EXECUTION_OUTPUT_READY":
        return "READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE"
    if readback_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return "WAITING_FOR_CONTROLLED_EXECUTION"
    if readback_state == "SKIPPED_BY_OPERATOR":
        return "PARKED_OPERATOR_SKIPPED_THIS_ROUND"
    if readback_state in {"BLOCKED_BY_OPERATOR_DECISION", "BLOCKED_DISPATCH_NOT_READY"}:
        return "BLOCKED_OPERATOR_OR_DISPATCH_INPUT_REVIEW"
    if readback_state == "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED":
        return "BLOCKED_RESULT_REVIEW_REQUIRED"
    return "MANUAL_REVIEW_REQUIRED"


def _closeout_next_action(closeout_state: str) -> str:
    if closeout_state == "READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE":
        return "feed_result_artifact_into_evidence_orchestration_state_and_rebuild_stage6"
    if closeout_state == "WAITING_FOR_CONTROLLED_EXECUTION":
        return "run_controlled_dispatch_task_or_record_operator_skip"
    if closeout_state == "PARKED_OPERATOR_SKIPPED_THIS_ROUND":
        return "keep_in_internal_review_until_operator_reopens_or_closes_task"
    if closeout_state == "BLOCKED_RESULT_REVIEW_REQUIRED":
        return "inspect_result_blocking_reasons_then_retry_or_park_without_clearance_claim"
    return "resolve_dispatch_blocker_before_retry"


def _summary(
    *,
    closeout_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "stage6_review_action_dispatch_closeout_state": (
            "STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_READY"
            if not blocking_reasons
            else "STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_INPUT_BLOCKED"
        ),
        "dispatch_closeout_count": len(closeout_records),
        "dispatch_closeout_state_counts": _counts(record.get("dispatch_closeout_state") for record in closeout_records),
        "ready_to_feed_back_count": sum(
            1 for record in closeout_records if record.get("ready_to_feed_back_to_evidence_state")
        ),
        "waiting_for_controlled_execution_count": sum(
            1
            for record in closeout_records
            if record.get("dispatch_closeout_state") == "WAITING_FOR_CONTROLLED_EXECUTION"
        ),
        "blocked_or_review_count": sum(
            1
            for record in closeout_records
            if str(record.get("dispatch_closeout_state") or "").startswith("BLOCKED")
            or record.get("dispatch_closeout_state") == "MANUAL_REVIEW_REQUIRED"
        ),
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "blocking_reasons": list(blocking_reasons),
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    closeout_records: list[Mapping[str, Any]],
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
    result["manifest"]["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result["manifest"].items() if key != "manifest_sha256"}
    )
    _write_json(out_dir / "stage6-review-dispatch-closeout-table.json", {"summary": result["summary"], "records": closeout_records})
    _write_json(out_dir / "stage6-review-action-dispatch-closeout-v1.json", result)


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
    parser = argparse.ArgumentParser(description="Close out Stage6 review action dispatch readback records.")
    parser.add_argument("--dispatch-readback-json", default="")
    parser.add_argument("--dispatch-readback-root", default=str(DEFAULT_DISPATCH_READBACK_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_stage6_review_action_dispatch_closeout(
        dispatch_readback_json=args.dispatch_readback_json or None,
        dispatch_readback_root=args.dispatch_readback_root,
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
    "STAGE6_REVIEW_ACTION_DISPATCH_CLOSEOUT_KIND",
    "build_stage6_review_action_dispatch_closeout",
]
