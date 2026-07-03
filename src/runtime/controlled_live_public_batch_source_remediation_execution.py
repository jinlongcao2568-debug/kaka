from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from runtime.controlled_live_public_batch_evidence_summary import (
    build_controlled_live_public_batch_evidence_summary,
)
from runtime.controlled_live_public_batch_source_remediation import (
    build_controlled_live_public_batch_source_remediation,
)
from runtime.controlled_live_public_batch_stage4_readback import (
    build_controlled_live_public_batch_stage4_readback,
)
from storage.evaluation_real_sample_execution import build_evaluation_real_sample_execution


CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_KIND = (
    "controlled_live_public_batch_source_remediation_execution_v1"
)
CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/controlled-live-public-batch-source-remediation-execution-v1"
)


def build_controlled_live_public_batch_source_remediation_execution(
    *,
    source_remediation_json: str | Path,
    targets_json: str | Path | None = None,
    seed_json: str | Path | None = None,
    target_backend: str = "json-file",
    storage_path: str | Path | None = None,
    object_storage_path: str | Path | None = None,
    database_url: str | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute: bool = False,
    created_at: str | None = None,
    target_limit: int | None = None,
    per_target_candidate_limit: int = 1,
    professional_source_only: bool = False,
    discovery_service: Any | None = None,
    capture_service: Any | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    remediation_path = Path(source_remediation_json)
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    storage = Path(storage_path) if storage_path else output_dir / "storage.json"
    object_storage = Path(object_storage_path) if object_storage_path else output_dir / "objects"

    remediation_payload = _load_json(remediation_path)
    queue_records = _records(_mapping(remediation_payload.get("source_remediation_queue")).get("records"))
    group_records = _records(_mapping(remediation_payload.get("source_remediation_groups")).get("records"))
    requested_target_ids = _queued_target_ids(queue_records=queue_records, group_records=group_records)
    if target_limit is not None:
        requested_target_ids = requested_target_ids[: max(0, int(target_limit))]

    rerun_result: dict[str, Any] | None = None
    if requested_target_ids:
        rerun_result = build_evaluation_real_sample_execution(
            targets_json=targets_json,
            seed_json=seed_json,
            database_url=database_url,
            target_backend=target_backend,
            storage_path=storage,
            object_storage_path=object_storage,
            execute=execute,
            created_at=created,
            target_ids=requested_target_ids,
            per_target_candidate_limit=per_target_candidate_limit,
            professional_source_only=professional_source_only,
            discovery_service=discovery_service,
            capture_service=capture_service,
        )
    rerun_manifest_json = output_dir / "controlled-live-public-batch-source-remediation-rerun-manifest.json"
    post_run_outputs = _post_run_outputs(
        rerun_result=rerun_result,
        rerun_manifest_json=rerun_manifest_json,
        storage_path=storage,
        output_dir=output_dir,
        execute=execute,
        created_at=created,
    )

    summary = _summary(
        source_remediation_payload=remediation_payload,
        queue_records=queue_records,
        group_records=group_records,
        requested_target_ids=requested_target_ids,
        rerun_result=rerun_result,
        post_run_outputs=post_run_outputs,
        execute=execute,
    )
    result = {
        "manifest_kind": CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_KIND,
        "manifest_version": CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_EXECUTION_VERSION,
        "adapter_id": "controlled-live-public-batch-source-remediation-execution-v1",
        "created_at": created,
        "source_remediation_json": str(remediation_path),
        "targets_json": str(targets_json or ""),
        "seed_json": str(seed_json or ""),
        "target_backend": target_backend,
        "storage_path": str(storage),
        "object_storage_path": str(object_storage),
        "execute": execute,
        "requested_target_ids": requested_target_ids,
        "rerun_manifest_json": str(rerun_manifest_json if rerun_result else ""),
        "post_run_outputs": post_run_outputs,
        "summary": summary,
        "rerun_execution_manifest": _mapping(_mapping(rerun_result).get("manifest")),
        "safety": _safety(execute=execute),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(
        output_dir / "controlled-live-public-batch-source-remediation-execution-v1.json",
        result,
    )
    (output_dir / "controlled-live-public-batch-source-remediation-execution-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _post_run_outputs(
    *,
    rerun_result: Mapping[str, Any] | None,
    rerun_manifest_json: Path,
    storage_path: Path,
    output_dir: Path,
    execute: bool,
    created_at: str,
) -> dict[str, Any]:
    if not rerun_result:
        return {}
    _write_json(rerun_manifest_json, rerun_result)
    if not execute:
        return {
            "rerun_manifest_json": str(rerun_manifest_json),
            "post_run_evidence_generation_state": "NOT_RUN_DRY_RUN_ONLY",
        }

    evidence_root = output_dir / "evidence-summary"
    stage4_root = output_dir / "stage4-readback"
    source_remediation_root = output_dir / "source-remediation"
    evidence = build_controlled_live_public_batch_evidence_summary(
        real_sample_execution_json=rerun_manifest_json,
        storage_json=storage_path,
        output_root=evidence_root,
        created_at=created_at,
    )
    stage4 = build_controlled_live_public_batch_stage4_readback(
        evidence_summary_json=evidence_root / "controlled-live-public-batch-evidence-summary-v1.json",
        real_sample_execution_json=rerun_manifest_json,
        storage_json=storage_path,
        output_root=stage4_root,
        created_at=created_at,
    )
    source_remediation = build_controlled_live_public_batch_source_remediation(
        evidence_summary_json=evidence_root / "controlled-live-public-batch-evidence-summary-v1.json",
        real_sample_execution_json=rerun_manifest_json,
        stage4_readback_json=stage4_root / "controlled-live-public-batch-stage4-readback-v1.json",
        output_root=source_remediation_root,
        created_at=created_at,
    )
    return {
        "rerun_manifest_json": str(rerun_manifest_json),
        "post_run_evidence_generation_state": "GENERATED",
        "post_run_evidence_summary_json": str(evidence_root / "controlled-live-public-batch-evidence-summary-v1.json"),
        "post_run_stage4_readback_json": str(stage4_root / "controlled-live-public-batch-stage4-readback-v1.json"),
        "post_run_source_remediation_json": str(
            source_remediation_root / "controlled-live-public-batch-source-remediation-v1.json"
        ),
        "post_run_project_sample_count": _int(_mapping(evidence.get("summary")).get("project_sample_count")),
        "post_run_fixed_snapshot_sha256_count": _int(
            _mapping(evidence.get("summary")).get("fixed_snapshot_sha256_count")
        ),
        "post_run_stage4_all_required_readbacks_ready": bool(
            _mapping(stage4.get("summary")).get("stage4_all_required_readbacks_ready")
        ),
        "post_run_source_remediation_record_count": _int(
            _mapping(source_remediation.get("summary")).get("source_remediation_record_count")
        ),
        "post_run_source_remediation_closeout_state": str(
            _mapping(source_remediation.get("summary")).get("source_remediation_closeout_state") or ""
        ),
    }


def _queued_target_ids(
    *,
    queue_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
) -> list[str]:
    ids: list[Any] = []
    for group in group_records:
        recommended = _mapping(group.get("recommended_execution"))
        ids.extend(_string_list(recommended.get("blocked_parent_target_ids")))
    for record in queue_records:
        ids.extend(_string_list(record.get("minimum_rerun_target_ids")))
        ids.append(record.get("parent_target_id"))
    return _dedupe(ids)


def _summary(
    *,
    source_remediation_payload: Mapping[str, Any],
    queue_records: list[Mapping[str, Any]],
    group_records: list[Mapping[str, Any]],
    requested_target_ids: list[str],
    rerun_result: Mapping[str, Any] | None,
    post_run_outputs: Mapping[str, Any],
    execute: bool,
) -> dict[str, Any]:
    rerun_manifest = _mapping(_mapping(rerun_result).get("manifest"))
    rerun_summary = _mapping(rerun_manifest.get("summary"))
    selected_target_ids = _string_list(rerun_manifest.get("selected_target_ids"))
    missing_target_ids = _string_list(rerun_manifest.get("missing_requested_target_ids"))
    state = _execution_state(
        requested_target_ids=requested_target_ids,
        selected_target_ids=selected_target_ids,
        rerun_summary=rerun_summary,
        execute=execute,
    )
    return {
        "source_remediation_execution_mode": "EXECUTED" if execute else "DRY_RUN",
        "execute": execute,
        "source_remediation_manifest_sha256": str(source_remediation_payload.get("manifest_sha256") or ""),
        "source_remediation_record_count": len(queue_records),
        "source_remediation_group_count": len(group_records),
        "queued_blocked_parent_target_count": len(requested_target_ids),
        "requested_target_ids": requested_target_ids,
        "selected_target_ids": selected_target_ids,
        "missing_requested_target_ids": missing_target_ids,
        "rerun_target_execution_bucket_count": _int(rerun_summary.get("target_execution_bucket_count")),
        "rerun_project_sample_count": _int(rerun_summary.get("project_sample_count")),
        "rerun_detail_snapshot_count": _int(rerun_summary.get("detail_snapshot_count")),
        "rerun_attachment_snapshot_count": _int(rerun_summary.get("attachment_snapshot_count")),
        "rerun_stage3_parse_success_count": _int(rerun_summary.get("stage3_parse_success_count")),
        "rerun_stage3_parse_failed_count": _int(rerun_summary.get("stage3_parse_failed_count")),
        "rerun_target_execution_state_counts": _mapping(rerun_summary.get("execution_state_counts")),
        "rerun_coverage_quality_state": str(rerun_summary.get("coverage_quality_state") or ""),
        "source_remediation_execution_state": state,
        "post_run_evidence_generation_state": str(
            post_run_outputs.get("post_run_evidence_generation_state") or ""
        ),
        "post_run_evidence_summary_json": str(post_run_outputs.get("post_run_evidence_summary_json") or ""),
        "post_run_stage4_readback_json": str(post_run_outputs.get("post_run_stage4_readback_json") or ""),
        "post_run_source_remediation_json": str(post_run_outputs.get("post_run_source_remediation_json") or ""),
        "post_run_fixed_snapshot_sha256_count": _int(
            post_run_outputs.get("post_run_fixed_snapshot_sha256_count")
        ),
        "post_run_stage4_all_required_readbacks_ready": bool(
            post_run_outputs.get("post_run_stage4_all_required_readbacks_ready")
        ),
        "post_run_source_remediation_record_count": _int(
            post_run_outputs.get("post_run_source_remediation_record_count")
        ),
        "post_run_source_remediation_closeout_state": str(
            post_run_outputs.get("post_run_source_remediation_closeout_state") or ""
        ),
        "next_required_step": _next_required_step(state, post_run_outputs=post_run_outputs),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _execution_state(
    *,
    requested_target_ids: list[str],
    selected_target_ids: list[str],
    rerun_summary: Mapping[str, Any],
    execute: bool,
) -> str:
    if not requested_target_ids:
        return "NO_SOURCE_REMEDIATION_REQUIRED"
    if not selected_target_ids:
        return "SOURCE_REMEDIATION_TARGETS_NOT_FOUND"
    if not execute:
        return "SOURCE_REMEDIATION_RERUN_PLANNED"
    if _int(rerun_summary.get("detail_snapshot_count")) > 0:
        return "SOURCE_REMEDIATION_RERUN_EXECUTED_WITH_SNAPSHOTS"
    if _int(rerun_summary.get("project_sample_count")) > 0:
        return "SOURCE_REMEDIATION_RERUN_EXECUTED_REVIEW_REQUIRED"
    return "SOURCE_REMEDIATION_RERUN_EXECUTED_NO_SAMPLES"


def _next_required_step(state: str, *, post_run_outputs: Mapping[str, Any]) -> str:
    if state == "NO_SOURCE_REMEDIATION_REQUIRED":
        return "gray_launch_review_if_other_gates_ready"
    if state == "SOURCE_REMEDIATION_RERUN_PLANNED":
        return "rerun_source_remediation_execution_with_execute"
    if state == "SOURCE_REMEDIATION_TARGETS_NOT_FOUND":
        return "repair_or_expand_evaluation_target_registry"
    if state == "SOURCE_REMEDIATION_RERUN_EXECUTED_WITH_SNAPSHOTS":
        if _int(post_run_outputs.get("post_run_source_remediation_record_count")) > 0:
            return "continue_source_remediation_queue"
        if bool(post_run_outputs.get("post_run_stage4_all_required_readbacks_ready")):
            return "human_gray_launch_review"
        return "rebuild_evidence_summary_stage4_and_source_remediation"
    return "review_source_remediation_execution_result"


def _safety(*, execute: bool) -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "download_enabled": bool(execute),
        "fetch_public_urls_enabled": bool(execute),
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "source_remediation_execution_enabled": bool(execute),
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Live Public Batch Source Remediation Execution",
        "",
        f"- source_remediation_execution_mode: {summary.get('source_remediation_execution_mode')}",
        f"- source_remediation_record_count: {summary.get('source_remediation_record_count')}",
        f"- source_remediation_group_count: {summary.get('source_remediation_group_count')}",
        f"- queued_blocked_parent_target_count: {summary.get('queued_blocked_parent_target_count')}",
        f"- selected_target_ids: {', '.join(_string_list(summary.get('selected_target_ids')))}",
        f"- missing_requested_target_ids: {', '.join(_string_list(summary.get('missing_requested_target_ids')))}",
        f"- rerun_project_sample_count: {summary.get('rerun_project_sample_count')}",
        f"- rerun_detail_snapshot_count: {summary.get('rerun_detail_snapshot_count')}",
        f"- source_remediation_execution_state: {summary.get('source_remediation_execution_state')}",
        f"- next_required_step: {summary.get('next_required_step')}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- query_miss_is_not_clearance: {str(bool(summary.get('query_miss_is_not_clearance'))).lower()}",
        "",
    ]
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any]:
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


def _dedupe(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-remediation-json", required=True)
    parser.add_argument("--targets-json", default="")
    parser.add_argument("--seed-json", default="")
    parser.add_argument("--target-backend", default="json-file")
    parser.add_argument("--storage-path", default="")
    parser.add_argument("--object-storage-path", default="")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--target-limit", type=int, default=None)
    parser.add_argument("--per-target-candidate-limit", type=int, default=1)
    parser.add_argument("--professional-source-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_controlled_live_public_batch_source_remediation_execution(
        source_remediation_json=args.source_remediation_json,
        targets_json=args.targets_json or None,
        seed_json=args.seed_json or None,
        target_backend=args.target_backend,
        storage_path=args.storage_path or None,
        object_storage_path=args.object_storage_path or None,
        database_url=args.database_url or None,
        output_root=args.output_root,
        target_limit=args.target_limit,
        per_target_candidate_limit=args.per_target_candidate_limit,
        professional_source_only=args.professional_source_only,
        execute=args.execute,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
