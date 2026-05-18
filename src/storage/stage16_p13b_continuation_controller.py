from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


STAGE16_P13B_CONTINUATION_KIND = "stage16_p13b_continuation_controller_v1_manifest"
STAGE16_P13B_CONTINUATION_VERSION = 1
STAGE16_P13B_CONTINUATION_ADAPTER_ID = "stage16-p13b-continuation-controller-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage16-p13b-continuation-controller-v1")


def build_stage16_p13b_continuation_controller(
    *,
    stage16_storage_json: str | Path,
    company_first_stage4_inputs_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    storage_path = Path(stage16_storage_json)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    blocking_reasons: list[str] = []

    storage_payload = _load_json(storage_path)
    if not storage_payload:
        blocking_reasons.append("stage16_storage_json_missing_or_invalid")
    refs = _latest_autonomous_run_refs(storage_payload)
    if storage_payload and not refs:
        blocking_reasons.append("operator_autonomous_opportunity_search_run_missing")

    candidate_options = _json_value(refs.get("candidate_options_json"), [])
    closed_loop_results = _json_value(refs.get("closed_loop_results_json"), [])
    closed_by_project = _closed_by_project(closed_loop_results)
    company_first_inputs = _company_first_inputs_by_project(company_first_stage4_inputs_json)
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}

    project_records: list[dict[str, Any]] = []
    p13b_project_records: list[dict[str, Any]] = []
    p13b_candidate_records: list[dict[str, Any]] = []
    for candidate in candidate_options if isinstance(candidate_options, list) else []:
        if not isinstance(candidate, Mapping):
            continue
        project_id = str(candidate.get("project_id") or "").strip()
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue
        closed = closed_by_project.get(project_id, {})
        supplement = company_first_inputs.get(project_id)
        record = _project_continuation_record(
            candidate=candidate,
            closed=closed,
            supplement=supplement,
            created_at=created,
        )
        project_records.append(record)
        if record["continuation_state"] != "READY_FOR_P13B_DATA_GGZY":
            continue
        p13b_project_records.append(_p13b_project_value_record(record))
        p13b_candidate_records.append(_p13b_candidate_group_record(record))

    project_value_table = {
        "summary": {
            "project_count": len(p13b_project_records),
            "source_stage16_project_count": len(project_records),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "records": p13b_project_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    candidate_group_table = {
        "summary": {
            "candidate_group_count": len(p13b_candidate_records),
            "source_stage16_project_count": len(project_records),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "records": p13b_candidate_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = _summary(project_records, p13b_project_records, p13b_candidate_records, blocking_reasons)
    manifest = {
        "manifest_version": STAGE16_P13B_CONTINUATION_VERSION,
        "manifest_kind": STAGE16_P13B_CONTINUATION_KIND,
        "adapter_id": STAGE16_P13B_CONTINUATION_ADAPTER_ID,
        "pipeline_stage": "Stage16P13BContinuationController",
        "manifest_id": f"STAGE16-P13B-CONT-{_fingerprint({'records': project_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_stage16_storage_json": str(storage_path),
        "source_company_first_stage4_inputs_json": str(company_first_stage4_inputs_json or ""),
        "project_continuation_records": project_records,
        "p13b_project_value_table": project_value_table,
        "p13b_candidate_group_verification_table": candidate_group_table,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage16_p13b_continuation_controller_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _write_json(out_dir / "stage16-p13b-continuation-controller-v1.json", result)
    _write_json(out_dir / "project-continuation-table.json", {"summary": summary, "records": project_records})
    _write_json(out_dir / "project-value-table.json", project_value_table)
    _write_json(out_dir / "candidate-group-verification-table.json", candidate_group_table)
    return result


def _project_continuation_record(
    *,
    candidate: Mapping[str, Any],
    closed: Mapping[str, Any],
    supplement: Mapping[str, Any] | None,
    created_at: str,
) -> dict[str, Any]:
    project_id = str(candidate.get("project_id") or "").strip()
    project_name = str(candidate.get("project_name") or "").strip()
    readback = closed.get("real_public_stage4_9_readback") if isinstance(closed.get("real_public_stage4_9_readback"), Mapping) else {}
    priority_class = str(candidate.get("opportunity_priority_class") or "").strip()
    lane = str(candidate.get("engineering_work_lane") or "").strip()
    source_url = str(candidate.get("source_url") or "").strip()
    company_text = str(candidate.get("candidate_company") or "").strip()
    candidate_companies = _split_companies(company_text)
    responsible_person = _responsible_person(candidate, supplement)
    certificate_no = _certificate_no(candidate, supplement)
    current_project_time_window = _current_project_time_window(candidate, readback, supplement)
    person_public_id = str((supplement or {}).get("person_public_id_optional") or "").strip()
    group_members = _group_members(candidate_companies, supplement)
    group_id = str((supplement or {}).get("candidate_group_id") or "").strip()
    if not group_id and group_members:
        group_id = f"CANDIDATE-GROUP-{_project_key(project_id) or _fingerprint(project_id)[:12]}-P13B-1"
    state, next_action, reasons = _continuation_state(
        candidate=candidate,
        readback=readback,
        supplement=supplement,
        responsible_person=responsible_person,
        certificate_no=certificate_no,
        priority_class=priority_class,
        lane=lane,
    )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "source_url": source_url,
        "candidate_company_text": company_text,
        "candidate_group_id": group_id,
        "candidate_group_members": group_members,
        "responsible_person_name": responsible_person,
        "project_manager_certificate_no": certificate_no,
        "current_project_time_window": current_project_time_window,
        "person_public_id_optional": person_public_id,
        "engineering_work_lane": lane,
        "opportunity_priority_class": priority_class,
        "stage2_detail_capture_state": str(candidate.get("stage2_detail_capture_state") or ""),
        "stage3_detail_parse_state": str(candidate.get("stage3_detail_parse_state") or ""),
        "stage4_hard_defect_gate_state": str(closed.get("real_world_hard_defect_gate_state") or ""),
        "stage5_rule_gate_status": str(readback.get("stage5_rule_gate_status") or ""),
        "stage5_evidence_gate_status": str(readback.get("stage5_evidence_gate_status") or ""),
        "jzsc_company_first_identity_resolution_required": bool(
            readback.get("jzsc_company_first_identity_resolution_required")
        ),
        "company_first_supplement_applied": bool(supplement),
        "continuation_state": state,
        "recommended_next_action": next_action,
        "review_reasons": reasons,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _continuation_state(
    *,
    candidate: Mapping[str, Any],
    readback: Mapping[str, Any],
    supplement: Mapping[str, Any] | None,
    responsible_person: str,
    certificate_no: str,
    priority_class: str,
    lane: str,
) -> tuple[str, str, list[str]]:
    if str(candidate.get("stage2_detail_capture_state") or "") not in {"FETCHED", "REUSED_EXISTING"}:
        return (
            "WAIT_STAGE2_DETAIL_CAPTURE",
            "increase_detail_capture_limit_or_retry_stage2",
            ["stage2_detail_not_ready"],
        )
    if "DESIGN_SURVEY" in priority_class or lane == "survey_design":
        return (
            "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER",
            "build_design_survey_responsible_overlap_adapter_or_keep_stage4_general_gap_review",
            ["design_survey_not_project_manager_release_mainline"],
        )
    if bool(readback.get("jzsc_company_first_identity_resolution_required")) and not supplement:
        return (
            "WAIT_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT",
            "run_company_first_identifier_resolution_before_p13b",
            ["project_manager_certificate_missing_before_company_first"],
        )
    if not responsible_person:
        return (
            "WAIT_RESPONSIBLE_PERSON_EXTRACTION",
            "targeted_original_or_attachment_readback_for_responsible_person",
            ["responsible_person_missing"],
        )
    if not certificate_no:
        return (
            "WAIT_CERTIFICATE_OR_PUBLIC_IDENTIFIER",
            "run_company_first_or_name_enumeration_before_p13b",
            ["project_manager_certificate_or_public_identifier_missing"],
        )
    return (
        "READY_FOR_P13B_DATA_GGZY",
        "run_data_ggzy_company_history_overlap_triage",
        [],
    )


def _p13b_project_value_record(record: Mapping[str, Any]) -> dict[str, Any]:
    source_url = str(record.get("source_url") or "")
    return {
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "current_project_time_window": dict(record.get("current_project_time_window") or {}),
        "value_closeout_state": "EXTERNAL_CONFLICT_SOURCE_REQUIRED",
        "candidate_notice_source_urls": [source_url] if source_url else [],
        "project_source_urls": [source_url] if source_url else [],
        "source_stage16_continuation_state": record.get("continuation_state"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _p13b_candidate_group_record(record: Mapping[str, Any]) -> dict[str, Any]:
    source_url = str(record.get("source_url") or "")
    return {
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "candidate_group_id": record.get("candidate_group_id"),
        "candidate_group_members": list(record.get("candidate_group_members") or []),
        "responsible_person_name": record.get("responsible_person_name"),
        "certificate_no": record.get("project_manager_certificate_no"),
        "current_project_time_window": dict(record.get("current_project_time_window") or {}),
        "person_public_id_optional": record.get("person_public_id_optional"),
        "source_urls": [source_url] if source_url else [],
        "source_stage16_continuation_state": record.get("continuation_state"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _responsible_person(candidate: Mapping[str, Any], supplement: Mapping[str, Any] | None) -> str:
    if supplement:
        value = str(supplement.get("responsible_person_name") or supplement.get("project_manager_name") or "").strip()
        if value:
            return value
    for key in (
        "project_manager_name",
        "primary_responsible_person_name",
        "chief_supervision_engineer_name",
        "design_lead_name",
        "survey_lead_name",
    ):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def _certificate_no(candidate: Mapping[str, Any], supplement: Mapping[str, Any] | None) -> str:
    if supplement:
        value = str(
            supplement.get("certificate_no")
            or supplement.get("project_manager_certificate_no")
            or ""
        ).strip()
        if value:
            return value
    return str(candidate.get("project_manager_certificate_no") or "").strip()


def _current_project_time_window(
    candidate: Mapping[str, Any],
    readback: Mapping[str, Any],
    supplement: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sources = [
        supplement or {},
        candidate,
        readback,
        readback.get("query_context") if isinstance(readback.get("query_context"), Mapping) else {},
    ]
    for source in sources:
        window = source.get("current_project_time_window") or source.get("project_time_window")
        if isinstance(window, Mapping):
            copied = dict(window)
            if copied:
                copied.setdefault("window_state", "CURRENT_PROJECT_TIME_WINDOW_PASSTHROUGH")
                copied.setdefault("basis", "stage16_upstream_current_project_time_window")
                return copied
    for source in sources:
        period_text = _first_text(
            source,
            (
                "current_project_period_text",
                "project_period_text",
                "construction_period_text",
                "service_period_text",
                "contract_period_text",
                "performance_period_text",
                "period_text",
                "duration_text",
                "工期",
                "服务期",
            ),
        )
        start_at = _first_text(
            source,
            (
                "current_project_start_at",
                "current_project_start_date",
                "project_start_at",
                "project_start_date",
                "contract_start_at",
                "contract_start_date",
                "service_start_at",
                "service_start_date",
            ),
        )
        end_at = _first_text(
            source,
            (
                "current_project_end_at",
                "current_project_end_date",
                "project_end_at",
                "project_end_date",
                "contract_end_at",
                "contract_end_date",
                "service_end_at",
                "service_end_date",
            ),
        )
        if period_text or start_at or end_at:
            return {
                "window_state": "CURRENT_PROJECT_TIME_WINDOW_PASSTHROUGH",
                "start_at": start_at,
                "end_at": end_at,
                "period_text": period_text,
                "basis": "stage16_upstream_period_or_start_end_fields",
            }
    return {}


def _first_text(source: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = source.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _group_members(candidate_companies: list[str], supplement: Mapping[str, Any] | None) -> list[str]:
    if supplement:
        members = _dedupe(str(item or "").strip() for item in list(supplement.get("candidate_group_members") or []))
        if members:
            return members
        company = str(supplement.get("candidate_company_name") or "").strip()
        if company:
            return [company]
    return candidate_companies


def _split_companies(value: Any) -> list[str]:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[一二三四五六七八九十\d]+家[：:]\s*", "", text)
    rows: list[str] = []
    marker_matches = list(
        re.finditer(
            r"(?:^|[,，;；、])\s*[（(]\s*(?:主|成)\s*[）)]\s*(?P<company>[^,，;；、]+)",
            text,
        )
    )
    if marker_matches:
        rows = [match.group("company") for match in marker_matches]
    else:
        rows = re.split(r"[,，;；、]", text)
    return _dedupe(_clean_company_name(row) for row in rows)


def _clean_company_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]\s*", "", text)
    text = re.sub(r"^(?:主|成)[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _company_first_inputs_by_project(path: str | Path | None) -> dict[str, Mapping[str, Any]]:
    if not path:
        return {}
    payload = _load_json(Path(path))
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    out: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        project_id = str(item.get("project_id") or "").strip()
        if project_id and (
            item.get("project_manager_certificate_no")
            or item.get("certificate_no")
            or item.get("person_public_id_optional")
        ):
            out[project_id] = item
    return out


def _summary(
    records: list[Mapping[str, Any]],
    p13b_projects: list[Mapping[str, Any]],
    p13b_candidates: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "source_project_count": len(records),
        "ready_for_p13b_count": len(p13b_projects),
        "p13b_candidate_group_count": len(p13b_candidates),
        "continuation_state_counts": _counts(record.get("continuation_state") for record in records),
        "recommended_next_action_counts": _counts(record.get("recommended_next_action") for record in records),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _latest_autonomous_run_refs(payload: Mapping[str, Any]) -> dict[str, Any]:
    operator_actions = payload.get("operator_actions") if isinstance(payload.get("operator_actions"), Mapping) else {}
    rows = operator_actions.get("operator-autonomous-opportunity-search-runs") if isinstance(operator_actions, Mapping) else []
    if not isinstance(rows, list) or not rows:
        return {}
    latest = rows[-1] if isinstance(rows[-1], Mapping) else {}
    refs = latest.get("object_refs") if isinstance(latest.get("object_refs"), Mapping) else {}
    return dict(refs)


def _closed_by_project(closed_loop_results: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in closed_loop_results if isinstance(closed_loop_results, list) else []:
        if isinstance(row, Mapping) and row.get("project_id"):
            out[str(row.get("project_id"))] = row
    return out


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"JG\d{4}-\d+(?:-\d+)?", text)
    if match:
        return match.group(0)
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe(values: Any) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage1-6 to P13B continuation controller outputs.")
    parser.add_argument("--stage16-storage-json", required=True)
    parser.add_argument("--company-first-stage4-inputs-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_stage16_p13b_continuation_controller(
        stage16_storage_json=args.stage16_storage_json,
        company_first_stage4_inputs_json=args.company_first_stage4_inputs_json or None,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
    )
    output_json = (
        Path(args.output_json)
        if args.output_json
        else Path(args.output_root) / "stage16-p13b-continuation-controller-v1.json"
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "output_root": str(args.output_root),
                    "safe_to_execute": result["safe_to_execute"],
                    "summary": result["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "STAGE16_P13B_CONTINUATION_KIND",
    "build_stage16_p13b_continuation_controller",
]
