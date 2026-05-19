param(
    [string]$DispatchCloseoutJson = "",
    [string]$DispatchCloseoutRoot = "",
    [string]$BaselineEvidenceStateJson = "",
    [string]$BaselineEvidenceStateRoot = "",
    [string]$EvidenceStateRebuildOutputRoot = "",
    [string]$ReleaseEvidenceFieldQueryOutputRoot = "",
    [string]$BatchCloseoutRebuildOutputRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DispatchCloseoutRoot) {
    $DispatchCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-closeout-v1"
}
if (-not $BaselineEvidenceStateRoot) {
    $BaselineEvidenceStateRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-orchestration-state-v1"
}
if (-not $EvidenceStateRebuildOutputRoot) {
    $EvidenceStateRebuildOutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-state-rebuild-from-stage6-routing-v1"
}
if (-not $ReleaseEvidenceFieldQueryOutputRoot) {
    $ReleaseEvidenceFieldQueryOutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\release-evidence-field-query-from-stage6-routing-v1"
}
if (-not $BatchCloseoutRebuildOutputRoot) {
    $BatchCloseoutRebuildOutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-batch-closeout-from-stage6-routing-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-result-routing-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_action_result_routing",
    "--dispatch-closeout-root", $DispatchCloseoutRoot,
    "--baseline-evidence-state-root", $BaselineEvidenceStateRoot,
    "--evidence-state-rebuild-output-root", $EvidenceStateRebuildOutputRoot,
    "--release-evidence-field-query-output-root", $ReleaseEvidenceFieldQueryOutputRoot,
    "--batch-closeout-rebuild-output-root", $BatchCloseoutRebuildOutputRoot,
    "--output-root", $OutputRoot
)

if ($DispatchCloseoutJson) {
    $argsList += @("--dispatch-closeout-json", $DispatchCloseoutJson)
}
if ($BaselineEvidenceStateJson) {
    $argsList += @("--baseline-evidence-state-json", $BaselineEvidenceStateJson)
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
