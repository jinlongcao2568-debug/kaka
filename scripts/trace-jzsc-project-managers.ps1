param(
    [string]$InputJson = "",
    [string]$OpeningUrl = "",
    [string]$OutputJsonl = "",
    [string]$OutputJson = "",
    [string]$OutputMarkdown = "",
    [int]$Limit = 0,
    [switch]$Resume,
    [int]$MaxPersonnelPages = 12,
    [int]$PersonnelRetryAttempts = 1,
    [string]$RequiredRegistrationCategory = "一级注册建造师",
    [string]$RequiredRegistrationProfessionKeywords = "水利水电工程,水利水电,水利工程"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kaka-jzsc-pm-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

if (-not $OutputJsonl) {
    $OutputJsonl = Join-Path $repoRoot ("handoff\jzsc_project_manager_trace_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".jsonl")
}
if (-not $OutputJson) {
    $OutputJson = [System.IO.Path]::ChangeExtension($OutputJsonl, ".summary.json")
}
if (-not $OutputMarkdown) {
    $OutputMarkdown = [System.IO.Path]::ChangeExtension($OutputJsonl, ".md")
}

$env:KAKA_JZSC_INPUT_JSON = $InputJson
$env:KAKA_JZSC_OPENING_URL = $OpeningUrl
$env:KAKA_JZSC_OUTPUT_JSONL = $OutputJsonl
$env:KAKA_JZSC_OUTPUT_JSON = $OutputJson
$env:KAKA_JZSC_OUTPUT_MD = $OutputMarkdown
$env:KAKA_JZSC_LIMIT = [string]$Limit
$env:KAKA_JZSC_RESUME = if ($Resume) { "1" } else { "0" }
$env:KAKA_JZSC_MAX_PERSONNEL_PAGES = [string]$MaxPersonnelPages
$env:KAKA_JZSC_PERSONNEL_RETRY_ATTEMPTS = [string]$PersonnelRetryAttempts
$env:KAKA_JZSC_REQUIRED_CATEGORY = $RequiredRegistrationCategory
$env:KAKA_JZSC_REQUIRED_PROFESSION_KEYWORDS = $RequiredRegistrationProfessionKeywords
$env:KAKA_STORAGE_PATH = Join-Path $runRoot "store.json"
$env:KAKA_OBJECT_STORAGE_PATH = Join-Path $runRoot "objects"
$env:PYTHONIOENCODING = "utf-8"

$python = @'
from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shared.settings import Settings
from stage4_verification.guangdong_gdcic_openplatform import (
    query_guangdong_gdcic_openplatform_person_directory,
)
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.rule_runner import evaluate_project_manager_qualification_rules
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def split_keywords(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；\s]+", value or "") if item.strip()]


def clean_main_company(value: str) -> str:
    raw = re.sub(r"<[^>]+>", "", text(value))
    raw = raw.replace("（", "(").replace("）", ")")
    parts = [part.strip() for part in re.split(r"[;；]", raw) if part.strip()]
    for part in parts:
        if re.match(r"^\(?主\)?", part):
            return re.sub(r"^\(?主\)?\s*[:：]?", "", part).strip()
    if parts:
        return re.sub(r"^\(?[主成]\)?\s*[:：]?", "", parts[0]).strip()
    return raw


def load_input_targets(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = payload.get("targets") or payload.get("records") or payload.get("rows") or []
    else:
        rows = []
    return [normalize_target(row) for row in rows if isinstance(row, Mapping)]


def extract_guangzhou_opening_targets(opening_url: str) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
        )
        page.goto(opening_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "window.mini && mini.get('grid1') && mini.get('grid1').getData && mini.get('grid1').getData().length > 0",
            timeout=45000,
        )
        grid = page.evaluate(
            """() => {
              const grid = mini.get('grid1');
              return {
                columns: grid.columns.map((item) => ({header: item.header, field: item.field})),
                rows: grid.getData()
              };
            }"""
        )
        browser.close()

    field_by_header = {
        text(column.get("header")): text(column.get("field"))
        for column in list(grid.get("columns") or [])
        if text(column.get("header")) and text(column.get("field"))
    }
    targets: list[dict[str, Any]] = []
    for index, row in enumerate(list(grid.get("rows") or []), start=1):
        values = {
            header: row.get(field)
            for header, field in field_by_header.items()
        }
        raw_company = text(values.get("投标单位名称"))
        person = text(values.get("项目负责人"))
        cert = text(values.get("项目负责人证书编号"))
        if not raw_company or not person:
            continue
        targets.append(
            {
                "idx": index,
                "company": clean_main_company(raw_company),
                "raw_bidder_name": raw_company,
                "responsible_person": person,
                "certificate_no": cert,
                "safety_b_certificate_no": "",
                "source_url": opening_url,
                "source_kind": "guangzhou_opening_info",
            }
        )
    return targets


def normalize_target(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_company = text(
        row.get("company")
        or row.get("candidate_company")
        or row.get("candidate_company_name")
        or row.get("bidder_name")
        or row.get("投标单位名称")
    )
    person = text(
        row.get("responsible_person")
        or row.get("responsible_person_name")
        or row.get("project_manager_name")
        or row.get("person")
        or row.get("项目负责人")
    )
    cert = text(
        row.get("certificate_no")
        or row.get("announcement_certificate_no")
        or row.get("certificate_no_optional")
        or row.get("project_manager_certificate_no")
        or row.get("项目负责人证书编号")
    )
    safety_b_certificate_no = text(
        row.get("safety_b_certificate_no")
        or row.get("safety_b_certificate_no_optional")
        or row.get("safety_production_b_certificate_no")
        or row.get("安全生产考核合格证书编号")
        or row.get("安管B证编号")
    )
    return {
        "idx": row.get("idx"),
        "company": clean_main_company(raw_company),
        "raw_bidder_name": text(row.get("raw_bidder_name") or raw_company),
        "responsible_person": person,
        "certificate_no": cert,
        "safety_b_certificate_no": safety_b_certificate_no,
        "source_url": text(row.get("source_url") or row.get("notice_url")),
        "source_kind": text(row.get("source_kind") or "input_json"),
    }


def object_storage_repo() -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=os.environ.get("KAKA_STORAGE_PATH")
        or str(Path(tempfile.gettempdir()) / "kaka-jzsc-pm-store.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=os.environ.get("KAKA_OBJECT_STORAGE_PATH")
        or str(Path(tempfile.gettempdir()) / "kaka-jzsc-pm-objects"),
    )
    return ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)


def target_key(target: Mapping[str, Any]) -> str:
    return "|".join(
        [
            text(target.get("company")),
            text(target.get("responsible_person")),
            text(target.get("certificate_no")),
            text(target.get("safety_b_certificate_no")),
        ]
    )


def parsed_context(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "parse_run_id": f"PARSE-JZSC-PM-{target.get('idx') or target_key(target)}",
        "snapshot_id": f"SNAP-JZSC-PM-{target.get('idx') or target_key(target)}",
        "source_url": text(target.get("source_url")),
        "parsed_fields": [
            {
                "field_name": "candidate_company_name",
                "field_value_optional": text(target.get("company")),
            },
            {
                "field_name": "project_manager_name",
                "field_value_optional": text(target.get("responsible_person")),
            },
            {
                "field_name": "project_manager_public_identifier_optional",
                "field_value_optional": text(target.get("certificate_no")),
            },
            {
                "field_name": "project_manager_safety_b_certificate_no_optional",
                "field_value_optional": text(target.get("safety_b_certificate_no")),
            },
        ],
    }


def detailed_jzsc_state(
    result: Mapping[str, Any],
    carrier: Mapping[str, Any],
    failure_reasons: list[str],
) -> str:
    carrier_state = text(carrier.get("verification_result"))
    if carrier_state:
        return carrier_state
    identity_state = text(result.get("identity_resolution_state"))
    if identity_state and identity_state != "NOT_RUN_FAIL_CLOSED":
        return identity_state
    if text(result.get("executor_state")) != "FAIL_CLOSED":
        return identity_state
    reasons = set(failure_reasons)
    if any(
        reason.startswith("jzsc_company_search_")
        or reason == "company_search_result_not_found_after_three_attempts"
        for reason in reasons
    ):
        return "FAIL_CLOSED_COMPANY_SEARCH_QUERY_ERROR"
    if any(reason.startswith("project_manager_not_found_by_company_name_person_name") for reason in reasons):
        return "FAIL_CLOSED_PERSONNEL_NOT_FOUND_IN_SAME_COMPANY_PUBLIC_ROWS"
    if "rendered_company_personnel_rows_missing" in reasons:
        return "FAIL_CLOSED_PERSONNEL_ROWS_MISSING"
    return "FAIL_CLOSED_QUERY_ERROR"


def compact_record(
    target: Mapping[str, Any],
    result: Mapping[str, Any],
    gdcic_person_directory: Mapping[str, Any],
    stage5_qualification_rules: Mapping[str, Any],
    qualification_readback: Mapping[str, Any],
) -> dict[str, Any]:
    carrier = dict(result.get("personnel_carrier") or {})
    failure_reasons = list(
        dict.fromkeys(
            [
                *[text(item) for item in list(result.get("fail_closed_reasons") or [])],
                *[text(item) for item in list(carrier.get("failure_reasons") or [])],
                *[text(item) for item in list(gdcic_person_directory.get("failure_reasons") or [])],
                *[text(item) for item in list(stage5_qualification_rules.get("failure_reasons") or [])],
            ]
        )
    )
    jzsc_state = detailed_jzsc_state(result, carrier, [item for item in failure_reasons if item])
    return {
        "idx": target.get("idx"),
        "company": text(target.get("company")),
        "raw_bidder_name": text(target.get("raw_bidder_name")),
        "responsible_person": text(target.get("responsible_person")),
        "announcement_certificate_no": text(target.get("certificate_no")),
        "safety_b_certificate_no": text(target.get("safety_b_certificate_no")),
        "required_registration_category": text(
            qualification_readback.get("required_registration_category")
        ),
        "required_registration_profession_keywords": list(
            qualification_readback.get("required_registration_profession_keywords") or []
        ),
        "source_url": text(target.get("source_url")),
        "source_kind": text(target.get("source_kind")),
        "qualification_readback": dict(qualification_readback),
        "executor_state": text(result.get("executor_state")),
        "readback_state": text(result.get("readback_state")),
        "identity_resolution_state": text(result.get("identity_resolution_state"))
        or jzsc_state,
        "matched_company_name": text(result.get("matched_company_name_optional")),
        "matched_company_public_id": text(result.get("matched_company_public_id_optional")),
        "rendered_company_personnel_row_count": int(result.get("rendered_company_personnel_row_count") or 0),
        "personnel_verification_result": text(carrier.get("verification_result")),
        "failure_reason_optional": text(carrier.get("failure_reason_optional")),
        "failure_reasons": [item for item in failure_reasons if item],
        "requirement_check": dict(carrier.get("requirement_check") or {}),
        "jzsc_verification_state": (
            text(carrier.get("verification_result"))
            or text(result.get("identity_resolution_state"))
            or jzsc_state
        ),
        "gdcic_person_directory_state": text(gdcic_person_directory.get("readback_state")),
        "gdcic_identity_resolution_state": text(
            gdcic_person_directory.get("identity_resolution_state")
        ),
        "gdcic_certificate_verification_state": text(
            gdcic_person_directory.get("certificate_verification_state")
        ),
        "gdcic_failure_reasons": list(gdcic_person_directory.get("failure_reasons") or []),
        "same_company_certificate_confirmed": bool(
            qualification_readback.get("announced_certificate_same_company_match")
        ),
        "required_profession_publicly_confirmed": bool(
            qualification_readback.get("required_registration_profession_publicly_confirmed")
        ),
        "stage5_qualification_rules": dict(stage5_qualification_rules),
        "stage5_qualification_overall_status": text(
            stage5_qualification_rules.get("overall_status")
        ),
        "official_check_recommendations": list(
            stage5_qualification_rules.get("official_check_recommendations") or []
        ),
        "name_matched_personnel_rows": list(carrier.get("name_matched_personnel_rows") or []),
        "identifier_mismatch_personnel_rows": list(carrier.get("identifier_mismatch_personnel_rows") or []),
        "matched_personnel_rows": list(carrier.get("matched_personnel_rows") or []),
        "parsed_personnel_rows": list(carrier.get("parsed_personnel_rows") or []),
        "browser_attempts": list(result.get("browser_attempts") or []),
    }


def run_gdcic_person_directory(target: Mapping[str, Any], repo: ObjectStorageRepository) -> dict[str, Any]:
    try:
        return dict(
            query_guangdong_gdcic_openplatform_person_directory(
                {
                    "project_id": "JG2026-11125",
                    "project_manager_name": text(target.get("responsible_person")),
                    "candidate_company": text(target.get("company")),
                    "project_manager_certificate_no": text(target.get("certificate_no")),
                    "safety_b_certificate_no": text(target.get("safety_b_certificate_no")),
                    "region_code": "CN-GD",
                    "source_url": text(target.get("source_url")),
                },
                repository=repo,
            )
        )
    except Exception as exc:
        return {
            "adapter_id": "guangdong_gdcic_openplatform",
            "readback_state": "FAIL_CLOSED_QUERY_ERROR",
            "source_query_state": "NO_REPLAYABLE_SOURCE_QUERY",
            "identity_resolution_state": "REVIEW_REQUIRED",
            "certificate_verification_state": "NOT_VERIFIED_BY_GDCIC_PERSON_DIRECTORY",
            "failure_reasons": [f"gdcic_person_directory_query_error:{type(exc).__name__}"],
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
            "no_national_constructor_registration_substitute": True,
        }


def build_qualification_readback(
    target: Mapping[str, Any],
    jzsc_result: Mapping[str, Any],
    gdcic_person_directory: Mapping[str, Any],
    *,
    required_category: str,
    required_profession_keywords: list[str],
) -> dict[str, Any]:
    carrier = dict(jzsc_result.get("personnel_carrier") or {})
    requirement_check = dict(carrier.get("requirement_check") or {})
    captured_categories = [
        text(item) for item in list(requirement_check.get("captured_registration_categories") or []) if text(item)
    ]
    captured_professions = [
        text(item) for item in list(requirement_check.get("captured_registration_professions") or []) if text(item)
    ]
    jzsc_match = carrier.get("verification_result") == "MATCHED"
    gdcic_cert_match = (
        gdcic_person_directory.get("certificate_verification_state")
        == "ANNOUNCED_CERTIFICATE_NO_FOUND_IN_GDCIC_PERSON_DIRECTORY_ROWS"
    )
    first_class_constructor_publicly_confirmed = any(
        "一级注册建造师" in item or "一级建造师" in item for item in captured_categories
    )
    profession_confirmed = bool(captured_professions) and any(
        keyword in profession
        for profession in captured_professions
        for keyword in required_profession_keywords
    )
    source_refs = [
        carrier.get("verification_run_id"),
        carrier.get("source_snapshot_id"),
        carrier.get("source_url"),
        gdcic_person_directory.get("source_readback_id"),
        gdcic_person_directory.get("source_url"),
    ]
    failure_reasons = list(
        dict.fromkeys(
            [
                *[text(item) for item in list(jzsc_result.get("fail_closed_reasons") or [])],
                *[text(item) for item in list(carrier.get("failure_reasons") or [])],
                *[text(item) for item in list(gdcic_person_directory.get("failure_reasons") or [])],
            ]
        )
    )
    return {
        "qualification_run_id": "PMQ-" + hashlib.sha1(
            target_key(target).encode("utf-8")
        ).hexdigest()[:16],
        "readback_state": "READBACK_READY",
        "project_id": "JG2026-11125",
        "company": text(target.get("company")),
        "project_manager_name": text(target.get("responsible_person")),
        "announced_certificate_no": text(target.get("certificate_no")),
        "safety_b_certificate_no": text(target.get("safety_b_certificate_no")),
        "safety_b_certificate_present": bool(text(target.get("safety_b_certificate_no"))),
        "required_registration_category": required_category,
        "required_registration_profession_keywords": required_profession_keywords,
        "announced_certificate_same_company_match": bool(jzsc_match or gdcic_cert_match),
        "registration_certificate_publicly_confirmed": bool(jzsc_match or gdcic_cert_match),
        "first_class_constructor_publicly_confirmed": first_class_constructor_publicly_confirmed,
        "required_registration_category_publicly_confirmed": first_class_constructor_publicly_confirmed,
        "required_registration_profession_publicly_confirmed": profession_confirmed,
        "captured_registration_categories": captured_categories,
        "captured_registration_professions": captured_professions,
        "source_refs": [text(item) for item in source_refs if text(item)],
        "jzsc": carrier,
        "guangdong_three_library_person_directory": dict(gdcic_person_directory),
        "failure_reasons": [item for item in failure_reasons if item],
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


def markdown_escape(value: Any) -> str:
    return text(value).replace("|", "\\|").replace("\n", " ")


def write_markdown_report(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        "# JG2026-11125 项目负责人资格内部核验表",
        "",
        f"- 生成时间：{markdown_escape(summary.get('generated_at'))}",
        f"- 目标数量：{summary.get('target_count')}，记录数量：{summary.get('record_count')}",
        "- 边界：仅作公开来源核验与人工复核，不作违法、围标、废标结论。",
        "",
        "| 序号 | 投标单位 | 项目负责人 | 公告证书号 | JZSC结果 | 三库人员目录 | Stage5资格状态 | 官方核查建议 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in list(summary.get("records") or []):
        suggestions = "；".join(list(record.get("official_check_recommendations") or []))
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_escape(record.get("idx")),
                    markdown_escape(record.get("company")),
                    markdown_escape(record.get("responsible_person")),
                    markdown_escape(record.get("announcement_certificate_no")),
                    markdown_escape(
                        record.get("jzsc_verification_state")
                        or record.get("personnel_verification_result")
                        or record.get("identity_resolution_state")
                    ),
                    markdown_escape(record.get("gdcic_certificate_verification_state")),
                    markdown_escape(record.get("stage5_qualification_overall_status")),
                    markdown_escape(suggestions),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 失败原因统计",
            "",
        ]
    )
    for reason, count in sorted(dict(summary.get("failure_reason_counts") or {}).items()):
        lines.append(f"- {markdown_escape(reason)}：{count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    input_json = text(os.environ.get("KAKA_JZSC_INPUT_JSON"))
    opening_url = text(os.environ.get("KAKA_JZSC_OPENING_URL"))
    output_jsonl = Path(os.environ["KAKA_JZSC_OUTPUT_JSONL"])
    output_json = Path(os.environ["KAKA_JZSC_OUTPUT_JSON"])
    output_md = Path(os.environ["KAKA_JZSC_OUTPUT_MD"])
    limit = int(os.environ.get("KAKA_JZSC_LIMIT") or "0")
    resume = (os.environ.get("KAKA_JZSC_RESUME") or "") == "1"
    max_personnel_pages = int(os.environ.get("KAKA_JZSC_MAX_PERSONNEL_PAGES") or "12")
    personnel_retry_attempts = int(os.environ.get("KAKA_JZSC_PERSONNEL_RETRY_ATTEMPTS") or "1")
    required_category = text(os.environ.get("KAKA_JZSC_REQUIRED_CATEGORY"))
    required_profession_keywords = split_keywords(
        text(os.environ.get("KAKA_JZSC_REQUIRED_PROFESSION_KEYWORDS"))
    )

    if input_json:
        targets = load_input_targets(input_json)
    elif opening_url:
        targets = extract_guangzhou_opening_targets(opening_url)
    else:
        raise SystemExit("InputJson or OpeningUrl is required.")
    targets = [target for target in targets if text(target.get("company")) and text(target.get("responsible_person"))]
    if limit > 0:
        targets = targets[:limit]

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    completed_keys: set[str] = set()
    records: list[dict[str, Any]] = []
    if resume and output_jsonl.exists():
        for line in output_jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            records.append(record)
            completed_keys.add(
                "|".join(
                    [
                        text(record.get("company")),
                        text(record.get("responsible_person")),
                        text(record.get("announcement_certificate_no")),
                        text(record.get("safety_b_certificate_no")),
                    ]
                )
            )

    repo = object_storage_repo()
    service = Stage4Service()
    for index, target in enumerate(targets, start=1):
        key = target_key(target)
        if key in completed_keys:
            print(f"[jzsc-pm] skip completed {index}/{len(targets)} {key}", flush=True)
            continue
        print(f"[jzsc-pm] run {index}/{len(targets)} {key}", flush=True)
        result = service.run_jzsc_company_first_browser_execution(
            parsed_context(target),
            target_company_name=text(target.get("company")),
            target_project_manager_name=text(target.get("responsible_person")),
            target_identifier=text(target.get("certificate_no")) or None,
            repository=repo,
            max_personnel_pages=max_personnel_pages,
            personnel_retry_attempts=personnel_retry_attempts,
            capture_personnel_project_records=False,
            required_registration_category=required_category or None,
            required_registration_profession_keywords=required_profession_keywords,
        )
        gdcic_person_directory = run_gdcic_person_directory(target, repo)
        qualification_readback = build_qualification_readback(
            target,
            result,
            gdcic_person_directory,
            required_category=required_category,
            required_profession_keywords=required_profession_keywords,
        )
        stage5_qualification_rules = evaluate_project_manager_qualification_rules(
            qualification_readback
        )
        record = compact_record(
            target,
            result,
            gdcic_person_directory,
            stage5_qualification_rules,
            qualification_readback,
        )
        with output_jsonl.open("a", encoding="utf-8") as writer:
            writer.write(json.dumps(record, ensure_ascii=False) + "\n")
        records.append(record)
        completed_keys.add(key)
        print(
            f"[jzsc-pm] done {index}/{len(targets)} state={record['identity_resolution_state']} "
            f"personnel={record['personnel_verification_result']} reasons={';'.join(record['failure_reasons'])}",
            flush=True,
        )

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "input_json": input_json,
        "opening_url": opening_url,
        "output_jsonl": str(output_jsonl),
        "output_json": str(output_json),
        "output_markdown": str(output_md),
        "target_count": len(targets),
        "record_count": len(records),
        "required_registration_category": required_category,
        "required_registration_profession_keywords": required_profession_keywords,
        "executor_state_counts": dict(Counter(record.get("executor_state") for record in records)),
        "jzsc_verification_state_counts": dict(Counter(record.get("jzsc_verification_state") for record in records)),
        "identity_resolution_counts": dict(Counter(record.get("identity_resolution_state") for record in records)),
        "personnel_verification_counts": dict(Counter(record.get("personnel_verification_result") for record in records)),
        "failure_reason_counts": dict(Counter(reason for record in records for reason in record.get("failure_reasons", []))),
        "stage5_qualification_status_counts": dict(
            Counter(record.get("stage5_qualification_overall_status") for record in records)
        ),
        "records": records,
    }
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(output_md, summary)
    print(json.dumps({"jsonl": str(output_jsonl), "summary": str(output_json), "markdown": str(output_md), "target_count": len(targets), "record_count": len(records)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'@

Push-Location $repoRoot
try {
    $python | python -X utf8 -
}
finally {
    Pop-Location
}
