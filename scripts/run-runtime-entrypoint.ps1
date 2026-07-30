param(
    [Parameter(Mandatory = $true)]
    [string]$EntrypointId,
    [string]$PayloadJson = "",
    [string]$Payload = "",
    [string]$BatchCloseoutJson = "",
    [string]$BatchCloseoutRoot = "",
    [string]$RuntimeBlockerNextSubqueueJson = "",
    [string]$RuntimeBlockerNextSubqueueRoot = "",
    [string]$Stage6ReviewLoopJson = "",
    [string]$Stage6ReviewLoopRoot = "",
    [string]$Stage6ReviewLoopStatusJson = "",
    [string]$Stage6ReviewLoopStatusRoot = "",
    [string]$ReleaseFieldQueryJson = "",
    [string]$ReleaseFieldQueryRoot = "",
    [string]$ReleaseEvidenceAdapterPlanJson = "",
    [string]$ReleaseEvidenceAdapterPlanRoot = "",
    [string]$GdcicBrowserReadbackJson = "",
    [string]$GdcicBrowserReadbackRoot = "",
    [string]$OriginalBacktraceContinuationJson = "",
    [string]$OriginalBacktraceContinuationRoot = "",
    [string]$Stage16P13bContinuationJson = "",
    [string]$Stage16P13bContinuationRoot = "",
    [string]$Stage1_6RealPublicPressureReportJson = "",
    [string]$Stage1_6ReadinessJson = "",
    [string]$Stage1_6GapSummaryJson = "",
    [string]$Stage1MarketScanJson = "",
    [string]$Stage1SourceBlueprintJson = "",
    [string]$Stage2CaptureJson = "",
    [string]$Stage3ParseJson = "",
    [string]$Stage123FrontChainOutputRoot = "",
    [string]$Stage5CalibrationSampleJson = "",
    [string]$Stage5CalibrationSampleRoot = "",
    [string]$Stage4BackfillFollowupQueueJson = "",
    [string]$Stage4BackfillFollowupQueueRoot = "",
    [string]$Stage45ReplaySamplesJson = "",
    [string]$Stage45ReplayOutputRoot = "",
    [string]$OutputJson = "",
    [string]$CreatedAt = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.entrypoint_cli",
    "--entrypoint-id", $EntrypointId
)

if ($PayloadJson) {
    $argsList += @("--payload-json", $PayloadJson)
}
if ($Payload) {
    $argsList += @("--payload", $Payload)
}
if ($BatchCloseoutJson) {
    $argsList += @("--batch-closeout-json", $BatchCloseoutJson)
}
if ($BatchCloseoutRoot) {
    $argsList += @("--batch-closeout-root", $BatchCloseoutRoot)
}
if ($RuntimeBlockerNextSubqueueJson) {
    $argsList += @("--runtime-blocker-next-subqueue-json", $RuntimeBlockerNextSubqueueJson)
}
if ($RuntimeBlockerNextSubqueueRoot) {
    $argsList += @("--runtime-blocker-next-subqueue-root", $RuntimeBlockerNextSubqueueRoot)
}
if ($Stage6ReviewLoopJson) {
    $argsList += @("--stage6-review-loop-json", $Stage6ReviewLoopJson)
}
if ($Stage6ReviewLoopRoot) {
    $argsList += @("--stage6-review-loop-root", $Stage6ReviewLoopRoot)
}
if ($Stage6ReviewLoopStatusJson) {
    $argsList += @("--stage6-review-loop-status-json", $Stage6ReviewLoopStatusJson)
}
if ($Stage6ReviewLoopStatusRoot) {
    $argsList += @("--stage6-review-loop-status-root", $Stage6ReviewLoopStatusRoot)
}
if ($ReleaseFieldQueryJson) {
    $argsList += @("--release-field-query-json", $ReleaseFieldQueryJson)
}
if ($ReleaseFieldQueryRoot) {
    $argsList += @("--release-field-query-root", $ReleaseFieldQueryRoot)
}
if ($ReleaseEvidenceAdapterPlanJson) {
    $argsList += @("--release-evidence-adapter-plan-json", $ReleaseEvidenceAdapterPlanJson)
}
if ($ReleaseEvidenceAdapterPlanRoot) {
    $argsList += @("--release-evidence-adapter-plan-root", $ReleaseEvidenceAdapterPlanRoot)
}
if ($GdcicBrowserReadbackJson) {
    $argsList += @("--gdcic-browser-readback-json", $GdcicBrowserReadbackJson)
}
if ($GdcicBrowserReadbackRoot) {
    $argsList += @("--gdcic-browser-readback-root", $GdcicBrowserReadbackRoot)
}
if ($OriginalBacktraceContinuationJson) {
    $argsList += @("--original-backtrace-continuation-json", $OriginalBacktraceContinuationJson)
}
if ($OriginalBacktraceContinuationRoot) {
    $argsList += @("--original-backtrace-continuation-root", $OriginalBacktraceContinuationRoot)
}
if ($Stage16P13bContinuationJson) {
    $argsList += @("--stage16-p13b-continuation-json", $Stage16P13bContinuationJson)
}
if ($Stage16P13bContinuationRoot) {
    $argsList += @("--stage16-p13b-continuation-root", $Stage16P13bContinuationRoot)
}
if ($Stage1_6RealPublicPressureReportJson) {
    $argsList += @("--stage1-6-real-public-pressure-report-json", $Stage1_6RealPublicPressureReportJson)
}
if ($Stage1_6ReadinessJson) {
    $argsList += @("--stage1-6-readiness-json", $Stage1_6ReadinessJson)
}
if ($Stage1_6GapSummaryJson) {
    $argsList += @("--stage1-6-gap-summary-json", $Stage1_6GapSummaryJson)
}
if ($Stage1MarketScanJson) {
    $argsList += @("--stage1-market-scan-json", $Stage1MarketScanJson)
}
if ($Stage1SourceBlueprintJson) {
    $argsList += @("--stage1-source-blueprint-json", $Stage1SourceBlueprintJson)
}
if ($Stage2CaptureJson) {
    $argsList += @("--stage2-capture-json", $Stage2CaptureJson)
}
if ($Stage3ParseJson) {
    $argsList += @("--stage3-parse-json", $Stage3ParseJson)
}
if ($Stage123FrontChainOutputRoot) {
    $argsList += @("--stage123-front-chain-output-root", $Stage123FrontChainOutputRoot)
}
if ($Stage5CalibrationSampleJson) {
    $argsList += @("--stage5-calibration-sample-json", $Stage5CalibrationSampleJson)
}
if ($Stage5CalibrationSampleRoot) {
    $argsList += @("--stage5-calibration-sample-root", $Stage5CalibrationSampleRoot)
}
if ($Stage4BackfillFollowupQueueJson) {
    $argsList += @("--stage4-backfill-followup-queue-json", $Stage4BackfillFollowupQueueJson)
}
if ($Stage4BackfillFollowupQueueRoot) {
    $argsList += @("--stage4-backfill-followup-queue-root", $Stage4BackfillFollowupQueueRoot)
}
if ($Stage45ReplaySamplesJson) {
    $argsList += @("--stage45-replay-samples-json", $Stage45ReplaySamplesJson)
}
if ($Stage45ReplayOutputRoot) {
    $argsList += @("--stage45-replay-output-root", $Stage45ReplayOutputRoot)
}
if ($OutputJson) {
    $argsList += @("--output-json", $OutputJson)
}
if ($CreatedAt) {
    $argsList += @("--created-at", $CreatedAt)
}
if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
