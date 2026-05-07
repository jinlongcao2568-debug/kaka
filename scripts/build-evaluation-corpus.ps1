param(
    [string]$InputJson = "",
    [string]$DatabaseUrl = "",
    [string]$ObjectStoragePath = "",
    [int]$Limit = -1,
    [switch]$Execute,
    [switch]$FetchPublicUrls,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputJson) {
    $InputJson = Join-Path $repoRoot "contracts\evaluation\evaluation_corpus_seed.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $env:LOCALAPPDATA "kaka\object-storage"
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:KAKA_STORAGE_DATABASE_URL
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = [Environment]::GetEnvironmentVariable("KAKA_STORAGE_DATABASE_URL", "User")
}

if ($Execute -and -not $DatabaseUrl) {
    throw "KAKA_STORAGE_DATABASE_URL is required when -Execute is used. Set it or pass -DatabaseUrl."
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.evaluation_corpus",
    "--input-json", $InputJson,
    "--target-backend", "postgresql",
    "--object-storage-path", $ObjectStoragePath
)

if ($DatabaseUrl) {
    $argsList += @("--database-url", $DatabaseUrl)
}

if ($Limit -ge 0) {
    $argsList += @("--limit", "$Limit")
}

if ($Execute) {
    $argsList += "--execute"
}

if ($FetchPublicUrls) {
    $argsList += "--fetch-public-urls"
}

if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    & python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "evaluation corpus build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
