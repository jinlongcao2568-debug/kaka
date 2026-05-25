param(
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
    [string]$Stage5CalibrationSampleJson = "",
    [string]$Stage5CalibrationSampleRoot = "",
    [string]$DesignSurveyPublicRegistryReadbackJson = "",
    [string]$DesignSurveyPublicRegistryReadbackRoot = "",
    [string]$Stage1To6ScoreboardJson = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [string]$BaselineEvidenceStateJson = "",
    [int]$DispatchMaxGroups = -1,
    [int]$RuntimeBlockerDispatchMaxTasks = -1,
    [switch]$ExecuteDispatch,
    [switch]$ExecuteRuntimeBlockerDispatch,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $BatchCloseoutRoot) {
    $BatchCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-batch-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-cycle-runner-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_cycle_runner",
    "--batch-closeout-root", $BatchCloseoutRoot,
    "--output-root", $OutputRoot,
    "--cwd", "$repoRoot"
)

if ($BatchCloseoutJson) {
    $argsList += @("--batch-closeout-json", $BatchCloseoutJson)
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
if ($Stage5CalibrationSampleJson) {
    $argsList += @("--stage5-calibration-sample-json", $Stage5CalibrationSampleJson)
}
if ($Stage5CalibrationSampleRoot) {
    $argsList += @("--stage5-calibration-sample-root", $Stage5CalibrationSampleRoot)
}
if ($DesignSurveyPublicRegistryReadbackJson) {
    $argsList += @("--design-survey-public-registry-readback-json", $DesignSurveyPublicRegistryReadbackJson)
}
if ($DesignSurveyPublicRegistryReadbackRoot) {
    $argsList += @("--design-survey-public-registry-readback-root", $DesignSurveyPublicRegistryReadbackRoot)
}
if ($Stage1To6ScoreboardJson) {
    $argsList += @("--stage1-6-scoreboard-json", $Stage1To6ScoreboardJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($BaselineEvidenceStateJson) {
    $argsList += @("--baseline-evidence-state-json", $BaselineEvidenceStateJson)
}
if ($DispatchMaxGroups -ge 0) {
    $argsList += @("--dispatch-max-groups", "$DispatchMaxGroups")
}
if ($RuntimeBlockerDispatchMaxTasks -ge 0) {
    $argsList += @("--runtime-blocker-dispatch-max-tasks", "$RuntimeBlockerDispatchMaxTasks")
}
if ($ExecuteDispatch) {
    $argsList += "--execute-dispatch"
}
if ($ExecuteRuntimeBlockerDispatch) {
    $argsList += "--execute-runtime-blocker-dispatch"
}
if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    $pythonExitCode = $LASTEXITCODE
    if ($pythonExitCode -ne 0) {
        exit $pythonExitCode
    }
} finally {
    Pop-Location
}
