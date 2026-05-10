param(
    [string]$OutputRoot = "",
    [string]$CoverageJson = "",
    [string]$OutputJson = "",
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\guangzhou-flow-interface-v1"
}

if (-not $CoverageJson) {
    $CoverageJson = Join-Path $OutputRoot "guangzhou-flow-interface-coverage.json"
}

if (-not (Test-Path $CoverageJson)) {
    throw "Coverage json not found: $CoverageJson"
}

$payload = Get-Content -Raw -Encoding UTF8 $CoverageJson | ConvertFrom-Json -Depth 100

if ($OutputJson) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputJson) | Out-Null
    $payload | ConvertTo-Json -Depth 100 | Set-Content -Encoding UTF8 $OutputJson
}

if ($EmitJson) {
    $payload | ConvertTo-Json -Depth 100
    exit 0
}

$summary = $payload.summary
if (-not $summary -and $payload.manifest) {
    $summary = $payload.manifest.summary
}

Write-Host "guangzhou flow interface coverage report"
Write-Host ("coverage_state={0}" -f $summary.interface_coverage_state)
Write-Host ("required_flow_covered={0}/{1}" -f $summary.required_flow_covered_count, $summary.required_flow_count)
Write-Host ("sample_interface_count={0}" -f $summary.sample_interface_count)
Write-Host ("attachment_snapshot_count={0}" -f $summary.attachment_snapshot_count)

if ($summary.missing_required_flow_nos -and $summary.missing_required_flow_nos.Count -gt 0) {
    Write-Host ("missing_required_flow_nos={0}" -f (($summary.missing_required_flow_nos | ForEach-Object { $_ }) -join ","))
}

if ($summary.optional_missing_flow_nos -and $summary.optional_missing_flow_nos.Count -gt 0) {
    Write-Host ("optional_missing_flow_nos={0}" -f (($summary.optional_missing_flow_nos | ForEach-Object { $_ }) -join ","))
}
