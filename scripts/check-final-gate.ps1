[CmdletBinding()]
param(
    [string]$RepoRoot,
    [switch]$EmitJson,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Uses control/source_blueprint_registry.yaml via scripts/check-task-packet.ps1
# Coverage anchors retained for anti-drift checks:
# - UNREGISTERED_SOURCE_BLUEPRINT_BATCH
# - REL-104
# - REL-109
# - REG-ARCH-UNUSED-CATALOG-PARTIAL-CONSUMPTION
# - REG-ARCH-HANDOFF-PRODUCER-CONSUMER-DRIFT
# - REG-ARCH-UNIFIED-RUNTIME-SPINE

function Resolve-RepoRoot {
    param([string]$Provided)
    if ($Provided) { return (Resolve-Path $Provided).Path }
    return (Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) '..')).Path
}

function Invoke-Step {
    param([string]$Path,[string]$Root)
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path -RepoRoot $Root -EmitJson *> $tmp
        $code = $LASTEXITCODE
        $raw = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
        $jsonStart = $raw.IndexOf('{')
        if ($jsonStart -ge 0) { $raw = $raw.Substring($jsonStart) }
        $parsed = $raw | ConvertFrom-Json -Depth 100
        return [pscustomobject]@{ exitCode=$code; result=$parsed }
    }
    catch {
        return [pscustomobject]@{ exitCode=1; result=[pscustomobject]@{ script=(Split-Path $Path -Leaf); ok=$false; issues=@([pscustomobject]@{severity='ERROR';code='STEP_FAILED';message=$_.Exception.Message}) } }
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-CommandStep {
    param([string]$Name,[string]$Executable,[string[]]$Arguments,[string]$Root)
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        Push-Location $Root
        & $Executable @Arguments *> $tmp
        $code = $LASTEXITCODE
        $issues = [System.Collections.Generic.List[object]]::new()
        if ($code -ne 0) {
            $output = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
            $issues.Add([pscustomobject]@{ severity='ERROR'; code='STEP_FAILED'; path=$Name; message="$Name failed with exit code $code. Output: $output" }) | Out-Null
        }
        return [pscustomobject]@{ exitCode=$code; result=[pscustomobject]@{ script=$Name; ok=($code -eq 0); issues=$issues } }
    }
    catch {
        return [pscustomobject]@{ exitCode=1; result=[pscustomobject]@{ script=$Name; ok=$false; issues=@([pscustomobject]@{ severity='ERROR'; code='STEP_FAILED'; path=$Name; message=$_.Exception.Message }) } }
    }
    finally {
        Pop-Location -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Get-FieldValue {
    param([object]$Object,[string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) { return $Object[$Name] }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$scriptDir = Split-Path -Parent $PSCommandPath
$steps = @(
    'doctor.ps1',
    'check-task-packet.ps1',
    'validate-contracts.ps1',
    'check-state-alignment.ps1',
    'run-golden.ps1',
    'run-governance-contracts.ps1',
    'lint-drift.ps1'
)
$stepResults = @(
    foreach ($step in $steps) { Invoke-Step -Path (Join-Path $scriptDir $step) -Root $root }
)
$stepResults += Invoke-CommandStep -Name 'check-handoff-dependencies.ps1' -Executable 'pwsh' -Arguments @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $scriptDir 'check-handoff-dependencies.ps1')) -Root $root
if (Get-Command python -ErrorAction SilentlyContinue) {
    $stepResults += Invoke-CommandStep -Name 'python tests/run_tests.py' -Executable 'python' -Arguments @('tests/run_tests.py') -Root $root
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $stepResults += Invoke-CommandStep -Name 'python tests/run_tests.py' -Executable 'py' -Arguments @('-3','tests/run_tests.py') -Root $root
} else {
    $stepResults += [pscustomobject]@{ exitCode=1; result=[pscustomobject]@{ script='python tests/run_tests.py'; ok=$false; issues=@([pscustomobject]@{ severity='ERROR'; code='PYTHON_RUNTIME_MISSING'; path='python tests/run_tests.py'; message='No compatible python runtime command was found.' }) } }
}
$issues = [System.Collections.Generic.List[object]]::new()
foreach ($sr in $stepResults) {
    $resultObject = Get-FieldValue -Object $sr -Name 'result'
    if (-not $resultObject) { continue }
    $resultIssues = Get-FieldValue -Object $resultObject -Name 'issues'
    if ($null -eq $resultIssues) { continue }
    foreach ($issue in @($resultIssues)) {
        if ($null -ne $issue) { $issues.Add($issue) | Out-Null }
    }
}
$result = [pscustomobject]@{ script='check-final-gate.ps1'; repoRoot=$root; ok=(@($issues | Where-Object severity -eq 'ERROR').Count -eq 0); steps=$stepResults; issues=$issues }
if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[check-final-gate] repo: $root"
    foreach ($sr in $stepResults) { Write-Host ("[check-final-gate] step={0} ok={1} exit={2}" -f $sr.result.script, $sr.result.ok, $sr.exitCode) }
    if ($result.ok) { Write-Host '[check-final-gate] PASS' } else { foreach ($issue in $issues) { Write-Host ("[{0}] {1} {2}" -f $issue.severity, $issue.code, $issue.message) } }
}
if ($EmitJson) { $result | ConvertTo-Json -Depth 100 }
if (-not $result.ok) { exit 1 }
exit 0
