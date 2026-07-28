param(
    [string]$TargetsJson = "",
    [string]$OutputRoot = "",
    [string]$RunRootBase = "",
    [string]$GroupBy = "source_profile",
    [int]$PerTargetCandidateLimit = 12,
    [int]$TargetLimit = 0,
    [int]$SegmentTimeoutSeconds = 900,
    [switch]$ProfessionalSourceOnly,
    [switch]$Execute,
    [switch]$AutoExecuteSourceRemediation,
    [switch]$EnableAlternatePublicSource,
    [switch]$ForceRerun,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

function Stop-ControlledSegmentProcesses([string]$RunRoot) {
    if (-not $RunRoot) {
        return
    }
    $escapedRunRoot = $RunRoot.Replace("[", "`[").Replace("]", "`]")
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*$escapedRunRoot*" } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            } catch {
                Write-Warning "failed to stop process $($_.ProcessId) for segment run root ${RunRoot}: $($_.Exception.Message)"
            }
        }
}

function Invoke-ControlledSegmentRun([array]$RunArgs, [string]$RunRoot, [int]$TimeoutSeconds) {
    $process = Start-Process -FilePath "pwsh" -ArgumentList $RunArgs -WindowStyle Hidden -PassThru
    if ($TimeoutSeconds -gt 0) {
        $completed = $process.WaitForExit($TimeoutSeconds * 1000)
        if (-not $completed) {
            Write-Warning "controlled gray public batch segment timed out after $TimeoutSeconds seconds: $RunRoot"
            Stop-ControlledSegmentProcesses -RunRoot $RunRoot
            return 124
        }
    } else {
        $process.WaitForExit()
    }
    return [int]$process.ExitCode
}

if (-not $TargetsJson) {
    $TargetsJson = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-gray-public-source-targets-v1\controlled-gray-public-source-targets-v1.json"
}

if (-not $OutputRoot) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\controlled-gray-public-batch-segments-$stamp"
}

if (-not $RunRootBase) {
    $RunRootBase = Join-Path $OutputRoot "runs"
}

$segmentsJson = Join-Path $OutputRoot "controlled-gray-public-batch-segments-v1.json"
$aggregateRoot = Join-Path $OutputRoot "aggregate"
$aggregateJson = Join-Path $aggregateRoot "controlled-gray-public-batch-segment-aggregate-v1.json"

$planArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "build-controlled-gray-public-batch-segments-v1.ps1"),
    "-TargetsJson", $TargetsJson,
    "-OutputRoot", $OutputRoot,
    "-RunRootBase", $RunRootBase,
    "-GroupBy", $GroupBy,
    "-PerTargetCandidateLimit", "$PerTargetCandidateLimit",
    "-TargetLimit", "$TargetLimit"
)

if ($ProfessionalSourceOnly) {
    $planArgs += "-ProfessionalSourceOnly"
}

if ($Execute) {
    $planArgs += "-Execute"
}

if ($AutoExecuteSourceRemediation) {
    $planArgs += "-AutoExecuteSourceRemediation"
}

if ($EnableAlternatePublicSource) {
    $planArgs += "-EnableAlternatePublicSource"
}

& pwsh @planArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path $segmentsJson)) {
    throw "controlled gray public batch segment plan was not generated: $segmentsJson"
}

$plan = Get-Content -Raw -Path $segmentsJson -Encoding UTF8 | ConvertFrom-Json
$segments = @($plan.segment_table.records)
if ($segments.Count -eq 0) {
    throw "controlled gray public batch segment plan has no segments: $segmentsJson"
}

foreach ($segment in $segments) {
    $targetIds = @($segment.target_ids)
    if ($targetIds.Count -eq 0) {
        throw "controlled gray public batch segment has no target ids: $($segment.segment_id)"
    }
    $closeoutPath = [string]$segment.closeout_json
    if ((Test-Path $closeoutPath) -and -not $ForceRerun) {
        Write-Host "controlled gray public batch segment already complete; skipping: $($segment.segment_id)"
        continue
    }
    $runArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $scriptDir "run-controlled-live-public-batch-v1.ps1"),
        "-RunRoot", [string]$segment.run_root,
        "-TargetsJson", $TargetsJson,
        "-TargetIds", ($targetIds -join ","),
        "-TargetLimit", "$TargetLimit",
        "-PerTargetCandidateLimit", "$PerTargetCandidateLimit"
    )
    if ($ProfessionalSourceOnly) {
        $runArgs += "-ProfessionalSourceOnly"
    }
    if ($Execute) {
        $runArgs += "-Execute"
    }
    if ($AutoExecuteSourceRemediation) {
        $runArgs += "-AutoExecuteSourceRemediation"
    }
    if ($EnableAlternatePublicSource) {
        $runArgs += "-EnableAlternatePublicSource"
    }
    $exitCode = Invoke-ControlledSegmentRun -RunArgs $runArgs -RunRoot ([string]$segment.run_root) -TimeoutSeconds $SegmentTimeoutSeconds
    if ($exitCode -ne 0) {
        Write-Warning "controlled gray public batch segment did not complete: $($segment.segment_id) exit_code=$exitCode"
    }
}

$segmentRoots = @($segments | ForEach-Object { [string]$_.run_root })
$aggregateArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $scriptDir "build-controlled-gray-public-batch-segment-aggregate-v1.ps1"),
    "-SegmentPlanJson", $segmentsJson,
    "-SegmentRoots", ($segmentRoots -join ",")
)
$aggregateArgs += @("-OutputRoot", $aggregateRoot)

if ($EmitJson) {
    $aggregateArgs += "-EmitJson"
}

& pwsh @aggregateArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path $aggregateJson)) {
    throw "controlled gray public batch segment aggregate was not generated: $aggregateJson"
}

if (-not $EmitJson) {
    $aggregatePayload = Get-Content -Raw -Path $aggregateJson -Encoding UTF8 | ConvertFrom-Json
    $summary = $aggregatePayload.summary
    Write-Host "controlled gray public batch segment aggregate: state=$($summary.aggregate_gray_review_state) segments=$($summary.completed_segment_count)/$($summary.segment_count) samples=$($summary.project_sample_count) hashes=$($summary.fixed_snapshot_sha256_count) stage4_missing=$($summary.stage4_readback_missing_sample_count) source_remediation_final=$($summary.source_remediation_final_record_count)"
    Write-Host "segment plan: $segmentsJson"
    Write-Host "segment aggregate: $aggregateJson"
}
