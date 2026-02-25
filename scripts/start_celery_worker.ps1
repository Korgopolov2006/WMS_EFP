param(
    [string]$ProjectRoot = "d:\1Kinopoisk\Diplom_Codex",
    [string]$LogFile = "logs\celery_worker.log"
)

$ErrorActionPreference = "Stop"

function Get-CeleryWorkerProcess {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and $_.CommandLine -match "celery(\.exe)?\s+-A\s+wms\s+worker"
        }
}

try {
    $redis = Get-Service -Name "Redis" -ErrorAction Stop
    if ($redis.Status -ne "Running") {
        Start-Service -Name "Redis"
        Start-Sleep -Seconds 2
    }
} catch {
    Write-Error "Redis service is not available: $($_.Exception.Message)"
    exit 1
}

$existing = Get-CeleryWorkerProcess
if ($existing) {
    Write-Output "Celery worker is already running."
    exit 0
}

Set-Location $ProjectRoot
if (!(Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

$cmd = "cd /d $ProjectRoot && celery -A wms worker -l info --pool=solo --concurrency=1 >> $LogFile 2>&1"
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WindowStyle Hidden -PassThru
Write-Output "Started Celery worker. PID=$($proc.Id)"
