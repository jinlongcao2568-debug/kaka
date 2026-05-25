param(
    [string]$PressureRoot = "",
    [string]$PressureSummaryJson = "",
    [string]$ReadinessJson = "",
    [string]$GapSummaryJson = "",
    [string]$FieldQueryRoot = "",
    [string]$FieldQueryJson = "",
    [string]$SupplementalFieldQueryRoot = "",
    [string]$SupplementalFieldQueryJson = "",
    [string]$GdcicBrowserReadbackRoot = "",
    [string]$GdcicBrowserReadbackJson = "",
    [string]$P13BCompanyHistoryRoot = "",
    [string]$P13BCompanyHistoryJson = "",
    [string]$P13BOriginalNoticeBacktraceRoot = "",
    [string]$P13BOriginalNoticeBacktraceJson = "",
    [string]$P13BYgpOriginalReadbackRoot = "",
    [string]$P13BYgpOriginalReadbackJson = "",
    [string]$P13BOverlapTriageCloseoutRoot = "",
    [string]$P13BOverlapTriageCloseoutJson = "",
    [string]$Stage6StatusRoot = "",
    [string]$Stage6StatusJson = "",
    [string]$PriorScoreboardJson = "",
    [string]$IncrementalProjectIds = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $PressureRoot) {
    $PressureRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-stage1-6-real-public-pressure-v1"
}
if (-not $FieldQueryRoot) {
    $FieldQueryRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-local-field-query-probe-v1"
}
if (-not $GdcicBrowserReadbackRoot) {
    $GdcicBrowserReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\gdcic-browser-authorized-readback-v1"
}
if (-not $P13BCompanyHistoryRoot) {
    $P13BCompanyHistoryRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-company-history-overlap-triage-v1"
}
if (-not $P13BOriginalNoticeBacktraceRoot) {
    $P13BOriginalNoticeBacktraceRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-notice-backtrace-v1"
}
if (-not $P13BYgpOriginalReadbackRoot) {
    $P13BYgpOriginalReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-ygp-original-readback-v1"
}
if (-not $P13BOverlapTriageCloseoutRoot) {
    $P13BOverlapTriageCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-overlap-triage-closeout-v1"
}
if (-not $Stage6StatusRoot) {
    $Stage6StatusRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-cycle-runner-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-sellable-scoreboard-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage1_6_sellable_scoreboard",
    "--pressure-root", $PressureRoot,
    "--field-query-root", $FieldQueryRoot,
    "--gdcic-browser-readback-root", $GdcicBrowserReadbackRoot,
    "--p13b-company-history-root", $P13BCompanyHistoryRoot,
    "--p13b-original-notice-backtrace-root", $P13BOriginalNoticeBacktraceRoot,
    "--p13b-ygp-original-readback-root", $P13BYgpOriginalReadbackRoot,
    "--p13b-overlap-triage-closeout-root", $P13BOverlapTriageCloseoutRoot,
    "--stage6-status-root", $Stage6StatusRoot,
    "--output-root", $OutputRoot
)

if ($PressureSummaryJson) {
    $argsList += @("--pressure-summary-json", $PressureSummaryJson)
}
if ($ReadinessJson) {
    $argsList += @("--readiness-json", $ReadinessJson)
}
if ($GapSummaryJson) {
    $argsList += @("--gap-summary-json", $GapSummaryJson)
}
if ($FieldQueryJson) {
    $argsList += @("--field-query-json", $FieldQueryJson)
}
if ($SupplementalFieldQueryRoot) {
    $argsList += @("--supplemental-field-query-root", $SupplementalFieldQueryRoot)
}
if ($SupplementalFieldQueryJson) {
    $argsList += @("--supplemental-field-query-json", $SupplementalFieldQueryJson)
}
if ($GdcicBrowserReadbackJson) {
    $argsList += @("--gdcic-browser-readback-json", $GdcicBrowserReadbackJson)
}
if ($P13BCompanyHistoryJson) {
    $argsList += @("--p13b-company-history-json", $P13BCompanyHistoryJson)
}
if ($P13BOriginalNoticeBacktraceJson) {
    $argsList += @("--p13b-original-notice-backtrace-json", $P13BOriginalNoticeBacktraceJson)
}
if ($P13BYgpOriginalReadbackJson) {
    $argsList += @("--p13b-ygp-original-readback-json", $P13BYgpOriginalReadbackJson)
}
if ($P13BOverlapTriageCloseoutJson) {
    $argsList += @("--p13b-overlap-triage-closeout-json", $P13BOverlapTriageCloseoutJson)
}
if ($Stage6StatusJson) {
    $argsList += @("--stage6-status-json", $Stage6StatusJson)
}
if ($PriorScoreboardJson) {
    $argsList += @("--prior-scoreboard-json", $PriorScoreboardJson)
}
if ($IncrementalProjectIds) {
    $argsList += @("--incremental-project-ids", $IncrementalProjectIds)
}
if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    $pythonExitCode = $LASTEXITCODE
    if ($pythonExitCode -ne 0) {
        exit $pythonExitCode
    }
} finally {
    Pop-Location
}
