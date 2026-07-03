param(
    [string]$EvidenceSummaryJson = "",
    [string]$RealSampleExecutionJson = "",
    [string]$Stage4ReadbackJson = "",
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

if (-not $EvidenceSummaryJson) {
    $EvidenceSummaryJson = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-20260703-v1\evidence-summary\controlled-live-public-batch-evidence-summary-v1.json"
}

if (-not $Stage4ReadbackJson) {
    $Stage4ReadbackJson = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-20260703-v1\stage4-readback\controlled-live-public-batch-stage4-readback-v1.json"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-20260703-v1\source-remediation"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.controlled_live_public_batch_source_remediation",
    "--evidence-summary-json", $EvidenceSummaryJson,
    "--real-sample-execution-json", $RealSampleExecutionJson,
    "--stage4-readback-json", $Stage4ReadbackJson,
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
