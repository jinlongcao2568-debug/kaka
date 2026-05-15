from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_EVIDENCE_VALUE_CLOSEOUT_KIND = "guangzhou_evidence_value_closeout_v1_manifest"
GUANGZHOU_EVIDENCE_VALUE_CLOSEOUT_VERSION = 1
GUANGZHOU_EVIDENCE_VALUE_CLOSEOUT_ADAPTER_ID = "guangzhou-evidence-value-closeout-v1-builder"

DEFAULT_BATCH_STABILITY_ROOT = Path("tmp/evaluation-real-samples/guangzhou-batch-stability-closeout-p11-10-highwayfix-v1")
DEFAULT_EVIDENCE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-p11-10-highwayfix-final-v1")
DEFAULT_READABLE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-readable-report-p11-10-highwayfix-v1")
DEFAULT_INTERNAL_PACKAGE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-internal-evidence-package-manifest-p11-10-highwayfix-p9-v1")
DEFAULT_FIXATION_BACKFILL_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-backfill-p11-10-highwayfix-p9-v1")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-p11-10-highwayfix-merged-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-value-closeout-p12-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
LOW_VALUE_HINTS = ("车辆", "半挂车", "牵引车", "救援服务", "保险", "材料采购", "设备采购")


def build_guangzhou_evidence_value_closeout(
    *,
    batch_stability_root: str | Path = DEFAULT_BATCH_STABILITY_ROOT,
    evidence_report_root: str | Path = DEFAULT_EVIDENCE_REPORT_ROOT,
    readable_report_root: str | Path = DEFAULT_READABLE_REPORT_ROOT,
    internal_package_root: str | Path = DEFAULT_INTERNAL_PACKAGE_ROOT,
    fixation_backfill_root: str | Path = DEFAULT_FIXATION_BACKFILL_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    batch_dir = Path(batch_stability_root)
    evidence_dir = Path(evidence_report_root)
    readable_dir = Path(readable_report_root)
    internal_dir = Path(internal_package_root)
    backfill_dir = Path(fixation_backfill_root)
    stage4_dir = Path(stage4_execution_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    batch_payload = _load_json(batch_dir / "guangzhou-batch-stability-closeout-v1.json", missing_inputs, "batch_stability_closeout_missing")
    evidence_payload = _load_json(evidence_dir / "guangzhou-evidence-report-v1.json", missing_inputs, "evidence_report_missing")
    readable_payload = _load_json(readable_dir / "guangzhou-evidence-readable-report-v1.json", missing_inputs, "readable_report_missing")
    internal_payload = _load_json(internal_dir / "internal-evidence-package-manifest-v1.json", missing_inputs, "internal_evidence_package_missing")
    backfill_payload = _load_json(backfill_dir / "evidence-fixation-backfill-v1.json", missing_inputs, "fixation_backfill_missing")
    stage4_payload = _load_json(stage4_dir / "company-first-stage4-execution.json", missing_inputs, "stage4_execution_missing")

    evidence_manifest = _source_manifest(evidence_payload)
    batch_summary = _summary(batch_payload)
    readable_summary = _summary(readable_payload)
    internal_summary = _summary(internal_payload)
    backfill_summary = _summary(backfill_payload)
    stage4_summary = _summary(stage4_payload)
    project_reports = [dict(item) for item in _list(evidence_manifest.get("project_reports")) if isinstance(item, Mapping)]

    stage4_by_group = _stage4_by_group(stage4_payload)
    project_value_records = [
        _project_value_record(
            project,
            batch_summary=batch_summary,
            readable_summary=readable_summary,
            internal_summary=internal_summary,
            backfill_summary=backfill_summary,
        )
        for project in project_reports
    ]
    candidate_group_records = [
        record
        for project in project_reports
        for record in _candidate_group_records(project, stage4_by_group=stage4_by_group)
    ]
    delivery_gap_records = [
        gap
        for project in project_value_records
        for gap in _delivery_gaps(project, backfill_summary=backfill_summary, internal_summary=internal_summary)
    ]

    value_state_counts = _counts(record.get("value_closeout_state") for record in project_value_records)
    summary = {
        "value_closeout_state": "P12_VALUE_CLOSEOUT_READY" if not missing_inputs else "P12_VALUE_CLOSEOUT_INPUT_BLOCKED",
        "project_count": len(project_value_records),
        "candidate_group_count": len(candidate_group_records),
        "internal_review_ready_project_count": sum(1 for record in project_value_records if record.get("internal_review_ready")),
        "external_conflict_source_required_project_count": value_state_counts.get("EXTERNAL_CONFLICT_SOURCE_REQUIRED", 0),
        "low_value_or_not_applicable_project_count": value_state_counts.get("LOW_VALUE_OR_NOT_APPLICABLE", 0),
        "process_blocked_project_count": value_state_counts.get("PROCESS_BLOCKED_REVIEW", 0),
        "customer_delivery_not_ready_project_count": len(project_value_records),
        "flow_08_targeted_parse_required_count": sum(1 for record in project_value_records if record.get("flow_08_targeted_parse_required")),
        "value_closeout_state_counts": value_state_counts,
        "delivery_gap_count": len(delivery_gap_records),
        "delivery_gap_type_counts": _counts(record.get("gap_type") for record in delivery_gap_records),
        "source_fixation_record_count": _int(internal_summary.get("source_fixation_record_count")),
        "backfilled_no_remaining_gap_count": _int(backfill_summary.get("backfilled_no_remaining_gap_count") or backfill_summary.get("backfilled_record_count")),
        "classified_record_hash_only_count": _int(backfill_summary.get("classified_record_hash_only_count")),
        "unfixable_with_current_artifacts_count": _int(backfill_summary.get("unfixable_with_current_artifacts_count")),
        "p11_batch_closeout_state": str(batch_summary.get("batch_closeout_state") or ""),
        "p11_attachment_snapshot_success_rate": _float(batch_summary.get("attachment_snapshot_success_rate")),
        "p11_stage4_resolved_group_count": _int(batch_summary.get("stage4_resolved_group_count")),
        "stage4_execution_job_count": _int(stage4_summary.get("job_count")),
        "missing_inputs": missing_inputs,
        "forbidden_term_scan_state": "PENDING",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "customer_delivery_ready": False,
    }

    manifest = {
        "manifest_version": GUANGZHOU_EVIDENCE_VALUE_CLOSEOUT_VERSION,
        "manifest_kind": GUANGZHOU_EVIDENCE_VALUE_CLOSEOUT_KIND,
        "adapter_id": GUANGZHOU_EVIDENCE_VALUE_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "GuangzhouEvidenceValueCloseoutV1",
        "manifest_id": f"GUANGZHOU-EVIDENCE-VALUE-{_fingerprint({'summary': summary, 'projects': project_value_records})[:16]}",
        "created_at": created,
        "source_batch_stability_root": str(batch_dir),
        "source_evidence_report_root": str(evidence_dir),
        "source_readable_report_root": str(readable_dir),
        "source_internal_package_root": str(internal_dir),
        "source_fixation_backfill_root": str(backfill_dir),
        "source_stage4_execution_root": str(stage4_dir),
        "summary": summary,
        "project_value_records": project_value_records,
        "candidate_group_verification_records": candidate_group_records,
        "delivery_gap_records": delivery_gap_records,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "customer_delivery_ready": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "customer_delivery_ready": False,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})

    result = {
        "guangzhou_evidence_value_closeout_mode": "BUILT" if not missing_inputs else "INPUT_BLOCKED",
        "safe_to_execute": not missing_inputs,
        "blocking_reasons": missing_inputs,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*missing_inputs, *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
        text = json.dumps(result, ensure_ascii=False, indent=2)

    _write_json(out_dir / "project-value-table.json", {"summary": summary, "records": project_value_records})
    _write_json(out_dir / "candidate-group-verification-table.json", {"summary": summary, "records": candidate_group_records})
    _write_json(out_dir / "delivery-gap-table.json", {"summary": summary, "records": delivery_gap_records})
    (out_dir / "guangzhou-evidence-value-closeout-v1.json").write_text(text, encoding="utf-8")
    return result


def _project_value_record(
    project: Mapping[str, Any],
    *,
    batch_summary: Mapping[str, Any],
    readable_summary: Mapping[str, Any],
    internal_summary: Mapping[str, Any],
    backfill_summary: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = dict(project.get("verification_evidence") or {})
    stability = dict(project.get("process_stability") or {})
    groups = [dict(item) for item in _list(evidence.get("candidate_group_records")) if isinstance(item, Mapping)]
    project_id = str(project.get("project_id") or evidence.get("project_id") or "")
    project_name = str(project.get("project_name") or evidence.get("project_name") or "")
    flow08_required = bool(evidence.get("flow_08_targeted_parse_required"))
    blocking = _hard_blocking_reasons(stability)
    unfixable = _int(backfill_summary.get("unfixable_with_current_artifacts_count"))
    resolved_groups = sum(1 for group in groups if _group_resolved(group))
    low_value = _low_value_project(project_name, groups)
    official_readback_ready = _int(evidence.get("official_source_readback_ready_count")) + _int(evidence.get("guangdong_local_field_readback_ready_count"))

    if unfixable > 0 or flow08_required:
        state = "PROCESS_BLOCKED_REVIEW"
    elif low_value:
        state = "LOW_VALUE_OR_NOT_APPLICABLE"
    elif blocking:
        state = "PROCESS_BLOCKED_REVIEW"
    elif groups and resolved_groups == len(groups):
        state = "INTERNAL_REVIEW_READY" if official_readback_ready > 0 else "EXTERNAL_CONFLICT_SOURCE_REQUIRED"
    else:
        state = "PROCESS_BLOCKED_REVIEW"

    return {
        "project_id": project_id,
        "project_name": project_name,
        "value_closeout_state": state,
        "internal_review_ready": state in {"INTERNAL_REVIEW_READY", "EXTERNAL_CONFLICT_SOURCE_REQUIRED"},
        "customer_delivery_state": "CUSTOMER_DELIVERY_NOT_READY",
        "candidate_group_count": len(groups),
        "resolved_candidate_group_count": resolved_groups,
        "flow_08_present": bool((evidence.get("flow_08_registry") or {}).get("flow_08_present")),
        "flow_08_targeted_parse_required": flow08_required,
        "candidate_notice_source_urls": _list(evidence.get("candidate_notice_source_urls")),
        "project_source_urls": _list(evidence.get("project_source_urls")),
        "main_value_signals": _value_signals(evidence=evidence, groups=groups, official_readback_ready=official_readback_ready),
        "missing_value_inputs": _missing_value_inputs(
            state=state,
            flow08_required=flow08_required,
            official_readback_ready=official_readback_ready,
            blocking=blocking,
            unfixable=unfixable,
        ),
        "recommended_next_actions": _next_actions_for_state(state),
        "p11_batch_closeout_state": str(batch_summary.get("batch_closeout_state") or ""),
        "readable_report_state": str(readable_summary.get("report_state") or ""),
        "source_fixation_state": {
            "source_fixation_record_count": _int(internal_summary.get("source_fixation_record_count")),
            "backfilled_no_remaining_gap_count": _int(backfill_summary.get("backfilled_no_remaining_gap_count") or backfill_summary.get("backfilled_record_count")),
            "classified_record_hash_only_count": _int(backfill_summary.get("classified_record_hash_only_count")),
            "unfixable_with_current_artifacts_count": unfixable,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_group_records(project: Mapping[str, Any], *, stage4_by_group: Mapping[str, list[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    evidence = dict(project.get("verification_evidence") or {})
    out: list[dict[str, Any]] = []
    for group in _list(evidence.get("candidate_group_records")):
        if not isinstance(group, Mapping):
            continue
        group_id = str(group.get("candidate_group_id") or "")
        stage4_records = [dict(item) for item in stage4_by_group.get(group_id, [])]
        member_records = _list(group.get("member_records"))
        out.append(
            {
                "project_id": str(project.get("project_id") or ""),
                "project_name": str(project.get("project_name") or ""),
                "candidate_group_id": group_id,
                "candidate_group_order": str(group.get("candidate_group_order") or ""),
                "candidate_group_members": _dedupe([*_list(group.get("candidate_group_members")), *_list(group.get("matched_company_names"))]),
                "responsible_person_name": str(group.get("responsible_person_name") or ""),
                "certificate_no": str(group.get("certificate_no") or ""),
                "registered_unit_names": _dedupe(
                    [
                        str(record.get("registered_unit_name_optional") or "")
                        for record in [*member_records, *stage4_records]
                        if isinstance(record, Mapping)
                    ]
                ),
                "public_registration_match_state": "PUBLIC_REGISTRATION_MATCHED" if _group_resolved(group) else "PUBLIC_REGISTRATION_REVIEW_REQUIRED",
                "flow_08_targeted_parse_required": bool(group.get("flow_08_targeted_parse_required")),
                "source_urls": _list(evidence.get("candidate_notice_source_urls")),
                "stage4_route_ids": _dedupe(str(record.get("stage4_resolution_route") or record.get("provider_id") or "") for record in stage4_records),
                "stage4_readback_states": _dedupe(str(record.get("readback_state") or "") for record in stage4_records),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return out


def _delivery_gaps(
    project: Mapping[str, Any],
    *,
    backfill_summary: Mapping[str, Any],
    internal_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    project_id = str(project.get("project_id") or "")
    state = str(project.get("value_closeout_state") or "")
    gaps = [
        ("CUSTOMER_APPROVAL_REQUIRED", "客户交付前需要审批链放行"),
        ("CUSTOMER_WORDING_REVIEW_REQUIRED", "客户版措辞需要脱敏和边界复核"),
        ("TRUSTED_TIMESTAMP_RESERVED", "可信时间戳/存证编号仍是后置能力"),
        ("NOTARY_RESERVED", "公证能力仍是后置能力"),
    ]
    if state == "EXTERNAL_CONFLICT_SOURCE_REQUIRED":
        gaps.append(("EXTERNAL_ACTIVE_CONFLICT_SOURCE_REQUIRED", "需补施工许可、合同备案、竣工验收、项目经理变更、处罚投诉等外部在建/履约源"))
    if state == "PROCESS_BLOCKED_REVIEW":
        gaps.append(("PROCESS_BLOCKED_REVIEW", "流程、核验或证据固化仍需按 taxonomy 处理"))
    if project.get("flow_08_targeted_parse_required"):
        gaps.append(("FLOW_08_TARGETED_PARSE_REQUIRED", "已触发 08 定向解析，完成前不得进入交付"))
    if _int(backfill_summary.get("classified_record_hash_only_count")) > 0:
        gaps.append(("RECORD_HASH_ONLY_EXPLANATION_REQUIRED", "记录级 hash 需要在交付前说明其不等同于源内容完整 hash"))
    if _int(internal_summary.get("trusted_timestamp_state") == "RESERVED_NOT_IMPLEMENTED"):
        gaps.append(("TRUSTED_TIMESTAMP_NOT_IMPLEMENTED", "可信时间戳未实现"))

    return [
        {
            "project_id": project_id,
            "project_name": str(project.get("project_name") or ""),
            "gap_type": gap_type,
            "gap_description": description,
            "customer_delivery_blocker": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for gap_type, description in gaps
    ]


def _value_signals(*, evidence: Mapping[str, Any], groups: list[Mapping[str, Any]], official_readback_ready: int) -> list[str]:
    signals: list[str] = []
    if groups:
        signals.append("candidate_group_public_registration_chain_present")
    if all(_group_resolved(group) for group in groups) and groups:
        signals.append("candidate_groups_resolved_by_public_registration")
    if official_readback_ready > 0:
        signals.append("official_or_local_readback_present")
    if evidence.get("flow_08_targeted_parse_required"):
        signals.append("flow_08_targeted_parse_triggered")
    if not evidence.get("flow_08_targeted_parse_required"):
        signals.append("flow_08_registered_as_backup_not_default_parse")
    return signals


def _missing_value_inputs(
    *,
    state: str,
    flow08_required: bool,
    official_readback_ready: int,
    blocking: list[Any],
    unfixable: int,
) -> list[str]:
    missing: list[str] = []
    if state == "LOW_VALUE_OR_NOT_APPLICABLE":
        return ["commercial_value_review"]
    if state == "EXTERNAL_CONFLICT_SOURCE_REQUIRED" and official_readback_ready == 0:
        missing.append("external_active_conflict_source_readback")
    if flow08_required:
        missing.append("flow_08_targeted_parse_completion")
    if blocking:
        missing.append("process_blocking_reason_review")
    if unfixable > 0:
        missing.append("source_fixation_unfixable_gap_repair")
    return missing


def _hard_blocking_reasons(stability: Mapping[str, Any]) -> list[Any]:
    reasons = _list(stability.get("closeout_blocking_reasons"))
    failure = {str(item or "") for item in _list(stability.get("failure_taxonomy"))}
    hard: list[Any] = []
    for reason in reasons:
        text = str(reason or "")
        if text == "attachment_download_incomplete" and failure <= {"DEFERRED_BY_DOWNLOAD_REPAIR_LIMIT"}:
            continue
        hard.append(reason)
    return hard


def _next_actions_for_state(state: str) -> list[str]:
    mapping = {
        "INTERNAL_REVIEW_READY": ["internal_reviewer_check", "delivery_boundary_review"],
        "EXTERNAL_CONFLICT_SOURCE_REQUIRED": ["run_external_active_conflict_source_probe", "internal_reviewer_check"],
        "LOW_VALUE_OR_NOT_APPLICABLE": ["mark_low_priority_or_skip_sales", "keep_process_record"],
        "PROCESS_BLOCKED_REVIEW": ["repair_blocking_taxonomy", "rerun_value_closeout"],
    }
    return mapping.get(state, ["internal_review"])


def _low_value_project(project_name: str, groups: list[Mapping[str, Any]]) -> bool:
    if not groups:
        return True
    return any(hint in project_name for hint in LOW_VALUE_HINTS)


def _group_resolved(group: Mapping[str, Any]) -> bool:
    state = str(group.get("group_resolution_state") or "")
    if "RESOLVED" in state:
        return True
    for member in _list(group.get("member_records")):
        if isinstance(member, Mapping) and str(member.get("supplement_after_execution_state") or "").startswith("COMPANY_FIRST_CERTIFICATE_RESOLVED"):
            return True
    return False


def _stage4_by_group(stage4_payload: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    manifest = _source_manifest(stage4_payload)
    out: dict[str, list[Mapping[str, Any]]] = {}
    for item in _list(manifest.get("items") or manifest.get("project_sample_items")):
        if not isinstance(item, Mapping):
            continue
        group_id = str(item.get("candidate_group_id") or "")
        if group_id:
            out.setdefault(group_id, []).append(item)
    return out


def _load_json(path: Path, missing: list[str], reason: str) -> dict[str, Any]:
    if not path.exists():
        missing.append(reason)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        missing.append(reason)
        return {}


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload.get("manifest"), Mapping):
        return payload["manifest"]  # type: ignore[return-value]
    return payload


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload.get("summary"), Mapping):
        return payload["summary"]  # type: ignore[return-value]
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping) and isinstance(manifest.get("summary"), Mapping):
        return manifest["summary"]  # type: ignore[return-value]
    return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if key:
            out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangzhou evidence value closeout v1.")
    parser.add_argument("--batch-stability-root", default=str(DEFAULT_BATCH_STABILITY_ROOT))
    parser.add_argument("--evidence-report-root", default=str(DEFAULT_EVIDENCE_REPORT_ROOT))
    parser.add_argument("--readable-report-root", default=str(DEFAULT_READABLE_REPORT_ROOT))
    parser.add_argument("--internal-package-root", default=str(DEFAULT_INTERNAL_PACKAGE_ROOT))
    parser.add_argument("--fixation-backfill-root", default=str(DEFAULT_FIXATION_BACKFILL_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_guangzhou_evidence_value_closeout(
        batch_stability_root=args.batch_stability_root,
        evidence_report_root=args.evidence_report_root,
        readable_report_root=args.readable_report_root,
        internal_package_root=args.internal_package_root,
        fixation_backfill_root=args.fixation_backfill_root,
        stage4_execution_root=args.stage4_execution_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            "guangzhou evidence value closeout built: "
            f"state={summary.get('value_closeout_state')} "
            f"projects={summary.get('project_count')} "
            f"external_required={summary.get('external_conflict_source_required_project_count')}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
