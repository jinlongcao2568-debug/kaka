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
        message  = $Message
        path     = $Path
    }) | Out-Null
}

function Read-JsonFile {
    param([string]$Path, [ref]$Issues)
    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_FILE' -Message 'Required file is missing.' -Path $Path
        return $null
    }

    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100)
    }
    catch {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'INVALID_JSON' -Message $_.Exception.Message -Path $Path
        return $null
    }
}

function Read-TextFile {
    param([string]$Path, [ref]$Issues)
    if (-not (Test-Path -LiteralPath $Path)) {
        Add-Issue -Bag $Issues -Severity 'ERROR' -Code 'MISSING_FILE' -Message 'Required file is missing.' -Path $Path
        return ''
    }

    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

function Get-RegexValue {
    param(
        [string]$Text,
        [string]$Pattern
    )

    $match = [regex]::Match($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::Multiline)
    if (-not $match.Success) { return $null }
    return $match.Groups[1].Value.Trim()
}

function Set-Equals {
    param(
        [string[]]$Expected,
        [string[]]$Actual
    )

    if ($Expected.Count -ne $Actual.Count) { return $false }
    return (@(Compare-Object -ReferenceObject $Expected -DifferenceObject $Actual).Count -eq 0)
}

function Test-RelativeAssetPath {
    param([string]$RelativePath)

    if ([string]::IsNullOrWhiteSpace($RelativePath)) { return $false }
    return (Test-Path -LiteralPath (Join-Path $root $RelativePath))
}

function Get-FormalDecisionIds {
    param(
        [string]$Text,
        [string]$DocCode
    )

    $pattern = "(?m)^\s*#{2,6}\s+\[($DocCode-R-\d{3}(?:-[A-Z])?)\]"
    $ids = [System.Collections.Generic.List[string]]::new()
    foreach ($match in [regex]::Matches($Text, $pattern)) {
        $id = $match.Groups[1].Value
        if (-not $ids.Contains($id)) {
            $ids.Add($id) | Out-Null
        }
    }
    return @($ids)
}

function Get-DecisionBaseId {
    param([string]$DecisionId)
    $match = [regex]::Match($DecisionId, '^(D\d+-R-\d{3})')
    if (-not $match.Success) { return $null }
    return $match.Groups[1].Value
}

function Get-DecisionNumericTail {
    param([string]$DecisionId)
    $match = [regex]::Match($DecisionId, '(\d{3})')
    if (-not $match.Success) { return -1 }
    return [int]$match.Groups[1].Value
}

function Get-RulingIndexSummaryRow {
    param(
        [string]$RulingIndexText,
        [string]$DocCode
    )

    $escapedDocCode = [regex]::Escape($DocCode)
    $pattern = '(?m)^\| ' + $escapedDocCode + ' \| `(' + $escapedDocCode + '-R-\d{3}(?:-[A-Z])?)` \| `(' + $escapedDocCode + '-R-\d{3}(?:-[A-Z])?)` \| (\d+) \|'
    $match = [regex]::Match($RulingIndexText, $pattern)
    if (-not $match.Success) { return $null }

    return [pscustomobject]@{
        startId = $match.Groups[1].Value
        endId   = $match.Groups[2].Value
        count   = [int]$match.Groups[3].Value
    }
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$issues = [System.Collections.Generic.List[object]]::new()

$enumCatalog = Read-JsonFile -Path (Join-Path $root 'contracts/enums/enum_catalog.json') -Issues ([ref]$issues)
$fieldPolicy = Read-JsonFile -Path (Join-Path $root 'contracts/governance/field_policy_dictionary.json') -Issues ([ref]$issues)
$schemaCatalog = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/schema_catalog.json') -Issues ([ref]$issues)
$exportTemplates = Read-JsonFile -Path (Join-Path $root 'contracts/ui/export_template_catalog.json') -Issues ([ref]$issues)
$referenceIndex = Read-JsonFile -Path (Join-Path $root 'control/reference_index.json') -Issues ([ref]$issues)
$releaseGates = Read-JsonFile -Path (Join-Path $root 'contracts/release/release_gates.json') -Issues ([ref]$issues)
$runtimePolicyCatalog = Read-JsonFile -Path (Join-Path $root 'contracts/release/runtime_policy_catalog.json') -Issues ([ref]$issues)
$deploymentMatrix = Read-JsonFile -Path (Join-Path $root 'contracts/release/deployment_matrix.json') -Issues ([ref]$issues)
$modelCatalog = Read-JsonFile -Path (Join-Path $root 'contracts/model/model_catalog.json') -Issues ([ref]$issues)
$modelUsagePolicy = Read-JsonFile -Path (Join-Path $root 'contracts/model/model_usage_policy.json') -Issues ([ref]$issues)
$modelReleaseGates = Read-JsonFile -Path (Join-Path $root 'contracts/model/model_release_gates.json') -Issues ([ref]$issues)
$toolUsagePolicy = Read-JsonFile -Path (Join-Path $root 'contracts/model/tool_usage_policy_catalog.json') -Issues ([ref]$issues)
$sourceRegistry = Read-JsonFile -Path (Join-Path $root 'contracts/governance/source_registry.json') -Issues ([ref]$issues)
$routePolicyCatalog = Read-JsonFile -Path (Join-Path $root 'contracts/governance/route_policy_catalog.json') -Issues ([ref]$issues)
$sourceFamilyRegistry = Read-JsonFile -Path (Join-Path $root 'contracts/governance/source_family_registry.json') -Issues ([ref]$issues)
$platformLevelRegistry = Read-JsonFile -Path (Join-Path $root 'contracts/governance/platform_level_registry.json') -Issues ([ref]$issues)
$vendorRegistry = Read-JsonFile -Path (Join-Path $root 'contracts/sales/vendor_registry_catalog.json') -Issues ([ref]$issues)
$sourceVendorUsagePolicy = Read-JsonFile -Path (Join-Path $root 'contracts/sales/source_vendor_usage_policy.json') -Issues ([ref]$issues)
$channelVendorExecutionPolicy = Read-JsonFile -Path (Join-Path $root 'contracts/sales/channel_vendor_execution_policy.json') -Issues ([ref]$issues)
$contactPolicyCatalog = Read-JsonFile -Path (Join-Path $root 'contracts/sales/contact_policy_catalog.json') -Issues ([ref]$issues)
$contactChannelCatalog = Read-JsonFile -Path (Join-Path $root 'contracts/sales/contact_channel_catalog.json') -Issues ([ref]$issues)
$contactTargetSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/contact_target.schema.json') -Issues ([ref]$issues)
$outreachPlanSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/outreach_plan.schema.json') -Issues ([ref]$issues)
$touchRecordSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/touch_record.schema.json') -Issues ([ref]$issues)
$projectFactSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/project_fact.schema.json') -Issues ([ref]$issues)
$saleableOpportunitySchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/saleable_opportunity.schema.json') -Issues ([ref]$issues)
$bidderCandidateSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/bidder_candidate.schema.json') -Issues ([ref]$issues)
$challengerCandidateProfileSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/challenger_candidate_profile.schema.json') -Issues ([ref]$issues)
$executionContextSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/execution_context.schema.json') -Issues ([ref]$issues)
$publicChainSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/public_chain.schema.json') -Issues ([ref]$issues)
$noticeVersionChainSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/notice_version_chain.schema.json') -Issues ([ref]$issues)
$multiCompetitorCollectionSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/competitor_candidate_collection.schema.json') -Issues ([ref]$issues)
$contactCandidateCollectionSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/contact_candidate_collection.schema.json') -Issues ([ref]$issues)
$contactSelectionTraceSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/contact_selection_trace.schema.json') -Issues ([ref]$issues)
$clockChainProfileSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/clock_chain_profile.schema.json') -Issues ([ref]$issues)
$modelGovernanceSchema = Read-JsonFile -Path (Join-Path $root 'contracts/schemas/model_governance_record.schema.json') -Issues ([ref]$issues)
$writebackImpactPolicy = Read-JsonFile -Path (Join-Path $root 'contracts/governance/writeback_impact_policy.json') -Issues ([ref]$issues)
$h06Contract = Read-JsonFile -Path (Join-Path $root 'handoff/stage6_to_stage7/contract.json') -Issues ([ref]$issues)
$h07Contract = Read-JsonFile -Path (Join-Path $root 'handoff/stage7_to_stage8/contract.json') -Issues ([ref]$issues)
$h08Contract = Read-JsonFile -Path (Join-Path $root 'handoff/stage8_to_stage9/contract.json') -Issues ([ref]$issues)

$l0Text = Read-TextFile -Path (Join-Path $root 'docs/L0.md') -Issues ([ref]$issues)
$d2Text = Read-TextFile -Path (Join-Path $root 'docs/D2_正式对象契约与字段字典.md') -Issues ([ref]$issues)
$d5Text = Read-TextFile -Path (Join-Path $root 'docs/D5_页面导出与人工复核规范.md') -Issues ([ref]$issues)
$d6Text = Read-TextFile -Path (Join-Path $root 'docs/D6_字段策略字典与客户交付字段规范.md') -Issues ([ref]$issues)
$d7Text = Read-TextFile -Path (Join-Path $root 'docs/D7_对象级交付矩阵与外发治理规范.md') -Issues ([ref]$issues)
$d8Text = Read-TextFile -Path (Join-Path $root 'docs/D8_真实竞争者识别可售对象与销售推进规范.md') -Issues ([ref]$issues)
$d9Text = Read-TextFile -Path (Join-Path $root 'docs/D9_联系对象与销售触达规范.md') -Issues ([ref]$issues)
$d11Text = Read-TextFile -Path (Join-Path $root 'docs/D11_测试验收与金标回归清单.md') -Issues ([ref]$issues)
$d13Text = Read-TextFile -Path (Join-Path $root 'docs/D13_公开可查边界能力清单.md') -Issues ([ref]$issues)
$d14Text = Read-TextFile -Path (Join-Path $root 'docs/D14_AI模型治理规范.md') -Issues ([ref]$issues)
$sourceRouteTopicText = Read-TextFile -Path (Join-Path $root 'docs/专题_来源覆盖与采集路由规范.md') -Issues ([ref]$issues)
$techDecisionText = Read-TextFile -Path (Join-Path $root 'docs/技术实现决策页.md') -Issues ([ref]$issues)
$rulingIndexText = Read-TextFile -Path (Join-Path $root 'docs/裁决总表.md') -Issues ([ref]$issues)
$launchAdjudicationText = Read-TextFile -Path (Join-Path $root 'docs/正式业务代码开发开工裁决页.md') -Issues ([ref]$issues)
$currentTaskText = Read-TextFile -Path (Join-Path $root 'control/current_task.yaml') -Issues ([ref]$issues)
$taskPacketLibraryText = Read-TextFile -Path (Join-Path $root 'control/task_packet_library.yaml') -Issues ([ref]$issues)
$milestoneText = Read-TextFile -Path (Join-Path $root 'control/milestone_status.yaml') -Issues ([ref]$issues)
$repoStatusText = Read-TextFile -Path (Join-Path $root 'control/repo_status.md') -Issues ([ref]$issues)
$runtimeInventoryText = Read-TextFile -Path (Join-Path $root 'control/runtime_inventory.yaml') -Issues ([ref]$issues)
$releaseManifestText = Read-TextFile -Path (Join-Path $root 'control/release_manifest.yaml') -Issues ([ref]$issues)
$modelReleaseManifestText = Read-TextFile -Path (Join-Path $root 'control/model_release_manifest.yaml') -Issues ([ref]$issues)
$statusBoardText = Read-TextFile -Path (Join-Path $root 'docs/文档与资产状态板.md') -Issues ([ref]$issues)
$approvalMappingText = Read-TextFile -Path (Join-Path $root 'control/approval_chain_semantic_mapping.yaml') -Issues ([ref]$issues)
$ax9sText = Read-TextFile -Path (Join-Path $root 'docs/AX9S_开发执行路由图.md') -Issues ([ref]$issues)
$pipelineText = Read-TextFile -Path (Join-Path $root 'src/shared/pipeline.py') -Issues ([ref]$issues)
$capabilityRuntimeText = Read-TextFile -Path (Join-Path $root 'src/shared/capability_runtime.py') -Issues ([ref]$issues)
$policyExecutorText = Read-TextFile -Path (Join-Path $root 'src/shared/policy_executor.py') -Issues ([ref]$issues)
$runtimeValidatorText = Read-TextFile -Path (Join-Path $root 'src/shared/runtime_validator.py') -Issues ([ref]$issues)
$contractsRuntimeText = Read-TextFile -Path (Join-Path $root 'src/shared/contracts_runtime.py') -Issues ([ref]$issues)
$statePacketText = Read-TextFile -Path (Join-Path $root 'src/shared/state_packet.py') -Issues ([ref]$issues)
$stage6ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage6_fact_review/service.py') -Issues ([ref]$issues)
$stage7ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage7_sales/service.py') -Issues ([ref]$issues)
$stage8ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage8_outreach/service.py') -Issues ([ref]$issues)
$stage9ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage9_delivery/service.py') -Issues ([ref]$issues)
$stage9ImpactExecutorText = Read-TextFile -Path (Join-Path $root 'src/stage9_delivery/impact_executor.py') -Issues ([ref]$issues)
$stage1ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage1_tasking/service.py') -Issues ([ref]$issues)
$stage1ExtractorText = Read-TextFile -Path (Join-Path $root 'src/stage1_tasking/extractors.py') -Issues ([ref]$issues)
$stage2ServiceText = Read-TextFile -Path (Join-Path $root 'src/stage2_ingestion/service.py') -Issues ([ref]$issues)
$stage2ExtractorText = Read-TextFile -Path (Join-Path $root 'src/stage2_ingestion/extractors.py') -Issues ([ref]$issues)
$internalChainTestText = Read-TextFile -Path (Join-Path $root 'tests/test_internal_chain.py') -Issues ([ref]$issues)
$stage12ExtractorTestText = Read-TextFile -Path (Join-Path $root 'tests/test_stage12_extractors.py') -Issues ([ref]$issues)
$h01Contract = Read-JsonFile -Path (Join-Path $root 'handoff/stage1_to_stage2/contract.json') -Issues ([ref]$issues)
$h01Example = Read-JsonFile -Path (Join-Path $root 'handoff/stage1_to_stage2/example.json') -Issues ([ref]$issues)

function Test-SchemaHasProperty {
    param(
        [object]$Schema,
        [string]$SchemaPath,
        [string]$FieldName
    )

    if (-not $Schema) { return }
    if (-not ($Schema.properties.PSObject.Properties.Name -contains $FieldName)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_SCHEMA_FIELD_MISSING' -Message "$SchemaPath must declare $FieldName." -Path $SchemaPath
    }
}

function Test-CatalogHasOptionalField {
    param(
        [string]$ObjectName,
        [string]$FieldName
    )

    if (-not $schemaCatalog) { return }
    $entry = @($schemaCatalog.schemas | Where-Object object -eq $ObjectName | Select-Object -First 1)
    if ($entry.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_CATALOG_OBJECT_MISSING' -Message "schema_catalog missing $ObjectName." -Path 'contracts/schemas/schema_catalog.json'
        return
    }
    $requiredFields = @($entry[0].required)
    $optionalFields = if ($entry[0].PSObject.Properties.Name -contains 'optional') { @($entry[0].optional) } else { @() }
    $catalogFields = $requiredFields + $optionalFields
    if ($catalogFields -notcontains $FieldName) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_CATALOG_FIELD_MISSING' -Message "schema_catalog $ObjectName must declare $FieldName." -Path 'contracts/schemas/schema_catalog.json'
    }
}

function Test-CatalogHasField {
    param(
        [string]$ObjectName,
        [string]$FieldName
    )

    if (-not $schemaCatalog) { return }
    $entry = @($schemaCatalog.schemas | Where-Object object -eq $ObjectName | Select-Object -First 1)
    if ($entry.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SCHEMA_CATALOG_OBJECT_MISSING' -Message "schema_catalog missing $ObjectName." -Path 'contracts/schemas/schema_catalog.json'
        return
    }
    $requiredFields = @($entry[0].required)
    $optionalFields = if ($entry[0].PSObject.Properties.Name -contains 'optional') { @($entry[0].optional) } else { @() }
    $catalogFields = $requiredFields + $optionalFields
    if ($catalogFields -notcontains $FieldName) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SCHEMA_CATALOG_FIELD_MISSING' -Message "schema_catalog $ObjectName must declare $FieldName." -Path 'contracts/schemas/schema_catalog.json'
    }
}

function Test-HandoffOptionalField {
    param(
        [object]$Contract,
        [string]$ContractPath,
        [string]$FieldName
    )

    if (-not $Contract) { return }
    if (@($Contract.optional_payload_fields) -notcontains $FieldName) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_HANDOFF_FIELD_MISSING' -Message "$ContractPath must carry optional payload field $FieldName." -Path $ContractPath
    }
}

$formalSinkSchemaBindings = @(
    [pscustomobject]@{ object='project_fact'; field='project_value_score_optional'; schema=$projectFactSchema; path='contracts/schemas/project_fact.schema.json' },
    [pscustomobject]@{ object='saleable_opportunity'; field='opportunity_value_score_optional'; schema=$saleableOpportunitySchema; path='contracts/schemas/saleable_opportunity.schema.json' },
    [pscustomobject]@{ object='bidder_candidate'; field='normalized_price_amount_optional'; schema=$bidderCandidateSchema; path='contracts/schemas/bidder_candidate.schema.json' },
    [pscustomobject]@{ object='bidder_candidate'; field='price_conflict_gate_status_optional'; schema=$bidderCandidateSchema; path='contracts/schemas/bidder_candidate.schema.json' },
    [pscustomobject]@{ object='challenger_candidate_profile'; field='confidence_score_optional'; schema=$challengerCandidateProfileSchema; path='contracts/schemas/challenger_candidate_profile.schema.json' },
    [pscustomobject]@{ object='clock_chain_profile'; field='current_action_start_at_optional'; schema=$clockChainProfileSchema; path='contracts/schemas/clock_chain_profile.schema.json' },
    [pscustomobject]@{ object='clock_chain_profile'; field='current_action_deadline_at_optional'; schema=$clockChainProfileSchema; path='contracts/schemas/clock_chain_profile.schema.json' }
)

foreach ($binding in $formalSinkSchemaBindings) {
    Test-SchemaHasProperty -Schema $binding.schema -SchemaPath $binding.path -FieldName $binding.field
    Test-CatalogHasOptionalField -ObjectName $binding.object -FieldName $binding.field
    $d2FieldToken = "| ``$($binding.object)`` | ``$($binding.field)`` |"
    if (-not $d2Text.Contains($d2FieldToken)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_D2_FIELD_MISSING' -Message "D2 must declare $($binding.object).$($binding.field)." -Path 'docs/D2_正式对象契约与字段字典.md'
    }
}

foreach ($fieldName in @(
    'project_value_score_optional',
    'normalized_price_amount_optional',
    'price_conflict_gate_status_optional',
    'confidence_score_optional',
    'current_action_start_at_optional',
    'current_action_deadline_at_optional'
)) {
    Test-HandoffOptionalField -Contract $h06Contract -ContractPath 'handoff/stage6_to_stage7/contract.json' -FieldName $fieldName
    if (-not ($stage7ServiceText.Contains('stage6_handoff.get') -and $stage7ServiceText.Contains($fieldName))) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_H06_RUNTIME_CONSUMPTION_MISSING' -Message "Stage7 must consume H-06 optional field $fieldName." -Path 'src/stage7_sales/service.py'
    }
}

foreach ($fieldName in @(
    'project_value_score_optional',
    'opportunity_value_score_optional',
    'normalized_price_amount_optional',
    'price_conflict_gate_status_optional',
    'confidence_score_optional',
    'current_action_start_at_optional',
    'current_action_deadline_at_optional'
)) {
    Test-HandoffOptionalField -Contract $h07Contract -ContractPath 'handoff/stage7_to_stage8/contract.json' -FieldName $fieldName
    if (-not $stage7ServiceText.Contains("`"$fieldName`":")) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_H07_RUNTIME_PROJECTION_MISSING' -Message "Stage7 must project H-07 optional field $fieldName." -Path 'src/stage7_sales/service.py'
    }
    if (-not $stage7ServiceText.Contains("inputs_out[`"$fieldName`"]")) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_H07_INPUT_PROJECTION_MISSING' -Message "Stage7 projected inputs must include $fieldName." -Path 'src/stage7_sales/service.py'
    }
    if (-not $stage8ServiceText.Contains($fieldName) -or -not $stage8ServiceText.Contains('formal_sink_consumption')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FORMAL_SINK_STAGE8_CONSUMPTION_MISSING' -Message "Stage8 must consume formal sink field $fieldName in trace." -Path 'src/stage8_outreach/service.py'
    }
}

if ($sourceRegistry) {
    $sourceEntries = @($sourceRegistry.entries)
    if ($sourceEntries.Count -lt 9) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_SOURCE_BASELINE_TOO_SMALL' -Message 'source_registry must contain a minimum authoritative baseline and may not stay at symbolic sample size.' -Path 'contracts/governance/source_registry.json'
    }
    $actualFamilies = @($sourceEntries | ForEach-Object { [string]$_.source_family } | Sort-Object -Unique)
    $actualPlatforms = @($sourceEntries | ForEach-Object { [string]$_.platform_level } | Sort-Object -Unique)
    $actualCarriers = @($sourceEntries | ForEach-Object { [string]$_.carrier_type } | Sort-Object -Unique)
    $expectedFamilies = @('PROCUREMENT_NOTICE','AWARD_ANNOUNCEMENT','REGULATORY_PUBLICATION','ENTERPRISE_REGISTRY','JUDICIAL_CREDIT_RISK','ANNEX_QA_SUPPLEMENT','OTHER_PUBLIC_SOURCE')
    $expectedPlatforms = @('NATIONAL','PROVINCE','CITY','COUNTY','INDUSTRY_PLATFORM','ENTERPRISE_SITE')
    $expectedCarriers = @('HTML_PAGE','PDF_ATTACHMENT','DOC_ATTACHMENT','IMAGE_ATTACHMENT','TABLE_SEGMENT','TEXT_SEGMENT')
    if (-not (Set-Equals -Expected $expectedFamilies -Actual $actualFamilies)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_SOURCE_FAMILY_BASELINE_DRIFT' -Message "source_registry families must match authoritative baseline. expected=$($expectedFamilies -join '/'), actual=$($actualFamilies -join '/')" -Path 'contracts/governance/source_registry.json'
    }
    if (-not (Set-Equals -Expected $expectedPlatforms -Actual $actualPlatforms)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_PLATFORM_BASELINE_DRIFT' -Message "source_registry platform levels must match authoritative baseline. expected=$($expectedPlatforms -join '/'), actual=$($actualPlatforms -join '/')" -Path 'contracts/governance/source_registry.json'
    }
    if (-not (Set-Equals -Expected $expectedCarriers -Actual $actualCarriers)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_CARRIER_BASELINE_DRIFT' -Message "source_registry carrier types must match authoritative baseline. expected=$($expectedCarriers -join '/'), actual=$($actualCarriers -join '/')" -Path 'contracts/governance/source_registry.json'
    }
    foreach ($entry in $sourceEntries) {
        foreach ($fieldName in @('source_registry_id','source_family','platform_level','region_scope','coverage_tier','carrier_type','route_policy_id','default_route','fallback_route','collection_state','requires_manual_review','maturity_level','version_chain_strategy','clock_resolution_rule_id')) {
            if (-not ($entry.PSObject.Properties.Name -contains $fieldName)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_SOURCE_BASELINE_FIELD_MISSING' -Message "source_registry entry must declare $fieldName." -Path 'contracts/governance/source_registry.json'
            }
        }
    }
}

if ($routePolicyCatalog) {
    $policies = @($routePolicyCatalog.policies)
    if ($policies.Count -lt 8) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_ROUTE_BASELINE_TOO_SMALL' -Message 'route_policy_catalog must declare a minimum authoritative baseline, not just one sample policy.' -Path 'contracts/governance/route_policy_catalog.json'
    }
    $actualRouteTypes = @($policies | ForEach-Object { [string]$_.route_type } | Sort-Object -Unique)
    $expectedRouteTypes = @('LIST_TO_DETAIL','DETAIL_DIRECT','ATTACHMENT_FIRST','VERSION_CHAIN','METADATA_ONLY','SEMI_MANUAL','REGISTER_ONLY')
    foreach ($routeType in $expectedRouteTypes) {
        if ($actualRouteTypes -notcontains $routeType) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_ROUTE_TYPE_BASELINE_DRIFT' -Message "route_policy_catalog must cover route_type=$routeType." -Path 'contracts/governance/route_policy_catalog.json'
        }
    }
    foreach ($policy in $policies) {
        foreach ($fieldName in @('route_policy_id','route_type','source_family_refs','platform_level_refs','carrier_type_refs','source_registry_refs','default_route','fallback_route','route_fallback_order','default_decision','review_conditions','review_signals','block_conditions','blocked_signals','version_chain_relation','clock_chain_relation','action_deadline_relation')) {
            if (-not ($policy.PSObject.Properties.Name -contains $fieldName)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_ROUTE_POLICY_FIELD_MISSING' -Message "route policy must declare $fieldName." -Path 'contracts/governance/route_policy_catalog.json'
            }
        }
    }
}

if ($sourceFamilyRegistry) {
    $actual = @($sourceFamilyRegistry.entries | ForEach-Object { [string]$_.source_family } | Sort-Object -Unique)
    $expected = @('PROCUREMENT_NOTICE','AWARD_ANNOUNCEMENT','REGULATORY_PUBLICATION','ENTERPRISE_REGISTRY','JUDICIAL_CREDIT_RISK','ANNEX_QA_SUPPLEMENT','OTHER_PUBLIC_SOURCE')
    if (-not (Set-Equals -Expected $expected -Actual $actual)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_SOURCE_FAMILY_REGISTRY_DRIFT' -Message "source_family_registry must match authoritative baseline families. expected=$($expected -join '/'), actual=$($actual -join '/')" -Path 'contracts/governance/source_family_registry.json'
    }
}
if ($platformLevelRegistry) {
    $actual = @($platformLevelRegistry.entries | ForEach-Object { [string]$_.platform_level } | Sort-Object -Unique)
    $expected = @('NATIONAL','PROVINCE','CITY','COUNTY','INDUSTRY_PLATFORM','ENTERPRISE_SITE')
    if (-not (Set-Equals -Expected $expected -Actual $actual)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_PLATFORM_LEVEL_REGISTRY_DRIFT' -Message "platform_level_registry must match authoritative baseline levels. expected=$($expected -join '/'), actual=$($actual -join '/')" -Path 'contracts/governance/platform_level_registry.json'
    }
}

foreach ($binding in @(
    [pscustomobject]@{ object='execution_context'; field='carrier_type'; schema=$executionContextSchema; path='contracts/schemas/execution_context.schema.json' },
    [pscustomobject]@{ object='public_chain'; field='source_registry_id'; schema=$publicChainSchema; path='contracts/schemas/public_chain.schema.json' },
    [pscustomobject]@{ object='public_chain'; field='route_policy_id'; schema=$publicChainSchema; path='contracts/schemas/public_chain.schema.json' },
    [pscustomobject]@{ object='public_chain'; field='fallback_route'; schema=$publicChainSchema; path='contracts/schemas/public_chain.schema.json' },
    [pscustomobject]@{ object='public_chain'; field='route_decision_state'; schema=$publicChainSchema; path='contracts/schemas/public_chain.schema.json' },
    [pscustomobject]@{ object='public_chain'; field='route_review_reasons'; schema=$publicChainSchema; path='contracts/schemas/public_chain.schema.json' },
    [pscustomobject]@{ object='public_chain'; field='route_downgrade_signals'; schema=$publicChainSchema; path='contracts/schemas/public_chain.schema.json' },
    [pscustomobject]@{ object='public_chain'; field='route_block_signals'; schema=$publicChainSchema; path='contracts/schemas/public_chain.schema.json' },
    [pscustomobject]@{ object='notice_version_chain'; field='source_registry_id'; schema=$noticeVersionChainSchema; path='contracts/schemas/notice_version_chain.schema.json' },
    [pscustomobject]@{ object='notice_version_chain'; field='route_policy_id'; schema=$noticeVersionChainSchema; path='contracts/schemas/notice_version_chain.schema.json' },
    [pscustomobject]@{ object='notice_version_chain'; field='fallback_route'; schema=$noticeVersionChainSchema; path='contracts/schemas/notice_version_chain.schema.json' },
    [pscustomobject]@{ object='notice_version_chain'; field='version_chain_strategy'; schema=$noticeVersionChainSchema; path='contracts/schemas/notice_version_chain.schema.json' },
    [pscustomobject]@{ object='clock_chain_profile'; field='clock_resolution_rule_id'; schema=$clockChainProfileSchema; path='contracts/schemas/clock_chain_profile.schema.json' }
)) {
    Test-SchemaHasProperty -Schema $binding.schema -SchemaPath $binding.path -FieldName $binding.field
    Test-CatalogHasField -ObjectName $binding.object -FieldName $binding.field
}

if ($h01Contract) {
    foreach ($fieldName in @('source_family','platform_level','region_scope','coverage_tier','carrier_type','clock_resolution_rule_id','current_action_start_at_optional','current_action_deadline_at_optional')) {
        Test-HandoffOptionalField -Contract $h01Contract -ContractPath 'handoff/stage1_to_stage2/contract.json' -FieldName $fieldName
    }
}
if ($h01Example) {
    foreach ($fieldName in @('source_family','platform_level','region_scope','coverage_tier','carrier_type','clock_resolution_rule_id','current_action_start_at_optional','current_action_deadline_at_optional')) {
        if (-not ($h01Example.payload.PSObject.Properties.Name -contains $fieldName)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_H01_OPTIONAL_BASELINE_MISSING' -Message "H-01 example must include authoritative baseline field $fieldName." -Path 'handoff/stage1_to_stage2/example.json'
        }
    }
}
foreach ($token in @(
    '"carrier_type": extracted.carrier_type',
    '"carrier_type": extracted.carrier_type,',
    '"source_registry_id": source_registry_id',
    '"route_policy_id": route_policy_id',
    '"route_decision_state": extracted.route_decision_state',
    '"route_review_reasons": extracted.route_review_reasons',
    '"route_downgrade_signals": extracted.route_downgrade_signals',
    '"route_block_signals": extracted.route_block_signals',
    '"version_chain_strategy": extracted.version_chain_strategy',
    '"clock_resolution_rule_id": extracted.clock_resolution_rule_id',
    'clock_chain_payload["current_action_deadline_at_optional"] = extracted.current_action_deadline_at_optional'
)) {
    if (-not $stage2ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_RUNTIME_BASELINE_PROJECTION_MISSING' -Message "Stage2 service must project authoritative baseline token: $token" -Path 'src/stage2_ingestion/service.py'
    }
}
foreach ($token in @(
    'carrier_authority = handoff.get("carrier_type") or execution_context.get("carrier_type")',
    'route_decision_state',
    'route_downgrade_signals',
    'route_block_signals',
    'version_chain_strategy',
    'clock_resolution_rule_id'
)) {
    if (-not $stage2ExtractorText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_RUNTIME_BASELINE_EXTRACTION_MISSING' -Message "Stage2 extractor must retain authoritative baseline token: $token" -Path 'src/stage2_ingestion/extractors.py'
    }
}
if (-not $stage1ServiceText.Contains('"carrier_type": extracted.carrier_type')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_H01_CARRIER_AUTHORITY_MISSING' -Message 'Stage1 must project carrier_type into execution_context and H-01 handoff.' -Path 'src/stage1_tasking/service.py'
}
foreach ($token in @('source_family_registry.json', 'platform_level_registry.json', 'ROUTE-OTHER-REGISTER-001', 'SRC-REG-REG-NATIONAL-HTML')) {
    if (-not $sourceRouteTopicText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_TOPIC_BASELINE_DRIFT' -Message "source route topic must explicitly carry authoritative baseline token $token." -Path 'docs/专题_来源覆盖与采集路由规范.md'
    }
}
$topicSourceIds = [regex]::Matches($sourceRouteTopicText, 'SRC-[A-Z0-9-]+') | ForEach-Object { $_.Value } | Sort-Object -Unique
$topicRouteIds = [regex]::Matches($sourceRouteTopicText, 'ROUTE-[A-Z0-9-]+') | ForEach-Object { $_.Value } | Sort-Object -Unique
if ($sourceRegistry) {
    $registryIds = @($sourceRegistry.entries | ForEach-Object { [string]$_.source_registry_id })
    foreach ($id in $topicSourceIds) {
        if ($registryIds -notcontains $id) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_TOPIC_SOURCE_ID_MISSING' -Message "Topic-doc source baseline id $id must exist in source_registry." -Path 'contracts/governance/source_registry.json'
        }
    }
}
if ($routePolicyCatalog) {
    $policyIds = @($routePolicyCatalog.policies | ForEach-Object { [string]$_.route_policy_id })
    foreach ($id in $topicRouteIds) {
        if ($policyIds -notcontains $id) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_TOPIC_ROUTE_ID_MISSING' -Message "Topic-doc route baseline id $id must exist in route_policy_catalog." -Path 'contracts/governance/route_policy_catalog.json'
        }
    }
}
if (-not $stage12ExtractorTestText.Contains('test_stage12_authoritative_baseline_registries_cover_minimum_scope') -or -not $stage12ExtractorTestText.Contains('test_stage12_authoritative_baseline_runtime_cases')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE12_BASELINE_TEST_MISSING' -Message 'tests/test_stage12_extractors.py must cover authoritative baseline registries and runtime cases.' -Path 'tests/test_stage12_extractors.py'
}

foreach ($token in @('multi_competitor_collection', 'contact_candidate_collection', 'contact_selection_trace')) {
    if (-not $d2Text.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CANDIDATE_COLLECTION_D2_DRIFT' -Message "D2 must declare $token." -Path 'docs/D2_正式对象契约与字段字典.md'
    }
}
foreach ($token in @('multi_competitor_collection', 'H-06', 'H-07')) {
    if (-not $d8Text.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'COMPETITOR_COLLECTION_D8_DRIFT' -Message "D8 must align Stage7 collection carrier token $token." -Path 'docs/D8_真实竞争者识别可售对象与销售推进规范.md'
    }
}
foreach ($token in @('contact_candidate_collection', 'contact_selection_trace', 'reselect_history')) {
    if (-not $d9Text.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CONTACT_COLLECTION_D9_DRIFT' -Message "D9 must align Stage8 collection carrier token $token." -Path 'docs/D9_联系对象与销售触达规范.md'
    }
    if (-not $d11Text.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CONTACT_COLLECTION_D11_DRIFT' -Message "D11 must align Stage8 collection carrier token $token." -Path 'docs/D11_测试验收与金标回归清单.md'
    }
}

foreach ($binding in @(
    [pscustomobject]@{ object='multi_competitor_collection'; field='multi_competitor_collection_id'; schema=$multiCompetitorCollectionSchema; path='contracts/schemas/competitor_candidate_collection.schema.json' },
    [pscustomobject]@{ object='multi_competitor_collection'; field='winning_candidate_id'; schema=$multiCompetitorCollectionSchema; path='contracts/schemas/competitor_candidate_collection.schema.json' },
    [pscustomobject]@{ object='contact_candidate_collection'; field='contact_candidate_collection_id'; schema=$contactCandidateCollectionSchema; path='contracts/schemas/contact_candidate_collection.schema.json' },
    [pscustomobject]@{ object='contact_candidate_collection'; field='selection_trace_id'; schema=$contactCandidateCollectionSchema; path='contracts/schemas/contact_candidate_collection.schema.json' },
    [pscustomobject]@{ object='contact_selection_trace'; field='contact_selection_trace_id'; schema=$contactSelectionTraceSchema; path='contracts/schemas/contact_selection_trace.schema.json' },
    [pscustomobject]@{ object='contact_selection_trace'; field='winning_contact_candidate_id'; schema=$contactSelectionTraceSchema; path='contracts/schemas/contact_selection_trace.schema.json' }
)) {
    Test-SchemaHasProperty -Schema $binding.schema -SchemaPath $binding.path -FieldName $binding.field
    Test-CatalogHasField -ObjectName $binding.object -FieldName $binding.field
}

if ($h06Contract) {
    if (@($h06Contract.consumer_objects) -notcontains 'multi_competitor_collection') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H06_COLLECTION_CONSUMER_MISSING' -Message 'H-06 must declare multi_competitor_collection as Stage7 formal consumer output.' -Path 'handoff/stage6_to_stage7/contract.json'
    }
}
if ($h07Contract) {
    foreach ($objectName in @('multi_competitor_collection')) {
        if (@($h07Contract.producer_objects) -notcontains $objectName) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H07_COLLECTION_PRODUCER_MISSING' -Message "H-07 must declare $objectName in producer_objects." -Path 'handoff/stage7_to_stage8/contract.json'
        }
    }
    foreach ($objectName in @('contact_candidate_collection', 'contact_selection_trace')) {
        if (@($h07Contract.consumer_objects) -notcontains $objectName) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H07_COLLECTION_CONSUMER_MISSING' -Message "H-07 must declare $objectName in consumer_objects." -Path 'handoff/stage7_to_stage8/contract.json'
        }
    }
    foreach ($fieldName in @('multi_competitor_collection_id_optional', 'winning_competitor_candidate_id_optional', 'winning_challenger_profile_id_optional')) {
        Test-HandoffOptionalField -Contract $h07Contract -ContractPath 'handoff/stage7_to_stage8/contract.json' -FieldName $fieldName
    }
}

if (-not $stage7ServiceText.Contains('multi_competitor_collection')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE7_COLLECTION_RUNTIME_MISSING' -Message 'Stage7 runtime must emit multi_competitor_collection.' -Path 'src/stage7_sales/service.py'
}
foreach ($fieldName in @('multi_competitor_collection_id_optional', 'winning_competitor_candidate_id_optional', 'winning_challenger_profile_id_optional')) {
    if (-not $stage7ServiceText.Contains($fieldName)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE7_COLLECTION_HANDOFF_PROJECTION_MISSING' -Message "Stage7 must project $fieldName." -Path 'src/stage7_sales/service.py'
    }
}
foreach ($token in @('contact_candidate_collection', 'contact_selection_trace', 'reselect_history')) {
    if (-not $stage8ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE8_COLLECTION_RUNTIME_MISSING' -Message "Stage8 runtime must materially use $token." -Path 'src/stage8_outreach/service.py'
    }
}
if (-not $stage8ServiceText.Contains('records.get("multi_competitor_collection")')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H07_OPTIONAL_RUNTIME_CONSUMER_MISSING' -Message 'Stage8 must explicitly consume H-07 optional producer multi_competitor_collection via records.get().' -Path 'src/stage8_outreach/service.py'
}
if ($h08Contract -and @($h08Contract.producer_objects) -notcontains 'outreach_plan') {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H08_OPTIONAL_PRODUCER_DECLARATION_MISSING' -Message 'H-08 must keep outreach_plan in producer_objects because Stage9 optionally consumes it.' -Path 'handoff/stage8_to_stage9/contract.json'
}
foreach ($token in @('records.get("outreach_plan")', 'if outreach_plan else None')) {
    if (-not $stage9ServiceText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'H08_OPTIONAL_RUNTIME_CONSUMER_DRIFT' -Message "Stage9 must keep optional H-08 outreach_plan consumption token $token." -Path 'src/stage9_delivery/service.py'
    }
}

function Find-PythonCommand {
    foreach ($candidate in @(
        @{ executable = 'python'; arguments = @() },
        @{ executable = 'py'; arguments = @('-3') },
        @{ executable = 'py'; arguments = @() }
    )) {
        if (Get-Command $candidate.executable -ErrorAction SilentlyContinue) {
            return $candidate
        }
    }
    return $null
}

# FR-01: release_level single vocabulary
$legacyToken = 'EXTERNAL_LEADPACK_DELIVERABLE'
$legacyScanFiles = @{
    'docs/L0.md' = $l0Text
    'docs/D5_页面导出与人工复核规范.md' = $d5Text
    'docs/D6_字段策略字典与客户交付字段规范.md' = $d6Text
    'docs/D13_公开可查边界能力清单.md' = $d13Text
    'contracts/enums/enum_catalog.json' = if ($enumCatalog) { $enumCatalog | ConvertTo-Json -Depth 100 } else { '' }
    'contracts/ui/export_template_catalog.json' = if ($exportTemplates) { $exportTemplates | ConvertTo-Json -Depth 50 } else { '' }
    'control/approval_chain_semantic_mapping.yaml' = $approvalMappingText
}

foreach ($entry in $legacyScanFiles.GetEnumerator()) {
    if ($entry.Value -and $entry.Value.Contains($legacyToken)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LEGACY_RELEASE_LEVEL_TOKEN' -Message "Legacy token $legacyToken must not appear in current formal surface." -Path $entry.Key
    }
}

if ($enumCatalog) {
    $releaseEnum = @($enumCatalog.enums | Where-Object enum_name -eq 'release_level')
    if ($releaseEnum.Count -ne 1) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RELEASE_LEVEL_ENUM_MISSING' -Message 'release_level enum must exist exactly once.' -Path 'contracts/enums/enum_catalog.json'
    }
    else {
        $expectedReleaseLevels = @('DEV_ALLOWED', 'INTERNAL_OPERABLE', 'LEADPACK_DELIVERABLE', 'EXTERNAL_BLOCKED')
        $actualReleaseLevels = @($releaseEnum[0].values | ForEach-Object { $_.value })
        if (-not (Set-Equals -Expected $expectedReleaseLevels -Actual $actualReleaseLevels)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RELEASE_LEVEL_ENUM_DRIFT' -Message "release_level enum must equal: $($expectedReleaseLevels -join '/'). Actual: $($actualReleaseLevels -join '/')" -Path 'contracts/enums/enum_catalog.json'
        }
    }
}

if ($exportTemplates) {
    foreach ($templateId in @('leadpack_report', 'external_action_assist_pack')) {
        $template = @($exportTemplates.templates | Where-Object templateId -eq $templateId | Select-Object -First 1)
        if ($template.Count -eq 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXPORT_TEMPLATE_MISSING' -Message "Export template $templateId is missing." -Path 'contracts/ui/export_template_catalog.json'
            continue
        }
        if ($template[0].minimumReleaseLevel -ne 'LEADPACK_DELIVERABLE') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXPORT_TEMPLATE_RELEASE_DRIFT' -Message "$templateId must use LEADPACK_DELIVERABLE." -Path 'contracts/ui/export_template_catalog.json'
        }
    }
}

foreach ($requiredToken in @('LEADPACK_DELIVERABLE', 'EXTERNAL_BLOCKED')) {
    if (-not $l0Text.Contains($requiredToken)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'L0_RELEASE_LAYER_MISSING' -Message "L0 must contain release layer token $requiredToken." -Path 'docs/L0.md'
    }
    if (-not $d13Text.Contains($requiredToken)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D13_RELEASE_LAYER_MISSING' -Message "D13 must contain release layer token $requiredToken." -Path 'docs/D13_公开可查边界能力清单.md'
    }
}

if (-not ($approvalMappingText -match 'client_report_release:[\s\S]*?release_level:\s*"LEADPACK_DELIVERABLE"')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'APPROVAL_MAPPING_DRIFT' -Message 'client_report_release must map to LEADPACK_DELIVERABLE.' -Path 'control/approval_chain_semantic_mapping.yaml'
}
if (-not ($approvalMappingText -match 'external_action_release:[\s\S]*?release_level:\s*"LEADPACK_DELIVERABLE"')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'APPROVAL_MAPPING_DRIFT' -Message 'external_action_release must map to LEADPACK_DELIVERABLE.' -Path 'control/approval_chain_semantic_mapping.yaml'
}
if (-not ($approvalMappingText -match 'external_api_release:[\s\S]*?release_level:\s*"EXTERNAL_BLOCKED"')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'APPROVAL_MAPPING_DRIFT' -Message 'external_api_release must map to EXTERNAL_BLOCKED.' -Path 'control/approval_chain_semantic_mapping.yaml'
}

if ($releaseGates) {
    $externalApiGate = @($releaseGates.gates | Where-Object releaseGateId -eq 'external_api_release' | Select-Object -First 1)
    if ($externalApiGate.Count -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXTERNAL_API_GATE_MISSING' -Message 'external_api_release gate must exist.' -Path 'contracts/release/release_gates.json'
    }
    else {
        if ($externalApiGate[0].surface -ne 'RESTRICTED_RELEASE') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXTERNAL_API_GATE_SURFACE_DRIFT' -Message 'external_api_release surface must be RESTRICTED_RELEASE.' -Path 'contracts/release/release_gates.json'
        }
        if ($externalApiGate[0].minimumReleaseLevel -ne 'EXTERNAL_BLOCKED') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXTERNAL_API_GATE_RELEASE_DRIFT' -Message 'external_api_release minimumReleaseLevel must be EXTERNAL_BLOCKED.' -Path 'contracts/release/release_gates.json'
        }
        if ($externalApiGate[0].approvalChainId -ne 'external_api_release') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXTERNAL_API_GATE_APPROVAL_DRIFT' -Message 'external_api_release approvalChainId must remain external_api_release.' -Path 'contracts/release/release_gates.json'
        }
        if (-not [bool]$externalApiGate[0].blockedByDefault) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXTERNAL_API_GATE_BLOCK_DEFAULT_MISSING' -Message 'external_api_release must stay blockedByDefault=true.' -Path 'contracts/release/release_gates.json'
        }
    }
}

$externalApiGateLine = [string](@($d7Text -split "`r?`n" | Where-Object { $_ -match '^\| `external_api_release` ' } | Select-Object -First 1))
if (-not $externalApiGateLine) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D7_EXTERNAL_API_ROW_MISSING' -Message 'D7 must define the external_api_release row.' -Path 'docs/D7_对象级交付矩阵与外发治理规范.md'
}
else {
    if (-not $externalApiGateLine.Contains('EXTERNAL_BLOCKED')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D7_EXTERNAL_API_RELEASE_DRIFT' -Message 'D7 external_api_release row must use EXTERNAL_BLOCKED.' -Path 'docs/D7_对象级交付矩阵与外发治理规范.md'
    }
    if ($externalApiGateLine.Contains('CLIENT_VISIBLE') -or $externalApiGateLine.Contains('LEADPACK_DELIVERABLE')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D7_EXTERNAL_API_RELEASE_DRIFT' -Message 'D7 external_api_release row must not imply client/external release.' -Path 'docs/D7_对象级交付矩阵与外发治理规范.md'
    }
}

# FR-02: stage8 compliance field alignment
$expectedComplianceFields = @(
    'contact_target.contact_legal_basis',
    'contact_target.frequency_policy_state',
    'contact_target.quiet_hours_policy_state',
    'contact_target.opt_out_state',
    'contact_target.channel_policy_status',
    'contact_target.reasonable_expectation_status'
)

if ($fieldPolicy) {
    foreach ($fieldPath in $expectedComplianceFields) {
        $entry = @($fieldPolicy.entries | Where-Object fieldPath -eq $fieldPath | Select-Object -First 1)
        if ($entry.Count -eq 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FIELD_POLICY_ENTRY_MISSING' -Message "Missing Stage 8 compliance field entry: $fieldPath" -Path 'contracts/governance/field_policy_dictionary.json'
            continue
        }

        if ($entry[0].fieldClass -ne 'GOVERNANCE_RESTRICTED') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FIELD_POLICY_CLASS_DRIFT' -Message "$fieldPath must be GOVERNANCE_RESTRICTED." -Path 'contracts/governance/field_policy_dictionary.json'
        }
        if ($entry[0].requiredReleaseLevel -ne 'INTERNAL_OPERABLE') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FIELD_POLICY_RELEASE_DRIFT' -Message "$fieldPath must stay at INTERNAL_OPERABLE." -Path 'contracts/governance/field_policy_dictionary.json'
        }

        $allowedSurfaces = @($entry[0].allowedSurfaces)
        if (-not (Set-Equals -Expected @('INTERNAL_OPERATIONS', 'GOVERNANCE_ONLY') -Actual $allowedSurfaces)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'FIELD_POLICY_SURFACE_DRIFT' -Message "$fieldPath must only allow INTERNAL_OPERATIONS/GOVERNANCE_ONLY. Actual: $($allowedSurfaces -join '/')" -Path 'contracts/governance/field_policy_dictionary.json'
        }
    }
}

if (-not $d6Text.Contains('[D6-R-056]')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D6_ALIGNMENT_APPENDIX_MISSING' -Message 'D6-R-056 stage8 compliance appendix is required.' -Path 'docs/D6_字段策略字典与客户交付字段规范.md'
}
foreach ($token in $expectedComplianceFields) {
    if (-not $d6Text.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D6_ALIGNMENT_FIELD_MISSING' -Message "D6 alignment appendix must mention $token." -Path 'docs/D6_字段策略字典与客户交付字段规范.md'
    }
}
if (-not $d7Text.Contains('[D7-R-063]')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D7_ALIGNMENT_APPENDIX_MISSING' -Message 'D7-R-063 stage8 compliance delivery appendix is required.' -Path 'docs/D7_对象级交付矩阵与外发治理规范.md'
}
if (-not $d7Text.Contains('Stage 8 合规判定字段') -or -not $d7Text.Contains('LEADPACK_DELIVERABLE') -or -not $d7Text.Contains('BLOCK')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D7_ALIGNMENT_TEXT_DRIFT' -Message 'D7 must explicitly mark stage8 compliance decision fields as blocked from LeadPack/external delivery.' -Path 'docs/D7_对象级交付矩阵与外发治理规范.md'
}
if (-not $d9Text.Contains('[D9-R-071]')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D9_ALIGNMENT_APPENDIX_MISSING' -Message 'D9-R-071 stage8 compliance consumption appendix is required.' -Path 'docs/D9_联系对象与销售触达规范.md'
}
foreach ($token in @('contact_legal_basis', 'frequency_policy_state', 'quiet_hours_policy_state', 'opt_out_state', 'channel_policy_status', 'reasonable_expectation_status')) {
    if (-not $d9Text.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D9_ALIGNMENT_FIELD_MISSING' -Message "D9 alignment appendix must mention $token." -Path 'docs/D9_联系对象与销售触达规范.md'
    }
}
foreach ($legacyD9Token in @('reasonable_expectation_state', 'channel_policy_state', 'PASS / REVIEW / BLOCK')) {
    if ($d9Text.Contains($legacyD9Token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'D9_LEGACY_STAGE8_TOKEN' -Message "D9 must not retain legacy Stage 8 token: $legacyD9Token" -Path 'docs/D9_联系对象与销售触达规范.md'
    }
}

# FR-03: control state alignment
$currentTaskPhase = Get-RegexValue -Text $currentTaskText -Pattern '^currentPhase:\s*"([^"]+)"'
$currentTaskState = Get-RegexValue -Text $currentTaskText -Pattern '^current_state:\s*"([^"]+)"'
$repoPhase = Get-RegexValue -Text $repoStatusText -Pattern '^Current Phase:\s*(.+)$'
$repoState = Get-RegexValue -Text $repoStatusText -Pattern '^Current Readiness Conclusion:\s*(.+)$'
$milestonePhase = Get-RegexValue -Text $milestoneText -Pattern '^phase:\s*"([^"]+)"'
$milestoneState = Get-RegexValue -Text $milestoneText -Pattern '^\s+current_readiness_conclusion:\s*"([^"]+)"'
$boardPhase = Get-RegexValue -Text $statusBoardText -Pattern '^- 当前阶段：`([^`]+)`'
$boardState = Get-RegexValue -Text $statusBoardText -Pattern '^- 当前判断：`([^`]+)`'
$launchRepoState = Get-RegexValue -Text $launchAdjudicationText -Pattern '^- 当前仓库总体 readiness：`([^`]+)`'
$releaseManifestState = Get-RegexValue -Text $releaseManifestText -Pattern '^\s+repo_readiness:\s*"([^"]+)"'
$modelReleaseManifestState = Get-RegexValue -Text $modelReleaseManifestText -Pattern '^\s+repo_readiness:\s*"([^"]+)"'
$currentTaskTaskId = Get-RegexValue -Text $currentTaskText -Pattern '^\s+task_id:\s*"([^"]+)"'
$currentTaskTitle = Get-RegexValue -Text $currentTaskText -Pattern '^\s+title:\s*"([^"]+)"'
$currentTaskObjective = Get-RegexValue -Text $currentTaskText -Pattern '^\s+objective:\s*"([^"]+)"'
$currentTaskPacketId = Get-RegexValue -Text $currentTaskText -Pattern '^\s+packet_id:\s*"([^"]+)"'
$currentTaskSubpacketId = Get-RegexValue -Text $currentTaskText -Pattern '^\s+subpacket_id:\s*"([^"]+)"'
$repoWorkstream = Get-RegexValue -Text $repoStatusText -Pattern '^Current Workstream:\s*(.+)$'
$statusBoardReason = Get-RegexValue -Text $statusBoardText -Pattern '^- 主要原因：(.+)$'
$boardCandidateGap = Get-RegexValue -Text $statusBoardText -Pattern '^- 当前是否 candidate-gap：`([^`]+)`'
$boardStrategicBranch = Get-RegexValue -Text $statusBoardText -Pattern '^- 当前是否 strategic-branch：`([^`]+)`'
$boardClosureReview = Get-RegexValue -Text $statusBoardText -Pattern '^- 当前 closure review：`([^`]+)`'
$boardMainlineSelection = Get-RegexValue -Text $statusBoardText -Pattern '^- 当前 mainline selection：`([^`]+)`'
$launchCandidateGap = Get-RegexValue -Text $launchAdjudicationText -Pattern '^- 当前是否 candidate-gap：`([^`]+)`'
$launchStrategicBranch = Get-RegexValue -Text $launchAdjudicationText -Pattern '^- 当前是否 strategic-branch：`([^`]+)`'
$launchClosureReview = Get-RegexValue -Text $launchAdjudicationText -Pattern '^- 当前 closure review：`([^`]+)`'
$launchMainlineSelection = Get-RegexValue -Text $launchAdjudicationText -Pattern '^- 当前 mainline selection：`([^`]+)`'
$taskPacketLibrarySource = Get-RegexValue -Text $taskPacketLibraryText -Pattern '^\s*formal_task_packet_source:\s*(.+)$'
$canonicalReadiness = 'READY_FOR_POST-REPAIR_MAINLINE_SELECTION'
$legacyBatchTokens = @('FINAL_BLOCKERS_P01_P06', 'P-01~P-06', 'FR-01~FR-05')

if ($currentTaskText.Contains('AUTO_DEV_NAVIGATION_PACK')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CURRENT_TASK_STALE' -Message 'current_task.yaml must not remain on AUTO_DEV_NAVIGATION_PACK.' -Path 'control/current_task.yaml'
}

$phaseValues = @($currentTaskPhase, $repoPhase, $milestonePhase, $boardPhase) | Where-Object { $_ }
if ($phaseValues.Count -ne 4 -or @($phaseValues | Select-Object -Unique).Count -ne 1) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PHASE_ALIGNMENT_DRIFT' -Message "current_task/repo_status/milestone/status board phase must match. Values: $($phaseValues -join ' | ')" -Path 'control/current_task.yaml'
}

$readinessValues = @(
    $currentTaskState,
    $repoState,
    $milestoneState,
    $boardState,
    $launchRepoState,
    $releaseManifestState,
    $modelReleaseManifestState
) | Where-Object { $_ }
if ($readinessValues.Count -ne 7 -or @($readinessValues | Select-Object -Unique).Count -ne 1) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'READINESS_ALIGNMENT_DRIFT' -Message "current_task/repo_status/milestone/status board/opening/release/model readiness must match. Values: $($readinessValues -join ' | ')" -Path 'control/current_task.yaml'
}
elseif ($readinessValues[0] -ne $canonicalReadiness) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'READINESS_CANONICAL_TOKEN_DRIFT' -Message "Current canonical readiness must be $canonicalReadiness. Actual: $($readinessValues[0])" -Path 'control/current_task.yaml'
}

if (-not $milestoneText.Contains('docs_layer_semantics:')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DOCS_LAYER_SEMANTICS_MISSING' -Message 'milestone_status.yaml must explain docs_layer semantics.' -Path 'control/milestone_status.yaml'
}
if (-not $statusBoardText.Contains('docs_layer=EFFECTIVE')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DOCS_LAYER_SEMANTICS_MISSING' -Message '状态板 must explain docs_layer=EFFECTIVE semantics.' -Path 'docs/文档与资产状态板.md'
}
if (-not $repoStatusText.Contains('candidate navigation asset')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'NAVIGATION_ASSET_STATUS_MISSING' -Message 'repo_status must mark AX9S as candidate navigation asset.' -Path 'control/repo_status.md'
}
if (-not $ax9sText.Contains('候选导航资产')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'NAVIGATION_ASSET_STATUS_MISSING' -Message 'AX9S route map must mark itself as candidate navigation asset.' -Path 'docs/AX9S_开发执行路由图.md'
}
if (-not $ax9sText.Contains('control/current_task.yaml') -or -not $ax9sText.Contains('当前 active 执行任务')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIQUE_ACTIVE_TASK_SOURCE_DRIFT' -Message 'AX9S route map must keep control/current_task.yaml as the unique active task source.' -Path 'docs/AX9S_开发执行路由图.md'
}
if ($taskPacketLibrarySource -ne 'control/current_task.yaml#currentTask.task_packet') {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIQUE_ACTIVE_TASK_SOURCE_DRIFT' -Message 'task_packet_library formal_task_packet_source must point to control/current_task.yaml#currentTask.task_packet.' -Path 'control/task_packet_library.yaml'
}
if (-not $currentTaskText.Contains('current_task -> task_packet_library -> repo_status')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIQUE_ACTIVE_TASK_SOURCE_DRIFT' -Message 'current_task.yaml must preserve the current_task -> task_packet_library -> repo_status active-source priority note.' -Path 'control/current_task.yaml'
}
$activeTaskIdentityValues = @(
    $currentTaskTaskId,
    $currentTaskPacketId,
    $currentTaskSubpacketId
) | Where-Object { $_ }
if ($activeTaskIdentityValues.Count -ne 3 -or @($activeTaskIdentityValues | Select-Object -Unique).Count -ne 1) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'ACTIVE_TASK_IDENTITY_DRIFT' -Message "current_task task_id/packet_id/subpacket_id must be single-sourced. Values: $($activeTaskIdentityValues -join ' | ')" -Path 'control/current_task.yaml'
}
if (-not $repoWorkstream) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REPO_STATUS_WORKSTREAM_DRIFT' -Message 'repo_status.md must declare the active governance workstream.' -Path 'control/repo_status.md'
}
else {
    $normalizedTaskId = ($currentTaskTaskId -replace '[_\-\s]+', '').ToUpperInvariant()
    $normalizedWorkstream = ($repoWorkstream -replace '[_\-\s]+', '').ToUpperInvariant()
    if ($normalizedTaskId -and -not $normalizedWorkstream.Contains($normalizedTaskId)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REPO_STATUS_WORKSTREAM_DRIFT' -Message 'repo_status.md Current Workstream must carry the active task id.' -Path 'control/repo_status.md'
    }
    if ($repoWorkstream -match 'AUTHORITY[-_ ]CONVERGENCE|CLOSEOUT|ADMIN') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REPO_STATUS_WORKSTREAM_STALE' -Message 'repo_status.md Current Workstream must not remain on legacy closeout/admin wording.' -Path 'control/repo_status.md'
    }
}

if (-not $statusBoardReason) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STATUS_BOARD_REASON_MISSING' -Message '状态板 must declare the main reason for the current active packet.' -Path 'docs/文档与资产状态板.md'
}
elseif ($statusBoardReason -match 'AUTHORITY[-_ ]CONVERGENCE|CLOSEOUT|ADMIN') {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STATUS_BOARD_REASON_STALE' -Message '状态板主要原因 must not remain on legacy closeout/admin wording.' -Path 'docs/文档与资产状态板.md'
}

foreach ($layeredDocState in @(
    @{ path = 'docs/文档与资产状态板.md'; field = 'candidate-gap'; actual = $boardCandidateGap; expected = '否' },
    @{ path = 'docs/文档与资产状态板.md'; field = 'strategic-branch'; actual = $boardStrategicBranch; expected = '否' },
    @{ path = 'docs/文档与资产状态板.md'; field = 'closure review'; actual = $boardClosureReview; expected = '已关闭' },
    @{ path = 'docs/文档与资产状态板.md'; field = 'mainline selection'; actual = $boardMainlineSelection; expected = '就绪' },
    @{ path = 'docs/正式业务代码开发开工裁决页.md'; field = 'candidate-gap'; actual = $launchCandidateGap; expected = '否' },
    @{ path = 'docs/正式业务代码开发开工裁决页.md'; field = 'strategic-branch'; actual = $launchStrategicBranch; expected = '否' },
    @{ path = 'docs/正式业务代码开发开工裁决页.md'; field = 'closure review'; actual = $launchClosureReview; expected = '已关闭' },
    @{ path = 'docs/正式业务代码开发开工裁决页.md'; field = 'mainline selection'; actual = $launchMainlineSelection; expected = '就绪' }
)) {
    if (-not $layeredDocState.actual) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAYERED_STATE_DOC_VALUE_MISSING' -Message "$($layeredDocState.field) value is missing." -Path $layeredDocState.path
    }
    elseif ($layeredDocState.actual -ne $layeredDocState.expected) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAYERED_STATE_DOC_VALUE_DRIFT' -Message "$($layeredDocState.field) must be $($layeredDocState.expected). Actual: $($layeredDocState.actual)" -Path $layeredDocState.path
    }
}

$layeredStateSpecs = @(
    @{ name = 'candidate_gap_active'; expected = 'false' },
    @{ name = 'strategic_branch_active'; expected = 'false' },
    @{ name = 'closure_review_active'; expected = 'false' },
    @{ name = 'closure_review_completed'; expected = 'true' },
    @{ name = 'mainline_selection_ready'; expected = 'true' }
)
foreach ($spec in $layeredStateSpecs) {
    $pattern = '^\s+' + [regex]::Escape($spec.name) + ':\s*(true|false)'
    $values = @(
        Get-RegexValue -Text $currentTaskText -Pattern $pattern
        Get-RegexValue -Text $milestoneText -Pattern $pattern
        Get-RegexValue -Text $releaseManifestText -Pattern $pattern
        Get-RegexValue -Text $modelReleaseManifestText -Pattern $pattern
    ) | Where-Object { $_ }
    if ($values.Count -ne 4 -or @($values | Select-Object -Unique).Count -ne 1) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAYERED_STATE_ALIGNMENT_DRIFT' -Message "$($spec.name) must match across current_task/milestone/release/model manifests. Values: $($values -join ' | ')" -Path 'control/current_task.yaml'
    }
    elseif ($values[0].ToLowerInvariant() -ne $spec.expected) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAYERED_STATE_EXPECTATION_DRIFT' -Message "$($spec.name) must be $($spec.expected) for the current post-repair mainline-selection state." -Path 'control/current_task.yaml'
    }
}

foreach ($docExpectation in @(
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'Candidate Gap Active: false' },
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'Strategic Branch Active: false' },
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'Closure Review Active: false' },
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'Closure Review Completed: true' },
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'Mainline Selection Ready: true' }
)) {
    if (-not $docExpectation.text.Contains($docExpectation.token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAYERED_STATE_DOC_TEXT_MISSING' -Message "Missing layered-state token: $($docExpectation.token)" -Path $docExpectation.path
    }
}

foreach ($redlineExpectation in @(
    @{ path = 'control/current_task.yaml'; text = $currentTaskText; token = 'external software release remains blocked' },
    @{ path = 'control/current_task.yaml'; text = $currentTaskText; token = 'stage8 real execution remains governed / approval-gated / blocked by default' },
    @{ path = 'control/current_task.yaml'; text = $currentTaskText; token = 'stage9 real payment/delivery remains governed / approval-gated / blocked by default' },
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'External software release remains blocked' },
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'Stage 8 real execution remains governed / approval-gated / blocked by default' },
    @{ path = 'control/repo_status.md'; text = $repoStatusText; token = 'Stage 9 real payment/delivery/refund remains governed / approval-gated / blocked by default' },
    @{ path = 'docs/文档与资产状态板.md'; text = $statusBoardText; token = 'external software release：`BLOCKED`' },
    @{ path = 'docs/文档与资产状态板.md'; text = $statusBoardText; token = 'Stage 8 real execution：governed / approval-gated / blocked by default' },
    @{ path = 'docs/文档与资产状态板.md'; text = $statusBoardText; token = 'Stage 9 real payment / delivery / refund：governed / approval-gated / blocked by default' },
    @{ path = 'docs/正式业务代码开发开工裁决页.md'; text = $launchAdjudicationText; token = '外部软件 release 仍为 BLOCKED' },
    @{ path = 'docs/正式业务代码开发开工裁决页.md'; text = $launchAdjudicationText; token = 'Stage 8 / Stage 9 高风险执行仍 governed / approval-gated / blocked by default' }
)) {
    if (-not $redlineExpectation.text.Contains($redlineExpectation.token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REDLINE_BOUNDARY_DRIFT' -Message "Missing redline boundary token: $($redlineExpectation.token)" -Path $redlineExpectation.path
    }
}

foreach ($legacyToken in $legacyBatchTokens) {
    foreach ($entry in @(
        @{ path = 'control/current_task.yaml'; field = 'task_id'; value = $currentTaskTaskId },
        @{ path = 'control/current_task.yaml'; field = 'title'; value = $currentTaskTitle },
        @{ path = 'control/current_task.yaml'; field = 'objective'; value = $currentTaskObjective },
        @{ path = 'control/repo_status.md'; field = 'Current Workstream'; value = $repoWorkstream },
        @{ path = 'docs/文档与资产状态板.md'; field = '主要原因'; value = $statusBoardReason }
    )) {
        if ($entry.value -and [string]$entry.value -match [regex]::Escape($legacyToken)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STATE_TEXT_LEGACY_BATCH_DRIFT' -Message "$($entry.field) must not retain legacy batch token: $legacyToken" -Path $entry.path
        }
    }
}

# AUD-01 / AUD-02 / AUD-03: ruling index, reference index, launch adjudication scope
$trackedRulingDocs = @(
    @{ docCode = 'D6'; path = 'docs/D6_字段策略字典与客户交付字段规范.md'; text = $d6Text },
    @{ docCode = 'D7'; path = 'docs/D7_对象级交付矩阵与外发治理规范.md'; text = $d7Text },
    @{ docCode = 'D9'; path = 'docs/D9_联系对象与销售触达规范.md'; text = $d9Text }
)

foreach ($trackedDoc in $trackedRulingDocs) {
    $docCode = $trackedDoc.docCode
    $definedIds = @(Get-FormalDecisionIds -Text $trackedDoc.text -DocCode $docCode)
    $mainIds = @($definedIds | Where-Object { $_ -notmatch '-[A-Z]$' } | Sort-Object -Unique)
    $subIds = @($definedIds | Where-Object { $_ -match '-[A-Z]$' } | Sort-Object -Unique)
    $summaryRow = Get-RulingIndexSummaryRow -RulingIndexText $rulingIndexText -DocCode $docCode

    if (-not $summaryRow) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULING_INDEX_SUMMARY_ROW_MISSING' -Message "$docCode summary row is missing from 裁决总表.md." -Path 'docs/裁决总表.md'
        continue
    }

    $actualMaxMainId = @($mainIds | Sort-Object { Get-DecisionNumericTail $_ })[-1]
    if ($summaryRow.endId -ne $actualMaxMainId) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULING_INDEX_END_ID_DRIFT' -Message "$docCode summary row end id must be $actualMaxMainId. Actual: $($summaryRow.endId)" -Path 'docs/裁决总表.md'
    }
    if ($summaryRow.count -ne $mainIds.Count) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULING_INDEX_COUNT_DRIFT' -Message "$docCode summary row count must be $($mainIds.Count). Actual: $($summaryRow.count)" -Path 'docs/裁决总表.md'
    }
    if ($actualMaxMainId -and (-not $rulingIndexText.Contains($actualMaxMainId))) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULING_INDEX_MAIN_ID_MISSING' -Message "$docCode latest formal decision id $actualMaxMainId must be mentioned in 裁决总表.md." -Path 'docs/裁决总表.md'
    }

    foreach ($subId in $subIds) {
        if (-not $rulingIndexText.Contains($subId)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RULING_INDEX_SUB_ID_MISSING' -Message "$docCode sub decision id $subId must be indexed in 裁决总表.md." -Path 'docs/裁决总表.md'
        }
    }
}

if (-not $referenceIndex) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_MISSING' -Message 'control/reference_index.json must exist and be parseable.' -Path 'control/reference_index.json'
}
else {
    if (-not ($referenceIndex.PSObject.Properties.Name -contains 'formalDocs')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_SECTION_MISSING' -Message 'reference_index.json must define formalDocs.' -Path 'control/reference_index.json'
    }
    else {
        $formalDocs = $referenceIndex.formalDocs
        $expectedFormalDocs = @{
            L0 = 'docs/L0.md'
            judgmentIndex = 'docs/裁决总表.md'
            D1 = 'docs/D1_研发_Codex执行手册.md'
            D2 = 'docs/D2_正式对象契约与字段字典.md'
            D3 = 'docs/D3_正式规则码总表与判定说明书.md'
            D4 = 'docs/D4_OpenAPI接口契约.md'
            D5 = 'docs/D5_页面导出与人工复核规范.md'
            D6 = 'docs/D6_字段策略字典与客户交付字段规范.md'
            D7 = 'docs/D7_对象级交付矩阵与外发治理规范.md'
            D8 = 'docs/D8_真实竞争者识别可售对象与销售推进规范.md'
            D9 = 'docs/D9_联系对象与销售触达规范.md'
            D10 = 'docs/D10_订单支付交付与治理反馈规范.md'
            D11 = 'docs/D11_测试验收与金标回归清单.md'
            D12 = 'docs/D12_部署发布与运行治理规范.md'
            D13 = 'docs/D13_公开可查边界能力清单.md'
            D14 = 'docs/D14_AI模型治理规范.md'
        }
        foreach ($entry in $expectedFormalDocs.GetEnumerator()) {
            $actualValue = $null
            if ($formalDocs.PSObject.Properties.Name -contains $entry.Key) {
                $actualValue = [string]$formalDocs.($entry.Key)
            }
            if ($actualValue -ne $entry.Value) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_FORMAL_DOC_DRIFT' -Message "reference_index formalDocs.$($entry.Key) must equal $($entry.Value)." -Path 'control/reference_index.json'
            }
            elseif (-not (Test-RelativeAssetPath -RelativePath $actualValue)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_FORMAL_DOC_PATH_MISSING' -Message "reference_index formalDocs.$($entry.Key) path does not exist: $actualValue" -Path 'control/reference_index.json'
            }
        }
    }

    if (-not ($referenceIndex.PSObject.Properties.Name -contains 'formalSupportDocs')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_SECTION_MISSING' -Message 'reference_index.json must define formalSupportDocs.' -Path 'control/reference_index.json'
    }
    else {
        $formalSupportDocs = $referenceIndex.formalSupportDocs
        $expectedSupportDocs = @{
            statusBoard = 'docs/文档与资产状态板.md'
            techDecision = 'docs/技术实现决策页.md'
            launchAdjudication = 'docs/正式业务代码开发开工裁决页.md'
        }
        foreach ($entry in $expectedSupportDocs.GetEnumerator()) {
            $actualValue = $null
            if ($formalSupportDocs.PSObject.Properties.Name -contains $entry.Key) {
                $actualValue = [string]$formalSupportDocs.($entry.Key)
            }
            if ($actualValue -ne $entry.Value) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_SUPPORT_DOC_DRIFT' -Message "reference_index formalSupportDocs.$($entry.Key) must equal $($entry.Value)." -Path 'control/reference_index.json'
            }
            elseif (-not (Test-RelativeAssetPath -RelativePath $actualValue)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_SUPPORT_DOC_PATH_MISSING' -Message "reference_index formalSupportDocs.$($entry.Key) path does not exist: $actualValue" -Path 'control/reference_index.json'
            }
        }
    }

    if (-not ($referenceIndex.PSObject.Properties.Name -contains 'navigationAssets')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_SECTION_MISSING' -Message 'reference_index.json must define navigationAssets.' -Path 'control/reference_index.json'
    }
    else {
        $executionRouteMap = $referenceIndex.navigationAssets.executionRouteMap
        if (-not $executionRouteMap) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_NAV_ASSET_MISSING' -Message 'reference_index.json must include navigationAssets.executionRouteMap.' -Path 'control/reference_index.json'
        }
        else {
            if ([string]$executionRouteMap.path -ne 'docs/AX9S_开发执行路由图.md') {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_NAV_ASSET_DRIFT' -Message 'executionRouteMap.path must equal docs/AX9S_开发执行路由图.md.' -Path 'control/reference_index.json'
            }
            elseif (-not (Test-RelativeAssetPath -RelativePath ([string]$executionRouteMap.path))) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_NAV_ASSET_PATH_MISSING' -Message "executionRouteMap.path does not exist: $([string]$executionRouteMap.path)" -Path 'control/reference_index.json'
            }
            if ([string]$executionRouteMap.assetRole -ne 'candidate navigation asset') {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_NAV_ASSET_DRIFT' -Message 'executionRouteMap.assetRole must be candidate navigation asset.' -Path 'control/reference_index.json'
            }
            if ([bool]$executionRouteMap.formalStatusSource) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_NAV_ASSET_DRIFT' -Message 'executionRouteMap.formalStatusSource must be false.' -Path 'control/reference_index.json'
            }
        }
    }

    if (-not ($referenceIndex.PSObject.Properties.Name -contains 'formalStatusSources')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_SECTION_MISSING' -Message 'reference_index.json must define formalStatusSources.' -Path 'control/reference_index.json'
    }
    else {
        $formalStatusSources = $referenceIndex.formalStatusSources
        $expectedStatusSources = @{
            repoStatus = 'control/repo_status.md'
            currentTask = 'control/current_task.yaml'
            milestoneStatus = 'control/milestone_status.yaml'
            statusBoard = 'docs/文档与资产状态板.md'
            launchAdjudicationScope = 'docs/正式业务代码开发开工裁决页.md'
            releaseManifest = 'control/release_manifest.yaml'
            modelReleaseManifest = 'control/model_release_manifest.yaml'
        }
        foreach ($entry in $expectedStatusSources.GetEnumerator()) {
            $actualValue = $null
            if ($formalStatusSources.PSObject.Properties.Name -contains $entry.Key) {
                $actualValue = [string]$formalStatusSources.($entry.Key)
            }
            if ($actualValue -ne $entry.Value) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_STATUS_SOURCE_DRIFT' -Message "reference_index formalStatusSources.$($entry.Key) must equal $($entry.Value)." -Path 'control/reference_index.json'
            }
            elseif (-not (Test-RelativeAssetPath -RelativePath $actualValue)) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_STATUS_SOURCE_PATH_MISSING' -Message "reference_index formalStatusSources.$($entry.Key) path does not exist: $actualValue" -Path 'control/reference_index.json'
            }
        }
        if ($formalStatusSources.PSObject.Properties.Name -contains 'futureUnlockDecisionState') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_STATUS_SOURCE_DRIFT' -Message 'futureUnlockDecisionState must not remain in formalStatusSources after post-repair authority convergence.' -Path 'control/reference_index.json'
        }
    }

    if (-not ($referenceIndex.PSObject.Properties.Name -contains 'stateSyncSemantics')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_SECTION_MISSING' -Message 'reference_index.json must define stateSyncSemantics.' -Path 'control/reference_index.json'
    }
    else {
        $stateSyncSemantics = $referenceIndex.stateSyncSemantics
        $expectedStateSyncSemantics = @{
            canonicalReadiness = 'READY_FOR_POST-REPAIR_MAINLINE_SELECTION'
            conditionalGoScope = 'READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT'
            launchAdjudicationRole = 'conditional-go scope only'
            futureUnlockStateRole = 'historical decision snapshot only'
            routeMapRole = 'navigation only'
        }
        foreach ($entry in $expectedStateSyncSemantics.GetEnumerator()) {
            $actualValue = $null
            if ($stateSyncSemantics.PSObject.Properties.Name -contains $entry.Key) {
                $actualValue = [string]$stateSyncSemantics.($entry.Key)
            }
            if ($actualValue -ne $entry.Value) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'REFERENCE_INDEX_STATE_SYNC_SEMANTICS_DRIFT' -Message "reference_index stateSyncSemantics.$($entry.Key) must equal $($entry.Value)." -Path 'control/reference_index.json'
            }
        }
    }
}

if (-not $launchAdjudicationText.Contains('作用域说明')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAUNCH_ADJUDICATION_SCOPE_NOTE_MISSING' -Message '正式业务代码开发开工裁决页 must include a scope note.' -Path 'docs/正式业务代码开发开工裁决页.md'
}
if (-not $launchAdjudicationText.Contains('READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAUNCH_ADJUDICATION_SCOPE_NOTE_MISSING' -Message '开工裁决页 must keep READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT as the conditional-go scope.' -Path 'docs/正式业务代码开发开工裁决页.md'
}
if (-not $launchAdjudicationText.Contains($canonicalReadiness)) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAUNCH_ADJUDICATION_SCOPE_NOTE_MISSING' -Message "开工裁决页 must acknowledge $canonicalReadiness scope." -Path 'docs/正式业务代码开发开工裁决页.md'
}
if (
    (-not ($launchAdjudicationText -match '作用域说明[\s\S]*READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT')) -or
    (-not ($launchAdjudicationText -match '作用域说明[\s\S]*READY_FOR_POST-REPAIR_MAINLINE_SELECTION')) -or
    (-not ($launchAdjudicationText -match '作用域说明[\s\S]*(作用域不同|不同作用域|不冲突)'))
) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'LAUNCH_ADJUDICATION_SCOPE_NOTE_DRIFT' -Message '开工裁决页 scope note must explain that internal development conditional-go and post-repair mainline-selection readiness are different scopes.' -Path 'docs/正式业务代码开发开工裁决页.md'
}

# FR-04B: capability_mode matrix alignment
$expectedCapabilityModes = @(
    'PERMANENTLY_BLOCKED',
    'BUILDABLE_BUT_OFF_BY_DEFAULT',
    'INTERNAL_ONLY',
    'INTERNAL_GOVERNED',
    'APPROVAL_REQUIRED',
    'SHADOW_MODE',
    'DRY_RUN',
    'REAL_RUN_READY',
    'EMERGENCY_OFF'
)

foreach ($docCheck in @(
    @{ path = 'docs/D13_公开可查边界能力清单.md'; text = $d13Text },
    @{ path = 'docs/D14_AI模型治理规范.md'; text = $d14Text },
    @{ path = 'docs/技术实现决策页.md'; text = $techDecisionText }
)) {
    foreach ($mode in $expectedCapabilityModes) {
        if (-not $docCheck.text.Contains($mode)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_MODE_DOC_MISSING' -Message "$mode must be documented in the formal capability_mode surface." -Path $docCheck.path
        }
    }
}

if ($runtimePolicyCatalog) {
    $actualModes = @($runtimePolicyCatalog.capability_mode_vocabulary)
    if (-not (Set-Equals -Expected $expectedCapabilityModes -Actual $actualModes)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_MODE_VOCAB_DRIFT' -Message "runtime_policy_catalog capability_mode_vocabulary drift: $($actualModes -join '/')" -Path 'contracts/release/runtime_policy_catalog.json'
    }
    $expectedFamilies = @('external_source','contact_enrichment','execution_vendor','model_provider','tool_provider','stage8_execution','stage9_execution','delivery_export_variants','risky_automation','emergency_off')
    $actualFamilies = @($runtimePolicyCatalog.capability_families | ForEach-Object { $_.family_id })
    foreach ($family in $expectedFamilies) {
        if ($actualFamilies -notcontains $family) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_MODE_FAMILY_MISSING' -Message "runtime policy must contain capability family $family." -Path 'contracts/release/runtime_policy_catalog.json'
        }
    }
    foreach ($family in @($runtimePolicyCatalog.capability_families)) {
        if ($expectedCapabilityModes -notcontains [string]$family.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_MODE_INVALID' -Message "Invalid current_capability_mode $($family.current_capability_mode) for family $($family.family_id)." -Path 'contracts/release/runtime_policy_catalog.json'
        }
    }
}

if ($deploymentMatrix) {
    foreach ($tier in @($deploymentMatrix.environment_tiers)) {
        if (-not $tier.default_capability_modes) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DEPLOYMENT_CAPABILITY_MODE_MISSING' -Message "Environment tier $($tier.tier) must declare default_capability_modes." -Path 'contracts/release/deployment_matrix.json'
            continue
        }
        foreach ($mode in @($tier.default_capability_modes)) {
            if ($expectedCapabilityModes -notcontains [string]$mode) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'DEPLOYMENT_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $mode in tier $($tier.tier)." -Path 'contracts/release/deployment_matrix.json'
            }
        }
    }
}

if ($releaseGates) {
    if (-not [bool]$releaseGates.capability_mode_rules.non_override_release_layer) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RELEASE_GATE_CAPABILITY_MODE_DRIFT' -Message 'release_gates capability_mode_rules.non_override_release_layer must stay true.' -Path 'contracts/release/release_gates.json'
    }
    if (-not [bool]$releaseGates.capability_mode_rules.external_block_redline_kept) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'RELEASE_GATE_CAPABILITY_MODE_DRIFT' -Message 'release_gates must keep external_block_redline_kept=true.' -Path 'contracts/release/release_gates.json'
    }
}

if ($vendorRegistry) {
    foreach ($entry in @($vendorRegistry.entries)) {
        if (-not $entry.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'VENDOR_CAPABILITY_MODE_MISSING' -Message "Vendor $($entry.vendor_id) must declare current_capability_mode." -Path 'contracts/sales/vendor_registry_catalog.json'
            continue
        }
        if ($expectedCapabilityModes -notcontains [string]$entry.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'VENDOR_CAPABILITY_MODE_INVALID' -Message "Vendor $($entry.vendor_id) has invalid current_capability_mode $($entry.current_capability_mode)." -Path 'contracts/sales/vendor_registry_catalog.json'
        }
        if ([string]$entry.current_status -eq 'BLOCKED' -and [string]$entry.current_capability_mode -eq 'REAL_RUN_READY') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'VENDOR_CAPABILITY_MODE_REDLINE' -Message "Blocked vendor $($entry.vendor_id) cannot be REAL_RUN_READY." -Path 'contracts/sales/vendor_registry_catalog.json'
        }
    }
}

if ($sourceVendorUsagePolicy) {
    foreach ($policy in @($sourceVendorUsagePolicy.stagePolicies)) {
        if (-not $policy.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SOURCE_POLICY_CAPABILITY_MODE_MISSING' -Message "source vendor stage policy $($policy.stage_range)/$($policy.vendor_role) must declare current_capability_mode." -Path 'contracts/sales/source_vendor_usage_policy.json'
            continue
        }
        if ($expectedCapabilityModes -notcontains [string]$policy.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SOURCE_POLICY_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $($policy.current_capability_mode) in source vendor policy." -Path 'contracts/sales/source_vendor_usage_policy.json'
        }
    }
}

if ($channelVendorExecutionPolicy) {
    foreach ($entry in @($channelVendorExecutionPolicy.entries)) {
        if (-not $entry.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXECUTION_POLICY_CAPABILITY_MODE_MISSING' -Message "execution vendor entry $($entry.vendor_id)/stage$($entry.stage) must declare current_capability_mode." -Path 'contracts/sales/channel_vendor_execution_policy.json'
            continue
        }
        if ($expectedCapabilityModes -notcontains [string]$entry.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXECUTION_POLICY_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $($entry.current_capability_mode) in execution vendor policy." -Path 'contracts/sales/channel_vendor_execution_policy.json'
        }
        if ([bool]$entry.live_execution_enabled -and [string]$entry.current_capability_mode -ne 'REAL_RUN_READY') {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'EXECUTION_POLICY_LIVE_MODE_DRIFT' -Message "Live execution entry $($entry.vendor_id) must be REAL_RUN_READY." -Path 'contracts/sales/channel_vendor_execution_policy.json'
        }
    }
}

if ($contactPolicyCatalog) {
    if (-not $contactPolicyCatalog.capabilityModeVocabularyRef) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CONTACT_POLICY_CAPABILITY_MODE_REF_MISSING' -Message 'contact_policy_catalog must declare capabilityModeVocabularyRef.' -Path 'contracts/sales/contact_policy_catalog.json'
    }
    foreach ($mode in @($contactPolicyCatalog.outreachPolicy.approvalCapabilityModes + $contactPolicyCatalog.outreachPolicy.realRunReadyCapabilityModes + $contactPolicyCatalog.outreachPolicy.blockedCapabilityModes)) {
        if ($expectedCapabilityModes -notcontains [string]$mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CONTACT_POLICY_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $mode in contact_policy_catalog." -Path 'contracts/sales/contact_policy_catalog.json'
        }
    }
}

if ($contactChannelCatalog) {
    foreach ($entry in @($contactChannelCatalog.entries)) {
        foreach ($mode in @($entry.defaultCapabilityModeByChannelFamily.PSObject.Properties.Value)) {
            if ($expectedCapabilityModes -notcontains [string]$mode) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CONTACT_CHANNEL_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $mode in contact_channel_catalog." -Path 'contracts/sales/contact_channel_catalog.json'
            }
        }
    }
}

if ($modelCatalog) {
    foreach ($provider in @($modelCatalog.providers)) {
        if (-not $provider.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MODEL_PROVIDER_CAPABILITY_MODE_MISSING' -Message "Model provider $($provider.provider_id) must declare current_capability_mode." -Path 'contracts/model/model_catalog.json'
            continue
        }
        if ($expectedCapabilityModes -notcontains [string]$provider.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MODEL_PROVIDER_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $($provider.current_capability_mode) in model_catalog providers." -Path 'contracts/model/model_catalog.json'
        }
    }
    foreach ($model in @($modelCatalog.models)) {
        if (-not $model.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MODEL_CAPABILITY_MODE_MISSING' -Message "Model $($model.model_id) must declare current_capability_mode." -Path 'contracts/model/model_catalog.json'
        }
    }
}

if ($modelUsagePolicy) {
    foreach ($mode in @($modelUsagePolicy.capability_mode_matrix.PSObject.Properties.Value)) {
        if ($mode -is [string] -and ($expectedCapabilityModes -notcontains [string]$mode)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MODEL_USAGE_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $mode in model_usage_policy." -Path 'contracts/model/model_usage_policy.json'
        }
    }
}

if ($modelReleaseGates) {
    if (-not [bool]$modelReleaseGates.external_release_blocked) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MODEL_RELEASE_EXTERNAL_REDLINE' -Message 'model_release_gates must keep external_release_blocked=true.' -Path 'contracts/model/model_release_gates.json'
    }
}

if ($toolUsagePolicy) {
    foreach ($policy in @($toolUsagePolicy.policies)) {
        if (-not $policy.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TOOL_POLICY_CAPABILITY_MODE_MISSING' -Message "Tool usage policy $($policy.policy_id) must declare current_capability_mode." -Path 'contracts/model/tool_usage_policy_catalog.json'
            continue
        }
        if ($expectedCapabilityModes -notcontains [string]$policy.current_capability_mode) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'TOOL_POLICY_CAPABILITY_MODE_INVALID' -Message "Invalid capability_mode $($policy.current_capability_mode) in tool_usage_policy_catalog." -Path 'contracts/model/tool_usage_policy_catalog.json'
        }
    }
}

foreach ($requiredText in @(
    @{ path = 'control/runtime_inventory.yaml'; text = $runtimeInventoryText; token = 'capability_mode_vocabulary' },
    @{ path = 'control/model_release_manifest.yaml'; text = $modelReleaseManifestText; token = 'capability_mode_vocabulary_ref' }
)) {
    if (-not $requiredText.text.Contains($requiredText.token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_MODE_CONTROL_SURFACE_MISSING' -Message "Missing $($requiredText.token) on control surface." -Path $requiredText.path
    }
}
foreach ($runtimeToken in @('capability_mode_priority_order', 'action_intents:', 'decision_matrix:')) {
    if (-not $runtimeInventoryText.Contains($runtimeToken)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_MODE_RUNTIME_LAYER_MISSING' -Message "runtime_inventory must declare $runtimeToken for runtime permission resolution." -Path 'control/runtime_inventory.yaml'
    }
}
if ($writebackImpactPolicy) {
    if ([string]$writebackImpactPolicy.current_state -ne 'INTERNAL_V0_ACTIVE' -or -not [bool]$writebackImpactPolicy.runtime_executor_enabled) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_IMPACT_POLICY_DRIFT' -Message 'writeback impact policy must be INTERNAL_V0_ACTIVE with runtime_executor_enabled=true.' -Path 'contracts/governance/writeback_impact_policy.json'
    }
    if ([string]$writebackImpactPolicy.contract_state -ne 'FORMAL_CONTRACT_ACTIVE') {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_CONTRACT_STATE_DRIFT' -Message 'writeback impact policy must declare contract_state=FORMAL_CONTRACT_ACTIVE.' -Path 'contracts/governance/writeback_impact_policy.json'
    }
    if (-not ($writebackImpactPolicy.PSObject.Properties.Name -contains 'target_contracts')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_TARGET_CONTRACTS_MISSING' -Message 'writeback impact policy must define target_contracts.' -Path 'contracts/governance/writeback_impact_policy.json'
    }
    $contractSemantics = $writebackImpactPolicy.contract_semantics
    foreach ($contractFlag in @(
        'outcome_targets_authoritative',
        'governance_targets_additive_only',
        'payment_exception_targets_additive_only',
        'delivery_exception_targets_additive_only',
        'silent_override_outcome_targets_forbidden'
    )) {
        if (-not [bool]$contractSemantics.$contractFlag) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_CONTRACT_SEMANTICS_DRIFT' -Message "writeback impact policy must keep contract_semantics.$contractFlag=true." -Path 'contracts/governance/writeback_impact_policy.json'
        }
    }
}
if (-not $runtimeInventoryText.Contains('writeback_impact_executor:') -or -not $runtimeInventoryText.Contains('current_state: "INTERNAL_V0_ACTIVE"')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'WRITEBACK_IMPACT_RUNTIME_INVENTORY_MISSING' -Message 'runtime_inventory must explicitly declare active internal writeback impact executor state.' -Path 'control/runtime_inventory.yaml'
}
if (-not $modelReleaseManifestText.Contains('runtime_permission_layer:')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'MODEL_RELEASE_PERMISSION_LAYER_MISSING' -Message 'model_release_manifest must declare runtime_permission_layer binding.' -Path 'control/model_release_manifest.yaml'
}
foreach ($serviceCheck in @(
    @{ path = 'src/stage8_outreach/service.py'; text = $stage8ServiceText },
    @{ path = 'src/stage9_delivery/service.py'; text = $stage9ServiceText }
)) {
    foreach ($token in @('resolve_permissions(', 'permission_trace', 'permission_decision_state', 'permission_governance', 'evaluate_runtime_guards(', 'governance_trace', 'governance_decision_state', 'governance_additions')) {
        if (-not $serviceCheck.text.Contains($token)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_MODE_RUNTIME_CONSUMPTION_MISSING' -Message "$token must be consumed on risky Stage 8/9 service paths." -Path $serviceCheck.path
        }
    }
}
if (-not $pipelineText.Contains('_validate_handoff(') -or -not $pipelineText.Contains('evaluate_handoff_consumer(')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'HANDOFF_RUNTIME_PIPELINE_MISSING' -Message 'shared pipeline must validate H-01~H-04 consumer handoff semantics before downstream execution.' -Path 'src/shared/pipeline.py'
}
if (-not $stage6ServiceText.Contains('evaluate_handoff_consumer(') -or -not $stage7ServiceText.Contains('evaluate_handoff_consumer(') -or -not $stage8ServiceText.Contains('evaluate_handoff_consumer(') -or -not $stage9ServiceText.Contains('evaluate_handoff_consumer(')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'HANDOFF_RUNTIME_CONSUMER_MISSING' -Message 'Stage6-9 consumer services must call evaluate_handoff_consumer.' -Path 'src/shared/contracts_runtime.py'
}
if (-not $pipelineText.Contains('evaluate_handoff_consumer(') -or -not $stage6ServiceText.Contains('evaluate_object_semantics(') -or -not $stage7ServiceText.Contains('evaluate_object_semantics(') -or -not $stage8ServiceText.Contains('evaluate_object_semantics(') -or -not $stage9ServiceText.Contains('evaluate_object_semantics(')) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SEMANTIC_RUNTIME_CONSUMPTION_MISSING' -Message 'shared semantic validator must be consumed by pipeline and Stage6-9 services.' -Path 'src/shared/runtime_validator.py'
}
foreach ($token in @('evaluate_handoff_consumer(', 'evaluate_object_semantics(', 'SemanticValidationResult')) {
    if (-not $runtimeValidatorText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SEMANTIC_VALIDATOR_ENTRY_MISSING' -Message "$token must exist on shared runtime_validator." -Path 'src/shared/runtime_validator.py'
    }
}
foreach ($token in @('evaluate_handoff_consumer(', 'evaluate_object_semantics(')) {
    if (-not $contractsRuntimeText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CONTRACT_STORE_SEMANTIC_ENTRY_MISSING' -Message "$token must be exposed on ContractStore." -Path 'src/shared/contracts_runtime.py'
    }
}
foreach ($token in @('semantic_trace', 'semantic_decision_state', 'semantic_additions', 'add_semantic_validation(')) {
    if (-not $statePacketText.Contains($token)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STATE_PACKET_SEMANTIC_TRACE_MISSING' -Message "$token must exist on shared StatePacket." -Path 'src/shared/state_packet.py'
    }
}

# FR-04C: catalog consumption classification + unified runtime spine
$catalogConsumptionSpecs = @(
    @{
        catalogPath = 'contracts/governance/source_registry.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/contracts_runtime.py'; tokens = @('self.source_registry = self._load_json("contracts/governance/source_registry.json")', 'source_registry_index', 'def resolve_source_entry(') },
            @{ path = 'src/stage1_tasking/extractors.py'; tokens = @('store.resolve_source_entry(', 'source_registry_id=str(source_entry["source_registry_id"])') },
            @{ path = 'src/stage2_ingestion/extractors.py'; tokens = @('store.resolve_source_entry(', 'source_registry_id=source_registry_id') }
        )
    },
    @{
        catalogPath = 'contracts/governance/route_policy_catalog.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/contracts_runtime.py'; tokens = @('self.route_policy_catalog = self._load_json("contracts/governance/route_policy_catalog.json")', 'route_policy_index', 'def resolve_route_policy(') },
            @{ path = 'src/stage1_tasking/extractors.py'; tokens = @('store.resolve_route_policy(', 'route_policy_id=str(route_policy["route_policy_id"])') },
            @{ path = 'src/stage2_ingestion/extractors.py'; tokens = @('store.resolve_route_policy(', 'route_decision_state, route_downgrade_signals, route_block_signals = _route_decision(') }
        )
    },
    @{
        catalogPath = 'control/runtime_inventory.yaml'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.runtime_inventory = self._load_yaml("control/runtime_inventory.yaml")', 'family_inventory_index') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('"capability_family": "stage8_execution"', 'resolve_permissions(') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('"capability_family": "stage9_execution"', 'resolve_permissions(') }
        )
    },
    @{
        catalogPath = 'contracts/release/runtime_policy_catalog.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.runtime_policy = self._load_json("contracts/release/runtime_policy_catalog.json")', 'family_policy_index', 'decision_matrix') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('resolve_permissions(') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('resolve_permissions(') }
        )
    },
    @{
        catalogPath = 'contracts/sales/vendor_registry_catalog.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.vendor_registry = self._load_json("contracts/sales/vendor_registry_catalog.json")', 'vendor_index', '_resolve_source_vendor(', '_resolve_execution_vendor(') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('"target_type": "source_vendor"', '"target_type": "execution_vendor"', 'resolve_permissions(') }
        )
    },
    @{
        catalogPath = 'contracts/sales/source_vendor_usage_policy.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.source_vendor_usage_policy = self._load_json("contracts/sales/source_vendor_usage_policy.json")', '_resolve_source_vendor(', 'source_vendor_usage_policy') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('"target_type": "source_vendor"', 'resolve_permissions(') }
        )
    },
    @{
        catalogPath = 'contracts/sales/channel_vendor_execution_policy.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.channel_vendor_execution_policy = self._load_json("contracts/sales/channel_vendor_execution_policy.json")', '_resolve_execution_vendor(', 'channel_vendor_execution_policy') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('"target_type": "execution_vendor"', 'resolve_permissions(') }
        )
    },
    @{
        catalogPath = 'contracts/sales/stage7_resolution_policy.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'contracts/sales/stage7_resolution_policy.json'; tokens = @('"actorSeedPolicies"', '"priceCandidateResolution"') },
            @{ path = 'src/stage7_sales/resolution.py'; tokens = @('load_contract("contracts/sales/stage7_resolution_policy.json", settings)', '"actorSeedPolicies"') },
            @{ path = 'src/stage7_sales/service.py'; tokens = @('resolve_actor_seed(', 'stage7_resolution_trace', 'multi_competitor_collection') }
        )
    },
    @{
        catalogPath = 'contracts/model/model_usage_policy.json'
        mode = 'INTENTIONAL_PARTIAL'
        reason = 'provider usage remains input-gated until a later bound-provider batch'
        signals = @(
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.model_usage_policy = self._load_json("contracts/model/model_usage_policy.json")', 'self.model_usage_policy.get("allowed_action_intents", [])', '_resolve_model_provider(') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('"target_type": "model_provider"') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('"target_type": "model_provider"') }
        )
    },
    @{
        catalogPath = 'contracts/model/tool_usage_policy_catalog.json'
        mode = 'INTENTIONAL_PARTIAL'
        reason = 'tool-provider resolution remains input-gated until a later bound-provider batch'
        signals = @(
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.tool_usage_policy = self._load_json("contracts/model/tool_usage_policy_catalog.json")', '_resolve_tool_provider(', 'tool_usage_policy_catalog') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('"target_type": "tool_provider"') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('"target_type": "tool_provider"') }
        )
    },
    @{
        catalogPath = 'contracts/governance/field_policy_dictionary.json'
        mode = 'INTENTIONAL_PARTIAL'
        reason = 'field policy is broader than the current runtime surface and must be consumed via RuntimeValidator for touched objects'
        signals = @(
            @{ path = 'src/shared/runtime_validator.py'; tokens = @('self.field_policy = self._load_json("contracts/governance/field_policy_dictionary.json")', '_evaluate_field_policy(', 'field_policy_index') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('evaluate_runtime_guards(') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('evaluate_runtime_guards(') }
        )
    },
    @{
        catalogPath = 'contracts/release/delivery_matrix.json'
        mode = 'INTENTIONAL_PARTIAL'
        reason = 'delivery matrix is broader than current Stage8/9 execution and must still be consumed for touched governed objects'
        signals = @(
            @{ path = 'src/shared/runtime_validator.py'; tokens = @('self.delivery_matrix = self._load_json("contracts/release/delivery_matrix.json")', '_evaluate_delivery_matrix(', 'delivery_index') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('evaluate_runtime_guards(') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('evaluate_runtime_guards(') }
        )
    },
    @{
        catalogPath = 'contracts/release/release_gates.json'
        mode = 'INTENTIONAL_PARTIAL'
        reason = 'release gates exceed the current runtime surface and must still be consumed for touched Stage8/9 guarded objects'
        signals = @(
            @{ path = 'src/shared/runtime_validator.py'; tokens = @('self.release_gates = self._load_json("contracts/release/release_gates.json")', '_evaluate_release_gates(', 'release_gate_index') },
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('self.release_gates = self._load_json("contracts/release/release_gates.json")') },
            @{ path = 'src/stage8_outreach/service.py'; tokens = @('evaluate_runtime_guards(') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('evaluate_runtime_guards(') }
        )
    },
    @{
        catalogPath = 'contracts/sales/payment_exception_catalog.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/policy_executor.py'; tokens = @('"payment_exception": "contracts/sales/payment_exception_catalog.json"', '_evaluate_payment_exception(') },
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('"payment_exception"', '"stage9_delivery"') }
        )
    },
    @{
        catalogPath = 'contracts/sales/delivery_exception_catalog.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/policy_executor.py'; tokens = @('"delivery_exception": "contracts/sales/delivery_exception_catalog.json"', '_evaluate_delivery_exception(') },
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('"delivery_exception"', '"stage9_delivery"') }
        )
    },
    @{
        catalogPath = 'contracts/sales/outcome_taxonomy_catalog.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/policy_executor.py'; tokens = @('"outcome_taxonomy": "contracts/sales/outcome_taxonomy_catalog.json"', '_evaluate_outcome_taxonomy(') },
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('"outcome_taxonomy"', '"stage9_delivery"') }
        )
    },
    @{
        catalogPath = 'contracts/sales/governance_feedback_policy_catalog.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/shared/policy_executor.py'; tokens = @('"governance_taxonomy": "contracts/sales/governance_feedback_policy_catalog.json"', '_evaluate_governance_taxonomy(') },
            @{ path = 'src/shared/capability_runtime.py'; tokens = @('"governance_taxonomy"', '"stage9_delivery"') }
        )
    },
    @{
        catalogPath = 'contracts/governance/writeback_impact_policy.json'
        mode = 'FULL_RUNTIME'
        reason = ''
        signals = @(
            @{ path = 'src/stage9_delivery/impact_executor.py'; tokens = @('load_contract("contracts/governance/writeback_impact_policy.json"', 'describe_targets(') },
            @{ path = 'src/stage9_delivery/service.py'; tokens = @('self.impact_executor.execute(', 'writeback_target_contracts') }
        )
    }
)

foreach ($spec in $catalogConsumptionSpecs) {
    if ($spec.mode -notin @('FULL_RUNTIME', 'INTENTIONAL_PARTIAL')) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CATALOG_CONSUMPTION_MODE_INVALID' -Message "Invalid consumption mode for $($spec.catalogPath)." -Path $spec.catalogPath
        continue
    }
    if ($spec.mode -eq 'INTENTIONAL_PARTIAL' -and [string]::IsNullOrWhiteSpace($spec.reason)) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CATALOG_INTENTIONAL_PARTIAL_REASON_MISSING' -Message "Intentional partial catalog $($spec.catalogPath) must declare a reason." -Path $spec.catalogPath
    }

    $matchedSignalCount = 0
    foreach ($signal in $spec.signals) {
        $signalText = switch ($signal.path) {
            'src/shared/contracts_runtime.py' { $contractsRuntimeText }
            'src/shared/capability_runtime.py' { $capabilityRuntimeText }
            'src/shared/policy_executor.py' { $policyExecutorText }
            'src/shared/runtime_validator.py' { $runtimeValidatorText }
            'src/stage1_tasking/extractors.py' { $stage1ExtractorText }
            'src/stage2_ingestion/extractors.py' { $stage2ExtractorText }
            'src/stage7_sales/resolution.py' { Read-TextFile -Path (Join-Path $root 'src/stage7_sales/resolution.py') -Issues ([ref]$issues) }
            'src/stage8_outreach/service.py' { $stage8ServiceText }
            'src/stage9_delivery/service.py' { $stage9ServiceText }
            'src/stage9_delivery/impact_executor.py' { $stage9ImpactExecutorText }
            default { Read-TextFile -Path (Join-Path $root $signal.path) -Issues ([ref]$issues) }
        }

        $missingTokens = @($signal.tokens | Where-Object { -not $signalText.Contains($_) })
        if ($missingTokens.Count -eq 0) {
            $matchedSignalCount += 1
            continue
        }

        $code = if ($spec.mode -eq 'FULL_RUNTIME') { 'CATALOG_RUNTIME_UNDECLARED_PARTIAL' } else { 'CATALOG_INTENTIONAL_PARTIAL_SIGNAL_MISSING' }
        $classification = if ($spec.mode -eq 'FULL_RUNTIME') { 'UNDECLARED_PARTIAL' } else { 'INTENTIONAL_PARTIAL' }
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code $code -Message "$($spec.catalogPath) classified as $classification because $($signal.path) is missing runtime consumption signals: $($missingTokens -join ', ')" -Path $spec.catalogPath
    }

    if ($matchedSignalCount -eq 0) {
        Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CATALOG_RUNTIME_UNUSED' -Message "$($spec.catalogPath) classified as UNUSED because runtime-consumption signals were not found." -Path $spec.catalogPath
    }
}

foreach ($serviceCheck in @(
    @{
        path = 'src/stage7_sales/service.py'
        text = $stage7ServiceText
        orderedTokens = @('evaluate_handoff_consumer(', 'self.runtime.run(', 'evaluate_object_semantics(')
    },
    @{
        path = 'src/stage8_outreach/service.py'
        text = $stage8ServiceText
        orderedTokens = @('resolve_permissions(', 'self.runtime.run(', 'evaluate_runtime_guards(', 'evaluate_object_semantics(')
    },
    @{
        path = 'src/stage9_delivery/service.py'
        text = $stage9ServiceText
        orderedTokens = @('resolve_permissions(', 'self.runtime.run(', 'evaluate_runtime_guards(', 'evaluate_object_semantics(')
    }
)) {
    $positions = [System.Collections.Generic.List[int]]::new()
    foreach ($token in $serviceCheck.orderedTokens) {
        $index = $serviceCheck.text.IndexOf($token)
        if ($index -lt 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIFIED_RUNTIME_SPINE_TOKEN_MISSING' -Message "$token must exist on $($serviceCheck.path)." -Path $serviceCheck.path
            continue
        }
        $positions.Add($index) | Out-Null
    }
    if ($positions.Count -eq $serviceCheck.orderedTokens.Count) {
        $ordered = $true
        for ($i = 1; $i -lt $positions.Count; $i += 1) {
            if ($positions[$i] -lt $positions[$i - 1]) {
                $ordered = $false
                break
            }
        }
        if (-not $ordered) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIFIED_RUNTIME_SPINE_ORDER_DRIFT' -Message "$($serviceCheck.path) must keep the unified runtime spine order: $($serviceCheck.orderedTokens -join ' -> ')." -Path $serviceCheck.path
        }
    }
    foreach ($token in @('PolicyExecutor(', 'CapabilityResolver(', 'RuntimeValidator(', 'def _run_policy_chain', 'runtime.executor.execute(')) {
        if ($serviceCheck.text.Contains($token)) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'UNIFIED_RUNTIME_SPINE_BYPASS' -Message "$($serviceCheck.path) must not reintroduce $token." -Path $serviceCheck.path
        }
    }
}

# FR-05: stage4-7 formal output / handoff alignment
$pythonCommand = Find-PythonCommand
if (-not $pythonCommand) {
    Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'PYTHON_RUNTIME_MISSING' -Message 'Python is required for Stage 4-7 semantic alignment assertions.' -Path 'scripts/check-semantic-alignment.ps1'
}
else {
    $pythonScript = @'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))

from helpers import load_fixture
from stage1_tasking.service import Stage1Service
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from stage7_sales.service import Stage7Service


def load_json(relative_path: str) -> dict:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def run_to_stage7(fixture_name: str) -> dict:
    payload = load_fixture(fixture_name)
    stage1 = Stage1Service().run(payload)
    stage2 = Stage2Service().run(stage1)
    stage3 = Stage3Service().run(stage2)
    stage4 = Stage4Service().run(stage3)
    stage5 = Stage5Service().run(stage4)
    stage6 = Stage6Service().run(stage5)
    stage7 = Stage7Service().run(stage6)
    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage4": stage4,
        "stage5": stage5,
        "stage6": stage6,
        "stage7": stage7,
    }


def record_dependencies(relative_path: str) -> list[str]:
    text = (root / relative_path).read_text(encoding="utf-8")
    return sorted(set(re.findall(r'\.record\("([^"]+)"\)', text)))


issues: list[dict[str, str]] = []


def add_issue(code: str, message: str, path: str) -> None:
    issues.append(
        {
            "severity": "ERROR",
            "code": code,
            "message": message,
            "path": path,
        }
    )


contracts = {
    1: load_json("handoff/stage1_to_stage2/contract.json"),
    4: load_json("handoff/stage4_to_stage5/contract.json"),
    5: load_json("handoff/stage5_to_stage6/contract.json"),
    6: load_json("handoff/stage6_to_stage7/contract.json"),
    7: load_json("handoff/stage7_to_stage8/contract.json"),
}
integration_rows = {
    row["contractId"]: row
    for row in load_json("handoff/integration_matrix.json")["rows"]
    if row["contractId"] in {
        "H-01-STAGE1-TO-STAGE2",
        "H-04-STAGE4-TO-STAGE5",
        "H-05-STAGE5-TO-STAGE6",
        "H-06-STAGE6-TO-STAGE7",
        "H-07-STAGE7-TO-STAGE8",
    }
}
service_paths = {
    "H-01-STAGE1-TO-STAGE2": "src/stage2_ingestion/service.py",
    "H-04-STAGE4-TO-STAGE5": "src/stage5_rules_evidence/service.py",
    "H-05-STAGE5-TO-STAGE6": "src/stage6_fact_review/service.py",
    "H-06-STAGE6-TO-STAGE7": "src/stage7_sales/service.py",
    "H-07-STAGE7-TO-STAGE8": "src/stage8_outreach/service.py",
}
stage_keys = {1: "stage1", 4: "stage4", 5: "stage5", 6: "stage6", 7: "stage7"}

happy = run_to_stage7("internal_chain_happy.json")
blocked = run_to_stage7("internal_chain_block.json")

for stage_number, stage_key in stage_keys.items():
    contract = contracts[stage_number]
    actual_outputs = set(happy[stage_key].records.keys())
    declared_outputs = set(contract["producer_objects"])
    if not actual_outputs.issubset(declared_outputs):
        add_issue(
            "HANDOFF_PRODUCER_DRIFT",
            f"{stage_key} outputs {sorted(actual_outputs)} exceed declared producer set {sorted(declared_outputs)}.",
            f"handoff/{Path(service_paths[contract['handoff_id']]).name}",
        )

if "pseudo_competitor_signal_set" not in happy["stage4"].records:
    add_issue(
        "STAGE4_FORMAL_OUTPUT_MISSING",
        "Stage4 happy path must produce pseudo_competitor_signal_set.",
        "src/stage4_verification/service.py",
    )
if "review_request" not in blocked["stage5"].records:
    add_issue(
        "STAGE5_FORMAL_OUTPUT_MISSING",
        "Stage5 blocked/review path must produce review_request.",
        "src/stage5_rules_evidence/service.py",
    )
for required_object in ("legal_action_recommendation", "challenger_candidate_profile"):
    if required_object not in happy["stage6"].records:
        add_issue(
            "STAGE6_FORMAL_OUTPUT_MISSING",
            f"Stage6 happy path must produce {required_object}.",
            "src/stage6_fact_review/service.py",
        )
for required_object in (
    "legal_action_actor_profile",
    "procurement_decision_actor_profile",
    "buyer_fit",
    "challenger_buyer_fit",
    "saleable_opportunity",
):
    if required_object not in happy["stage7"].records:
        add_issue(
            "STAGE7_FORMAL_OUTPUT_MISSING",
            f"Stage7 happy path must produce {required_object}.",
            "src/stage7_sales/service.py",
        )

for field_name in contracts[1]["required_payload_fields"]:
    if field_name not in happy["stage1"].handoff:
        add_issue(
            "HANDOFF_PAYLOAD_FIELD_MISSING",
            f"H-01 handoff payload must include {field_name}.",
            "src/stage1_tasking/service.py",
        )
for field_name in contracts[6]["required_payload_fields"]:
    if field_name not in happy["stage6"].handoff:
        add_issue(
            "HANDOFF_PAYLOAD_FIELD_MISSING",
            f"H-06 handoff payload must include {field_name}.",
            "src/stage6_fact_review/service.py",
        )
for field_name in contracts[7]["required_payload_fields"]:
    if field_name not in happy["stage7"].handoff:
        add_issue(
            "HANDOFF_PAYLOAD_FIELD_MISSING",
            f"H-07 handoff payload must include {field_name}.",
            "src/stage7_sales/service.py",
        )

for contract_id, service_path in service_paths.items():
    actual_dependencies = record_dependencies(service_path)
    expected_dependencies = sorted(integration_rows[contract_id]["criticalObjects"])
    if actual_dependencies != expected_dependencies:
        add_issue(
            "HANDOFF_CONSUMER_DEPENDENCY_DRIFT",
            f"{contract_id} consumer dependencies drift. expected={expected_dependencies}, actual={actual_dependencies}",
            service_path,
        )

stage6_outputs = set(happy["stage6"].records.keys())
stage7_outputs = set(happy["stage7"].records.keys())

if not stage6_outputs.issuperset(set(contracts[6]["producer_objects"])):
    add_issue(
        "STAGE6_PRODUCER_SET_INCOMPLETE",
        "Stage6 happy path must cover the declared H-06 producer set.",
        "src/stage6_fact_review/service.py",
    )
if not stage7_outputs.issuperset(set(integration_rows["H-07-STAGE7-TO-STAGE8"]["criticalObjects"])):
    add_issue(
        "STAGE7_TO_STAGE8_CHAIN_INCOMPLETE",
        "Stage7 happy path must cover H-07 critical dependency objects before Stage8 starts.",
        "src/stage7_sales/service.py",
    )

print(json.dumps({"issues": issues}, ensure_ascii=False))
'@
    $tempPython = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $tempPython -Value $pythonScript -Encoding UTF8
        $pythonArgs = @($pythonCommand.arguments + @($tempPython, $root))
        $pythonOutput = & $pythonCommand.executable @pythonArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE4_7_ALIGNMENT_FAILED' -Message "Stage4-7 semantic alignment runner failed: $($pythonOutput -join ' ')" -Path 'scripts/check-semantic-alignment.ps1'
        }
        else {
            $raw = ($pythonOutput -join [Environment]::NewLine)
            $jsonStart = $raw.IndexOf('{')
            if ($jsonStart -lt 0) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE4_7_ALIGNMENT_NO_JSON' -Message 'Stage4-7 alignment runner did not emit JSON.' -Path 'scripts/check-semantic-alignment.ps1'
            }
            else {
                $alignment = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 50
                foreach ($issue in @($alignment.issues)) {
                    $issues.Add($issue) | Out-Null
                }
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempPython) {
            Remove-Item -LiteralPath $tempPython -Force -ErrorAction SilentlyContinue
        }
    }
}

# FR-05B: schema/catalog/runtime-validator exact drift checks
if ($pythonCommand) {
    $pythonScript = @'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))

from shared.runtime_validator import RuntimeValidator


def load_json(relative_path: str) -> dict:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def add_issue(issues, code, message, path):
    issues.append({"severity": "ERROR", "code": code, "message": message, "path": path})


def type_matches(type_spec, schema_field: dict) -> bool:
    schema_type = schema_field.get("type")
    schema_types = set(schema_type if isinstance(schema_type, list) else [schema_type])
    expected = type_spec.expected_type
    if expected == "str":
        return "string" in schema_types
    if expected == "int":
        return "integer" in schema_types
    if expected == "number":
        return bool(schema_types.intersection({"number", "integer"}))
    if expected == "bool":
        return "boolean" in schema_types
    if expected == "list":
        if "array" not in schema_types:
            return False
        if type_spec.item_type:
            expected_item = "string" if type_spec.item_type == "str" else type_spec.item_type
            return schema_field.get("items", {}).get("type") == expected_item
        return True
    if expected == "object":
        return "object" in schema_types
    return False


issues = []
validator = RuntimeValidator(str(root))
schema_catalog = {
    entry["object"]: entry
    for entry in load_json("contracts/schemas/schema_catalog.json")["schemas"]
}
enum_names = {
    entry["enum_name"]
    for entry in load_json("contracts/enums/enum_catalog.json")["enums"]
}
critical_objects = [
    "execution_context",
    "public_chain",
    "clock_chain_profile",
    "notice_version_chain",
    "saleable_opportunity",
    "contact_target",
    "outreach_plan",
    "touch_record",
    "order_record",
    "payment_record",
    "delivery_record",
    "opportunity_outcome_event",
    "governance_feedback_event",
]
for object_name in critical_objects:
    schema_path = f"contracts/schemas/{object_name}.schema.json"
    schema = load_json(schema_path)
    catalog = schema_catalog[object_name]
    if set(catalog["required"]) != set(schema.get("required", [])):
        add_issue(
            issues,
            "SCHEMA_CATALOG_REQUIRED_DRIFT",
            f"{object_name} required fields drift between schema_catalog and concrete schema.",
            schema_path,
        )
    for enum_name in catalog.get("enum_refs", []):
        if enum_name not in enum_names:
            add_issue(
                issues,
                "SCHEMA_ENUM_REF_DRIFT",
                f"{object_name} references missing enum {enum_name}.",
                "contracts/enums/enum_catalog.json",
            )
    strict_profile = validator.STRICT_PROFILES[object_name]
    missing_required = sorted(set(catalog["required"]) - set(strict_profile.keys()))
    if missing_required:
        add_issue(
            issues,
            "RUNTIME_VALIDATOR_REQUIRED_DRIFT",
            f"{object_name} runtime_validator missing required fields: {missing_required}",
            "src/shared/runtime_validator.py",
        )
    for field_name, type_spec in strict_profile.items():
        if field_name not in schema.get("properties", {}):
            add_issue(
                issues,
                "RUNTIME_VALIDATOR_FIELD_DRIFT",
                f"{object_name}.{field_name} missing from concrete schema.",
                schema_path,
            )
            continue
        if not type_matches(type_spec, schema["properties"][field_name]):
            add_issue(
                issues,
                "RUNTIME_VALIDATOR_TYPE_DRIFT",
                f"{object_name}.{field_name} type drift between runtime_validator and concrete schema.",
                "src/shared/runtime_validator.py",
            )

print(json.dumps({"issues": issues}, ensure_ascii=False))
'@
    $schemaTemp = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $schemaTemp -Value $pythonScript -Encoding UTF8
        $schemaArgs = @($pythonCommand.arguments + @($schemaTemp, $root))
        $schemaOutput = & $pythonCommand.executable @schemaArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SCHEMA_VALIDATOR_ALIGNMENT_FAILED' -Message "schema/runtime-validator alignment runner failed: $($schemaOutput -join ' ')" -Path 'scripts/check-semantic-alignment.ps1'
        }
        else {
            $raw = ($schemaOutput -join [Environment]::NewLine)
            $jsonStart = $raw.IndexOf('{')
            if ($jsonStart -lt 0) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SCHEMA_VALIDATOR_ALIGNMENT_NO_JSON' -Message 'schema/runtime-validator alignment runner did not emit JSON.' -Path 'scripts/check-semantic-alignment.ps1'
            }
            else {
                $alignment = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 50
                foreach ($issue in @($alignment.issues)) {
                    $issues.Add($issue) | Out-Null
                }
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $schemaTemp) {
            Remove-Item -LiteralPath $schemaTemp -Force -ErrorAction SilentlyContinue
        }
    }
}

# FR-06: stage8-9 pre-route behavior / H-08 handoff / policy executor alignment
if ($pythonCommand) {
    $pythonScript = @'
import copy
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))

from helpers import load_fixture
from stage9_delivery.service import Stage9Service
from shared.pipeline import run_internal_chain
from shared.policy_executor import PolicyExecutor
from shared.contracts_runtime import StageBundle


def load_json(relative_path: str) -> dict:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def record_dependencies(relative_path: str) -> list[str]:
    text = (root / relative_path).read_text(encoding="utf-8")
    return sorted(set(re.findall(r'\.record\("([^"]+)"\)', text)))


def decision_map(trace: list[dict]) -> dict[str, dict]:
    return {
        entry["policy_key"]: entry
        for entry in trace
        if isinstance(entry, dict) and entry.get("policy_key") and entry.get("catalog_id")
    }


def _stage8_policy_sources() -> tuple[dict, dict, dict]:
    return (
        load_json("contracts/sales/outreach_cadence_catalog.json")["policies"][0],
        load_json("contracts/sales/retry_policy_catalog.json")["policies"][0],
        load_json("contracts/sales/touch_stop_condition_catalog.json")["policies"][0],
    )


def _select_cadence_profile(policy: dict, *, urgency: str, window_urgency: int) -> dict:
    normalized_urgency = (urgency or "NORMAL").upper()
    if normalized_urgency == "CRITICAL" or window_urgency >= 90:
        profile_id = "CADENCE-CRITICAL"
    elif normalized_urgency == "HIGH" or window_urgency >= 80:
        profile_id = "CADENCE-HIGH"
    elif normalized_urgency == "LOW":
        profile_id = "CADENCE-LOW"
    else:
        profile_id = "CADENCE-NORMAL"
    return next(item for item in policy["cadence_profiles"] if item["profile_id"] == profile_id)


def _select_channel_override(policy: dict, channel_family: str) -> dict:
    return next(
        (item for item in policy["channel_overrides"] if item["channel_family"] == channel_family),
        {},
    )


def _select_channel_ladder(policy: dict, channel_family: str) -> dict:
    return next(
        (item for item in policy["channel_ladders"] if item["entry_channel_family"] == channel_family),
        {
            "ladder_id": f"LADDER-{channel_family}",
            "step_sequence": [channel_family],
            "fallback_sequence": [],
            "fallback_trigger_response_statuses": [],
            "sequence_mode": "GOVERNED_PREVIEW_ONLY",
            "live_execution_enabled": False,
        },
    )


def _retry_rule(policy: dict, response_status: str) -> dict:
    return next(item for item in policy["retry_rules"] if item["response_status"] == response_status)


def _parse_policy_actions(actions: list[str]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for action in actions:
        field_name, raw_value = action.split("=", 1)
        if raw_value == "true":
            parsed[field_name] = True
        elif raw_value == "false":
            parsed[field_name] = False
        else:
            parsed[field_name] = raw_value
    return parsed


def _stop_rule(policy: dict, *, section: str, reason: str) -> dict:
    if section == "stop_after_retry":
        rule = dict(policy["stop_after_retry"])
        rule["actions_map"] = _parse_policy_actions(rule["actions"])
        return rule
    rule = next(item for item in policy[section] if item["reason"] == reason)
    enriched = dict(rule)
    enriched["actions_map"] = _parse_policy_actions(rule["actions"])
    return enriched


issues: list[dict[str, str]] = []


def add_issue(code: str, message: str, path: str) -> None:
    issues.append(
        {
            "severity": "ERROR",
            "code": code,
            "message": message,
            "path": path,
        }
    )


expected_stage8_keys = [
    "contact_source_policy",
    "contact_compliance",
    "contact_priority",
    "outreach_cadence",
    "retry_policy",
    "touch_stop",
]
expected_stage9_keys = [
    "payment_exception",
    "delivery_exception",
    "outcome_taxonomy",
    "governance_taxonomy",
]
stage8_cadence_policy, stage8_retry_policy, stage8_stop_policy = _stage8_policy_sources()

happy = run_internal_chain(load_fixture("internal_chain_happy.json"))
stage8_decisions = decision_map(happy["stage8"].handoff.get("policy_trace", []))
for key in expected_stage8_keys:
    entry = stage8_decisions.get(key)
    if entry is None:
        add_issue(
            "STAGE8_POLICY_TRACE_MISSING",
            f"Stage8 trace must include decision entry for {key}.",
            "src/stage8_outreach/service.py",
        )
        continue
    for required_field in ("policy_key", "catalog_id", "decision_state", "outputs", "reasons"):
        if required_field not in entry:
            add_issue(
                "STAGE8_POLICY_TRACE_INCOMPLETE",
                f"Stage8 decision trace for {key} must include {required_field}.",
                "src/stage8_outreach/service.py",
            )
happy_channel_family = str(happy["stage8"].record("contact_target").get("channel_family", "ORG_EMAIL"))
happy_ladder = _select_channel_ladder(stage8_cadence_policy, happy_channel_family)
happy_cadence_outputs = stage8_decisions.get("outreach_cadence", {}).get("outputs", {})
if (
    happy_cadence_outputs.get("retry_policy_id") != stage8_cadence_policy.get("retry_policy_id")
    or happy_cadence_outputs.get("stop_policy_id") != stage8_cadence_policy.get("stop_policy_id")
    or happy_cadence_outputs.get("channel_ladder_id") != happy_ladder["ladder_id"]
):
    add_issue(
        "STAGE8_CADENCE_SOURCE_DRIFT",
        "Stage8 outreach_cadence trace must single-source retry/stop refs and channel ladder from outreach_cadence_catalog.",
        "src/shared/policy_executor.py",
    )

conflict_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
conflict_payload.update(
    {
        "channel_family": "PERSONAL_PHONE",
        "contact_channel": "PHONE",
        "response_status": "NO_RESPONSE",
    }
)
conflict = run_internal_chain(conflict_payload)
conflict_trace = decision_map(conflict["stage8"].handoff.get("policy_trace", []))
conflict_contact = conflict["stage8"].record("contact_target").data
conflict_plan = conflict["stage8"].record("outreach_plan").data
conflict_touch = conflict["stage8"].record("touch_record").data
conflict_cadence_outputs = conflict_trace.get("outreach_cadence", {}).get("outputs", {})
expected_conflict_profile = _select_cadence_profile(
    stage8_cadence_policy,
    urgency=str(
        conflict_payload.get("commercial_urgency_level_optional")
        or conflict_payload.get("commercial_urgency_level")
        or "NORMAL"
    ),
    window_urgency=int(conflict_payload.get("window_urgency_score", 50)),
)
expected_conflict_override = _select_channel_override(stage8_cadence_policy, "PERSONAL_PHONE")
expected_conflict_ladder = _select_channel_ladder(stage8_cadence_policy, "PERSONAL_PHONE")
expected_conflict_retry = _retry_rule(stage8_retry_policy, "NO_RESPONSE")
expected_conflict_retry_count = 1 if expected_conflict_retry.get("next_action") == "RETRY" else 0
expected_conflict_attempt_index = 2 if expected_conflict_retry.get("next_action") == "RETRY" else 1
if not conflict_contact.get("contact_conflict_flag"):
    add_issue(
        "STAGE8_CONFLICT_BEHAVIOR_DRIFT",
        "Stage8 conflict scenario must persist contact_conflict_flag=true.",
        "src/stage8_outreach/service.py",
    )
if (
    conflict_plan.get("cadence_profile_id") != expected_conflict_profile["profile_id"]
    or conflict_plan.get("retry_policy_id") != stage8_cadence_policy.get("retry_policy_id")
    or conflict_plan.get("stop_policy_id") != stage8_cadence_policy.get("stop_policy_id")
    or conflict_plan.get("max_retry_count")
    != expected_conflict_override.get("max_attempts_7d", expected_conflict_profile["max_attempts_7d"])
):
    add_issue(
        "STAGE8_CADENCE_SINGLE_SOURCE_DRIFT",
        "Stage8 cadence/retry/stop ids and max_retry_count must stay aligned with outreach_cadence_catalog.",
        "src/shared/policy_executor.py",
    )
if (
    conflict_cadence_outputs.get("channel_ladder_id") != expected_conflict_ladder["ladder_id"]
    or conflict_cadence_outputs.get("ladder_sequence") != expected_conflict_ladder["step_sequence"]
    or conflict_cadence_outputs.get("channel_fallback_sequence") != expected_conflict_ladder["fallback_sequence"]
    or conflict_cadence_outputs.get("fallback_channel_family_optional")
    != next(iter(expected_conflict_ladder["fallback_sequence"]), None)
    or conflict_cadence_outputs.get("ladder_sequence_mode") != expected_conflict_ladder["sequence_mode"]
    or conflict_cadence_outputs.get("live_execution_enabled") is not False
):
    add_issue(
        "STAGE8_LADDER_TRACE_DRIFT",
        "Stage8 outreach_cadence trace must expose the catalog-defined ladder/fallback sequence without implying live execution.",
        "src/shared/policy_executor.py",
    )
if (
    conflict_plan.get("retry_count") != expected_conflict_retry_count
    or conflict_touch.get("attempt_index") != expected_conflict_attempt_index
):
    add_issue(
        "STAGE8_RETRY_BEHAVIOR_DRIFT",
        "Stage8 NO_RESPONSE scenario must increment retry_count and attempt_index.",
        "src/stage8_outreach/service.py",
    )
if not conflict["stage8"].inputs.get("next_touch_due_at_optional"):
    add_issue(
        "STAGE8_CADENCE_BEHAVIOR_DRIFT",
        "Stage8 cadence scenario must emit next_touch_due_at_optional.",
        "src/stage8_outreach/service.py",
    )

opt_out_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
opt_out_payload.update(
    {
        "opt_out_state": "OPTED_OUT",
        "response_status": "OPTED_OUT",
    }
)
opt_out = run_internal_chain(opt_out_payload)
opt_out_stop = _stop_rule(
    stage8_stop_policy,
    section="permanent_block_conditions",
    reason="opt_out_blocked",
)
if (
    opt_out["stage8"].record("contact_target").get("contact_target_status") != opt_out_stop["actions_map"]["contact_target_status"]
    or opt_out["stage8"].record("outreach_plan").get("plan_status") != opt_out_stop["actions_map"]["plan_status"]
    or opt_out["stage8"].record("touch_record").get("touch_record_state") != "CANCELLED"
):
    add_issue(
        "STAGE8_STOP_BEHAVIOR_DRIFT",
        "Stage8 opt-out scenario must block contact_target, cancel outreach_plan and cancel touch_record.",
        "src/stage8_outreach/service.py",
    )

retry_exhausted_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
retry_exhausted_payload.update(
    {
        "channel_family": "ORG_EMAIL",
        "contact_channel": "EMAIL",
        "response_status": "NO_RESPONSE",
        "retry_count": 2,
    }
)
retry_exhausted = run_internal_chain(retry_exhausted_payload)
retry_exhausted_trace = decision_map(retry_exhausted["stage8"].handoff.get("policy_trace", []))
retry_exhausted_stop = _stop_rule(
    stage8_stop_policy,
    section="stop_after_retry",
    reason="retry_exhausted",
)
expected_retry_exhausted_ladder = _select_channel_ladder(stage8_cadence_policy, "ORG_EMAIL")
if (
    retry_exhausted["stage8"].record("contact_target").get("contact_target_status")
    != retry_exhausted_stop["actions_map"]["contact_target_status"]
    or retry_exhausted["stage8"].record("outreach_plan").get("plan_status")
    != retry_exhausted_stop["actions_map"]["plan_status"]
    or retry_exhausted["stage8"].record("outreach_plan").get("stop_reason_optional")
    != retry_exhausted_stop["reason"]
):
    add_issue(
        "STAGE8_RETRY_EXHAUSTED_STOP_DRIFT",
        "Stage8 retry exhausted path must follow touch_stop_condition_catalog.stop_after_retry.",
        "src/stage8_outreach/service.py",
    )
if (
    retry_exhausted_trace.get("outreach_cadence", {}).get("outputs", {}).get("channel_ladder_id")
    != expected_retry_exhausted_ladder["ladder_id"]
):
    add_issue(
        "STAGE8_RETRY_EXHAUSTED_LADDER_DRIFT",
        "Stage8 retry exhausted path must retain the catalog-defined channel ladder trace.",
        "src/shared/policy_executor.py",
    )

wrong_role_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
wrong_role_payload.update({"response_status": "WRONG_ROLE"})
wrong_role = run_internal_chain(wrong_role_payload)
wrong_role_touch = wrong_role["stage8"].record("touch_record").data
for missing_field in ("next_step_optional", "written_back_at_optional"):
    if missing_field not in wrong_role_touch:
        add_issue(
            "STAGE8_WRITEBACK_SURFACE_MISSING",
            f"Stage8 failure path must persist {missing_field} before route-map start.",
            "src/stage8_outreach/service.py",
        )

h08_contract = load_json("handoff/stage8_to_stage9/contract.json")
missing_h08_handoff_fields = [
    field_name
    for field_name in h08_contract["required_payload_fields"]
    if field_name not in happy["stage8"].handoff
]
if missing_h08_handoff_fields:
    add_issue(
        "H08_HANDOFF_PAYLOAD_INCOMPLETE",
        f"H-08 handoff is missing required payload fields: {missing_h08_handoff_fields}.",
        "src/stage8_outreach/service.py",
    )

missing_h08_input_fields = [
    field_name
    for field_name in h08_contract["required_payload_fields"]
    if field_name not in happy["stage8"].inputs
]
if missing_h08_input_fields:
    add_issue(
        "H08_INPUT_PAYLOAD_INCOMPLETE",
        f"Projected Stage8 inputs are missing H-08 required payload fields: {missing_h08_input_fields}.",
        "src/stage8_outreach/service.py",
    )

expected_stage8_producer_set = sorted(h08_contract["producer_objects"])
actual_stage8_outputs = sorted(happy["stage8"].records.keys())
if not set(expected_stage8_producer_set).issubset(set(actual_stage8_outputs)):
    add_issue(
        "H08_PRODUCER_SET_DRIFT",
        f"Stage8 producer set drift. expected={expected_stage8_producer_set}, actual={actual_stage8_outputs}",
        "src/stage8_outreach/service.py",
    )

for object_name in ("contact_candidate_collection_snapshot", "contact_selection_trace_snapshot"):
    if object_name not in happy["stage8"].inputs:
        add_issue(
            "STAGE8_COLLECTION_OUTPUT_MISSING",
            f"Stage8 must emit {object_name}.",
            "src/stage8_outreach/service.py",
        )

if "multi_competitor_collection" not in happy["stage7"].records:
    add_issue(
        "STAGE7_COLLECTION_OUTPUT_MISSING",
        "Stage7 must emit multi_competitor_collection before Stage8 starts.",
        "src/stage7_sales/service.py",
    )

if "multi_competitor_collection" in happy["stage7"].records and "contact_candidate_collection_snapshot" in happy["stage8"].inputs:
    multi_collection = happy["stage7"].record("multi_competitor_collection").data
    contact_collection = happy["stage8"].inputs["contact_candidate_collection_snapshot"]
    selection_trace = happy["stage8"].inputs["contact_selection_trace_snapshot"]
    contact_target = happy["stage8"].record("contact_target").data
    if contact_collection.get("multi_competitor_collection_id") != multi_collection.get("multi_competitor_collection_id"):
        add_issue(
            "STAGE8_COLLECTION_UPSTREAM_REF_DRIFT",
            "contact_candidate_collection must keep upstream multi_competitor_collection_id.",
            "src/stage8_outreach/service.py",
        )
    if selection_trace.get("contact_candidate_collection_id") != contact_collection.get("contact_candidate_collection_id"):
        add_issue(
            "STAGE8_SELECTION_TRACE_REF_DRIFT",
            "contact_selection_trace must keep contact_candidate_collection_id aligned.",
            "src/stage8_outreach/service.py",
        )
    if contact_target.get("contact_selection_reason") != selection_trace.get("winning_selection_reason"):
        add_issue(
            "STAGE8_SELECTION_REASON_DRIFT",
            "contact_target must consume winning_selection_reason from contact_selection_trace.",
            "src/stage8_outreach/service.py",
        )

reselect_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
reselect_payload.update(
    {
        "response_status": "WRONG_ROLE",
        "previous_contact_candidate_id_optional": "cand-old",
        "contact_candidate_pool": [
            {
                "candidate_id": "cand-new",
                "org_name": "New Org",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T11:00:00Z",
            }
        ],
    }
)
reselect_stage8 = run_internal_chain(reselect_payload)["stage8"]
reselect_collection = reselect_stage8.inputs["contact_candidate_collection_snapshot"]
reselect_trace = reselect_stage8.inputs["contact_selection_trace_snapshot"]
if not reselect_collection.get("reselect_history") or not reselect_trace.get("reselect_history"):
    add_issue(
        "STAGE8_RESELECT_TRACE_MISSING",
        "Stage8 wrong-role path must persist reselect_history in formal collection and trace.",
        "src/stage8_outreach/service.py",
    )

expected_h08_projection = {
    "opportunity_id": happy["stage8"].record("saleable_opportunity").get("opportunity_id"),
    "touch_record_id": happy["stage8"].record("touch_record").get("touch_record_id"),
    "response_status": happy["stage8"].record("touch_record").get("response_status"),
    "saleability_status": happy["stage8"].record("saleable_opportunity").get("saleability_status"),
    "crm_owner_state": happy["stage8"].record("saleable_opportunity").get("crm_owner_state"),
}
for field_name, expected_value in expected_h08_projection.items():
    if happy["stage8"].handoff.get(field_name) != expected_value:
        add_issue(
            "H08_HANDOFF_VALUE_DRIFT",
            f"H-08 handoff field {field_name} must project from formal Stage8 records.",
            "src/stage8_outreach/service.py",
        )
    if happy["stage8"].inputs.get(field_name) != expected_value:
        add_issue(
            "H08_INPUT_VALUE_DRIFT",
            f"Projected Stage8 input field {field_name} must align with formal Stage8 records.",
            "src/stage8_outreach/service.py",
        )

if wrong_role["stage8"].inputs.get("written_back_at_optional") != wrong_role_touch.get("written_back_at_optional"):
    add_issue(
        "STAGE8_WRITEBACK_PROJECTION_DRIFT",
        "Stage8 failure path must project written_back_at_optional into downstream inputs.",
        "src/stage8_outreach/service.py",
    )
if wrong_role["stage8"].inputs.get("next_step_optional") != wrong_role_touch.get("next_step_optional"):
    add_issue(
        "STAGE8_NEXT_STEP_PROJECTION_DRIFT",
        "Stage8 failure path must project next_step_optional into downstream inputs.",
        "src/stage8_outreach/service.py",
    )

integration_rows = {
    row["contractId"]: row
    for row in load_json("handoff/integration_matrix.json")["rows"]
}
expected_stage9_dependencies = sorted(
    integration_rows["H-08-STAGE8-TO-STAGE9"]["criticalObjects"]
)
actual_stage9_dependencies = record_dependencies("src/stage9_delivery/service.py")
if actual_stage9_dependencies != expected_stage9_dependencies:
    add_issue(
        "H08_STAGE9_CONSUMER_SET_DRIFT",
        f"Stage9 consumer dependencies drift. expected={expected_stage9_dependencies}, actual={actual_stage9_dependencies}",
        "src/stage9_delivery/service.py",
    )

happy_stage9 = happy["stage9"]
happy_order = happy_stage9.record("order_record").data
happy_governance = happy_stage9.record("governance_feedback_event").data
happy_outcome = happy_stage9.record("opportunity_outcome_event").data
if happy_order.get("opportunity_id") != expected_h08_projection["opportunity_id"]:
    add_issue(
        "STAGE9_OPPORTUNITY_CONSUMPTION_DRIFT",
        "Stage9 order_record.opportunity_id must come from H-08 / saleable_opportunity.",
        "src/stage9_delivery/service.py",
    )
for token in (
    expected_h08_projection["opportunity_id"],
    expected_h08_projection["touch_record_id"],
    expected_h08_projection["response_status"],
    expected_h08_projection["saleability_status"],
    expected_h08_projection["crm_owner_state"],
):
    if token not in happy_governance.get("trigger_summary", ""):
        add_issue(
            "STAGE9_TRIGGER_SUMMARY_DRIFT",
            "Stage9 governance trigger_summary must retain H-08 key field values for audit.",
            "src/stage9_delivery/service.py",
        )
        break
if happy_order.get("order_status") != "PENDING_APPROVAL" or happy_governance.get("trigger_type") != "APPROVAL_MISSING":
    add_issue(
        "STAGE9_OWNER_STATE_CONSUMPTION_DRIFT",
        "Stage9 must let crm_owner_state affect order/governance runtime decisions.",
        "src/stage9_delivery/service.py",
    )
if happy_outcome.get("outcome_family") != "CONTACT_FAILED" or happy_outcome.get("contact_failure_state") != "NO_RESPONSE":
    add_issue(
        "STAGE9_RESPONSE_STATUS_CONSUMPTION_DRIFT",
        "Stage9 must let response_status affect outcome runtime decisions.",
        "src/stage9_delivery/service.py",
    )

connected_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
connected_payload.update({"crm_owner_state": "ASSIGNED", "response_status": "CONNECTED"})
connected = run_internal_chain(connected_payload)
if (
    connected["stage9"].record("order_record").get("order_status") != "DRAFT"
    or connected["stage9"].record("delivery_record").get("delivery_status") != "NOT_READY"
):
    add_issue(
        "STAGE9_CONNECTED_RUNTIME_DRIFT",
        "Stage9 CONNECTED + ASSIGNED scenario must stay in draft/not-ready path.",
        "src/stage9_delivery/service.py",
    )

blocked = run_internal_chain(load_fixture("internal_chain_block.json"))
if (
    blocked["stage9"].record("order_record").get("order_status") != "ON_HOLD"
    or blocked["stage9"].record("delivery_record").get("delivery_status") != "RELEASE_BLOCKED"
    or blocked["stage9"].record("governance_feedback_event").get("trigger_type") != "EVIDENCE_INSUFFICIENT"
):
    add_issue(
        "STAGE9_SALEABILITY_CONSUMPTION_DRIFT",
        "Stage9 BLOCKED opportunity scenario must hold order, block delivery and raise evidence-insufficient governance trigger.",
        "src/stage9_delivery/service.py",
    )

wrong_role_assigned_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
wrong_role_assigned_payload.update({"crm_owner_state": "ASSIGNED", "response_status": "WRONG_ROLE"})
wrong_role_assigned = run_internal_chain(wrong_role_assigned_payload)
if (
    wrong_role_assigned["stage9"].record("order_record").get("order_status") != "ON_HOLD"
    or wrong_role_assigned["stage9"].record("delivery_record").get("delivery_status") != "RELEASE_BLOCKED"
    or wrong_role_assigned["stage9"].record("opportunity_outcome_event").get("contact_failure_state") != "WRONG_ROLE"
):
    add_issue(
        "STAGE9_CONTACT_FAILURE_CONSUMPTION_DRIFT",
        "Stage9 contact-failure scenario must hold order, block delivery and write WRONG_ROLE into outcome state.",
        "src/stage9_delivery/service.py",
    )

stage9_service = Stage9Service()
missing_saleable_bundle = StageBundle(
    stage=8,
    records={key: value for key, value in happy["stage8"].records.items() if key != "saleable_opportunity"},
    handoff=dict(happy["stage8"].handoff),
    trace_rules=list(happy["stage8"].trace_rules),
    inputs=dict(happy["stage8"].inputs),
)
try:
    stage9_service.run(missing_saleable_bundle)
    add_issue(
        "STAGE9_MISSING_SALEABLE_OPPORTUNITY_NOT_BLOCKED",
        "Stage9 must fail when saleable_opportunity is missing from Stage8 bundle.",
        "src/stage9_delivery/service.py",
    )
except ValueError:
    pass

missing_h08_field_bundle = StageBundle(
    stage=8,
    records=dict(happy["stage8"].records),
    handoff={key: value for key, value in happy["stage8"].handoff.items() if key != "crm_owner_state"},
    trace_rules=list(happy["stage8"].trace_rules),
    inputs=dict(happy["stage8"].inputs),
)
try:
    stage9_service.run(missing_h08_field_bundle)
    add_issue(
        "STAGE9_MISSING_H08_FIELD_NOT_BLOCKED",
        "Stage9 must fail when H-08 required payload fields are missing even if projected inputs still exist.",
        "src/stage9_delivery/service.py",
    )
except ValueError:
    pass

missing_policy_files = [
    policy_key for policy_key in expected_stage9_keys if policy_key not in PolicyExecutor.POLICY_FILES
]
if missing_policy_files:
    add_issue(
        "STAGE9_POLICY_FILE_MAP_MISSING",
        f"PolicyExecutor is missing stage9 policy file mappings: {missing_policy_files}",
        "src/shared/policy_executor.py",
    )

exception_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
exception_payload.update(
    {
        "refund_state": "COMPLETED",
        "outcome_family": "DELIVERY_ABANDONED",
        "outcome_reason_tags": ["REFUND_COMPLETED"],
        "trigger_type": "EXCEPTION_TRIGGERED",
    }
)
exception = run_internal_chain(exception_payload)
stage9_decisions = decision_map(exception["stage9"].inputs.get("policy_trace", []))
if set(stage9_decisions.keys()) != set(expected_stage9_keys):
    add_issue(
        "STAGE9_POLICY_SEQUENCE_INCOMPLETE",
        f"Stage9 trace must include exactly {expected_stage9_keys}, actual={sorted(stage9_decisions.keys())}",
        "src/stage9_delivery/service.py",
    )
for key in expected_stage9_keys:
    entry = stage9_decisions.get(key)
    if entry is None:
        add_issue(
            "STAGE9_POLICY_TRACE_MISSING",
            f"Stage9 trace must include decision entry for {key}.",
            "src/stage9_delivery/service.py",
        )
        continue
    for required_field in ("policy_key", "catalog_id", "decision_state", "outputs", "reasons"):
        if required_field not in entry:
            add_issue(
                "STAGE9_POLICY_TRACE_INCOMPLETE",
                f"Stage9 decision trace for {key} must include {required_field}.",
                "src/stage9_delivery/service.py",
            )

outcome_catalog = load_json("contracts/sales/outcome_taxonomy_catalog.json")
governance_catalog = load_json("contracts/sales/governance_feedback_policy_catalog.json")
payment_catalog = load_json("contracts/sales/payment_exception_catalog.json")
delivery_catalog = load_json("contracts/sales/delivery_exception_catalog.json")
writeback_policy = load_json("contracts/governance/writeback_impact_policy.json")
outcome_record = exception["stage9"].record("opportunity_outcome_event").data
expected_outcome_targets = next(
    entry["writeback_targets"]
    for entry in outcome_catalog["entries"]
    if entry["outcome_family"] == outcome_record["outcome_family"]
)
if sorted(outcome_record.get("writeback_targets", [])) != sorted(expected_outcome_targets):
    add_issue(
        "STAGE9_OUTCOME_WRITEBACK_TARGET_DRIFT",
        f"Outcome writeback_targets must follow outcome taxonomy. expected={expected_outcome_targets}, actual={outcome_record.get('writeback_targets', [])}",
        "src/stage9_delivery/service.py",
    )
actual_governance_targets = exception["stage9"].inputs.get("governance_writeback_targets_optional", [])
expected_governance_targets = stage9_decisions.get("governance_taxonomy", {}).get("outputs", {}).get("writeback_targets", [])
if actual_governance_targets != expected_governance_targets:
    add_issue(
        "STAGE9_GOVERNANCE_WRITEBACK_TARGET_DRIFT",
        f"Governance writeback targets must remain visible as governed/additive runtime data. expected={expected_governance_targets}, actual={actual_governance_targets}",
        "src/stage9_delivery/service.py",
    )
actual_payment_exception_targets = exception["stage9"].inputs.get("payment_exception_writeback_targets_optional", [])
if actual_payment_exception_targets != ["saleable_opportunity", "project_fact"]:
    add_issue(
        "STAGE9_PAYMENT_WRITEBACK_TARGET_DRIFT",
        f"Payment exception writeback targets must stay visible and exception-specific. expected={['saleable_opportunity', 'project_fact']}, actual={actual_payment_exception_targets}",
        "src/stage9_delivery/service.py",
    )
actual_delivery_exception_targets = exception["stage9"].inputs.get("delivery_exception_writeback_targets_optional", [])
if actual_delivery_exception_targets != ["delivery_record"]:
    add_issue(
        "STAGE9_DELIVERY_WRITEBACK_TARGET_DRIFT",
        f"Refund-completed scenario must retain ARCHIVE_FAILURE delivery writeback target visibility. expected={['delivery_record']}, actual={actual_delivery_exception_targets}",
        "src/stage9_delivery/service.py",
    )
expected_effective_targets = list(expected_outcome_targets)
for target in expected_governance_targets + actual_payment_exception_targets + actual_delivery_exception_targets:
    if target not in expected_effective_targets:
        expected_effective_targets.append(target)
if exception["stage9"].inputs.get("effective_writeback_targets") != expected_effective_targets:
    add_issue(
        "STAGE9_EFFECTIVE_WRITEBACK_TARGET_DRIFT",
        f"Effective writeback targets must equal outcome targets plus additive governance and exception targets. expected={expected_effective_targets}, actual={exception['stage9'].inputs.get('effective_writeback_targets')}",
        "src/stage9_delivery/service.py",
    )
writeback_contracts = exception["stage9"].inputs.get("writeback_target_contracts", {})
required_contract_fields = {
    "target_family",
    "mutation_semantics",
    "persistence_semantics",
    "additive_governance_allowed",
    "silent_override_forbidden",
}
for target in expected_effective_targets:
    contract = writeback_contracts.get(target)
    if not contract:
        add_issue(
            "WRITEBACK_TARGET_CONTRACT_RUNTIME_MISSING",
            f"Effective writeback target {target} must expose runtime contract semantics.",
            "src/stage9_delivery/service.py",
        )
        continue
    missing_fields = sorted(required_contract_fields - set(contract.keys()))
    if missing_fields:
        add_issue(
            "WRITEBACK_TARGET_CONTRACT_RUNTIME_INCOMPLETE",
            f"Writeback target {target} is missing contract fields {missing_fields}.",
            "src/stage9_delivery/service.py",
        )

catalog_targets = set()
for entry in outcome_catalog["entries"]:
    catalog_targets.update(entry.get("writeback_targets", []))
for entry in governance_catalog["entries"]:
    catalog_targets.update(entry.get("writeback_targets", []))
for rule in payment_catalog["policies"][0]["mapping_rules"]:
    catalog_targets.update(rule.get("writeback_targets", []))
for rule in delivery_catalog["policies"][0]["mapping_rules"]:
    catalog_targets.update(rule.get("writeback_targets", []))
target_contracts = writeback_policy.get("target_contracts", {})
missing_target_contracts = sorted(catalog_targets - set(target_contracts.keys()))
if missing_target_contracts:
    add_issue(
        "WRITEBACK_TARGET_CONTRACT_MISSING",
        f"writeback_impact_policy must declare target contracts for all runtime writeback targets. missing={missing_target_contracts}",
        "contracts/governance/writeback_impact_policy.json",
    )
for target, contract in target_contracts.items():
    missing_fields = sorted(required_contract_fields - set(contract.keys()))
    if missing_fields:
        add_issue(
            "WRITEBACK_TARGET_CONTRACT_INCOMPLETE",
            f"Target contract {target} is missing fields {missing_fields}.",
            "contracts/governance/writeback_impact_policy.json",
        )

payment_exception_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
payment_exception_payload.update({"payment_status": "PARTIALLY_PAID"})
payment_exception = run_internal_chain(payment_exception_payload)
payment_record = payment_exception["stage9"].record("payment_record").data
if payment_record.get("payment_exception_family_optional") != "PARTIAL_PAYMENT":
    add_issue(
        "STAGE9_PAYMENT_EXCEPTION_BEHAVIOR_MISSING",
        "Stage9 PARTIALLY_PAID scenario must persist payment_exception_family_optional=PARTIAL_PAYMENT.",
        "src/stage9_delivery/service.py",
    )

chargeback_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
chargeback_payload.update(
    {
        "crm_owner_state": "ASSIGNED",
        "response_status": "CONNECTED",
        "payment_status": "PAYMENT_EXCEPTION",
        "payment_exception_family_optional": "CHARGEBACK_REVIEW",
    }
)
chargeback = run_internal_chain(chargeback_payload)["stage9"]
if (
    chargeback.record("payment_record").get("payment_exception_family_optional") != "CHARGEBACK_REVIEW"
    or chargeback.record("governance_feedback_event").get("trigger_type") != "EXCEPTION_TRIGGERED"
    or chargeback.inputs.get("payment_exception_writeback_targets_optional") != ["order_record", "project_fact"]
):
    add_issue(
        "STAGE9_CHARGEBACK_REVIEW_RUNTIME_GAP",
        "Stage9 must runtime-cover CHARGEBACK_REVIEW with decision trace, state sink and exception-specific writeback targets.",
        "src/stage9_delivery/service.py",
    )

delivery_exception_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
delivery_exception_payload.update(
    {
        "delivery_status": "REDELIVERY_REQUIRED",
        "outcome_family": "DELIVERY_ABANDONED",
        "outcome_reason_tags": ["DELIVERY_REJECTED"],
        "trigger_type": "DELIVERY_BLOCK",
    }
)
delivery_exception = run_internal_chain(delivery_exception_payload)
delivery_record = delivery_exception["stage9"].record("delivery_record").data
if (
    delivery_record.get("delivery_exception_family_optional") != "REDELIVERY_REQUIRED"
    or delivery_record.get("redeliver_required_optional") is not True
):
    add_issue(
        "STAGE9_DELIVERY_EXCEPTION_BEHAVIOR_MISSING",
        "Stage9 redelivery scenario must persist delivery_exception_family_optional and redeliver_required_optional.",
        "src/stage9_delivery/service.py",
    )

delivery_family_cases = [
    ("DELIVERY_REJECTED", ["saleable_opportunity", "project_fact"], "REJECTED", "NOT_PARTIAL"),
    ("PARTIAL_DELIVERY", ["saleable_opportunity"], "PENDING", "PARTIAL"),
    ("ACK_TIMEOUT", ["delivery_record"], "TIMEOUT", "NOT_PARTIAL"),
]
for family, expected_targets, expected_ack, expected_partial in delivery_family_cases:
    payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
    payload.update(
        {
            "crm_owner_state": "ASSIGNED",
            "response_status": "CONNECTED",
            "delivery_exception_family_optional": family,
        }
    )
    stage9 = run_internal_chain(payload)["stage9"]
    if (
        stage9.record("delivery_record").get("delivery_exception_family_optional") != family
        or stage9.record("delivery_record").get("customer_ack_state_optional") != expected_ack
        or stage9.record("delivery_record").get("partial_delivery_state_optional") != expected_partial
        or stage9.record("opportunity_outcome_event").get("outcome_family") != "DELIVERY_ABANDONED"
        or stage9.record("governance_feedback_event").get("trigger_type") != "DELIVERY_BLOCK"
        or stage9.inputs.get("delivery_exception_writeback_targets_optional") != expected_targets
    ):
        add_issue(
            "STAGE9_DELIVERY_EXCEPTION_RUNTIME_GAP",
            f"Stage9 must runtime-cover {family} with decision trace, state sink and exception-specific writeback targets.",
            "src/stage9_delivery/service.py",
        )

print(json.dumps({"issues": issues}, ensure_ascii=False))
'@
    $tempPython = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $tempPython -Value $pythonScript -Encoding UTF8
        $pythonArgs = @($pythonCommand.arguments + @($tempPython, $root))
        $pythonOutput = & $pythonCommand.executable @pythonArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE8_9_ALIGNMENT_FAILED' -Message "Stage8-9 pre-route runner failed: $($pythonOutput -join ' ')" -Path 'scripts/check-semantic-alignment.ps1'
        }
        else {
            $raw = ($pythonOutput -join [Environment]::NewLine)
            $jsonStart = $raw.IndexOf('{')
            if ($jsonStart -lt 0) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'STAGE8_9_ALIGNMENT_NO_JSON' -Message 'Stage8-9 pre-route runner did not emit JSON.' -Path 'scripts/check-semantic-alignment.ps1'
            }
            else {
                $alignment = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 50
                foreach ($issue in @($alignment.issues)) {
                    $issues.Add($issue) | Out-Null
                }
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempPython) {
            Remove-Item -LiteralPath $tempPython -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($pythonCommand) {
    $permissionPython = @'
import copy
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))

from helpers import load_fixture, run_internal_chain_to_stage7
from shared.capability_runtime import CapabilityRuntime
from shared.context_packet import ContextPacket
from shared.pipeline import run_internal_chain


def add_issue(issues, code, message, path):
    issues.append({"severity": "ERROR", "code": code, "message": message, "path": path})


issues = []
happy = load_fixture("internal_chain_happy.json")
stage_result = run_internal_chain(copy.deepcopy(happy))

for stage_key, path in (("stage8", "src/stage8_outreach/service.py"), ("stage9", "src/stage9_delivery/service.py")):
    trace = stage_result[stage_key].inputs.get("policy_trace", [])
    permission_trace = stage_result[stage_key].inputs.get("permission_trace", [])
    if not permission_trace:
        add_issue(issues, "PERMISSION_TRACE_MISSING", f"{stage_key} must emit permission_trace before risky execution.", path)
        continue
    first_permission = next((index for index, entry in enumerate(trace) if entry.get("event") == "capability_resolution"), None)
    first_policy = next((index for index, entry in enumerate(trace) if entry.get("event") == "load_policy"), None)
    if first_permission is None or first_policy is None or first_permission >= first_policy:
        add_issue(issues, "PERMISSION_TRACE_ORDER_DRIFT", f"{stage_key} capability resolution must happen before policy load.", path)

stage8_payload = copy.deepcopy(happy)
stage8_payload["capability_mode_overrides"] = {"stage8_execution": "EMERGENCY_OFF"}
stage8_emergency = run_internal_chain(stage8_payload)["stage8"]
if (
    stage8_emergency.inputs.get("permission_decision_state") != "BLOCK"
    or stage8_emergency.record("contact_target").get("contact_target_status") != "BLOCKED"
    or stage8_emergency.record("outreach_plan").get("plan_status") != "BLOCKED"
    or stage8_emergency.record("touch_record").get("touch_record_state") != "CANCELLED"
):
    add_issue(issues, "STAGE8_EMERGENCY_OFF_DRIFT", "Stage8 EMERGENCY_OFF must short-circuit the risky path.", "src/stage8_outreach/service.py")

stage9_payload = copy.deepcopy(happy)
stage9_payload["capability_mode_overrides"] = {"stage9_execution": "EMERGENCY_OFF"}
stage9_emergency = run_internal_chain(stage9_payload)["stage9"]
if (
    stage9_emergency.inputs.get("permission_decision_state") != "BLOCK"
    or stage9_emergency.record("order_record").get("order_status") != "ON_HOLD"
    or stage9_emergency.record("delivery_record").get("delivery_status") != "RELEASE_BLOCKED"
):
    add_issue(issues, "STAGE9_EMERGENCY_OFF_DRIFT", "Stage9 EMERGENCY_OFF must short-circuit internal writeback.", "src/stage9_delivery/service.py")

stage7 = run_internal_chain_to_stage7(copy.deepcopy(happy))["stage7"]
runtime = CapabilityRuntime()
external_context = ContextPacket.from_records(
    capability_mode="stage8_outreach",
    stage=8,
    project_id=stage7.record("saleable_opportunity").get("project_id"),
    records={"saleable_opportunity": stage7.record("saleable_opportunity")},
    inputs={
        "release_level": "EXTERNAL_BLOCKED",
        "approval_state": "APPROVED",
        "capability_mode_overrides": {"execution_vendor": "REAL_RUN_READY"},
    },
)
external_state = runtime.resolve_permissions(
    external_context,
    [
        {
            "capability_family": "execution_vendor",
            "requested_action": "LIVE_EXECUTION",
            "target_id": "EXEC-EMAIL-SERVICE",
            "target_type": "execution_vendor",
            "target_role": "EXECUTION_VENDOR",
            "release_level": "EXTERNAL_BLOCKED",
            "approval_state": "APPROVED",
        }
    ],
)
if external_state.permission_decision_state != "BLOCK":
    add_issue(issues, "REAL_RUN_READY_RELEASE_DRIFT", "REAL_RUN_READY must not override EXTERNAL_BLOCKED.", "src/shared/capability_runtime.py")

print(json.dumps({"issues": issues}, ensure_ascii=False))
'@
    $permissionTemp = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $permissionTemp -Value $permissionPython -Encoding UTF8
        $permissionArgs = @($pythonCommand.arguments + @($permissionTemp, $root))
        $permissionOutput = & $pythonCommand.executable @permissionArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_PERMISSION_RUNTIME_FAILED' -Message "capability runtime checker failed: $($permissionOutput -join ' ')" -Path 'scripts/check-semantic-alignment.ps1'
        }
        else {
            $raw = ($permissionOutput -join [Environment]::NewLine)
            $jsonStart = $raw.IndexOf('{')
            if ($jsonStart -lt 0) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'CAPABILITY_PERMISSION_RUNTIME_NO_JSON' -Message 'capability runtime checker did not emit JSON.' -Path 'scripts/check-semantic-alignment.ps1'
            }
            else {
                $permissionAlignment = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 50
                foreach ($issue in @($permissionAlignment.issues)) {
                    $issues.Add($issue) | Out-Null
                }
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $permissionTemp) {
            Remove-Item -LiteralPath $permissionTemp -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($pythonCommand) {
    $governancePython = @'
import copy
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))

from helpers import load_fixture
from shared.pipeline import run_internal_chain


def add_issue(issues, code, message, path):
    issues.append({"severity": "ERROR", "code": code, "message": message, "path": path})


issues = []

stage8_high_restriction = copy.deepcopy(load_fixture("internal_chain_happy.json"))
stage8_high_restriction.update({"person_name_optional": "张三", "approval_state": "PENDING"})
stage8_result = run_internal_chain(stage8_high_restriction)["stage8"]
if (
    stage8_result.record("contact_target").get("contact_target_status") != "REVIEW_REQUIRED"
    or stage8_result.inputs.get("governance_decision_state") != "REVIEW"
):
    add_issue(issues, "STAGE8_FIELD_POLICY_RUNTIME_DRIFT", "Stage8 high-restriction field must trigger runtime review via field policy.", "src/stage8_outreach/service.py")

stage8_leadpack = copy.deepcopy(load_fixture("internal_chain_happy.json"))
stage8_leadpack["requested_delivery_surface"] = "LEADPACK_DELIVERABLE"
stage8_leadpack_result = run_internal_chain(stage8_leadpack)["stage8"]
if (
    stage8_leadpack_result.record("outreach_plan").get("plan_status") != "BLOCKED"
    or stage8_leadpack_result.inputs.get("governance_decision_state") != "BLOCK"
):
    add_issue(issues, "STAGE8_DELIVERY_MATRIX_RUNTIME_DRIFT", "Stage8 outreach_plan must be runtime-blocked for direct LeadPack delivery surface.", "src/stage8_outreach/service.py")

stage9_leadpack = copy.deepcopy(load_fixture("internal_chain_happy.json"))
stage9_leadpack["requested_delivery_surface"] = "LEADPACK_DELIVERABLE"
stage9_leadpack_result = run_internal_chain(stage9_leadpack)["stage9"]
if (
    stage9_leadpack_result.record("order_record").get("order_status") != "ON_HOLD"
    or stage9_leadpack_result.record("delivery_record").get("delivery_status") != "RELEASE_BLOCKED"
    or stage9_leadpack_result.inputs.get("governance_decision_state") != "BLOCK"
):
    add_issue(issues, "STAGE9_DELIVERY_MATRIX_RUNTIME_DRIFT", "Stage9 direct objects must be runtime-blocked for LeadPack delivery surface.", "src/stage9_delivery/service.py")

stage9_release = copy.deepcopy(load_fixture("internal_chain_happy.json"))
stage9_release["release_level"] = "DEV_ALLOWED"
stage9_release_result = run_internal_chain(stage9_release)["stage9"]
if stage9_release_result.inputs.get("governance_decision_state") != "REVIEW":
    add_issue(issues, "STAGE9_RELEASE_GATE_RUNTIME_DRIFT", "Stage9 must runtime-consume release gates when release_level is insufficient.", "src/stage9_delivery/service.py")

for stage_key, path, expected_objects in (
    ("stage8", "src/stage8_outreach/service.py", {"contact_target", "outreach_plan", "touch_record"}),
    ("stage9", "src/stage9_delivery/service.py", {"order_record", "payment_record", "delivery_record", "opportunity_outcome_event", "governance_feedback_event"}),
):
    result = run_internal_chain(load_fixture("internal_chain_happy.json"))[stage_key]
    trace = result.inputs.get("governance_trace", [])
    if not trace:
        add_issue(issues, "GOVERNANCE_TRACE_MISSING", f"{stage_key} must emit governance_trace.", path)
        continue
    guarded = {entry.get("object_type") for entry in trace}
    if guarded != expected_objects:
        add_issue(issues, "GOVERNANCE_TRACE_OBJECT_DRIFT", f"{stage_key} governance_trace object set drift. expected={sorted(expected_objects)}, actual={sorted(guarded)}", path)
    for entry in trace:
        for token in ("field_policy", "delivery_matrix", "release_gates"):
            if token not in entry:
                add_issue(issues, "GOVERNANCE_TRACE_SHAPE_DRIFT", f"{stage_key} governance_trace entries must retain {token}.", path)

print(json.dumps({"issues": issues}, ensure_ascii=False))
'@
    $governanceTemp = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $governanceTemp -Value $governancePython -Encoding UTF8
        $governanceArgs = @($pythonCommand.arguments + @($governanceTemp, $root))
        $governanceOutput = & $pythonCommand.executable @governanceArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'GOVERNANCE_RUNTIME_FAILED' -Message "governance runtime checker failed: $($governanceOutput -join ' ')" -Path 'scripts/check-semantic-alignment.ps1'
        }
        else {
            $raw = ($governanceOutput -join [Environment]::NewLine)
            $jsonStart = $raw.IndexOf('{')
            if ($jsonStart -lt 0) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'GOVERNANCE_RUNTIME_NO_JSON' -Message 'governance runtime checker did not emit JSON.' -Path 'scripts/check-semantic-alignment.ps1'
            }
            else {
                $governanceAlignment = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 50
                foreach ($issue in @($governanceAlignment.issues)) {
                    $issues.Add($issue) | Out-Null
                }
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $governanceTemp) {
            Remove-Item -LiteralPath $governanceTemp -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($pythonCommand) {
    $semanticPython = @'
import copy
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
sys.path.insert(0, str(root / "tests"))

from helpers import load_fixture
from shared.contracts_runtime import ContractStore, StageBundle
from shared.pipeline import run_internal_chain
from stage1_tasking.service import Stage1Service
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from stage7_sales.service import Stage7Service


def add_issue(issues, code, message, path):
    issues.append({"severity": "ERROR", "code": code, "message": message, "path": path})


store = ContractStore.default()
issues = []

payload = load_fixture("internal_chain_happy.json")
stage1 = Stage1Service().run(copy.deepcopy(payload))
stage2 = Stage2Service().run(stage1)
stage3 = Stage3Service().run(stage2)
stage4 = Stage4Service().run(stage3)
stage5 = Stage5Service().run(stage4)
stage6 = Stage6Service().run(stage5)
stage7 = Stage7Service().run(stage6)

stage_map = {
    2: stage1,
    3: stage2,
    4: stage3,
    5: stage4,
    6: stage5,
    7: stage6,
    8: stage7,
}
for consumer_stage, producer_bundle in stage_map.items():
    result = store.evaluate_handoff_consumer(producer_bundle=producer_bundle, consumer_stage=consumer_stage)
    if result is None or result.decision_state != "ALLOW":
        add_issue(issues, "HANDOFF_CONSUMER_RUNTIME_DRIFT", f"H-{producer_bundle.stage:02d}->{consumer_stage:02d} happy-path consumer runtime check must ALLOW.", "src/shared/runtime_validator.py")

broken_h01 = StageBundle(
    stage=1,
    records={key: value for key, value in stage1.records.items() if key != "task_execution_context"},
    handoff={key: value for key, value in stage1.handoff.items() if key != "review_lane"},
    trace_rules=list(stage1.trace_rules),
    inputs={key: value for key, value in stage1.inputs.items() if key != "review_lane"},
)
if store.evaluate_handoff_consumer(producer_bundle=broken_h01, consumer_stage=2).decision_state != "BLOCK":
    add_issue(issues, "H01_RUNTIME_REQUIRED_FIELD_DRIFT", "H-01 missing task_execution_context/review_lane must BLOCK in consumer runtime.", "src/shared/runtime_validator.py")

broken_h02 = StageBundle(
    stage=2,
    records={key: value for key, value in stage2.records.items() if key != "fixation_bundle"},
    handoff={key: value for key, value in stage2.handoff.items() if key != "fixation_bundle_id"},
    trace_rules=list(stage2.trace_rules),
    inputs={key: value for key, value in stage2.inputs.items() if key != "fixation_bundle_id"},
)
if store.evaluate_handoff_consumer(producer_bundle=broken_h02, consumer_stage=3).decision_state != "BLOCK":
    add_issue(issues, "H02_RUNTIME_FIXATION_DRIFT", "H-02 missing fixation_bundle/fixation_bundle_id must BLOCK in consumer runtime.", "src/shared/runtime_validator.py")

baseline_cases = [
    {
        "source_family": "AWARD_ANNOUNCEMENT",
        "platform_level": "CITY",
        "region_scope": "CITY",
        "coverage_tier": "T2_LOCAL",
        "carrier_type": "HTML_PAGE",
        "source_registry_id": "SRC-REG-AWARD-CITY-HTML",
        "route_policy_id": "ROUTE-AWARD-ANNOUNCEMENT-001",
        "default_route": "LIST_TO_DETAIL",
        "fallback_route": "DETAIL_DIRECT",
        "route_decision_state": "REVIEW",
        "version_chain_strategy": "ANNOUNCEMENT_REPLACEMENT_CHAIN",
    },
    {
        "source_family": "REGULATORY_PUBLICATION",
        "platform_level": "NATIONAL",
        "region_scope": "NATIONAL",
        "coverage_tier": "T0_CORE",
        "carrier_type": "HTML_PAGE",
        "source_registry_id": "SRC-REG-REG-NATIONAL-HTML",
        "route_policy_id": "ROUTE-REG-PUBLICATION-001",
        "default_route": "DETAIL_DIRECT",
        "fallback_route": "METADATA_ONLY",
        "route_decision_state": "ALLOW",
        "version_chain_strategy": "LATEST_ONLY",
    },
    {
        "source_family": "ENTERPRISE_REGISTRY",
        "platform_level": "INDUSTRY_PLATFORM",
        "region_scope": "NATIONAL",
        "coverage_tier": "T1_REGIONAL",
        "carrier_type": "TABLE_SEGMENT",
        "source_registry_id": "SRC-REG-ENTERPRISE-INDUSTRY-TABLE",
        "route_policy_id": "ROUTE-ENTERPRISE-REGISTRY-001",
        "default_route": "METADATA_ONLY",
        "fallback_route": "SEMI_MANUAL",
        "route_decision_state": "REVIEW",
        "version_chain_strategy": "METADATA_REFRESH_CHAIN",
    },
]
for case in baseline_cases:
    payload_case = copy.deepcopy(payload)
    payload_case.update(
        {
            "source_family": case["source_family"],
            "platform_level": case["platform_level"],
            "region_scope": case["region_scope"],
            "coverage_tier": case["coverage_tier"],
            "carrier_type": case["carrier_type"],
            "current_action_start_at_optional": "2026-04-01T00:00:00Z",
            "current_action_deadline_at_optional": "2026-04-12T23:59:59Z",
        }
    )
    payload_case.pop("default_route", None)
    payload_case.pop("fallback_route", None)
    stage1_case = Stage1Service().run(copy.deepcopy(payload_case))
    stage2_case = Stage2Service().run(stage1_case)
    public_chain = stage2_case.record("public_chain").data
    version_chain = stage2_case.record("notice_version_chain").data
    clock_chain = stage2_case.record("clock_chain_profile").data

    if stage1_case.handoff.get("source_registry_id") != case["source_registry_id"] or stage1_case.handoff.get("route_policy_id") != case["route_policy_id"]:
        add_issue(issues, "STAGE12_BASELINE_STAGE1_RUNTIME_DRIFT", f"Stage1 authoritative baseline routing drift for {case['source_family']}/{case['platform_level']}.", "src/stage1_tasking/service.py")
    if (
        public_chain.get("source_registry_id") != case["source_registry_id"]
        or public_chain.get("route_policy_id") != case["route_policy_id"]
        or public_chain.get("carrier_type") != case["carrier_type"]
        or public_chain.get("default_route") != case["default_route"]
        or public_chain.get("fallback_route") != case["fallback_route"]
        or public_chain.get("route_decision_state") != case["route_decision_state"]
    ):
        add_issue(issues, "STAGE12_BASELINE_STAGE2_RUNTIME_DRIFT", f"Stage2 authoritative source/route baseline drift for {case['source_family']}/{case['platform_level']}.", "src/stage2_ingestion/service.py")
    if version_chain.get("version_chain_strategy") != case["version_chain_strategy"]:
        add_issue(issues, "STAGE12_VERSION_BASELINE_RUNTIME_DRIFT", f"Stage2 version chain strategy drift for {case['source_family']}/{case['platform_level']}.", "src/stage2_ingestion/service.py")
    if (
        clock_chain.get("clock_resolution_rule_id") != "CLOCK-DEFAULT"
        or clock_chain.get("current_action_start_at_optional") != "2026-04-01T00:00:00Z"
        or clock_chain.get("current_action_deadline_at_optional") != "2026-04-12T23:59:59Z"
    ):
        add_issue(issues, "STAGE12_CLOCK_BASELINE_RUNTIME_DRIFT", f"Stage2 clock baseline drift for {case['source_family']}/{case['platform_level']}.", "src/stage2_ingestion/service.py")

carrier_override_payload = copy.deepcopy(payload)
carrier_override_payload.update(
    {
        "current_action_start_at_optional": "2026-04-01T00:00:00Z",
        "current_action_deadline_at_optional": "2026-04-12T23:59:59Z",
    }
)
stage1_authority = Stage1Service().run(copy.deepcopy(carrier_override_payload))
conflicted_stage1 = StageBundle(
    stage=1,
    records=dict(stage1_authority.records),
    handoff=dict(stage1_authority.handoff),
    trace_rules=list(stage1_authority.trace_rules),
    inputs={**stage1_authority.inputs, "carrier_type": "IMAGE_ATTACHMENT", "default_route": "REGISTER_ONLY"},
)
stage2_authority = Stage2Service().run(conflicted_stage1)
if (
    stage2_authority.record("public_chain").get("carrier_type") != "HTML_PAGE"
    or stage2_authority.record("public_chain").get("route_policy_id") != "ROUTE-PROC-NOTICE-001"
    or stage2_authority.record("public_chain").get("default_route") != "LIST_TO_DETAIL"
):
    add_issue(issues, "STAGE12_H01_AUTHORITY_OVERRIDE_DRIFT", "Stage2 must consume carrier/source/route authority from H-01 instead of raw input override.", "src/stage2_ingestion/service.py")

broken_h03 = StageBundle(
    stage=3,
    records={key: value for key, value in stage3.records.items() if key != "project_base"},
    handoff=dict(stage3.handoff),
    trace_rules=list(stage3.trace_rules),
    inputs=dict(stage3.inputs),
)
if store.evaluate_handoff_consumer(producer_bundle=broken_h03, consumer_stage=4).decision_state != "BLOCK":
    add_issue(issues, "H03_RUNTIME_CRITICAL_OBJECT_DRIFT", "H-03 missing project_base must BLOCK in consumer runtime.", "src/shared/runtime_validator.py")

broken_h04 = StageBundle(
    stage=4,
    records={key: value for key, value in stage4.records.items() if key != "evidence_grade_profile"},
    handoff=dict(stage4.handoff),
    trace_rules=list(stage4.trace_rules),
    inputs=dict(stage4.inputs),
)
if store.evaluate_handoff_consumer(producer_bundle=broken_h04, consumer_stage=5).decision_state != "BLOCK":
    add_issue(issues, "H04_RUNTIME_CRITICAL_OBJECT_DRIFT", "H-04 missing evidence_grade_profile must BLOCK in consumer runtime.", "src/shared/runtime_validator.py")

broken_h05 = StageBundle(
    stage=5,
    records={key: value for key, value in stage5.records.items() if key != "rule_gate_decision"},
    handoff={key: value for key, value in stage5.handoff.items() if key != "coverage_sellable_state"},
    trace_rules=list(stage5.trace_rules),
    inputs={key: value for key, value in stage5.inputs.items() if key != "coverage_sellable_state"},
)
if store.evaluate_handoff_consumer(producer_bundle=broken_h05, consumer_stage=6).decision_state != "BLOCK":
    add_issue(issues, "H05_RUNTIME_GATE_DRIFT", "H-05 missing rule_gate_decision/coverage_sellable_state must BLOCK in consumer runtime.", "src/shared/runtime_validator.py")

h06_conflict = StageBundle(
    stage=6,
    records=dict(stage6.records),
    handoff=dict(stage6.handoff),
    trace_rules=list(stage6.trace_rules),
    inputs={**stage6.inputs, "window_status": "MISSED"},
)
if store.evaluate_handoff_consumer(producer_bundle=h06_conflict, consumer_stage=7).decision_state != "BLOCK":
    add_issue(issues, "H06_RUNTIME_RECOMPUTE_DRIFT", "H-06 recompute conflict must BLOCK in consumer runtime.", "src/shared/runtime_validator.py")

h07_conflict = StageBundle(
    stage=7,
    records=dict(stage7.records),
    handoff=dict(stage7.handoff),
    trace_rules=list(stage7.trace_rules),
    inputs={**stage7.inputs, "opportunity_id": "OPP-WRONG"},
)
if store.evaluate_handoff_consumer(producer_bundle=h07_conflict, consumer_stage=8).decision_state != "BLOCK":
    add_issue(issues, "H07_RUNTIME_RECOMPUTE_DRIFT", "H-07 recompute conflict must BLOCK in consumer runtime.", "src/shared/runtime_validator.py")

stage7_conflict_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
stage7_conflict_payload["flags"] = {"report_approved": False}
stage7_conflict_payload["report_status"] = "READY"
stage7_conflict_result = run_internal_chain(stage7_conflict_payload)["stage7"]
if stage7_conflict_result.inputs.get("semantic_decision_state") not in ("REVIEW", "BLOCK"):
    add_issue(issues, "STAGE7_SEMANTIC_TRACE_DRIFT", "Stage7 semantic contradictions must affect runtime semantic_decision_state.", "src/stage7_sales/service.py")
if run_internal_chain(stage7_conflict_payload)["stage6"].record("project_fact").get("sale_gate_status") != "HOLD":
    add_issue(issues, "SALE_GATE_CANONICAL_HOLD_DRIFT", "Stage6 must emit sale_gate_status=HOLD when dual gates pass but report is not issued.", "src/stage6_fact_review/service.py")

stage8_conflict_payload = copy.deepcopy(load_fixture("internal_chain_block.json"))
stage8_conflict_result = run_internal_chain(stage8_conflict_payload)["stage8"]
if stage8_conflict_result.inputs.get("semantic_decision_state") != "BLOCK":
    add_issue(issues, "STAGE8_SEMANTIC_TRACE_DRIFT", "Stage8 contact/outreach contradictions must hit semantic layer.", "src/stage8_outreach/service.py")

stage9_conflict_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
stage9_conflict_payload.update({"outcome_family": "WON", "delivery_status": "RELEASE_BLOCKED"})
stage9_conflict_result = run_internal_chain(stage9_conflict_payload)["stage9"]
if stage9_conflict_result.inputs.get("semantic_decision_state") != "BLOCK":
    add_issue(issues, "STAGE9_SEMANTIC_TRACE_DRIFT", "Stage9 contradictory outcome/delivery combination must hit semantic layer.", "src/stage9_delivery/service.py")

for stage_key, path in (("stage6", "src/stage6_fact_review/service.py"), ("stage7", "src/stage7_sales/service.py"), ("stage8", "src/stage8_outreach/service.py"), ("stage9", "src/stage9_delivery/service.py")):
    result = run_internal_chain(load_fixture("internal_chain_happy.json"))[stage_key]
    if not result.inputs.get("semantic_trace"):
        add_issue(issues, "SEMANTIC_TRACE_MISSING", f"{stage_key} must emit semantic_trace.", path)
    if "semantic_decision_state" not in result.inputs:
        add_issue(issues, "SEMANTIC_DECISION_STATE_MISSING", f"{stage_key} must emit semantic_decision_state.", path)

print(json.dumps({"issues": issues}, ensure_ascii=False))
'@
    $semanticTemp = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $semanticTemp -Value $semanticPython -Encoding UTF8
        $semanticArgs = @($pythonCommand.arguments + @($semanticTemp, $root))
        $semanticOutput = & $pythonCommand.executable @semanticArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SEMANTIC_RUNTIME_FAILED' -Message "semantic runtime checker failed: $($semanticOutput -join ' ')" -Path 'scripts/check-semantic-alignment.ps1'
        }
        else {
            $raw = ($semanticOutput -join [Environment]::NewLine)
            $jsonStart = $raw.IndexOf('{')
            if ($jsonStart -lt 0) {
                Add-Issue -Bag ([ref]$issues) -Severity 'ERROR' -Code 'SEMANTIC_RUNTIME_NO_JSON' -Message 'semantic runtime checker did not emit JSON.' -Path 'scripts/check-semantic-alignment.ps1'
            }
            else {
                $semanticAlignment = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 50
                foreach ($issue in @($semanticAlignment.issues)) {
                    $issues.Add($issue) | Out-Null
                }
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $semanticTemp) {
            Remove-Item -LiteralPath $semanticTemp -Force -ErrorAction SilentlyContinue
        }
    }
}

$errors = @($issues | Where-Object severity -eq 'ERROR')
$result = [pscustomobject]@{
    script = 'check-semantic-alignment.ps1'
    repoRoot = $root
    ok = ($errors.Count -eq 0)
    errorCount = $errors.Count
    warningCount = @($issues | Where-Object severity -eq 'WARNING').Count
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[check-semantic-alignment] repo: $root"
    if ($issues.Count -eq 0) {
        Write-Host '[check-semantic-alignment] PASS'
    }
    else {
        foreach ($issue in $issues) {
            Write-Host ("[{0}] {1} {2} {3}" -f $issue.severity, $issue.code, $issue.path, $issue.message)
        }
    }
}

if ($EmitJson) {
    $result | ConvertTo-Json -Depth 50
}

if ($errors.Count -gt 0) { exit 1 }
exit 0
