param(
    [string[]]$SegmentRoots = @(),
    [string]$SegmentPlanJson = "",
    [string]$OutputRoot = "",
    [int]$GraySampleGoalMin = 100,
    [int]$GraySampleGoalMax = 200,
    [string]$OperatorDecision = "",
    [string]$OperatorName = "",
    [string]$OperatorDecisionNote = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-gray-public-batch-segment-aggregate-v1"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.controlled_gray_public_batch_segments",
    "aggregate",
    "--output-root", $OutputRoot,
    "--gray-sample-goal-min", "$GraySampleGoalMin",
    "--gray-sample-goal-max", "$GraySampleGoalMax"
)

if ($SegmentRoots -and $SegmentRoots.Count -gt 0) {
    $argsList += "--segment-roots"
    $argsList += $SegmentRoots
}

if ($SegmentPlanJson) {
    $argsList += @("--segment-plan-json", $SegmentPlanJson)
}

if ($OperatorDecision) {
    $argsList += @("--operator-decision", $OperatorDecision)
}

if ($OperatorName) {
    $argsList += @("--operator-name", $OperatorName)
}

if ($OperatorDecisionNote) {
    $argsList += @("--operator-decision-note", $OperatorDecisionNote)
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
