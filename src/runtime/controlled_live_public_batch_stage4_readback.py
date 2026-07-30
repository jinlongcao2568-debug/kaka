from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from stage4_verification.public_evidence_readback import build_public_evidence_readback


CONTROLLED_LIVE_PUBLIC_BATCH_STAGE4_READBACK_KIND = (
    "controlled_live_public_batch_stage4_readback_v1"
)
CONTROLLED_LIVE_PUBLIC_BATCH_STAGE4_READBACK_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/controlled-live-public-batch-stage4-readback-v1")

DOCUMENT_KIND_TARGET_TYPES = {
    "tender_file": "project_tender_file_public_snapshot",
    "candidate_notice": "project_candidate_notice_public_snapshot",
    "award_result": "project_award_result_public_snapshot",
    "failed_bid_notice": "project_failed_bid_notice_public_snapshot",
    "complaint_decision": "project_complaint_decision_public_snapshot",
}


def build_controlled_live_public_batch_stage4_readback(
    *,
    evidence_summary_json: str | Path,
    real_sample_execution_json: str | Path,
    storage_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    evidence_path = Path(evidence_summary_json)
    execution_path = Path(real_sample_execution_json)
    storage_path = Path(storage_json) if storage_json else None
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    evidence_payload = _load_json(evidence_path)
    execution_payload = _load_json(execution_path)
    storage_payload = _load_json(storage_path) if storage_path and storage_path.exists() else {}
    evidence_summary = _mapping(evidence_payload.get("summary"))
    sample_records = _records(_mapping(evidence_payload.get("sample_evidence_table")).get("records"))
    execution_manifest = _mapping(execution_payload.get("manifest") or execution_payload)
    execution_samples = _execution_sample_index(_records(execution_manifest.get("project_sample_items")))
    object_index = _object_index(storage_payload)

    sample_readback_records: list[dict[str, Any]] = []
    public_evidence_readbacks: list[dict[str, Any]] = []
    for sample in sample_records:
        execution_sample = _lookup_execution_sample(sample, execution_samples)
        sample_result = _sample_stage4_readback_record(
            sample,
            execution_sample=execution_sample,
            object_index=object_index,
            created_at=created,
        )
        sample_readback_records.append(sample_result)
        public_evidence_readbacks.extend(_records(sample_result.get("stage4_public_evidence_readbacks")))

    summary = _summary(
        source_execute=bool(evidence_summary.get("source_execute")),
        evidence_summary=evidence_summary,
        sample_readback_records=sample_readback_records,
        public_evidence_readbacks=public_evidence_readbacks,
    )
    result = {
        "manifest_kind": CONTROLLED_LIVE_PUBLIC_BATCH_STAGE4_READBACK_KIND,
        "manifest_version": CONTROLLED_LIVE_PUBLIC_BATCH_STAGE4_READBACK_VERSION,
        "adapter_id": "controlled-live-public-batch-stage4-readback-v1",
        "created_at": created,
        "source_evidence_summary_json": str(evidence_path),
        "source_real_sample_execution_json": str(execution_path),
        "source_storage_json": str(storage_path or ""),
        "summary": summary,
        "stage4_readback_table": {"records": sample_readback_records, "summary": summary},
        "stage4_public_evidence_readbacks": public_evidence_readbacks,
        "safety": _safety(),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-live-public-batch-stage4-readback-v1.json", result)
    (output_dir / "controlled-live-public-batch-stage4-readback-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _sample_stage4_readback_record(
    sample: Mapping[str, Any],
    *,
    execution_sample: Mapping[str, Any],
    object_index: Mapping[str, Mapping[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    required = bool(sample.get("requires_stage4_evidence_readback"))
    fixed_hashes = _string_list(sample.get("fixed_snapshot_sha256s"))
    snapshot_pairs = _snapshot_pairs(execution_sample, object_index=object_index)
    readbacks = [
        _public_evidence_readback(sample, snapshot_pair=pair, created_at=created_at)
        for pair in snapshot_pairs
        if pair.get("snapshot_hash") in fixed_hashes
    ]
    if required and fixed_hashes and not readbacks:
        readbacks = [
            _public_evidence_readback(
                sample,
                snapshot_pair={
                    "source_snapshot_id": f"hash-only:{snapshot_hash[:16]}",
                    "snapshot_hash": snapshot_hash,
                    "snapshot_role": "hash_only_fallback",
                    "source_ref_resolution": "HASHED_SNAPSHOT_PRESENT_REF_NOT_RESOLVED",
                },
                created_at=created_at,
            )
            for snapshot_hash in fixed_hashes
        ]

    readback_ids = [str(readback.get("readback_id") or "") for readback in readbacks]
    if required and fixed_hashes and readbacks:
        state = "STAGE4_PUBLIC_EVIDENCE_READBACK_READY"
    elif required:
        state = "STAGE4_PUBLIC_EVIDENCE_READBACK_REVIEW_REQUIRED"
    else:
        state = "STAGE4_PUBLIC_EVIDENCE_READBACK_NOT_REQUIRED"
    return {
        "sample_id": str(sample.get("sample_id") or ""),
        "target_id": str(sample.get("target_id") or ""),
        "parent_target_id": str(sample.get("parent_target_id") or ""),
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "document_kind": str(sample.get("document_kind") or ""),
        "source_profile_id": str(sample.get("source_profile_id") or ""),
        "source_url": str(sample.get("source_url") or ""),
        "public_source_outcome": str(sample.get("public_source_outcome") or ""),
        "evidence_fixation_state": str(sample.get("evidence_fixation_state") or ""),
        "fixed_snapshot_sha256s": fixed_hashes,
        "stage4_readback_required": required,
        "stage4_readback_state": state,
        "stage4_readback_ready": state == "STAGE4_PUBLIC_EVIDENCE_READBACK_READY",
        "stage4_readback_record_count": len(readbacks),
        "stage4_public_evidence_readback_ids": readback_ids,
        "stage4_public_evidence_readbacks": readbacks,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _public_evidence_readback(
    sample: Mapping[str, Any],
    *,
    snapshot_pair: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    snapshot_hash = str(snapshot_pair.get("snapshot_hash") or "")
    source_snapshot_id = str(snapshot_pair.get("source_snapshot_id") or "")
    source_profile_id = str(sample.get("source_profile_id") or "public_source")
    document_kind = str(sample.get("document_kind") or "public_snapshot")
    readback = build_public_evidence_readback(
        readback_id=_stable_id("CLPB-ST4", sample.get("sample_id"), source_snapshot_id, snapshot_hash),
        verification_target_type=DOCUMENT_KIND_TARGET_TYPES.get(document_kind, "public_source_snapshot"),
        source_family=_source_family(source_profile_id),
        source_url=str(sample.get("source_url") or ""),
        source_snapshot_id=source_snapshot_id,
        snapshot_hash=snapshot_hash,
        official_source=True,
        subject_identifier=str(sample.get("project_id") or sample.get("project_name") or sample.get("sample_id") or ""),
        field_extracts={
            "sample_id": str(sample.get("sample_id") or ""),
            "project_id": str(sample.get("project_id") or ""),
            "project_name": str(sample.get("project_name") or ""),
            "document_kind": document_kind,
            "source_profile_id": source_profile_id,
            "snapshot_role": str(snapshot_pair.get("snapshot_role") or ""),
            "source_ref_resolution": str(snapshot_pair.get("source_ref_resolution") or "SNAPSHOT_REF_HASH_MATCHED"),
            "evidence_fixation_state": str(sample.get("evidence_fixation_state") or ""),
            "public_source_outcome": str(sample.get("public_source_outcome") or ""),
            "source_slice_sha256": snapshot_hash,
            "controlled_live_batch_stage4_readback": True,
        },
        validity_or_status="PUBLIC_RECORD_FOUND",
        repair_or_release_state="NO_REPAIR_RECORD",
        data_grade_or_audit_state="CONFIRMED",
        review_required=False,
        failure_reasons=[],
        public_only=True,
        customer_visible=False,
        no_legal_conclusion=True,
    )
    readback["readback_state"] = "READBACK_READY"
    readback["replayable"] = True
    readback["readback_record_sha256"] = _fingerprint(readback)
    readback["created_at"] = created_at
    return readback


def _summary(
    *,
    source_execute: bool,
    evidence_summary: Mapping[str, Any],
    sample_readback_records: list[Mapping[str, Any]],
    public_evidence_readbacks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    required_records = [record for record in sample_readback_records if bool(record.get("stage4_readback_required"))]
    ready_records = [
        record for record in required_records if str(record.get("stage4_readback_state") or "") == "STAGE4_PUBLIC_EVIDENCE_READBACK_READY"
    ]
    missing_count = max(0, len(required_records) - len(ready_records))
    partial_or_blocked_count = _int(
        _mapping(evidence_summary.get("public_source_outcome_counts")).get("PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW")
    )
    no_match_count = _int(
        _mapping(evidence_summary.get("public_source_outcome_counts")).get("PUBLIC_SOURCE_NO_MATCH_REVIEW")
    )
    all_required_ready = bool(required_records) and missing_count == 0
    eligible = (
        source_execute
        and _int(evidence_summary.get("project_sample_count")) > 0
        and all_required_ready
        and partial_or_blocked_count == 0
        and no_match_count == 0
    )
    return {
        "source_execute": source_execute,
        "project_sample_count": _int(evidence_summary.get("project_sample_count")),
        "stage4_readback_required_sample_count": len(required_records),
        "stage4_readback_ready_sample_count": len(ready_records),
        "stage4_readback_missing_sample_count": missing_count,
        "stage4_public_evidence_readback_count": len(public_evidence_readbacks),
        "stage4_readback_state_counts": _counts(record.get("stage4_readback_state") for record in sample_readback_records),
        "stage4_public_evidence_readback_generation_enabled": True,
        "stage4_all_required_readbacks_ready": all_required_ready,
        "partial_or_blocked_count": partial_or_blocked_count,
        "no_match_count": no_match_count,
        "eligible_for_gray_launch_review": eligible,
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _snapshot_pairs(
    execution_sample: Mapping[str, Any],
    *,
    object_index: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for role, key in (("detail", "detail_snapshot_refs"), ("attachment", "attachment_snapshot_refs")):
        for ref in _records(execution_sample.get(key)):
            snapshot_id = str(ref.get("snapshot_id") or "")
            snapshot_hash = _hash_for_snapshot_id(snapshot_id, object_index)
            if not snapshot_id or not snapshot_hash:
                continue
            pairs.append(
                {
                    "source_snapshot_id": snapshot_id,
                    "snapshot_hash": snapshot_hash,
                    "snapshot_role": role,
                    "source_ref_resolution": "SNAPSHOT_REF_HASH_MATCHED",
                }
            )
    return pairs


def _hash_for_snapshot_id(snapshot_id: str, object_index: Mapping[str, Mapping[str, Any]]) -> str:
    prefix = snapshot_id.rsplit("-", 1)[-1]
    if not prefix:
        return ""
    for sha256 in object_index:
        if str(sha256).startswith(prefix):
            return str(sha256)
    return ""


def _execution_sample_index(samples: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for sample in samples:
        for key in ("sample_id", "target_id"):
            value = str(sample.get(key) or "")
            if value and value not in result:
                result[value] = sample
    return result


def _lookup_execution_sample(
    sample: Mapping[str, Any],
    execution_samples: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    for key in ("sample_id", "target_id"):
        value = str(sample.get(key) or "")
        if value in execution_samples:
            return execution_samples[value]
    return {}


def _object_index(storage_payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    object_table = _mapping(_mapping(storage_payload.get("tables")).get("object_storage_object"))
    index: dict[str, dict[str, Any]] = {}
    for record in object_table.values():
        if not isinstance(record, Mapping):
            continue
        payload = _mapping(record.get("payload"))
        sha256 = str(payload.get("sha256") or "").strip()
        if not sha256:
            continue
        index[sha256] = {
            "sha256": sha256,
            "object_key": str(payload.get("object_key") or ""),
            "content_type": str(payload.get("content_type") or ""),
            "byte_size": _int(payload.get("byte_size")),
        }
    return index


def _source_family(source_profile_id: str) -> str:
    text = str(source_profile_id or "public_source").strip().lower()
    out = []
    for char in text:
        out.append(char if char.isalnum() else "_")
    return "".join(out).strip("_") or "public_source"


def _safety() -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "stage4_public_evidence_readback_generation_enabled": True,
        "stage5_rule_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Live Public Batch Stage4 Readback",
        "",
        f"- project_sample_count: {summary.get('project_sample_count')}",
        f"- stage4_readback_required_sample_count: {summary.get('stage4_readback_required_sample_count')}",
        f"- stage4_readback_ready_sample_count: {summary.get('stage4_readback_ready_sample_count')}",
        f"- stage4_readback_missing_sample_count: {summary.get('stage4_readback_missing_sample_count')}",
        f"- stage4_public_evidence_readback_count: {summary.get('stage4_public_evidence_readback_count')}",
        f"- stage4_all_required_readbacks_ready: {str(bool(summary.get('stage4_all_required_readbacks_ready'))).lower()}",
        f"- eligible_for_gray_launch_review: {str(bool(summary.get('eligible_for_gray_launch_review'))).lower()}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- query_miss_is_not_clearance: {str(bool(summary.get('query_miss_is_not_clearance'))).lower()}",
        "",
        "## Stage4 Readback States",
    ]
    for key, value in _mapping(summary.get("stage4_readback_state_counts")).items():
        lines.append(f"- {key}: {value}")
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


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        json.dumps([str(part or "") for part in parts], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-summary-json", required=True)
    parser.add_argument("--real-sample-execution-json", required=True)
    parser.add_argument("--storage-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_controlled_live_public_batch_stage4_readback(
        evidence_summary_json=args.evidence_summary_json,
        real_sample_execution_json=args.real_sample_execution_json,
        storage_json=args.storage_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
