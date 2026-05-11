from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage3_parsing import markitdown_adapter


RESPONSIBLE_PERSON_EARLY_PROBE_MANIFEST_KIND = "responsible_person_early_probe_manifest"
RESPONSIBLE_PERSON_EARLY_PROBE_VERSION = 1
RESPONSIBLE_PERSON_EARLY_PROBE_ADAPTER_ID = "responsible-person-early-probe-v1"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-download-human-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangzhou-responsible-person-early-probe-v1")
TEXT_PROBE_LIMIT = 4000
DEFAULT_PROJECT_IDS: tuple[str, ...] = ()
PREFERRED_07_PDF_KEYWORDS = ("中标候选人公示", "定标候选人公示", "评标报告", "复评报告")
SMALL_PDF_MAX_BYTES = 20_000_000


def build_responsible_person_early_probe(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = DEFAULT_PROJECT_IDS,
    company_first_state: str = "NOT_RUN",
    name_enumeration_state: str = "NOT_RUN",
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(input_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    project_index = _load_project_index(in_root)
    selected_projects = _discover_project_dirs(in_root=in_root, project_ids=project_ids)
    if not selected_projects:
        blocking_reasons.append("responsible_person_early_probe_no_project_dirs")

    project_items = [
        _probe_project(
            project_dir=project_dir,
            input_root=in_root,
            project_index=project_index,
            company_first_state=company_first_state,
            name_enumeration_state=name_enumeration_state,
            created_at=created,
        )
        for project_dir in selected_projects
    ]
    stage4_inputs = _build_stage4_inputs(project_items=project_items, created_at=created)
    summary = _summary(project_items, stage4_inputs, blocking_reasons)
    manifest = {
        "manifest_version": RESPONSIBLE_PERSON_EARLY_PROBE_VERSION,
        "manifest_kind": RESPONSIBLE_PERSON_EARLY_PROBE_MANIFEST_KIND,
        "adapter_id": RESPONSIBLE_PERSON_EARLY_PROBE_ADAPTER_ID,
        "pipeline_stage": "ResponsiblePersonEarlyProbe",
        "manifest_id": f"RESPONSIBLE-PERSON-EARLY-PROBE-{_fingerprint({'items': project_items, 'summary': summary})[:16]}",
        "created_at": created,
        "source_input_root": str(in_root),
        "project_ids": [item["project_id"] for item in project_items],
        "company_first_state": _normalize_supplement_state(company_first_state),
        "name_enumeration_state": _normalize_supplement_state(name_enumeration_state),
        "items": project_items,
        "project_sample_items": project_items,
        "stage4_candidate_verification_inputs": stage4_inputs,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "fetch_public_urls_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "markitdown_enabled_for_local_files_only": True,
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
        "responsible_person_early_probe_mode": "EXECUTED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
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
    (out_root / "responsible-person-early-probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "stage4_candidate_verification_inputs.json").write_text(
        json.dumps(stage4_inputs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _probe_project(
    *,
    project_dir: Path,
    input_root: Path,
    project_index: Mapping[str, Mapping[str, Any]],
    company_first_state: str,
    name_enumeration_state: str,
    created_at: str,
) -> dict[str, Any]:
    project_id = project_dir.name
    indexed = project_index.get(project_id) or {}
    flow07_dirs = _flow07_dirs(project_dir)
    project_name = str(indexed.get("project_name") or _project_name_from_flow(flow07_dirs) or project_id)
    evidence_sources: list[dict[str, Any]] = []
    aggregate_text_parts: list[str] = []
    source_07_detail_path = ""
    ocr_required = False
    stopped_after_certificate = False

    for detail_path in _detail_paths(flow07_dirs):
        source_07_detail_path = source_07_detail_path or _relative(detail_path, input_root)
        text = _html_to_text(_safe_read_text(detail_path))
        if text:
            aggregate_text_parts.append(text)
        evidence_sources.append(
            _source_record(
                source_type="flow_07_detail_html",
                path=detail_path,
                input_root=input_root,
                extraction_state="TEXT_EXTRACTED" if text else "TEXT_EMPTY",
                text=text,
            )
        )
        if _has_stage4_minimum(_extract_profile("\n".join(aggregate_text_parts))):
            stopped_after_certificate = True
            break

    if not stopped_after_certificate:
        for pdf_path in _selected_07_pdf_paths(flow07_dirs):
            text_result = _markitdown_pdf_text(pdf_path)
            if text_result.state == markitdown_adapter.MARKITDOWN_TEXT_EMPTY:
                ocr_required = True
            if text_result.state == markitdown_adapter.MARKITDOWN_TEXT_EXTRACTED:
                aggregate_text_parts.append(text_result.text)
            evidence_sources.append(
                _source_record(
                    source_type="flow_07_pdf",
                    path=pdf_path,
                    input_root=input_root,
                    extraction_state=text_result.state,
                    text=text_result.text,
                    extra={
                        "markitdown_state": text_result.state,
                        "markitdown_text_sha256": text_result.text_sha256,
                        "markitdown_text_length": text_result.text_length,
                        "markitdown_warnings": list(text_result.warnings),
                    },
                )
            )
            if _has_stage4_minimum(_extract_profile("\n".join(aggregate_text_parts))):
                stopped_after_certificate = True
                break

    text = "\n".join(aggregate_text_parts)
    profile = _extract_profile(text)
    candidate_groups = _candidate_groups(text)
    if candidate_groups:
        profile = _profile_from_candidate_groups(candidate_groups, fallback_profile=profile)
    if not profile["candidate_company_candidates"]:
        fallback_company = str(indexed.get("candidate_company_name") or indexed.get("company_name") or "")
        if fallback_company:
            profile["candidate_company_candidates"] = [_candidate(fallback_company, "project_index_company")]
    verification_targets = _verification_targets(candidate_groups, fallback_profile=profile)
    responsible_role = _responsible_role(text=text, project_name=project_name, profile=profile)
    state_payload = _state_payload(
        profile=profile,
        verification_targets=verification_targets,
        responsible_role=responsible_role,
        company_first_state=company_first_state,
        name_enumeration_state=name_enumeration_state,
        ocr_required=ocr_required,
    )
    item = {
        "project_id": project_id,
        "project_name": project_name,
        "source_07_detail_path": source_07_detail_path,
        "evidence_sources_checked": evidence_sources,
        "candidate_company_candidates": profile["candidate_company_candidates"],
        "responsible_person_candidates": profile["responsible_person_candidates"],
        "certificate_no_candidates": profile["certificate_no_candidates"],
        "candidate_groups": candidate_groups,
        "verification_targets": verification_targets,
        "bid_price_candidates": profile["bid_price_candidates"],
        "rank_candidates": profile["rank_candidates"],
        "responsible_role": responsible_role,
        "early_probe_state": state_payload["early_probe_state"],
        "stage4_readiness_state": state_payload["stage4_readiness_state"],
        "next_actions": state_payload["next_actions"],
        "risk_escalation_state": state_payload["risk_escalation_state"],
        "flow_08_targeted_parse_required": state_payload["flow_08_targeted_parse_required"],
        "ocr_required": bool(ocr_required),
        "company_first_state": _normalize_supplement_state(company_first_state),
        "name_enumeration_state": _normalize_supplement_state(name_enumeration_state),
        "text_probe_sha256": _sha256_text(text) if text else "",
        "text_probe": _clip_probe(text),
        "stopped_after_certificate_ready_from_07": bool(stopped_after_certificate),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return item


def _state_payload(
    *,
    profile: Mapping[str, list[dict[str, Any]]],
    verification_targets: list[Mapping[str, Any]],
    responsible_role: str,
    company_first_state: str,
    name_enumeration_state: str,
    ocr_required: bool,
) -> dict[str, Any]:
    actionable_targets = [
        target
        for target in verification_targets
        if target.get("candidate_company_name") and target.get("responsible_person_name")
    ]
    has_company = bool(profile.get("candidate_company_candidates"))
    has_person = bool(profile.get("responsible_person_candidates"))
    has_certificate = bool(profile.get("certificate_no_candidates"))
    all_actionable_have_certificate = bool(actionable_targets) and all(
        target.get("certificate_no") for target in actionable_targets
    )
    normalized_company_state = _normalize_supplement_state(company_first_state)
    normalized_name_state = _normalize_supplement_state(name_enumeration_state)
    if responsible_role == "not_applicable" and not has_person and not has_certificate:
        return {
            "early_probe_state": "RESPONSIBLE_PERSON_NOT_APPLICABLE",
            "stage4_readiness_state": "STAGE4_NOT_APPLICABLE",
            "next_actions": ["RECORD_SERVICE_OR_INSURANCE_PROJECT_NOT_APPLICABLE"],
            "risk_escalation_state": "NO_ESCALATION",
            "flow_08_targeted_parse_required": False,
        }
    if has_company and has_person and all_actionable_have_certificate:
        return {
            "early_probe_state": "CERTIFICATE_READY_FROM_07",
            "stage4_readiness_state": "READY_FOR_STAGE4_INPUT",
            "next_actions": ["BUILD_STAGE4_CANDIDATE_VERIFICATION_INPUT"],
            "risk_escalation_state": "NO_ESCALATION",
            "flow_08_targeted_parse_required": False,
        }
    if has_company and has_person:
        if normalized_company_state == "NO_MATCH" and normalized_name_state == "NO_MATCH":
            return {
                "early_probe_state": "FLOW_08_TARGETED_PARSE_REQUIRED",
                "stage4_readiness_state": "STAGE4_BLOCKED_CERTIFICATE_NOT_FOUND",
                "next_actions": [
                    "FLOW_08_TARGETED_PARSE",
                    "CHECK_BID_FILE_PUBLICITY_FOR_CERTIFICATE",
                    "DO_NOT_OUTPUT_FINAL_CONFLICT",
                ],
                "risk_escalation_state": "HIGH_CLUE_REVIEW",
                "flow_08_targeted_parse_required": True,
            }
        if normalized_company_state == "NO_MATCH":
            return {
                "early_probe_state": "NAME_ENUMERATION_FALLBACK_REQUIRED",
                "stage4_readiness_state": "STAGE4_BLOCKED_CERTIFICATE_NOT_FOUND",
                "next_actions": ["RUN_NAME_ENUMERATION_FALLBACK", "THEN_DECIDE_FLOW_08_TARGETED_PARSE"],
                "risk_escalation_state": "MEDIUM_CLUE_REVIEW",
                "flow_08_targeted_parse_required": False,
            }
        return {
            "early_probe_state": "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED",
            "stage4_readiness_state": "SUPPLEMENT_REQUIRED_COMPANY_FIRST",
            "next_actions": ["RUN_COMPANY_FIRST_CERTIFICATE_SUPPLEMENT", "DO_NOT_RUN_STAGE4_LIVE_WITH_EMPTY_CERTIFICATE"],
            "risk_escalation_state": "LOW_CLUE_REVIEW",
            "flow_08_targeted_parse_required": False,
        }
    if ocr_required:
        return {
            "early_probe_state": "OCR_REQUIRED_FOR_07",
            "stage4_readiness_state": "STAGE4_BLOCKED_TEXT_EXTRACTION_REQUIRED",
            "next_actions": ["RUN_OCR_FOR_07_SMALL_PDF", "RETRY_RESPONSIBLE_PERSON_EARLY_PROBE"],
            "risk_escalation_state": "EVIDENCE_BLOCKED",
            "flow_08_targeted_parse_required": False,
        }
    return {
        "early_probe_state": "FLOW_08_TARGETED_PARSE_REQUIRED",
        "stage4_readiness_state": "STAGE4_BLOCKED_RESPONSIBLE_PERSON_NOT_FOUND",
        "next_actions": ["FLOW_08_TARGETED_PARSE", "DO_NOT_DEFAULT_DEEP_PARSE_ALL_08"],
        "risk_escalation_state": "MEDIUM_CLUE_REVIEW",
        "flow_08_targeted_parse_required": True,
    }


def _build_stage4_inputs(*, project_items: list[Mapping[str, Any]], created_at: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for project in project_items:
        if project.get("early_probe_state") != "CERTIFICATE_READY_FROM_07":
            continue
        targets = [
            target
            for target in list(project.get("verification_targets") or [])
            if isinstance(target, Mapping)
            and target.get("candidate_company_name")
            and target.get("responsible_person_name")
            and target.get("certificate_no")
        ]
        if not targets:
            company = _first_value(project.get("candidate_company_candidates"))
            person = _first_value(project.get("responsible_person_candidates"))
            certificate = _first_value(project.get("certificate_no_candidates"))
            targets = [
                {
                    "candidate_company_name": company,
                    "responsible_person_name": person,
                    "certificate_no": certificate,
                    "candidate_group_id": "",
                    "candidate_group_order": "",
                    "candidate_group_members": [company] if company else [],
                    "consortium_member_role": "single",
                }
            ]
        for target in targets:
            company = str(target.get("candidate_company_name") or "").strip()
            person = str(target.get("responsible_person_name") or "").strip()
            certificate = str(target.get("certificate_no") or "").strip()
            if not (company and person and certificate):
                continue
            item = {
                "stage4_input_id": f"STAGE4-RESP-PERSON-{_fingerprint({'p': project.get('project_id'), 'group': target.get('candidate_group_id'), 'c': company, 'n': person, 'cert': certificate})[:16]}",
                "source_probe_adapter_id": RESPONSIBLE_PERSON_EARLY_PROBE_ADAPTER_ID,
                "project_id": project.get("project_id"),
                "project_name": project.get("project_name"),
                "flow_no": "07",
                "flow_title": "中标候选人公示",
                "source_07_detail_path": project.get("source_07_detail_path", ""),
                "candidate_company_name": company,
                "candidate_group_id": target.get("candidate_group_id", ""),
                "candidate_group_order": target.get("candidate_group_order", ""),
                "candidate_group_rank_optional": target.get("candidate_group_rank_optional", ""),
                "candidate_group_primary_company_name": target.get("candidate_group_primary_company_name", ""),
                "candidate_group_members": target.get("candidate_group_members", []),
                "consortium_member_role": target.get("consortium_member_role", ""),
                "responsible_person_name": person,
                "responsible_role": project.get("responsible_role"),
                "project_manager_name": person,
                "project_manager_certificate_no": certificate,
                "certificate_no": certificate,
                "bid_price_candidates": project.get("bid_price_candidates", []),
                "rank_candidates": project.get("rank_candidates", []),
                "recommended_stage4_route": "JZSC_COMPANY_FIRST_PROJECT_MANAGER",
                "stage4_live_provider_enabled": False,
                "review_required": False,
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            items.append(item)
    return {
        "manifest_kind": "stage4_candidate_verification_inputs",
        "source_manifest_kind": RESPONSIBLE_PERSON_EARLY_PROBE_MANIFEST_KIND,
        "created_at": created_at,
        "items": items,
        "summary": {
            "stage4_input_count": len(items),
            "project_count": len({item.get("project_id") for item in items}),
            "with_responsible_person_count": sum(1 for item in items if item.get("responsible_person_name")),
            "with_certificate_count": sum(1 for item in items if item.get("certificate_no")),
            "stage4_live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _extract_profile(text: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "candidate_company_candidates": _company_candidates(text),
        "responsible_person_candidates": _responsible_person_candidates(text),
        "certificate_no_candidates": _certificate_candidates(text),
        "bid_price_candidates": _bid_price_candidates(text),
        "rank_candidates": _rank_candidates(text),
    }


def _candidate_groups(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in _normalize_text(text).splitlines() if line.strip()]
    header_index = _candidate_table_header_index(lines)
    if header_index < 0:
        return []
    rows: list[dict[str, Any]] = []
    index = header_index + 1
    while index < len(lines):
        if not re.fullmatch(r"\d{1,2}", lines[index]):
            index += 1
            continue
        group_order = int(lines[index])
        if group_order > 12:
            index += 1
            continue
        if index + 1 >= len(lines):
            break
        company_raw = lines[index + 1]
        if "公司" not in company_raw and "集团" not in company_raw and "院" not in company_raw:
            index += 1
            continue
        next_index = _next_row_index(lines, index + 1)
        segment = lines[index + 1 : next_index]
        row = _candidate_group_from_segment(segment, group_order=group_order)
        if row:
            rows.append(row)
        index = next_index
    return _dedupe_candidate_groups(rows)


def _candidate_table_header_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        window = "\n".join(lines[index : index + 14])
        if (
            ("中标候选人名称" in window or "合格中标候选人名称" in window or "定标候选人名称" in window)
            and ("拟派项目负责人" in window or "项目负责人" in window or "总监理工程师" in window)
            and ("项目负责人资质" in window or "总监理工程师资质" in window or "负责人资质" in window)
        ):
            header_terms = (
                "序号",
                "中标候选人名称",
                "合格中标候选人名称",
                "定标候选人名称",
                "候选人代码",
                "合格中标候选人代码",
                "排名",
                "投标报价",
                "质量承诺",
                "质量标准",
                "工期（交货期）",
                "监理服务期限",
                "候选人资格情况",
                "候选人业绩情况",
                "拟派项目负责人",
                "项目负责人",
                "总监理工程师",
                "项目负责人资质",
                "总监理工程师资质",
                "项目负责人业绩",
                "负责人业绩",
            )
            matching_offsets = [
                offset
                for offset, item in enumerate(lines[index : index + 14])
                if any(term in item for term in header_terms)
            ]
            return index + (max(matching_offsets) if matching_offsets else 0)
    return -1


def _next_row_index(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"\d{1,2}", lines[index]) and index + 1 < len(lines):
            next_line = lines[index + 1]
            if "公司" in next_line or "集团" in next_line or "院" in next_line:
                return index
        if lines[index] in {"非候选人公示", "公示时间", "公示开始时间", "异议受理部门"}:
            return index
    return len(lines)


def _candidate_group_from_segment(segment: list[str], *, group_order: int) -> dict[str, Any] | None:
    if not segment:
        return None
    company_raw = _clean_token(segment[0])
    members = _consortium_members(company_raw)
    if not members:
        return None
    person = ""
    certificate = ""
    bid_price = ""
    rank = ""
    for index, line in enumerate(segment[1:], start=1):
        if not bid_price and re.search(r"\d[\d,，.]*\s*(?:元|万元)", line):
            bid_price = _clean_token(line)
        if not rank and re.fullmatch(r"\d{1,2}", line):
            rank = line
        if not person:
            candidate_person = _clean_person(line)
            next_line = segment[index + 1] if index + 1 < len(segment) else ""
            if candidate_person and _line_mentions_person_certificate(next_line):
                person = candidate_person
                certificate = _certificate_from_line(next_line)
                continue
            if candidate_person and _looks_like_candidate_group_person_row(segment, index):
                person = candidate_person
                continue
        if person and not certificate and _line_mentions_person_certificate(line):
            certificate = _certificate_from_line(line)
    group_id = f"CANDIDATE-GROUP-{_fingerprint({'order': group_order, 'company': company_raw, 'person': person, 'cert': certificate})[:12]}"
    return {
        "candidate_group_id": group_id,
        "candidate_group_order": group_order,
        "candidate_group_rank_optional": rank or str(group_order),
        "candidate_name_raw": company_raw,
        "primary_company_name": members[0]["company_name"],
        "consortium_members": members,
        "responsible_person_name": person,
        "certificate_no": certificate,
        "bid_price_optional": bid_price,
        "source": "flow_07_candidate_table",
        "confidence": 0.82 if person and certificate else 0.7,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _consortium_members(raw: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for index, part in enumerate(re.split(r"[;；]", raw), start=1):
        part = _clean_token(part)
        if not part:
            continue
        role = "member"
        if re.search(r"[（(]\s*主\s*[）)]", part):
            role = "lead"
        elif index == 1 and not re.search(r"[（(]\s*成\s*[）)]", part):
            role = "single_or_lead"
        company = _clean_company(part)
        if not company:
            continue
        members.append(
            {
                "company_name": company,
                "consortium_role": role,
                "member_order": index,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return members


def _line_mentions_person_certificate(line: str) -> bool:
    return any(
        token in str(line or "")
        for token in ("注册建造师", "注册监理工程师", "监理工程师", "注册编号", "证书编号", "注册证号")
    )


def _looks_like_candidate_group_person_row(segment: list[str], index: int) -> bool:
    line = _clean_token(segment[index] if index < len(segment) else "")
    if not _clean_person(line):
        return False
    if index <= 0:
        return False
    previous_line = _clean_token(segment[index - 1] if index - 1 >= 0 else "")
    next_line = _clean_token(segment[index + 1] if index + 1 < len(segment) else "")
    if any(token in previous_line for token in ("公司", "集团", "院")) and _looks_like_money_or_score(next_line):
        return True
    if any(token in next_line for token in ("详见投标文件公开", "投标文件公开", "注册", "证书", "资质", "/")):
        return True
    if any(token in previous_line for token in ("详见投标文件公开", "投标文件公开", "按招标文件", "满足招标文件", "/")):
        return True
    return False


def _looks_like_money_or_score(value: str) -> bool:
    text = _clean_token(value)
    if not text:
        return False
    if re.fullmatch(r"\d[\d,，.]*\s*(?:元|万元)?", text):
        return True
    return False


def _certificate_from_line(line: str) -> str:
    for pattern in (
        r"(?:注册编号|证书编号|注册证号)[：:\s]*([A-Z\u4e00-\u9fff]?\d{6,24})",
        r"((?:粤|京|沪|津|冀|晋|蒙|辽|吉|黑|苏|浙|皖|闽|赣|鲁|豫|鄂|湘|桂|琼|渝|川|贵|云|藏|陕|甘|青|宁|新)[A-Z]?\d{8,24})",
    ):
        match = re.search(pattern, str(line or ""))
        if match:
            return _clean_token(match.group(1))
    return ""


def _dedupe_candidate_groups(groups: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for group in groups:
        key = (
            tuple(member.get("company_name") for member in list(group.get("consortium_members") or [])),
            group.get("responsible_person_name"),
            group.get("certificate_no"),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(dict(group))
    return rows[:12]


def _profile_from_candidate_groups(
    groups: list[Mapping[str, Any]],
    *,
    fallback_profile: Mapping[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    companies: list[dict[str, Any]] = []
    persons: list[dict[str, Any]] = []
    certificates: list[dict[str, Any]] = []
    bids: list[dict[str, Any]] = []
    ranks: list[dict[str, Any]] = []
    for group in groups:
        for member in list(group.get("consortium_members") or []):
            companies.append(_candidate(member.get("company_name"), "candidate_group_member"))
        if group.get("responsible_person_name"):
            persons.append(_candidate(group.get("responsible_person_name"), "candidate_group_responsible_person"))
        if group.get("certificate_no"):
            certificates.append(_candidate(group.get("certificate_no"), "candidate_group_certificate"))
        if group.get("bid_price_optional"):
            bids.append(_candidate(group.get("bid_price_optional"), "candidate_group_bid_price"))
        if group.get("candidate_group_rank_optional"):
            ranks.append(_candidate(group.get("candidate_group_rank_optional"), "candidate_group_rank"))
    return {
        "candidate_company_candidates": _dedupe(companies or list(fallback_profile.get("candidate_company_candidates") or []), limit=30),
        "responsible_person_candidates": _dedupe(persons or list(fallback_profile.get("responsible_person_candidates") or []), limit=30),
        "certificate_no_candidates": _dedupe(certificates or list(fallback_profile.get("certificate_no_candidates") or []), limit=30),
        "bid_price_candidates": _dedupe(bids or list(fallback_profile.get("bid_price_candidates") or []), limit=30),
        "rank_candidates": _dedupe(ranks or list(fallback_profile.get("rank_candidates") or []), limit=30),
    }


def _verification_targets(
    groups: list[Mapping[str, Any]],
    *,
    fallback_profile: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for group in groups:
        person = str(group.get("responsible_person_name") or "").strip()
        if not person:
            continue
        members = [dict(member) for member in list(group.get("consortium_members") or []) if isinstance(member, Mapping)]
        for member in members:
            company = str(member.get("company_name") or "").strip()
            if not company:
                continue
            targets.append(
                {
                    "candidate_group_id": group.get("candidate_group_id", ""),
                    "candidate_group_order": group.get("candidate_group_order", ""),
                    "candidate_group_rank_optional": group.get("candidate_group_rank_optional", ""),
                    "candidate_group_primary_company_name": group.get("primary_company_name", ""),
                    "candidate_group_members": [m.get("company_name") for m in members if m.get("company_name")],
                    "candidate_company_name": company,
                    "consortium_member_role": member.get("consortium_role", ""),
                    "responsible_person_name": person,
                    "certificate_no": group.get("certificate_no", ""),
                    "source": "candidate_group_member_target",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    if targets:
        return targets
    company = _first_value(fallback_profile.get("candidate_company_candidates"))
    person = _first_value(fallback_profile.get("responsible_person_candidates"))
    cert = _first_value(fallback_profile.get("certificate_no_candidates"))
    if company and person:
        return [
            {
                "candidate_group_id": "",
                "candidate_group_order": "",
                "candidate_group_rank_optional": "",
                "candidate_group_primary_company_name": company,
                "candidate_group_members": [company],
                "candidate_company_name": company,
                "consortium_member_role": "unknown",
                "responsible_person_name": person,
                "certificate_no": cert,
                "source": "fallback_project_level_target",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        ]
    return []


def _company_candidates(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    patterns = [
        r"(?:第一中标候选人|第二中标候选人|第三中标候选人|定标候选人|候选人名称|中标候选人名称|投标人名称|单位名称)[：:\s]*([^\n，,；;。]{2,90}?(?:公司|集团|院|所|中心))",
        r"([\u4e00-\u9fffA-Za-z0-9（）()·\-]{2,70}(?:公司|集团|院|所|中心))",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = _clean_company(match.group(1))
            if value:
                rows.append(_candidate(value, "company_pattern"))
    return _dedupe(rows, limit=12)


def _responsible_person_candidates(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in _responsible_certificate_pairs(text):
        rows.append(_candidate(pair["person"], "responsible_certificate_pair"))
    table_person_pattern = (
        r"(?:详见投标文件公开|满足招标文件要求，具体详见投标文件公开|/)\s*\n"
        r"([\u4e00-\u9fff·]{2,6})\s*\n"
        r"(?:详见投标文件公开|[^。\n]{0,100}?(?:注册编号|注册证号|证书编号|注册建造师|监理工程师)|/)"
    )
    for match in re.finditer(table_person_pattern, text):
        value = _clean_person(match.group(1))
        if value:
            rows.append(_candidate(value, "candidate_table_person_column"))
    role_pattern = (
        r"(?:项目经理|项目负责人|项目总负责人|总监理工程师|总监|设计负责人|勘察负责人|负责人)"
        r"(?:姓名)?(?:[：:\s]+|为)([\u4e00-\u9fff·]{2,6})"
    )
    for match in re.finditer(role_pattern, text):
        value = _clean_person(match.group(1))
        if value:
            rows.append(_candidate(value, "responsible_role_label"))
    cert_context = (
        r"([\u4e00-\u9fff·]{2,6})\s*(?:（[^）]{0,30}）|\([^)]{0,30}\))?\s*"
        r"(?:一级注册建造师|二级注册建造师|注册建造师|注册监理工程师|监理工程师|注册建筑师|注册结构工程师)"
    )
    for match in re.finditer(cert_context, text):
        value = _clean_person(match.group(1))
        if value:
            rows.append(_candidate(value, "certificate_context_name"))
    return _dedupe(rows, limit=12)


def _certificate_candidates(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in _responsible_certificate_pairs(text):
        rows.append(_candidate(pair["certificate"], "responsible_certificate_pair"))
    patterns = [
        r"(?:证书编号|注册编号|注册证号|执业证号)[：:\s]*([A-Z\u4e00-\u9fff]?\d{6,24})",
        r"(?:粤|京|沪|津|冀|晋|蒙|辽|吉|黑|苏|浙|皖|闽|赣|鲁|豫|鄂|湘|桂|琼|渝|川|贵|云|藏|陕|甘|青|宁|新)[A-Z]?\d{8,24}",
        r"(?:注册建造师|建造师|监理工程师|注册监理工程师)[/／\s]*([A-Z\u4e00-\u9fff]?\d{6,24})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if not _certificate_context_is_personal(text, match.start(), match.end()):
                continue
            value = match.group(1) if match.lastindex else match.group(0)
            value = _clean_token(value)
            if value:
                rows.append(_candidate(value, "certificate_pattern"))
    return _dedupe(rows, limit=12)


def _responsible_certificate_pairs(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    patterns = [
        (
            r"(?P<person>[\u4e00-\u9fff·]{2,6})\s*\n"
            r"(?P<cert_type>[^\n]{0,80}?(?:注册建造师|一级注册建造师|二级注册建造师|注册监理工程师|监理工程师|注册建筑师|注册结构工程师)[^\n]{0,80}?)"
            r"(?:注册编号|证书编号|注册证号)[：:\s]*(?P<cert>[A-Z\u4e00-\u9fff]?\d{6,24})"
        ),
        (
            r"(?P<person>[\u4e00-\u9fff·]{2,6})\s+"
            r"(?P<cert_type>[^\n；;。]{0,80}?(?:注册建造师|一级注册建造师|二级注册建造师|注册监理工程师|监理工程师|注册建筑师|注册结构工程师)[^\n；;。]{0,80}?)"
            r"(?:注册编号|证书编号|注册证号)[：:\s]*(?P<cert>[A-Z\u4e00-\u9fff]?\d{6,24})"
        ),
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            person = _clean_person(match.group("person"))
            cert = _clean_token(match.group("cert"))
            if person and cert:
                rows.append({"person": person, "certificate": cert})
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["person"], row["certificate"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:12]


def _certificate_context_is_personal(text: str, start: int, end: int) -> bool:
    left = str(text or "")[max(0, start - 120) : start]
    right = str(text or "")[end : min(len(str(text or "")), end + 80)]
    context = f"{left}{right}"
    if any(token in context for token in ("设计资质", "勘察资质", "施工资质", "安全生产许可证", "企业资质", "许可证编号", "候选人资格情况")):
        return False
    return any(
        token in context
        for token in (
            "项目负责人",
            "项目经理",
            "拟派",
            "总监理工程师",
            "总监",
            "一级注册建造师",
            "二级注册建造师",
            "注册监理工程师",
            "监理工程师",
            "注册编号",
        )
    )


def _bid_price_candidates(text: str) -> list[dict[str, Any]]:
    rows = []
    for match in re.finditer(r"(?:投标报价|中标价|报价|投标总价)[：:\s]*([0-9,，.]+)\s*(万元|元)?", text):
        rows.append(_candidate(f"{match.group(1)}{match.group(2) or ''}", "bid_price_pattern"))
    return _dedupe(rows, limit=12)


def _rank_candidates(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in ("第一中标候选人", "第二中标候选人", "第三中标候选人", "第一定标候选人", "第二定标候选人", "第三定标候选人"):
        if label in text:
            rows.append(_candidate(label, "rank_keyword"))
    for match in re.finditer(r"(?:排名|名次)[：:\s]*(第?[一二三四五六七八九十\d]+)", text):
        rows.append(_candidate(match.group(1), "rank_label"))
    return _dedupe(rows, limit=12)


def _responsible_role(*, text: str, project_name: str, profile: Mapping[str, list[dict[str, Any]]]) -> str:
    combined = f"{project_name}\n{text}"
    if any(token in combined for token in ("保险项目", "保险服务")) and not profile.get("responsible_person_candidates"):
        return "not_applicable"
    if "总监理工程师" in combined or re.search(r"\b总监\b", combined):
        return "chief_supervision_engineer"
    if "设计负责人" in combined:
        return "design_lead"
    if "勘察负责人" in combined:
        return "survey_lead"
    if "服务负责人" in combined or "项目总负责人" in combined:
        return "service_project_lead"
    return "project_manager"


def _has_stage4_minimum(profile: Mapping[str, list[dict[str, Any]]]) -> bool:
    return bool(
        profile.get("candidate_company_candidates")
        and profile.get("responsible_person_candidates")
        and profile.get("certificate_no_candidates")
    )


def _load_project_index(input_root: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    map_path = input_root / "human-readable-file-map.csv"
    if map_path.exists():
        with map_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                project_id = str(row.get("project_id") or "").strip()
                if not project_id:
                    continue
                current = index.setdefault(project_id, {})
                if row.get("project_name") and not current.get("project_name"):
                    current["project_name"] = row.get("project_name")
    manifest = _load_json(input_root / "download-probe-manifest.json")
    for sample in _iter_project_samples(manifest):
        project_id = str(sample.get("project_id") or "").strip()
        if not project_id:
            continue
        current = index.setdefault(project_id, {})
        if sample.get("project_name") and not current.get("project_name"):
            current["project_name"] = sample.get("project_name")
    return index


def _iter_project_samples(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    samples = manifest.get("project_sample_items") if isinstance(manifest, Mapping) else []
    return [sample for sample in samples or [] if isinstance(sample, Mapping)]


def _discover_project_dirs(*, in_root: Path, project_ids: list[str] | tuple[str, ...]) -> list[Path]:
    root = in_root / "projects" / "CN-GD"
    if not root.exists():
        return []
    dirs = [path for path in root.iterdir() if path.is_dir() and path.name.startswith("PROJ-CN-GD-")]
    if not project_ids:
        return sorted(dirs, key=lambda path: path.name)
    wanted = {_project_code(value) for value in project_ids if _project_code(value)}
    return sorted([path for path in dirs if _project_code(path.name) in wanted], key=lambda path: path.name)


def _flow07_dirs(project_dir: Path) -> list[Path]:
    flow_dirs: list[Path] = []
    for flow_root in project_dir.glob("07_*"):
        if not flow_root.is_dir():
            continue
        flow_dirs.extend([path for path in flow_root.iterdir() if path.is_dir()])
    return sorted(flow_dirs, key=lambda path: str(path))


def _detail_paths(flow07_dirs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for flow_dir in flow07_dirs:
        detail = flow_dir / "detail" / "detail.html"
        if detail.exists():
            paths.append(detail)
    return paths


def _selected_07_pdf_paths(flow07_dirs: list[Path]) -> list[Path]:
    pdfs: list[Path] = []
    for flow_dir in flow07_dirs:
        attachments = flow_dir / "attachments"
        if attachments.exists():
            pdfs.extend(sorted(attachments.glob("*.pdf"), key=lambda path: path.name))
    preferred = [path for path in pdfs if any(keyword in path.name for keyword in PREFERRED_07_PDF_KEYWORDS)]
    if preferred:
        return sorted(preferred, key=lambda path: path.name)
    return sorted([path for path in pdfs if _safe_size(path) <= SMALL_PDF_MAX_BYTES], key=lambda path: (_safe_size(path), path.name))[:3]


def _markitdown_pdf_text(path: Path) -> markitdown_adapter.MarkItDownText:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return markitdown_adapter.MarkItDownText(
            text="",
            state=markitdown_adapter.MARKITDOWN_CONVERT_FAILED,
            warnings=[f"READ_FAILED:{type(exc).__name__}"],
        )
    return markitdown_adapter.convert_bytes_to_markdown_text(
        data,
        source_file_ref=str(path),
        content_type="application/pdf",
    )


def _source_record(
    *,
    source_type: str,
    path: Path,
    input_root: Path,
    extraction_state: str,
    text: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "source_type": source_type,
        "path": _relative(path, input_root),
        "extraction_state": extraction_state,
        "text_sha256": _sha256_text(text) if text else "",
        "text_length": len(text or ""),
        "text_probe": _clip_probe(text),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _summary(
    project_items: list[Mapping[str, Any]],
    stage4_inputs: Mapping[str, Any],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "project_count": len(project_items),
        "early_probe_state_counts": _counts(item.get("early_probe_state") for item in project_items),
        "stage4_readiness_state_counts": _counts(item.get("stage4_readiness_state") for item in project_items),
        "responsible_role_counts": _counts(item.get("responsible_role") for item in project_items),
        "certificate_ready_count": sum(1 for item in project_items if item.get("early_probe_state") == "CERTIFICATE_READY_FROM_07"),
        "company_first_certificate_supplement_required_count": sum(
            1 for item in project_items if item.get("early_probe_state") == "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED"
        ),
        "name_enumeration_fallback_required_count": sum(
            1 for item in project_items if item.get("early_probe_state") == "NAME_ENUMERATION_FALLBACK_REQUIRED"
        ),
        "flow_08_targeted_parse_required_count": sum(1 for item in project_items if item.get("flow_08_targeted_parse_required")),
        "ocr_required_count": sum(1 for item in project_items if item.get("ocr_required")),
        "stage4_input_count": len(stage4_inputs.get("items") or []),
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "\n", str(raw_html or ""))
    text = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>|</li>|</h\d>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _normalize_text(html.unescape(text))


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _normalize_text(text: Any) -> str:
    lines = []
    for line in str(text or "").replace("\u3000", " ").splitlines():
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return "\n".join(lines)


def _candidate(value: Any, source: str) -> dict[str, Any]:
    return {
        "value": _clean_token(value),
        "source": source,
        "confidence": 0.64,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _dedupe(candidates: list[Mapping[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = _clean_token(candidate.get("value"))
        if not value or value in seen:
            continue
        seen.add(value)
        row = dict(candidate)
        row["value"] = value
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _clean_company(value: Any) -> str:
    text = _clean_token(value)
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]", "", text)
    text = re.split(r"(?:招标人|招标代理|委托|排名|报价|资质|证书|姓名)", text)[0]
    text = re.split(r"[；;]", text)[0]
    text = _clean_token(text)
    if not text:
        return ""
    if any(
        token in text
        for token in (
            "交易集团有限公司",
            "公共资源交易中心",
            "招标代理",
            "建设监理有限公司",
            "本招标",
        )
    ):
        return ""
    return text


def _clean_person(value: Any) -> str:
    text = _clean_token(value)
    if not re.fullmatch(r"[\u4e00-\u9fff·]{2,6}", text):
        return ""
    if text in {"项目负责人", "总监理", "总监理工程师", "工程师", "候选人", "负责人"}:
        return ""
    if any(token in text for token in ("项目", "负责", "资质", "业绩", "投标", "报价", "候选", "证书", "代码", "合同", "约定")):
        return ""
    return text


def _clean_token(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[：:，,、；;\s|｜]+|[：:，,、；;\s|｜]+$", "", text)
    return text


def _first_value(values: Any) -> str:
    if isinstance(values, list) and values:
        first = values[0]
        if isinstance(first, Mapping):
            return str(first.get("value") or "")
    return ""


def _project_name_from_flow(flow07_dirs: list[Path]) -> str:
    if not flow07_dirs:
        return ""
    name = flow07_dirs[0].name
    parts = name.split("_", 2)
    return parts[-1] if parts else name


def _normalize_supplement_state(value: Any) -> str:
    normalized = str(value or "NOT_RUN").strip().upper()
    if normalized in {"NO_MATCH", "NOT_RUN", "MATCHED", "AMBIGUOUS"}:
        return normalized
    return "NOT_RUN"


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _clip_probe(text: str) -> str:
    normalized = _normalize_text(text)
    return normalized[:TEXT_PROBE_LIMIT] + "...[TRUNCATED]" if len(normalized) > TEXT_PROBE_LIMIT else normalized


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _project_code(value: Any) -> str:
    match = re.search(r"JG\d{4}-\d+", str(value or "").upper())
    return match.group(0) if match else ""


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ResponsiblePersonEarlyProbe v1.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--company-first-state", default="NOT_RUN")
    parser.add_argument("--name-enumeration-state", default="NOT_RUN")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_responsible_person_early_probe(
        input_root=args.input_root,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        company_first_state=args.company_first_state,
        name_enumeration_state=args.name_enumeration_state,
    )
    output_json = Path(args.output_json) if args.output_json else Path(args.output_root) / "responsible-person-early-probe.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"responsible person early probe built: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RESPONSIBLE_PERSON_EARLY_PROBE_MANIFEST_KIND",
    "build_responsible_person_early_probe",
]
