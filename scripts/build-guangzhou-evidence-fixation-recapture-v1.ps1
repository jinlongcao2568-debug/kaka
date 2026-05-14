param(
    [string]$BackfillRoot = "",
    [string]$InternalPackageRoot = "",
    [string]$FlowRoot = "",
    [string]$DownloadRoot = "",
    [string]$Stage4ExecutionRoot = "",
    [string]$OutputRoot = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $BackfillRoot) {
    $BackfillRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-fixation-backfill-v1"
}
if (-not $InternalPackageRoot) {
    $InternalPackageRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-internal-evidence-package-manifest-p8-v1"
}
if (-not $FlowRoot) {
    $FlowRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-72h-v1"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-human-v1"
}
if (-not $Stage4ExecutionRoot) {
    $Stage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-stage4-execution-v4-merged"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-fixation-recapture-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_evidence_fixation_recapture",
    "--backfill-root", $BackfillRoot,
    "--internal-package-root", $InternalPackageRoot,
    "--flow-root", $FlowRoot,
    "--download-root", $DownloadRoot,
    "--stage4-execution-root", $Stage4ExecutionRoot,
    "--output-root", $OutputRoot
)

if ($Execute) {
    $argsList += "--execute"
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
