param(
    [string]$RunRoot = "",
    [switch]$RunPressure,
    [switch]$RunFieldQuery,
    [switch]$RunStage6Cycle,
    [switch]$RunGdcicAuthorizedReadback,
    [switch]$RunP13BPublicSourceChain,
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
    [switch]$AttemptAllStage16Candidates,
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
$stage6Root = Join-Path $RunRoot "stage6-cycle"
$gdcicReadbackRoot = Join-Path $RunRoot "gdcic-browser-authorized-readback"
$p13bCompanyHistoryRoot = Join-Path $RunRoot "p13b-company-history"
$p13bOriginalNoticeRoot = Join-Path $RunRoot "p13b-original-notice"
$p13bYgpReadbackRoot = Join-Path $RunRoot "p13b-ygp-original-readback"
$p13bCloseoutRoot = Join-Path $RunRoot "p13b-overlap-closeout"
$scoreboardRoot = Join-Path $RunRoot "scoreboard"

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

if ($RunPressure) {
    $pressureArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\run-guangzhou-stage1-6-real-public-pressure-v1.ps1"),
        "-OutputRoot", $pressureRoot,
        "-CandidateLimit", "$CandidateLimit",
        "-DetailCaptureLimit", "$DetailCaptureLimit",
        "-AttachmentCaptureLimit", "$AttachmentCaptureLimit"
    )
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

$releasePlanJson = Join-Path $pressureRoot "stage4-release-adapter-bridge-plan.json"
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

$fieldQueryJson = Join-Path $fieldQueryRoot "guangdong-local-field-query-probe-v1.json"
if ($RunStage6Cycle) {
    & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\run-stage6-review-cycle-v1.ps1") `
        -ReleaseFieldQueryJson $fieldQueryJson `
        -OutputRoot $stage6Root
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$gdcicReadbackJson = Join-Path $gdcicReadbackRoot "gdcic-browser-authorized-readback-v1.json"
if ($RunGdcicAuthorizedReadback) {
    $gdcicArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-gdcic-browser-authorized-readback-v1.ps1"),
        "-ReleaseEvidenceAdapterPlanJson", $releasePlanJson,
        "-FieldQueryJson", $fieldQueryJson,
        "-OutputRoot", $gdcicReadbackRoot,
        "-MaxLiveBrowserTasks", "$MaxLiveBrowserTasks"
    )
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
if ($RunP13BPublicSourceChain) {
    if (-not (Test-Path $gdcicReadbackJson)) {
        Write-Error "RunP13BPublicSourceChain requires gdcic-browser-authorized-readback-v1.json. Use -RunGdcicAuthorizedReadback first or provide an existing run root."
        exit 1
    }
    $p13bArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\build-p13b-company-history-overlap-triage-v1.ps1"),
        "-GdcicBrowserReadbackRoot", $gdcicReadbackRoot,
        "-OutputRoot", $p13bCompanyHistoryRoot,
        "-MaxLiveCompanies", "$MaxLiveP13BCompanies",
        "-MaxBidRecordsPerCompany", "$MaxBidRecordsPerCompany",
        "-MaxBidListPagesPerCompany", "$MaxBidListPagesPerCompany",
        "-MaxLongTailBidShowsPerCompany", "$MaxLongTailBidShowsPerCompany"
    )
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

$stage6StatusJson = Join-Path $stage6Root "stage6-review-loop-project-status-table.json"
if (-not (Test-Path $stage6StatusJson)) {
    $stage6StatusJson = Join-Path $stage6Root "stage6-review-cycle-runner-v1.json"
}

$scoreboardArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $repoRoot "scripts\build-stage1-6-sellable-scoreboard-v1.ps1"),
    "-PressureRoot", $pressureRoot,
    "-FieldQueryRoot", $fieldQueryRoot,
    "-GdcicBrowserReadbackRoot", $gdcicReadbackRoot,
    "-P13BCompanyHistoryRoot", $p13bCompanyHistoryRoot,
    "-P13BOriginalNoticeBacktraceRoot", $p13bOriginalNoticeRoot,
    "-P13BYgpOriginalReadbackRoot", $p13bYgpReadbackRoot,
    "-P13BOverlapTriageCloseoutRoot", $p13bCloseoutRoot,
    "-Stage6StatusRoot", $stage6Root,
    "-OutputRoot", $scoreboardRoot
)
if (Test-Path $fieldQueryJson) {
    $scoreboardArgs += @("-FieldQueryJson", $fieldQueryJson)
}
if (Test-Path $stage6StatusJson) {
    $scoreboardArgs += @("-Stage6StatusJson", $stage6StatusJson)
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
