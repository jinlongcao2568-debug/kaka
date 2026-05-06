param(
    [string]$TraceJson = "handoff/guangzhou_candidate_30_abcd_trace_20260503_impl.json",
    [string]$MergedStage4Json = "handoff/guangzhou_candidate_22_stage4_jzsc_merged_retry5_20260504_impl.json",
    [string]$RetryStage4Json = "handoff/guangzhou_candidate_11_stage4_jzsc_failed_retry5_optimized_20260504_impl.json",
    [string]$ProviderQueueJson = "handoff/guangzhou_stage4_provider_queue_live_gdcic_20260504_impl.json",
    [string]$ReviewJsonl = "handoff/guangzhou_11_stage4_review_matrix.jsonl",
    [string]$ReviewSummaryJson = "handoff/guangzhou_11_stage4_review_matrix.summary.json",
    [string]$ReviewMarkdown = "handoff/guangzhou_11_stage4_review_matrix.md",
    [string]$BlockerJsonl = "handoff/guangzhou_22_stage4_blocker_attribution.jsonl",
    [string]$BlockerSummaryJson = "handoff/guangzhou_22_stage4_blocker_attribution.summary.json",
    [string]$BlockerMarkdown = "handoff/guangzhou_22_stage4_blocker_attribution.md"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = (Join-Path $repoRoot "src")

Push-Location $repoRoot
try {
    python -X utf8 -m stage4_verification.guangzhou_stage4_review_matrix `
        --trace-json $TraceJson `
        --merged-stage4-json $MergedStage4Json `
        --retry-stage4-json $RetryStage4Json `
        --provider-queue-json $ProviderQueueJson `
        --review-jsonl $ReviewJsonl `
        --review-summary-json $ReviewSummaryJson `
        --review-markdown $ReviewMarkdown `
        --blocker-jsonl $BlockerJsonl `
        --blocker-summary-json $BlockerSummaryJson `
        --blocker-markdown $BlockerMarkdown
}
finally {
    Pop-Location
}
