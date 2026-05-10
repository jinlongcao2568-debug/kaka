param(
    [string]$TargetsJson = "",
    [string]$SeedJson = "",
    [string[]]$TargetIds = @(),
    [int]$TargetLimit = 0,
    [int]$PerTargetCandidateLimit = 1,
    [string]$TargetBackend = "json-file",
    [string]$StoragePath = "",
    [string]$ObjectStoragePath = "",
    [string]$DatabaseUrl = "",
    [string]$OutputJson = "",
    [switch]$UseAllTargets,
    [switch]$ProfessionalSourceOnly,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $TargetsJson) {
    $TargetsJson = Join-Path $repoRoot "contracts\evaluation\evaluation_real_project_sample_targets.json"
}

if (-not $SeedJson) {
    $SeedJson = Join-Path $repoRoot "contracts\evaluation\evaluation_corpus_seed.json"
}

if (-not $StoragePath) {
    $StoragePath = Join-Path $repoRoot "tmp\evaluation-real-samples\storage.json"
}

if (-not $ObjectStoragePath) {
    $ObjectStoragePath = Join-Path $repoRoot "tmp\evaluation-real-samples\objects"
}

if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "tmp\evaluation-real-samples\real-sample-execution.json"
}

if ($UseAllTargets) {
    $TargetIds = @()
} elseif (-not $TargetIds -or $TargetIds.Count -eq 0) {
    $TargetIds = @(
        "REAL-GD-TENDER-001",
        "REAL-GD-CANDIDATE-001",
        "REAL-GD-AWARD-001",
        "REAL-JS-TENDER-001",
        "REAL-JS-CANDIDATE-001",
        "REAL-HB-TENDER-001",
        "REAL-ZJ-CANDIDATE-001",
        "REAL-SD-AWARD-001",
        "REAL-SH-TENDER-001",
        "REAL-GP-FAILED-BID-001",
        "REAL-GP-COMPLAINT-001",
        "REAL-GGZY-FLOW-RETENDER-001",
        "REAL-OFFICIAL-CASE-FAIRNESS-001"
    )
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:KAKA_STORAGE_DATABASE_URL
}

if (-not $DatabaseUrl) {
    $DatabaseUrl = [Environment]::GetEnvironmentVariable("KAKA_STORAGE_DATABASE_URL", "User")
}

if ($Execute -and $TargetBackend -eq "postgresql" -and -not $DatabaseUrl) {
    throw "KAKA_STORAGE_DATABASE_URL is required when -Execute uses postgresql. Use -TargetBackend json-file for local controlled sample runs."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StoragePath) | Out-Null
New-Item -ItemType Directory -Force -Path $ObjectStoragePath | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.evaluation_real_sample_execution",
    "--targets-json", $TargetsJson,
    "--seed-json", $SeedJson,
    "--target-backend", $TargetBackend,
    "--storage-path", $StoragePath,
    "--object-storage-path", $ObjectStoragePath,
    "--per-target-candidate-limit", "$PerTargetCandidateLimit",
    "--output-json", $OutputJson
)

if ($TargetIds -and $TargetIds.Count -gt 0) {
    $argsList += "--target-ids"
    $argsList += $TargetIds
}

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
    }
}
