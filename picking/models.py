from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from catalog.models import Product
from inventory.models import Stock


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        abstract = True


class OrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    CONFIRMED = "CONFIRMED", "Подтверждён"
    IN_PICKING = "IN_PICKING", "В подборе"
    PICKED = "PICKED", "Подобран"
    RESERVED = "RESERVED", "Зарезервирован"
    SHIPPED = "SHIPPED", "Отгружен"
    CANCELLED = "CANCELLED", "Отменён"


class Order(TimeStampedModel):
    number = models.CharField("Номер заказа", max_length=32, unique=True, db_index=True)
    customer_name = models.CharField("Клиент", max_length=255)
    customer_phone = models.CharField("Телефон", max_length=32, blank=True)
    customer_email = models.EmailField("Email", blank=True)

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
        db_index=True,
    )

    source = models.CharField("Источник", max_length=32, default="MANUAL", help_text="MANUAL, POS, ONLINE, API")
    external_id = models.CharField("Внешний ID", max_length=64, blank=True, help_text="ID из внешней системы")

    confirmed_at = models.DateTimeField("Подтверждён", null=True, blank=True)
    picked_at = models.DateTimeField("Подобран", null=True, blank=True)
    shipped_at = models.DateTimeField("Отгружен", null=True, blank=True)

    reserved_at_window = models.BooleanField("Зарезервирован у окна", default=False)
    window_number = models.CharField("Номер окна выдачи", max_length=16, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders_created",
        verbose_name="Создал",
    )
    picked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders_picked",
        verbose_name="Подобрал",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["status"], name="idx_order_status"),
            models.Index(fields=["number"], name="idx_order_number"),
        ]

    def __str__(self) -> str:
        return f"{self.number} — {self.customer_name}"


class OrderLine(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Заказ",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_lines",
        verbose_name="Товар",
    )

    qty_ordered = models.DecimalField(
        "Заказано, шт",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    qty_picked = models.DecimalField(
        "Подобрано, шт",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    price = models.DecimalField("Цена", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Строка заказа"
        verbose_name_plural = "Строки заказа"
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="uniq_order_line_order_product"),
        ]
        ordering = ["product__name"]

    def __str__(self) -> str:
        return f"{self.order.number} — {self.product.internal_sku} ({self.qty_picked}/{self.qty_ordered})"


class PickingTaskStatus(models.TextChoices):
    PENDING = "PENDING", "Ожидает"
    IN_PROGRESS = "IN_PROGRESS", "В работе"
    COMPLETED = "COMPLETED", "Завершена"
    CANCELLED = "CANCELLED", "Отменена"


class PickingTask(TimeStampedModel):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="picking_tasks",
        verbose_name="Заказ",
    )

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=PickingTaskStatus.choices,
        default=PickingTaskStatus.PENDING,
        db_index=True,
    )

    zone_type_code = models.CharField(
        "Тип зоны",
        max_length=32,
        help_text="CELL, SHELF, FLOOR — для маршрутизации",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="picking_tasks",
        verbose_name="Назначен",
        null=True,
        blank=True,
    )

    started_at = models.DateTimeField("Начало", null=True, blank=True)
    completed_at = models.DateTimeField("Завершение", null=True, blank=True)

    class Meta:
        verbose_name = "Задача подбора"
        verbose_name_plural = "Задачи подбора"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["status"], name="idx_picking_task_status"),
            models.Index(fields=["zone_type_code"], name="idx_picking_task_zone"),
        ]

    def __str__(self) -> str:
        return f"Подбор {self.order.number} ({self.zone_type_code})"


class PickingLine(models.Model):
    task = models.ForeignKey(
        PickingTask,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Задача подбора",
    )
    order_line = models.ForeignKey(
        OrderLine,
        on_delete=models.CASCADE,
        related_name="picking_lines",
        verbose_name="Строка заказа",
    )
    stock = models.ForeignKey(
        Stock,
        on_delete=models.PROTECT,
        related_name="picking_lines",
        verbose_name="Остаток",
    )

    qty_picked = models.DecimalField(
        "Подобрано, шт",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    scanned_oem = models.CharField("Отсканированный OEM", max_length=64, blank=True)

    class Meta:
        verbose_name = "Строка подбора"
        verbose_name_plural = "Строки подбора"
        constraints = [
            models.UniqueConstraint(fields=["task", "order_line", "stock"], name="uniq_picking_line_task_order_stock"),
        ]

    def __str__(self) -> str:
        return f"{self.task} — {self.order_line.product.internal_sku} ({self.qty_picked})"
