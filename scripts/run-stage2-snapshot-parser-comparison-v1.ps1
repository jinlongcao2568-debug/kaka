param(
    [string]$InputRoot = "tmp/evaluation-real-samples/stage1-5-limit3-p13b-live-new-strategy-v1",
    [string]$OutputDir = "",
    [int]$MaxSnapshots = 200,
    [string[]]$ProjectId = @()
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    if ([string]::IsNullOrWhiteSpace($OutputDir)) {
        $OutputDir = Join-Path $InputRoot "140-stage2-snapshot-parser-comparison"
    }

    $env:PYTHONPATH = "src"
    $argsList = @(
        "-m", "stage2_ingestion.snapshot_parser_comparison",
        "--input-root", $InputRoot,
        "--output-dir", $OutputDir,
        "--max-snapshots", [string]$MaxSnapshots
    )
    foreach ($id in $ProjectId) {
        if (-not [string]::IsNullOrWhiteSpace($id)) {
            $argsList += @("--project-id", $id)
        }
    }
    python @argsList
} finally {
    Pop-Location
}
