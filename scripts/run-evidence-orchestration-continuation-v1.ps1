param(
    [string]$Stage16StorageJson = "",
    [string]$CompanyFirstStage4InputsJson = "",
    [string]$P13BCompanyHistoryJson = "",
    [string]$P13BCompanyHistoryRoot = "",
    [string]$OriginalNoticeBacktraceJson = "",
    [string]$OriginalNoticeBacktraceRoot = "",
    [string]$YgpReadbackRoot = "",
    [string]$YgpReadbackJson = "",
    [string]$BrowserReadbackRoot = "",
    [string]$BrowserReadbackJson = "",
    [string]$DesignSurveyAdapterPlanJson = "",
    [string]$DesignSurveyAdapterPlanRoot = "",
    [string]$DesignSurveyStage4ExecutionJson = "",
    [string]$DesignSurveyStage4ExecutionRoot = "",
    [string]$DesignSurveyFlow08ReadbackJson = "",
    [string]$DesignSurveyFlow08ReadbackRoot = "",
    [string]$DesignSurveyFlow08AttachmentParseJson = "",
    [string]$DesignSurveyFlow08AttachmentParseRoot = "",
    [string]$DesignSurveyPublicRegistryFallbackJson = "",
    [string]$DesignSurveyPublicRegistryFallbackRoot = "",
    [string]$DesignSurveyPublicRegistryReadbackJson = "",
    [string]$DesignSurveyPublicRegistryReadbackRoot = "",
    [string]$PublicRegistrySnapshotHtmlPath = "",
    [string]$PublicRegistrySnapshotHtmlRoot = "",
    [string]$PublicRegistrySnapshotJson = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$EnableLiveOriginalNoticeBacktrace,
    [switch]$ExecuteLivePublicRegistryEntryReadback,
    [int]$MaxLiveOriginalNotices = 0,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $Stage16StorageJson) {
    $storageCandidates = Get-ChildItem -Path (Join-Path $repoRoot "tmp\evaluation-real-samples") -Recurse -Filter "storage.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    if (-not $storageCandidates -or $storageCandidates.Count -eq 0) {
        throw "No stage16 storage.json found under tmp\evaluation-real-samples. Pass -Stage16StorageJson explicitly."
    }
    $Stage16StorageJson = $storageCandidates[0].FullName
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-orchestration-continuation-run-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.evidence_orchestration_continuation_runner",
    "--stage16-storage-json", $Stage16StorageJson,
    "--output-root", $OutputRoot
)

if ($CompanyFirstStage4InputsJson) {
    $argsList += @("--company-first-stage4-inputs-json", $CompanyFirstStage4InputsJson)
}
if ($P13BCompanyHistoryJson) {
    $argsList += @("--p13b-company-history-json", $P13BCompanyHistoryJson)
}
if ($P13BCompanyHistoryRoot) {
    $argsList += @("--p13b-company-history-root", $P13BCompanyHistoryRoot)
}
if ($OriginalNoticeBacktraceJson) {
    $argsList += @("--original-notice-backtrace-json", $OriginalNoticeBacktraceJson)
}
if ($OriginalNoticeBacktraceRoot) {
    $argsList += @("--original-notice-backtrace-root", $OriginalNoticeBacktraceRoot)
}
if ($YgpReadbackRoot) {
    $argsList += @("--ygp-readback-root", $YgpReadbackRoot)
}
if ($YgpReadbackJson) {
    $argsList += @("--ygp-readback-json", $YgpReadbackJson)
}
if ($BrowserReadbackRoot) {
    $argsList += @("--browser-readback-root", $BrowserReadbackRoot)
}
if ($BrowserReadbackJson) {
    $argsList += @("--browser-readback-json", $BrowserReadbackJson)
}
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
if ($DesignSurveyFlow08ReadbackJson) {
    $argsList += @("--design-survey-flow08-readback-json", $DesignSurveyFlow08ReadbackJson)
}
if ($DesignSurveyFlow08ReadbackRoot) {
    $argsList += @("--design-survey-flow08-readback-root", $DesignSurveyFlow08ReadbackRoot)
}
if ($DesignSurveyFlow08AttachmentParseJson) {
    $argsList += @("--design-survey-flow08-attachment-parse-json", $DesignSurveyFlow08AttachmentParseJson)
}
if ($DesignSurveyFlow08AttachmentParseRoot) {
    $argsList += @("--design-survey-flow08-attachment-parse-root", $DesignSurveyFlow08AttachmentParseRoot)
}
if ($DesignSurveyPublicRegistryFallbackJson) {
    $argsList += @("--design-survey-public-registry-fallback-json", $DesignSurveyPublicRegistryFallbackJson)
}
if ($DesignSurveyPublicRegistryFallbackRoot) {
    $argsList += @("--design-survey-public-registry-fallback-root", $DesignSurveyPublicRegistryFallbackRoot)
}
if ($DesignSurveyPublicRegistryReadbackJson) {
    $argsList += @("--design-survey-public-registry-readback-json", $DesignSurveyPublicRegistryReadbackJson)
}
if ($DesignSurveyPublicRegistryReadbackRoot) {
    $argsList += @("--design-survey-public-registry-readback-root", $DesignSurveyPublicRegistryReadbackRoot)
}
if ($PublicRegistrySnapshotHtmlPath) {
    $argsList += @("--public-registry-snapshot-html-path", $PublicRegistrySnapshotHtmlPath)
}
if ($PublicRegistrySnapshotHtmlRoot) {
    $argsList += @("--public-registry-snapshot-html-root", $PublicRegistrySnapshotHtmlRoot)
}
if ($PublicRegistrySnapshotJson) {
    $argsList += @("--public-registry-snapshot-json", $PublicRegistrySnapshotJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($EnableLiveOriginalNoticeBacktrace) {
    $argsList += "--enable-live-original-notice-backtrace"
}
if ($ExecuteLivePublicRegistryEntryReadback) {
    $argsList += "--execute-live-public-registry-entry-readback"
}
if ($MaxLiveOriginalNotices -gt 0) {
    $argsList += @("--max-live-original-notices", "$MaxLiveOriginalNotices")
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
