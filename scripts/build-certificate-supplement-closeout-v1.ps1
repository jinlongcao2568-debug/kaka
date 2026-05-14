param(
    [string]$EvidenceReportRoot = "",
    [string]$Stage4ExecutionRoot = "",
    [string]$OfficialSourceReadbackRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $EvidenceReportRoot) {
    $EvidenceReportRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-report-p5-closeout-v1"
}
if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-v4-merged"
}
if (-not $OfficialSourceReadbackRoot) {
    $OfficialSourceReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-official-source-readback-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\certificate-supplement-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.certificate_supplement_closeout",
    "--evidence-report-root", $EvidenceReportRoot,
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--official-source-readback-root", $OfficialSourceReadbackRoot,
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
