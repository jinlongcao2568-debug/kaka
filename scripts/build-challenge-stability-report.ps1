param(
    [string]$RealSampleExecutionManifestJson = "",
    [string]$OutputJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RealSampleExecutionManifestJson) {
    $RealSampleExecutionManifestJson = Join-Path $repoRoot "tmp\evaluation-real-samples\challenge-full-real-sample-execution.json"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "tmp\evaluation-real-samples\challenge-stability-report.json"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.challenge_stability_report",
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
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
