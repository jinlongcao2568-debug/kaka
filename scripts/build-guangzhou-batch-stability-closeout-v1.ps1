param(
    [string]$FlowRoot = "",
    [string]$DownloadRoot = "",
    [string]$ResponsiblePersonRoot = "",
    [string]$Stage4ExecutionRoot = "",
    [string]$ReadinessRoot = "",
    [string]$EvidenceReportRoot = "",
    [string]$CertificateSupplementRoot = "",
    [string]$InternalPackageRoot = "",
    [string]$FixationBackfillRoot = "",
    [string]$RecaptureRoot = "",
    [string]$ReadableReportRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $FlowRoot) {
    $FlowRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-p11-10-v1"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-p11-10-v1"
}
if (-not $ResponsiblePersonRoot) {
    $ResponsiblePersonRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-responsible-person-p11-10-v1"
}
if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-p11-10-v1"
}
if (-not $ReadinessRoot) {
    $ReadinessRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-upstream-readiness-p11-10-v1"
}
if (-not $EvidenceReportRoot) {
    $EvidenceReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-report-p11-10-final-v1"
}
if (-not $CertificateSupplementRoot) {
    $CertificateSupplementRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\certificate-supplement-closeout-p11-10-v1"
}
if (-not $InternalPackageRoot) {
    $InternalPackageRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-internal-evidence-package-manifest-p11-10-p9-v1"
}
if (-not $FixationBackfillRoot) {
    $FixationBackfillRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-fixation-backfill-p11-10-v1"
}
if (-not $RecaptureRoot) {
    $RecaptureRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-fixation-recapture-p11-10-v1"
}
if (-not $ReadableReportRoot) {
    $ReadableReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-readable-report-p11-10-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-batch-stability-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_batch_stability_closeout",
    "--flow-root", $FlowRoot,
    "--download-root", $DownloadRoot,
    "--responsible-person-root", $ResponsiblePersonRoot,
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--readiness-root", $ReadinessRoot,
    "--evidence-report-root", $EvidenceReportRoot,
    "--certificate-supplement-root", $CertificateSupplementRoot,
    "--internal-package-root", $InternalPackageRoot,
    "--fixation-backfill-root", $FixationBackfillRoot,
    "--recapture-root", $RecaptureRoot,
    "--readable-report-root", $ReadableReportRoot,
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
