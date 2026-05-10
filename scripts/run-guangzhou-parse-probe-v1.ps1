param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "PROJ-CN-GD-JG2026-10815,PROJ-CN-GD-JG2026-11021",
    [string]$FlowNos = "03,04",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-probe-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-parse-probe-v1"
}

if (-not $StoragePath) {
    $StoragePath = Join-Path $InputRoot "storage.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $InputRoot "objects"
}

$parseProbeJson = Join-Path $OutputRoot "parse-probe-manifest.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangzhou_parse_probe",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--project-ids", $ProjectIds,
    "--flow-nos", $FlowNos,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--output-json", $parseProbeJson
)

if ($Execute) {
    $argsList += "--execute"
}

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
