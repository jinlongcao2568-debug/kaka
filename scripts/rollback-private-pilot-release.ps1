[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$TenantId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,62}$')][string]$InstanceId,
    [Parameter(Mandatory = $true)][string]$PrivateHostname,
    [Parameter(Mandatory = $true)][string]$PrincipalsFile,
    [Parameter(Mandatory = $true)][string]$PostgresPasswordFile,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')][string]$CurrentImageTag,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')][string]$PreviousImageTag,
    [Parameter(Mandatory = $true)][string]$ValidatedBackupManifest,
    [Parameter(Mandatory = $true)][string]$RollbackReportRoot,
    [Parameter(Mandatory = $true)][switch]$ConfirmReleaseRollback
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composeFile = Join-Path $repoRoot 'docker-compose.private-pilot.yml'
$resolvedPrincipals = (Resolve-Path -LiteralPath $PrincipalsFile).Path
$resolvedPassword = (Resolve-Path -LiteralPath $PostgresPasswordFile).Path
$resolvedManifest = (Resolve-Path -LiteralPath $ValidatedBackupManifest).Path
$resolvedReportRoot = [IO.Path]::GetFullPath($RollbackReportRoot)

if (-not $ConfirmReleaseRollback) { throw 'Release rollback requires -ConfirmReleaseRollback.' }
if ($CurrentImageTag -eq $PreviousImageTag) { throw 'PreviousImageTag must differ from CurrentImageTag.' }
if ($resolvedReportRoot -eq $repoRoot -or $resolvedReportRoot.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw 'RollbackReportRoot must be outside the repository.'
}
$backup = Get-Content -LiteralPath $resolvedManifest -Raw | ConvertFrom-Json
if ($backup.backup_state -ne 'COMPLETE' -or $backup.source_tenant_id -ne $TenantId -or $backup.source_instance_id -ne $InstanceId) {
    throw 'ValidatedBackupManifest does not describe a complete backup for this exact deployment.'
}

$requiredImages = @(
    "kaka-private-pilot-api:$PreviousImageTag",
    "kaka-private-pilot-worker:$PreviousImageTag",
    "kaka-private-pilot-browser-worker:$PreviousImageTag"
)
foreach ($image in $requiredImages) {
    docker image inspect $image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Rollback image is not present locally: $image" }
}

[IO.Directory]::CreateDirectory($resolvedReportRoot) | Out-Null
$env:KAKA_DEPLOYMENT_TENANT_ID = $TenantId
$env:KAKA_DEPLOYMENT_INSTANCE_ID = $InstanceId
$env:KAKA_PRIVATE_HOSTNAME = $PrivateHostname
$env:KAKA_PRIVATE_PRINCIPALS_FILE = $resolvedPrincipals
$env:KAKA_PRIVATE_POSTGRES_PASSWORD_FILE = $resolvedPassword

$rollbackSucceeded = $false
$rollbackErrorCategory = $null
try {
    docker compose -f $composeFile stop --timeout 30 alert-dispatcher | Out-Null
    $env:KAKA_IMAGE_TAG = $PreviousImageTag
    docker compose -f $composeFile config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Rollback Compose config is invalid.' }
    docker compose -f $composeFile up -d --no-build --wait --wait-timeout 180 app worker egress-proxy browser-worker edge
    if ($LASTEXITCODE -ne 0) { throw 'Previous release failed health-gated startup.' }
    $rollbackSucceeded = $true
}
catch {
    $rollbackErrorCategory = $_.Exception.GetType().Name
    $env:KAKA_IMAGE_TAG = $CurrentImageTag
    docker compose -f $composeFile up -d --no-build --wait --wait-timeout 180 app worker egress-proxy browser-worker edge
    if ($LASTEXITCODE -ne 0) {
        throw 'Rollback failed and automatic forward recovery also failed; operator intervention required.'
    }
    throw
}
finally {
    $report = [ordered]@{
        report_version = 1
        tenant_id = $TenantId
        instance_id = $InstanceId
        backup_id = $backup.backup_id
        current_image_tag = $CurrentImageTag
        requested_previous_image_tag = $PreviousImageTag
        rollback_succeeded = $rollbackSucceeded
        rollback_error_category = $rollbackErrorCategory
        database_restore_executed = $false
        automated_schema_downgrade_executed = $false
        health_gate_required = $true
        completed_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $reportPath = Join-Path $resolvedReportRoot ("release-rollback-{0}.json" -f [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
}

Write-Output "Private-pilot release rollback completed: $PreviousImageTag"
