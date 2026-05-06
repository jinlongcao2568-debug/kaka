param(
    [string[]]$Companies = @(
        "中铁五局集团有限公司",
        "中国建筑第八工程局有限公司",
        "中国水利水电第十四工程局有限公司"
    ),
    [string]$EntryUrl = "https://jzsc.mohurd.gov.cn/data/company",
    [string]$OutputJson = "",
    [string]$OutputMarkdown = "",
    [string]$SnapshotDir = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

if (-not $OutputJson) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputJson = Join-Path "handoff" "jzsc_source_health_$stamp.json"
}
if (-not $OutputMarkdown) {
    $OutputMarkdown = [System.IO.Path]::ChangeExtension($OutputJson, ".md")
}
if (-not $SnapshotDir) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($OutputJson)
    $SnapshotDir = Join-Path "handoff" ($base + "_assets")
}

$normalizedCompanies = @()
foreach ($item in $Companies) {
    if ([string]::IsNullOrWhiteSpace($item)) {
        continue
    }
    foreach ($part in ($item -split "[,，;；]")) {
        if (-not [string]::IsNullOrWhiteSpace($part)) {
            $normalizedCompanies += $part.Trim()
        }
    }
}

$env:JZSC_HEALTH_COMPANIES_JSON = ($normalizedCompanies | ConvertTo-Json -Compress)
$env:JZSC_HEALTH_ENTRY_URL = $EntryUrl
$env:JZSC_HEALTH_OUTPUT_JSON = $OutputJson
$env:JZSC_HEALTH_OUTPUT_MARKDOWN = $OutputMarkdown
$env:JZSC_HEALTH_SNAPSHOT_DIR = $SnapshotDir

$python = @'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stage4_verification.jzsc_browser_executor import diagnose_jzsc_company_search_health


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def md_escape(value: Any) -> str:
    return text(value).replace("|", "\\|").replace("\n", "<br>")


def write_markdown(payload: Mapping[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# JZSC 源健康诊断")
    lines.append("")
    lines.append(f"- 诊断时间：{md_escape(payload.get('captured_at'))}")
    lines.append(f"- 入口 URL：{md_escape(payload.get('entry_url'))}")
    lines.append(f"- 源健康状态：{md_escape(payload.get('source_health_status'))}")
    lines.append(f"- 控制企业是否至少返回一条企业候选：{payload.get('control_company_any_row')}")
    lines.append("")
    lines.append("| 企业 | 状态 | 状态码 | 行数 | Vue状态 | 阻断 | 失败原因 | 最终URL | 快照 |")
    lines.append("|---|---:|---:|---:|---:|---:|---|---|---|")
    for item in list(payload.get("company_results") or []):
        refs = []
        if text(item.get("html_snapshot_path")):
            refs.append(text(item.get("html_snapshot_path")))
        if text(item.get("screenshot_path")):
            refs.append(text(item.get("screenshot_path")))
        lines.append(
            "| "
            + " | ".join(
                [
                    md_escape(item.get("query_company_name")),
                    md_escape(item.get("diagnostic_state")),
                    md_escape(item.get("diagnostic_status_code")),
                    md_escape(item.get("company_row_count")),
                    md_escape(item.get("vue_data_extraction_state")),
                    md_escape(item.get("challenge_state")),
                    md_escape(", ".join(str(x) for x in list(item.get("failure_reasons") or []))),
                    md_escape(item.get("final_url")),
                    md_escape("<br>".join(refs)),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 口径")
    lines.append("")
    lines.append("- 控制企业也无法返回候选时，优先视为 JZSC 自动化链路或页面结构不可信，不把七家 NOT_RUN_FAIL_CLOSED 当成证书强证据。")
    lines.append("- 检测到验证码、滑块、访问阻断时只记录 BLOCKED_REVIEW_REQUIRED，本脚本不做验证码突破、代理池或指纹伪装。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


raw_companies = json.loads(os.environ.get("JZSC_HEALTH_COMPANIES_JSON") or "[]")
if isinstance(raw_companies, str):
    companies = [raw_companies]
else:
    companies = list(raw_companies or [])
entry_url = os.environ.get("JZSC_HEALTH_ENTRY_URL") or "https://jzsc.mohurd.gov.cn/data/company"
output_json = Path(os.environ["JZSC_HEALTH_OUTPUT_JSON"])
output_markdown = Path(os.environ["JZSC_HEALTH_OUTPUT_MARKDOWN"])
snapshot_dir = os.environ.get("JZSC_HEALTH_SNAPSHOT_DIR") or ""

payload = diagnose_jzsc_company_search_health(
    [str(item).strip() for item in companies if str(item).strip()],
    entry_url=entry_url,
    snapshot_dir=snapshot_dir,
)
output_json.parent.mkdir(parents=True, exist_ok=True)
output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
write_markdown(payload, output_markdown)
print(
    json.dumps(
        {
            "output_json": str(output_json),
            "output_markdown": str(output_markdown),
            "source_health_status": payload.get("source_health_status"),
            "control_company_any_row": payload.get("control_company_any_row"),
            "company_count": payload.get("company_count"),
            "status_counts": {
                str(item.get("diagnostic_state")): sum(
                    1
                    for other in list(payload.get("company_results") or [])
                    if other.get("diagnostic_state") == item.get("diagnostic_state")
                )
                for item in list(payload.get("company_results") or [])
            },
        },
        ensure_ascii=False,
    )
)
'@

$tmp = New-TemporaryFile
try {
    Set-Content -LiteralPath $tmp -Value $python -Encoding UTF8
    python $tmp
}
finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
