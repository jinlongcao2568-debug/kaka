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

function Resolve-PythonTestCommand {
    foreach ($candidate in @(
        @{ executable = 'python'; arguments = @('tests/run_tests.py') },
        @{ executable = 'py'; arguments = @('-3', 'tests/run_tests.py') },
        @{ executable = 'py'; arguments = @('tests/run_tests.py') }
    )) {
        if (Get-Command $candidate.executable -ErrorAction SilentlyContinue) {
            return [pscustomobject]$candidate
        }
    }

    return $null
}

function Invoke-CommandStep {
    param(
        [string]$Name,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Root
    )

    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        Push-Location $Root
        & $Executable @Arguments *> $tmp
        $code = $LASTEXITCODE
        $issues = [System.Collections.Generic.List[object]]::new()
        if ($code -ne 0) {
            $output = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
            $issues.Add([pscustomobject]@{
                severity = 'ERROR'
                code     = 'STEP_FAILED'
                path     = $Name
                message  = "$Name failed with exit code $code. Output: $output"
            }) | Out-Null
        }

        return [pscustomobject]@{
            exitCode = $code
            result   = [pscustomobject]@{
                script = $Name
                ok     = ($code -eq 0)
                issues = $issues
            }
        }
    }
    catch {
        return [pscustomobject]@{
            exitCode = 1
            result   = [pscustomobject]@{
                script = $Name
                ok     = $false
                issues = @([pscustomobject]@{
                    severity = 'ERROR'
                    code     = 'STEP_FAILED'
                    path     = $Name
                    message  = $_.Exception.Message
                })
            }
        }
    }
    finally {
        Pop-Location -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Load-YamlDocument {
    param([string]$Path)

    $convertYaml = Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue
    if ($convertYaml) {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8) | ConvertFrom-Yaml
    }

    $yq = Get-Command yq -ErrorAction SilentlyContinue
    if ($yq) {
        $json = & $yq.Source -o=json '.' $Path
        if ($LASTEXITCODE -ne 0) {
            throw "yq failed to parse $Path"
        }
        return $json | ConvertFrom-Json -Depth 100
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw 'Neither ConvertFrom-Yaml nor yq nor python is available for YAML parsing.'
    }

    $json = @'
import json
import sys
import yaml

path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as handle:
    data = yaml.safe_load(handle)
sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
'@ | & $pythonCommand.Source - $Path
    if ($LASTEXITCODE -ne 0) {
        throw "python yaml parser failed for $Path"
    }
    return $json | ConvertFrom-Json -Depth 100
}

function Get-FieldValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) { return $Object[$Name] }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$scriptDir = Split-Path -Parent $PSCommandPath
$steps = @(
    'validate-contracts.ps1',
    'check-automation-readiness.ps1',
    'check-semantic-alignment.ps1',
    'run-golden.ps1',
    'run-governance-contracts.ps1',
    'lint-drift.ps1'
)

$stepResults = foreach ($step in $steps) {
    Invoke-Step -Path (Join-Path $scriptDir $step) -Root $root
}

$pythonCommand = Resolve-PythonTestCommand
if (-not $pythonCommand) {
    $stepResults += [pscustomobject]@{
        exitCode = 1
        result   = [pscustomobject]@{
            script = 'python tests/run_tests.py'
            ok     = $false
            issues = @([pscustomobject]@{
                severity = 'ERROR'
                code     = 'PYTHON_RUNTIME_MISSING'
                path     = 'python tests/run_tests.py'
                message  = 'No compatible python runtime command was found (python / py -3 / py).'
            })
        }
    }
}
else {
    $stepResults += Invoke-CommandStep -Name 'python tests/run_tests.py' -Executable $pythonCommand.executable -Arguments $pythonCommand.arguments -Root $root
}

$issues = [System.Collections.Generic.List[object]]::new()
foreach ($sr in $stepResults) {
    if ($sr.result -and $sr.result.issues) {
        foreach ($issue in $sr.result.issues) { $issues.Add($issue) | Out-Null }
    }
}

$deduped = [System.Collections.Generic.List[object]]::new()
$seenIssueKeys = [System.Collections.Generic.HashSet[string]]::new()
foreach ($issue in $issues) {
    $path = if ($issue.PSObject.Properties.Name -contains 'path') { [string]$issue.path } else { '' }
    $message = if ($issue.PSObject.Properties.Name -contains 'message') { [string]$issue.message } else { '' }
    $key = "{0}|{1}|{2}|{3}" -f $issue.severity, $issue.code, $path, $message
    if ($seenIssueKeys.Add($key)) {
        $deduped.Add($issue) | Out-Null
    }
}
$issues = $deduped

$releaseChecklistPath = Join-Path $root 'contracts/testing/release_checklist.json'
if (-not (Test-Path -LiteralPath $releaseChecklistPath)) {
    $issues.Add([pscustomobject]@{ severity='ERROR'; code='MISSING_RELEASE_CHECKLIST'; path=$releaseChecklistPath; message='Release checklist file is required before release checks can pass.' }) | Out-Null
}
else {
    try {
        $releaseChecklist = Get-Content -LiteralPath $releaseChecklistPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        $releaseItemIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($section in @($releaseChecklist.sections)) {
            foreach ($item in @($section.items)) {
                $releaseItemIds.Add([string]$item.itemId) | Out-Null
            }
        }
        foreach ($requiredId in @('REL-100','REL-101','REL-102','REL-103','REL-104','REL-105','REL-106','REL-107','REL-108','REL-109','REL-110','REL-111','REL-112','REL-113','REL-114','REL-160','REL-161','REL-162','REL-163','REL-164','REL-165','REL-187','REL-188','REL-189','REL-190','REL-191','REL-192')) {
            if (-not $releaseItemIds.Contains($requiredId)) {
                $issues.Add([pscustomobject]@{
                    severity = 'ERROR'
                    code     = 'RELEASE_REVIEW_GATE_ITEM_MISSING'
                    path     = $releaseChecklistPath
                    message  = "release_checklist.json missing required review gate item $requiredId."
                }) | Out-Null
            }
        }
    }
    catch {
        $issues.Add([pscustomobject]@{
            severity = 'ERROR'
            code     = 'RELEASE_CHECKLIST_PARSE_FAILED'
            path     = $releaseChecklistPath
            message  = $_.Exception.Message
        }) | Out-Null
    }
}

$regressionManifestPath = Join-Path $root 'contracts/testing/regression_manifest.json'
if (-not (Test-Path -LiteralPath $regressionManifestPath)) {
    $issues.Add([pscustomobject]@{ severity='ERROR'; code='MISSING_REGRESSION_MANIFEST'; path=$regressionManifestPath; message='Regression manifest file is required before release checks can pass.' }) | Out-Null
}
else {
    try {
        $regressionManifest = Get-Content -LiteralPath $regressionManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        $suiteIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($suite in @($regressionManifest.suites)) {
            $suiteIds.Add([string]$suite.suite_id) | Out-Null
        }
        foreach ($requiredSuite in @('REG-ARCH-SERVICE-HARDCODE-ANTI-REGRESSION','REG-ARCH-UNUSED-CATALOG-PARTIAL-CONSUMPTION','REG-ARCH-GOVERNANCE-RUNTIME-CONSUMPTION-CLOSURE','REG-ARCH-SCHEMA-VALIDATOR-MODEL-DRIFT','REG-ARCH-HANDOFF-PRODUCER-CONSUMER-DRIFT','REG-ARCH-UNIFIED-RUNTIME-SPINE','REG-CHANGE-CLASS-REVIEW-GATE','REG-TASK-PACKET-HARD-GATE','REG-REVIEW-GATE-STOP-LINKAGE','REG-RELEASE-READINESS-REVIEW-GATE','REG-POST-REPAIR-STATE-SYNC','REG-FF17-S2-RUNTIME-SURFACE-WRITEBACK-HARDENING','REG-FF17-S2-CAPABILITY-CANONICAL-SOURCE','REG-BLUEPRINT-REGISTRY-COMPATIBILITY')) {
            if (-not $suiteIds.Contains($requiredSuite)) {
                $issues.Add([pscustomobject]@{
                    severity = 'ERROR'
                    code     = 'REGRESSION_REVIEW_GATE_SUITE_MISSING'
                    path     = $regressionManifestPath
                    message  = "regression_manifest.json missing required review gate suite $requiredSuite."
                }) | Out-Null
            }
        }
    }
    catch {
        $issues.Add([pscustomobject]@{
            severity = 'ERROR'
            code     = 'REGRESSION_MANIFEST_PARSE_FAILED'
            path     = $regressionManifestPath
            message  = $_.Exception.Message
        }) | Out-Null
    }
}

$reviewGateMatrixPath = Join-Path $root 'control/review_gate_matrix.yaml'
if (-not (Test-Path -LiteralPath $reviewGateMatrixPath)) {
    $issues.Add([pscustomobject]@{
        severity = 'ERROR'
        code     = 'MISSING_REVIEW_GATE_MATRIX'
        path     = $reviewGateMatrixPath
        message  = 'review_gate_matrix.yaml is required before release checks can pass.'
    }) | Out-Null
}

$currentTaskPath = Join-Path $root 'control/current_task.yaml'
if (-not (Test-Path -LiteralPath $currentTaskPath)) {
    $issues.Add([pscustomobject]@{
        severity = 'ERROR'
        code     = 'MISSING_CURRENT_TASK'
        path     = $currentTaskPath
        message  = 'control/current_task.yaml is required before release checks can pass.'
    }) | Out-Null
}
else {
    try {
        $currentTask = Load-YamlDocument -Path $currentTaskPath
        $taskPacket = Get-FieldValue -Object (Get-FieldValue -Object $currentTask -Name 'currentTask') -Name 'task_packet'
        if (-not $taskPacket) {
            $issues.Add([pscustomobject]@{
                severity = 'ERROR'
                code     = 'CURRENT_TASK_PACKET_MISSING'
                path     = $currentTaskPath
                message  = 'current_task.yaml must include currentTask.task_packet before release checks can pass.'
            }) | Out-Null
        }
        else {
            $sourceBlueprintBatchId = [string](Get-FieldValue -Object $taskPacket -Name 'source_blueprint_batch_id')
            if ([string]::IsNullOrWhiteSpace($sourceBlueprintBatchId)) {
                $issues.Add([pscustomobject]@{
                    severity = 'ERROR'
                    code     = 'CURRENT_TASK_SOURCE_BLUEPRINT_BATCH_MISSING'
                    path     = $currentTaskPath
                    message  = 'currentTask.task_packet.source_blueprint_batch_id is required and must be registered in blueprint_registry.'
                }) | Out-Null
            }
            else {
                $taskPacketLibraryPath = Join-Path $root 'control/task_packet_library.yaml'
                if (-not (Test-Path -LiteralPath $taskPacketLibraryPath)) {
                    $issues.Add([pscustomobject]@{
                        severity = 'ERROR'
                        code     = 'BLUEPRINT_REGISTRY_FILE_MISSING'
                        path     = $taskPacketLibraryPath
                        message  = 'control/task_packet_library.yaml is required for source blueprint validation.'
                    }) | Out-Null
                }
                else {
                    $taskPacketLibrary = Load-YamlDocument -Path $taskPacketLibraryPath
                    $blueprintRegistry = Get-FieldValue -Object $taskPacketLibrary -Name 'blueprint_registry'
                    $registeredBlueprints = @()
                    if ($blueprintRegistry) {
                        $registeredBlueprints = @((Get-FieldValue -Object $blueprintRegistry -Name 'registered_blueprints'))
                    }

                    if (@($registeredBlueprints).Count -eq 0) {
                        $issues.Add([pscustomobject]@{
                            severity = 'ERROR'
                            code     = 'BLUEPRINT_REGISTRY_MISSING'
                            path     = $taskPacketLibraryPath
                            message  = 'task_packet_library.yaml must define blueprint_registry.registered_blueprints.'
                        }) | Out-Null
                    }
                    else {
                        $registeredIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
                        foreach ($blueprint in $registeredBlueprints) {
                            $blueprintId = [string](Get-FieldValue -Object $blueprint -Name 'blueprint_id')
                            if (-not [string]::IsNullOrWhiteSpace($blueprintId)) {
                                $registeredIds.Add($blueprintId) | Out-Null
                            }
                        }

                        if (-not $registeredIds.Contains($sourceBlueprintBatchId)) {
                            $issues.Add([pscustomobject]@{
                                severity = 'ERROR'
                                code     = 'UNREGISTERED_SOURCE_BLUEPRINT_BATCH'
                                path     = $currentTaskPath
                                message  = "currentTask.task_packet.source_blueprint_batch_id=$sourceBlueprintBatchId is not registered in control/task_packet_library.yaml#blueprint_registry."
                            }) | Out-Null
                        }
                    }
                }
            }
        }
    }
    catch {
        $issues.Add([pscustomobject]@{
            severity = 'ERROR'
            code     = 'CURRENT_TASK_PARSE_FAILED'
            path     = $currentTaskPath
            message  = $_.Exception.Message
        }) | Out-Null
    }
}

$result = [pscustomobject]@{
    script = 'check-release.ps1'
    repoRoot = $root
    ok = (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)
    steps = $stepResults
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[check-release] repo: $root"
    foreach ($sr in $stepResults) {
        Write-Host ("[check-release] step={0} ok={1} exit={2}" -f $sr.result.script, $sr.result.ok, $sr.exitCode)
    }
    if ($issues.Count -eq 0) {
        Write-Host '[check-release] PASS'
    } else {
        foreach ($issue in $issues) {
            $msg = if ($issue.PSObject.Properties.Name -contains 'message') { $issue.message } else { '' }
            Write-Host ("[{0}] {1} {2}" -f $issue.severity, $issue.code, $msg)
        }
    }
}

if ($EmitJson) { $result | ConvertTo-Json -Depth 100 }
if (-not $result.ok) { exit 1 }
exit 0
