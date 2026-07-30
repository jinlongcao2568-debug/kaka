param(
    [string]$Stage6ReviewCycleJson = "",
    [string]$ReleaseFieldQueryJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $Stage6ReviewCycleJson) {
    Write-Error "Stage6ReviewCycleJson is required."
    exit 1
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\runtime-blocker-fallback-source-plan-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.runtime_blocker_fallback_source_plan",
    "--stage6-review-cycle-json", $Stage6ReviewCycleJson,
    "--output-root", $OutputRoot
)
if ($ReleaseFieldQueryJson) {
    $argsList += @("--release-field-query-json", $ReleaseFieldQueryJson)
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
