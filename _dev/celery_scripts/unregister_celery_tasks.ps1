param()

$ErrorActionPreference = "SilentlyContinue"

schtasks /Delete /TN "WMS_CeleryWorker_OnLogon" /F | Out-Null
schtasks /Delete /TN "WMS_CeleryWatchdog_5min" /F | Out-Null

$startupDir = [Environment]::GetFolderPath("Startup")
$startupCmd = Join-Path $startupDir "WMS_CeleryStartup.cmd"
if (Test-Path $startupCmd) {
    Remove-Item $startupCmd -Force
}

Write-Output "Scheduled tasks/startup fallback removed (if they existed)."
