param(
    [string]$SourceTargetsJson = "",
    [string]$OutputRoot = "",
    [int]$PerTargetSampleGoal = 12,
    [string]$GroupBy = "target",
    [int]$PerTargetCandidateLimit = 12,
    [int]$TargetLimit = 0,
    [int]$SegmentTimeoutSeconds = 900,
    [string]$OperatorDecision = "",
    [string]$OperatorName = "",
    [string]$OperatorDecisionNote = "",
    [switch]$ProfessionalSourceOnly,
    [switch]$Execute,
    [switch]$AutoExecuteSourceRemediation,
    [switch]$ForceRerun,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $SourceTargetsJson) {
    $SourceTargetsJson = Join-Path $repoRoot "contracts\evaluation\evaluation_real_project_sample_targets.json"
}

if (-not $OutputRoot) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-gray-public-orchestrator-$stamp"
}

$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

$sourceTargetsRoot = Join-Path $OutputRoot "source-targets"
$segmentsRoot = Join-Path $OutputRoot "segments"
$segmentRunsRoot = Join-Path $segmentsRoot "runs"
$segmentsJson = Join-Path $segmentsRoot "controlled-gray-public-batch-segments-v1.json"
$targetsJson = Join-Path $sourceTargetsRoot "controlled-gray-public-source-targets-v1.json"
$aggregateRoot = Join-Path $segmentsRoot "aggregate"
$approvedAggregateRoot = Join-Path $OutputRoot "aggregate-approved"
$finalAggregateRoot = $aggregateRoot
if ($OperatorDecision) {
    $finalAggregateRoot = $approvedAggregateRoot
}
$finalAggregateJson = Join-Path $finalAggregateRoot "controlled-gray-public-batch-segment-aggregate-v1.json"
$orchestratorJson = Join-Path $OutputRoot "controlled-gray-public-orchestrator-v1.json"
$sourceTargetsSummaryJson = Join-Path $sourceTargetsRoot "controlled-gray-public-source-targets-summary-v1.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$targetArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "build-controlled-gray-public-source-targets-v1.ps1"),
    "-SourceTargetsJson", $SourceTargetsJson,
    "-OutputRoot", $sourceTargetsRoot,
    "-PerTargetSampleGoal", "$PerTargetSampleGoal"
)

& pwsh @targetArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path $targetsJson)) {
    throw "controlled gray public source targets were not generated: $targetsJson"
}

$segmentArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "run-controlled-gray-public-batch-segments-v1.ps1"),
    "-TargetsJson", $targetsJson,
    "-OutputRoot", $segmentsRoot,
    "-RunRootBase", $segmentRunsRoot,
    "-GroupBy", $GroupBy,
    "-PerTargetCandidateLimit", "$PerTargetCandidateLimit",
    "-TargetLimit", "$TargetLimit",
    "-SegmentTimeoutSeconds", "$SegmentTimeoutSeconds"
)

if ($ProfessionalSourceOnly) {
    $segmentArgs += "-ProfessionalSourceOnly"
}

if ($Execute) {
    $segmentArgs += "-Execute"
}

if ($AutoExecuteSourceRemediation) {
    $segmentArgs += "-AutoExecuteSourceRemediation"
}

if ($ForceRerun) {
    $segmentArgs += "-ForceRerun"
}

& pwsh @segmentArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($OperatorDecision) {
    if (-not (Test-Path $segmentsJson)) {
        throw "controlled gray public segment plan was not generated: $segmentsJson"
    }
    $approvalArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $scriptDir "build-controlled-gray-public-batch-segment-aggregate-v1.ps1"),
        "-SegmentPlanJson", $segmentsJson,
        "-OutputRoot", $approvedAggregateRoot,
        "-OperatorDecision", $OperatorDecision
    )
    if ($OperatorName) {
        $approvalArgs += @("-OperatorName", $OperatorName)
    }
    if ($OperatorDecisionNote) {
        $approvalArgs += @("-OperatorDecisionNote", $OperatorDecisionNote)
    }
    & pwsh @approvalArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path $finalAggregateJson)) {
    throw "controlled gray public final aggregate was not generated: $finalAggregateJson"
}

if (-not (Test-Path $sourceTargetsSummaryJson)) {
    throw "controlled gray public source target summary was not generated: $sourceTargetsSummaryJson"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$orchestratorArgs = @(
    "-m", "runtime.controlled_gray_public_orchestrator",
    "--output-root", $OutputRoot,
    "--source-targets-json", $SourceTargetsJson,
    "--derived-targets-json", $targetsJson,
    "--source-targets-summary-json", $sourceTargetsSummaryJson,
    "--segments-json", $segmentsJson,
    "--aggregate-json", $finalAggregateJson,
    "--group-by", $GroupBy,
    "--per-target-sample-goal", "$PerTargetSampleGoal",
    "--per-target-candidate-limit", "$PerTargetCandidateLimit",
    "--target-limit", "$TargetLimit",
    "--segment-timeout-seconds", "$SegmentTimeoutSeconds"
)

if ($ProfessionalSourceOnly) {
    $orchestratorArgs += "--professional-source-only"
}

if ($Execute) {
    $orchestratorArgs += "--execute"
}

if ($AutoExecuteSourceRemediation) {
    $orchestratorArgs += "--auto-execute-source-remediation"
}

if ($ForceRerun) {
    $orchestratorArgs += "--force-rerun"
}

if ($OperatorDecision) {
    $orchestratorArgs += @("--operator-decision", $OperatorDecision)
}

if ($OperatorName) {
    $orchestratorArgs += @("--operator-name", $OperatorName)
}

if ($OperatorDecisionNote) {
    $orchestratorArgs += @("--operator-decision-note", $OperatorDecisionNote)
}

if ($EmitJson) {
    $orchestratorArgs += "--json"
}

Push-Location $repoRoot
try {
    python @orchestratorArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

if (-not (Test-Path $orchestratorJson)) {
    throw "controlled gray public orchestrator manifest was not generated: $orchestratorJson"
}

if (-not $EmitJson) {
    $orchestratorPayload = Get-Content -Raw -Path $orchestratorJson -Encoding UTF8 | ConvertFrom-Json
    $summary = $orchestratorPayload.summary
    Write-Host "controlled gray public orchestrator: orchestration=$($summary.orchestration_state) aggregate=$($summary.aggregate_gray_review_state) approval=$($summary.human_gray_launch_approval_state) samples=$($summary.project_sample_count) hashes=$($summary.fixed_snapshot_sha256_count) stage4_missing=$($summary.stage4_readback_missing_sample_count) source_remediation_final=$($summary.source_remediation_final_record_count)"
    Write-Host "orchestrator: $orchestratorJson"
    Write-Host "aggregate: $finalAggregateJson"
}
