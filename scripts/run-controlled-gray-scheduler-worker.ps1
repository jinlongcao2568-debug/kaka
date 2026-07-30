param(
    [switch]$Once,
    [switch]$Serve,
    [string]$WorkerId = "controlled-gray-scheduler-worker-v1",
    [ValidateSet("core", "browser")]
    [string]$WorkerCapability = "core",
    [double]$PollSeconds = 2,
    [int]$LeaseSeconds = 120,
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
    $StatusJson = Join-Path $repoRoot "tmp\runtime\controlled-gray-scheduler-worker-status-v1.json"
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\tests"
$env:PYTHONIOENCODING = "utf-8"

$argsList = @(
    "-m", "runtime.controlled_gray_scheduler_worker",
    $(if ($Once) { "--once" } else { "--serve" }),
    "--worker-id", $WorkerId,
    "--worker-capability", $WorkerCapability,
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
