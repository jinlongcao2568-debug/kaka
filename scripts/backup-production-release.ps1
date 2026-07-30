[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$TenantId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$InstanceId,
    [Parameter(Mandatory = $true)][string]$PublicHostname,
    [Parameter(Mandatory = $true)][string]$PrincipalsFile,
    [Parameter(Mandatory = $true)][string]$PostgresPasswordFile,
    [Parameter(Mandatory = $true)][string]$BackupRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$')][string]$BackupId,
    [Parameter(Mandatory = $true)][string]$EnvironmentFile,
    [Parameter(Mandatory = $true)][switch]$PauseWriters,
    [ValidateRange(300, 604800)][int]$ScheduleIntervalSeconds = 21600,
    [ValidateRange(300, 1209600)][int]$RpoTargetSeconds = 28800,
    [switch]$LeaveWritersStopped
)

$ErrorActionPreference = 'Stop'
$productionOverlay = [IO.Path]::GetFullPath(
    (Join-Path (Join-Path $PSScriptRoot '..') 'docker-compose.production.yml')
)
& (Join-Path $PSScriptRoot 'backup-private-pilot.ps1') `
    -TenantId $TenantId `
    -InstanceId $InstanceId `
    -PrivateHostname $PublicHostname `
    -PrincipalsFile $PrincipalsFile `
    -PostgresPasswordFile $PostgresPasswordFile `
    -BackupRoot $BackupRoot `
    -BackupId $BackupId `
    -PauseWriters:$PauseWriters `
    -ScheduleIntervalSeconds $ScheduleIntervalSeconds `
    -RpoTargetSeconds $RpoTargetSeconds `
    -LeaveWritersStopped:$LeaveWritersStopped `
    -ComposeEnvironmentFile $EnvironmentFile `
    -ProductionOverlayFile $productionOverlay `
    -RequireProductionOverlay
