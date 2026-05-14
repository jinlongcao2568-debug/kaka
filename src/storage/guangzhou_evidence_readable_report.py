from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_EVIDENCE_READABLE_REPORT_KIND = "guangzhou_evidence_readable_report_v1_manifest"
GUANGZHOU_EVIDENCE_READABLE_REPORT_VERSION = 1
GUANGZHOU_EVIDENCE_READABLE_REPORT_ADAPTER_ID = "guangzhou-evidence-readable-report-v1-builder"

DEFAULT_EVIDENCE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-p3-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-readable-report-v1")

FORBIDDEN_TERMS = ("是不是本人", "确认本人", "无风险", "无冲突", "在建冲突成立", "冲突成立", "造假成立", "违法成立")


def build_guangzhou_evidence_readable_report(
    *,
    evidence_report_root: str | Path = DEFAULT_EVIDENCE_REPORT_ROOT,
    evidence_report_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    evidence_dir = Path(evidence_report_root)
    evidence_path = Path(evidence_report_json) if evidence_report_json else evidence_dir / "guangzhou-evidence-report-v1.json"
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    evidence_manifest = _source_manifest(_load_json(evidence_path, blocking_reasons, "evidence_report_missing"))
    project_cards = [_project_card(project) for project in _list(evidence_manifest.get("project_reports")) if isinstance(project, Mapping)]
    summary = _summary(evidence_manifest, project_cards, blocking_reasons)
    markdown = _markdown(summary, project_cards)
    manifest = {
        "manifest_version": GUANGZHOU_EVIDENCE_READABLE_REPORT_VERSION,
        "manifest_kind": GUANGZHOU_EVIDENCE_READABLE_REPORT_KIND,
        "adapter_id": GUANGZHOU_EVIDENCE_READABLE_REPORT_ADAPTER_ID,
        "pipeline_stage": "GuangzhouEvidenceReadableReportV1",
        "manifest_id": f"GUANGZHOU-EVIDENCE-READABLE-{_fingerprint({'summary': summary, 'projects': project_cards})[:16]}",
        "created_at": created,
        "source_evidence_report_root": str(evidence_dir),
        "source_evidence_report_json": str(evidence_path),
        "project_cards": project_cards,
        "summary": summary,
        "markdown_file": "guangzhou-evidence-readable-report-v1.md",
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
        "guangzhou_evidence_readable_report_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    json_text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in json_text or term in markdown]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*blocking_reasons, *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        json_text = json.dumps(result, ensure_ascii=False, indent=2)
        markdown = _markdown(result["summary"], project_cards)
    (out_dir / "guangzhou-evidence-readable-report-v1.json").write_text(json_text, encoding="utf-8")
    (out_dir / "guangzhou-evidence-readable-report-v1.md").write_text(markdown, encoding="utf-8")
    return result


def _project_card(project: Mapping[str, Any]) -> dict[str, Any]:
    evidence = dict(project.get("verification_evidence") or {})
    stability = dict(project.get("process_stability") or {})
    groups = [_candidate_group_card(group) for group in _list(evidence.get("candidate_group_records")) if isinstance(group, Mapping)]
    gdcic_counts = dict(evidence.get("gdcic_readback_classification_counts") or {})
    flow08 = dict(evidence.get("flow_08_registry") or {})
    recommendations = _recommended_actions(project)
    status = _project_status(groups=groups, evidence=evidence, stability=stability)
    return {
        "project_id": str(project.get("project_id") or ""),
        "project_name": str(project.get("project_name") or ""),
        "project_status": status,
        "candidate_notice_urls": _list(evidence.get("candidate_notice_source_urls")),
        "project_source_urls": _list(evidence.get("project_source_urls")),
        "candidate_groups": groups,
        "candidate_group_count": len(groups),
        "resolved_candidate_group_count": sum(1 for group in groups if group.get("group_state") == "PUBLIC_REGISTRATION_MATCHED"),
        "flow_08_state": {
            "present": bool(flow08.get("flow_08_present")),
            "targeted_parse_required": bool(evidence.get("flow_08_targeted_parse_required")),
            "default_state": "REGISTER_ONLY_BACKUP" if not evidence.get("flow_08_targeted_parse_required") else "TARGETED_PARSE_REQUIRED",
            "source_urls": _list(flow08.get("source_urls")),
            "attachment_count": _int(flow08.get("attachment_count")),
        },
        "gdcic_readback_summary": {
            "official_source_readback_state": str(evidence.get("official_source_readback_state") or "NOT_BUILT"),
            "official_source_readback_ready_count": _int(evidence.get("official_source_readback_ready_count")),
            "classification_counts": gdcic_counts,
            "field_availability_counts": dict(evidence.get("gdcic_field_availability_counts") or {}),
            "missing_field_counts": dict(evidence.get("gdcic_missing_field_counts") or {}),
            "certificate_field_availability_state": str(evidence.get("gdcic_certificate_field_availability_state") or ""),
            "person_registration_readback_count": _int(gdcic_counts.get("PERSON_REGISTRATION_READBACK")),
            "company_project_readback_count": _int(gdcic_counts.get("COMPANY_PROJECT_READBACK")),
            "certificate_field_readback_count": _int(gdcic_counts.get("CERTIFICATE_FIELD_READBACK")),
            "empty_result_review_count": _int(gdcic_counts.get("EMPTY_PUBLIC_RESULT_REVIEW")),
            "blocked_or_captcha_review_count": _int(gdcic_counts.get("BLOCKED_OR_CAPTCHA_REVIEW")),
        },
        "process_stability": {
            "closeout_state": str(stability.get("evidence_report_closeout_state") or ""),
            "safe_to_closeout": bool(stability.get("safe_to_closeout_evidence_report")),
            "download_probe_flow_count": _int(stability.get("download_probe_flow_count")),
            "attachment_snapshot_count": _int(stability.get("attachment_snapshot_count")),
            "stage4_readback_ready_count": _int(stability.get("stage4_readback_ready_count")),
            "deferred_reasons": _list(stability.get("closeout_deferred_reasons")),
            "blocking_reasons": _list(stability.get("closeout_blocking_reasons")),
            "failure_taxonomy": _list(stability.get("failure_taxonomy")),
        },
        "next_actions": recommendations,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_group_card(group: Mapping[str, Any]) -> dict[str, Any]:
    state = str(group.get("group_resolution_state") or "")
    return {
        "candidate_group_id": str(group.get("candidate_group_id") or group.get("group_id") or ""),
        "candidate_group_order": str(group.get("candidate_group_order") or group.get("rank") or ""),
        "candidate_group_members": _dedupe(
            [
                *_list(group.get("candidate_group_members")),
                *_list(group.get("matched_company_names")),
            ]
        ),
        "responsible_person_name": str(group.get("responsible_person_name") or ""),
        "responsible_role": str(group.get("responsible_role") or ""),
        "certificate_no": str(group.get("certificate_no") or ""),
        "bid_price": str(group.get("bid_price") or ""),
        "rank": str(group.get("rank") or group.get("candidate_group_order") or ""),
        "group_state": "PUBLIC_REGISTRATION_MATCHED" if "RESOLVED" in state else "REVIEW_REQUIRED",
        "source_state": state,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _recommended_actions(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _list(project.get("optimization_recommendations")):
        if not isinstance(item, Mapping):
            continue
        action = str(item.get("recommended_action") or "")
        if not action:
            continue
        out.append(
            {
                "action": action,
                "label": _action_label(action),
                "reason": str(item.get("reason") or ""),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return out


def _action_label(action: str) -> str:
    mapping = {
        "CLOSEOUT_EVIDENCE_REPORT_READY": "可进入内部证据报告收口",
        "READY_FOR_INTERNAL_EVIDENCE_PACKAGE_REVIEW": "可进入内部证据包复核",
        "OFFICIAL_SOURCE_READBACK_READY": "官方源字段回放可用",
        "GDCIC_PERSON_REGISTRATION_READBACK_REVIEW": "GDCIC 人员注册信息可复核",
        "GDCIC_COMPANY_PROJECT_READBACK_REVIEW": "GDCIC 企业项目记录可复核",
        "GDCIC_CERTIFICATE_FIELD_READBACK_REVIEW": "GDCIC 证书字段可复核",
        "GDCIC_EMPTY_PUBLIC_RESULT_REVIEW_REQUIRED": "GDCIC 空结果需复核",
        "GDCIC_BLOCKED_OR_CAPTCHA_REVIEW_REQUIRED": "GDCIC 源阻断需重试或适配",
        "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_REVIEW": "GDCIC 当前 readback 未返回证书字段",
        "GDCIC_CERTIFICATE_FIELDS_READY_REVIEW": "GDCIC 证书字段可辅助复核",
        "ACTIVE_CONFLICT_EXTERNAL_SOURCE_TASKS_READY": "外部线索任务已生成",
        "RUN_FLOW_08_TARGETED_PARSE": "需要 08 定向解析",
        "SUPPLEMENT_PUBLIC_REGISTRATION_MATCH": "补充公开注册信息匹配",
        "REPAIR_PROCESS_STABILITY_ITEMS": "修复过程稳定性问题",
    }
    return mapping.get(action, action)


def _project_status(*, groups: list[Mapping[str, Any]], evidence: Mapping[str, Any], stability: Mapping[str, Any]) -> str:
    if not groups and str(stability.get("evidence_report_closeout_state") or "") == "EVIDENCE_REPORT_CLOSEOUT_NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    if evidence.get("flow_08_targeted_parse_required"):
        return "FLOW_08_TARGETED_PARSE_REQUIRED"
    if groups and all(group.get("group_state") == "PUBLIC_REGISTRATION_MATCHED" for group in groups):
        return "READY_FOR_INTERNAL_REVIEW"
    return "REVIEW_REQUIRED"


def _summary(evidence_manifest: Mapping[str, Any], project_cards: list[Mapping[str, Any]], blocking_reasons: list[str]) -> dict[str, Any]:
    source_summary = dict(evidence_manifest.get("summary") or {})
    gdcic_counts = _merge_counts(*(dict(project.get("gdcic_readback_summary", {}).get("classification_counts") or {}) for project in project_cards))
    gdcic_field_counts = _merge_counts(*(dict(project.get("gdcic_readback_summary", {}).get("field_availability_counts") or {}) for project in project_cards))
    gdcic_missing_counts = _merge_counts(*(dict(project.get("gdcic_readback_summary", {}).get("missing_field_counts") or {}) for project in project_cards))
    return {
        "report_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "project_count": len(project_cards),
        "candidate_group_count": sum(_int(project.get("candidate_group_count")) for project in project_cards),
        "resolved_candidate_group_count": sum(_int(project.get("resolved_candidate_group_count")) for project in project_cards),
        "not_applicable_project_count": sum(1 for project in project_cards if project.get("project_status") == "NOT_APPLICABLE"),
        "flow_08_targeted_parse_required_project_count": sum(
            1 for project in project_cards if (project.get("flow_08_state") or {}).get("targeted_parse_required")
        ),
        "official_source_readback_ready_count": _int(source_summary.get("official_source_readback_ready_count")),
        "official_source_project_ready_count": _int(source_summary.get("official_source_project_ready_count")),
        "gdcic_readback_classification_counts": gdcic_counts,
        "gdcic_field_availability_counts": gdcic_field_counts,
        "gdcic_missing_field_counts": gdcic_missing_counts,
        "gdcic_certificate_field_availability_state": str(source_summary.get("gdcic_certificate_field_availability_state") or ""),
        "source_evidence_report_state": str(source_summary.get("report_state") or ""),
        "source_closeout_state": str(source_summary.get("evidence_report_closeout_overall_state") or ""),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _markdown(summary: Mapping[str, Any], project_cards: list[Mapping[str, Any]]) -> str:
    lines = [
        "# 广州 EvidenceReport 可读化 v1",
        "",
        "> 内部只读报告。只输出事实、线索、证据状态和建议核验事项，不输出法律定性。",
        "",
        "## 总览",
        "",
        f"- 项目数：{_int(summary.get('project_count'))}",
        f"- 候选组数：{_int(summary.get('candidate_group_count'))}",
        f"- 已公开注册信息匹配候选组：{_int(summary.get('resolved_candidate_group_count'))}",
        f"- 官方源字段回放数：{_int(summary.get('official_source_readback_ready_count'))}",
        f"- 08 定向解析项目数：{_int(summary.get('flow_08_targeted_parse_required_project_count'))}",
        f"- GDCIC 分类：{_compact_counts(summary.get('gdcic_readback_classification_counts'))}",
        f"- GDCIC 字段可用性：{_compact_counts(summary.get('gdcic_field_availability_counts'))}",
        f"- GDCIC 证书字段状态：`{summary.get('gdcic_certificate_field_availability_state') or '-'}`",
        "",
    ]
    for project in project_cards:
        lines.extend(_project_markdown(project))
    return "\n".join(lines).rstrip() + "\n"


def _project_markdown(project: Mapping[str, Any]) -> list[str]:
    lines = [
        f"## {project.get('project_id')}｜{project.get('project_name')}",
        "",
        f"- 项目状态：`{project.get('project_status')}`",
        f"- 候选公示 URL：{_join_urls(project.get('candidate_notice_urls'))}",
        f"- 项目流程 URL 数：{len(_list(project.get('project_source_urls')))}",
        f"- 08 状态：`{(project.get('flow_08_state') or {}).get('default_state')}`，附件数：{_int((project.get('flow_08_state') or {}).get('attachment_count'))}",
        f"- GDCIC：{_compact_counts((project.get('gdcic_readback_summary') or {}).get('classification_counts'))}",
        f"- GDCIC 字段：{_compact_counts((project.get('gdcic_readback_summary') or {}).get('field_availability_counts'))}",
        f"- GDCIC 证书字段状态：`{(project.get('gdcic_readback_summary') or {}).get('certificate_field_availability_state') or '-'}`",
        "",
        "### 候选组",
        "",
    ]
    groups = _list(project.get("candidate_groups"))
    if not groups:
        lines.append("- `NOT_APPLICABLE`：该项目未形成工程负责人候选组。")
    else:
        for group in groups:
            members = "；".join(_list(group.get("candidate_group_members"))) or "-"
            lines.append(
                "- "
                f"排名/序号：{group.get('rank') or group.get('candidate_group_order') or '-'}；"
                f"成员：{members}；"
                f"负责人：{group.get('responsible_person_name') or '-'}；"
                f"证书号：{group.get('certificate_no') or '-'}；"
                f"状态：`{group.get('group_state')}`"
            )
    lines.extend(["", "### 过程稳定性", ""])
    stability = dict(project.get("process_stability") or {})
    lines.extend(
        [
            f"- Closeout：`{stability.get('closeout_state')}`",
            f"- 下载流程数：{_int(stability.get('download_probe_flow_count'))}",
            f"- 附件 snapshot：{_int(stability.get('attachment_snapshot_count'))}",
            f"- Stage4 readback：{_int(stability.get('stage4_readback_ready_count'))}",
            f"- Deferred：{_compact_list(stability.get('deferred_reasons'))}",
            f"- Failure taxonomy：{_compact_list(stability.get('failure_taxonomy'))}",
            "",
            "### 下一步动作",
            "",
        ]
    )
    actions = _list(project.get("next_actions"))
    if not actions:
        lines.append("- 暂无额外动作。")
    else:
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            lines.append(f"- `{action.get('action')}`：{action.get('label')}")
    lines.append("")
    return lines


def _join_urls(urls: Any) -> str:
    items = _list(urls)
    if not items:
        return "-"
    return "；".join(str(item) for item in items[:3])


def _compact_counts(value: Any) -> str:
    counts = dict(value or {})
    if not counts:
        return "`{}`"
    return "；".join(f"`{key}={_int(val)}`" for key, val in sorted(counts.items()))


def _compact_list(value: Any) -> str:
    items = [str(item) for item in _list(value) if str(item)]
    return "；".join(items[:8]) if items else "-"


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


def _merge_counts(*items: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        for key, value in dict(item or {}).items():
            out[str(key)] = out.get(str(key), 0) + _int(value)
    return dict(sorted(out.items()))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou Evidence readable report v1.")
    parser.add_argument("--evidence-report-root", default=str(DEFAULT_EVIDENCE_REPORT_ROOT))
    parser.add_argument("--evidence-report-json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_evidence_readable_report(
        evidence_report_root=args.evidence_report_root,
        evidence_report_json=args.evidence_report_json,
        output_root=args.output_root,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            "guangzhou evidence readable report built: "
            f"state={result['summary']['report_state']} "
            f"projects={result['summary']['project_count']}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
