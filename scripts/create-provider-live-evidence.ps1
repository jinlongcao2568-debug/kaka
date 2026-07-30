[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('sales_outreach', 'crm_quote', 'leadpack_page_delivery', 'payment_collection')][string]$Family,
    [Parameter(Mandatory = $true)][string]$ProviderId,
    [Parameter(Mandatory = $true)][string]$SigningKeyFile,
    [Parameter(Mandatory = $true)][string]$OutputFile,
    [Parameter(Mandatory = $true)][string]$ExpiresAt,
    [Parameter(Mandatory = $true)][string]$SandboxExecutionRef,
    [Parameter(Mandatory = $true)][string]$CallbackEventRef,
    [Parameter(Mandatory = $true)][string]$ApprovalRef,
    [Parameter(Mandatory = $true)][string]$AuditRef,
    [Parameter(Mandatory = $true)][string]$OperatorActionRef
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$env:PYTHONPATH = Join-Path $repoRoot 'src'
python -m runtime.provider_live_evidence `
    --family $Family `
    --provider-id $ProviderId `
    --signing-key-file $SigningKeyFile `
    --output-file $OutputFile `
    --expires-at $ExpiresAt `
    --sandbox-execution-ref $SandboxExecutionRef `
    --callback-event-ref $CallbackEventRef `
    --approval-ref $ApprovalRef `
    --audit-ref $AuditRef `
    --operator-action-ref $OperatorActionRef
if ($LASTEXITCODE -ne 0) {
    throw 'Provider live evidence generation failed.'
}
