param(
    [string]$DispatchJson = "",
    [string]$DispatchRoot = "",
    [string]$BaselineEvidenceStateJson = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [int]$MaxGroups = -1,
    [switch]$Execute,
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
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-runner-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_action_dispatch_runner",
    "--dispatch-root", $DispatchRoot,
    "--output-root", $OutputRoot,
    "--cwd", "$repoRoot"
)

if ($DispatchJson) {
    $argsList += @("--dispatch-json", $DispatchJson)
}
if ($BaselineEvidenceStateJson) {
    $argsList += @("--baseline-evidence-state-json", $BaselineEvidenceStateJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($MaxGroups -ge 0) {
    $argsList += @("--max-groups", "$MaxGroups")
}
if ($Execute) {
    $argsList += "--execute"
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
