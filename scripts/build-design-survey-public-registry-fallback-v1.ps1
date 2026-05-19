param(
    [string]$DesignSurveyStage4ExecutionJson = "",
    [string]$DesignSurveyStage4ExecutionRoot = "",
    [string]$Flow08Stage4InputsJson = "",
    [string]$Flow08Stage4InputsRoot = "",
    [string]$Flow08AttachmentParseJson = "",
    [string]$Flow08AttachmentParseRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DesignSurveyStage4ExecutionJson -and -not $DesignSurveyStage4ExecutionRoot) {
    $stage4Candidates = Get-ChildItem -Path (Join-Path $repoRoot "tmp\evaluation-real-samples") -Recurse -Filter "company-first-stage4-execution.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    if (-not $stage4Candidates -or $stage4Candidates.Count -eq 0) {
        throw "No company-first-stage4-execution.json found under tmp\evaluation-real-samples. Pass -DesignSurveyStage4ExecutionJson explicitly."
    }
    $DesignSurveyStage4ExecutionJson = $stage4Candidates[0].FullName
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-public-registry-fallback-v1"
}

$outputJson = Join-Path $OutputRoot "design-survey-public-registry-fallback-v1.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.design_survey_public_registry_fallback",
    "--output-root", $OutputRoot,
    "--output-json", $outputJson
)

if ($DesignSurveyStage4ExecutionJson) {
    $argsList += @("--design-survey-stage4-execution-json", $DesignSurveyStage4ExecutionJson)
}
if ($DesignSurveyStage4ExecutionRoot) {
    $argsList += @("--design-survey-stage4-execution-root", $DesignSurveyStage4ExecutionRoot)
}
if ($Flow08Stage4InputsJson) {
    $argsList += @("--flow08-stage4-inputs-json", $Flow08Stage4InputsJson)
}
if ($Flow08Stage4InputsRoot) {
    $argsList += @("--flow08-stage4-inputs-root", $Flow08Stage4InputsRoot)
}
if ($Flow08AttachmentParseJson) {
    $argsList += @("--flow08-attachment-parse-json", $Flow08AttachmentParseJson)
}
if ($Flow08AttachmentParseRoot) {
    $argsList += @("--flow08-attachment-parse-root", $Flow08AttachmentParseRoot)
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
