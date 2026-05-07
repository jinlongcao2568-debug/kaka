param(
    [string]$DatabaseUrl = "",
    [string]$RunId = "",
    [string]$InputJson = "",
    [string]$RunArtifactsRoot = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:KAKA_STORAGE_DATABASE_URL
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = [Environment]::GetEnvironmentVariable("KAKA_STORAGE_DATABASE_URL", "User")
}

if ($Execute -and -not $DatabaseUrl) {
    throw "KAKA_STORAGE_DATABASE_URL is required for -Execute. Set it or pass -DatabaseUrl."
}

if (-not $RunArtifactsRoot) {
    $RunArtifactsRoot = Join-Path $env:LOCALAPPDATA "kaka\run-artifacts\real-capture"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.download_archive_manifest",
    "--target-backend", "postgresql",
    "--run-artifacts-root", $RunArtifactsRoot
)

if ($DatabaseUrl) {
    $argsList += @("--database-url", $DatabaseUrl)
}

if ($RunId) {
    $argsList += @("--run-id", $RunId)
}

if ($InputJson) {
    $argsList += @("--input-json", $InputJson)
}

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
        throw "download archive manifest failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
