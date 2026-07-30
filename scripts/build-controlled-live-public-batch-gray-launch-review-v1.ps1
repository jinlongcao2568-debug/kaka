param(
    [string]$RunRoot = "",
    [string]$CloseoutJson = "",
    [string]$EvidenceSummaryJson = "",
    [string]$Stage4ReadbackJson = "",
    [string]$SourceRemediationJson = "",
    [string]$SourceRemediationExecutionJson = "",
    [string]$RunManifestJson = "",
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

if ($RunRoot) {
    $RunRoot = Resolve-Path $RunRoot
}

if ($RunRoot -and -not $CloseoutJson) {
    $CloseoutJson = Join-Path $RunRoot "controlled-live-public-batch-closeout.json"
}

if ($RunRoot -and -not $RunManifestJson) {
    $RunManifestJson = Join-Path $RunRoot "run-manifest.json"
}

if ($RunRoot -and -not $EvidenceSummaryJson) {
    $EvidenceSummaryJson = Join-Path $RunRoot "evidence-summary\controlled-live-public-batch-evidence-summary-v1.json"
}

if ($RunRoot -and -not $Stage4ReadbackJson) {
    $Stage4ReadbackJson = Join-Path $RunRoot "stage4-readback\controlled-live-public-batch-stage4-readback-v1.json"
}

if ($RunRoot -and -not $SourceRemediationJson) {
    $SourceRemediationJson = Join-Path $RunRoot "source-remediation\controlled-live-public-batch-source-remediation-v1.json"
}

if ($RunRoot -and -not $SourceRemediationExecutionJson) {
    $candidate = Join-Path $RunRoot "source-remediation-execution\controlled-live-public-batch-source-remediation-execution-v1.json"
    if (Test-Path $candidate) {
        $SourceRemediationExecutionJson = $candidate
    }
}

if ($RunRoot -and -not $OutputRoot) {
    $OutputRoot = Join-Path $RunRoot "gray-launch-review"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-gray-launch-review-v1"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.controlled_live_public_batch_gray_launch_review",
    "--output-root", $OutputRoot,
    "--gray-sample-goal-min", "$GraySampleGoalMin",
    "--gray-sample-goal-max", "$GraySampleGoalMax"
)

if ($OperatorDecision) {
    $argsList += @("--operator-decision", $OperatorDecision)
}

if ($OperatorName) {
    $argsList += @("--operator-name", $OperatorName)
}

if ($OperatorDecisionNote) {
    $argsList += @("--operator-decision-note", $OperatorDecisionNote)
}

if ($CloseoutJson) {
    $argsList += @("--closeout-json", $CloseoutJson)
}

if ($EvidenceSummaryJson) {
    $argsList += @("--evidence-summary-json", $EvidenceSummaryJson)
}

if ($Stage4ReadbackJson) {
    $argsList += @("--stage4-readback-json", $Stage4ReadbackJson)
}

if ($SourceRemediationJson) {
    $argsList += @("--source-remediation-json", $SourceRemediationJson)
}

if ($SourceRemediationExecutionJson) {
    $argsList += @("--source-remediation-execution-json", $SourceRemediationExecutionJson)
}

if ($RunManifestJson) {
    $argsList += @("--run-manifest-json", $RunManifestJson)
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
