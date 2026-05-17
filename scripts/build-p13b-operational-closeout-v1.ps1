param(
    [string]$CompanyHistoryTriageRoot = "",
    [string]$OriginalNoticeBacktraceRoot = "",
    [string]$OverlapTriageCloseoutRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $CompanyHistoryTriageRoot) {
    $CompanyHistoryTriageRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-company-history-overlap-triage-v1"
}
if (-not $OriginalNoticeBacktraceRoot) {
    $OriginalNoticeBacktraceRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-notice-backtrace-v1"
}
if (-not $OverlapTriageCloseoutRoot) {
    $OverlapTriageCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-overlap-triage-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-operational-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.p13b_operational_closeout",
    "--company-history-triage-root", $CompanyHistoryTriageRoot,
    "--original-notice-backtrace-root", $OriginalNoticeBacktraceRoot,
    "--overlap-triage-closeout-root", $OverlapTriageCloseoutRoot,
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
