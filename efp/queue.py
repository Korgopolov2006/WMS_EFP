from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .services import EFPService
from wms.celery import app as celery_app

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 60 * 30
JOB_STALE_SECONDS = 60 * 5
PING_CACHE_TTL_SECONDS = 15
REDIS_PING_CACHE_KEY = "efp:health:redis_ping"
CELERY_PING_CACHE_KEY = "efp:health:celery_ping"


def _job_cache_key(task_id: str) -> str:
    return f"efp:job:{task_id}"


def _make_job_payload(*, status: str, oem_code: str, backend: str, task_id: str, **extra) -> dict:
    payload = {
        "status": status,
        "oem_code": oem_code,
        "backend": backend,
        "task_id": task_id,
        "updated_at": timezone.now().isoformat(),
    }
    payload.update(extra)
    return payload


def _save_job(task_id: str, payload: dict) -> None:
    cache.set(_job_cache_key(task_id), payload, timeout=JOB_TTL_SECONDS)


def _run_search_in_background(task_id: str, oem_code: str, backend: str) -> None:
    _save_job(task_id, _make_job_payload(status="running", oem_code=oem_code, backend=backend, task_id=task_id))
    try:
        success, results, message, error_code = EFPService.search_part(oem_code, use_cache=True)
        _save_job(
            task_id,
            _make_job_payload(
                status="done",
                oem_code=oem_code,
                backend=backend,
                task_id=task_id,
                result={
                    "success": success,
                    "results": results,
                    "message": message,
                    "error_code": error_code,
                    "manual_url": EFPService.manual_search_url(oem_code),
                },
            ),
        )
    except Exception as exc:
        logger.exception("EFP background search failed for OEM %s", oem_code)
        _save_job(
            task_id,
            _make_job_payload(
                status="failed",
                oem_code=oem_code,
                backend=backend,
                task_id=task_id,
                error=str(exc),
                result={
                    "success": False,
                    "results": [],
                    "message": "Ошибка фоновой проверки EFP.",
                    "error_code": "queue_runtime_error",
                    "manual_url": EFPService.manual_search_url(oem_code),
                },
            ),
        )


def _check_redis_available() -> bool:
    cached = cache.get(REDIS_PING_CACHE_KEY)
    if isinstance(cached, bool):
        return cached

    ok = False
    try:
        import redis
        client = redis.from_url(settings.CELERY_BROKER_URL)
        ok = bool(client.ping())
    except Exception:
        ok = False

    cache.set(REDIS_PING_CACHE_KEY, ok, timeout=PING_CACHE_TTL_SECONDS)
    return ok


def _check_celery_worker_available() -> bool:
    cached = cache.get(CELERY_PING_CACHE_KEY)
    if isinstance(cached, bool):
        return cached

    ok = False
    try:
        inspector = celery_app.control.inspect(timeout=1)
        ping_result = inspector.ping() if inspector else None
        ok = bool(ping_result)
    except Exception:
        ok = False

    cache.set(CELERY_PING_CACHE_KEY, ok, timeout=PING_CACHE_TTL_SECONDS)
    return ok


def enqueue_efp_search(oem_code: str) -> tuple[str, str, str]:
    normalized_oem = EFPService._normalize_oem_code(oem_code)
    task_id = uuid.uuid4().hex
    queue_warning = ""

    _save_job(task_id, _make_job_payload(status="queued", oem_code=normalized_oem, backend="pending", task_id=task_id))

    if not _check_redis_available():
        raise RuntimeError("Redis broker is unavailable")
    if not _check_celery_worker_available():
        raise RuntimeError("No active Celery workers")

    # Пытаемся отправить задачу в Celery. Fallback в локальный поток включается только флагом EFP_ALLOW_THREAD_FALLBACK.
    try:
        from .tasks import efp_search_task

        async_result = efp_search_task.delay(task_id, normalized_oem)
        _save_job(
            task_id,
            _make_job_payload(
                status="queued",
                oem_code=normalized_oem,
                backend="celery",
                task_id=task_id,
                celery_id=str(getattr(async_result, "id", "")),
            ),
        )
        return task_id, "celery", queue_warning
    except Exception as exc:
        allow_thread_fallback = bool(getattr(settings, "EFP_ALLOW_THREAD_FALLBACK", False))
        logger.warning("Celery queue unavailable: %s", exc)
        if not allow_thread_fallback:
            raise RuntimeError("Celery queue is unavailable") from exc

        logger.warning("Fallback to local thread is enabled")
        queue_warning = "Очередь Celery недоступна, используется локальный фоновый режим."
        _save_job(
            task_id,
            _make_job_payload(
                status="queued",
                oem_code=normalized_oem,
                backend="thread",
                task_id=task_id,
                queue_warning=queue_warning,
            ),
        )
        thread = threading.Thread(
            target=_run_search_in_background,
            args=(task_id, normalized_oem, "thread"),
            daemon=True,
        )
        thread.start()
        return task_id, "thread", queue_warning


def get_efp_search_job(task_id: str) -> dict | None:
    job = cache.get(_job_cache_key(task_id))
    if not isinstance(job, dict):
        return None

    updated_raw = job.get("updated_at")
    if isinstance(updated_raw, str):
        try:
            updated_dt = datetime.fromisoformat(updated_raw)
            if timezone.is_naive(updated_dt):
                updated_dt = timezone.make_aware(updated_dt, timezone.get_current_timezone())
            if job.get("status") in {"queued", "running"} and timezone.now() - updated_dt > timedelta(seconds=JOB_STALE_SECONDS):
                stale_job = dict(job)
                stale_job["status"] = "failed"
                stale_job["result"] = {
                    "success": False,
                    "results": [],
                    "message": "Проверка EFP не завершилась вовремя.",
                    "error_code": "queue_timeout",
                    "manual_url": EFPService.manual_search_url(job.get("oem_code", "")),
                }
                _save_job(task_id, stale_job)
                return stale_job
        except Exception:
            logger.debug("Cannot parse updated_at for EFP job %s", task_id)

    return job
