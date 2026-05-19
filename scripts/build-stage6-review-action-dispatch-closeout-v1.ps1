param(
    [string]$DispatchReadbackJson = "",
    [string]$DispatchReadbackRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DispatchReadbackRoot) {
    $DispatchReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-readback-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_action_dispatch_closeout",
    "--dispatch-readback-root", $DispatchReadbackRoot,
    "--output-root", $OutputRoot
)

if ($DispatchReadbackJson) {
    $argsList += @("--dispatch-readback-json", $DispatchReadbackJson)
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
