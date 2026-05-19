param(
    [string]$ContinuationRoot = "",
    [string]$ContinuationJson = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$EnableLivePublicQuery,
    [switch]$DownloadTargetAttachments,
    [int]$MaxLiveReadbacks = 0,
    [int]$MaxAttachmentsPerTask = 3,
    [switch]$EnableOcr,
    [int]$MaxPages = 20,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $ContinuationRoot) {
    $ContinuationRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-original-backtrace-continuation-controller-v2"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-targeted-person-readback-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.p13b_targeted_person_readback",
    "--continuation-root", $ContinuationRoot,
    "--output-root", $OutputRoot
)

if ($ContinuationJson) {
    $argsList += @("--continuation-json", $ContinuationJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
}
if ($DownloadTargetAttachments) {
    $argsList += "--download-target-attachments"
}
if ($MaxLiveReadbacks -gt 0) {
    $argsList += @("--max-live-readbacks", "$MaxLiveReadbacks")
}
if ($MaxAttachmentsPerTask -ge 0) {
    $argsList += @("--max-attachments-per-task", "$MaxAttachmentsPerTask")
}
if ($EnableOcr) {
    $argsList += "--enable-ocr"
}
if ($MaxPages -gt 0) {
    $argsList += @("--max-pages", "$MaxPages")
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
