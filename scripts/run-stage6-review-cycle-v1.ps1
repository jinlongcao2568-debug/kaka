param(
    [string]$BatchCloseoutJson = "",
    [string]$BatchCloseoutRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [string]$BaselineEvidenceStateJson = "",
    [int]$DispatchMaxGroups = -1,
    [switch]$ExecuteDispatch,
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
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($BaselineEvidenceStateJson) {
    $argsList += @("--baseline-evidence-state-json", $BaselineEvidenceStateJson)
}
if ($DispatchMaxGroups -ge 0) {
    $argsList += @("--dispatch-max-groups", "$DispatchMaxGroups")
}
if ($ExecuteDispatch) {
    $argsList += "--execute-dispatch"
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
