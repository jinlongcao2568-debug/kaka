param(
    [string]$InputRoot = "",
    [string]$InputJson = "",
    [string]$OutputRoot = "",
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveOriginalNotices = 0,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-notice-backtrace-v1-smoke"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-ygp-original-readback-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.p13b_ygp_original_readback",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot
)

if ($InputJson) {
    $argsList += @("--input-json", $InputJson)
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
}
if ($MaxLiveOriginalNotices -gt 0) {
    $argsList += @("--max-live-original-notices", "$MaxLiveOriginalNotices")
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
