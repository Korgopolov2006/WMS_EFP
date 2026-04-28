from __future__ import annotations

from django.conf import settings
from django.db import models

from inventory.models import Inventory
from picking.models import Order, PickingTask
from receiving.models import Receiving


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        abstract = True


class TaskType(models.TextChoices):
    RECEIVING = "RECEIVING", "Приёмка"
    INVENTORY = "INVENTORY", "Инвентаризация"
    PICKING = "PICKING", "Подбор"
    SHIPPING = "SHIPPING", "Отгрузка"
    STOCK_MOVEMENT = "STOCK_MOVEMENT", "Перемещение товара"
    OTHER = "OTHER", "Прочее"


class TaskStatus(models.TextChoices):
    PENDING = "PENDING", "Ожидает"
    IN_PROGRESS = "IN_PROGRESS", "В работе"
    COMPLETED = "COMPLETED", "Завершена"
    CANCELLED = "CANCELLED", "Отменена"
    ON_HOLD = "ON_HOLD", "Приостановлена"


class TaskPriority(models.TextChoices):
    LOW = "LOW", "Низкий"
    NORMAL = "NORMAL", "Обычный"
    HIGH = "HIGH", "Высокий"
    URGENT = "URGENT", "Срочный"


class Task(TimeStampedModel):
    """
    Универсальная задача для управления различными операциями на складе.
    """

    task_type = models.CharField(
        "Тип задачи",
        max_length=32,
        choices=TaskType.choices,
        db_index=True,
    )
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        db_index=True,
    )
    priority = models.CharField(
        "Приоритет",
        max_length=16,
        choices=TaskPriority.choices,
        default=TaskPriority.NORMAL,
        db_index=True,
    )

    title = models.CharField("Название задачи", max_length=255)
    description = models.TextField("Описание", blank=True)

    # Связи с документами
    receiving = models.ForeignKey(
        Receiving,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Приёмка",
        null=True,
        blank=True,
    )
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Инвентаризация",
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Заказ",
        null=True,
        blank=True,
    )
    picking_task = models.ForeignKey(
        PickingTask,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Задача подбора",
        null=True,
        blank=True,
    )

    # Исполнители
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_tasks",
        verbose_name="Назначен",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tasks",
        verbose_name="Создал",
    )

    # Временные метки
    due_date = models.DateTimeField("Срок выполнения", null=True, blank=True)
    started_at = models.DateTimeField("Начало", null=True, blank=True)
    completed_at = models.DateTimeField("Завершение", null=True, blank=True)

    # Дополнительные данные
    metadata = models.JSONField("Метаданные", default=dict, blank=True)

    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["task_type", "status"], name="idx_task_type_status"),
            models.Index(fields=["assigned_to", "status"], name="idx_task_assigned_status"),
            models.Index(fields=["priority", "due_date"], name="idx_task_priority_due"),
        ]

    def __str__(self) -> str:
        return f"{self.get_task_type_display()}: {self.title} ({self.get_status_display()})"

    def can_be_assigned_to(self, user) -> bool:
        """Проверяет, может ли задача быть назначена пользователю."""
        from accounts.constants import Roles

        if user.is_superuser:
            return True

        # Логика проверки прав в зависимости от типа задачи
        if self.task_type == TaskType.RECEIVING:
            return user.role in [Roles.STOREKEEPER, Roles.ADMIN]
        elif self.task_type == TaskType.PICKING:
            return user.role in [Roles.SMALL_PARTS_PICKER, Roles.LOADER, Roles.STOREKEEPER, Roles.ADMIN]
        elif self.task_type == TaskType.INVENTORY:
            return user.role in [Roles.STOREKEEPER, Roles.ADMIN]
        elif self.task_type == TaskType.SHIPPING:
            return user.role in [Roles.LOADER, Roles.STOREKEEPER, Roles.ADMIN]
        elif self.task_type == TaskType.STOCK_MOVEMENT:
            return user.role in [Roles.STOREKEEPER, Roles.ADMIN]
        return True


class TaskComment(TimeStampedModel):
    """Комментарии к задачам."""

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Задача",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_comments",
        verbose_name="Автор",
    )
    text = models.TextField("Текст комментария")

    class Meta:
        verbose_name = "Комментарий к задаче"
        verbose_name_plural = "Комментарии к задачам"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Комментарий к задаче #{self.task.id} от {self.author.username}"
