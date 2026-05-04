param(
    [string]$TraceJson = "",
    [int]$Limit = 22,
    [int]$MaxPersonnelPages = 3,
    [int]$MaxProjectPages = 3,
    [int]$PersonnelRetryAttempts = 3,
    [int]$EscalatedPersonnelRetryAttempts = 5,
    [int]$ProjectRetryAttempts = 3,
    [switch]$CaptureJzscProjectRecords,
    [switch]$DisableFailedRetryEscalation,
    [string]$PreviousStage4Json = "",
    [switch]$OnlyPreviousUnsuccessful,
    [switch]$OnlyIdentityMatchedProjectEmpty,
    [string]$OutputStem = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kaka-gz-stage4-jzsc-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

if (-not $TraceJson) {
    $TraceJson = Join-Path $repoRoot "handoff\guangzhou_candidate_30_abcd_trace_20260503_impl.json"
}
if (-not $env:KAKA_STORAGE_PATH) {
    $env:KAKA_STORAGE_PATH = Join-Path $runRoot "store.json"
}
if (-not $env:KAKA_OBJECT_STORAGE_PATH) {
    $env:KAKA_OBJECT_STORAGE_PATH = Join-Path $runRoot "objects"
}
$env:PYTHONIOENCODING = "utf-8"
$env:GUANGZHOU_STAGE4_TRACE_JSON = $TraceJson
$env:GUANGZHOU_STAGE4_LIMIT = [string]$Limit
$env:GUANGZHOU_STAGE4_MAX_PERSONNEL_PAGES = [string]$MaxPersonnelPages
$env:GUANGZHOU_STAGE4_MAX_PROJECT_PAGES = [string]$MaxProjectPages
$env:GUANGZHOU_STAGE4_PERSONNEL_RETRY_ATTEMPTS = [string]$PersonnelRetryAttempts
$env:GUANGZHOU_STAGE4_ESCALATED_PERSONNEL_RETRY_ATTEMPTS = [string]$EscalatedPersonnelRetryAttempts
$env:GUANGZHOU_STAGE4_DISABLE_FAILED_RETRY_ESCALATION = if ($DisableFailedRetryEscalation) { "1" } else { "0" }
$env:GUANGZHOU_STAGE4_PROJECT_RETRY_ATTEMPTS = [string]$ProjectRetryAttempts
$env:GUANGZHOU_STAGE4_CAPTURE_JZSC_PROJECT_RECORDS = if ($CaptureJzscProjectRecords) { "1" } else { "0" }
$env:GUANGZHOU_STAGE4_PREVIOUS_JSON = $PreviousStage4Json
$env:GUANGZHOU_STAGE4_ONLY_PREVIOUS_UNSUCCESSFUL = if ($OnlyPreviousUnsuccessful) { "1" } else { "0" }
$env:GUANGZHOU_STAGE4_ONLY_IDENTITY_MATCHED_PROJECT_EMPTY = if ($OnlyIdentityMatchedProjectEmpty) { "1" } else { "0" }
$env:GUANGZHOU_STAGE4_OUTPUT_STEM = $OutputStem

$python = @'
from __future__ import annotations

import json
import os
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
from stage4_verification.service import Stage4Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


TRACE_JSON = Path(os.environ["GUANGZHOU_STAGE4_TRACE_JSON"])
LIMIT = int(os.environ.get("GUANGZHOU_STAGE4_LIMIT") or "22")
MAX_PERSONNEL_PAGES = int(os.environ.get("GUANGZHOU_STAGE4_MAX_PERSONNEL_PAGES") or "3")
MAX_PROJECT_PAGES = int(os.environ.get("GUANGZHOU_STAGE4_MAX_PROJECT_PAGES") or "3")
PERSONNEL_RETRY_ATTEMPTS = int(os.environ.get("GUANGZHOU_STAGE4_PERSONNEL_RETRY_ATTEMPTS") or "3")
ESCALATED_PERSONNEL_RETRY_ATTEMPTS = int(os.environ.get("GUANGZHOU_STAGE4_ESCALATED_PERSONNEL_RETRY_ATTEMPTS") or "5")
DISABLE_FAILED_RETRY_ESCALATION = (os.environ.get("GUANGZHOU_STAGE4_DISABLE_FAILED_RETRY_ESCALATION") or "") == "1"
PROJECT_RETRY_ATTEMPTS = int(os.environ.get("GUANGZHOU_STAGE4_PROJECT_RETRY_ATTEMPTS") or "3")
CAPTURE_JZSC_PROJECT_RECORDS = (os.environ.get("GUANGZHOU_STAGE4_CAPTURE_JZSC_PROJECT_RECORDS") or "") == "1"
PREVIOUS_STAGE4_JSON = (os.environ.get("GUANGZHOU_STAGE4_PREVIOUS_JSON") or "").strip()
ONLY_PREVIOUS_UNSUCCESSFUL = (os.environ.get("GUANGZHOU_STAGE4_ONLY_PREVIOUS_UNSUCCESSFUL") or "") == "1"
ONLY_IDENTITY_MATCHED_PROJECT_EMPTY = (os.environ.get("GUANGZHOU_STAGE4_ONLY_IDENTITY_MATCHED_PROJECT_EMPTY") or "") == "1"
OUTPUT_STEM = (os.environ.get("GUANGZHOU_STAGE4_OUTPUT_STEM") or "").strip()
NOW = datetime.now().astimezone().isoformat()


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def md(value: Any) -> str:
    return text(value).replace("|", "\\|").replace("\n", " ")


def object_storage_repo() -> ObjectStorageRepository:
    storage_path = os.environ.get("KAKA_STORAGE_PATH") or str(Path(tempfile.gettempdir()) / "kaka-stage4-jzsc.json")
    object_path = os.environ.get("KAKA_OBJECT_STORAGE_PATH") or str(Path(tempfile.gettempdir()) / "kaka-stage4-jzsc-objects")
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=storage_path,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=object_path,
    )
    return ObjectStorageRepository(
        session=DatabaseSession(settings=settings),
        settings=settings,
    )


def parsed_context(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = [
        {
            "field_name": "current_project_name",
            "field_value_optional": text(row.get("title")),
            "source_file_ref": "GUANGZHOU-STAGE4-TRACE",
            "confidence": 0.9,
        },
        {
            "field_name": "candidate_company_name",
            "field_value_optional": text(row.get("company")),
            "source_file_ref": "GUANGZHOU-STAGE4-TRACE",
            "confidence": 0.9,
        },
        {
            "field_name": "project_manager_name",
            "field_value_optional": text(row.get("responsible_person")),
            "source_file_ref": "GUANGZHOU-STAGE4-TRACE",
            "confidence": 0.9,
        },
    ]
    if text(row.get("certificate_no")):
        fields.append(
            {
                "field_name": "project_manager_public_identifier_optional",
                "field_value_optional": text(row.get("certificate_no")),
                "source_file_ref": "GUANGZHOU-STAGE4-TRACE",
                "confidence": 0.9,
            }
        )
    return {
        "parse_run_id": f"PARSE-GZ-STAGE4-{row.get('idx')}",
        "snapshot_id": f"SNAP-GZ-STAGE4-{row.get('idx')}",
        "source_url": text(row.get("url")),
        "parsed_fields": fields,
    }


def outcome(result: Mapping[str, Any]) -> str:
    if text(result.get("executor_state")) == "READBACK_READY" and text(result.get("identity_resolution_state")) == "MATCHED":
        return "JZSC_PERSON_COMPANY_CERT_MATCHED"
    if int(result.get("rendered_company_personnel_row_count") or 0) > 0:
        return "PERSON_FOUND_BUT_IDENTITY_REVIEW"
    if text(result.get("matched_company_public_id_optional")):
        return "COMPANY_MATCHED_PERSON_NOT_FOUND_REVIEW"
    if any("company_search_result_not_found" in text(reason) for reason in list(result.get("fail_closed_reasons") or [])):
        return "COMPANY_NOT_FOUND_REVIEW"
    if any("playwright_timeout" in text(reason) for reason in list(result.get("fail_closed_reasons") or [])):
        return "BROWSER_TIMEOUT_REVIEW"
    return "REVIEW_REQUIRED"


def should_escalate_failed_personnel_retry(result: Mapping[str, Any]) -> bool:
    if DISABLE_FAILED_RETRY_ESCALATION:
        return False
    if ESCALATED_PERSONNEL_RETRY_ATTEMPTS <= PERSONNEL_RETRY_ATTEMPTS:
        return False
    return outcome(result) != "JZSC_PERSON_COMPANY_CERT_MATCHED"


def run_stage4_for_row(
    service: Stage4Service,
    repo: ObjectStorageRepository,
    row: Mapping[str, Any],
    *,
    personnel_retry_attempts: int,
) -> dict[str, Any]:
    try:
        return dict(
            service.run_jzsc_company_first_browser_execution(
                parsed_context(row),
                target_company_name=text(row.get("company")),
                target_project_manager_name=text(row.get("responsible_person")),
                target_identifier=text(row.get("certificate_no")) or None,
                repository=repo,
                max_personnel_pages=MAX_PERSONNEL_PAGES,
                max_project_pages=MAX_PROJECT_PAGES,
                personnel_retry_attempts=personnel_retry_attempts,
                project_retry_attempts=PROJECT_RETRY_ATTEMPTS,
                capture_personnel_project_records=CAPTURE_JZSC_PROJECT_RECORDS,
            )
        )
    except Exception as exc:
        return {
            "executor_state": "FAIL_CLOSED",
            "readback_state": "REVIEW_REQUIRED",
            "fail_closed_reasons": [f"stage4_trace_exception:{exc}"],
        }


def compact_result(
    row: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    initial_result: Mapping[str, Any] | None = None,
    retry_escalated: bool = False,
    final_personnel_retry_attempts: int = PERSONNEL_RETRY_ATTEMPTS,
) -> dict[str, Any]:
    personnel_carrier = dict(result.get("personnel_carrier") or {})
    active_conflict = dict(result.get("project_manager_active_conflict") or {})
    attempts = list(result.get("browser_attempts") or [])
    initial = dict(initial_result or result)
    return {
        "idx": row.get("idx"),
        "type": text(row.get("type")),
        "title": text(row.get("title")),
        "notice_url": text(row.get("url")),
        "candidate_company": text(row.get("company")),
        "responsible_person": text(row.get("responsible_person")),
        "announcement_certificate_no": text(row.get("certificate_no")),
        "stage4_outcome": outcome(result),
        "initial_stage4_outcome": outcome(initial),
        "retry_escalated_after_initial_failure": retry_escalated,
        "initial_personnel_retry_attempts": PERSONNEL_RETRY_ATTEMPTS,
        "final_personnel_retry_attempts": final_personnel_retry_attempts,
        "executor_state": text(result.get("executor_state")),
        "readback_state": text(result.get("readback_state")),
        "identity_resolution_state": text(result.get("identity_resolution_state")),
        "matched_company_name": text(result.get("matched_company_name_optional")),
        "matched_company_public_id": text(result.get("matched_company_public_id_optional")),
        "jzsc_certificate_no": text(
            personnel_carrier.get("project_manager_certificate_no_optional")
            or result.get("resolved_public_identifier_optional")
        ),
        "jzsc_registered_unit": text(personnel_carrier.get("project_manager_registered_unit_optional")),
        "person_public_id": text(personnel_carrier.get("person_public_id_optional")),
        "personnel_detail_url": text(personnel_carrier.get("personnel_detail_url_optional")),
        "company_personnel_source_url": text(result.get("company_personnel_source_url")),
        "personnel_project_source_url": text(result.get("personnel_project_source_url")),
        "rendered_company_personnel_row_count": int(result.get("rendered_company_personnel_row_count") or 0),
        "rendered_personnel_project_row_count": int(result.get("rendered_personnel_project_row_count") or 0),
        "fail_closed_reasons": [text(reason) for reason in list(result.get("fail_closed_reasons") or []) if text(reason)],
        "nonfatal_diagnostics": [text(reason) for reason in list(result.get("browser_nonfatal_diagnostics") or []) if text(reason)],
        "browser_attempts": attempts,
        "active_conflict_overlap_judgement": text(active_conflict.get("overlap_judgement")),
        "next_manual_review_route": next_route(result),
    }


def next_route(result: Mapping[str, Any]) -> str:
    state = outcome(result)
    if state.startswith("IDENTITY_AND_PROJECT"):
        return "继续进入 Stage5：用人员项目记录和当前公告窗口做冲突判断"
    if state == "JZSC_PERSON_COMPANY_CERT_MATCHED":
        return "四库人员公司匹配和证书ID已核到；用证书ID/人员公开ID进入地方住建、施工许可、合同备案、竣工、项目经理变更链核验业绩/在建冲突"
    if state == "PERSON_FOUND_BUT_IDENTITY_REVIEW":
        return "四库找到人员行但未满足唯一/证书/单位一致性，保留人工复核并补人员详情/地方注册库"
    if state == "COMPANY_MATCHED_PERSON_NOT_FOUND_REVIEW":
        return "企业已确认；公司+人名三类尝试未命中，进入人工复核/地方住建人员库/公告承诺核验"
    if state == "COMPANY_NOT_FOUND_REVIEW":
        return "企业未在四库命中；换企业别名/联合体成员/地方住建企业库复核"
    return "保留人工复核，不得直接判违规"


source = json.loads(TRACE_JSON.read_text(encoding="utf-8"))
focus_indices: set[int] = set()
if ONLY_PREVIOUS_UNSUCCESSFUL:
    if not PREVIOUS_STAGE4_JSON:
        raise SystemExit("PreviousStage4Json is required when -OnlyPreviousUnsuccessful is used.")
    previous = json.loads(Path(PREVIOUS_STAGE4_JSON).read_text(encoding="utf-8"))
    focus_indices = {
        int(record.get("idx"))
        for record in list(previous.get("records") or [])
        if text(record.get("stage4_outcome")) not in {
            "JZSC_PERSON_COMPANY_CERT_MATCHED",
            "IDENTITY_MATCHED_PROJECT_ROWS_EMPTY_OR_BLOCKED",
        }
    }
if ONLY_IDENTITY_MATCHED_PROJECT_EMPTY:
    if not PREVIOUS_STAGE4_JSON:
        raise SystemExit("PreviousStage4Json is required when -OnlyIdentityMatchedProjectEmpty is used.")
    previous = json.loads(Path(PREVIOUS_STAGE4_JSON).read_text(encoding="utf-8"))
    focus_indices = {
        int(record.get("idx"))
        for record in list(previous.get("records") or [])
        if text(record.get("stage4_outcome")) == "IDENTITY_MATCHED_PROJECT_ROWS_EMPTY_OR_BLOCKED"
    }
rows = [
    row
    for row in list(source.get("rows") or [])
    if bool(row.get("responsible_role_required"))
    and text(row.get("company"))
    and text(row.get("responsible_person"))
    and (not focus_indices or int(row.get("idx") or 0) in focus_indices)
]
rows = rows[:LIMIT]
repo = object_storage_repo()
service = Stage4Service()
records: list[dict[str, Any]] = []
total_rows = len(rows)
for row_no, row in enumerate(rows, start=1):
    print(
        f"[stage4-jzsc] {row_no}/{total_rows} idx={row.get('idx')} "
        f"company={text(row.get('company'))} person={text(row.get('responsible_person'))} "
        f"retry={PERSONNEL_RETRY_ATTEMPTS}",
        flush=True,
    )
    initial_result = run_stage4_for_row(
        service,
        repo,
        row,
        personnel_retry_attempts=PERSONNEL_RETRY_ATTEMPTS,
    )
    final_result = initial_result
    retry_escalated = False
    final_retry_attempts = PERSONNEL_RETRY_ATTEMPTS
    if should_escalate_failed_personnel_retry(initial_result):
        retry_escalated = True
        final_retry_attempts = ESCALATED_PERSONNEL_RETRY_ATTEMPTS
        final_result = run_stage4_for_row(
            service,
            repo,
            row,
            personnel_retry_attempts=ESCALATED_PERSONNEL_RETRY_ATTEMPTS,
        )
    record = compact_result(
        row,
        final_result,
        initial_result=initial_result,
        retry_escalated=retry_escalated,
        final_personnel_retry_attempts=final_retry_attempts,
    )
    records.append(record)
    print(
        f"[stage4-jzsc] {row_no}/{total_rows} idx={row.get('idx')} "
        f"initial={record['initial_stage4_outcome']} final={record['stage4_outcome']} "
        f"retry={record['initial_personnel_retry_attempts']}->{record['final_personnel_retry_attempts']}",
        flush=True,
    )

outcome_counts = dict(Counter(record["stage4_outcome"] for record in records))
summary = {
    "generated_at": NOW,
    "trace_json": str(TRACE_JSON),
    "input_role_required_count": len([row for row in list(source.get("rows") or []) if bool(row.get("responsible_role_required"))]),
    "executed_count": len(records),
    "limit": LIMIT,
    "max_personnel_pages": MAX_PERSONNEL_PAGES,
    "max_project_pages": MAX_PROJECT_PAGES,
    "personnel_retry_attempts": PERSONNEL_RETRY_ATTEMPTS,
    "escalated_personnel_retry_attempts": ESCALATED_PERSONNEL_RETRY_ATTEMPTS,
    "failed_retry_escalation_enabled": not DISABLE_FAILED_RETRY_ESCALATION and ESCALATED_PERSONNEL_RETRY_ATTEMPTS > PERSONNEL_RETRY_ATTEMPTS,
    "project_retry_attempts": PROJECT_RETRY_ATTEMPTS,
    "capture_jzsc_project_records": CAPTURE_JZSC_PROJECT_RECORDS,
    "previous_stage4_json": PREVIOUS_STAGE4_JSON,
    "only_previous_unsuccessful": ONLY_PREVIOUS_UNSUCCESSFUL,
    "only_identity_matched_project_empty": ONLY_IDENTITY_MATCHED_PROJECT_EMPTY,
    "outcome_counts": outcome_counts,
    "identity_matched_count": sum(1 for record in records if record["identity_resolution_state"] == "MATCHED"),
    "initial_identity_matched_count": sum(1 for record in records if record["initial_stage4_outcome"] == "JZSC_PERSON_COMPANY_CERT_MATCHED"),
    "failed_items_rerun_with_escalated_retry_count": sum(1 for record in records if record["retry_escalated_after_initial_failure"]),
    "escalated_retry_recovered_identity_count": sum(
        1
        for record in records
        if record["retry_escalated_after_initial_failure"]
        and record["stage4_outcome"] == "JZSC_PERSON_COMPANY_CERT_MATCHED"
        and record["initial_stage4_outcome"] != "JZSC_PERSON_COMPANY_CERT_MATCHED"
    ),
    "company_matched_count": sum(1 for record in records if record["matched_company_public_id"]),
    "person_found_count": sum(1 for record in records if record["rendered_company_personnel_row_count"] > 0),
    "project_rows_found_count": sum(1 for record in records if record["rendered_personnel_project_row_count"] > 0),
}

date_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
stem = OUTPUT_STEM or f"guangzhou_candidate_22_stage4_jzsc_trace_{date_suffix}"
out_dir = ROOT / "handoff"
out_dir.mkdir(parents=True, exist_ok=True)
json_path = out_dir / f"{stem}.json"
md_path = out_dir / f"{stem}.md"

lines: list[str] = []
lines.append("# 广州 A/B/C 负责人 Stage4 四库公司优先核验追踪")
lines.append("")
lines.append(f"- 运行时间：{NOW}")
lines.append(f"- 输入报告：{TRACE_JSON}")
lines.append(f"- 执行条数：{len(records)} / A/B/C 应核验 {summary['input_role_required_count']}")
lines.append(f"- 四库核验口径：只核人员-公司匹配、证书ID/人员公开ID；四库业绩不作为在建冲突依据")
lines.append(f"- 人员页翻页上限：{MAX_PERSONNEL_PAGES}；初次人员搜索重试：{PERSONNEL_RETRY_ATTEMPTS}；失败项升级重试：{'关闭' if DISABLE_FAILED_RETRY_ESCALATION else ESCALATED_PERSONNEL_RETRY_ATTEMPTS}")
lines.append(f"- 四库业绩抓取：{'开启诊断' if CAPTURE_JZSC_PROJECT_RECORDS else '默认跳过'}；项目页上限：{MAX_PROJECT_PAGES}；项目页重试：{PROJECT_RETRY_ATTEMPTS}")
if ONLY_IDENTITY_MATCHED_PROJECT_EMPTY:
    lines.append(f"- 本轮只复跑上一轮身份已匹配但项目页空/校验的条目：{PREVIOUS_STAGE4_JSON}")
if ONLY_PREVIOUS_UNSUCCESSFUL:
    lines.append(f"- 本轮只复跑上一轮未完成身份匹配的条目：{PREVIOUS_STAGE4_JSON}")
lines.append(f"- 初次身份命中：{summary['initial_identity_matched_count']}；失败升级复跑：{summary['failed_items_rerun_with_escalated_retry_count']}；升级后新增命中：{summary['escalated_retry_recovered_identity_count']}")
lines.append(f"- 公司命中：{summary['company_matched_count']}；最终人员身份命中：{summary['identity_matched_count']}；项目记录命中：{summary['project_rows_found_count']}")
lines.append("")
lines.append("## 结果分布")
lines.append("")
lines.append(json.dumps(outcome_counts, ensure_ascii=False, indent=2))
lines.append("")
lines.append("## 明细")
lines.append("")
lines.append("| 序号 | 类型 | 标题 | 公司 | 负责人 | 公告证书 | 四库公司 | 四库证书/人员ID | 重试 | 初次结果 | 最终结果 | 失败/诊断 | 下一步 |")
lines.append("|---:|---|---|---|---|---|---|---|---|---|---|---|---|")
for record in records:
    cert = record["jzsc_certificate_no"]
    if record["person_public_id"]:
        cert = f"{cert}<br>{record['person_public_id']}" if cert else record["person_public_id"]
    reasons = [*record["fail_closed_reasons"], *record["nonfatal_diagnostics"]]
    lines.append(
        f"| {record['idx']} | {md(record['type'])} | {md(record['title'])} | {md(record['candidate_company'])} | "
        f"{md(record['responsible_person'])} | {md(record['announcement_certificate_no'])} | "
        f"{md(record['matched_company_name'])}<br>{md(record['matched_company_public_id'])} | "
        f"{md(cert)} | {record['initial_personnel_retry_attempts']}→{record['final_personnel_retry_attempts']}{' 升级' if record['retry_escalated_after_initial_failure'] else ''} | "
        f"{md(record['initial_stage4_outcome'])} | {md(record['stage4_outcome'])} | "
        f"{md('; '.join(reasons))} | {md(record['next_manual_review_route'])} |"
    )

json_path.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
md_path.write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"markdown": str(md_path), "json": str(json_path), "summary": summary}, ensure_ascii=False, indent=2))
'@

Push-Location $repoRoot
try {
    $python | python -X utf8 -
}
finally {
    Pop-Location
}
