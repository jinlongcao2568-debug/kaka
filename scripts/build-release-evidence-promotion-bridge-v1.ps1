param(
    [string]$DiagnosticRoot = "",
    [string]$DiagnosticJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DiagnosticRoot) {
    $DiagnosticRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-latest-scoreboard-diagnostic-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\release-evidence-promotion-bridge-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.release_evidence_promotion_bridge",
    "--diagnostic-root", $DiagnosticRoot,
    "--output-root", $OutputRoot
)
if ($DiagnosticJson) {
    $argsList += @("--diagnostic-json", $DiagnosticJson)
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
