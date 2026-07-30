param(
    [string]$LatestScoreboardJson = "",
    [string]$PreviousScoreboardJson = "",
    [string]$ScoreboardComparisonJson = "",
    [string]$FollowupQueueJson = "",
    [string]$SearchRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-latest-scoreboard-diagnostic-v1"
}
if (-not $SearchRoot) {
    $SearchRoot = Join-Path $repoRoot "tmp\evaluation-real-samples"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage1_6_latest_scoreboard_diagnostic",
    "--search-root", $SearchRoot,
    "--output-root", $OutputRoot
)
if ($LatestScoreboardJson) {
    $argsList += @("--latest-scoreboard-json", $LatestScoreboardJson)
}
if ($PreviousScoreboardJson) {
    $argsList += @("--previous-scoreboard-json", $PreviousScoreboardJson)
}
if ($ScoreboardComparisonJson) {
    $argsList += @("--scoreboard-comparison-json", $ScoreboardComparisonJson)
}
if ($FollowupQueueJson) {
    $argsList += @("--followup-queue-json", $FollowupQueueJson)
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
