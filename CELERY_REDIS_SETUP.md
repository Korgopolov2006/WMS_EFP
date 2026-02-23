# Celery + Redis (Windows)

## Что уже настроено
- Redis service: `Redis` (Windows service).
- Celery broker/result backend: `redis://127.0.0.1:6379/1`.
- EFP очередь работает в strict-режиме (`EFP_ALLOW_THREAD_FALLBACK=0`).

## Быстрый старт
1. `powershell -File scripts/start_celery_worker.ps1`
2. Проверка:
   - `powershell -File scripts/check_celery_worker.ps1 -Strict`
   - `python manage.py check_efp_queue --strict`

## Единое меню управления
- Запуск интерактивного центра управления:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/celery_control_center.ps1`
- Дальше достаточно ввести цифру действия.
- Есть неинтерактивный режим:
  `-Action status|start|stop|restart|queue|logs|register|unregister|watchdog|health`
- По умолчанию включено автовосстановление worker:
  если strict check падает, скрипт пытается поднять worker и повторить проверку.
- Отключить автовосстановление:
  `-NoAutoRecover`

## Автозапуск и watchdog
1. `powershell -File scripts/register_celery_tasks.ps1`
2. Проверить задачи:
   - `schtasks /Query /TN WMS_CeleryWorker_OnLogon`
   - `schtasks /Query /TN WMS_CeleryWatchdog_5min`

Если Task Scheduler недоступен по правам, скрипт автоматически создаст fallback в Startup:
- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WMS_CeleryStartup.cmd`
- он запускает worker и фоновый watchdog-цикл каждые 5 минут.

## Остановка
- `powershell -File scripts/stop_celery_worker.ps1`

## Откат планировщика
- `powershell -File scripts/unregister_celery_tasks.ps1`
