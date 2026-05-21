param(
    [string]$Registry = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $Registry) {
    $Registry = Join-Path $repoRoot "control\automation_entrypoint_registry.yaml"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\automation-entrypoint-audit-v1"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.automation_entrypoint_audit",
    "--repo-root", "$repoRoot",
    "--registry", "$Registry",
    "--output-root", "$OutputRoot",
    "--write-output"
)

if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "automation entrypoint audit failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
