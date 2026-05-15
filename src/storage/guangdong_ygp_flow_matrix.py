from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


GUANGDONG_YGP_FLOW_MATRIX_KIND = "guangdong_ygp_flow_matrix_v1_manifest"
GUANGDONG_YGP_FLOW_MATRIX_VERSION = 1
GUANGDONG_YGP_FLOW_MATRIX_ADAPTER_ID = "guangdong-ygp-flow-matrix-v1-builder"

DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples/p13b-original-notice-backtrace-v1-smoke")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/guangdong-ygp-flow-matrix-v1")

YGP_HOST = "ygp.gdzwfw.gov.cn"
YGP_API_ROOT = "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis"
FORBIDDEN_TERMS = ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人")

HttpGetter = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]

FLOW_MODULES = (
    {"flow_no": "01", "flow_title": "招标计划/采购意向", "document_kind": "bid_plan"},
    {"flow_no": "02", "flow_title": "招标文件公示/采购需求", "document_kind": "tender_file_publicity"},
    {"flow_no": "03", "flow_title": "招标公告/关联公告", "document_kind": "tender_file"},
    {"flow_no": "04", "flow_title": "澄清答疑/更正公告", "document_kind": "clarification_notice"},
    {"flow_no": "05", "flow_title": "开标信息", "document_kind": "opening_info"},
    {"flow_no": "06", "flow_title": "资审结果公示", "document_kind": "qualification_review_result"},
    {"flow_no": "07", "flow_title": "中标候选人公示", "document_kind": "candidate_notice"},
    {"flow_no": "08", "flow_title": "投标(资格预审申请)文件公开", "document_kind": "bid_file_publicity"},
    {"flow_no": "09", "flow_title": "中标结果公示/公告", "document_kind": "award_result"},
    {"flow_no": "10", "flow_title": "中标信息", "document_kind": "award_info"},
    {"flow_no": "11", "flow_title": "合同信息公开", "document_kind": "contract_public_info"},
    {"flow_no": "12", "flow_title": "项目异常", "document_kind": "project_exception"},
)


def build_guangdong_ygp_flow_matrix(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    input_json: str | Path | None = None,
    source_urls: list[str] | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_public_query: bool = False,
    max_live_source_urls: int | None = None,
    http_getter: HttpGetter | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_dir = Path(input_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(input_json) if input_json else _default_input_json(in_dir)
    blocking_reasons: list[str] = []
    source_payload = _load_json(source_path, blocking_reasons, "ygp_flow_matrix_input_missing") if source_path else {}
    urls = _dedupe([*(source_urls or []), *_source_urls_from_input(_source_manifest(source_payload))])
    task_records = _task_records_from_urls(urls, created_at=created)
    execution_mode = "LIVE_PUBLIC_QUERY_ATTEMPTED" if enable_live_public_query else "PLAN_ONLY_NOT_EXECUTED"
    project_records, flow_matrix_records, detail_readback_records = _execute_tasks(
        task_records,
        created_at=created,
        enable_live_public_query=enable_live_public_query,
        max_live_source_urls=max_live_source_urls,
        http_getter=http_getter,
    )
    summary = _summary(
        task_records=task_records,
        project_records=project_records,
        flow_matrix_records=flow_matrix_records,
        detail_readback_records=detail_readback_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GUANGDONG_YGP_FLOW_MATRIX_VERSION,
        "manifest_kind": GUANGDONG_YGP_FLOW_MATRIX_KIND,
        "adapter_id": GUANGDONG_YGP_FLOW_MATRIX_ADAPTER_ID,
        "pipeline_stage": "GuangdongYgpFlowMatrixV1",
        "manifest_id": f"GUANGDONG-YGP-FLOW-MATRIX-{_fingerprint({'summary': summary, 'tasks': task_records})[:16]}",
        "created_at": created,
        "source_input_root": str(in_dir),
        "source_input_json": str(source_path or ""),
        "execution_mode": execution_mode,
        "live_public_query_enabled": bool(enable_live_public_query),
        "max_live_source_urls": max_live_source_urls,
        "flow_modules": list(FLOW_MODULES),
        "ygp_flow_matrix_task_records": task_records,
        "ygp_project_records": project_records,
        "ygp_flow_matrix_records": flow_matrix_records,
        "ygp_detail_readback_records": detail_readback_records,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "parse_enabled": False,
            "stage4_live_provider_enabled": False,
            "llm_execution_enabled": False,
            "network_enabled": bool(enable_live_public_query),
            "manifest_stores_raw_html_or_blob": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "not_guangzhou_primary_source": True,
            "guangdong_city_adapter_base_capability": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "guangdong_ygp_flow_matrix_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
        "safe_to_execute": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    forbidden_hits = [term for term in FORBIDDEN_TERMS if term in text]
    if forbidden_hits:
        result["safe_to_execute"] = False
        result["blocking_reasons"] = [
            *blocking_reasons,
            *[f"forbidden_report_term:{term}" for term in forbidden_hits],
        ]
        result["summary"]["forbidden_term_scan_state"] = "FAIL"
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        result["summary"]["forbidden_term_scan_state"] = "PASS"
        result["manifest"]["summary"]["forbidden_term_scan_state"] = "PASS"
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "guangdong-ygp-flow-matrix-v1.json").write_text(text, encoding="utf-8")
    return result


def _default_input_json(root: Path) -> Path | None:
    for name in (
        "original-notice-backtrace-v1.json",
        "company-history-overlap-triage-v1.json",
        "ygp-original-readback-v1.json",
    ):
        path = root / name
        if path.exists():
            return path
    return root / "original-notice-backtrace-v1.json"


def _source_urls_from_input(source_manifest: Mapping[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in (
        "original_notice_task_records",
        "original_notice_fetch_records",
        "original_notice_extraction_records",
        "manual_original_url_backtrace_table",
        "bid_show_records",
        "ygp_original_readback_records",
    ):
        for record in _list(source_manifest.get(key)):
            if not isinstance(record, Mapping):
                continue
            for field in ("original_notice_url", "source_url"):
                url = str(record.get(field) or "").strip()
                if YGP_HOST in url.lower():
                    urls.append(url)
    return _dedupe(urls)


def _task_records_from_urls(urls: list[str], *, created_at: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for url in urls:
        if YGP_HOST not in url.lower():
            continue
        tasks.append(
            {
                "ygp_flow_matrix_task_id": _stable_id("YGP-FLOW-MATRIX", url),
                "source_url": url,
                "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                "flow_matrix_state": "PLAN_ONLY_NOT_EXECUTED",
                "created_at": created_at,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return tasks


def _execute_tasks(
    tasks: list[dict[str, Any]],
    *,
    created_at: str,
    enable_live_public_query: bool,
    max_live_source_urls: int | None,
    http_getter: HttpGetter | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not enable_live_public_query:
        return [], [], []
    getter = http_getter or _default_http_getter
    project_records: list[dict[str, Any]] = []
    flow_matrix_records: list[dict[str, Any]] = []
    detail_records: list[dict[str, Any]] = []
    attempted = 0
    for task in tasks:
        if max_live_source_urls is not None and attempted >= max_live_source_urls:
            project_records.append(
                {
                    **task,
                    "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                    "project_readback_state": "YGP_FLOW_MATRIX_BLOCKED",
                    "blocker_taxonomy": ["max_live_source_urls_deferred"],
                    "created_at": created_at,
                }
            )
            continue
        attempted += 1
        project, flow_rows, details = _execute_one_task(task, getter=getter, created_at=created_at)
        project_records.append(project)
        flow_matrix_records.extend(flow_rows)
        detail_records.extend(details)
    return project_records, flow_matrix_records, detail_records


def _execute_one_task(task: Mapping[str, Any], *, getter: HttpGetter, created_at: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    source_url = str(task.get("source_url") or "")
    route_attempts: list[dict[str, Any]] = []
    resolved = _resolve_project_route(source_url, getter=getter, task=task, route_attempts=route_attempts)
    if not resolved:
        project = _project_blocked(task, route_attempts=route_attempts, blockers=["ygp_project_route_unresolved"], created_at=created_at)
        return project, [], []
    node_list_url = _node_list_url(resolved)
    node_response = _fetch_url(node_list_url, getter, route="ygp_node_list_fetch", task=task)
    route_attempts.append(node_response["attempt"])
    node_payload = _json_payload(node_response["body"])
    if node_response["status_code"] != 200 or not isinstance(node_payload.get("data"), list):
        blockers = _blockers_from_response(
            status=node_response["status_code"],
            body_probe=node_response["body"][:300],
            error=node_response["error"],
            prefix="ygp_node_list",
        ) or ["ygp_node_list_payload_missing"]
        project = _project_blocked(task, route_attempts=route_attempts, blockers=blockers, created_at=created_at)
        return project, [], []

    nodes = [node for node in node_payload.get("data", []) if isinstance(node, Mapping)]
    flow_rows = _flow_rows_from_nodes(task, resolved=resolved, nodes=nodes, created_at=created_at)
    detail_records: list[dict[str, Any]] = []
    for row in flow_rows:
        if str(row.get("flow_item_state") or "") != "YGP_FLOW_ITEM_PRESENT":
            continue
        detail = _fetch_detail_for_flow(row, resolved=resolved, getter=getter, created_at=created_at)
        detail_records.append(detail)
    project = {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "project_readback_state": "YGP_FLOW_MATRIX_READY",
        "resolved_project_route": resolved,
        "node_list_url": node_list_url,
        "node_count": len(nodes),
        "present_flow_count": len({row.get("flow_no") for row in flow_rows if row.get("flow_item_state") == "YGP_FLOW_ITEM_PRESENT"}),
        "detail_readback_ready_count": sum(1 for record in detail_records if record.get("detail_readback_state") == "YGP_DETAIL_READBACK_READY"),
        "route_attempts": route_attempts,
        "blocker_taxonomy": [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    return project, flow_rows, detail_records


def _resolve_project_route(
    source_url: str,
    *,
    getter: HttpGetter,
    task: Mapping[str, Any],
    route_attempts: list[dict[str, Any]],
) -> dict[str, str] | None:
    parsed = urllib.parse.urlparse(source_url)
    if parsed.fragment:
        resolved = _route_from_hash_url(source_url)
        if resolved:
            return resolved
    if "/url-mapping/" in parsed.path:
        response = _fetch_url(source_url, getter, route="ygp_url_mapping_no_redirect", task=task, no_redirect=True)
        route_attempts.append(response["attempt"])
        location = response["headers"].get("Location") or response["headers"].get("location") or ""
        if location:
            return _route_from_hash_url(urllib.parse.urljoin(source_url, location))
        if response["url"] != source_url and urllib.parse.urlparse(response["url"]).fragment:
            return _route_from_hash_url(response["url"])
    return None


def _route_from_hash_url(url: str) -> dict[str, str] | None:
    parsed = urllib.parse.urlparse(url)
    fragment = parsed.fragment or ""
    if "?" not in fragment:
        return None
    hash_path, query = fragment.split("?", 1)
    params = {key: values[-1] for key, values in urllib.parse.parse_qs(query).items() if values}
    path_parts = [part for part in hash_path.split("/") if part]
    trading_type = params.get("tradingType") or ""
    if not trading_type and len(path_parts) >= 5:
        trading_type = path_parts[-1]
    version = ""
    for part in path_parts:
        if re.fullmatch(r"v\d+", part):
            version = part
    required = ("siteCode", "projectCode", "bizCode")
    if not all(params.get(key) for key in required):
        return None
    return {
        "source_hash_url": url,
        "siteCode": params.get("siteCode", ""),
        "projectCode": params.get("projectCode", ""),
        "bizCode": params.get("bizCode", ""),
        "noticeId": params.get("noticeId", ""),
        "nodeId": params.get("nodeId", ""),
        "publishDate": params.get("publishDate", ""),
        "tradingType": trading_type,
        "version": version or "v3",
        "source": params.get("source", ""),
        "titleDetails": params.get("titleDetails", ""),
    }


def _node_list_url(route: Mapping[str, str]) -> str:
    query = urllib.parse.urlencode(
        {
            "siteCode": route.get("siteCode", ""),
            "tradingType": route.get("tradingType", ""),
            "bizCode": route.get("bizCode", ""),
            "projectCode": route.get("projectCode", ""),
        }
    )
    return f"{YGP_API_ROOT}/trading-notice/new/nodeList?{query}"


def _detail_url(route: Mapping[str, str], *, node_id: str, biz_code: str, notice_id: str) -> str:
    query = urllib.parse.urlencode(
        {
            "nodeId": node_id,
            "version": route.get("version") or "v3",
            "tradingType": route.get("tradingType", ""),
            "noticeId": notice_id,
            "bizCode": biz_code,
            "projectCode": route.get("projectCode", ""),
            "siteCode": route.get("siteCode", ""),
        }
    )
    return f"{YGP_API_ROOT}/trading-notice/new/detail?{query}"


def _flow_rows_from_nodes(
    task: Mapping[str, Any],
    *,
    resolved: Mapping[str, str],
    nodes: list[Mapping[str, Any]],
    created_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    present_flow_nos: set[str] = set()
    represented_flow_nos: set[str] = set()
    for node in nodes:
        flow = _map_node_to_flow(str(node.get("nodeName") or ""), str(node.get("selectedBizCode") or ""))
        if not flow:
            continue
        flow_no = str(flow["flow_no"])
        entries = _node_notice_entries(node)
        if not entries:
            key = f"{flow['flow_no']}|{node.get('nodeId') or ''}|absent"
            if key in seen:
                continue
            seen.add(key)
            represented_flow_nos.add(flow_no)
            rows.append(_flow_row(task, resolved=resolved, node=node, flow=flow, notice_id="", biz_code="", notice_label="", state="YGP_FLOW_ITEM_ABSENT", created_at=created_at))
            continue
        for entry in entries:
            key = f"{flow['flow_no']}|{node.get('nodeId') or ''}|{entry['biz_code']}|{entry['notice_id']}"
            if key in seen:
                continue
            seen.add(key)
            present_flow_nos.add(flow_no)
            represented_flow_nos.add(flow_no)
            rows.append(_flow_row(task, resolved=resolved, node=node, flow=flow, notice_id=entry["notice_id"], biz_code=entry["biz_code"], notice_label=entry["notice_label"], state="YGP_FLOW_ITEM_PRESENT", created_at=created_at))
    for flow in FLOW_MODULES:
        if str(flow["flow_no"]) in represented_flow_nos:
            continue
        key = f"{flow['flow_no']}|matrix_absent"
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            _flow_row(
                task,
                resolved=resolved,
                node={},
                flow=flow,
                notice_id="",
                biz_code="",
                notice_label="",
                state="YGP_FLOW_ITEM_NOT_PRESENT",
                created_at=created_at,
            )
        )
    rows.sort(key=lambda row: (str(row.get("flow_no") or ""), str(row.get("published_at") or ""), str(row.get("notice_id") or "")))
    return rows


def _node_notice_entries(node: Mapping[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in _list(node.get("dsList")):
        if not isinstance(item, Mapping):
            continue
        for key, values in item.items():
            biz_code, notice_label = _split_biz_label(str(key))
            for notice_id in _list(values):
                if str(notice_id or "").strip():
                    entries.append({"biz_code": biz_code or str(node.get("selectedBizCode") or ""), "notice_label": notice_label, "notice_id": str(notice_id)})
    if not entries and str(node.get("noticeId") or "").strip():
        entries.append(
            {
                "biz_code": str(node.get("selectedBizCode") or ""),
                "notice_label": str(node.get("nodeName") or ""),
                "notice_id": str(node.get("noticeId") or ""),
            }
        )
    return entries


def _flow_row(
    task: Mapping[str, Any],
    *,
    resolved: Mapping[str, str],
    node: Mapping[str, Any],
    flow: Mapping[str, str],
    notice_id: str,
    biz_code: str,
    notice_label: str,
    state: str,
    created_at: str,
) -> dict[str, Any]:
    detail_url = _detail_url(resolved, node_id=str(node.get("nodeId") or ""), biz_code=biz_code, notice_id=notice_id) if notice_id else ""
    return {
        "ygp_flow_item_id": _stable_id("YGP-FLOW-ITEM", task.get("source_url"), flow.get("flow_no"), node.get("nodeId"), biz_code, notice_id),
        "ygp_flow_matrix_task_id": str(task.get("ygp_flow_matrix_task_id") or ""),
        "source_url": str(task.get("source_url") or ""),
        "site_code": str(resolved.get("siteCode") or ""),
        "project_code": str(resolved.get("projectCode") or ""),
        "trading_type": str(resolved.get("tradingType") or ""),
        "flow_no": str(flow.get("flow_no") or ""),
        "flow_title": str(flow.get("flow_title") or ""),
        "document_kind": str(flow.get("document_kind") or ""),
        "node_name": str(node.get("nodeName") or ""),
        "node_id": str(node.get("nodeId") or ""),
        "biz_code": biz_code,
        "notice_label": notice_label,
        "notice_id": notice_id,
        "data_count": int(node.get("dataCount") or 0),
        "detail_url": detail_url,
        "flow_item_state": state,
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fetch_detail_for_flow(
    row: Mapping[str, Any],
    *,
    resolved: Mapping[str, str],
    getter: HttpGetter,
    created_at: str,
) -> dict[str, Any]:
    detail_url = str(row.get("detail_url") or "")
    response = _fetch_url(detail_url, getter, route="ygp_detail_fetch", task=row)
    payload = _json_payload(response["body"])
    if response["status_code"] != 200 or not isinstance(payload.get("data"), Mapping):
        blockers = _blockers_from_response(
            status=response["status_code"],
            body_probe=response["body"][:300],
            error=response["error"],
            prefix="ygp_detail",
        ) or ["ygp_detail_payload_missing"]
        return {
            **dict(row),
            "detail_readback_state": "YGP_DETAIL_READBACK_BLOCKED",
            "source_url": detail_url,
            "status_code": response["status_code"],
            "content_type": response["content_type"],
            "route_attempt": response["attempt"],
            "blocker_taxonomy": blockers,
            "created_at": created_at,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    extracted = _extract_detail_payload(payload.get("data"))
    return {
        **dict(row),
        "detail_readback_state": "YGP_DETAIL_READBACK_READY",
        "source_url": detail_url,
        "status_code": response["status_code"],
        "content_type": response["content_type"],
        "notice_title": extracted["notice_title"],
        "published_at": extracted["published_at"],
        "project_name": extracted["project_name"],
        "candidate_company_names": extracted["candidate_company_names"],
        "responsible_person_names": extracted["responsible_person_names"],
        "period_text": extracted["period_text"],
        "award_date": extracted["award_date"],
        "attachment_names": extracted["attachment_names"],
        "text_probe": extracted["text_probe"],
        "text_probe_sha256": _sha256(extracted["text_probe"]) if extracted["text_probe"] else "",
        "readback_payload_sha256": _sha256(response["body"]) if response["body"] else "",
        "record_payload_sha256": _fingerprint(extracted),
        "route_attempt": response["attempt"],
        "blocker_taxonomy": [],
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _extract_detail_payload(data: Any) -> dict[str, Any]:
    record = data if isinstance(data, Mapping) else {}
    title = str(record.get("title") or "")
    published_at = str(record.get("publishDate") or record.get("publishTime") or "")
    columns = _list(record.get("tradingNoticeColumnModelList"))
    text_parts: list[str] = [title, published_at]
    attachment_names: list[str] = []
    for column in columns:
        if not isinstance(column, Mapping):
            continue
        text_parts.append(str(column.get("name") or ""))
        for table in _list(column.get("multiKeyValueTableList")):
            for row in _list(table):
                if isinstance(row, Mapping):
                    key = str(row.get("key") or row.get("aliasName") or row.get("code") or "")
                    value = str(row.get("value") or "")
                    if key or value:
                        text_parts.append(f"{key}：{value}")
        richtext = str(column.get("richtext") or "")
        if richtext:
            text_parts.append(_html_to_text(richtext))
        for file_item in _list(column.get("noticeFileBOList")):
            if isinstance(file_item, Mapping):
                name = str(file_item.get("fileName") or file_item.get("name") or file_item.get("attachName") or "")
                if name:
                    attachment_names.append(name)
                    text_parts.append(f"附件：{name}")
    text = "\n".join(part for part in text_parts if part)
    return {
        "notice_title": title,
        "published_at": published_at,
        "project_name": _extract_first(text, [r"(?:采购项目名称|项目名称|工程名称)\s*[:：\t ]+\s*([^。；;\n]{4,120})"]),
        "candidate_company_names": _extract_company_names(text),
        "responsible_person_names": _extract_responsible_people(text),
        "period_text": _extract_period_text(text),
        "award_date": _extract_award_date(text) or published_at,
        "attachment_names": _dedupe(attachment_names),
        "text_probe": text[:1000],
    }


def _map_node_to_flow(node_name: str, biz_code: str) -> Mapping[str, str] | None:
    name = re.sub(r"\s+", "", node_name or "")
    if any(token in name for token in ("招标计划", "采购意向")):
        return FLOW_MODULES[0]
    if any(token in name for token in ("招标文件公示", "采购需求")):
        return FLOW_MODULES[1]
    if any(token in name for token in ("招标公告", "采购公告", "采购项目", "资格预审公告")):
        return FLOW_MODULES[2]
    if any(token in name for token in ("澄清", "答疑", "更正", "补充", "变更公告")):
        return FLOW_MODULES[3]
    if "开标" in name:
        return FLOW_MODULES[4]
    if any(token in name for token in ("资审结果", "资格审查结果")):
        return FLOW_MODULES[5]
    if "候选" in name:
        return FLOW_MODULES[6]
    if any(token in name for token in ("投标文件公开", "资格预审申请文件公开")):
        return FLOW_MODULES[7]
    if any(token in name for token in ("中标结果", "结果公告", "成交结果")):
        return FLOW_MODULES[8]
    if name == "中标信息" or biz_code == "05":
        return FLOW_MODULES[9]
    if any(token in name for token in ("合同公告", "合同信息", "合同公开")):
        return FLOW_MODULES[10]
    if any(token in name for token in ("终止", "项目异常", "废标", "流标")):
        return FLOW_MODULES[11]
    return None


def _fetch_url(
    url: str,
    getter: HttpGetter,
    *,
    route: str,
    task: Mapping[str, Any],
    no_redirect: bool = False,
) -> dict[str, Any]:
    response = dict(getter(url, {"route": route, "task": dict(task), "no_redirect": no_redirect}))
    status_code = int(response.get("status_code") or response.get("status") or 0)
    body = str(response.get("body") or response.get("content") or response.get("text") or "")
    headers = response.get("headers") if isinstance(response.get("headers"), Mapping) else {}
    content_type = str(response.get("content_type") or headers.get("Content-Type") or headers.get("content-type") or "")
    final_url = str(response.get("url") or url)
    error = str(response.get("error") or "")
    return {
        "url": final_url,
        "status_code": status_code,
        "content_type": content_type,
        "body": body,
        "headers": dict(headers),
        "error": error,
        "attempt": {
            "route": route,
            "url": final_url,
            "status_code": status_code,
            "content_type": content_type,
            "body_sha256": _sha256(body) if body else "",
            "error": error,
        },
    }


def _default_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 KakaYgpFlowMatrix/1.0",
            "Accept": "application/json,text/html,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://ygp.gdzwfw.gov.cn/",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler) if context.get("no_redirect") else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=25) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": response.headers.get("Content-Type", ""),
                "headers": dict(response.headers.items()),
                "body": body,
                "url": response.geturl(),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "status_code": int(exc.code),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body": body,
            "url": url,
            "error": str(exc),
        }
    except urllib.error.URLError as exc:
        return {"status_code": 0, "content_type": "", "headers": {}, "body": "", "url": url, "error": str(exc.reason)}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _blockers_from_response(*, status: int, body_probe: str, error: str, prefix: str) -> list[str]:
    blockers: list[str] = []
    if status in {403, 429}:
        blockers.append(f"{prefix}_forbidden_or_rate_limited_review")
    if status in {500, 502, 503, 504}:
        blockers.append(f"{prefix}_temporary_unavailable_retry_required")
    if status == 0 and error:
        blockers.append(f"{prefix}_transport_error_retry_required")
    if "验证码" in body_probe or "captcha" in body_probe.lower():
        blockers.append(f"{prefix}_captcha_or_challenge_review")
    if status == 200 and not body_probe.strip():
        blockers.append(f"{prefix}_empty_body_review")
    return _dedupe(blockers)


def _project_blocked(
    task: Mapping[str, Any],
    *,
    route_attempts: list[dict[str, Any]],
    blockers: list[str],
    created_at: str,
) -> dict[str, Any]:
    return {
        **dict(task),
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        "project_readback_state": "YGP_FLOW_MATRIX_BLOCKED",
        "route_attempts": route_attempts,
        "blocker_taxonomy": _dedupe(blockers),
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _summary(
    *,
    task_records: list[Mapping[str, Any]],
    project_records: list[Mapping[str, Any]],
    flow_matrix_records: list[Mapping[str, Any]],
    detail_readback_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    present_flows = {str(row.get("flow_no") or "") for row in flow_matrix_records if row.get("flow_item_state") == "YGP_FLOW_ITEM_PRESENT"}
    return {
        "guangdong_ygp_flow_matrix_state": "GUANGDONG_YGP_FLOW_MATRIX_READY" if not blocking_reasons else "GUANGDONG_YGP_FLOW_MATRIX_INPUT_BLOCKED",
        "execution_mode": execution_mode,
        "ygp_flow_matrix_task_count": len(task_records),
        "ygp_project_readback_count": len(project_records),
        "ygp_flow_item_count": len(flow_matrix_records),
        "ygp_present_flow_count": len(present_flows),
        "ygp_detail_readback_count": len(detail_readback_records),
        "ygp_detail_readback_ready_count": sum(1 for record in detail_readback_records if record.get("detail_readback_state") == "YGP_DETAIL_READBACK_READY"),
        "present_flow_nos": sorted(present_flows),
        "project_readback_state_counts": _counts(record.get("project_readback_state") for record in project_records),
        "flow_item_state_counts": _counts(record.get("flow_item_state") for record in flow_matrix_records),
        "detail_readback_state_counts": _counts(record.get("detail_readback_state") for record in detail_readback_records),
        "blocker_taxonomy_counts": _counts(
            blocker
            for record in [*project_records, *detail_readback_records]
            for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _extract_first(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_responsible_people(text: str) -> list[str]:
    patterns = [
        r"(?:项目负责人|项目经理|施工项目负责人|设计负责人|勘察负责人|总监理工程师|工程总承包项目经理)\s*[:：\t ]+\s*([\u4e00-\u9fa5·]{2,8})",
        r"(?:负责人姓名|姓名)\s*[:：\t ]+\s*([\u4e00-\u9fa5·]{2,8})",
    ]
    people: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            people.append(match.group(1).strip())
    return _dedupe(people)


def _extract_period_text(text: str) -> str:
    patterns = [
        r"(?:工期（交货期）|工期\(交货期\)|工期|服务期|合同履行期限|履行期限|服务期限)\s*[:：\t ]+\s*([^。；;\n]{2,100})",
        r"(?:计划工期)\s*[:：\t ]+\s*([^。；;\n]{2,100})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_award_date(text: str) -> str:
    patterns = [
        r"(?:中标日期|成交日期|公告日期|发布日期)\s*[:：\t ]+\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_company_names(text: str) -> list[str]:
    patterns = [
        r"(?:中标人|成交供应商|供应商名称|中标单位|中标候选人|第一中标候选人)\s*[:：\t ]+\s*([^。；;\n]{4,160})",
        r"(?:联合体成员|联合体\(成\)|联合体（成）)\s*[:：\t ]+\s*([^。；;\n]{4,160})",
    ]
    names: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            segment = match.group(1)
            for part in re.split(r"[;,，、；]|(?:联合体)|(?:\(成\))|(?:（成）)|(?:\(主\))|(?:（主）)", segment):
                part = part.strip()
                if "公司" in part or "集团" in part or "院" in part:
                    names.append(part)
    return _dedupe(names)


def _json_payload(text: str) -> Any:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, Mapping) else {}


def _html_to_text(content: str) -> str:
    text = re.sub(r"<\s*br\s*/?>", "\n", content, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _split_biz_label(value: str) -> tuple[str, str]:
    if "@" in value:
        left, right = value.split("@", 1)
        return left.strip(), right.strip()
    return value.strip(), ""


def _source_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return manifest if isinstance(manifest, Mapping) else payload


def _load_json(path: Path | None, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path or not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return data if isinstance(data, dict) else {}


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
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha256('|'.join(str(part or '') for part in parts))[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Guangdong YGP 01-12 flow matrix manifest.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--input-json", default=None)
    parser.add_argument("--source-url", action="append", default=[])
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-public-query", action="store_true")
    parser.add_argument("--max-live-source-urls", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_guangdong_ygp_flow_matrix(
        input_root=args.input_root,
        input_json=args.input_json,
        source_urls=args.source_url,
        output_root=args.output_root,
        enable_live_public_query=args.enable_live_public_query,
        max_live_source_urls=args.max_live_source_urls,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
