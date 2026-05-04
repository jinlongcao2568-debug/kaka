param(
    [Parameter(Mandatory=$true)][string]$DocumentPath,
    [string]$SourceUrl = "",
    [string]$DetailPageUrl = "",
    [string]$OpportunityPriorityClass = "",
    [switch]$EnableOcr,
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:STAGE4_DOC_PATH = $DocumentPath
$env:STAGE4_DOC_SOURCE_URL = $SourceUrl
$env:STAGE4_DOC_DETAIL_URL = $DetailPageUrl
$env:STAGE4_DOC_CLASS = $OpportunityPriorityClass
$env:STAGE4_DOC_ENABLE_OCR = if ($EnableOcr) { "1" } else { "0" }
$env:STAGE4_DOC_OUTPUT_JSON = $OutputJson

$python = @'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stage4_verification.service import Stage4Service

service = Stage4Service()
payload = service.extract_stage4_attachment_document(
    os.environ["STAGE4_DOC_PATH"],
    source_url=os.environ.get("STAGE4_DOC_SOURCE_URL") or "",
    detail_page_url=os.environ.get("STAGE4_DOC_DETAIL_URL") or "",
    opportunity_priority_class=os.environ.get("STAGE4_DOC_CLASS") or None,
    enable_ocr=(os.environ.get("STAGE4_DOC_ENABLE_OCR") or "") == "1",
)
output_json = os.environ.get("STAGE4_DOC_OUTPUT_JSON") or ""
if output_json:
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
'@

Push-Location $repoRoot
try {
    $python | python -X utf8 -
}
finally {
    Pop-Location
}
