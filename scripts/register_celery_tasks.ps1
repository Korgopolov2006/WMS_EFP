param(
    [string]$ProjectRoot = "d:\1Kinopoisk\Diplom_Codex"
)

$ErrorActionPreference = "Stop"

$startScript = "$ProjectRoot\scripts\start_celery_worker.ps1"
$watchdogScript = "$ProjectRoot\scripts\watchdog_celery.ps1"

$taskStartName = "WMS_CeleryWorker_OnLogon"
$taskWatchdogName = "WMS_CeleryWatchdog_5min"

$startCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -ProjectRoot `"$ProjectRoot`""
$watchdogCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`" -ProjectRoot `"$ProjectRoot`""

function Register-WithTaskScheduler {
    $startOk = $false
    $watchdogOk = $false

    schtasks /Create /TN $taskStartName /TR $startCmd /SC ONLOGON /F 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $startOk = $true
    }

    schtasks /Create /TN $taskWatchdogName /TR $watchdogCmd /SC MINUTE /MO 5 /F 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $watchdogOk = $true
    }

    return @{ start_ok = $startOk; watchdog_ok = $watchdogOk }
}

function Register-WithStartupFolder {
    $startupDir = [Environment]::GetFolderPath("Startup")
    $startupCmd = Join-Path $startupDir "WMS_CeleryStartup.cmd"
    $watchdogLoopScript = "$ProjectRoot\scripts\celery_watchdog_loop.ps1"
    $content = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$startScript" -ProjectRoot "$ProjectRoot"
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$watchdogLoopScript" -ProjectRoot "$ProjectRoot"
"@
    Set-Content -Path $startupCmd -Value $content -Encoding ASCII
    Write-Output "Task Scheduler is unavailable. Startup fallback configured:"
    Write-Output " - $startupCmd"
}

try {
    $result = Register-WithTaskScheduler
    if ($result.start_ok -and $result.watchdog_ok) {
        Write-Output "Registered tasks:"
        Write-Output " - $taskStartName"
        Write-Output " - $taskWatchdogName"
    } elseif ($result.watchdog_ok) {
        Register-WithStartupFolder
        Write-Output "Watchdog task registered, startup task denied:"
        Write-Output " - $taskWatchdogName"
    } else {
        Register-WithStartupFolder
    }
} catch {
    Register-WithStartupFolder
}
