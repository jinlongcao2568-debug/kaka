param(
    [string]$RealSampleExecutionManifestJson = "",
    [string]$RuleCalibrationManifestJson = "",
    [string]$OutputJson = "",
    [int]$ReviewSampleLimit = 9,
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

if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "tmp\evaluation-real-samples\tailored-review-adjudication.json"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.tailored_review_adjudication",
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
    "--rule-calibration-manifest-json", $RuleCalibrationManifestJson,
    "--review-sample-limit", $ReviewSampleLimit,
    "--output-json", $OutputJson
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
