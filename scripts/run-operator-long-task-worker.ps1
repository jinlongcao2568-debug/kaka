param(
    [switch]$Once,
    [switch]$Serve,
    [string]$WorkerId = "operator-long-task-browser-worker-v1",
    [double]$PollSeconds = 5,
    [int]$LeaseSeconds = 900,
    [double]$HeartbeatSeconds = 15,
    [int]$RetryDelaySeconds = 60,
    [string]$StatusJson = "",
    [int]$MaxIdlePolls = 0,
    [switch]$EmitJson
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if ($Once -and $Serve) {
    throw "Choose only one of -Once or -Serve."
}
if (-not $Once -and -not $Serve) {
    $Serve = $true
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
if (-not $StatusJson) {
    $StatusJson = Join-Path $repoRoot "tmp\runtime\operator-long-task-browser-worker-status-v1.json"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.operator_long_task_worker",
    $(if ($Once) { "--once" } else { "--serve" }),
    "--worker-id", $WorkerId,
    "--worker-capability", "browser",
    "--poll-seconds", "$PollSeconds",
    "--lease-seconds", "$LeaseSeconds",
    "--heartbeat-seconds", "$HeartbeatSeconds",
    "--retry-delay-seconds", "$RetryDelaySeconds",
    "--status-json", $StatusJson,
    "--max-idle-polls", "$MaxIdlePolls"
)
if ($EmitJson) {
    $argsList += "--json"
}

& python @argsList
exit $LASTEXITCODE
