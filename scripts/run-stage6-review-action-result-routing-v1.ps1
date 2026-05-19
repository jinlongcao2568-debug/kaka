param(
    [string]$ResultRoutingJson = "",
    [string]$ResultRoutingRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [int]$MaxCommands = -1,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ResultRoutingRoot) {
    $ResultRoutingRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-result-routing-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-result-runner-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_action_result_runner",
    "--result-routing-root", $ResultRoutingRoot,
    "--output-root", $OutputRoot,
    "--cwd", "$repoRoot"
)

if ($ResultRoutingJson) {
    $argsList += @("--result-routing-json", $ResultRoutingJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($MaxCommands -ge 0) {
    $argsList += @("--max-commands", "$MaxCommands")
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
