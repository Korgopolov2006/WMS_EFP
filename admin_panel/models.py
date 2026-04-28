"""
Модели административной панели WMS.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Журнал действий администраторов."""

    class ActionType(models.TextChoices):
        LOGIN = "LOGIN", "Вход в систему"
        LOGOUT = "LOGOUT", "Выход из системы"
        CREATE = "CREATE", "Создание"
        UPDATE = "UPDATE", "Обновление"
        DELETE = "DELETE", "Удаление"
        ACTIVATE = "ACTIVATE", "Активация"
        DEACTIVATE = "DEACTIVATE", "Деактивация"
        BACKUP_CREATE = "BACKUP_CREATE", "Создание резервной копии"
        BACKUP_RESTORE = "BACKUP_RESTORE", "Восстановление из резервной копии"
        BACKUP_DELETE = "BACKUP_DELETE", "Удаление резервной копии"
        PASSWORD_RESET = "PASSWORD_RESET", "Сброс пароля"
        VIEW = "VIEW", "Просмотр"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="Пользователь",
    )
    action = models.CharField(
        "Действие",
        max_length=32,
        choices=ActionType.choices,
        db_index=True,
    )
    resource_type = models.CharField("Тип ресурса", max_length=64, blank=True)
    resource_id = models.CharField("ID ресурса", max_length=64, blank=True)
    resource_str = models.CharField("Ресурс (текст)", max_length=255, blank=True)
    changes = models.JSONField("Изменения", null=True, blank=True)
    ip_address = models.GenericIPAddressField(
        "IP адрес", null=True, blank=True, unpack_ipv4=True
    )
    user_agent = models.CharField("User-Agent", max_length=512, blank=True)
    timestamp = models.DateTimeField("Дата и время", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        ts = self.timestamp.strftime("%d.%m.%Y %H:%M") if self.timestamp else "—"
        who = self.user.username if self.user else "system"
        return f"{ts} · {who} · {self.get_action_display()}"


class BackupRecord(models.Model):
    """Запись о резервной копии базы данных."""

    filename = models.CharField("Имя файла", max_length=255, unique=True)
    size_bytes = models.BigIntegerField("Размер (байт)", default=0)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backups",
        verbose_name="Создал",
    )
    notes = models.TextField("Заметки", blank=True)
    is_auto = models.BooleanField("Автоматический", default=False)

    class Meta:
        verbose_name = "Резервная копия"
        verbose_name_plural = "Резервные копии"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.filename

    @property
    def size_human(self) -> str:
        """Читаемый размер файла."""
        size = float(self.size_bytes)
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} ТБ"
