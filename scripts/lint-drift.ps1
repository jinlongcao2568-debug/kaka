[CmdletBinding()]
param(
    [string]$RepoRoot,
    [switch]$EmitJson,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$Provided)
    if ($Provided) { return (Resolve-Path $Provided).Path }
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$issues = [System.Collections.Generic.List[object]]::new()

$blockingPattern = ([string]::Join('', @([char]33509,[char]24050,[char]23384,[char]22312)))
$patternTbd = ([string]::Join('', @([char]116,[char]98,[char]100,[char]95)))
$patternWork = ([string]::Join('', @([char]84,[char]79,[char]68,[char]79)))
$patternRepair = ([string]::Join('', @([char]70,[char]73,[char]88,[char]77,[char]69)))
$patternSpecs = @(
    [pscustomobject]@{ label = $patternTbd; regex = '(?<![A-Za-z0-9_])' + [regex]::Escape($patternTbd) },
    [pscustomobject]@{ label = $patternWork; regex = '(?<![A-Za-z0-9_])' + [regex]::Escape($patternWork) + '(?![A-Za-z0-9_])' },
    [pscustomobject]@{ label = $patternRepair; regex = '(?<![A-Za-z0-9_])' + [regex]::Escape($patternRepair) + '(?![A-Za-z0-9_])' },
    [pscustomobject]@{ label = $blockingPattern; regex = [regex]::Escape($blockingPattern) }
)

$scanDirs = @('docs','contracts','scripts') | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path -LiteralPath $_ }
$files = foreach ($dir in $scanDirs) {
    Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in '.md','.json','.yaml','.yml','.ps1' }
}

foreach ($file in $files) {
    $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
    foreach ($patternSpec in $patternSpecs) {
        if ($content -match $patternSpec.regex) {
            $severity = if ($patternSpec.label -eq $blockingPattern) { 'ERROR' } else { 'WARNING' }
            $issues.Add([pscustomobject]@{ severity=$severity; code='DRIFT_PATTERN'; path=$file.FullName; message="Found pattern: $($patternSpec.label)" }) | Out-Null
        }
    }
}

$l0Candidates = @(Get-ChildItem -LiteralPath $root -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'L0' })
if (@($l0Candidates).Count -gt 1) {
    $issues.Add([pscustomobject]@{ severity='ERROR'; code='MULTIPLE_L0_CANDIDATES'; path=$root; message='More than one L0 candidate file detected at repository root.' }) | Out-Null
}

$d13Candidates = @(Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'D13' -and $_.Extension -eq '.md' -and $_.FullName -notmatch '\\archive\\' })
if (@($d13Candidates).Count -gt 1) {
    $issues.Add([pscustomobject]@{ severity='WARNING'; code='MULTIPLE_D13_FILES'; path=$root; message='More than one D13-like markdown file detected. Confirm only one is the effective formal source.' }) | Out-Null
}

$result = [pscustomobject]@{
    script = 'lint-drift.ps1'
    repoRoot = $root
    ok = (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[lint-drift] repo: $root"
    if ($issues.Count -eq 0) {
        Write-Host '[lint-drift] PASS'
    } else {
        foreach ($issue in $issues) {
            Write-Host ("[{0}] {1} {2} {3}" -f $issue.severity, $issue.code, $issue.path, $issue.message)
        }
    }
}

if ($EmitJson) { $result | ConvertTo-Json -Depth 20 }
if (-not $result.ok) { exit 1 }
exit 0
