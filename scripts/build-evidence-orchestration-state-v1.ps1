param(
    [string]$Stage16StorageJson = "",
    [string]$CompanyFirstStage4InputsJson = "",
    [string]$P13BCompanyHistoryJson = "",
    [string]$P13BCompanyHistoryRoot = "",
    [string]$OriginalNoticeBacktraceJson = "",
    [string]$OriginalNoticeBacktraceRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
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
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-orchestration-state-v1"
}

$outputJson = Join-Path $OutputRoot "evidence-orchestration-state-v1.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.evidence_orchestration_state_machine",
    "--stage16-storage-json", $Stage16StorageJson,
    "--output-root", $OutputRoot,
    "--output-json", $outputJson
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
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
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
