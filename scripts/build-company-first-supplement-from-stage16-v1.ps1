param(
    [string]$StorageJson = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [string]$CompanyFirstResultState = "NOT_RUN",
    [string]$NameEnumerationResultState = "NOT_RUN",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $StorageJson) {
    $storageCandidates = Get-ChildItem -Path (Join-Path $repoRoot "tmp\evaluation-real-samples") -Recurse -Filter "storage.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    if (-not $storageCandidates -or $storageCandidates.Count -eq 0) {
        throw "No stage16 storage.json found under tmp\evaluation-real-samples. Pass -StorageJson explicitly."
    }
    $StorageJson = $storageCandidates[0].FullName
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage16-company-first-supplement-v1"
}

$outputJson = Join-Path $OutputRoot "stage16-company-first-supplement-bridge.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.stage16_company_first_supplement_bridge",
    "--storage-json", $StorageJson,
    "--output-root", $OutputRoot,
    "--company-first-result-state", $CompanyFirstResultState,
    "--name-enumeration-result-state", $NameEnumerationResultState,
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
