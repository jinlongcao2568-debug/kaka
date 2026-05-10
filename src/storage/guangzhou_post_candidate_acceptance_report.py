from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_POST_CANDIDATE_ACCEPTANCE_REPORT_VERSION = 1
GUANGZHOU_POST_CANDIDATE_ACCEPTANCE_REPORT_KIND = "guangzhou_post_candidate_acceptance_report"
GUANGZHOU_POST_CANDIDATE_ACCEPTANCE_REPORT_ADAPTER_ID = (
    "guangzhou-post-candidate-acceptance-report-builder"
)

SAMPLE_READY = "SAMPLE_READY"
PARTIAL_REVIEW_REQUIRED = "PARTIAL_REVIEW_REQUIRED"
BLOCKED = "BLOCKED"


def build_guangzhou_post_candidate_acceptance_report(
    *,
    output_root: str | Path,
    real_sample_execution_manifest_json: str | Path | None = None,
    project_file_audit_json: str | Path | None = None,
    challenge_stability_report_json: str | Path | None = None,
    golden_contract_json: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    root = Path(output_root)
    run_manifest_path = Path(real_sample_execution_manifest_json) if real_sample_execution_manifest_json else root / "run-manifest.json"
    audit_path = Path(project_file_audit_json) if project_file_audit_json else root / "project-file-audit.json"
    stability_path = (
        Path(challenge_stability_report_json)
        if challenge_stability_report_json
        else root / "challenge-stability-report.json"
    )
    contract_path = (
        Path(golden_contract_json)
        if golden_contract_json
        else Path("contracts/evaluation/guangzhou_12_flow_golden_projects.json")
    )

    blocking_reasons: list[str] = []
    run_payload = _load_json_optional(run_manifest_path, blocking_reasons, "run_manifest_missing")
    audit_payload = _load_json_optional(audit_path, blocking_reasons, "project_file_audit_missing")
    stability_payload = _load_json_optional(stability_path, blocking_reasons, "challenge_stability_report_missing")
    golden_contract = _load_json_optional(contract_path, blocking_reasons, "golden_contract_missing")

    run_manifest = _source_manifest(run_payload)
    audit_manifest = _source_manifest(audit_payload)
    stability_manifest = _source_manifest(stability_payload)
    pipeline_stage = str(run_manifest.get("pipeline_stage") or "")
    flow_modules = _flow_modules(golden_contract)
    project_items = [
        dict(item)
        for item in list(audit_manifest.get("items") or [])
        if isinstance(item, Mapping)
    ]
    project_reports = [
        _project_report(project_item=item, flow_modules=flow_modules)
        for item in project_items
    ]
    golden_results = [
        _golden_project_result(project, project_reports, pipeline_stage=pipeline_stage)
        for project in list(golden_contract.get("projects") or [])
        if isinstance(project, Mapping)
    ]
    manual_items = _manual_check_items(project_reports=project_reports, golden_results=golden_results)
    summary = _summary(
        run_manifest=run_manifest,
        project_reports=project_reports,
        stability_manifest=stability_manifest,
        golden_results=golden_results,
        manual_items=manual_items,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GUANGZHOU_POST_CANDIDATE_ACCEPTANCE_REPORT_VERSION,
        "manifest_kind": GUANGZHOU_POST_CANDIDATE_ACCEPTANCE_REPORT_KIND,
        "adapter_id": GUANGZHOU_POST_CANDIDATE_ACCEPTANCE_REPORT_ADAPTER_ID,
        "manifest_id": f"GUANGZHOU-POST-CANDIDATE-ACCEPTANCE-{_fingerprint({'projects': project_reports, 'summary': summary})[:16]}",
        "created_at": created,
        "output_root": str(root),
        "source_real_sample_execution_manifest_path": str(run_manifest_path),
        "source_project_file_audit_path": str(audit_path),
        "source_challenge_stability_report_path": str(stability_path),
        "golden_contract_path": str(contract_path),
        "pipeline_stage": pipeline_stage,
        "official_entry_url": str(golden_contract.get("official_entry_url") or ""),
        "source_profile_id": str(golden_contract.get("source_profile_id") or ""),
        "flow_modules": flow_modules,
        "project_reports": project_reports,
        "golden_project_results": golden_results,
        "manual_check_recommended_items": manual_items,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    return {
        "guangzhou_post_candidate_acceptance_report_mode": "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }


def _project_report(*, project_item: Mapping[str, Any], flow_modules: list[dict[str, Any]]) -> dict[str, Any]:
    flow_inventory = [
        dict(item)
        for item in list(project_item.get("guangzhou_flow_inventory") or [])
        if isinstance(item, Mapping)
    ]
    flow_matrix = [
        _flow_matrix_row(module=module, project_item=project_item, flow_inventory=flow_inventory)
        for module in flow_modules
    ]
    verification_urls = project_item.get("verification_urls") if isinstance(project_item.get("verification_urls"), Mapping) else {}
    all_urls = _dedupe_strings(
        [
            *list(verification_urls.get("all_urls") or []),
            *list(verification_urls.get("project_source_urls") or []),
            *list(verification_urls.get("attachment_snapshot_urls") or []),
            *[
                str(item.get("source_url") or "")
                for item in flow_inventory
            ],
            *[
                str(item.get("parent_source_url") or "")
                for item in flow_inventory
            ],
        ]
    )
    verification_urls_out = {
        **dict(verification_urls),
        "all_urls": all_urls,
        "url_count": len(all_urls),
    }
    per_project_files = [
        _file_inventory_row(row)
        for row in list(project_item.get("file_inventory") or [])
        if isinstance(row, Mapping)
    ]
    return {
        "project_id": str(project_item.get("project_id") or ""),
        "project_name": str(project_item.get("project_name") or ""),
        "source_profile_ids": list(project_item.get("source_profile_ids") or []),
        "document_kinds": list(project_item.get("document_kinds") or []),
        "post_candidate_entry_state": str(project_item.get("post_candidate_entry_state") or ""),
        "backtrace_completeness_state": str(project_item.get("backtrace_completeness_state") or ""),
        "guangzhou_flow_completeness_state": str(project_item.get("guangzhou_flow_completeness_state") or ""),
        "flow_matrix": flow_matrix,
        "present_flow_nos": [row["flow_no"] for row in flow_matrix if row["present"]],
        "missing_flow_nos": [row["flow_no"] for row in flow_matrix if not row["present"]],
        "detail_file_count": _int(project_item.get("detail_file_count")),
        "attachment_file_count": _int(project_item.get("attachment_file_count")),
        "replayable_file_count": _int(project_item.get("replayable_file_count")),
        "download_completeness_state": str(project_item.get("download_completeness_state") or ""),
        "parse_completeness_state": str(project_item.get("parse_completeness_state") or ""),
        "ready_for_tailored_analysis": bool(project_item.get("ready_for_tailored_analysis")),
        "verification_urls": verification_urls_out,
        "per_project_file_inventory": per_project_files,
        "failure_reasons": list(project_item.get("failure_reasons") or []),
        "manual_check_reasons": _project_manual_check_reasons(project_item=project_item, flow_matrix=flow_matrix),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_matrix_row(
    *,
    module: Mapping[str, Any],
    project_item: Mapping[str, Any],
    flow_inventory: list[Mapping[str, Any]],
) -> dict[str, Any]:
    flow_no = str(module.get("flow_no") or "")
    items = [item for item in flow_inventory if str(item.get("flow_no") or "") == flow_no]
    details = [item for item in items if str(item.get("file_role") or "") in {"detail", "detail_url"}]
    attachments = [item for item in items if str(item.get("file_role") or "") == "attachment"]
    attempts = [
        dict(item)
        for item in list(project_item.get("backtrace_stage_attempts") or [])
        if isinstance(item, Mapping) and str(item.get("guangzhou_flow_no") or "") == flow_no
    ]
    failure_taxonomy = _dedupe_strings(
        reason
        for attempt in attempts
        for reason in list(attempt.get("failure_taxonomy") or [])
    )
    return {
        "flow_no": flow_no,
        "flow_title": str(module.get("flow_title") or ""),
        "document_kind": str(module.get("document_kind") or ""),
        "present": bool(items),
        "detail_count": len(details),
        "attachment_count": len(attachments),
        "downloaded_attachment_count": sum(1 for item in attachments if bool(item.get("replayable"))),
        "published_dates": _dedupe_strings(item.get("published_date") for item in items),
        "detail_urls": _dedupe_strings(item.get("source_url") for item in details),
        "attachment_urls": _dedupe_strings(item.get("source_url") for item in attachments),
        "local_paths": _dedupe_strings(item.get("copied_file_path") for item in items),
        "failure_taxonomy": failure_taxonomy,
        "target_execution_states": _dedupe_strings(attempt.get("target_execution_state") for attempt in attempts),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _file_inventory_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(row.get("project_id") or ""),
        "flow_no": str(row.get("guangzhou_flow_no") or ""),
        "flow_title": str(row.get("guangzhou_flow_title") or ""),
        "published_date": _published_date(row),
        "source_url": str(row.get("source_url") or ""),
        "snapshot_id": str(row.get("snapshot_id") or ""),
        "local_path": str(row.get("file_path") or ""),
        "file_role": str(row.get("file_role") or ""),
        "download_state": str(row.get("download_state") or ""),
        "parse_state": str(row.get("parse_state") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _golden_project_result(
    golden_project: Mapping[str, Any],
    project_reports: list[Mapping[str, Any]],
    *,
    pipeline_stage: str = "",
) -> dict[str, Any]:
    project_code = str(golden_project.get("project_code") or "")
    expected_project_id = str(golden_project.get("project_id") or "")
    report = next(
        (
            item
            for item in project_reports
            if str(item.get("project_id") or "") == expected_project_id
            or project_code in str(item.get("project_id") or "")
            or project_code in str(item.get("project_name") or "")
        ),
        None,
    )
    if not report:
        return {
            "project_code": project_code,
            "project_id": expected_project_id,
            "golden_acceptance_state": "GOLDEN_PROJECT_MISSING",
            "failed_assertions": ["golden_project_missing_from_batch"],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    failed: list[str] = []
    by_flow = {str(row.get("flow_no") or ""): row for row in list(report.get("flow_matrix") or [])}
    for flow_no in list(golden_project.get("must_have_flow_nos") or []):
        if not bool((by_flow.get(str(flow_no)) or {}).get("present")):
            failed.append(f"must_have_flow_missing:{flow_no}")
    expected_present = [str(value) for value in list(golden_project.get("expected_present_flow_nos") or [])]
    present = [str(value) for value in list(report.get("present_flow_nos") or [])]
    if present != expected_present:
        failed.append(f"present_flow_nos_mismatch:{'/'.join(present)}")
    expected_missing = [str(value) for value in list(golden_project.get("expected_missing_flow_nos") or [])]
    missing = [str(value) for value in list(report.get("missing_flow_nos") or [])]
    if missing != expected_missing:
        failed.append(f"missing_flow_nos_mismatch:{'/'.join(missing)}")
    flow_url_only = pipeline_stage == "FlowUrlOnly"
    if not flow_url_only:
        if _int(report.get("detail_file_count")) != _int(golden_project.get("expected_detail_count")):
            failed.append("detail_count_mismatch")
        if _int(report.get("attachment_file_count")) != _int(golden_project.get("expected_attachment_count")):
            failed.append("attachment_count_mismatch")
        if _int(golden_project.get("expected_replayable_file_count")) and _int(report.get("replayable_file_count")) != _int(
            golden_project.get("expected_replayable_file_count")
        ):
            failed.append("replayable_file_count_mismatch")
    for expectation in list(golden_project.get("flow_expectations") or []):
        if not isinstance(expectation, Mapping):
            continue
        row = by_flow.get(str(expectation.get("flow_no") or "")) or {}
        if _int(row.get("detail_count")) != _int(expectation.get("expected_detail_count")):
            failed.append(f"flow_detail_count_mismatch:{expectation.get('flow_no')}")
        if not flow_url_only and _int(row.get("attachment_count")) != _int(expectation.get("expected_attachment_count")):
            failed.append(f"flow_attachment_count_mismatch:{expectation.get('flow_no')}")
        for detail in list(expectation.get("details") or []):
            if not isinstance(detail, Mapping):
                continue
            if str(detail.get("source_url") or "") not in list(row.get("detail_urls") or []):
                failed.append(f"flow_detail_url_missing:{expectation.get('flow_no')}")
            if str(detail.get("published_date") or "") not in list(row.get("published_dates") or []):
                failed.append(f"flow_published_date_missing:{expectation.get('flow_no')}")
    return {
        "project_code": project_code,
        "project_id": str(report.get("project_id") or ""),
        "golden_acceptance_state": "GOLDEN_ACCEPTED" if not failed else "GOLDEN_FAILED",
        "failed_assertions": _dedupe_strings(failed),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _manual_check_items(
    *,
    project_reports: list[Mapping[str, Any]],
    golden_results: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for golden in golden_results:
        if str(golden.get("golden_acceptance_state") or "") != "GOLDEN_ACCEPTED":
            items.append(
                {
                    "project_id": str(golden.get("project_id") or ""),
                    "reason": "golden_acceptance_failed",
                    "details": list(golden.get("failed_assertions") or []),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    for report in project_reports:
        reasons = list(report.get("manual_check_reasons") or [])
        if not reasons:
            continue
        items.append(
            {
                "project_id": str(report.get("project_id") or ""),
                "project_name": str(report.get("project_name") or ""),
                "reason": "project_review_recommended",
                "details": reasons,
                "verification_urls": dict(report.get("verification_urls") or {}),
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return items


def _project_manual_check_reasons(
    *,
    project_item: Mapping[str, Any],
    flow_matrix: list[Mapping[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    if str(project_item.get("post_candidate_entry_state") or "") != "POST_CANDIDATE_ENTRY_PRESENT":
        reasons.append("post_candidate_entry_missing")
    present = {str(row.get("flow_no") or "") for row in flow_matrix if row.get("present")}
    for required_flow in ("05", "06", "08"):
        if required_flow not in present:
            reasons.append(f"important_flow_missing:{required_flow}")
    for row in flow_matrix:
        if list(row.get("failure_taxonomy") or []):
            reasons.append(f"flow_failure_taxonomy:{row.get('flow_no')}")
        if _int(row.get("attachment_count")) != _int(row.get("downloaded_attachment_count")):
            reasons.append(f"flow_attachment_download_incomplete:{row.get('flow_no')}")
    if str(project_item.get("download_completeness_state") or "") == "DOWNLOAD_INCOMPLETE":
        reasons.append("project_download_incomplete")
    return _dedupe_strings(reasons)


def _summary(
    *,
    run_manifest: Mapping[str, Any],
    project_reports: list[Mapping[str, Any]],
    stability_manifest: Mapping[str, Any],
    golden_results: list[Mapping[str, Any]],
    manual_items: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    project_count = len(project_reports)
    golden_ok = bool(golden_results) and all(
        str(item.get("golden_acceptance_state") or "") == "GOLDEN_ACCEPTED"
        for item in golden_results
    )
    stability_summary = stability_manifest.get("summary") if isinstance(stability_manifest.get("summary"), Mapping) else {}
    challenge_failed_count = _int(stability_summary.get("challenge_failed_count"))
    challenge_failure_has_taxonomy = bool(stability_summary.get("failure_taxonomy_counts")) or challenge_failed_count == 0
    relation_blocked = any(
        "relation" in reason or "candidate" in reason
        for reason in blocking_reasons
    )
    if blocking_reasons or project_count <= 0 or relation_blocked:
        state = BLOCKED
    elif project_count >= 20 and golden_ok and challenge_failure_has_taxonomy:
        state = SAMPLE_READY
    else:
        state = PARTIAL_REVIEW_REQUIRED
    return {
        "batch_acceptance_state": state,
        "project_count": project_count,
        "source_project_sample_count": _int((run_manifest.get("summary") or {}).get("project_sample_count")),
        "selected_post_candidate_entry_count": _int((run_manifest.get("summary") or {}).get("selected_post_candidate_entry_count")),
        "golden_acceptance_passed": golden_ok,
        "golden_project_result_counts": _counts(str(item.get("golden_acceptance_state") or "") for item in golden_results),
        "manual_check_recommended_count": len(manual_items),
        "challenge_failed_count": challenge_failed_count,
        "challenge_resolved_count": _int(stability_summary.get("challenge_resolved_count")),
        "detail_file_count": sum(_int(item.get("detail_file_count")) for item in project_reports),
        "attachment_file_count": sum(_int(item.get("attachment_file_count")) for item in project_reports),
        "ready_for_tailored_analysis_count": sum(1 for item in project_reports if bool(item.get("ready_for_tailored_analysis"))),
        "flow_presence_counts": _counts(
            flow_no
            for item in project_reports
            for flow_no in list(item.get("present_flow_nos") or [])
        ),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _load_json_optional(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        blocking_reasons.append(f"{missing_reason}:not_json_object")
        return {}
    return dict(data)


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload)


def _flow_modules(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(contract.get("flow_modules") or [])
        if isinstance(item, Mapping)
    ]


def _published_date(row: Mapping[str, Any]) -> str:
    for key in ("published_date", "parent_published_at"):
        text = str(row.get(key) or "")
        if len(text) >= 10:
            return text[:10]
    return ""


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou post-candidate acceptance report.")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--real-sample-execution-manifest-json")
    parser.add_argument("--project-file-audit-json")
    parser.add_argument("--challenge-stability-report-json")
    parser.add_argument("--golden-contract-json")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_post_candidate_acceptance_report(
        output_root=args.output_root,
        real_sample_execution_manifest_json=args.real_sample_execution_manifest_json,
        project_file_audit_json=args.project_file_audit_json,
        challenge_stability_report_json=args.challenge_stability_report_json,
        golden_contract_json=args.golden_contract_json,
    )
    output_path = Path(args.output_json) if args.output_json else Path(args.output_root) / "guangzhou-post-candidate-acceptance-report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "guangzhou post-candidate acceptance report "
            f"{result['guangzhou_post_candidate_acceptance_report_mode']}: safe_to_execute={result['safe_to_execute']}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BLOCKED",
    "PARTIAL_REVIEW_REQUIRED",
    "SAMPLE_READY",
    "build_guangzhou_post_candidate_acceptance_report",
]
