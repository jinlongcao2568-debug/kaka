param(
    [string]$InputRoot = "",
    [string]$StrategyRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "PROJ-CN-GD-JG2026-10815,PROJ-CN-GD-JG2026-11021",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [int]$MaxExtractFiles = 12,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-probe-v1"
}
if (-not $StrategyRoot) {
    $StrategyRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-strategy-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-archive-extract-probe-v1"
}
if (-not $StoragePath) {
    $StoragePath = Join-Path $InputRoot "storage.json"
}
if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $InputRoot "objects"
}

$outputJson = Join-Path $OutputRoot "archive-extract-probe-manifest.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_archive_extract_probe",
    "--input-root", $InputRoot,
    "--strategy-root", $StrategyRoot,
    "--output-root", $OutputRoot,
    "--project-ids", $ProjectIds,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--max-extract-files", ([string]$MaxExtractFiles),
    "--output-json", $outputJson
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
