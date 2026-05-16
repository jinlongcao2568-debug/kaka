param(
    [string]$DownloadRoot = "",
    [string]$MiniCloseoutRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $DownloadRoot) {
    $DownloadRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-morecity-smoke-v1-07-download"
}
if (-not $MiniCloseoutRoot) {
    $MiniCloseoutRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-evidence-mini-closeout-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\ygp-oversize-policy-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"

$argsList = @(
    "-m", "storage.guangdong_ygp_oversize_policy",
    "--download-root", $DownloadRoot,
    "--mini-closeout-root", $MiniCloseoutRoot,
    "--output-root", $OutputRoot
)

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
