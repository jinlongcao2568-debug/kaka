param(
    [string]$SourceRemediationJson = "",
    [string]$TargetsJson = "",
    [string]$SeedJson = "",
    [string]$TargetBackend = "json-file",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [string]$DatabaseUrl = "",
    [string]$OutputRoot = "",
    [int]$TargetLimit = 0,
    [int]$PerTargetCandidateLimit = 1,
    [switch]$ProfessionalSourceOnly,
    [switch]$EnableAlternatePublicSource,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $SourceRemediationJson) {
    $SourceRemediationJson = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-live-public-batch-20260703-v1\source-remediation\controlled-live-public-batch-source-remediation-v1.json"
}

if (-not $TargetsJson) {
    $TargetsJson = Join-Path $repoRoot "contracts\evaluation\evaluation_real_project_sample_targets.json"
}

if (-not $SeedJson) {
    $SeedJson = Join-Path $repoRoot "contracts\evaluation\evaluation_corpus_seed.json"
}

if (-not $OutputRoot) {
    $sourceRemediationRoot = Split-Path -Parent $SourceRemediationJson
    $runRoot = Split-Path -Parent $sourceRemediationRoot
    $OutputRoot = Join-Path $runRoot "source-remediation-execution"
}

if (-not $StoragePath) {
    $StoragePath = Join-Path $OutputRoot "storage.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $OutputRoot "objects"
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:KAKA_STORAGE_DATABASE_URL
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = [Environment]::GetEnvironmentVariable("KAKA_STORAGE_DATABASE_URL", "User")
}

if ($Execute -and $TargetBackend -eq "postgresql" -and -not $DatabaseUrl) {
    throw "KAKA_STORAGE_DATABASE_URL is required when -Execute uses postgresql. Use -TargetBackend json-file for local controlled source remediation runs."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StoragePath) | Out-Null
New-Item -ItemType Directory -Force -Path $ObjectStoragePath | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.controlled_live_public_batch_source_remediation_execution",
    "--source-remediation-json", $SourceRemediationJson,
    "--targets-json", $TargetsJson,
    "--seed-json", $SeedJson,
    "--target-backend", $TargetBackend,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--output-root", $OutputRoot,
    "--per-target-candidate-limit", "$PerTargetCandidateLimit"
)

if ($TargetLimit -gt 0) {
    $argsList += @("--target-limit", "$TargetLimit")
}

if ($DatabaseUrl) {
    $argsList += @("--database-url", $DatabaseUrl)
}

if ($Execute) {
    $argsList += "--execute"
}

if ($ProfessionalSourceOnly) {
    $argsList += "--professional-source-only"
}

if ($EnableAlternatePublicSource) {
    $argsList += "--enable-alternate-public-source"
}

if ($EmitJson) {
    $argsList += "--json"
}

$previousAttachmentChallengeResolver = $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER
if ($EnableAttachmentChallengeResolver) {
    $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER = "1"
}

Push-Location $repoRoot
try {
    python @argsList
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
    if ($EnableAttachmentChallengeResolver) {
        if ($null -eq $previousAttachmentChallengeResolver) {
            Remove-Item Env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER -ErrorAction SilentlyContinue
        } else {
            $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER = $previousAttachmentChallengeResolver
        }
    }
}
