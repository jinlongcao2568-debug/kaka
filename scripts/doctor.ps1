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
$checks = [System.Collections.Generic.List[object]]::new()

$checks.Add([pscustomobject]@{ name='pwsh_version'; ok=($PSVersionTable.PSVersion.Major -ge 7); detail=$PSVersionTable.PSVersion.ToString() }) | Out-Null
$checks.Add([pscustomobject]@{ name='root_readme'; ok=(Test-Path -LiteralPath (Join-Path $root 'README.md')); detail='README.md' }) | Out-Null
$checks.Add([pscustomobject]@{ name='decision_index'; ok=(Test-Path -LiteralPath (Join-Path $root 'docs/裁决总表.md')); detail='docs/裁决总表.md' }) | Out-Null
$checks.Add([pscustomobject]@{ name='contracts_root'; ok=(Test-Path -LiteralPath (Join-Path $root 'contracts')); detail='contracts/' }) | Out-Null
$checks.Add([pscustomobject]@{ name='docs_root'; ok=(Test-Path -LiteralPath (Join-Path $root 'docs')); detail='docs/' }) | Out-Null
$checks.Add([pscustomobject]@{ name='scripts_root'; ok=(Test-Path -LiteralPath (Join-Path $root 'scripts')); detail='scripts/' }) | Out-Null
$checks.Add([pscustomobject]@{ name='testing_release_checklist'; ok=(Test-Path -LiteralPath (Join-Path $root 'contracts/testing/release_checklist.json')); detail='contracts/testing/release_checklist.json' }) | Out-Null

$just = Get-Command just -ErrorAction SilentlyContinue
$checks.Add([pscustomobject]@{ name='just_available'; ok=($null -ne $just); detail= if ($just) { $just.Source } else { 'not found' } }) | Out-Null

$result = [pscustomobject]@{
    script = 'doctor.ps1'
    repoRoot = $root
    ok = (@($checks | Where-Object ok -eq $false).Count -eq 0)
    checks = $checks
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[doctor] repo: $root"
    foreach ($check in $checks) {
        $mark = if ($check.ok) { 'PASS' } else { 'FAIL' }
        Write-Host ("[{0}] {1} -> {2}" -f $mark, $check.name, $check.detail)
    }
}

if ($EmitJson) { $result | ConvertTo-Json -Depth 20 }
if (-not $result.ok) { exit 1 }
exit 0



