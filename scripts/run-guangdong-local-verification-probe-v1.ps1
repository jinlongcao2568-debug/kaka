param(
    [string]$ActiveConflictRoot = "",
    [string]$ActiveConflictJson = "",
    [string]$OutputRoot = "",
    [string[]]$SourceProfileIds = @(),
    [switch]$EnableLiveReachability,
    [int]$MaxLiveTasks = 6,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ActiveConflictRoot) {
    $ActiveConflictRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-active-conflict-probe-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-local-verification-probe-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_local_verification_probe",
    "--active-conflict-root", $ActiveConflictRoot,
    "--output-root", $OutputRoot
)

if ($ActiveConflictJson) {
    $argsList += @("--active-conflict-json", $ActiveConflictJson)
}
if ($SourceProfileIds.Count -gt 0) {
    $argsList += "--source-profile-ids"
    $argsList += $SourceProfileIds
}
if ($EnableLiveReachability) {
    $argsList += "--enable-live-reachability"
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
