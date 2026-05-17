param(
    [string]$InputRoot = "",
    [string]$RunRoot = "",
    [switch]$EnableLivePublicQuery,
    [int]$MaxLiveCompanies = 2,
    [int]$MaxBidRecordsPerCompany = 10,
    [int]$MaxLiveOriginalNotices = 2,
    [string]$HistoryWindowYears = "1,2,3",
    [string]$YgpReadbackRoot = "",
    [string]$YgpReadbackJson = "",
    [string]$YgpCoverageCloseoutRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-evidence-value-closeout-p12-v1"
}
if (-not $RunRoot) {
    $RunRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\p13b-overlap-triage-run-v1"
}

$companyHistoryRoot = Join-Path $RunRoot "01-company-history"
$originalNoticeRoot = Join-Path $RunRoot "02-original-notice"
$closeoutRoot = Join-Path $RunRoot "03-closeout"
$operationalRoot = Join-Path $RunRoot "04-operational-closeout"

foreach ($path in @($RunRoot, $companyHistoryRoot, $originalNoticeRoot, $closeoutRoot, $operationalRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

$buildCompanyScript = Join-Path $scriptDir "build-p13b-company-history-overlap-triage-v1.ps1"
$buildOriginalScript = Join-Path $scriptDir "build-p13b-original-notice-backtrace-v1.ps1"
$buildCloseoutScript = Join-Path $scriptDir "build-p13b-overlap-triage-closeout-v1.ps1"
$buildOperationalScript = Join-Path $scriptDir "build-p13b-operational-closeout-v1.ps1"

function Invoke-Step {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments
    )
    $command = @("pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $Arguments
    & $command[0] $command[1..($command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$companyArgs = @(
    "-InputRoot", $InputRoot,
    "-OutputRoot", $companyHistoryRoot,
    "-MaxLiveCompanies", "$MaxLiveCompanies",
    "-MaxBidRecordsPerCompany", "$MaxBidRecordsPerCompany",
    "-HistoryWindowYears", $HistoryWindowYears
)
if ($EnableLivePublicQuery) {
    $companyArgs += "-EnableLivePublicQuery"
}
if ($EmitJson) {
    $companyArgs += "-EmitJson"
}
Invoke-Step -ScriptPath $buildCompanyScript -Arguments $companyArgs

$originalArgs = @(
    "-CompanyHistoryTriageRoot", $companyHistoryRoot,
    "-OutputRoot", $originalNoticeRoot,
    "-MaxLiveOriginalNotices", "$MaxLiveOriginalNotices"
)
if ($YgpReadbackRoot) {
    $originalArgs += @("-YgpReadbackRoot", $YgpReadbackRoot)
}
if ($YgpReadbackJson) {
    $originalArgs += @("-YgpReadbackJson", $YgpReadbackJson)
}
if ($EnableLivePublicQuery) {
    $originalArgs += "-EnableLivePublicQuery"
}
if ($EmitJson) {
    $originalArgs += "-EmitJson"
}
Invoke-Step -ScriptPath $buildOriginalScript -Arguments $originalArgs

$closeoutArgs = @(
    "-CompanyHistoryTriageRoot", $companyHistoryRoot,
    "-OriginalNoticeBacktraceRoot", $originalNoticeRoot,
    "-OutputRoot", $closeoutRoot
)
if ($YgpReadbackRoot) {
    $closeoutArgs += @("-YgpReadbackRoot", $YgpReadbackRoot)
} elseif ($YgpReadbackJson) {
    $closeoutArgs += @("-YgpReadbackRoot", (Split-Path -Parent $YgpReadbackJson))
}
if ($PSBoundParameters.ContainsKey("YgpCoverageCloseoutRoot")) {
    $closeoutArgs += @("-YgpCoverageCloseoutRoot", $YgpCoverageCloseoutRoot)
}
if ($EmitJson) {
    $closeoutArgs += "-EmitJson"
}
Invoke-Step -ScriptPath $buildCloseoutScript -Arguments $closeoutArgs

$operationalArgs = @(
    "-CompanyHistoryTriageRoot", $companyHistoryRoot,
    "-OriginalNoticeBacktraceRoot", $originalNoticeRoot,
    "-OverlapTriageCloseoutRoot", $closeoutRoot,
    "-OutputRoot", $operationalRoot
)
if ($EmitJson) {
    $operationalArgs += "-EmitJson"
}
Invoke-Step -ScriptPath $buildOperationalScript -Arguments $operationalArgs
