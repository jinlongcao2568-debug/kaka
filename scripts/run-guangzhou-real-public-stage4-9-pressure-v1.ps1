param(
    [string]$OutputRoot = "",
    [string]$Query = "中标候选人公示",
    [string[]]$ProjectTypes = @("construction", "municipal", "water_conservancy", "highway"),
    [string[]]$SourceProfileIds = @("GUANGZHOU-YWTB-CONSTRUCTION-LIST"),
    [int]$CandidateLimit = 10,
    [int]$DetailCaptureLimit = 10,
    [int]$AttachmentCaptureLimit = 20,
    [double]$Stage2DetailCaptureTimeBudgetSeconds = 600,
    [double]$Stage16TimeBudgetSeconds = 600,
    [int]$DiscoveryProfileLimitPerRegion = 1,
    [switch]$AttemptAllStage16Candidates,
    [switch]$EnableAttachmentChallengeResolver,
    [int]$ChallengeTimeoutMs = 90000,
    [switch]$ChallengeBrowserHeaded,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-real-public-stage4-9-pressure-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$challengeEnvNames = @(
    "KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER",
    "KAKA_CHALLENGE_TIMEOUT_MS",
    "KAKA_CHALLENGE_BROWSER_HEADLESS"
)
$previousChallengeEnv = @{}
foreach ($name in $challengeEnvNames) {
    $previousChallengeEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

if ($EnableAttachmentChallengeResolver) {
    $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER = "1"
    $env:KAKA_CHALLENGE_TIMEOUT_MS = "$ChallengeTimeoutMs"
    $env:KAKA_CHALLENGE_BROWSER_HEADLESS = if ($ChallengeBrowserHeaded) { "0" } else { "1" }
}

$argsList = @(
    "-m", "storage.real_public_stage4_9_pressure_report",
    "--mode", "run",
    "--output-root", $OutputRoot,
    "--query", $Query,
    "--candidate-limit", "$CandidateLimit",
    "--detail-capture-limit", "$DetailCaptureLimit",
    "--attachment-capture-limit", "$AttachmentCaptureLimit",
    "--stage2-detail-capture-time-budget-seconds", "$Stage2DetailCaptureTimeBudgetSeconds",
    "--stage1-6-time-budget-seconds", "$Stage16TimeBudgetSeconds",
    "--discovery-profile-limit-per-region", "$DiscoveryProfileLimitPerRegion"
)

foreach ($projectType in $ProjectTypes) {
    $argsList += @("--project-type", $projectType)
}
foreach ($profileId in $SourceProfileIds) {
    $argsList += @("--source-profile-id", $profileId)
}
if ($EmitJson) {
    $argsList += "--json"
}
if ($AttemptAllStage16Candidates) {
    $argsList += "--attempt-all-stage1-6-candidates"
}

Push-Location $repoRoot
try {
    python @argsList
    $pythonExitCode = $LASTEXITCODE
    if ($pythonExitCode -ne 0) {
        exit $pythonExitCode
    }
} finally {
    foreach ($name in $challengeEnvNames) {
        $previous = $previousChallengeEnv[$name]
        if ($null -eq $previous) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$name" -Value $previous
        }
    }
    Pop-Location
}
