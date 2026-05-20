param(
    [string]$ReleaseEvidenceAdapterPlanRoot = "",
    [string]$ReleaseEvidenceAdapterPlanJson = "",
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
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ReleaseEvidenceAdapterPlanRoot) {
    $ReleaseEvidenceAdapterPlanRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\release-evidence-adapter-plan-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\gdcic-browser-authorized-readback-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.gdcic_browser_authorized_readback",
    "--release-evidence-adapter-plan-root", $ReleaseEvidenceAdapterPlanRoot,
    "--output-root", $OutputRoot
)

if ($ReleaseEvidenceAdapterPlanJson) {
    $argsList += @("--release-evidence-adapter-plan-json", $ReleaseEvidenceAdapterPlanJson)
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
