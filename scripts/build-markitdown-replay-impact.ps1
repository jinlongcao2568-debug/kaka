param(
    [string]$RealSampleExecutionManifestJson = "",
    [string]$RuleCalibrationManifestJson = "",
    [string]$TailoredReviewAdjudicationJson = "",
    [string]$TailoredSignalSeedJson = "",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [string]$DatabaseUrl = "",
    [string]$TargetBackend = "json-file",
    [string]$OutputJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RealSampleExecutionManifestJson) {
    $RealSampleExecutionManifestJson = Join-Path $repoRoot "tmp\evaluation-real-samples\real-sample-execution.json"
}

if (-not $RuleCalibrationManifestJson) {
    $RuleCalibrationManifestJson = Join-Path $repoRoot "tmp\evaluation-real-samples\file-rule-calibration.json"
}

if (-not $TailoredReviewAdjudicationJson) {
    $TailoredReviewAdjudicationJson = Join-Path $repoRoot "tmp\evaluation-real-samples\tailored-review-adjudication.json"
}

if (-not $TailoredSignalSeedJson) {
    $TailoredSignalSeedJson = Join-Path $repoRoot "contracts\evaluation\tailored_bid_signal_seed.json"
}

if (-not $StoragePath) {
    $StoragePath = Join-Path $repoRoot "tmp\evaluation-real-samples\storage.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $repoRoot "tmp\evaluation-real-samples\objects"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "tmp\evaluation-real-samples\markitdown-replay-impact.json"
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:KAKA_STORAGE_DATABASE_URL
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = [Environment]::GetEnvironmentVariable("KAKA_STORAGE_DATABASE_URL", "User")
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.markitdown_replay_impact",
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
    "--rule-calibration-manifest-json", $RuleCalibrationManifestJson,
    "--tailored-signal-seed-json", $TailoredSignalSeedJson,
    "--target-backend", $TargetBackend,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--output-json", $OutputJson
)

if (Test-Path $TailoredReviewAdjudicationJson) {
    $argsList += @("--tailored-review-adjudication-json", $TailoredReviewAdjudicationJson)
}

if ($DatabaseUrl) {
    $argsList += @("--database-url", $DatabaseUrl)
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
