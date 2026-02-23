param(
    [ValidateSet("menu", "status", "start", "stop", "restart", "queue", "logs", "register", "unregister", "watchdog", "health")]
    [string]$Action = "menu",
    [int]$TailLines = 80,
    [string]$ProjectRoot = "d:\1Kinopoisk\Diplom_Codex",
    [switch]$NoAutoRecover
)

$ErrorActionPreference = "Stop"
$AutoRecoverEnabled = -not $NoAutoRecover

function Write-Separator {
    Write-Output ("-" * 80)
}

function Write-Title {
    param([string]$Text)
    Write-Separator
    Write-Output $Text
    Write-Separator
}

function Write-ActionIntro {
    param(
        [string]$Title,
        [string]$What,
        [string]$Why
    )
    Write-Title $Title
    Write-Output "Что делаем: $What"
    Write-Output "Зачем это нужно: $Why"
    Write-Separator
}

function Invoke-ScriptFile {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @()
    )
    if (!(Test-Path $ScriptPath)) {
        throw "Не найден скрипт: $ScriptPath"
    }
    & $ScriptPath @Arguments
    return $LASTEXITCODE
}

function Get-WorkerStatus {
    param([switch]$PrintRaw)

    $statusScript = Join-Path $ProjectRoot "scripts\check_celery_worker.ps1"
    if (!(Test-Path $statusScript)) {
        throw "Не найден скрипт статуса: $statusScript"
    }

    $rawLines = @(& $statusScript 2>$null)
    if ($PrintRaw) {
        $rawLines | ForEach-Object { Write-Host $_ }
    }
    $jsonLine = ($rawLines | Where-Object { $_ -match '^\{.*\}$' } | Select-Object -Last 1)
    if (-not $jsonLine) {
        return $null
    }
    try {
        return ($jsonLine | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Try-AutoRecoverWorker {
    param(
        [string]$Reason,
        [int]$WaitSeconds = 6
    )

    if (-not $AutoRecoverEnabled) {
        Write-Host "Автовосстановление отключено (NoAutoRecover)."
        return $false
    }

    Write-Separator
    Write-Host "Автовосстановление: $Reason"
    Write-Host "Пытаемся поднять Celery worker..."
    $startScript = Join-Path $ProjectRoot "scripts\start_celery_worker.ps1"
    $startOutput = @(& $startScript -ProjectRoot $ProjectRoot)
    $startOutput | ForEach-Object { Write-Host $_ }
    Start-Sleep -Seconds $WaitSeconds

    $statusAfter = Get-WorkerStatus
    if ($statusAfter -and $statusAfter.worker_running) {
        Write-Host "Автовосстановление успешно: worker запущен."
        return $true
    }

    Write-Host "Первый запуск не удался. Пробуем watchdog..."
    $watchdogScript = Join-Path $ProjectRoot "scripts\watchdog_celery.ps1"
    $watchOutput = @(& $watchdogScript -ProjectRoot $ProjectRoot)
    $watchOutput | ForEach-Object { Write-Host $_ }
    Start-Sleep -Seconds 3

    $statusAfterWatchdog = Get-WorkerStatus
    if ($statusAfterWatchdog -and $statusAfterWatchdog.worker_running) {
        Write-Host "Автовосстановление успешно через watchdog."
        return $true
    }

    Write-Host "Автовосстановление не удалось: worker все еще не запущен."
    return $false
}

function Invoke-QueueStrictCheck {
    Push-Location $ProjectRoot
    try {
        $lines = @(& python manage.py check_efp_queue --strict)
        $exitCode = $LASTEXITCODE
        $lines | ForEach-Object { Write-Host $_ }
        return ($exitCode -eq 0)
    } finally {
        Pop-Location
    }
}

function Show-Status {
    Write-ActionIntro `
        -Title "Проверка состояния Celery/Redis" `
        -What "Проверяем Redis service и запущен ли Celery worker." `
        -Why "Это быстрый ответ: может ли очередь обрабатывать задачи прямо сейчас."

    $status = Get-WorkerStatus -PrintRaw
    if (-not $status) {
        Write-Output "Не удалось распарсить статус worker."
    } elseif (-not $status.worker_running -and $status.redis_running) {
        Write-Output "Внимание: Redis работает, но Celery worker не запущен."
        Try-AutoRecoverWorker -Reason "worker не найден в статусе" | Out-Null
        $status = Get-WorkerStatus -PrintRaw
    }
    if ($status) {
        Write-Output ("Итоговый статус: " + ($status | ConvertTo-Json -Compress))
    }

    Write-Separator
    Write-Output "Дополнительно проверяем очередь через Django management command..."
    Push-Location $ProjectRoot
    try {
        python manage.py check_efp_queue
    } finally {
        Pop-Location
    }
}

function Start-Worker {
    Write-ActionIntro `
        -Title "Запуск Celery worker" `
        -What "Поднимаем Redis (если нужен) и запускаем Celery worker в фоне." `
        -Why "Без worker фоновые EFP-задачи не будут выполняться."

    $script = Join-Path $ProjectRoot "scripts\start_celery_worker.ps1"
    & $script -ProjectRoot $ProjectRoot
}

function Stop-Worker {
    Write-ActionIntro `
        -Title "Остановка Celery worker" `
        -What "Останавливаем все процессы Celery worker для проекта." `
        -Why "Нужно для безопасного перезапуска, обновлений и диагностики."

    $script = Join-Path $ProjectRoot "scripts\stop_celery_worker.ps1"
    & $script
}

function Restart-Worker {
    Write-ActionIntro `
        -Title "Перезапуск Celery worker" `
        -What "Останавливаем worker и запускаем заново." `
        -Why "Сбрасывает зависшие состояния и подхватывает новые изменения."

    Stop-Worker
    Start-Sleep -Seconds 1
    Start-Worker
}

function Check-QueueStrict {
    Write-ActionIntro `
        -Title "Строгая проверка очереди" `
        -What "Проверяем Redis и Celery worker в strict-режиме." `
        -Why "Если что-то недоступно, команда вернет ошибку. Это контроль боеготовности."

    $ok = Invoke-QueueStrictCheck
    if ($ok) {
        Write-Output "Strict check: OK"
        return
    }

    Write-Output "Strict check: FAIL"
    if (Try-AutoRecoverWorker -Reason "strict check не прошел") {
        Write-Separator
        Write-Output "Повторяем strict check после восстановления..."
        $okAfter = Invoke-QueueStrictCheck
        if ($okAfter) {
            Write-Output "Strict check после восстановления: OK"
        } else {
            Write-Output "Strict check после восстановления: FAIL"
        }
    }
}

function Show-Logs {
    Write-ActionIntro `
        -Title "Просмотр логов Celery worker" `
        -What "Показываем последние строки файла logs\celery_worker.log." `
        -Why "Лог помогает понять, почему задача выполнилась или упала."

    $logPath = Join-Path $ProjectRoot "logs\celery_worker.log"
    if (!(Test-Path $logPath)) {
        Write-Output "Лог еще не создан: $logPath"
        return
    }
    Get-Content $logPath -Tail $TailLines
}

function Register-AutoStart {
    Write-ActionIntro `
        -Title "Настройка автозапуска и watchdog" `
        -What "Пробуем зарегистрировать задачи планировщика; при отказе настраиваем Startup fallback." `
        -Why "Чтобы worker автоматически запускался и поднимался после сбоев."

    $script = Join-Path $ProjectRoot "scripts\register_celery_tasks.ps1"
    & $script -ProjectRoot $ProjectRoot
}

function Unregister-AutoStart {
    Write-ActionIntro `
        -Title "Отключение автозапуска и watchdog" `
        -What "Удаляем задачи планировщика и Startup fallback файл." `
        -Why "Полезно при смене способа запуска или чистке окружения."

    $script = Join-Path $ProjectRoot "scripts\unregister_celery_tasks.ps1"
    & $script
}

function Run-WatchdogOnce {
    Write-ActionIntro `
        -Title "Ручной запуск watchdog" `
        -What "Один раз запускаем проверку: если worker не работает, скрипт поднимет его." `
        -Why "Удобно для быстрой самопочинки без ручного старта."

    $script = Join-Path $ProjectRoot "scripts\watchdog_celery.ps1"
    & $script -ProjectRoot $ProjectRoot
}

function Show-HealthReport {
    Write-ActionIntro `
        -Title "Полная диагностика" `
        -What "Собираем состояние worker, strict проверку очереди, сервис Redis, scheduler и Startup fallback." `
        -Why "Это полный снимок работоспособности фона."

    Show-Status
    Write-Separator

    Write-Output "Проверка Redis service:"
    try {
        Get-Service Redis | Select-Object Name, Status, StartType | Format-Table -AutoSize
    } catch {
        Write-Output "Redis service не найден."
    }
    Write-Separator

    Write-Output "Проверка задач планировщика:"
    cmd /c "schtasks /Query /TN WMS_CeleryWatchdog_5min >nul 2>nul"
    if ($LASTEXITCODE -eq 0) {
        & schtasks /Query /TN WMS_CeleryWatchdog_5min
    } else {
        Write-Output "Задача WMS_CeleryWatchdog_5min не найдена или недоступна."
    }

    cmd /c "schtasks /Query /TN WMS_CeleryWorker_OnLogon >nul 2>nul"
    if ($LASTEXITCODE -eq 0) {
        & schtasks /Query /TN WMS_CeleryWorker_OnLogon
    } else {
        Write-Output "Задача WMS_CeleryWorker_OnLogon не найдена или недоступна."
    }
    Write-Separator

    $startupDir = [Environment]::GetFolderPath("Startup")
    $startupCmd = Join-Path $startupDir "WMS_CeleryStartup.cmd"
    if (Test-Path $startupCmd) {
        Write-Output "Startup fallback найден: $startupCmd"
    } else {
        Write-Output "Startup fallback не найден."
    }

    Write-Separator
    Write-Output "Strict queue check:"
    try {
        Check-QueueStrict
    } catch {
        Write-Output "Strict check завершился с ошибкой: $($_.Exception.Message)"
    }
}

function Invoke-MenuChoice {
    param([string]$Choice)
    switch -Exact ($Choice) {
        "1" { Show-Status; $script:MenuContinue = $true; return }
        "2" { Start-Worker; $script:MenuContinue = $true; return }
        "3" { Stop-Worker; $script:MenuContinue = $true; return }
        "4" { Restart-Worker; $script:MenuContinue = $true; return }
        "5" { Check-QueueStrict; $script:MenuContinue = $true; return }
        "6" { Show-Logs; $script:MenuContinue = $true; return }
        "7" { Register-AutoStart; $script:MenuContinue = $true; return }
        "8" { Unregister-AutoStart; $script:MenuContinue = $true; return }
        "9" { Run-WatchdogOnce; $script:MenuContinue = $true; return }
        "10" { Show-HealthReport; $script:MenuContinue = $true; return }
        "0" {
            Write-Output "Выход."
            $script:MenuContinue = $false
            return
        }
        default {
            Write-Output "Неизвестный пункт: '$Choice'"
            Write-Output "Введите число из меню (0-10)."
            $script:MenuContinue = $true
            return
        }
    }
}

function Show-Menu {
    Write-Title "WMS Celery Control Center"
    Write-Output "Проект: $ProjectRoot"
    Write-Separator
    Write-Output "1  - Статус (Redis + worker + queue)"
    Write-Output "2  - Запустить worker"
    Write-Output "3  - Остановить worker"
    Write-Output "4  - Перезапустить worker"
    Write-Output "5  - Строгая проверка очереди"
    Write-Output "6  - Показать последние логи worker"
    Write-Output "7  - Настроить автозапуск/watchdog"
    Write-Output "8  - Убрать автозапуск/watchdog"
    Write-Output "9  - Запустить watchdog один раз"
    Write-Output "10 - Полная диагностика"
    Write-Output "0  - Выход"
    if ($AutoRecoverEnabled) {
        Write-Output "Режим автовосстановления: ВКЛ"
    } else {
        Write-Output "Режим автовосстановления: ВЫКЛ"
    }
    Write-Separator
}

function Run-InteractiveMenu {
    $continue = $true
    while ($continue) {
        Show-Menu
        $choice = (Read-Host "Введите цифру действия").Trim()
        Write-Separator
        Write-Output "Вы выбрали: $choice"
        try {
            $script:MenuContinue = $true
            Invoke-MenuChoice -Choice $choice
            $continue = $script:MenuContinue
        } catch {
            Write-Output "Ошибка выполнения: $($_.Exception.Message)"
            if ($_.ScriptStackTrace) {
                Write-Output "Stack: $($_.ScriptStackTrace)"
            }
        }
    }
}

switch ($Action) {
    "menu" { Run-InteractiveMenu; break }
    "status" { Show-Status; break }
    "start" { Start-Worker; break }
    "stop" { Stop-Worker; break }
    "restart" { Restart-Worker; break }
    "queue" { Check-QueueStrict; break }
    "logs" { Show-Logs; break }
    "register" { Register-AutoStart; break }
    "unregister" { Unregister-AutoStart; break }
    "watchdog" { Run-WatchdogOnce; break }
    "health" { Show-HealthReport; break }
}








