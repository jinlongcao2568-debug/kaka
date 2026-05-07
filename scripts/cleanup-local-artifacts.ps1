param(
    [string]$RepoRoot = "",
    [string]$ObjectStoragePath = "",
    [string]$RunArtifactsRoot = "",
    [string]$DatabaseUrl = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $RepoRoot) {
    $RepoRoot = Resolve-Path (Join-Path $scriptDir "..")
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $env:LOCALAPPDATA "kaka\object-storage"
}

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

$env:PYTHONPATH = "$RepoRoot\src;$RepoRoot\tests"

$argsList = @(
    "-m", "storage.local_artifact_cleanup",
    "--repo-root", $RepoRoot,
    "--object-storage-path", $ObjectStoragePath,
    "--run-artifacts-root", $RunArtifactsRoot,
    "--database-url", $DatabaseUrl,
    "--target-backend", "postgresql"
)

if ($Execute) {
    $argsList += "--execute"
}

if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $RepoRoot
try {
    & python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "local artifact cleanup failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
