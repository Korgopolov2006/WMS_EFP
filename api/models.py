from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models


class ApiToken(models.Model):
    """
    Токен для интеграций (машинный доступ).
    Использование: Authorization: Bearer <token>
    """

    name = models.CharField("Название", max_length=120)
    token = models.CharField("Токен", max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
        verbose_name="Пользователь",
    )
    is_active = models.BooleanField("Активен", default=True, db_index=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    last_used_at = models.DateTimeField("Последнее использование", null=True, blank=True)

    class Meta:
        verbose_name = "API токен"
        verbose_name_plural = "API токены"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.user})"

    @staticmethod
    def generate_token() -> str:
        # 32 bytes -> 64 hex chars
        return secrets.token_hex(32)

