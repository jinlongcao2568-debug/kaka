param(
    [string]$CompanyHistoryTriageRoot = "",
    [string]$OriginalNoticeBacktraceRoot = "",
    [string]$YgpReadbackRoot = "",
    [string]$YgpCoverageCloseoutRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $CompanyHistoryTriageRoot) {
    $CompanyHistoryTriageRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-company-history-overlap-triage-ygp-v1"
}
if (-not $OriginalNoticeBacktraceRoot) {
    $OriginalNoticeBacktraceRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-notice-backtrace-ygp-v1-ygpreadback"
}
if (-not $YgpReadbackRoot) {
    $YgpReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-ygp-original-readback-p13b-v1"
}
if (-not $YgpCoverageCloseoutRoot) {
    $YgpCoverageCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-ygp-city-coverage-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-overlap-triage-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.p13b_overlap_triage_closeout",
    "--company-history-triage-root", $CompanyHistoryTriageRoot,
    "--original-notice-backtrace-root", $OriginalNoticeBacktraceRoot,
    "--ygp-readback-root", $YgpReadbackRoot,
    "--ygp-coverage-closeout-root", $YgpCoverageCloseoutRoot,
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
