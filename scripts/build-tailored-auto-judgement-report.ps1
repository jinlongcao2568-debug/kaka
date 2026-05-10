param(
    [string]$RealSampleExecutionManifestJson = "",
    [string]$RuleCalibrationManifestJson = "",
    [string]$TailoredReviewAdjudicationJson = "",
    [string]$MarkItDownReplayImpactJson = "",
    [string]$TailoredSignalSeedJson = "",
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

if (-not $MarkItDownReplayImpactJson) {
    $MarkItDownReplayImpactJson = Join-Path $repoRoot "tmp\evaluation-real-samples\markitdown-replay-impact.json"
}

if (-not $TailoredSignalSeedJson) {
    $TailoredSignalSeedJson = Join-Path $repoRoot "contracts\evaluation\tailored_bid_signal_seed.json"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "tmp\evaluation-real-samples\tailored-auto-judgement-report.json"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.tailored_auto_judgement_report",
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
    "--rule-calibration-manifest-json", $RuleCalibrationManifestJson,
    "--tailored-signal-seed-json", $TailoredSignalSeedJson,
    "--output-json", $OutputJson
)

if (Test-Path $TailoredReviewAdjudicationJson) {
    $argsList += @("--tailored-review-adjudication-json", $TailoredReviewAdjudicationJson)
}

if (Test-Path $MarkItDownReplayImpactJson) {
    $argsList += @("--markitdown-replay-impact-json", $MarkItDownReplayImpactJson)
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
