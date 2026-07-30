param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$EarlyProbeJson = "",
    [string]$ProjectIds = "",
    [string]$CompanyFirstResultState = "NOT_RUN",
    [string]$NameEnumerationResultState = "NOT_RUN",
    [string]$SourceStage4RecordsJson = "",
    [string]$Stage13LongTailJson = "",
    [string]$Stage4BridgeTableJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-responsible-person-early-probe-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-company-first-supplement-v1"
}

$outputJson = Join-Path $OutputRoot "company-first-certificate-supplement.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.company_first_certificate_supplement_probe",
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--company-first-result-state", $CompanyFirstResultState,
    "--name-enumeration-result-state", $NameEnumerationResultState,
    "--output-json", $outputJson
)

if ($EarlyProbeJson) {
    $argsList += @("--early-probe-json", $EarlyProbeJson)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($SourceStage4RecordsJson) {
    $argsList += @("--source-stage4-records-json", $SourceStage4RecordsJson)
}
if ($Stage13LongTailJson) {
    $argsList += @("--stage1-3-long-tail-json", $Stage13LongTailJson)
}
if ($Stage4BridgeTableJson) {
    $argsList += @("--stage4-bridge-table-json", $Stage4BridgeTableJson)
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
