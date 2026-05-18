# Stage: stage4_verification
# Browser executor for JZSC company-first project-manager identity capture.

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from typing import Any, Callable, Mapping

from shared.utils import utc_now_iso
from storage.repositories.object_storage_repo import ObjectStorageRepository


JZSC_BROWSER_EXECUTOR_ID = "stage4.jzsc_company_first_browser_executor.v1"
JZSC_RENDERED_COMPANY_PERSONNEL_SNAPSHOT_KIND = "jzsc_rendered_company_personnel_rows"
JZSC_RENDERED_PERSONNEL_PROJECT_SNAPSHOT_KIND = "jzsc_rendered_personnel_project_rows"
JZSC_COMPANY_SEARCH_PAGE_NOT_LOADED = "jzsc_company_search_page_not_loaded"
JZSC_COMPANY_SEARCH_LOADED_BUT_NO_VUE_DATA = "jzsc_company_search_loaded_but_no_vue_data"
JZSC_COMPANY_SEARCH_PARAMETER_INVALID_OR_NOT_APPLIED = (
    "jzsc_company_search_parameter_invalid_or_not_applied"
)
JZSC_COMPANY_SEARCH_DOM_OR_API_STRUCTURE_CHANGED = (
    "jzsc_company_search_dom_or_api_structure_changed"
)
JZSC_COMPANY_SEARCH_PUBLIC_PLATFORM_EMPTY_RESULT = (
    "jzsc_company_search_public_platform_returned_empty_result"
)
JZSC_COMPANY_SEARCH_SUSPECTED_CAPTCHA_OR_ACCESS_BLOCK = (
    "jzsc_company_search_suspected_captcha_or_access_block"
)
JZSC_COMPANY_SEARCH_ROWS_RETURNED_WITHOUT_TARGET_MATCH = (
    "jzsc_company_search_rows_returned_without_target_match"
)
JZSC_COMPANY_SEARCH_OK_COMPANY_ROW_MATCHED = "jzsc_company_search_ok_company_row_matched"

BrowserRunner = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def classify_jzsc_company_search_diagnostics(
    *,
    page_loaded: bool,
    body_text: str,
    target_company_name: str,
    query_parameter_present: bool,
    challenge_state: str = "",
    vue_component_count: int = 0,
    company_row_count: int = 0,
    company_match_found: bool = False,
    extraction_error: str = "",
) -> dict[str, Any]:
    body = str(body_text or "")
    body_length = len(body)
    reasons: list[str] = []
    if challenge_state:
        reasons.append(JZSC_COMPANY_SEARCH_SUSPECTED_CAPTCHA_OR_ACCESS_BLOCK)
    if not page_loaded or body_length == 0:
        reasons.append(JZSC_COMPANY_SEARCH_PAGE_NOT_LOADED)
    if extraction_error:
        reasons.append(JZSC_COMPANY_SEARCH_DOM_OR_API_STRUCTURE_CHANGED)
    if page_loaded and body_length > 0 and vue_component_count == 0:
        reasons.append(JZSC_COMPANY_SEARCH_LOADED_BUT_NO_VUE_DATA)
    if not query_parameter_present:
        reasons.append(JZSC_COMPANY_SEARCH_PARAMETER_INVALID_OR_NOT_APPLIED)
    if company_row_count <= 0 and not reasons:
        if _body_indicates_empty_result(body) or (
            target_company_name and target_company_name in body
        ):
            reasons.append(JZSC_COMPANY_SEARCH_PUBLIC_PLATFORM_EMPTY_RESULT)
        else:
            reasons.append(JZSC_COMPANY_SEARCH_DOM_OR_API_STRUCTURE_CHANGED)
    if company_row_count > 0 and not company_match_found:
        reasons.append(JZSC_COMPANY_SEARCH_ROWS_RETURNED_WITHOUT_TARGET_MATCH)

    reasons = _dedupe_strings(reasons)
    if company_match_found:
        state = "PASS"
        status_code = JZSC_COMPANY_SEARCH_OK_COMPANY_ROW_MATCHED
    elif challenge_state:
        state = "BLOCKED_REVIEW_REQUIRED"
        status_code = "SUSPECTED_CAPTCHA_OR_ACCESS_BLOCK"
    elif reasons:
        state = "FAIL_CLOSED_QUERY_ERROR"
        status_code = reasons[0]
    else:
        state = "FAIL_CLOSED_QUERY_ERROR"
        status_code = JZSC_COMPANY_SEARCH_DOM_OR_API_STRUCTURE_CHANGED
    return {
        "diagnostic_state": state,
        "diagnostic_status_code": status_code,
        "failure_reasons": reasons,
        "body_length": body_length,
        "challenge_state": challenge_state,
        "vue_component_count": vue_component_count,
        "company_row_count": company_row_count,
        "company_match_found": company_match_found,
    }


def diagnose_jzsc_company_search_health(
    company_names: list[str],
    *,
    entry_url: str = "https://jzsc.mohurd.gov.cn/data/company",
    snapshot_dir: str | None = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {
            "adapter_id": JZSC_BROWSER_EXECUTOR_ID,
            "diagnostic_run_id": _stable_id("JZSC-SOURCE-HEALTH", company_names, entry_url),
            "entry_url": entry_url,
            "captured_at": utc_now_iso(),
            "source_health_status": "UNTRUSTED_PLAYWRIGHT_UNAVAILABLE",
            "failure_reasons": [f"playwright_unavailable:{exc}"],
            "company_results": [],
            "control_company_any_row": False,
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
        }

    names = _dedupe_strings(company_names)
    run_id = _stable_id("JZSC-SOURCE-HEALTH", names, entry_url, utc_now_iso())
    snapshot_root = Path(snapshot_dir) if snapshot_dir else None
    if snapshot_root:
        snapshot_root.mkdir(parents=True, exist_ok=True)
    company_results: list[dict[str, Any]] = []
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
            for index, company_name in enumerate(names, start=1):
                result = _search_company_diagnostic(
                    page,
                    entry_url=entry_url,
                    company_name=company_name,
                    snapshot_dir=snapshot_root,
                    run_id=run_id,
                    index=index,
                )
                company_results.append(result)
        finally:
            browser.close()

    any_rows = any(int(item.get("company_row_count") or 0) > 0 for item in company_results)
    any_match = any(bool(item.get("company_match_found")) for item in company_results)
    blocked = any(
        item.get("diagnostic_state") == "BLOCKED_REVIEW_REQUIRED"
        for item in company_results
    )
    if any_match:
        health_status = "HEALTHY_AT_LEAST_ONE_CONTROL_COMPANY_RETURNED"
    elif any_rows:
        health_status = "UNTRUSTED_ONLY_NON_MATCHING_DEFAULT_ROWS_RETURNED"
    elif blocked:
        health_status = "UNTRUSTED_BLOCKED_BY_CHALLENGE_OR_ACCESS_CONTROL"
    else:
        health_status = "UNTRUSTED_NO_CONTROL_COMPANY_ROWS"
    return {
        "adapter_id": JZSC_BROWSER_EXECUTOR_ID,
        "diagnostic_run_id": run_id,
        "entry_url": entry_url,
        "captured_at": utc_now_iso(),
        "company_count": len(company_results),
        "source_health_status": health_status,
        "control_company_any_row": any_rows,
        "control_company_any_match": any_match,
        "company_results": company_results,
        "failure_reasons": _dedupe_strings(
            [
                reason
                for item in company_results
                for reason in list(item.get("failure_reasons") or [])
            ]
        ),
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


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
    required_registration_category: str | None = None,
    required_registration_profession_keywords: list[str] | None = None,
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
    capture_plan["required_registration_category_optional"] = required_registration_category
    capture_plan["required_registration_profession_keywords"] = list(
        required_registration_profession_keywords or []
    )
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
    route_nonfatal_reasons: list[str] = []
    if company_rows:
        fail_closed_reasons, route_nonfatal_reasons = _downgrade_company_search_route_failures_after_personnel_match(
            fail_closed_reasons
        )

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
            dict.fromkeys(
                [
                    *[
                        str(reason)
                        for reason in list(browser_result.get("nonfatal_diagnostics") or [])
                        if str(reason).strip()
                    ],
                    *route_nonfatal_reasons,
                ]
            )
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
            required_registration_category=required_registration_category,
            required_registration_profession_keywords=required_registration_profession_keywords,
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


def _downgrade_company_search_route_failures_after_personnel_match(
    reasons: list[str],
) -> tuple[list[str], list[str]]:
    route_level_reasons = {
        JZSC_COMPANY_SEARCH_ROWS_RETURNED_WITHOUT_TARGET_MATCH,
        "company_search_result_not_found_after_three_attempts",
    }
    hard_reasons: list[str] = []
    nonfatal: list[str] = []
    for reason in reasons:
        if reason in route_level_reasons:
            nonfatal.append(f"company_search_route_failed_but_personnel_unit_match_captured:{reason}")
            continue
        hard_reasons.append(reason)
    return list(dict.fromkeys(hard_reasons)), list(dict.fromkeys(nonfatal))


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
            company_rows, personnel_attempts = _resolve_personnel_rows_by_person_company_direct(
                page,
                manager_name=manager_name,
                company_names=company_candidates,
                retry_attempts=personnel_retry_attempts,
            )
            browser_attempts.extend(personnel_attempts)
            personnel_url = page.url
            matched_company_name = (
                _matched_registered_unit_from_rendered_rows(company_rows)
                or (company_candidates[0] if company_candidates else company_name)
            )
            matched_company_id = ""
            company_match: dict[str, Any] | None = None
            company_search_failure_reasons: list[str] = []
            if not company_rows:
                for attempt_no, candidate_company in enumerate(company_candidates[:3], start=1):
                    search_result = _search_company_diagnostic_with_retry(
                        page,
                        entry_url=entry_url,
                        company_name=candidate_company,
                        retry_attempts=personnel_retry_attempts,
                    )
                    rows = list(search_result.get("company_rows") or [])
                    attempt_failure_reasons = [
                        str(reason)
                        for reason in list(search_result.get("failure_reasons") or [])
                        if str(reason).strip()
                    ]
                    company_search_failure_reasons.extend(attempt_failure_reasons)
                    browser_attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "attempt_type": "company_search",
                            "query_company_name": candidate_company,
                            "result_count": len(rows),
                            "diagnostic_state": search_result.get("diagnostic_state"),
                            "diagnostic_status_code": search_result.get("diagnostic_status_code"),
                            "failure_reasons": attempt_failure_reasons,
                            "query_url": search_result.get("query_url"),
                            "final_url": search_result.get("final_url"),
                            "page_title": search_result.get("page_title"),
                            "challenge_state": search_result.get("challenge_state"),
                            "vue_component_count": search_result.get("vue_component_count"),
                            "company_row_count": search_result.get("company_row_count"),
                            "body_key_text": search_result.get("body_key_text"),
                        }
                    )
                    company_match = _pick_company_match(rows, candidate_company)
                    if company_match:
                        break
                if not company_match:
                    failure_reasons.extend(_dedupe_strings(company_search_failure_reasons))
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
    return list(
        _search_company_diagnostic(
            page,
            entry_url=entry_url,
            company_name=company_name,
        ).get("company_rows")
        or []
    )


def _search_company_diagnostic_with_retry(
    page: Any,
    *,
    entry_url: str,
    company_name: str,
    retry_attempts: int,
) -> dict[str, Any]:
    last_result: dict[str, Any] = {}
    for retry_no in range(1, max(1, retry_attempts) + 1):
        result = _search_company_diagnostic(
            page,
            entry_url=entry_url,
            company_name=company_name,
        )
        result["retry_no"] = retry_no
        last_result = result
        if result.get("company_rows"):
            return result
        page.wait_for_timeout(900 * retry_no)
    return last_result


def _search_company_diagnostic(
    page: Any,
    *,
    entry_url: str,
    company_name: str,
    snapshot_dir: Path | None = None,
    run_id: str = "",
    index: int = 0,
) -> dict[str, Any]:
    query_url = f"{entry_url.split('?', 1)[0]}?complexname={quote(company_name or '')}"
    final_url = ""
    page_title = ""
    body_text = ""
    page_loaded = False
    navigation_error = ""
    extraction_error = ""
    submission_state = ""
    company_rows: list[dict[str, Any]] = []
    vue_component_count = 0
    if not company_name:
        diagnostic = classify_jzsc_company_search_diagnostics(
            page_loaded=False,
            body_text="",
            target_company_name=company_name,
            query_parameter_present=False,
        )
        return {
            **diagnostic,
            "query_company_name": company_name,
            "query_url": query_url,
            "final_url": final_url,
            "page_title": page_title,
            "body_key_text": "",
            "company_rows": [],
            "company_rows_preview": [],
            "navigation_error": "company_name_missing",
            "vue_data_extraction_state": "NOT_RUN_COMPANY_NAME_MISSING",
        }
    try:
        page.goto(entry_url.split("?", 1)[0], wait_until="domcontentloaded", timeout=60000)
        page_loaded = True
        page.wait_for_timeout(2500)
        submission_state = _submit_company_keyword_query(page, company_name)
        company_rows = _extract_company_rows_until_target_or_default(
            page,
            company_name,
            timeout_ms=8000,
        )
    except Exception as exc:
        navigation_error = str(exc)
    try:
        final_url = str(page.url or "")
    except Exception:
        final_url = ""
    try:
        page_title = str(page.title() or "")
    except Exception:
        page_title = ""
    body_text = _body_text(page)
    challenge_state = _classify_page_challenge(body_text)
    try:
        vue_component_count = _count_vue_components(page)
        latest_rows = _extract_vue_company_rows(page)
        if not company_rows or (
            latest_rows
            and not _pick_company_match(company_rows, company_name)
            and _pick_company_match(latest_rows, company_name)
        ):
            company_rows = latest_rows
    except Exception as exc:
        extraction_error = str(exc)
        if not company_rows:
            company_rows = []
    company_match = _pick_company_match(company_rows, company_name)
    diagnostic = classify_jzsc_company_search_diagnostics(
        page_loaded=page_loaded,
        body_text=body_text,
        target_company_name=company_name,
        query_parameter_present="complexname=" in final_url or "complexname=" in query_url,
        challenge_state=challenge_state,
        vue_component_count=vue_component_count,
        company_row_count=len(company_rows),
        company_match_found=bool(company_match),
        extraction_error=extraction_error,
    )
    html_snapshot_path = ""
    screenshot_path = ""
    if snapshot_dir:
        prefix = _safe_snapshot_prefix(run_id=run_id, index=index, company_name=company_name)
        html_path = snapshot_dir / f"{prefix}.html"
        png_path = snapshot_dir / f"{prefix}.png"
        try:
            html_path.write_text(page.content(), encoding="utf-8")
            html_snapshot_path = str(html_path)
        except Exception as exc:
            diagnostic["failure_reasons"] = _dedupe_strings(
                [*list(diagnostic.get("failure_reasons") or []), f"html_snapshot_write_failed:{exc}"]
            )
        try:
            page.screenshot(path=str(png_path), full_page=True)
            screenshot_path = str(png_path)
        except Exception as exc:
            diagnostic["failure_reasons"] = _dedupe_strings(
                [*list(diagnostic.get("failure_reasons") or []), f"screenshot_write_failed:{exc}"]
            )
    return {
        **diagnostic,
        "query_company_name": company_name,
        "query_url": query_url,
        "final_url": final_url,
        "page_title": page_title,
        "body_key_text": _body_key_text(body_text, company_name),
        "body_contains_company_name": bool(company_name and company_name in body_text),
        "company_rows": company_rows,
        "company_rows_preview": company_rows[:5],
        "matched_company_name_optional": (company_match or {}).get("QY_NAME"),
        "matched_company_public_id_optional": (company_match or {}).get("QY_ID"),
        "navigation_error": navigation_error,
        "extraction_error": extraction_error,
        "company_search_submission_state": submission_state,
        "vue_data_extraction_state": _vue_data_extraction_state(
            vue_component_count=vue_component_count,
            company_row_count=len(company_rows),
            extraction_error=extraction_error,
        ),
        "html_snapshot_path": html_snapshot_path,
        "screenshot_path": screenshot_path,
    }


def _search_company_rows_with_retry(
    page: Any,
    *,
    entry_url: str,
    company_name: str,
    retry_attempts: int,
) -> list[dict[str, Any]]:
    return list(
        _search_company_diagnostic_with_retry(
            page,
            entry_url=entry_url,
            company_name=company_name,
            retry_attempts=retry_attempts,
        ).get("company_rows")
        or []
    )


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


def _submit_company_keyword_query(page: Any, company_name: str) -> str:
    if not company_name:
        return "NOT_RUN_COMPANY_NAME_MISSING"
    selector = 'input[placeholder="请输入关键词，例如企业名称、统一社会信用代码"]'
    try:
        page.locator(selector).fill(company_name, timeout=5000)
        page.locator("#query-btn").click(timeout=5000)
        return "HEADER_KEYWORD_SEARCH_CLICKED"
    except Exception as exc:
        if _set_company_query_via_vue(page, company_name):
            return "COMPANY_QUERY_VIA_VUE"
        _submit_company_query(page, company_name)
        return f"COMPANY_QUERY_FALLBACK_ATTEMPTED:{exc}"


def _set_company_query_via_vue(page: Any, company_name: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """(companyName) => {
                  const components = Array.from(document.querySelectorAll('*'))
                    .map((el) => el.__vue__)
                    .filter((vm) => vm && vm.query && Object.prototype.hasOwnProperty.call(vm.query, 'complexname'));
                  const vm = components.find((item) => typeof item.queryHandler === 'function' || typeof item.getCompanyList === 'function');
                  if (!vm) return false;
                  vm.query.complexname = companyName || '';
                  vm.query.pg = 1;
                  vm.query.pgsz = vm.query.pgsz || 15;
                  if (typeof vm.queryHandler === 'function') {
                    vm.queryHandler();
                  } else {
                    vm.getCompanyList();
                  }
                  return true;
                }""",
                company_name,
            )
        )
    except Exception:
        return False


def _wait_for_company_search_rows_or_idle(
    page: Any,
    company_name: str,
    *,
    timeout_ms: int,
) -> None:
    try:
        page.wait_for_function(
            """(companyName) => {
              const normalizedTarget = String(companyName || '').replace(/[\\s;；,，、]/g, '');
              const components = Array.from(document.querySelectorAll('*'))
                .map((el) => el.__vue__)
                .filter((vm) => !!vm);
              for (const vm of components) {
                if (!Array.isArray(vm.tableData)) continue;
                const rows = vm.tableData.filter((row) => row && typeof row === 'object' && Object.prototype.hasOwnProperty.call(row, 'QY_ID'));
                if (rows.some((row) => {
                  const name = String(row.QY_NAME || '').replace(/[\\s;；,，、]/g, '');
                  return normalizedTarget && (name === normalizedTarget || name.includes(normalizedTarget) || normalizedTarget.includes(name));
                })) {
                  return true;
                }
                if (vm.query && Object.prototype.hasOwnProperty.call(vm.query, 'complexname') && vm.loading === false && rows.length === 0) {
                  return true;
                }
              }
              return false;
            }""",
            company_name,
            timeout=timeout_ms,
        )
    except Exception:
        page.wait_for_timeout(500)


def _extract_company_rows_until_target_or_default(
    page: Any,
    company_name: str,
    *,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + max(1, timeout_ms) / 1000
    last_rows: list[dict[str, Any]] = []
    first_non_empty_rows: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        rows = _extract_vue_company_rows(page)
        if rows:
            last_rows = rows
            if not first_non_empty_rows:
                first_non_empty_rows = rows
            if _pick_company_match(rows, company_name):
                return rows
        try:
            page.wait_for_timeout(80)
        except Exception:
            break
    return last_rows or first_non_empty_rows


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


def _resolve_personnel_rows_by_person_company_direct(
    page: Any,
    *,
    manager_name: str,
    company_names: list[str],
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
                    "attempt_type": "person_name_with_company_query",
                    "query_person_name": manager_name,
                    "query_company_name": company_name,
                    "result_count": len(rows),
                    "matched_count": len(matches),
                }
            )
            if matches:
                return [_person_search_row_to_rendered_row(row) for row in matches], attempts
        page.wait_for_timeout(500 * retry_no)
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


def _count_vue_components(page: Any) -> int:
    try:
        return int(
            page.evaluate(
                """() => Array.from(document.querySelectorAll('*'))
                  .map((el) => el.__vue__)
                  .filter((vm) => !!vm).length"""
            )
            or 0
        )
    except Exception:
        return 0


def _body_key_text(body_text: str, company_name: str) -> str:
    text = str(body_text or "")
    normalized_lines = [" ".join(line.split()) for line in text.splitlines()]
    tokens = [company_name, "验证码", "安全验证", "暂无", "未查询", "企业名称", "查询"]
    selected = [
        line
        for line in normalized_lines
        if line and any(token and token in line for token in tokens)
    ]
    if not selected:
        selected = [line for line in normalized_lines if line][:8]
    return "\n".join(selected[:12])[:1200]


def _body_indicates_empty_result(body_text: str) -> bool:
    text = str(body_text or "")
    return any(
        token in text
        for token in (
            "暂无数据",
            "暂无结果",
            "未查询到",
            "无查询结果",
            "没有查询到",
            "没有相关",
            "查询结果为空",
        )
    )


def _vue_data_extraction_state(
    *,
    vue_component_count: int,
    company_row_count: int,
    extraction_error: str,
) -> str:
    if extraction_error:
        return "EXTRACT_ERROR"
    if vue_component_count <= 0:
        return "NO_VUE_COMPONENTS"
    if company_row_count <= 0:
        return "VUE_COMPONENTS_FOUND_NO_COMPANY_ROWS"
    return "VUE_COMPANY_ROWS_EXTRACTED"


def _safe_snapshot_prefix(*, run_id: str, index: int, company_name: str) -> str:
    digest = hashlib.sha1(f"{run_id}|{index}|{company_name}".encode("utf-8")).hexdigest()[:10]
    safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(company_name or "").strip())
    safe_name = safe_name[:48] or "company"
    return f"{index:02d}_{safe_name}_{digest}"


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
        "registration_profession": _first_non_empty(
            row.get("REG_PROF_NAME"),
            row.get("REG_PROF"),
            row.get("ZY_NAME"),
            row.get("PROFESSION_NAME"),
        ),
        "registration_at": _timestamp_ms_to_date(row.get("REG_SDATE")),
        "raw_source_row": dict(row),
    }


def _matched_registered_unit_from_rendered_rows(rows: list[Mapping[str, Any]]) -> str:
    for row in rows:
        value = str(
            _first_non_empty(
                row.get("registered_unit_name"),
                row.get("registered_unit_name_optional"),
                row.get("REG_QYMC"),
                "",
            )
            or ""
        ).strip()
        if value:
            return value
    return ""


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
