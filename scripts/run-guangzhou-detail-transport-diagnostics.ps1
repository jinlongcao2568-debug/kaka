param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [string]$FlowNos = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-v2-new5"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-detail-transport-v2"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_detail_transport_diagnostics",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot
)

if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($FlowNos) {
    $argsList += @("--flow-nos", $FlowNos)
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
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
