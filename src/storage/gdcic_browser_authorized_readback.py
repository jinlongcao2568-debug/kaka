from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from shared.utils import utc_now_iso


GDCIC_BROWSER_AUTHORIZED_READBACK_KIND = "gdcic_browser_authorized_readback_v1_manifest"
GDCIC_BROWSER_AUTHORIZED_READBACK_VERSION = 1
GDCIC_BROWSER_AUTHORIZED_READBACK_ADAPTER_ID = "gdcic-browser-authorized-readback-v1-builder"

DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_ROOT = Path("tmp/evaluation-real-samples/release-evidence-adapter-plan-v1")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/gdcic-browser-authorized-readback-v1")

GUANGDONG_GDCIC_HOME_PROFILE_ID = "GUANGDONG-GDCIC-HOME"
GUANGDONG_GDCIC_HOME_BASE_URL = "http://210.76.80.152:8008"
GUANGDONG_GDCIC_CONTRACT_SYSTEM_URL = f"{GUANGDONG_GDCIC_HOME_BASE_URL}/JG/home/Indexht"

TARGET_TYPES = {"contract_performance", "project_manager_change_notice"}
FORBIDDEN_TERMS = ("在建冲突成立", "无在建", "无风险", "无冲突", "造假成立", "违法成立", "确认本人", "是不是本人")

BrowserRunner = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def build_gdcic_browser_authorized_readback(
    *,
    release_evidence_adapter_plan_root: str | Path = DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_ROOT,
    release_evidence_adapter_plan_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    enable_live_browser_execution: bool = False,
    max_live_browser_tasks: int | None = None,
    browser_runner: BrowserRunner | None = None,
    storage_state_json: str | Path | None = None,
    user_data_dir: str | Path | None = None,
    headed: bool = False,
    wait_after_search_ms: int = 2500,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    plan_dir = Path(release_evidence_adapter_plan_root)
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = (
        Path(release_evidence_adapter_plan_json)
        if release_evidence_adapter_plan_json
        else plan_dir / "release-evidence-adapter-plan-v1.json"
    )
    blocking_reasons: list[str] = []
    payload = _load_json(source_path, blocking_reasons, "release_evidence_adapter_plan_missing")
    source_manifest = _source_manifest(payload)
    task_records = _task_records_from_release_plan(source_manifest, created_at=created)
    execution_mode = "LIVE_BROWSER_EXECUTION_ATTEMPTED" if enable_live_browser_execution else "PLAN_ONLY_NOT_EXECUTED"
    active_runner = browser_runner
    if active_runner is None and enable_live_browser_execution:
        active_runner = _make_playwright_browser_runner(
            storage_state_json=storage_state_json,
            user_data_dir=user_data_dir,
            headed=headed,
            wait_after_search_ms=wait_after_search_ms,
        )
    readback_records = _execute_tasks(
        task_records,
        created_at=created,
        enable_live_browser_execution=enable_live_browser_execution,
        max_live_browser_tasks=max_live_browser_tasks,
        browser_runner=active_runner,
    )
    summary = _summary(
        task_records=task_records,
        readback_records=readback_records,
        execution_mode=execution_mode,
        blocking_reasons=blocking_reasons,
    )
    manifest = {
        "manifest_version": GDCIC_BROWSER_AUTHORIZED_READBACK_VERSION,
        "manifest_kind": GDCIC_BROWSER_AUTHORIZED_READBACK_KIND,
        "adapter_id": GDCIC_BROWSER_AUTHORIZED_READBACK_ADAPTER_ID,
        "pipeline_stage": "GDCICBrowserAuthorizedReadbackV1",
        "manifest_id": f"GDCIC-BROWSER-AUTHORIZED-READBACK-{_fingerprint({'tasks': task_records, 'summary': summary})[:16]}",
        "created_at": created,
        "source_release_evidence_adapter_plan_root": str(plan_dir),
        "source_release_evidence_adapter_plan_json": str(source_path),
        "execution_mode": execution_mode,
        "live_browser_execution_enabled": bool(enable_live_browser_execution),
        "max_live_browser_tasks": max_live_browser_tasks,
        "storage_state_json_used": str(storage_state_json or ""),
        "user_data_dir_used": str(user_data_dir or ""),
        "headed_browser_requested": bool(headed),
        "browser_readback_task_records": task_records,
        "browser_readback_records": readback_records,
        "summary": summary,
        "safety": {
            "network_enabled": bool(enable_live_browser_execution),
            "browser_execution_enabled": bool(enable_live_browser_execution),
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            "stores_raw_html_or_blob": False,
            "requires_authorized_session_for_login_protected_pages": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    result = {
        "gdcic_browser_authorized_readback_mode": "BUILT" if not blocking_reasons else "INPUT_BLOCKED",
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
        result["summary"]["forbidden_term_hits"] = forbidden_hits
        text = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "gdcic-browser-authorized-readback-v1.json").write_text(text, encoding="utf-8")
    (out_dir / "gdcic-browser-authorized-readback-tasks.json").write_text(
        json.dumps(task_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "gdcic-browser-authorized-readback-records.json").write_text(
        json.dumps(readback_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _task_records_from_release_plan(source_manifest: Mapping[str, Any], *, created_at: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in _list(source_manifest.get("release_evidence_adapter_task_records")):
        if not isinstance(task, Mapping):
            continue
        target_type = str(task.get("release_evidence_target_type") or "").strip()
        if target_type not in TARGET_TYPES:
            continue
        region_code = str(
            task.get("local_housing_authority_adapter_region_code")
            or task.get("release_evidence_query_region_code")
            or ""
        ).strip().upper()
        source_profile_id = str(task.get("source_profile_id") or "").strip().upper()
        if region_code and region_code != "CN-GD":
            continue
        if source_profile_id and source_profile_id not in {GUANGDONG_GDCIC_HOME_PROFILE_ID, "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"}:
            continue
        browser_task = _task_record(task, target_type=target_type, created_at=created_at)
        key = str(browser_task.get("gdcic_browser_readback_task_id") or "")
        if key in seen:
            continue
        seen.add(key)
        tasks.append(browser_task)
    return tasks


def _task_record(task: Mapping[str, Any], *, target_type: str, created_at: str) -> dict[str, Any]:
    query_params = dict(task.get("query_params") or {})
    project_name = str(query_params.get("projectName") or task.get("project_name") or "").strip()
    company_name = str(
        query_params.get("companyName")
        or query_params.get("candidateCompanyName")
        or task.get("candidate_company_name")
        or ""
    ).strip()
    person_name = str(
        query_params.get("personName")
        or query_params.get("projectManagerName")
        or _first_text(_list(task.get("matched_person_names")))
        or ""
    ).strip()
    task_id = str(task.get("release_evidence_adapter_task_id") or task.get("query_task_id") or "")
    keywords = _dedupe([project_name, company_name, person_name, *_list(query_params.get("keywords"))])
    return {
        "gdcic_browser_readback_task_id": _stable_id("GDCIC-BROWSER-READBACK", task_id, target_type, project_name, company_name, person_name),
        "release_evidence_adapter_task_id": task_id,
        "source_release_evidence_probe_task_id": str(task.get("source_release_evidence_probe_task_id") or ""),
        "source_release_evidence_probe_plan_id": str(task.get("source_release_evidence_probe_plan_id") or ""),
        "project_id": str(task.get("project_id") or query_params.get("projectId") or ""),
        "project_name": project_name,
        "candidate_company_name": company_name,
        "person_name": person_name,
        "source_profile_id": GUANGDONG_GDCIC_HOME_PROFILE_ID,
        "release_evidence_target_type": target_type,
        "target_source_types": ["project_manager_change_notice"] if target_type == "project_manager_change_notice" else ["contract_public_info"],
        "source_url": GUANGDONG_GDCIC_CONTRACT_SYSTEM_URL,
        "query_params": {
            **query_params,
            "projectName": project_name,
            "companyName": company_name,
            "personName": person_name,
            "keywords": keywords,
        },
        "query_keywords": keywords,
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "readback_state": "PLAN_ONLY_NOT_EXECUTED",
        "created_at": created_at,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _execute_tasks(
    task_records: list[Mapping[str, Any]],
    *,
    created_at: str,
    enable_live_browser_execution: bool,
    max_live_browser_tasks: int | None,
    browser_runner: BrowserRunner | None,
) -> list[dict[str, Any]]:
    if not enable_live_browser_execution:
        return []
    if browser_runner is None:
        return [
            _blocked_record(
                task,
                created_at=created_at,
                blockers=["gdcic_browser_runner_missing"],
                readback_state="BROWSER_AUTHORIZED_READBACK_BLOCKED",
            )
            for task in task_records
        ]
    records: list[dict[str, Any]] = []
    attempted = 0
    for task in task_records:
        if max_live_browser_tasks is not None and attempted >= max_live_browser_tasks:
            records.append(
                _blocked_record(
                    task,
                    created_at=created_at,
                    blockers=["max_live_browser_tasks_deferred"],
                    readback_state="LIVE_BROWSER_EXECUTION_DEFERRED_BY_LIMIT",
                )
            )
            continue
        attempted += 1
        records.append(_readback_one(task, browser_runner=browser_runner, created_at=created_at))
    return records


def _readback_one(
    task: Mapping[str, Any],
    *,
    browser_runner: BrowserRunner,
    created_at: str,
) -> dict[str, Any]:
    try:
        response = dict(browser_runner(task))
    except Exception as exc:  # pragma: no cover - defensive around live browser stacks.
        response = {"status_code": 0, "body_text": "", "final_url": task.get("source_url"), "error": f"{type(exc).__name__}:{exc}"}
    text = _response_text(response)
    status_code = _int(response.get("status_code") or response.get("status") or response.get("http_status"))
    final_url = str(response.get("final_url") or response.get("url") or task.get("source_url") or "")
    error = str(response.get("error") or "")
    blockers = _browser_blockers(text=text, status_code=status_code, final_url=final_url, error=error)
    if blockers:
        return _blocked_record(
            task,
            created_at=created_at,
            blockers=blockers,
            readback_state="LOGIN_OR_SSO_REQUIRED_BLOCKED"
            if any("login" in item.lower() or "sso" in item.lower() for item in blockers)
            else "BROWSER_AUTHORIZED_READBACK_BLOCKED",
            status_code=status_code,
            final_url=final_url,
            text=text,
            error=error,
        )
    matched = _matched_record_from_text(task, text=text, final_url=final_url, captured_at=created_at)
    if matched:
        return {
            **_base_record(task, created_at=created_at),
            "readback_state": "BROWSER_AUTHORIZED_READBACK_READY",
            "adapter_result_state": "MATCHED",
            "authorization_readiness_state": "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
            "field_surface_state": "TARGET_FIELD_MATCHED_REVIEW_REQUIRED",
            "operator_next_actions": [],
            "source_url": str(task.get("source_url") or ""),
            "final_url": final_url,
            "status_code": status_code or 200,
            "text_probe": _text_probe(text),
            "text_probe_sha256": _sha256(_text_probe(text)),
            "records": [matched],
            "record_count": 1,
            "blocker_taxonomy": [],
            "query_miss_is_not_clearance": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    return {
        **_base_record(task, created_at=created_at),
        "readback_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
        "adapter_result_state": "NOT_FOUND",
        "authorization_readiness_state": "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
        "field_surface_state": "TARGET_FIELD_NOT_FOUND_REVIEW_REQUIRED",
        "operator_next_actions": ["review_gdcic_authorized_query_terms_or_capture_more_precise_field_page"],
        "source_url": str(task.get("source_url") or ""),
        "final_url": final_url,
        "status_code": status_code or 200,
        "text_probe": _text_probe(text),
        "text_probe_sha256": _sha256(_text_probe(text)),
        "records": [],
        "record_count": 0,
        "blocker_taxonomy": ["gdcic_browser_authorized_readback_no_target_field_match_review"],
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _blocked_record(
    task: Mapping[str, Any],
    *,
    created_at: str,
    blockers: list[str],
    readback_state: str,
    status_code: int = 0,
    final_url: str = "",
    text: str = "",
    error: str = "",
) -> dict[str, Any]:
    authorization_state = _authorization_state_from_blockers(blockers, readback_state)
    return {
        **_base_record(task, created_at=created_at),
        "readback_state": readback_state,
        "adapter_result_state": "BLOCKED" if readback_state != "LIVE_BROWSER_EXECUTION_DEFERRED_BY_LIMIT" else "NEEDS_BROWSER",
        "authorization_readiness_state": authorization_state,
        "field_surface_state": _field_surface_state_from_authorization_state(authorization_state),
        "operator_next_actions": _operator_next_actions_for_authorization_state(authorization_state),
        "source_url": str(task.get("source_url") or ""),
        "final_url": final_url or str(task.get("source_url") or ""),
        "status_code": status_code or None,
        "text_probe": _text_probe(text),
        "text_probe_sha256": _sha256(_text_probe(text)),
        "records": [],
        "record_count": 0,
        "blocker_taxonomy": _dedupe(blockers),
        "error": error,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _base_record(task: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    return {
        "gdcic_browser_readback_task_id": str(task.get("gdcic_browser_readback_task_id") or ""),
        "release_evidence_adapter_task_id": str(task.get("release_evidence_adapter_task_id") or ""),
        "source_release_evidence_probe_task_id": str(task.get("source_release_evidence_probe_task_id") or ""),
        "source_release_evidence_probe_plan_id": str(task.get("source_release_evidence_probe_plan_id") or ""),
        "project_id": str(task.get("project_id") or ""),
        "project_name": str(task.get("project_name") or ""),
        "candidate_company_name": str(task.get("candidate_company_name") or ""),
        "person_name": str(task.get("person_name") or ""),
        "source_profile_id": GUANGDONG_GDCIC_HOME_PROFILE_ID,
        "release_evidence_target_type": str(task.get("release_evidence_target_type") or ""),
        "target_source_types": _list(task.get("target_source_types")),
        "captured_at": created_at,
    }


def _matched_record_from_text(
    task: Mapping[str, Any],
    *,
    text: str,
    final_url: str,
    captured_at: str,
) -> dict[str, Any] | None:
    target_type = str(task.get("release_evidence_target_type") or "")
    keywords = _list(task.get("query_keywords")) or _list((task.get("query_params") or {}).get("keywords"))
    project_name = str(task.get("project_name") or "")
    company_name = str(task.get("candidate_company_name") or "")
    person_name = str(task.get("person_name") or "")
    identity_hits = sum(
        1
        for value in (project_name, company_name, person_name)
        if value and value in text
    )
    if target_type == "project_manager_change_notice":
        target_tokens = ("项目经理变更", "项目负责人变更", "人员变更", "原项目经理", "新项目经理", "变更")
    else:
        target_tokens = ("合同", "履约", "备案", "工期", "开工", "竣工", "完工")
    if identity_hits <= 0 or not any(token in text for token in target_tokens):
        return None
    selected_text = _selected_record_text(text, keywords=[*keywords, *target_tokens])
    return {
        "source_url": str(task.get("source_url") or ""),
        "browser_url": final_url,
        "captured_at": captured_at,
        "project_name": project_name,
        "company_name": company_name,
        "person_name": person_name,
        "record_text": selected_text,
        "record_text_sha256": _sha256(selected_text),
        "matched_keywords": [keyword for keyword in keywords if keyword and keyword in text][:10],
        "query_miss_is_not_clearance": True,
        "readback_is_line_clue_not_final_conclusion": True,
    }


def _make_playwright_browser_runner(
    *,
    storage_state_json: str | Path | None,
    user_data_dir: str | Path | None,
    headed: bool,
    wait_after_search_ms: int,
) -> BrowserRunner:
    def runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
        return _playwright_browser_runner(
            task,
            storage_state_json=storage_state_json,
            user_data_dir=user_data_dir,
            headed=headed,
            wait_after_search_ms=wait_after_search_ms,
        )

    return runner


def _playwright_browser_runner(
    task: Mapping[str, Any],
    *,
    storage_state_json: str | Path | None,
    user_data_dir: str | Path | None,
    headed: bool,
    wait_after_search_ms: int,
) -> Mapping[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional local browser stack.
        return {"status_code": 0, "body_text": "", "final_url": task.get("source_url"), "error": f"playwright_unavailable:{exc}"}
    source_url = str(task.get("source_url") or GUANGDONG_GDCIC_CONTRACT_SYSTEM_URL)
    with sync_playwright() as playwright:
        context = None
        browser = None
        try:
            if user_data_dir:
                context = playwright.chromium.launch_persistent_context(
                    str(user_data_dir),
                    headless=not headed,
                    ignore_https_errors=True,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
            else:
                browser = playwright.chromium.launch(headless=not headed)
                context_kwargs: dict[str, Any] = {
                    "ignore_https_errors": True,
                    "locale": "zh-CN",
                    "timezone_id": "Asia/Shanghai",
                }
                if storage_state_json:
                    context_kwargs["storage_state"] = str(storage_state_json)
                context = browser.new_context(**context_kwargs)
            page = context.new_page()
            response = page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            text_before = _body_text(page)
            if not _looks_like_login_or_challenge(text_before, page.url):
                _try_search(page, task)
                page.wait_for_timeout(max(300, int(wait_after_search_ms or 0)))
            body_text = _body_text(page)
            if not body_text:
                body_text = _html_to_text(page.content())
            status_code = int(getattr(response, "status", 200) or 200) if response else 200
            return {
                "status_code": status_code,
                "body_text": body_text,
                "final_url": page.url or source_url,
            }
        except Exception as exc:  # pragma: no cover - depends on live browser behavior.
            return {"status_code": 0, "body_text": "", "final_url": source_url, "error": f"playwright_route_failed:{type(exc).__name__}:{exc}"}
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def _try_search(page: Any, task: Mapping[str, Any]) -> None:
    query = _first_text(
        (
            task.get("candidate_company_name"),
            _clean_project_title(task.get("project_name")),
            task.get("person_name"),
        )
    )
    if not query:
        return
    selectors = (
        "input[type='search']",
        "input[placeholder*='企业']",
        "input[placeholder*='项目']",
        "input[placeholder*='关键']",
        "input[type='text']",
        ".el-input__inner",
    )
    filled = False
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            locator.fill(query, timeout=1500)
            filled = True
            break
        except Exception:
            continue
    if not filled:
        return
    for label in ("查询", "搜索", "检索"):
        try:
            page.get_by_text(label).first.click(timeout=1500)
            return
        except Exception:
            continue
    try:
        page.keyboard.press("Enter")
    except Exception:
        return


def _browser_blockers(*, text: str, status_code: int, final_url: str, error: str) -> list[str]:
    blockers: list[str] = []
    if error:
        blockers.append(f"gdcic_browser_execution_error:{error.split(':', 1)[0]}")
    if status_code and status_code >= 400:
        blockers.append("gdcic_browser_http_error")
    if not str(text or "").strip():
        blockers.append("gdcic_browser_empty_payload")
    if _looks_like_login_or_challenge(text, final_url):
        blockers.append("gdcic_login_or_sso_required_for_authorized_readback")
    return _dedupe(blockers)


def _authorization_state_from_blockers(blockers: list[str], readback_state: str) -> str:
    joined = " ".join(str(blocker or "") for blocker in blockers).lower()
    if readback_state == "LIVE_BROWSER_EXECUTION_DEFERRED_BY_LIMIT":
        return "NOT_EXECUTED_DEFERRED_BY_LIMIT"
    if "login" in joined or "sso" in joined:
        return "LOGIN_OR_SSO_REQUIRED"
    if "playwright_unavailable" in joined:
        return "LOCAL_BROWSER_RUNTIME_UNAVAILABLE"
    if "empty_payload" in joined:
        return "BROWSER_PAYLOAD_EMPTY_REVIEW_REQUIRED"
    if blockers:
        return "BROWSER_EXECUTION_BLOCKED_REVIEW_REQUIRED"
    return "UNKNOWN_REVIEW_REQUIRED"


def _field_surface_state_from_authorization_state(authorization_state: str) -> str:
    if authorization_state == "LOGIN_OR_SSO_REQUIRED":
        return "LOGIN_OR_SSO_BLOCKED_BEFORE_FIELD_SURFACE"
    if authorization_state == "LOCAL_BROWSER_RUNTIME_UNAVAILABLE":
        return "LOCAL_BROWSER_RUNTIME_UNAVAILABLE"
    if authorization_state == "NOT_EXECUTED_DEFERRED_BY_LIMIT":
        return "FIELD_SURFACE_NOT_ATTEMPTED_DEFERRED"
    if authorization_state == "BROWSER_PAYLOAD_EMPTY_REVIEW_REQUIRED":
        return "FIELD_SURFACE_EMPTY_REVIEW_REQUIRED"
    return "FIELD_SURFACE_BLOCKED_REVIEW_REQUIRED"


def _operator_next_actions_for_authorization_state(authorization_state: str) -> list[str]:
    if authorization_state == "LOGIN_OR_SSO_REQUIRED":
        return ["provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"]
    if authorization_state == "LOCAL_BROWSER_RUNTIME_UNAVAILABLE":
        return ["install_or_enable_playwright_browser_runtime_then_rerun"]
    if authorization_state == "NOT_EXECUTED_DEFERRED_BY_LIMIT":
        return ["increase_max_live_browser_tasks_or_run_specific_task"]
    if authorization_state == "BROWSER_PAYLOAD_EMPTY_REVIEW_REQUIRED":
        return ["rerun_with_headed_browser_or_longer_wait_budget"]
    return ["review_gdcic_browser_execution_blocker_then_rerun"]


def _looks_like_login_or_challenge(text: str, url: str) -> bool:
    probe = f"{text}\n{url}".lower()
    if "登录" in str(text or "") and (
        "招投标及合同履约监管系统" in str(text or "")
        or "广东省建筑市场监管公共服务平台" in str(text or "")
    ):
        return True
    return any(
        token.lower() in probe
        for token in (
            "SSO/jrsso/auth",
            "UniteLogin",
            "统一身份认证",
            "用户登录",
            "账号登录",
            "请登录",
            "验证码",
            "滑块",
            "captcha",
        )
    )


def _response_text(response: Mapping[str, Any]) -> str:
    for key in ("body_text", "text", "body", "content"):
        value = response.get(key)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        if value is not None:
            return _html_to_text(str(value)) if "<" in str(value)[:500] else str(value)
    return ""


def _body_text(page: Any) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=5000) or "")
    except Exception:
        return ""


def _html_to_text(value: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.replace("&nbsp;", " ").split())


def _selected_record_text(text: str, *, keywords: list[Any]) -> str:
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    selected = [
        line
        for line in lines
        if line and any(str(keyword or "").strip() and str(keyword).strip() in line for keyword in keywords)
    ]
    if not selected:
        selected = [line for line in lines if line][:20]
    return "\n".join(selected[:40])[:4000]


def _text_probe(text: str) -> str:
    return " ".join(str(text or "").split())[:1200]


def _summary(
    *,
    task_records: list[Mapping[str, Any]],
    readback_records: list[Mapping[str, Any]],
    execution_mode: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    authorization_state_counts = _counts(record.get("authorization_readiness_state") for record in readback_records)
    return {
        "execution_mode": execution_mode,
        "gdcic_browser_readback_task_count": len(task_records),
        "gdcic_browser_readback_record_count": len(readback_records),
        "gdcic_browser_readback_ready_count": sum(
            1 for record in readback_records if str(record.get("readback_state") or "") == "BROWSER_AUTHORIZED_READBACK_READY"
        ),
        "gdcic_browser_login_or_sso_required_count": sum(
            1 for record in readback_records if str(record.get("readback_state") or "") == "LOGIN_OR_SSO_REQUIRED_BLOCKED"
        ),
        "gdcic_browser_no_field_match_count": sum(
            1 for record in readback_records if str(record.get("readback_state") or "") == "NO_FIELD_MATCH_REVIEW_REQUIRED"
        ),
        "readback_state_counts": _counts(record.get("readback_state") for record in readback_records),
        "adapter_result_state_counts": _counts(record.get("adapter_result_state") for record in readback_records),
        "authorization_readiness_state_counts": authorization_state_counts,
        "gdcic_authorized_session_overall_state": _overall_authorization_state(
            execution_mode=execution_mode,
            readback_records=readback_records,
            authorization_state_counts=authorization_state_counts,
        ),
        "operator_next_action_counts": _counts(
            action
            for record in readback_records
            for action in _list(record.get("operator_next_actions"))
        ),
        "release_evidence_target_type_counts": _counts(task.get("release_evidence_target_type") for task in task_records),
        "blocker_taxonomy_counts": _counts(
            blocker
            for record in readback_records
            for blocker in _list(record.get("blocker_taxonomy"))
        ),
        "blocking_reasons": blocking_reasons,
        "query_miss_is_not_clearance": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _overall_authorization_state(
    *,
    execution_mode: str,
    readback_records: list[Mapping[str, Any]],
    authorization_state_counts: Mapping[str, int],
) -> str:
    if execution_mode == "PLAN_ONLY_NOT_EXECUTED":
        return "NOT_ATTEMPTED_PLAN_ONLY"
    if not readback_records:
        return "NO_BROWSER_READBACK_RECORDS"
    if authorization_state_counts.get("FIELD_SURFACE_REACHED_REVIEW_REQUIRED"):
        return "FIELD_SURFACE_REACHED_REVIEW_REQUIRED"
    if authorization_state_counts.get("LOGIN_OR_SSO_REQUIRED"):
        return "LOGIN_OR_SSO_REQUIRED"
    if authorization_state_counts.get("NOT_EXECUTED_DEFERRED_BY_LIMIT") == len(readback_records):
        return "NOT_EXECUTED_DEFERRED_BY_LIMIT"
    if authorization_state_counts.get("LOCAL_BROWSER_RUNTIME_UNAVAILABLE") == len(readback_records):
        return "LOCAL_BROWSER_RUNTIME_UNAVAILABLE"
    return "PARTIAL_OR_BLOCKED_REVIEW_REQUIRED"


def _source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") if isinstance(payload, Mapping) else {}
    return dict(manifest) if isinstance(manifest, Mapping) else dict(payload)


def _load_json(path: Path, blocking_reasons: list[str], missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        blocking_reasons.append(missing_reason)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blocking_reasons.append(f"{missing_reason}:invalid_json")
        return {}
    return data if isinstance(data, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first_text(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


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
        if text:
            counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items()))


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() if value else ""


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_fingerprint([str(part or '') for part in parts])[:16]}"


def _clean_project_title(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in ("中标候选人公示", "中标结果公示", "中标结果公告", "招标公告", "招标文件", "资格审查结果公示"):
        text = text.replace(suffix, "")
    return " ".join(text.split()).strip(" -_，,。")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build GDCIC browser authorized readback v1.")
    parser.add_argument("--release-evidence-adapter-plan-root", default=str(DEFAULT_RELEASE_EVIDENCE_ADAPTER_PLAN_ROOT))
    parser.add_argument("--release-evidence-adapter-plan-json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--enable-live-browser-execution", action="store_true")
    parser.add_argument("--max-live-browser-tasks", type=int)
    parser.add_argument("--storage-state-json")
    parser.add_argument("--user-data-dir")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-after-search-ms", type=int, default=2500)
    parser.add_argument("--created-at")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_gdcic_browser_authorized_readback(
        release_evidence_adapter_plan_root=args.release_evidence_adapter_plan_root,
        release_evidence_adapter_plan_json=args.release_evidence_adapter_plan_json,
        output_root=args.output_root,
        enable_live_browser_execution=args.enable_live_browser_execution,
        max_live_browser_tasks=args.max_live_browser_tasks,
        storage_state_json=args.storage_state_json,
        user_data_dir=args.user_data_dir,
        headed=args.headed,
        wait_after_search_ms=args.wait_after_search_ms,
        created_at=args.created_at,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("safe_to_execute") else 1


if __name__ == "__main__":
    raise SystemExit(main())
