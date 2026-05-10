param(
    [string]$OutputRoot = "",
    [string]$RealSampleExecutionManifestJson = "",
    [string]$ProjectFileAuditJson = "",
    [string]$ChallengeStabilityReportJson = "",
    [string]$GoldenContractJson = "",
    [string]$OutputJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-post-candidate-v2-batch"
}

if (-not $RealSampleExecutionManifestJson) {
    $RealSampleExecutionManifestJson = Join-Path $OutputRoot "run-manifest.json"
}

if (-not $ProjectFileAuditJson) {
    $ProjectFileAuditJson = Join-Path $OutputRoot "project-file-audit.json"
}

if (-not $ChallengeStabilityReportJson) {
    $ChallengeStabilityReportJson = Join-Path $OutputRoot "challenge-stability-report.json"
}

if (-not $GoldenContractJson) {
    $GoldenContractJson = Join-Path $repoRoot "contracts\evaluation\guangzhou_12_flow_golden_projects.json"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $OutputRoot "guangzhou-post-candidate-acceptance-report.json"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_post_candidate_acceptance_report",
    "--output-root", $OutputRoot,
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
    "--project-file-audit-json", $ProjectFileAuditJson,
    "--challenge-stability-report-json", $ChallengeStabilityReportJson,
    "--golden-contract-json", $GoldenContractJson,
    "--output-json", $OutputJson
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
