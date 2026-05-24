param(
    [string[]]$RunRoot = @(),
    [string[]]$ScoreboardJson = @(),
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-scoreboard-comparison-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

function Expand-ListArg {
    param([string[]]$Values)
    $expanded = @()
    foreach ($value in $Values) {
        if (-not $value) {
            continue
        }
        foreach ($part in ($value -split "[,;]")) {
            $trimmed = $part.Trim()
            if ($trimmed) {
                $expanded += $trimmed
            }
        }
    }
    return $expanded
}

$argsList = @(
    "-m", "storage.stage1_6_scoreboard_comparison",
    "--output-root", $OutputRoot
)

foreach ($value in (Expand-ListArg -Values $RunRoot)) {
    if ($value) {
        $argsList += @("--run-root", $value)
    }
}
foreach ($value in (Expand-ListArg -Values $ScoreboardJson)) {
    if ($value) {
        $argsList += @("--scoreboard-json", $value)
    }
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
