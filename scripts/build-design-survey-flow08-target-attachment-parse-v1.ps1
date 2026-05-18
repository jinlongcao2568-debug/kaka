param(
    [string]$DesignSurveyFlow08ReadbackJson = "",
    [string]$DesignSurveyFlow08ReadbackRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [switch]$EnableOcr,
    [int]$MaxPages = 20,
    [int]$OcrMaxPages = 2,
    [string]$OcrPageRanges = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DesignSurveyFlow08ReadbackRoot -and -not $DesignSurveyFlow08ReadbackJson) {
    $DesignSurveyFlow08ReadbackRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-flow08-targeted-readback-v1"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\design-survey-flow08-target-attachment-parse-v1"
}

$outputJson = Join-Path $OutputRoot "design-survey-flow08-target-attachment-parse-v1.json"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.design_survey_flow08_target_attachment_parse",
    "--output-root", $OutputRoot,
    "--output-json", $outputJson,
    "--max-pages", "$MaxPages",
    "--ocr-max-pages", "$OcrMaxPages"
)

if ($DesignSurveyFlow08ReadbackJson) {
    $argsList += @("--design-survey-flow08-readback-json", $DesignSurveyFlow08ReadbackJson)
}
if ($DesignSurveyFlow08ReadbackRoot) {
    $argsList += @("--design-survey-flow08-readback-root", $DesignSurveyFlow08ReadbackRoot)
}
if ($ProjectIds) {
    $argsList += @("--project-ids", $ProjectIds)
}
if ($EnableOcr) {
    $argsList += "--enable-ocr"
}
if ($OcrPageRanges) {
    $argsList += @("--ocr-page-ranges", $OcrPageRanges)
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
