param()

$ErrorActionPreference = "Stop"

$procs = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and $_.CommandLine -match "celery(\.exe)?\s+-A\s+wms\s+worker"
    }

if (!$procs) {
    Write-Output "Celery worker is not running."
    exit 0
}

foreach ($p in $procs) {
    try {
        Stop-Process -Id $p.ProcessId -Force
        Write-Output "Stopped Celery worker PID=$($p.ProcessId)"
    } catch {
        Write-Warning "Failed to stop PID=$($p.ProcessId): $($_.Exception.Message)"
    }
}
