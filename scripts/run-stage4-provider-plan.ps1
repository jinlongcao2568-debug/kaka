param(
    [string]$OpportunityPriorityClass = "A_HIGH_CONSTRUCTION_EPC",
    [string]$CandidateCompanyName,
    [string]$ResponsiblePersonName,
    [string]$CertificateNo = "",
    [string]$PersonPublicId = "",
    [string]$QueuePath = "",
    [int]$MaxAttempts = 3,
    [switch]$Enqueue
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:STAGE4_PLAN_CLASS = $OpportunityPriorityClass
$env:STAGE4_PLAN_COMPANY = $CandidateCompanyName
$env:STAGE4_PLAN_PERSON = $ResponsiblePersonName
$env:STAGE4_PLAN_CERT = $CertificateNo
$env:STAGE4_PLAN_PERSON_ID = $PersonPublicId
$env:STAGE4_PLAN_QUEUE_PATH = $QueuePath
$env:STAGE4_PLAN_MAX_ATTEMPTS = [string]$MaxAttempts
$env:STAGE4_PLAN_ENQUEUE = if ($Enqueue) { "1" } else { "0" }

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
plan = service.build_stage4_provider_plan(
    opportunity_priority_class=os.environ.get("STAGE4_PLAN_CLASS") or "",
    candidate_company_name=os.environ.get("STAGE4_PLAN_COMPANY") or "",
    responsible_person_name=os.environ.get("STAGE4_PLAN_PERSON") or "",
    certificate_no=os.environ.get("STAGE4_PLAN_CERT") or "",
    person_public_id=os.environ.get("STAGE4_PLAN_PERSON_ID") or "",
)
payload = {"provider_plan": plan}
if (os.environ.get("STAGE4_PLAN_ENQUEUE") or "") == "1":
    payload["queue"] = service.enqueue_stage4_provider_plan_jobs(
        plan,
        queue_path=os.environ.get("STAGE4_PLAN_QUEUE_PATH") or None,
        max_attempts=int(os.environ.get("STAGE4_PLAN_MAX_ATTEMPTS") or "3"),
    )
print(json.dumps(payload, ensure_ascii=False, indent=2))
'@

Push-Location $repoRoot
try {
    $python | python -X utf8 -
}
finally {
    Pop-Location
}
