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
    return (Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) '..')).Path
}

function Add-Issue {
    param([ref]$Bag,[string]$Severity,[string]$Code,[string]$Message,[string]$Path='')
    $Bag.Value.Add([pscustomobject]@{
        severity = $Severity
        code = $Code
        path = $Path
        message = $Message
    }) | Out-Null
}

function Read-TextFile {
    param([string]$Path,[ref]$Issues)
    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_FILE' -Message 'Required file is missing.' -Path $Path
        return ''
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

function Load-YamlFile {
    param([string]$Path,[ref]$Issues)
    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_FILE' -Message 'Required YAML file is missing.' -Path $Path
        return $null
    }
    try {
        $convertYaml = Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue
        if ($convertYaml) {
            return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8) | ConvertFrom-Yaml
        }
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { throw 'python is required to parse YAML in this environment.' }
        $json = @'
import json
import sys
import yaml
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = yaml.safe_load(handle)
sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
'@ | & $python.Source - $Path
        if ($LASTEXITCODE -ne 0) { throw "python yaml parser failed for $Path" }
        return $json | ConvertFrom-Json -Depth 100
    }
    catch {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'YAML_PARSE_FAILED' -Message $_.Exception.Message -Path $Path
        return $null
    }
}

function Get-FieldValue {
    param([object]$Object,[string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

function Get-RegexValue {
    param([string]$Text,[string]$Pattern)
    $match = [regex]::Match($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::Multiline)
    if (-not $match.Success) { return $null }
    return $match.Groups[1].Value.Trim()
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$issues = [System.Collections.Generic.List[object]]::new()

$currentTask = Load-YamlFile -Path (Join-Path $root 'control/current_task.yaml') -Issues ([ref]$issues)
$productTaskLibrary = Load-YamlFile -Path (Join-Path $root 'control/product_task_library.yaml') -Issues ([ref]$issues)
$repoStatusText = Read-TextFile -Path (Join-Path $root 'control/repo_status.md') -Issues ([ref]$issues)
$milestoneText = Read-TextFile -Path (Join-Path $root 'control/milestone_status.yaml') -Issues ([ref]$issues)
$ax9sText = Read-TextFile -Path (Join-Path $root 'docs/AX9S_开发执行路由图.md') -Issues ([ref]$issues)
$agText = Read-TextFile -Path (Join-Path $root 'AGENTS.md') -Issues ([ref]$issues)

if ($agText -and -not $agText.Contains('current_task -> product_task_library -> repo_status')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ACTIVE_SOURCE_PRIORITY_DRIFT' -Message 'AGENTS.md must preserve current_task -> product_task_library -> repo_status.' -Path 'AGENTS.md'
}

$currentTaskText = Read-TextFile -Path (Join-Path $root 'control/current_task.yaml') -Issues ([ref]$issues)
if ($currentTaskText -and -not $currentTaskText.Contains('current_task -> product_task_library -> repo_status')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ACTIVE_SOURCE_PRIORITY_DRIFT' -Message 'current_task.yaml must preserve current_task -> product_task_library -> repo_status.' -Path 'control/current_task.yaml'
}
if ($repoStatusText -and -not $repoStatusText.Contains('current_task -> product_task_library -> repo_status')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ACTIVE_SOURCE_PRIORITY_DRIFT' -Message 'repo_status.md must preserve current_task -> product_task_library -> repo_status.' -Path 'control/repo_status.md'
}

if ($ax9sText) {
    foreach ($token in @('candidate navigation asset', '候选导航资产', 'control/current_task.yaml', 'control/product_task_library.yaml', '只作导航提示，不决定执行顺序')) {
        if (-not $ax9sText.Contains($token)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ROUTE_MAP_ROLE_DRIFT' -Message "AX9S route map must keep token: $token" -Path 'docs/AX9S_开发执行路由图.md'
        }
    }
}

$phase = Get-RegexValue -Text $repoStatusText -Pattern '^Current Phase:\s*(.+)$'
$readiness = Get-RegexValue -Text $repoStatusText -Pattern '^Current Readiness Conclusion:\s*(.+)$'
$conditionalGo = Get-RegexValue -Text $repoStatusText -Pattern '^Current Conditional-Go:\s*(.+)$'
if ($phase -ne 'PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT') {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REPO_PHASE_DRIFT' -Message "Current Phase must be PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT. Actual: $phase" -Path 'control/repo_status.md'
}
if ($readiness -ne 'READY_FOR_POST-REPAIR_MAINLINE_SELECTION') {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REPO_READINESS_DRIFT' -Message "Current Readiness Conclusion must be READY_FOR_POST-REPAIR_MAINLINE_SELECTION. Actual: $readiness" -Path 'control/repo_status.md'
}
if ($conditionalGo -ne 'READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT') {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REPO_CONDITIONAL_GO_DRIFT' -Message "Current Conditional-Go must be READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT. Actual: $conditionalGo" -Path 'control/repo_status.md'
}

foreach ($token in @(
    'External software release is a controlled-opening capability',
    'Stage 8 real execution is a controlled-opening capability',
    'Stage 9 real payment/delivery/refund is a controlled-opening capability',
    'Automated refund execution remains excluded'
)) {
    if (-not $repoStatusText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CONTROLLED_OPENING_BOUNDARY_DRIFT' -Message "repo_status.md must keep token: $token" -Path 'control/repo_status.md'
    }
}

$tasks = @((Get-FieldValue -Object $productTaskLibrary -Name 'tasks'))
if (@($tasks).Count -eq 0) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PRODUCT_TASK_LIBRARY_EMPTY' -Message 'control/product_task_library.yaml must define product tasks.' -Path 'control/product_task_library.yaml'
}
$syncRegistration = Get-FieldValue -Object $productTaskLibrary -Name 'planning_sync_implementation_registration'
if (-not $syncRegistration) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PLANNING_SYNC_REGISTRATION_MISSING' -Message 'control/product_task_library.yaml must define planning_sync_implementation_registration.' -Path 'control/product_task_library.yaml'
} else {
    $triggerPolicy = [string](Get-FieldValue -Object $syncRegistration -Name 'trigger_policy')
    $implementationState = [string](Get-FieldValue -Object $syncRegistration -Name 'implementation_state')
    $updateTriggers = @((Get-FieldValue -Object $syncRegistration -Name 'update_triggers'))
    $updatePolicy = Get-FieldValue -Object $syncRegistration -Name 'update_policy'
    if ($triggerPolicy -ne 'warning_only') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PLANNING_SYNC_POLICY_DRIFT' -Message 'planning sync trigger_policy must stay warning_only.' -Path 'control/product_task_library.yaml'
    }
    if ($implementationState -ne 'IMPLEMENTED') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PLANNING_SYNC_NOT_IMPLEMENTED' -Message 'planning sync implementation_state must be IMPLEMENTED.' -Path 'control/product_task_library.yaml'
    }
    if (@($updateTriggers).Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PLANNING_SYNC_TRIGGERS_MISSING' -Message 'planning sync must declare update_triggers.' -Path 'control/product_task_library.yaml'
    }
    if (-not $updatePolicy) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PLANNING_SYNC_UPDATE_POLICY_MISSING' -Message 'planning sync must declare update_policy.' -Path 'control/product_task_library.yaml'
    }
}
$routeMapNearEndMatch = [regex]::Match($ax9sText, '(?ms)^## 3\. 近端导航提示\s*\r?\n(?<body>.*?)(?=^##\s|\z)')
if ($routeMapNearEndMatch.Success) {
    $routeIds = [System.Collections.Generic.List[string]]::new()
    foreach ($match in [regex]::Matches($routeMapNearEndMatch.Groups['body'].Value, '(?m)^\-\s*`([^`]+)`')) {
        $id = $match.Groups[1].Value
        if (-not $routeIds.Contains($id)) { $routeIds.Add($id) | Out-Null }
    }
    $taskIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($task in $tasks) {
        $taskId = [string](Get-FieldValue -Object $task -Name 'task_id')
        if (-not [string]::IsNullOrWhiteSpace($taskId)) { $taskIds.Add($taskId) | Out-Null }
    }
    foreach ($routeId in $routeIds) {
        if (-not $taskIds.Contains($routeId)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'WARNING' -Code 'ROUTE_MAP_NEAR_END_HINT_LAGGING' -Message "AX9S near-end hint $routeId is not present in control/product_task_library.yaml." -Path 'docs/AX9S_开发执行路由图.md'
        }
    }
}

$result = [pscustomobject]@{
    script = 'check-state-alignment.ps1'
    repoRoot = $root
    ok = (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[check-state-alignment] repo: $root"
    if ($result.ok) {
        Write-Host '[check-state-alignment] PASS'
        foreach ($issue in @($issues | Where-Object severity -eq 'WARNING')) {
            Write-Host ("[{0}] {1} {2}" -f $issue.severity, $issue.code, $issue.message)
        }
    }
    else {
        foreach ($issue in $issues) {
            Write-Host ("[{0}] {1} {2}" -f $issue.severity, $issue.code, $issue.message)
        }
    }
}

if ($EmitJson) { $result | ConvertTo-Json -Depth 100 }
if (-not $result.ok) { exit 1 }
exit 0
