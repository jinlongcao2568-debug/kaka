param(
    [string]$GdcicQueryProbeRoot = "",
    [string]$GdcicQueryProbeJson = "",
    [string]$EvidenceReportRoot = "",
    [string]$EvidenceReportJson = "",
    [string]$GuangdongLocalFieldQueryRoot = "",
    [string]$GuangdongLocalFieldQueryJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $GdcicQueryProbeRoot) {
    $GdcicQueryProbeRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-gdcic-query-probe-v1-live-max12"
}
if (-not $EvidenceReportRoot) {
    $EvidenceReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-report-closeout-v1"
}
if (-not $GuangdongLocalFieldQueryRoot) {
    $GuangdongLocalFieldQueryRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-local-field-query-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-official-source-readback-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_official_source_readback_closeout",
    "--gdcic-query-probe-root", $GdcicQueryProbeRoot,
    "--evidence-report-root", $EvidenceReportRoot,
    "--guangdong-local-field-query-root", $GuangdongLocalFieldQueryRoot,
    "--output-root", $OutputRoot
)

if ($GdcicQueryProbeJson) {
    $argsList += @("--gdcic-query-probe-json", $GdcicQueryProbeJson)
}
if ($EvidenceReportJson) {
    $argsList += @("--evidence-report-json", $EvidenceReportJson)
}
if ($GuangdongLocalFieldQueryJson) {
    $argsList += @("--guangdong-local-field-query-json", $GuangdongLocalFieldQueryJson)
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
