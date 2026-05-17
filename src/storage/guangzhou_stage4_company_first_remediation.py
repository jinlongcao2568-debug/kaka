from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso
from storage.company_first_stage4_execution import build_company_first_stage4_execution


GUANGZHOU_STAGE4_COMPANY_FIRST_REMEDIATION_KIND = "guangzhou_stage4_company_first_remediation_v1_manifest"
GUANGZHOU_STAGE4_COMPANY_FIRST_REMEDIATION_VERSION = 1
GUANGZHOU_STAGE4_COMPANY_FIRST_REMEDIATION_ADAPTER_ID = "guangzhou-stage4-company-first-remediation-v1-builder"

DEFAULT_PRESSURE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-real-public-stage4-9-pressure-v1")
DEFAULT_RUN_RESULT_JSON = DEFAULT_PRESSURE_ROOT / "run-result.json"
DEFAULT_CANDIDATE_PRESSURE_JSON = DEFAULT_PRESSURE_ROOT / "candidate-pressure-table.json"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-stage4-company-first-remediation-v1")

FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")
ALLOWED_REMEDIATION_STATES = {
    "COMPANY_FIRST_CERTIFICATE_RESOLVED",
    "NAME_ENUMERATION_FALLBACK_REQUIRED",
    "FLOW_08_TARGETED_PARSE_REQUIRED",
    "REVIEW_REQUIRED",
    "UNRESOLVED_NO_MEMBER_MATCHED",
}

ExecutionBuilder = Callable[..., dict[str, Any]]


def build_guangzhou_stage4_company_first_remediation(
    *,
    run_result_json: str | Path = DEFAULT_RUN_RESULT_JSON,
    candidate_pressure_json: str | Path = DEFAULT_CANDIDATE_PRESSURE_JSON,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    execute: bool = True,
    execution_builder: ExecutionBuilder | None = None,
    browser_runner: Any | None = None,
    highway_market_runner: Any | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_result_path = Path(run_result_json)
    candidate_pressure_path = Path(candidate_pressure_json)

    blocking_reasons: list[str] = []
    run_result = _load_json(run_result_path, blocking_reasons, "run_result_missing")
    candidate_pressure = _load_json(candidate_pressure_path, blocking_reasons, "candidate_pressure_missing")

    candidate_options = _candidate_options_by_project(run_result)
    pressure_rows = [
        dict(item)
        for item in list(candidate_pressure.get("records") or [])
        if isinstance(item, Mapping)
    ]
    selected_candidates = [
        _selected_candidate(row, candidate_options)
        for row in pressure_rows
        if _should_select(row)
    ]
    remediation_inputs = _build_stage4_inputs(selected_candidates, created_at=created)

    execution_result: dict[str, Any] = {}
    execution_root = out_dir / "stage4-execution"
    if remediation_inputs["items"]:
        stage4_inputs_path = out_dir / "stage4-remediation-inputs.json"
        stage4_inputs_path.write_text(json.dumps(remediation_inputs, ensure_ascii=False, indent=2), encoding="utf-8")
        builder = execution_builder or build_company_first_stage4_execution
        execution_result = builder(
            input_root=out_dir / "input-placeholder",
            output_root=execution_root,
            stage4_inputs_json=stage4_inputs_path,
            execute=execute,
            browser_runner=browser_runner,
            highway_market_runner=highway_market_runner,
        )

    execution_items_by_group = _execution_items_by_group(execution_result)
    candidate_records = [
        _candidate_record(candidate, execution_items_by_group.get(candidate["candidate_group_id"], []))
        for candidate in selected_candidates
    ]
    summary = _summary(
        candidate_records=candidate_records,
        remediation_inputs=remediation_inputs,
        execution_result=execution_result,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GUANGZHOU_STAGE4_COMPANY_FIRST_REMEDIATION_VERSION,
        "manifest_kind": GUANGZHOU_STAGE4_COMPANY_FIRST_REMEDIATION_KIND,
        "adapter_id": GUANGZHOU_STAGE4_COMPANY_FIRST_REMEDIATION_ADAPTER_ID,
        "pipeline_stage": "GuangzhouStage4CompanyFirstRemediationV1",
        "manifest_id": f"GUANGZHOU-COMPANY-FIRST-REMEDIATION-{_fingerprint({'summary': summary, 'candidates': candidate_records})[:16]}",
        "created_at": created,
        "source_run_result_json": str(run_result_path),
        "source_candidate_pressure_json": str(candidate_pressure_path),
        "execution_root": str(execution_root),
        "stage4_remediation_inputs": remediation_inputs,
        "candidate_records": candidate_records,
        "execution_summary": dict(execution_result.get("summary") or {}),
        "summary": summary,
        "safety": {
            "network_enabled": bool(execute),
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": bool(execute),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_stage4_company_first_remediation_mode": "EXECUTED" if execute else "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _apply_forbidden_term_scan(result)
    _write_json(out_dir / "company-first-remediation-v1.json", result)
    _write_json(out_dir / "company-first-candidate-table.json", {"summary": summary, "records": candidate_records})
    return result


def _should_select(row: Mapping[str, Any]) -> bool:
    return bool(row.get("jzsc_company_first_identity_resolution_required")) or bool(
        str(row.get("responsible_role_gap_code") or "").strip()
    )


def _candidate_options_by_project(run_result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("project_id") or ""): dict(item)
        for item in list(run_result.get("candidate_options") or [])
        if isinstance(item, Mapping) and str(item.get("project_id") or "").strip()
    }


def _selected_candidate(row: Mapping[str, Any], candidates_by_project: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    project_id = str(row.get("project_id") or "")
    candidate = dict(candidates_by_project.get(project_id) or {})
    company_text = str(candidate.get("candidate_company") or row.get("candidate_company") or "").strip()
    members = _candidate_company_members(company_text)
    person_name = _first_non_empty(candidate.get("project_manager_name"), candidate.get("primary_responsible_person_name"))
    group_id = f"CANDIDATE-GROUP-REM-{_fingerprint({'project_id': project_id, 'company': company_text})[:12]}"
    return {
        "project_id": project_id,
        "project_name": str(candidate.get("project_name") or row.get("project_name") or ""),
        "source_url": str(candidate.get("source_url") or row.get("source_url") or ""),
        "candidate_company": company_text,
        "candidate_group_members": members or ([company_text] if company_text else []),
        "candidate_group_id": group_id,
        "responsible_person_name": str(person_name or ""),
        "responsible_role": str(candidate.get("primary_responsible_role") or ""),
        "project_manager_certificate_no": str(candidate.get("project_manager_certificate_no") or ""),
        "project_manager_public_identifier_optional": str(candidate.get("project_manager_public_identifier_optional") or ""),
        "jzsc_company_first_identity_resolution_required": bool(row.get("jzsc_company_first_identity_resolution_required")),
        "responsible_role_gap_code": str(row.get("responsible_role_gap_code") or ""),
        "baseline_candidate_row": dict(row),
        "baseline_candidate_option": candidate,
    }


def _build_stage4_inputs(candidates: list[Mapping[str, Any]], *, created_at: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        person_name = str(candidate.get("responsible_person_name") or "").strip()
        if not person_name:
            continue
        members = list(candidate.get("candidate_group_members") or [])
        for index, member in enumerate(members, start=1):
            company_name = str(member or "").strip()
            if not company_name:
                continue
            items.append(
                {
                    "project_id": candidate.get("project_id"),
                    "project_name": candidate.get("project_name"),
                    "source_07_detail_path": candidate.get("source_url"),
                    "candidate_company_name": company_name,
                    "candidate_group_id": candidate.get("candidate_group_id"),
                    "candidate_group_order": 1,
                    "candidate_group_members": members,
                    "consortium_member_role": "lead" if index == 1 else "member",
                    "responsible_person_name": person_name,
                    "responsible_role": candidate.get("responsible_role") or "project_manager",
                    "certificate_no": candidate.get("project_manager_certificate_no") or "",
                    "person_public_id_optional": candidate.get("project_manager_public_identifier_optional") or "",
                    "opportunity_priority_class": candidate.get("baseline_candidate_option", {}).get("opportunity_priority_class") or "",
                    "created_at": created_at,
                }
            )
    return {
        "manifest_kind": "guangzhou_stage4_company_first_remediation_inputs",
        "created_at": created_at,
        "items": items,
        "summary": {
            "candidate_count": len(candidates),
            "stage4_input_count": len(items),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _execution_items_by_group(execution_result: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    manifest = execution_result.get("manifest") if isinstance(execution_result.get("manifest"), Mapping) else {}
    for item in list(manifest.get("items") or []):
        if not isinstance(item, Mapping):
            continue
        group_id = str(item.get("candidate_group_id") or "")
        if not group_id:
            continue
        grouped.setdefault(group_id, []).append(dict(item))
    return grouped


def _candidate_record(candidate: Mapping[str, Any], execution_items: list[Mapping[str, Any]]) -> dict[str, Any]:
    baseline = dict(candidate.get("baseline_candidate_row") or {})
    person_name = str(candidate.get("responsible_person_name") or "").strip()
    if not person_name:
        return {
            "project_id": candidate.get("project_id"),
            "project_name": candidate.get("project_name"),
            "candidate_company": candidate.get("candidate_company"),
            "candidate_group_members": list(candidate.get("candidate_group_members") or []),
            "remediation_state": "REVIEW_REQUIRED",
            "remediation_target_kind": "RESPONSIBLE_ROLE_GAP_REVIEW",
            "replay_field_writeback": {},
            "recommended_next_action": "run_stage4_source_gap_probe_for_role_identity_completion",
            "jzsc_company_first_identity_resolution_required": bool(
                candidate.get("jzsc_company_first_identity_resolution_required")
            ),
            "responsible_role_gap_code": baseline.get("responsible_role_gap_code") or candidate.get("responsible_role_gap_code") or "",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    if not execution_items:
        return {
            "project_id": candidate.get("project_id"),
            "project_name": candidate.get("project_name"),
            "candidate_company": candidate.get("candidate_company"),
            "candidate_group_members": list(candidate.get("candidate_group_members") or []),
            "remediation_state": "REVIEW_REQUIRED",
            "remediation_target_kind": "COMPANY_FIRST_EXECUTION_MISSING",
            "replay_field_writeback": {},
            "recommended_next_action": "rerun_company_first_identifier_resolution",
            "jzsc_company_first_identity_resolution_required": bool(
                candidate.get("jzsc_company_first_identity_resolution_required")
            ),
            "responsible_role_gap_code": baseline.get("responsible_role_gap_code") or candidate.get("responsible_role_gap_code") or "",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }

    remediation_state = _candidate_remediation_state(execution_items)
    replay_field_writeback = _candidate_replay_writeback(execution_items, baseline)
    next_action = {
        "COMPANY_FIRST_CERTIFICATE_RESOLVED": "replay_with_company_first_writeback",
        "NAME_ENUMERATION_FALLBACK_REQUIRED": "run_name_enumeration_fallback",
        "FLOW_08_TARGETED_PARSE_REQUIRED": "prepare_flow_08_targeted_parse_but_do_not_auto_execute",
        "UNRESOLVED_NO_MEMBER_MATCHED": "keep_internal_review_and_wait_source_probe_or_flow_08",
        "REVIEW_REQUIRED": "keep_internal_review_and_wait_source_probe_or_flow_08",
    }[remediation_state]
    return {
        "project_id": candidate.get("project_id"),
        "project_name": candidate.get("project_name"),
        "candidate_company": candidate.get("candidate_company"),
        "candidate_group_members": list(candidate.get("candidate_group_members") or []),
        "remediation_state": remediation_state,
        "remediation_target_kind": "COMPANY_FIRST_IDENTIFIER_RESOLUTION",
        "execution_item_count": len(execution_items),
        "resolved_company_name_optional": _first_non_empty(
            *[item.get("candidate_group_matched_company_name_optional") for item in execution_items],
            *[item.get("matched_company_name_optional") for item in execution_items],
        ),
        "resolved_certificate_no_optional": _first_non_empty(
            *[item.get("resolved_certificate_no_optional") for item in execution_items],
        ),
        "replay_field_writeback": replay_field_writeback,
        "recommended_next_action": next_action,
        "jzsc_company_first_identity_resolution_required": bool(
            candidate.get("jzsc_company_first_identity_resolution_required")
        ),
        "responsible_role_gap_code": baseline.get("responsible_role_gap_code") or candidate.get("responsible_role_gap_code") or "",
        "raw_stage4_items": [dict(item) for item in execution_items],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_remediation_state(items: list[Mapping[str, Any]]) -> str:
    if any(str(item.get("supplement_after_execution_state") or "") == "COMPANY_FIRST_CERTIFICATE_RESOLVED" for item in items):
        return "COMPANY_FIRST_CERTIFICATE_RESOLVED"
    if any(str(item.get("supplement_after_execution_state") or "") == "FLOW_08_TARGETED_PARSE_REQUIRED" for item in items):
        return "FLOW_08_TARGETED_PARSE_REQUIRED"
    if any(str(item.get("supplement_after_execution_state") or "") == "NAME_ENUMERATION_FALLBACK_REQUIRED" for item in items):
        return "NAME_ENUMERATION_FALLBACK_REQUIRED"
    if all(str(item.get("candidate_group_resolution_state") or "") == "UNRESOLVED_NO_MEMBER_MATCHED" for item in items):
        return "UNRESOLVED_NO_MEMBER_MATCHED"
    return "REVIEW_REQUIRED"


def _candidate_replay_writeback(items: list[Mapping[str, Any]], baseline: Mapping[str, Any]) -> dict[str, Any]:
    resolved = next(
        (
            dict(item)
            for item in items
            if str(item.get("supplement_after_execution_state") or "") == "COMPANY_FIRST_CERTIFICATE_RESOLVED"
        ),
        {},
    )
    if not resolved:
        return {}
    person_name = str(resolved.get("responsible_person_name") or baseline.get("primary_responsible_person_name") or "")
    writeback = {
        "project_manager_certificate_no": str(resolved.get("resolved_certificate_no_optional") or ""),
        "project_manager_certificate_no_parse_state": "P2_COMPANY_FIRST_STAGE4_REMEDIATION",
        "project_manager_public_identifier_optional": str(
            resolved.get("person_public_id_optional") or resolved.get("resolved_certificate_no_optional") or ""
        ),
        "project_manager_name": person_name,
        "project_manager_name_parse_state": "P2_COMPANY_FIRST_STAGE4_REMEDIATION",
        "primary_responsible_person_name": str(
            baseline.get("primary_responsible_person_name") or person_name or ""
        ),
        "primary_responsible_person_name_parse_state": "P2_COMPANY_FIRST_STAGE4_REMEDIATION",
        "responsible_role_gap_code": "",
        "stage4_company_first_remediation_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
    }
    return {key: value for key, value in writeback.items() if str(value or "").strip() or key == "responsible_role_gap_code"}


def _summary(
    *,
    candidate_records: list[Mapping[str, Any]],
    remediation_inputs: Mapping[str, Any],
    execution_result: Mapping[str, Any],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    remediation_state_counts = _counts(record.get("remediation_state") for record in candidate_records)
    return {
        "candidate_count": len(candidate_records),
        "company_first_candidate_count": sum(
            1 for record in candidate_records if record.get("remediation_target_kind") == "COMPANY_FIRST_IDENTIFIER_RESOLUTION"
        ),
        "role_gap_candidate_count": sum(
            1 for record in candidate_records if record.get("responsible_role_gap_code")
        ),
        "executable_candidate_count": _as_int(remediation_inputs.get("summary", {}).get("candidate_count")),
        "stage4_input_count": _as_int(remediation_inputs.get("summary", {}).get("stage4_input_count")),
        "remediation_state_counts": remediation_state_counts,
        "flow_08_targeted_parse_required_count": remediation_state_counts.get("FLOW_08_TARGETED_PARSE_REQUIRED", 0),
        "execution_summary": dict(execution_result.get("summary") or {}),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "forbidden_term_scan_state": "PENDING",
    }


def _candidate_company_members(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[;；]", text)
    members: list[str] = []
    for part in parts:
        cleaned = re.sub(r"^\((?:主|成)\)", "", part.strip())
        cleaned = re.sub(r"^（(?:主|成)）", "", cleaned.strip())
        if cleaned and cleaned not in members:
            members.append(cleaned)
    return members


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _apply_forbidden_term_scan(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    target = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else payload
    if forbidden_hits:
        target["forbidden_term_scan_state"] = "FAIL"
        target["forbidden_term_hits"] = forbidden_hits
        payload["safe_to_execute"] = False
        payload["blocking_reasons"] = [
            *list(payload.get("blocking_reasons") or []),
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
    else:
        target["forbidden_term_scan_state"] = "PASS"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou Stage4 company-first remediation.")
    parser.add_argument("--run-result-json", default=str(DEFAULT_RUN_RESULT_JSON))
    parser.add_argument("--candidate-pressure-json", default=str(DEFAULT_CANDIDATE_PRESSURE_JSON))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_stage4_company_first_remediation(
        run_result_json=args.run_result_json,
        candidate_pressure_json=args.candidate_pressure_json,
        output_root=args.output_root,
        execute=bool(args.execute),
    )
    print(json.dumps(result if args.emit_json else result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
