param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "PROJ-CN-GD-JG2026-10815,PROJ-CN-GD-JG2026-11021",
    [string]$DownloadProbeManifestJson = "",
    [string]$AnalysisPlanJson = "",
    [string]$ParseProbeManifestJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-probe-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-strategy-v1"
}

$outputJson = Join-Path $OutputRoot "evidence-verification-strategy.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.evidence_verification_strategy",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--project-ids", $ProjectIds,
    "--output-json", $outputJson
)

if ($DownloadProbeManifestJson) {
    $argsList += @("--download-probe-manifest-json", $DownloadProbeManifestJson)
}
if ($AnalysisPlanJson) {
    $argsList += @("--analysis-plan-json", $AnalysisPlanJson)
}
if ($ParseProbeManifestJson) {
    $argsList += @("--parse-probe-manifest-json", $ParseProbeManifestJson)
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
