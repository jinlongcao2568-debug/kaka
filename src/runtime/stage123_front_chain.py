from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage1_tasking.market_scan import Stage1MarketScanEngine
from stage1_tasking.source_blueprint import Stage1SourceBlueprintOrchestrator


STAGE123_FRONT_CHAIN_KIND = "stage123_runtime_front_chain_v1_manifest"
STAGE123_FRONT_CHAIN_VERSION = 1
DEFAULT_STAGE123_FRONT_CHAIN_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage123-runtime-front-chain-v1")


def build_stage123_runtime_front_chain(
    payload: Mapping[str, Any],
    *,
    created_at: str | None = None,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    payload_map = dict(payload)
    out_dir = Path(output_root or payload_map.get("stage123_front_chain_output_root") or DEFAULT_STAGE123_FRONT_CHAIN_OUTPUT_ROOT)
    market_scan = _market_scan_result(payload_map, created_at=created)
    source_blueprint = _source_blueprint_result(payload_map, market_scan=market_scan, created_at=created)
    stage2_records = _stage2_capture_records(payload_map, source_blueprint=source_blueprint)
    stage3_records = _stage3_parse_records(payload_map, stage2_records=stage2_records)
    stage_records = [
        _stage1_record(market_scan, source_blueprint),
        _stage2_record(stage2_records),
        _stage3_record(stage3_records),
    ]
    summary = _summary(stage_records, market_scan, source_blueprint, stage2_records, stage3_records)
    manifest = {
        "manifest_kind": STAGE123_FRONT_CHAIN_KIND,
        "manifest_version": STAGE123_FRONT_CHAIN_VERSION,
        "created_at": created,
        "stage_records": stage_records,
        "stage1_market_scan": market_scan,
        "stage1_source_blueprint": source_blueprint,
        "stage2_capture_records": stage2_records,
        "stage3_parse_records": stage3_records,
        "summary": summary,
        "safety": {
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "download_execution_enabled": False,
            "parse_execution_from_untrusted_live_source_enabled": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    result = {
        "stage123_runtime_front_chain_mode": "BUILT",
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stage123-runtime-front-chain-v1.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def has_stage123_front_chain_input(payload: Mapping[str, Any]) -> bool:
    return any(
        key in payload and payload.get(key) not in (None, "", [], {})
        for key in (
            "stage123_front_chain_payload",
            "stage1_market_scan_json",
            "stage1_market_scan_payload",
            "stage1_market_scan_result",
            "stage1_source_blueprint_json",
            "stage1_source_blueprint_payload",
            "stage2_capture_json",
            "stage2_capture_records",
            "stage2_capture_readbacks",
            "stage3_parse_json",
            "stage3_parse_records",
            "stage3_parse_readbacks",
        )
    )


def _market_scan_result(payload: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    explicit = payload.get("stage1_market_scan_result")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    from_json = _json_mapping(payload.get("stage1_market_scan_json"))
    if from_json:
        return _select_mapping(
            from_json,
            (
                "stage1_market_scan",
                "market_scan",
                "result",
                "summary",
            ),
        )
    nested = payload.get("stage123_front_chain_payload")
    nested_payload = nested if isinstance(nested, Mapping) else {}
    market_payload = payload.get("stage1_market_scan_payload")
    if not isinstance(market_payload, Mapping):
        market_payload = nested_payload.get("stage1_market_scan_payload")
    if not isinstance(market_payload, Mapping):
        return {}
    run_payload = dict(market_payload)
    run_payload.setdefault("now", created_at)
    return Stage1MarketScanEngine().run(run_payload, persist=False)


def _source_blueprint_result(
    payload: Mapping[str, Any],
    *,
    market_scan: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    explicit = payload.get("stage1_source_blueprint_result")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    from_json = _json_mapping(payload.get("stage1_source_blueprint_json"))
    if from_json:
        return _select_mapping(
            from_json,
            (
                "stage1_source_blueprint",
                "source_blueprint",
                "source_blueprint_result",
                "result",
                "manifest",
            ),
        )
    nested = payload.get("stage123_front_chain_payload")
    nested_payload = nested if isinstance(nested, Mapping) else {}
    blueprint_payload = payload.get("stage1_source_blueprint_payload")
    if not isinstance(blueprint_payload, Mapping):
        blueprint_payload = nested_payload.get("stage1_source_blueprint_payload")
    if not isinstance(blueprint_payload, Mapping):
        candidates = _list(market_scan.get("opportunity_candidates"))
        if not candidates:
            return {}
        blueprint_payload = {
            "market_scan": dict(market_scan),
            "opportunity_candidate": dict(candidates[0]),
            "now": created_at,
        }
    run_payload = dict(blueprint_payload)
    run_payload.setdefault("market_scan", dict(market_scan))
    run_payload.setdefault("now", created_at)
    try:
        return Stage1SourceBlueprintOrchestrator().build(run_payload, persist=False)
    except ValueError as exc:
        return {
            "source_blueprint_plan_state": "BLOCKED",
            "blocking_reasons": [str(exc)],
            "stage2_capture_plan": {},
        }


def _stage2_capture_records(payload: Mapping[str, Any], *, source_blueprint: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = _list(payload.get("stage2_capture_records") or payload.get("stage2_capture_readbacks"))
    if records:
        return [dict(record) for record in records if isinstance(record, Mapping)]
    records = _records_from_json(payload.get("stage2_capture_json"))
    if records:
        return records
    capture_plan = source_blueprint.get("stage2_capture_plan") if isinstance(source_blueprint, Mapping) else {}
    if not isinstance(capture_plan, Mapping) or not capture_plan:
        return []
    return [
        {
            "capture_plan_id": str(capture_plan.get("capture_plan_id") or ""),
            "project_id": str(capture_plan.get("project_id") or ""),
            "project_name": str(capture_plan.get("project_name") or ""),
            "stage2_capture_state": "PLAN_READY_NOT_EXECUTED",
            "capture_steps": _list(capture_plan.get("capture_steps")),
            "output_artifact_refs": [],
            "blocking_reasons": ["stage2_capture_not_executed_without_operator_approved_source_fetch"],
            "live_execution_enabled": False,
            "customer_visible_allowed": False,
        }
    ]


def _stage3_parse_records(payload: Mapping[str, Any], *, stage2_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = _list(payload.get("stage3_parse_records") or payload.get("stage3_parse_readbacks"))
    if records:
        return [dict(record) for record in records if isinstance(record, Mapping)]
    records = _records_from_json(payload.get("stage3_parse_json"))
    if records:
        return records
    if not stage2_records:
        return []
    return [
        {
            "project_id": str(record.get("project_id") or ""),
            "stage3_parse_state": "WAITING_FOR_STAGE2_CAPTURE_ARTIFACT",
            "input_artifact_refs": _dedupe(_list(record.get("output_artifact_refs"))),
            "output_artifact_refs": [],
            "blocking_reasons": ["stage3_parse_waiting_for_stage2_capture_artifact"],
            "customer_visible_allowed": False,
        }
        for record in stage2_records
    ]


def _stage1_record(market_scan: Mapping[str, Any], source_blueprint: Mapping[str, Any]) -> dict[str, Any]:
    scan_state = "COMPLETED" if market_scan else "NOT_PROVIDED"
    blueprint_state = "COMPLETED" if source_blueprint and source_blueprint.get("stage2_capture_plan") else "NOT_READY"
    return {
        "stage_id": "stage1_tasking",
        "run_state": "READY_FOR_STAGE2" if scan_state == "COMPLETED" and blueprint_state == "COMPLETED" else "REVIEW_REQUIRED",
        "market_scan_state": scan_state,
        "source_blueprint_state": blueprint_state,
        "selected_candidate_count": int(market_scan.get("selected_candidate_count") or 0) if market_scan else 0,
        "next_action": "dispatch_stage2_capture_plan" if blueprint_state == "COMPLETED" else "record_stage1_market_scan_or_candidate",
        "blocking_reasons": [] if blueprint_state == "COMPLETED" else ["stage1_source_blueprint_or_candidate_missing"],
    }


def _stage2_record(stage2_records: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = _counts(str(record.get("stage2_capture_state") or record.get("capture_state") or "") for record in stage2_records)
    ready_count = sum(1 for record in stage2_records if str(record.get("stage2_capture_state") or record.get("capture_state") or "") in {"CAPTURED", "READBACK_READY", "DETAIL_CAPTURED"})
    return {
        "stage_id": "stage2_ingestion",
        "run_state": "READY_FOR_STAGE3" if ready_count else "BLOCKED",
        "record_count": len(stage2_records),
        "capture_state_counts": counts,
        "next_action": "dispatch_stage3_parse" if ready_count else "await_controlled_stage2_capture_readback",
        "blocking_reasons": [] if ready_count else ["stage2_capture_readback_missing_or_not_executed"],
    }


def _stage3_record(stage3_records: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = _counts(str(record.get("stage3_parse_state") or record.get("parse_state") or "") for record in stage3_records)
    ready_count = sum(1 for record in stage3_records if str(record.get("stage3_parse_state") or record.get("parse_state") or "") in {"PARSED", "READY_FOR_STAGE4", "READBACK_READY"})
    return {
        "stage_id": "stage3_parsing",
        "run_state": "READY_FOR_STAGE4" if ready_count else "BLOCKED",
        "record_count": len(stage3_records),
        "parse_state_counts": counts,
        "next_action": "dispatch_stage4_verification" if ready_count else "await_controlled_stage3_parse_readback",
        "blocking_reasons": [] if ready_count else ["stage3_parse_readback_missing_or_not_parsed"],
    }


def _summary(
    stage_records: list[Mapping[str, Any]],
    market_scan: Mapping[str, Any],
    source_blueprint: Mapping[str, Any],
    stage2_records: list[Mapping[str, Any]],
    stage3_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    blocking_reasons = _dedupe(
        reason
        for record in stage_records
        for reason in _list(record.get("blocking_reasons"))
    )
    return {
        "stage123_front_chain_state": "READY_WITH_BLOCKERS" if blocking_reasons else "READY",
        "stage1_market_scan_present": bool(market_scan),
        "stage1_selected_candidate_count": int(market_scan.get("selected_candidate_count") or 0) if market_scan else 0,
        "stage1_source_blueprint_present": bool(source_blueprint),
        "stage2_capture_record_count": len(stage2_records),
        "stage3_parse_record_count": len(stage3_records),
        "stage123_stability_summary": _stage123_stability_summary(stage2_records, stage3_records),
        "stage_run_state_counts": _counts(record.get("run_state") for record in stage_records),
        "blocking_reasons": blocking_reasons,
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
    }


def _stage123_stability_summary(
    stage2_records: list[Mapping[str, Any]],
    stage3_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    stage2_attachment_snapshot_count = sum(_int(record.get("attachment_snapshot_count")) for record in stage2_records)
    stage2_attachment_attempted_count = sum(
        _int(record.get("attachment_capture_attempted_count")) for record in stage2_records
    )
    stage3_attachment_ocr_required_count = sum(
        _int(record.get("attachment_ocr_required_count")) for record in stage3_records
    )
    stage3_attachment_ocr_extracted_count = sum(
        _int(record.get("attachment_ocr_extracted_count")) for record in stage3_records
    )
    attachment_text_cache_hit_count = sum(
        _int(record.get("attachment_text_cache_hit_count")) for record in stage3_records
    )
    responsible_gap_count = sum(
        1
        for record in stage3_records
        if bool(record.get("responsible_role_gap_review_required"))
        or str(record.get("responsible_role_gap_code") or "").strip()
    )
    attachment_readback_missing_count = sum(
        1
        for record in [*stage2_records, *stage3_records]
        if "attachment_snapshot_readback_missing" in _list(record.get("blocking_reasons"))
        or "attachment_snapshot_readback_missing" in _list(record.get("degraded_reasons"))
    )
    stage3_parse_blocker_count = sum(
        1
        for record in stage3_records
        if str(record.get("stage3_parse_state") or record.get("parse_state") or "") not in {
            "PARSED",
            "READY_FOR_STAGE4",
            "READBACK_READY",
        }
    )
    return {
        "stage2_attachment_capture_attempted_count": stage2_attachment_attempted_count,
        "stage2_attachment_snapshot_count": stage2_attachment_snapshot_count,
        "stage2_attachment_snapshot_missing_count": max(
            stage2_attachment_attempted_count - stage2_attachment_snapshot_count,
            0,
        ),
        "attachment_snapshot_readback_missing_count": attachment_readback_missing_count,
        "stage3_attachment_ocr_required_count": stage3_attachment_ocr_required_count,
        "stage3_attachment_ocr_extracted_count": stage3_attachment_ocr_extracted_count,
        "stage3_attachment_ocr_pending_count": max(
            stage3_attachment_ocr_required_count - stage3_attachment_ocr_extracted_count,
            0,
        ),
        "attachment_text_cache_hit_count": attachment_text_cache_hit_count,
        "stage3_responsible_role_gap_count": responsible_gap_count,
        "stage3_parse_blocker_count": stage3_parse_blocker_count,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
    }


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _json_mapping(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    path = Path(text)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _records_from_json(value: Any) -> list[dict[str, Any]]:
    loaded = _json_mapping(value)
    raw_records = _first_record_list(
        loaded,
        (
            "records",
            "stage2_capture_records",
            "stage2_capture_readbacks",
            "stage3_parse_records",
            "stage3_parse_readbacks",
            "capture_records",
            "parse_records",
            "readbacks",
            "application_records",
        ),
    )
    return [dict(record) for record in _list(raw_records) if isinstance(record, Mapping)]


def _select_mapping(value: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        nested = value.get(key)
        if isinstance(nested, Mapping):
            return dict(nested)
    manifest = value.get("manifest")
    if isinstance(manifest, Mapping):
        for key in keys:
            nested = manifest.get(key)
            if isinstance(nested, Mapping):
                return dict(nested)
    return dict(value)


def _first_record_list(value: Mapping[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, list):
            return raw
    manifest = value.get("manifest")
    if isinstance(manifest, Mapping):
        for key in keys:
            raw = manifest.get(key)
            if isinstance(raw, list):
                return raw
    result = value.get("result")
    if isinstance(result, Mapping):
        for key in keys:
            raw = result.get(key)
            if isinstance(raw, list):
                return raw
    return []


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "STAGE123_FRONT_CHAIN_KIND",
    "build_stage123_runtime_front_chain",
    "has_stage123_front_chain_input",
]
