param(
    [string]$RealSampleExecutionManifestJson = "",
    [string]$TailoredSignalSeedJson = "",
    [string]$DatabaseUrl = "",
    [string]$TargetBackend = "json-file",
    [string]$OutputJson = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RealSampleExecutionManifestJson) {
    $RealSampleExecutionManifestJson = Join-Path $repoRoot "tmp\evaluation-real-samples\real-sample-execution.json"
}

if (-not $TailoredSignalSeedJson) {
    $TailoredSignalSeedJson = Join-Path $repoRoot "contracts\evaluation\tailored_bid_signal_seed.json"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "tmp\evaluation-real-samples\file-rule-calibration.json"
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:KAKA_STORAGE_DATABASE_URL
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = [Environment]::GetEnvironmentVariable("KAKA_STORAGE_DATABASE_URL", "User")
}

if ($Execute -and $TargetBackend -eq "postgresql" -and -not $DatabaseUrl) {
    throw "KAKA_STORAGE_DATABASE_URL is required when -Execute uses postgresql."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.evaluation_rule_calibration",
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
    "--tailored-signal-seed-json", $TailoredSignalSeedJson,
    "--target-backend", $TargetBackend,
    "--output-json", $OutputJson
)

if ($DatabaseUrl) {
    $argsList += @("--database-url", $DatabaseUrl)
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
} finally {
    Pop-Location
}
