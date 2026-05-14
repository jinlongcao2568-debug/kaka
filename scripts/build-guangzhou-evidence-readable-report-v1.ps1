param(
    [string]$EvidenceReportRoot = "",
    [string]$EvidenceReportJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $EvidenceReportRoot) {
    $EvidenceReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-report-p3-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-readable-report-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_evidence_readable_report",
    "--evidence-report-root", $EvidenceReportRoot,
    "--output-root", $OutputRoot
)

if ($EvidenceReportJson) {
    $argsList += @("--evidence-report-json", $EvidenceReportJson)
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
