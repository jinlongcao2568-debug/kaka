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

$aggregatePayload = Get-Content -Raw -Path $finalAggregateJson -Encoding UTF8 | ConvertFrom-Json
$summary = $aggregatePayload.summary
$orchestrator = [ordered]@{
    manifest_kind = "controlled_gray_public_orchestrator_v1"
    output_root = "$OutputRoot"
    source_targets_json = "$SourceTargetsJson"
    derived_targets_json = "$targetsJson"
    segments_json = "$segmentsJson"
    aggregate_json = "$finalAggregateJson"
    execute = [bool]$Execute
    group_by = "$GroupBy"
    per_target_sample_goal = $PerTargetSampleGoal
    per_target_candidate_limit = $PerTargetCandidateLimit
    target_limit = $TargetLimit
    segment_timeout_seconds = $SegmentTimeoutSeconds
    professional_source_only = [bool]$ProfessionalSourceOnly
    auto_execute_source_remediation = [bool]$AutoExecuteSourceRemediation
    force_rerun = [bool]$ForceRerun
    operator_decision = "$OperatorDecision"
    aggregate_gray_review_state = [string]$summary.aggregate_gray_review_state
    human_gray_launch_approval_state = [string]$summary.human_gray_launch_approval_state
    approved_for_controlled_gray_execution = [bool]$summary.approved_for_controlled_gray_execution
    project_sample_count = [int]$summary.project_sample_count
    fixed_snapshot_sha256_count = [int]$summary.fixed_snapshot_sha256_count
    stage4_readback_ready_sample_count = [int]$summary.stage4_readback_ready_sample_count
    stage4_readback_missing_sample_count = [int]$summary.stage4_readback_missing_sample_count
    source_remediation_final_record_count = [int]$summary.source_remediation_final_record_count
    customer_visible_allowed = $false
    external_send_enabled = $false
    payment_execution_enabled = $false
    delivery_execution_enabled = $false
    automatic_refund_enabled = $false
    query_miss_is_not_clearance = $true
    no_legal_conclusion = $true
}

$orchestrator | ConvertTo-Json -Depth 8 | Set-Content -Path $orchestratorJson -Encoding UTF8

if ($EmitJson) {
    $orchestrator | ConvertTo-Json -Depth 8
} else {
    Write-Host "controlled gray public orchestrator: state=$($summary.aggregate_gray_review_state) approval=$($summary.human_gray_launch_approval_state) samples=$($summary.project_sample_count) hashes=$($summary.fixed_snapshot_sha256_count) stage4_missing=$($summary.stage4_readback_missing_sample_count) source_remediation_final=$($summary.source_remediation_final_record_count)"
    Write-Host "orchestrator: $orchestratorJson"
    Write-Host "aggregate: $finalAggregateJson"
}
