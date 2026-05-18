param(
    [string]$Stage16StorageJson = "",
    [string]$CompanyFirstStage4InputsJson = "",
    [string]$RunRoot = "",
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveCompanies = 2,
    [int]$MaxBidRecordsPerCompany = 10,
    [string]$HistoryWindowYears = "1,2,3",
    [int]$HistoryWindowMonths = 36,
    [int]$BidListPageSize = 20,
    [int]$MaxBidListPagesPerCompany = 6,
    [int]$LongTailCutoffYear = 2019,
    [int]$MaxLongTailBidShowsPerCompany = 3,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$env:PYTHONIOENCODING = "utf-8"

if (-not $RunRoot) {
    $RunRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage16-p13b-continuation-run-v1"
}

$controllerRoot = Join-Path $RunRoot "00-controller"
$p13bRoot = Join-Path $RunRoot "01-p13b-company-history"
foreach ($path in @($RunRoot, $controllerRoot, $p13bRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

$controllerScript = Join-Path $scriptDir "build-stage16-p13b-continuation-controller-v1.ps1"
$p13bScript = Join-Path $scriptDir "build-p13b-company-history-overlap-triage-v1.ps1"

$controllerArgs = @("-OutputRoot", $controllerRoot)
if ($Stage16StorageJson) {
    $controllerArgs += @("-Stage16StorageJson", $Stage16StorageJson)
}
if ($CompanyFirstStage4InputsJson) {
    $controllerArgs += @("-CompanyFirstStage4InputsJson", $CompanyFirstStage4InputsJson)
}
if ($EmitJson) {
    $controllerArgs += "-EmitJson"
}

& pwsh -NoProfile -ExecutionPolicy Bypass -File $controllerScript @controllerArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$p13bArgs = @(
    "-InputRoot", $controllerRoot,
    "-OutputRoot", $p13bRoot,
    "-MaxLiveCompanies", "$MaxLiveCompanies",
    "-MaxBidRecordsPerCompany", "$MaxBidRecordsPerCompany",
    "-HistoryWindowYears", $HistoryWindowYears,
    "-HistoryWindowMonths", "$HistoryWindowMonths",
    "-BidListPageSize", "$BidListPageSize",
    "-MaxBidListPagesPerCompany", "$MaxBidListPagesPerCompany",
    "-LongTailCutoffYear", "$LongTailCutoffYear",
    "-MaxLongTailBidShowsPerCompany", "$MaxLongTailBidShowsPerCompany"
)
if ($EnableLivePublicQuery) {
    $p13bArgs += "-EnableLivePublicQuery"
}
if ($EmitJson) {
    $p13bArgs += "-EmitJson"
}

& pwsh -NoProfile -ExecutionPolicy Bypass -File $p13bScript @p13bArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
