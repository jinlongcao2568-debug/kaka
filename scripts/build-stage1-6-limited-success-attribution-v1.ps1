param(
    [string]$SuccessScoreboardJson = "",
    [string]$TargetScoreboardJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $SuccessScoreboardJson) {
    Write-Error "SuccessScoreboardJson is required."
    exit 1
}
if (-not $TargetScoreboardJson) {
    Write-Error "TargetScoreboardJson is required."
    exit 1
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-limited-success-attribution-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage1_6_limited_success_attribution",
    "--success-scoreboard-json", $SuccessScoreboardJson,
    "--target-scoreboard-json", $TargetScoreboardJson,
    "--output-root", $OutputRoot
)
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
