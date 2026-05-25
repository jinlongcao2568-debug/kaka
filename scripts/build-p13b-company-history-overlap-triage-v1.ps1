param(
    [string]$InputRoot = "",
    [string]$YgpExpansionRoot = "",
    [string]$YgpCoverageCloseoutRoot = "",
    [string]$GdcicBrowserReadbackJson = "",
    [string]$GdcicBrowserReadbackRoot = "",
    [string]$Stage4BackfillFollowupQueueJson = "",
    [string]$Stage4BackfillFollowupQueueRoot = "",
    [string]$RuntimeBlockerFallbackSourcePlanJson = "",
    [string]$ReleaseFieldQueryJson = "",
    [string]$ReleaseFieldQueryRoot = "",
    [string]$OutputRoot = "",
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveCompanies = 0,
    [int]$MaxBidRecordsPerCompany = 10,
    [string]$HistoryWindowYears = "1,2,3",
    [int]$HistoryWindowMonths = 36,
    [int]$BidListPageSize = 20,
    [int]$MaxBidListPagesPerCompany = 6,
    [int]$LongTailCutoffYear = 2019,
    [int]$MaxLongTailBidShowsPerCompany = 3,
    [string]$ProjectIds = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-value-closeout-p12-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-company-history-overlap-triage-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

if ($Stage4BackfillFollowupQueueJson -and $RuntimeBlockerFallbackSourcePlanJson) {
    Write-Error "Use either -Stage4BackfillFollowupQueueJson or -RuntimeBlockerFallbackSourcePlanJson, not both."
    exit 1
}

$argsList = @(
    "-m", "storage.p13b_company_history_overlap_triage",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--max-bid-records-per-company", "$MaxBidRecordsPerCompany",
    "--history-window-years", $HistoryWindowYears,
    "--history-window-months", "$HistoryWindowMonths",
    "--bid-list-page-size", "$BidListPageSize",
    "--max-bid-list-pages-per-company", "$MaxBidListPagesPerCompany",
    "--long-tail-cutoff-year", "$LongTailCutoffYear",
    "--max-long-tail-bid-shows-per-company", "$MaxLongTailBidShowsPerCompany"
)

if ($YgpExpansionRoot) {
    $argsList += @("--ygp-expansion-root", $YgpExpansionRoot)
}
if ($YgpCoverageCloseoutRoot) {
    $argsList += @("--ygp-coverage-closeout-root", $YgpCoverageCloseoutRoot)
}
if ($GdcicBrowserReadbackJson) {
    $argsList += @("--gdcic-browser-readback-json", $GdcicBrowserReadbackJson)
}
if ($GdcicBrowserReadbackRoot) {
    $argsList += @("--gdcic-browser-readback-root", $GdcicBrowserReadbackRoot)
}
if ($Stage4BackfillFollowupQueueJson) {
    $argsList += @("--stage4-backfill-followup-queue-json", $Stage4BackfillFollowupQueueJson)
}
if ($RuntimeBlockerFallbackSourcePlanJson) {
    $argsList += @("--stage4-backfill-followup-queue-json", $RuntimeBlockerFallbackSourcePlanJson)
}
if ($Stage4BackfillFollowupQueueRoot) {
    $argsList += @("--stage4-backfill-followup-queue-root", $Stage4BackfillFollowupQueueRoot)
}
if ($ReleaseFieldQueryJson) {
    $argsList += @("--release-field-query-json", $ReleaseFieldQueryJson)
}
if ($ReleaseFieldQueryRoot) {
    $argsList += @("--release-field-query-root", $ReleaseFieldQueryRoot)
}
if ($EnableLivePublicQuery) {
    $argsList += "--enable-live-public-query"
}
if ($MaxLiveCompanies -gt 0) {
    $argsList += @("--max-live-companies", "$MaxLiveCompanies")
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
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
