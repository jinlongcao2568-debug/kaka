[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$EnvironmentFile,
    [switch]$RequireActive
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

docker compose @composeArgs config --quiet
if ($LASTEXITCODE -ne 0) {
    throw 'Production Compose configuration is invalid.'
}

$runningApp = docker compose @composeArgs ps --services --status running app
if ($LASTEXITCODE -ne 0 -or $runningApp -notcontains 'app') {
    throw 'Production app service is not running.'
}

$preflightArgs = @('python', '-m', 'runtime.production_release_preflight')
if ($RequireActive) {
    $preflightArgs += '--require-active'
}
docker compose @composeArgs exec -T app @preflightArgs
if ($LASTEXITCODE -ne 0) {
    throw 'Production release preflight is blocked.'
}
