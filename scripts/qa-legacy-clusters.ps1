param(
    [string]$DatabaseUrl = "",
    [string]$RunArtifactsRoot = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RunArtifactsRoot) {
    $RunArtifactsRoot = Join-Path $env:LOCALAPPDATA "kaka\run-artifacts\repo-cleanup"
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:KAKA_STORAGE_DATABASE_URL
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = [Environment]::GetEnvironmentVariable("KAKA_STORAGE_DATABASE_URL", "User")
}

if (-not $DatabaseUrl) {
    throw "KAKA_STORAGE_DATABASE_URL is required. Set it or pass -DatabaseUrl."
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.legacy_cluster_qa",
    "--database-url", $DatabaseUrl,
    "--target-backend", "postgresql",
    "--run-artifacts-root", $RunArtifactsRoot
)

if ($Execute) {
    $argsList += "--execute"
}

if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    & python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "legacy cluster qa failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
