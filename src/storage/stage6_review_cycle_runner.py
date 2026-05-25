from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from shared.utils import utc_now_iso
import yaml
from storage.evidence_stage6_fact_package import build_evidence_stage6_fact_package
from storage.runtime_closeout_precedence import (
    build_runtime_blocker_next_subqueue_table,
    build_runtime_blocker_controller_dispatch_table,
    build_runtime_blocker_subqueue_controller_table,
    runtime_blocker_subqueue_routes as _runtime_blocker_subqueue_routes,
)
from storage.runtime_blocker_controller_dispatch_runner import (
    run_runtime_blocker_controller_dispatch_runner,
)
from storage.guangdong_local_field_query_probe import build_guangdong_local_field_query_probe
from storage.stage6_review_cycle_continuation_refs import build_stage6_review_cycle_continuation_input_refs
from storage.stage6_review_action_dispatch import build_stage6_review_action_dispatch
from storage.stage6_review_action_dispatch_runner import run_stage6_review_action_dispatch_runner


STAGE6_REVIEW_CYCLE_RUNNER_KIND = "stage6_review_cycle_runner_v1_manifest"
STAGE6_REVIEW_CYCLE_RUNNER_VERSION = 1
STAGE6_REVIEW_CYCLE_RUNNER_ADAPTER_ID = "stage6-review-cycle-runner-v1"

DEFAULT_BATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage6-review-cycle-runner-v1")
DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT = Path(
    "tmp/evaluation-real-samples/design-survey-public-registry-readback-v1"
)
DEFAULT_RUNTIME_BLOCKER_NEXT_SUBQUEUE_FILENAME = "stage6-review-loop-runtime-blocker-next-subqueues.json"
DEFAULT_STAGE6_REVIEW_LOOP_STATUS_FILENAME = "stage6-review-loop-project-status-table.json"
DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH = Path("control") / "stage6_review_cycle_bootstrap_registry.yaml"

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
BOOTSTRAP_REGISTRY_RUNTIME_LAYER = "schema/contract:stage6_review_cycle_bootstrap_registry"
BOOTSTRAP_REGISTRY_REQUIRED_INPUT = ["valid_stage6_review_cycle_bootstrap_registry_yaml"]

CommandExecutor = Callable[[list[str], Path], Mapping[str, Any]]

DEFAULT_BOOTSTRAP_SOURCE_REGISTRY = [
    {
        "source_kind": "RELEASE_FIELD_QUERY_JSON",
        "source_ref_key": "release_field_query_json",
        "source_root_ref_key": "release_field_query_root",
        "default_filename": "guangdong-local-field-query-probe-v1.json",
        "handler_kind": "loop_runner_bootstrap",
        "loop_runner_arg": "release_field_query_json",
        "missing_reason": "release_field_query_json_missing_or_invalid",
        "bootstrap_failure_reason": "stage6_review_loop_bootstrap_from_release_field_query_failed",
    },
    {
        "source_kind": "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON",
        "source_ref_key": "runtime_blocker_next_subqueue_json",
        "source_root_ref_key": "runtime_blocker_next_subqueue_root",
        "default_filename": DEFAULT_RUNTIME_BLOCKER_NEXT_SUBQUEUE_FILENAME,
        "handler_kind": "next_subqueue_json",
    },
    {
        "source_kind": "STAGE6_REVIEW_LOOP_JSON",
        "source_ref_key": "stage6_review_loop_json",
        "source_root_ref_key": "stage6_review_loop_root",
        "default_filename": "stage6-review-loop-runner-v1.json",
        "handler_kind": "stage6_loop_runner_artifact",
    },
    {
        "source_kind": "STAGE6_REVIEW_LOOP_STATUS_JSON",
        "source_ref_key": "stage6_review_loop_status_json",
        "source_root_ref_key": "stage6_review_loop_status_root",
        "default_filename": DEFAULT_STAGE6_REVIEW_LOOP_STATUS_FILENAME,
        "handler_kind": "status_table_json",
    },
    {
        "source_kind": "RELEASE_EVIDENCE_ADAPTER_PLAN_JSON",
        "source_ref_key": "release_evidence_adapter_plan_json",
        "source_root_ref_key": "release_evidence_adapter_plan_root",
        "default_filename": "release-evidence-adapter-plan-v1.json",
        "handler_kind": "loop_runner_bootstrap",
        "loop_runner_arg": "release_evidence_adapter_plan_json",
        "missing_reason": "release_evidence_adapter_plan_json_missing_or_invalid",
        "bootstrap_failure_reason": "stage6_review_loop_bootstrap_from_release_evidence_plan_failed",
    },
    {
        "source_kind": "GDCIC_BROWSER_READBACK_JSON",
        "source_ref_key": "gdcic_browser_readback_json",
        "source_root_ref_key": "gdcic_browser_readback_root",
        "default_filename": "gdcic-browser-authorized-readback-v1.json",
        "handler_kind": "derived_release_field_query",
        "missing_reason": "gdcic_browser_readback_json_missing_or_invalid",
        "bootstrap_failure_reason": "stage6_review_cycle_derive_release_field_query_from_gdcic_readback_failed",
    },
    {
        "source_kind": "ORIGINAL_BACKTRACE_CONTINUATION_JSON",
        "source_ref_key": "original_backtrace_continuation_json",
        "source_root_ref_key": "original_backtrace_continuation_root",
        "default_filename": "p13b-original-backtrace-continuation-controller-v2.json",
        "handler_kind": "loop_runner_bootstrap",
        "loop_runner_arg": "original_backtrace_continuation_json",
        "missing_reason": "original_backtrace_continuation_json_missing_or_invalid",
        "bootstrap_failure_reason": "stage6_review_loop_bootstrap_from_original_backtrace_continuation_failed",
    },
    {
        "source_kind": "STAGE16_P13B_CONTINUATION_JSON",
        "source_ref_key": "stage16_p13b_continuation_json",
        "source_root_ref_key": "stage16_p13b_continuation_root",
        "default_filename": "stage16-p13b-continuation-controller-v1.json",
        "handler_kind": "loop_runner_bootstrap",
        "loop_runner_arg": "stage16_p13b_continuation_json",
        "missing_reason": "stage16_p13b_continuation_json_missing_or_invalid",
        "bootstrap_failure_reason": "stage6_review_loop_bootstrap_from_stage16_p13b_continuation_failed",
    },
    {
        "source_kind": "STAGE5_CALIBRATION_SAMPLE_JSON",
        "source_ref_key": "stage5_calibration_sample_json",
        "source_root_ref_key": "stage5_calibration_sample_root",
        "default_filename": "stage5-calibration-sample-table.json",
        "handler_kind": "loop_runner_bootstrap",
        "loop_runner_arg": "stage5_calibration_sample_json",
        "missing_reason": "stage5_calibration_sample_json_missing_or_invalid",
        "bootstrap_failure_reason": "stage6_review_loop_bootstrap_from_stage5_calibration_sample_failed",
    },
]


def _bootstrap_source_registry_rows() -> list[dict[str, Any]]:
    return [
        {
            "source_kind": str(item["source_kind"]),
            "source_ref_key": str(item["source_ref_key"]),
            "handler_kind": str(item["handler_kind"]),
            "loop_runner_arg": str(item.get("loop_runner_arg") or ""),
            "priority_order": index,
        }
        for index, item in enumerate(_bootstrap_source_registry(), start=1)
    ]


def _bootstrap_registry_payload() -> dict[str, Any]:
    path = DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return {
            "registry_id": "",
            "registry_version": 0,
            "registry_path": str(path),
            "registry_state": "BOOTSTRAP_REGISTRY_MISSING_OR_INVALID",
            "blocking_reason": "stage6_review_cycle_bootstrap_registry_missing_or_invalid",
            "registry_error": str(exc),
            "validation_errors": [],
            "validation_error_records": [
                _bootstrap_registry_validation_error_record(
                    source_index=None,
                    source_kind="BOOTSTRAP_REGISTRY",
                    field="registry_path",
                    error_code="registry_missing_or_invalid",
                    invalid_value=str(path),
                    blocking_reason="stage6_review_cycle_bootstrap_registry_missing_or_invalid",
                    operator_next_action="restore_stage6_review_cycle_bootstrap_registry_yaml_then_rerun_cycle",
                )
            ],
            "sources": [],
        }
    if not isinstance(loaded, Mapping):
        return {
            "registry_id": "",
            "registry_version": 0,
            "registry_path": str(path),
            "registry_state": "BOOTSTRAP_REGISTRY_MISSING_OR_INVALID",
            "blocking_reason": "stage6_review_cycle_bootstrap_registry_not_mapping",
            "registry_error": "stage6_review_cycle_bootstrap_registry_not_mapping",
            "validation_errors": [],
            "validation_error_records": [
                _bootstrap_registry_validation_error_record(
                    source_index=None,
                    source_kind="BOOTSTRAP_REGISTRY",
                    field="document_root",
                    error_code="registry_not_mapping",
                    invalid_value=type(loaded).__name__,
                    blocking_reason="stage6_review_cycle_bootstrap_registry_not_mapping",
                    operator_next_action="fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
                )
            ],
            "sources": [],
        }
    sources = loaded.get("sources")
    if not isinstance(sources, list):
        return {
            "registry_id": str(loaded.get("registry_id") or ""),
            "registry_version": int(loaded.get("registry_version") or 0),
            "registry_path": str(path),
            "registry_state": "BOOTSTRAP_REGISTRY_MISSING_OR_INVALID",
            "blocking_reason": "stage6_review_cycle_bootstrap_registry_sources_missing",
            "registry_error": "stage6_review_cycle_bootstrap_registry_sources_missing",
            "validation_errors": [],
            "validation_error_records": [
                _bootstrap_registry_validation_error_record(
                    source_index=None,
                    source_kind="BOOTSTRAP_REGISTRY",
                    field="sources",
                    error_code="sources_missing",
                    invalid_value="",
                    blocking_reason="stage6_review_cycle_bootstrap_registry_sources_missing",
                    operator_next_action="fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
                )
            ],
            "sources": [],
        }
    validation_errors, validation_error_records = _validate_bootstrap_registry_sources(sources)
    if validation_errors:
        return {
            "registry_id": str(loaded.get("registry_id") or ""),
            "registry_version": int(loaded.get("registry_version") or 0),
            "registry_path": str(path),
            "registry_state": "BOOTSTRAP_REGISTRY_SCHEMA_INVALID",
            "blocking_reason": "stage6_review_cycle_bootstrap_registry_schema_invalid",
            "registry_error": "stage6_review_cycle_bootstrap_registry_schema_invalid",
            "validation_errors": validation_errors,
            "validation_error_records": validation_error_records,
            "sources": [],
        }
    return {
        "registry_id": str(loaded.get("registry_id") or ""),
        "registry_version": int(loaded.get("registry_version") or 0),
        "registry_path": str(path),
        "registry_state": "BOOTSTRAP_REGISTRY_READY",
        "blocking_reason": "",
        "registry_error": "",
        "validation_errors": [],
        "validation_error_records": [],
        "sources": [dict(item) for item in sources if isinstance(item, Mapping)],
    }


def _bootstrap_registry_validation_error_record(
    *,
    source_index: int | None,
    source_kind: str,
    field: str,
    error_code: str,
    invalid_value: str,
    blocking_reason: str,
    operator_next_action: str,
) -> dict[str, Any]:
    return {
        "source_index": source_index,
        "source_kind": source_kind,
        "field": field,
        "error_code": error_code,
        "invalid_value": invalid_value,
        "runtime_layer": BOOTSTRAP_REGISTRY_RUNTIME_LAYER,
        "blocking_reason": blocking_reason,
        "required_input": list(BOOTSTRAP_REGISTRY_REQUIRED_INPUT),
        "operator_next_action": operator_next_action,
    }


def _validate_bootstrap_registry_sources(sources: list[Any]) -> tuple[list[str], list[dict[str, Any]]]:
    allowed_handler_kinds = set(_bootstrap_handler_dispatch_map().keys())
    errors: list[str] = []
    error_records: list[dict[str, Any]] = []
    for index, item in enumerate(sources):
        if not isinstance(item, Mapping):
            errors.append(f"source[{index}]:not_mapping")
            error_records.append(
                _bootstrap_registry_validation_error_record(
                    source_index=index,
                    source_kind="",
                    field="source_entry",
                    error_code="source_not_mapping",
                    invalid_value=type(item).__name__,
                    blocking_reason="stage6_review_cycle_bootstrap_registry_schema_invalid",
                    operator_next_action="fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
                )
            )
            continue
        source_kind = str(item.get("source_kind") or "").strip()
        missing_fields = [
            field for field in ("source_kind", "source_ref_key", "handler_kind")
            if not str(item.get(field) or "").strip()
        ]
        if missing_fields:
            errors.append(f"source[{index}]:missing_fields:{','.join(missing_fields)}")
            for field in missing_fields:
                error_records.append(
                    _bootstrap_registry_validation_error_record(
                        source_index=index,
                        source_kind=source_kind,
                        field=field,
                        error_code="missing_required_field",
                        invalid_value="",
                        blocking_reason="stage6_review_cycle_bootstrap_registry_schema_invalid",
                        operator_next_action="fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
                    )
                )
        handler_kind = str(item.get("handler_kind") or "").strip()
        if handler_kind and handler_kind not in allowed_handler_kinds:
            errors.append(f"source[{index}]:unknown_handler_kind:{handler_kind}")
            error_records.append(
                _bootstrap_registry_validation_error_record(
                    source_index=index,
                    source_kind=source_kind,
                    field="handler_kind",
                    error_code="unknown_handler_kind",
                    invalid_value=handler_kind,
                    blocking_reason="stage6_review_cycle_bootstrap_registry_schema_invalid",
                    operator_next_action="fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
                )
            )
    return errors, error_records


def _bootstrap_source_registry() -> list[dict[str, Any]]:
    payload = _bootstrap_registry_payload()
    sources = payload.get("sources")
    return [dict(item) for item in sources if isinstance(item, Mapping)]


def _bootstrap_source_candidate_registry_rows() -> list[dict[str, Any]]:
    return [
        {
            "source_kind": str(item["source_kind"]),
            "source_ref_key": str(item["source_ref_key"]),
            "source_root_ref_key": str(item.get("source_root_ref_key") or ""),
            "default_filename": str(item.get("default_filename") or ""),
            "priority_order": index,
        }
        for index, item in enumerate(_bootstrap_source_registry(), start=1)
    ]


def _bootstrap_source_handler_registry_rows() -> list[dict[str, Any]]:
    return [
        {
            "source_kind": str(item["source_kind"]),
            "handler_kind": str(item["handler_kind"]),
            "loop_runner_arg": str(item.get("loop_runner_arg") or ""),
            "priority_order": index,
        }
        for index, item in enumerate(_bootstrap_source_registry(), start=1)
    ]


def _bootstrap_handler_dispatch_map() -> dict[str, Callable[..., tuple[dict[str, Any], str, str, Path | None, Path | None, str]]]:
    return {
        "next_subqueue_json": _resolve_next_subqueue_candidate,
        "stage6_loop_runner_artifact": _resolve_stage6_loop_runner_artifact_candidate,
        "status_table_json": _resolve_status_table_candidate,
        "loop_runner_bootstrap": _resolve_loop_bootstrap_candidate,
        "derived_release_field_query": _resolve_derived_release_field_query_candidate,
        "stage4_followup_queue": _resolve_stage4_followup_queue_candidate,
    }


def _bootstrap_source_candidates(
    *,
    runtime_blocker_next_subqueue_json: str | Path | None,
    runtime_blocker_next_subqueue_root: str | Path | None,
    stage6_review_loop_json: str | Path | None,
    stage6_review_loop_root: str | Path | None,
    stage6_review_loop_status_json: str | Path | None,
    stage6_review_loop_status_root: str | Path | None,
    release_field_query_json: str | Path | None,
    release_field_query_root: str | Path | None,
    release_evidence_adapter_plan_json: str | Path | None,
    release_evidence_adapter_plan_root: str | Path | None,
    gdcic_browser_readback_json: str | Path | None,
    gdcic_browser_readback_root: str | Path | None,
    original_backtrace_continuation_json: str | Path | None,
    original_backtrace_continuation_root: str | Path | None,
    stage16_p13b_continuation_json: str | Path | None,
    stage16_p13b_continuation_root: str | Path | None,
    stage5_calibration_sample_json: str | Path | None,
    stage5_calibration_sample_root: str | Path | None,
    stage4_backfill_followup_queue_json: str | Path | None = None,
    stage4_backfill_followup_queue_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    explicit_jsons = {
        "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON": runtime_blocker_next_subqueue_json,
        "STAGE6_REVIEW_LOOP_JSON": stage6_review_loop_json,
        "STAGE6_REVIEW_LOOP_STATUS_JSON": stage6_review_loop_status_json,
        "RELEASE_FIELD_QUERY_JSON": release_field_query_json,
        "RELEASE_EVIDENCE_ADAPTER_PLAN_JSON": release_evidence_adapter_plan_json,
        "GDCIC_BROWSER_READBACK_JSON": gdcic_browser_readback_json,
        "ORIGINAL_BACKTRACE_CONTINUATION_JSON": original_backtrace_continuation_json,
        "STAGE16_P13B_CONTINUATION_JSON": stage16_p13b_continuation_json,
        "STAGE5_CALIBRATION_SAMPLE_JSON": stage5_calibration_sample_json,
        "STAGE4_BACKFILL_FOLLOWUP_QUEUE_JSON": stage4_backfill_followup_queue_json,
    }
    explicit_roots = {
        "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON": runtime_blocker_next_subqueue_root,
        "STAGE6_REVIEW_LOOP_JSON": stage6_review_loop_root,
        "STAGE6_REVIEW_LOOP_STATUS_JSON": stage6_review_loop_status_root,
        "RELEASE_FIELD_QUERY_JSON": release_field_query_root,
        "RELEASE_EVIDENCE_ADAPTER_PLAN_JSON": release_evidence_adapter_plan_root,
        "GDCIC_BROWSER_READBACK_JSON": gdcic_browser_readback_root,
        "ORIGINAL_BACKTRACE_CONTINUATION_JSON": original_backtrace_continuation_root,
        "STAGE16_P13B_CONTINUATION_JSON": stage16_p13b_continuation_root,
        "STAGE5_CALIBRATION_SAMPLE_JSON": stage5_calibration_sample_root,
        "STAGE4_BACKFILL_FOLLOWUP_QUEUE_JSON": stage4_backfill_followup_queue_root,
    }
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(_bootstrap_source_registry(), start=1):
        source_kind = str(item["source_kind"])
        rows.append(
            {
                **dict(item),
                "priority_order": index,
                "source_path": _bootstrap_source_path(
                    source_kind,
                    explicit_json=explicit_jsons.get(source_kind),
                    explicit_root=explicit_roots.get(source_kind),
                ),
            }
        )
    return rows


def run_stage6_review_cycle_runner(
    *,
    batch_closeout_json: str | Path | None = None,
    batch_closeout_root: str | Path = DEFAULT_BATCH_CLOSEOUT_ROOT,
    runtime_blocker_next_subqueue_json: str | Path | None = None,
    runtime_blocker_next_subqueue_root: str | Path | None = None,
    stage6_review_loop_json: str | Path | None = None,
    stage6_review_loop_root: str | Path | None = None,
    stage6_review_loop_status_json: str | Path | None = None,
    stage6_review_loop_status_root: str | Path | None = None,
    release_field_query_json: str | Path | None = None,
    release_field_query_root: str | Path | None = None,
    supplemental_release_field_query_json: str | Path | None = None,
    supplemental_release_field_query_root: str | Path | None = None,
    release_evidence_adapter_plan_json: str | Path | None = None,
    release_evidence_adapter_plan_root: str | Path | None = None,
    gdcic_browser_readback_json: str | Path | None = None,
    gdcic_browser_readback_root: str | Path | None = None,
    original_backtrace_continuation_json: str | Path | None = None,
    original_backtrace_continuation_root: str | Path | None = None,
    stage16_p13b_continuation_json: str | Path | None = None,
    stage16_p13b_continuation_root: str | Path | None = None,
    stage5_calibration_sample_json: str | Path | None = None,
    stage5_calibration_sample_root: str | Path | None = None,
    stage4_backfill_followup_queue_json: str | Path | None = None,
    stage4_backfill_followup_queue_root: str | Path | None = None,
    design_survey_public_registry_readback_json: str | Path | None = None,
    design_survey_public_registry_readback_root: str | Path | None = None,
    stage1_6_scoreboard_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute_dispatch: bool = False,
    dispatch_max_groups: int | None = None,
    execute_runtime_blocker_dispatch: bool = False,
    runtime_blocker_dispatch_max_tasks: int | None = None,
    project_ids: list[str] | tuple[str, ...] = (),
    baseline_evidence_state_json: str | Path | None = None,
    cwd: str | Path | None = None,
    created_at: str | None = None,
    command_executor: CommandExecutor | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    stage6_root = out_dir / "1"
    dispatch_root = out_dir / "2"
    dispatch_runner_root = out_dir / "3"
    controller_dispatch_root = out_dir / "4-runtime-blocker-controller-dispatch"
    controller_dispatch_runner_root = out_dir / "5-runtime-blocker-controller-dispatch-runner"
    out_dir.mkdir(parents=True, exist_ok=True)

    stage6_result = build_evidence_stage6_fact_package(
        batch_closeout_json=batch_closeout_json,
        batch_closeout_root=batch_closeout_root,
        output_root=stage6_root,
        created_at=created,
    )
    dispatch_result: dict[str, Any] = {}
    dispatch_runner_result: dict[str, Any] = {}
    dispatch_runner_skip_reason = ""
    blocking_reasons: list[str] = [*_list(stage6_result.get("blocking_reasons"))]
    bootstrap_candidates = _bootstrap_source_candidates(
        runtime_blocker_next_subqueue_json=runtime_blocker_next_subqueue_json,
        runtime_blocker_next_subqueue_root=runtime_blocker_next_subqueue_root,
        stage6_review_loop_json=stage6_review_loop_json,
        stage6_review_loop_root=stage6_review_loop_root,
        stage6_review_loop_status_json=stage6_review_loop_status_json,
        stage6_review_loop_status_root=stage6_review_loop_status_root,
        release_field_query_json=release_field_query_json,
        release_field_query_root=release_field_query_root,
        release_evidence_adapter_plan_json=release_evidence_adapter_plan_json,
        release_evidence_adapter_plan_root=release_evidence_adapter_plan_root,
        gdcic_browser_readback_json=gdcic_browser_readback_json,
        gdcic_browser_readback_root=gdcic_browser_readback_root,
        original_backtrace_continuation_json=original_backtrace_continuation_json,
        original_backtrace_continuation_root=original_backtrace_continuation_root,
        stage16_p13b_continuation_json=stage16_p13b_continuation_json,
        stage16_p13b_continuation_root=stage16_p13b_continuation_root,
        stage5_calibration_sample_json=stage5_calibration_sample_json,
        stage5_calibration_sample_root=stage5_calibration_sample_root,
        stage4_backfill_followup_queue_json=stage4_backfill_followup_queue_json,
        stage4_backfill_followup_queue_root=stage4_backfill_followup_queue_root,
    )
    candidate_by_kind = {str(item["source_kind"]): item for item in bootstrap_candidates}
    next_subqueue_path = candidate_by_kind.get("RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON", {}).get("source_path")
    stage6_review_loop_path = candidate_by_kind.get("STAGE6_REVIEW_LOOP_JSON", {}).get("source_path")
    stage6_review_loop_status_path = candidate_by_kind.get("STAGE6_REVIEW_LOOP_STATUS_JSON", {}).get("source_path")
    release_field_query_path = candidate_by_kind.get("RELEASE_FIELD_QUERY_JSON", {}).get("source_path")
    supplemental_release_field_query_path = _release_field_query_path(
        release_field_query_json=supplemental_release_field_query_json,
        release_field_query_root=supplemental_release_field_query_root,
    )
    if release_field_query_path is None and supplemental_release_field_query_path is not None:
        release_field_query_path = supplemental_release_field_query_path
        if "RELEASE_FIELD_QUERY_JSON" in candidate_by_kind:
            candidate_by_kind["RELEASE_FIELD_QUERY_JSON"]["source_path"] = supplemental_release_field_query_path
        for candidate in bootstrap_candidates:
            if str(candidate.get("source_kind") or "") == "RELEASE_FIELD_QUERY_JSON":
                candidate["source_path"] = supplemental_release_field_query_path
    release_evidence_adapter_plan_path = candidate_by_kind.get("RELEASE_EVIDENCE_ADAPTER_PLAN_JSON", {}).get("source_path")
    gdcic_browser_readback_path = candidate_by_kind.get("GDCIC_BROWSER_READBACK_JSON", {}).get("source_path")
    derived_release_field_query_path = _derive_release_field_query_from_gdcic_readback(
        release_field_query_path=release_field_query_path,
        release_evidence_adapter_plan_path=release_evidence_adapter_plan_path,
        gdcic_browser_readback_path=gdcic_browser_readback_path,
        output_root=out_dir / "0-derived-release-field-query",
        created_at=created,
    )
    if derived_release_field_query_path:
        release_field_query_path = derived_release_field_query_path
        if "RELEASE_FIELD_QUERY_JSON" in candidate_by_kind:
            candidate_by_kind["RELEASE_FIELD_QUERY_JSON"]["source_path"] = derived_release_field_query_path
        for candidate in bootstrap_candidates:
            if str(candidate.get("source_kind") or "") == "RELEASE_FIELD_QUERY_JSON":
                candidate["source_path"] = derived_release_field_query_path
    original_backtrace_continuation_path = candidate_by_kind.get("ORIGINAL_BACKTRACE_CONTINUATION_JSON", {}).get("source_path")
    stage16_p13b_continuation_path = candidate_by_kind.get("STAGE16_P13B_CONTINUATION_JSON", {}).get("source_path")
    stage5_calibration_sample_path = candidate_by_kind.get("STAGE5_CALIBRATION_SAMPLE_JSON", {}).get("source_path")
    stage4_backfill_followup_queue_path = candidate_by_kind.get("STAGE4_BACKFILL_FOLLOWUP_QUEUE_JSON", {}).get("source_path")
    design_survey_public_registry_readback_path = _optional_json_path(
        explicit_json=design_survey_public_registry_readback_json,
        root=design_survey_public_registry_readback_root or DEFAULT_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK_ROOT,
        default_filename="design-survey-public-registry-readback-v1.json",
    )
    derived_next_subqueue_path = out_dir / "stage6-review-cycle-runtime-blocker-next-subqueues.json"
    (
        runtime_blocker_next_subqueue_table,
        next_subqueue_input_state,
        next_subqueue_blocker,
        effective_next_subqueue_path,
        effective_stage6_review_loop_status_path,
        bootstrap_source_kind,
    ) = _resolve_runtime_blocker_next_subqueue_input(
        candidates=bootstrap_candidates,
        stage6_loop_output_root=out_dir / "0-stage6-loop-bootstrap",
        derived_output_path=derived_next_subqueue_path,
        supplemental_release_field_query_path=supplemental_release_field_query_path,
    )
    standalone_runtime_blocker_queue_only = _standalone_runtime_blocker_queue_only_mode(
        stage6_result=stage6_result,
        runtime_blocker_next_subqueue_input_state=next_subqueue_input_state,
        runtime_blocker_next_subqueue_table=runtime_blocker_next_subqueue_table,
        bootstrap_source_kind=bootstrap_source_kind,
    )
    bootstrap_resolution_trace = _build_bootstrap_resolution_trace(
        candidates=bootstrap_candidates,
        selected_source_kind=bootstrap_source_kind,
        selected_resolution_state=next_subqueue_input_state,
    )
    selected_handler_kind = str(_bootstrap_source_entry(bootstrap_source_kind).get("handler_kind") or "")
    bootstrap_registry_payload = _bootstrap_registry_payload()
    bootstrap_registry_state = str(bootstrap_registry_payload.get("registry_state") or "BOOTSTRAP_REGISTRY_READY")
    bootstrap_registry_blocking_reason = str(bootstrap_registry_payload.get("blocking_reason") or "")
    bootstrap_registry_validation_errors = list(bootstrap_registry_payload.get("validation_errors") or [])
    bootstrap_registry_validation_error_records = list(
        bootstrap_registry_payload.get("validation_error_records") or []
    )
    blocking_reasons: list[str] = (
        []
        if standalone_runtime_blocker_queue_only
        else [*_list(stage6_result.get("blocking_reasons"))]
    )
    if bootstrap_registry_blocking_reason:
        bootstrap_source_kind = "BOOTSTRAP_REGISTRY_BLOCKED"
        selected_handler_kind = ""
        next_subqueue_input_state = "BOOTSTRAP_REGISTRY_BLOCKED"
        standalone_runtime_blocker_queue_only = False
        blocking_reasons.append(bootstrap_registry_blocking_reason)
    if next_subqueue_blocker:
        blocking_reasons.append(next_subqueue_blocker)
    runtime_blocker_subqueue_controller_table = build_runtime_blocker_subqueue_controller_table(
        runtime_blocker_next_subqueue_table,
        source_next_subqueue_ref=str(effective_next_subqueue_path or ""),
    )
    runtime_blocker_controller_dispatch_table = build_runtime_blocker_controller_dispatch_table(
        runtime_blocker_subqueue_controller_table,
        output_root=str(controller_dispatch_root),
    )
    runtime_blocker_controller_dispatch_runner_result = run_runtime_blocker_controller_dispatch_runner(
        controller_dispatch_table=runtime_blocker_controller_dispatch_table,
        output_root=controller_dispatch_runner_root,
        execute_commands=execute_runtime_blocker_dispatch,
        max_tasks=runtime_blocker_dispatch_max_tasks,
        project_ids=project_ids,
        cwd=cwd,
        created_at=created,
        command_executor=command_executor,
    )
    blocking_reasons.extend(_list(runtime_blocker_controller_dispatch_runner_result.get("blocking_reasons")))

    if standalone_runtime_blocker_queue_only:
        dispatch_runner_skip_reason = "standalone_runtime_blocker_queue_only"
    elif bootstrap_registry_blocking_reason:
        dispatch_runner_skip_reason = "bootstrap_registry_blocked"
    elif bool(stage6_result.get("safe_to_execute")):
        dispatch_result = build_stage6_review_action_dispatch(
            stage6_fact_package_root=stage6_root,
            output_root=dispatch_root,
            created_at=created,
        )
        blocking_reasons.extend(_list(dispatch_result.get("blocking_reasons")))
    else:
        blocking_reasons.append("stage6_fact_package_not_safe_to_dispatch")

    dispatch_task_count = _dispatch_task_count(dispatch_result)
    if dispatch_result and bool(dispatch_result.get("safe_to_execute")) and dispatch_task_count > 0:
        dispatch_runner_result = run_stage6_review_action_dispatch_runner(
            dispatch_root=dispatch_root,
            baseline_evidence_state_json=baseline_evidence_state_json,
            output_root=dispatch_runner_root,
            execute_commands=execute_dispatch,
            max_groups=dispatch_max_groups,
            project_ids=project_ids,
            cwd=cwd,
            created_at=created,
            command_executor=command_executor,
        )
        blocking_reasons.extend(_list(dispatch_runner_result.get("blocking_reasons")))
    elif dispatch_result and bool(dispatch_result.get("safe_to_execute")):
        dispatch_runner_skip_reason = "stage6_dispatch_has_no_automated_tasks"
    elif dispatch_result:
        blocking_reasons.append("stage6_dispatch_not_safe_to_run")

    summary = _summary(
        stage6_result=stage6_result,
        dispatch_result=dispatch_result,
        dispatch_runner_result=dispatch_runner_result,
        dispatch_runner_skip_reason=dispatch_runner_skip_reason,
        blocking_reasons=blocking_reasons,
        execute_dispatch=execute_dispatch,
        runtime_blocker_next_subqueue_table=runtime_blocker_next_subqueue_table,
        runtime_blocker_subqueue_controller_table=runtime_blocker_subqueue_controller_table,
        runtime_blocker_controller_dispatch_table=runtime_blocker_controller_dispatch_table,
        runtime_blocker_controller_dispatch_runner_result=runtime_blocker_controller_dispatch_runner_result,
        runtime_blocker_next_subqueue_input_state=next_subqueue_input_state,
        bootstrap_source_kind=bootstrap_source_kind,
        selected_handler_kind=selected_handler_kind,
        bootstrap_registry_state=bootstrap_registry_state,
        bootstrap_registry_path=str(bootstrap_registry_payload.get("registry_path") or ""),
        bootstrap_registry_validation_errors=bootstrap_registry_validation_errors,
        bootstrap_registry_validation_error_records=bootstrap_registry_validation_error_records,
    )
    runtime_blocker_worker_followup_queue = (
        runtime_blocker_controller_dispatch_runner_result.get("manifest", {}).get("runtime_blocker_worker_followup_queue")
        if isinstance(runtime_blocker_controller_dispatch_runner_result.get("manifest"), Mapping)
        else {"records": [], "summary": {}}
    )
    operator_projection_status_table = _operator_projection_status_table(
        summary=summary,
        stage6_result=stage6_result,
        runtime_blocker_worker_followup_queue=runtime_blocker_worker_followup_queue,
        runtime_blocker_subqueue_controller_table=runtime_blocker_subqueue_controller_table,
        runtime_blocker_controller_dispatch_table=runtime_blocker_controller_dispatch_table,
        runtime_blocker_controller_dispatch_runner_result=runtime_blocker_controller_dispatch_runner_result,
        output_root=out_dir,
        source_release_field_query_path=release_field_query_path,
        source_runtime_blocker_next_subqueue_path=effective_next_subqueue_path,
        source_stage6_review_loop_status_path=effective_stage6_review_loop_status_path,
        source_gdcic_browser_readback_path=gdcic_browser_readback_path,
        source_design_survey_public_registry_readback_path=design_survey_public_registry_readback_path,
        source_stage1_6_scoreboard_path=Path(stage1_6_scoreboard_json) if stage1_6_scoreboard_json else None,
        source_supplemental_release_field_query_path=supplemental_release_field_query_path,
    )
    if isinstance(operator_projection_status_table.get("summary"), Mapping):
        summary.update(_operator_projection_controller_summary(operator_projection_status_table["summary"]))
    stage5_calibration_summary = _stage5_calibration_projection_summary(
        operator_projection_status_table.get("records")
        if isinstance(operator_projection_status_table.get("records"), list)
        else []
    )
    summary.update(stage5_calibration_summary)
    if isinstance(operator_projection_status_table.get("summary"), Mapping):
        operator_projection_status_table["summary"].update(stage5_calibration_summary)
    batch_closeout_path = (
        Path(batch_closeout_json)
        if batch_closeout_json
        else Path(batch_closeout_root) / "evidence-batch-closeout-v1.json"
    )
    manifest = {
        "manifest_version": STAGE6_REVIEW_CYCLE_RUNNER_VERSION,
        "manifest_kind": STAGE6_REVIEW_CYCLE_RUNNER_KIND,
        "adapter_id": STAGE6_REVIEW_CYCLE_RUNNER_ADAPTER_ID,
        "pipeline_stage": "Stage6ReviewCycleRunnerV1",
        "manifest_id": f"STAGE6-REVIEW-CYCLE-RUNNER-{_fingerprint({'summary': summary})[:16]}",
        "created_at": created,
        "source_batch_closeout_json": str(batch_closeout_path),
        "source_runtime_blocker_next_subqueue_json": str(effective_next_subqueue_path or ""),
        "source_stage6_review_loop_json": str(stage6_review_loop_path or ""),
        "source_stage6_review_loop_status_json": str(effective_stage6_review_loop_status_path or ""),
        "stage6_review_cycle_bootstrap_registry_state": bootstrap_registry_state,
        "stage6_review_cycle_bootstrap_registry_id": str(bootstrap_registry_payload.get("registry_id") or ""),
        "stage6_review_cycle_bootstrap_registry_version": int(bootstrap_registry_payload.get("registry_version") or 0),
        "stage6_review_cycle_bootstrap_registry_path": str(bootstrap_registry_payload.get("registry_path") or ""),
        "stage6_review_cycle_bootstrap_registry_validation_errors": bootstrap_registry_validation_errors,
        "stage6_review_cycle_bootstrap_registry_validation_error_records": bootstrap_registry_validation_error_records,
        "stage6_review_cycle_bootstrap_source_kind": bootstrap_source_kind,
        "stage6_review_cycle_bootstrap_selected_handler_kind": selected_handler_kind,
        "stage6_review_cycle_bootstrap_source_registry": _bootstrap_source_registry_rows(),
        "stage6_review_cycle_bootstrap_candidate_registry": _bootstrap_source_candidate_registry_rows(),
        "stage6_review_cycle_bootstrap_handler_registry": _bootstrap_source_handler_registry_rows(),
        "stage6_review_cycle_bootstrap_resolution_trace": bootstrap_resolution_trace,
        "source_release_field_query_json": str(release_field_query_path or ""),
        "source_supplemental_release_field_query_json": str(supplemental_release_field_query_path or ""),
        "source_release_evidence_adapter_plan_json": str(release_evidence_adapter_plan_path or ""),
        "source_gdcic_browser_readback_json": str(gdcic_browser_readback_path or ""),
        "derived_release_field_query_from_gdcic_browser_readback_json": str(derived_release_field_query_path or ""),
        "source_original_backtrace_continuation_json": str(original_backtrace_continuation_path or ""),
        "source_stage16_p13b_continuation_json": str(stage16_p13b_continuation_path or ""),
        "source_stage5_calibration_sample_json": str(stage5_calibration_sample_path or ""),
        "source_stage4_backfill_followup_queue_json": str(stage4_backfill_followup_queue_path or ""),
        "source_design_survey_public_registry_readback_json": str(
            design_survey_public_registry_readback_path or ""
        ),
        "source_stage1_6_scoreboard_json": str(stage1_6_scoreboard_json or ""),
        "runtime_blocker_next_subqueue_input_state": next_subqueue_input_state,
        "stage6_fact_package_root": str(stage6_root),
        "stage6_fact_package_json": str(stage6_root / "stage6-fact-package-v1.json"),
        "stage6_dispatch_root": str(dispatch_root),
        "stage6_dispatch_json": str(dispatch_root / "stage6-review-action-dispatch-v1.json"),
        "stage6_dispatch_runner_root": str(dispatch_runner_root),
        "stage6_dispatch_runner_json": str(dispatch_runner_root / "stage6-review-action-dispatch-runner-v1.json"),
        "execute_dispatch": bool(execute_dispatch),
        "dispatch_max_groups": dispatch_max_groups,
        "project_ids": list(project_ids),
        "source_manifest_ids": {
            "stage6_fact_package": _manifest_id(stage6_result),
            "stage6_dispatch": _manifest_id(dispatch_result),
            "stage6_dispatch_runner": _manifest_id(dispatch_runner_result),
        },
        "runtime_blocker_next_subqueue_table": runtime_blocker_next_subqueue_table,
        "runtime_blocker_subqueue_controller_table": runtime_blocker_subqueue_controller_table,
        "runtime_blocker_controller_dispatch_table": runtime_blocker_controller_dispatch_table,
        "runtime_blocker_controller_dispatch_runner_root": str(controller_dispatch_runner_root),
        "runtime_blocker_controller_dispatch_runner_json": str(
            controller_dispatch_runner_root / "runtime-blocker-controller-dispatch-runner-v1.json"
        ),
        "runtime_blocker_controller_dispatch_runner": runtime_blocker_controller_dispatch_runner_result,
        "runtime_blocker_worker_followup_queue": runtime_blocker_worker_followup_queue,
        "operator_projection_status_table_json": str(out_dir / "stage6-review-loop-project-status-table.json"),
        "operator_projection_status_table": operator_projection_status_table,
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
            "dispatch_execution_enabled": bool(execute_dispatch),
            "dispatch_execution_is_internal_allowlisted": True,
            "runtime_blocker_dispatch_execution_enabled": bool(execute_runtime_blocker_dispatch),
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage6_review_cycle_runner_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED_OR_PARTIAL",
        "safe_to_execute": (
            _safe(runtime_blocker_controller_dispatch_runner_result)
            and not blocking_reasons
            and (
                standalone_runtime_blocker_queue_only
                or (
                    _safe(stage6_result)
                    and _safe(dispatch_result)
                    and (_safe(dispatch_runner_result) if dispatch_task_count > 0 else True)
                )
            )
        ),
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result)
    return result


def _summary(
    *,
    stage6_result: Mapping[str, Any],
    dispatch_result: Mapping[str, Any],
    dispatch_runner_result: Mapping[str, Any],
    dispatch_runner_skip_reason: str,
    blocking_reasons: list[str],
    execute_dispatch: bool,
    runtime_blocker_next_subqueue_table: Mapping[str, Any],
    runtime_blocker_subqueue_controller_table: Mapping[str, Any],
    runtime_blocker_controller_dispatch_table: Mapping[str, Any],
    runtime_blocker_controller_dispatch_runner_result: Mapping[str, Any],
    runtime_blocker_next_subqueue_input_state: str,
    bootstrap_source_kind: str,
    selected_handler_kind: str,
    bootstrap_registry_state: str,
    bootstrap_registry_path: str,
    bootstrap_registry_validation_errors: list[str],
    bootstrap_registry_validation_error_records: list[dict[str, Any]],
) -> dict[str, Any]:
    stage6_summary = _result_summary(stage6_result)
    dispatch_summary = _result_summary(dispatch_result)
    dispatch_runner_summary = _result_summary(dispatch_runner_result)
    dispatch_task_count = int(dispatch_summary.get("dispatch_task_count") or 0)
    standalone_mode = dispatch_runner_skip_reason == "standalone_runtime_blocker_queue_only"
    next_subqueue_summary = _result_summary(runtime_blocker_next_subqueue_table)
    controller_queue_summary = _result_summary(runtime_blocker_subqueue_controller_table)
    controller_dispatch_summary = _result_summary(runtime_blocker_controller_dispatch_table)
    controller_dispatch_runner_summary = _result_summary(runtime_blocker_controller_dispatch_runner_result)
    return {
        "stage6_review_cycle_runner_state": (
            "STAGE6_REVIEW_CYCLE_READY" if not blocking_reasons else "STAGE6_REVIEW_CYCLE_PARTIAL_OR_BLOCKED"
        ),
        "stage6_review_cycle_bootstrap_registry_state": bootstrap_registry_state,
        "stage6_review_cycle_bootstrap_registry_path": bootstrap_registry_path,
        "stage6_review_cycle_bootstrap_registry_validation_errors": bootstrap_registry_validation_errors,
        "stage6_review_cycle_bootstrap_registry_validation_error_count": len(
            bootstrap_registry_validation_error_records
        ),
        "stage6_review_cycle_bootstrap_registry_validation_error_records": bootstrap_registry_validation_error_records,
        "stage6_review_cycle_bootstrap_source_kind": bootstrap_source_kind,
        "stage6_review_cycle_bootstrap_selected_handler_kind": selected_handler_kind,
        "stage6_review_cycle_input_mode": (
            "RUNTIME_BLOCKER_SUBQUEUE_ONLY"
            if standalone_mode
            else "BATCH_CLOSEOUT_STAGE6_DISPATCH"
        ),
        "execution_mode": "CONTROLLED_INTERNAL_DISPATCH_EXECUTION" if execute_dispatch else "DRY_RUN_DISPATCH_NOT_EXECUTED",
        "stage6_fact_package_safe": _safe(stage6_result),
        "stage6_dispatch_safe": _safe(dispatch_result),
        "stage6_dispatch_runner_safe": _safe(dispatch_runner_result) if dispatch_task_count > 0 else True,
        "stage6_dispatch_runner_skip_reason": dispatch_runner_skip_reason,
        "stage6_input_closeout_project_count": 0 if standalone_mode else int(stage6_summary.get("input_closeout_project_count") or 0),
        "stage6_project_fact_count": 0 if standalone_mode else int(stage6_summary.get("project_fact_count") or 0),
        "stage6_review_action_plan_count": 0 if standalone_mode else int(stage6_summary.get("review_action_plan_count") or 0),
        "stage6_review_action_family_counts": {} if standalone_mode else dict(stage6_summary.get("review_action_family_counts") or {}),
        "dispatch_task_count": dispatch_task_count,
        "manual_only_action_plan_count": int(dispatch_summary.get("manual_only_action_plan_count") or 0),
        "dispatch_task_type_counts": dict(dispatch_summary.get("dispatch_task_type_counts") or {}),
        "dispatch_runner_group_count": int(dispatch_runner_summary.get("dispatch_runner_group_count") or 0),
        "dispatch_runner_group_execution_state_counts": dict(
            dispatch_runner_summary.get("group_execution_state_counts") or {}
        ),
        "dispatch_runner_dry_run_ready_group_count": int(dispatch_runner_summary.get("dry_run_ready_group_count") or 0),
        "dispatch_runner_executed_success_group_count": int(
            dispatch_runner_summary.get("executed_success_group_count") or 0
        ),
        "dispatch_runner_executed_failed_group_count": int(
            dispatch_runner_summary.get("executed_failed_group_count") or 0
        ),
        "runtime_blocker_next_subqueue_input_state": runtime_blocker_next_subqueue_input_state,
        "runtime_blocker_next_subqueue_record_count": int(
            next_subqueue_summary.get("next_subqueue_record_count") or 0
        ),
        "runtime_blocker_next_subqueue_route_counts": dict(
            next_subqueue_summary.get("subqueue_route_counts") or {}
        ),
        "runtime_blocker_controller_queue_record_count": int(
            controller_queue_summary.get("controller_queue_record_count") or 0
        ),
        "runtime_blocker_controller_route_state_counts": dict(
            controller_queue_summary.get("controller_route_state_counts") or {}
        ),
        "runtime_blocker_controller_next_action_counts": dict(
            controller_queue_summary.get("controller_next_action_counts") or {}
        ),
        "runtime_blocker_controller_dispatch_worker_family_counts": dict(
            controller_queue_summary.get("dispatch_worker_family_counts") or {}
        ),
        "runtime_blocker_controller_automated_worker_dispatch_allowed_count": int(
            controller_queue_summary.get("automated_worker_dispatch_allowed_count") or 0
        ),
        "runtime_blocker_controller_dispatch_task_count": int(
            controller_dispatch_summary.get("controller_dispatch_task_count") or 0
        ),
        "runtime_blocker_controller_dispatch_readiness_state_counts": dict(
            controller_dispatch_summary.get("dispatch_readiness_state_counts") or {}
        ),
        "runtime_blocker_controller_dispatch_route_counts": dict(
            controller_dispatch_summary.get("dispatch_route_counts") or {}
        ),
        "runtime_blocker_controller_dispatch_ready_count": int(
            controller_dispatch_summary.get("ready_for_controlled_worker_dispatch_count") or 0
        ),
        "runtime_blocker_controller_dispatch_blocking_reason_counts": dict(
            controller_dispatch_summary.get("blocking_reason_counts") or {}
        ),
        "runtime_blocker_dispatch_runner_task_count": int(
            controller_dispatch_runner_summary.get("runtime_blocker_dispatch_runner_task_count") or 0
        ),
        "runtime_blocker_dispatch_runner_execution_state_counts": dict(
            controller_dispatch_runner_summary.get("execution_state_counts") or {}
        ),
        "runtime_blocker_dispatch_runner_readback_state_counts": dict(
            controller_dispatch_runner_summary.get("worker_readback_state_counts") or {}
        ),
        "runtime_blocker_dispatch_runner_closeout_state_counts": dict(
            controller_dispatch_runner_summary.get("worker_closeout_state_counts") or {}
        ),
        "runtime_blocker_dispatch_runner_dry_run_ready_count": int(
            controller_dispatch_runner_summary.get("dry_run_ready_count") or 0
        ),
        "runtime_blocker_dispatch_runner_existing_output_consumed_count": int(
            controller_dispatch_runner_summary.get("existing_output_consumed_count") or 0
        ),
        "runtime_blocker_dispatch_runner_executed_success_count": int(
            controller_dispatch_runner_summary.get("executed_success_count") or 0
        ),
        "runtime_blocker_dispatch_runner_executed_failed_count": int(
            controller_dispatch_runner_summary.get("executed_failed_count") or 0
        ),
        "runtime_blocker_dispatch_runner_ready_for_field_query_backfill_count": int(
            controller_dispatch_runner_summary.get("ready_for_field_query_backfill_count") or 0
        ),
        "runtime_blocker_dispatch_runner_followup_task_count": int(
            controller_dispatch_runner_summary.get("followup_task_count") or 0
        ),
        "runtime_blocker_dispatch_runner_followup_task_type_counts": dict(
            controller_dispatch_runner_summary.get("followup_task_type_counts") or {}
        ),
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "blocking_reasons": list(blocking_reasons),
        "forbidden_term_scan_state": "PENDING",
    }


def _operator_projection_status_table(
    *,
    summary: Mapping[str, Any],
    stage6_result: Mapping[str, Any],
    runtime_blocker_worker_followup_queue: Any,
    runtime_blocker_subqueue_controller_table: Mapping[str, Any],
    runtime_blocker_controller_dispatch_table: Mapping[str, Any],
    runtime_blocker_controller_dispatch_runner_result: Mapping[str, Any],
    source_stage6_review_loop_status_path: Path | None,
    source_gdcic_browser_readback_path: Path | None,
    source_design_survey_public_registry_readback_path: Path | None,
    source_stage1_6_scoreboard_path: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    source_release_field_query_path: Path | None = None,
    source_supplemental_release_field_query_path: Path | None = None,
    source_runtime_blocker_next_subqueue_path: Path | None = None,
) -> dict[str, Any]:
    followup_records = [
        dict(record)
        for record in _list(
            runtime_blocker_worker_followup_queue.get("records")
            if isinstance(runtime_blocker_worker_followup_queue, Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    controller_project_records = _controller_dispatch_project_status_records(
        controller_queue_table=runtime_blocker_subqueue_controller_table,
        controller_dispatch_table=runtime_blocker_controller_dispatch_table,
        controller_dispatch_runner_result=runtime_blocker_controller_dispatch_runner_result,
    )
    source_status_records = _status_projection_records_from_status_table(source_stage6_review_loop_status_path)
    stage6_fact_package_records = _stage6_fact_package_projection_records(stage6_result)
    merged_controller_projection_records = _merge_projection_records(
        controller_project_records,
        source_status_records,
    )
    merged_stage6_projection_records = _merge_projection_records(
        merged_controller_projection_records,
        stage6_fact_package_records,
    )
    bootstrap_registry_project_records = _bootstrap_registry_projection_status_records(summary)
    followup_project_records = _followup_project_status_records(followup_records)
    followup_project_count = len(
        {
            str(record.get("project_id") or "").strip()
            for record in followup_records
            if str(record.get("project_id") or "").strip()
        }
    )
    if bootstrap_registry_project_records:
        project_records = bootstrap_registry_project_records
        operator_projection_source = "stage6_review_cycle_bootstrap_registry_blocker"
    elif followup_records:
        project_records = _merge_projection_records(
            followup_project_records,
            merged_stage6_projection_records,
        )
        operator_projection_source = "stage6_review_cycle_runtime_blocker_worker_followup_queue"
    elif controller_project_records:
        project_records = merged_stage6_projection_records
        operator_projection_source = "stage6_review_cycle_runtime_blocker_controller_queue"
    else:
        project_records = _merge_projection_records(source_status_records, stage6_fact_package_records)
        if source_status_records:
            operator_projection_source = "stage6_review_cycle_source_status_projection"
        elif stage6_fact_package_records:
            operator_projection_source = "stage6_review_cycle_stage6_fact_package_projection"
        else:
            project_records = []
            operator_projection_source = "stage6_review_cycle_runtime_blocker_controller_queue"
    gdcic_projection_by_project = _gdcic_readback_projection_by_project(source_gdcic_browser_readback_path)
    if gdcic_projection_by_project:
        project_records = _merge_gdcic_readback_projection(
            project_records,
            gdcic_projection_by_project,
        )
    design_registry_projection_by_project = _design_survey_public_registry_readback_projection_by_project(
        source_design_survey_public_registry_readback_path
    )
    if design_registry_projection_by_project:
        project_records = _merge_design_survey_public_registry_readback_projection(
            project_records,
            design_registry_projection_by_project,
        )
    scoreboard_alternative_route_by_project = _stage1_6_scoreboard_gdcic_alternative_route_projection_by_project(
        source_stage1_6_scoreboard_path
    )
    if scoreboard_alternative_route_by_project:
        project_records = _merge_stage1_6_scoreboard_gdcic_alternative_route_projection(
            project_records,
            scoreboard_alternative_route_by_project,
        )
    continuation_input_refs = build_stage6_review_cycle_continuation_input_refs(
        output_root=output_root,
        release_field_query_json=source_release_field_query_path,
        supplemental_release_field_query_json=source_supplemental_release_field_query_path,
        runtime_blocker_next_subqueue_json=source_runtime_blocker_next_subqueue_path,
        stage6_review_loop_status_json=source_stage6_review_loop_status_path,
        gdcic_browser_readback_json=source_gdcic_browser_readback_path,
        stage1_6_scoreboard_json=source_stage1_6_scoreboard_path,
    )
    projection_summary = {
        **dict(summary),
        "operator_projection_source": operator_projection_source,
        "continuation_input_refs": continuation_input_refs,
        "project_status_record_count": len(project_records),
        "gdcic_browser_authorized_readback_project_count": len(gdcic_projection_by_project),
        "gdcic_browser_authorized_readback_state_counts": _counts(
            record.get("gdcic_browser_authorized_readback_state")
            for record in gdcic_projection_by_project.values()
        ),
        "gdcic_browser_authorized_session_input_state_counts": _counts(
            record.get("gdcic_browser_authorized_session_input_state")
            for record in gdcic_projection_by_project.values()
        ),
        "gdcic_browser_target_real_readback_success_count": sum(
            int(record.get("gdcic_browser_target_real_readback_success_count") or 0)
            for record in gdcic_projection_by_project.values()
        ),
        "gdcic_authorization_alternative_public_route_project_count": len(
            scoreboard_alternative_route_by_project
        ),
        "gdcic_authorization_alternative_public_route_count": sum(
            int(record.get("gdcic_alternative_public_source_route_count") or 0)
            for record in scoreboard_alternative_route_by_project.values()
        ),
        "gdcic_authorization_alternative_public_route_target_type_counts": _sum_count_maps(
            record.get("gdcic_alternative_public_source_route_target_type_counts")
            for record in scoreboard_alternative_route_by_project.values()
        ),
        "gdcic_authorization_readiness_state_counts_from_scoreboard": _counts(
            record.get("gdcic_authorization_readiness_state")
            for record in scoreboard_alternative_route_by_project.values()
        ),
        "stage4_gdcic_project_code_route_policy_counts_from_scoreboard": _counts(
            record.get("stage4_gdcic_project_code_route_policy")
            for record in scoreboard_alternative_route_by_project.values()
        ),
        "stage4_gdcic_route_blocked_by_policy_project_count_from_scoreboard": sum(
            1
            for record in scoreboard_alternative_route_by_project.values()
            if record.get("stage4_public_identifier_refs")
            and not bool(record.get("stage4_gdcic_project_code_route_allowed"))
        ),
        "stage4_public_identifier_source_counts_from_scoreboard": _counts(
            ref.get("source")
            for record in scoreboard_alternative_route_by_project.values()
            for ref in _list(record.get("stage4_public_identifier_refs"))
            if isinstance(ref, Mapping)
        ),
        "stage4_ygp_backfill_bridge_projection_state_counts_from_scoreboard": _counts(
            record.get("stage4_ygp_backfill_bridge_projection_state")
            for record in scoreboard_alternative_route_by_project.values()
            if str(record.get("stage4_ygp_backfill_bridge_projection_state") or "").strip()
        ),
        "stage4_ygp_backfill_bridge_ready_project_count_from_scoreboard": sum(
            1
            for record in scoreboard_alternative_route_by_project.values()
            if record.get("stage4_ygp_backfill_bridge_projection_state")
            in {
                "YGP_STAGE4_BACKFILL_READY_FOR_STAGE4_BRIDGE",
                "YGP_STAGE4_RELEASE_ADAPTER_TASK_READY",
            }
        ),
        "stage6_official_readback_internal_review_state_counts_from_scoreboard": _counts(
            record.get("stage6_official_readback_internal_review_state")
            for record in scoreboard_alternative_route_by_project.values()
            if str(record.get("stage6_official_readback_internal_review_state") or "").strip()
        ),
        "stage5_operational_review_bucket_counts_from_scoreboard": _counts(
            record.get("stage5_operational_review_bucket")
            for record in scoreboard_alternative_route_by_project.values()
            if str(record.get("stage5_operational_review_bucket") or "").strip()
        ),
        "stage5_operational_primary_track_counts_from_scoreboard": _counts(
            record.get("stage5_operational_primary_track")
            for record in scoreboard_alternative_route_by_project.values()
            if str(record.get("stage5_operational_primary_track") or "").strip()
        ),
        "p13b_public_source_readback_state_counts_from_scoreboard": _counts(
            record.get("p13b_public_source_readback_state")
            for record in scoreboard_alternative_route_by_project.values()
            if str(record.get("p13b_public_source_readback_state") or "").strip()
        ),
        "p13b_local_authority_resolution_state_counts_from_scoreboard": _sum_count_maps(
            record.get("p13b_local_authority_resolution_state_counts")
            for record in scoreboard_alternative_route_by_project.values()
        ),
        "p13b_local_authority_executed_readback_state_counts_from_scoreboard": _sum_count_maps(
            record.get("p13b_local_authority_executed_readback_state_counts")
            for record in scoreboard_alternative_route_by_project.values()
        ),
        "design_survey_public_registry_readback_project_count": len(
            design_registry_projection_by_project
        ),
        "design_survey_public_registry_readback_state_counts": _counts(
            record.get("design_survey_public_registry_readback_state")
            for record in design_registry_projection_by_project.values()
        ),
        "design_survey_public_registry_verification_result_counts": _counts(
            record.get("design_survey_public_registry_verification_result")
            for record in design_registry_projection_by_project.values()
        ),
        "design_survey_public_registry_not_found_review_count": sum(
            1
            for record in design_registry_projection_by_project.values()
            if record.get("design_survey_public_registry_readback_state") == "NOT_FOUND"
        ),
        "limited_sellable_review_candidate_count": sum(
            1
            for record in project_records
            if record.get("limited_sellable_review_candidate_state") == "REVIEW_CANDIDATE"
        ),
        "limited_sellable_review_candidate_state_counts": _counts(
            record.get("limited_sellable_review_candidate_state") for record in project_records
        ),
        "strong_lead_candidate_state_counts": _counts(
            record.get("strong_lead_candidate_state") for record in project_records
        ),
        "commercialization_boundary_state_counts": _counts(
            record.get("commercialization_boundary_state") for record in project_records
        ),
        "runtime_blocker_worker_followup_count": len(followup_records),
        "runtime_blocker_worker_followup_project_count": followup_project_count,
        "runtime_blocker_worker_followup_entrypoint_counts": _counts(
            record.get("formal_entrypoint_id") for record in followup_records
        ),
        "runtime_blocker_worker_followup_task_type_counts": _counts(
            record.get("followup_task_type") for record in followup_records
        ),
        "runtime_blocker_worker_followup_readiness_state_counts": _counts(
            record.get("followup_readiness_state") for record in followup_records
        ),
        "runtime_blocker_worker_followup_next_action_counts": _counts(
            record.get("next_action") for record in followup_records
        ),
    }
    return {
        "summary": projection_summary,
        "continuation_input_refs": continuation_input_refs,
        "records": project_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _operator_projection_controller_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "stage5_operational_review_bucket_counts_from_scoreboard",
        "stage5_operational_primary_track_counts_from_scoreboard",
        "p13b_local_authority_resolution_state_counts_from_scoreboard",
        "p13b_public_source_readback_state_counts_from_scoreboard",
        "p13b_local_authority_executed_readback_state_counts_from_scoreboard",
        "stage4_ygp_backfill_bridge_projection_state_counts_from_scoreboard",
        "stage4_ygp_backfill_bridge_ready_project_count_from_scoreboard",
    )
    return {key: summary[key] for key in keys if key in summary}


def _stage5_calibration_projection_summary(records: list[Any]) -> dict[str, Any]:
    rows = [record for record in records if isinstance(record, Mapping)]
    return {
        "stage5_calibration_sample_count": sum(
            1 for record in rows if str(record.get("stage5_calibration_review_bucket") or "").strip()
        ),
        "stage5_calibration_truth_label_required_count": sum(
            1 for record in rows if bool(record.get("calibration_truth_label_required"))
        ),
        "stage5_calibration_review_bucket_counts": _counts(
            record.get("stage5_calibration_review_bucket") for record in rows
        ),
        "stage5_abcd_calibration_counts": _counts(
            record.get("stage5_abcd_calibration_bucket") for record in rows
        ),
        "stage5_calibration_evidence_strength_counts": _counts(
            record.get("stage5_calibration_evidence_strength") for record in rows
        ),
        "stage5_calibration_review_family_counts": _counts(
            record.get("stage5_calibration_review_family") for record in rows
        ),
        "stage5_calibration_suggested_action_counts": _counts(
            record.get("suggested_calibration_action") for record in rows
        ),
    }


def _gdcic_readback_projection_by_project(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    if not summary and isinstance(manifest.get("summary"), Mapping):
        summary = dict(manifest["summary"])
    task_records = [
        dict(record)
        for record in _list(manifest.get("browser_readback_task_records"))
        if isinstance(record, Mapping)
    ]
    readback_records = [
        dict(record)
        for record in _list(manifest.get("browser_readback_records"))
        if isinstance(record, Mapping)
    ]
    project_ids = _dedupe(
        [
            *[record.get("project_id") for record in task_records],
            *[record.get("project_id") for record in readback_records],
        ]
    )
    overall_state = str(summary.get("gdcic_authorized_session_overall_state") or "")
    session_input_state = str(
        summary.get("authorized_session_input_state")
        or manifest.get("authorized_session_input_state")
        or ""
    )
    session_ready = bool(summary.get("authorized_session_input_ready"))
    real_not_faked = bool(summary.get("real_readback_success_not_faked", True))
    proof_state = str(
        summary.get("real_readback_success_proof_state")
        or "NO_REAL_AUTHORIZED_READBACK_SUCCESS"
    )
    summary_operator_next_actions = _dedupe(
        [
            summary.get("authorization_blocker_operator_next_action"),
            *[
                action
                for action, count in (
                    summary.get("operator_next_action_counts", {}).items()
                    if isinstance(summary.get("operator_next_action_counts"), Mapping)
                    else []
                )
                if int(count or 0) > 0
            ],
        ]
    )
    if not summary_operator_next_actions and not session_ready:
        summary_operator_next_actions = ["provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"]
    out: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        project_tasks = [record for record in task_records if str(record.get("project_id") or "").strip() == project_id]
        project_records = [record for record in readback_records if str(record.get("project_id") or "").strip() == project_id]
        ready_count = sum(
            1
            for record in project_records
            if str(record.get("readback_state") or "") == "BROWSER_AUTHORIZED_READBACK_READY"
        )
        out[project_id] = {
            "project_id": project_id,
            "gdcic_browser_authorized_readback_state": overall_state or "UNKNOWN_REVIEW_REQUIRED",
            "gdcic_browser_authorized_readback_json": str(path),
            "gdcic_browser_readback_task_count": len(project_tasks),
            "gdcic_browser_readback_record_count": len(project_records),
            "gdcic_browser_readback_adapter_result_state_counts": _counts(
                record.get("adapter_result_state") for record in project_records
            ),
            "gdcic_browser_authorization_readiness_state_counts": _counts(
                record.get("authorization_readiness_state") for record in project_records
            ),
            "gdcic_browser_authorized_session_input_state": session_input_state,
            "gdcic_browser_authorized_session_input_ready": session_ready,
            "gdcic_browser_target_real_readback_success_count": ready_count,
            "gdcic_browser_real_readback_success_not_faked": real_not_faked,
            "gdcic_browser_real_readback_success_proof_state": (
                "PROVEN_BY_BROWSER_AUTHORIZED_READBACK_READY_RECORDS"
                if ready_count
                else proof_state
            ),
            "gdcic_browser_operator_next_actions": _dedupe(
                [
                    *summary_operator_next_actions,
                    *[
                        action
                        for record in project_records
                        for action in _list(record.get("operator_next_actions"))
                    ],
                ]
            ),
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
    return out


def _merge_gdcic_readback_projection(
    project_records: list[dict[str, Any]],
    gdcic_projection_by_project: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(record) for record in project_records]
    by_project_id = {
        str(record.get("project_id") or "").strip(): record
        for record in out
        if str(record.get("project_id") or "").strip()
    }
    for project_id, projection in gdcic_projection_by_project.items():
        if project_id in by_project_id:
            target = by_project_id[project_id]
            target.update({key: value for key, value in projection.items() if key != "project_id"})
            refs = _dedupe(
                [
                    *_list(target.get("input_artifact_refs")),
                    projection.get("gdcic_browser_authorized_readback_json"),
                ]
            )
            if refs:
                target["input_artifact_refs"] = refs
        else:
            out.append(dict(projection))
    return out


def _design_survey_public_registry_readback_projection_by_project(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else {}
    table = (
        manifest.get("public_registry_readback_table")
        if isinstance(manifest.get("public_registry_readback_table"), Mapping)
        else {}
    )
    records = [dict(record) for record in _list(table.get("records")) if isinstance(record, Mapping)]
    out: dict[str, dict[str, Any]] = {}
    for project_id in _dedupe(record.get("project_id") for record in records):
        project_records = [
            record for record in records if str(record.get("project_id") or "").strip() == project_id
        ]
        readback_state_counts = _counts(record.get("readback_state") for record in project_records)
        verification_counts = _counts(record.get("verification_result") for record in project_records)
        provider_counts = _counts(record.get("provider_result_state") for record in project_records)
        readback_state = _dominant_count_key(readback_state_counts)
        verification_result = _dominant_count_key(verification_counts)
        out[project_id] = {
            "project_id": project_id,
            "design_survey_public_registry_readback_json": str(path),
            "design_survey_public_registry_readback_record_count": len(project_records),
            "design_survey_public_registry_provider_result_state_counts": provider_counts,
            "design_survey_public_registry_readback_state_counts": readback_state_counts,
            "design_survey_public_registry_verification_result_counts": verification_counts,
            "design_survey_public_registry_provider_result_state": _dominant_count_key(provider_counts),
            "design_survey_public_registry_readback_state": readback_state,
            "design_survey_public_registry_verification_result": verification_result,
            "design_survey_public_registry_stage6_review_bucket": (
                "DESIGN_SURVEY_PUBLIC_REGISTRY_MATCHED_REVIEW"
                if verification_result == "MATCHED" or readback_state == "MATCHED"
                else "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW"
                if readback_state == "NOT_FOUND"
                else "DESIGN_SURVEY_PUBLIC_REGISTRY_BLOCKED_REVIEW"
            ),
            "design_survey_public_registry_query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
    return out


def _merge_design_survey_public_registry_readback_projection(
    project_records: list[dict[str, Any]],
    design_registry_projection_by_project: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(record) for record in project_records]
    by_project_id = {
        str(record.get("project_id") or "").strip(): record
        for record in out
        if str(record.get("project_id") or "").strip()
    }
    for project_id, projection in design_registry_projection_by_project.items():
        if project_id in by_project_id:
            target = by_project_id[project_id]
            target.update({key: value for key, value in projection.items() if key != "project_id"})
            refs = _dedupe(
                [
                    *_list(target.get("input_artifact_refs")),
                    projection.get("design_survey_public_registry_readback_json"),
                ]
            )
            if refs:
                target["input_artifact_refs"] = refs
        else:
            out.append(dict(projection))
    return out


def _stage1_6_scoreboard_gdcic_alternative_route_projection_by_project(
    path: Path | None,
) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scoreboard = payload.get("scoreboard") if isinstance(payload.get("scoreboard"), Mapping) else {}
    gdcic_status = (
        scoreboard.get("gdcic_authorized_readback_status")
        if isinstance(scoreboard.get("gdcic_authorized_readback_status"), Mapping)
        else {}
    )
    project_rows = [
        dict(record)
        for record in _list(payload.get("project_rows"))
        if isinstance(record, Mapping) and str(record.get("project_id") or "").strip()
    ]
    out: dict[str, dict[str, Any]] = {}
    for row in project_rows:
        project_id = str(row.get("project_id") or "").strip()
        route_count = _scoreboard_gdcic_alternative_route_count_for_row(row)
        target_type_counts = _scoreboard_gdcic_alternative_route_target_type_counts_for_row(row)
        if route_count <= 0 and not target_type_counts:
            continue
        auth_state = str(gdcic_status.get("authorization_readiness_state") or "")
        out[project_id] = {
            "project_id": project_id,
            "stage1_6_scoreboard_json": str(path),
            "stage5_operational_primary_track": str(row.get("stage5_operational_primary_track") or ""),
            "stage5_operational_review_bucket": str(row.get("stage5_operational_review_bucket") or ""),
            "p13b_public_source_readback_state": str(row.get("p13b_public_source_readback_state") or ""),
            "p13b_local_authority_source_task_count": int(
                row.get("p13b_local_authority_source_task_count") or 0
            ),
            "p13b_local_authority_source_readback_count": int(
                row.get("p13b_local_authority_source_readback_count") or 0
            ),
            "p13b_local_authority_executed_readback_state_counts": dict(
                row.get("p13b_local_authority_executed_readback_state_counts") or {}
            ),
            "p13b_local_authority_resolution_state_counts": dict(
                row.get("p13b_local_authority_resolution_state_counts") or {}
            ),
            "p13b_local_authority_source_url_resolution_state_counts": dict(
                row.get("p13b_local_authority_source_url_resolution_state_counts") or {}
            ),
            "limited_sellable_review_candidate_state": str(
                row.get("limited_sellable_review_candidate_state") or ""
            ),
            "p13b_ygp_original_readback_state": str(row.get("p13b_ygp_original_readback_state") or ""),
            "p13b_ygp_stage4_backfill_ready_count": int(
                row.get("p13b_ygp_stage4_backfill_ready_count") or 0
            ),
            "p13b_ygp_stage4_release_adapter_task_count": int(
                row.get("p13b_ygp_stage4_release_adapter_task_count") or 0
            ),
            "stage4_ygp_backfill_bridge_projection_state": _scoreboard_ygp_stage4_bridge_projection_state(row),
            "stage6_official_readback_internal_review_state": _scoreboard_official_readback_internal_review_state(row),
            "stage6_official_readback_internal_next_action": _scoreboard_official_readback_internal_next_action(row),
            "stage6_official_readback_customer_visible_allowed": False,
            "stage6_official_readback_query_miss_is_not_clearance": True,
            "stage4_public_identifier_backfill_source": str(
                row.get("stage4_public_identifier_backfill_source") or ""
            ),
            "stage4_gdcic_project_code_route_allowed": bool(
                row.get("stage4_gdcic_project_code_route_allowed")
            ),
            "stage4_gdcic_project_code_route_policy": str(
                row.get("stage4_gdcic_project_code_route_policy") or ""
            ),
            "stage4_gdcic_project_code_route_guardrail": _scoreboard_gdcic_route_guardrail(row),
            "stage4_public_identifier_refs": _scoreboard_public_identifier_refs(row),
            "gdcic_authorization_readiness_state": auth_state,
            "gdcic_authorized_session_input_ready": bool(
                gdcic_status.get("authorized_session_input_ready")
            ),
            "gdcic_target_real_readback_success_count": int(
                gdcic_status.get("target_real_readback_success_count") or 0
            ),
            "gdcic_real_readback_success_proof_state": str(
                gdcic_status.get("real_readback_success_proof_state")
                or "NO_REAL_AUTHORIZED_READBACK_SUCCESS"
            ),
            "gdcic_authorization_blocker_is_not_terminal_if_alternative_public_sources_exist": True,
            "gdcic_alternative_public_source_route_count": route_count,
            "gdcic_alternative_public_source_route_target_type_counts": target_type_counts,
            "gdcic_alternative_public_source_route_next_action": (
                "continue_alternative_public_source_release_evidence_readback_chain"
            ),
            "gdcic_alternative_public_source_route_customer_visible_allowed": False,
            "gdcic_alternative_public_source_route_query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
    return out


def _scoreboard_ygp_stage4_bridge_projection_state(row: Mapping[str, Any]) -> str:
    if _scoreboard_int(row.get("p13b_ygp_stage4_release_adapter_task_count")) > 0:
        return "YGP_STAGE4_RELEASE_ADAPTER_TASK_READY"
    if _scoreboard_int(row.get("p13b_ygp_stage4_backfill_ready_count")) > 0:
        return "YGP_STAGE4_BACKFILL_READY_FOR_STAGE4_BRIDGE"
    if str(row.get("p13b_ygp_original_readback_state") or "").upper() == "YGP_READBACK_READY":
        return "YGP_READBACK_READY_NEEDS_STAGE4_BRIDGE_TASK"
    return ""


def _scoreboard_official_readback_internal_review_state(row: Mapping[str, Any]) -> str:
    if str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE":
        return "LIMITED_SELLABLE_INTERNAL_REVIEW_CANDIDATE"
    if str(row.get("stage5_operational_primary_track") or "") == "official_readback_ready":
        bridge_state = _scoreboard_ygp_stage4_bridge_projection_state(row)
        if bridge_state:
            return "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_INTERNAL_REVIEW"
        return "OFFICIAL_READBACK_READY_NEEDS_STAGE4_BRIDGE_INPUT"
    if str(row.get("p13b_ygp_original_readback_state") or "").upper() == "YGP_BLOCKED":
        return "YGP_READBACK_BLOCKED_INTERNAL_RETRY_OR_LOCAL_AUTHORITY_REVIEW"
    return ""


def _scoreboard_official_readback_internal_next_action(row: Mapping[str, Any]) -> str:
    state = _scoreboard_official_readback_internal_review_state(row)
    if state == "LIMITED_SELLABLE_INTERNAL_REVIEW_CANDIDATE":
        return "keep_internal_review_candidate_until_approval_audit_and_customer_delivery_gate"
    if state == "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_INTERNAL_REVIEW":
        return "feed_public_identifier_to_release_evidence_adapter_before_limited_review"
    if state == "OFFICIAL_READBACK_READY_NEEDS_STAGE4_BRIDGE_INPUT":
        return "build_stage4_bridge_task_from_official_readback_context"
    if state == "YGP_READBACK_BLOCKED_INTERNAL_RETRY_OR_LOCAL_AUTHORITY_REVIEW":
        return "retry_ygp_readback_or_route_to_project_local_authority_without_clearance_claim"
    return ""


def _scoreboard_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _scoreboard_gdcic_alternative_route_count_for_row(row: Mapping[str, Any]) -> int:
    count = 0
    count += int(row.get("p13b_bid_show_original_notice_url_count") or 0)
    count += int(row.get("p13b_local_authority_source_task_count") or 0)
    count += int(row.get("p13b_ygp_stage4_release_adapter_task_count") or 0) or int(
        row.get("p13b_ygp_stage4_backfill_ready_count") or 0
    )
    if str(row.get("p13b_original_notice_readback_state") or "").strip():
        count += 1
    if int(row.get("design_survey_public_registry_readback_record_count") or 0):
        count += 1
    return count


def _scoreboard_gdcic_alternative_route_target_type_counts_for_row(
    row: Mapping[str, Any],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    _add_count(counts, "data_ggzy_bid_show", int(row.get("p13b_bid_show_original_notice_url_count") or 0))
    _add_count(
        counts,
        "local_authority_public_source",
        int(row.get("p13b_local_authority_source_task_count") or 0),
    )
    _add_count(
        counts,
        "ygp_original_readback",
        int(row.get("p13b_ygp_stage4_release_adapter_task_count") or 0)
        or int(row.get("p13b_ygp_stage4_backfill_ready_count") or 0),
    )
    if str(row.get("p13b_original_notice_readback_state") or "").strip():
        _add_count(counts, "original_notice_readback", 1)
    if int(row.get("design_survey_public_registry_readback_record_count") or 0):
        _add_count(counts, "design_survey_public_registry", 1)
    return counts


def _scoreboard_public_identifier_refs(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if int(row.get("p13b_bid_show_original_notice_url_count") or 0):
        refs.append(
            {
                "source": "DATA_GGZY_BID_SHOW_ORIGINAL_URL",
                "count": int(row.get("p13b_bid_show_original_notice_url_count") or 0),
                "target": "P13B_OR_STAGE4_BRIDGE_ONLY",
                "gdcic_project_code_route_allowed": False,
            }
        )
    if int(row.get("p13b_bid_show_responsible_person_present_count") or 0):
        refs.append(
            {
                "source": "DATA_GGZY_BID_SHOW_RESPONSIBLE_PERSON",
                "count": int(row.get("p13b_bid_show_responsible_person_present_count") or 0),
                "target": "P13B_OR_STAGE4_BRIDGE_ONLY",
                "gdcic_project_code_route_allowed": False,
            }
        )
    for source, field in (
        ("YGP_PROJECT_CODE", "p13b_ygp_project_code_variants"),
        ("YGP_BIZ_CODE", "p13b_ygp_biz_code_variants"),
        ("YGP_SITE_CODE", "p13b_ygp_site_code_variants"),
        ("YGP_NOTICE_ID", "p13b_ygp_notice_id_variants"),
        ("P13B_OVERLAP_YGP_PROJECT_CODE", "p13b_overlap_ygp_project_code_variants"),
        ("P13B_OVERLAP_YGP_BIZ_CODE", "p13b_overlap_ygp_biz_code_variants"),
        ("P13B_OVERLAP_YGP_SITE_CODE", "p13b_overlap_ygp_site_code_variants"),
        ("P13B_OVERLAP_YGP_NOTICE_ID", "p13b_overlap_ygp_notice_id_variants"),
    ):
        values = _dedupe(_list(row.get(field)))
        if values:
            refs.append(
                {
                    "source": source,
                    "values": values,
                    "target": "P13B_OR_STAGE4_BRIDGE_ONLY",
                    "gdcic_project_code_route_allowed": False,
                }
            )
    return refs


def _scoreboard_gdcic_route_guardrail(row: Mapping[str, Any]) -> str:
    if bool(row.get("stage4_gdcic_project_code_route_allowed")):
        return "ONLY_EXPLICIT_PROVINCIAL_OR_URL_PROJECT_CODE_ALLOWED"
    policy = str(row.get("stage4_gdcic_project_code_route_policy") or "")
    if policy:
        return policy
    if _scoreboard_public_identifier_refs(row):
        return "PUBLIC_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE_ROUTE"
    return "NO_GDCIC_PROJECT_CODE_ROUTE"


def _merge_stage1_6_scoreboard_gdcic_alternative_route_projection(
    project_records: list[dict[str, Any]],
    alternative_route_by_project: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(record) for record in project_records]
    by_project_id = {
        str(record.get("project_id") or "").strip(): record
        for record in out
        if str(record.get("project_id") or "").strip()
    }
    for project_id, projection in alternative_route_by_project.items():
        if project_id in by_project_id:
            target = by_project_id[project_id]
            target.update({key: value for key, value in projection.items() if key != "project_id"})
            refs = _dedupe(
                [
                    *_list(target.get("input_artifact_refs")),
                    projection.get("stage1_6_scoreboard_json"),
                ]
            )
            if refs:
                target["input_artifact_refs"] = refs
        else:
            out.append(dict(projection))
    return out


def _sum_count_maps(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values or []:
        if not isinstance(value, Mapping):
            continue
        for key, count in value.items():
            _add_count(counts, str(key), int(count or 0))
    return counts


def _add_count(counts: dict[str, int], key: str, amount: int) -> None:
    if not key or amount <= 0:
        return
    counts[key] = counts.get(key, 0) + amount


def _dominant_count_key(counts: Mapping[str, int]) -> str:
    ranked = sorted(
        ((str(key), int(value or 0)) for key, value in counts.items() if str(key or "").strip()),
        key=lambda item: (-item[1], item[0]),
    )
    return ranked[0][0] if ranked else ""


def _status_projection_records_from_status_table(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("records") if isinstance(payload, Mapping) else []
    if not isinstance(records, list):
        return []
    return [dict(record) for record in records if isinstance(record, Mapping)]


def _stage6_fact_package_projection_records(stage6_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = stage6_result.get("manifest") if isinstance(stage6_result.get("manifest"), Mapping) else {}
    source_batch_closeout_json = str(manifest.get("source_batch_closeout_json") or "").strip()
    intake_rows = [
        dict(record)
        for record in _list(
            manifest.get("stage6_intake_table", {}).get("records")
            if isinstance(manifest.get("stage6_intake_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping)
    ]
    review_queue_by_project = {
        str(record.get("project_id") or "").strip(): dict(record)
        for record in _list(
            manifest.get("review_queue_table", {}).get("records")
            if isinstance(manifest.get("review_queue_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping) and str(record.get("project_id") or "").strip()
    }
    review_plan_by_project = {
        str(record.get("project_id") or "").strip(): dict(record)
        for record in _list(
            manifest.get("stage6_review_action_plan_table", {}).get("records")
            if isinstance(manifest.get("stage6_review_action_plan_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping) and str(record.get("project_id") or "").strip()
    }
    report_by_project = {
        str(record.get("project_id") or "").strip(): dict(record)
        for record in _list(
            manifest.get("report_record_table", {}).get("records")
            if isinstance(manifest.get("report_record_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping) and str(record.get("project_id") or "").strip()
    }
    pack_by_project = {
        str(record.get("project_id") or "").strip(): dict(record)
        for record in _list(
            manifest.get("internal_evidence_pack_table", {}).get("records")
            if isinstance(manifest.get("internal_evidence_pack_table"), Mapping)
            else []
        )
        if isinstance(record, Mapping) and str(record.get("project_id") or "").strip()
    }
    out: list[dict[str, Any]] = []
    for intake in intake_rows:
        project_id = str(intake.get("project_id") or "").strip()
        if not project_id or not bool(intake.get("stage6_ready")):
            continue
        review_queue = review_queue_by_project.get(project_id, {})
        review_plan = review_plan_by_project.get(project_id, {})
        report_record = report_by_project.get(project_id, {})
        pack_record = pack_by_project.get(project_id, {})
        blocker = (
            dict(review_plan.get("runtime_blocker_ledger_record"))
            if isinstance(review_plan.get("runtime_blocker_ledger_record"), Mapping)
            and review_plan.get("runtime_blocker_ledger_record")
            else {}
        )
        blocker_rows = [blocker] if blocker else []
        stage7_allowed = bool(intake.get("stage7_commercial_input_allowed"))
        out.append(
            {
                "project_id": project_id,
                "project_name": str(intake.get("project_name") or ""),
                "assigned_owner": str(review_plan.get("assigned_owner") or ""),
                "assigned_owner_role": str(review_plan.get("assigned_owner_role") or ""),
                "owner_assignment_source_ref": str(review_plan.get("owner_assignment_source_ref") or ""),
                "dispatch_task_type": "",
                "loop_terminal_state": (
                    "RESULT_EXECUTED_NO_NEXT_DISPATCH"
                    if stage7_allowed
                    else "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH"
                ),
                "next_recommended_action": _first_text(
                    review_queue.get("recommended_next_action"),
                    intake.get("recommended_next_action"),
                    "manual_review",
                ),
                "stage6_fact_package_state": str(intake.get("stage6_fact_package_state") or ""),
                "stage6_ready": bool(intake.get("stage6_ready")),
                "stage7_commercial_input_allowed": stage7_allowed,
                "evidence_grade": str(intake.get("evidence_grade") or ""),
                "next_cycle_dispatch_block_reason": _first_text(
                    *(review_queue.get("review_reasons") or []),
                    review_plan.get("dispatch_block_reason"),
                ),
                "runtime_blocker_ledger_records": blocker_rows,
                "runtime_blocker_ledger_state_counts": _counts(
                    row.get("blocker_state") for row in blocker_rows
                ),
                "runtime_blocker_ledger_layer_counts": _counts(
                    row.get("runtime_layer") for row in blocker_rows
                ),
                "closeout_precedence_marker_source_refs": (
                    [
                        {
                            "source_ref": "evidence_batch_closeout_json",
                            "artifact_ref": source_batch_closeout_json,
                        }
                    ]
                    if source_batch_closeout_json
                    else []
                ),
                "input_artifact_refs": [source_batch_closeout_json] if source_batch_closeout_json else [],
                "output_artifact_refs": _dedupe(
                    [
                        report_record.get("brief_path"),
                        report_record.get("evidence_pack_path"),
                        report_record.get("review_summary_path"),
                        report_record.get("review_summary_markdown_path"),
                        report_record.get("review_action_plan_path"),
                        pack_record.get("brief_path"),
                        pack_record.get("evidence_pack_path"),
                    ]
                ),
                "runtime_blocker_subqueue_routes": [],
                "runtime_blocker_subqueue_counts": {},
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return out


def _merge_projection_records(
    primary_records: list[dict[str, Any]],
    supplemental_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [dict(record) for record in primary_records]
    by_project_id = {
        str(record.get("project_id") or "").strip(): record
        for record in out
        if str(record.get("project_id") or "").strip()
    }
    for record in supplemental_records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id and project_id in by_project_id:
            existing = by_project_id[project_id]
            for key, value in record.items():
                if _should_merge_projection_value(
                    key=key,
                    existing_value=existing.get(key) if key in existing else None,
                    supplemental_value=value,
                    key_exists=key in existing,
                ):
                    existing[key] = value
            continue
        out.append(dict(record))
        if project_id:
            by_project_id[project_id] = out[-1]
    return out


def _should_merge_projection_value(
    *,
    key: str,
    existing_value: Any,
    supplemental_value: Any,
    key_exists: bool,
) -> bool:
    if not key_exists:
        return True
    if _is_empty_projection_value(existing_value) and not _is_empty_projection_value(supplemental_value):
        return True
    if (
        key.endswith("_count")
        and isinstance(existing_value, int)
        and not isinstance(existing_value, bool)
        and existing_value == 0
        and isinstance(supplemental_value, int)
        and not isinstance(supplemental_value, bool)
        and supplemental_value > 0
    ):
        return True
    return False


def _is_empty_projection_value(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, (list, dict, tuple, set)) and not value:
        return True
    return False


def _bootstrap_registry_projection_status_records(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    validation_records = [
        dict(record)
        for record in _list(summary.get("stage6_review_cycle_bootstrap_registry_validation_error_records"))
        if isinstance(record, Mapping)
    ]
    if not validation_records:
        return []
    registry_path = str(summary.get("stage6_review_cycle_bootstrap_registry_path") or "").strip()
    next_action = _first_text(
        *(record.get("operator_next_action") for record in validation_records),
        "fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
    )
    blocker_reason = _first_text(
        *(record.get("blocking_reason") for record in validation_records),
        "stage6_review_cycle_bootstrap_registry_schema_invalid",
    )
    blocker_rows = _bootstrap_registry_blocker_ledger_records(
        validation_records=validation_records,
        registry_path=registry_path,
    )
    return [
        {
            "project_id": "SYSTEM-STAGE6-REVIEW-CYCLE-BOOTSTRAP-REGISTRY",
            "project_name": "Stage6 review cycle bootstrap registry",
            "assigned_owner": "",
            "assigned_owner_role": "",
            "owner_assignment_source_ref": "",
            "dispatch_task_type": "",
            "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
            "next_recommended_action": next_action,
            "stage6_fact_package_state": "BOOTSTRAP_REGISTRY_BLOCKED",
            "stage6_ready": False,
            "stage7_commercial_input_allowed": False,
            "next_cycle_dispatch_block_reason": blocker_reason,
            "runtime_blocker_ledger_records": blocker_rows,
            "runtime_blocker_ledger_state_counts": _counts(
                record.get("blocker_state") for record in blocker_rows
            ),
            "runtime_blocker_ledger_layer_counts": _counts(
                record.get("runtime_layer") for record in blocker_rows
            ),
            "runtime_blocker_subqueue_routes": _runtime_blocker_subqueue_routes(blocker_rows),
            "runtime_blocker_worker_followup_records": [],
            "runtime_blocker_worker_followup_count": 0,
            "release_field_query_state": "",
            "release_field_query_task_count": 0,
            "release_field_query_adapter_result_state_counts": {},
            "release_field_query_downstream_abcd_grade_counts": {},
            "release_field_query_authorized_session_input_state_counts": {},
            "release_field_query_authorization_state_counts": {},
            "release_field_query_operator_next_actions": [],
            "release_field_query_source_hit_summaries": [],
            "release_field_query_source_hit_summary_labels": [],
            "input_artifact_refs": [registry_path] if registry_path else [],
            "output_artifact_refs": [],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        }
    ]


def _bootstrap_registry_blocker_ledger_records(
    *,
    validation_records: list[Mapping[str, Any]],
    registry_path: str,
) -> list[dict[str, Any]]:
    blocker_rows: list[dict[str, Any]] = []
    for index, record in enumerate(validation_records, start=1):
        source_index = record.get("source_index")
        source_index_text = "root" if source_index is None else str(source_index)
        operator_next_action = str(record.get("operator_next_action") or "")
        blocker_rows.append(
            {
                "blocker_ledger_id": f"BLK-STAGE6-CYCLE-BOOTSTRAP-REGISTRY-{index}",
                "ledger_scope": "stage6_review_cycle_bootstrap_registry",
                "project_id": "SYSTEM-STAGE6-REVIEW-CYCLE-BOOTSTRAP-REGISTRY",
                "project_name": "Stage6 review cycle bootstrap registry",
                "task_id": f"stage6-bootstrap-registry-{source_index_text}",
                "task_scope": "stage6_review_cycle_bootstrap_registry",
                "task_type": "stage6_review_cycle_bootstrap_registry_validation",
                "blocker_state": "STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_BLOCKED",
                "blocker_reason": str(record.get("blocking_reason") or ""),
                "runtime_layer": str(record.get("runtime_layer") or BOOTSTRAP_REGISTRY_RUNTIME_LAYER),
                "source_ledger_scopes": ["stage6_review_cycle_bootstrap_registry"],
                "source_runtime_layers": [str(record.get("runtime_layer") or BOOTSTRAP_REGISTRY_RUNTIME_LAYER)],
                "source_blocker_reasons": [str(record.get("error_code") or "")],
                "required_input": _dedupe(_list(record.get("required_input"))),
                "retry_policy": "manual_reopen_requires_registry_fix_or_schema_repair",
                "reopen_conditions": ["valid_bootstrap_registry_available_and_audited"],
                "operator_next_action": operator_next_action,
                "next_action": operator_next_action,
                "artifact_ref": registry_path or str(record.get("invalid_value") or ""),
                "source_index": source_index,
                "source_kind": str(record.get("source_kind") or ""),
                "field": str(record.get("field") or ""),
                "invalid_value": str(record.get("invalid_value") or ""),
                "error_code": str(record.get("error_code") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return blocker_rows


def _followup_project_status_records(followup_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in followup_records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            grouped.setdefault(project_id, []).append(record)
    out: list[dict[str, Any]] = []
    for project_id in sorted(grouped):
        records = grouped[project_id]
        first = records[0]
        out.append(
            {
                "project_id": project_id,
                "project_name": _first_text(*(record.get("project_name") for record in records)),
                "assigned_owner": _first_text(*(record.get("assigned_owner") for record in records)),
                "assigned_owner_role": _first_text(*(record.get("assigned_owner_role") for record in records)),
                "owner_assignment_source_ref": _first_text(
                    *(record.get("owner_assignment_source_ref") for record in records)
                ),
                "dispatch_task_type": "RUN_RELEASE_EVIDENCE_FIELD_QUERY",
                "loop_terminal_state": "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY",
                "next_recommended_action": _first_text(
                    *(record.get("next_action") for record in records),
                    "run_guangdong_local_field_query_probe_then_stage6_review_loop_backfill",
                ),
                "stage6_fact_package_state": "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY",
                "stage6_ready": True,
                "stage7_commercial_input_allowed": False,
                "next_cycle_dispatch_block_reason": "",
                "release_field_query_state": "",
                "release_field_query_result_json": "",
                "release_field_query_manifest_id": "",
                "release_field_query_task_count": 0,
                "release_field_query_adapter_result_state_counts": {},
                "release_field_query_downstream_abcd_grade_counts": {},
                "release_field_query_authorized_session_input_state_counts": {},
                "release_field_query_authorization_state_counts": {},
                "release_field_query_operator_next_actions": [],
                "release_field_query_source_hit_summaries": [],
                "release_field_query_source_hit_summary_labels": [],
                "runtime_blocker_worker_followup_records": [dict(record) for record in records],
                "runtime_blocker_worker_followup_count": len(records),
                "runtime_blocker_worker_followup_entrypoint_counts": _counts(
                    record.get("formal_entrypoint_id") for record in records
                ),
                "runtime_blocker_worker_followup_task_type_counts": _counts(
                    record.get("followup_task_type") for record in records
                ),
                "runtime_blocker_worker_followup_readiness_state_counts": _counts(
                    record.get("followup_readiness_state") for record in records
                ),
                "runtime_blocker_worker_followup_next_action_counts": _counts(
                    record.get("next_action") for record in records
                ),
                "input_artifact_refs": _dedupe(
                    ref
                    for record in records
                    for ref in [
                        record.get("release_evidence_adapter_plan_json"),
                        record.get("gdcic_browser_readback_json"),
                    ]
                ),
                "output_artifact_refs": _dedupe(
                    ref
                    for record in records
                    for ref in [record.get("output_root"), record.get("expected_output_artifact")]
                ),
                "source_runtime_blocker_dispatch_runner_task_id": str(
                    first.get("source_runtime_blocker_dispatch_runner_task_id") or ""
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
    return out


def _controller_dispatch_project_status_records(
    *,
    controller_queue_table: Mapping[str, Any],
    controller_dispatch_table: Mapping[str, Any],
    controller_dispatch_runner_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    queue_records = [
        dict(record)
        for record in _list(controller_queue_table.get("records") if isinstance(controller_queue_table, Mapping) else [])
        if isinstance(record, Mapping)
    ]
    dispatch_records = [
        dict(record)
        for record in _list(controller_dispatch_table.get("records") if isinstance(controller_dispatch_table, Mapping) else [])
        if isinstance(record, Mapping)
    ]
    runner_manifest = (
        controller_dispatch_runner_result.get("manifest")
        if isinstance(controller_dispatch_runner_result.get("manifest"), Mapping)
        else {}
    )
    runner_table = (
        runner_manifest.get("runtime_blocker_dispatch_runner_table")
        if isinstance(runner_manifest.get("runtime_blocker_dispatch_runner_table"), Mapping)
        else {}
    )
    runner_records = [
        dict(record)
        for record in _list(runner_table.get("records"))
        if isinstance(record, Mapping)
    ]
    queue_by_project: dict[str, list[dict[str, Any]]] = {}
    dispatch_by_project: dict[str, list[dict[str, Any]]] = {}
    runner_by_project: dict[str, list[dict[str, Any]]] = {}
    for record in queue_records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            queue_by_project.setdefault(project_id, []).append(record)
    for record in dispatch_records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            dispatch_by_project.setdefault(project_id, []).append(record)
    for record in runner_records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            runner_by_project.setdefault(project_id, []).append(record)
    out: list[dict[str, Any]] = []
    for project_id in sorted({*queue_by_project.keys(), *dispatch_by_project.keys(), *runner_by_project.keys()}):
        project_queue_records = queue_by_project.get(project_id, [])
        project_dispatch_records = dispatch_by_project.get(project_id, [])
        project_runner_records = runner_by_project.get(project_id, [])
        runtime_blocker_rows = _dedupe_controller_blocker_records(project_queue_records)
        loop_terminal_state = _controller_cycle_loop_terminal_state(project_runner_records)
        next_recommended_action = _controller_cycle_next_action(project_runner_records, project_queue_records)
        out.append(
            {
                "project_id": project_id,
                "project_name": _first_text(
                    *(record.get("project_name") for record in project_queue_records),
                    *(record.get("project_name") for record in project_runner_records),
                ),
                "assigned_owner": _first_text(
                    *(record.get("assigned_owner") for record in project_queue_records),
                    *(record.get("assigned_owner") for record in project_runner_records),
                ),
                "assigned_owner_role": _first_text(
                    *(record.get("assigned_owner_role") for record in project_queue_records),
                    *(record.get("assigned_owner_role") for record in project_runner_records),
                ),
                "owner_assignment_source_ref": _first_text(
                    *(record.get("owner_assignment_source_ref") for record in project_queue_records)
                ),
                "dispatch_task_type": _controller_cycle_dispatch_task_type(
                    project_dispatch_records=project_dispatch_records,
                    project_queue_records=project_queue_records,
                ),
                "loop_terminal_state": loop_terminal_state,
                "next_recommended_action": next_recommended_action,
                "stage6_fact_package_state": "RUNTIME_BLOCKER_CONTROLLER_QUEUE_READY",
                "stage6_ready": True,
                "stage7_commercial_input_allowed": False,
                "next_cycle_dispatch_block_reason": _first_text(
                    *(record.get("blocker_reason") for record in project_queue_records),
                    *(
                        reason
                        for record in project_dispatch_records
                        for reason in _list(record.get("dispatch_blocking_reasons"))
                    ),
                ),
                "runtime_blocker_ledger_records": runtime_blocker_rows,
                "runtime_blocker_ledger_state_counts": _counts(
                    record.get("blocker_state") for record in runtime_blocker_rows
                ),
                "runtime_blocker_ledger_layer_counts": _counts(
                    record.get("runtime_layer") for record in runtime_blocker_rows
                ),
                "runtime_blocker_subqueue_routes": _counts(
                    record.get("subqueue_route") for record in project_queue_records
                ).keys(),
                "runtime_blocker_subqueue_counts": _counts(
                    record.get("subqueue_route") for record in project_queue_records
                ),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        )
        out[-1]["runtime_blocker_subqueue_routes"] = list(out[-1]["runtime_blocker_subqueue_counts"].keys())
    return out


def _dedupe_controller_blocker_records(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        blocker_id = str(record.get("blocker_ledger_id") or "").strip()
        key = blocker_id or _fingerprint(record)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(record))
    return out


def _controller_cycle_loop_terminal_state(project_runner_records: list[Mapping[str, Any]]) -> str:
    if any(str(record.get("execution_state") or "") == "DRY_RUN_READY" for record in project_runner_records):
        return "WAITING_FOR_DISPATCH_EXECUTION"
    return "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH"


def _controller_cycle_next_action(
    project_runner_records: list[Mapping[str, Any]],
    project_queue_records: list[Mapping[str, Any]],
) -> str:
    if any(str(record.get("execution_state") or "") == "DRY_RUN_READY" for record in project_runner_records):
        return "run_controlled_dispatch_task_or_record_operator_skip"
    return _first_text(
        *(record.get("operator_next_action") for record in project_queue_records),
        *(record.get("next_action") for record in project_queue_records),
        "manual_review_or_new_source_override_required_before_retry",
    )


def _controller_cycle_dispatch_task_type(
    *,
    project_dispatch_records: list[Mapping[str, Any]],
    project_queue_records: list[Mapping[str, Any]],
) -> str:
    task_type = _first_text(*(record.get("dispatch_worker_family") for record in project_dispatch_records))
    if task_type == "browser_worker":
        return "RUN_RELEASE_EVIDENCE_FIELD_QUERY"
    if task_type == "retry_policy":
        queue_scope = _first_text(*(record.get("task_scope") for record in project_queue_records))
        if queue_scope == "p13b_follow_up":
            return "RUN_DATA_GGZY_COMPANY_HISTORY_OVERLAP_TRIAGE"
        if queue_scope == "original_readback":
            return "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW"
    return ""


def _finalize_and_write(out_dir: Path, result: dict[str, Any]) -> None:
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
    _write_json(
        out_dir / "stage6-review-cycle-runtime-blocker-next-subqueues.json",
        result["manifest"]["runtime_blocker_next_subqueue_table"],
    )
    _write_json(
        out_dir / "stage6-review-cycle-runtime-blocker-controller-queue.json",
        result["manifest"]["runtime_blocker_subqueue_controller_table"],
    )
    _write_json(
        out_dir / "stage6-review-cycle-runtime-blocker-controller-dispatch-tasks.json",
        result["manifest"]["runtime_blocker_controller_dispatch_table"],
    )
    _write_json(
        out_dir / "stage6-review-cycle-runtime-blocker-controller-dispatch-runner.json",
        result["manifest"]["runtime_blocker_controller_dispatch_runner"],
    )
    _write_json(
        out_dir / "stage6-review-cycle-runtime-blocker-worker-followup-queue.json",
        result["manifest"]["runtime_blocker_worker_followup_queue"],
    )
    _write_json(
        out_dir / "stage6-review-loop-project-status-table.json",
        result["manifest"]["operator_projection_status_table"],
    )
    _write_json(out_dir / "stage6-review-cycle-runner-v1.json", result)


def _result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result, Mapping) else {}
    return dict(summary) if isinstance(summary, Mapping) else {}


def _dispatch_task_count(dispatch_result: Mapping[str, Any]) -> int:
    return int(_result_summary(dispatch_result).get("dispatch_task_count") or 0)


def _bootstrap_source_path(
    source_kind: str,
    *,
    explicit_json: str | Path | None,
    explicit_root: str | Path | None,
) -> Path | None:
    if explicit_json:
        return Path(explicit_json)
    entry = _bootstrap_source_entry(source_kind)
    if explicit_root and str(entry.get("default_filename") or "").strip():
        return Path(explicit_root) / str(entry["default_filename"])
    return None


def _optional_json_path(
    *,
    explicit_json: str | Path | None,
    root: str | Path | None,
    default_filename: str,
) -> Path | None:
    if explicit_json:
        return Path(explicit_json)
    if root:
        return Path(root) / default_filename
    return None


def _runtime_blocker_next_subqueue_path(
    *,
    runtime_blocker_next_subqueue_json: str | Path | None,
    runtime_blocker_next_subqueue_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON",
        explicit_json=runtime_blocker_next_subqueue_json,
        explicit_root=runtime_blocker_next_subqueue_root,
    )


def _stage6_review_loop_path(
    *,
    stage6_review_loop_json: str | Path | None,
    stage6_review_loop_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "STAGE6_REVIEW_LOOP_JSON",
        explicit_json=stage6_review_loop_json,
        explicit_root=stage6_review_loop_root,
    )


def _stage6_review_loop_status_path(
    *,
    stage6_review_loop_status_json: str | Path | None,
    stage6_review_loop_status_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "STAGE6_REVIEW_LOOP_STATUS_JSON",
        explicit_json=stage6_review_loop_status_json,
        explicit_root=stage6_review_loop_status_root,
    )


def _release_field_query_path(
    *,
    release_field_query_json: str | Path | None,
    release_field_query_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "RELEASE_FIELD_QUERY_JSON",
        explicit_json=release_field_query_json,
        explicit_root=release_field_query_root,
    )


def _release_evidence_adapter_plan_path(
    *,
    release_evidence_adapter_plan_json: str | Path | None,
    release_evidence_adapter_plan_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "RELEASE_EVIDENCE_ADAPTER_PLAN_JSON",
        explicit_json=release_evidence_adapter_plan_json,
        explicit_root=release_evidence_adapter_plan_root,
    )


def _gdcic_browser_readback_path(
    *,
    gdcic_browser_readback_json: str | Path | None,
    gdcic_browser_readback_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "GDCIC_BROWSER_READBACK_JSON",
        explicit_json=gdcic_browser_readback_json,
        explicit_root=gdcic_browser_readback_root,
    )


def _derive_release_field_query_from_gdcic_readback(
    *,
    release_field_query_path: Path | None,
    release_evidence_adapter_plan_path: Path | None,
    gdcic_browser_readback_path: Path | None,
    output_root: Path,
    created_at: str,
) -> Path | None:
    if release_field_query_path is not None:
        return None
    if (
        release_evidence_adapter_plan_path is None
        or gdcic_browser_readback_path is None
        or not release_evidence_adapter_plan_path.exists()
        or not gdcic_browser_readback_path.exists()
    ):
        return None
    result = build_guangdong_local_field_query_probe(
        release_evidence_adapter_plan_json=release_evidence_adapter_plan_path,
        gdcic_browser_readback_json=gdcic_browser_readback_path,
        output_root=output_root,
        source_profile_ids=["GUANGDONG-GDCIC-HOME"],
        enable_live_public_query=True,
        max_live_tasks=None,
        http_getter=_no_live_gdcic_http_getter,
        created_at=created_at,
    )
    output_path = output_root / "guangdong-local-field-query-probe-v1.json"
    if result.get("safe_to_execute") and output_path.exists():
        return output_path
    return None


def _no_live_gdcic_http_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
        "text_probe": (
            "<script>top.window.location.href='http://210.76.80.152:8008/SSO/jrsso/auth'</script>"
            if "Indexht" in str(url)
            else "<table><tbody></tbody></table>"
        ),
    }


def _original_backtrace_continuation_path(
    *,
    original_backtrace_continuation_json: str | Path | None,
    original_backtrace_continuation_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "ORIGINAL_BACKTRACE_CONTINUATION_JSON",
        explicit_json=original_backtrace_continuation_json,
        explicit_root=original_backtrace_continuation_root,
    )


def _stage16_p13b_continuation_path(
    *,
    stage16_p13b_continuation_json: str | Path | None,
    stage16_p13b_continuation_root: str | Path | None,
) -> Path | None:
    return _bootstrap_source_path(
        "STAGE16_P13B_CONTINUATION_JSON",
        explicit_json=stage16_p13b_continuation_json,
        explicit_root=stage16_p13b_continuation_root,
    )


def _bootstrap_source_entry(source_kind: str) -> dict[str, Any]:
    for item in _bootstrap_source_registry():
        if str(item.get("source_kind") or "") == source_kind:
            return dict(item)
    return {}


def _resolve_stage6_loop_runner_artifact_candidate(
    *,
    candidate: Mapping[str, Any],
    source_path: Path,
    stage6_loop_output_root: Path,
    derived_output_path: Path,
) -> tuple[dict[str, Any], str, str, Path | None, Path | None, str]:
    source_kind = str(candidate.get("source_kind") or "")
    if not source_path.exists():
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage6_review_loop_json_missing_or_invalid",
            derived_output_path,
            None,
            source_kind,
        )
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage6_review_loop_json_missing_or_invalid",
            derived_output_path,
            None,
            source_kind,
        )
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    embedded_next_subqueue = (
        manifest.get("runtime_blocker_next_subqueue_table")
        if isinstance(manifest.get("runtime_blocker_next_subqueue_table"), Mapping)
        else {}
    )
    embedded_records = embedded_next_subqueue.get("records") if isinstance(embedded_next_subqueue.get("records"), list) else []
    if embedded_records:
        table = dict(embedded_next_subqueue)
        table.setdefault("table_kind", "runtime_blocker_next_subqueue_table_v1")
        table.setdefault("summary", {})
        table["source_next_subqueue_json"] = str(source_path)
        table["source_status_table_ref"] = str(source_path)
        return table, "IMPORTED_FROM_STAGE6_LOOP_RUNNER_ARTIFACT", "", derived_output_path, source_path, source_kind
    project_status_table = (
        manifest.get("project_status_table")
        if isinstance(manifest.get("project_status_table"), Mapping)
        else {}
    )
    records = project_status_table.get("records") if isinstance(project_status_table.get("records"), list) else []
    if not records:
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage6_review_loop_json_missing_project_status_or_next_subqueue",
            derived_output_path,
            source_path,
            source_kind,
        )
    table = build_runtime_blocker_next_subqueue_table(
        [record for record in records if isinstance(record, Mapping)],
        source_status_table_ref=str(source_path),
    )
    return table, "DERIVED_FROM_STAGE6_LOOP_RUNNER_ARTIFACT", "", derived_output_path, source_path, source_kind


def _resolve_next_subqueue_candidate(
    *,
    candidate: Mapping[str, Any],
    source_path: Path,
    stage6_loop_output_root: Path,
    derived_output_path: Path,
) -> tuple[dict[str, Any], str, str, Path | None, Path | None, str]:
    source_kind = str(candidate.get("source_kind") or "")
    table, state, blocker = _load_runtime_blocker_next_subqueue_table(source_path)
    return table, state, blocker, source_path, None, source_kind


def _resolve_status_table_candidate(
    *,
    candidate: Mapping[str, Any],
    source_path: Path,
    stage6_loop_output_root: Path,
    derived_output_path: Path,
) -> tuple[dict[str, Any], str, str, Path | None, Path | None, str]:
    source_kind = str(candidate.get("source_kind") or "")
    if not source_path.exists():
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage6_review_loop_status_json_missing_or_invalid",
            derived_output_path,
            source_path,
            source_kind,
        )
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage6_review_loop_status_json_missing_or_invalid",
            derived_output_path,
            source_path,
            source_kind,
        )
    records = payload.get("records") if isinstance(payload, Mapping) else []
    if not isinstance(records, list):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage6_review_loop_status_json_missing_or_invalid",
            derived_output_path,
            source_path,
            source_kind,
        )
    table = build_runtime_blocker_next_subqueue_table(
        [record for record in records if isinstance(record, Mapping)],
        source_status_table_ref=str(source_path),
    )
    return table, "DERIVED_FROM_STAGE6_STATUS_TABLE", "", derived_output_path, source_path, source_kind


def _resolve_loop_bootstrap_candidate(
    *,
    candidate: Mapping[str, Any],
    source_path: Path,
    stage6_loop_output_root: Path,
    derived_output_path: Path,
    supplemental_release_field_query_path: Path | None = None,
) -> tuple[dict[str, Any], str, str, Path | None, Path | None, str]:
    source_kind = str(candidate.get("source_kind") or "")
    missing_reason = str(candidate.get("missing_reason") or "")
    bootstrap_failure_reason = str(candidate.get("bootstrap_failure_reason") or "")
    loop_runner_arg = str(candidate.get("loop_runner_arg") or "")
    if not source_path.exists():
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            missing_reason,
            derived_output_path,
            None,
            source_kind,
        )
    from storage.stage6_review_loop_runner import run_stage6_review_loop_runner

    loop_kwargs = {
        "dispatch_root": stage6_loop_output_root / "missing-dispatch",
        "batch_closeout_root": stage6_loop_output_root / "missing-closeout",
        "output_root": stage6_loop_output_root,
        "auto_discover_latest_batch_closeout": False,
        loop_runner_arg: source_path,
    }
    if (
        source_kind == "RELEASE_FIELD_QUERY_JSON"
        and supplemental_release_field_query_path is not None
        and supplemental_release_field_query_path.exists()
        and supplemental_release_field_query_path != source_path
    ):
        loop_kwargs["supplemental_release_field_query_json"] = supplemental_release_field_query_path
    loop_result = run_stage6_review_loop_runner(**loop_kwargs)
    status_path = stage6_loop_output_root / "stage6-review-loop-project-status-table.json"
    if not loop_result.get("safe_to_execute") or not status_path.exists():
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            bootstrap_failure_reason,
            derived_output_path,
            status_path,
            source_kind,
        )
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage6_review_loop_bootstrap_status_json_invalid",
            derived_output_path,
            status_path,
            source_kind,
        )
    records = payload.get("records") if isinstance(payload, Mapping) else []
    table = build_runtime_blocker_next_subqueue_table(
        [record for record in records if isinstance(record, Mapping)],
        source_status_table_ref=str(status_path),
    )
    return table, "DERIVED_FROM_STAGE6_LOOP_RUNNER", "", derived_output_path, status_path, source_kind


def _resolve_derived_release_field_query_candidate(
    *,
    candidate: Mapping[str, Any],
    source_path: Path,
    stage6_loop_output_root: Path,
    derived_output_path: Path,
) -> tuple[dict[str, Any], str, str, Path | None, Path | None, str]:
    source_kind = str(candidate.get("source_kind") or "")
    return (
        _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
        "MISSING_OR_INVALID",
        str(candidate.get("bootstrap_failure_reason") or "derived_release_field_query_not_available"),
        derived_output_path,
        source_path if source_path.exists() else None,
        source_kind,
    )


def _resolve_stage4_followup_queue_candidate(
    *,
    candidate: Mapping[str, Any],
    source_path: Path,
    stage6_loop_output_root: Path,
    derived_output_path: Path,
) -> tuple[dict[str, Any], str, str, Path | None, Path | None, str]:
    source_kind = str(candidate.get("source_kind") or "")
    if not source_path.exists():
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            str(candidate.get("missing_reason") or "stage4_backfill_followup_queue_json_missing_or_invalid"),
            derived_output_path,
            None,
            source_kind,
        )
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage4_backfill_followup_queue_json_missing_or_invalid",
            derived_output_path,
            source_path,
            source_kind,
        )
    if not isinstance(payload, Mapping):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(derived_output_path)),
            "MISSING_OR_INVALID",
            "stage4_backfill_followup_queue_json_missing_or_invalid",
            derived_output_path,
            source_path,
            source_kind,
        )
    records = [
        _stage4_followup_next_subqueue_record(record, source_path=source_path)
        for record in _list(payload.get("records") or payload.get("followup_records"))
        if isinstance(record, Mapping)
    ]
    table = {
        "table_kind": "runtime_blocker_next_subqueue_table_v1",
        "source_next_subqueue_json": str(source_path),
        "source_stage4_backfill_followup_queue_json": str(source_path),
        "summary": {
            "next_subqueue_record_count": len(records),
            "subqueue_route_counts": _counts(record.get("subqueue_route") for record in records),
            "subqueue_state_counts": _counts(record.get("subqueue_state") for record in records),
            "runtime_layer_counts": _counts(record.get("runtime_layer") for record in records),
            "required_input_counts": _counts(
                required_input
                for record in records
                for required_input in _list(record.get("required_input"))
            ),
            "operator_next_action_counts": _counts(record.get("operator_next_action") for record in records),
        },
        "records": records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    _write_json(derived_output_path, table)
    return table, "DERIVED_FROM_STAGE4_BACKFILL_FOLLOWUP_QUEUE", "", derived_output_path, source_path, source_kind


def _stage4_followup_next_subqueue_record(record: Mapping[str, Any], *, source_path: Path) -> dict[str, Any]:
    project_id = str(record.get("project_id") or "").strip()
    route = "fallback_source"
    required_input = _dedupe(record.get("required_input"))
    operator_next_action = str(
        record.get("recommended_next_action")
        or record.get("operator_next_action")
        or "run_stage4_followup_queue_through_public_source_chain"
    )
    source_record_id = str(record.get("followup_record_id") or record.get("record_id") or "")
    if not source_record_id:
        source_record_id = f"STAGE4-FOLLOWUP-{_fingerprint(record)[:16]}"
    return {
        "next_subqueue_record_id": f"RUNTIME-SUBQUEUE-STAGE4-FOLLOWUP-{_fingerprint([source_record_id, route])[:16]}",
        "subqueue_route": route,
        "subqueue_state": "WAITING_FOR_FALLBACK_SOURCE_ADAPTER_PLAN",
        "project_id": project_id,
        "project_name": str(record.get("project_name") or ""),
        "assigned_owner": "",
        "assigned_owner_role": "",
        "owner_assignment_source_ref": "",
        "loop_terminal_state": "STAGE4_BACKFILL_FOLLOWUP_QUEUE_REQUIRES_CONTROLLER_ROUTE",
        "project_next_recommended_action": operator_next_action,
        "release_field_query_state": "",
        "blocker_ledger_id": source_record_id,
        "blocker_state": str(record.get("gap_detail") or record.get("followup_queue_state") or "STAGE4_BACKFILL_FOLLOWUP_REQUIRED"),
        "blocker_reason": str(record.get("followup_route") or ""),
        "runtime_layer": "controller decision:stage4_backfill_followup_queue",
        "ledger_scope": "stage4_backfill_followup_queue",
        "source_ledger_scopes": ["stage4_backfill_followup_queue"],
        "source_blocker_ledger_ids": [source_record_id],
        "task_scope": "stage4_backfill_followup",
        "task_type": str(record.get("followup_route") or "stage4_backfill_followup"),
        "task_id": source_record_id,
        "required_input": required_input,
        "retry_policy": "manual_reopen_after_public_source_plan",
        "reopen_conditions": _dedupe(record.get("required_input")),
        "operator_next_action": operator_next_action,
        "next_action": operator_next_action,
        "input_artifact_refs": _dedupe([str(source_path), *[str(item) for item in _list(record.get("source_refs"))]]),
        "source_status_table_ref": str(source_path),
        "controller_consumable": True,
        "stage4_followup_route": str(record.get("followup_route") or ""),
        "stage4_followup_queue_state": str(record.get("followup_queue_state") or ""),
        "stage4_followup_execution_priority": str(record.get("execution_priority") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _build_bootstrap_resolution_trace(
    *,
    candidates: list[Mapping[str, Any]],
    selected_source_kind: str,
    selected_resolution_state: str,
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    selected_order = {
        item["source_kind"]: index for index, item in enumerate(_bootstrap_source_registry())
    }.get(selected_source_kind, -1)
    for candidate in candidates:
        kind = str(candidate["source_kind"])
        path = candidate.get("source_path")
        provided = path is not None
        priority_order = int(candidate.get("priority_order") or 0)
        resolution_state = "NOT_PROVIDED"
        if provided and kind == selected_source_kind:
            resolution_state = selected_resolution_state
        elif provided and selected_order >= 0 and priority_order - 1 > selected_order:
            resolution_state = "SKIPPED_HIGHER_PRIORITY_SOURCE_SELECTED"
        elif provided:
            resolution_state = "PROVIDED_NOT_SELECTED"
        trace.append(
            {
                "source_kind": kind,
                "priority_order": priority_order,
                "source_ref_key": str(candidate["source_ref_key"]),
                "handler_kind": str(candidate["handler_kind"]),
                "loop_runner_arg": str(candidate.get("loop_runner_arg") or ""),
                "provided": provided,
                "selected": kind == selected_source_kind,
                "source_path": str(path or ""),
                "resolution_state": resolution_state,
            }
        )
    return trace


def _standalone_runtime_blocker_queue_only_mode(
    *,
    stage6_result: Mapping[str, Any],
    runtime_blocker_next_subqueue_input_state: str,
    runtime_blocker_next_subqueue_table: Mapping[str, Any],
    bootstrap_source_kind: str,
) -> bool:
    if str(runtime_blocker_next_subqueue_input_state or "") not in {
        "READY",
        "DERIVED_FROM_STAGE6_STATUS_TABLE",
        "DERIVED_FROM_STAGE6_LOOP_RUNNER",
        "IMPORTED_FROM_STAGE6_LOOP_RUNNER_ARTIFACT",
        "DERIVED_FROM_STAGE6_LOOP_RUNNER_ARTIFACT",
        "DERIVED_FROM_STAGE4_BACKFILL_FOLLOWUP_QUEUE",
    }:
        return False
    return str(bootstrap_source_kind or "") != "NOT_PROVIDED"


def _resolve_runtime_blocker_next_subqueue_input(
    *,
    candidates: list[Mapping[str, Any]],
    stage6_loop_output_root: Path,
    derived_output_path: Path,
    supplemental_release_field_query_path: Path | None = None,
) -> tuple[dict[str, Any], str, str, Path | None, Path | None, str]:
    dispatch_map = _bootstrap_handler_dispatch_map()
    for candidate in candidates:
        source_kind = str(candidate.get("source_kind") or "")
        source_path = candidate.get("source_path")
        if source_path is None:
            continue
        handler_kind = str(candidate.get("handler_kind") or "")
        handler = dispatch_map.get(handler_kind)
        if handler is None:
            continue
        if handler_kind == "loop_runner_bootstrap":
            return handler(
                candidate=candidate,
                source_path=Path(source_path),
                stage6_loop_output_root=stage6_loop_output_root,
                derived_output_path=derived_output_path,
                supplemental_release_field_query_path=supplemental_release_field_query_path,
            )
        return handler(
            candidate=candidate,
            source_path=Path(source_path),
            stage6_loop_output_root=stage6_loop_output_root,
            derived_output_path=derived_output_path,
        )
    return _empty_runtime_blocker_next_subqueue_table(), "NOT_PROVIDED", "", None, None, "NOT_PROVIDED"


def _load_runtime_blocker_next_subqueue_table(path: Path | None) -> tuple[dict[str, Any], str, str]:
    if not path:
        return _empty_runtime_blocker_next_subqueue_table(), "NOT_PROVIDED", ""
    if not path.exists():
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(path)),
            "MISSING_OR_INVALID",
            "runtime_blocker_next_subqueue_json_missing_or_invalid",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(path)),
            "MISSING_OR_INVALID",
            "runtime_blocker_next_subqueue_json_missing_or_invalid",
        )
    if not isinstance(payload, Mapping):
        return (
            _empty_runtime_blocker_next_subqueue_table(source_ref=str(path)),
            "MISSING_OR_INVALID",
            "runtime_blocker_next_subqueue_json_missing_or_invalid",
        )
    copied = dict(payload)
    copied.setdefault("source_status_table_ref", "")
    copied.setdefault("records", [])
    copied.setdefault("summary", {})
    copied["source_next_subqueue_json"] = str(path)
    return copied, "READY", ""


def _empty_runtime_blocker_next_subqueue_table(*, source_ref: str = "") -> dict[str, Any]:
    return {
        "table_kind": "runtime_blocker_next_subqueue_table_v1",
        "source_next_subqueue_json": source_ref,
        "summary": {
            "next_subqueue_record_count": 0,
            "subqueue_route_counts": {},
            "subqueue_state_counts": {},
        },
        "records": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _manifest_id(result: Mapping[str, Any]) -> str:
    manifest = result.get("manifest") if isinstance(result, Mapping) else {}
    return str(manifest.get("manifest_id") or "") if isinstance(manifest, Mapping) else ""


def _safe(result: Mapping[str, Any]) -> bool:
    if not result:
        return False
    return bool(result.get("safe_to_execute"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the next Stage6 review cycle from EvidenceBatchCloseout v1.")
    parser.add_argument("--batch-closeout-json", default="")
    parser.add_argument("--batch-closeout-root", default=str(DEFAULT_BATCH_CLOSEOUT_ROOT))
    parser.add_argument("--runtime-blocker-next-subqueue-json", default="")
    parser.add_argument("--runtime-blocker-next-subqueue-root", default="")
    parser.add_argument("--stage6-review-loop-json", default="")
    parser.add_argument("--stage6-review-loop-root", default="")
    parser.add_argument("--stage6-review-loop-status-json", default="")
    parser.add_argument("--stage6-review-loop-status-root", default="")
    parser.add_argument("--release-field-query-json", default="")
    parser.add_argument("--release-field-query-root", default="")
    parser.add_argument("--supplemental-release-field-query-json", default="")
    parser.add_argument("--supplemental-release-field-query-root", default="")
    parser.add_argument("--release-evidence-adapter-plan-json", default="")
    parser.add_argument("--release-evidence-adapter-plan-root", default="")
    parser.add_argument("--gdcic-browser-readback-json", default="")
    parser.add_argument("--gdcic-browser-readback-root", default="")
    parser.add_argument("--original-backtrace-continuation-json", default="")
    parser.add_argument("--original-backtrace-continuation-root", default="")
    parser.add_argument("--stage16-p13b-continuation-json", default="")
    parser.add_argument("--stage16-p13b-continuation-root", default="")
    parser.add_argument("--stage5-calibration-sample-json", default="")
    parser.add_argument("--stage5-calibration-sample-root", default="")
    parser.add_argument("--stage4-backfill-followup-queue-json", default="")
    parser.add_argument("--stage4-backfill-followup-queue-root", default="")
    parser.add_argument("--design-survey-public-registry-readback-json", default="")
    parser.add_argument("--design-survey-public-registry-readback-root", default="")
    parser.add_argument("--stage1-6-scoreboard-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute-dispatch", action="store_true")
    parser.add_argument("--dispatch-max-groups", type=int, default=None)
    parser.add_argument("--execute-runtime-blocker-dispatch", action="store_true")
    parser.add_argument("--runtime-blocker-dispatch-max-tasks", type=int, default=None)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--baseline-evidence-state-json", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_stage6_review_cycle_runner(
        batch_closeout_json=args.batch_closeout_json or None,
        batch_closeout_root=args.batch_closeout_root,
        runtime_blocker_next_subqueue_json=args.runtime_blocker_next_subqueue_json or None,
        runtime_blocker_next_subqueue_root=args.runtime_blocker_next_subqueue_root or None,
        stage6_review_loop_json=args.stage6_review_loop_json or None,
        stage6_review_loop_root=args.stage6_review_loop_root or None,
        stage6_review_loop_status_json=args.stage6_review_loop_status_json or None,
        stage6_review_loop_status_root=args.stage6_review_loop_status_root or None,
        release_field_query_json=args.release_field_query_json or None,
        release_field_query_root=args.release_field_query_root or None,
        supplemental_release_field_query_json=args.supplemental_release_field_query_json or None,
        supplemental_release_field_query_root=args.supplemental_release_field_query_root or None,
        release_evidence_adapter_plan_json=args.release_evidence_adapter_plan_json or None,
        release_evidence_adapter_plan_root=args.release_evidence_adapter_plan_root or None,
        gdcic_browser_readback_json=args.gdcic_browser_readback_json or None,
        gdcic_browser_readback_root=args.gdcic_browser_readback_root or None,
        original_backtrace_continuation_json=args.original_backtrace_continuation_json or None,
        original_backtrace_continuation_root=args.original_backtrace_continuation_root or None,
        stage16_p13b_continuation_json=args.stage16_p13b_continuation_json or None,
        stage16_p13b_continuation_root=args.stage16_p13b_continuation_root or None,
        stage5_calibration_sample_json=args.stage5_calibration_sample_json or None,
        stage5_calibration_sample_root=args.stage5_calibration_sample_root or None,
        stage4_backfill_followup_queue_json=args.stage4_backfill_followup_queue_json or None,
        stage4_backfill_followup_queue_root=args.stage4_backfill_followup_queue_root or None,
        design_survey_public_registry_readback_json=args.design_survey_public_registry_readback_json or None,
        design_survey_public_registry_readback_root=args.design_survey_public_registry_readback_root or None,
        stage1_6_scoreboard_json=args.stage1_6_scoreboard_json or None,
        output_root=args.output_root,
        execute_dispatch=bool(args.execute_dispatch),
        dispatch_max_groups=args.dispatch_max_groups,
        execute_runtime_blocker_dispatch=bool(args.execute_runtime_blocker_dispatch),
        runtime_blocker_dispatch_max_tasks=args.runtime_blocker_dispatch_max_tasks,
        project_ids=_parse_csv(args.project_ids),
        baseline_evidence_state_json=args.baseline_evidence_state_json or None,
        cwd=args.cwd or None,
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
    "STAGE6_REVIEW_CYCLE_RUNNER_KIND",
    "run_stage6_review_cycle_runner",
]
