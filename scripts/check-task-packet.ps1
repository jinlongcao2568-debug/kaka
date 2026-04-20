[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string[]]$PlannedTargetPaths,
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
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) { return $Object[$Name] }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

function Normalize-Path {
    param([string]$Path)
    return ($Path -replace '\\', '/').Trim()
}

function Test-PatternMatch {
    param([string]$Path,[string[]]$Patterns)
    $normalized = Normalize-Path $Path
    foreach ($pattern in $Patterns) {
        $wildcard = [System.Management.Automation.WildcardPattern]::new((Normalize-Path $pattern), [System.Management.Automation.WildcardOptions]::IgnoreCase)
        if ($wildcard.IsMatch($normalized)) { return $true }
    }
    return $false
}

function Get-ActualChangedPaths {
    param([string]$Root)
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { return @() }
    try {
        Push-Location $Root
        $porcelain = & git -c core.quotepath=false status --porcelain=v1 --untracked-files=no
        if ($LASTEXITCODE -ne 0 -or -not $porcelain) { return @() }
        $paths = foreach ($line in $porcelain) {
            if (-not [string]::IsNullOrWhiteSpace($line)) { Normalize-Path ($line.Substring(3).Trim()) }
        }
        return @($paths | Where-Object { $_ } | Select-Object -Unique)
    }
    finally {
        Pop-Location -ErrorAction SilentlyContinue
    }
}

function Test-PathScopeCompliance {
    param(
        [string[]]$Paths,
        [string[]]$DeclaredPatterns,
        [string[]]$AllowedPatterns,
        [string[]]$ForbiddenPatterns,
        [string]$IssuePrefix,
        [switch]$RequireDeclaredMatch,
        [ref]$Issues
    )
    foreach ($path in @($Paths | ForEach-Object { Normalize-Path ([string]$_) })) {
        if ([string]::IsNullOrWhiteSpace($path)) { continue }
        if ($RequireDeclaredMatch -and -not (Test-PatternMatch -Path $path -Patterns $DeclaredPatterns)) {
            Add-Issue -Bag $Issues -Severity 'ERROR' -Code ($IssuePrefix + '_PATH_NOT_DECLARED') -Message "$IssuePrefix path $path is outside declared_changed_paths." -Path $path
        }
        if (-not (Test-PatternMatch -Path $path -Patterns $AllowedPatterns)) {
            Add-Issue -Bag $Issues -Severity 'ERROR' -Code ($IssuePrefix + '_PATH_NOT_ALLOWED') -Message "$IssuePrefix path $path is outside allowed_modification_paths." -Path $path
        }
        if (Test-PatternMatch -Path $path -Patterns $ForbiddenPatterns) {
            Add-Issue -Bag $Issues -Severity 'ERROR' -Code ($IssuePrefix + '_PATH_FORBIDDEN') -Message "$IssuePrefix path $path matches forbidden_modification_paths." -Path $path
        }
    }
}

function Remove-GeneratedRuntimeArtifacts {
    param([string[]]$Paths)
    $generatedPatterns = @(
        '**/__pycache__/**',
        '__pycache__/**',
        '*.pyc',
        '.pytest_cache/**'
    )
    return @($Paths | Where-Object { -not (Test-PatternMatch -Path $_ -Patterns $generatedPatterns) })
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$issues = [System.Collections.Generic.List[object]]::new()

$requiredFiles = @(
    'control/current_task.yaml',
    'control/product_task_library.yaml',
    'control/source_blueprint_registry.yaml',
    'control/operator_assignment_roster_defaults.yaml',
    'control/repo_status.md',
    'control/review_gate_matrix.yaml',
    'control/automation_task_packet_rules.yaml',
    'control/owners.yaml'
)
foreach ($rel in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $rel))) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MISSING_ASSET' -Message 'Required task-packet asset is missing.' -Path $rel
    }
}

$currentTask = Load-YamlFile -Path (Join-Path $root 'control/current_task.yaml') -Issues ([ref]$issues)
$productTaskLibrary = Load-YamlFile -Path (Join-Path $root 'control/product_task_library.yaml') -Issues ([ref]$issues)
$sourceBlueprintRegistry = Load-YamlFile -Path (Join-Path $root 'control/source_blueprint_registry.yaml') -Issues ([ref]$issues)
$rosterDefaults = Load-YamlFile -Path (Join-Path $root 'control/operator_assignment_roster_defaults.yaml') -Issues ([ref]$issues)
$reviewGateMatrix = Load-YamlFile -Path (Join-Path $root 'control/review_gate_matrix.yaml') -Issues ([ref]$issues)
$taskRules = Load-YamlFile -Path (Join-Path $root 'control/automation_task_packet_rules.yaml') -Issues ([ref]$issues)

$currentTaskNode = Get-FieldValue -Object $currentTask -Name 'currentTask'
$taskPacket = Get-FieldValue -Object $currentTaskNode -Name 'task_packet'
if (-not $taskPacket) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_MISSING' -Message 'control/current_task.yaml must include currentTask.task_packet.' -Path 'control/current_task.yaml'
}

$sourceBlueprintBatchId = [string](Get-FieldValue -Object $taskPacket -Name 'source_blueprint_batch_id')
$registeredBlueprints = @((Get-FieldValue -Object $sourceBlueprintRegistry -Name 'registered_blueprints'))
$registeredBlueprintIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($entry in $registeredBlueprints) {
    $id = [string](Get-FieldValue -Object $entry -Name 'blueprint_id')
    if (-not [string]::IsNullOrWhiteSpace($id)) { $registeredBlueprintIds.Add($id) | Out-Null }
}
if (-not $registeredBlueprintIds.Contains($sourceBlueprintBatchId)) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNREGISTERED_SOURCE_BLUEPRINT_BATCH' -Message "currentTask.task_packet.source_blueprint_batch_id=$sourceBlueprintBatchId is not registered in control/source_blueprint_registry.yaml." -Path 'control/current_task.yaml'
}

$operatorRosterSourceRef = [string](Get-FieldValue -Object $currentTaskNode -Name 'operator_assignment_roster_source_ref')
$stableRosterRef = [string](Get-FieldValue -Object $rosterDefaults -Name 'source_ref')
if ([string]::IsNullOrWhiteSpace($operatorRosterSourceRef)) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OPERATOR_ROSTER_SOURCE_REF_MISSING' -Message 'control/current_task.yaml must define currentTask.operator_assignment_roster_source_ref.' -Path 'control/current_task.yaml'
}
elseif ($operatorRosterSourceRef -ne $stableRosterRef) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OPERATOR_ROSTER_SOURCE_REF_DRIFT' -Message "currentTask.operator_assignment_roster_source_ref must equal $stableRosterRef." -Path 'control/current_task.yaml'
}

$currentRoster = Get-FieldValue -Object $currentTaskNode -Name 'operator_assignment_roster'
$stableRosters = Get-FieldValue -Object $rosterDefaults -Name 'defaults'
foreach ($stage in @('stage7','stage8','stage9')) {
    $currentStageRoster = Get-FieldValue -Object $currentRoster -Name $stage
    $stableStageRoster = Get-FieldValue -Object $stableRosters -Name $stage
    if (-not $currentStageRoster) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OPERATOR_ROSTER_STAGE_MISSING' -Message "currentTask.operator_assignment_roster.$stage must be present." -Path 'control/current_task.yaml'
        continue
    }
    if (-not $stableStageRoster) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OPERATOR_ROSTER_STABLE_STAGE_MISSING' -Message "control/operator_assignment_roster_defaults.yaml must define defaults.$stage." -Path 'control/operator_assignment_roster_defaults.yaml'
        continue
    }
    $currentJson = $currentStageRoster | ConvertTo-Json -Depth 20 -Compress
    $stableJson = $stableStageRoster | ConvertTo-Json -Depth 20 -Compress
    if ($currentJson -ne $stableJson) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OPERATOR_ROSTER_STAGE_DRIFT' -Message "currentTask.operator_assignment_roster.$stage must stay aligned with control/operator_assignment_roster_defaults.yaml." -Path 'control/current_task.yaml'
    }
}

$declaredPaths = @($taskPacket.declared_changed_paths | ForEach-Object { Normalize-Path ([string]$_) })
$allowedPaths = @($taskPacket.allowed_modification_paths | ForEach-Object { Normalize-Path ([string]$_) })
$forbiddenPaths = @($taskPacket.forbidden_modification_paths | ForEach-Object { Normalize-Path ([string]$_) })
$baselineDirtyPaths = @((Get-FieldValue -Object $taskPacket -Name 'baseline_dirty_paths') | ForEach-Object { Normalize-Path ([string]$_) })
foreach ($path in $declaredPaths) {
    if (-not (Test-PatternMatch -Path $path -Patterns $allowedPaths)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DECLARED_PATH_NOT_ALLOWED' -Message "Declared path $path is outside allowed_modification_paths." -Path 'control/current_task.yaml'
    }
    if (Test-PatternMatch -Path $path -Patterns $forbiddenPaths) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DECLARED_PATH_FORBIDDEN' -Message "Declared path $path matches forbidden_modification_paths." -Path 'control/current_task.yaml'
    }
}
if (@($PlannedTargetPaths).Count -gt 0) {
    Test-PathScopeCompliance -Paths $PlannedTargetPaths -DeclaredPatterns $declaredPaths -AllowedPatterns $allowedPaths -ForbiddenPatterns $forbiddenPaths -IssuePrefix 'PLANNED' -RequireDeclaredMatch -Issues ([ref]$issues)
}
$actualChangedPaths = Get-ActualChangedPaths -Root $root
if (@($actualChangedPaths).Count -gt 0) {
    $actualChangedPaths = Remove-GeneratedRuntimeArtifacts -Paths $actualChangedPaths
    if (@($baselineDirtyPaths).Count -gt 0) {
        $actualChangedPaths = @($actualChangedPaths | Where-Object { $_ -notin $baselineDirtyPaths })
    }
    Test-PathScopeCompliance -Paths $actualChangedPaths -DeclaredPatterns $declaredPaths -AllowedPatterns $allowedPaths -ForbiddenPatterns $forbiddenPaths -IssuePrefix 'ACTUAL' -Issues ([ref]$issues)
}

$repoStatusText = if (Test-Path -LiteralPath (Join-Path $root 'control/repo_status.md')) { Get-Content -Raw -LiteralPath (Join-Path $root 'control/repo_status.md') -Encoding UTF8 } else { '' }
if ($repoStatusText -and -not $repoStatusText.Contains('current_task -> product_task_library -> repo_status')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIQUE_ACTIVE_TASK_SOURCE_DRIFT' -Message 'repo_status must preserve current_task -> product_task_library -> repo_status source priority wording.' -Path 'control/repo_status.md'
}
$currentTaskText = if (Test-Path -LiteralPath (Join-Path $root 'control/current_task.yaml')) { Get-Content -Raw -LiteralPath (Join-Path $root 'control/current_task.yaml') -Encoding UTF8 } else { '' }
if ($currentTaskText -and -not $currentTaskText.Contains('current_task -> product_task_library -> repo_status')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIQUE_ACTIVE_TASK_SOURCE_DRIFT' -Message 'current_task.yaml must preserve the current_task -> product_task_library -> repo_status active-source priority note.' -Path 'control/current_task.yaml'
}

$result = [pscustomobject]@{
    script = 'check-task-packet.ps1'
    repoRoot = $root
    ok = (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[check-task-packet] repo: $root"
    if ($result.ok) {
        Write-Host '[check-task-packet] PASS'
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
