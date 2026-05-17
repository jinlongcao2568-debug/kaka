param(
    [string]$BaselineRunResultJson = "",
    [string]$BaselineCandidatePressureJson = "",
    [string]$CompanyFirstRemediationJson = "",
    [string]$SourceGapProbeJson = "",
    [string]$OutputRoot = "",
    [int]$CandidateLimit = 10,
    [int]$DetailCaptureLimit = 10,
    [int]$AttachmentCaptureLimit = 20,
    [double]$Stage2DetailCaptureTimeBudgetSeconds = 600,
    [double]$Stage16TimeBudgetSeconds = 600,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-stage4-9-remediation-replay-v1"
}
if (-not $BaselineRunResultJson) {
    $BaselineRunResultJson = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-real-public-stage4-9-pressure-v1\run-result.json"
}
if (-not $BaselineCandidatePressureJson) {
    $BaselineCandidatePressureJson = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-real-public-stage4-9-pressure-v1\candidate-pressure-table.json"
}
if (-not $CompanyFirstRemediationJson) {
    $CompanyFirstRemediationJson = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-stage4-company-first-remediation-v1\company-first-remediation-v1.json"
}
if (-not $SourceGapProbeJson) {
    $SourceGapProbeJson = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-stage4-source-gap-probe-v1\stage4-source-gap-probe-v1.json"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_stage4_9_remediation_delta_report",
    "--mode", "run-replay",
    "--baseline-run-result-json", $BaselineRunResultJson,
    "--baseline-candidate-pressure-json", $BaselineCandidatePressureJson,
    "--company-first-remediation-json", $CompanyFirstRemediationJson,
    "--source-gap-probe-json", $SourceGapProbeJson,
    "--output-root", $OutputRoot,
    "--candidate-limit", "$CandidateLimit",
    "--detail-capture-limit", "$DetailCaptureLimit",
    "--attachment-capture-limit", "$AttachmentCaptureLimit",
    "--stage2-detail-capture-time-budget-seconds", "$Stage2DetailCaptureTimeBudgetSeconds",
    "--stage1-6-time-budget-seconds", "$Stage16TimeBudgetSeconds"
)
if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
