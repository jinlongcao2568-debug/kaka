param(
    [string]$LocalVerificationRoot = "",
    [string]$LocalVerificationJson = "",
    [string]$OutputRoot = "",
    [string[]]$SourceProfileIds = @(),
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveTasks = 12,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $LocalVerificationRoot) {
    $LocalVerificationRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-local-verification-probe-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-local-field-query-probe-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_local_field_query_probe",
    "--local-verification-root", $LocalVerificationRoot,
    "--output-root", $OutputRoot
)

if ($LocalVerificationJson) {
    $argsList += @("--local-verification-json", $LocalVerificationJson)
}
if ($SourceProfileIds.Count -gt 0) {
    $argsList += "--source-profile-ids"
    $argsList += $SourceProfileIds
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
    $argsList += @("--max-live-tasks", "$MaxLiveTasks")
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
