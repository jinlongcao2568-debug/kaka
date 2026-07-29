param(
    [string]$RepoRoot = "",
    [string]$Registry = "",
    [string]$OutputRoot = "",
    [switch]$EmitJson,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($RepoRoot) {
    $repoRoot = Resolve-Path $RepoRoot
} else {
    $repoRoot = Resolve-Path (Join-Path $scriptDir "..")
}

if (-not $Registry) {
    $Registry = Join-Path $repoRoot "control\automation_entrypoint_registry.yaml"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "tmp\evaluation-real-samples\automation-entrypoint-audit-v1"
}

$env:PYTHONPATH = @(
    (Join-Path $repoRoot "src"),
    (Join-Path $repoRoot "tests")
) -join [System.IO.Path]::PathSeparator
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "storage.automation_entrypoint_audit",
    "--repo-root", "$repoRoot",
    "--registry", "$Registry",
    "--output-root", "$OutputRoot",
    "--write-output",
    "--json"
)

Push-Location $repoRoot
try {
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        python @argsList *> $tmp
        $pythonExitCode = $LASTEXITCODE
        $raw = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
        $jsonStart = $raw.IndexOf('{')
        if ($jsonStart -lt 0) {
            $issues = @([pscustomobject]@{
                severity = 'ERROR'
                code = 'AUTOMATION_ENTRYPOINT_AUDIT_NO_JSON'
                path = 'scripts/audit-automation-entrypoints.ps1'
                message = 'storage.automation_entrypoint_audit did not emit JSON.'
            })
            $result = [pscustomobject]@{
                script = 'audit-automation-entrypoints.ps1'
                repoRoot = "$repoRoot"
                ok = $false
                issues = $issues
            }
        } else {
            $parsed = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 100
            $issues = [System.Collections.Generic.List[object]]::new()
            foreach ($reason in @($parsed.blocking_reasons)) {
                $issues.Add([pscustomobject]@{
                    severity = 'ERROR'
                    code = 'AUTOMATION_ENTRYPOINT_AUDIT_BLOCKED'
                    path = 'control/automation_entrypoint_registry.yaml'
                    message = [string]$reason
                }) | Out-Null
            }
            foreach ($warning in @($parsed.warnings)) {
                $issues.Add([pscustomobject]@{
                    severity = 'WARNING'
                    code = 'AUTOMATION_ENTRYPOINT_AUDIT_WARNING'
                    path = 'control/automation_entrypoint_registry.yaml'
                    message = [string]$warning
                }) | Out-Null
            }
            $ok = ([bool]$parsed.safe_to_continue_automation) -and ($pythonExitCode -eq 0)
            if (($pythonExitCode -ne 0) -and (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)) {
                $issues.Add([pscustomobject]@{
                    severity = 'ERROR'
                    code = 'AUTOMATION_ENTRYPOINT_AUDIT_FAILED'
                    path = 'scripts/audit-automation-entrypoints.ps1'
                    message = "storage.automation_entrypoint_audit exited with code $pythonExitCode."
                }) | Out-Null
                $ok = $false
            }
            $result = [pscustomobject]@{
                script = 'audit-automation-entrypoints.ps1'
                repoRoot = "$repoRoot"
                ok = $ok
                summary = $parsed.summary
                outputPath = $parsed.output_path
                issues = $issues
                manifest = $parsed.manifest
            }
        }

        if (-not $Quiet -and -not $EmitJson) {
            Write-Host "[audit-automation-entrypoints] repo: $repoRoot"
            if ($result.ok) {
                Write-Host '[audit-automation-entrypoints] PASS'
                if ($result.summary) {
                    Write-Host ("[audit-automation-entrypoints] scripts={0} formal_entrypoints={1} unclassified={2}" -f $result.summary.script_count, $result.summary.formal_entrypoint_count, $result.summary.unclassified_script_count)
                }
            } else {
                foreach ($issue in @($result.issues)) {
                    Write-Host ("[{0}] {1} {2}" -f $issue.severity, $issue.code, $issue.message)
                }
            }
            if ($result.outputPath) {
                Write-Host "output_path: $($result.outputPath)"
            }
        }

        if ($EmitJson) {
            $result | ConvertTo-Json -Depth 100
        }

        if (-not $result.ok) {
            exit 1
        }
    }
    finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
