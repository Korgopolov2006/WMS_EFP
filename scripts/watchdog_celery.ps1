param(
    [string]$ProjectRoot = "d:\1Kinopoisk\Diplom_Codex"
)

$ErrorActionPreference = "Stop"

$worker = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and $_.CommandLine -match "celery(\.exe)?\s+-A\s+wms\s+worker"
    }

if ($worker) {
    Write-Output "Worker is running."
    exit 0
}

& "$ProjectRoot\scripts\start_celery_worker.ps1" -ProjectRoot $ProjectRoot
