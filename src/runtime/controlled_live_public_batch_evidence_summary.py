from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


CONTROLLED_LIVE_PUBLIC_BATCH_EVIDENCE_SUMMARY_KIND = (
    "controlled_live_public_batch_evidence_summary_v1"
)
CONTROLLED_LIVE_PUBLIC_BATCH_EVIDENCE_SUMMARY_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/controlled-live-public-batch-evidence-summary-v1")


def build_controlled_live_public_batch_evidence_summary(
    *,
    real_sample_execution_json: str | Path,
    storage_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    execution_path = Path(real_sample_execution_json)
    storage_path = Path(storage_json) if storage_json else None
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    execution_payload = _load_json(execution_path)
    manifest = _mapping(execution_payload.get("manifest") or execution_payload)
    storage_payload = _load_json(storage_path) if storage_path and storage_path.exists() else {}
    object_index = _object_index(storage_payload)
    target_records = [_target_record(item) for item in _records(manifest.get("items"))]
    sample_records = [
        _sample_record(item, object_index=object_index)
        for item in _records(manifest.get("project_sample_items"))
    ]
    summary = _summary(
        manifest=manifest,
        target_records=target_records,
        sample_records=sample_records,
        object_index=object_index,
    )
    evidence_graph = _evidence_graph(summary=summary, sample_records=sample_records)
    result = {
        "manifest_kind": CONTROLLED_LIVE_PUBLIC_BATCH_EVIDENCE_SUMMARY_KIND,
        "manifest_version": CONTROLLED_LIVE_PUBLIC_BATCH_EVIDENCE_SUMMARY_VERSION,
        "adapter_id": "controlled-live-public-batch-evidence-summary-v1",
        "created_at": created,
        "source_real_sample_execution_json": str(execution_path),
        "source_storage_json": str(storage_path or ""),
        "summary": summary,
        "evidence_graph": evidence_graph,
        "target_evidence_table": {"records": target_records, "summary": summary},
        "sample_evidence_table": {"records": sample_records, "summary": summary},
        "safety": _safety(),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-live-public-batch-evidence-summary-v1.json", result)
    (output_dir / "controlled-live-public-batch-evidence-summary-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _target_record(item: Mapping[str, Any]) -> dict[str, Any]:
    failure_taxonomy = _string_list(item.get("failure_taxonomy"))
    state = str(item.get("target_execution_state") or "")
    return {
        "target_id": str(item.get("target_id") or ""),
        "jurisdiction": str(item.get("jurisdiction") or ""),
        "platform_name": str(item.get("platform_name") or ""),
        "document_kind": str(item.get("document_kind") or ""),
        "source_profile_id": str(item.get("source_profile_id") or ""),
        "target_execution_state": state,
        "discovery_candidate_count": _int(item.get("discovery_candidate_count")),
        "detail_snapshot_ref_count": len(_records(item.get("detail_snapshot_refs"))),
        "attachment_snapshot_ref_count": len(_records(item.get("attachment_snapshot_refs"))),
        "failure_taxonomy": failure_taxonomy,
        "public_source_outcome": _target_outcome(state, failure_taxonomy),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _sample_record(item: Mapping[str, Any], *, object_index: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    detail_refs = _records(item.get("detail_snapshot_refs"))
    attachment_refs = _records(item.get("attachment_snapshot_refs"))
    detail_hashes = _hashes_for_refs(detail_refs, object_index=object_index, ref_key="snapshot_id")
    attachment_hashes = _hashes_for_refs(attachment_refs, object_index=object_index, ref_key="snapshot_id")
    all_hashes = _dedupe([*detail_hashes, *attachment_hashes])
    state = str(item.get("target_execution_state") or "")
    outcome = _sample_outcome(state, all_hashes)
    return {
        "sample_id": str(item.get("sample_id") or item.get("target_id") or ""),
        "parent_target_id": str(item.get("parent_target_id") or ""),
        "target_id": str(item.get("target_id") or ""),
        "project_id": str(item.get("project_id") or ""),
        "project_name": str(item.get("project_name") or ""),
        "document_kind": str(item.get("document_kind") or ""),
        "jurisdiction": str(item.get("jurisdiction") or ""),
        "source_profile_id": str(item.get("source_profile_id") or ""),
        "source_url": str(item.get("source_url") or ""),
        "target_execution_state": state,
        "detail_capture_status": str(item.get("detail_capture_status") or ""),
        "stage3_parse_state": str(item.get("stage3_parse_state") or ""),
        "document_completeness_state": str(item.get("document_completeness_state") or ""),
        "detail_snapshot_count": len(detail_refs),
        "attachment_snapshot_count": len(attachment_refs),
        "detail_snapshot_sha256s": detail_hashes,
        "attachment_snapshot_sha256s": attachment_hashes,
        "fixed_snapshot_sha256s": all_hashes,
        "evidence_fixation_state": _fixation_state(state, all_hashes),
        "public_source_outcome": outcome,
        "machine_judgement_ready": True,
        "machine_verification_decision": _machine_decision(outcome),
        "requires_stage4_evidence_readback": bool(all_hashes),
        "stage4_public_evidence_readback_generation_enabled": False,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    manifest: Mapping[str, Any],
    target_records: list[Mapping[str, Any]],
    sample_records: list[Mapping[str, Any]],
    object_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    fixed_hashes = _dedupe(
        hash_value
        for record in sample_records
        for hash_value in _string_list(record.get("fixed_snapshot_sha256s"))
    )
    return {
        "source_execution_mode": str(manifest.get("execution_mode") or ""),
        "source_execute": bool(manifest.get("execute")),
        "target_execution_bucket_count": len(target_records),
        "project_sample_count": len(sample_records),
        "discovery_candidate_count": sum(_int(record.get("discovery_candidate_count")) for record in target_records),
        "detail_snapshot_count": sum(_int(record.get("detail_snapshot_count")) for record in sample_records),
        "attachment_snapshot_count": sum(_int(record.get("attachment_snapshot_count")) for record in sample_records),
        "fixed_snapshot_sha256_count": len(fixed_hashes),
        "object_storage_sha256_count": len(object_index),
        "target_execution_state_counts": _counts(record.get("target_execution_state") for record in target_records),
        "sample_execution_state_counts": _counts(record.get("target_execution_state") for record in sample_records),
        "sample_document_kind_counts": _counts(record.get("document_kind") for record in sample_records),
        "source_profile_counts": _counts(record.get("source_profile_id") for record in target_records),
        "public_source_outcome_counts": _counts(record.get("public_source_outcome") for record in sample_records),
        "evidence_fixation_state_counts": _counts(record.get("evidence_fixation_state") for record in sample_records),
        "machine_verification_decision_counts": _counts(
            record.get("machine_verification_decision") for record in sample_records
        ),
        "machine_judgement_ready_count": sum(1 for record in sample_records if bool(record.get("machine_judgement_ready"))),
        "stage4_evidence_readback_required_count": sum(
            1 for record in sample_records if bool(record.get("requires_stage4_evidence_readback"))
        ),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


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


def _hashes_for_refs(
    refs: list[Mapping[str, Any]],
    *,
    object_index: Mapping[str, Mapping[str, Any]],
    ref_key: str,
) -> list[str]:
    hashes: list[str] = []
    for ref in refs:
        snapshot_id = str(ref.get(ref_key) or "")
        prefix = snapshot_id.rsplit("-", 1)[-1]
        if not prefix:
            continue
        for sha256 in object_index:
            if sha256.startswith(prefix):
                hashes.append(sha256)
                break
    return _dedupe(hashes)


def _target_outcome(state: str, failure_taxonomy: list[str]) -> str:
    if state == "CAPTURED_WITH_SNAPSHOTS":
        return "PUBLIC_SOURCE_HIT_WITH_SNAPSHOT"
    if state == "DISCOVERY_NO_MATCH_REVIEW":
        return "PUBLIC_SOURCE_NO_MATCH_REVIEW"
    if state == "CAPTURE_PARTIAL_REVIEW":
        return "PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW"
    if failure_taxonomy:
        return "PUBLIC_SOURCE_REVIEW_REQUIRED"
    return "PUBLIC_SOURCE_STATE_REVIEW_REQUIRED"


def _sample_outcome(state: str, hashes: list[str]) -> str:
    if hashes:
        return "PUBLIC_SOURCE_HIT_WITH_HASHED_SNAPSHOT"
    if state == "DISCOVERY_NO_MATCH_REVIEW":
        return "PUBLIC_SOURCE_NO_MATCH_REVIEW"
    if state == "CAPTURE_PARTIAL_REVIEW":
        return "PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW"
    return "PUBLIC_SOURCE_REVIEW_REQUIRED"


def _fixation_state(state: str, hashes: list[str]) -> str:
    if hashes:
        return "SNAPSHOT_FILE_HASHED"
    if state == "DISCOVERY_NO_MATCH_REVIEW":
        return "NO_CANDIDATE_TO_HASH"
    return "NO_HASHED_SNAPSHOT_REVIEW_REQUIRED"


def _machine_decision(outcome: str) -> str:
    if outcome == "PUBLIC_SOURCE_HIT_WITH_HASHED_SNAPSHOT":
        return "PUBLIC_SOURCE_SNAPSHOT_CAPTURED_REQUIRES_STAGE4_EVIDENCE_READBACK"
    if outcome == "PUBLIC_SOURCE_NO_MATCH_REVIEW":
        return "CURRENT_PUBLIC_SOURCE_RETURNED_NO_MATCH_NOT_CLEARANCE"
    if outcome == "PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW":
        return "PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_NOT_CLEARANCE"
    return "PUBLIC_SOURCE_REVIEW_REQUIRED_NOT_CLEARANCE"


def _safety() -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _evidence_graph(*, summary: Mapping[str, Any], sample_records: list[Mapping[str, Any]]) -> dict[str, Any]:
    outcome_counts = _mapping(summary.get("public_source_outcome_counts"))
    decision_counts = _mapping(summary.get("machine_verification_decision_counts"))
    hit_count = _int(outcome_counts.get("PUBLIC_SOURCE_HIT_WITH_HASHED_SNAPSHOT"))
    partial_count = _int(outcome_counts.get("PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW"))
    no_match_count = _int(outcome_counts.get("PUBLIC_SOURCE_NO_MATCH_REVIEW"))
    stage4_count = _int(decision_counts.get("PUBLIC_SOURCE_SNAPSHOT_CAPTURED_REQUIRES_STAGE4_EVIDENCE_READBACK"))
    partial_not_clearance_count = _int(decision_counts.get("PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_NOT_CLEARANCE"))
    no_match_not_clearance_count = _int(decision_counts.get("CURRENT_PUBLIC_SOURCE_RETURNED_NO_MATCH_NOT_CLEARANCE"))
    nodes = [
        _graph_node(
            "batch",
            "受控公开源批次",
            f"样本 {summary.get('project_sample_count')} / 目标 {summary.get('target_execution_bucket_count')}",
            "batch",
        ),
        _graph_node(
            "public_sources",
            "公开源执行",
            f"候选 {summary.get('discovery_candidate_count')} / 来源 {len(_mapping(summary.get('source_profile_counts')))}",
            "source",
        ),
        _graph_node(
            "hashed_snapshots",
            "证据 hash 固化",
            f"快照 hash {summary.get('fixed_snapshot_sha256_count')}",
            "evidence",
        ),
        _graph_node(
            "hit_with_hash",
            "命中且已固化",
            f"{hit_count}",
            "outcome",
        ),
        _graph_node(
            "partial_or_blocked",
            "部分阻断",
            f"{partial_count}",
            "outcome",
        ),
        _graph_node(
            "no_match",
            "未命中",
            f"{no_match_count}",
            "outcome",
        ),
        _graph_node(
            "stage4_readback",
            "下一步 Stage4 回读",
            f"{stage4_count}",
            "decision",
        ),
        _graph_node(
            "not_clearance",
            "不能当作放行",
            f"{partial_not_clearance_count + no_match_not_clearance_count}",
            "decision",
        ),
        _graph_node(
            "safety_boundary",
            "安全边界",
            "不客户可见 / 不支付 / 不交付",
            "gate",
        ),
    ]
    edges = [
        _graph_edge("batch", "public_sources", "execute"),
        _graph_edge("public_sources", "hit_with_hash", "hit"),
        _graph_edge("public_sources", "partial_or_blocked", "blocked"),
        _graph_edge("public_sources", "no_match", "no_match"),
        _graph_edge("hit_with_hash", "hashed_snapshots", "fix"),
        _graph_edge("hashed_snapshots", "stage4_readback", "readback_required"),
        _graph_edge("partial_or_blocked", "not_clearance", "review"),
        _graph_edge("no_match", "not_clearance", "review"),
        _graph_edge("batch", "safety_boundary", "guarded"),
    ]
    sample_graph_records = [
        {
            "sample_id": str(record.get("sample_id") or ""),
            "project_id": str(record.get("project_id") or ""),
            "project_name": str(record.get("project_name") or ""),
            "source_profile_id": str(record.get("source_profile_id") or ""),
            "document_kind": str(record.get("document_kind") or ""),
            "evidence_fixation_state": str(record.get("evidence_fixation_state") or ""),
            "fixed_snapshot_sha256_count": len(_string_list(record.get("fixed_snapshot_sha256s"))),
            "public_source_outcome": str(record.get("public_source_outcome") or ""),
            "machine_verification_decision": str(record.get("machine_verification_decision") or ""),
            "requires_stage4_evidence_readback": bool(record.get("requires_stage4_evidence_readback")),
        }
        for record in sample_records
    ]
    graph = {
        "graph_kind": "controlled_live_public_batch_evidence_graph_v1",
        "nodes": nodes,
        "edges": edges,
        "sample_graph_records": sample_graph_records,
    }
    graph["mermaid"] = _mermaid_graph(nodes, edges)
    return graph


def _graph_node(node_id: str, label: str, detail: str, node_type: str) -> dict[str, str]:
    return {"id": node_id, "label": label, "detail": detail, "type": node_type}


def _graph_edge(source: str, target: str, label: str) -> dict[str, str]:
    return {"source": source, "target": target, "label": label}


def _mermaid_graph(nodes: list[Mapping[str, Any]], edges: list[Mapping[str, Any]]) -> str:
    lines = ["flowchart LR"]
    for node in nodes:
        node_id = _mermaid_id(str(node.get("id") or "node"))
        label = _mermaid_label(f"{node.get('label') or ''}\\n{node.get('detail') or ''}")
        lines.append(f'  {node_id}["{label}"]')
    for edge in edges:
        source = _mermaid_id(str(edge.get("source") or "source"))
        target = _mermaid_id(str(edge.get("target") or "target"))
        label = _mermaid_label(str(edge.get("label") or ""))
        lines.append(f"  {source} -- {label} --> {target}")
    return "\n".join(lines)


def _mermaid_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", value)
    text = text.strip("_") or "node"
    if text[0].isdigit():
        text = f"n_{text}"
    return text


def _mermaid_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', "'").replace("\n", "<br/>")


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    graph = _mapping(result.get("evidence_graph"))
    lines = [
        "# Controlled Live Public Batch Evidence Summary",
        "",
        f"- project_sample_count: {summary.get('project_sample_count')}",
        f"- detail_snapshot_count: {summary.get('detail_snapshot_count')}",
        f"- attachment_snapshot_count: {summary.get('attachment_snapshot_count')}",
        f"- fixed_snapshot_sha256_count: {summary.get('fixed_snapshot_sha256_count')}",
        f"- machine_judgement_ready_count: {summary.get('machine_judgement_ready_count')}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- payment_execution_enabled: {str(bool(summary.get('payment_execution_enabled'))).lower()}",
        f"- delivery_execution_enabled: {str(bool(summary.get('delivery_execution_enabled'))).lower()}",
        f"- query_miss_is_not_clearance: {str(bool(summary.get('query_miss_is_not_clearance'))).lower()}",
        "",
        "## Public Source Outcomes",
    ]
    for key, value in _mapping(summary.get("public_source_outcome_counts")).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Machine Decisions"])
    for key, value in _mapping(summary.get("machine_verification_decision_counts")).items():
        lines.append(f"- {key}: {value}")
    mermaid = str(graph.get("mermaid") or "").strip()
    if mermaid:
        lines.extend(["", "## Evidence Graph", "", "```mermaid", mermaid, "```"])
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


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-sample-execution-json", required=True)
    parser.add_argument("--storage-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_controlled_live_public_batch_evidence_summary(
        real_sample_execution_json=args.real_sample_execution_json,
        storage_json=args.storage_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
