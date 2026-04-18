[CmdletBinding()]
param(
    [string]$RepoRoot,
    [switch]$EmitJson,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$Provided)
    if ($Provided) { return (Resolve-Path $Provided).Path }
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing file: $Path" }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100)
}

function Invoke-SemanticAlignment {
    param(
        [string]$RepoRoot,
        [ref]$Issues
    )

    $scriptPath = Join-Path (Split-Path -Parent $PSCommandPath) 'check-semantic-alignment.ps1'
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        & pwsh -NoProfile -ExecutionPolicy Bypass -File $scriptPath -RepoRoot $RepoRoot -EmitJson *> $tmp
        $raw = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
        $jsonStart = $raw.IndexOf('{')
        if ($jsonStart -lt 0) {
            $Issues.Value.Add([pscustomobject]@{ severity='ERROR'; code='SEMANTIC_ALIGNMENT_NO_JSON'; path=$scriptPath; message='check-semantic-alignment.ps1 did not emit JSON.' }) | Out-Null
            return
        }

        $parsed = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 100
        foreach ($issue in @($parsed.issues)) {
            $Issues.Value.Add($issue) | Out-Null
        }
    }
    catch {
        $Issues.Value.Add([pscustomobject]@{ severity='ERROR'; code='SEMANTIC_ALIGNMENT_FAILED'; path=$scriptPath; message=$_.Exception.Message }) | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$issues = [System.Collections.Generic.List[object]]::new()

$files = @{
    publicBoundary = 'contracts/governance/public_boundary_registry.json'
    coverage       = 'contracts/governance/coverage_registry.json'
    fieldPolicy    = 'contracts/governance/field_policy_dictionary.json'
    approvalChain  = 'contracts/governance/approval_chain_catalog.json'
    deliveryMatrix = 'contracts/release/delivery_matrix.json'
    releaseGates   = 'contracts/release/release_gates.json'
}

$data = @{}
foreach ($name in $files.Keys) {
    $full = Join-Path $root $files[$name]
    try { $data[$name] = Read-JsonFile -Path $full }
    catch {
        $issues.Add([pscustomobject]@{ severity='ERROR'; code='MISSING_OR_INVALID_JSON'; path=$full; message=$_.Exception.Message }) | Out-Null
    }
}

if ($data.ContainsKey('publicBoundary') -and $data.publicBoundary.capabilities) {
    foreach ($cap in $data.publicBoundary.capabilities) {
        foreach ($key in @('capability_id','tier')) {
            if (-not ($cap.PSObject.Properties.Name -contains $key)) {
                $issues.Add([pscustomobject]@{ severity='ERROR'; code='PUBLIC_BOUNDARY_INCOMPLETE'; path='contracts/governance/public_boundary_registry.json'; message="Capability missing key: $key" }) | Out-Null
            }
        }
    }
}

if ($data.ContainsKey('coverage') -and $data.coverage.entries) {
    foreach ($entry in $data.coverage.entries) {
        if (-not ($entry.PSObject.Properties.Name -contains 'coverage_sellable_state')) {
            $issues.Add([pscustomobject]@{ severity='ERROR'; code='COVERAGE_INCOMPLETE'; path='contracts/governance/coverage_registry.json'; message='Coverage entry missing coverage_sellable_state.' }) | Out-Null
        }
    }
}

if ($data.ContainsKey('fieldPolicy') -and $data.fieldPolicy.entries) {
    foreach ($field in $data.fieldPolicy.entries) {
        foreach ($key in @('fieldPath','fieldClass','maskRule')) {
            if (-not ($field.PSObject.Properties.Name -contains $key)) {
                $issues.Add([pscustomobject]@{ severity='ERROR'; code='FIELD_POLICY_INCOMPLETE'; path='contracts/governance/field_policy_dictionary.json'; message="Field policy missing key: $key" }) | Out-Null
            }
        }
    }
}

if ($data.ContainsKey('approvalChain') -and $data.approvalChain.chains) {
    foreach ($chain in $data.approvalChain.chains) {
        if (-not ($chain.PSObject.Properties.Name -contains 'approvalChainId')) {
            $issues.Add([pscustomobject]@{ severity='ERROR'; code='APPROVAL_CHAIN_INCOMPLETE'; path='contracts/governance/approval_chain_catalog.json'; message='Approval chain missing approvalChainId.' }) | Out-Null
        }
    }
}

if ($data.ContainsKey('deliveryMatrix') -and $data.deliveryMatrix.objects) {
    foreach ($row in $data.deliveryMatrix.objects) {
        foreach ($key in @('object','surface_policy','release_level')) {
            if (-not ($row.PSObject.Properties.Name -contains $key)) {
                $issues.Add([pscustomobject]@{ severity='ERROR'; code='DELIVERY_MATRIX_INCOMPLETE'; path='contracts/release/delivery_matrix.json'; message="Delivery row missing key: $key" }) | Out-Null
            }
        }
    }
}

if ($data.ContainsKey('releaseGates') -and $data.releaseGates.gates) {
    foreach ($gate in $data.releaseGates.gates) {
        foreach ($key in @('releaseGateId','surface','minimumReleaseLevel')) {
            if (-not ($gate.PSObject.Properties.Name -contains $key)) {
                $issues.Add([pscustomobject]@{ severity='ERROR'; code='RELEASE_GATE_INCOMPLETE'; path='contracts/release/release_gates.json'; message="Release gate missing key: $key" }) | Out-Null
            }
        }
    }
}

Invoke-SemanticAlignment -RepoRoot $root -Issues ([ref]$issues)

$result = [pscustomobject]@{
    script = 'run-governance-contracts.ps1'
    repoRoot = $root
    ok = (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[run-governance-contracts] repo: $root"
    if ($issues.Count -eq 0) {
        Write-Host '[run-governance-contracts] PASS'
    } else {
        foreach ($issue in $issues) {
            Write-Host ("[{0}] {1} {2} {3}" -f $issue.severity, $issue.code, $issue.path, $issue.message)
        }
    }
}

if ($EmitJson) { $result | ConvertTo-Json -Depth 20 }
if (-not $result.ok) { exit 1 }
exit 0
