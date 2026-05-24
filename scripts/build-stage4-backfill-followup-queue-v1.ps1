param(
    [string]$ScoreboardJson = "",
    [string]$ScoreboardComparisonJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ScoreboardJson) {
    $ScoreboardJson = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-sellable-rate-regression-live18-20260525-r2\scoreboard\stage1-6-sellable-scoreboard-v1.json"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage4-backfill-followup-queue-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage4_backfill_followup_queue",
    "--scoreboard-json", $ScoreboardJson,
    "--output-root", $OutputRoot
)
if ($ScoreboardComparisonJson) {
    $argsList += @("--scoreboard-comparison-json", $ScoreboardComparisonJson)
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
