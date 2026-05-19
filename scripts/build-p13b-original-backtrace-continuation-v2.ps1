param(
    [string]$OriginalNoticeBacktraceJson = "",
    [string]$OriginalNoticeBacktraceRoot = "",
    [string]$TargetedPersonReadbackJson = "",
    [string]$TargetedPersonReadbackRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-backtrace-continuation-controller-v2"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.p13b_original_backtrace_continuation_controller",
    "--output-root", $OutputRoot
)

if ($OriginalNoticeBacktraceJson) {
    $argsList += @("--original-notice-backtrace-json", $OriginalNoticeBacktraceJson)
}
if ($OriginalNoticeBacktraceRoot) {
    $argsList += @("--original-notice-backtrace-root", $OriginalNoticeBacktraceRoot)
}
if ($TargetedPersonReadbackJson) {
    $argsList += @("--targeted-person-readback-json", $TargetedPersonReadbackJson)
}
if ($TargetedPersonReadbackRoot) {
    $argsList += @("--targeted-person-readback-root", $TargetedPersonReadbackRoot)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
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
