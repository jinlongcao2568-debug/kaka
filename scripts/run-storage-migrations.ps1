[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$Revision = 'head'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$Provided)
    if ($Provided) { return (Resolve-Path $Provided).Path }
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

function Find-PythonCommand {
    foreach ($candidate in @(
        @{ executable = 'python'; arguments = @() },
        @{ executable = 'py'; arguments = @('-3') },
        @{ executable = 'py'; arguments = @() }
    )) {
        if (Get-Command $candidate.executable -ErrorAction SilentlyContinue) {
            return [pscustomobject]$candidate
        }
    }
    return $null
}

$root = Resolve-RepoRoot -Provided $RepoRoot
if (-not $env:KAKA_STORAGE_DATABASE_URL) {
    throw 'KAKA_STORAGE_DATABASE_URL is required; storage migrations never use a default database URL.'
}

$pythonCommand = Find-PythonCommand
if (-not $pythonCommand) {
    throw 'No compatible python runtime command was found (python / py -3 / py).'
}

$previousPythonPath = $env:PYTHONPATH
try {
    $srcPath = Join-Path $root 'src'
    $env:PYTHONPATH = if ($previousPythonPath) { "$srcPath;$previousPythonPath" } else { $srcPath }
    Push-Location $root
    try {
        & $pythonCommand.executable @($pythonCommand.arguments) -m alembic upgrade $Revision
        if ($LASTEXITCODE -ne 0) {
            throw "alembic upgrade $Revision failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
