param(
    [string]$MiniCloseoutRoot = "",
    [string]$CityDiscoveryRoot = "",
    [string]$DownloadRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $MiniCloseoutRoot) {
    $MiniCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-evidence-mini-closeout-v2"
}
if (-not $CityDiscoveryRoot) {
    $CityDiscoveryRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-morecity-smoke-v1-city-discovery"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-morecity-smoke-v1-07-download"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-ygp-original-readback-expansion-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.p13b_ygp_original_readback_expansion",
    "--mini-closeout-root", $MiniCloseoutRoot,
    "--city-discovery-root", $CityDiscoveryRoot,
    "--download-root", $DownloadRoot,
    "--output-root", $OutputRoot
)

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
