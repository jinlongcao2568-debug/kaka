param(
    [string]$BatchCloseoutJson = "",
    [string]$BatchCloseoutRoot = "",
    [string]$P13BOperationalCloseoutJson = "",
    [string]$P13BOperationalCloseoutRoot = "",
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
if (-not $P13BOperationalCloseoutRoot) {
    $P13BOperationalCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-operational-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\release-evidence-adapter-plan-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.release_evidence_adapter_plan",
    "--batch-closeout-root", $BatchCloseoutRoot,
    "--p13b-operational-closeout-root", $P13BOperationalCloseoutRoot,
    "--output-root", $OutputRoot
)

if ($BatchCloseoutJson) {
    $argsList += @("--batch-closeout-json", $BatchCloseoutJson)
}
if ($P13BOperationalCloseoutJson) {
    $argsList += @("--p13b-operational-closeout-json", $P13BOperationalCloseoutJson)
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
