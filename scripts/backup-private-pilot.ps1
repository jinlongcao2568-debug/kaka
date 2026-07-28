[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$TenantId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$InstanceId,
    [Parameter(Mandatory = $true)][string]$PrivateHostname,
    [Parameter(Mandatory = $true)][string]$PrincipalsFile,
    [Parameter(Mandatory = $true)][string]$PostgresPasswordFile,
    [Parameter(Mandatory = $true)][string]$BackupRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$')][string]$BackupId,
    [Parameter(Mandatory = $true)][switch]$PauseWriters,
    [ValidateRange(300, 604800)][int]$ScheduleIntervalSeconds = 21600,
    [ValidateRange(300, 1209600)][int]$RpoTargetSeconds = 28800,
    [switch]$LeaveWritersStopped
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composeFile = Join-Path $repoRoot 'docker-compose.private-pilot.yml'
$resolvedPrincipals = (Resolve-Path -LiteralPath $PrincipalsFile).Path
$resolvedPassword = (Resolve-Path -LiteralPath $PostgresPasswordFile).Path
$resolvedBackupRoot = [IO.Path]::GetFullPath($BackupRoot)

if (-not $PauseWriters) {
    throw 'Backup requires -PauseWriters so database and object-storage writers are quiesced.'
}
if ($RpoTargetSeconds -lt $ScheduleIntervalSeconds) {
    throw 'RpoTargetSeconds cannot be shorter than ScheduleIntervalSeconds.'
}
if ($resolvedBackupRoot -eq $repoRoot -or $resolvedBackupRoot.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw 'BackupRoot must be outside the repository.'
}
[IO.Directory]::CreateDirectory($resolvedBackupRoot) | Out-Null

$env:KAKA_DEPLOYMENT_TENANT_ID = $TenantId
$env:KAKA_DEPLOYMENT_INSTANCE_ID = $InstanceId
$env:KAKA_PRIVATE_HOSTNAME = $PrivateHostname
$env:KAKA_PRIVATE_PRINCIPALS_FILE = $resolvedPrincipals
$env:KAKA_PRIVATE_POSTGRES_PASSWORD_FILE = $resolvedPassword
$env:KAKA_PRIVATE_BACKUP_ROOT = $resolvedBackupRoot
$env:KAKA_BACKUP_ID = $BackupId
$env:KAKA_BACKUP_WRITERS_PAUSED_ACK = "WRITERS_PAUSED:$TenantId-$InstanceId"
$env:KAKA_BACKUP_SCHEDULE_INTERVAL_SECONDS = [string]$ScheduleIntervalSeconds
$env:KAKA_BACKUP_RPO_TARGET_SECONDS = [string]$RpoTargetSeconds

$runningServices = @(
    docker compose -f $composeFile ps --services --status running
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read private-pilot running services.' }
)
$writerServices = @('app', 'worker', 'browser-worker') | Where-Object { $runningServices -contains $_ }

try {
    if ($writerServices.Count -gt 0) {
        docker compose -f $composeFile stop --timeout 60 @writerServices
        if ($LASTEXITCODE -ne 0) { throw 'Failed to stop all private-pilot writers.' }
    }

    docker compose --profile backup -f $composeFile build backup-tools
    if ($LASTEXITCODE -ne 0) { throw 'Failed to build the pinned PostgreSQL 18 backup-tools image.' }

    docker compose --profile backup -f $composeFile run --rm backup-tools backup
    if ($LASTEXITCODE -ne 0) { throw 'Private-pilot backup failed closed.' }

    docker compose --profile backup -f $composeFile run --rm backup-tools validate
    if ($LASTEXITCODE -ne 0) { throw 'Private-pilot backup artifact validation failed.' }
}
finally {
    if (-not $LeaveWritersStopped -and $writerServices.Count -gt 0) {
        docker compose -f $composeFile up -d --no-build @writerServices
        if ($LASTEXITCODE -ne 0) {
            Write-Error 'Backup finished or failed, but one or more previously running writers did not resume.'
        }
    }
}

Write-Output "Validated private-pilot backup: $resolvedBackupRoot\$BackupId"
