param(
    [string]$DesignSurveyFlow08AttachmentParseJson = "",
    [string]$DesignSurveyFlow08AttachmentParseRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DesignSurveyFlow08AttachmentParseJson -and -not $DesignSurveyFlow08AttachmentParseRoot) {
    $parseCandidates = Get-ChildItem -Path (Join-Path $repoRoot "tmp\evaluation-real-samples") -Recurse -Filter "design-survey-flow08-target-attachment-parse-v1.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    if (-not $parseCandidates -or $parseCandidates.Count -eq 0) {
        throw "No design-survey-flow08-target-attachment-parse-v1.json found under tmp\evaluation-real-samples. Pass -DesignSurveyFlow08AttachmentParseJson explicitly."
    }
    $DesignSurveyFlow08AttachmentParseJson = $parseCandidates[0].FullName
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-flow08-stage4-inputs-v1"
}

$outputJson = Join-Path $OutputRoot "design-survey-flow08-stage4-inputs-v1.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.design_survey_flow08_stage4_inputs",
    "--output-root", $OutputRoot,
    "--output-json", $outputJson
)

if ($DesignSurveyFlow08AttachmentParseJson) {
    $argsList += @("--design-survey-flow08-attachment-parse-json", $DesignSurveyFlow08AttachmentParseJson)
}
if ($DesignSurveyFlow08AttachmentParseRoot) {
    $argsList += @("--design-survey-flow08-attachment-parse-root", $DesignSurveyFlow08AttachmentParseRoot)
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
