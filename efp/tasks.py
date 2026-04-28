from __future__ import annotations

try:
    from celery import shared_task
except Exception:
    shared_task = None

from .queue import _run_search_in_background


if shared_task:

    @shared_task(name="efp.search_oem")
    def efp_search_task(task_id: str, oem_code: str) -> None:
        _run_search_in_background(task_id=task_id, oem_code=oem_code, backend="celery")

else:

    class _CeleryMissingTask:
        def delay(self, *args, **kwargs):
            raise RuntimeError("Celery is not installed")

    efp_search_task = _CeleryMissingTask()
