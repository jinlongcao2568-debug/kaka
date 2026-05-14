param(
    [string]$FlowRoot = "",
    [string]$DownloadRoot = "",
    [string]$ResponsiblePersonRoot = "",
    [string]$Stage4ExecutionRoot = "",
    [string]$ReadinessRoot = "",
    [string]$ActiveConflictProbeRoot = "",
    [string]$GdcicQueryProbeRoot = "",
    [string]$OfficialSourceReadbackRoot = "",
    [string]$CertificateSupplementCloseoutRoot = "",
    [string]$GuangdongLocalVerificationRoot = "",
    [string]$GuangdongLocalFieldQueryRoot = "",
    [string]$OutputRoot = "",
    [switch]$NoDefaultOptionalRoots,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $FlowRoot) {
    $FlowRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-72h-v1"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-human-v1"
}
if (-not $ResponsiblePersonRoot) {
    $ResponsiblePersonRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-responsible-person-early-probe-v3"
}
if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-v4-merged"
}
if (-not $ReadinessRoot) {
    $ReadinessRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-upstream-readiness-with-stage4-groups-v3"
}
if (-not $NoDefaultOptionalRoots -and -not $ActiveConflictProbeRoot) {
    $ActiveConflictProbeRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-active-conflict-probe-v1"
}
if (-not $NoDefaultOptionalRoots -and -not $GdcicQueryProbeRoot) {
    $GdcicQueryProbeRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-gdcic-query-probe-v1"
}
if (-not $NoDefaultOptionalRoots -and -not $OfficialSourceReadbackRoot) {
    $OfficialSourceReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-official-source-readback-closeout-v1"
}
if (-not $NoDefaultOptionalRoots -and -not $CertificateSupplementCloseoutRoot) {
    $CertificateSupplementCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\certificate-supplement-closeout-v1"
}
if (-not $NoDefaultOptionalRoots -and -not $GuangdongLocalVerificationRoot) {
    $GuangdongLocalVerificationRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-local-verification-probe-v1"
}
if (-not $NoDefaultOptionalRoots -and -not $GuangdongLocalFieldQueryRoot) {
    $GuangdongLocalFieldQueryRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-local-field-query-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-report-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_evidence_report",
    "--flow-root", $FlowRoot,
    "--download-root", $DownloadRoot,
    "--responsible-person-root", $ResponsiblePersonRoot,
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--readiness-root", $ReadinessRoot,
    "--output-root", $OutputRoot
)

if ($ActiveConflictProbeRoot) {
    $argsList += @("--active-conflict-probe-root", $ActiveConflictProbeRoot)
}
if ($GdcicQueryProbeRoot) {
    $argsList += @("--gdcic-query-probe-root", $GdcicQueryProbeRoot)
}
if ($OfficialSourceReadbackRoot) {
    $argsList += @("--official-source-readback-root", $OfficialSourceReadbackRoot)
}
if ($CertificateSupplementCloseoutRoot) {
    $argsList += @("--certificate-supplement-closeout-root", $CertificateSupplementCloseoutRoot)
}
if ($GuangdongLocalVerificationRoot) {
    $argsList += @("--guangdong-local-verification-root", $GuangdongLocalVerificationRoot)
}
if ($GuangdongLocalFieldQueryRoot) {
    $argsList += @("--guangdong-local-field-query-root", $GuangdongLocalFieldQueryRoot)
}
if ($NoDefaultOptionalRoots) {
    $argsList += "--no-default-optional-roots"
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
