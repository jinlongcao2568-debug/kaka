[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$TenantId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$InstanceId,
    [Parameter(Mandatory = $true)][string]$PrivateHostname,
    [Parameter(Mandatory = $true)][string]$PrincipalsFile,
    [Parameter(Mandatory = $true)][string]$PostgresPasswordFile,
    [Parameter(Mandatory = $true)][string]$BackupRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$')][string]$BackupId,
    [Parameter(Mandatory = $true)][string]$RestoreReportRoot,
    [Parameter(Mandatory = $true)][switch]$ConfirmIsolatedRestore,
    [ValidateRange(60, 86400)][int]$RtoTargetSeconds = 3600
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composeFile = Join-Path $repoRoot 'docker-compose.private-pilot.yml'
$resolvedPrincipals = (Resolve-Path -LiteralPath $PrincipalsFile).Path
$resolvedPassword = (Resolve-Path -LiteralPath $PostgresPasswordFile).Path
$resolvedBackupRoot = (Resolve-Path -LiteralPath $BackupRoot).Path
$resolvedReportRoot = [IO.Path]::GetFullPath($RestoreReportRoot)
$backupManifest = Join-Path (Join-Path $resolvedBackupRoot $BackupId) 'manifest.json'

if (-not $ConfirmIsolatedRestore) {
    throw 'Restore drill requires -ConfirmIsolatedRestore.'
}
if (-not (Test-Path -LiteralPath $backupManifest -PathType Leaf)) {
    throw "Backup manifest not found: $backupManifest"
}
if ($resolvedReportRoot -eq $repoRoot -or $resolvedReportRoot.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw 'RestoreReportRoot must be outside the repository.'
}
[IO.Directory]::CreateDirectory($resolvedReportRoot) | Out-Null

$targetDatabase = "$TenantId-$InstanceId-restore-drill"
$env:KAKA_DEPLOYMENT_TENANT_ID = $TenantId
$env:KAKA_DEPLOYMENT_INSTANCE_ID = $InstanceId
$env:KAKA_PRIVATE_HOSTNAME = $PrivateHostname
$env:KAKA_PRIVATE_PRINCIPALS_FILE = $resolvedPrincipals
$env:KAKA_PRIVATE_POSTGRES_PASSWORD_FILE = $resolvedPassword
$env:KAKA_PRIVATE_BACKUP_ROOT = $resolvedBackupRoot
$env:KAKA_PRIVATE_RESTORE_REPORT_ROOT = $resolvedReportRoot
$env:KAKA_BACKUP_ID = $BackupId
$env:KAKA_RESTORE_ISOLATED_ACK = "RESTORE_ISOLATED:$targetDatabase"
$env:KAKA_RESTORE_RTO_TARGET_SECONDS = [string]$RtoTargetSeconds

docker compose --profile restore-drill -f $composeFile build restore-tools
if ($LASTEXITCODE -ne 0) { throw 'Failed to build the pinned PostgreSQL 18 restore-tools image.' }

try {
    docker compose --profile restore-drill -f $composeFile up --no-build --abort-on-container-exit --exit-code-from restore-tools restore-tools
    if ($LASTEXITCODE -ne 0) { throw 'Isolated private-pilot restore drill failed closed.' }
}
finally {
    docker compose --profile restore-drill -f $composeFile stop --timeout 30 restore-postgres restore-tools | Out-Null
}

$reportPath = Join-Path $resolvedReportRoot "$BackupId-restore-report.json"
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw "Restore process exited without the required RTO report: $reportPath"
}
Write-Output "Validated isolated restore report: $reportPath"
