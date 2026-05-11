from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso


JZSC_PERSONNEL_ROUTE_BENCHMARK_MANIFEST_KIND = "jzsc_personnel_route_benchmark_manifest"
JZSC_PERSONNEL_ROUTE_BENCHMARK_VERSION = 1
DEFAULT_STAGE4_EXECUTION_ROOT = Path(
    "tmp/evaluation-real-samples/guangzhou-company-first-stage4-execution-v4-merged"
)
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/jzsc-personnel-route-benchmark-v1")


def build_jzsc_personnel_route_benchmark(
    *,
    stage4_execution_root: str | Path = DEFAULT_STAGE4_EXECUTION_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    max_targets: int = 12,
    max_name_only_pages: int = 3,
    execute: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    in_root = Path(stage4_execution_root)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    source_path = in_root / "company-first-stage4-execution.json"
    payload = _load_json(source_path)
    targets = _load_targets(payload)[: max(1, int(max_targets or 1))]
    if execute:
        items = _execute_targets(targets, max_name_only_pages=max(1, int(max_name_only_pages or 1)))
    else:
        items = [_dry_run_target(target, max_name_only_pages=max_name_only_pages) for target in targets]
    summary = _summary(items)
    manifest = {
        "manifest_version": JZSC_PERSONNEL_ROUTE_BENCHMARK_VERSION,
        "manifest_kind": JZSC_PERSONNEL_ROUTE_BENCHMARK_MANIFEST_KIND,
        "adapter_id": "jzsc-personnel-route-benchmark-v1",
        "created_at": created,
        "source_stage4_execution_json": str(source_path),
        "execute_enabled": bool(execute),
        "max_targets": int(max_targets or 0),
        "max_name_only_pages": int(max_name_only_pages or 0),
        "target_count": len(targets),
        "items": items,
        "summary": summary,
        "safety": {
            "download_enabled": False,
            "llm_execution_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "manifest_stores_raw_html_or_blob": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    result = {
        "benchmark_state": "EXECUTED" if execute else "DRY_RUN",
        "manifest": manifest,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    (out_root / "jzsc-personnel-route-benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _execute_targets(targets: list[dict[str, Any]], *, max_name_only_pages: int) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return [
            {
                **target,
                "routes": [
                    _route_error("playwright_unavailable", f"playwright_unavailable:{exc}")
                ],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            for target in targets
        ]

    items: list[dict[str, Any]] = []
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
            for target in targets:
                routes = [
                    _run_person_route(
                        page,
                        route_name="person_name_with_company_query",
                        target=target,
                        company_name=str(target.get("candidate_company_name") or ""),
                        max_pages=1,
                    ),
                    _run_person_route(
                        page,
                        route_name="person_name_only_filter_company",
                        target=target,
                        company_name="",
                        max_pages=max_name_only_pages,
                    ),
                    _run_company_then_person_route(page, target=target),
                ]
                items.append(
                    {
                        **target,
                        "routes": routes,
                        "recommended_default_route": _recommended_route(routes),
                        "fallback_route_order": _fallback_order(routes),
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                )
        finally:
            browser.close()
    return items


def _run_person_route(
    page: Any,
    *,
    route_name: str,
    target: Mapping[str, Any],
    company_name: str,
    max_pages: int,
) -> dict[str, Any]:
    from stage4_verification.jzsc_browser_executor import (
        _body_text,
        _classify_page_challenge,
        _person_search_row_to_rendered_row,
        _pick_person_company_matches,
        _search_person_rows,
    )

    started = time.perf_counter()
    person_name = str(target.get("responsible_person_name") or "")
    target_company = str(target.get("candidate_company_name") or "")
    try:
        rows = _search_person_rows(
            page,
            manager_name=person_name,
            company_name=company_name,
            max_pages=max(1, int(max_pages or 1)),
        )
        matches = _pick_person_company_matches(rows, person_name, [target_company])
        rendered = [_person_search_row_to_rendered_row(row) for row in matches]
        detail = _open_first_detail_probe(page, rendered, person_name=person_name)
        return {
            "route_name": route_name,
            "query_person_name": person_name,
            "query_company_name": company_name,
            "page_limit": max_pages,
            "row_count": len(rows),
            "matched_count": len(matches),
            "detail_open_state": detail["detail_open_state"],
            "detail_contains_person": detail["detail_contains_person"],
            "detail_challenge_state": detail["detail_challenge_state"],
            "matched_registered_units": _dedupe(
                str(row.get("REG_QYMC") or row.get("registered_unit_name") or "")
                for row in matches
            ),
            "candidate_certificate_no_options": _dedupe(
                str(row.get("REG_SEAL_CODE") or row.get("registration_no") or "")
                for row in matches
            ),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "route_state": "MATCHED" if matches else "NO_MATCH",
            "detail_verification_state": (
                "DETAIL_PERSON_TEXT_CONFIRMED"
                if detail["detail_contains_person"]
                else "DETAIL_OPENED_TEXT_NOT_CONFIRMED"
                if detail["detail_open_state"] == "DETAIL_OPENED"
                else detail["detail_open_state"]
            ),
            "failure_reasons": [] if matches else ["person_company_match_not_found"],
        }
    except Exception as exc:
        body = _body_text(page)
        return {
            "route_name": route_name,
            "query_person_name": person_name,
            "query_company_name": company_name,
            "page_limit": max_pages,
            "row_count": 0,
            "matched_count": 0,
            "detail_open_state": "NOT_RUN",
            "detail_contains_person": False,
            "detail_challenge_state": _classify_page_challenge(body),
            "matched_registered_units": [],
            "candidate_certificate_no_options": [],
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "route_state": "ERROR",
            "failure_reasons": [f"route_exception:{exc}"],
        }


def _run_company_then_person_route(page: Any, *, target: Mapping[str, Any]) -> dict[str, Any]:
    from stage4_verification.jzsc_browser_executor import (
        _candidate_company_names,
        _pick_company_match,
        _search_company_diagnostic,
    )

    started = time.perf_counter()
    target_company = str(target.get("candidate_company_name") or "")
    company_candidates = _candidate_company_names(target_company)[:3]
    matched_company = ""
    company_attempts: list[dict[str, Any]] = []
    for company in company_candidates:
        result = _search_company_diagnostic(
            page,
            entry_url="https://jzsc.mohurd.gov.cn/data/company",
            company_name=company,
        )
        rows = list(result.get("company_rows") or [])
        match = _pick_company_match(rows, company)
        company_attempts.append(
            {
                "query_company_name": company,
                "row_count": len(rows),
                "matched": bool(match),
                "diagnostic_state": result.get("diagnostic_state", ""),
                "failure_reasons": list(result.get("failure_reasons") or []),
            }
        )
        if match:
            matched_company = str(match.get("QY_NAME") or company)
            break
    route = _run_person_route(
        page,
        route_name="company_search_then_person_query",
        target=target,
        company_name=matched_company or target_company,
        max_pages=1,
    )
    route["company_search_attempts"] = company_attempts
    route["company_search_matched_name"] = matched_company
    route["duration_ms"] = int((time.perf_counter() - started) * 1000)
    if not matched_company:
        route["failure_reasons"] = _dedupe(
            [*list(route.get("failure_reasons") or []), "company_search_match_not_found"]
        )
    return route


def _open_first_detail_probe(page: Any, rendered_rows: list[Mapping[str, Any]], *, person_name: str) -> dict[str, Any]:
    from stage4_verification.jzsc_browser_executor import _body_text, _classify_page_challenge

    detail_url = ""
    for row in rendered_rows:
        detail_url = str(row.get("detail_url") or row.get("personnel_detail_url_optional") or "").strip()
        if detail_url:
            break
    if not detail_url:
        return {
            "detail_open_state": "DETAIL_URL_MISSING",
            "detail_contains_person": False,
            "detail_challenge_state": "",
        }
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        body = _body_text(page)
        return {
            "detail_open_state": "DETAIL_OPENED",
            "detail_contains_person": bool(person_name and person_name in body),
            "detail_challenge_state": _classify_page_challenge(body),
        }
    except Exception as exc:
        body = _body_text(page)
        return {
            "detail_open_state": f"DETAIL_OPEN_FAILED:{exc}",
            "detail_contains_person": False,
            "detail_challenge_state": _classify_page_challenge(body),
        }


def _recommended_route(routes: list[Mapping[str, Any]]) -> str:
    matched = [route for route in routes if route.get("route_state") == "MATCHED"]
    if not matched:
        return "NO_ROUTE_MATCHED"
    ordered = sorted(matched, key=lambda route: int(route.get("duration_ms") or 0))
    return str(ordered[0].get("route_name") or "")


def _fallback_order(routes: list[Mapping[str, Any]]) -> list[str]:
    preferred = [
        "person_name_with_company_query",
        "company_search_then_person_query",
        "person_name_only_filter_company",
    ]
    by_name = {str(route.get("route_name") or ""): route for route in routes}
    return [name for name in preferred if name in by_name]


def _dry_run_target(target: Mapping[str, Any], *, max_name_only_pages: int) -> dict[str, Any]:
    routes = [
        {
            "route_name": "person_name_with_company_query",
            "query_person_name": target.get("responsible_person_name", ""),
            "query_company_name": target.get("candidate_company_name", ""),
            "page_limit": 1,
            "route_state": "PLANNED_NOT_EXECUTED",
        },
        {
            "route_name": "person_name_only_filter_company",
            "query_person_name": target.get("responsible_person_name", ""),
            "query_company_name": "",
            "page_limit": max_name_only_pages,
            "route_state": "PLANNED_NOT_EXECUTED",
        },
        {
            "route_name": "company_search_then_person_query",
            "query_person_name": target.get("responsible_person_name", ""),
            "query_company_name": target.get("candidate_company_name", ""),
            "page_limit": 1,
            "route_state": "PLANNED_NOT_EXECUTED",
        },
    ]
    return {
        **dict(target),
        "routes": routes,
        "recommended_default_route": "NOT_EXECUTED",
        "fallback_route_order": _fallback_order(routes),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _route_error(route_name: str, reason: str) -> dict[str, Any]:
    return {
        "route_name": route_name,
        "route_state": "ERROR",
        "failure_reasons": [reason],
        "duration_ms": 0,
    }


def _load_targets(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = list((payload.get("manifest") or {}).get("items") or [])
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in items:
        item = dict(raw or {})
        if item.get("supplement_after_execution_state") != "COMPANY_FIRST_CERTIFICATE_RESOLVED":
            continue
        company = str(item.get("candidate_company_name") or "").strip()
        person = str(item.get("responsible_person_name") or "").strip()
        if not company or not person:
            continue
        key = (
            str(item.get("project_id") or ""),
            str(item.get("candidate_group_id") or ""),
            company,
            person,
        )
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            {
                "project_id": item.get("project_id", ""),
                "project_name": item.get("project_name", ""),
                "candidate_group_id": item.get("candidate_group_id", ""),
                "candidate_group_order": item.get("candidate_group_order", ""),
                "candidate_company_name": company,
                "responsible_person_name": person,
                "source_certificate_no_optional": item.get("source_certificate_no_optional", ""),
                "resolved_certificate_no_optional": item.get("resolved_certificate_no_optional", ""),
            }
        )
    return targets


def _summary(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    route_names = _dedupe(
        str(route.get("route_name") or "")
        for item in items
        for route in list(item.get("routes") or [])
    )
    route_summary: dict[str, dict[str, Any]] = {}
    for route_name in route_names:
        routes = [
            route
            for item in items
            for route in list(item.get("routes") or [])
            if route.get("route_name") == route_name
        ]
        attempts = len(routes)
        matched = sum(1 for route in routes if route.get("route_state") == "MATCHED")
        durations = [int(route.get("duration_ms") or 0) for route in routes if route.get("duration_ms") not in (None, "")]
        route_summary[route_name] = {
            "attempt_count": attempts,
            "matched_count": matched,
            "match_rate": round(matched / attempts, 4) if attempts else 0.0,
            "detail_verified_count": sum(1 for route in routes if route.get("detail_contains_person")),
            "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            "failure_reasons": _dedupe(
                str(reason)
                for route in routes
                for reason in list(route.get("failure_reasons") or [])
            ),
        }
    recommendation = "KEEP_COMPANY_AND_NAME_ROUTES_AS_FALLBACKS"
    if route_summary:
        matched_routes = [
            (name, data)
            for name, data in route_summary.items()
            if data.get("matched_count")
        ]
        if matched_routes:
            best_name, _best_data = sorted(
                matched_routes,
                key=lambda entry: (
                    -float(entry[1].get("match_rate") or 0),
                    int(entry[1].get("avg_duration_ms") or 0),
                ),
            )[0]
            recommendation = f"DEFAULT_{best_name.upper()}_WITH_OTHER_ROUTES_AS_FALLBACK"
    return {
        "target_count": len(items),
        "route_summary": route_summary,
        "recommended_policy": recommendation,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark JZSC personnel lookup routes.")
    parser.add_argument("--stage4-execution-root", default=str(DEFAULT_STAGE4_EXECUTION_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--max-targets", type=int, default=12)
    parser.add_argument("--max-name-only-pages", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_jzsc_personnel_route_benchmark(
        stage4_execution_root=args.stage4_execution_root,
        output_root=args.output_root,
        max_targets=args.max_targets,
        max_name_only_pages=args.max_name_only_pages,
        execute=args.execute,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "jzsc personnel route benchmark built: "
            f"{result['summary'].get('recommended_policy')}"
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
