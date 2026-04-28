from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand
import redis

from wms.celery import app as celery_app


class Command(BaseCommand):
    help = "Проверка доступности Redis/Celery для фоновой EFP-проверки."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Вернуть код ошибки, если Redis/Celery недоступны.",
        )

    def handle(self, *args, **options):
        broker_url = settings.CELERY_BROKER_URL
        result_backend = settings.CELERY_RESULT_BACKEND

        redis_ok = False
        redis_error = ""
        try:
            client = redis.from_url(broker_url)
            redis_ok = bool(client.ping())
        except Exception as exc:
            redis_ok = False
            redis_error = str(exc)

        celery_ok = False
        celery_workers = []
        celery_error = ""
        try:
            inspect = celery_app.control.inspect(timeout=1)
            ping = inspect.ping() if inspect else None
            if isinstance(ping, dict) and ping:
                celery_ok = True
                celery_workers = sorted(ping.keys())
        except Exception as exc:
            celery_ok = False
            celery_error = str(exc)

        payload = {
            "broker_url": broker_url,
            "result_backend": result_backend,
            "redis_ok": redis_ok,
            "redis_error": redis_error,
            "celery_ok": celery_ok,
            "celery_workers": celery_workers,
            "celery_error": celery_error,
        }

        self.stdout.write(json.dumps(payload, ensure_ascii=False))

        if options.get("strict") and (not redis_ok or not celery_ok):
            raise SystemExit(1)
