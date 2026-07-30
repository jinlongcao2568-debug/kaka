param(
    [string]$OutputRoot = "",
    [string[]]$TargetIds = @(),
    [int]$TargetLimit = 0,
    [int]$PerTargetCandidateLimit = 5,
    [string]$EvidenceSummaryOutputRoot = "",
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$Execute,
    [switch]$SkipEvidenceSummary,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\professional-clean-v1"
}

$storagePath = Join-Path $OutputRoot "storage.json"
$objectStoragePath = Join-Path $OutputRoot "objects"
$runManifestJson = Join-Path $OutputRoot "run-manifest.json"
$auditJson = Join-Path $OutputRoot "project-file-audit.json"

if (-not $EvidenceSummaryOutputRoot) {
    $EvidenceSummaryOutputRoot = Join-Path $OutputRoot "evidence-summary"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$runArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "run-evaluation-real-sample-execution.ps1"),
    "-ProfessionalSourceOnly",
    "-PerTargetCandidateLimit", "$PerTargetCandidateLimit",
    "-TargetBackend", "json-file",
    "-StoragePath", $storagePath,
    "-ObjectStoragePath", $objectStoragePath,
    "-OutputJson", $runManifestJson
)

if ($TargetIds -and $TargetIds.Count -gt 0) {
    $runArgs += "-TargetIds"
    $runArgs += ($TargetIds -join ",")
} else {
    $runArgs += "-UseAllTargets"
}

if ($TargetLimit -gt 0) {
    $runArgs += @("-TargetLimit", "$TargetLimit")
}

if ($EnableAttachmentChallengeResolver) {
    $runArgs += "-EnableAttachmentChallengeResolver"
}

if ($Execute) {
    $runArgs += "-Execute"
}

if ($EmitJson) {
    $runArgs += "-EmitJson"
}

& pwsh @runArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not $SkipEvidenceSummary) {
    $evidenceSummaryArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $scriptDir "build-controlled-live-public-batch-evidence-summary-v1.ps1"),
        "-RealSampleExecutionJson", $runManifestJson,
        "-StorageJson", $storagePath,
        "-OutputRoot", $EvidenceSummaryOutputRoot
    )

    if ($EmitJson) {
        $evidenceSummaryArgs += "-EmitJson"
    }

    & pwsh @evidenceSummaryArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$archiveArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "build-professional-clean-project-archive.ps1"),
    "-RealSampleExecutionManifestJson", $runManifestJson,
    "-OutputRoot", $OutputRoot,
    "-StoragePath", $storagePath,
    "-ObjectStoragePath", $objectStoragePath,
    "-OutputJson", $auditJson
)

if ($EmitJson) {
    $archiveArgs += "-EmitJson"
}

& pwsh @archiveArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
