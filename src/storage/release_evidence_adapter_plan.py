from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


RELEASE_EVIDENCE_ADAPTER_PLAN_KIND = "release_evidence_adapter_plan_v1_manifest"
RELEASE_EVIDENCE_ADAPTER_PLAN_VERSION = 1
RELEASE_EVIDENCE_ADAPTER_PLAN_ADAPTER_ID = "release-evidence-adapter-plan-v1"

DEFAULT_BATCH_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/evidence-batch-closeout-v1")
DEFAULT_P13B_OPERATIONAL_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/p13b-operational-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/release-evidence-adapter-plan-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
ALLOWED_ADAPTER_RESULT_STATES = ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"]

SOURCE_TARGET_ALIASES = {
    "construction_permit": "construction_permit",
    "construction_permit_change": "project_manager_change_notice",
    "contract_public_info": "contract_performance",
    "contract_public_record": "contract_performance",
    "contract_filing": "contract_performance",
    "contract_filing_or_contract_public_info": "contract_performance",
    "contract_filing_or_contract_credit_info": "contract_performance",
    "contract_credit_info": "contract_performance",
    "completion_filing": "completion_acceptance",
    "completion_or_acceptance_filing": "completion_acceptance",
    "completion_acceptance_or_completion_filing": "completion_acceptance",
    "project_manager_change_notice": "project_manager_change_notice",
    "project_manager_change_notice_or_permit_change": "project_manager_change_notice",
}

TARGET_POLICY = {
    "construction_permit": {
        "evidence_family": "B_ENHANCEMENT_OFFICIAL_READBACK",
        "source_role": "permit_or_license_window_enhancement",
    },
    "contract_performance": {
        "evidence_family": "B_ENHANCEMENT_OFFICIAL_READBACK",
        "source_role": "contract_or_performance_window_enhancement",
    },
    "completion_acceptance": {
        "evidence_family": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
        "source_role": "completion_or_acceptance_release_explanation",
    },
    "project_manager_change_notice": {
        "evidence_family": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
        "source_role": "project_manager_change_or_responsibility_window_split",
    },
}


def build_release_evidence_adapter_plan(
    *,
    batch_closeout_json: str | Path | None = None,
    batch_closeout_root: str | Path = DEFAULT_BATCH_CLOSEOUT_ROOT,
    p13b_operational_closeout_json: str | Path | None = None,
    p13b_operational_closeout_root: str | Path | None = DEFAULT_P13B_OPERATIONAL_CLOSEOUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    batch_path = Path(batch_closeout_json) if batch_closeout_json else Path(batch_closeout_root) / "evidence-batch-closeout-v1.json"
    batch_payload = _load_json(batch_path, blocking_reasons, "evidence_batch_closeout_missing_or_invalid")
    batch_manifest = _source_manifest(batch_payload)

    operational_path = _resolve_optional_json(
        explicit_json=p13b_operational_closeout_json,
        root=p13b_operational_closeout_root,
        default_file_name="p13b-operational-closeout-v1.json",
    )
    operational_payload = _load_json(operational_path, [], "p13b_operational_closeout_missing_or_invalid") if operational_path else {}
    operational_manifest = _source_manifest(operational_payload)

    closeout_records = [
        dict(record)
        for record in _list(batch_manifest.get("closeout_records"))
        if isinstance(record, Mapping)
    ]
    source_task_records = [
        dict(record)
        for record in _list(operational_manifest.get("release_evidence_probe_task_records"))
        if isinstance(record, Mapping)
    ]
    source_plan_records = [
        dict(record)
        for record in _list(operational_manifest.get("release_evidence_probe_plan_records"))
        if isinstance(record, Mapping)
    ]
    source_tasks_by_project = _tasks_by_project(source_task_records)
    source_plans_by_project = _records_by_project(source_plan_records)
    project_plan_records = [
        _project_plan_record(
            closeout=record,
            source_tasks=source_tasks_by_project.get(str(record.get("project_id") or ""), []),
            source_plan=source_plans_by_project.get(str(record.get("project_id") or ""), {}),
            created_at=created,
        )
        for record in closeout_records
    ]
    adapter_task_records = [
        task
        for closeout in closeout_records
        for task in _adapter_tasks_for_project(
            closeout=closeout,
            source_tasks=source_tasks_by_project.get(str(closeout.get("project_id") or ""), []),
            source_plan=source_plans_by_project.get(str(closeout.get("project_id") or ""), {}),
            created_at=created,
        )
    ]
    summary = _summary(
        project_plan_records=project_plan_records,
        adapter_task_records=adapter_task_records,
        blocking_reasons=blocking_reasons,
        operational_supplied=bool(operational_manifest),
    )
    manifest = {
        "manifest_version": RELEASE_EVIDENCE_ADAPTER_PLAN_VERSION,
        "manifest_kind": RELEASE_EVIDENCE_ADAPTER_PLAN_KIND,
        "adapter_id": RELEASE_EVIDENCE_ADAPTER_PLAN_ADAPTER_ID,
        "pipeline_stage": "ReleaseEvidenceAdapterPlanV1",
        "manifest_id": f"RELEASE-EVIDENCE-ADAPTER-PLAN-{_fingerprint({'summary': summary, 'tasks': adapter_task_records})[:16]}",
        "created_at": created,
        "source_batch_closeout_json": str(batch_path),
        "source_batch_closeout_manifest_id": str(batch_manifest.get("manifest_id") or ""),
        "source_p13b_operational_closeout_json": str(operational_path or ""),
        "source_p13b_operational_closeout_manifest_id": str(operational_manifest.get("manifest_id") or ""),
        "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
        "target_policy": TARGET_POLICY,
        "project_release_evidence_plan_records": project_plan_records,
        "release_evidence_adapter_task_records": adapter_task_records,
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
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }
    result = {
        "release_evidence_adapter_plan_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, project_plan_records, adapter_task_records)
    return result


def _project_plan_record(
    *,
    closeout: Mapping[str, Any],
    source_tasks: list[Mapping[str, Any]],
    source_plan: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    project_id = str(closeout.get("project_id") or "")
    closeout_state = str(closeout.get("closeout_state") or "")
    is_a_signal = closeout_state == "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW" or str(
        closeout.get("evidence_grade") or ""
    ).startswith("A_")
    normalized_targets = _task_target_types(source_tasks)
    if is_a_signal and source_tasks:
        plan_state = "RELEASE_EVIDENCE_ADAPTER_TASKS_PLANNED"
        next_action = "run_release_evidence_adapters_when_live_approved"
    elif is_a_signal:
        plan_state = "RELEASE_EVIDENCE_SOURCE_PLAN_REQUIRED"
        next_action = "build_p13b_operational_closeout_or_region_release_source_plan"
    else:
        plan_state = "NO_A_SIGNAL_RELEASE_EVIDENCE_NOT_PLANNED"
        next_action = str(closeout.get("next_action_label") or "keep_internal_review_without_release_adapter_plan")
    return {
        "release_evidence_project_plan_id": _stable_id("REL-EVIDENCE-PROJECT-PLAN", project_id, closeout_state),
        "project_id": project_id,
        "project_name": str(closeout.get("project_name") or ""),
        "closeout_state": closeout_state,
        "evidence_state": str(closeout.get("evidence_state") or ""),
        "evidence_grade": str(closeout.get("evidence_grade") or ""),
        "release_evidence_project_plan_state": plan_state,
        "source_release_evidence_probe_task_count": len(source_tasks),
        "normalized_target_types": normalized_targets,
        "release_evidence_query_region_code": str(
            source_plan.get("release_evidence_query_region_code")
            or _first_non_empty(task.get("release_evidence_query_region_code") for task in source_tasks)
        ),
        "release_evidence_query_region_basis": str(
            source_plan.get("release_evidence_query_region_basis")
            or _first_non_empty(task.get("release_evidence_query_region_basis") for task in source_tasks)
        ),
        "local_housing_authority_adapter_scope": str(
            source_plan.get("local_housing_authority_adapter_scope")
            or _first_non_empty(task.get("local_housing_authority_adapter_scope") for task in source_tasks)
        ),
        "local_housing_authority_adapter_region_code": str(
            source_plan.get("local_housing_authority_adapter_region_code")
            or _first_non_empty(task.get("local_housing_authority_adapter_region_code") for task in source_tasks)
        ),
        "non_guangdong_release_adapter_rule": str(
            source_plan.get("non_guangdong_release_adapter_rule")
            or _first_non_empty(task.get("non_guangdong_release_adapter_rule") for task in source_tasks)
        ),
        "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
        "recommended_next_action": next_action,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "created_at": created_at,
    }


def _adapter_tasks_for_project(
    *,
    closeout: Mapping[str, Any],
    source_tasks: list[Mapping[str, Any]],
    source_plan: Mapping[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    if str(closeout.get("closeout_state") or "") != "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW" and not str(
        closeout.get("evidence_grade") or ""
    ).startswith("A_"):
        return []
    rows: list[dict[str, Any]] = []
    for source_task in source_tasks:
        for target_type in _normalized_target_types(source_task):
            policy = TARGET_POLICY.get(target_type)
            if not policy:
                continue
            rows.append(
                {
                    "release_evidence_adapter_task_id": _stable_id(
                        "REL-EVIDENCE-ADAPTER-TASK",
                        source_task.get("release_evidence_probe_task_id"),
                        target_type,
                    ),
                    "source_release_evidence_probe_task_id": str(source_task.get("release_evidence_probe_task_id") or ""),
                    "source_release_evidence_probe_plan_id": str(source_task.get("release_evidence_probe_plan_id") or ""),
                    "project_id": str(closeout.get("project_id") or source_task.get("project_id") or ""),
                    "project_name": str(closeout.get("project_name") or source_task.get("project_name") or ""),
                    "candidate_company_name": str(source_task.get("candidate_company_name") or ""),
                    "matched_person_names": _list(source_task.get("matched_person_names")),
                    "release_evidence_target_type": target_type,
                    "release_evidence_grade_on_match": policy["evidence_family"],
                    "release_evidence_source_role": policy["source_role"],
                    "initial_release_evidence_abcd_grade": str(
                        source_task.get("initial_release_evidence_abcd_grade") or "A_STRONG_TIME_OVERLAP_SIGNAL"
                    ),
                    "release_evidence_query_region_code": str(source_task.get("release_evidence_query_region_code") or ""),
                    "release_evidence_query_region_basis": str(source_task.get("release_evidence_query_region_basis") or ""),
                    "local_housing_authority_adapter_scope": str(source_task.get("local_housing_authority_adapter_scope") or ""),
                    "local_housing_authority_adapter_region_code": str(
                        source_task.get("local_housing_authority_adapter_region_code") or ""
                    ),
                    "non_guangdong_release_adapter_rule": str(source_task.get("non_guangdong_release_adapter_rule") or ""),
                    "source_entry_id": str(source_task.get("source_entry_id") or ""),
                    "subsource_id": str(source_task.get("subsource_id") or ""),
                    "source_profile_id": str(source_task.get("source_profile_id") or ""),
                    "source_name": str(source_task.get("source_name") or ""),
                    "source_url": str(source_task.get("source_url") or ""),
                    "api_url": str(source_task.get("api_url") or ""),
                    "official_reference_url": str(source_task.get("official_reference_url") or ""),
                    "trigger_source_url": str(source_task.get("trigger_source_url") or ""),
                    "query_params": dict(source_task.get("query_params") or {}),
                    "next_adapter": str(source_task.get("next_adapter") or ""),
                    "runtime_status": str(source_task.get("runtime_status") or ""),
                    "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
                    "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
                    "matched_means": "public_record_supports_enhancement_or_reverse_explanation_not_legal_conclusion",
                    "not_found_means": "source_query_miss_or_no_public_match_not_clearance",
                    "blocked_means": "source_blocked_or_unavailable_needs_review",
                    "needs_browser_means": "browser_or_authorized_runtime_required_before_field_readback",
                    "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                    "readback_ready": False,
                    "query_miss_is_not_clearance": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "created_at": created_at,
                    "source_plan_region_code": str(source_plan.get("release_evidence_query_region_code") or ""),
                }
            )
    return _dedupe_records(rows, ("source_release_evidence_probe_task_id", "release_evidence_target_type"))


def _task_target_types(source_tasks: list[Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        target_type
        for task in source_tasks
        for target_type in _normalized_target_types(task)
        if target_type in TARGET_POLICY
    )


def _normalized_target_types(task: Mapping[str, Any]) -> list[str]:
    raw_values = [
        *_list(task.get("matched_target_source_types")),
        *_list(task.get("canonical_release_evidence_source_targets")),
        *_list(task.get("requested_release_evidence_source_targets")),
    ]
    return _dedupe(SOURCE_TARGET_ALIASES.get(str(value or ""), str(value or "")) for value in raw_values)


def _summary(
    *,
    project_plan_records: list[Mapping[str, Any]],
    adapter_task_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    operational_supplied: bool,
) -> dict[str, Any]:
    return {
        "release_evidence_adapter_plan_state": "RELEASE_EVIDENCE_ADAPTER_PLAN_READY"
        if not blocking_reasons
        else "RELEASE_EVIDENCE_ADAPTER_PLAN_INPUT_BLOCKED",
        "project_plan_count": len(project_plan_records),
        "project_plan_state_counts": _counts(record.get("release_evidence_project_plan_state") for record in project_plan_records),
        "adapter_task_count": len(adapter_task_records),
        "adapter_task_target_type_counts": _counts(record.get("release_evidence_target_type") for record in adapter_task_records),
        "adapter_task_grade_on_match_counts": _counts(record.get("release_evidence_grade_on_match") for record in adapter_task_records),
        "local_housing_region_counts": _counts(record.get("local_housing_authority_adapter_region_code") for record in adapter_task_records),
        "operational_closeout_supplied": operational_supplied,
        "allowed_adapter_result_states": list(ALLOWED_ADAPTER_RESULT_STATES),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    project_plan_records: list[Mapping[str, Any]],
    adapter_task_records: list[Mapping[str, Any]],
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
    _write_json(out_dir / "release-evidence-project-plan-table.json", {"summary": result["summary"], "records": project_plan_records})
    _write_json(out_dir / "release-evidence-adapter-task-table.json", {"summary": result["summary"], "records": adapter_task_records})
    _write_json(out_dir / "release-evidence-adapter-plan-v1.json", result)


def _resolve_optional_json(*, explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> Path | None:
    if explicit_json:
        return Path(explicit_json)
    if root:
        return Path(root) / default_file_name
    return None


def _load_json(path: Path | None, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if path is None or not path.exists():
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


def _tasks_by_project(records: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out.setdefault(project_id, []).append(record)
    return out


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for record in records:
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            out[project_id] = record
    return out


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


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _dedupe_records(rows: Iterable[Mapping[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _first_non_empty(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint('|'.join(str(part or '') for part in parts))[:12]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Release Evidence Adapter Plan v1.")
    parser.add_argument("--batch-closeout-json", default="")
    parser.add_argument("--batch-closeout-root", default=str(DEFAULT_BATCH_CLOSEOUT_ROOT))
    parser.add_argument("--p13b-operational-closeout-json", default="")
    parser.add_argument("--p13b-operational-closeout-root", default=str(DEFAULT_P13B_OPERATIONAL_CLOSEOUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at", default="")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_release_evidence_adapter_plan(
        batch_closeout_json=args.batch_closeout_json or None,
        batch_closeout_root=args.batch_closeout_root,
        p13b_operational_closeout_json=args.p13b_operational_closeout_json or None,
        p13b_operational_closeout_root=args.p13b_operational_closeout_root or None,
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
    "RELEASE_EVIDENCE_ADAPTER_PLAN_KIND",
    "build_release_evidence_adapter_plan",
]
