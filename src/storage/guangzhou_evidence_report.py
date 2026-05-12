from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_EVIDENCE_REPORT_KIND = "guangzhou_evidence_report_v1_manifest"
GUANGZHOU_EVIDENCE_REPORT_VERSION = 1
GUANGZHOU_EVIDENCE_REPORT_ADAPTER_ID = "guangzhou-evidence-report-v1-builder"

DEFAULT_FLOW_ROOT = Path("tmp/evaluation-real-samples/guangzhou-flowurl-analysis-72h-v1")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/guangzhou-download-human-v1")
DEFAULT_RESPONSIBLE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-responsible-person-early-probe-v3")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v4-merged")
DEFAULT_READINESS_ROOT = Path("tmp/evaluation-real-samples/guangzhou-upstream-readiness-with-stage4-groups-v3")
DEFAULT_ACTIVE_CONFLICT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-active-conflict-probe-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-v1")

FORBIDDEN_TERMS = ("是不是本人", "确认本人", "冲突成立", "造假成立", "违法成立")

ACTIVE_CONFLICT_SOURCE_CATEGORIES = (
    "local_public_resource_candidate_or_award_notices",
    "local_housing_construction_or_administrative_approval_platform",
    "construction_permit",
    "contract_filing",
    "completion_or_acceptance_filing",
    "project_manager_change_notice",
    "administrative_penalty_or_complaint_decision",
    "public_web_clues_with_replayable_source_url",
)


def build_guangzhou_evidence_report(
    *,
    flow_root: str | Path = DEFAULT_FLOW_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    responsible_person_root: str | Path = DEFAULT_RESPONSIBLE_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    readiness_root: str | Path = DEFAULT_READINESS_ROOT,
    active_conflict_probe_root: str | Path = DEFAULT_ACTIVE_CONFLICT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    flow_dir = Path(flow_root)
    download_dir = Path(download_root)
    responsible_dir = Path(responsible_person_root)
    stage4_dir = Path(stage4_execution_root)
    readiness_dir = Path(readiness_root)
    active_conflict_dir = Path(active_conflict_probe_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    flow_manifest = _source_manifest(_load_json(flow_dir / "run-manifest.json", missing_inputs, "flow_run_manifest_missing"))
    analysis_manifest = _source_manifest(_load_json(flow_dir / "analysis-plan.json", [], "analysis_plan_missing"))
    download_manifest = _source_manifest(_load_json(download_dir / "download-probe-manifest.json", missing_inputs, "download_probe_manifest_missing"))
    responsible_manifest = _source_manifest(_load_json(responsible_dir / "responsible-person-early-probe.json", missing_inputs, "responsible_person_early_probe_missing"))
    stage4_manifest = _source_manifest(_load_json(stage4_dir / "company-first-stage4-execution.json", [], "stage4_execution_manifest_missing"))
    readiness_manifest = _source_manifest(_load_json(readiness_dir / "guangzhou-upstream-readiness-report.json", [], "readiness_report_missing"))
    active_conflict_manifest = _source_manifest(_load_json_optional(active_conflict_dir / "guangzhou-active-conflict-probe-v1.json"))

    project_ids = _project_ids(
        flow_manifest,
        analysis_manifest,
        download_manifest,
        responsible_manifest,
        stage4_manifest,
        readiness_manifest,
    )
    project_reports = [
        _project_report(
            project_id=project_id,
            flow_manifest=flow_manifest,
            analysis_manifest=analysis_manifest,
            download_manifest=download_manifest,
            responsible_manifest=responsible_manifest,
            stage4_manifest=stage4_manifest,
            readiness_manifest=readiness_manifest,
            active_conflict_manifest=active_conflict_manifest,
        )
        for project_id in project_ids
    ]
    summary = _summary(
        project_reports=project_reports,
        missing_inputs=missing_inputs,
        active_conflict_manifest=active_conflict_manifest,
    )
    manifest = {
        "manifest_version": GUANGZHOU_EVIDENCE_REPORT_VERSION,
        "manifest_kind": GUANGZHOU_EVIDENCE_REPORT_KIND,
        "adapter_id": GUANGZHOU_EVIDENCE_REPORT_ADAPTER_ID,
        "pipeline_stage": "GuangzhouEvidenceReportV1",
        "manifest_id": f"GUANGZHOU-EVIDENCE-REPORT-{_fingerprint({'projects': project_reports, 'summary': summary})[:16]}",
        "created_at": created,
        "source_flow_root": str(flow_dir),
        "source_download_root": str(download_dir),
        "source_responsible_person_root": str(responsible_dir),
        "source_stage4_execution_root": str(stage4_dir),
        "source_readiness_root": str(readiness_dir),
        "source_active_conflict_probe_root": str(active_conflict_dir),
        "report_sections": [
            "verification_evidence",
            "process_stability",
            "optimization_recommendations",
        ],
        "project_reports": project_reports,
        "summary": summary,
        "safety": {
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
        "guangzhou_evidence_report_mode": "BUILT",
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
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangzhou-evidence-report-v1.json").write_text(text, encoding="utf-8")
    return result


def _project_report(
    *,
    project_id: str,
    flow_manifest: Mapping[str, Any],
    analysis_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    responsible_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
    readiness_manifest: Mapping[str, Any],
    active_conflict_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    flow_items = _items_for_project(flow_manifest, project_id)
    analysis_items = _items_for_project(analysis_manifest, project_id)
    download_items = _items_for_project(download_manifest, project_id)
    responsible_item = _first(_items_for_project(responsible_manifest, project_id))
    stage4_items = _items_for_project(stage4_manifest, project_id)
    readiness_project = _first(_project_records_for_project(readiness_manifest, project_id))
    active_conflict_project = _first(_project_task_records_for_project(active_conflict_manifest, project_id))
    group_records = list(readiness_project.get("candidate_group_verification_records") or [])
    if not group_records:
        group_records = _candidate_groups_from_responsible(responsible_item)

    flow_08_registry = _flow_08_registry(analysis_items=analysis_items, download_items=download_items)
    targeted_parse_required = any(bool(row.get("flow_08_targeted_parse_required")) for row in group_records) or bool(
        responsible_item.get("flow_08_targeted_parse_required")
    )
    verification_evidence = {
        "project_id": project_id,
        "project_name": _project_name(project_id, flow_items, download_items, responsible_item, readiness_project),
        "candidate_group_records": [_group_record(row) for row in group_records],
        "candidate_group_count": len(group_records),
        "resolved_candidate_group_count": sum(1 for row in group_records if "RESOLVED" in str(row.get("group_resolution_state") or "")),
        "public_registration_match_state": _public_registration_state(group_records),
        "flow_08_targeted_parse_required": targeted_parse_required,
        "flow_08_registry": flow_08_registry,
        "candidate_notice_source_urls": _source_urls_for_flow([*flow_items, *download_items], "07"),
        "project_source_urls": _dedupe(row.get("source_url") for row in [*flow_items, *download_items]),
        "active_conflict_probe_tasks": _active_conflict_tasks(project_id=project_id, group_records=group_records),
        "active_conflict_probe_state": (
            "TASKS_READY"
            if active_conflict_project
            else "PLAN_ONLY_TASKS_NOT_BUILT"
        ),
        "active_conflict_probe_task_ids": _list(active_conflict_project.get("task_ids")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    process_stability = {
        "flow_07_present": any(_flow_no(row) == "07" for row in [*flow_items, *download_items]),
        "flow_08_present": flow_08_registry["flow_08_present"],
        "flow_08_default_parse_state": "REGISTER_ONLY_NO_DEFAULT_PARSE",
        "download_probe_flow_count": len(download_items),
        "download_attempted_count": sum(_int(row.get("download_attempted_count")) for row in download_items),
        "attachment_snapshot_count": sum(_int(row.get("attachment_snapshot_count")) for row in download_items),
        "responsible_person_early_probe_state": str(responsible_item.get("early_probe_state") or ""),
        "responsible_person_stage4_readiness_state": str(responsible_item.get("stage4_readiness_state") or ""),
        "stage4_execution_job_count": len(stage4_items),
        "stage4_readback_ready_count": sum(1 for row in stage4_items if str(row.get("stage4_execution_state") or "") == "READBACK_READY"),
        "failure_taxonomy": _dedupe(
            reason
            for row in [*flow_items, *download_items, responsible_item, readiness_project]
            for reason in _list(row.get("failure_taxonomy") or row.get("blocking_layers") or row.get("fail_closed_reasons"))
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    optimization_recommendations = _recommendations(
        verification_evidence=verification_evidence,
        process_stability=process_stability,
    )
    return {
        "project_id": project_id,
        "project_name": verification_evidence["project_name"],
        "verification_evidence": verification_evidence,
        "process_stability": process_stability,
        "optimization_recommendations": optimization_recommendations,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_08_registry(*, analysis_items: list[Mapping[str, Any]], download_items: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [row for row in [*analysis_items, *download_items] if _flow_no(row) == "08"]
    attachment_names: list[str] = []
    attachment_urls: list[str] = []
    for row in rows:
        for ref in _list(row.get("attachment_snapshot_refs")):
            if not isinstance(ref, Mapping):
                continue
            attachment_names.append(str(ref.get("attachment_link_text") or Path(str(ref.get("attachment_url") or "")).name or ""))
            attachment_urls.append(str(ref.get("attachment_url") or ref.get("source_url") or ""))
    return {
        "flow_08_present": bool(rows),
        "source_urls": _dedupe(row.get("source_url") for row in rows),
        "published_dates": _dedupe(row.get("published_date") for row in rows),
        "attachment_count": sum(_int(row.get("listed_attachment_count")) for row in download_items if _flow_no(row) == "08") or len(attachment_urls),
        "attachment_names": _dedupe(attachment_names),
        "attachment_urls": _dedupe(attachment_urls),
        "default_download_policy": "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED",
        "default_parse_depth": "LIST_ONLY",
        "default_parse_required": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _group_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_group_id": str(row.get("candidate_group_id") or ""),
        "candidate_group_order": str(row.get("candidate_group_order") or ""),
        "candidate_group_members": _list(row.get("candidate_group_members")),
        "responsible_person_name": str(row.get("responsible_person_name") or ""),
        "certificate_no": str(row.get("certificate_no") or row.get("resolved_certificate_no_optional") or ""),
        "matched_company_names": _list(row.get("matched_company_names")),
        "group_resolution_state": str(row.get("group_resolution_state") or ""),
        "flow_08_targeted_parse_required": bool(row.get("flow_08_targeted_parse_required")),
        "member_records": _list(row.get("member_records")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_groups_from_responsible(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group in _list(item.get("candidate_groups")):
        if not isinstance(group, Mapping):
            continue
        out.append(
            {
                "candidate_group_id": str(group.get("candidate_group_id") or ""),
                "candidate_group_order": str(group.get("candidate_group_order") or group.get("rank") or ""),
                "candidate_group_members": _list(group.get("candidate_group_members") or group.get("company_names")),
                "responsible_person_name": str(group.get("responsible_person_name") or ""),
                "certificate_no": str(group.get("certificate_no") or ""),
                "matched_company_names": [],
                "group_resolution_state": "PENDING_STAGE4_PUBLIC_REGISTRATION_MATCH",
                "flow_08_targeted_parse_required": bool(item.get("flow_08_targeted_parse_required")),
                "member_records": [],
            }
        )
    return out


def _active_conflict_tasks(*, project_id: str, group_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for group in group_records:
        person = str(group.get("responsible_person_name") or "").strip()
        if not person:
            continue
        companies = _dedupe([*_list(group.get("matched_company_names")), *_list(group.get("candidate_group_members"))])
        tasks.append(
            {
                "project_id": project_id,
                "candidate_group_id": str(group.get("candidate_group_id") or ""),
                "responsible_person_name": person,
                "company_names": companies,
                "probe_state": "PLAN_ONLY_NOT_EXECUTED",
                "source_categories": list(ACTIVE_CONFLICT_SOURCE_CATEGORIES),
                "jzsc_usage_boundary": "AUXILIARY_ONLY_NOT_REALTIME_ACTIVE_CONFLICT_SINGLE_SOURCE",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return tasks


def _recommendations(*, verification_evidence: Mapping[str, Any], process_stability: Mapping[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    if verification_evidence.get("flow_08_targeted_parse_required"):
        recommendations.append(_recommendation("RUN_FLOW_08_TARGETED_PARSE", "存在 08 定向解析触发条件，先按目标文件关键词解析。"))
    elif verification_evidence.get("public_registration_match_state") == "ALL_GROUPS_RESOLVED":
        recommendations.append(_recommendation("READY_FOR_INTERNAL_EVIDENCE_PACKAGE_REVIEW", "候选组公开注册信息已匹配，08 保持登记状态。"))
    else:
        recommendations.append(_recommendation("SUPPLEMENT_PUBLIC_REGISTRATION_MATCH", "公开注册信息匹配仍需补查，暂不扩大 08 解析。"))
    if process_stability.get("failure_taxonomy"):
        recommendations.append(_recommendation("REPAIR_PROCESS_STABILITY_ITEMS", "存在采集、下载或核验过程失败分类，先修可定位失败。"))
    if verification_evidence.get("active_conflict_probe_state") == "TASKS_READY":
        recommendations.append(_recommendation("ACTIVE_CONFLICT_EXTERNAL_SOURCE_TASKS_READY", "已生成地方公开来源待核验任务清单，不用四库单独下结论。"))
    else:
        recommendations.append(_recommendation("BUILD_ACTIVE_CONFLICT_EXTERNAL_SOURCE_PROBE", "按地方公开来源生成在建/履约冲突线索任务，不用四库单独下结论。"))
    return recommendations


def _recommendation(action: str, reason: str) -> dict[str, Any]:
    return {
        "recommended_action": action,
        "reason": reason,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    project_reports: list[Mapping[str, Any]],
    missing_inputs: list[str],
    active_conflict_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    groups = [
        group
        for project in project_reports
        for group in _list(((project.get("verification_evidence") or {}).get("candidate_group_records")))
        if isinstance(group, Mapping)
    ]
    flow_08_required = [
        project
        for project in project_reports
        if bool((project.get("verification_evidence") or {}).get("flow_08_targeted_parse_required"))
    ]
    return {
        "report_state": "READY" if not missing_inputs else "INPUT_BLOCKED",
        "project_count": len(project_reports),
        "candidate_group_count": len(groups),
        "resolved_candidate_group_count": sum(1 for group in groups if "RESOLVED" in str(group.get("group_resolution_state") or "")),
        "flow_08_present_project_count": sum(1 for project in project_reports if bool(((project.get("verification_evidence") or {}).get("flow_08_registry") or {}).get("flow_08_present"))),
        "flow_08_targeted_parse_required_project_count": len(flow_08_required),
        "active_conflict_probe_task_count": sum(len(_list((project.get("verification_evidence") or {}).get("active_conflict_probe_tasks"))) for project in project_reports),
        "active_conflict_external_probe_state": (
            "TASKS_READY"
            if active_conflict_manifest
            else "NOT_BUILT"
        ),
        "active_conflict_external_probe_task_count": _int(
            (active_conflict_manifest.get("summary") or {}).get("active_conflict_probe_task_count")
        ),
        "section_names": ["verification_evidence", "process_stability", "optimization_recommendations"],
        "blocking_reasons": missing_inputs,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _public_registration_state(group_records: list[Mapping[str, Any]]) -> str:
    if not group_records:
        return "NO_CANDIDATE_GROUPS"
    resolved = sum(1 for row in group_records if "RESOLVED" in str(row.get("group_resolution_state") or ""))
    if resolved == len(group_records):
        return "ALL_GROUPS_RESOLVED"
    if resolved:
        return "PARTIAL_GROUPS_RESOLVED"
    return "GROUPS_PENDING_OR_UNRESOLVED"


def _project_ids(*manifests: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for manifest in manifests:
        for key in ("project_sample_items", "items", "project_records"):
            for item in _list(manifest.get(key)):
                if isinstance(item, Mapping):
                    ids.append(str(item.get("project_id") or ""))
    return _dedupe(ids)


def _items_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("project_sample_items", "items"):
        for item in _list(manifest.get(key)):
            if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id:
                out.append(dict(item))
    return out


def _project_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _project_task_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_task_records"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _project_name(project_id: str, *sources: Any) -> str:
    for source in sources:
        if isinstance(source, Mapping):
            text = str(source.get("project_name") or "").strip()
            if text:
                return text
        for item in _list(source):
            if isinstance(item, Mapping):
                text = str(item.get("project_name") or "").strip()
                if text:
                    return text
    return project_id


def _flow_no(row: Mapping[str, Any]) -> str:
    return str(row.get("flow_no") or row.get("guangzhou_flow_no") or "").zfill(2)


def _load_json(path: Path, missing_inputs: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        missing_inputs.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _source_urls_for_flow(rows: list[Mapping[str, Any]], flow_no: str) -> list[str]:
    return _dedupe(row.get("source_url") for row in rows if _flow_no(row) == flow_no)


def _first(items: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(items[0]) if items else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou EvidenceReport v1.")
    parser.add_argument("--flow-root", default=str(DEFAULT_FLOW_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--responsible-person-root", default=str(DEFAULT_RESPONSIBLE_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--readiness-root", default=str(DEFAULT_READINESS_ROOT))
    parser.add_argument("--active-conflict-probe-root", default=str(DEFAULT_ACTIVE_CONFLICT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_evidence_report(
        flow_root=args.flow_root,
        download_root=args.download_root,
        responsible_person_root=args.responsible_person_root,
        stage4_execution_root=args.stage4_execution_root,
        readiness_root=args.readiness_root,
        active_conflict_probe_root=args.active_conflict_probe_root,
        output_root=args.output_root,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
