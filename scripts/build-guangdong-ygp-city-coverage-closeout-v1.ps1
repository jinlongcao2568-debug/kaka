param(
    [string]$CityDiscoveryRoot = "",
    [string]$DownloadRoot = "",
    [string]$MiniCloseoutRoot = "",
    [string]$OversizePolicyRoot = "",
    [string]$P13BYgpExpansionRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $CityDiscoveryRoot) {
    $CityDiscoveryRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-morecity-smoke-v1-city-discovery"
}
if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-morecity-smoke-v1-07-download"
}
if (-not $MiniCloseoutRoot) {
    $MiniCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-evidence-mini-closeout-v2"
}
if (-not $OversizePolicyRoot) {
    $OversizePolicyRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-oversize-policy-v1"
}
if (-not $P13BYgpExpansionRoot) {
    $P13BYgpExpansionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-ygp-original-readback-expansion-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangdong-ygp-city-coverage-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_ygp_city_coverage_closeout",
    "--city-discovery-root", $CityDiscoveryRoot,
    "--download-root", $DownloadRoot,
    "--mini-closeout-root", $MiniCloseoutRoot,
    "--oversize-policy-root", $OversizePolicyRoot,
    "--p13b-ygp-expansion-root", $P13BYgpExpansionRoot,
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
