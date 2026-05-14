param(
    [string]$ProjectRoot = "d:\1Kinopoisk\Diplom_Codex",
    [int]$IntervalSeconds = 300
)

$ErrorActionPreference = "SilentlyContinue"

$lockPath = Join-Path $env:TEMP "wms_celery_watchdog.lock"
$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open($lockPath, "OpenOrCreate", "ReadWrite", "None")
} catch {
    Write-Output "Watchdog already running, exiting."
    exit 0
}

try {
    while ($true) {
        & "$ProjectRoot\scripts\check_celery_worker.ps1" -Strict | Out-Null
        if ($LASTEXITCODE -ne 0) {
            & "$ProjectRoot\scripts\start_celery_worker.ps1" -ProjectRoot $ProjectRoot | Out-Null
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
} finally {
    if ($lockStream) {
        $lockStream.Close()
    }
}
