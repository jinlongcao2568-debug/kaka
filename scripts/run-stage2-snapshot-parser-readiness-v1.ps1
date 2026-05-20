param(
    [string]$InputParent = "tmp/evaluation-real-samples",
    [string]$OutputDir = "tmp/evaluation-real-samples/stage2-snapshot-parser-readiness-v1",
    [string]$RootPattern = "stage1-5-limit3-*",
    [int]$MaxSnapshotsPerRoot = 200,
    [switch]$ExcludeEmptyRoots
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $env:PYTHONPATH = "src"
    $argsList = @(
        "-m", "stage2_ingestion.snapshot_parser_readiness",
        "--input-parent", $InputParent,
        "--output-dir", $OutputDir,
        "--root-pattern", $RootPattern,
        "--max-snapshots-per-root", [string]$MaxSnapshotsPerRoot
    )
    if ($ExcludeEmptyRoots) {
        $argsList += "--exclude-empty-roots"
    }
    python @argsList
} finally {
    Pop-Location
}
