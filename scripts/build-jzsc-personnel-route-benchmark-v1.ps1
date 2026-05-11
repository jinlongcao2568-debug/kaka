param(
    [string]$Stage4ExecutionRoot = "",
    [string]$OutputRoot = "",
    [int]$MaxTargets = 12,
    [int]$MaxNameOnlyPages = 3,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-v4-merged"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\jzsc-personnel-route-benchmark-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.jzsc_personnel_route_benchmark",
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--output-root", $OutputRoot,
    "--max-targets", "$MaxTargets",
    "--max-name-only-pages", "$MaxNameOnlyPages"
)

if ($Execute) {
    $argsList += "--execute"
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
