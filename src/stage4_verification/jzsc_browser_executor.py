# Stage: stage4_verification
# Browser executor for JZSC company-first project-manager identity capture.

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Any, Callable, Mapping

from shared.utils import utc_now_iso
from storage.repositories.object_storage_repo import ObjectStorageRepository


JZSC_BROWSER_EXECUTOR_ID = "stage4.jzsc_company_first_browser_executor.v1"
JZSC_RENDERED_COMPANY_PERSONNEL_SNAPSHOT_KIND = "jzsc_rendered_company_personnel_rows"
JZSC_RENDERED_PERSONNEL_PROJECT_SNAPSHOT_KIND = "jzsc_rendered_personnel_project_rows"

BrowserRunner = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def execute_jzsc_company_first_browser_capture(
    parsed_context: Mapping[str, Any],
    *,
    target_company_name: str,
    target_project_manager_name: str,
    target_identifier: str | None = None,
    repository: ObjectStorageRepository | None = None,
    browser_runner: BrowserRunner | None = None,
    base_public_verification_carriers: list[Mapping[str, Any]] | None = None,
    max_personnel_pages: int = 20,
    max_project_pages: int = 20,
    personnel_retry_attempts: int = 3,
    project_retry_attempts: int = 3,
    capture_personnel_project_records: bool = False,
) -> dict[str, Any]:
    from stage4_verification.service import Stage4Service

    service = Stage4Service()
    capture_plan = dict(
        service.build_jzsc_project_manager_company_first_capture_plan(
            target_company_name=target_company_name,
            target_project_manager_name=target_project_manager_name,
            target_identifier=target_identifier,
            max_personnel_pages=max_personnel_pages,
            max_project_pages=max_project_pages,
        )
    )
    capture_plan["project_retry_attempts"] = max(1, int(project_retry_attempts or 1))
    capture_plan["personnel_retry_attempts"] = max(1, int(personnel_retry_attempts or 1))
    capture_plan["capture_personnel_project_records"] = bool(capture_personnel_project_records)
    run_id = _stable_id(
        "JZSC-BROWSER-RUN",
        capture_plan.get("capture_plan_id"),
        target_company_name,
        target_project_manager_name,
        target_identifier,
    )
    runner = browser_runner or _playwright_browser_runner
    repo = repository or ObjectStorageRepository()
    try:
        browser_result = dict(runner(capture_plan))
    except Exception as exc:
        return _fail_closed(
            run_id=run_id,
            capture_plan=capture_plan,
            target_company_name=target_company_name,
            target_project_manager_name=target_project_manager_name,
            reasons=[f"browser_runner_exception:{exc}"],
        )

    fail_closed_reasons = [
        str(reason)
        for reason in list(browser_result.get("failure_reasons") or [])
        if str(reason).strip()
    ]
    company_rows = list(browser_result.get("rendered_company_personnel_rows") or [])
    project_rows = list(browser_result.get("rendered_personnel_project_rows") or [])
    company_source_url = str(
        browser_result.get("company_personnel_source_url")
        or browser_result.get("company_detail_url")
        or capture_plan.get("entry_url")
        or ""
    ).strip()
    project_source_url = str(
        browser_result.get("personnel_project_source_url")
        or browser_result.get("personnel_detail_url")
        or ""
    ).strip()

    if not company_rows:
        fail_closed_reasons.append("rendered_company_personnel_rows_missing")
    if not company_source_url:
        fail_closed_reasons.append("company_personnel_source_url_missing")

    company_snapshot_id = ""
    project_snapshot_id = ""
    if company_rows and company_source_url:
        company_snapshot_id = _save_rows_snapshot(
            repo,
            snapshot_kind=JZSC_RENDERED_COMPANY_PERSONNEL_SNAPSHOT_KIND,
            source_url=company_source_url,
            rows=company_rows,
            run_id=run_id,
            target_company_name=target_company_name,
            target_project_manager_name=target_project_manager_name,
            role="company_personnel",
        )
    if project_rows and project_source_url:
        project_snapshot_id = _save_rows_snapshot(
            repo,
            snapshot_kind=JZSC_RENDERED_PERSONNEL_PROJECT_SNAPSHOT_KIND,
            source_url=project_source_url,
            rows=project_rows,
            run_id=run_id,
            target_company_name=target_company_name,
            target_project_manager_name=target_project_manager_name,
            role="personnel_projects",
        )

    base = {
        "adapter_id": JZSC_BROWSER_EXECUTOR_ID,
        "browser_execution_run_id": run_id,
        "capture_plan": capture_plan,
        "target_company_name": target_company_name,
        "target_project_manager_name": target_project_manager_name,
        "matched_company_name_optional": browser_result.get("matched_company_name_optional"),
        "matched_company_public_id_optional": browser_result.get("matched_company_public_id_optional"),
        "target_identifier_optional": target_identifier,
        "live_browser_executed": bool(browser_result.get("live_browser_executed", browser_runner is None)),
        "browser_runner_id": str(browser_result.get("browser_runner_id") or "custom_browser_runner"),
        "company_personnel_source_url": company_source_url,
        "company_personnel_source_snapshot_id": company_snapshot_id,
        "personnel_project_source_url": project_source_url,
        "personnel_project_source_snapshot_id": project_snapshot_id,
        "rendered_company_personnel_row_count": len(company_rows),
        "rendered_personnel_project_row_count": len(project_rows),
        "fail_closed_reasons": list(dict.fromkeys(fail_closed_reasons)),
        "browser_nonfatal_diagnostics": list(
            dict.fromkeys(str(reason) for reason in list(browser_result.get("nonfatal_diagnostics") or []) if str(reason).strip())
        ),
        "browser_attempts": list(browser_result.get("browser_attempts") or []),
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }
    if fail_closed_reasons:
        return {
            **base,
            "executor_state": "FAIL_CLOSED",
            "readback_state": "REVIEW_REQUIRED",
            "customer_sellable_evidence_ready": False,
        }

    readback = dict(
        service.run_jzsc_company_first_rendered_readback(
            parsed_context,
            target_company_name=str(browser_result.get("matched_company_name_optional") or target_company_name),
            target_project_manager_name=target_project_manager_name,
            rendered_company_personnel_rows=company_rows,
            company_personnel_source_url=company_source_url,
            company_personnel_source_snapshot_id=company_snapshot_id,
            rendered_personnel_project_rows=project_rows if project_rows else None,
            personnel_project_source_url=project_source_url if project_rows else None,
            personnel_project_source_snapshot_id=project_snapshot_id if project_rows else None,
            target_identifier=target_identifier,
            base_public_verification_carriers=base_public_verification_carriers,
        )
    )
    return {
        **base,
        **readback,
        "adapter_id": JZSC_BROWSER_EXECUTOR_ID,
        "executor_state": "READBACK_READY",
        "readback_state": readback.get("readback_state") or "READBACK_READY",
        "fail_closed_reasons": list(dict.fromkeys([*fail_closed_reasons, *list(readback.get("fail_closed_reasons") or [])])),
        "customer_sellable_evidence_ready": False,
    }


def _playwright_browser_runner(capture_plan: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {
            "browser_runner_id": "playwright",
            "live_browser_executed": False,
            "failure_reasons": [f"playwright_unavailable:{exc}"],
        }

    target = dict(capture_plan.get("target") or {})
    company_name = str(target.get("company_name") or "").strip()
    manager_name = str(target.get("project_manager_name") or "").strip()
    entry_url = str(capture_plan.get("entry_url") or "").strip()
    max_personnel_pages = _capture_step_max_pages(
        capture_plan,
        "capture_registered_personnel_rows",
        default=20,
    )
    max_project_pages = _capture_step_max_pages(
        capture_plan,
        "capture_personnel_project_records",
        default=20,
    )
    project_retry_attempts = _int_or_default(capture_plan.get("project_retry_attempts"), 3)
    personnel_retry_attempts = _int_or_default(capture_plan.get("personnel_retry_attempts"), 3)
    capture_personnel_project_records = bool(
        capture_plan.get("capture_personnel_project_records")
    )
    if not company_name or not manager_name or not entry_url:
        return {
            "browser_runner_id": "playwright",
            "live_browser_executed": False,
            "failure_reasons": ["capture_plan_target_or_entry_url_missing"],
        }

    failure_reasons: list[str] = []
    nonfatal_diagnostics: list[str] = []
    browser_attempts: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
        )
        try:
            company_candidates = _candidate_company_names(company_name)
            company_match: dict[str, Any] | None = None
            for attempt_no, candidate_company in enumerate(company_candidates[:3], start=1):
                rows = _search_company_rows_with_retry(
                    page,
                    entry_url=entry_url,
                    company_name=candidate_company,
                    retry_attempts=personnel_retry_attempts,
                )
                browser_attempts.append(
                    {
                        "attempt_no": attempt_no,
                        "attempt_type": "company_search",
                        "query_company_name": candidate_company,
                        "result_count": len(rows),
                    }
                )
                company_match = _pick_company_match(rows, candidate_company)
                if company_match:
                    break
            if not company_match:
                failure_reasons.append("company_search_result_not_found_after_three_attempts")

            matched_company_name = str(
                (company_match or {}).get("QY_NAME")
                or (company_candidates[0] if company_candidates else company_name)
            ).strip()
            matched_company_id = str((company_match or {}).get("QY_ID") or "").strip()
            matched_company_names = _dedupe_strings(
                [matched_company_name, *company_candidates, company_name]
            )

            company_rows, personnel_attempts = _resolve_personnel_rows_by_company_first(
                page,
                manager_name=manager_name,
                company_names=matched_company_names,
                max_pages=max_personnel_pages,
                retry_attempts=personnel_retry_attempts,
            )
            browser_attempts.extend(personnel_attempts)
            personnel_url = page.url
            if not company_rows:
                failure_reasons.append(
                    f"project_manager_not_found_by_company_name_person_name_after_{personnel_retry_attempts}_attempts"
                )

            project_rows: list[dict[str, Any]] = []
            project_url = ""
            if company_rows and capture_personnel_project_records:
                detail_url = str(company_rows[0].get("detail_url") or "").strip()
                if detail_url:
                    detail_result = _capture_person_detail_and_project_rows(
                        page,
                        detail_url=detail_url,
                        manager_name=manager_name,
                        max_project_pages=max_project_pages,
                        retry_attempts=project_retry_attempts,
                    )
                    project_rows = list(detail_result.get("project_rows") or [])
                    project_url = str(detail_result.get("project_source_url") or page.url)
                    nonfatal_diagnostics.extend(
                        list(detail_result.get("nonfatal_diagnostics") or [])
                    )
                    browser_attempts.extend(list(detail_result.get("browser_attempts") or []))
                else:
                    nonfatal_diagnostics.append("personnel_detail_url_missing_from_person_search_row")
            elif company_rows:
                nonfatal_diagnostics.append(
                    "jzsc_project_records_skipped_by_policy_lagging_not_used_for_performance_verification"
                )
                browser_attempts.append(
                    {
                        "attempt_type": "skip_personnel_project_records",
                        "reason": "jzsc_project_records_lagging_not_used_for_performance_verification",
                    }
                )
            result = {
                "browser_runner_id": "playwright",
                "live_browser_executed": True,
                "company_personnel_source_url": personnel_url,
                "personnel_project_source_url": project_url or page.url,
                "rendered_company_personnel_rows": company_rows,
                "rendered_personnel_project_rows": project_rows,
                "failure_reasons": failure_reasons,
                "nonfatal_diagnostics": nonfatal_diagnostics,
                "browser_attempts": browser_attempts,
                "matched_company_name_optional": matched_company_name,
                "matched_company_public_id_optional": matched_company_id,
            }
        except PlaywrightTimeoutError as exc:
            result = {
                "browser_runner_id": "playwright",
                "live_browser_executed": True,
                "failure_reasons": [f"playwright_timeout:{exc}"],
                "nonfatal_diagnostics": nonfatal_diagnostics,
                "browser_attempts": browser_attempts,
            }
        finally:
            browser.close()
    return result


def _search_company_rows(page: Any, entry_url: str, company_name: str) -> list[dict[str, Any]]:
    if not company_name:
        return []
    query_url = f"{entry_url.split('?', 1)[0]}?complexname={quote(company_name)}"
    page.goto(query_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    _wait_for_body_or_timeout(page, company_name, timeout_ms=10000)
    page.wait_for_timeout(1500)
    return _extract_vue_company_rows(page)


def _search_company_rows_with_retry(
    page: Any,
    *,
    entry_url: str,
    company_name: str,
    retry_attempts: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for retry_no in range(1, max(1, retry_attempts) + 1):
        rows = _search_company_rows(page, entry_url, company_name)
        if rows:
            return rows
        page.wait_for_timeout(900 * retry_no)
    return rows


def _submit_company_query(page: Any, company_name: str) -> None:
    inputs = page.locator("input")
    count = inputs.count()
    for index in range(count):
        candidate = inputs.nth(index)
        try:
            if not candidate.is_visible(timeout=500):
                continue
            candidate.fill(company_name, timeout=2000)
            break
        except Exception:
            continue
    for label in ("查询", "搜索"):
        try:
            page.get_by_text(label, exact=True).click(timeout=2000)
            return
        except Exception:
            continue
    try:
        page.keyboard.press("Enter")
    except Exception:
        return


def _resolve_personnel_rows_by_company_first(
    page: Any,
    *,
    manager_name: str,
    company_names: list[str],
    max_pages: int,
    retry_attempts: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    target_names = _dedupe_strings(company_names)[:3]
    for retry_no in range(1, max(1, retry_attempts) + 1):
        for company_index, company_name in enumerate(target_names, start=1):
            rows = _search_person_rows(
                page,
                manager_name=manager_name,
                company_name=company_name,
                max_pages=1,
            )
            matches = _pick_person_company_matches(rows, manager_name, target_names)
            attempts.append(
                {
                    "attempt_no": len(attempts) + 1,
                    "retry_no": retry_no,
                    "company_candidate_no": company_index,
                    "attempt_type": "person_search_name_and_registered_unit",
                    "query_person_name": manager_name,
                    "query_company_name": company_name,
                    "result_count": len(rows),
                    "matched_count": len(matches),
                }
            )
            if matches:
                return [_person_search_row_to_rendered_row(row) for row in matches], attempts
        page.wait_for_timeout(900 * retry_no)

    name_only_retry_attempts = max(1, min(2, retry_attempts))
    if retry_attempts > name_only_retry_attempts:
        attempts.append(
            {
                "attempt_no": len(attempts) + 1,
                "attempt_type": "name_only_fallback_retry_limited",
                "requested_retry_attempts": retry_attempts,
                "effective_retry_attempts": name_only_retry_attempts,
                "reason": "company_name_person_name_exact_retry_exhausted_first",
            }
        )

    for retry_no in range(1, name_only_retry_attempts + 1):
        rows = _search_person_rows(
            page,
            manager_name=manager_name,
            company_name="",
            max_pages=max(1, max_pages),
        )
        matches = _pick_person_company_matches(rows, manager_name, target_names)
        attempts.append(
            {
                "attempt_no": len(attempts) + 1,
                "retry_no": retry_no,
                "attempt_type": "person_search_name_only_paginated_company_filter",
                "query_person_name": manager_name,
                "query_company_names": target_names,
                "result_count": len(rows),
                "matched_count": len(matches),
                "page_limit": max_pages,
            }
        )
        if matches:
            return [_person_search_row_to_rendered_row(row) for row in matches], attempts
        page.wait_for_timeout(900 * retry_no)
    return [], attempts


def _search_person_rows(
    page: Any,
    *,
    manager_name: str,
    company_name: str,
    max_pages: int,
) -> list[dict[str, Any]]:
    page.goto("https://jzsc.mohurd.gov.cn/data/person", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    if not _set_person_query_via_vue(page, manager_name=manager_name, company_name=company_name, page_no=1):
        _fill_if_possible(page, 'input[placeholder="请输入人员姓名"]', manager_name)
        _fill_if_possible(page, 'input[placeholder="请输入注册单位"]', company_name)
        try:
            page.locator("span.ssButton").click(timeout=5000)
        except Exception:
            _open_text_if_possible(page, "查询")
    _wait_for_person_query(page, manager_name=manager_name, company_name=company_name)
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for page_no in range(1, max(1, max_pages) + 1):
        for row in _extract_vue_person_rows(page):
            key = "|".join(
                str(row.get(key_name) or "")
                for key_name in ("RY_ID", "REG_QYID", "REG_TYPE_NAME", "REG_SEAL_CODE")
            )
            if key not in seen_keys:
                seen_keys.add(key)
                rows.append(row)
        if page_no >= max_pages:
            break
        if _set_person_query_via_vue(
            page,
            manager_name=manager_name,
            company_name=company_name,
            page_no=page_no + 1,
        ):
            _wait_for_person_query(page, manager_name=manager_name, company_name=company_name)
            continue
        if not _click_next_page(page):
            break
        page.wait_for_timeout(1800)
    return rows


def _capture_person_detail_and_project_rows(
    page: Any,
    *,
    detail_url: str,
    manager_name: str,
    max_project_pages: int,
    retry_attempts: int,
) -> dict[str, Any]:
    diagnostics: list[str] = []
    attempts: list[dict[str, Any]] = []
    project_rows: list[dict[str, Any]] = []
    for attempt_no in range(1, max(1, retry_attempts) + 1):
        page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
        _wait_for_body_or_timeout(page, manager_name, timeout_ms=12000)
        body_text = _body_text(page)
        clicked_controls = _click_normal_verification_controls(page)
        if clicked_controls:
            page.wait_for_timeout(2500)
            body_text = _body_text(page)
        detail_challenge = _classify_page_challenge(body_text)
        if detail_challenge:
            diagnostics.append(f"personnel_detail_{detail_challenge}")
        attempts.append(
            {
                "attempt_no": attempt_no,
                "attempt_type": "open_personnel_detail",
                "detail_url": detail_url,
                "body_contains_target_person": manager_name in body_text,
                "clicked_normal_verification_controls": clicked_controls,
                "challenge_state": detail_challenge,
            }
        )
        try:
            _click_project_records_tab(page)
            page.wait_for_timeout(2500)
            clicked_project_controls = _click_normal_verification_controls(page)
            if clicked_project_controls:
                page.wait_for_timeout(3000)
            project_rows = _extract_vue_project_rows(page, manager_name=manager_name)
            project_rows = _read_more_project_pages(
                page,
                manager_name=manager_name,
                project_rows=project_rows,
                max_project_pages=max_project_pages,
            )
            project_body = _body_text(page)
            project_challenge = _classify_page_challenge(project_body)
            attempts.append(
                {
                    "attempt_no": attempt_no,
                    "attempt_type": "capture_personnel_project_records",
                    "detail_url": page.url,
                    "project_row_count": len(project_rows),
                    "clicked_normal_verification_controls": clicked_project_controls,
                    "challenge_state": project_challenge,
                }
            )
            if project_rows:
                break
            if project_challenge:
                diagnostics.append(f"personnel_project_records_{project_challenge}")
            else:
                diagnostics.append("personnel_project_records_empty_or_not_public")
        except Exception as exc:
            diagnostics.append(f"personnel_project_records_tab_unavailable:{exc}")
            attempts.append(
                {
                    "attempt_no": attempt_no,
                    "attempt_type": "capture_personnel_project_records",
                    "detail_url": page.url,
                    "project_row_count": len(project_rows),
                    "exception": str(exc),
                }
            )
        if project_rows:
            break
        page.wait_for_timeout(1200 * attempt_no)
    return {
        "project_rows": project_rows,
        "project_source_url": page.url,
        "nonfatal_diagnostics": diagnostics,
        "browser_attempts": attempts,
    }


def _click_project_records_tab(page: Any) -> None:
    for label in ("个人工程业绩", "工程业绩", "业绩信息"):
        try:
            page.get_by_text(label, exact=True).click(timeout=3000)
            return
        except Exception:
            continue
    page.get_by_text("个人工程业绩").first.click(timeout=5000)


def _click_normal_verification_controls(page: Any) -> list[str]:
    clicked: list[str] = []
    for label in (
        "继续访问",
        "重新验证",
        "刷新验证",
        "刷新",
        "重试",
        "确定",
        "确认",
        "我知道了",
        "关闭",
    ):
        try:
            locator = page.get_by_text(label, exact=True).first
            if not locator.is_visible(timeout=500):
                continue
            locator.click(timeout=1500)
            clicked.append(label)
        except Exception:
            continue
    return clicked


def _classify_page_challenge(body_text: str) -> str:
    text = str(body_text or "")
    if any(token in text for token in ("滑块", "拖动滑块", "验证码", "请完成验证", "安全验证")):
        return "captcha_or_slider_manual_required"
    if any(token in text for token in ("验证已过期", "校验失败", "令牌", "token", "Token")):
        return "challenge_or_token_required"
    return ""


def _read_more_project_pages(
    page: Any,
    *,
    manager_name: str,
    project_rows: list[dict[str, Any]],
    max_project_pages: int,
) -> list[dict[str, Any]]:
    rows = list(project_rows)
    seen = {
        str(row.get("project_id") or row.get("project_name") or row.get("raw_row") or "")
        for row in rows
    }
    for _page_no in range(2, max(1, max_project_pages) + 1):
        if not _click_next_page(page):
            break
        page.wait_for_timeout(2200)
        for row in _extract_vue_project_rows(page, manager_name=manager_name):
            key = str(row.get("project_id") or row.get("project_name") or row.get("raw_row") or "")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _open_text_if_possible(page: Any, text: str) -> None:
    if not text:
        return
    try:
        page.get_by_text(text, exact=True).first.click(timeout=2000)
    except Exception:
        try:
            page.get_by_text(text).first.click(timeout=2000)
        except Exception:
            return


def _body_text(page: Any) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=10000) or "")
    except Exception:
        return ""


def _fill_if_possible(page: Any, selector: str, value: str) -> bool:
    try:
        page.locator(selector).fill(value or "", timeout=5000)
        return True
    except Exception:
        return False


def _wait_for_body_or_timeout(page: Any, token: str, *, timeout_ms: int) -> None:
    if not token:
        page.wait_for_timeout(min(timeout_ms, 2000))
        return
    try:
        page.wait_for_function(
            "(token) => document.body && document.body.innerText.includes(token)",
            token,
            timeout=timeout_ms,
        )
    except Exception:
        page.wait_for_timeout(1200)


def _click_next_page(page: Any) -> bool:
    try:
        button = page.locator(".el-pagination .btn-next").last
        if button.is_disabled(timeout=500):
            return False
        button.click(timeout=3000)
        return True
    except Exception:
        return False


def _set_person_query_via_vue(
    page: Any,
    *,
    manager_name: str,
    company_name: str,
    page_no: int,
) -> bool:
    try:
        return bool(
            page.evaluate(
                """({managerName, companyName, pageNo}) => {
                  const components = Array.from(document.querySelectorAll('*'))
                    .map((el) => el.__vue__)
                    .filter((vm) => vm && vm.query && Object.prototype.hasOwnProperty.call(vm.query, 'ry_name'));
                  const vm = components.find((item) => typeof item.getPersonLsit === 'function');
                  if (!vm) return false;
                  vm.query.ry_name = managerName || '';
                  vm.query.ry_qymc = companyName || '';
                  vm.query.pg = pageNo || 1;
                  vm.query.pgsz = vm.query.pgsz || 15;
                  vm.getPersonLsit();
                  return true;
                }""",
                {
                    "managerName": manager_name,
                    "companyName": company_name,
                    "pageNo": page_no,
                },
            )
        )
    except Exception:
        return False


def _wait_for_person_query(page: Any, *, manager_name: str, company_name: str) -> None:
    token = company_name or manager_name
    # The JZSC Vue table keeps the previous page data until the encrypted API response
    # is decrypted. A short fixed wait prevents reading stale rows as query results.
    page.wait_for_timeout(3200)
    try:
        page.wait_for_function(
            """({token}) => {
              const components = Array.from(document.querySelectorAll('*'))
                .map((el) => el.__vue__)
                .filter((vm) => vm && vm.query && Object.prototype.hasOwnProperty.call(vm.query, 'ry_name'));
              const vm = components.find((item) => Array.isArray(item.tableData));
              if (!vm) return false;
              if (vm.loading) return false;
              if (!token) return true;
              return JSON.stringify(vm.tableData || []).includes(token) || (vm.tableData || []).length === 0;
            }""",
            {"token": token},
            timeout=12000,
        )
    except Exception:
        page.wait_for_timeout(1500)


def _extract_vue_company_rows(page: Any) -> list[dict[str, Any]]:
    rows = _extract_vue_rows_with_key(page, "QY_ID")
    return [row for row in rows if row.get("QY_NAME")]


def _extract_vue_person_rows(page: Any) -> list[dict[str, Any]]:
    rows = _extract_vue_rows_with_key(page, "RY_ID")
    return [row for row in rows if row.get("RY_NAME")]


def _extract_vue_project_rows(page: Any, *, manager_name: str) -> list[dict[str, Any]]:
    rows = _extract_vue_rows_with_any_key(
        page,
        ("PRJ_ID", "PROJECT_ID", "PROJECT_NAME", "PRJ_NAME", "XMMC", "PROJECT_CODE"),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        project_name = _first_non_empty(
            row.get("PROJECT_NAME"),
            row.get("PRJ_NAME"),
            row.get("XMMC"),
            row.get("GC_NAME"),
            row.get("PROJECTNAME"),
        )
        if not project_name:
            continue
        result.append(
            {
                "row_no": row.get("RN"),
                "project_id": _first_non_empty(
                    row.get("PROJECT_ID"),
                    row.get("PRJ_ID"),
                    row.get("PROJECT_CODE"),
                    row.get("PRJ_CODE"),
                    row.get("XMBH"),
                ),
                "project_name": project_name,
                "registered_unit_name": _first_non_empty(
                    row.get("QY_NAME"),
                    row.get("REG_QYMC"),
                    row.get("CONTRACTOR_NAME"),
                    row.get("CJDW"),
                ),
                "project_manager_name": _first_non_empty(
                    row.get("RY_NAME"),
                    row.get("PROJECT_MANAGER_NAME"),
                    row.get("XMJL"),
                    manager_name,
                ),
                "role": _first_non_empty(row.get("ROLE"), row.get("DUTY"), row.get("RY_ROLE")),
                "detail_url": _project_detail_url(row),
                "raw_row": " ".join(str(value) for value in row.values() if value not in (None, "")),
            }
        )
    return result


def _extract_vue_rows_with_key(page: Any, key_name: str) -> list[dict[str, Any]]:
    return _extract_vue_rows_with_any_key(page, (key_name,))


def _extract_vue_rows_with_any_key(page: Any, key_names: tuple[str, ...]) -> list[dict[str, Any]]:
    try:
        rows = page.evaluate(
            """(keyNames) => {
              const out = [];
              const seen = new Set();
              function pushRows(value) {
                if (!Array.isArray(value)) return;
                for (const row of value) {
                  if (!row || typeof row !== 'object') continue;
                  if (!keyNames.some((key) => Object.prototype.hasOwnProperty.call(row, key))) continue;
                  const payload = JSON.stringify(row);
                  if (seen.has(payload)) continue;
                  seen.add(payload);
                  out.push(row);
                }
              }
              for (const el of Array.from(document.querySelectorAll('*'))) {
                const vm = el.__vue__;
                if (!vm) continue;
                pushRows(vm.tableData);
                pushRows(vm.data);
                if (vm.pagination) pushRows(vm.pagination.tableData);
              }
              return out;
            }""",
            list(key_names),
        )
    except Exception:
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _pick_company_match(rows: list[Mapping[str, Any]], company_name: str) -> dict[str, Any] | None:
    normalized_target = _normalize_company(company_name)
    for row in rows:
        if _normalize_company(row.get("QY_NAME")) == normalized_target:
            return dict(row)
    for row in rows:
        row_name = _normalize_company(row.get("QY_NAME"))
        if normalized_target and (normalized_target in row_name or row_name in normalized_target):
            return dict(row)
    return None


def _pick_person_company_matches(
    rows: list[Mapping[str, Any]],
    manager_name: str,
    company_names: list[str],
) -> list[dict[str, Any]]:
    normalized_names = {_normalize_company(name) for name in company_names if _normalize_company(name)}
    matches: list[dict[str, Any]] = []
    for row in rows:
        if _normalize_person(row.get("RY_NAME")) != _normalize_person(manager_name):
            continue
        row_company = _normalize_company(row.get("REG_QYMC"))
        if row_company and row_company in normalized_names:
            matches.append(dict(row))
    return matches


def _person_search_row_to_rendered_row(row: Mapping[str, Any]) -> dict[str, Any]:
    row_no = _first_non_empty(row.get("RN"), row.get("row_no"), 1)
    person_name = str(_first_non_empty(row.get("RY_NAME"), row.get("person_name"), "") or "").strip()
    identity = str(_first_non_empty(row.get("RY_CARDNO"), row.get("masked_identity_no"), "") or "").strip()
    category = str(_first_non_empty(row.get("REG_TYPE_NAME"), row.get("registration_category"), "") or "").strip()
    registration = str(_first_non_empty(row.get("REG_SEAL_CODE"), row.get("registration_no"), "") or "").strip()
    row_text = " ".join(str(part) for part in (row_no, person_name, identity, category, registration) if str(part).strip())
    detail_url = _person_detail_url(row)
    return {
        "row_text": row_text,
        "row_no": _int_or_none(row_no),
        "person_name": person_name,
        "masked_identity_no": identity,
        "registration_category": category,
        "registration_no": registration,
        "detail_url": detail_url,
        "person_public_id": row.get("RY_ID"),
        "registered_unit_name": row.get("REG_QYMC"),
        "registration_at": _timestamp_ms_to_date(row.get("REG_SDATE")),
        "raw_source_row": dict(row),
    }


def _candidate_company_names(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    normalized = (
        raw.replace("（", "(")
        .replace("）", ")")
        .replace("；", ";")
        .replace("，", ";")
        .replace(",", ";")
        .replace("、", ";")
    )
    normalized = re.sub(r"\((主|成|联合体牵头方|联合体成员)\)", ";", normalized)
    parts = [
        re.sub(r"^\s*[\(（]?(主|成)[\)）]?\s*", "", part).strip()
        for part in re.split(r"[;]+", normalized)
        if part.strip()
    ]
    cleaned: list[str] = []
    for part in parts:
        part = re.sub(r"^\s*(主|成)\s*[:：]?\s*", "", part).strip()
        part = re.sub(r"\s+", "", part)
        if part and part not in cleaned:
            cleaned.append(part)
    if raw not in cleaned:
        cleaned.append(raw)
    return cleaned


def _normalize_company(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\((主|成|联合体牵头方|联合体成员)\)", "", text)
    text = re.sub(r"[;；,，、\s]", "", text)
    return text.upper()


def _normalize_person(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _person_detail_url(row: Mapping[str, Any]) -> str:
    person_id = str(_first_non_empty(row.get("RY_ID"), row.get("person_public_id"), "") or "").strip()
    if not person_id:
        return ""
    return f"https://jzsc.mohurd.gov.cn/data/person/detail?id={quote(person_id)}"


def _project_detail_url(row: Mapping[str, Any]) -> str:
    project_id = str(_first_non_empty(row.get("PROJECT_ID"), row.get("PRJ_ID"), row.get("ID"), "") or "").strip()
    if not project_id:
        return ""
    return f"https://jzsc.mohurd.gov.cn/data/project/detail?id={quote(project_id)}"


def _timestamp_ms_to_date(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    return datetime.fromtimestamp(number / 1000, tz=timezone.utc).date().isoformat()


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _capture_step_max_pages(capture_plan: Mapping[str, Any], step_id: str, *, default: int) -> int:
    for step in list(capture_plan.get("capture_steps") or []):
        if isinstance(step, Mapping) and step.get("step_id") == step_id:
            try:
                return int(step.get("max_pages") or default)
            except (TypeError, ValueError):
                return default
    return default


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe_strings(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))


def _extract_personnel_rows_from_text(text: str, manager_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    normalized_lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    name_pattern = re.escape(manager_name) if manager_name else r"[\u4e00-\u9fff]{2,8}"
    for line in normalized_lines:
        if manager_name and manager_name not in line:
            continue
        match = re.search(
            rf"(?P<row_no>\d+)\s+(?P<name>{name_pattern})\s+"
            r"(?P<identity>[0-9A-Za-z*]{8,})\s+(?P<category>.+?)\s+(?P<registration>[A-Za-z\u4e00-\u9fff]?\d[A-Za-z0-9\-]{4,})",
            line,
        )
        if not match:
            continue
        rows.append(
            {
                "row_text": line,
                "row_no": int(match.group("row_no")),
                "person_name": match.group("name"),
                "masked_identity_no": match.group("identity"),
                "registration_category": match.group("category"),
                "registration_no": match.group("registration"),
            }
        )
    return rows


def _extract_project_rows_from_text(text: str, manager_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    normalized_lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    for line in normalized_lines:
        if manager_name and manager_name not in line:
            continue
        if not any(token in line for token in ("工程", "项目", "施工", "监理", "设计")):
            continue
        rows.append({"row_text": line, "project_manager_name": manager_name})
    return rows


def _save_rows_snapshot(
    repository: ObjectStorageRepository,
    *,
    snapshot_kind: str,
    source_url: str,
    rows: list[Any],
    run_id: str,
    target_company_name: str,
    target_project_manager_name: str,
    role: str,
) -> str:
    payload = {
        "adapter_id": JZSC_BROWSER_EXECUTOR_ID,
        "snapshot_kind": snapshot_kind,
        "captured_at": utc_now_iso(),
        "source_url": source_url,
        "target_company_name": target_company_name,
        "target_project_manager_name": target_project_manager_name,
        "rows": rows,
    }
    snapshot_id = _stable_id("SNAP-JZSC-BROWSER", run_id, role, rows)
    repository.save_snapshot(
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        snapshot_id=snapshot_id,
        snapshot_kind=snapshot_kind,
        content_type="application/json; charset=utf-8",
        source_url_optional=source_url,
        source_family_optional="national_construction_market_platform",
        lineage_refs={
            "browser_execution_run_id": run_id,
            "target_company_name": target_company_name,
            "target_project_manager_name": target_project_manager_name,
            "snapshot_role": role,
        },
        adapter_id=JZSC_BROWSER_EXECUTOR_ID,
        source_visibility_state="PUBLIC_VISIBLE",
        fetch_mode="browser_rendered_capture",
        raw_snapshot_metadata={"rendered_row_count": len(rows)},
    )
    return snapshot_id


def _fail_closed(
    *,
    run_id: str,
    capture_plan: Mapping[str, Any],
    target_company_name: str,
    target_project_manager_name: str,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "adapter_id": JZSC_BROWSER_EXECUTOR_ID,
        "browser_execution_run_id": run_id,
        "capture_plan": dict(capture_plan),
        "target_company_name": target_company_name,
        "target_project_manager_name": target_project_manager_name,
        "executor_state": "FAIL_CLOSED",
        "readback_state": "REVIEW_REQUIRED",
        "live_browser_executed": False,
        "rendered_company_personnel_row_count": 0,
        "rendered_personnel_project_row_count": 0,
        "fail_closed_reasons": list(dict.fromkeys(reasons)),
        "customer_sellable_evidence_ready": False,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha1(
        json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:20]
    return f"{prefix}-{digest}"
