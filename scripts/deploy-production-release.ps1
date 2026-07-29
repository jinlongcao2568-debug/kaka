[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$EnvironmentFile,
    [Parameter(Mandatory = $true)][switch]$ConfirmProductionDeployment,
    [ValidateRange(30, 600)][int]$AlertProbeWaitSeconds = 120,
    [ValidateRange(60, 900)][int]$WaitTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$baseCompose = Join-Path $repoRoot 'docker-compose.private-pilot.yml'
$productionCompose = Join-Path $repoRoot 'docker-compose.production.yml'
$resolvedEnvironment = (Resolve-Path -LiteralPath $EnvironmentFile).Path
$composeArgs = @(
    '--env-file', $resolvedEnvironment,
    '-f', $baseCompose,
    '-f', $productionCompose
)

if (-not $ConfirmProductionDeployment) {
    throw 'Production deployment requires -ConfirmProductionDeployment.'
}

docker compose @composeArgs config --quiet
if ($LASTEXITCODE -ne 0) {
    throw 'Production Compose configuration is invalid.'
}

docker compose @composeArgs pull
if ($LASTEXITCODE -ne 0) {
    throw 'One or more immutable production images could not be pulled.'
}

docker compose @composeArgs up -d --no-build --wait --wait-timeout $WaitTimeoutSeconds
if ($LASTEXITCODE -ne 0) {
    throw 'Production services failed health-gated startup.'
}

docker compose @composeArgs exec -T app python -m runtime.production_payment_provider_probe
if ($LASTEXITCODE -ne 0) {
    throw 'Stripe live account and settlement readiness probe failed.'
}

docker compose @composeArgs exec -T app python -m runtime.production_alert_probe --wait-seconds $AlertProbeWaitSeconds
if ($LASTEXITCODE -ne 0) {
    throw 'Actual production alert delivery probe failed.'
}

docker compose @composeArgs exec -T app python -m runtime.production_release_preflight
if ($LASTEXITCODE -ne 0) {
    throw 'Production services started, but release technical gates remain blocked.'
}

Write-Output 'Production deployment is technically ready for a separate owner request and reviewer approval.'
