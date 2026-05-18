param(
    [string]$DesignSurveyAdapterPlanJson = "",
    [string]$DesignSurveyAdapterPlanRoot = "",
    [string]$DesignSurveyStage4ExecutionJson = "",
    [string]$DesignSurveyStage4ExecutionRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$Execute,
    [switch]$DownloadTargetAttachments,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DesignSurveyAdapterPlanRoot -and -not $DesignSurveyAdapterPlanJson) {
    $DesignSurveyAdapterPlanRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-responsible-adapter-plan-v1"
}

if (-not $DesignSurveyStage4ExecutionRoot -and -not $DesignSurveyStage4ExecutionJson) {
    $DesignSurveyStage4ExecutionRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-stage4-execution-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-flow08-targeted-readback-v1"
}

$outputJson = Join-Path $OutputRoot "design-survey-flow08-targeted-readback-v1.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$previousAttachmentChallengeResolver = $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER
$previousChallengeTimeoutMs = $env:KAKA_CHALLENGE_TIMEOUT_MS
if ($EnableAttachmentChallengeResolver) {
    $env:KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER = "1"
    if (-not $env:KAKA_CHALLENGE_TIMEOUT_MS) {
        $env:KAKA_CHALLENGE_TIMEOUT_MS = "30000"
    }
}

$argsList = @(
    "-m", "storage.design_survey_flow08_targeted_readback",
    "--output-root", $OutputRoot,
    "--output-json", $outputJson
)

if ($DesignSurveyAdapterPlanJson) {
    $argsList += @("--design-survey-adapter-plan-json", $DesignSurveyAdapterPlanJson)
}
if ($DesignSurveyAdapterPlanRoot) {
    $argsList += @("--design-survey-adapter-plan-root", $DesignSurveyAdapterPlanRoot)
}
if ($DesignSurveyStage4ExecutionJson) {
    $argsList += @("--design-survey-stage4-execution-json", $DesignSurveyStage4ExecutionJson)
}
if ($DesignSurveyStage4ExecutionRoot) {
    $argsList += @("--design-survey-stage4-execution-root", $DesignSurveyStage4ExecutionRoot)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($Execute) {
    $argsList += "--execute"
}
if ($DownloadTargetAttachments) {
    $argsList += "--download-target-attachments"
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
