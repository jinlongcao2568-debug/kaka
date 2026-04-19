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

function Add-Issue {
    param(
        [ref]$Bag,
        [string]$Severity,
        [string]$Code,
        [string]$Message,
        [string]$Path = ''
    )

    $Bag.Value.Add([pscustomobject]@{
        severity = $Severity
        code     = $Code
        path     = $Path
        message  = $Message
    }) | Out-Null
}

function Load-Yaml {
    param(
        [string]$Path,
        [ref]$Issues
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_FILE' -Message 'Required YAML file is missing.' -Path $Path
        return $null
    }

    try {
        $convertYaml = Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue
        if ($convertYaml) {
            $parsed = (Get-Content -LiteralPath $Path -Raw -Encoding UTF8) | ConvertFrom-Yaml
        }
        else {
            $yq = Get-Command yq -ErrorAction SilentlyContinue
            if ($yq) {
                $json = & $yq.Source -o=json '.' $Path
                if ($LASTEXITCODE -ne 0) {
                    throw "yq failed to parse $Path"
                }
                $parsed = $json | ConvertFrom-Json -Depth 100
            }
            else {
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
                $parsed = $json | ConvertFrom-Json -Depth 100
            }
        }
        return ($parsed | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100)
    }
    catch {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'YAML_PARSE_FAILED' -Message $_.Exception.Message -Path $Path
        return $null
    }
}

function Normalize-Path {
    param([string]$Path)
    return ($Path -replace '\\', '/').Trim()
}

function Test-IgnoredGeneratedPath {
    param([string]$Path)

    $normalized = Normalize-Path $Path
    if ($normalized -match '(^|/)\.pytest_cache(/|$)') {
        return $true
    }
    if ($normalized -match '(^|/)__pycache__/.*\.(pyc|pyo)$') {
        return $true
    }
    return $false
}

function Test-PatternMatch {
    param(
        [string]$Path,
        [string[]]$Patterns
    )

    foreach ($pattern in $Patterns) {
        $wildcard = [System.Management.Automation.WildcardPattern]::new((Normalize-Path $pattern), [System.Management.Automation.WildcardOptions]::IgnoreCase)
        if ($wildcard.IsMatch((Normalize-Path $Path))) {
            return $true
        }
    }

    return $false
}

function Get-FieldValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) { return $null }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

function Get-ActualChangedPaths {
    param([string]$Root)

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        return @()
    }

    try {
        Push-Location $Root
        & git rev-parse --verify HEAD *> $null
        if ($LASTEXITCODE -ne 0) {
            return @()
        }

        # Force raw UTF-8-ish path emission so PowerShell does not have to consume git's
        # quoted octal escapes for non-ASCII filenames.
        $porcelain = & git -c core.quotepath=false status --porcelain=v1 --untracked-files=no
        if ($LASTEXITCODE -ne 0 -or -not $porcelain) {
            return @()
        }

        $paths = @()
        foreach ($line in $porcelain) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            $trimmed = $line.Substring(3).Trim()
            if ($trimmed) { $paths += (Normalize-Path $trimmed) }
        }
        return $paths | Select-Object -Unique
    }
    catch {
        return @()
    }
    finally {
        Pop-Location -ErrorAction SilentlyContinue
    }
}

function Get-ChangeClassMap {
    param([object]$ReviewMatrix)

    $map = @{}
    foreach ($class in @($ReviewMatrix.change_classes)) {
        $map[$class.id] = [int]$class.rank
    }
    return $map
}

function Classify-Paths {
    param(
        [string[]]$Paths,
        [object]$ReviewMatrix
    )

    $classRanks = Get-ChangeClassMap -ReviewMatrix $ReviewMatrix
    $domainMatches = [System.Collections.Generic.List[object]]::new()
    $requiredOwners = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $requiredDomains = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $highestClass = 'LOW_RISK_DIRECT'
    $highestRank = if ($classRanks.ContainsKey($highestClass)) { $classRanks[$highestClass] } else { 0 }

    foreach ($path in $Paths) {
        foreach ($domain in @($ReviewMatrix.domains)) {
            if (Test-PatternMatch -Path $path -Patterns @($domain.file_globs)) {
                $rank = $classRanks[$domain.change_class]
                if ($rank -gt $highestRank) {
                    $highestRank = $rank
                    $highestClass = $domain.change_class
                }

                foreach ($ownerRole in @($domain.required_owner_reviews)) {
                    if (-not [string]::IsNullOrWhiteSpace([string]$ownerRole)) {
                        $requiredOwners.Add([string]$ownerRole) | Out-Null
                    }
                }

                if ($rank -ge 2) {
                    $requiredDomains.Add([string]$domain.domain_id) | Out-Null
                }

                $domainMatches.Add([pscustomobject]@{
                    path         = $path
                    domain_id    = $domain.domain_id
                    change_class = $domain.change_class
                    rank         = $rank
                }) | Out-Null
            }
        }
    }

    return [pscustomobject]@{
        highestClass   = $highestClass
        highestRank    = $highestRank
        domainMatches  = $domainMatches
        requiredOwners = @($requiredOwners)
        requiredDomains = @($requiredDomains)
    }
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$issues = [System.Collections.Generic.List[object]]::new()

$requiredFiles = @(
    'docs/自动化开发动作门禁表.md',
    'control/automation_action_matrix.yaml',
    'control/automation_stop_conditions.yaml',
    'control/automation_task_packet_rules.yaml',
    'control/review_gate_matrix.yaml',
    'control/current_task.yaml',
    'control/owners.yaml'
)

foreach ($rel in $requiredFiles) {
    $path = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $path)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MISSING_ASSET' -Message 'Required automation readiness asset is missing.' -Path $rel
    }
}

$actionMatrix = Load-Yaml -Path (Join-Path $root 'control/automation_action_matrix.yaml') -Issues ([ref]$issues)
$stopConditions = Load-Yaml -Path (Join-Path $root 'control/automation_stop_conditions.yaml') -Issues ([ref]$issues)
$taskRules = Load-Yaml -Path (Join-Path $root 'control/automation_task_packet_rules.yaml') -Issues ([ref]$issues)
$reviewGateMatrix = Load-Yaml -Path (Join-Path $root 'control/review_gate_matrix.yaml') -Issues ([ref]$issues)
$currentTask = Load-Yaml -Path (Join-Path $root 'control/current_task.yaml') -Issues ([ref]$issues)
$owners = Load-Yaml -Path (Join-Path $root 'control/owners.yaml') -Issues ([ref]$issues)

if ($actionMatrix) {
    if (-not (Get-FieldValue -Object $actionMatrix -Name 'action_classes') -or -not (Get-FieldValue -Object $actionMatrix -Name 'actions')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ACTION_MATRIX_INCOMPLETE' -Message 'automation_action_matrix.yaml must define action_classes and actions.' -Path 'control/automation_action_matrix.yaml'
    }
    if ((Get-FieldValue -Object $actionMatrix -Name 'review_gate_matrix') -ne 'control/review_gate_matrix.yaml') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ACTION_MATRIX_REVIEW_GATE_REF_MISSING' -Message 'automation_action_matrix.yaml must reference control/review_gate_matrix.yaml.' -Path 'control/automation_action_matrix.yaml'
    }
}

if ($stopConditions) {
    if (-not (Get-FieldValue -Object $stopConditions -Name 'script_failures') -or -not (Get-FieldValue -Object $stopConditions -Name 'consecutive_failure_rule')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STOP_CONDITIONS_INCOMPLETE' -Message 'automation_stop_conditions.yaml must define script_failures and consecutive_failure_rule.' -Path 'control/automation_stop_conditions.yaml'
    }
    $reviewLinkage = Get-FieldValue -Object $stopConditions -Name 'review_gate_linkage'
    if (-not $reviewLinkage) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STOP_REVIEW_LINKAGE_MISSING' -Message 'automation_stop_conditions.yaml must define review_gate_linkage.' -Path 'control/automation_stop_conditions.yaml'
    }
}

if ($taskRules) {
    foreach ($key in @('task_packet_source','required_fields','field_rules','requires_task_packet_for','fail_conditions','classification_source')) {
        if (-not (Get-FieldValue -Object $taskRules -Name $key)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_RULES_INCOMPLETE' -Message "automation_task_packet_rules.yaml missing $key." -Path 'control/automation_task_packet_rules.yaml'
        }
    }
}

$classRanks = @{}
$requiredDomainIds = @(
    'shared_runtime_core',
    'governance_release_core',
    'provider_vendor_source_policy_core',
    'stage8_stage9_high_risk_execution',
    'automation_control_core'
)
if ($reviewGateMatrix) {
    $classRanks = Get-ChangeClassMap -ReviewMatrix $reviewGateMatrix
    foreach ($requiredClass in @('LOW_RISK_DIRECT','DRAFT_WITH_REVIEW','MANDATORY_HUMAN_REVIEW','STOP_AND_ESCALATE')) {
        if (-not $classRanks.ContainsKey($requiredClass)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REVIEW_GATE_CLASS_MISSING' -Message "review_gate_matrix.yaml missing $requiredClass." -Path 'control/review_gate_matrix.yaml'
        }
    }

    $domainIds = @(@($reviewGateMatrix.domains) | ForEach-Object { $_.domain_id })
    foreach ($domainId in $requiredDomainIds) {
        if ($domainIds -notcontains $domainId) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REVIEW_GATE_DOMAIN_MISSING' -Message "review_gate_matrix.yaml missing required domain $domainId." -Path 'control/review_gate_matrix.yaml'
        }
    }

    $requiredPathClassifications = @(
        [pscustomobject]@{
            path = 'contracts/sales/vendor_registry_catalog.json'
            expectedClass = 'MANDATORY_HUMAN_REVIEW'
            requiredDomain = 'provider_vendor_source_policy_core'
            requiredOwners = @('architecture_owner', 'governance_owner')
        }
    )

    foreach ($binding in $requiredPathClassifications) {
        $classification = Classify-Paths -Paths @($binding.path) -ReviewMatrix $reviewGateMatrix
        if ($classification.highestClass -ne $binding.expectedClass) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REVIEW_GATE_PATH_CLASS_MISMATCH' -Message "$($binding.path) must classify as $($binding.expectedClass)." -Path 'control/review_gate_matrix.yaml'
        }
        if (@($classification.requiredDomains) -notcontains $binding.requiredDomain) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REVIEW_GATE_PATH_DOMAIN_MISSING' -Message "$($binding.path) must map to $($binding.requiredDomain)." -Path 'control/review_gate_matrix.yaml'
        }
        foreach ($ownerRole in @($binding.requiredOwners)) {
            if (@($classification.requiredOwners) -notcontains $ownerRole) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REVIEW_GATE_PATH_OWNER_MISSING' -Message "$($binding.path) must require $ownerRole review." -Path 'control/review_gate_matrix.yaml'
            }
        }
    }
}

$taskPacket = $null
if ($currentTask) {
    $currentTaskNode = Get-FieldValue -Object $currentTask -Name 'currentTask'
    $taskPacket = Get-FieldValue -Object $currentTaskNode -Name 'task_packet'
    if (-not $taskPacket) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_MISSING' -Message 'control/current_task.yaml must include currentTask.task_packet.' -Path 'control/current_task.yaml'
    }
}

if ($taskPacket -and $taskRules) {
    foreach ($field in @($taskRules.required_fields)) {
        $value = Get-FieldValue -Object $taskPacket -Name ([string]$field)
        $fieldPath = "control/current_task.yaml#currentTask.task_packet.$field"
        switch ([string]$field) {
            'human_review_required' {
                if ($null -eq $value) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_FIELD_MISSING' -Message 'human_review_required is required.' -Path $fieldPath
                }
            }
            'impacted_assets' {
                if ($null -eq $value -or @($value.PSObject.Properties).Count -eq 0) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_FIELD_MISSING' -Message 'impacted_assets must be a non-empty object.' -Path $fieldPath
                }
            }
            default {
                if ($null -eq $value) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_FIELD_MISSING' -Message "$field is required." -Path $fieldPath
                }
                elseif ($value -is [string] -and [string]::IsNullOrWhiteSpace($value)) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_FIELD_EMPTY' -Message "$field cannot be empty." -Path $fieldPath
                }
                elseif ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string]) -and @($value).Count -eq 0) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TASK_PACKET_FIELD_EMPTY' -Message "$field cannot be empty." -Path $fieldPath
                }
            }
        }
    }
}

$detectedClassification = $null
if ($taskPacket -and $reviewGateMatrix -and @($classRanks.Keys).Count -gt 0) {
    $declaredPaths = @($taskPacket.declared_changed_paths | ForEach-Object { Normalize-Path ([string]$_) })
    if (@($declaredPaths).Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DECLARED_PATHS_MISSING' -Message 'declared_changed_paths must list the touched files for classification.' -Path 'control/current_task.yaml#currentTask.task_packet.declared_changed_paths'
    }

    foreach ($path in $declaredPaths) {
        if (-not (Test-PatternMatch -Path $path -Patterns @($taskPacket.allowed_modification_paths))) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DECLARED_PATH_NOT_ALLOWED' -Message "Declared path $path is outside allowed_modification_paths." -Path 'control/current_task.yaml'
        }
        if (Test-PatternMatch -Path $path -Patterns @($taskPacket.forbidden_modification_paths)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DECLARED_PATH_FORBIDDEN' -Message "Declared path $path matches forbidden_modification_paths." -Path 'control/current_task.yaml'
        }
    }

    $detectedClassification = Classify-Paths -Paths $declaredPaths -ReviewMatrix $reviewGateMatrix
    $baselineDirtyPathValues = Get-FieldValue -Object $taskPacket -Name 'baseline_dirty_paths'
    if ($null -eq $baselineDirtyPathValues) {
        $baselineDirtyPaths = @()
    }
    else {
        $baselineDirtyPaths = @($baselineDirtyPathValues | ForEach-Object { Normalize-Path ([string]$_) })
    }
    $declaredClass = [string]$taskPacket.change_class
    if (-not $classRanks.ContainsKey($declaredClass)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DECLARED_CHANGE_CLASS_INVALID' -Message "Declared change_class $declaredClass is not defined in review_gate_matrix.yaml." -Path 'control/current_task.yaml'
    }
    elseif ($classRanks[$declaredClass] -lt $detectedClassification.highestRank) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DECLARED_CHANGE_CLASS_TOO_LOW' -Message "Declared change_class $declaredClass is lower than required $($detectedClassification.highestClass)." -Path 'control/current_task.yaml'
    }

    if ($detectedClassification.highestRank -ge 1 -and -not [bool]$taskPacket.human_review_required) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'HUMAN_REVIEW_REQUIRED' -Message "Detected change class $($detectedClassification.highestClass) requires human_review_required=true." -Path 'control/current_task.yaml'
    }

    $ownerRoles = @($taskPacket.owner_reviews_required | ForEach-Object { [string]$_ })
    foreach ($requiredOwner in @($detectedClassification.requiredOwners)) {
        if ($ownerRoles -notcontains $requiredOwner) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OWNER_REVIEW_MISSING' -Message "Required owner review $requiredOwner is missing from currentTask.task_packet.owner_reviews_required." -Path 'control/current_task.yaml'
        }
    }

    $declaredDomains = @($taskPacket.change_domains | ForEach-Object { [string]$_ })
    foreach ($requiredDomain in @($detectedClassification.requiredDomains)) {
        if ($declaredDomains -notcontains $requiredDomain) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CHANGE_DOMAIN_MISSING' -Message "Detected high-risk domain $requiredDomain must be declared in currentTask.task_packet.change_domains." -Path 'control/current_task.yaml'
        }
    }

    $reviewEvidence = Get-FieldValue -Object $taskPacket -Name 'review_evidence'
    if ($detectedClassification.highestRank -ge 1) {
        if (-not $reviewEvidence) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REVIEW_EVIDENCE_MISSING' -Message 'review_evidence must be present for non-low-risk batches.' -Path 'control/current_task.yaml'
        }
        elseif (-not [bool](Get-FieldValue -Object $reviewEvidence -Name 'declared')) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REVIEW_EVIDENCE_DECLARATION_MISSING' -Message 'review_evidence.declared must be true for non-low-risk batches.' -Path 'control/current_task.yaml'
        }
    }

    if ($detectedClassification.highestClass -eq 'STOP_AND_ESCALATE') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STOP_AND_ESCALATE_TRIGGERED' -Message 'Detected STOP_AND_ESCALATE domain in declared paths; automation must stop and hand off to human owners.' -Path 'control/current_task.yaml'
    }

    $actualChangedPaths = Get-ActualChangedPaths -Root $root
    if (@($actualChangedPaths).Count -gt 0) {
        foreach ($actualPath in $actualChangedPaths) {
            $normalizedActualPath = Normalize-Path $actualPath
            if ($baselineDirtyPaths -contains $normalizedActualPath) {
                continue
            }
            if (Test-IgnoredGeneratedPath -Path $normalizedActualPath) {
                continue
            }
            if (-not (Test-PatternMatch -Path $actualPath -Patterns @($taskPacket.allowed_modification_paths))) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ACTUAL_PATH_NOT_ALLOWED' -Message "Actual changed path $actualPath is outside allowed_modification_paths." -Path $actualPath
            }
        }
    }
}

if ($owners -and $taskPacket) {
    $ownerRegistry = Get-FieldValue -Object $owners -Name 'owners'
    foreach ($ownerRole in @($taskPacket.owner_reviews_required)) {
        if (-not (Get-FieldValue -Object $ownerRegistry -Name ([string]$ownerRole))) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OWNER_ROLE_UNKNOWN' -Message "Owner role $ownerRole is not defined in control/owners.yaml." -Path 'control/owners.yaml'
        }
    }
}

$result = [pscustomobject]@{
    script = 'check-automation-readiness.ps1'
    repoRoot = $root
    ok = (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)
    detected = if ($detectedClassification) {
        [pscustomobject]@{
            highestClass = $detectedClassification.highestClass
            domains      = @($detectedClassification.requiredDomains)
            requiredOwners = @($detectedClassification.requiredOwners)
        }
    } else {
        $null
    }
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[check-automation-readiness] repo: $root"
    if ($result.ok) {
        if ($result.detected) {
            Write-Host ("[check-automation-readiness] detected_change_class={0}" -f $result.detected.highestClass)
        }
        Write-Host '[check-automation-readiness] PASS'
    } else {
        foreach ($issue in $issues) {
            Write-Host ("[{0}] {1} {2}" -f $issue.severity, $issue.code, $issue.message)
        }
    }
}

if ($EmitJson) { $result | ConvertTo-Json -Depth 100 }
if (-not $result.ok) { exit 1 }
exit 0
