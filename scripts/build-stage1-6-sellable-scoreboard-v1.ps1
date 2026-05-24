param(
    [string]$PressureRoot = "",
    [string]$PressureSummaryJson = "",
    [string]$ReadinessJson = "",
    [string]$GapSummaryJson = "",
    [string]$FieldQueryRoot = "",
    [string]$FieldQueryJson = "",
    [string]$Stage6StatusRoot = "",
    [string]$Stage6StatusJson = "",
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
if ($Stage6StatusJson) {
    $argsList += @("--stage6-status-json", $Stage6StatusJson)
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
