from __future__ import annotations

try:
    from .celery import app as celery_app
except Exception:  # noqa: BLE001
    celery_app = None

__all__ = ("celery_app",)
