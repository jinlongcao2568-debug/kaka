param(
    [string]$BatchStabilityRoot = "",
    [string]$EvidenceReportRoot = "",
    [string]$ReadableReportRoot = "",
    [string]$InternalPackageRoot = "",
    [string]$FixationBackfillRoot = "",
    [string]$Stage4ExecutionRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $BatchStabilityRoot) {
    $BatchStabilityRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-batch-stability-closeout-p11-10-highwayfix-v1"
}
if (-not $EvidenceReportRoot) {
    $EvidenceReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-report-p11-10-highwayfix-final-v1"
}
if (-not $ReadableReportRoot) {
    $ReadableReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-readable-report-p11-10-highwayfix-v1"
}
if (-not $InternalPackageRoot) {
    $InternalPackageRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-internal-evidence-package-manifest-p11-10-highwayfix-p9-v1"
}
if (-not $FixationBackfillRoot) {
    $FixationBackfillRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-fixation-backfill-p11-10-highwayfix-p9-v1"
}
if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-p11-10-highwayfix-merged-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-value-closeout-p12-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_evidence_value_closeout",
    "--batch-stability-root", $BatchStabilityRoot,
    "--evidence-report-root", $EvidenceReportRoot,
    "--readable-report-root", $ReadableReportRoot,
    "--internal-package-root", $InternalPackageRoot,
    "--fixation-backfill-root", $FixationBackfillRoot,
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--output-root", $OutputRoot
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
