param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "PROJ-CN-GD-JG2026-10815,PROJ-CN-GD-JG2026-11021",
    [string]$FlowNos = "03,04,07,08",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [int]$MaxBidFilePublicityDownloadsPerProject = 2,
    [switch]$UseAllAnalysisProjects,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-probe-v1"
}

if (-not $StoragePath) {
    $StoragePath = Join-Path $OutputRoot "storage.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $OutputRoot "objects"
}

$downloadProbeJson = Join-Path $OutputRoot "download-probe-manifest.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StoragePath) | Out-Null
New-Item -ItemType Directory -Force -Path $ObjectStoragePath | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$previousAttachmentChallengeResolver = $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER
$previousChallengeTimeoutMs = $env:KAKA_CHALLENGE_TIMEOUT_MS
if ($EnableAttachmentChallengeResolver) {
    $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER = "1"
    if (-not $env:KAKA_CHALLENGE_TIMEOUT_MS) {
        $env:KAKA_CHALLENGE_TIMEOUT_MS = "45000"
    }
}

$argsList = @(
    "-m", "storage.guangzhou_download_probe",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--flow-nos", $FlowNos,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--max-bid-file-publicity-downloads-per-project", "$MaxBidFilePublicityDownloadsPerProject",
    "--output-json", $downloadProbeJson
)

if ($UseAllAnalysisProjects) {
    $argsList += "--use-all-analysis-projects"
} else {
    $argsList += @("--project-ids", $ProjectIds)
}

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
    if ($EnableAttachmentChallengeResolver) {
        if ($null -eq $previousAttachmentChallengeResolver) {
            Remove-Item Env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER -ErrorAction SilentlyContinue
        } else {
            $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER = $previousAttachmentChallengeResolver
        }
        if ($null -eq $previousChallengeTimeoutMs) {
            Remove-Item Env:KAKA_CHALLENGE_TIMEOUT_MS -ErrorAction SilentlyContinue
        } else {
            $env:KAKA_CHALLENGE_TIMEOUT_MS = $previousChallengeTimeoutMs
        }
    }
}
