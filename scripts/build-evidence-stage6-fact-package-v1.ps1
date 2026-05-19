param(
    [string]$BatchCloseoutJson = "",
    [string]$BatchCloseoutRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $BatchCloseoutRoot) {
    $BatchCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-batch-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-stage6-fact-package-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.evidence_stage6_fact_package",
    "--batch-closeout-root", $BatchCloseoutRoot,
    "--output-root", $OutputRoot
)

if ($BatchCloseoutJson) {
    $argsList += @("--batch-closeout-json", $BatchCloseoutJson)
}
if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
