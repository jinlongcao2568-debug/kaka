from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


PRIORITY_REVIEW_IDXS = (1, 2, 3, 4, 5, 7, 9, 13, 16, 21, 28)

JZSC_PERSON_IDENTITY = "JZSC_PERSON_IDENTITY"
GUANGDONG_THREE_LIBRARY = "GUANGDONG_THREE_LIBRARY"
LOCAL_HOUSING_CONSTRUCTION = "LOCAL_HOUSING_CONSTRUCTION"
PROJECT_MANAGER_CHANGE = "PROJECT_MANAGER_CHANGE"
PENALTY_CREDIT = "PENALTY_CREDIT"

REVIEW_ONLY_STATE = "NOT_SELLABLE_REVIEW_ONLY"
ATTACHMENT_TEXT_UNAVAILABLE = "ATTACHMENT_TEXT_NOT_AVAILABLE_REVIEW_REQUIRED"
NO_LEGAL_CONCLUSION = True
POST_AWARD_PROJECT_RECORD_PROVIDERS = frozenset(
    {
        "CONSTRUCTION_PERMIT",
        "CONTRACT_FILING",
        "COMPLETION_FILING",
        PROJECT_MANAGER_CHANGE,
    }
)
PROJECT_RECORD_MATURE_STATES = frozenset(
    {
        "PROJECT_CODE_PRESENT",
        "PROJECT_RECORD_STAGE_SIGNAL_PRESENT",
    }
)

METHOD_PATTERNS = (
    "综合评估法",
    "经评审的最低投标价法",
    "最低投标价法",
    "合理低价法",
    "评定分离",
    "票决法",
    "K值抽取",
    "两阶段评标",
)

PROVIDER_DISPLAY_ORDER = (
    JZSC_PERSON_IDENTITY,
    GUANGDONG_THREE_LIBRARY,
    LOCAL_HOUSING_CONSTRUCTION,
    "CONSTRUCTION_PERMIT",
    "CONTRACT_FILING",
    "COMPLETION_FILING",
    PROJECT_MANAGER_CHANGE,
    PENALTY_CREDIT,
)


def build_review_matrices(
    *,
    trace_payload: Mapping[str, Any],
    merged_stage4_payload: Mapping[str, Any],
    retry_stage4_payload: Mapping[str, Any] | None = None,
    provider_queue_payload: Mapping[str, Any],
    priority_idxs: Iterable[int] = PRIORITY_REVIEW_IDXS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the 11-row review matrix and the 22-row blocker matrix.

    The function is intentionally read-only and does not query live sources. It
    only normalizes existing Stage2/Stage4 handoff facts into review artifacts.
    """

    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    trace_by_idx = _records_by_idx(trace_payload.get("rows") or trace_payload.get("records") or [])
    merged_by_idx = _records_by_idx(merged_stage4_payload.get("records") or [])
    retry_by_idx = _records_by_idx((retry_stage4_payload or {}).get("records") or [])
    jobs_by_idx_provider = _jobs_by_idx_provider(provider_queue_payload.get("jobs") or [])

    all_records: list[dict[str, Any]] = []
    for idx in sorted(merged_by_idx):
        base = dict(merged_by_idx[idx])
        if idx in retry_by_idx:
            base.update({k: v for k, v in retry_by_idx[idx].items() if v not in (None, "", [], {})})
        trace = trace_by_idx.get(idx, {})
        jobs_by_provider = jobs_by_idx_provider.get(idx, {})
        all_records.append(_build_record(idx, base, trace, jobs_by_provider))

    priority_set = set(int(value) for value in priority_idxs)
    priority_records = [record for record in all_records if record["idx"] in priority_set]

    blocker_payload = {
        "summary": _summary(
            generated_at=generated_at,
            matrix_name="guangzhou_22_stage4_blocker_attribution",
            records=all_records,
            source_count=len(merged_by_idx),
        ),
        "records": all_records,
    }
    review_payload = {
        "summary": _summary(
            generated_at=generated_at,
            matrix_name="guangzhou_11_stage4_review_matrix",
            records=priority_records,
            source_count=len(priority_set),
        ),
        "records": priority_records,
    }
    return {"review_11": review_payload, "blocker_22": blocker_payload}


def build_review_matrices_from_files(
    *,
    trace_json: Path,
    merged_stage4_json: Path,
    retry_stage4_json: Path,
    provider_queue_json: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return build_review_matrices(
        trace_payload=_read_json(trace_json),
        merged_stage4_payload=_read_json(merged_stage4_json),
        retry_stage4_payload=_read_json(retry_stage4_json),
        provider_queue_payload=_read_json(provider_queue_json),
        generated_at=generated_at,
    )


def write_review_outputs(
    *,
    review_payload: Mapping[str, Any],
    blocker_payload: Mapping[str, Any],
    review_jsonl: Path,
    review_summary_json: Path,
    review_markdown: Path,
    blocker_jsonl: Path,
    blocker_summary_json: Path,
    blocker_markdown: Path,
) -> None:
    _write_jsonl(review_jsonl, review_payload.get("records") or [])
    _write_json(review_summary_json, review_payload.get("summary") or {})
    _write_markdown(review_markdown, review_payload, title="广州 11 条 Stage4 评标方式与身份卡点核对表")

    _write_jsonl(blocker_jsonl, blocker_payload.get("records") or [])
    _write_json(blocker_summary_json, blocker_payload.get("summary") or {})
    _write_markdown(blocker_markdown, blocker_payload, title="广州 22 条 Stage4 卡点归因表")


def _build_record(
    idx: int,
    stage4_record: Mapping[str, Any],
    trace_record: Mapping[str, Any],
    jobs_by_provider: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    title = _first_text(stage4_record.get("title"), trace_record.get("title"))
    notice_url = _first_text(stage4_record.get("notice_url"), trace_record.get("url"))
    priority_class = _first_text(stage4_record.get("type"), trace_record.get("type"))
    candidate_company = _first_text(stage4_record.get("candidate_company"), trace_record.get("company"))
    person = _first_text(stage4_record.get("responsible_person"), trace_record.get("responsible_person"))
    cert = _first_text(stage4_record.get("announcement_certificate_no"), trace_record.get("certificate_no"))
    project_name = _clean_project_name(_first_text(stage4_record.get("project_name"), title))
    publication = _publication_state(title)
    notice_stage = _notice_stage(stage4_record, trace_record, title, publication)
    fact_maturity_stage = _fact_maturity_stage(stage4_record, trace_record, jobs_by_provider, notice_stage)
    project_code_required = fact_maturity_stage in PROJECT_RECORD_MATURE_STATES
    provider_statuses = {
        provider_id: _provider_status(
            provider_id,
            jobs_by_provider.get(provider_id) or [],
            provider_applicability_state=_provider_applicability_state(
                provider_id,
                notice_stage=notice_stage,
                fact_maturity_stage=fact_maturity_stage,
            ),
            project_code_required=project_code_required,
        )
        for provider_id in PROVIDER_DISPLAY_ORDER
    }
    attachment_state, attachment_names = _attachment_state(trace_record)
    evaluation_method, evaluation_method_state = _extract_method(
        stage4_record,
        trace_record,
        explicit_keys=("evaluation_method", "bid_evaluation_method", "bid_evaluation_policy"),
        fallback_state=attachment_state,
    )
    determination_method, determination_method_state = _extract_method(
        stage4_record,
        trace_record,
        explicit_keys=("determination_method", "calibration_method", "winner_determination_method"),
        fallback_state=attachment_state,
    )
    qualification_requirement, qualification_requirement_state = _responsible_requirement(
        stage4_record,
        trace_record,
        priority_class,
        attachment_state,
    )
    qualification_profile = _qualification_requirement_profile(
        stage4_record=stage4_record,
        trace_record=trace_record,
        priority_class=priority_class,
        qualification_requirement=qualification_requirement,
        qualification_requirement_state=qualification_requirement_state,
        notice_url=notice_url,
    )
    if (
        qualification_requirement_state.endswith("_REVIEW_REQUIRED")
        and qualification_profile["certificate_verification_route"] != "CERTIFICATE_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED"
    ):
        qualification_requirement_state = "RESPONSIBLE_QUALIFICATION_REQUIREMENT_EXTRACTED_FROM_CERTIFICATE_FIELDS"

    risk_records = _enterprise_risk_records(provider_statuses.get(PENALTY_CREDIT) or {})
    attachment_blocker_codes = _attachment_blocker_codes(trace_record)
    blockers = _blocker_attribution(
        stage4_record=stage4_record,
        provider_statuses=provider_statuses,
        attachment_state=attachment_state,
        attachment_blocker_codes=attachment_blocker_codes,
        qualification_requirement_state=qualification_requirement_state,
        qualification_profile=qualification_profile,
        risk_records=risk_records,
    )
    next_sources = _next_review_sources(blockers, publication["candidate_scope_state"])

    return {
        "idx": idx,
        "project_title": title,
        "project_name": project_name,
        "notice_url": notice_url,
        "notice_stage": notice_stage,
        "fact_maturity_stage": fact_maturity_stage,
        "notice_publication_state": publication["notice_publication_state"],
        "candidate_scope_state": publication["candidate_scope_state"],
        "final_winner_confirmation_state": publication["final_winner_confirmation_state"],
        "opportunity_priority_class": priority_class,
        "type_label": _first_text(trace_record.get("type_label")),
        "engineering_work_lane": _first_text(trace_record.get("engineering_work_lane")),
        "source_dataset_name": _first_text(trace_record.get("source_dataset_name")),
        "source_trading_process": _first_text(trace_record.get("source_trading_process")),
        "candidate_company": candidate_company,
        "matched_company_name": _first_text(stage4_record.get("matched_company_name")),
        "matched_company_public_id": _first_text(stage4_record.get("matched_company_public_id")),
        "responsible_person": person,
        "announcement_certificate_no": cert,
        "stage4_outcome": _first_text(
            stage4_record.get("normalized_stage4_outcome"),
            stage4_record.get("stage4_outcome"),
        ),
        "identity_resolution_state": _first_text(stage4_record.get("identity_resolution_state")),
        "evaluation_method": evaluation_method,
        "evaluation_method_state": evaluation_method_state,
        "determination_method": determination_method,
        "determination_method_state": determination_method_state,
        "responsible_qualification_requirement": qualification_requirement,
        "responsible_qualification_requirement_state": qualification_requirement_state,
        "responsible_role_type": qualification_profile["responsible_role_type"],
        "required_certificate_type": qualification_profile["required_certificate_type"],
        "required_specialty": qualification_profile["required_specialty"],
        "required_grade": qualification_profile["required_grade"],
        "required_title": qualification_profile["required_title"],
        "safety_b_required": qualification_profile["safety_b_required"],
        "safety_b_requirement_state": qualification_profile["safety_b_requirement_state"],
        "requirement_source_text": qualification_profile["requirement_source_text"],
        "requirement_source_url": qualification_profile["requirement_source_url"],
        "certificate_verification_route": qualification_profile["certificate_verification_route"],
        "attachment_text_state": attachment_state,
        "attachment_link_count": trace_record.get("attachment_link_count") or 0,
        "attachment_snapshot_count": trace_record.get("attachment_snapshot_count") or 0,
        "attachment_capture_statuses": trace_record.get("attachment_capture_statuses") or {},
        "attachment_text_merge_state": _first_text(trace_record.get("attachment_text_merge_state")),
        "attachment_text_parse_states": list(trace_record.get("attachment_text_parse_states") or []),
        "attachment_blocker_codes": attachment_blocker_codes,
        "attachment_snapshot_refs": list(trace_record.get("attachment_snapshot_refs") or []),
        "qualification_text_candidate_blocks": list(trace_record.get("qualification_text_candidate_blocks") or []),
        "attachment_names": attachment_names,
        "jzsc_status": provider_statuses[JZSC_PERSON_IDENTITY],
        "gdcic_status": provider_statuses[GUANGDONG_THREE_LIBRARY],
        "local_housing_construction_status": provider_statuses[LOCAL_HOUSING_CONSTRUCTION],
        "project_manager_change_status": provider_statuses[PROJECT_MANAGER_CHANGE],
        "provider_applicability_state": {
            provider_id: status.get("provider_applicability_state")
            for provider_id, status in provider_statuses.items()
        },
        "provider_statuses": provider_statuses,
        "blocker_attribution": blockers,
        "next_review_sources": next_sources,
        "enterprise_risk_public_records": risk_records,
        "enterprise_risk_note": (
            "企业风险公开记录待复核；不是当前项目冲突证据"
            if risk_records
            else ""
        ),
        "customer_sellable_evidence_state": REVIEW_ONLY_STATE,
        "no_legal_conclusion": NO_LEGAL_CONCLUSION,
    }


def _provider_status(
    provider_id: str,
    jobs: list[Mapping[str, Any]],
    *,
    provider_applicability_state: str = "APPLICABLE",
    project_code_required: bool = True,
) -> dict[str, Any]:
    if not jobs:
        return {
            "provider_id": provider_id,
            "job_status": "NOT_ENQUEUED",
            "provider_result_state": provider_applicability_state
            if provider_applicability_state != "APPLICABLE"
            else "NOT_ENQUEUED",
            "verification_result": "NOT_APPLICABLE",
            "provider_applicability_state": provider_applicability_state,
            "review_reasons": [provider_applicability_state]
            if provider_applicability_state != "APPLICABLE"
            else ["provider_job_not_found_in_existing_queue"],
            "failure_reasons": [],
            "blocker_codes": [],
        }
    job = jobs[0]
    result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
    review_reasons = _dedupe([*_as_list(result.get("review_reasons")), *_as_list(job.get("error_history"))])
    failure_reasons = _dedupe(_provider_failure_reasons(result))
    blocker_codes = _provider_blockers(
        provider_id,
        review_reasons,
        failure_reasons,
        result,
        provider_applicability_state=provider_applicability_state,
        project_code_required=project_code_required,
    )
    raw_verification_result = _clean_text(result.get("verification_result"))
    verification_result = (
        "NOT_APPLICABLE"
        if provider_id in POST_AWARD_PROJECT_RECORD_PROVIDERS
        and provider_applicability_state != "APPLICABLE"
        else raw_verification_result
    )
    return {
        "provider_id": provider_id,
        "job_id": _clean_text(job.get("job_id")),
        "job_status": _clean_text(job.get("status")),
        "provider_result_state": _clean_text(result.get("provider_result_state")),
        "verification_result": verification_result,
        "raw_verification_result": raw_verification_result,
        "provider_applicability_state": provider_applicability_state,
        "review_reasons": _dedupe(
            [provider_applicability_state, *review_reasons]
            if provider_applicability_state != "APPLICABLE"
            else review_reasons
        ),
        "failure_reasons": failure_reasons,
        "blocker_codes": blocker_codes,
        "customer_sellable_evidence_ready": bool(result.get("customer_sellable_evidence_ready")),
        "relevant_source_results": list(result.get("relevant_source_results") or []),
    }


def _provider_failure_reasons(result: Mapping[str, Any]) -> list[str]:
    reasons = list(_as_list(result.get("failure_reasons")))
    source_readback = result.get("source_readback")
    if isinstance(source_readback, Mapping):
        reasons.extend(_as_list(source_readback.get("failure_reasons")))
    for source_result in list(result.get("relevant_source_results") or []):
        if isinstance(source_result, Mapping):
            reasons.extend(_as_list(source_result.get("failure_reasons")))
    return reasons


def _provider_blockers(
    provider_id: str,
    review_reasons: list[str],
    failure_reasons: list[str],
    result: Mapping[str, Any],
    *,
    provider_applicability_state: str,
    project_code_required: bool,
) -> list[str]:
    if provider_id == JZSC_PERSON_IDENTITY:
        return []
    if provider_id in POST_AWARD_PROJECT_RECORD_PROVIDERS and provider_applicability_state != "APPLICABLE":
        return []
    all_reasons = [*review_reasons, *failure_reasons]
    blockers: list[str] = []
    if provider_id in {LOCAL_HOUSING_CONSTRUCTION, PROJECT_MANAGER_CHANGE} and any(
        "runtime_adapter_not_implemented" in reason for reason in all_reasons
    ):
        blockers.append("SYSTEM_GAP_RUNTIME_ADAPTER_NOT_IMPLEMENTED")
    if project_code_required and any(reason == "gdcic_project_code_not_resolved" for reason in all_reasons):
        blockers.append("SYSTEM_GAP_PROJECT_CODE_RESOLUTION")
    if project_code_required:
        blockers.extend(_gdcic_project_code_resolution_blockers(all_reasons))
    if result.get("verification_result") == "PUBLIC_RECORD_FOUND_REVIEW":
        blockers.append("ENTERPRISE_RISK_PUBLIC_RECORD_REVIEW")
    if result.get("verification_result") == "REVIEW_REQUIRED" and not blockers:
        blockers.append(f"{provider_id}_REVIEW_REQUIRED")
    return _dedupe(blockers)


def _gdcic_project_code_resolution_blockers(reasons: Iterable[str]) -> list[str]:
    blockers: list[str] = []
    reason_set = set(str(reason) for reason in reasons)
    if "gdcic_project_code_not_resolved_after_project_name_candidate_queries" in reason_set:
        blockers.append("GDCIC_PROJECT_CODE_TITLE_CANDIDATES_NOT_MATCHED")
    if "gdcic_project_lookup_empty_result" in reason_set or any(
        reason.endswith("_empty_result") for reason in reason_set
    ):
        blockers.append("GDCIC_PROJECT_CODE_LOOKUP_EMPTY_RESULT")
    if "project_code_missing_from_query_context" in reason_set:
        blockers.append("GDCIC_PROJECT_CODE_MISSING_FROM_QUERY_CONTEXT")
    if any("structure_changed" in reason or "schema_changed" in reason for reason in reason_set):
        blockers.append("GDCIC_PROJECT_CODE_RESPONSE_STRUCTURE_CHANGED")
    return blockers


def _blocker_attribution(
    *,
    stage4_record: Mapping[str, Any],
    provider_statuses: Mapping[str, Mapping[str, Any]],
    attachment_state: str,
    attachment_blocker_codes: Iterable[str],
    qualification_requirement_state: str,
    qualification_profile: Mapping[str, Any],
    risk_records: list[dict[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    outcome = _clean_text(stage4_record.get("normalized_stage4_outcome") or stage4_record.get("stage4_outcome"))
    if outcome == "COMPANY_MATCHED_PERSON_NOT_FOUND_REVIEW":
        blockers.append("JZSC_PERSON_IDENTITY_NOT_CLOSED")
    elif outcome == "PERSON_FOUND_BUT_IDENTITY_REVIEW":
        blockers.append("JZSC_PERSON_FOUND_IDENTITY_NOT_CLOSED")
    elif outcome and outcome != "JZSC_PERSON_COMPANY_CERT_MATCHED":
        blockers.append("JZSC_IDENTITY_REVIEW_REQUIRED")

    for provider in provider_statuses.values():
        blockers.extend(list(provider.get("blocker_codes") or []))
    if attachment_state == ATTACHMENT_TEXT_UNAVAILABLE:
        blockers.append(ATTACHMENT_TEXT_UNAVAILABLE)
        blockers.extend(attachment_blocker_codes)
    if qualification_requirement_state.endswith("_REVIEW_REQUIRED"):
        blockers.append(qualification_requirement_state)
    route_blocker = _certificate_route_blocker(qualification_profile)
    if route_blocker:
        blockers.append(route_blocker)
    if risk_records:
        blockers.append("ENTERPRISE_RISK_PUBLIC_RECORD_REVIEW")
    blockers.append("STAGE4_DEEP_VERIFICATION_NOT_CLOSED")
    return _dedupe(blockers)


def _enterprise_risk_records(provider_status: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source_result in list(provider_status.get("relevant_source_results") or []):
        if not isinstance(source_result, Mapping):
            continue
        if source_result.get("coverage_state") != "COVERED":
            continue
        for row in list(source_result.get("matched_records_preview") or []):
            if not isinstance(row, Mapping):
                continue
            records.append(
                {
                    "source_type": _clean_text(source_result.get("source_type")),
                    "source_url": _clean_text(source_result.get("source_url")),
                    "enterprise_name": _first_text(row.get("entName"), row.get("corpName"), row.get("orgName")),
                    "project_name": _first_text(row.get("projectName"), row.get("perfName")),
                    "happen_time": _first_text(row.get("happenTime"), row.get("punishTime")),
                    "publish_time": _first_text(row.get("publishTime"), row.get("publicDate")),
                    "record_id": _first_text(row.get("id"), row.get("recordId")),
                    "review_note": "企业风险公开记录待复核；不是当前项目冲突证据",
                }
            )
    return records


def _next_review_sources(blockers: Iterable[str], candidate_scope_state: str) -> list[str]:
    blocker_set = set(blockers)
    sources: list[str] = []
    if ATTACHMENT_TEXT_UNAVAILABLE in blocker_set:
        sources.append("回源下载并解析招标公告、招标文件、评标报告、定标报告正文")
    if "SYSTEM_GAP_RUNTIME_ADAPTER_NOT_IMPLEMENTED" in blocker_set:
        sources.append("补地方住建公开库；施工/EPC 再补项目经理变更公开记录 adapter 后重跑")
    if "SYSTEM_GAP_PROJECT_CODE_RESOLUTION" in blocker_set:
        sources.append("增强 GDCIC 项目名清洗、标题后缀清理和项目代码反查")
    if "GDCIC_PROJECT_CODE_LOOKUP_EMPTY_RESULT" in blocker_set:
        sources.append("复核当前公告阶段是否应已有施工许可、合同、竣工或变更公开记录")
    if "REGISTERED_ENGINEER_ROUTE_REVIEW_REQUIRED" in blocker_set:
        sources.append("按公告证书类型核查勘察设计注册工程师或对应注册人员库")
    if "PROFESSIONAL_TITLE_REVIEW_REQUIRED" in blocker_set:
        sources.append("按职称要求复核附件承诺、地方人社或行业主管部门公开信息")
    if "CERTIFICATE_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED" in blocker_set:
        sources.append("回源解析项目负责人资格要求原文，确认证书类型、专业、等级和职称")
    if "SAFETY_B_SUPPLEMENT_ONLY_REVIEW" in blocker_set:
        sources.append("安全B证仅作为附加条件复核，不替代主证")
    if any(code.startswith("JZSC_") for code in blocker_set):
        sources.append("用地方人员库、证书号反查、公告承诺字段复核人员身份")
    if candidate_scope_state == "CANDIDATES_ONLY_FINAL_WINNER_NOT_CONFIRMED":
        sources.append("回源核对中标结果公示或中标通知书确认最终范围")
    if "ENTERPRISE_RISK_PUBLIC_RECORD_REVIEW" in blocker_set:
        sources.append("单列企业风险公开记录复核，不并入当前项目事实冲突")
    return _dedupe(sources)


def _publication_state(title: str) -> dict[str, str]:
    if "中标候选人及中标结果公示" in title:
        return {
            "notice_publication_state": "CANDIDATE_AND_RESULT_PUBLICATION",
            "candidate_scope_state": "CANDIDATE_AND_RESULT_PUBLICATION",
            "final_winner_confirmation_state": "FINAL_WINNER_NEEDS_BODY_CONFIRMATION",
        }
    if "中标候选人公示" in title:
        return {
            "notice_publication_state": "CANDIDATE_PUBLICATION",
            "candidate_scope_state": "CANDIDATES_ONLY_FINAL_WINNER_NOT_CONFIRMED",
            "final_winner_confirmation_state": "FINAL_WINNER_NOT_CONFIRMED",
        }
    if "中标结果" in title:
        return {
            "notice_publication_state": "RESULT_PUBLICATION",
            "candidate_scope_state": "RESULT_PUBLICATION_REVIEW_REQUIRED",
            "final_winner_confirmation_state": "FINAL_WINNER_NEEDS_BODY_CONFIRMATION",
        }
    return {
        "notice_publication_state": "NOTICE_TYPE_REVIEW_REQUIRED",
        "candidate_scope_state": "NOTICE_SCOPE_REVIEW_REQUIRED",
        "final_winner_confirmation_state": "FINAL_WINNER_NOT_CONFIRMED",
    }


def _notice_stage(
    stage4_record: Mapping[str, Any],
    trace_record: Mapping[str, Any],
    title: str,
    publication: Mapping[str, Any],
) -> str:
    raw = _first_text(
        stage4_record.get("notice_stage"),
        trace_record.get("notice_stage"),
        stage4_record.get("source_notice_stage"),
        trace_record.get("source_notice_stage"),
    )
    normalized = _normalize_notice_stage(raw)
    if normalized:
        return normalized
    publication_state = _clean_text(publication.get("notice_publication_state"))
    if publication_state == "CANDIDATE_PUBLICATION":
        return "candidate_notice"
    if publication_state in {"CANDIDATE_AND_RESULT_PUBLICATION", "RESULT_PUBLICATION"}:
        return "award_result"
    text = title
    if "中标候选人" in text:
        return "candidate_notice"
    if "中标结果" in text or "中标公告" in text or "成交结果" in text:
        return "award_result"
    if "招标公告" in text:
        return "tender_notice"
    return "notice_stage_review_required"


def _normalize_notice_stage(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    aliases = {
        "candidate_notice": "candidate_notice",
        "candidate_publication": "candidate_notice",
        "中标候选人公示": "candidate_notice",
        "award_result": "award_result",
        "result_notice": "award_result",
        "bid_result": "award_result",
        "中标结果": "award_result",
        "中标结果公示": "award_result",
        "tender_notice": "tender_notice",
        "招标公告": "tender_notice",
    }
    if text in aliases:
        return aliases[text]
    lowered = text.lower()
    for raw, normalized in aliases.items():
        if raw.lower() in lowered:
            return normalized
    return text


def _fact_maturity_stage(
    stage4_record: Mapping[str, Any],
    trace_record: Mapping[str, Any],
    jobs_by_provider: Mapping[str, list[Mapping[str, Any]]],
    notice_stage: str,
) -> str:
    if _record_has_project_code(stage4_record) or _record_has_project_code(trace_record) or _jobs_have_project_code(jobs_by_provider):
        return "PROJECT_CODE_PRESENT"
    if _has_project_record_stage_signal(stage4_record, trace_record):
        return "PROJECT_RECORD_STAGE_SIGNAL_PRESENT"
    if notice_stage in {"candidate_notice", "award_result", "tender_notice"}:
        return "NOTICE_STAGE_NOT_PROJECT_RECORD_MATURE"
    return "NOTICE_STAGE_REVIEW_REQUIRED"


def _record_has_project_code(record: Mapping[str, Any]) -> bool:
    for key in (
        "project_code",
        "projectCode",
        "prjCode",
        "prjNum",
        "project_no",
        "projectNo",
        "projectNum",
        "tender_project_code",
        "tenderProjectCode",
    ):
        if _clean_text(record.get(key)):
            return True
    for key in ("source_url", "notice_url", "url"):
        url = _clean_text(record.get(key))
        if re.search(r"(?:projectCode|project_code|prjCode|projectNo|projectNum|tenderProjectCode)=", url, re.I):
            return True
    return False


def _jobs_have_project_code(jobs_by_provider: Mapping[str, list[Mapping[str, Any]]]) -> bool:
    for jobs in jobs_by_provider.values():
        for job in jobs:
            if not isinstance(job, Mapping):
                continue
            result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
            readback = result.get("source_readback") if isinstance(result.get("source_readback"), Mapping) else {}
            if readback.get("project_codes"):
                return True
    return False


def _has_project_record_stage_signal(
    stage4_record: Mapping[str, Any],
    trace_record: Mapping[str, Any],
) -> bool:
    haystack = _available_text(stage4_record, trace_record)
    return bool(re.search(r"施工许可|施工许可证|合同备案|合同信息|竣工备案|竣工验收|项目经理变更|负责人变更|总监变更", haystack))


def _provider_applicability_state(
    provider_id: str,
    *,
    notice_stage: str,
    fact_maturity_stage: str,
) -> str:
    if provider_id in POST_AWARD_PROJECT_RECORD_PROVIDERS:
        if fact_maturity_stage in PROJECT_RECORD_MATURE_STATES:
            return "APPLICABLE"
        if notice_stage in {"candidate_notice", "award_result"}:
            return "NOT_EXPECTED_YET_REVIEW"
        return "NOT_APPLICABLE_AT_CURRENT_NOTICE_STAGE"
    if provider_id == GUANGDONG_THREE_LIBRARY and fact_maturity_stage not in PROJECT_RECORD_MATURE_STATES:
        return "APPLICABLE_IDENTITY_ONLY_PROJECT_RECORD_NOT_EXPECTED_YET_REVIEW"
    return "APPLICABLE"


def _attachment_state(trace_record: Mapping[str, Any]) -> tuple[str, list[str]]:
    names = _attachment_names(trace_record)
    merge_state = _clean_text(trace_record.get("attachment_text_merge_state"))
    if merge_state == "ATTACHMENT_TEXT_MERGED" or trace_record.get("qualification_text_candidate_blocks"):
        return "ATTACHMENT_TEXT_AVAILABLE_FOR_EXTRACTION", names
    link_count = int(trace_record.get("attachment_link_count") or len(names) or 0)
    snapshot_count = int(trace_record.get("attachment_snapshot_count") or 0)
    if link_count > 0 and snapshot_count <= 0:
        return ATTACHMENT_TEXT_UNAVAILABLE, names
    if link_count <= 0:
        return "NO_ATTACHMENT_TEXT_SOURCE_REVIEW_REQUIRED", names
    return "ATTACHMENT_TEXT_AVAILABLE_FOR_EXTRACTION", names


def _attachment_blocker_codes(trace_record: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for state in _flatten_text_values(trace_record.get("attachment_text_parse_states")):
        upper = state.upper()
        if not upper:
            continue
        if "CAPTCHA" in upper or "MANUAL_VERIFICATION" in upper:
            codes.append("ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED:CAPTCHA_MANUAL_REQUIRED")
        elif "READBACK_FAILED" in upper:
            codes.append("ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED:SNAPSHOT_READBACK_FAILED")
        elif "NO_SNAPSHOT" in upper:
            codes.append("ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED:NO_SNAPSHOT")
        elif "UNSUPPORTED" in upper or "UNKNOWN" in upper:
            codes.append("ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED:UNSUPPORTED_ATTACHMENT")
        elif "PARSER_FAILURE" in upper or "PARSE_FAILED" in upper:
            codes.append("ATTACHMENT_PARSE_FAILED_REVIEW_REQUIRED")
    return _dedupe(codes)


def _attachment_names(trace_record: Mapping[str, Any]) -> list[str]:
    raw_items = list(trace_record.get("attachment_items") or trace_record.get("attachments") or [])
    names: list[str] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            names.append(_first_text(item.get("name"), item.get("text"), item.get("title"), item.get("url")))
        else:
            names.append(_clean_text(item))
    return [name for name in _dedupe(names) if name]


def _extract_method(
    stage4_record: Mapping[str, Any],
    trace_record: Mapping[str, Any],
    *,
    explicit_keys: tuple[str, ...],
    fallback_state: str,
) -> tuple[str, str]:
    texts: list[str] = []
    for source in (stage4_record, trace_record):
        for key in explicit_keys:
            texts.append(_clean_text(source.get(key)))
        for key in ("notice_text", "detail_text", "attachment_text", "extracted_text"):
            texts.append(_clean_text(source.get(key)))
    haystack = "\n".join(text for text in texts if text)
    for pattern in METHOD_PATTERNS:
        if pattern in haystack:
            return pattern, "EXTRACTED_FROM_AVAILABLE_TEXT"
    return "", fallback_state if fallback_state == ATTACHMENT_TEXT_UNAVAILABLE else "METHOD_NOT_EXTRACTED_REVIEW_REQUIRED"


def _qualification_requirement_profile(
    *,
    stage4_record: Mapping[str, Any],
    trace_record: Mapping[str, Any],
    priority_class: str,
    qualification_requirement: str,
    qualification_requirement_state: str,
    notice_url: str,
) -> dict[str, Any]:
    haystack = "\n".join(
        text
        for text in (
            qualification_requirement,
            _available_text(stage4_record, trace_record),
        )
        if text
    )
    cert_type = _first_text(
        stage4_record.get("required_certificate_type"),
        trace_record.get("required_certificate_type"),
        stage4_record.get("project_manager_certificate_type"),
        trace_record.get("project_manager_certificate_type"),
        stage4_record.get("certificate_type"),
        trace_record.get("certificate_type"),
        _infer_certificate_type(haystack),
    )
    specialty = _first_text(
        stage4_record.get("required_specialty"),
        trace_record.get("required_specialty"),
        stage4_record.get("project_manager_cert_specialty"),
        trace_record.get("project_manager_cert_specialty"),
        stage4_record.get("project_manager_certificate_specialty"),
        trace_record.get("project_manager_certificate_specialty"),
        _infer_specialty(haystack),
    )
    title = _first_text(
        stage4_record.get("required_title"),
        trace_record.get("required_title"),
        stage4_record.get("project_manager_professional_title"),
        trace_record.get("project_manager_professional_title"),
        _infer_professional_title(haystack),
    )
    grade = _first_text(
        stage4_record.get("required_grade"),
        trace_record.get("required_grade"),
        _infer_required_grade(cert_type, haystack),
    )
    safety_b_present = bool(
        _first_text(
            stage4_record.get("safety_b_certificate_no"),
            trace_record.get("safety_b_certificate_no"),
            stage4_record.get("safety_b_certificate_no_optional"),
            trace_record.get("safety_b_certificate_no_optional"),
        )
    )
    safety_b_required = _safety_b_required(haystack) or safety_b_present
    return {
        "responsible_role_type": _responsible_role_type(priority_class, haystack),
        "required_certificate_type": cert_type,
        "required_specialty": specialty,
        "required_grade": grade,
        "required_title": title,
        "safety_b_required": safety_b_required,
        "safety_b_requirement_state": _safety_b_requirement_state(safety_b_required, safety_b_present),
        "requirement_source_text": _first_text(qualification_requirement, _certificate_source_text(cert_type, specialty, title)),
        "requirement_source_url": _first_text(
            stage4_record.get("requirement_source_url"),
            trace_record.get("requirement_source_url"),
            notice_url,
        ),
        "certificate_verification_route": _certificate_verification_route(cert_type, title, safety_b_required),
        "qualification_requirement_state": qualification_requirement_state,
    }


def _available_text(*sources: Mapping[str, Any]) -> str:
    parts: list[str] = []
    keys = (
        "notice_text",
        "detail_text",
        "attachment_text",
        "attachment_text_merge_state",
        "attachment_text_parse_states",
        "qualification_text_candidate_blocks",
        "extracted_text",
        "raw_text",
        "title",
        "project_manager_certificate_type",
        "project_manager_cert_specialty",
        "project_manager_professional_title",
        "responsible_qualification_requirement",
        "project_manager_requirement",
        "qualification_requirement",
    )
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, list):
                for item in value:
                    text = _clean_text(item)
                    if text:
                        parts.append(text)
            else:
                text = _clean_text(value)
                if text:
                    parts.append(text)
    return "\n".join(_dedupe(parts))


def _flatten_text_values(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [_clean_text(value)]
    if isinstance(value, (list, tuple, set)):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_text_values(item))
        return [item for item in flattened if item]
    text = _clean_text(value)
    return [text] if text else []


def _infer_certificate_type(text: str) -> str:
    patterns = (
        (r"一级注册建造师|一级建造师", "一级建造师"),
        (r"二级注册建造师|二级建造师", "二级建造师"),
        (r"注册建造师", "注册建造师"),
        (r"注册土木工程师\s*[（(]\s*岩土\s*[）)]|注册岩土工程师", "注册土木工程师（岩土）"),
        (r"注册土木工程师\s*[（(]\s*道路工程\s*[）)]", "注册土木工程师(道路工程)"),
        (r"注册土木工程师\s*[（(]\s*水利水电工程\s*[）)]", "注册土木工程师（水利水电工程）"),
        (r"注册土木工程师\s*[（(]\s*港口与航道工程\s*[）)]", "注册土木工程师（港口与航道工程）"),
        (r"一级注册建筑师|一级建筑师", "一级注册建筑师"),
        (r"二级注册建筑师|二级建筑师", "二级注册建筑师"),
        (r"注册建筑师", "注册建筑师"),
        (r"一级注册结构工程师|一级结构工程师", "一级注册结构工程师"),
        (r"二级注册结构工程师|二级结构工程师", "二级注册结构工程师"),
        (r"注册结构工程师", "注册结构工程师"),
        (r"注册电气工程师[（(][^）)]+[）)]|注册电气工程师", ""),
        (r"注册公用设备工程师[（(][^）)]+[）)]|注册公用设备工程师", ""),
        (r"注册(?:化工|环保|监理|造价|安全)工程师", ""),
        (r"注册(?:土木|结构|公用设备|电气)工程师[（(][^）)]+[）)]", ""),
    )
    for pattern, canonical in patterns:
        match = re.search(pattern, text)
        if match:
            return canonical or _clean_text(match.group(0))
    return ""


def _infer_specialty(text: str) -> str:
    aliases = (
        ("水利水电工程", "水利"),
        ("水利工程", "水利"),
        ("机电工程", "机电"),
        ("市政公用工程", "市政"),
        ("建筑工程", "建筑"),
        ("公路工程", "公路"),
        ("道路工程", "道路"),
        ("岩土工程", "岩土"),
        ("岩土", "岩土"),
        ("结构工程", "结构"),
        ("给水排水", "给排水"),
        ("暖通空调", "暖通"),
        ("供配电", "电气"),
    )
    for raw, canonical in aliases:
        if raw in text:
            return canonical
    return ""


def _infer_professional_title(text: str) -> str:
    match = re.search(r"(正高级工程师|高级工程师|工程师|助理工程师)", text)
    return _clean_text(match.group(1)) if match else ""


def _infer_required_grade(cert_type: str, text: str) -> str:
    combined = f"{cert_type} {text}"
    if "一级" in combined:
        return "一级"
    if "二级" in combined:
        return "二级"
    return ""


def _responsible_role_type(priority_class: str, text: str) -> str:
    if "勘察负责人" in text:
        return "survey_lead"
    if "设计负责人" in text:
        return "design_lead"
    if priority_class == "C_MEDIUM_DESIGN_SURVEY":
        return "design_or_survey_lead"
    if priority_class == "B_HIGH_SUPERVISION":
        return "chief_supervision_engineer"
    return "project_manager_or_construction_lead"


def _safety_b_required(text: str) -> bool:
    return bool(re.search(r"安全生产考核合格证(?:书)?|安全\s*B|B\s*类|安管人员.*B", text, re.I))


def _safety_b_requirement_state(required: bool, present: bool) -> str:
    if required and present:
        return "SAFETY_B_PRESENT_REVIEW"
    if required:
        return "SAFETY_B_REQUIRED"
    return "SAFETY_B_NOT_REQUIRED_OR_NOT_EXTRACTED"


def _certificate_source_text(cert_type: str, specialty: str, title: str) -> str:
    return " ".join(part for part in (cert_type, specialty, title) if part)


def _certificate_verification_route(cert_type: str, title: str, safety_b_required: bool) -> str:
    if "建造师" in cert_type:
        return "CONSTRUCTOR_REGISTRATION_ROUTE"
    if cert_type and re.search(r"注册(?:土木|建筑|结构|电气|公用设备|化工|环保|监理|造价|安全)工程师|注册建筑师|注册结构工程师", cert_type):
        return "REGISTERED_ENGINEER_ROUTE_REVIEW_REQUIRED"
    if title and not cert_type:
        return "PROFESSIONAL_TITLE_REVIEW_REQUIRED"
    if safety_b_required and not cert_type:
        return "SAFETY_B_SUPPLEMENT_ONLY_REVIEW"
    return "CERTIFICATE_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED"


def _certificate_route_blocker(profile: Mapping[str, Any]) -> str:
    route = _clean_text(profile.get("certificate_verification_route"))
    if route in {
        "REGISTERED_ENGINEER_ROUTE_REVIEW_REQUIRED",
        "PROFESSIONAL_TITLE_REVIEW_REQUIRED",
        "CERTIFICATE_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED",
        "SAFETY_B_SUPPLEMENT_ONLY_REVIEW",
    }:
        return route
    return ""


def _responsible_requirement(
    stage4_record: Mapping[str, Any],
    trace_record: Mapping[str, Any],
    priority_class: str,
    attachment_state: str,
) -> tuple[str, str]:
    for source in (stage4_record, trace_record):
        requirement = _first_non_bool_text(
            source,
            (
                "responsible_role_required",
                "responsible_qualification_requirement",
                "project_manager_requirement",
                "qualification_requirement",
            ),
        )
        if requirement:
            return requirement, "EXTRACTED_FROM_TRACE_OR_TEXT"
    if priority_class == "C_MEDIUM_DESIGN_SURVEY":
        return "", "DESIGN_SURVEY_QUALIFICATION_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED"
    if attachment_state == ATTACHMENT_TEXT_UNAVAILABLE:
        return "", "RESPONSIBLE_QUALIFICATION_REQUIREMENT_NOT_EXTRACTED_REVIEW_REQUIRED"
    return "", "RESPONSIBLE_QUALIFICATION_REQUIREMENT_REVIEW_REQUIRED"


def _summary(
    *,
    generated_at: str,
    matrix_name: str,
    records: list[Mapping[str, Any]],
    source_count: int,
) -> dict[str, Any]:
    blocker_counts = Counter(
        blocker for record in records for blocker in list(record.get("blocker_attribution") or [])
    )
    publication_counts = Counter(_clean_text(record.get("candidate_scope_state")) for record in records)
    stage4_counts = Counter(_clean_text(record.get("stage4_outcome")) for record in records)
    notice_stage_counts = Counter(_clean_text(record.get("notice_stage")) for record in records)
    certificate_route_counts = Counter(_clean_text(record.get("certificate_verification_route")) for record in records)
    return {
        "generated_at": generated_at,
        "matrix_name": matrix_name,
        "source_count": source_count,
        "record_count": len(records),
        "review_only_policy": True,
        "customer_sellable_evidence_ready": False,
        "stage4_outcome_counts": dict(stage4_counts),
        "notice_stage_counts": dict(notice_stage_counts),
        "candidate_scope_counts": dict(publication_counts),
        "certificate_route_counts": dict(certificate_route_counts),
        "blocker_counts": dict(blocker_counts),
    }


def _write_markdown(path: Path, payload: Mapping[str, Any], *, title: str) -> None:
    records = list(payload.get("records") or [])
    summary = payload.get("summary") or {}
    lines = [
        f"# {title}",
        "",
        f"- generated_at: {summary.get('generated_at', '')}",
        f"- record_count: {summary.get('record_count', 0)}",
        "- policy: REVIEW 只进入内部复核，不进入销售证据。",
        "",
        "## Summary",
        "",
    ]
    for key, values in (
        ("stage4_outcome_counts", summary.get("stage4_outcome_counts") or {}),
        ("notice_stage_counts", summary.get("notice_stage_counts") or {}),
        ("candidate_scope_counts", summary.get("candidate_scope_counts") or {}),
        ("certificate_route_counts", summary.get("certificate_route_counts") or {}),
        ("blocker_counts", summary.get("blocker_counts") or {}),
    ):
        lines.append(f"### {key}")
        for name, count in sorted(values.items()):
            lines.append(f"- {name}: {count}")
        lines.append("")

    lines.extend(
        [
            "## Review Matrix",
            "",
            "| # | 项目 | 公告范围 | 评标方式 | 定标方式 | 负责人要求 | 人员/证书 | JZSC | GDCIC | 主要卡点 | 下一步 |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(record.get("idx", "")),
                    _md(record.get("project_name")),
                    _md(record.get("candidate_scope_state")),
                    _md(record.get("evaluation_method") or record.get("evaluation_method_state")),
                    _md(record.get("determination_method") or record.get("determination_method_state")),
                    _md(
                        record.get("responsible_qualification_requirement")
                        or record.get("required_certificate_type")
                        or record.get("required_title")
                        or record.get("certificate_verification_route")
                        or record.get("responsible_qualification_requirement_state")
                    ),
                    _md(
                        f"{record.get('responsible_person', '')} "
                        f"{record.get('announcement_certificate_no', '')}".strip()
                    ),
                    _md(_provider_brief(record.get("jzsc_status") or {})),
                    _md(_provider_brief(record.get("gdcic_status") or {})),
                    _md("; ".join(list(record.get("blocker_attribution") or [])[:5])),
                    _md("; ".join(list(record.get("next_review_sources") or [])[:3])),
                ]
            )
            + " |"
        )

    risk_records = [
        (record.get("idx"), risk)
        for record in records
        for risk in list(record.get("enterprise_risk_public_records") or [])
    ]
    if risk_records:
        lines.extend(
            [
                "",
                "## Enterprise Risk Public Records",
                "",
                "说明：以下仅为企业风险公开记录待复核，不作为当前项目事实冲突。",
                "",
                "| # | 企业 | 记录项目 | 发生时间 | 发布时间 | 来源类型 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for idx, risk in risk_records:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(idx),
                        _md(risk.get("enterprise_name")),
                        _md(risk.get("project_name")),
                        _md(risk.get("happen_time")),
                        _md(risk.get("publish_time")),
                        _md(risk.get("source_type")),
                    ]
                )
                + " |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _provider_brief(provider_status: Mapping[str, Any]) -> str:
    verification = _clean_text(provider_status.get("verification_result"))
    state = _clean_text(provider_status.get("provider_result_state"))
    applicability = _clean_text(provider_status.get("provider_applicability_state"))
    blockers = ",".join(list(provider_status.get("blocker_codes") or [])[:2])
    return " / ".join(
        part
        for part in (
            verification,
            state,
            applicability if applicability != "APPLICABLE" else "",
            blockers,
        )
        if part
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def _records_by_idx(records: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    by_idx: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        idx = _safe_int(record.get("idx"))
        if idx is not None:
            by_idx[idx] = dict(record)
    return by_idx


def _jobs_by_idx_provider(jobs: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, list[Mapping[str, Any]]]]:
    grouped: dict[int, dict[str, list[Mapping[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
        idx = _safe_int(payload.get("source_trace_record_idx"))
        provider_id = _clean_text(job.get("provider_id") or payload.get("provider_id"))
        if idx is None or not provider_id:
            continue
        grouped[idx][provider_id].append(job)
    return grouped


def _clean_project_name(value: Any) -> str:
    text = _clean_text(value)
    suffixes = (
        "中标候选人及中标结果公示",
        "中标候选人公示",
        "中标结果公示",
        "中标结果公告",
        "评标报告",
    )
    for suffix in suffixes:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _first_non_bool_text(source: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        text = _clean_text(value)
        if text:
            return text
    return ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    text = _clean_text(value)
    return [text] if text else []


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _md(value: Any) -> str:
    return _clean_text(value).replace("|", "\\|").replace("\n", " ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-json", required=True)
    parser.add_argument("--merged-stage4-json", required=True)
    parser.add_argument("--retry-stage4-json", required=True)
    parser.add_argument("--provider-queue-json", required=True)
    parser.add_argument("--review-jsonl", required=True)
    parser.add_argument("--review-summary-json", required=True)
    parser.add_argument("--review-markdown", required=True)
    parser.add_argument("--blocker-jsonl", required=True)
    parser.add_argument("--blocker-summary-json", required=True)
    parser.add_argument("--blocker-markdown", required=True)
    args = parser.parse_args(argv)

    payloads = build_review_matrices_from_files(
        trace_json=Path(args.trace_json),
        merged_stage4_json=Path(args.merged_stage4_json),
        retry_stage4_json=Path(args.retry_stage4_json),
        provider_queue_json=Path(args.provider_queue_json),
    )
    write_review_outputs(
        review_payload=payloads["review_11"],
        blocker_payload=payloads["blocker_22"],
        review_jsonl=Path(args.review_jsonl),
        review_summary_json=Path(args.review_summary_json),
        review_markdown=Path(args.review_markdown),
        blocker_jsonl=Path(args.blocker_jsonl),
        blocker_summary_json=Path(args.blocker_summary_json),
        blocker_markdown=Path(args.blocker_markdown),
    )
    print(
        json.dumps(
            {
                "review_11": payloads["review_11"]["summary"],
                "blocker_22": payloads["blocker_22"]["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
