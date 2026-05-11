param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [string]$CompanyFirstState = "NOT_RUN",
    [string]$NameEnumerationState = "NOT_RUN",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-human-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-responsible-person-early-probe-v1"
}

$outputJson = Join-Path $OutputRoot "responsible-person-early-probe.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.responsible_person_early_probe",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--company-first-state", $CompanyFirstState,
    "--name-enumeration-state", $NameEnumerationState,
    "--output-json", $outputJson
)

if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
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
