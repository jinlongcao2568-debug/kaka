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
