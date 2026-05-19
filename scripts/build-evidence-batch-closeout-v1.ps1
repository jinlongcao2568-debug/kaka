param(
    [string]$EvidenceStateJson = "",
    [string]$EvidenceStateRoot = "",
    [string]$ContinuationRunJson = "",
    [string]$ContinuationRunRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $EvidenceStateRoot) {
    $EvidenceStateRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-orchestration-state-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-batch-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.evidence_batch_closeout",
    "--evidence-state-root", $EvidenceStateRoot,
    "--output-root", $OutputRoot
)

if ($EvidenceStateJson) {
    $argsList += @("--evidence-state-json", $EvidenceStateJson)
}
if ($ContinuationRunJson) {
    $argsList += @("--continuation-run-json", $ContinuationRunJson)
}
if ($ContinuationRunRoot) {
    $argsList += @("--continuation-run-root", $ContinuationRunRoot)
}
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
