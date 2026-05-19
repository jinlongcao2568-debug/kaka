param(
    [string]$DispatchJson = "",
    [string]$DispatchRoot = "",
    [string]$ReleaseEvidenceAdapterPlanJson = "",
    [string]$ReleaseEvidenceAdapterPlanRoot = "",
    [string]$EvidenceOrchestrationContinuationJson = "",
    [string]$EvidenceOrchestrationContinuationRoot = "",
    [string]$DesignSurveyPublicRegistryReadbackJson = "",
    [string]$DesignSurveyPublicRegistryReadbackRoot = "",
    [string]$DispatchDecisionJson = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DispatchRoot) {
    $DispatchRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-v1"
}
if (-not $ReleaseEvidenceAdapterPlanRoot) {
    $ReleaseEvidenceAdapterPlanRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\release-evidence-adapter-plan-v1"
}
if (-not $EvidenceOrchestrationContinuationRoot) {
    $EvidenceOrchestrationContinuationRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-orchestration-continuation-run-v1"
}
if (-not $DesignSurveyPublicRegistryReadbackRoot) {
    $DesignSurveyPublicRegistryReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-public-registry-readback-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-readback-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_action_dispatch_readback",
    "--dispatch-root", $DispatchRoot,
    "--release-evidence-adapter-plan-root", $ReleaseEvidenceAdapterPlanRoot,
    "--evidence-orchestration-continuation-root", $EvidenceOrchestrationContinuationRoot,
    "--design-survey-public-registry-readback-root", $DesignSurveyPublicRegistryReadbackRoot,
    "--output-root", $OutputRoot
)

if ($DispatchJson) {
    $argsList += @("--dispatch-json", $DispatchJson)
}
if ($ReleaseEvidenceAdapterPlanJson) {
    $argsList += @("--release-evidence-adapter-plan-json", $ReleaseEvidenceAdapterPlanJson)
}
if ($EvidenceOrchestrationContinuationJson) {
    $argsList += @("--evidence-orchestration-continuation-json", $EvidenceOrchestrationContinuationJson)
}
if ($DesignSurveyPublicRegistryReadbackJson) {
    $argsList += @("--design-survey-public-registry-readback-json", $DesignSurveyPublicRegistryReadbackJson)
}
if ($DispatchDecisionJson) {
    $argsList += @("--dispatch-decision-json", $DispatchDecisionJson)
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
