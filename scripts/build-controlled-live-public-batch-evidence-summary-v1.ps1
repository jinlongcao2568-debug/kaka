param(
    [string]$RealSampleExecutionJson = "",
    [string]$StorageJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RealSampleExecutionJson) {
    $RealSampleExecutionJson = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-20260703-v1\evaluation-real-sample-execution\real-sample-execution.json"
}

if (-not $StorageJson) {
    $StorageJson = Join-Path (Split-Path -Parent $RealSampleExecutionJson) "storage.json"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-20260703-v1\evidence-summary"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.controlled_live_public_batch_evidence_summary",
    "--real-sample-execution-json", $RealSampleExecutionJson,
    "--storage-json", $StorageJson,
    "--output-root", $OutputRoot
)

if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
