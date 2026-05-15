param(
    [string]$OutputRoot = "tmp\evaluation-real-samples\guangdong-ygp-city-discovery-v1",
    [string[]]$CityCodes = @("440400", "440500", "440600"),
    [int]$PerCityCandidateLimit = 2,
    [int]$MaxPagesPerCity = 3,
    [switch]$BuildFlowMatrix,
    [switch]$EnableLivePublicQuery,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $repoRoot "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcPath
}

$argsList = @(
    "-m", "storage.guangdong_ygp_city_discovery",
    "--output-root", $OutputRoot,
    "--per-city-candidate-limit", [string]$PerCityCandidateLimit,
    "--max-pages-per-city", [string]$MaxPagesPerCity
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
    if (-not [string]::IsNullOrWhiteSpace($cityCode)) {
        $argsList += @("--city-code", $cityCode)
    }
}

if ($BuildFlowMatrix) {
    $argsList += "--build-flow-matrix"
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
}
if ($EmitJson) {
    $argsList += "--json"
}

python @argsList
