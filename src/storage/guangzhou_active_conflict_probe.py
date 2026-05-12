from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from stage4_verification.regional_hard_defect_sources import build_regional_hard_defect_source_plan


GUANGZHOU_ACTIVE_CONFLICT_PROBE_KIND = "guangzhou_active_conflict_probe_v1_manifest"
GUANGZHOU_ACTIVE_CONFLICT_PROBE_VERSION = 1
GUANGZHOU_ACTIVE_CONFLICT_PROBE_ADAPTER_ID = "guangzhou-active-conflict-probe-v1-builder"

DEFAULT_EVIDENCE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-active-conflict-probe-v1")

FORBIDDEN_TERMS = ("在建冲突成立", "冲突成立", "造假成立", "违法成立", "确认本人")


def build_guangzhou_active_conflict_probe(
    *,
    evidence_report_root: str | Path = DEFAULT_EVIDENCE_REPORT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    evidence_report_json: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    evidence_dir = Path(evidence_report_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = Path(evidence_report_json) if evidence_report_json else evidence_dir / "guangzhou-evidence-report-v1.json"
    blocking_reasons: list[str] = []
    evidence_report = _source_manifest(_load_json(report_path, blocking_reasons, "evidence_report_missing"))

    evidence_project_reports = [
        dict(project)
        for project in _list(evidence_report.get("project_reports"))
        if isinstance(project, Mapping)
    ]
    task_records = _task_records_from_evidence_report(
        project_reports=evidence_project_reports,
        created_at=created,
    )
    project_task_records = _project_task_records(
        task_records,
        project_reports=evidence_project_reports,
    )
    manual_check_table = _manual_check_table(task_records)
    summary = _summary(
        task_records=task_records,
        project_task_records=project_task_records,
        blocking_reasons=blocking_reasons,
    )

    manifest = {
        "manifest_version": GUANGZHOU_ACTIVE_CONFLICT_PROBE_VERSION,
        "manifest_kind": GUANGZHOU_ACTIVE_CONFLICT_PROBE_KIND,
        "adapter_id": GUANGZHOU_ACTIVE_CONFLICT_PROBE_ADAPTER_ID,
        "pipeline_stage": "GuangzhouActiveConflictProbeV1",
        "manifest_id": f"GUANGZHOU-ACTIVE-CONFLICT-PROBE-{_fingerprint({'tasks': task_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_evidence_report_root": str(evidence_dir),
        "source_evidence_report_json": str(report_path),
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "project_task_records": project_task_records,
        "task_records": task_records,
        "manual_check_table": manual_check_table,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_active_conflict_probe_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*blocking_reasons, *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangzhou-active-conflict-probe-v1.json").write_text(text, encoding="utf-8")
    return result


def _task_records_from_evidence_report(*, project_reports: list[Mapping[str, Any]], created_at: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for project in project_reports:
        verification = dict(project.get("verification_evidence") or {})
        project_id = str(project.get("project_id") or verification.get("project_id") or "")
        project_name = str(project.get("project_name") or verification.get("project_name") or "")
        candidate_notice_source_urls = _list(verification.get("candidate_notice_source_urls"))
        project_source_urls = _list(verification.get("project_source_urls"))
        for group in _list(verification.get("candidate_group_records")):
            if not isinstance(group, Mapping):
                continue
            person = str(group.get("responsible_person_name") or "").strip()
            if not person:
                continue
            company_variants = _dedupe(
                [
                    *_list(group.get("matched_company_names")),
                    *_list(group.get("candidate_group_members")),
                ]
            )
            candidate_company = company_variants[0] if company_variants else ""
            certificate_no = str(group.get("certificate_no") or "").strip()
            source_plan = build_regional_hard_defect_source_plan(
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "candidate_company": candidate_company,
                    "project_manager_name": person,
                    "project_manager_certificate_no": certificate_no,
                    "source_url": _first_text(candidate_notice_source_urls) or _first_text(project_source_urls),
                    "region_code": "CN-GD",
                }
            )
            task_id = _stable_id(
                "GZ-ACTIVE-CONFLICT-TASK",
                project_id,
                str(group.get("candidate_group_id") or ""),
                person,
                certificate_no,
            )
            records.append(
                {
                    "task_id": task_id,
                    "project_id": project_id,
                    "project_name": project_name,
                    "candidate_group_id": str(group.get("candidate_group_id") or ""),
                    "candidate_group_order": str(group.get("candidate_group_order") or ""),
                    "responsible_person_name": person,
                    "candidate_group_members": _list(group.get("candidate_group_members")),
                    "matched_company_names": _list(group.get("matched_company_names")),
                    "company_query_variants": company_variants,
                    "certificate_no": certificate_no,
                    "candidate_notice_source_urls": _dedupe(candidate_notice_source_urls),
                    "project_source_urls": _dedupe(project_source_urls),
                    "probe_state": "PLAN_ONLY_NOT_EXECUTED",
                    "query_keywords": _query_keywords(
                        project_name=project_name,
                        person=person,
                        companies=company_variants,
                        certificate_no=certificate_no,
                    ),
                    "source_plan": source_plan,
                    "source_entries": _source_entry_summaries(source_plan),
                    "source_category_counts": _counts(
                        source_type
                        for entry in _list(source_plan.get("source_entries"))
                        if isinstance(entry, Mapping)
                        for source_type in _list(entry.get("target_source_types"))
                    ),
                    "missing_source_types": _list(source_plan.get("missing_source_types")),
                    "next_required_runtime_adapters": _list(source_plan.get("next_required_runtime_adapters")),
                    "created_at": created_at,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return records


def _project_task_records(
    task_records: list[Mapping[str, Any]],
    *,
    project_reports: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for task in task_records:
        grouped.setdefault(str(task.get("project_id") or ""), []).append(task)
    records: list[dict[str, Any]] = []
    project_ids = _dedupe(
        [
            *[str(project.get("project_id") or "") for project in project_reports],
            *grouped.keys(),
        ]
    )
    project_name_by_id = {
        str(project.get("project_id") or ""): str(project.get("project_name") or "")
        for project in project_reports
        if str(project.get("project_id") or "")
    }
    for project_id in project_ids:
        tasks = grouped.get(project_id, [])
        records.append(
            {
                "project_id": project_id,
                "project_name": _first_text([project_name_by_id.get(project_id), *[task.get("project_name") for task in tasks]]),
                "task_ids": [str(task.get("task_id") or "") for task in tasks],
                "task_count": len(tasks),
                "responsible_person_names": _dedupe(task.get("responsible_person_name") for task in tasks),
                "company_query_variants": _dedupe(
                    company for task in tasks for company in _list(task.get("company_query_variants"))
                ),
                "missing_source_types": _dedupe(
                    source_type for task in tasks for source_type in _list(task.get("missing_source_types"))
                ),
                "next_required_runtime_adapters": _dedupe(
                    adapter for task in tasks for adapter in _list(task.get("next_required_runtime_adapters"))
                ),
                "probe_state": "PLAN_ONLY_NOT_EXECUTED" if tasks else "NO_RESPONSIBLE_PERSON_TASKS",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return records


def _manual_check_table(task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in task_records:
        rows.append(
            {
                "task_id": task.get("task_id"),
                "project_id": task.get("project_id"),
                "project_name": task.get("project_name"),
                "candidate_group_id": task.get("candidate_group_id"),
                "responsible_person_name": task.get("responsible_person_name"),
                "certificate_no": task.get("certificate_no"),
                "company_query_variants": _list(task.get("company_query_variants")),
                "candidate_notice_source_urls": _list(task.get("candidate_notice_source_urls")),
                "recommended_source_entries": _list(task.get("source_entries")),
                "manual_check_state": "PENDING_MANUAL_OR_ADAPTER_VERIFICATION",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return rows


def _source_entry_summaries(source_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for entry in _list(source_plan.get("source_entries")):
        if not isinstance(entry, Mapping):
            continue
        entries.append(
            {
                "entry_id": str(entry.get("entry_id") or ""),
                "region_code": str(entry.get("region_code") or ""),
                "region_name": str(entry.get("region_name") or ""),
                "source_profile_id": str(entry.get("source_profile_id") or ""),
                "source_name": str(entry.get("source_name") or ""),
                "source_url": str(entry.get("source_url") or ""),
                "target_source_types": _list(entry.get("target_source_types")),
                "query_keys": _list(entry.get("query_keys")),
                "runtime_status": str(entry.get("runtime_status") or ""),
                "next_adapter": str(entry.get("next_adapter") or ""),
            }
        )
    return entries


def _query_keywords(*, project_name: str, person: str, companies: list[str], certificate_no: str) -> list[str]:
    values: list[str] = []
    for company in companies:
        values.extend(
            [
                " ".join(part for part in (company, person) if part),
                " ".join(part for part in (company, person, certificate_no) if part),
                " ".join(part for part in (company, project_name) if part),
            ]
        )
    values.extend([person, certificate_no, project_name])
    return _dedupe(values)


def _summary(
    *,
    task_records: list[Mapping[str, Any]],
    project_task_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    source_category_counts: dict[str, int] = {}
    missing_source_type_counts: dict[str, int] = {}
    for task in task_records:
        for key, value in dict(task.get("source_category_counts") or {}).items():
            source_category_counts[str(key)] = source_category_counts.get(str(key), 0) + int(value)
        for source_type in _list(task.get("missing_source_types")):
            text = str(source_type)
            missing_source_type_counts[text] = missing_source_type_counts.get(text, 0) + 1
    return {
        "probe_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "active_conflict_probe_task_count": len(task_records),
        "project_count": len(project_task_records),
        "project_with_task_count": sum(1 for row in project_task_records if _list(row.get("task_ids"))),
        "project_without_task_count": sum(1 for row in project_task_records if not _list(row.get("task_ids"))),
        "source_category_counts": source_category_counts,
        "missing_source_type_counts": missing_source_type_counts,
        "next_required_runtime_adapters": _dedupe(
            adapter for task in task_records for adapter in _list(task.get("next_required_runtime_adapters"))
        ),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            counts[text] = counts.get(text, 0) + 1
    return counts


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _first_text(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint([str(part or '') for part in parts])[:16]}"


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou ActiveConflictProbe v1.")
    parser.add_argument("--evidence-report-root", default=str(DEFAULT_EVIDENCE_REPORT_ROOT))
    parser.add_argument("--evidence-report-json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_active_conflict_probe(
        evidence_report_root=args.evidence_report_root,
        evidence_report_json=args.evidence_report_json,
        output_root=args.output_root,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
