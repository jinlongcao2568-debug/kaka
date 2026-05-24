param(
    [string]$ReleaseEvidenceAdapterPlanRoot = "",
    [string]$ReleaseEvidenceAdapterPlanJson = "",
    [string]$FieldQueryJson = "",
    [string]$OutputRoot = "",
    [switch]$EnableLiveBrowserExecution,
    [int]$MaxLiveBrowserTasks = 0,
    [string]$StorageStateJson = "",
    [string]$UserDataDir = "",
    [switch]$Headed,
    [int]$WaitAfterSearchMs = 2500,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

function Get-FirstExistingPath {
    param(
        [string[]]$Candidates,
        [ValidateSet("Leaf", "Container")]
        [string]$PathType
    )
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType $PathType)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Get-FirstEnvValue {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) {
            return $value
        }
    }
    return ""
}

if (-not $ReleaseEvidenceAdapterPlanRoot) {
    $ReleaseEvidenceAdapterPlanRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\release-evidence-adapter-plan-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\gdcic-browser-authorized-readback-v1"
}
if (-not $StorageStateJson) {
    $StorageStateJson = Get-FirstEnvValue @("KAKA_GDCIC_STORAGE_STATE_JSON", "GDCIC_STORAGE_STATE_JSON")
}
if (-not $StorageStateJson) {
    $StorageStateJson = Get-FirstExistingPath `
        -PathType Leaf `
        -Candidates @(
            (Join-Path $repoRoot ".auth\gdcic-storage-state.json"),
            (Join-Path $repoRoot "local\auth\gdcic-storage-state.json"),
            (Join-Path $repoRoot "tmp\auth\gdcic-storage-state.json")
        )
}
if (-not $UserDataDir) {
    $UserDataDir = Get-FirstEnvValue @("KAKA_GDCIC_USER_DATA_DIR", "GDCIC_USER_DATA_DIR")
}
if (-not $UserDataDir) {
    $UserDataDir = Get-FirstExistingPath `
        -PathType Container `
        -Candidates @(
            (Join-Path $repoRoot ".auth\gdcic-user-data"),
            (Join-Path $repoRoot "local\auth\gdcic-user-data"),
            (Join-Path $repoRoot "tmp\auth\gdcic-user-data")
        )
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"
if ($env:KAKA_GDCIC_READBACK_PRESERVE_STORAGE_ENV -ne "1") {
    $env:KAKA_STORAGE_BACKEND = "json-file"
    $env:KAKA_STORAGE_SCOPE = "process"
    $env:KAKA_STORAGE_PATH = Join-Path $OutputRoot "runtime-state.json"
    $env:KAKA_OBJECT_STORAGE_BACKEND = "local-filesystem"
    $env:KAKA_OBJECT_STORAGE_PATH = Join-Path $OutputRoot "objects"
}

$argsList = @(
    "-m", "storage.gdcic_browser_authorized_readback",
    "--release-evidence-adapter-plan-root", $ReleaseEvidenceAdapterPlanRoot,
    "--output-root", $OutputRoot
)

if ($ReleaseEvidenceAdapterPlanJson) {
    $argsList += @("--release-evidence-adapter-plan-json", $ReleaseEvidenceAdapterPlanJson)
}
if ($FieldQueryJson) {
    $argsList += @("--field-query-json", $FieldQueryJson)
}
if ($EnableLiveBrowserExecution) {
    $argsList += "--enable-live-browser-execution"
}
if ($MaxLiveBrowserTasks -gt 0) {
    $argsList += @("--max-live-browser-tasks", "$MaxLiveBrowserTasks")
}
if ($StorageStateJson) {
    $argsList += @("--storage-state-json", $StorageStateJson)
}
if ($UserDataDir) {
    $argsList += @("--user-data-dir", $UserDataDir)
}
if ($Headed) {
    $argsList += "--headed"
}
if ($WaitAfterSearchMs -gt 0) {
    $argsList += @("--wait-after-search-ms", "$WaitAfterSearchMs")
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
