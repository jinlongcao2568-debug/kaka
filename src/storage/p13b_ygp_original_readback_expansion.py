from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


P13B_YGP_ORIGINAL_READBACK_EXPANSION_KIND = "p13b_ygp_original_readback_expansion_v1_manifest"
P13B_YGP_ORIGINAL_READBACK_EXPANSION_VERSION = 1
P13B_YGP_ORIGINAL_READBACK_EXPANSION_ADAPTER_ID = "p13b-ygp-original-readback-expansion-v1-builder"

DEFAULT_MINI_CLOSEOUT_ROOT = Path("tmp/evaluation-real-samples/ygp-evidence-mini-closeout-v2")
DEFAULT_CITY_DISCOVERY_ROOT = Path("tmp/evaluation-real-samples/ygp-morecity-smoke-v1-city-discovery")
DEFAULT_DOWNLOAD_ROOT = Path("tmp/evaluation-real-samples/ygp-morecity-smoke-v1-07-download")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-ygp-original-readback-expansion-v1")

SELECTED_READINESS_STATES = {
    "YGP_EVIDENCE_MINI_READY_FOR_P13B",
    "YGP_EVIDENCE_MINI_READY_WITH_OVERSIZE_BACKLOG",
}
NO_PUBLIC_ATTACHMENT_STATE = "YGP_EVIDENCE_MINI_NO_PUBLIC_ATTACHMENT_REVIEW"
FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")


def build_p13b_ygp_original_readback_expansion(
    *,
    mini_closeout_root: str | Path = DEFAULT_MINI_CLOSEOUT_ROOT,
    city_discovery_root: str | Path = DEFAULT_CITY_DISCOVERY_ROOT,
    download_root: str | Path = DEFAULT_DOWNLOAD_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    mini_dir = Path(mini_closeout_root)
    city_discovery_dir = Path(city_discovery_root)
    download_dir = Path(download_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    mini_closeout = _load_json(
        mini_dir / "ygp-evidence-mini-closeout-v2.json",
        blocking_reasons,
        "ygp_evidence_mini_closeout_v2_missing",
    )
    full_chain = _load_json(download_dir / "ygp-full-chain-manifest.json", blocking_reasons, "ygp_full_chain_manifest_missing")
    city_discovery = _load_first_json(
        [
            city_discovery_dir / "guangdong-ygp-city-discovery-v1.json",
            download_dir / "city-discovery" / "guangdong-ygp-city-discovery-v1.json",
        ],
        blocking_reasons,
        "ygp_city_discovery_manifest_missing",
    )

    mini_manifest = _source_manifest(mini_closeout)
    full_manifest = _source_manifest(full_chain)
    samples_by_project = {
        str(sample.get("project_id") or ""): dict(sample)
        for sample in _list(full_manifest.get("project_sample_items"))
        if isinstance(sample, Mapping) and str(sample.get("guangdong_ygp_flow_no") or "") == "07"
    }

    task_records: list[dict[str, Any]] = []
    not_selected_records: list[dict[str, Any]] = []
    for record in _list(mini_manifest.get("city_project_records")):
        if not isinstance(record, Mapping):
            continue
        sample = samples_by_project.get(str(record.get("project_id") or ""), {})
        detail_payload, detail_ref, detail_blockers = _load_detail_payload(sample, download_dir)
        extraction = _extract_detail_fields(detail_payload, fallback_project_name=str(record.get("project_name") or ""))
        decision = _selection_decision(record, extraction)
        if not decision["selected"]:
            not_selected_records.append(_not_selected_record(record, decision["reason"]))
            continue
        task_records.append(
            _task_record(
                record=record,
                sample=sample,
                detail_payload=detail_payload,
                detail_ref=detail_ref,
                detail_blockers=detail_blockers,
                extraction=extraction,
                created_at=created,
            )
        )

    field_records = [_field_record(record) for record in task_records]
    overlap_records = _overlap_triage_input_records(task_records)
    summary = _build_summary(
        task_records=task_records,
        field_records=field_records,
        overlap_records=overlap_records,
        not_selected_records=not_selected_records,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": P13B_YGP_ORIGINAL_READBACK_EXPANSION_VERSION,
        "manifest_kind": P13B_YGP_ORIGINAL_READBACK_EXPANSION_KIND,
        "adapter_id": P13B_YGP_ORIGINAL_READBACK_EXPANSION_ADAPTER_ID,
        "pipeline_stage": "P13BYgpOriginalReadbackExpansionV1",
        "manifest_id": f"P13B-YGP-ORIGINAL-READBACK-EXPANSION-{_fingerprint({'summary': summary, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_mini_closeout_root": str(mini_dir),
        "source_city_discovery_root": str(city_discovery_dir),
        "source_download_root": str(download_dir),
        "source_mini_closeout_manifest_path": str(mini_dir / "ygp-evidence-mini-closeout-v2.json"),
        "source_full_chain_manifest_path": str(download_dir / "ygp-full-chain-manifest.json"),
        "source_city_discovery_manifest_path": str(_loaded_path(city_discovery) or ""),
        "source_profile_id": "P13B-YGP-MORECITY-ORIGINAL-READBACK-EXPANSION",
        "execution_mode": "READ_ONLY_LOCAL_ARTIFACTS",
        "task_records": task_records,
        "field_records": field_records,
        "overlap_triage_input_records": overlap_records,
        "not_selected_records": not_selected_records,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "flow_08_default_downloaded": False,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "p13b_ygp_original_readback_expansion_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    _finalize_and_write(out_dir, result, task_records, field_records, overlap_records)
    return result


def _selection_decision(record: Mapping[str, Any], extraction: Mapping[str, Any]) -> dict[str, Any]:
    state = str(record.get("evidence_package_readiness_state") or "")
    if state in SELECTED_READINESS_STATES:
        return {"selected": True, "reason": "selected_by_evidence_mini_readiness"}
    if state == NO_PUBLIC_ATTACHMENT_STATE and _has_detail_field_signal(extraction):
        return {"selected": True, "reason": "no_public_attachment_but_detail_fields_ready"}
    return {"selected": False, "reason": state or "P13B_YGP_NOT_SELECTED"}


def _task_record(
    *,
    record: Mapping[str, Any],
    sample: Mapping[str, Any],
    detail_payload: Mapping[str, Any],
    detail_ref: Mapping[str, Any],
    detail_blockers: list[str],
    extraction: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    city_code = str(record.get("city_code") or sample.get("city_code") or "")
    project_id = str(record.get("project_id") or sample.get("project_id") or "")
    readiness_state = str(record.get("evidence_package_readiness_state") or "")
    backlog_tracked = readiness_state == "YGP_EVIDENCE_MINI_READY_WITH_OVERSIZE_BACKLOG"
    source_blocked = bool(detail_blockers) or not detail_payload
    state = _task_state(
        readiness_state=readiness_state,
        backlog_tracked=backlog_tracked,
        source_blocked=source_blocked,
        extraction=extraction,
    )
    source_url = str(record.get("source_url") or sample.get("source_url") or detail_payload.get("source_url") or "")
    publish_date = str(extraction.get("publish_date") or detail_payload.get("published_at") or "")
    return {
        "p13b_ygp_original_readback_task_id": _stable_id("P13B-YGP-READBACK-EXPANSION", project_id, source_url),
        "city_code": city_code,
        "project_id": project_id,
        "project_name": str(record.get("project_name") or sample.get("project_name") or detail_payload.get("project_name") or ""),
        "source_07_url": source_url,
        "source_url": source_url,
        "source_profile_id": str(sample.get("source_profile_id") or "GUANGDONG-YGP-FULL-CHAIN"),
        "readiness_state_from_mini_closeout": readiness_state,
        "backlog_tracked": bool(backlog_tracked),
        "present_flow_nos": _list(record.get("present_flow_nos")),
        "candidate_company_candidates": _list(extraction.get("candidate_company_candidates")),
        "responsible_person_candidates": _list(extraction.get("responsible_person_candidates")),
        "certificate_no_candidates": _list(extraction.get("certificate_no_candidates")),
        "bid_price_candidates": _list(extraction.get("bid_price_candidates")),
        "rank_candidates": _list(extraction.get("rank_candidates")),
        "period_text": str(extraction.get("period_text") or ""),
        "service_period_text": str(extraction.get("service_period_text") or extraction.get("period_text") or ""),
        "award_date": str(extraction.get("award_date") or ""),
        "publish_date": publish_date,
        "detail_readback_sha256": str(detail_ref.get("sha256") or detail_payload.get("text_probe_sha256") or _sha256(str(detail_payload.get("text_probe") or ""))),
        "detail_snapshot_id": str(detail_ref.get("snapshot_id") or ""),
        "detail_snapshot_local_path": str(detail_ref.get("local_path") or ""),
        "detail_readback_state": str(detail_ref.get("readback_state") or ("READBACK_READY" if detail_payload else "")),
        "field_signal_count": _int(extraction.get("field_signal_count")),
        "p13b_ygp_original_readback_state": state,
        "blocker_taxonomy": detail_blockers,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _task_state(
    *,
    readiness_state: str,
    backlog_tracked: bool,
    source_blocked: bool,
    extraction: Mapping[str, Any],
) -> str:
    if source_blocked:
        return "P13B_YGP_SOURCE_BLOCKED"
    if readiness_state == NO_PUBLIC_ATTACHMENT_STATE and _has_detail_field_signal(extraction):
        return "P13B_YGP_NO_PUBLIC_ATTACHMENT_BUT_DETAIL_READY"
    if backlog_tracked and _has_detail_field_signal(extraction):
        return "P13B_YGP_BACKLOG_TRACKED_READY"
    if _has_detail_field_signal(extraction):
        return "P13B_YGP_ORIGINAL_READBACK_READY"
    return "P13B_YGP_FIELD_PARTIAL_REVIEW"


def _not_selected_record(record: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "city_code": str(record.get("city_code") or ""),
        "project_id": str(record.get("project_id") or ""),
        "project_name": str(record.get("project_name") or ""),
        "readiness_state_from_mini_closeout": str(record.get("evidence_package_readiness_state") or ""),
        "p13b_ygp_original_readback_state": "P13B_YGP_NOT_SELECTED",
        "not_selected_reason": reason,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _field_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "city_code": record.get("city_code"),
        "project_id": record.get("project_id"),
        "project_name": record.get("project_name"),
        "p13b_ygp_original_readback_state": record.get("p13b_ygp_original_readback_state"),
        "candidate_company_candidates": _list(record.get("candidate_company_candidates")),
        "responsible_person_candidates": _list(record.get("responsible_person_candidates")),
        "certificate_no_candidates": _list(record.get("certificate_no_candidates")),
        "bid_price_candidates": _list(record.get("bid_price_candidates")),
        "rank_candidates": _list(record.get("rank_candidates")),
        "period_text": record.get("period_text"),
        "service_period_text": record.get("service_period_text"),
        "award_date": record.get("award_date"),
        "publish_date": record.get("publish_date"),
        "detail_readback_sha256": record.get("detail_readback_sha256"),
        "field_signal_count": record.get("field_signal_count"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _overlap_triage_input_records(task_records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in task_records:
        if str(task.get("p13b_ygp_original_readback_state") or "") == "P13B_YGP_SOURCE_BLOCKED":
            continue
        for company in _list(task.get("candidate_company_candidates")):
            company_name = str(company or "").strip()
            if not company_name:
                continue
            rows.append(
                {
                    "p13b_overlap_triage_input_id": _stable_id("P13B-YGP-OVERLAP-INPUT", task.get("project_id"), company_name),
                    "city_code": task.get("city_code"),
                    "project_id": task.get("project_id"),
                    "project_name": task.get("project_name"),
                    "candidate_company_name": company_name,
                    "responsible_person_candidates": _list(task.get("responsible_person_candidates")),
                    "certificate_no_candidates": _list(task.get("certificate_no_candidates")),
                    "service_period_text": task.get("service_period_text"),
                    "award_date": task.get("award_date"),
                    "publish_date": task.get("publish_date"),
                    "source_url": task.get("source_url"),
                    "source_07_url": task.get("source_07_url"),
                    "detail_readback_sha256": task.get("detail_readback_sha256"),
                    "backlog_tracked": bool(task.get("backlog_tracked")),
                    "next_stage": "DATA_GGZY_COMPANY_HISTORY_OVERLAP_TRIAGE_INPUT",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return rows


def _load_detail_payload(sample: Mapping[str, Any], download_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    blockers: list[str] = []
    detail_refs = [
        dict(ref)
        for ref in _list(sample.get("detail_snapshot_refs"))
        if isinstance(ref, Mapping) and str(ref.get("guangdong_ygp_flow_no") or sample.get("guangdong_ygp_flow_no") or "") == "07"
    ]
    if not detail_refs:
        return {}, {}, ["ygp_07_detail_snapshot_missing"]
    detail_ref = detail_refs[0]
    if str(detail_ref.get("readback_state") or "") != "READBACK_READY":
        blockers.append("ygp_07_detail_readback_not_ready")
    local_path = _resolve_local_path(str(detail_ref.get("local_path") or ""), download_dir)
    if not local_path or not local_path.exists():
        blockers.append("ygp_07_detail_local_snapshot_missing")
        return {}, detail_ref, blockers
    try:
        payload = json.loads(local_path.read_text(encoding="utf-8"))
    except Exception:
        blockers.append("ygp_07_detail_local_snapshot_invalid_json")
        return {}, detail_ref, blockers
    return payload if isinstance(payload, dict) else {}, detail_ref, blockers


def _resolve_local_path(value: str, download_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.exists():
        return path
    if not path.is_absolute():
        cwd_path = Path.cwd() / path
        if cwd_path.exists():
            return cwd_path
        download_path = download_dir / path
        if download_path.exists():
            return download_path
    return path


def _extract_detail_fields(detail: Mapping[str, Any], *, fallback_project_name: str) -> dict[str, Any]:
    text = _detail_text(detail)
    companies = _extract_company_names(text)
    people = _extract_responsible_people(text)
    certificates = _extract_certificate_numbers(text)
    bid_prices = _extract_bid_prices(text)
    ranks = _extract_ranks(text)
    period = _extract_period_text(text)
    award_date = _extract_award_date(text)
    publish_date = str(detail.get("published_at") or _extract_publish_date(text) or "")
    field_signal_count = (
        len(companies)
        + len(people)
        + len(certificates)
        + len(bid_prices)
        + len(ranks)
        + sum(1 for value in (period, award_date, publish_date) if value)
    )
    return {
        "project_name": str(detail.get("project_name") or fallback_project_name or ""),
        "notice_title": str(detail.get("notice_title") or ""),
        "candidate_company_candidates": companies,
        "responsible_person_candidates": people,
        "certificate_no_candidates": certificates,
        "bid_price_candidates": bid_prices,
        "rank_candidates": ranks,
        "period_text": period,
        "service_period_text": period,
        "award_date": award_date,
        "publish_date": publish_date,
        "field_signal_count": field_signal_count,
        "text_sha256": _sha256(text) if text else "",
    }


def _has_detail_field_signal(extraction: Mapping[str, Any]) -> bool:
    return bool(_list(extraction.get("candidate_company_candidates")) or _list(extraction.get("responsible_person_candidates")))


def _detail_text(detail: Mapping[str, Any]) -> str:
    text = str(detail.get("text_probe") or "")
    if not text:
        text = _json_to_text(detail)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _extract_company_names(text: str) -> list[str]:
    segment = text
    for marker in ("异议受理部门", "招标投标监督部门", "公示开始时间"):
        if marker in segment:
            segment = segment.split(marker, 1)[0]
            break
    pattern = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,80}(?:有限公司|股份有限公司|集团有限公司|集团|研究院|设计院|公司)")
    names: list[str] = []
    for match in pattern.finditer(segment):
        name = match.group(0).strip(" 　，,；;：:")
        if len(name) > 80 or any(token in name for token in ("招标代理机构", "招标人", "监督部门")):
            continue
        names.append(name)
    return _dedupe(names)


def _extract_responsible_people(text: str) -> list[str]:
    patterns = [
        r"(?:项目负责人|项目经理|施工项目负责人|设计负责人|勘察负责人|总监理工程师|工程总承包项目经理|负责人姓名|姓名)\s*[:：]\s*([\u4e00-\u9fa5·]{2,8})",
        r"(?:拟派项目负责人|拟派总监理工程师)[^\n]{0,20}\n([\u4e00-\u9fa5·]{2,8})",
    ]
    people: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if name.endswith("工") or name in {"联系人", "负责人"}:
                continue
            people.append(name)
    return _dedupe(people)


def _extract_certificate_numbers(text: str) -> list[str]:
    values: list[str] = []
    for pattern in (
        r"(?:注册编号|注册证号|证书编号|证书号)\s*[:：]?\s*([A-Za-z0-9粤豫湘鄂川浙苏鲁闽桂赣皖琼晋冀辽吉黑蒙宁青新藏陕甘贵云京津沪渝港澳]{6,30})",
        r"(?:注册号)\s*[:：]?\s*([A-Za-z0-9]{6,30})",
    ):
        for match in re.finditer(pattern, text):
            values.append(match.group(1).strip(" 　；;，,。"))
    return _dedupe(values)


def _extract_bid_prices(text: str) -> list[str]:
    segment = text
    for marker in ("异议受理部门", "招标投标监督部门"):
        if marker in segment:
            segment = segment.split(marker, 1)[0]
            break
    values = re.findall(r"(?<![\d])\d{3,12}\.\d{1,4}(?![\d])", segment)
    return _dedupe(values)


def _extract_ranks(text: str) -> list[str]:
    values = re.findall(r"第[一二三四五六七八九十\d]+(?:中标候选人|定标候选人|候选人)", text)
    if not values and "定标候选人不排序" in text:
        values.append("定标候选人不排序")
    return _dedupe(values)


def _extract_period_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if any(token in line for token in ("服务期", "工期", "履行期限", "服务期限")) and len(line) > 8:
            if line in {"工期（交货期）", "工期", "服务期"}:
                continue
            return line[:240]
    match = re.search(r"(?:工期（交货期）|工期|服务期|服务期限|履行期限)\s*[:：]\s*([^。；;\n]{2,160})", text)
    return match.group(1).strip() if match else ""


def _extract_award_date(text: str) -> str:
    patterns = [
        r"(?:中标日期|成交日期|开标日期)\s*[:：]?\s*([0-9]{4}年\s*[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return ""


def _extract_publish_date(text: str) -> str:
    match = re.search(r"(?:公示发布时间|发布日期|公告日期)\s*[:：]?\s*([0-9]{4}[-年][0-9]{1,2}[-月][0-9]{1,2}(?:日)?(?:\s+[0-9:]{4,8})?)", text)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _build_summary(
    *,
    task_records: list[Mapping[str, Any]],
    field_records: list[Mapping[str, Any]],
    overlap_records: list[Mapping[str, Any]],
    not_selected_records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
) -> dict[str, Any]:
    state_counts = _counts(record.get("p13b_ygp_original_readback_state") for record in task_records)
    return {
        "p13b_ygp_original_readback_expansion_state": "P13B_YGP_ORIGINAL_READBACK_EXPANSION_READY"
        if not blocking_reasons
        else "P13B_YGP_ORIGINAL_READBACK_EXPANSION_INPUT_BLOCKED",
        "task_count": len(task_records),
        "ready_count": state_counts.get("P13B_YGP_ORIGINAL_READBACK_READY", 0)
        + state_counts.get("P13B_YGP_BACKLOG_TRACKED_READY", 0)
        + state_counts.get("P13B_YGP_NO_PUBLIC_ATTACHMENT_BUT_DETAIL_READY", 0),
        "partial_review_count": state_counts.get("P13B_YGP_FIELD_PARTIAL_REVIEW", 0),
        "backlog_tracked_count": sum(1 for record in task_records if record.get("backlog_tracked")),
        "no_public_attachment_but_detail_ready_count": state_counts.get("P13B_YGP_NO_PUBLIC_ATTACHMENT_BUT_DETAIL_READY", 0),
        "source_blocked_count": state_counts.get("P13B_YGP_SOURCE_BLOCKED", 0),
        "not_selected_count": len(not_selected_records),
        "field_record_count": len(field_records),
        "overlap_triage_input_count": len(overlap_records),
        "p13b_ygp_original_readback_state_counts": state_counts,
        "not_selected_state_counts": _counts(record.get("readiness_state_from_mini_closeout") for record in not_selected_records),
        "blocking_reasons": blocking_reasons,
        "forbidden_term_scan_state": "PENDING",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _finalize_and_write(
    out_dir: Path,
    result: dict[str, Any],
    task_records: list[Mapping[str, Any]],
    field_records: list[Mapping[str, Any]],
    overlap_records: list[Mapping[str, Any]],
) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [*list(result.get("blocking_reasons") or []), *[f"forbidden_report_term:{term}" for term in forbidden_hits]]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "FAIL"
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
    _write_json(out_dir / "p13b-ygp-original-readback-task-table.json", {"summary": result["summary"], "records": task_records})
    _write_json(out_dir / "p13b-ygp-original-readback-field-table.json", {"summary": result["summary"], "records": field_records})
    _write_json(out_dir / "p13b-ygp-overlap-triage-input-table.json", {"summary": result["summary"], "records": overlap_records})
    _write_json(out_dir / "p13b-ygp-original-readback-expansion-v1.json", result)


def _load_first_json(paths: list[Path], missing: list[str], reason: str) -> dict[str, Any]:
    for path in paths:
        if path.exists():
            payload = _load_json(path, missing, reason)
            payload["_loaded_path"] = str(path)
            return payload
    missing.append(reason)
    return {}


def _loaded_path(payload: Mapping[str, Any]) -> str:
    return str(payload.get("_loaded_path") or "")


def _load_json(path: Path, missing: list[str], reason: str) -> dict[str, Any]:
    if not path.exists():
        missing.append(reason)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        missing.append(f"{reason}:invalid_json")
        return {}


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_to_text(value: Any) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(child, (str, int, float)):
                    parts.append(f"{key}：{child}")
                else:
                    walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, (str, int, float)):
            parts.append(str(item))

    walk(value)
    return "\n".join(parts)


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        key = str(value).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counter = Counter(str(value) for value in values if str(value or "").strip())
    return dict(sorted(counter.items()))


def _int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value or 0)
    except Exception:
        return 0


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build P13B YGP original readback expansion v1.")
    parser.add_argument("--mini-closeout-root", default=str(DEFAULT_MINI_CLOSEOUT_ROOT))
    parser.add_argument("--city-discovery-root", default=str(DEFAULT_CITY_DISCOVERY_ROOT))
    parser.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_p13b_ygp_original_readback_expansion(
        mini_closeout_root=args.mini_closeout_root,
        city_discovery_root=args.city_discovery_root,
        download_root=args.download_root,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = result.get("summary", {})
        print(
            "p13b ygp original readback expansion built: "
            f"state={summary.get('p13b_ygp_original_readback_expansion_state')} "
            f"tasks={summary.get('task_count')} "
            f"ready={summary.get('ready_count')} "
            f"overlap_inputs={summary.get('overlap_triage_input_count')}"
        )
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
