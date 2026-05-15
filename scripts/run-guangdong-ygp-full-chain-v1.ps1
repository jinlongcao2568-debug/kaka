param(
    [string]$OutputRoot = "tmp\evaluation-real-samples\guangdong-ygp-full-chain-v1",
    [string[]]$CityCodes = @(
        "440200", "440400", "440500", "440600", "440700", "440800", "440900",
        "441200", "441300", "441400", "441500", "441600", "441700", "441800",
        "441900", "442000", "445100", "445200", "445300"
    ),
    [int]$PerCityCandidateLimit = 1,
    [int]$MaxPagesPerCity = 5,
    [string[]]$FlowNos = @("03", "04", "07", "08"),
    [int]$MaxAttachmentsPerFlowItem = 5,
    [int]$MaxBidFilePublicityDownloadsPerProject = 2,
    [switch]$EnableAttachmentChallengeResolver,
    [switch]$Execute,
    [switch]$ExecuteStage4,
    [string]$CompanyFirstResultState = "NOT_RUN",
    [string]$NameEnumerationResultState = "NOT_RUN",
    [string]$SourceStage4RecordsJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $repoRoot "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcPath
}

$argsList = @(
    "-m", "storage.guangdong_ygp_full_chain",
    "--output-root", $OutputRoot,
    "--per-city-candidate-limit", [string]$PerCityCandidateLimit,
    "--max-pages-per-city", [string]$MaxPagesPerCity,
    "--flow-nos", (($FlowNos -join ",").Trim()),
    "--max-attachments-per-flow-item", [string]$MaxAttachmentsPerFlowItem,
    "--max-bid-file-publicity-downloads-per-project", [string]$MaxBidFilePublicityDownloadsPerProject,
    "--company-first-result-state", $CompanyFirstResultState,
    "--name-enumeration-result-state", $NameEnumerationResultState
)

$normalizedCityCodes = @()
foreach ($cityCodeValue in $CityCodes) {
    foreach ($cityCode in ([string]$cityCodeValue -split ",")) {
        $trimmed = $cityCode.Trim()
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
            $normalizedCityCodes += $trimmed
        }
    }
}

foreach ($cityCode in $normalizedCityCodes) {
    $argsList += @("--city-code", $cityCode)
}

if ($SourceStage4RecordsJson) {
    $argsList += @("--source-stage4-records-json", $SourceStage4RecordsJson)
}
if ($EnableAttachmentChallengeResolver) {
    $argsList += "--enable-attachment-challenge-resolver"
}
if ($Execute) {
    $argsList += "--execute"
}
if ($ExecuteStage4) {
    $argsList += "--execute-stage4"
}
if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    $pythonExitCode = $LASTEXITCODE
    if ($pythonExitCode -ne 0) {
        exit $pythonExitCode
    }
} finally {
    Pop-Location
}
