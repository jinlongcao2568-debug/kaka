[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Executable,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Executable) {
    throw "An executable is required. Example: pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest tests.test_real_sample_autonomous_opportunity_acceptance -v"
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kaka-local-json-env-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

$previousEnv = @{
    KAKA_STORAGE_BACKEND       = $env:KAKA_STORAGE_BACKEND
    KAKA_STORAGE_SCOPE         = $env:KAKA_STORAGE_SCOPE
    KAKA_STORAGE_PATH          = $env:KAKA_STORAGE_PATH
    KAKA_STORAGE_DATABASE_URL  = $env:KAKA_STORAGE_DATABASE_URL
    KAKA_STORAGE_TEST_ISOLATION = $env:KAKA_STORAGE_TEST_ISOLATION
    KAKA_OBJECT_STORAGE_BACKEND = $env:KAKA_OBJECT_STORAGE_BACKEND
    KAKA_OBJECT_STORAGE_PATH    = $env:KAKA_OBJECT_STORAGE_PATH
    LOCALAPPDATA                = $env:LOCALAPPDATA
}

try {
    $env:KAKA_STORAGE_BACKEND = 'json-file'
    $env:KAKA_STORAGE_SCOPE = 'process'
    $env:KAKA_STORAGE_PATH = Join-Path $tempRoot 'storage.json'
    $env:KAKA_OBJECT_STORAGE_BACKEND = 'local-filesystem'
    $env:KAKA_OBJECT_STORAGE_PATH = Join-Path $tempRoot 'objects'
    $env:LOCALAPPDATA = Join-Path $tempRoot 'local-app-data'
    Remove-Item Env:KAKA_STORAGE_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:KAKA_STORAGE_TEST_ISOLATION -ErrorAction SilentlyContinue

    & $Executable @($Arguments)
    if ($LASTEXITCODE -ne $null) {
        exit $LASTEXITCODE
    }
    if (-not $?) {
        exit 1
    }
    exit 0
}
finally {
    foreach ($entry in $previousEnv.GetEnumerator()) {
        if ($null -eq $entry.Value) {
            Remove-Item ("Env:" + $entry.Key) -ErrorAction SilentlyContinue
        }
        else {
            Set-Item ("Env:" + $entry.Key) -Value $entry.Value
        }
    }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
