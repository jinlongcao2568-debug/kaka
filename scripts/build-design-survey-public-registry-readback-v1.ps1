param(
    [string]$PublicRegistryFallbackJson = "",
    [string]$PublicRegistryFallbackRoot = "",
    [string]$ProviderJobsJson = "",
    [string]$SnapshotHtmlPath = "",
    [string]$SnapshotHtmlRoot = "",
    [string]$SnapshotJson = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$ExecuteLiveEntryReadback,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $PublicRegistryFallbackJson -and -not $PublicRegistryFallbackRoot -and -not $ProviderJobsJson) {
    $fallbackCandidates = Get-ChildItem -Path (Join-Path $repoRoot "tmp\evaluation-real-samples") -Recurse -Filter "design-survey-public-registry-fallback-v1.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    if (-not $fallbackCandidates -or $fallbackCandidates.Count -eq 0) {
        throw "No design-survey-public-registry-fallback-v1.json found under tmp\evaluation-real-samples. Pass -PublicRegistryFallbackJson or -ProviderJobsJson explicitly."
    }
    $PublicRegistryFallbackJson = $fallbackCandidates[0].FullName
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-public-registry-readback-v1"
}

$outputJson = Join-Path $OutputRoot "design-survey-public-registry-readback-v1.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.design_survey_public_registry_readback",
    "--output-root", $OutputRoot,
    "--output-json", $outputJson
)

if ($PublicRegistryFallbackJson) {
    $argsList += @("--public-registry-fallback-json", $PublicRegistryFallbackJson)
}
if ($PublicRegistryFallbackRoot) {
    $argsList += @("--public-registry-fallback-root", $PublicRegistryFallbackRoot)
}
if ($ProviderJobsJson) {
    $argsList += @("--provider-jobs-json", $ProviderJobsJson)
}
if ($SnapshotHtmlPath) {
    $argsList += @("--snapshot-html-path", $SnapshotHtmlPath)
}
if ($SnapshotHtmlRoot) {
    $argsList += @("--snapshot-html-root", $SnapshotHtmlRoot)
}
if ($SnapshotJson) {
    $argsList += @("--snapshot-json", $SnapshotJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($ExecuteLiveEntryReadback) {
    $argsList += "--execute-live-entry-readback"
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
