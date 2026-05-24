param(
    [string]$RunRoot = "",
    [switch]$RunPressure,
    [switch]$RunFieldQuery,
    [switch]$RunStage6Cycle,
    [switch]$EnableLivePublicQuery,
    [int]$CandidateLimit = 30,
    [int]$DetailCaptureLimit = 30,
    [int]$AttachmentCaptureLimit = 60,
    [int]$MaxLiveFieldTasks = 16,
    [switch]$AttemptAllStage16Candidates,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RunRoot) {
    $RunRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-sellable-rate-regression-v1"
}

$pressureRoot = Join-Path $RunRoot "pressure"
$fieldQueryRoot = Join-Path $RunRoot "field-query"
$stage6Root = Join-Path $RunRoot "stage6-cycle"
$scoreboardRoot = Join-Path $RunRoot "scoreboard"

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null

if ($RunPressure) {
    $pressureArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\run-guangzhou-stage1-6-real-public-pressure-v1.ps1"),
        "-OutputRoot", $pressureRoot,
        "-CandidateLimit", "$CandidateLimit",
        "-DetailCaptureLimit", "$DetailCaptureLimit",
        "-AttachmentCaptureLimit", "$AttachmentCaptureLimit"
    )
    if ($AttemptAllStage16Candidates) {
        $pressureArgs += "-AttemptAllStage16Candidates"
    }
    & pwsh @pressureArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & python -m storage.real_public_stage1_6_pressure_report `
        --mode build `
        --output-root $pressureRoot `
        --run-result-json (Join-Path $pressureRoot "run-result.json") `
        --candidate-limit $CandidateLimit
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$releasePlanJson = Join-Path $pressureRoot "stage4-release-adapter-bridge-plan.json"
if ($RunFieldQuery) {
    $fieldArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\run-guangdong-local-field-query-probe-v1.ps1"),
        "-ReleaseEvidenceAdapterPlanJson", $releasePlanJson,
        "-OutputRoot", $fieldQueryRoot,
        "-MaxLiveTasks", "$MaxLiveFieldTasks"
    )
    if ($EnableLivePublicQuery) {
        $fieldArgs += "-EnableLivePublicQuery"
    }
    & pwsh @fieldArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$fieldQueryJson = Join-Path $fieldQueryRoot "guangdong-local-field-query-probe-v1.json"
if ($RunStage6Cycle) {
    & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\run-stage6-review-cycle-v1.ps1") `
        -ReleaseFieldQueryJson $fieldQueryJson `
        -OutputRoot $stage6Root
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$stage6StatusJson = Join-Path $stage6Root "stage6-review-loop-project-status-table.json"
if (-not (Test-Path $stage6StatusJson)) {
    $stage6StatusJson = Join-Path $stage6Root "stage6-review-cycle-runner-v1.json"
}

$scoreboardArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $repoRoot "scripts\build-stage1-6-sellable-scoreboard-v1.ps1"),
    "-PressureRoot", $pressureRoot,
    "-FieldQueryRoot", $fieldQueryRoot,
    "-Stage6StatusRoot", $stage6Root,
    "-OutputRoot", $scoreboardRoot
)
if (Test-Path $fieldQueryJson) {
    $scoreboardArgs += @("-FieldQueryJson", $fieldQueryJson)
}
if (Test-Path $stage6StatusJson) {
    $scoreboardArgs += @("-Stage6StatusJson", $stage6StatusJson)
}
if ($EmitJson) {
    $scoreboardArgs += "-EmitJson"
}

& pwsh @scoreboardArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
