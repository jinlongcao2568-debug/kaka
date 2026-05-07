param(
    [string]$DatabaseUrl = "",
    [string]$ObjectStoragePath = "",
    [int]$Limit = -1,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $env:LOCALAPPDATA "kaka\object-storage"
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
    "-m", "storage.legacy_attachment_parse",
    "--database-url", $DatabaseUrl,
    "--target-backend", "postgresql",
    "--object-storage-path", $ObjectStoragePath
)

if ($Limit -ge 0) {
    $argsList += @("--limit", [string]$Limit)
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
        throw "legacy attachment parse failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
