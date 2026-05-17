param(
    [string]$OutputRoot = "",
    [string]$RunResultJson = "",
    [int]$CandidateLimit = 10,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-real-public-stage4-9-pressure-v1"
}
if (-not $RunResultJson) {
    $RunResultJson = Join-Path $OutputRoot "run-result.json"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.real_public_stage4_9_pressure_report",
    "--mode", "build",
    "--output-root", $OutputRoot,
    "--run-result-json", $RunResultJson,
    "--candidate-limit", "$CandidateLimit"
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
