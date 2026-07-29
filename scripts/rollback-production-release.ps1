[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$TenantId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$InstanceId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$')][string]$CurrentReleaseVersion,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$')][string]$PreviousReleaseVersion,
    [Parameter(Mandatory = $true)][string]$CurrentEnvironmentFile,
    [Parameter(Mandatory = $true)][string]$PreviousEnvironmentFile,
    [Parameter(Mandatory = $true)][string]$ValidatedBackupManifest,
    [Parameter(Mandatory = $true)][string]$RollbackReportFile,
    [Parameter(Mandatory = $true)][switch]$ConfirmProductionRollbackDrill,
    [ValidateRange(60, 900)][int]$WaitTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$baseCompose = Join-Path $repoRoot 'docker-compose.private-pilot.yml'
$productionCompose = Join-Path $repoRoot 'docker-compose.production.yml'
$currentEnv = (Resolve-Path -LiteralPath $CurrentEnvironmentFile).Path
$previousEnv = (Resolve-Path -LiteralPath $PreviousEnvironmentFile).Path
$manifestPath = (Resolve-Path -LiteralPath $ValidatedBackupManifest).Path
$reportPath = [IO.Path]::GetFullPath($RollbackReportFile)
$currentArgs = @('--env-file', $currentEnv, '-f', $baseCompose, '-f', $productionCompose)
$previousArgs = @('--env-file', $previousEnv, '-f', $baseCompose, '-f', $productionCompose)

if (-not $ConfirmProductionRollbackDrill) {
    throw 'Production rollback drill requires -ConfirmProductionRollbackDrill.'
}
if ($CurrentReleaseVersion -eq $PreviousReleaseVersion) {
    throw 'PreviousReleaseVersion must differ from CurrentReleaseVersion.'
}
if ($reportPath -eq $repoRoot -or $reportPath.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw 'RollbackReportFile must be outside the repository.'
}

$backupRoot = Split-Path -Parent (Split-Path -Parent $manifestPath)
$backupId = Split-Path -Leaf (Split-Path -Parent $manifestPath)
$env:KAKA_BACKUP_ROOT = $backupRoot
$env:KAKA_BACKUP_ID = $backupId
$env:PYTHONPATH = Join-Path $repoRoot 'src'
$validatedBackup = python -m runtime.private_pilot_backup validate | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw 'Backup manifest or backup artifacts failed validation.'
}
if (
    $validatedBackup.source_tenant_id -ne $TenantId -or
    $validatedBackup.source_instance_id -ne $InstanceId -or
    $validatedBackup.backup_state -ne 'COMPLETE'
) {
    throw 'Validated backup does not belong to this exact production deployment.'
}

foreach ($composeArgs in @($currentArgs, $previousArgs)) {
    docker compose @composeArgs config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'Current or previous production Compose configuration is invalid.'
    }
}

$rollbackSucceeded = $false
$postRollbackReadinessVerified = $false
$currentReleaseRestored = $false
$rollbackErrorCategory = $null
try {
    docker compose @currentArgs stop --timeout 30 edge operator-edge alert-dispatcher
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to close production ingress before the rollback drill.'
    }

    docker compose @previousArgs pull app worker browser-worker egress-proxy
    if ($LASTEXITCODE -ne 0) {
        throw 'Previous immutable release images could not be pulled.'
    }
    docker compose @previousArgs up -d --no-build --wait --wait-timeout $WaitTimeoutSeconds app worker egress-proxy browser-worker
    if ($LASTEXITCODE -ne 0) {
        throw 'Previous release failed health-gated startup.'
    }
    docker compose @previousArgs exec -T app python -c "from shared.settings import Settings; from storage.db import DatabaseSession; from storage.sqlalchemy_backend import REQUIRED_STORAGE_SCHEMA_REVISION; s=Settings.from_env(environment='PROD_LIVE_MODE'); d=DatabaseSession(settings=s); assert d.storage_schema_revision == REQUIRED_STORAGE_SCHEMA_REVISION; d.close()"
    if ($LASTEXITCODE -ne 0) {
        throw 'Previous release storage/readiness verification failed.'
    }
    $postRollbackReadinessVerified = $true
    $rollbackSucceeded = $true
}
catch {
    $rollbackErrorCategory = $_.Exception.GetType().Name
    throw
}
finally {
    try {
        docker compose @currentArgs pull app worker browser-worker egress-proxy alert-dispatcher edge operator-edge
        if ($LASTEXITCODE -ne 0) {
            throw 'Current immutable release images could not be pulled for forward recovery.'
        }
        docker compose @currentArgs up -d --no-build --wait --wait-timeout $WaitTimeoutSeconds
        if ($LASTEXITCODE -ne 0) {
            throw 'Current release failed forward recovery after the rollback drill.'
        }
        $currentReleaseRestored = $true
    }
    finally {
        [IO.Directory]::CreateDirectory((Split-Path -Parent $reportPath)) | Out-Null
        $report = [ordered]@{
            report_version = 1
            tenant_id = $TenantId
            instance_id = $InstanceId
            backup_id = $validatedBackup.backup_id
            current_image_tag = $CurrentReleaseVersion
            requested_previous_image_tag = $PreviousReleaseVersion
            rollback_succeeded = $rollbackSucceeded
            rollback_error_category = $rollbackErrorCategory
            database_restore_executed = $false
            automated_schema_downgrade_executed = $false
            health_gate_required = $true
            production_overlay_used = $true
            post_rollback_readiness_verified = $postRollbackReadinessVerified
            current_release_restored_after_drill = $currentReleaseRestored
            customer_ingress_closed_during_drill = $true
            completed_at = [DateTimeOffset]::UtcNow.ToString('o')
        }
        $temporaryReport = "$reportPath.$([Guid]::NewGuid().ToString('N')).tmp"
        $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporaryReport -Encoding utf8
        Move-Item -LiteralPath $temporaryReport -Destination $reportPath
    }
}

Write-Output "Production rollback drill completed and current release restored: $reportPath"
