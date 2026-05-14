from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


CERTIFICATE_SUPPLEMENT_CLOSEOUT_KIND = "certificate_supplement_closeout_v1_manifest"
CERTIFICATE_SUPPLEMENT_CLOSEOUT_VERSION = 1
CERTIFICATE_SUPPLEMENT_CLOSEOUT_ADAPTER_ID = "certificate-supplement-closeout-v1"

DEFAULT_EVIDENCE_REPORT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-evidence-report-p5-closeout-v1")
DEFAULT_STAGE4_EXECUTION_ROOT = Path("tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v4-merged")
DEFAULT_OFFICIAL_SOURCE_READBACK_ROOT = Path("tmp/evaluation-real-samples/guangdong-official-source-readback-closeout-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/certificate-supplement-closeout-v1")

FORBIDDEN_TERMS = ("是不是本人", "确认本人", "无风险", "无冲突", "在建冲突成立", "冲突成立", "造假成立", "违法成立")

GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED = "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK"
CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4 = "CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4"
CERTIFICATE_SUPPLEMENT_RESOLVED_FROM_07 = "CERTIFICATE_SUPPLEMENT_RESOLVED_FROM_07"
CERTIFICATE_SUPPLEMENT_UNRESOLVED_REVIEW = "CERTIFICATE_SUPPLEMENT_UNRESOLVED_REVIEW"
FLOW_08_TARGETED_PARSE_REQUIRED_AFTER_SUPPLEMENT = "FLOW_08_TARGETED_PARSE_REQUIRED_AFTER_SUPPLEMENT"


def build_certificate_supplement_closeout(
    *,
    evidence_report_root: str | Path = DEFAULT_EVIDENCE_REPORT_ROOT,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    official_source_readback_root: str | Path = DEFAULT_OFFICIAL_SOURCE_READBACK_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
    official_source_required: bool = True,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    evidence_dir = Path(evidence_report_root)
    stage4_dir = Path(stage4_execution_root)
    official_dir = Path(official_source_readback_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    evidence_manifest = _source_manifest(
        _load_json(evidence_dir / "guangzhou-evidence-report-v1.json", blocking_reasons, "evidence_report_missing")
    )
    stage4_manifest = _source_manifest(
        _load_json(stage4_dir / "company-first-stage4-execution.json", blocking_reasons, "stage4_execution_missing")
    )
    official_missing_reasons: list[str] = []
    official_manifest = _source_manifest(
        _load_json(
            official_dir / "guangdong-official-source-readback-closeout-v1.json",
            blocking_reasons if official_source_required else official_missing_reasons,
            "official_source_readback_missing",
        )
    )

    stage4_items = _list(stage4_manifest.get("items"))
    project_records = [
        _project_record(project=project, stage4_items=stage4_items, official_manifest=official_manifest)
        for project in _list(evidence_manifest.get("project_reports"))
        if isinstance(project, Mapping)
    ]
    group_records = [
        group
        for project in project_records
        for group in _list(project.get("certificate_supplement_group_records"))
    ]
    summary = _summary(project_records=project_records, group_records=group_records, blocking_reasons=blocking_reasons)
    if official_missing_reasons:
        summary["official_source_readback_optional_missing_reasons"] = official_missing_reasons
        summary["official_source_readback_is_not_closeout_gate"] = True
    manifest = {
        "manifest_version": CERTIFICATE_SUPPLEMENT_CLOSEOUT_VERSION,
        "manifest_kind": CERTIFICATE_SUPPLEMENT_CLOSEOUT_KIND,
        "adapter_id": CERTIFICATE_SUPPLEMENT_CLOSEOUT_ADAPTER_ID,
        "pipeline_stage": "CertificateSupplementCloseoutV1",
        "manifest_id": f"CERTIFICATE-SUPPLEMENT-CLOSEOUT-{_fingerprint({'summary': summary, 'projects': project_records})[:16]}",
        "created_at": created,
        "source_evidence_report_root": str(evidence_dir),
        "source_stage4_execution_root": str(stage4_dir),
        "source_official_source_readback_root": str(official_dir),
        "official_source_required": official_source_required,
        "project_records": project_records,
        "certificate_supplement_group_records": group_records,
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
        "certificate_supplement_closeout_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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
    (out_dir / "certificate-supplement-closeout-v1.json").write_text(text, encoding="utf-8")
    return result


def _project_record(*, project: Mapping[str, Any], stage4_items: list[Any], official_manifest: Mapping[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("project_id") or "")
    evidence = dict(project.get("verification_evidence") or {})
    gdcic_state = str(evidence.get("gdcic_certificate_field_availability_state") or _official_project_gdcic_state(official_manifest, project_id))
    project_stage4_items = [item for item in stage4_items if isinstance(item, Mapping) and str(item.get("project_id") or "") == project_id]
    group_records = [
        _group_record(
            project_id=project_id,
            project_name=str(project.get("project_name") or evidence.get("project_name") or ""),
            group=group,
            stage4_items=project_stage4_items,
            gdcic_certificate_field_availability_state=gdcic_state,
        )
        for group in _list(evidence.get("candidate_group_records"))
        if isinstance(group, Mapping)
    ]
    return {
        "project_id": project_id,
        "project_name": str(project.get("project_name") or evidence.get("project_name") or ""),
        "gdcic_certificate_field_availability_state": gdcic_state,
        "candidate_group_count": len(group_records),
        "certificate_resolved_group_count": sum(1 for row in group_records if _is_resolved(row)),
        "certificate_unresolved_group_count": sum(1 for row in group_records if row.get("certificate_supplement_state") == CERTIFICATE_SUPPLEMENT_UNRESOLVED_REVIEW),
        "flow_08_targeted_parse_required_count": sum(1 for row in group_records if bool(row.get("flow_08_targeted_parse_required"))),
        "gdcic_certificate_field_gap_compensated_by_stage4_count": sum(
            1
            for row in group_records
            if row.get("gdcic_certificate_field_availability_state") == GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED
            and row.get("certificate_supplement_state") == CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4
        ),
        "certificate_supplement_group_records": group_records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _group_record(
    *,
    project_id: str,
    project_name: str,
    group: Mapping[str, Any],
    stage4_items: list[Any],
    gdcic_certificate_field_availability_state: str,
) -> dict[str, Any]:
    group_id = str(group.get("candidate_group_id") or "")
    group_stage4_items = [
        item
        for item in stage4_items
        if isinstance(item, Mapping) and str(item.get("candidate_group_id") or "") == group_id
    ]
    resolved_item = _resolved_stage4_item(group_stage4_items)
    flow08_required = bool(group.get("flow_08_targeted_parse_required")) or any(
        bool(item.get("flow_08_targeted_parse_required")) for item in group_stage4_items if isinstance(item, Mapping)
    )
    source_certificate_no = str(group.get("certificate_no") or "")
    resolved_certificate_no = str(resolved_item.get("resolved_certificate_no_optional") or source_certificate_no)
    state = _group_state(
        flow08_required=flow08_required,
        has_stage4_certificate=bool(resolved_item.get("resolved_certificate_no_optional")),
        has_source_certificate=bool(source_certificate_no),
    )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "candidate_group_id": group_id,
        "candidate_group_order": str(group.get("candidate_group_order") or ""),
        "candidate_group_members": _dedupe([*_list(group.get("candidate_group_members")), *_list(group.get("matched_company_names"))]),
        "responsible_person_name": str(group.get("responsible_person_name") or ""),
        "gdcic_certificate_field_availability_state": gdcic_certificate_field_availability_state,
        "stage4_supplement_state": str(resolved_item.get("supplement_after_execution_state") or "NOT_RESOLVED_BY_STAGE4"),
        "certificate_supplement_state": state,
        "certificate_no": resolved_certificate_no,
        "registered_unit_name": str(resolved_item.get("registered_unit_name_optional") or ""),
        "registration_category": str(resolved_item.get("required_registration_category_optional") or ""),
        "matched_company_name": str(
            resolved_item.get("candidate_group_matched_company_name_optional")
            or resolved_item.get("matched_company_name_optional")
            or resolved_item.get("registered_unit_name_optional")
            or resolved_item.get("candidate_company_name")
            or ""
        ),
        "personnel_public_source_url": str(
            resolved_item.get("personnel_project_source_url")
            or resolved_item.get("company_personnel_source_url")
            or ""
        ),
        "stage4_execution_state": str(resolved_item.get("stage4_execution_state") or "NOT_RESOLVED_BY_STAGE4"),
        "flow_08_targeted_parse_required": flow08_required,
        "next_action": _next_action(state),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _group_state(*, flow08_required: bool, has_stage4_certificate: bool, has_source_certificate: bool) -> str:
    if flow08_required:
        return FLOW_08_TARGETED_PARSE_REQUIRED_AFTER_SUPPLEMENT
    if has_stage4_certificate:
        return CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4
    if has_source_certificate:
        return CERTIFICATE_SUPPLEMENT_RESOLVED_FROM_07
    return CERTIFICATE_SUPPLEMENT_UNRESOLVED_REVIEW


def _next_action(state: str) -> str:
    if state == CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4:
        return "USE_STAGE4_CERTIFICATE_FIELDS_FOR_INTERNAL_REVIEW"
    if state == CERTIFICATE_SUPPLEMENT_RESOLVED_FROM_07:
        return "USE_FLOW_07_CERTIFICATE_FIELDS_FOR_INTERNAL_REVIEW"
    if state == FLOW_08_TARGETED_PARSE_REQUIRED_AFTER_SUPPLEMENT:
        return "RUN_FLOW_08_TARGETED_PARSE"
    return "RETRY_PUBLIC_REGISTRATION_SOURCE_OR_NAME_ENUMERATION"


def _resolved_stage4_item(items: list[Any]) -> dict[str, Any]:
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("supplement_after_execution_state") or "") == "COMPANY_FIRST_CERTIFICATE_RESOLVED" and str(
            item.get("resolved_certificate_no_optional") or ""
        ):
            return dict(item)
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("stage4_execution_state") or "") == "READBACK_READY" and str(item.get("resolved_certificate_no_optional") or ""):
            return dict(item)
    return {}


def _summary(*, project_records: list[Mapping[str, Any]], group_records: list[Mapping[str, Any]], blocking_reasons: list[str]) -> dict[str, Any]:
    candidate_group_count = len(group_records)
    resolved_count = sum(1 for row in group_records if _is_resolved(row))
    unresolved_count = sum(1 for row in group_records if row.get("certificate_supplement_state") == CERTIFICATE_SUPPLEMENT_UNRESOLVED_REVIEW)
    flow08_count = sum(1 for row in group_records if bool(row.get("flow_08_targeted_parse_required")))
    closeout_state = (
        "P6_CERTIFICATE_SUPPLEMENT_READY"
        if not blocking_reasons and candidate_group_count and resolved_count == candidate_group_count and flow08_count == 0
        else "P6_CERTIFICATE_SUPPLEMENT_REVIEW_REQUIRED"
    )
    return {
        "closeout_state": closeout_state,
        "project_count": len(project_records),
        "candidate_group_count": candidate_group_count,
        "certificate_resolved_group_count": resolved_count,
        "certificate_unresolved_group_count": unresolved_count,
        "flow_08_targeted_parse_required_count": flow08_count,
        "gdcic_certificate_field_gap_compensated_by_stage4_count": sum(
            1
            for row in group_records
            if row.get("gdcic_certificate_field_availability_state") == GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED
            and row.get("certificate_supplement_state") == CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4
        ),
        "certificate_supplement_state_counts": _counts(row.get("certificate_supplement_state") for row in group_records),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _official_project_gdcic_state(official_manifest: Mapping[str, Any], project_id: str) -> str:
    for row in _list(official_manifest.get("project_records")):
        if isinstance(row, Mapping) and str(row.get("project_id") or "") == project_id:
            return str(row.get("gdcic_certificate_field_availability_state") or "")
    return str((official_manifest.get("summary") or {}).get("gdcic_certificate_field_availability_state") or "")


def _is_resolved(row: Mapping[str, Any]) -> bool:
    return str(row.get("certificate_supplement_state") or "") in {
        CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4,
        CERTIFICATE_SUPPLEMENT_RESOLVED_FROM_07,
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


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Certificate Supplement Closeout v1.")
    parser.add_argument("--evidence-report-root", default=str(DEFAULT_EVIDENCE_REPORT_ROOT))
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--official-source-readback-root", default=str(DEFAULT_OFFICIAL_SOURCE_READBACK_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--created-at")
    parser.add_argument("--official-source-optional", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_certificate_supplement_closeout(
        evidence_report_root=args.evidence_report_root,
        stage4_execution_root=args.stage4_execution_root,
        official_source_readback_root=args.official_source_readback_root,
        output_root=args.output_root,
        created_at=args.created_at,
        official_source_required=not args.official_source_optional,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
