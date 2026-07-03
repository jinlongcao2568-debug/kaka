param(
    [string]$RunRoot = "",
    [string[]]$TargetIds = @(),
    [int]$TargetLimit = 25,
    [int]$PerTargetCandidateLimit = 2,
    [switch]$ProfessionalSourceOnly,
    [switch]$Execute,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RunRoot) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $RunRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-$stamp"
}

$runManifestJson = Join-Path $RunRoot "run-manifest.json"
$storagePath = Join-Path $RunRoot "storage.json"
$objectStoragePath = Join-Path $RunRoot "objects"
$evidenceSummaryRoot = Join-Path $RunRoot "evidence-summary"
$evidenceSummaryJson = Join-Path $evidenceSummaryRoot "controlled-live-public-batch-evidence-summary-v1.json"
$evidenceSummaryMarkdown = Join-Path $evidenceSummaryRoot "controlled-live-public-batch-evidence-summary-v1.md"
$archiveAuditJson = Join-Path $RunRoot "project-file-audit.json"
$closeoutJson = Join-Path $RunRoot "controlled-live-public-batch-closeout.json"

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null

$runArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "run-evaluation-real-sample-execution.ps1"),
    "-PerTargetCandidateLimit", "$PerTargetCandidateLimit",
    "-TargetBackend", "json-file",
    "-StoragePath", $storagePath,
    "-ObjectStoragePath", $objectStoragePath,
    "-OutputJson", $runManifestJson
)

if ($TargetIds -and $TargetIds.Count -gt 0) {
    $runArgs += "-TargetIds"
    $runArgs += $TargetIds
} else {
    $runArgs += "-UseAllTargets"
}

if ($TargetLimit -gt 0) {
    $runArgs += @("-TargetLimit", "$TargetLimit")
}

if ($ProfessionalSourceOnly) {
    $runArgs += "-ProfessionalSourceOnly"
}

if ($EnableAttachmentChallengeResolver) {
    $runArgs += "-EnableAttachmentChallengeResolver"
}

if ($Execute) {
    $runArgs += "-Execute"
}

& pwsh @runArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$evidenceSummaryArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "build-controlled-live-public-batch-evidence-summary-v1.ps1"),
    "-RealSampleExecutionJson", $runManifestJson,
    "-StorageJson", $storagePath,
    "-OutputRoot", $evidenceSummaryRoot
)

& pwsh @evidenceSummaryArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$archiveArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "build-professional-clean-project-archive.ps1"),
    "-RealSampleExecutionManifestJson", $runManifestJson,
    "-OutputRoot", $RunRoot,
    "-StoragePath", $storagePath,
    "-ObjectStoragePath", $objectStoragePath,
    "-OutputJson", $archiveAuditJson
)

& pwsh @archiveArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path $evidenceSummaryJson)) {
    throw "controlled live batch evidence summary was not generated: $evidenceSummaryJson"
}

if (-not (Test-Path $archiveAuditJson)) {
    throw "controlled live batch archive audit was not generated: $archiveAuditJson"
}

$summaryPayload = Get-Content -Raw -Path $evidenceSummaryJson -Encoding UTF8 | ConvertFrom-Json
$summary = $summaryPayload.summary
$stage4RequiredCount = [int]$summary.stage4_evidence_readback_required_count
$partialOrBlockedCount = [int]$summary.public_source_outcome_counts.PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW
$noMatchCount = [int]$summary.public_source_outcome_counts.PUBLIC_SOURCE_NO_MATCH_REVIEW
$hashedCount = [int]$summary.fixed_snapshot_sha256_count
$sampleCount = [int]$summary.project_sample_count

$grayLaunchDecision = "NOT_READY_REAL_PUBLIC_EXECUTION_REQUIRED"
$nextRequiredStep = "rerun_controlled_live_public_batch_with_execute"
if ($Execute -and $sampleCount -le 0) {
    $grayLaunchDecision = "NOT_READY_NO_REAL_PUBLIC_SAMPLES"
    $nextRequiredStep = "expand_or_fix_public_source_targets"
} elseif ($Execute -and $stage4RequiredCount -gt 0) {
    $grayLaunchDecision = "NOT_READY_STAGE4_EVIDENCE_READBACK_REQUIRED"
    $nextRequiredStep = "run_stage4_evidence_readback_for_hashed_public_snapshots"
} elseif ($Execute -and ($partialOrBlockedCount -gt 0 -or $noMatchCount -gt 0)) {
    $grayLaunchDecision = "NOT_READY_SOURCE_REVIEW_REQUIRED"
    $nextRequiredStep = "review_partial_blocked_and_no_match_public_sources"
} elseif ($Execute -and $sampleCount -gt 0) {
    $grayLaunchDecision = "ELIGIBLE_FOR_GRAY_LAUNCH_REVIEW"
    $nextRequiredStep = "human_gray_launch_review"
}

$closeout = [ordered]@{
    manifest_kind = "controlled_live_public_batch_closeout_v1"
    run_root = "$RunRoot"
    execute = [bool]$Execute
    target_limit = $TargetLimit
    per_target_candidate_limit = $PerTargetCandidateLimit
    run_manifest_json = "$runManifestJson"
    storage_json = "$storagePath"
    object_storage_path = "$objectStoragePath"
    evidence_summary_json = "$evidenceSummaryJson"
    evidence_summary_markdown = "$evidenceSummaryMarkdown"
    archive_audit_json = "$archiveAuditJson"
    closeout_json = "$closeoutJson"
    sample_count = $sampleCount
    fixed_snapshot_sha256_count = $hashedCount
    stage4_evidence_readback_required_count = $stage4RequiredCount
    partial_or_blocked_count = $partialOrBlockedCount
    no_match_count = $noMatchCount
    customer_visible_allowed = $false
    external_send_enabled = $false
    payment_execution_enabled = $false
    delivery_execution_enabled = $false
    automatic_refund_enabled = $false
    query_miss_is_not_clearance = $true
    no_legal_conclusion = $true
    gray_launch_decision = $grayLaunchDecision
    next_required_step = $nextRequiredStep
}

$closeout | ConvertTo-Json -Depth 8 | Set-Content -Path $closeoutJson -Encoding UTF8

if ($EmitJson) {
    $closeout | ConvertTo-Json -Depth 8
} else {
    Write-Host "controlled live public batch closeout: sample_count=$sampleCount fixed_snapshot_sha256_count=$hashedCount stage4_required=$stage4RequiredCount partial_or_blocked=$partialOrBlockedCount gray_launch_decision=$grayLaunchDecision"
    Write-Host "evidence summary: $evidenceSummaryJson"
    Write-Host "evidence graph markdown: $evidenceSummaryMarkdown"
    Write-Host "archive audit: $archiveAuditJson"
}
