[CmdletBinding()]
param(
    [string]$RepoRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$Provided)

    if (-not [string]::IsNullOrWhiteSpace($Provided)) {
        return (Resolve-Path -LiteralPath $Provided).Path
    }

    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

function Get-DisplayPath {
    param(
        [string]$BasePath,
        [string]$TargetPath
    )

    return ([System.IO.Path]::GetRelativePath($BasePath, $TargetPath) -replace '\\', '/')
}

function Write-Log {
    param([string]$Message)

    Write-Output "[clean-python-cache] $Message"
}

$resolvedRoot = Resolve-RepoRoot -Provided $RepoRoot
if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
    throw "Repo root does not exist: $resolvedRoot"
}

$removedDirectories = [System.Collections.Generic.List[string]]::new()
$removedFiles = [System.Collections.Generic.List[string]]::new()
$failures = [System.Collections.Generic.List[string]]::new()

Write-Log "repo root: $resolvedRoot"

$cacheDirectories = @(
    Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Force -Directory -Filter '__pycache__' -ErrorAction Stop
    Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Force -Directory -Filter '.pytest_cache' -ErrorAction Stop
) | Sort-Object FullName -Unique -Descending

foreach ($directory in $cacheDirectories) {
    if (-not (Test-Path -LiteralPath $directory.FullName)) {
        continue
    }

    $displayPath = Get-DisplayPath -BasePath $resolvedRoot -TargetPath $directory.FullName
    try {
        Remove-Item -LiteralPath $directory.FullName -Recurse -Force -ErrorAction Stop
        $removedDirectories.Add($displayPath) | Out-Null
        Write-Log "removed directory: $displayPath"
    }
    catch {
        $message = "failed to remove directory: $displayPath :: $($_.Exception.Message)"
        $failures.Add($message) | Out-Null
        Write-Log $message
    }
}

$pycFiles = @(Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Force -File -Filter '*.pyc' -ErrorAction Stop) |
    Sort-Object FullName -Unique

foreach ($file in $pycFiles) {
    if (-not (Test-Path -LiteralPath $file.FullName)) {
        continue
    }

    $displayPath = Get-DisplayPath -BasePath $resolvedRoot -TargetPath $file.FullName
    try {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop
        $removedFiles.Add($displayPath) | Out-Null
        Write-Log "removed file: $displayPath"
    }
    catch {
        $message = "failed to remove file: $displayPath :: $($_.Exception.Message)"
        $failures.Add($message) | Out-Null
        Write-Log $message
    }
}

if ($removedDirectories.Count -eq 0 -and $removedFiles.Count -eq 0 -and $failures.Count -eq 0) {
    Write-Log 'no Python cache artifacts found'
}

Write-Log ("summary: removed {0} cache directories and {1} .pyc files" -f $removedDirectories.Count, $removedFiles.Count)

if ($failures.Count -gt 0) {
    Write-Log 'status: FAILED'
    exit 1
}

Write-Log 'status: SUCCESS'
