from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_BATCH_STABILITY_CLOSEOUT_KIND = "guangzhou_batch_stability_closeout_v1_manifest"
GUANGZHOU_BATCH_STABILITY_CLOSEOUT_VERSION = 1
GUANGZHOU_BATCH_STABILITY_CLOSEOUT_ADAPTER_ID = "guangzhou-batch-stability-closeout-v1-builder"

DEFAULT_FLOW_ROOT = Path("tmp/evaluation-real-samples/guangzhou-flowurl-p11-10-v1")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/guangzhou-download-p11-10-v1")
DEFAULT_RESPONSIBLE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-responsible-person-p11-10-v1")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-p11-10-v1")
DEFAULT_READINESS_ROOT = Path("tmp/evaluation-real-samples/guangzhou-upstream-readiness-p11-10-v1")
DEFAULT_EVIDENCE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-p11-10-final-v1")
DEFAULT_CERTIFICATE_SUPPLEMENT_ROOT = Path("tmp/evaluation-real-samples/certificate-supplement-closeout-p11-10-v1")
DEFAULT_INTERNAL_PACKAGE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-internal-evidence-package-manifest-p11-10-p9-v1")
DEFAULT_FIXATION_BACKFILL_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-backfill-p11-10-v1")
DEFAULT_RECAPTURE_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-recapture-p11-10-v1")
DEFAULT_READABLE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-readable-report-p11-10-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-batch-stability-closeout-v1")

_FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")


def build_guangzhou_batch_stability_closeout(
    *,
    flow_root: str | Path = DEFAULT_FLOW_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    responsible_person_root: str | Path = DEFAULT_RESPONSIBLE_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    readiness_root: str | Path = DEFAULT_READINESS_ROOT,
    evidence_report_root: str | Path = DEFAULT_EVIDENCE_REPORT_ROOT,
    certificate_supplement_root: str | Path = DEFAULT_CERTIFICATE_SUPPLEMENT_ROOT,
    internal_package_root: str | Path = DEFAULT_INTERNAL_PACKAGE_ROOT,
    fixation_backfill_root: str | Path = DEFAULT_FIXATION_BACKFILL_ROOT,
    recapture_root: str | Path = DEFAULT_RECAPTURE_ROOT,
    readable_report_root: str | Path = DEFAULT_READABLE_REPORT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    flow_dir = Path(flow_root)
    download_dir = Path(download_root)
    responsible_dir = Path(responsible_person_root)
    stage4_dir = Path(stage4_execution_root)
    readiness_dir = Path(readiness_root)
    evidence_dir = Path(evidence_report_root)
    certificate_dir = Path(certificate_supplement_root)
    internal_package_dir = Path(internal_package_root)
    backfill_dir = Path(fixation_backfill_root)
    recapture_dir = Path(recapture_root)
    readable_dir = Path(readable_report_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing_inputs: list[str] = []
    flow_manifest = _load_json(flow_dir / "run-manifest.json", missing_inputs, "flow_run_manifest_missing")
    download_manifest = _load_first_json(
        [
            download_dir / "download-repair-merged-manifest.json",
            download_dir / "download-probe-manifest.json",
            download_dir / "download-repair-manifest.json",
        ],
        missing_inputs,
        "download_manifest_missing",
    )
    responsible_manifest = _load_json(
        responsible_dir / "responsible-person-early-probe.json",
        missing_inputs,
        "responsible_person_early_probe_missing",
    )
    stage4_manifest = _load_json(stage4_dir / "company-first-stage4-execution.json", [], "stage4_execution_missing")
    readiness_manifest = _load_json(
        readiness_dir / "guangzhou-upstream-readiness-report.json",
        [],
        "readiness_report_missing",
    )
    evidence_manifest = _load_json(
        evidence_dir / "guangzhou-evidence-report-v1.json",
        missing_inputs,
        "evidence_report_missing",
    )
    certificate_manifest = _load_json_optional(certificate_dir / "certificate-supplement-closeout-v1.json")
    internal_package_manifest = _load_json(
        internal_package_dir / "internal-evidence-package-manifest-v1.json",
        missing_inputs,
        "internal_evidence_package_manifest_missing",
    )
    backfill_manifest = _load_json(
        backfill_dir / "evidence-fixation-backfill-v1.json",
        missing_inputs,
        "evidence_fixation_backfill_missing",
    )
    recapture_manifest = _load_json_optional(recapture_dir / "evidence-fixation-recapture-v1.json")
    readable_manifest = _load_json(
        readable_dir / "guangzhou-evidence-readable-report-v1.json",
        missing_inputs,
        "readable_report_missing",
    )

    flow_summary = _summary(flow_manifest)
    download_summary = _summary(download_manifest)
    responsible_summary = _summary(responsible_manifest)
    stage4_summary = _summary(stage4_manifest)
    readiness_summary = _summary(readiness_manifest)
    evidence_summary = _summary(evidence_manifest)
    certificate_summary = _summary(certificate_manifest)
    internal_summary = _summary(internal_package_manifest)
    backfill_summary = _summary(backfill_manifest)
    recapture_summary = _summary(recapture_manifest)
    readable_summary = _summary(readable_manifest)

    project_ids = _project_ids(
        flow_manifest,
        download_manifest,
        responsible_manifest,
        stage4_manifest,
        evidence_manifest,
        internal_package_manifest,
        readable_manifest,
    )
    project_records = [
        _project_record(
            project_id,
            flow_manifest=flow_manifest,
            download_manifest=download_manifest,
            responsible_manifest=responsible_manifest,
            stage4_manifest=stage4_manifest,
            evidence_manifest=evidence_manifest,
            internal_package_manifest=internal_package_manifest,
            readable_manifest=readable_manifest,
        )
        for project_id in project_ids
    ]

    entry_project_count = _int(
        flow_summary.get("unique_project_count")
        or flow_summary.get("selected_post_candidate_entry_count")
        or len(project_ids)
    )
    readable_project_count = _int(readable_summary.get("project_count") or _count_ready_readable_projects(readable_manifest))
    readable_ready_threshold = math.ceil(max(entry_project_count, 1) * 0.8)
    unreadable_due_to_chain = readable_project_count < readable_ready_threshold

    failure_taxonomy_counts = _merge_counts(
        download_summary.get("failure_taxonomy_counts"),
        download_summary.get("flow_no_failure_taxonomy_counts"),
        readiness_summary.get("blocking_reason_counts"),
        evidence_summary.get("closeout_blocking_reason_counts"),
        backfill_summary.get("backfill_status_counts"),
        recapture_summary.get("failure_taxonomy_counts"),
        {"missing_inputs": len(missing_inputs)} if missing_inputs else {},
    )

    systemic_blockers = _systemic_blockers(
        missing_inputs=missing_inputs,
        download_summary=download_summary,
        readiness_summary=readiness_summary,
        internal_summary=internal_summary,
        backfill_summary=backfill_summary,
        readable_manifest=readable_manifest,
        unreadable_due_to_chain=unreadable_due_to_chain,
    )
    if systemic_blockers:
        batch_state = "P11_BLOCKED"
    elif entry_project_count < 8:
        batch_state = "P11_PARTIAL_SOURCE_COVERAGE"
    else:
        batch_state = "P11_STABILITY_READY"

    summary = {
        "batch_closeout_state": batch_state,
        "entry_project_count": entry_project_count,
        "selected_post_candidate_entry_count": _int(flow_summary.get("selected_post_candidate_entry_count")),
        "flow_project_sample_count": _int(flow_summary.get("project_sample_count")),
        "download_probe_project_count": _int(download_summary.get("download_probe_project_count") or download_summary.get("unique_project_count")),
        "download_flow_item_count": _int(download_summary.get("flow_item_count")),
        "attachment_snapshot_count": _int(download_summary.get("attachment_snapshot_count")),
        "attachment_snapshot_success_rate": _float(download_summary.get("attachment_snapshot_success_rate")),
        "responsible_person_project_count": _int(responsible_summary.get("project_count")),
        "responsible_person_certificate_ready_count": _int(responsible_summary.get("certificate_ready_count")),
        "stage4_execution_job_count": _int(stage4_summary.get("job_count")),
        "stage4_resolved_group_count": _int(
            stage4_summary.get("resolved_candidate_group_count")
            or (stage4_summary.get("state_counts") or {}).get("COMPANY_FIRST_CERTIFICATE_RESOLVED")
            or evidence_summary.get("resolved_candidate_group_count")
        ),
        "safe_to_closeout_evidence_report": bool(evidence_summary.get("safe_to_closeout_evidence_report")),
        "evidence_report_project_count": _int(evidence_summary.get("project_count")),
        "candidate_group_count": _int(
            evidence_summary.get("candidate_group_count")
            or internal_summary.get("candidate_group_count")
            or certificate_summary.get("candidate_group_count")
        ),
        "resolved_candidate_group_count": _int(
            evidence_summary.get("resolved_candidate_group_count")
            or internal_summary.get("certificate_resolved_group_count")
            or certificate_summary.get("certificate_resolved_group_count")
        ),
        "flow_08_targeted_parse_required_count": _int(
            evidence_summary.get("flow_08_targeted_parse_required_project_count")
            or internal_summary.get("flow_08_targeted_parse_required_count")
        ),
        "internal_package_project_count": _int(internal_summary.get("project_count")),
        "source_fixation_record_count": _int(internal_summary.get("source_fixation_record_count")),
        "backfilled_no_remaining_gap_count": _int(
            backfill_summary.get("backfilled_no_remaining_gap_count") or backfill_summary.get("backfilled_record_count")
        ),
        "classified_record_hash_only_count": _int(backfill_summary.get("classified_record_hash_only_count")),
        "unfixable_with_current_artifacts_count": _int(backfill_summary.get("unfixable_with_current_artifacts_count")),
        "recapture_task_count": _int(recapture_summary.get("recapture_task_count")),
        "readable_report_project_count": readable_project_count,
        "readable_ready_project_threshold": readable_ready_threshold,
        "forbidden_term_scan_state": _forbidden_scan_state([evidence_manifest, internal_package_manifest, readable_manifest]),
        "missing_inputs": missing_inputs,
        "systemic_blockers": systemic_blockers,
        "failure_taxonomy_counts": failure_taxonomy_counts,
        "official_source_readback_is_not_p11_gate": True,
        "flow_08_default_deep_parse_required": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "customer_delivery_ready": False,
    }

    manifest = {
        "manifest_version": GUANGZHOU_BATCH_STABILITY_CLOSEOUT_VERSION,
        "manifest_kind": GUANGZHOU_BATCH_STABILITY_CLOSEOUT_KIND,
        "adapter_id": GUANGZHOU_BATCH_STABILITY_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "GuangzhouBatchStabilityCloseoutV1",
        "manifest_id": f"GUANGZHOU-BATCH-STABILITY-{_fingerprint({'summary': summary, 'projects': project_records})[:16]}",
        "created_at": created,
        "source_flow_root": str(flow_dir),
        "source_download_root": str(download_dir),
        "source_responsible_person_root": str(responsible_dir),
        "source_stage4_execution_root": str(stage4_dir),
        "source_readiness_root": str(readiness_dir),
        "source_evidence_report_root": str(evidence_dir),
        "source_certificate_supplement_root": str(certificate_dir),
        "source_internal_package_root": str(internal_package_dir),
        "source_fixation_backfill_root": str(backfill_dir),
        "source_recapture_root": str(recapture_dir),
        "source_readable_report_root": str(readable_dir),
        "summary": summary,
        "project_records": project_records,
        "safety": {
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

    output_path = out_dir / "guangzhou-batch-stability-closeout-v1.json"
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "batch_stability_closeout_mode": "BUILT",
        "safe_to_execute": True,
        "output_json": str(output_path),
        "summary": summary,
        "manifest": manifest,
    }


def _systemic_blockers(
    *,
    missing_inputs: list[str],
    download_summary: Mapping[str, Any],
    readiness_summary: Mapping[str, Any],
    internal_summary: Mapping[str, Any],
    backfill_summary: Mapping[str, Any],
    readable_manifest: Mapping[str, Any],
    unreadable_due_to_chain: bool,
) -> list[str]:
    blockers = list(missing_inputs)
    if _int(download_summary.get("download_probe_project_count") or download_summary.get("unique_project_count")) == 0:
        blockers.append("download_probe_no_project_state")
    if download_summary and _float(download_summary.get("attachment_snapshot_success_rate")) == 0.0:
        blockers.append("download_snapshot_success_rate_zero")
    if readiness_summary and not bool(readiness_summary.get("safe_to_closeout_evidence_report")):
        blockers.append("readiness_not_safe_to_closeout")
    if _int(backfill_summary.get("unfixable_with_current_artifacts_count")):
        blockers.append("unclassified_or_unfixable_fixation_gap_present")
    if internal_summary and str(internal_summary.get("forbidden_term_scan_state") or "") not in ("PASS", ""):
        blockers.append("internal_package_forbidden_term_scan_failed")
    readable_summary = _summary(readable_manifest)
    if readable_manifest and str(readable_summary.get("forbidden_term_scan_state") or "") not in ("PASS", ""):
        blockers.append("readable_report_forbidden_term_scan_failed")
    if unreadable_due_to_chain:
        blockers.append("readable_report_project_threshold_not_met")
    return _dedupe(blockers)


def _project_record(
    project_id: str,
    *,
    flow_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    responsible_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
    evidence_manifest: Mapping[str, Any],
    internal_package_manifest: Mapping[str, Any],
    readable_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    flow_project = _first(_records_for_project(flow_manifest, project_id))
    download_project = _first(_records_for_project(download_manifest, project_id))
    responsible_project = _first(_records_for_project(responsible_manifest, project_id))
    evidence_project = _first(_records_for_project(evidence_manifest, project_id))
    internal_project = _first(_records_for_project(internal_package_manifest, project_id))
    readable_project = _first(_records_for_project(readable_manifest, project_id))
    stage4_records = _records_for_project(stage4_manifest, project_id)
    return {
        "project_id": project_id,
        "project_name": _project_name(
            project_id,
            flow_project,
            download_project,
            responsible_project,
            evidence_project,
            internal_project,
            readable_project,
        ),
        "flow_url_state": "PRESENT" if flow_project else "MISSING",
        "download_state": "PRESENT" if download_project else "MISSING",
        "responsible_person_state": str(responsible_project.get("early_probe_state") or ("PRESENT" if responsible_project else "MISSING")),
        "stage4_record_count": len(stage4_records),
        "evidence_report_state": "PRESENT" if evidence_project else "MISSING",
        "internal_package_state": "PRESENT" if internal_project else "MISSING",
        "readable_report_state": "PRESENT" if readable_project else "MISSING",
        "flow_08_targeted_parse_required": bool(
            (evidence_project.get("summary") or {}).get("flow_08_targeted_parse_required")
            or (evidence_project.get("verification_evidence") or {}).get("flow_08_targeted_parse_required")
        ),
        "failure_taxonomy_counts": _merge_counts(
            download_project.get("failure_taxonomy_counts"),
            (evidence_project.get("process_stability") or {}).get("failure_taxonomy_counts"),
        ),
    }


def _records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    candidate_keys = (
        "project_records",
        "project_reports",
        "project_task_records",
        "download_project_records",
        "responsible_person_project_records",
        "candidate_group_records",
        "stage4_execution_jobs",
        "job_records",
    )
    for key in candidate_keys:
        for record in _list(manifest.get(key)):
            if not isinstance(record, Mapping):
                continue
            if str(record.get("project_id") or "") == project_id:
                records.append(dict(record))
    nested = manifest.get("manifest")
    if isinstance(nested, Mapping):
        records.extend(_records_for_project(nested, project_id))
    return records


def _project_ids(*manifests: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for manifest in manifests:
        ids.extend(_extract_project_ids(manifest))
    return _dedupe(ids)


def _extract_project_ids(manifest: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    keys = (
        "project_records",
        "project_reports",
        "project_sample_items",
        "selected_post_candidate_entries",
        "manual_url_check_rows",
        "flow_matrix_records",
        "download_project_records",
        "responsible_person_project_records",
        "candidate_group_records",
        "stage4_execution_jobs",
        "job_records",
    )
    for key in keys:
        for record in _list(manifest.get(key)):
            if isinstance(record, Mapping):
                project_id = str(record.get("project_id") or "").strip()
                if project_id:
                    ids.append(project_id)
    nested = manifest.get("manifest")
    if isinstance(nested, Mapping):
        ids.extend(_extract_project_ids(nested))
    summary = _summary(manifest)
    for project_id in _list(summary.get("project_ids")):
        ids.append(str(project_id))
    return ids


def _count_ready_readable_projects(manifest: Mapping[str, Any]) -> int:
    records = _list(manifest.get("project_records")) or _list(manifest.get("project_reports"))
    return len([record for record in records if isinstance(record, Mapping)])


def _load_json(path: Path, missing_inputs: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        missing_inputs.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _load_first_json(paths: list[Path], missing_inputs: list[str], missing_reason: str) -> dict[str, Any]:
    for path in paths:
        if path.exists():
            return _load_json(path, [], missing_reason)
    missing_inputs.append(missing_reason)
    return {}


def _load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    nested = manifest.get("manifest")
    if isinstance(nested, Mapping):
        nested_summary = nested.get("summary")
        if isinstance(nested_summary, Mapping):
            return dict(nested_summary)
    summary = manifest.get("summary")
    return dict(summary) if isinstance(summary, Mapping) else {}


def _merge_counts(*sources: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            count = _int(value)
            if count:
                out[str(key)] = out.get(str(key), 0) + count
    return out


def _forbidden_scan_state(payloads: Iterable[Mapping[str, Any]]) -> str:
    text = json.dumps(list(payloads), ensure_ascii=False, sort_keys=True, default=str)
    return "FAIL" if any(term in text for term in _FORBIDDEN_TERMS) else "PASS"


def _project_name(project_id: str, *sources: Any) -> str:
    for source in sources:
        if isinstance(source, Mapping):
            text = str(source.get("project_name") or source.get("title") or "").strip()
            if text:
                return text
        for item in _list(source):
            if isinstance(item, Mapping):
                text = str(item.get("project_name") or item.get("title") or "").strip()
                if text:
                    return text
    return project_id


def _first(items: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(items[0]) if items else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Guangzhou P11 batch stability closeout v1.")
    parser.add_argument("--flow-root", default=str(DEFAULT_FLOW_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--responsible-person-root", default=str(DEFAULT_RESPONSIBLE_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--readiness-root", default=str(DEFAULT_READINESS_ROOT))
    parser.add_argument("--evidence-report-root", default=str(DEFAULT_EVIDENCE_REPORT_ROOT))
    parser.add_argument("--certificate-supplement-root", default=str(DEFAULT_CERTIFICATE_SUPPLEMENT_ROOT))
    parser.add_argument("--internal-package-root", default=str(DEFAULT_INTERNAL_PACKAGE_ROOT))
    parser.add_argument("--fixation-backfill-root", default=str(DEFAULT_FIXATION_BACKFILL_ROOT))
    parser.add_argument("--recapture-root", default=str(DEFAULT_RECAPTURE_ROOT))
    parser.add_argument("--readable-report-root", default=str(DEFAULT_READABLE_REPORT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_batch_stability_closeout(
        flow_root=args.flow_root,
        download_root=args.download_root,
        responsible_person_root=args.responsible_person_root,
        stage4_execution_root=args.stage4_execution_root,
        readiness_root=args.readiness_root,
        evidence_report_root=args.evidence_report_root,
        certificate_supplement_root=args.certificate_supplement_root,
        internal_package_root=args.internal_package_root,
        fixation_backfill_root=args.fixation_backfill_root,
        recapture_root=args.recapture_root,
        readable_report_root=args.readable_report_root,
        output_root=args.output_root,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
