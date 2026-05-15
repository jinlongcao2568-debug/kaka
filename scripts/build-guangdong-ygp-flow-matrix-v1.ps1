param(
    [string]$InputRoot = "",
    [string]$InputJson = "",
    [string]$OutputRoot = "",
    [string[]]$SourceUrls = @(),
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveSourceUrls = 0,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-notice-backtrace-v1-smoke"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-ygp-flow-matrix-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_ygp_flow_matrix",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot
)

if ($InputJson) {
    $argsList += @("--input-json", $InputJson)
}
foreach ($sourceUrl in $SourceUrls) {
    if ($sourceUrl) {
        $argsList += @("--source-url", $sourceUrl)
    }
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
}
if ($MaxLiveSourceUrls -gt 0) {
    $argsList += @("--max-live-source-urls", "$MaxLiveSourceUrls")
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
