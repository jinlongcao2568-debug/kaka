param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$ProviderJobsJson = "",
    [string]$Stage4InputsJson = "",
    [string]$ProjectIds = "",
    [string]$CandidateGroupIds = "",
    [int]$MaxPersonnelPages = 12,
    [int]$MaxProjectPages = 3,
    [int]$PersonnelRetryAttempts = 2,
    [switch]$CapturePersonnelProjectRecords,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-supplement-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-v1"
}

$outputJson = Join-Path $OutputRoot "company-first-stage4-execution.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.company_first_stage4_execution",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--max-personnel-pages", "$MaxPersonnelPages",
    "--max-project-pages", "$MaxProjectPages",
    "--personnel-retry-attempts", "$PersonnelRetryAttempts",
    "--output-json", $outputJson
)

if ($ProviderJobsJson) {
    $argsList += @("--provider-jobs-json", $ProviderJobsJson)
}
if ($Stage4InputsJson) {
    $argsList += @("--stage4-inputs-json", $Stage4InputsJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($CandidateGroupIds) {
    $argsList += @("--candidate-group-ids", $CandidateGroupIds)
}
if ($CapturePersonnelProjectRecords) {
    $argsList += "--capture-personnel-project-records"
}
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
