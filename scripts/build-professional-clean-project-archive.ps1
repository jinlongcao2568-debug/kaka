param(
    [string]$RealSampleExecutionManifestJson = "",
    [string]$OutputRoot = "",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [string]$OutputJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\professional-clean-v1"
}

if (-not $RealSampleExecutionManifestJson) {
    $RealSampleExecutionManifestJson = Join-Path $OutputRoot "run-manifest.json"
}

if (-not $StoragePath) {
    $StoragePath = Join-Path $OutputRoot "storage.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $OutputRoot "objects"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $OutputRoot "project-file-audit.json"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StoragePath) | Out-Null
New-Item -ItemType Directory -Force -Path $ObjectStoragePath | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.professional_clean_project_archive",
    "--real-sample-execution-manifest-json", $RealSampleExecutionManifestJson,
    "--output-root", $OutputRoot,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--output-json", $OutputJson
)

if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    $pythonExitCode = $LASTEXITCODE
    if ($pythonExitCode -ne 0) {
        exit $pythonExitCode
    }
} finally {
    Pop-Location
}
