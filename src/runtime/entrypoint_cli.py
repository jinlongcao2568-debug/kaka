from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from runtime.entrypoint_registry import RuntimeEntrypointRegistry
from runtime.run_controller import RunController
from shared.utils import utc_now_iso


SUPPORTED_RUNTIME_CONTROLLER_TARGETS = {
    "stage1_6_internal_http_orchestration_preview",
    "stage1_3_repair_worker",
    "stage6_review_cycle_runner",
}


def run_runtime_entrypoint(
    *,
    entrypoint_id: str,
    payload: Mapping[str, Any],
    registry_path: str | Path | None = None,
    registry: RuntimeEntrypointRegistry | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    active_registry = registry or (
        RuntimeEntrypointRegistry.from_path(registry_path)
        if registry_path is not None
        else RuntimeEntrypointRegistry.default()
    )
    active_registry.require_transport_entrypoint()
    target_entrypoint = active_registry.require_registered_entrypoint(entrypoint_id)
    if entrypoint_id not in SUPPORTED_RUNTIME_CONTROLLER_TARGETS:
        raise ValueError(f"unsupported_runtime_controller_entrypoint_id:{entrypoint_id}")

    created = created_at or utc_now_iso()
    payload_map = dict(payload)
    payload_map["entrypoint_id"] = entrypoint_id
    if entrypoint_id == "stage1_3_repair_worker":
        from runtime.stage13_repair_worker import build_stage1_3_repair_worker_plan
        from storage.repositories.runtime_state_repo import RuntimeStateRepository

        worker_result = build_stage1_3_repair_worker_plan(payload_map, created_at=created)
        worker_persistence = RuntimeStateRepository().save_worker_result(worker_result)
        return {
            "entrypoint_transport_mode": "RUNTIME_CONTROLLER_ENTRYPOINT",
            "entrypoint_id": entrypoint_id,
            "registry_path": str(active_registry.path),
            "registry_entrypoint_status": str(target_entrypoint.get("status") or ""),
            "created_at": created,
            "worker_result": worker_result,
            "worker_persistence": worker_persistence,
            "safety": {
                "external_customer_action_enabled": False,
                "customer_visible_download_enabled": False,
                "real_outreach_enabled": False,
                "real_payment_enabled": False,
                "real_delivery_enabled": False,
                "real_refund_enabled": False,
                "automatic_refund_enabled": False,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }

    controller = RunController(stage6_preview_executor=_stage6_preview_executor)
    if entrypoint_id == "stage6_review_cycle_runner":
        controller_result = controller.start_stage1_6_runtime_cycle(payload_map, created_at=created)
    else:
        controller_result = controller.start_stage1_6_preview_run(payload_map, created_at=created)
    return {
        "entrypoint_transport_mode": "RUNTIME_CONTROLLER_ENTRYPOINT",
        "entrypoint_id": entrypoint_id,
        "registry_path": str(active_registry.path),
        "registry_entrypoint_status": str(target_entrypoint.get("status") or ""),
        "created_at": created,
        "controller_result": controller_result,
        "safety": controller_result["run_state"]["safety"],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _stage6_preview_executor(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    explicit = payload.get("stage6_preview_result")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    return {
        "stage_id": "stage6_fact_review",
        "stage_state": "BLOCKED",
        "output_artifact_refs": [],
        "blocking_reasons": ["stage6_preview_result_missing"],
        "next_action": "manual_review_runtime_entrypoint_payload",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a controller-owned runtime entrypoint transport.")
    parser.add_argument("--entrypoint-id", required=True)
    parser.add_argument("--payload-json", default="")
    parser.add_argument("--payload", default="")
    parser.add_argument("--batch-closeout-json", default="")
    parser.add_argument("--batch-closeout-root", default="")
    parser.add_argument("--runtime-blocker-next-subqueue-json", default="")
    parser.add_argument("--runtime-blocker-next-subqueue-root", default="")
    parser.add_argument("--stage6-review-loop-json", default="")
    parser.add_argument("--stage6-review-loop-root", default="")
    parser.add_argument("--stage6-review-loop-status-json", default="")
    parser.add_argument("--stage6-review-loop-status-root", default="")
    parser.add_argument("--release-field-query-json", default="")
    parser.add_argument("--release-field-query-root", default="")
    parser.add_argument("--release-evidence-adapter-plan-json", default="")
    parser.add_argument("--release-evidence-adapter-plan-root", default="")
    parser.add_argument("--gdcic-browser-readback-json", default="")
    parser.add_argument("--gdcic-browser-readback-root", default="")
    parser.add_argument("--original-backtrace-continuation-json", default="")
    parser.add_argument("--original-backtrace-continuation-root", default="")
    parser.add_argument("--stage16-p13b-continuation-json", default="")
    parser.add_argument("--stage16-p13b-continuation-root", default="")
    parser.add_argument("--stage1-6-real-public-pressure-report-json", default="")
    parser.add_argument("--stage1-6-readiness-json", default="")
    parser.add_argument("--stage1-6-gap-summary-json", default="")
    parser.add_argument("--stage1-6-scoreboard-json", default="")
    parser.add_argument("--stage1-market-scan-json", default="")
    parser.add_argument("--stage1-source-blueprint-json", default="")
    parser.add_argument("--stage2-capture-json", default="")
    parser.add_argument("--stage3-parse-json", default="")
    parser.add_argument("--stage123-front-chain-output-root", default="")
    parser.add_argument("--stage5-calibration-sample-json", default="")
    parser.add_argument("--stage5-calibration-sample-root", default="")
    parser.add_argument("--stage4-backfill-followup-queue-json", default="")
    parser.add_argument("--stage4-backfill-followup-queue-root", default="")
    parser.add_argument("--stage45-replay-samples-json", default="")
    parser.add_argument("--stage45-replay-output-root", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_json:
        payload = json.loads(Path(args.payload_json).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload_json_must_be_object")
    elif args.payload:
        payload = json.loads(args.payload)
        if not isinstance(payload, dict):
            raise ValueError("payload_must_be_object")
    else:
        payload = {}
    explicit_runtime_inputs = {
        "batch_closeout_json": args.batch_closeout_json,
        "batch_closeout_root": args.batch_closeout_root,
        "runtime_blocker_next_subqueue_json": args.runtime_blocker_next_subqueue_json,
        "runtime_blocker_next_subqueue_root": args.runtime_blocker_next_subqueue_root,
        "stage6_review_loop_json": args.stage6_review_loop_json,
        "stage6_review_loop_root": args.stage6_review_loop_root,
        "stage6_review_loop_status_json": args.stage6_review_loop_status_json,
        "stage6_review_loop_status_root": args.stage6_review_loop_status_root,
        "release_field_query_json": args.release_field_query_json,
        "release_field_query_root": args.release_field_query_root,
        "release_evidence_adapter_plan_json": args.release_evidence_adapter_plan_json,
        "release_evidence_adapter_plan_root": args.release_evidence_adapter_plan_root,
        "gdcic_browser_readback_json": args.gdcic_browser_readback_json,
        "gdcic_browser_readback_root": args.gdcic_browser_readback_root,
        "original_backtrace_continuation_json": args.original_backtrace_continuation_json,
        "original_backtrace_continuation_root": args.original_backtrace_continuation_root,
        "stage16_p13b_continuation_json": args.stage16_p13b_continuation_json,
        "stage16_p13b_continuation_root": args.stage16_p13b_continuation_root,
        "stage1_6_real_public_pressure_report_json": args.stage1_6_real_public_pressure_report_json,
        "stage1_6_readiness_json": args.stage1_6_readiness_json,
        "stage1_6_gap_summary_json": args.stage1_6_gap_summary_json,
        "stage1_6_scoreboard_json": args.stage1_6_scoreboard_json,
        "stage1_market_scan_json": args.stage1_market_scan_json,
        "stage1_source_blueprint_json": args.stage1_source_blueprint_json,
        "stage2_capture_json": args.stage2_capture_json,
        "stage3_parse_json": args.stage3_parse_json,
        "stage123_front_chain_output_root": args.stage123_front_chain_output_root,
        "stage5_calibration_sample_json": args.stage5_calibration_sample_json,
        "stage5_calibration_sample_root": args.stage5_calibration_sample_root,
        "stage4_backfill_followup_queue_json": args.stage4_backfill_followup_queue_json,
        "stage4_backfill_followup_queue_root": args.stage4_backfill_followup_queue_root,
        "stage45_replay_samples_json": args.stage45_replay_samples_json,
        "stage45_replay_output_root": args.stage45_replay_output_root,
    }
    for key, value in explicit_runtime_inputs.items():
        if value:
            payload[key] = value
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_runtime_entrypoint(
        entrypoint_id=args.entrypoint_id,
        payload=_load_payload(args),
        created_at=args.created_at or None,
    )
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
