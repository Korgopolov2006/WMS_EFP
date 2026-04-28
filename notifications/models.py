"""
Модель уведомлений пользователя.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class NotificationKind(models.TextChoices):
    INFO = "INFO", "Информация"
    SUCCESS = "SUCCESS", "Успех"
    WARNING = "WARNING", "Предупреждение"
    DANGER = "DANGER", "Ошибка"


class NotificationPriority(models.TextChoices):
    LOW = "LOW", "Низкий"
    NORMAL = "NORMAL", "Обычный"
    HIGH = "HIGH", "Высокий"


class Notification(models.Model):
    """
    Лёгкое in-app уведомление: показывается в bell-меню, на странице /notifications/,
    без обязательной email-доставки. При желании сервис уведомлений может
    дополнительно отправлять email (см. notifications.services.notify).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Пользователь",
    )
    kind = models.CharField(
        "Тип",
        max_length=16,
        choices=NotificationKind.choices,
        default=NotificationKind.INFO,
        db_index=True,
    )
    priority = models.CharField(
        "Приоритет",
        max_length=8,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
        db_index=True,
    )
    title = models.CharField("Заголовок", max_length=200)
    body = models.TextField("Текст", blank=True)
    link = models.CharField("Ссылка", max_length=500, blank=True)

    # Группировка одинаковых событий (low_stock-<sku>, backup-error и т.д.)
    # — позволяет апсёртить вместо плодения дубликатов.
    dedup_key = models.CharField(
        "Ключ дедупликации",
        max_length=128,
        blank=True,
        db_index=True,
    )

    is_read = models.BooleanField("Прочитано", default=False, db_index=True)
    read_at = models.DateTimeField("Прочитано в", null=True, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"], name="idx_notif_user_unread"),
        ]

    def __str__(self) -> str:
        return f"[{self.get_kind_display()}] {self.title}"
