param(
    [string]$OutputRoot = "",
    [int]$PerTargetCandidateLimit = 3,
    [string]$TargetBackend = "json-file",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [ValidateSet("FlowUrlOnly", "AttachmentList", "Download", "Parse", "Full")]
    [string]$PipelineStage = "Full",
    [switch]$Resume,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-post-candidate-v1"
}

if (-not $StoragePath) {
    $StoragePath = Join-Path $OutputRoot "storage.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $OutputRoot "objects"
}

$runManifestJson = Join-Path $OutputRoot "run-manifest.json"
$stabilityJson = Join-Path $OutputRoot "challenge-stability-report.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StoragePath) | Out-Null
New-Item -ItemType Directory -Force -Path $ObjectStoragePath | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$previousAttachmentChallengeResolver = $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER
$previousChallengeTimeoutMs = $env:KAKA_CHALLENGE_TIMEOUT_MS
if ($EnableAttachmentChallengeResolver) {
    $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER = "1"
    if (-not $env:KAKA_CHALLENGE_TIMEOUT_MS) {
        $env:KAKA_CHALLENGE_TIMEOUT_MS = "30000"
    }
}

$argsList = @(
    "-m", "storage.guangzhou_post_candidate_backtrace",
    "--output-root", $OutputRoot,
    "--target-backend", $TargetBackend,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--per-target-candidate-limit", "$PerTargetCandidateLimit",
    "--pipeline-stage", $PipelineStage,
    "--output-json", $runManifestJson
)

if ($Execute) {
    $argsList += "--execute"
}

if ($Resume) {
    $argsList += "--resume"
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

& pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptDir "build-challenge-stability-report.ps1") `
    -RealSampleExecutionManifestJson $runManifestJson `
    -OutputJson $stabilityJson
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
