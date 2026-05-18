from __future__ import annotations

import argparse
import hashlib
import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urljoin

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage1_tasking.real_candidate_discovery import _discover_guangzhou_ywtb_api_link_items
from stage2_ingestion.service import Stage2Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


DESIGN_SURVEY_FLOW08_READBACK_KIND = "design_survey_flow08_targeted_readback_v1_manifest"
DESIGN_SURVEY_FLOW08_READBACK_VERSION = 1
DESIGN_SURVEY_FLOW08_READBACK_ID = "design-survey-flow08-targeted-readback-v1"
GUANGZHOU_PROFILE_ID = "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/design-survey-flow08-targeted-readback-v1")

FLOW08_TARGETED_READBACK_READY_NOT_EXECUTED = "FLOW08_TARGETED_READBACK_READY_NOT_EXECUTED"
FLOW08_DISCOVERY_EMPTY_OR_BLOCKED = "FLOW08_DISCOVERY_EMPTY_OR_BLOCKED"
FLOW08_DETAIL_FETCH_BLOCKED_OR_DEGRADED = "FLOW08_DETAIL_FETCH_BLOCKED_OR_DEGRADED"
FLOW08_ATTACHMENT_LISTED_TARGET_ROW_UNRESOLVED = "FLOW08_ATTACHMENT_LISTED_TARGET_ROW_UNRESOLVED"
FLOW08_TARGET_ATTACHMENT_BOUND_DOWNLOAD_DEFERRED = "FLOW08_TARGET_ATTACHMENT_BOUND_DOWNLOAD_DEFERRED"
FLOW08_TARGET_ATTACHMENT_FETCHED = "FLOW08_TARGET_ATTACHMENT_FETCHED"
FLOW08_TARGET_ATTACHMENT_FETCH_BLOCKED_OR_DEGRADED = "FLOW08_TARGET_ATTACHMENT_FETCH_BLOCKED_OR_DEGRADED"
FLOW08_TARGET_FIELDS_MISSING = "FLOW08_TARGET_FIELDS_MISSING"


Flow08Discoverer = Callable[..., Mapping[str, Any]]
DetailFetcher = Callable[..., Mapping[str, Any]]
AttachmentFetcher = Callable[..., Mapping[str, Any]]
SnapshotReader = Callable[[str], bytes]


def build_design_survey_flow08_targeted_readback(
    *,
    design_survey_adapter_plan_json: str | Path | None = None,
    design_survey_adapter_plan_root: str | Path | None = None,
    design_survey_stage4_execution_json: str | Path | None = None,
    design_survey_stage4_execution_root: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    project_ids: list[str] | tuple[str, ...] = (),
    execute: bool = False,
    download_target_attachments: bool = False,
    created_at: str | None = None,
    flow08_discoverer: Flow08Discoverer | None = None,
    detail_fetcher: DetailFetcher | None = None,
    attachment_fetcher: AttachmentFetcher | None = None,
    snapshot_reader: SnapshotReader | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    plan_manifest = _optional_manifest(
        explicit_json=design_survey_adapter_plan_json,
        root=design_survey_adapter_plan_root,
        default_file_name="design-survey-responsible-adapter-plan-v1.json",
    )
    stage4_manifest = _optional_manifest(
        explicit_json=design_survey_stage4_execution_json,
        root=design_survey_stage4_execution_root,
        default_file_name="company-first-stage4-execution.json",
    )
    if not plan_manifest:
        blocking_reasons.append("design_survey_adapter_plan_missing")
    if not stage4_manifest:
        blocking_reasons.append("design_survey_stage4_execution_missing")

    plan_index = _design_survey_plan_index_by_project(plan_manifest)
    stage4_index = _flow08_required_stage4_index_by_project(stage4_manifest)
    selected_projects = {_project_key(value) for value in project_ids if _project_key(value)}
    project_keys = sorted(set(stage4_index) | (selected_projects if selected_projects else set()))
    if selected_projects:
        project_keys = [project_id for project_id in project_keys if _project_key(project_id) in selected_projects]

    session: DatabaseSession | None = None
    repository: ObjectStorageRepository | None = None
    if execute and (detail_fetcher is None or attachment_fetcher is None or snapshot_reader is None):
        settings = Settings(
            storage_backend="json-file",
            storage_path_optional=str(out_dir / "flow08-readback-storage.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(out_dir / "objects"),
        )
        session = DatabaseSession(settings=settings)
        repository = ObjectStorageRepository(session=session, settings=settings)
        service = Stage2Service(settings=settings)
        if detail_fetcher is None:
            detail_fetcher = _stage2_detail_fetcher(service, repository)
        if attachment_fetcher is None:
            attachment_fetcher = _stage2_attachment_fetcher(service, repository)
        if snapshot_reader is None:
            snapshot_reader = repository.read_snapshot_bytes
    flow08_discoverer = flow08_discoverer or _default_flow08_discoverer

    records: list[dict[str, Any]] = []
    try:
        for project_id in project_keys:
            plan_project = plan_index.get(project_id, {})
            stage4_project = stage4_index.get(project_id, {})
            records.append(
                _build_project_readback_record(
                    project_id=project_id,
                    plan_project=plan_project,
                    stage4_project=stage4_project,
                    execute=execute,
                    download_target_attachments=download_target_attachments,
                    created_at=created,
                    flow08_discoverer=flow08_discoverer,
                    detail_fetcher=detail_fetcher,
                    attachment_fetcher=attachment_fetcher,
                    snapshot_reader=snapshot_reader,
                )
            )
    finally:
        if session is not None:
            session.close()

    readback_table = {
        "summary": _summary(records, blocking_reasons, execute=execute, download_target_attachments=download_target_attachments),
        "records": records,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    attachment_table = {
        "summary": _attachment_summary(records),
        "records": [
            attachment
            for record in records
            for attachment in _list(record.get("target_attachment_records"))
        ],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    summary = dict(readback_table["summary"])
    manifest = {
        "manifest_version": DESIGN_SURVEY_FLOW08_READBACK_VERSION,
        "manifest_kind": DESIGN_SURVEY_FLOW08_READBACK_KIND,
        "adapter_id": DESIGN_SURVEY_FLOW08_READBACK_ID,
        "pipeline_stage": "DesignSurveyFlow08TargetedReadbackV1",
        "manifest_id": f"DESIGN-SURVEY-FLOW08-{_fingerprint({'records': records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_design_survey_adapter_plan_json": _manifest_source_path(
            design_survey_adapter_plan_json,
            design_survey_adapter_plan_root,
            "design-survey-responsible-adapter-plan-v1.json",
        ),
        "source_design_survey_stage4_execution_json": _manifest_source_path(
            design_survey_stage4_execution_json,
            design_survey_stage4_execution_root,
            "company-first-stage4-execution.json",
        ),
        "flow08_targeted_readback_table": readback_table,
        "target_attachment_table": attachment_table,
        "summary": summary,
        "scope_guardrails": {
            "only_projects_triggered_by_stage4_flow08_required": True,
            "do_not_parse_all_flow_08_by_default": True,
            "do_not_download_non_target_candidate_attachments": True,
            "target_attachment_download_requires_explicit_switch": True,
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "safety": {
            "external_service_connection_enabled": bool(execute),
            "fetch_public_urls_enabled": bool(execute),
            "download_enabled": bool(execute and download_target_attachments),
            "parse_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "design_survey_flow08_targeted_readback_mode": "EXECUTED" if execute else "DRY_RUN",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
        "execution": {
            "executed": bool(execute),
            "download_target_attachments": bool(download_target_attachments),
            "download_enabled": bool(execute and download_target_attachments),
            "parse_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }

    _write_json(out_dir / "design-survey-flow08-targeted-readback-v1.json", result)
    _write_json(out_dir / "flow08-targeted-readback-table.json", readback_table)
    _write_json(out_dir / "flow08-target-attachment-table.json", attachment_table)
    return result


def _build_project_readback_record(
    *,
    project_id: str,
    plan_project: Mapping[str, Any],
    stage4_project: Mapping[str, Any],
    execute: bool,
    download_target_attachments: bool,
    created_at: str,
    flow08_discoverer: Flow08Discoverer,
    detail_fetcher: DetailFetcher | None,
    attachment_fetcher: AttachmentFetcher | None,
    snapshot_reader: SnapshotReader | None,
) -> dict[str, Any]:
    stage4_items = [
        item
        for item in _list(stage4_project.get("items"))
        if isinstance(item, Mapping)
        and (
            bool(item.get("flow_08_targeted_parse_required"))
            or str(item.get("supplement_after_execution_state") or "") == "FLOW_08_TARGETED_PARSE_REQUIRED"
        )
    ]
    target_companies = _target_companies(plan_project, stage4_items)
    project_name = _first_text(
        plan_project.get("project_name"),
        *(item.get("project_name") for item in stage4_items),
    )
    responsible_person = _first_text(
        plan_project.get("responsible_person_name"),
        *(item.get("responsible_person_name") for item in stage4_items),
    )
    base = {
        "flow08_readback_id": _stable_id("DESIGN-SURVEY-FLOW08", project_id),
        "project_id": project_id,
        "project_name": project_name,
        "responsible_person_name": responsible_person,
        "target_company_text": _first_text(plan_project.get("candidate_company_text"), ";".join(target_companies)),
        "target_company_names": target_companies,
        "stage4_flow08_required_item_count": len(stage4_items),
        "source_stage4_fail_closed_reasons": _dedupe(
            reason
            for item in stage4_items
            for reason in _list(item.get("fail_closed_reasons"))
        ),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if not target_companies or not project_name:
        return {
            **base,
            "flow08_readback_state": FLOW08_TARGET_FIELDS_MISSING,
            "discovery_state": "NOT_RUN",
            "detail_fetch_state": "NOT_RUN",
            "target_attachment_match_state": "NOT_RUN",
            "target_attachment_records": [],
            "next_action": "return_to_stage3_or_design_survey_adapter_plan_for_target_fields",
            "review_reasons": ["project_name_or_target_companies_missing"],
        }
    if not execute:
        return {
            **base,
            "flow08_readback_state": FLOW08_TARGETED_READBACK_READY_NOT_EXECUTED,
            "discovery_state": "NOT_RUN",
            "detail_fetch_state": "NOT_RUN",
            "target_attachment_match_state": "NOT_RUN",
            "target_attachment_records": [],
            "flow08_discovery_context": _flow08_discovery_context(project_name=project_name, project_id=project_id),
            "next_action": "execute_design_survey_flow08_targeted_readback",
            "review_reasons": ["flow08_targeted_readback_not_executed"],
        }

    context = _flow08_discovery_context(project_name=project_name, project_id=project_id)
    discovery = dict(flow08_discoverer(now=created_at, context=context))
    discovery_items = [dict(item) for item in _list(discovery.get("items")) if isinstance(item, Mapping)]
    flow08_item = discovery_items[0] if discovery_items else {}
    flow08_url = str(flow08_item.get("url") or flow08_item.get("source_url") or "").strip()
    if not flow08_url:
        return {
            **base,
            "flow08_readback_state": FLOW08_DISCOVERY_EMPTY_OR_BLOCKED,
            "discovery_state": str(discovery.get("state") or "EMPTY"),
            "flow08_discovery_context": context,
            "flow08_discovery_summary": _discovery_summary(discovery),
            "detail_fetch_state": "NOT_RUN",
            "target_attachment_match_state": "NOT_RUN",
            "target_attachment_records": [],
            "next_action": "manual_review_or_retry_flow08_discovery_without_clearance_claim",
            "review_reasons": _dedupe(
                [
                    "flow08_discovery_no_public_url",
                    *[
                        reason
                        for attempt in _list(discovery.get("process_attempts"))
                        for reason in _list((attempt or {}).get("failure_taxonomy") if isinstance(attempt, Mapping) else [])
                    ],
                ]
            ),
        }

    if detail_fetcher is None:
        return {
            **base,
            "flow08_readback_state": FLOW08_DETAIL_FETCH_BLOCKED_OR_DEGRADED,
            "discovery_state": str(discovery.get("state") or ""),
            "flow08_discovery_context": context,
            "flow08_discovery_summary": _discovery_summary(discovery),
            "flow08_detail_url": flow08_url,
            "detail_fetch_state": "DETAIL_FETCHER_MISSING",
            "target_attachment_match_state": "NOT_RUN",
            "target_attachment_records": [],
            "next_action": "rerun_with_detail_fetcher",
            "review_reasons": ["detail_fetcher_missing"],
        }

    detail = dict(
        detail_fetcher(
            url=flow08_url,
            project_id=project_id,
            lineage_refs={
                "project_id": project_id,
                "flow_no": "08",
                "purpose": "design_survey_flow08_targeted_readback",
            },
        )
    )
    detail_status = str(detail.get("status") or "")
    if detail_status != "FETCHED":
        return {
            **base,
            "flow08_readback_state": FLOW08_DETAIL_FETCH_BLOCKED_OR_DEGRADED,
            "discovery_state": str(discovery.get("state") or ""),
            "flow08_discovery_context": context,
            "flow08_discovery_summary": _discovery_summary(discovery),
            "flow08_detail_url": flow08_url,
            "detail_fetch_state": detail_status or "DETAIL_FETCH_FAILED",
            "detail_readback": _detail_summary(detail),
            "target_attachment_match_state": "NOT_RUN",
            "target_attachment_records": [],
            "next_action": "manual_review_or_retry_flow08_detail_readback_without_clearance_claim",
            "review_reasons": _dedupe(["flow08_detail_fetch_not_fetched", *_list(detail.get("degraded_reasons"))]),
        }

    html = _detail_html(detail, snapshot_reader=snapshot_reader)
    candidate_rows = _extract_candidate_attachment_rows(html, detail_url=str(detail.get("final_url") or flow08_url))
    attachment_records = _target_attachment_records(
        candidate_rows=candidate_rows,
        detail=detail,
        target_companies=target_companies,
        project_id=project_id,
        project_name=project_name,
        responsible_person=responsible_person,
        created_at=created_at,
    )
    bound_records = [
        record
        for record in attachment_records
        if str(record.get("target_attachment_match_state") or "") == "TARGET_CANDIDATE_ATTACHMENT_BOUND"
    ]
    if not bound_records:
        return {
            **base,
            "flow08_readback_state": FLOW08_ATTACHMENT_LISTED_TARGET_ROW_UNRESOLVED,
            "discovery_state": str(discovery.get("state") or ""),
            "flow08_discovery_context": context,
            "flow08_discovery_summary": _discovery_summary(discovery),
            "flow08_detail_url": flow08_url,
            "detail_fetch_state": detail_status,
            "detail_readback": _detail_summary(detail),
            "candidate_attachment_row_count": len(candidate_rows),
            "target_attachment_match_state": "TARGET_ROW_UNRESOLVED",
            "target_attachment_records": attachment_records,
            "next_action": "manual_bind_flow08_candidate_row_or_retry_detail_readback",
            "review_reasons": ["flow08_target_candidate_attachment_row_unresolved"],
        }

    target_record = bound_records[0]
    if not download_target_attachments:
        return {
            **base,
            "flow08_readback_state": FLOW08_TARGET_ATTACHMENT_BOUND_DOWNLOAD_DEFERRED,
            "discovery_state": str(discovery.get("state") or ""),
            "flow08_discovery_context": context,
            "flow08_discovery_summary": _discovery_summary(discovery),
            "flow08_detail_url": flow08_url,
            "detail_fetch_state": detail_status,
            "detail_readback": _detail_summary(detail),
            "candidate_attachment_row_count": len(candidate_rows),
            "target_attachment_match_state": "TARGET_CANDIDATE_ATTACHMENT_BOUND",
            "target_attachment_records": attachment_records,
            "next_action": "download_bound_flow08_target_attachment_then_parse_responsible_fields",
            "review_reasons": ["target_attachment_download_deferred_by_policy"],
        }

    if attachment_fetcher is None:
        return {
            **base,
            "flow08_readback_state": FLOW08_TARGET_ATTACHMENT_FETCH_BLOCKED_OR_DEGRADED,
            "discovery_state": str(discovery.get("state") or ""),
            "flow08_discovery_context": context,
            "flow08_discovery_summary": _discovery_summary(discovery),
            "flow08_detail_url": flow08_url,
            "detail_fetch_state": detail_status,
            "detail_readback": _detail_summary(detail),
            "candidate_attachment_row_count": len(candidate_rows),
            "target_attachment_match_state": "TARGET_CANDIDATE_ATTACHMENT_BOUND",
            "target_attachment_records": attachment_records,
            "next_action": "rerun_with_attachment_fetcher",
            "review_reasons": ["attachment_fetcher_missing"],
        }
    attachment = dict(
        attachment_fetcher(
            url=str(target_record.get("attachment_url") or ""),
            detail_url=str(detail.get("final_url") or flow08_url),
            project_id=project_id,
            lineage_refs={
                "project_id": project_id,
                "flow_no": "08",
                "candidate_company": str(target_record.get("candidate_company_text") or ""),
                "purpose": "design_survey_flow08_targeted_attachment",
            },
        )
    )
    target_record["attachment_fetch"] = _attachment_fetch_summary(attachment)
    target_record["attachment_fetch_state"] = str(attachment.get("status") or "")
    target_record["attachment_snapshot_id_optional"] = str(attachment.get("snapshot_id_optional") or "")
    state = (
        FLOW08_TARGET_ATTACHMENT_FETCHED
        if str(attachment.get("status") or "") == "FETCHED"
        else FLOW08_TARGET_ATTACHMENT_FETCH_BLOCKED_OR_DEGRADED
    )
    return {
        **base,
        "flow08_readback_state": state,
        "discovery_state": str(discovery.get("state") or ""),
        "flow08_discovery_context": context,
        "flow08_discovery_summary": _discovery_summary(discovery),
        "flow08_detail_url": flow08_url,
        "detail_fetch_state": detail_status,
        "detail_readback": _detail_summary(detail),
        "candidate_attachment_row_count": len(candidate_rows),
        "target_attachment_match_state": "TARGET_CANDIDATE_ATTACHMENT_BOUND",
        "target_attachment_records": attachment_records,
        "next_action": (
            "run_targeted_stage4_attachment_document_parse_for_design_survey_identity"
            if state == FLOW08_TARGET_ATTACHMENT_FETCHED
            else "manual_review_or_retry_target_attachment_download_without_clearance_claim"
        ),
        "review_reasons": []
        if state == FLOW08_TARGET_ATTACHMENT_FETCHED
        else _dedupe(["target_attachment_fetch_not_fetched", *_list(attachment.get("degraded_reasons"))]),
    }


def _default_flow08_discoverer(*, now: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return _discover_guangzhou_ywtb_api_link_items(now=now, context=context)


def _stage2_detail_fetcher(service: Stage2Service, repository: ObjectStorageRepository) -> DetailFetcher:
    def fetcher(*, url: str, project_id: str, lineage_refs: Mapping[str, str]) -> Mapping[str, Any]:
        return service.fetch_real_public_candidate_detail_url(
            url,
            profile_id=GUANGZHOU_PROFILE_ID,
            repository=repository,
            lineage_refs=lineage_refs,
            project_id=project_id,
        )

    return fetcher


def _stage2_attachment_fetcher(service: Stage2Service, repository: ObjectStorageRepository) -> AttachmentFetcher:
    def fetcher(
        *,
        url: str,
        detail_url: str,
        project_id: str,
        lineage_refs: Mapping[str, str],
    ) -> Mapping[str, Any]:
        return service.fetch_real_public_same_site_attachment_url(
            url,
            parent_profile_id=GUANGZHOU_PROFILE_ID,
            repository=repository,
            detail_page_url=detail_url,
            lineage_refs=lineage_refs,
            project_id=project_id,
        )

    return fetcher


def _target_attachment_records(
    *,
    candidate_rows: list[Mapping[str, Any]],
    detail: Mapping[str, Any],
    target_companies: list[str],
    project_id: str,
    project_name: str,
    responsible_person: str,
    created_at: str,
) -> list[dict[str, Any]]:
    rows = candidate_rows
    if not rows:
        rows = [
            {
                "row_index": index,
                "candidate_company_text": "",
                "attachment_url": str(item.get("url") or ""),
                "attachment_text": str(item.get("text") or ""),
                "row_text": str(item.get("text") or ""),
            }
            for index, item in enumerate(_list(detail.get("same_site_attachment_link_items")), start=1)
            if isinstance(item, Mapping) and str(item.get("url") or "").strip()
        ]
    scored = [
        (_candidate_row_match_score(row, target_companies), row)
        for row in rows
        if str(row.get("attachment_url") or "").strip()
    ]
    best_score = max((score for score, _row in scored), default=0)
    records: list[dict[str, Any]] = []
    for score, row in scored:
        matched = _matched_companies(row, target_companies)
        records.append(
            {
                "target_attachment_id": _stable_id(
                    "DESIGN-SURVEY-FLOW08-ATTACH",
                    project_id,
                    row.get("attachment_url"),
                ),
                "project_id": project_id,
                "project_name": project_name,
                "responsible_person_name": responsible_person,
                "candidate_company_text": str(row.get("candidate_company_text") or ""),
                "target_company_names": target_companies,
                "matched_target_company_names": matched,
                "candidate_row_index": int(row.get("row_index") or 0),
                "row_text_probe": _clip(row.get("row_text"), 500),
                "attachment_url": str(row.get("attachment_url") or ""),
                "attachment_link_text": str(row.get("attachment_text") or ""),
                "target_attachment_match_score": score,
                "target_attachment_match_state": (
                    "TARGET_CANDIDATE_ATTACHMENT_BOUND" if score > 0 and score == best_score else "NON_TARGET_ATTACHMENT"
                ),
                "download_policy_state": "TARGET_ATTACHMENT_ONLY_DOWNLOAD_IF_EXPLICITLY_ENABLED",
                "parse_policy_state": "TARGETED_PARSE_ONLY_AFTER_DOWNLOAD",
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    records.sort(
        key=lambda item: (
            0 if item["target_attachment_match_state"] == "TARGET_CANDIDATE_ATTACHMENT_BOUND" else 1,
            -int(item.get("target_attachment_match_score") or 0),
            int(item.get("candidate_row_index") or 0),
        )
    )
    return records


def _extract_candidate_attachment_rows(html: str, *, detail_url: str) -> list[dict[str, Any]]:
    if not html:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, match in enumerate(re.finditer(r"<tr\b[^>]*>(?P<body>.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL), start=1):
        body = match.group("body") or ""
        href_match = re.search(r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<text>.*?)</a>", body, flags=re.IGNORECASE | re.DOTALL)
        if not href_match:
            continue
        href = unescape(href_match.group("href")).strip()
        if not href:
            continue
        attachment_url = urljoin(detail_url, href).split("#", 1)[0].strip()
        cell_texts = [
            _html_to_text(cell.group("body"))
            for cell in re.finditer(r"<td\b[^>]*>(?P<body>.*?)</td>", body, flags=re.IGNORECASE | re.DOTALL)
        ]
        row_text = _html_to_text(body)
        company_text = _candidate_company_from_cells(cell_texts)
        key = (company_text, attachment_url)
        if not company_text or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "row_index": len(rows) + 1,
                "source_tr_index": index,
                "candidate_company_text": company_text,
                "attachment_url": attachment_url,
                "attachment_text": _html_to_text(href_match.group("text")),
                "row_text": row_text,
            }
        )
    return rows


def _candidate_company_from_cells(cells: list[str]) -> str:
    for cell in cells:
        text = str(cell or "").strip()
        if not text or text in {"查看资料", "投标文件商务部分", "投标文件技术部分"}:
            continue
        if any(token in text for token in ("公司", "院", "集团", "联合体", "(主)", "（主）")):
            return text
    return ""


def _candidate_row_match_score(row: Mapping[str, Any], target_companies: list[str]) -> int:
    matched = _matched_companies(row, target_companies)
    if not matched:
        return 0
    score = len(matched) * 100
    if len(matched) == len(target_companies) and len(target_companies) > 1:
        score += 80
    return score


def _matched_companies(row: Mapping[str, Any], target_companies: list[str]) -> list[str]:
    row_text = _normalize_match_text(f"{row.get('candidate_company_text') or ''} {row.get('row_text') or ''}")
    matched: list[str] = []
    for company in target_companies:
        normalized = _normalize_match_text(company)
        if normalized and normalized in row_text:
            matched.append(company)
    return matched


def _target_companies(plan_project: Mapping[str, Any], stage4_items: list[Mapping[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for value in _list(plan_project.get("candidate_group_members")):
        candidates.append(str(value or ""))
    for item in stage4_items:
        for value in _list(item.get("candidate_group_members")):
            candidates.append(str(value or ""))
        candidates.append(str(item.get("candidate_company_name") or ""))
    if not candidates:
        candidates.extend(_split_companies(plan_project.get("candidate_company_text")))
    return _dedupe(_clean_company_name(value) for value in candidates if _clean_company_name(value))


def _flow08_discovery_context(*, project_name: str, project_id: str) -> dict[str, Any]:
    base_name = _base_guangzhou_project_name(project_name)
    project_code = _project_code_from_text(f"{project_id} {project_name}")
    variants = _dedupe(
        [
            project_code,
            project_name,
            base_name,
            _short_guangzhou_project_query(base_name),
        ]
    )
    filters = [
        "BACKTRACE_FLOW_CODE:04",
        f"BACKTRACE_PROJECT_NAME:{project_name}",
        f"BACKTRACE_BASE_PROJECT_NAME:{base_name}",
        *[f"BACKTRACE_QUERY_VARIANT:{variant}" for variant in variants if variant],
    ]
    return {
        "evaluation_document_kind": "bid_file_publicity",
        "selection_filters": filters,
        "target_flow_no": "08",
        "target_flow_code": "04",
    }


def _detail_html(detail: Mapping[str, Any], *, snapshot_reader: SnapshotReader | None) -> str:
    direct = str(detail.get("raw_html_optional") or detail.get("html_text_optional") or "")
    if direct:
        return direct
    snapshot_id = str(detail.get("snapshot_id_optional") or "")
    if not snapshot_id or snapshot_reader is None:
        return ""
    try:
        return snapshot_reader(snapshot_id).decode("utf-8", "ignore")
    except Exception:
        return ""


def _detail_summary(detail: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(detail.get("status") or ""),
        "http_status": detail.get("http_status"),
        "title": str(detail.get("title") or ""),
        "detail_url": str(detail.get("detail_url") or ""),
        "final_url": str(detail.get("final_url") or ""),
        "snapshot_id_optional": str(detail.get("snapshot_id_optional") or ""),
        "same_site_attachment_link_count": len(_list(detail.get("same_site_attachment_link_items"))),
        "attachment_discovery_taxonomy": _list(detail.get("attachment_discovery_taxonomy")),
        "degraded_reasons": _list(detail.get("degraded_reasons")),
        "failure_taxonomy": detail.get("failure_taxonomy"),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _attachment_fetch_summary(attachment: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(attachment.get("status") or ""),
        "content_type": str(attachment.get("content_type") or ""),
        "attachment_filename": str(attachment.get("attachment_filename") or ""),
        "byte_size": int(attachment.get("byte_size") or 0),
        "sha256": str(attachment.get("sha256") or ""),
        "snapshot_id_optional": str(attachment.get("snapshot_id_optional") or ""),
        "degraded_reasons": _list(attachment.get("degraded_reasons")),
        "attachment_failure_taxonomy": _list(attachment.get("attachment_failure_taxonomy")),
        "attachment_blocker_class": str(attachment.get("attachment_blocker_class") or ""),
        "attachment_blocker_reason": str(attachment.get("attachment_blocker_reason") or ""),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _discovery_summary(discovery: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "state": str(discovery.get("state") or ""),
        "endpoint": str(discovery.get("endpoint") or ""),
        "query_window": dict(discovery.get("query_window") or {}),
        "api_time_filter_state": str(discovery.get("api_time_filter_state") or ""),
        "trading_process_strategy": str(discovery.get("trading_process_strategy") or ""),
        "primary_trading_process": str(discovery.get("primary_trading_process") or ""),
        "attempted_pages": int(discovery.get("attempted_pages") or 0),
        "record_count": int(discovery.get("record_count") or 0),
        "item_count": len(_list(discovery.get("items"))),
        "process_attempts": [
            {
                "process_label": str(attempt.get("process_label") or ""),
                "trading_process": str(attempt.get("trading_process") or ""),
                "record_count": int(attempt.get("record_count") or 0),
                "accepted_item_count": int(attempt.get("accepted_item_count") or 0),
                "state": str(attempt.get("state") or ""),
                "failure_taxonomy": _list(attempt.get("failure_taxonomy")),
            }
            for attempt in _list(discovery.get("process_attempts"))
            if isinstance(attempt, Mapping)
        ][:12],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _design_survey_plan_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    project_table = manifest.get("project_table") if isinstance(manifest.get("project_table"), Mapping) else {}
    for record in _list(project_table.get("records")):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if project_id:
            index[project_id] = dict(record)
    return index


def _flow08_required_stage4_index_by_project(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in _list(manifest.get("items")):
        if not isinstance(record, Mapping):
            continue
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            continue
        if not (
            bool(record.get("flow_08_targeted_parse_required"))
            or str(record.get("supplement_after_execution_state") or "") == "FLOW_08_TARGETED_PARSE_REQUIRED"
        ):
            continue
        index.setdefault(project_id, {}).setdefault("items", []).append(dict(record))
    return index


def _optional_manifest(
    *,
    explicit_json: str | Path | None,
    root: str | Path | None,
    default_file_name: str,
) -> dict[str, Any]:
    path = Path(explicit_json) if explicit_json else (Path(root) / default_file_name if root else None)
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    return dict(manifest) if isinstance(manifest, Mapping) else {}


def _manifest_source_path(explicit_json: str | Path | None, root: str | Path | None, default_file_name: str) -> str:
    if explicit_json:
        return str(explicit_json)
    if root:
        return str(Path(root) / default_file_name)
    return ""


def _summary(
    records: list[Mapping[str, Any]],
    blocking_reasons: list[str],
    *,
    execute: bool,
    download_target_attachments: bool,
) -> dict[str, Any]:
    return {
        "project_count": len(records),
        "flow08_readback_state_counts": _counts(record.get("flow08_readback_state") for record in records),
        "discovery_state_counts": _counts(record.get("discovery_state") for record in records),
        "detail_fetch_state_counts": _counts(record.get("detail_fetch_state") for record in records),
        "target_attachment_match_state_counts": _counts(record.get("target_attachment_match_state") for record in records),
        "target_attachment_bound_project_count": sum(
            1
            for record in records
            if str(record.get("target_attachment_match_state") or "") == "TARGET_CANDIDATE_ATTACHMENT_BOUND"
        ),
        "target_attachment_fetched_project_count": sum(
            1
            for record in records
            if str(record.get("flow08_readback_state") or "") == FLOW08_TARGET_ATTACHMENT_FETCHED
        ),
        "execute_enabled": bool(execute),
        "download_target_attachments": bool(download_target_attachments),
        "download_enabled": bool(execute and download_target_attachments),
        "parse_enabled": False,
        "blocking_reasons": list(blocking_reasons),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _attachment_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    attachments = [
        attachment
        for record in records
        for attachment in _list(record.get("target_attachment_records"))
        if isinstance(attachment, Mapping)
    ]
    return {
        "target_attachment_record_count": len(attachments),
        "target_attachment_match_state_counts": _counts(
            attachment.get("target_attachment_match_state") for attachment in attachments
        ),
        "attachment_fetch_state_counts": _counts(attachment.get("attachment_fetch_state") for attachment in attachments),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _html_to_text(value: Any) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", str(value or ""), flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _base_guangzhou_project_name(value: Any) -> str:
    text = _normalize_public_title(value)
    for marker in (
        "中标候选人公示",
        "中标结果公告",
        "中标结果",
        "中标信息",
        "招标公告",
        "重新招标公告",
        "变更公告",
        "补充公告",
        "答疑公告",
        "澄清公告",
        "投标文件公开",
        "开标记录",
    ):
        text = text.replace(marker, "")
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _short_guangzhou_project_query(value: Any) -> str:
    text = _base_guangzhou_project_name(value)
    for marker in ("项目", "工程", "标段"):
        index = text.find(marker)
        if index >= 8:
            return text[: index + len(marker)]
    return text[:40]


def _normalize_public_title(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _project_code_from_text(value: Any) -> str:
    match = re.search(r"JG20\d{2}-\d{4,6}(?:-\d{3})?", str(value or ""), flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _split_companies(value: Any) -> list[str]:
    text = " ".join(str(value or "").split())
    marker_matches = list(
        re.finditer(
            r"(?:^|[,，;；、])\s*[（(]\s*(?:主|成)\s*[）)]\s*(?P<company>[^,，;；、]+)",
            text,
        )
    )
    rows = [match.group("company") for match in marker_matches] if marker_matches else re.split(r"[,，;；、]", text)
    return _dedupe(_clean_company_name(row) for row in rows if _clean_company_name(row))


def _clean_company_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^[（(]\s*(?:主|成)\s*[）)]\s*", "", text)
    text = re.sub(r"^(?:主|成)[：:]\s*", "", text)
    return text.strip(" ：:;；,，、")


def _normalize_match_text(value: Any) -> str:
    text = _clean_company_name(value)
    return re.sub(r"[\s（）()【】\[\];；,，、:：]", "", text)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _project_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _stable_id(prefix: str, *values: Any) -> str:
    return f"{prefix}-{_fingerprint(values)[:16].upper()}"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _dedupe(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _clip(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[: max(0, limit)]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build design-survey Flow08 targeted readback manifest.")
    parser.add_argument("--design-survey-adapter-plan-json", default="")
    parser.add_argument("--design-survey-adapter-plan-root", default="")
    parser.add_argument("--design-survey-stage4-execution-json", default="")
    parser.add_argument("--design-survey-stage4-execution-root", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--download-target-attachments", action="store_true")
    parser.add_argument("--output-json")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_design_survey_flow08_targeted_readback(
        design_survey_adapter_plan_json=args.design_survey_adapter_plan_json or None,
        design_survey_adapter_plan_root=args.design_survey_adapter_plan_root or None,
        design_survey_stage4_execution_json=args.design_survey_stage4_execution_json or None,
        design_survey_stage4_execution_root=args.design_survey_stage4_execution_root or None,
        output_root=args.output_root,
        project_ids=_parse_csv(args.project_ids),
        execute=bool(args.execute),
        download_target_attachments=bool(args.download_target_attachments),
    )
    output_json = (
        Path(args.output_json)
        if args.output_json
        else Path(args.output_root) / "design-survey-flow08-targeted-readback-v1.json"
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "output_root": str(args.output_root),
                    "safe_to_execute": result["safe_to_execute"],
                    "summary": result["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DESIGN_SURVEY_FLOW08_READBACK_KIND",
    "build_design_survey_flow08_targeted_readback",
]
