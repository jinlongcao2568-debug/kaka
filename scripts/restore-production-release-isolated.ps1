[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$TenantId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$InstanceId,
    [Parameter(Mandatory = $true)][string]$PublicHostname,
    [Parameter(Mandatory = $true)][string]$PrincipalsFile,
    [Parameter(Mandatory = $true)][string]$PostgresPasswordFile,
    [Parameter(Mandatory = $true)][string]$BackupRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$')][string]$BackupId,
    [Parameter(Mandatory = $true)][string]$RestoreReportRoot,
    [Parameter(Mandatory = $true)][string]$EnvironmentFile,
    [Parameter(Mandatory = $true)][switch]$ConfirmIsolatedRestore,
    [ValidateRange(60, 86400)][int]$RtoTargetSeconds = 3600
)

$ErrorActionPreference = 'Stop'
$productionOverlay = [IO.Path]::GetFullPath(
    (Join-Path (Join-Path $PSScriptRoot '..') 'docker-compose.production.yml')
)
& (Join-Path $PSScriptRoot 'restore-private-pilot-isolated.ps1') `
    -TenantId $TenantId `
    -InstanceId $InstanceId `
    -PrivateHostname $PublicHostname `
    -PrincipalsFile $PrincipalsFile `
    -PostgresPasswordFile $PostgresPasswordFile `
    -BackupRoot $BackupRoot `
    -BackupId $BackupId `
    -RestoreReportRoot $RestoreReportRoot `
    -ConfirmIsolatedRestore:$ConfirmIsolatedRestore `
    -RtoTargetSeconds $RtoTargetSeconds `
    -ComposeEnvironmentFile $EnvironmentFile `
    -ProductionOverlayFile $productionOverlay `
    -RequireProductionOverlay
