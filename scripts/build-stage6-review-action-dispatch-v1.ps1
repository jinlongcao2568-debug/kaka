param(
    [string]$Stage6FactPackageJson = "",
    [string]$Stage6FactPackageRoot = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $Stage6FactPackageRoot) {
    $Stage6FactPackageRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\evidence-stage6-fact-package-v1"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\stage6-review-action-dispatch-v1"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.stage6_review_action_dispatch",
    "--stage6-fact-package-root", $Stage6FactPackageRoot,
    "--output-root", $OutputRoot
)

if ($Stage6FactPackageJson) {
    $argsList += @("--stage6-fact-package-json", $Stage6FactPackageJson)
}
if ($EmitJson) {
    $argsList += "--json"
}

Push-Location $repoRoot
try {
    python @argsList
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
