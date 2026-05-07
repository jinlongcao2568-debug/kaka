param(
    [string]$TargetsJson = "",
    [string]$SeedJson = "",
    [string]$DatabaseUrl = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $TargetsJson) {
    $TargetsJson = Join-Path $repoRoot "contracts\evaluation\evaluation_real_project_sample_targets.json"
}

if (-not $SeedJson) {
    $SeedJson = Join-Path $repoRoot "contracts\evaluation\evaluation_corpus_seed.json"
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
    "-m", "storage.evaluation_real_sample_plan",
    "--targets-json", $TargetsJson,
    "--seed-json", $SeedJson,
    "--target-backend", "postgresql"
)

if ($DatabaseUrl) {
    $argsList += @("--database-url", $DatabaseUrl)
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
        throw "evaluation real sample plan failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
