param(
    [string]$OutputRoot = "",
    [string]$RealSampleExecutionManifestJson = "",
    [string]$ProjectFileAuditJson = "",
    [string]$BusinessDirectionContractJson = "",
    [string]$OutputJson = "",
    [string]$Now = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-post-candidate-v1"
}

if (-not $RealSampleExecutionManifestJson) {
    $RealSampleExecutionManifestJson = Join-Path $OutputRoot "run-manifest.json"
}

if (-not $ProjectFileAuditJson) {
    $ProjectFileAuditJson = Join-Path $OutputRoot "project-file-audit.json"
}

if (-not $BusinessDirectionContractJson) {
    $BusinessDirectionContractJson = Join-Path $repoRoot "contracts\evaluation\business_direction_strategy_contract.json"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $OutputRoot "analysis-plan.json"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.product_analysis_strategy_plan",
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
    "--business-direction-contract-json", $BusinessDirectionContractJson,
    "--output-json", $OutputJson
)

if ($ProjectFileAuditJson -and (Test-Path $ProjectFileAuditJson)) {
    $argsList += @("--project-file-audit-json", $ProjectFileAuditJson)
}

if ($Now) {
    $argsList += @("--now", $Now)
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
