from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from shared.utils import utc_now_iso


EVIDENCE_VERIFICATION_STRATEGY_MANIFEST_KIND = "evidence_verification_strategy_manifest"
EVIDENCE_VERIFICATION_STRATEGY_VERSION = 1
EVIDENCE_VERIFICATION_STRATEGY_ADAPTER_ID = "evidence-verification-strategy-v1-builder"

ARCHIVE_EXTENSIONS = {".zip", ".rar"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}
DEFAULT_PROJECT_IDS = ("PROJ-CN-GD-JG2026-10815", "PROJ-CN-GD-JG2026-11021")


FLOW_TITLES = {
    "01": "招标计划",
    "02": "招标文件公示",
    "03": "招标公告/关联公告",
    "04": "澄清答疑",
    "05": "开标信息",
    "06": "资审结果公示",
    "07": "中标候选人公示",
    "08": "投标(资格预审申请)文件公开",
    "09": "中标结果公示/公告",
    "10": "中标信息",
    "11": "合同信息公开",
    "12": "项目异常",
}


def build_evidence_verification_strategy(
    *,
    input_root: str | Path,
    output_root: str | Path,
    project_ids: list[str] | tuple[str, ...] = DEFAULT_PROJECT_IDS,
    download_probe_manifest_json: str | Path | None = None,
    analysis_plan_json: str | Path | None = None,
    parse_probe_manifest_json: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(input_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    blocking_reasons: list[str] = []

    download_path = Path(download_probe_manifest_json) if download_probe_manifest_json else in_root / "download-probe-manifest.json"
    download_payload = _load_json(download_path, blocking_reasons, "download_probe_manifest_missing")
    download_manifest = _source_manifest(download_payload)

    analysis_path = _resolve_analysis_plan_path(
        explicit=Path(analysis_plan_json) if analysis_plan_json else None,
        input_root=in_root,
        download_manifest=download_manifest,
    )
    analysis_payload = _load_json_optional(analysis_path)
    analysis_manifest = _source_manifest(analysis_payload)

    parse_path = Path(parse_probe_manifest_json) if parse_probe_manifest_json else in_root / "parse-probe-manifest.json"
    parse_manifest = _source_manifest(_load_json_optional(parse_path))

    selected_samples = _select_project_samples(download_manifest=download_manifest, project_ids=project_ids)
    if not selected_samples and not blocking_reasons:
        blocking_reasons.append("evidence_strategy_no_download_probe_samples_selected")

    analysis_lookup = _analysis_item_lookup(analysis_manifest)
    parse_lookup = _parse_item_lookup(parse_manifest)
    items: list[dict[str, Any]] = []
    for sample in selected_samples:
        items.extend(_strategy_items_for_sample(sample, analysis_lookup=analysis_lookup, parse_lookup=parse_lookup, created_at=created))

    summary = _summary(items=items, selected_samples=selected_samples, blocking_reasons=blocking_reasons)
    manifest = {
        "manifest_version": EVIDENCE_VERIFICATION_STRATEGY_VERSION,
        "manifest_kind": EVIDENCE_VERIFICATION_STRATEGY_MANIFEST_KIND,
        "adapter_id": EVIDENCE_VERIFICATION_STRATEGY_ADAPTER_ID,
        "pipeline_stage": "EvidenceVerificationStrategy",
        "manifest_id": f"EVIDENCE-VERIFICATION-STRATEGY-{_fingerprint({'items': items})[:16]}",
        "created_at": created,
        "source_input_root": str(in_root),
        "source_download_probe_manifest_path": str(download_path),
        "source_analysis_plan_path": str(analysis_path) if analysis_path else "",
        "source_parse_probe_manifest_path": str(parse_path) if parse_path.exists() else "",
        "project_ids": list(project_ids),
        "items": items,
        "sample_items": items[:100],
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "archive_extract_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "graphify_enabled": False,
            "mempalace_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "evidence_verification_strategy_mode": "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    output_path = out_root / "evidence-verification-strategy.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _strategy_items_for_sample(
    sample: Mapping[str, Any],
    *,
    analysis_lookup: Mapping[tuple[str, str, str], Mapping[str, Any]],
    parse_lookup: Mapping[str, Mapping[str, Any]],
    created_at: str,
) -> list[dict[str, Any]]:
    project_id = str(sample.get("project_id") or "")
    flow_no = _flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no"))
    source_url = str(sample.get("source_url") or "")
    analysis_item = dict(analysis_lookup.get((project_id, flow_no, source_url)) or {})
    if bool(analysis_item.get("adapter_validation_only")) or bool(sample.get("adapter_validation_only")):
        return [
            _strategy_item(
                sample=sample,
                ref={},
                item_index=1,
                created_at=created_at,
                strategy_state="SKIPPED_ADAPTER_VALIDATION_ONLY",
                verification_enabled=False,
                extract_policy="SKIP",
                parse_policy="SKIP",
                target_fields=[],
                stage4_targets=[],
                skip_reason="adapter_validation_only_not_evidence_package_input",
            )
        ]
    refs = [dict(ref) for ref in list(sample.get("attachment_snapshot_refs") or []) if isinstance(ref, Mapping)]
    if not refs:
        return [
            _strategy_item(
                sample=sample,
                ref={},
                item_index=1,
                created_at=created_at,
                strategy_state="NO_ATTACHMENT_REF_FOR_EVIDENCE_STRATEGY",
                verification_enabled=False,
                extract_policy="SKIP",
                parse_policy="SKIP",
                target_fields=[],
                stage4_targets=[],
                skip_reason="no_attachment_snapshot_refs",
            )
        ]

    targeted_parse_required = _flow_08_targeted_parse_required(
        sample=sample,
        analysis_item=analysis_item,
    )
    out: list[dict[str, Any]] = []
    for index, ref in enumerate(refs, start=1):
        flow_policy = _flow_policy(
            flow_no=flow_no,
            ref=ref,
            flow_08_targeted_parse_required=targeted_parse_required,
        )
        parsed_state = str((parse_lookup.get(str(ref.get("snapshot_id") or "")) or {}).get("parse_state") or "")
        out.append(
            _strategy_item(
                sample=sample,
                ref=ref,
                item_index=index,
                created_at=created_at,
                strategy_state=flow_policy["strategy_state"],
                verification_enabled=flow_policy["verification_enabled"],
                extract_policy=flow_policy["extract_policy"],
                parse_policy=flow_policy["parse_policy"],
                target_fields=flow_policy["target_fields"],
                stage4_targets=flow_policy["stage4_targets"],
                skip_reason=flow_policy["skip_reason"],
                parsed_state=parsed_state,
            )
        )
    return out


def _flow_policy(
    *,
    flow_no: str,
    ref: Mapping[str, Any],
    flow_08_targeted_parse_required: bool = False,
) -> dict[str, Any]:
    archive = _is_archive_ref(ref)
    document = _is_document_ref(ref)
    if flow_no == "07":
        return {
            "strategy_state": "EVIDENCE_VERIFICATION_READY",
            "verification_enabled": True,
            "extract_policy": "TARGETED_EXTRACT" if archive else "TEXT_PROBE" if document else "INVENTORY_ONLY",
            "parse_policy": "TEXT_PROBE",
            "target_fields": [
                "candidate_company",
                "candidate_rank",
                "bid_price",
                "project_manager_name",
                "certificate_no",
                "certificate_type",
                "registration_profession",
            ],
            "stage4_targets": [
                "project_manager_qualification",
                "project_manager_active_conflict",
                "candidate_verification",
                "real_competitor_identification",
            ],
            "skip_reason": "",
        }
    if flow_no == "08":
        if not flow_08_targeted_parse_required:
            return {
                "strategy_state": "FLOW_08_REGISTER_ONLY",
                "verification_enabled": False,
                "extract_policy": "INVENTORY_ONLY",
                "parse_policy": "SKIP",
                "target_fields": [
                    "attachment_inventory",
                    "candidate_or_bidder_file_groups",
                    "targeted_parse_candidate_keywords",
                ],
                "stage4_targets": [
                    "future_flow_08_targeted_parse_if_triggered",
                ],
                "skip_reason": "flow_08_registered_only_until_stage4_or_public_registration_trigger",
            }
        return {
            "strategy_state": "TARGETED_BID_PUBLICITY_SAMPLE_READY",
            "verification_enabled": True,
            "extract_policy": "TARGETED_EXTRACT" if archive else "TEXT_PROBE" if document else "INVENTORY_ONLY",
            "parse_policy": "TEXT_PROBE_THEN_TARGETED_DEEP_PARSE",
            "target_fields": [
                "candidate_company",
                "project_manager_name",
                "certificate_no",
                "bid_price",
                "rejection_reason",
            ],
            "stage4_targets": [
                "candidate_verification",
                "real_competitor_identification",
                "project_manager_qualification",
            ],
            "skip_reason": "",
        }
    if flow_no in {"03", "04"}:
        return {
            "strategy_state": "TENDER_RULE_COMPARISON_READY",
            "verification_enabled": True,
            "extract_policy": "TARGETED_EXTRACT" if archive else "SECTION_PARSE" if document else "INVENTORY_ONLY",
            "parse_policy": "SECTION_PARSE",
            "target_fields": [
                "qualification_requirement",
                "evaluation_method",
                "project_manager_requirement",
                "certificate_requirement",
                "rejection_rule",
            ],
            "stage4_targets": [
                "project_manager_qualification",
                "tender_rule_comparison",
                "tailored_bid_signal_context",
            ],
            "skip_reason": "",
        }
    if flow_no in {"05", "06", "09", "10", "11", "12"}:
        return {
            "strategy_state": "METADATA_OR_TEXT_PROBE_ONLY",
            "verification_enabled": flow_no in {"05", "06", "09", "10", "11", "12"},
            "extract_policy": "INVENTORY_ONLY" if archive else "TEXT_PROBE" if document else "SKIP",
            "parse_policy": "TEXT_PROBE" if document else "METADATA_ONLY",
            "target_fields": ["candidate_company", "rejection_reason", "bid_price"],
            "stage4_targets": ["candidate_verification"],
            "skip_reason": "",
        }
    return {
        "strategy_state": "FLOW_NOT_IN_EVIDENCE_STRATEGY_SCOPE",
        "verification_enabled": False,
        "extract_policy": "SKIP",
        "parse_policy": "SKIP",
        "target_fields": [],
        "stage4_targets": [],
        "skip_reason": "flow_not_in_evidence_strategy_scope",
    }


def _flow_08_targeted_parse_required(
    *,
    sample: Mapping[str, Any],
    analysis_item: Mapping[str, Any],
) -> bool:
    truthy_keys = (
        "flow_08_targeted_parse_required",
        "targeted_parse_required",
        "force_flow_08_targeted_parse",
        "public_registration_mismatch_requires_flow_08",
    )
    for source in (sample, analysis_item):
        for key in truthy_keys:
            if bool(source.get(key)):
                return True
        joined = " ".join(
            str(item)
            for item in [
                *_as_list(source.get("next_actions")),
                *_as_list(source.get("llm_trigger_reasons")),
                source.get("strategy_state"),
                source.get("skip_reason"),
            ]
        )
        if "FLOW_08_TARGETED_PARSE_REQUIRED" in joined:
            return True
    return False


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _strategy_item(
    *,
    sample: Mapping[str, Any],
    ref: Mapping[str, Any],
    item_index: int,
    created_at: str,
    strategy_state: str,
    verification_enabled: bool,
    extract_policy: str,
    parse_policy: str,
    target_fields: list[str],
    stage4_targets: list[str],
    skip_reason: str,
    parsed_state: str = "",
) -> dict[str, Any]:
    project_id = str(sample.get("project_id") or "")
    flow_no = _flow_no(sample.get("guangzhou_flow_no") or sample.get("flow_no"))
    snapshot_id = str(ref.get("snapshot_id") or "")
    attachment_url = str(ref.get("attachment_url") or ref.get("source_url") or "")
    archive = _is_archive_ref(ref)
    return {
        "evidence_strategy_item_id": f"EVIDENCE-STRATEGY-{flow_no}-{item_index:03d}-{_fingerprint({'project': project_id, 'snapshot': snapshot_id, 'url': attachment_url})[:12]}",
        "project_id": project_id,
        "project_name": str(sample.get("project_name") or ""),
        "flow_no": flow_no,
        "flow_title": str(sample.get("guangzhou_flow_title") or FLOW_TITLES.get(flow_no, "")),
        "document_kind": str(sample.get("document_kind") or ""),
        "source_url": str(sample.get("source_url") or ""),
        "published_date": str(sample.get("published_at_optional") or sample.get("published_date") or ""),
        "attachment_snapshot_id": snapshot_id,
        "attachment_url": attachment_url,
        "attachment_link_text": str(ref.get("attachment_link_text") or ""),
        "attachment_role_type": str(ref.get("attachment_role_type") or ""),
        "attachment_content_type": str(ref.get("content_type") or ""),
        "attachment_byte_size": _int(ref.get("byte_size")),
        "archive_candidate": archive,
        "document_candidate": _is_document_ref(ref),
        "verification_enabled": verification_enabled,
        "strategy_state": strategy_state,
        "extract_policy": extract_policy,
        "parse_policy": parse_policy,
        "target_fields": list(target_fields),
        "stage4_targets": list(stage4_targets),
        "max_extract_files": 2 if flow_no == "08" else 12,
        "file_name_priority_keywords": _priority_keywords(flow_no),
        "parsed_state_optional": parsed_state,
        "skip_reason": skip_reason,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _priority_keywords(flow_no: str) -> list[str]:
    if flow_no == "07":
        return ["候选", "评标", "中标", "项目负责人", "证书", "报价", "排名", "公示"]
    if flow_no == "08":
        return ["投标", "资格", "商务", "技术", "报价", "项目负责人", "证书"]
    if flow_no in {"03", "04"}:
        return ["招标文件", "答疑", "澄清", "补遗", "资格", "评分", "评标", "技术"]
    return ["附件", "公告", "公示", "报价", "否决", "废标"]


def _select_project_samples(*, download_manifest: Mapping[str, Any], project_ids: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    requested = {_normalize_project_token(value) for value in project_ids if _normalize_project_token(value)}
    out: list[dict[str, Any]] = []
    for sample in list(download_manifest.get("project_sample_items") or []):
        if not isinstance(sample, Mapping):
            continue
        project_id = str(sample.get("project_id") or "")
        if requested and not (_project_aliases(project_id) & requested):
            continue
        out.append(dict(sample))
    return out


def _analysis_item_lookup(analysis_manifest: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    lookup: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in list(analysis_manifest.get("items") or []):
        if not isinstance(item, Mapping):
            continue
        lookup[(str(item.get("project_id") or ""), _flow_no(item.get("flow_no")), str(item.get("source_url") or ""))] = item
    return lookup


def _parse_item_lookup(parse_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    lookup: dict[str, Mapping[str, Any]] = {}
    for item in list(parse_manifest.get("items") or []):
        if isinstance(item, Mapping) and str(item.get("snapshot_id") or ""):
            lookup[str(item.get("snapshot_id"))] = item
    return lookup


def _summary(*, items: list[Mapping[str, Any]], selected_samples: list[Mapping[str, Any]], blocking_reasons: list[str]) -> dict[str, Any]:
    return {
        "strategy_state": "READY" if not blocking_reasons else "INPUT_BLOCKED",
        "project_sample_count": len(selected_samples),
        "strategy_item_count": len(items),
        "verification_enabled_count": sum(1 for item in items if bool(item.get("verification_enabled"))),
        "archive_candidate_count": sum(1 for item in items if bool(item.get("archive_candidate"))),
        "targeted_extract_count": sum(1 for item in items if str(item.get("extract_policy") or "") == "TARGETED_EXTRACT"),
        "flow_no_counts": _counts(item.get("flow_no") for item in items),
        "extract_policy_counts": _counts(item.get("extract_policy") for item in items),
        "parse_policy_counts": _counts(item.get("parse_policy") for item in items),
        "stage4_target_counts": _counts(target for item in items for target in list(item.get("stage4_targets") or [])),
        "blocking_reasons": blocking_reasons,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _resolve_analysis_plan_path(*, explicit: Path | None, input_root: Path, download_manifest: Mapping[str, Any]) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    candidates.append(input_root / "analysis-plan.json")
    source_root = str(download_manifest.get("source_input_root") or "")
    if source_root:
        candidates.append(Path(source_root) / "analysis-plan.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _is_archive_ref(ref: Mapping[str, Any]) -> bool:
    return _extension(ref) in ARCHIVE_EXTENSIONS or any(token in str(ref.get("content_type") or "").lower() for token in ("zip", "rar"))


def _is_document_ref(ref: Mapping[str, Any]) -> bool:
    return _extension(ref) in DOCUMENT_EXTENSIONS or any(
        token in str(ref.get("content_type") or "").lower()
        for token in ("pdf", "word", "excel", "spreadsheet", "msword", "officedocument")
    )


def _extension(ref: Mapping[str, Any]) -> str:
    url = str(ref.get("attachment_url") or ref.get("source_url") or "")
    suffix = Path(urlsplit(url).path).suffix.lower()
    text = str(ref.get("attachment_link_text") or "").lower()
    if suffix:
        return suffix
    match = re.search(r"\.(pdf|docx?|xlsx?|zip|rar)\b", text, flags=re.IGNORECASE)
    return f".{match.group(1).lower()}" if match else ""


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _load_json_optional(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _flow_no(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(2) if text else ""


def _project_aliases(project_id: str) -> set[str]:
    return {_normalize_project_token(project_id), _normalize_project_token(_extract_project_code(project_id))}


def _normalize_project_token(value: Any) -> str:
    text = str(value or "").upper().strip()
    return _extract_project_code(text) or text


def _extract_project_code(value: Any) -> str:
    match = re.search(r"JG\d{4}-\d+", str(value or "").upper())
    return match.group(0) if match else ""


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build EvidenceVerificationStrategy v1.")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--project-ids", default=",".join(DEFAULT_PROJECT_IDS))
    parser.add_argument("--download-probe-manifest-json")
    parser.add_argument("--analysis-plan-json")
    parser.add_argument("--parse-probe-manifest-json")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evidence_verification_strategy(
        input_root=args.input_root,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        download_probe_manifest_json=args.download_probe_manifest_json,
        analysis_plan_json=args.analysis_plan_json,
        parse_probe_manifest_json=args.parse_probe_manifest_json,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "evidence-verification-strategy.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"evidence verification strategy built: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVIDENCE_VERIFICATION_STRATEGY_MANIFEST_KIND",
    "build_evidence_verification_strategy",
]
