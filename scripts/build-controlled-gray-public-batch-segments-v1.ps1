param(
    [string]$TargetsJson = "",
    [string]$OutputRoot = "",
    [string]$RunRootBase = "",
    [string]$GroupBy = "source_profile",
    [int]$PerTargetCandidateLimit = 12,
    [int]$TargetLimit = 0,
    [switch]$ProfessionalSourceOnly,
    [switch]$Execute,
    [switch]$AutoExecuteSourceRemediation,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $TargetsJson) {
    $TargetsJson = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-gray-public-source-targets-v1\controlled-gray-public-source-targets-v1.json"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-gray-public-batch-segments-v1"
}

if (-not $RunRootBase) {
    $RunRootBase = Join-Path $OutputRoot "runs"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.controlled_gray_public_batch_segments",
    "plan",
    "--targets-json", $TargetsJson,
    "--output-root", $OutputRoot,
    "--run-root-base", $RunRootBase,
    "--group-by", $GroupBy,
    "--per-target-candidate-limit", "$PerTargetCandidateLimit",
    "--target-limit", "$TargetLimit"
)

if ($ProfessionalSourceOnly) {
    $argsList += "--professional-source-only"
}

if ($Execute) {
    $argsList += "--execute"
}

if ($AutoExecuteSourceRemediation) {
    $argsList += "--auto-execute-source-remediation"
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
