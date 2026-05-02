from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from storage.db import PersistedOperatorAction
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.repositories.operator_action_repo import OperatorActionRepository


REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID = "operator-real-candidate-stage2-captures"
REAL_CANDIDATE_STAGE2_CAPTURE_MODE = "REAL_PUBLIC_CANDIDATE_DETAIL_CAPTURE"
DEFAULT_DETAIL_CAPTURE_LIMIT = 5
DEFAULT_ATTACHMENT_CAPTURE_LIMIT = 2


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _candidate_key(candidate: Mapping[str, Any]) -> str:
    basis = str(candidate.get("candidate_key") or candidate.get("source_url") or candidate.get("notice_id") or "")
    return hashlib.sha1(basis.lower().encode("utf-8")).hexdigest()[:24]


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(text).split())


def _decode_snapshot_text(readback: Mapping[str, Any]) -> str:
    data = readback.get("bytes")
    if not isinstance(data, (bytes, bytearray)):
        return ""
    for encoding in ("utf-8", "gb18030"):
        try:
            return bytes(data).decode(encoding)
        except UnicodeDecodeError:
            continue
    return bytes(data).decode("utf-8", errors="replace")


def _parser_fields_by_name(parser_carrier: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for field in list(parser_carrier.get("parsed_fields", []) or []):
        if not isinstance(field, Mapping):
            continue
        name = str(field.get("field_name") or "")
        if name and name not in fields:
            fields[name] = dict(field)
    return fields


def _field_value(fields: Mapping[str, Mapping[str, Any]], *names: str) -> str:
    for name in names:
        field = fields.get(name)
        if not field:
            continue
        value = str(field.get("field_value_optional") or "").strip()
        if value:
            return value
    return ""


def _extract_amount(text: str) -> tuple[float | None, str]:
    normalized = text.replace(",", "")
    labeled_patterns = (
        r"(?:中标|成交|预算|采购|合同|估算|招标控制价|最高限价)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元)\s*(?:人民币|中标|成交|预算|合同|估算)",
    )
    for pattern in labeled_patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        number = _as_float(match.group(1))
        if number is None:
            continue
        unit = match.group(2)
        return (number * 10000 if unit in {"万", "万元"} else number), "DETAIL_TEXT"
    return None, "DETAIL_TEXT_NOT_FOUND"


def _infer_notice_stage(text: str, fallback: str) -> str:
    if any(token in text for token in ("中标候选人", "成交候选人", "候选人公示")):
        return "candidate_notice"
    if any(token in text for token in ("中标公告", "成交公告", "结果公告", "中标结果", "成交结果")):
        return "award_result"
    if any(token in text for token in ("更正公告", "变更公告", "澄清公告")):
        return "correction_notice"
    if any(token in text for token in ("招标公告", "采购公告", "竞争性谈判公告", "磋商公告")):
        return "tender_notice"
    return str(fallback or "procurement_notice")


def _extract_candidate_company(text: str) -> tuple[str, str]:
    patterns = (
        r"(?:中标|成交)\s*(?:供应商|单位|人|候选人)(?:名称)?[:：\s]+([^，。,；;\n\r]{2,80})",
        r"第一(?:中标|成交)?候选人[:：\s]+([^，。,；;\n\r]{2,80})",
        r"(?:供应商名称|中标人名称|成交人名称)[:：\s]+([^，。,；;\n\r]{2,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = _clean_company_value(_clean_text(match.group(1)))
        if value:
            return value, "DETAIL_TEXT"
    return "", "DETAIL_TEXT_NOT_FOUND"


def _clean_company_value(value: str) -> str:
    text = value.strip()
    text = re.split(
        r"\s+(?:中标|成交|预算|采购|合同|公告|附件|金额|项目名称|采购人|供应商地址|地址)",
        text,
        maxsplit=1,
    )[0]
    text = re.split(r"(?:中标|成交)[（(]", text, maxsplit=1)[0]
    return text.strip(" ：:，,；;。")


def _extract_deadline(text: str) -> tuple[str, str]:
    date_pattern = (
        r"(\d{4}\s*(?:-|/|年)\s*\d{1,2}\s*(?:-|/|月)\s*\d{1,2}(?:\s*日)?"
        r"(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?)"
    )
    patterns = (
        rf"(?:异议|质疑|投诉|答疑|澄清)[^。；;\n\r]{{0,20}}?(?:截止|结束)(?:时间)?[:：\s]*{date_pattern}",
        rf"公告(?:质疑|答疑|异议|投诉)[^。；;\n\r]{{0,10}}?(?:截止|结束)(?:时间)?[:：\s]*{date_pattern}",
        rf"公示[^。；;\n\r]{{0,20}}?(?:截止|结束|期至)(?:时间)?[:：\s]*{date_pattern}",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        context = _clean_text(match.group(0))
        if "发布时间" in context or "发布日期" in context:
            continue
        raw = _clean_text(match.group(1))
        return _normalize_date_to_iso_end_of_day(raw) or raw, "DETAIL_TEXT"
    return "", "DETAIL_TEXT_NOT_FOUND"


def _normalize_date_to_iso_end_of_day(value: str) -> str:
    match = re.search(
        r"(\d{4})\s*(?:-|/|年)\s*(\d{1,2})\s*(?:-|/|月)\s*(\d{1,2})(?:\s*日)?"
        r"(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?",
        value,
    )
    if not match:
        return ""
    year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    hour = int(match.group(4)) if match.group(4) else 23
    minute = int(match.group(5)) if match.group(5) else 59
    second = int(match.group(6)) if match.group(6) else 59
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}+08:00"


def _candidate_key_fields(candidate: Mapping[str, Any]) -> list[str]:
    fields: set[str] = set()
    existing = candidate.get("key_fields_present")
    if isinstance(existing, list):
        fields.update(str(item) for item in existing if item)
    elif isinstance(existing, str):
        fields.update(item.strip() for item in existing.split(",") if item.strip())
    for key in ("project_name", "notice_stage", "candidate_company"):
        if candidate.get(key):
            fields.add(key)
    return sorted(fields)


class RealCandidateStage2CaptureRepository:
    def __init__(self, *, repository: OperatorActionRepository | None = None) -> None:
        self.repository = repository or OperatorActionRepository()

    def persist_capture(
        self,
        *,
        candidate: Mapping[str, Any],
        capture: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        candidate_key = str(candidate.get("candidate_key") or _candidate_key(candidate))
        snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
        status = str(capture.get("detail_capture_status") or "UNKNOWN")
        event_id = f"REAL-CANDIDATE-STAGE2-{candidate_key}-{hashlib.sha1(now.encode('utf-8')).hexdigest()[:8]}".replace(":", "").replace("+", "")
        action = PersistedOperatorAction(
            action_event_id=event_id,
            work_item_id=REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID,
            stage_scope=2,
            action_id="operator_real_candidate_stage2_detail_capture",
            button_flow_id="owner_console_real_candidate_stage2_capture",
            action_state=status,
            resulting_assignment_lifecycle_state=None,
            requested_by_role="single_operator",
            requested_by="卡卡罗特",
            assigned_owner_role="single_operator",
            assigned_owner="卡卡罗特",
            reviewer_role="single_operator",
            reviewer="卡卡罗特",
            reason="real_candidate_detail_snapshot_and_stage3_parse",
            object_refs={
                "candidate_key": candidate_key,
                "project_id": str(candidate.get("project_id") or ""),
                "project_name": str(candidate.get("project_name") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "source_profile_id": str(candidate.get("source_profile_id") or ""),
                "detail_snapshot_id": snapshot_id,
                "detail_capture_status": status,
                "stage3_parse_state": str(capture.get("stage3_parse_state") or ""),
                "attachment_link_count": str(capture.get("attachment_link_count") or 0),
                "attachment_snapshot_count": str(capture.get("attachment_snapshot_count") or 0),
                "capture_json": _json_text(capture),
            },
            trace_refs={
                "operator_console_route": "/operator-console/autonomous-opportunity-search",
                "stage2_capture_catalog_path": "/operator-console/real-candidate-stage2-captures",
                "snapshot_readback_path": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else "",
            },
            audit_refs={
                "internal_only": "true",
                "allowlisted_same_site_detail_capture": "true",
                "real_provider_call_enabled": "false",
            },
            requested_at=now,
            completed_at=now,
        )
        self.repository.append(action)
        return self._capture_action_payload(action)

    def list_captures(self, *, limit: int = 100) -> dict[str, Any]:
        actions = self.repository.list(work_item_id=REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID)
        rows = [self._capture_action_payload(action) for action in actions]
        rows.sort(key=lambda row: str(row.get("captured_at") or ""), reverse=True)
        latest_by_candidate: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("candidate_key") or "")
            if key and key not in latest_by_candidate:
                latest_by_candidate[key] = row
        latest = list(latest_by_candidate.values())[:limit]
        return {
            "surface_id": "operator_real_candidate_stage2_capture_catalog",
            "repository_backed_readback": True,
            "data_source": "OperatorActionRepository",
            "capture_mode": REAL_CANDIDATE_STAGE2_CAPTURE_MODE,
            "capture_count": len(latest),
            "raw_capture_event_count": len(rows),
            "duplicate_collapsed_count": max(len(rows) - len(latest), 0),
            "captures": latest,
            "manual_url_picker_primary_flow": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
            "customer_download_enabled": False,
        }

    def _capture_action_payload(self, action: PersistedOperatorAction) -> dict[str, Any]:
        refs = dict(action.object_refs)
        capture = dict(_json_value(refs.get("capture_json"), {}))
        capture.update(
            {
                "capture_event_id": action.action_event_id,
                "candidate_key": refs.get("candidate_key") or capture.get("candidate_key"),
                "project_id": refs.get("project_id") or capture.get("project_id"),
                "project_name": refs.get("project_name") or capture.get("project_name"),
                "source_url": refs.get("source_url") or capture.get("source_url"),
                "source_profile_id": refs.get("source_profile_id") or capture.get("source_profile_id"),
                "detail_snapshot_id_optional": refs.get("detail_snapshot_id") or capture.get("detail_snapshot_id_optional"),
                "detail_capture_status": refs.get("detail_capture_status") or action.action_state,
                "stage3_parse_state": refs.get("stage3_parse_state") or capture.get("stage3_parse_state"),
                "attachment_link_count": _as_int(refs.get("attachment_link_count"), 0),
                "attachment_snapshot_count": _as_int(refs.get("attachment_snapshot_count"), 0),
                "captured_at": action.requested_at,
                "repository_backed": True,
            }
        )
        return capture


class RealCandidateStage2CaptureService:
    def __init__(
        self,
        *,
        stage2_service: Stage2Service | None = None,
        stage3_service: Stage3Service | None = None,
        object_repository: ObjectStorageRepository | None = None,
        repository: RealCandidateStage2CaptureRepository | None = None,
    ) -> None:
        self.object_repository = object_repository or ObjectStorageRepository()
        self.stage2_service = stage2_service or Stage2Service()
        self.stage3_service = stage3_service or Stage3Service()
        self.repository = repository or RealCandidateStage2CaptureRepository()

    def capture_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        now: str | None = None,
        detail_capture_limit: int = DEFAULT_DETAIL_CAPTURE_LIMIT,
        attachment_capture_limit: int = DEFAULT_ATTACHMENT_CAPTURE_LIMIT,
    ) -> dict[str, Any]:
        captured_at = now or utc_now_iso()
        limit = max(0, detail_capture_limit)
        attachment_limit = max(0, attachment_capture_limit)
        enriched: list[dict[str, Any]] = []
        captures: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        for index, candidate in enumerate(candidates):
            row = dict(candidate)
            row.setdefault("candidate_key", _candidate_key(row))
            if index < limit:
                capture = self.capture_candidate(
                    row,
                    now=captured_at,
                    attachment_capture_limit=attachment_limit,
                )
                captures.append(capture)
                by_key[str(row.get("candidate_key") or "")] = capture
                row = self._enrich_candidate(row, capture)
            enriched.append(row)
        return {
            "surface_id": "operator_real_candidate_stage2_capture",
            "capture_mode": REAL_CANDIDATE_STAGE2_CAPTURE_MODE,
            "capture_limit": limit,
            "attachment_capture_limit": attachment_limit,
            "input_candidate_count": len(candidates),
            "detail_capture_attempted_count": len(captures),
            "detail_snapshot_count": sum(1 for item in captures if item.get("detail_snapshot_id_optional")),
            "stage3_parse_success_count": sum(1 for item in captures if str(item.get("stage3_parse_state") or "").startswith("PARSED")),
            "attachment_link_count": sum(_as_int(item.get("attachment_link_count"), 0) for item in captures),
            "attachment_capture_attempted_count": sum(_as_int(item.get("attachment_capture_attempted_count"), 0) for item in captures),
            "attachment_snapshot_count": sum(_as_int(item.get("attachment_snapshot_count"), 0) for item in captures),
            "captures": captures,
            "capture_by_candidate_key": by_key,
            "enriched_candidates": enriched,
            "repository_backed_readback": True,
            "stage2_detail_capture_enabled": True,
            "stage3_parser_readback_enabled": True,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
        }

    def capture_candidate(
        self,
        candidate: Mapping[str, Any],
        *,
        now: str | None = None,
        attachment_capture_limit: int = DEFAULT_ATTACHMENT_CAPTURE_LIMIT,
    ) -> dict[str, Any]:
        captured_at = now or utc_now_iso()
        candidate_key = str(candidate.get("candidate_key") or _candidate_key(candidate))
        source_url = str(candidate.get("source_url") or "").strip()
        profile_id = str(candidate.get("source_profile_id") or "").strip()
        base_capture = {
            "candidate_key": candidate_key,
            "project_id": str(candidate.get("project_id") or ""),
            "project_name": str(candidate.get("project_name") or ""),
            "source_url": source_url,
            "source_profile_id": profile_id,
            "capture_mode": REAL_CANDIDATE_STAGE2_CAPTURE_MODE,
            "captured_at": captured_at,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
        }
        if not source_url or not profile_id:
            capture = {
                **base_capture,
                "detail_capture_status": "SKIPPED",
                "detail_capture_failure_reasons": ["source_url_or_profile_id_missing"],
                "detail_snapshot_id_optional": "",
                "stage3_parse_state": "NOT_RUN",
                "attachment_link_count": 0,
                "attachment_capture_attempted_count": 0,
                "attachment_snapshot_count": 0,
                "attachment_captures": [],
            }
            capture["capture_record"] = self.repository.persist_capture(candidate=candidate, capture=capture, now=captured_at)
            return capture

        try:
            detail_carrier = dict(
                self.stage2_service.fetch_real_public_candidate_detail_url(
                    source_url,
                    profile_id=profile_id,
                    repository=self.object_repository,
                    lineage_refs={
                        "candidate_key": candidate_key,
                        "project_id": str(candidate.get("project_id") or ""),
                        "notice_id": str(candidate.get("notice_id") or ""),
                        "source_candidate_mode": str(candidate.get("source_candidate_mode") or ""),
                    },
                )
            )
        except Exception as exc:
            capture = {
                **base_capture,
                "detail_capture_status": "FAILED_CLOSED",
                "detail_capture_failure_reasons": [str(exc)],
                "detail_snapshot_id_optional": "",
                "stage3_parse_state": "NOT_RUN",
                "attachment_link_count": 0,
                "attachment_capture_attempted_count": 0,
                "attachment_snapshot_count": 0,
                "attachment_captures": [],
            }
            capture["capture_record"] = self.repository.persist_capture(candidate=candidate, capture=capture, now=captured_at)
            return capture

        snapshot_id = str(detail_carrier.get("snapshot_id_optional") or "")
        parser_carrier: dict[str, Any] = {}
        readback_text = ""
        if snapshot_id:
            replay = self.object_repository.replay_snapshot(snapshot_id)
            readback_text = _decode_snapshot_text(replay)
            parser_carrier = dict(
                self.stage3_service.parse_raw_snapshot(snapshot_id, repository=self.object_repository)
            )
        detail_fields = self._detail_fields(
            candidate=candidate,
            detail_carrier=detail_carrier,
            parser_carrier=parser_carrier,
            readback_text=readback_text,
        )
        attachment_link_items = list(detail_carrier.get("same_site_attachment_link_items", []) or [])
        attachment_captures = self._capture_same_site_attachments(
            attachment_link_items,
            candidate=candidate,
            candidate_key=candidate_key,
            parent_profile_id=profile_id,
            detail_page_url=source_url,
            detail_snapshot_id=snapshot_id,
            limit=attachment_capture_limit,
        )
        capture = {
            **base_capture,
            "detail_capture_status": str(detail_carrier.get("status") or "UNKNOWN"),
            "detail_snapshot_id_optional": snapshot_id,
            "detail_fetch_id": str(detail_carrier.get("detail_fetch_id") or ""),
            "detail_title": str(detail_carrier.get("title") or ""),
            "detail_content_type": str(detail_carrier.get("content_type") or ""),
            "detail_byte_size": _as_int(detail_carrier.get("byte_size"), 0),
            "detail_degraded_reasons": list(detail_carrier.get("degraded_reasons", []) or []),
            "stage3_parse_state": str(parser_carrier.get("parse_state") or "NOT_RUN"),
            "stage3_parse_error_taxonomy": list(parser_carrier.get("parse_error_taxonomy", []) or []),
            "parsed_field_count": len(parser_carrier.get("parsed_fields", []) or []),
            "detail_fields": detail_fields,
            "attachment_link_count": len(attachment_link_items),
            "same_site_attachment_link_items": attachment_link_items,
            "attachment_capture_attempted_count": len(attachment_captures),
            "attachment_snapshot_count": sum(1 for item in attachment_captures if item.get("attachment_snapshot_id_optional")),
            "attachment_captures": attachment_captures,
            "snapshot_readback_path_optional": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else "",
        }
        capture["capture_record"] = self.repository.persist_capture(candidate=candidate, capture=capture, now=captured_at)
        return capture

    def _capture_same_site_attachments(
        self,
        attachment_link_items: list[Any],
        *,
        candidate: Mapping[str, Any],
        candidate_key: str,
        parent_profile_id: str,
        detail_page_url: str,
        detail_snapshot_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        captures: list[dict[str, Any]] = []
        for item in attachment_link_items[: max(0, limit)]:
            link = dict(item or {}) if isinstance(item, Mapping) else {"url": str(item or "")}
            attachment_url = str(link.get("url") or "").strip()
            if not attachment_url:
                continue
            try:
                carrier = dict(
                    self.stage2_service.fetch_real_public_same_site_attachment_url(
                        attachment_url,
                        parent_profile_id=parent_profile_id,
                        repository=self.object_repository,
                        detail_page_url=detail_page_url,
                        lineage_refs={
                            "candidate_key": candidate_key,
                            "project_id": str(candidate.get("project_id") or ""),
                            "notice_id": str(candidate.get("notice_id") or ""),
                            "detail_snapshot_id": detail_snapshot_id,
                        },
                    )
                )
            except Exception as exc:
                captures.append(
                    {
                        "attachment_url": attachment_url,
                        "attachment_link_text": str(link.get("text") or ""),
                        "attachment_capture_status": "FAILED_CLOSED",
                        "attachment_snapshot_id_optional": "",
                        "attachment_degraded_reasons": [str(exc)],
                        "review_required": True,
                    }
                )
                continue
            captures.append(
                {
                    "attachment_url": attachment_url,
                    "attachment_link_text": str(link.get("text") or ""),
                    "attachment_capture_status": str(carrier.get("status") or "UNKNOWN"),
                    "attachment_snapshot_id_optional": str(carrier.get("snapshot_id_optional") or ""),
                    "attachment_filename": str(carrier.get("attachment_filename") or ""),
                    "content_type": str(carrier.get("content_type") or ""),
                    "byte_size": _as_int(carrier.get("byte_size"), 0),
                    "attachment_degraded_reasons": list(carrier.get("degraded_reasons", []) or []),
                    "review_required": bool(carrier.get("review_required")),
                }
            )
        return captures

    def _detail_fields(
        self,
        *,
        candidate: Mapping[str, Any],
        detail_carrier: Mapping[str, Any],
        parser_carrier: Mapping[str, Any],
        readback_text: str,
    ) -> dict[str, Any]:
        fields = _parser_fields_by_name(parser_carrier)
        text = _clean_text(readback_text)
        title = (
            _field_value(fields, "project_name", "announcement_title")
            or str(detail_carrier.get("title") or "")
            or str(candidate.get("project_name") or "")
        )
        amount, amount_state = _extract_amount(text)
        candidate_company, candidate_company_state = _extract_candidate_company(text)
        deadline, deadline_state = _extract_deadline(text)
        notice_stage = _infer_notice_stage(f"{title} {text[:2000]}", str(candidate.get("notice_stage") or ""))
        return {
            "project_name": title,
            "notice_stage": notice_stage,
            "amount": amount,
            "amount_parse_state": amount_state,
            "candidate_company": candidate_company,
            "candidate_company_parse_state": candidate_company_state,
            "objection_deadline_at_optional": deadline,
            "objection_deadline_parse_state": deadline_state,
            "parser_project_name": _field_value(fields, "project_name"),
            "parser_announcement_title": _field_value(fields, "announcement_title"),
            "parser_announcement_date": _field_value(fields, "announcement_date"),
        }

    def _enrich_candidate(self, candidate: Mapping[str, Any], capture: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(candidate)
        fields = dict(capture.get("detail_fields", {}) or {})
        detail_snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
        row["stage2_detail_capture_state"] = str(capture.get("detail_capture_status") or "")
        row["stage2_detail_snapshot_id_optional"] = detail_snapshot_id
        row["stage2_detail_capture_event_id_optional"] = str(
            dict(capture.get("capture_record", {}) or {}).get("capture_event_id") or ""
        )
        row["stage3_detail_parse_state"] = str(capture.get("stage3_parse_state") or "")
        row["stage2_attachment_link_count"] = _as_int(capture.get("attachment_link_count"), 0)
        row["same_site_attachment_link_items"] = list(capture.get("same_site_attachment_link_items", []) or [])
        attachment_snapshot_ids = [
            str(item.get("attachment_snapshot_id_optional") or "")
            for item in list(capture.get("attachment_captures", []) or [])
            if str(item.get("attachment_snapshot_id_optional") or "")
        ]
        row["stage2_attachment_snapshot_count"] = len(attachment_snapshot_ids)
        row["stage2_attachment_snapshot_ids"] = attachment_snapshot_ids
        row["stage2_attachment_captures"] = list(capture.get("attachment_captures", []) or [])
        if fields.get("project_name"):
            row["project_name"] = str(fields["project_name"])
        if fields.get("notice_stage"):
            row["notice_stage"] = str(fields["notice_stage"])
        if fields.get("amount") is not None:
            row["amount"] = fields["amount"]
            row["estimated_amount"] = fields["amount"]
            row["amount_parse_state"] = fields.get("amount_parse_state") or "DETAIL_TEXT"
        elif row.get("amount") in (None, ""):
            row["amount_parse_state"] = fields.get("amount_parse_state") or row.get("amount_parse_state") or "DETAIL_TEXT_NOT_FOUND"
        if fields.get("candidate_company"):
            row["candidate_company"] = str(fields["candidate_company"])
            row["candidate_company_parse_state"] = fields.get("candidate_company_parse_state") or "DETAIL_TEXT"
        else:
            row["candidate_company_parse_state"] = fields.get("candidate_company_parse_state") or "DETAIL_TEXT_NOT_FOUND"
        if fields.get("objection_deadline_at_optional"):
            row["objection_deadline_at_optional"] = str(fields["objection_deadline_at_optional"])
        if detail_snapshot_id:
            row["source_document_ref"] = detail_snapshot_id
            row["source_slice_ref"] = detail_snapshot_id
            row["real_snapshot_ids"] = [
                item
                for item in (
                    str(row.get("snapshot_id_optional") or ""),
                    detail_snapshot_id,
                    *attachment_snapshot_ids,
                )
                if item
            ]
        if row.get("candidate_company") and _as_int(row.get("candidate_count"), 0) < 1:
            row["candidate_count"] = 1
            row["competitor_count"] = max(_as_int(row.get("competitor_count"), 0), 1)
        row["key_fields_present"] = _candidate_key_fields(row)
        row["sellability_evidence_state"] = (
            "REAL_DETAIL_AND_ATTACHMENT_SNAPSHOTS_PARSED_NEEDS_STAGE4_TO_STAGE9"
            if detail_snapshot_id and attachment_snapshot_ids
            else "REAL_DETAIL_SNAPSHOT_PARSED_NEEDS_STAGE4_TO_STAGE9"
            if detail_snapshot_id
            else "REAL_LIST_PAGE_CANDIDATE_NEEDS_DETAIL_CAPTURE"
        )
        row["truth_boundary"] = (
            "真实详情页和同站附件快照已保存；客户可售前仍需 Stage4-9 消费快照并完成证据回链。"
            if detail_snapshot_id and attachment_snapshot_ids
            else
            "真实详情页快照已保存并完成 Stage3 读回；客户可售前仍需 Stage4-9 消费该快照并完成证据回链。"
            if detail_snapshot_id
            else "真实列表页候选已入库；详情页快照未完成，不能形成客户可售证据。"
        )
        return row


def list_real_candidate_stage2_captures(*, limit: int = 100) -> dict[str, Any]:
    return RealCandidateStage2CaptureRepository().list_captures(limit=limit)


__all__ = [
    "DEFAULT_DETAIL_CAPTURE_LIMIT",
    "DEFAULT_ATTACHMENT_CAPTURE_LIMIT",
    "REAL_CANDIDATE_STAGE2_CAPTURE_MODE",
    "REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID",
    "RealCandidateStage2CaptureRepository",
    "RealCandidateStage2CaptureService",
    "list_real_candidate_stage2_captures",
]
