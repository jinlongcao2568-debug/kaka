param(
    [string]$OutputDir = "tmp/evaluation-real-samples/stage2-scrapling-adaptive-selector-poc-v1",
    [int]$Percentage = 20
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $env:PYTHONPATH = "src"
    python -m stage2_ingestion.scrapling_adaptive_selector_poc --output-dir $OutputDir --percentage $Percentage
} finally {
    Pop-Location
}
