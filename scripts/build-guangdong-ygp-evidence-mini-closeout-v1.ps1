param(
    [string]$CityDiscoveryRoot = "",
    [string]$DownloadRoot = "",
    [string]$OutputRoot = "",
    [string[]]$CityCodes = @(),
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
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-evidence-mini-closeout-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_ygp_evidence_mini_closeout",
    "--city-discovery-root", $CityDiscoveryRoot,
    "--download-root", $DownloadRoot,
    "--output-root", $OutputRoot
)

$normalizedCityCodes = @()
foreach ($cityCodeValue in $CityCodes) {
    foreach ($cityCode in ([string]$cityCodeValue -split ",")) {
        $trimmed = $cityCode.Trim()
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
            $normalizedCityCodes += $trimmed
        }
    }
}
foreach ($cityCode in $normalizedCityCodes) {
    $argsList += @("--city-code", $cityCode)
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
