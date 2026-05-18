param(
    [string]$InputRoot = "",
    [string]$InputJson = "",
    [string]$CompanyHistoryTriageRoot = "",
    [string]$YgpReadbackRoot = "",
    [string]$YgpReadbackJson = "",
    [string]$BrowserReadbackRoot = "",
    [string]$BrowserReadbackJson = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveOriginalNotices = 0,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-company-history-overlap-triage-v1-smoke"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-notice-backtrace-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.p13b_original_notice_backtrace",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot
)

if ($InputJson) {
    $argsList += @("--input-json", $InputJson)
}
if ($CompanyHistoryTriageRoot) {
    $argsList += @("--company-history-triage-root", $CompanyHistoryTriageRoot)
}
if ($YgpReadbackRoot) {
    $argsList += @("--ygp-readback-root", $YgpReadbackRoot)
}
if ($YgpReadbackJson) {
    $argsList += @("--ygp-readback-json", $YgpReadbackJson)
}
if ($BrowserReadbackRoot) {
    $argsList += @("--browser-readback-root", $BrowserReadbackRoot)
}
if ($BrowserReadbackJson) {
    $argsList += @("--browser-readback-json", $BrowserReadbackJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
}
if ($MaxLiveOriginalNotices -gt 0) {
    $argsList += @("--max-live-original-notices", "$MaxLiveOriginalNotices")
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
