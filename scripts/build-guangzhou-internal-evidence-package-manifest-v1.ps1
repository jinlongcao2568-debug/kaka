param(
    [string]$EvidenceReportRoot = "",
    [string]$CertificateSupplementRoot = "",
    [string]$OfficialSourceReadbackRoot = "",
    [string]$Stage4ExecutionRoot = "",
    [string]$DownloadRoot = "",
    [string]$FlowRoot = "",
    [string]$FixationBackfillRoot = "",
    [string]$OutputRoot = "",
    [switch]$OfficialSourceOptional,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $EvidenceReportRoot) {
    $EvidenceReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-report-p6-closeout-v1"
}
if (-not $CertificateSupplementRoot) {
    $CertificateSupplementRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\certificate-supplement-closeout-v1"
}
if (-not $OfficialSourceReadbackRoot) {
    $OfficialSourceReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-official-source-readback-closeout-v1"
}
if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-v4-merged"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-human-v1"
}
if (-not $FlowRoot) {
    $FlowRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-72h-v1"
}
if (-not $FixationBackfillRoot) {
    $FixationBackfillRoot = ""
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-internal-evidence-package-manifest-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_internal_evidence_package_manifest",
    "--evidence-report-root", $EvidenceReportRoot,
    "--certificate-supplement-root", $CertificateSupplementRoot,
    "--official-source-readback-root", $OfficialSourceReadbackRoot,
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--download-root", $DownloadRoot,
    "--flow-root", $FlowRoot,
    "--output-root", $OutputRoot
)

if ($OfficialSourceOptional) {
    $argsList += "--official-source-optional"
}
if ($FixationBackfillRoot) {
    $argsList += @("--fixation-backfill-root", $FixationBackfillRoot)
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
