from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from storage.company_first_certificate_supplement_probe import (
    build_company_first_certificate_supplement_probe,
)


STAGE16_COMPANY_FIRST_BRIDGE_MANIFEST_KIND = "stage16_company_first_supplement_bridge_manifest"
STAGE16_COMPANY_FIRST_BRIDGE_VERSION = 1
STAGE16_COMPANY_FIRST_BRIDGE_ADAPTER_ID = "stage16-company-first-supplement-bridge-v1"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/stage16-company-first-supplement-v1")


def build_stage16_company_first_supplement_bridge(
    *,
    storage_json: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    company_first_result_state: str = "NOT_RUN",
    name_enumeration_result_state: str = "NOT_RUN",
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    storage_path = Path(storage_json)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    payload = _load_json(storage_path)
    if not payload:
        blocking_reasons.append("stage16_storage_json_missing_or_invalid")

    run_refs = _latest_autonomous_run_refs(payload)
    if payload and not run_refs:
        blocking_reasons.append("operator_autonomous_opportunity_search_run_missing")

    candidate_options = _json_value(run_refs.get("candidate_options_json"), [])
    closed_loop_results = _json_value(run_refs.get("closed_loop_results_json"), [])
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    readbacks_by_project = _readbacks_by_project(closed_loop_results)

    items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in candidate_options if isinstance(candidate_options, list) else []:
        if not isinstance(candidate, Mapping):
            continue
        project_id = str(candidate.get("project_id") or "").strip()
        if selected_projects and _project_key(project_id) not in selected_projects:
            continue
        readback = readbacks_by_project.get(project_id) or {}
        item = _bridge_item_from_candidate(candidate, readback=readback, created_at=created)
        if item:
            items.append(item)
            continue
        skipped.append(
            {
                "project_id": project_id,
                "skip_reason": _skip_reason(candidate, readback),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )

    early_probe_payload = _responsible_person_early_probe_payload(
        items=items,
        storage_path=storage_path,
        created_at=created,
    )
    early_probe_path = out_root / "responsible-person-early-probe.json"
    early_probe_path.write_text(json.dumps(early_probe_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    supplement_result = build_company_first_certificate_supplement_probe(
        input_root=out_root,
        output_root=out_root,
        company_first_result_state=company_first_result_state,
        name_enumeration_result_state=name_enumeration_result_state,
        created_at=created,
    )

    summary = _summary(
        items=items,
        skipped=skipped,
        blocking_reasons=blocking_reasons,
        supplement_result=supplement_result,
    )
    manifest = {
        "manifest_version": STAGE16_COMPANY_FIRST_BRIDGE_VERSION,
        "manifest_kind": STAGE16_COMPANY_FIRST_BRIDGE_MANIFEST_KIND,
        "adapter_id": STAGE16_COMPANY_FIRST_BRIDGE_ADAPTER_ID,
        "pipeline_stage": "Stage16CompanyFirstSupplementBridge",
        "manifest_id": f"STAGE16-COMPANY-FIRST-BRIDGE-{_fingerprint({'items': items, 'summary': summary})[:16]}",
        "created_at": created,
        "source_stage16_storage_json": str(storage_path),
        "source_operator_run_refs_present": bool(run_refs),
        "project_ids": [item["project_id"] for item in items],
        "items": items,
        "skipped_items": skipped,
        "summary": summary,
        "downstream_company_first_supplement_summary": supplement_result.get("summary", {}),
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "no_name_only_final_proof": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage16_company_first_supplement_bridge_mode": "EXECUTED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
        "company_first_certificate_supplement": supplement_result,
        "execution": {
            "executed": True,
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    (out_root / "stage16-company-first-supplement-bridge.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _bridge_item_from_candidate(candidate: Mapping[str, Any], *, readback: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    if not _needs_company_first(candidate, readback):
        return {}
    project_id = str(candidate.get("project_id") or "").strip()
    project_name = str(candidate.get("project_name") or "").strip()
    company_text = str(candidate.get("candidate_company") or "").strip()
    person = _responsible_person(candidate)
    if not (project_id and company_text and person):
        return {}
    companies = _split_consortium_companies(company_text)
    if not companies:
        return {}
    group_id = _candidate_group_id(project_id, companies) if len(companies) > 1 else ""
    group_members = [company["company_name"] for company in companies]
    targets = [
        {
            "candidate_group_id": group_id,
            "candidate_group_order": "1" if group_id else "",
            "candidate_group_members": group_members,
            "candidate_company_name": company["company_name"],
            "candidate_group_primary_company_name": group_members[0] if group_members else company["company_name"],
            "consortium_member_role": company["consortium_member_role"],
            "responsible_person_name": person,
            "certificate_no": "",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for company in companies
    ]
    return {
        "project_id": project_id,
        "project_name": project_name,
        "source_07_detail_path": str(candidate.get("source_url") or ""),
        "candidate_company_candidates": [
            _candidate_value(company["company_name"], f"stage16_candidate_company_{company['consortium_member_role']}")
            for company in companies
        ],
        "responsible_person_candidates": [_candidate_value(person, "stage16_project_manager_name")],
        "certificate_no_candidates": [],
        "candidate_groups": [
            {
                "candidate_group_id": group_id,
                "candidate_group_order": "1" if group_id else "",
                "candidate_group_members": group_members,
                "source_candidate_company_text": company_text,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        ]
        if group_id
        else [],
        "verification_targets": targets,
        "responsible_role": _responsible_role(candidate),
        "early_probe_state": "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED",
        "stage4_readiness_state": "SUPPLEMENT_REQUIRED_COMPANY_FIRST",
        "next_actions": ["RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT", "DO_NOT_RUN_STAGE4_LIVE_WITH_EMPTY_CERTIFICATE"],
        "risk_escalation_state": "LOW_CLUE_REVIEW",
        "flow_08_targeted_parse_required": False,
        "source_stage16_jzsc_company_first_identity_resolution_required": bool(
            readback.get("jzsc_company_first_identity_resolution_required")
        ),
        "source_project_manager_identifier_resolution_state": str(
            readback.get("project_manager_identifier_resolution_state") or ""
        ),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _needs_company_first(candidate: Mapping[str, Any], readback: Mapping[str, Any]) -> bool:
    resolution_state = str(readback.get("project_manager_identifier_resolution_state") or "")
    if bool(readback.get("jzsc_company_first_identity_resolution_required")):
        return True
    if resolution_state == "JZSC_COMPANY_FIRST_REQUIRED":
        return True
    company = str(candidate.get("candidate_company") or "").strip()
    person = _responsible_person(candidate)
    certificate = str(candidate.get("project_manager_certificate_no") or "").strip()
    has_project_manager = bool(str(candidate.get("project_manager_name") or "").strip())
    return bool(company and person and has_project_manager and not certificate)


def _skip_reason(candidate: Mapping[str, Any], readback: Mapping[str, Any]) -> str:
    if not _needs_company_first(candidate, readback):
        return "company_first_not_required"
    if not str(candidate.get("candidate_company") or "").strip():
        return "candidate_company_missing"
    if not _responsible_person(candidate):
        return "responsible_person_missing"
    return "company_first_target_unusable"


def _responsible_person(candidate: Mapping[str, Any]) -> str:
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


def _responsible_role(candidate: Mapping[str, Any]) -> str:
    role = str(candidate.get("primary_responsible_role") or "").strip()
    if role:
        return role
    if str(candidate.get("chief_supervision_engineer_name") or "").strip():
        return "chief_supervision_engineer"
    if str(candidate.get("design_lead_name") or "").strip():
        return "design_lead"
    if str(candidate.get("survey_lead_name") or "").strip():
        return "survey_lead"
    return "project_manager"


def _split_consortium_companies(value: Any) -> list[dict[str, str]]:
    text = _clean_company_text(value)
    if not text:
        return []
    marker_matches = list(
        re.finditer(
            r"(?:^|[,，;；、])\s*[（(]\s*(?P<role>主|成)\s*[）)]\s*(?P<company>[^,，;；、]+)",
            text,
        )
    )
    rows: list[dict[str, str]] = []
    for match in marker_matches:
        company = _clean_company_name(match.group("company"))
        if company:
            rows.append(
                {
                    "company_name": company,
                    "consortium_member_role": "lead" if match.group("role") == "主" else "member",
                }
            )
    if not rows:
        parts = re.split(r"[,，;；、]", text)
        for index, part in enumerate(parts):
            company = _clean_company_name(part)
            if company:
                rows.append(
                    {
                        "company_name": company,
                        "consortium_member_role": "single" if len(parts) == 1 else ("lead" if index == 0 else "member"),
                    }
                )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        company = row["company_name"]
        if company in seen:
            continue
        seen.add(company)
        deduped.append(row)
    if len(deduped) == 1:
        deduped[0]["consortium_member_role"] = "single"
    return deduped


def _clean_company_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[一二三四五六七八九十\d]+家[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _clean_company_name(value: Any) -> str:
    text = _clean_company_text(value)
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]\s*", "", text)
    text = re.sub(r"^(?:主|成)[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _candidate_value(value: str, source: str) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "confidence": 0.72,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_group_id(project_id: str, companies: list[Mapping[str, str]]) -> str:
    return f"CANDIDATE-GROUP-{_project_key(project_id) or _fingerprint(project_id)[:12]}-COMPANY-FIRST-1"


def _responsible_person_early_probe_payload(
    *,
    items: list[Mapping[str, Any]],
    storage_path: Path,
    created_at: str,
) -> dict[str, Any]:
    return {
        "manifest": {
            "manifest_version": 1,
            "manifest_kind": "responsible_person_early_probe_manifest",
            "adapter_id": STAGE16_COMPANY_FIRST_BRIDGE_ADAPTER_ID,
            "pipeline_stage": "ResponsiblePersonEarlyProbeCompatFromStage16",
            "created_at": created_at,
            "source_stage16_storage_json": str(storage_path),
            "items": list(items),
            "project_sample_items": list(items),
            "summary": {
                "project_count": len(items),
                "company_first_certificate_supplement_required_count": len(items),
                "stage4_input_count": 0,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    }


def _summary(
    *,
    items: list[Mapping[str, Any]],
    skipped: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    supplement_result: Mapping[str, Any],
) -> dict[str, Any]:
    supplement_summary = supplement_result.get("summary") if isinstance(supplement_result.get("summary"), Mapping) else {}
    return {
        "bridge_item_count": len(items),
        "skipped_item_count": len(skipped),
        "project_count": len({item.get("project_id") for item in items}),
        "verification_target_count": sum(len(item.get("verification_targets") or []) for item in items),
        "company_first_provider_job_count": int(supplement_summary.get("provider_job_count") or 0),
        "stage4_input_count": int(supplement_summary.get("stage4_input_count") or 0),
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


def _readbacks_by_project(closed_loop_results: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in closed_loop_results if isinstance(closed_loop_results, list) else []:
        if not isinstance(row, Mapping):
            continue
        project_id = str(row.get("project_id") or "").strip()
        readback = row.get("real_public_stage4_9_readback")
        if project_id and isinstance(readback, Mapping):
            out[project_id] = readback
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


def _project_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"JG\d{4}-\d+(?:-\d+)?", text)
    if match:
        return match.group(0)
    return text.rsplit("-", 1)[-1] if text.startswith("PROJ-") else text


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge Stage1-6 live storage into company-first supplement jobs.")
    parser.add_argument("--storage-json", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--company-first-result-state", default="NOT_RUN")
    parser.add_argument("--name-enumeration-result-state", default="NOT_RUN")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_stage16_company_first_supplement_bridge(
        storage_json=args.storage_json,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        company_first_result_state=args.company_first_result_state,
        name_enumeration_result_state=args.name_enumeration_result_state,
    )
    output_json = (
        Path(args.output_json)
        if args.output_json
        else Path(args.output_root) / "stage16-company-first-supplement-bridge.json"
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
                    "bridge_item_count": result["summary"]["bridge_item_count"],
                    "company_first_provider_job_count": result["summary"]["company_first_provider_job_count"],
                    "stage4_input_count": result["summary"]["stage4_input_count"],
                    "blocking_reasons": result["blocking_reasons"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "STAGE16_COMPANY_FIRST_BRIDGE_MANIFEST_KIND",
    "build_stage16_company_first_supplement_bridge",
]
