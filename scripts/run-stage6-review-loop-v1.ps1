param(
    [string]$DispatchJson = "",
    [string]$DispatchRoot = "",
    [string]$BatchCloseoutJson = "",
    [string]$BatchCloseoutRoot = "",
    [string]$BaselineEvidenceStateJson = "",
    [string]$BaselineEvidenceStateRoot = "",
    [string]$ReleaseFieldQueryJson = "",
    [string]$ReleaseFieldQueryRoot = "",
    [string]$ReleaseEvidenceAdapterPlanJson = "",
    [string]$ReleaseEvidenceAdapterPlanRoot = "",
    [string]$OriginalBacktraceContinuationJson = "",
    [string]$OriginalBacktraceContinuationRoot = "",
    [string]$Stage16P13bContinuationJson = "",
    [string]$Stage16P13bContinuationRoot = "",
    [string]$Stage5CalibrationSampleJson = "",
    [string]$Stage5CalibrationSampleRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [int]$DispatchMaxGroups = -1,
    [int]$ResultMaxCommands = -1,
    [switch]$ExecuteDispatch,
    [switch]$ExecuteResults,
    [switch]$ExecuteNextCycleDispatch,
    [switch]$DisableBootstrapFromBatchCloseout,
    [switch]$DisableAutoDiscoverLatestBatchCloseout,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DispatchRoot) {
    $DispatchRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-loop-runner-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_loop_runner",
    "--dispatch-root", $DispatchRoot,
    "--output-root", $OutputRoot,
    "--cwd", "$repoRoot"
)

if ($DispatchJson) {
    $argsList += @("--dispatch-json", $DispatchJson)
}
if ($BatchCloseoutJson) {
    $argsList += @("--batch-closeout-json", $BatchCloseoutJson)
}
if ($BatchCloseoutRoot) {
    $argsList += @("--batch-closeout-root", $BatchCloseoutRoot)
}
if ($BaselineEvidenceStateJson) {
    $argsList += @("--baseline-evidence-state-json", $BaselineEvidenceStateJson)
}
if ($BaselineEvidenceStateRoot) {
    $argsList += @("--baseline-evidence-state-root", $BaselineEvidenceStateRoot)
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
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($DispatchMaxGroups -ge 0) {
    $argsList += @("--dispatch-max-groups", "$DispatchMaxGroups")
}
if ($ResultMaxCommands -ge 0) {
    $argsList += @("--result-max-commands", "$ResultMaxCommands")
}
if ($DisableBootstrapFromBatchCloseout) {
    $argsList += "--disable-bootstrap-from-batch-closeout"
}
if (-not $DisableAutoDiscoverLatestBatchCloseout) {
    $argsList += "--auto-discover-latest-batch-closeout"
}
if ($ExecuteDispatch) {
    $argsList += "--execute-dispatch"
}
if ($ExecuteResults) {
    $argsList += "--execute-results"
}
if ($ExecuteNextCycleDispatch) {
    $argsList += "--execute-next-cycle-dispatch"
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
