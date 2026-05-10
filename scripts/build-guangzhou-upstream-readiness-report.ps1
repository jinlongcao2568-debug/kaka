param(
    [string]$FlowRoot = "",
    [string]$DownloadRoot = "",
    [string]$EvidenceStrategyRoot = "",
    [string]$ArchiveExtractRoot = "",
    [string]$ParseRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $FlowRoot) {
    $FlowRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-v1"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-probe-v1"
}
if (-not $EvidenceStrategyRoot) {
    $EvidenceStrategyRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-strategy-v1"
}
if (-not $ArchiveExtractRoot) {
    $ArchiveExtractRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-archive-extract-probe-v1"
}
if (-not $ParseRoot) {
    $ParseRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-parse-probe-v2"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-upstream-readiness-v1"
}

$outputJson = Join-Path $OutputRoot "guangzhou-upstream-readiness-report.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_probe_readiness_report",
    "--flow-root", $FlowRoot,
    "--download-root", $DownloadRoot,
    "--evidence-strategy-root", $EvidenceStrategyRoot,
    "--archive-extract-root", $ArchiveExtractRoot,
    "--parse-root", $ParseRoot,
    "--output-root", $OutputRoot,
    "--output-json", $outputJson
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
