param(
    [string]$ActiveConflictRoot = "",
    [string]$ActiveConflictJson = "",
    [string]$OutputRoot = "",
    [switch]$EnableLivePublicQuery,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ActiveConflictRoot) {
    $ActiveConflictRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-active-conflict-probe-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-gdcic-query-probe-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_gdcic_query_probe",
    "--active-conflict-root", $ActiveConflictRoot,
    "--output-root", $OutputRoot
)

if ($ActiveConflictJson) {
    $argsList += @("--active-conflict-json", $ActiveConflictJson)
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
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
