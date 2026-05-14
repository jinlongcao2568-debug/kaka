from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGZHOU_INTERNAL_EVIDENCE_PACKAGE_KIND = "guangzhou_internal_evidence_package_manifest_v1"
GUANGZHOU_INTERNAL_EVIDENCE_PACKAGE_VERSION = 1
GUANGZHOU_INTERNAL_EVIDENCE_PACKAGE_ADAPTER_ID = "guangzhou-internal-evidence-package-manifest-v1"

DEFAULT_EVIDENCE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-p6-closeout-v1")
DEFAULT_CERTIFICATE_SUPPLEMENT_ROOT = Path("tmp/evaluation-real-samples/certificate-supplement-closeout-v1")
DEFAULT_OFFICIAL_SOURCE_READBACK_ROOT = Path("tmp/evaluation-real-samples/guangdong-official-source-readback-closeout-v1")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v4-merged")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/guangzhou-download-human-v1")
DEFAULT_FLOW_ROOT = Path("tmp/evaluation-real-samples/guangzhou-flowurl-analysis-72h-v1")
DEFAULT_FIXATION_BACKFILL_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-fixation-backfill-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-internal-evidence-package-manifest-v1")

FORBIDDEN_TERMS = ("是不是本人", "确认本人", "无风险", "无冲突", "在建冲突成立", "冲突成立", "造假成立", "违法成立")


def build_guangzhou_internal_evidence_package_manifest(
    *,
    evidence_report_root: str | Path = DEFAULT_EVIDENCE_REPORT_ROOT,
    certificate_supplement_root: str | Path = DEFAULT_CERTIFICATE_SUPPLEMENT_ROOT,
    official_source_readback_root: str | Path = DEFAULT_OFFICIAL_SOURCE_READBACK_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    flow_root: str | Path = DEFAULT_FLOW_ROOT,
    fixation_backfill_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    evidence_dir = Path(evidence_report_root)
    certificate_dir = Path(certificate_supplement_root)
    official_dir = Path(official_source_readback_root)
    stage4_dir = Path(stage4_execution_root)
    download_dir = Path(download_root)
    flow_dir = Path(flow_root)
    backfill_dir = Path(fixation_backfill_root) if fixation_backfill_root else None
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    evidence_manifest = _source_manifest(
        _load_json(evidence_dir / "guangzhou-evidence-report-v1.json", blocking_reasons, "evidence_report_missing")
    )
    certificate_manifest = _source_manifest(
        _load_json(certificate_dir / "certificate-supplement-closeout-v1.json", blocking_reasons, "certificate_supplement_missing")
    )
    official_manifest = _source_manifest(
        _load_json(
            official_dir / "guangdong-official-source-readback-closeout-v1.json",
            blocking_reasons,
            "official_source_readback_missing",
        )
    )
    stage4_manifest = _source_manifest(
        _load_json(stage4_dir / "company-first-stage4-execution.json", blocking_reasons, "stage4_execution_missing")
    )
    download_manifest = _source_manifest(
        _load_json(download_dir / "download-probe-manifest.json", blocking_reasons, "download_probe_manifest_missing")
    )
    flow_manifest = _source_manifest(_load_json(flow_dir / "run-manifest.json", blocking_reasons, "flow_run_manifest_missing"))
    backfill_manifest = _source_manifest(
        _load_json_optional(backfill_dir / "evidence-fixation-backfill-v1.json") if backfill_dir else {}
    )

    project_reports = [item for item in _list(evidence_manifest.get("project_reports")) if isinstance(item, Mapping)]
    project_records = [
        _project_record(
            project=project,
            certificate_manifest=certificate_manifest,
            official_manifest=official_manifest,
            stage4_manifest=stage4_manifest,
            download_manifest=download_manifest,
            flow_manifest=flow_manifest,
        )
        for project in project_reports
    ]
    candidate_group_records = [
        group for project in project_records for group in _list(project.get("candidate_group_records")) if isinstance(group, Mapping)
    ]
    source_fixation_records = _source_fixation_records(
        project_records=project_records,
        evidence_manifest=evidence_manifest,
        certificate_manifest=certificate_manifest,
        official_manifest=official_manifest,
        stage4_manifest=stage4_manifest,
        download_manifest=download_manifest,
        flow_manifest=flow_manifest,
    )
    field_lineage_records = _field_lineage_records(
        project_records=project_records,
        source_fixation_records=source_fixation_records,
        evidence_manifest=evidence_manifest,
        certificate_manifest=certificate_manifest,
        official_manifest=official_manifest,
        stage4_manifest=stage4_manifest,
    )
    reverse_explanations = _reverse_explanations(
        project_records=project_records,
        source_fixation_records=source_fixation_records,
        official_manifest=official_manifest,
    )
    backfilled_source_records = _backfilled_source_fixation_records(source_fixation_records, backfill_manifest)
    redaction_log = _redaction_log(source_fixation_records, field_lineage_records)
    summary = _summary(
        project_records=project_records,
        candidate_group_records=candidate_group_records,
        source_fixation_records=source_fixation_records,
        backfilled_source_fixation_records=backfilled_source_records,
        field_lineage_records=field_lineage_records,
        reverse_explanations=reverse_explanations,
        blocking_reasons=blocking_reasons,
        certificate_manifest=certificate_manifest,
        backfill_manifest=backfill_manifest,
    )
    package_scope = {
        "product_mode": "POST_CANDIDATE_EVIDENCE_PACK",
        "scope_state": "INTERNAL_PRE_SALES_EVIDENCE_PACKAGE",
        "project_count": summary["project_count"],
        "candidate_group_count": summary["candidate_group_count"],
        "source_evidence_report_root": str(evidence_dir),
        "source_certificate_supplement_root": str(certificate_dir),
        "source_official_source_readback_root": str(official_dir),
        "source_stage4_execution_root": str(stage4_dir),
        "source_download_root": str(download_dir),
        "source_flow_root": str(flow_dir),
        "source_fixation_backfill_root": str(backfill_dir) if backfill_dir else "",
        "generated_at": created,
        "script_version": GUANGZHOU_INTERNAL_EVIDENCE_PACKAGE_ADAPTER_ID,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_version": GUANGZHOU_INTERNAL_EVIDENCE_PACKAGE_VERSION,
        "manifest_kind": GUANGZHOU_INTERNAL_EVIDENCE_PACKAGE_KIND,
        "adapter_id": GUANGZHOU_INTERNAL_EVIDENCE_PACKAGE_ADAPTER_ID,
        "pipeline_stage": "GuangzhouInternalEvidencePackageManifestV1",
        "manifest_id": f"GUANGZHOU-INTERNAL-EVIDENCE-PACKAGE-{_fingerprint({'projects': project_records, 'summary': summary})[:16]}",
        "created_at": created,
        "package_scope": package_scope,
        "project_records": project_records,
        "candidate_group_records": candidate_group_records,
        "source_fixation_records": source_fixation_records,
        "source_fixation_backfill_summary": dict(backfill_manifest.get("summary") or {}),
        "backfilled_source_fixation_records": backfilled_source_records,
        "field_lineage_records": field_lineage_records,
        "verification_summary": _verification_summary(project_records, certificate_manifest, official_manifest),
        "reverse_explanation_records": reverse_explanations,
        "redaction_log": redaction_log,
        "forbidden_term_scan": {
            "scan_state": "PASS",
            "hit_count": 0,
            "hit_codes": [],
        },
        "trusted_timestamp_state": "RESERVED_NOT_IMPLEMENTED",
        "notary_state": "RESERVED_NOT_IMPLEMENTED",
        "customer_delivery_ready": False,
        "approval_required_before_customer_delivery": True,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "manifest_stores_raw_html_or_blob": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "guangzhou_internal_evidence_package_manifest_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [f"forbidden_term_{idx}" for idx, term in enumerate(FORBIDDEN_TERMS, start=1) if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*blocking_reasons, *[f"forbidden_report_term:{code}" for code in forbidden_hits]]
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["forbidden_term_scan"] = {
            "scan_state": "FAIL",
            "hit_count": len(forbidden_hits),
            "hit_codes": forbidden_hits,
        }
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "internal-evidence-package-manifest-v1.json").write_text(text, encoding="utf-8")
    return result


def _project_record(
    *,
    project: Mapping[str, Any],
    certificate_manifest: Mapping[str, Any],
    official_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    flow_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    project_id = str(project.get("project_id") or "")
    evidence = dict(project.get("verification_evidence") or {})
    cert_project = _first(_project_records_for_project(certificate_manifest, project_id))
    official_project = _first(_project_records_for_project(official_manifest, project_id))
    flow_items = _flow_items_for_project(flow_manifest, project_id)
    download_items = _download_items_for_project(download_manifest, project_id)
    stage4_items = _items_for_project(stage4_manifest, project_id)
    certificate_groups = {
        str(row.get("candidate_group_id") or ""): dict(row)
        for row in _list(cert_project.get("certificate_supplement_group_records"))
        if isinstance(row, Mapping)
    }
    candidate_groups = [
        _candidate_group_record(
            project_id=project_id,
            project_name=str(project.get("project_name") or evidence.get("project_name") or ""),
            group=group,
            certificate_group=certificate_groups.get(str(group.get("candidate_group_id") or ""), {}),
            stage4_items=stage4_items,
        )
        for group in _list(evidence.get("candidate_group_records"))
        if isinstance(group, Mapping)
    ]
    flow_url_summary = _flow_url_summary(flow_items, download_items, evidence)
    return {
        "project_id": project_id,
        "project_name": str(project.get("project_name") or evidence.get("project_name") or ""),
        "candidate_notice_source_urls": _dedupe(_list(evidence.get("candidate_notice_source_urls"))),
        "project_source_urls": _dedupe([*_list(evidence.get("project_source_urls")), *[row.get("source_url") for row in flow_url_summary]]),
        "flow_url_summary": flow_url_summary,
        "candidate_group_records": candidate_groups,
        "candidate_group_count": len(candidate_groups),
        "certificate_resolved_group_count": sum(
            1 for group in candidate_groups if str(group.get("certificate_supplement_state") or "").startswith("CERTIFICATE_SUPPLEMENT_RESOLVED")
        ),
        "flow_08_targeted_parse_required": bool(evidence.get("flow_08_targeted_parse_required"))
        or any(bool(group.get("flow_08_targeted_parse_required")) for group in candidate_groups),
        "flow_08_registry": dict(evidence.get("flow_08_registry") or {}),
        "public_registration_match_state": str(evidence.get("public_registration_match_state") or ""),
        "official_source_readback_state": str(evidence.get("official_source_readback_state") or official_project.get("official_source_readback_state") or ""),
        "official_source_readback_ready_count": _int(evidence.get("official_source_readback_ready_count") or official_project.get("official_source_readback_ready_count")),
        "gdcic_readback_classification_counts": dict(evidence.get("gdcic_readback_classification_counts") or official_project.get("gdcic_readback_classification_counts") or {}),
        "gdcic_field_availability_counts": dict(evidence.get("gdcic_field_availability_counts") or official_project.get("gdcic_field_availability_counts") or {}),
        "gdcic_missing_field_counts": dict(evidence.get("gdcic_missing_field_counts") or official_project.get("gdcic_missing_field_counts") or {}),
        "gdcic_certificate_field_availability_state": str(
            evidence.get("gdcic_certificate_field_availability_state") or official_project.get("gdcic_certificate_field_availability_state") or ""
        ),
        "process_stability_state": str((project.get("process_stability") or {}).get("evidence_report_closeout_state") or ""),
        "safe_to_closeout_evidence_report": bool((project.get("process_stability") or {}).get("safe_to_closeout_evidence_report")),
        "download_flow_count": len(download_items),
        "stage4_readback_ready_count": sum(1 for item in stage4_items if str(item.get("stage4_execution_state") or "") == "READBACK_READY"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_group_record(
    *,
    project_id: str,
    project_name: str,
    group: Mapping[str, Any],
    certificate_group: Mapping[str, Any],
    stage4_items: list[Mapping[str, Any]],
) -> dict[str, Any]:
    group_id = str(group.get("candidate_group_id") or group.get("group_id") or "")
    stage4_group = _first([item for item in stage4_items if str(item.get("candidate_group_id") or "") == group_id])
    certificate_no = str(
        certificate_group.get("certificate_no")
        or stage4_group.get("resolved_certificate_no_optional")
        or group.get("certificate_no")
        or ""
    )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "candidate_group_id": group_id,
        "candidate_group_order": str(group.get("candidate_group_order") or group.get("rank") or ""),
        "candidate_group_members": _dedupe([*_list(group.get("candidate_group_members")), *_list(group.get("matched_company_names"))]),
        "responsible_person_name": str(group.get("responsible_person_name") or ""),
        "responsible_role": str(group.get("responsible_role") or ""),
        "certificate_no": certificate_no,
        "registered_unit_name": str(certificate_group.get("registered_unit_name") or stage4_group.get("registered_unit_name_optional") or ""),
        "registration_category": str(certificate_group.get("registration_category") or stage4_group.get("required_registration_category_optional") or ""),
        "matched_company_name": str(certificate_group.get("matched_company_name") or stage4_group.get("matched_company_name_optional") or ""),
        "personnel_public_source_url": str(
            certificate_group.get("personnel_public_source_url")
            or stage4_group.get("personnel_project_source_url")
            or stage4_group.get("company_personnel_source_url")
            or ""
        ),
        "bid_price": str(group.get("bid_price") or ""),
        "rank": str(group.get("rank") or group.get("candidate_group_order") or ""),
        "certificate_supplement_state": str(certificate_group.get("certificate_supplement_state") or ""),
        "stage4_execution_state": str(stage4_group.get("stage4_execution_state") or ""),
        "flow_08_targeted_parse_required": bool(certificate_group.get("flow_08_targeted_parse_required"))
        or bool(group.get("flow_08_targeted_parse_required")),
        "field_lineage_record_ids": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _flow_url_summary(
    flow_items: list[Mapping[str, Any]],
    download_items: list[Mapping[str, Any]],
    evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in flow_items:
        rows.append(
            {
                "flow_no": str(item.get("guangzhou_flow_no") or item.get("flow_no") or ""),
                "flow_title": str(item.get("guangzhou_flow_title") or item.get("flow_title") or ""),
                "source_url": str(item.get("source_url") or ""),
                "published_date": str(item.get("published_at_optional") or item.get("published_date") or ""),
                "source_family": "flow_url_manifest",
            }
        )
    for item in download_items:
        rows.append(
            {
                "flow_no": str(item.get("guangzhou_flow_no") or item.get("flow_no") or ""),
                "flow_title": str(item.get("guangzhou_flow_title") or item.get("flow_title") or ""),
                "source_url": str(item.get("source_url") or ""),
                "published_date": str(item.get("published_at_optional") or item.get("published_date") or ""),
                "source_family": "download_manifest",
            }
        )
    for url in _list(evidence.get("candidate_notice_source_urls")):
        rows.append(
            {
                "flow_no": "07",
                "flow_title": "中标候选人公示",
                "source_url": str(url or ""),
                "published_date": "",
                "source_family": "evidence_report_candidate_notice",
            }
        )
    return _dedupe_records(rows, ("flow_no", "source_url"))


def _source_fixation_records(
    *,
    project_records: list[Mapping[str, Any]],
    evidence_manifest: Mapping[str, Any],
    certificate_manifest: Mapping[str, Any],
    official_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
    download_manifest: Mapping[str, Any],
    flow_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _list(flow_manifest.get("project_sample_items")):
        if not isinstance(item, Mapping):
            continue
        records.append(
            _fixation_record(
                project_id=str(item.get("project_id") or ""),
                source_family="flow_url_manifest",
                source_url=str(item.get("source_url") or ""),
                flow_no=str(item.get("guangzhou_flow_no") or item.get("flow_no") or ""),
                flow_title=str(item.get("guangzhou_flow_title") or item.get("flow_title") or ""),
                capture_time=str(item.get("created_at") or item.get("published_at_optional") or ""),
                published_date=str(item.get("published_at_optional") or ""),
                access_path="flow_run_manifest.project_sample_items",
                script_version=str(flow_manifest.get("adapter_id") or "flowurl-runner"),
                snapshot_id="",
                readback_ref="",
                sha256="",
                local_path=str(item.get("guangzhou_flow_folder") or ""),
            )
        )
    for item in _list(download_manifest.get("project_sample_items")):
        if not isinstance(item, Mapping):
            continue
        base = {
            "project_id": str(item.get("project_id") or ""),
            "flow_no": str(item.get("guangzhou_flow_no") or item.get("flow_no") or ""),
            "flow_title": str(item.get("guangzhou_flow_title") or item.get("flow_title") or ""),
            "capture_time": str(item.get("created_at") or item.get("published_at_optional") or ""),
            "published_date": str(item.get("published_at_optional") or ""),
            "script_version": str(download_manifest.get("adapter_id") or "download-probe"),
        }
        for ref in _list(item.get("detail_snapshot_refs")):
            if isinstance(ref, Mapping):
                records.append(_fixation_record_from_snapshot_ref(base=base, source_family="download_detail_snapshot", ref=ref))
        for ref in _list(item.get("attachment_snapshot_refs")):
            if isinstance(ref, Mapping):
                records.append(_fixation_record_from_snapshot_ref(base=base, source_family="download_attachment_snapshot", ref=ref))
        if not item.get("detail_snapshot_refs") and item.get("source_url"):
            records.append(
                _fixation_record(
                    project_id=base["project_id"],
                    source_family="download_flow_item",
                    source_url=str(item.get("source_url") or ""),
                    flow_no=base["flow_no"],
                    flow_title=base["flow_title"],
                    capture_time=base["capture_time"],
                    published_date=base["published_date"],
                    access_path="download_probe_manifest.project_sample_items",
                    script_version=base["script_version"],
                    snapshot_id="",
                    readback_ref="",
                    sha256="",
                    local_path=str(item.get("guangzhou_flow_folder") or ""),
                )
            )
    for item in _list(stage4_manifest.get("items")):
        if not isinstance(item, Mapping):
            continue
        for url_key, snapshot_key, family in (
            ("company_personnel_source_url", "company_personnel_source_snapshot_id", "stage4_company_personnel_readback"),
            ("personnel_project_source_url", "personnel_project_source_snapshot_id", "stage4_personnel_project_readback"),
        ):
            url = str(item.get(url_key) or "")
            snapshot = str(item.get(snapshot_key) or "")
            if not url and not snapshot:
                continue
            records.append(
                _fixation_record(
                    project_id=str(item.get("project_id") or ""),
                    source_family=family,
                    source_url=url,
                    flow_no=str(item.get("flow_no") or ""),
                    flow_title=str(item.get("flow_title") or ""),
                    capture_time=str(item.get("created_at") or ""),
                    published_date="",
                    access_path=f"company_first_stage4_execution.items.{url_key}",
                    script_version=str(stage4_manifest.get("adapter_id") or "company-first-stage4-execution"),
                    snapshot_id=snapshot,
                    readback_ref=str(item.get("job_id") or ""),
                    sha256="",
                    local_path="",
                    candidate_group_id=str(item.get("candidate_group_id") or ""),
                )
            )
    for rec in _list(official_manifest.get("project_gdcic_classification_records")):
        if not isinstance(rec, Mapping):
            continue
        records.append(
            _fixation_record(
                project_id=str(rec.get("project_id") or ""),
                source_family="official_source_readback_summary",
                source_url=str(rec.get("source_url") or ""),
                flow_no="",
                flow_title="",
                capture_time=str(official_manifest.get("created_at") or ""),
                published_date="",
                access_path="official_source_readback.project_gdcic_classification_records",
                script_version=str(official_manifest.get("adapter_id") or "official-source-readback-closeout"),
                snapshot_id="",
                readback_ref=str(rec.get("query_task_id") or ""),
                sha256=_fingerprint(rec) if rec else "",
                local_path="",
                candidate_group_id=str(rec.get("candidate_group_id") or ""),
            )
        )
    for project in project_records:
        for url in _list(project.get("candidate_notice_source_urls")):
            records.append(
                _fixation_record(
                    project_id=str(project.get("project_id") or ""),
                    source_family="evidence_report_candidate_notice_url",
                    source_url=str(url or ""),
                    flow_no="07",
                    flow_title="中标候选人公示",
                    capture_time=str(evidence_manifest.get("created_at") or ""),
                    published_date="",
                    access_path="evidence_report.verification_evidence.candidate_notice_source_urls",
                    script_version=str(evidence_manifest.get("adapter_id") or "guangzhou-evidence-report-v1-builder"),
                    snapshot_id="",
                    readback_ref=str(evidence_manifest.get("manifest_id") or ""),
                    sha256="",
                    local_path="",
                )
            )
    return _dedupe_records(records, ("project_id", "source_family", "source_url", "snapshot_id", "readback_ref"))


def _backfilled_source_fixation_records(
    source_fixation_records: list[Mapping[str, Any]],
    backfill_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    backfill_by_source_id = {
        str(row.get("source_fixation_id") or ""): dict(row)
        for row in _list(backfill_manifest.get("backfill_records"))
        if isinstance(row, Mapping) and str(row.get("source_fixation_id") or "")
    }
    out: list[dict[str, Any]] = []
    for record in source_fixation_records:
        if str(record.get("fixation_state") or "") == "FIXATION_COMPLETE":
            continue
        source_id = str(record.get("source_fixation_id") or "")
        backfill = backfill_by_source_id.get(source_id)
        if not backfill:
            out.append(
                {
                    **dict(record),
                    "backfill_state": "BACKFILL_NOT_AVAILABLE",
                    "backfill_classification": "NOT_RUN_OR_NO_MATCH",
                    "backfill_record_id": "",
                    "strict_fixation_state": "STRICT_FIXATION_GAP",
                    "classified_fixation_state": "UNCLASSIFIED_GAP",
                }
            )
            continue
        fields = dict(backfill.get("backfilled_fields") or {})
        remaining = _list(backfill.get("remaining_gap_reasons"))
        merged = {
            **dict(record),
            "source_url": str(fields.get("source_url") or record.get("source_url") or ""),
            "snapshot_id": str(fields.get("snapshot_id") or record.get("snapshot_id") or ""),
            "readback_ref": str(fields.get("readback_ref") or record.get("readback_ref") or ""),
            "sha256": str(fields.get("sha256") or record.get("sha256") or ""),
            "local_path": str(fields.get("local_path") or record.get("local_path") or ""),
            "backfill_state": str(backfill.get("backfill_state") or ""),
            "backfill_classification": str(backfill.get("backfill_classification") or ""),
            "backfill_record_id": str(backfill.get("backfill_record_id") or ""),
            "backfill_source_ref": str(backfill.get("backfill_source_ref") or ""),
            "readback_record_sha256": str(fields.get("readback_record_sha256") or ""),
            "query_params": fields.get("query_params") or {},
            "remaining_gap_reasons": remaining,
            "strict_fixation_state": "STRICT_FIXATION_GAP",
            "classified_fixation_state": "CLASSIFIED_GAP_REVIEW" if remaining else "BACKFILLED_NO_REMAINING_GAP",
        }
        out.append(merged)
    return out


def _fixation_record_from_snapshot_ref(*, base: Mapping[str, str], source_family: str, ref: Mapping[str, Any]) -> dict[str, Any]:
    return _fixation_record(
        project_id=base["project_id"],
        source_family=source_family,
        source_url=str(ref.get("source_url") or ref.get("attachment_url") or ""),
        flow_no=base["flow_no"],
        flow_title=base["flow_title"],
        capture_time=base["capture_time"],
        published_date=base["published_date"],
        access_path=f"download_probe_manifest.project_sample_items.{source_family}",
        script_version=base["script_version"],
        snapshot_id=str(ref.get("snapshot_id") or ""),
        readback_ref=str(ref.get("readback_state") or ""),
        sha256=str(ref.get("sha256") or ""),
        local_path=str(ref.get("human_readable_path") or ref.get("local_path") or ""),
        content_type=str(ref.get("content_type") or ""),
        byte_size=_int(ref.get("byte_size")),
    )


def _fixation_record(
    *,
    project_id: str,
    source_family: str,
    source_url: str,
    flow_no: str,
    flow_title: str,
    capture_time: str,
    published_date: str,
    access_path: str,
    script_version: str,
    snapshot_id: str,
    readback_ref: str,
    sha256: str,
    local_path: str,
    candidate_group_id: str = "",
    content_type: str = "",
    byte_size: int = 0,
) -> dict[str, Any]:
    gaps = []
    if not source_url:
        gaps.append("source_url_missing")
    if not capture_time:
        gaps.append("capture_time_missing")
    if not access_path:
        gaps.append("access_path_missing")
    if not script_version:
        gaps.append("script_version_missing")
    if not snapshot_id and not readback_ref:
        gaps.append("snapshot_or_readback_ref_missing")
    if not sha256 and not _looks_hash(readback_ref):
        gaps.append("sha256_or_hash_missing")
    state = "FIXATION_COMPLETE" if not gaps else "FIXATION_GAP_REVIEW"
    payload = {
        "project_id": project_id,
        "candidate_group_id": candidate_group_id,
        "source_family": source_family,
        "source_url": source_url,
        "flow_no": flow_no,
        "flow_title": flow_title,
        "capture_time": capture_time,
        "published_date": published_date,
        "access_path": access_path,
        "script_version": script_version,
        "snapshot_id": snapshot_id,
        "readback_ref": readback_ref,
        "sha256": sha256,
        "local_path": local_path,
        "content_type": content_type,
        "byte_size": byte_size,
        "fixation_state": state,
        "fixation_gap_reasons": gaps,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload["source_fixation_id"] = f"FIX-{_fingerprint(payload)[:16]}"
    return payload


def _field_lineage_records(
    *,
    project_records: list[Mapping[str, Any]],
    source_fixation_records: list[Mapping[str, Any]],
    evidence_manifest: Mapping[str, Any],
    certificate_manifest: Mapping[str, Any],
    official_manifest: Mapping[str, Any],
    stage4_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    fixation_by_project = _fixations_by_project(source_fixation_records)
    for project in project_records:
        project_id = str(project.get("project_id") or "")
        source_ids = [str(row.get("source_fixation_id") or "") for row in fixation_by_project.get(project_id, [])]
        for group in _list(project.get("candidate_group_records")):
            if not isinstance(group, Mapping):
                continue
            group_id = str(group.get("candidate_group_id") or "")
            for field_name in (
                "candidate_group_members",
                "responsible_person_name",
                "certificate_no",
                "registered_unit_name",
                "registration_category",
                "bid_price",
                "rank",
            ):
                value = group.get(field_name)
                producer = "certificate_supplement_closeout" if field_name in {"certificate_no", "registered_unit_name", "registration_category"} else "evidence_report"
                records.append(
                    _lineage_record(
                        project_id=project_id,
                        candidate_group_id=group_id,
                        field_name=field_name,
                        field_value_probe=_compact_value(value),
                        producer_manifest_kind=str(
                            certificate_manifest.get("manifest_kind") if producer == "certificate_supplement_closeout" else evidence_manifest.get("manifest_kind")
                        ),
                        producer_adapter_id=str(
                            certificate_manifest.get("adapter_id") if producer == "certificate_supplement_closeout" else evidence_manifest.get("adapter_id")
                        ),
                        json_path=f"project_records[{project_id}].candidate_group_records[{group_id}].{field_name}",
                        source_fixation_ids=source_ids,
                    )
                )
        for field_name in (
            "official_source_readback_state",
            "official_source_readback_ready_count",
            "gdcic_readback_classification_counts",
            "gdcic_field_availability_counts",
            "gdcic_missing_field_counts",
            "gdcic_certificate_field_availability_state",
        ):
            records.append(
                _lineage_record(
                    project_id=project_id,
                    candidate_group_id="",
                    field_name=field_name,
                    field_value_probe=_compact_value(project.get(field_name)),
                    producer_manifest_kind=str(official_manifest.get("manifest_kind") or ""),
                    producer_adapter_id=str(official_manifest.get("adapter_id") or ""),
                    json_path=f"project_records[{project_id}].{field_name}",
                    source_fixation_ids=source_ids,
                )
            )
    for item in _list(stage4_manifest.get("items")):
        if not isinstance(item, Mapping):
            continue
        if not item.get("resolved_certificate_no_optional"):
            continue
        project_id = str(item.get("project_id") or "")
        group_id = str(item.get("candidate_group_id") or "")
        source_ids = [str(row.get("source_fixation_id") or "") for row in fixation_by_project.get(project_id, [])]
        records.append(
            _lineage_record(
                project_id=project_id,
                candidate_group_id=group_id,
                field_name="stage4_resolved_certificate_no",
                field_value_probe=str(item.get("resolved_certificate_no_optional") or ""),
                producer_manifest_kind=str(stage4_manifest.get("manifest_kind") or ""),
                producer_adapter_id=str(stage4_manifest.get("adapter_id") or ""),
                json_path=f"stage4.items[{item.get('job_id') or group_id}].resolved_certificate_no_optional",
                source_fixation_ids=source_ids,
            )
        )
    return _dedupe_records(records, ("project_id", "candidate_group_id", "field_name", "field_value_probe", "json_path"))


def _lineage_record(
    *,
    project_id: str,
    candidate_group_id: str,
    field_name: str,
    field_value_probe: str,
    producer_manifest_kind: str,
    producer_adapter_id: str,
    json_path: str,
    source_fixation_ids: list[str],
) -> dict[str, Any]:
    payload = {
        "project_id": project_id,
        "candidate_group_id": candidate_group_id,
        "field_name": field_name,
        "field_value_probe": field_value_probe,
        "producer_manifest_kind": producer_manifest_kind,
        "producer_adapter_id": producer_adapter_id,
        "json_path": json_path,
        "source_fixation_ids": [value for value in source_fixation_ids if value],
        "lineage_state": "FIELD_LINEAGE_READY" if producer_manifest_kind and json_path else "FIELD_LINEAGE_REVIEW",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload["field_lineage_id"] = f"LIN-{_fingerprint(payload)[:16]}"
    return payload


def _reverse_explanations(
    *,
    project_records: list[Mapping[str, Any]],
    source_fixation_records: list[Mapping[str, Any]],
    official_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    gaps_by_project: dict[str, set[str]] = {}
    for row in source_fixation_records:
        if row.get("fixation_state") != "FIXATION_COMPLETE":
            gaps_by_project.setdefault(str(row.get("project_id") or ""), set()).update(_list(row.get("fixation_gap_reasons")))
    official_by_project = {
        str(row.get("project_id") or ""): dict(row)
        for row in _list(official_manifest.get("project_records"))
        if isinstance(row, Mapping)
    }
    for project in project_records:
        project_id = str(project.get("project_id") or "")
        if project.get("gdcic_certificate_field_availability_state"):
            out.append(
                _reverse_record(
                    project_id=project_id,
                    explanation_type="GDCIC_CERTIFICATE_FIELD_GAP",
                    explanation_state=str(project.get("gdcic_certificate_field_availability_state") or ""),
                    recommended_action="USE_STAGE4_OR_OTHER_OFFICIAL_SOURCE_FOR_CERTIFICATE_FIELDS",
                )
            )
        official = official_by_project.get(project_id, {})
        blockers = _list(official.get("blocker_taxonomy_counts")) or list((official.get("blocker_taxonomy_counts") or {}).keys())
        if blockers:
            out.append(
                _reverse_record(
                    project_id=project_id,
                    explanation_type="OFFICIAL_SOURCE_BLOCKER_OR_EMPTY_RESULT",
                    explanation_state="REVIEW_REQUIRED",
                    recommended_action="RETRY_SOURCE_OR_USE_SOURCE_SPECIFIC_ADAPTER",
                    blocker_taxonomy=blockers,
                )
            )
        if gaps_by_project.get(project_id):
            out.append(
                _reverse_record(
                    project_id=project_id,
                    explanation_type="SOURCE_FIXATION_GAP",
                    explanation_state="FIXATION_GAP_REVIEW",
                    recommended_action="BACKFILL_SNAPSHOT_READBACK_HASH_OR_CAPTURE_TIME",
                    fixation_gap_reasons=sorted(gaps_by_project[project_id]),
                )
            )
        if not project.get("flow_08_targeted_parse_required"):
            out.append(
                _reverse_record(
                    project_id=project_id,
                    explanation_type="FLOW_08_NOT_DEFAULT_PARSED",
                    explanation_state="REGISTER_ONLY_BACKUP_NO_TRIGGER",
                    recommended_action="KEEP_FLOW_08_REGISTERED_FOR_TARGETED_PARSE_ONLY",
                )
            )
    return out


def _reverse_record(
    *,
    project_id: str,
    explanation_type: str,
    explanation_state: str,
    recommended_action: str,
    blocker_taxonomy: list[Any] | None = None,
    fixation_gap_reasons: list[Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "project_id": project_id,
        "explanation_type": explanation_type,
        "explanation_state": explanation_state,
        "recommended_action": recommended_action,
        "blocker_taxonomy": _list(blocker_taxonomy),
        "fixation_gap_reasons": _list(fixation_gap_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload["reverse_explanation_id"] = f"REV-{_fingerprint(payload)[:16]}"
    return payload


def _redaction_log(source_fixation_records: list[Mapping[str, Any]], field_lineage_records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "redaction_state": "INTERNAL_ONLY_REDACTION_APPLIED",
        "raw_html_blob_exported": False,
        "raw_pdf_or_office_blob_exported": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "withheld_groups": [
            "raw_html",
            "raw_pdf_doc_xls_archive_blob",
            "provider_internal_trace",
            "full_person_identifier",
            "unapproved_customer_delivery_package",
        ],
        "source_fixation_record_count": len(source_fixation_records),
        "field_lineage_record_count": len(field_lineage_records),
        "redaction_notes": [
            "manifest_keeps_refs_hashes_and_limited_field_probes_only",
            "customer_delivery_requires_separate_approval_and_projection",
        ],
    }


def _verification_summary(
    project_records: list[Mapping[str, Any]],
    certificate_manifest: Mapping[str, Any],
    official_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    cert_summary = dict(certificate_manifest.get("summary") or {})
    official_summary = dict(official_manifest.get("summary") or {})
    return {
        "project_count": len(project_records),
        "candidate_group_count": sum(_int(row.get("candidate_group_count")) for row in project_records),
        "certificate_resolved_group_count": _int(cert_summary.get("certificate_resolved_group_count")),
        "certificate_unresolved_group_count": _int(cert_summary.get("certificate_unresolved_group_count")),
        "flow_08_targeted_parse_required_count": _int(cert_summary.get("flow_08_targeted_parse_required_count")),
        "gdcic_certificate_field_gap_compensated_by_stage4_count": _int(
            cert_summary.get("gdcic_certificate_field_gap_compensated_by_stage4_count")
        ),
        "official_source_readback_ready_count": _int(official_summary.get("official_source_readback_ready_count")),
        "gdcic_certificate_field_availability_state": str(official_summary.get("gdcic_certificate_field_availability_state") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    project_records: list[Mapping[str, Any]],
    candidate_group_records: list[Mapping[str, Any]],
    source_fixation_records: list[Mapping[str, Any]],
    backfilled_source_fixation_records: list[Mapping[str, Any]],
    field_lineage_records: list[Mapping[str, Any]],
    reverse_explanations: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    certificate_manifest: Mapping[str, Any],
    backfill_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    fixation_gap_count = sum(1 for row in source_fixation_records if row.get("fixation_state") != "FIXATION_COMPLETE")
    backfill_summary = dict(backfill_manifest.get("summary") or {})
    strict_gap_count = fixation_gap_count
    classified_gap_count = sum(1 for row in backfilled_source_fixation_records if row.get("classified_fixation_state") == "CLASSIFIED_GAP_REVIEW")
    backfilled_no_remaining_gap_count = sum(
        1 for row in backfilled_source_fixation_records if row.get("classified_fixation_state") == "BACKFILLED_NO_REMAINING_GAP"
    )
    certificate_summary = dict(certificate_manifest.get("summary") or {})
    candidate_group_count = len(candidate_group_records)
    resolved_count = _int(certificate_summary.get("certificate_resolved_group_count")) or sum(
        1
        for row in candidate_group_records
        if str(row.get("certificate_supplement_state") or "").startswith("CERTIFICATE_SUPPLEMENT_RESOLVED")
    )
    flow08_count = _int(certificate_summary.get("flow_08_targeted_parse_required_count")) or sum(
        1 for row in candidate_group_records if row.get("flow_08_targeted_parse_required")
    )
    internal_state = (
        "P7_INTERNAL_EVIDENCE_PACKAGE_READY"
        if not blocking_reasons and project_records and candidate_group_count and resolved_count == candidate_group_count and flow08_count == 0
        else "P7_INTERNAL_EVIDENCE_PACKAGE_REVIEW_REQUIRED"
    )
    return {
        "internal_package_state": internal_state,
        "project_count": len(project_records),
        "candidate_group_count": candidate_group_count,
        "certificate_resolved_group_count": resolved_count,
        "certificate_unresolved_group_count": _int(certificate_summary.get("certificate_unresolved_group_count")),
        "flow_08_targeted_parse_required_count": flow08_count,
        "gdcic_certificate_field_gap_compensated_by_stage4_count": _int(
            certificate_summary.get("gdcic_certificate_field_gap_compensated_by_stage4_count")
        ),
        "source_fixation_record_count": len(source_fixation_records),
        "fixation_complete_count": len(source_fixation_records) - fixation_gap_count,
        "fixation_gap_count": fixation_gap_count,
        "fixation_completeness_state": "SOURCE_FIXATION_COMPLETE" if fixation_gap_count == 0 else "SOURCE_FIXATION_PARTIAL_REVIEW",
        "source_fixation_backfill_state": str(backfill_summary.get("backfill_state") or "NOT_BUILT"),
        "strict_fixation_gap_count": strict_gap_count,
        "classified_fixation_gap_count": classified_gap_count,
        "backfilled_no_remaining_gap_count": backfilled_no_remaining_gap_count,
        "backfill_unfixable_with_current_artifacts_count": _int(backfill_summary.get("unfixable_with_current_artifacts_count")),
        "field_lineage_record_count": len(field_lineage_records),
        "reverse_explanation_count": len(reverse_explanations),
        "forbidden_term_scan_state": "PASS",
        "customer_delivery_ready": False,
        "approval_required_before_customer_delivery": True,
        "trusted_timestamp_state": "RESERVED_NOT_IMPLEMENTED",
        "notary_state": "RESERVED_NOT_IMPLEMENTED",
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _project_records_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [dict(item) for item in _list(manifest.get("project_records")) if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id]


def _items_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    out = []
    for key in ("items", "project_sample_items", "stage4_candidate_verification_inputs"):
        for item in _list(manifest.get(key)):
            if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id:
                out.append(dict(item))
    return out


def _flow_items_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _list(manifest.get("project_sample_items"))
        if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id
    ]


def _download_items_for_project(manifest: Mapping[str, Any], project_id: str) -> list[dict[str, Any]]:
    out = []
    for key in ("items", "project_sample_items"):
        for item in _list(manifest.get(key)):
            if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id:
                out.append(dict(item))
    return out


def _fixations_by_project(records: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        out.setdefault(str(record.get("project_id") or ""), []).append(record)
    return out


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        blocking_reasons.append(f"{missing_reason}_invalid_json")
        return {}
    return data if isinstance(data, dict) else {}


def _load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else None
    if isinstance(manifest, Mapping):
        return dict(manifest)
    return dict(payload) if isinstance(payload, Mapping) else {}


def _first(items: Iterable[Any]) -> dict[str, Any]:
    for item in items:
        if isinstance(item, Mapping):
            return dict(item)
    return {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def _compact_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "; ".join(_dedupe(value))[:500]
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:500]
    return str(value or "")[:500]


def _looks_hash(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) in {32, 40, 64} and all(ch in "0123456789abcdef" for ch in text)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangzhou internal evidence package manifest v1.")
    parser.add_argument("--evidence-report-root", default=str(DEFAULT_EVIDENCE_REPORT_ROOT))
    parser.add_argument("--certificate-supplement-root", default=str(DEFAULT_CERTIFICATE_SUPPLEMENT_ROOT))
    parser.add_argument("--official-source-readback-root", default=str(DEFAULT_OFFICIAL_SOURCE_READBACK_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--flow-root", default=str(DEFAULT_FLOW_ROOT))
    parser.add_argument("--fixation-backfill-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = build_guangzhou_internal_evidence_package_manifest(
        evidence_report_root=args.evidence_report_root,
        certificate_supplement_root=args.certificate_supplement_root,
        official_source_readback_root=args.official_source_readback_root,
        stage4_execution_root=args.stage4_execution_root,
        download_root=args.download_root,
        flow_root=args.flow_root,
        fixation_backfill_root=args.fixation_backfill_root or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
