[CmdletBinding()]
param(
    [string]$RepoRoot,
    [switch]$Quiet,
    [switch]$EmitJson
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
        message  = $Message
        path     = $Path
    }) | Out-Null
}

function Test-JsonFile {
    param(
        [string]$Path,
        [ref]$Issues,
        [string[]]$RequiredTopLevelKeys = @()
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_FILE' -Message 'Required file is missing.' -Path $Path
        return $null
    }

    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        $obj = $raw | ConvertFrom-Json -Depth 100
    }
    catch {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'INVALID_JSON' -Message $_.Exception.Message -Path $Path
        return $null
    }

    foreach ($key in $RequiredTopLevelKeys) {
        if (-not ($obj.PSObject.Properties.Name -contains $key)) {
            Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_KEY' -Message "Missing top-level key: $key" -Path $Path
        }
    }

    return $obj
}

function Read-TextFile {
    param(
        [string]$Path,
        [ref]$Issues
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_FILE' -Message 'Required file is missing.' -Path $Path
        return ''
    }

    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

function Set-Equals {
    param(
        [string[]]$Expected,
        [string[]]$Actual
    )

    $expectedList = @($Expected)
    $actualList = @($Actual)

    if ($expectedList.Count -ne $actualList.Count) { return $false }
    return (@(Compare-Object -ReferenceObject $expectedList -DifferenceObject $actualList).Count -eq 0)
}

function Get-QuotedStringList {
    param(
        [string]$Text,
        [string]$Pattern
    )

    $match = [regex]::Match(
        $Text,
        $Pattern,
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )
    if (-not $match.Success) { return @() }

    $body = $match.Groups[1].Value
    $matches = [regex]::Matches($body, "'([^']+)'|""([^""]+)""")
    return @($matches | ForEach-Object {
        if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value }
    })
}

function Invoke-SemanticAlignment {
    param(
        [string]$RepoRoot,
        [ref]$Issues
    )

    $scriptPath = Join-Path (Split-Path -Parent $PSCommandPath) 'check-state-alignment.ps1'
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File $scriptPath -RepoRoot $RepoRoot -EmitJson *> $tmp
        $raw = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
        $jsonStart = $raw.IndexOf('{')
        if ($jsonStart -lt 0) {
            Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'STATE_ALIGNMENT_NO_JSON' -Message 'check-state-alignment.ps1 did not emit JSON.' -Path $scriptPath
            return
        }

        $parsed = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 100
        foreach ($issue in @($parsed.issues)) {
            $Issues.Value.Add($issue) | Out-Null
        }
    }
    catch {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'STATE_ALIGNMENT_FAILED' -Message $_.Exception.Message -Path $scriptPath
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$issues = [System.Collections.Generic.List[object]]::new()

$requiredDirs = @(
    'contracts/schemas',
    'contracts/enums',
    'contracts/rules',
    'contracts/gates',
    'contracts/testing',
    'contracts/governance',
    'contracts/release'
)

foreach ($dir in $requiredDirs) {
    $full = Join-Path $root $dir
    if (-not (Test-Path -LiteralPath $full)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MISSING_DIR' -Message 'Required directory is missing.' -Path $full
    }
}

$schemaCatalog = Test-JsonFile -Path (Join-Path $root 'contracts/schemas/schema_catalog.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','schemas')
$enumCatalog   = Test-JsonFile -Path (Join-Path $root 'contracts/enums/enum_catalog.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','enums')
$ruleCatalog   = Test-JsonFile -Path (Join-Path $root 'contracts/rules/rule_catalog.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','rules')
$ruleBasisCatalog = Test-JsonFile -Path (Join-Path $root 'contracts/rules/rule_basis_catalog.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','basis')
$gatePolicies  = Test-JsonFile -Path (Join-Path $root 'contracts/gates/gate_policies.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','gate_objects','upgrade_matrix','degrade_matrix')
$testingIndex  = Test-JsonFile -Path (Join-Path $root 'contracts/testing/regression_manifest.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('registry_id','version','suites')
$sourceRegistry = Test-JsonFile -Path (Join-Path $root 'contracts/governance/source_registry.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','entries')
$routePolicyCatalog = Test-JsonFile -Path (Join-Path $root 'contracts/governance/route_policy_catalog.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','policies')
$writebackImpactPolicy = Test-JsonFile -Path (Join-Path $root 'contracts/governance/writeback_impact_policy.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','current_state','runtime_executor_enabled','formal_targets')
$touchRecordSchema = Test-JsonFile -Path (Join-Path $root 'contracts/schemas/touch_record.schema.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('properties','required')
$opportunityOutcomeSchema = Test-JsonFile -Path (Join-Path $root 'contracts/schemas/opportunity_outcome_event.schema.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('properties','required')
$executionContextSchema = Test-JsonFile -Path (Join-Path $root 'contracts/schemas/execution_context.schema.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('properties','required')
$publicChainSchema = Test-JsonFile -Path (Join-Path $root 'contracts/schemas/public_chain.schema.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('properties','required')
$evidenceGateSchema = Test-JsonFile -Path (Join-Path $root 'contracts/schemas/evidence_gate_decision.schema.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('properties','required')
$stageHandoffCatalog = Test-JsonFile -Path (Join-Path $root 'handoff/stage_handoff_catalog.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('catalog_id','version','handoffs')
$h01Contract = Test-JsonFile -Path (Join-Path $root 'handoff/stage1_to_stage2/contract.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('producer_objects','required_payload_fields')
$h01Example = Test-JsonFile -Path (Join-Path $root 'handoff/stage1_to_stage2/example.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('handoff_id','example_id','payload')
$h08Contract = Test-JsonFile -Path (Join-Path $root 'handoff/stage8_to_stage9/contract.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('producer_objects','required_payload_fields')
$h02Contract = Test-JsonFile -Path (Join-Path $root 'handoff/stage2_to_stage3/contract.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('producer_objects','required_payload_fields')
$integrationMatrix = Test-JsonFile -Path (Join-Path $root 'handoff/integration_matrix.json') -Issues ([ref]$issues) -RequiredTopLevelKeys @('rows')
$stage1ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage1_tasking/service.py') -Issues ([ref]$issues)
$stage2ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage2_ingestion/service.py') -Issues ([ref]$issues)
$stage3ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage3_parsing/service.py') -Issues ([ref]$issues)
$runtimeInventoryText = Read-TextFile -Path (Join-Path $root 'control/runtime_inventory.yaml') -Issues ([ref]$issues)
$stage8ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage8_outreach/service.py') -Issues ([ref]$issues)
$stage9ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage9_delivery/service.py') -Issues ([ref]$issues)
$stage9ImpactExecutorText = Read-TextFile -Path (Join-Path $root 'src/stage9_delivery/impact_executor.py') -Issues ([ref]$issues)
$policyExecutorText = Read-TextFile -Path (Join-Path $root 'src/shared/policy_executor.py') -Issues ([ref]$issues)

if ($schemaCatalog -and $schemaCatalog.schemas) {
    foreach ($schema in $schemaCatalog.schemas) {
        foreach ($key in @('object','stage','layer','required','source_refs','upstream_dependencies','downstream_consumers','enum_refs','hard_constraints')) {
            if (-not ($schema.PSObject.Properties.Name -contains $key)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SCHEMA_INCOMPLETE' -Message "Schema entry missing key: $key" -Path 'contracts/schemas/schema_catalog.json'
            }
        }
    }
}

if ($enumCatalog -and $enumCatalog.enums) {
    foreach ($entry in $enumCatalog.enums) {
        foreach ($key in @('enum_name','values')) {
            if (-not ($entry.PSObject.Properties.Name -contains $key)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ENUM_INCOMPLETE' -Message "Enum entry missing key: $key" -Path 'contracts/enums/enum_catalog.json'
            }
        }
    }

    $saleGateEnum = @($enumCatalog.enums | Where-Object enum_name -eq 'sale_gate_status' | Select-Object -First 1)
    if ($saleGateEnum.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SALE_GATE_ENUM_MISSING' -Message 'sale_gate_status enum must exist.' -Path 'contracts/enums/enum_catalog.json'
    }
    else {
        $actualSaleGateValues = @($saleGateEnum[0].values | ForEach-Object { $_.value })
        $expectedSaleGateValues = @('OPEN', 'REVIEW', 'HOLD', 'BLOCK')
        if (-not (Set-Equals -Expected $expectedSaleGateValues -Actual $actualSaleGateValues)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SALE_GATE_ENUM_DRIFT' -Message "sale_gate_status enum must equal OPEN/REVIEW/HOLD/BLOCK. Actual: $($actualSaleGateValues -join '/')" -Path 'contracts/enums/enum_catalog.json'
        }
    }
}

$allowedRuleBasisStatuses = @('VERIFIED', 'INTERNAL_ONLY', 'BASIS_MISSING', 'HEURISTIC_ONLY', 'DEPRECATED')
$resultTypeRank = @{
    OBSERVATION = 1
    REVIEW_REQUEST = 2
    CLUE = 3
    AUTO_HIT = 4
}
$ruleBasisIndex = @{}
if ($ruleBasisCatalog -and $ruleBasisCatalog.basis) {
    foreach ($basis in @($ruleBasisCatalog.basis)) {
        foreach ($key in @('basis_id','basis_type','basis_name','article_refs','official_url','applies_to','does_not_apply_to','required_evidence','result_ceiling','basis_status')) {
            if (-not ($basis.PSObject.Properties.Name -contains $key)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULE_BASIS_INCOMPLETE' -Message "Rule basis entry missing key: $key" -Path 'contracts/rules/rule_basis_catalog.json'
            }
        }
        if ($basis.PSObject.Properties.Name -contains 'basis_id') {
            $ruleBasisIndex[[string]$basis.basis_id] = $basis
        }
        if (($basis.PSObject.Properties.Name -contains 'basis_status') -and ($allowedRuleBasisStatuses -notcontains [string]$basis.basis_status)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULE_BASIS_STATUS_INVALID' -Message "Rule basis has invalid status: $($basis.basis_id) -> $($basis.basis_status)" -Path 'contracts/rules/rule_basis_catalog.json'
        }
    }
}

if ($ruleCatalog -and $ruleCatalog.rules) {
    foreach ($rule in $ruleCatalog.rules) {
        foreach ($key in @('rule_code','default_result','minimum_external_use_grade','public_capability_tier','capability_id')) {
            if (-not ($rule.PSObject.Properties.Name -contains $key)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULE_INCOMPLETE' -Message "Rule entry missing key: $key" -Path 'contracts/rules/rule_catalog.json'
            }
        }
        if ($rule.PSObject.Properties.Name -contains 'stage' -and [int]$rule.stage -eq 5) {
            foreach ($key in @('basis_refs','basis_verification_state','applicability_scope','result_ceiling','customer_visible_allowed','no_legal_conclusion','basis_gate_policy')) {
                if (-not ($rule.PSObject.Properties.Name -contains $key)) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE5_RULE_BASIS_FIELD_MISSING' -Message "Stage5 rule $($rule.rule_code) missing basis field: $key" -Path 'contracts/rules/rule_catalog.json'
                }
            }
            if ($rule.PSObject.Properties.Name -contains 'basis_verification_state') {
                $basisState = [string]$rule.basis_verification_state
                if ($allowedRuleBasisStatuses -notcontains $basisState) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE5_RULE_BASIS_STATE_INVALID' -Message "Stage5 rule $($rule.rule_code) has invalid basis state: $basisState" -Path 'contracts/rules/rule_catalog.json'
                }
            }
            else {
                $basisState = ''
            }
            if ($rule.PSObject.Properties.Name -contains 'basis_refs') {
                $basisRefs = @($rule.basis_refs | ForEach-Object { [string]$_ } | Where-Object { $_ })
                if ($basisRefs.Count -eq 0) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE5_RULE_BASIS_REFS_EMPTY' -Message "Stage5 rule $($rule.rule_code) must declare basis_refs." -Path 'contracts/rules/rule_catalog.json'
                }
                foreach ($basisRef in $basisRefs) {
                    if (-not $ruleBasisIndex.ContainsKey($basisRef)) {
                        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE5_RULE_BASIS_REF_MISSING' -Message "Stage5 rule $($rule.rule_code) references missing basis: $basisRef" -Path 'contracts/rules/rule_catalog.json'
                    }
                    elseif ($basisState -eq 'VERIFIED' -and [string]$ruleBasisIndex[$basisRef].basis_status -ne 'VERIFIED') {
                        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE5_RULE_VERIFIED_BASIS_REF_NOT_VERIFIED' -Message "Stage5 rule $($rule.rule_code) is VERIFIED but basis $basisRef is $($ruleBasisIndex[$basisRef].basis_status)." -Path 'contracts/rules/rule_catalog.json'
                    }
                }
            }
            if (($rule.PSObject.Properties.Name -contains 'customer_visible_allowed') -and [bool]$rule.customer_visible_allowed) {
                if ($basisState -ne 'VERIFIED') {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE5_CUSTOMER_VISIBLE_BASIS_NOT_VERIFIED' -Message "Customer-visible Stage5 rule $($rule.rule_code) must have VERIFIED basis." -Path 'contracts/rules/rule_catalog.json'
                }
                $defaultResult = [string]$rule.default_result
                $resultCeiling = [string]$rule.result_ceiling
                if ($resultTypeRank.ContainsKey($defaultResult) -and $resultTypeRank.ContainsKey($resultCeiling)) {
                    if ([int]$resultTypeRank[$resultCeiling] -gt [int]$resultTypeRank[$defaultResult]) {
                        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE5_RESULT_CEILING_EXCEEDS_DEFAULT' -Message "Stage5 rule $($rule.rule_code) result_ceiling $resultCeiling exceeds default_result $defaultResult." -Path 'contracts/rules/rule_catalog.json'
                    }
                }
            }
        }
    }
}

if ($gatePolicies -and $gatePolicies.gate_objects) {
    foreach ($gate in $gatePolicies.gate_objects) {
        foreach ($key in @('gate','status_enum')) {
            if (-not ($gate.PSObject.Properties.Name -contains $key)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'GATE_INCOMPLETE' -Message "Gate entry missing key: $key" -Path 'contracts/gates/gate_policies.json'
            }
        }
    }
}

if ($testingIndex -and $testingIndex.suites) {
    foreach ($suite in $testingIndex.suites) {
        foreach ($key in @('suite_id','triggers')) {
            if (-not ($suite.PSObject.Properties.Name -contains $key)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REGRESSION_INCOMPLETE' -Message "Regression suite missing key: $key" -Path 'contracts/testing/regression_manifest.json'
            }
        }
    }
}

$expectedH08Fields = @(
    'opportunity_id',
    'touch_record_id',
    'response_status',
    'saleability_status',
    'crm_owner_state'
)
$expectedH01Fields = @(
    'source_registry_id',
    'route_policy_id',
    'default_route',
    'fallback_route'
)
$expectedH02Fields = @(
    'fixation_bundle_id',
    'origin_carrier_type',
    'first_seen_at',
    'last_retrieved_at',
    'clock_conflict_state'
)
$expectedStage2CriticalObjects = @('public_chain', 'clock_chain_profile', 'notice_version_chain', 'fixation_bundle')
$expectedStage9CriticalObjects = @('saleable_opportunity', 'touch_record')
$expectedStage9PolicySequence = @(
    'payment_exception',
    'delivery_exception',
    'outcome_taxonomy',
    'governance_taxonomy'
)

if ($h08Contract) {
    $actualH08Fields = @($h08Contract.required_payload_fields)
    foreach ($fieldName in $expectedH08Fields) {
        if ($actualH08Fields -notcontains $fieldName) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H08_REQUIRED_PAYLOAD_DRIFT' -Message "H-08 required payload fields must include: $fieldName" -Path 'handoff/stage8_to_stage9/contract.json'
        }
    }
}

if ($sourceRegistry) {
    if (@($sourceRegistry.entries).Count -lt 1) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SOURCE_REGISTRY_EMPTY' -Message 'source_registry.json must declare at least one machine-readable source entry.' -Path 'contracts/governance/source_registry.json'
    }
}
if ($routePolicyCatalog) {
    if (@($routePolicyCatalog.policies).Count -lt 1) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ROUTE_POLICY_EMPTY' -Message 'route_policy_catalog.json must declare at least one route policy.' -Path 'contracts/governance/route_policy_catalog.json'
    }
    foreach ($policy in @($routePolicyCatalog.policies)) {
        foreach ($fieldName in $expectedH01Fields) {
            if (@($policy.required_h01_fields) -notcontains $fieldName) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ROUTE_POLICY_H01_REQUIRED_DRIFT' -Message "route_policy_catalog required_h01_fields must include: $fieldName" -Path 'contracts/governance/route_policy_catalog.json'
            }
        }
    }
}
if ($writebackImpactPolicy) {
    if ($writebackImpactPolicy.current_state -ne 'INTERNAL_V0_ACTIVE' -or -not [bool]$writebackImpactPolicy.runtime_executor_enabled) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_IMPACT_ACTIVE_DRIFT' -Message 'writeback impact policy must be INTERNAL_V0_ACTIVE with runtime_executor_enabled=true in this batch.' -Path 'contracts/governance/writeback_impact_policy.json'
    }
}

if ($h01Contract) {
    $actualH01Fields = @($h01Contract.required_payload_fields)
    foreach ($fieldName in $expectedH01Fields) {
        if ($actualH01Fields -notcontains $fieldName) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_REQUIRED_PAYLOAD_DRIFT' -Message "H-01 required payload fields must include: $fieldName" -Path 'handoff/stage1_to_stage2/contract.json'
        }
        if (@($h01Contract.consumer_runtime_required_fields) -notcontains $fieldName) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_RUNTIME_REQUIRED_DRIFT' -Message "H-01 consumer runtime fields must include: $fieldName" -Path 'handoff/stage1_to_stage2/contract.json'
        }
    }
}

if ($stageHandoffCatalog) {
    $h01CatalogEntry = @($stageHandoffCatalog.handoffs | Where-Object handoff_id -eq 'H-01-STAGE1-TO-STAGE2' | Select-Object -First 1)
    if ($h01CatalogEntry.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_CATALOG_ENTRY_MISSING' -Message 'stage_handoff_catalog must contain H-01-STAGE1-TO-STAGE2.' -Path 'handoff/stage_handoff_catalog.json'
    }
    else {
        foreach ($fieldName in $expectedH01Fields) {
            if (@($h01CatalogEntry[0].required_payload_fields) -notcontains $fieldName) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_CATALOG_REQUIRED_DRIFT' -Message "H-01 catalog required payload fields must include: $fieldName" -Path 'handoff/stage_handoff_catalog.json'
            }
        }
    }
}

if ($h01Example) {
    foreach ($fieldName in $expectedH01Fields) {
        if (-not ($h01Example.payload.PSObject.Properties.Name -contains $fieldName)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_EXAMPLE_REQUIRED_DRIFT' -Message "H-01 example payload must include: $fieldName" -Path 'handoff/stage1_to_stage2/example.json'
        }
    }
}

if ($h02Contract) {
    foreach ($fieldName in $expectedH02Fields) {
        if (@($h02Contract.consumer_runtime_required_fields) -notcontains $fieldName) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H02_RUNTIME_REQUIRED_DRIFT' -Message "H-02 consumer runtime fields must include: $fieldName" -Path 'handoff/stage2_to_stage3/contract.json'
        }
    }
}

if ($integrationMatrix -and $integrationMatrix.rows) {
    $h01Row = @($integrationMatrix.rows | Where-Object contractId -eq 'H-01-STAGE1-TO-STAGE2' | Select-Object -First 1)
    if ($h01Row.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_INTEGRATION_ROW_MISSING' -Message 'integration_matrix must contain H-01-STAGE1-TO-STAGE2.' -Path 'handoff/integration_matrix.json'
    }
    else {
        $actualH01CriticalObjects = @($h01Row[0].criticalObjects | Sort-Object)
        $expectedH01CriticalObjects = @('task_execution_context', 'project_identity_strategy', 'clock_strategy_profile', 'execution_context')
        if (-not (Set-Equals -Expected ($expectedH01CriticalObjects | Sort-Object) -Actual $actualH01CriticalObjects)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_CRITICAL_OBJECT_DRIFT' -Message "H-01 criticalObjects must equal task_execution_context/project_identity_strategy/clock_strategy_profile/execution_context. Actual: $($actualH01CriticalObjects -join '/')" -Path 'handoff/integration_matrix.json'
        }
        $expectedH01MustNotRecompute = @(
            'window_priority_policy',
            'project_rooting_policy',
            'source_family',
            'platform_level',
            'region_scope',
            'coverage_tier',
            'source_registry_id',
            'route_policy_id',
            'default_route',
            'fallback_route'
        )
        foreach ($fieldName in $expectedH01MustNotRecompute) {
            if (@($h01Row[0].consumerMustNotRecompute) -notcontains $fieldName) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H01_MUST_NOT_RECOMPUTE_DRIFT' -Message "H-01 consumerMustNotRecompute must include: $fieldName" -Path 'handoff/integration_matrix.json'
            }
        }
    }
}

if ($integrationMatrix -and $integrationMatrix.rows) {
    $h02Row = @($integrationMatrix.rows | Where-Object contractId -eq 'H-02-STAGE2-TO-STAGE3' | Select-Object -First 1)
    if ($h02Row.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H02_INTEGRATION_ROW_MISSING' -Message 'integration_matrix must contain H-02-STAGE2-TO-STAGE3.' -Path 'handoff/integration_matrix.json'
    }
    else {
        $actualStage2CriticalObjects = @($h02Row[0].criticalObjects | Sort-Object)
        if (-not (Set-Equals -Expected ($expectedStage2CriticalObjects | Sort-Object) -Actual $actualStage2CriticalObjects)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H02_CRITICAL_OBJECT_DRIFT' -Message "H-02 criticalObjects must equal public_chain/clock_chain_profile/notice_version_chain/fixation_bundle. Actual: $($actualStage2CriticalObjects -join '/')" -Path 'handoff/integration_matrix.json'
        }
    }

    $h08Row = @($integrationMatrix.rows | Where-Object contractId -eq 'H-08-STAGE8-TO-STAGE9' | Select-Object -First 1)
    if ($h08Row.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H08_INTEGRATION_ROW_MISSING' -Message 'integration_matrix must contain H-08-STAGE8-TO-STAGE9.' -Path 'handoff/integration_matrix.json'
    }
    else {
        $actualCriticalObjects = @($h08Row[0].criticalObjects | Sort-Object)
        if (-not (Set-Equals -Expected ($expectedStage9CriticalObjects | Sort-Object) -Actual $actualCriticalObjects)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H08_CRITICAL_OBJECT_DRIFT' -Message "H-08 criticalObjects must equal saleable_opportunity/touch_record. Actual: $($actualCriticalObjects -join '/')" -Path 'handoff/integration_matrix.json'
        }
    }
}

foreach ($token in @(
    '"source_registry_id": source_entry["source_registry_id"]',
    '"route_policy_id": route_policy["route_policy_id"]',
    '"fallback_route": route_policy["route_fallback_order"][1]'
)) {
    if (-not $stage1ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE1_SOURCE_ROUTE_MISSING' -Message "Stage1 service must retain source/route registry token: $token" -Path 'src/stage1_tasking/service.py'
    }
}

foreach ($token in @(
    'self.store.build_record(',
    '"fixation_bundle"',
    '"fixation_bundle_id": fixation_bundle.get("fixation_bundle_id")',
    '"clock_conflict_state": clock_chain_profile.get("clock_conflict_state")',
    '"source_registry_id": source_registry_id',
    '"route_policy_id": route_policy_id'
)) {
    if (-not $stage2ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE2_FORMAL_OUTPUT_DRIFT' -Message "Stage2 service must retain formal drift-closure token: $token" -Path 'src/stage2_ingestion/service.py'
    }
}

foreach ($token in @(
    'stage2_bundle.record("clock_chain_profile")',
    'stage2_bundle.record("fixation_bundle")',
    '"fixation_bundle_id": fixation_bundle.get("fixation_bundle_id")'
)) {
    if (-not $stage3ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE3_EARLY_CONSUMPTION_DRIFT' -Message "Stage3 service must consume Stage2 formal token: $token" -Path 'src/stage3_parsing/service.py'
    }
}
if (-not $runtimeInventoryText.Contains('writeback_impact_executor:') -or -not $runtimeInventoryText.Contains('current_state: "INTERNAL_V0_ACTIVE"')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_IMPACT_CONTROL_DRIFT' -Message 'runtime_inventory must machine-readably declare writeback_impact_executor as INTERNAL_V0_ACTIVE.' -Path 'control/runtime_inventory.yaml'
}

if ($executionContextSchema) {
    foreach ($fieldName in @('source_registry_id', 'route_policy_id', 'fallback_route', 'requires_manual_review')) {
        if (-not ($executionContextSchema.properties.PSObject.Properties.Name -contains $fieldName)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EARLY_SCHEMA_FIELD_MISSING' -Message "execution_context schema must declare $fieldName." -Path 'contracts/schemas/execution_context.schema.json'
        }
    }
}
if ($publicChainSchema) {
    if ($publicChainSchema.properties.timeline_nodes.type -ne 'array') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EARLY_SCHEMA_TYPE_DRIFT' -Message 'public_chain.timeline_nodes must be array.' -Path 'contracts/schemas/public_chain.schema.json'
    }
    if ($publicChainSchema.properties.statutory_node_completeness.type -ne 'boolean') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EARLY_SCHEMA_TYPE_DRIFT' -Message 'public_chain.statutory_node_completeness must be boolean.' -Path 'contracts/schemas/public_chain.schema.json'
    }
}
if ($evidenceGateSchema) {
    if ($evidenceGateSchema.properties.manual_confirmation_required.type -ne 'boolean') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EARLY_SCHEMA_TYPE_DRIFT' -Message 'evidence_gate_decision.manual_confirmation_required must be boolean.' -Path 'contracts/schemas/evidence_gate_decision.schema.json'
    }
}

foreach ($fieldName in $expectedH08Fields) {
    if ($stage8ServiceText -notmatch [regex]::Escape('"' + $fieldName + '":')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE8_H08_FIELD_NOT_PROJECTED' -Message "Stage8 handoff must project H-08 field: $fieldName" -Path 'src/stage8_outreach/service.py'
    }
    if ($stage8ServiceText -notmatch [regex]::Escape('inputs_out["' + $fieldName + '"]')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE8_H08_INPUT_NOT_PROJECTED' -Message "Stage8 projected inputs must include H-08 field: $fieldName" -Path 'src/stage8_outreach/service.py'
    }
}

if ($touchRecordSchema) {
    $touchProperties = @($touchRecordSchema.properties.PSObject.Properties.Name)
    foreach ($fieldName in @('next_step_optional', 'written_back_at_optional')) {
        if ($touchProperties -notcontains $fieldName) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE8_FAILURE_FIELD_SCHEMA_MISSING' -Message "touch_record schema must declare Stage8 failure field: $fieldName" -Path 'contracts/schemas/touch_record.schema.json'
        }
    }
}

foreach ($token in @(
    '"next_step_optional": next_step_optional',
    '"written_back_at_optional": written_back_at_optional',
    'inputs_out["next_step_optional"] = touch_record.get("next_step_optional")',
    'inputs_out["written_back_at_optional"] = touch_record.get("written_back_at_optional")'
)) {
    if (-not $stage8ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE8_FAILURE_FIELD_RUNTIME_MISSING' -Message "Stage8 service must retain failure/writeback token: $token" -Path 'src/stage8_outreach/service.py'
    }
}

$actualStage9H08Fields = Get-QuotedStringList -Text $stage9ServiceText -Pattern 'REQUIRED_H08_FIELDS\s*=\s*\((.*?)\)'
if (-not (Set-Equals -Expected ($expectedH08Fields | Sort-Object) -Actual ($actualStage9H08Fields | Sort-Object))) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE9_H08_FIELD_SET_DRIFT' -Message "Stage9 REQUIRED_H08_FIELDS must equal the H-08 key field set. Actual: $($actualStage9H08Fields -join '/')" -Path 'src/stage9_delivery/service.py'
}

foreach ($token in @(
    'stage8_bundle.record("touch_record")',
    'stage8_bundle.record("saleable_opportunity")',
    'response_status = h08_payload["response_status"]',
    'saleability_status = h08_payload["saleability_status"]',
    'crm_owner_state = h08_payload["crm_owner_state"]',
    'opportunity_id": h08_payload["opportunity_id"]',
    'touch_record_id={h08_payload[''touch_record_id'']}'
)) {
    if (-not $stage9ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE9_H08_CONSUMPTION_MISSING' -Message "Stage9 service must directly consume H-08 token: $token" -Path 'src/stage9_delivery/service.py'
    }
}

$actualPolicySequence = Get-QuotedStringList -Text $stage9ServiceText -Pattern 'POLICY_SEQUENCE\s*=\s*\((.*?)\)'
if (-not (Set-Equals -Expected $expectedStage9PolicySequence -Actual $actualPolicySequence)) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE9_POLICY_SEQUENCE_DRIFT' -Message "Stage9 POLICY_SEQUENCE must remain payment_exception -> delivery_exception -> outcome_taxonomy -> governance_taxonomy. Actual: $($actualPolicySequence -join ' -> ')" -Path 'src/stage9_delivery/service.py'
}

foreach ($policyKey in $expectedStage9PolicySequence) {
    if ($policyExecutorText -notmatch [regex]::Escape('"' + $policyKey + '"')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'POLICY_EXECUTOR_MAP_MISSING' -Message "PolicyExecutor must map Stage9 policy key: $policyKey" -Path 'src/shared/policy_executor.py'
    }
    if ($policyExecutorText -notmatch ('def _evaluate_' + [regex]::Escape($policyKey))) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'POLICY_EXECUTOR_HANDLER_MISSING' -Message "PolicyExecutor must implement evaluator for: $policyKey" -Path 'src/shared/policy_executor.py'
    }
}

if ($opportunityOutcomeSchema) {
    $outcomeProperties = @($opportunityOutcomeSchema.properties.PSObject.Properties.Name)
    $outcomeRequired = @($opportunityOutcomeSchema.required)
    if ($outcomeProperties -notcontains 'writeback_targets' -or $outcomeRequired -notcontains 'writeback_targets') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'OUTCOME_WRITEBACK_SCHEMA_DRIFT' -Message 'opportunity_outcome_event must formally require writeback_targets.' -Path 'contracts/schemas/opportunity_outcome_event.schema.json'
    }
}

foreach ($token in @(
    'outcome_writeback_targets = ensure_list(',
    'runtime_state.outputs.get("outcome_taxonomy", {}).get("writeback_targets"',
    'governance_writeback_targets = ensure_list(',
    'runtime_state.outputs.get("governance_taxonomy", {}).get("writeback_targets"',
    'payment_exception_writeback_targets = ensure_list(',
    'delivery_exception_writeback_targets = ensure_list(',
    'writeback_target_resolution = self.impact_executor.resolve_effective_targets(',
    'effective_writeback_targets = list(',
    'writeback_target_resolution["effective_writeback_targets"]',
    'writeback_source_contracts=writeback_target_resolution["writeback_source_contracts"]',
    'writeback_target_sources=writeback_target_resolution["writeback_target_sources"]',
    '"writeback_targets": outcome_writeback_targets',
    '"effective_writeback_targets": effective_writeback_targets',
    '"writeback_source_contracts": impact_result["writeback_source_contracts"]',
    '"writeback_target_sources": impact_result["writeback_target_sources"]'
)) {
    if (-not $stage9ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE9_WRITEBACK_SEMANTIC_DRIFT' -Message "Stage9 service must expose semantic writeback contract token: $token" -Path 'src/stage9_delivery/service.py'
    }
}

foreach ($token in @(
    'def describe_source_contracts(',
    'def resolve_effective_targets(',
    'writeback_source_contracts',
    'writeback_target_sources',
    'additive_source_families_allowed',
    'Stage9 writeback target contract missing for target=',
    'Stage9 writeback source contract missing for source_family='
)) {
    if (-not $stage9ImpactExecutorText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE9_WRITEBACK_VALIDATOR_DRIFT' -Message "Stage9 impact executor must expose semantic writeback validator token: $token" -Path 'src/stage9_delivery/impact_executor.py'
    }
}

if ($writebackImpactPolicy) {
    if (-not ($writebackImpactPolicy.PSObject.Properties.Name -contains 'writeback_source_contracts')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_SOURCE_CONTRACTS_MISSING' -Message 'writeback_impact_policy.json must declare writeback_source_contracts.' -Path 'contracts/governance/writeback_impact_policy.json'
    }
    if ($writebackImpactPolicy.PSObject.Properties.Name -contains 'writeback_source_contracts') {
        foreach ($sourceName in @('outcome_taxonomy', 'governance_taxonomy', 'payment_exception', 'delivery_exception')) {
            $sourceContract = $writebackImpactPolicy.writeback_source_contracts.$sourceName
            if (-not $sourceContract) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_SOURCE_CONTRACT_MISSING' -Message "writeback_impact_policy.json missing source contract for $sourceName." -Path 'contracts/governance/writeback_impact_policy.json'
                continue
            }
            foreach ($requiredField in @('source_output_field', 'merge_semantics', 'persisted_stage9_record_target', 'silent_override_forbidden')) {
                if (-not ($sourceContract.PSObject.Properties.Name -contains $requiredField)) {
                    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_SOURCE_CONTRACT_INCOMPLETE' -Message "writeback source contract $sourceName missing field $requiredField." -Path 'contracts/governance/writeback_impact_policy.json'
                }
            }
        }
    }
}

Invoke-SemanticAlignment -RepoRoot $root -Issues ([ref]$issues)

$errors = @($issues | Where-Object severity -eq 'ERROR')
$result = [pscustomobject]@{
    script   = 'validate-contracts.ps1'
    repoRoot = $root
    ok       = ($errors.Count -eq 0)
    errorCount = $errors.Count
    warningCount = @($issues | Where-Object severity -eq 'WARNING').Count
    issues   = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[validate-contracts] repo: $root"
    if ($issues.Count -eq 0) {
        Write-Host '[validate-contracts] PASS'
    } else {
        foreach ($issue in $issues) {
            Write-Host ("[{0}] {1} {2} {3}" -f $issue.severity, $issue.code, $issue.path, $issue.message)
        }
    }
}

if ($EmitJson) {
    $result | ConvertTo-Json -Depth 20
}

if ($errors.Count -gt 0) { exit 1 }
exit 0
