param(
    [string]$RunRoot = "",
    [string]$SourceRegressionRunRoot = "",
    [switch]$RunPressure,
    [switch]$RunFieldQuery,
    [switch]$RunStage6Cycle,
    [switch]$RunGdcicAuthorizedReadback,
    [switch]$RunP13BPublicSourceChain,
    [switch]$RunYgpBackfillFieldQuery,
    [switch]$RunStage6MergedProjection,
    [string]$SupplementalFieldQueryRoot = "",
    [string]$SupplementalFieldQueryJson = "",
    [string]$ScoreboardComparisonJson = "",
    [string]$Stage4BackfillFollowupQueueJson = "",
    [switch]$ApplyStage4FollowupExecutionPlan,
    [string]$ProjectIds = "",
    [switch]$EnableLivePublicQuery,
    [switch]$EnableLiveBrowserExecution,
    [int]$CandidateLimit = 30,
    [int]$DetailCaptureLimit = 30,
    [int]$AttachmentCaptureLimit = 60,
    [int]$MaxLiveFieldTasks = 16,
    [int]$MaxLiveBrowserTasks = 0,
    [int]$MaxLiveP13BCompanies = 8,
    [int]$MaxBidRecordsPerCompany = 3,
    [int]$MaxBidListPagesPerCompany = 2,
    [int]$MaxLongTailBidShowsPerCompany = 1,
    [int]$MaxLiveOriginalNotices = 12,
    [int]$MaxLiveYgpOriginalNotices = 8,
    [int]$MaxLiveYgpBackfillTasks = 8,
    [string[]]$ExcludeProjectId = @(),
    [string[]]$ExcludeScoreboardJson = @(),
    [switch]$AttemptAllStage16Candidates,
    [switch]$DescribeEffectivePlanAndExit,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RunRoot) {
    $RunRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage1-6-sellable-rate-regression-v1"
}

$pressureRoot = Join-Path $RunRoot "pressure"
$fieldQueryRoot = Join-Path $RunRoot "field-query"
$ygpBackfillFieldQueryRoot = Join-Path $RunRoot "field-query-ygp-backfill"
$stage6Root = Join-Path $RunRoot "stage6-cycle"
$stage6MergedRoot = Join-Path $RunRoot "stage6-loop-merged"
$gdcicReadbackRoot = Join-Path $RunRoot "gdcic-browser-authorized-readback"
$p13bCompanyHistoryRoot = Join-Path $RunRoot "p13b-company-history"
$p13bOriginalNoticeRoot = Join-Path $RunRoot "p13b-original-notice"
$p13bYgpReadbackRoot = Join-Path $RunRoot "p13b-ygp-original-readback"
$p13bCloseoutRoot = Join-Path $RunRoot "p13b-overlap-closeout"
$scoreboardRoot = Join-Path $RunRoot "scoreboard"
$stage4BackfillFollowupQueueRoot = Join-Path $RunRoot "stage4-backfill-followup-queue"

$sourcePressureRoot = $pressureRoot
$sourceFieldQueryRoot = $fieldQueryRoot
$sourceGdcicReadbackRoot = $gdcicReadbackRoot
$sourceStage6Root = $stage6Root
$sourceStage6MergedRoot = $stage6MergedRoot
if ($SourceRegressionRunRoot) {
    $sourcePressureRoot = Join-Path $SourceRegressionRunRoot "pressure"
    $sourceFieldQueryRoot = Join-Path $SourceRegressionRunRoot "field-query"
    $sourceGdcicReadbackRoot = Join-Path $SourceRegressionRunRoot "gdcic-browser-authorized-readback"
    $sourceStage6Root = Join-Path $SourceRegressionRunRoot "stage6-cycle"
    $sourceStage6MergedRoot = Join-Path $SourceRegressionRunRoot "stage6-loop-merged"
}

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"
$priorScoreboardJsonForIncrementalMerge = ""

function Resolve-RepoPath {
    param([string]$Value)
    if (-not $Value) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Value))
}

function Resolve-ExistingDir {
    param([string]$Value)
    if (-not $Value) {
        return ""
    }
    $resolved = Resolve-RepoPath "$Value"
    if (Test-Path -Path $resolved -PathType Container) {
        return $resolved
    }
    return ""
}

function Expand-StringList {
    param([string[]]$Values)
    $items = @()
    foreach ($value in $Values) {
        if (-not $value) {
            continue
        }
        foreach ($part in ($value -split "[;,]")) {
            $text = $part.Trim().Trim('"')
            if ($text) {
                $items += $text
            }
        }
    }
    return $items
}

$ExcludeProjectId = Expand-StringList $ExcludeProjectId
$ExcludeScoreboardJson = Expand-StringList $ExcludeScoreboardJson
$followupQueue = $null
$executionPlan = $null

if ($ApplyStage4FollowupExecutionPlan) {
    if (-not $Stage4BackfillFollowupQueueJson) {
        Write-Error "ApplyStage4FollowupExecutionPlan requires -Stage4BackfillFollowupQueueJson."
        exit 1
    }
    if (-not (Test-Path $Stage4BackfillFollowupQueueJson)) {
        Write-Error "Stage4BackfillFollowupQueueJson not found: $Stage4BackfillFollowupQueueJson"
        exit 1
    }
    $followupQueue = Get-Content -LiteralPath $Stage4BackfillFollowupQueueJson -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    $executionPlan = $followupQueue.next_regression_execution_plan
    if (-not $executionPlan) {
        Write-Error "Stage4BackfillFollowupQueueJson has no next_regression_execution_plan."
        exit 1
    }
    if ($executionPlan.live_execution_enabled_by_default -eq $true) {
        Write-Error "Refusing execution plan with live_execution_enabled_by_default=true."
        exit 1
    }
    if (-not $ProjectIds -and $executionPlan.target_project_ids) {
        $ProjectIds = @($executionPlan.target_project_ids) -join ","
    }
    $overrides = $executionPlan.recommended_parameter_overrides
    if ($overrides) {
        if ($overrides.MaxLiveP13BCompanies -and -not $PSBoundParameters.ContainsKey("MaxLiveP13BCompanies")) {
            $MaxLiveP13BCompanies = [int]$overrides.MaxLiveP13BCompanies
        }
        if ($overrides.MaxBidRecordsPerCompany -and -not $PSBoundParameters.ContainsKey("MaxBidRecordsPerCompany")) {
            $MaxBidRecordsPerCompany = [int]$overrides.MaxBidRecordsPerCompany
        }
        if ($overrides.MaxBidListPagesPerCompany -and -not $PSBoundParameters.ContainsKey("MaxBidListPagesPerCompany")) {
            $MaxBidListPagesPerCompany = [int]$overrides.MaxBidListPagesPerCompany
        }
        if ($overrides.MaxLongTailBidShowsPerCompany -and -not $PSBoundParameters.ContainsKey("MaxLongTailBidShowsPerCompany")) {
            $MaxLongTailBidShowsPerCompany = [int]$overrides.MaxLongTailBidShowsPerCompany
        }
        if ($overrides.MaxLiveOriginalNotices -and -not $PSBoundParameters.ContainsKey("MaxLiveOriginalNotices")) {
            $MaxLiveOriginalNotices = [int]$overrides.MaxLiveOriginalNotices
        }
        if ($overrides.MaxLiveYgpOriginalNotices -and -not $PSBoundParameters.ContainsKey("MaxLiveYgpOriginalNotices")) {
            $MaxLiveYgpOriginalNotices = [int]$overrides.MaxLiveYgpOriginalNotices
        }
        if ($overrides.MaxLiveYgpBackfillTasks -and -not $PSBoundParameters.ContainsKey("MaxLiveYgpBackfillTasks")) {
            $MaxLiveYgpBackfillTasks = [int]$overrides.MaxLiveYgpBackfillTasks
        }
    }
    $recommendedSwitches = @($executionPlan.recommended_switches)
    if ($recommendedSwitches -contains "RunP13BPublicSourceChain" -and -not $PSBoundParameters.ContainsKey("RunP13BPublicSourceChain")) {
        $RunP13BPublicSourceChain = $true
    }
    if ($recommendedSwitches -contains "RunYgpBackfillFieldQuery" -and -not $PSBoundParameters.ContainsKey("RunYgpBackfillFieldQuery")) {
        $RunYgpBackfillFieldQuery = $true
    }
    if ($recommendedSwitches -contains "RunStage6MergedProjection" -and -not $PSBoundParameters.ContainsKey("RunStage6MergedProjection")) {
        $RunStage6MergedProjection = $true
    }
    Write-Host "[stage1-6-regression] applied Stage4 follow-up execution plan from $Stage4BackfillFollowupQueueJson"
    Write-Host "[stage1-6-regression] live public query remains explicit; EnableLivePublicQuery=$($EnableLivePublicQuery.IsPresent)"
} elseif ($Stage4BackfillFollowupQueueJson) {
    $resolvedFollowupQueueJson = Resolve-RepoPath "$Stage4BackfillFollowupQueueJson"
    if (-not (Test-Path $resolvedFollowupQueueJson)) {
        Write-Error "Stage4BackfillFollowupQueueJson not found: $Stage4BackfillFollowupQueueJson"
        exit 1
    }
    $Stage4BackfillFollowupQueueJson = $resolvedFollowupQueueJson
    $followupQueue = Get-Content -LiteralPath $Stage4BackfillFollowupQueueJson -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    $executionPlan = $followupQueue.next_regression_execution_plan
    if (-not $ProjectIds -and $executionPlan -and $executionPlan.target_project_ids) {
        $ProjectIds = @($executionPlan.target_project_ids) -join ","
    }
    Write-Host "[stage1-6-regression] loaded Stage4 follow-up queue for incremental scoreboard merge: $Stage4BackfillFollowupQueueJson"
}

if ($followupQueue) {
    $scoreboardPayload = $null
    if ($followupQueue -and $followupQueue.input_refs -and $followupQueue.input_refs.scoreboard_json) {
        $scoreboardPath = Resolve-RepoPath "$($followupQueue.input_refs.scoreboard_json)"
        if (Test-Path $scoreboardPath) {
            $priorScoreboardJsonForIncrementalMerge = $scoreboardPath
            $scoreboardPayload = Get-Content -LiteralPath $scoreboardPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        }
    }

    $continuationRefs = $null
    if ($followupQueue.continuation_input_refs) {
        $continuationRefs = $followupQueue.continuation_input_refs
    } elseif ($executionPlan -and $executionPlan.continuation_input_refs) {
        $continuationRefs = $executionPlan.continuation_input_refs
    }
    if ($continuationRefs) {
        if (-not $priorScoreboardJsonForIncrementalMerge -and $continuationRefs.prior_scoreboard_json) {
            $candidatePriorScoreboardJson = Resolve-RepoPath "$($continuationRefs.prior_scoreboard_json)"
            if (Test-Path $candidatePriorScoreboardJson) {
                $priorScoreboardJsonForIncrementalMerge = $candidatePriorScoreboardJson
                if (-not $scoreboardPayload) {
                    $scoreboardPayload = Get-Content -LiteralPath $candidatePriorScoreboardJson -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
                }
            }
        }
        $continuationPressureRoot = Resolve-ExistingDir "$($continuationRefs.effective_pressure_root)"
        if ($continuationPressureRoot -and (Test-Path (Join-Path $continuationPressureRoot "stage4-release-adapter-bridge-plan.json"))) {
            $sourcePressureRoot = $continuationPressureRoot
            Write-Host "[stage1-6-regression] reused pressure root from follow-up continuation_input_refs: $sourcePressureRoot"
        }
        $continuationFieldQueryRoot = Resolve-ExistingDir "$($continuationRefs.effective_release_field_query_root)"
        if ($continuationFieldQueryRoot -and (Test-Path (Join-Path $continuationFieldQueryRoot "guangdong-local-field-query-probe-v1.json"))) {
            $sourceFieldQueryRoot = $continuationFieldQueryRoot
            Write-Host "[stage1-6-regression] reused field query root from follow-up continuation_input_refs: $sourceFieldQueryRoot"
        }
        if (-not $SupplementalFieldQueryJson -and $continuationRefs.effective_supplemental_release_field_query_json) {
            $continuationSupplementalFieldQueryJson = Resolve-RepoPath "$($continuationRefs.effective_supplemental_release_field_query_json)"
            if (Test-Path $continuationSupplementalFieldQueryJson) {
                $SupplementalFieldQueryJson = $continuationSupplementalFieldQueryJson
                Write-Host "[stage1-6-regression] reused supplemental field query json from follow-up continuation_input_refs: $SupplementalFieldQueryJson"
            }
        }
        if (-not $SupplementalFieldQueryRoot -and $continuationRefs.effective_supplemental_release_field_query_root) {
            $continuationSupplementalFieldQueryRoot = Resolve-ExistingDir "$($continuationRefs.effective_supplemental_release_field_query_root)"
            if ($continuationSupplementalFieldQueryRoot -and (Test-Path (Join-Path $continuationSupplementalFieldQueryRoot "guangdong-local-field-query-probe-v1.json"))) {
                $SupplementalFieldQueryRoot = $continuationSupplementalFieldQueryRoot
                Write-Host "[stage1-6-regression] reused supplemental field query root from follow-up continuation_input_refs: $SupplementalFieldQueryRoot"
            }
        }
        $continuationGdcicRoot = Resolve-ExistingDir "$($continuationRefs.effective_gdcic_browser_readback_root)"
        if ($continuationGdcicRoot -and (Test-Path (Join-Path $continuationGdcicRoot "gdcic-browser-authorized-readback-v1.json"))) {
            $sourceGdcicReadbackRoot = $continuationGdcicRoot
            Write-Host "[stage1-6-regression] reused gdcic-browser readback root from follow-up continuation_input_refs: $sourceGdcicReadbackRoot"
        }
        $continuationStage6Root = Resolve-ExistingDir "$($continuationRefs.effective_stage6_status_root)"
        if ($continuationStage6Root -and (
            (Test-Path (Join-Path $continuationStage6Root "stage6-review-loop-project-status-table.json")) -or
            (Test-Path (Join-Path $continuationStage6Root "stage6-review-cycle-runner-v1.json"))
        )) {
            $sourceStage6MergedRoot = $continuationStage6Root
            Write-Host "[stage1-6-regression] reused Stage6 status root from follow-up continuation_input_refs: $sourceStage6MergedRoot"
        }
    }

    $sourceReleasePlanJson = Join-Path $sourcePressureRoot "stage4-release-adapter-bridge-plan.json"
    if (-not (Test-Path $sourceReleasePlanJson) -and $scoreboardPayload -and $scoreboardPayload.input_refs) {
        $pressureRefCandidates = @(
            $scoreboardPayload.input_refs.pressure_summary_json,
            $scoreboardPayload.input_refs.stage1_6_readiness_json,
            $scoreboardPayload.input_refs.stage1_6_gap_summary_json
        )
        foreach ($pressureRef in $pressureRefCandidates) {
            if (-not $pressureRef) {
                continue
            }
            $resolvedPressureRef = Resolve-RepoPath "$pressureRef"
            if (-not (Test-Path $resolvedPressureRef)) {
                continue
            }
            $candidatePressureRoot = Split-Path -Parent $resolvedPressureRef
            $candidateReleasePlanJson = Join-Path $candidatePressureRoot "stage4-release-adapter-bridge-plan.json"
            if (Test-Path $candidateReleasePlanJson) {
                $sourcePressureRoot = $candidatePressureRoot
                Write-Host "[stage1-6-regression] reused pressure root from scoreboard input_refs: $sourcePressureRoot"
                break
            }
        }
    }

    $sourceFieldQueryJson = Join-Path $sourceFieldQueryRoot "guangdong-local-field-query-probe-v1.json"
    if (-not (Test-Path $sourceFieldQueryJson) -and $scoreboardPayload -and $scoreboardPayload.input_refs -and $scoreboardPayload.input_refs.release_field_query_json) {
        $scoreboardFieldQueryJson = Resolve-RepoPath "$($scoreboardPayload.input_refs.release_field_query_json)"
        if (Test-Path $scoreboardFieldQueryJson) {
            $sourceFieldQueryRoot = Split-Path -Parent $scoreboardFieldQueryJson
            Write-Host "[stage1-6-regression] reused primary release field query from scoreboard input_refs: $scoreboardFieldQueryJson"
        }
    }

    if (-not $SupplementalFieldQueryJson -and -not $SupplementalFieldQueryRoot -and $scoreboardPayload -and $scoreboardPayload.input_refs -and $scoreboardPayload.input_refs.supplemental_release_field_query_json) {
        $scoreboardSupplementalFieldQueryJson = Resolve-RepoPath "$($scoreboardPayload.input_refs.supplemental_release_field_query_json)"
        if (Test-Path $scoreboardSupplementalFieldQueryJson) {
            $SupplementalFieldQueryJson = $scoreboardSupplementalFieldQueryJson
            $SupplementalFieldQueryRoot = Split-Path -Parent $scoreboardSupplementalFieldQueryJson
            Write-Host "[stage1-6-regression] reused supplemental release field query from scoreboard input_refs: $scoreboardSupplementalFieldQueryJson"
        }
    }

    $sourceGdcicJson = Join-Path $sourceGdcicReadbackRoot "gdcic-browser-authorized-readback-v1.json"
    if (-not (Test-Path $sourceGdcicJson) -and $scoreboardPayload -and $scoreboardPayload.input_refs -and $scoreboardPayload.input_refs.gdcic_browser_authorized_readback_json) {
        $scoreboardGdcicJson = Resolve-RepoPath "$($scoreboardPayload.input_refs.gdcic_browser_authorized_readback_json)"
        if (Test-Path $scoreboardGdcicJson) {
            $sourceGdcicReadbackRoot = Split-Path -Parent $scoreboardGdcicJson
            Write-Host "[stage1-6-regression] reused gdcic-browser-authorized-readback from scoreboard input_refs: $scoreboardGdcicJson"
        }
    }
}

if ($DescribeEffectivePlanAndExit) {
    $effectivePlan = [ordered]@{
        run_root = "$RunRoot"
        source_regression_run_root = "$SourceRegressionRunRoot"
        run_switches = [ordered]@{
            RunPressure = [bool]$RunPressure
            RunFieldQuery = [bool]$RunFieldQuery
            RunStage6Cycle = [bool]$RunStage6Cycle
            RunGdcicAuthorizedReadback = [bool]$RunGdcicAuthorizedReadback
            RunP13BPublicSourceChain = [bool]$RunP13BPublicSourceChain
            RunYgpBackfillFieldQuery = [bool]$RunYgpBackfillFieldQuery
            RunStage6MergedProjection = [bool]$RunStage6MergedProjection
            EnableLivePublicQuery = [bool]$EnableLivePublicQuery
            EnableLiveBrowserExecution = [bool]$EnableLiveBrowserExecution
        }
        budget_parameters = [ordered]@{
            CandidateLimit = $CandidateLimit
            DetailCaptureLimit = $DetailCaptureLimit
            AttachmentCaptureLimit = $AttachmentCaptureLimit
            MaxLiveFieldTasks = $MaxLiveFieldTasks
            MaxLiveBrowserTasks = $MaxLiveBrowserTasks
            MaxLiveP13BCompanies = $MaxLiveP13BCompanies
            MaxBidRecordsPerCompany = $MaxBidRecordsPerCompany
            MaxBidListPagesPerCompany = $MaxBidListPagesPerCompany
            MaxLongTailBidShowsPerCompany = $MaxLongTailBidShowsPerCompany
            MaxLiveOriginalNotices = $MaxLiveOriginalNotices
            MaxLiveYgpOriginalNotices = $MaxLiveYgpOriginalNotices
            MaxLiveYgpBackfillTasks = $MaxLiveYgpBackfillTasks
            ExcludeProjectId = @($ExcludeProjectId)
            ExcludeScoreboardJson = @($ExcludeScoreboardJson)
        }
        input_refs = [ordered]@{
            ScoreboardComparisonJson = "$ScoreboardComparisonJson"
            Stage4BackfillFollowupQueueJson = "$Stage4BackfillFollowupQueueJson"
            EffectivePressureRoot = "$sourcePressureRoot"
            EffectiveFieldQueryRoot = "$sourceFieldQueryRoot"
            EffectiveSupplementalFieldQueryRoot = "$SupplementalFieldQueryRoot"
            EffectiveSupplementalFieldQueryJson = "$SupplementalFieldQueryJson"
            EffectiveGdcicBrowserReadbackRoot = "$sourceGdcicReadbackRoot"
        }
        target = [ordered]@{
            ProjectIds = "$ProjectIds"
        }
        safety = [ordered]@{
            customer_visible_allowed = $false
            external_send_enabled = $false
            payment_execution_enabled = $false
            delivery_execution_enabled = $false
            automatic_refund_enabled = $false
            live_public_query_requires_explicit_switch = $true
            query_miss_is_not_clearance = $true
            no_legal_conclusion = $true
        }
    }
    $effectivePlan | ConvertTo-Json -Depth 20
    exit 0
}

if ($RunPressure) {
    $pressureArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\run-guangzhou-stage1-6-real-public-pressure-v1.ps1"),
        "-OutputRoot", $pressureRoot,
        "-CandidateLimit", "$CandidateLimit",
        "-DetailCaptureLimit", "$DetailCaptureLimit",
        "-AttachmentCaptureLimit", "$AttachmentCaptureLimit"
    )
    $resolvedExcludeProjectIds = @()
    foreach ($projectId in $ExcludeProjectId) {
        if ($projectId) {
            $resolvedExcludeProjectIds += $projectId
        }
    }
    if ($resolvedExcludeProjectIds.Count -gt 0) {
        $pressureArgs += @("-ExcludeProjectId", ($resolvedExcludeProjectIds -join ","))
    }
    $resolvedExcludeScoreboards = @()
    foreach ($scoreboardJson in $ExcludeScoreboardJson) {
        if ($scoreboardJson) {
            $resolvedExcludeScoreboards += (Resolve-RepoPath "$scoreboardJson")
        }
    }
    if ($resolvedExcludeScoreboards.Count -gt 0) {
        $pressureArgs += @("-ExcludeScoreboardJson", ($resolvedExcludeScoreboards -join ","))
    }
    if ($AttemptAllStage16Candidates) {
        $pressureArgs += "-AttemptAllStage16Candidates"
    }
    & pwsh @pressureArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & python -m storage.real_public_stage1_6_pressure_report `
        --mode build `
        --output-root $pressureRoot `
        --run-result-json (Join-Path $pressureRoot "run-result.json") `
        --candidate-limit $CandidateLimit
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$effectivePressureRoot = if ($RunPressure -or -not $SourceRegressionRunRoot) { $pressureRoot } else { $sourcePressureRoot }
$releasePlanJson = Join-Path $effectivePressureRoot "stage4-release-adapter-bridge-plan.json"
if ($RunFieldQuery) {
    $fieldArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\run-guangdong-local-field-query-probe-v1.ps1"),
        "-ReleaseEvidenceAdapterPlanJson", $releasePlanJson,
        "-OutputRoot", $fieldQueryRoot,
        "-MaxLiveTasks", "$MaxLiveFieldTasks"
    )
    if ($EnableLivePublicQuery) {
        $fieldArgs += "-EnableLivePublicQuery"
    }
    & pwsh @fieldArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$effectiveFieldQueryRoot = if ($RunFieldQuery -or -not $SourceRegressionRunRoot) { $fieldQueryRoot } else { $sourceFieldQueryRoot }
$fieldQueryJson = Join-Path $effectiveFieldQueryRoot "guangdong-local-field-query-probe-v1.json"
if ($RunStage6Cycle) {
    if (-not (Test-Path $fieldQueryJson)) {
        Write-Error "RunStage6Cycle requires guangdong-local-field-query-probe-v1.json. Use -RunFieldQuery first or provide an existing run root."
        exit 1
    }
    & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\run-stage6-review-cycle-v1.ps1") `
        -ReleaseFieldQueryJson $fieldQueryJson `
        -OutputRoot $stage6Root
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$effectiveGdcicReadbackRoot = if ($RunGdcicAuthorizedReadback -or -not $SourceRegressionRunRoot) { $gdcicReadbackRoot } else { $sourceGdcicReadbackRoot }
$gdcicReadbackJson = Join-Path $effectiveGdcicReadbackRoot "gdcic-browser-authorized-readback-v1.json"
if ($RunGdcicAuthorizedReadback) {
    $gdcicArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-gdcic-browser-authorized-readback-v1.ps1"),
        "-ReleaseEvidenceAdapterPlanJson", $releasePlanJson,
        "-OutputRoot", $gdcicReadbackRoot,
        "-MaxLiveBrowserTasks", "$MaxLiveBrowserTasks"
    )
    if (Test-Path $fieldQueryJson) {
        $gdcicArgs += @("-FieldQueryJson", $fieldQueryJson)
    }
    if ($EnableLiveBrowserExecution) {
        $gdcicArgs += "-EnableLiveBrowserExecution"
    }
    if ($EmitJson) {
        $gdcicArgs += "-EmitJson"
    }
    & pwsh @gdcicArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$p13bCompanyHistoryJson = Join-Path $p13bCompanyHistoryRoot "company-history-overlap-triage-v1.json"
$p13bOriginalNoticeJson = Join-Path $p13bOriginalNoticeRoot "original-notice-backtrace-v1.json"
$p13bYgpReadbackJson = Join-Path $p13bYgpReadbackRoot "ygp-original-readback-v1.json"
$p13bCloseoutJson = Join-Path $p13bCloseoutRoot "p13b-overlap-triage-closeout-v1.json"
$effectiveStage4BackfillFollowupQueueJson = ""
if ($Stage4BackfillFollowupQueueJson) {
    $effectiveStage4BackfillFollowupQueueJson = Resolve-RepoPath "$Stage4BackfillFollowupQueueJson"
} elseif (Test-Path (Join-Path $stage4BackfillFollowupQueueRoot "stage4-backfill-followup-queue-v1.json")) {
    $effectiveStage4BackfillFollowupQueueJson = Join-Path $stage4BackfillFollowupQueueRoot "stage4-backfill-followup-queue-v1.json"
}
if ($RunP13BPublicSourceChain) {
    if (-not (Test-Path $gdcicReadbackJson) -and (-not $effectiveStage4BackfillFollowupQueueJson -or -not (Test-Path $effectiveStage4BackfillFollowupQueueJson))) {
        Write-Error "RunP13BPublicSourceChain requires gdcic-browser-authorized-readback-v1.json or Stage4BackfillFollowupQueueJson."
        exit 1
    }
    $p13bArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-p13b-company-history-overlap-triage-v1.ps1"),
        "-OutputRoot", $p13bCompanyHistoryRoot,
        "-MaxLiveCompanies", "$MaxLiveP13BCompanies",
        "-MaxBidRecordsPerCompany", "$MaxBidRecordsPerCompany",
        "-MaxBidListPagesPerCompany", "$MaxBidListPagesPerCompany",
        "-MaxLongTailBidShowsPerCompany", "$MaxLongTailBidShowsPerCompany"
    )
    if (Test-Path $gdcicReadbackJson) {
        $p13bArgs += @("-GdcicBrowserReadbackRoot", $effectiveGdcicReadbackRoot)
    } elseif ($effectiveStage4BackfillFollowupQueueJson) {
        $p13bArgs += @("-Stage4BackfillFollowupQueueJson", $effectiveStage4BackfillFollowupQueueJson)
        if (Test-Path $fieldQueryJson) {
            $p13bArgs += @("-ReleaseFieldQueryJson", $fieldQueryJson)
        }
    }
    if ($ProjectIds) {
        $p13bArgs += @("-ProjectIds", $ProjectIds)
    }
    if ($EnableLivePublicQuery) {
        $p13bArgs += "-EnableLivePublicQuery"
    }
    if ($EmitJson) {
        $p13bArgs += "-EmitJson"
    }
    & pwsh @p13bArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $originalArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-p13b-original-notice-backtrace-v1.ps1"),
        "-CompanyHistoryTriageRoot", $p13bCompanyHistoryRoot,
        "-OutputRoot", $p13bOriginalNoticeRoot,
        "-MaxLiveOriginalNotices", "$MaxLiveOriginalNotices"
    )
    if ($ProjectIds) {
        $originalArgs += @("-ProjectIds", $ProjectIds)
    }
    if ($EnableLivePublicQuery) {
        $originalArgs += "-EnableLivePublicQuery"
    }
    if ($EmitJson) {
        $originalArgs += "-EmitJson"
    }
    & pwsh @originalArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $ygpArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-p13b-ygp-original-readback-v1.ps1"),
        "-InputRoot", $p13bOriginalNoticeRoot,
        "-OutputRoot", $p13bYgpReadbackRoot,
        "-MaxLiveOriginalNotices", "$MaxLiveYgpOriginalNotices"
    )
    if ($EnableLivePublicQuery) {
        $ygpArgs += "-EnableLivePublicQuery"
    }
    if ($EmitJson) {
        $ygpArgs += "-EmitJson"
    }
    & pwsh @ygpArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $closeoutArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-p13b-overlap-triage-closeout-v1.ps1"),
        "-CompanyHistoryTriageRoot", $p13bCompanyHistoryRoot,
        "-OriginalNoticeBacktraceRoot", $p13bOriginalNoticeRoot,
        "-YgpReadbackRoot", $p13bYgpReadbackRoot,
        "-OutputRoot", $p13bCloseoutRoot
    )
    if ($EmitJson) {
        $closeoutArgs += "-EmitJson"
    }
    & pwsh @closeoutArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$ygpBackfillFieldQueryJson = Join-Path $ygpBackfillFieldQueryRoot "guangdong-local-field-query-probe-v1.json"
if ($RunYgpBackfillFieldQuery) {
    if (-not (Test-Path $p13bCloseoutJson)) {
        Write-Error "RunYgpBackfillFieldQuery requires p13b-overlap-triage-closeout-v1.json. Use -RunP13BPublicSourceChain first or provide an existing run root."
        exit 1
    }
    $ygpBackfillArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\run-guangdong-local-field-query-probe-v1.ps1"),
        "-ReleaseEvidenceAdapterPlanJson", $p13bCloseoutJson,
        "-OutputRoot", $ygpBackfillFieldQueryRoot,
        "-SourceProfileIds", "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
        "-MaxLiveTasks", "$MaxLiveYgpBackfillTasks"
    )
    if ($EnableLivePublicQuery) {
        $ygpBackfillArgs += "-EnableLivePublicQuery"
    }
    if ($EmitJson) {
        $ygpBackfillArgs += "-EmitJson"
    }
    & pwsh @ygpBackfillArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not $SupplementalFieldQueryRoot -and (Test-Path $ygpBackfillFieldQueryJson)) {
    $SupplementalFieldQueryRoot = $ygpBackfillFieldQueryRoot
}
if (-not $SupplementalFieldQueryJson -and (Test-Path $ygpBackfillFieldQueryJson)) {
    $SupplementalFieldQueryJson = $ygpBackfillFieldQueryJson
}

if ($RunStage6MergedProjection) {
    $hasPrimaryFieldQuery = Test-Path $fieldQueryJson
    $hasSupplementalFieldQuery = ($SupplementalFieldQueryJson -and (Test-Path $SupplementalFieldQueryJson)) -or (
        $SupplementalFieldQueryRoot -and (Test-Path (Join-Path $SupplementalFieldQueryRoot "guangdong-local-field-query-probe-v1.json"))
    )
    if (-not $hasPrimaryFieldQuery -and -not $hasSupplementalFieldQuery) {
        Write-Error "RunStage6MergedProjection requires primary or supplemental guangdong-local-field-query-probe-v1.json. Use -RunFieldQuery, -RunYgpBackfillFieldQuery, or provide an existing run root."
        exit 1
    }
    $stage6MergedArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\run-stage6-review-loop-v1.ps1"),
        "-DispatchRoot", (Join-Path $RunRoot "missing-dispatch"),
        "-BatchCloseoutRoot", (Join-Path $RunRoot "missing-closeout"),
        "-OutputRoot", $stage6MergedRoot,
        "-DisableAutoDiscoverLatestBatchCloseout"
    )
    if ($hasPrimaryFieldQuery) {
        $stage6MergedArgs += @("-ReleaseFieldQueryJson", $fieldQueryJson)
    }
    if ($ProjectIds) {
        $stage6MergedArgs += @("-ProjectIds", $ProjectIds)
    }
    if ($SupplementalFieldQueryJson) {
        $stage6MergedArgs += @("-SupplementalReleaseFieldQueryJson", $SupplementalFieldQueryJson)
    } elseif ($SupplementalFieldQueryRoot) {
        $stage6MergedArgs += @("-SupplementalReleaseFieldQueryRoot", $SupplementalFieldQueryRoot)
    }
    if ($EmitJson) {
        $stage6MergedArgs += "-EmitJson"
    }
    & pwsh @stage6MergedArgs
    $stage6MergedExitCode = $LASTEXITCODE
    if ($stage6MergedExitCode -ne 0) {
        $stage6MergedStatusJson = Join-Path $stage6MergedRoot "stage6-review-loop-project-status-table.json"
        $stage6MergedRunnerJson = Join-Path $stage6MergedRoot "stage6-review-loop-runner-v1.json"
        if ((Test-Path $stage6MergedStatusJson) -or (Test-Path $stage6MergedRunnerJson)) {
            Write-Warning "RunStage6MergedProjection returned exit code $stage6MergedExitCode but emitted a status artifact; continuing so scoreboard can record the blocked state."
        } else {
            exit $stage6MergedExitCode
        }
    }
}

$effectiveStage6Root = if ($SourceRegressionRunRoot) { $sourceStage6Root } else { $stage6Root }
if (Test-Path (Join-Path $stage6MergedRoot "stage6-review-loop-project-status-table.json")) {
    $effectiveStage6Root = $stage6MergedRoot
} elseif ($SourceRegressionRunRoot -and (Test-Path (Join-Path $sourceStage6MergedRoot "stage6-review-loop-project-status-table.json"))) {
    $effectiveStage6Root = $sourceStage6MergedRoot
}

$stage6StatusJson = Join-Path $effectiveStage6Root "stage6-review-loop-project-status-table.json"
if (-not (Test-Path $stage6StatusJson)) {
    $stage6StatusJson = Join-Path $effectiveStage6Root "stage6-review-cycle-runner-v1.json"
}

$scoreboardArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $repoRoot "scripts\build-stage1-6-sellable-scoreboard-v1.ps1"),
    "-PressureRoot", $effectivePressureRoot,
    "-FieldQueryRoot", $effectiveFieldQueryRoot,
    "-GdcicBrowserReadbackRoot", $effectiveGdcicReadbackRoot,
    "-P13BCompanyHistoryRoot", $p13bCompanyHistoryRoot,
    "-P13BOriginalNoticeBacktraceRoot", $p13bOriginalNoticeRoot,
    "-P13BYgpOriginalReadbackRoot", $p13bYgpReadbackRoot,
    "-P13BOverlapTriageCloseoutRoot", $p13bCloseoutRoot,
    "-Stage6StatusRoot", $effectiveStage6Root,
    "-OutputRoot", $scoreboardRoot
)
if (Test-Path $fieldQueryJson) {
    $scoreboardArgs += @("-FieldQueryJson", $fieldQueryJson)
}
if ($SupplementalFieldQueryRoot) {
    $scoreboardArgs += @("-SupplementalFieldQueryRoot", $SupplementalFieldQueryRoot)
}
if ($SupplementalFieldQueryJson) {
    $scoreboardArgs += @("-SupplementalFieldQueryJson", $SupplementalFieldQueryJson)
}
if (Test-Path $stage6StatusJson) {
    $scoreboardArgs += @("-Stage6StatusJson", $stage6StatusJson)
}
if ($priorScoreboardJsonForIncrementalMerge -and $ProjectIds) {
    $scoreboardArgs += @("-PriorScoreboardJson", $priorScoreboardJsonForIncrementalMerge)
    $scoreboardArgs += @("-IncrementalProjectIds", $ProjectIds)
}
if (Test-Path $gdcicReadbackJson) {
    $scoreboardArgs += @("-GdcicBrowserReadbackJson", $gdcicReadbackJson)
}
if (Test-Path $p13bCompanyHistoryJson) {
    $scoreboardArgs += @("-P13BCompanyHistoryJson", $p13bCompanyHistoryJson)
}
if (Test-Path $p13bOriginalNoticeJson) {
    $scoreboardArgs += @("-P13BOriginalNoticeBacktraceJson", $p13bOriginalNoticeJson)
}
if (Test-Path $p13bYgpReadbackJson) {
    $scoreboardArgs += @("-P13BYgpOriginalReadbackJson", $p13bYgpReadbackJson)
}
if (Test-Path $p13bCloseoutJson) {
    $scoreboardArgs += @("-P13BOverlapTriageCloseoutJson", $p13bCloseoutJson)
}
if ($EmitJson) {
    $scoreboardArgs += "-EmitJson"
}

& pwsh @scoreboardArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$scoreboardJson = Join-Path $scoreboardRoot "stage1-6-sellable-scoreboard-v1.json"
if (Test-Path $scoreboardJson) {
    $stage4BackfillFollowupArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-stage4-backfill-followup-queue-v1.ps1"),
        "-ScoreboardJson", $scoreboardJson,
        "-OutputRoot", $stage4BackfillFollowupQueueRoot
    )
    if ($ScoreboardComparisonJson) {
        $stage4BackfillFollowupArgs += @("-ScoreboardComparisonJson", $ScoreboardComparisonJson)
    }
    if ($EmitJson) {
        $stage4BackfillFollowupArgs += "-EmitJson"
    }
    & pwsh @stage4BackfillFollowupArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
