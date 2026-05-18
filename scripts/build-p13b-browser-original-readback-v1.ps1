param(
    [string]$InputRoot = "",
    [string]$InputJson = "",
    [string]$OutputRoot = "",
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveBrowserReadbacks = 0,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-notice-backtrace-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-browser-original-readback-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.p13b_browser_original_readback",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot
)

if ($InputJson) {
    $argsList += @("--input-json", $InputJson)
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
}
if ($MaxLiveBrowserReadbacks -gt 0) {
    $argsList += @("--max-live-browser-readbacks", "$MaxLiveBrowserReadbacks")
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
