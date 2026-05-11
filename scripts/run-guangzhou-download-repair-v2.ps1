param(
    [string]$InputRoot = "",
    [string]$OutputRoot = "",
    [string]$ProjectIds = "",
    [string]$FlowNos = "08,07,04,03",
    [int]$StageTimeoutSeconds = 900,
    [int]$MaxBidFilePublicityDownloadsPerProject = 999,
    [int]$MaxAttachmentsPerFlowItem = 0,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$Execute,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$v1Script = Join-Path $scriptDir "run-guangzhou-download-probe-v1.ps1"

if (-not $InputRoot) {
    $InputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flowurl-analysis-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-download-repair-v2"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$segmentsRoot = Join-Path $OutputRoot "segments"
New-Item -ItemType Directory -Force -Path $segmentsRoot | Out-Null
$logsRoot = Join-Path $OutputRoot "logs"
New-Item -ItemType Directory -Force -Path $logsRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

function Format-Arg([string]$Value) {
    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

function Invoke-StageProcess([string[]]$ArgumentList, [string]$StdOutPath, [string]$StdErrPath, [int]$TimeoutSeconds) {
    $argumentString = ($ArgumentList | ForEach-Object { Format-Arg $_ }) -join " "
    $process = Start-Process -FilePath "pwsh" `
        -ArgumentList $argumentString `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdOutPath `
        -RedirectStandardError $StdErrPath
    if (-not $process.WaitForExit([Math]::Max(1, $TimeoutSeconds) * 1000)) {
        & taskkill /PID $process.Id /T /F | Out-Null
        return 124
    }
    return $process.ExitCode
}

$flowList = @(
    $FlowNos -split "," |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
)

$segmentRoots = @()
foreach ($flowNo in $flowList) {
    $segmentRoot = Join-Path $segmentsRoot ("flow-{0}" -f $flowNo)
    $segmentRoots += $segmentRoot
    New-Item -ItemType Directory -Force -Path $segmentRoot | Out-Null
    $stageMaxAttachments = 0
    if ($flowNo -eq "03") {
        $stageMaxAttachments = [Math]::Max(0, $MaxAttachmentsPerFlowItem)
    }

    $stageArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $v1Script,
        "-InputRoot", $InputRoot,
        "-OutputRoot", $segmentRoot,
        "-FlowNos", $flowNo,
        "-MaxBidFilePublicityDownloadsPerProject", "$MaxBidFilePublicityDownloadsPerProject",
        "-MaxAttachmentsPerFlowItem", "$stageMaxAttachments"
    )
    if ($ProjectIds) {
        $stageArgs += @("-ProjectIds", $ProjectIds)
    } else {
        $stageArgs += "-UseAllAnalysisProjects"
    }
    if ($EnableAttachmentChallengeResolver) {
        $stageArgs += "-EnableAttachmentChallengeResolver"
    }
    if ($Execute) {
        $stageArgs += "-Execute"
    }

    $stdoutPath = Join-Path $logsRoot ("flow-{0}.out.log" -f $flowNo)
    $stderrPath = Join-Path $logsRoot ("flow-{0}.err.log" -f $flowNo)
    $exitCode = Invoke-StageProcess -ArgumentList $stageArgs -StdOutPath $stdoutPath -StdErrPath $stderrPath -TimeoutSeconds $StageTimeoutSeconds
    $timedOut = $exitCode -eq 124

    $segmentArgs = @(
        "-m", "storage.guangzhou_download_repair",
        "--mode", "segment",
        "--segment-root", $segmentRoot,
        "--flow-no", $flowNo,
        "--output-json", (Join-Path $segmentRoot "download-repair-segment-manifest.json")
    )
    if ($timedOut) {
        $segmentArgs += "--timeout-interrupted"
    }
    python @segmentArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$mergedJson = Join-Path $OutputRoot "download-repair-merged-manifest.json"
$mergeArgs = @(
    "-m", "storage.guangzhou_download_repair",
    "--mode", "merge",
    "--output-root", $OutputRoot,
    "--segment-roots", ($segmentRoots -join ","),
    "--output-json", $mergedJson
)
if ($EmitJson) {
    $mergeArgs += "--json"
}

Push-Location $repoRoot
try {
    python @mergeArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
