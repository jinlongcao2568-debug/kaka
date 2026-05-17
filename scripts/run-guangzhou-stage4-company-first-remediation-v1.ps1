param(
    [string]$RunResultJson = "",
    [string]$CandidatePressureJson = "",
    [string]$OutputRoot = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-stage4-company-first-remediation-v1"
}
if (-not $RunResultJson) {
    $RunResultJson = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-real-public-stage4-9-pressure-v1\run-result.json"
}
if (-not $CandidatePressureJson) {
    $CandidatePressureJson = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-real-public-stage4-9-pressure-v1\candidate-pressure-table.json"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_stage4_company_first_remediation",
    "--run-result-json", $RunResultJson,
    "--candidate-pressure-json", $CandidatePressureJson,
    "--output-root", $OutputRoot
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
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
