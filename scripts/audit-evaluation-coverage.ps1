param(
    [string]$SeedJson = "",
    [string]$RequirementsJson = "",
    [string]$RealSampleExecutionManifestJson = "",
    [string]$DatabaseUrl = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $SeedJson) {
    $SeedJson = Join-Path $repoRoot "contracts\evaluation\evaluation_corpus_seed.json"
}

if (-not $RequirementsJson) {
    $RequirementsJson = Join-Path $repoRoot "contracts\evaluation\evaluation_coverage_requirements.json"
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
    "-m", "storage.evaluation_coverage_audit",
    "--seed-json", $SeedJson,
    "--requirements-json", $RequirementsJson,
    "--target-backend", "postgresql"
)

if ($DatabaseUrl) {
    $argsList += @("--database-url", $DatabaseUrl)
}

if ($RealSampleExecutionManifestJson) {
    $argsList += @("--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson)
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
        throw "evaluation coverage audit failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
