param(
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$status = [ordered]@{
    redis_running = $false
    worker_running = $false
    worker_pids = @()
}

try {
    $redis = Get-Service -Name "Redis" -ErrorAction Stop
    $status.redis_running = ($redis.Status -eq "Running")
} catch {
    $status.redis_running = $false
}

$procs = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and $_.CommandLine -match "celery(\.exe)?\s+-A\s+wms\s+worker"
    }

if ($procs) {
    $status.worker_running = $true
    $status.worker_pids = @($procs | ForEach-Object { $_.ProcessId })
}

$json = $status | ConvertTo-Json -Depth 3 -Compress
Write-Output $json

if ($Strict -and (-not $status.redis_running -or -not $status.worker_running)) {
    exit 1
}
