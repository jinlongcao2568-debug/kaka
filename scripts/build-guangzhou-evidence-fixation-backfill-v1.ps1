param(
    [string]$InternalEvidencePackageRoot = "",
    [string]$DownloadRoot = "",
    [string]$FlowRoot = "",
    [string]$GdcicQueryProbeRoot = "",
    [string]$Stage4ExecutionRoot = "",
    [string]$RecaptureRoot = "",
    [string]$OutputRoot = "",
    [switch]$GdcicQueryOptional,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InternalEvidencePackageRoot) {
    $InternalEvidencePackageRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-internal-evidence-package-manifest-v1"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-human-v1"
}
if (-not $FlowRoot) {
    $FlowRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-72h-v1"
}
if (-not $GdcicQueryProbeRoot) {
    $GdcicQueryProbeRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-gdcic-query-probe-v1-live-max12"
}
if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-v4-merged"
}
if (-not $RecaptureRoot) {
    $RecaptureRoot = ""
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-fixation-backfill-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_evidence_fixation_backfill",
    "--internal-evidence-package-root", $InternalEvidencePackageRoot,
    "--download-root", $DownloadRoot,
    "--flow-root", $FlowRoot,
    "--gdcic-query-probe-root", $GdcicQueryProbeRoot,
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--output-root", $OutputRoot
)

if ($GdcicQueryOptional) {
    $argsList += "--gdcic-query-optional"
}
if ($RecaptureRoot) {
    $argsList += @("--recapture-root", $RecaptureRoot)
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
