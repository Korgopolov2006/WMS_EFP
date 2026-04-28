from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from catalog.models import Product, StorageLocation


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        abstract = True


class Stock(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="stock_items",
        verbose_name="Товар",
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="stock_items",
        verbose_name="Место хранения",
    )

    qty_available = models.DecimalField("Доступно, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    qty_reserved = models.DecimalField("Зарезервировано, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))

    batch_no = models.CharField("Номер партии", max_length=64, blank=True)
    expiry_date = models.DateField("Срок годности", null=True, blank=True)

    class Meta:
        verbose_name = "Остаток"
        verbose_name_plural = "Остатки"
        constraints = [
            models.UniqueConstraint(fields=["product", "storage_location", "batch_no"], name="uniq_stock_product_location_batch"),
        ]
        indexes = [
            models.Index(fields=["product"], name="idx_stock_product"),
            models.Index(fields=["storage_location"], name="idx_stock_location"),
            models.Index(fields=["qty_available"], name="idx_stock_qty_available"),
        ]

    def __str__(self) -> str:
        return f"{self.product.internal_sku} @ {self.storage_location.code} = {self.qty_available}"

    @property
    def qty_total(self) -> Decimal:
        return self.qty_available + self.qty_reserved


class InventoryStatus(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    IN_PROGRESS = "IN_PROGRESS", "В процессе"
    COMPLETED = "COMPLETED", "Завершена"
    CANCELLED = "CANCELLED", "Отменена"


class Inventory(TimeStampedModel):
    number = models.CharField("Номер инвентаризации", max_length=32, unique=True)
    zone = models.ForeignKey(
        "catalog.StorageZone",
        on_delete=models.PROTECT,
        related_name="inventories",
        verbose_name="Зона",
        null=True,
        blank=True,
    )

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=InventoryStatus.choices,
        default=InventoryStatus.DRAFT,
        db_index=True,
    )

    started_at = models.DateTimeField("Начало", null=True, blank=True)
    completed_at = models.DateTimeField("Завершение", null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventories_created",
        verbose_name="Создал",
    )

    class Meta:
        verbose_name = "Инвентаризация"
        verbose_name_plural = "Инвентаризации"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.number} ({self.get_status_display()})"


class InventoryLine(models.Model):
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Инвентаризация",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="inventory_lines",
        verbose_name="Товар",
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="inventory_lines",
        verbose_name="Место хранения",
    )

    qty_book = models.DecimalField("По учёту, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    qty_actual = models.DecimalField("Фактически, шт", max_digits=10, decimal_places=2, null=True, blank=True)

    discrepancy = models.DecimalField("Расхождение", max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        verbose_name = "Строка инвентаризации"
        verbose_name_plural = "Строки инвентаризации"
        constraints = [
            models.UniqueConstraint(fields=["inventory", "product", "storage_location"], name="uniq_inv_line_inv_prod_loc"),
        ]

    def __str__(self) -> str:
        return f"{self.inventory.number} — {self.product.internal_sku} @ {self.storage_location.code}"

    def save(self, *args, **kwargs):
        if self.qty_actual is not None and self.qty_book is not None:
            self.discrepancy = self.qty_actual - self.qty_book
        super().save(*args, **kwargs)


class MovementType(models.TextChoices):
    RECEIPT = "RECEIPT", "Поступление"
    TRANSFER = "TRANSFER", "Перемещение"
    WRITE_OFF = "WRITE_OFF", "Списание"
    ISSUE = "ISSUE", "Выдача"
    RETURN = "RETURN", "Возврат"
    INVENTORY = "INVENTORY", "Инвентаризация"
    ADJUSTMENT = "ADJUSTMENT", "Корректировка"


class MovementStatus(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    POSTED = "POSTED", "Проведено"
    CANCELLED = "CANCELLED", "Отменено"


class StockMovement(models.Model):
    """
    Журнал движения товара: единая запись на любую операцию,
    влияющую на остатки. Не подменяет Stock — только аудит-след.
    """

    movement_type = models.CharField(
        "Тип операции",
        max_length=16,
        choices=MovementType.choices,
        db_index=True,
    )
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=MovementStatus.choices,
        default=MovementStatus.POSTED,
        db_index=True,
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name="Товар",
    )
    quantity = models.DecimalField(
        "Количество",
        max_digits=12,
        decimal_places=2,
    )

    from_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="movements_out",
        null=True, blank=True,
        verbose_name="Откуда",
    )
    to_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="movements_in",
        null=True, blank=True,
        verbose_name="Куда",
    )

    batch_no = models.CharField("Партия", max_length=64, blank=True)
    reason = models.CharField("Причина", max_length=128, blank=True)
    comment = models.TextField("Комментарий", blank=True)

    # Связь с исходным документом (Receiving/Order/Inventory) без жёсткой FK
    ref_type = models.CharField("Тип документа", max_length=32, blank=True)
    ref_id = models.CharField("ID документа", max_length=64, blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="stock_movements",
        verbose_name="Пользователь",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Движение товара"
        verbose_name_plural = "Журнал движений"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["product", "-created_at"], name="idx_mov_product_date"),
            models.Index(fields=["movement_type", "-created_at"], name="idx_mov_type_date"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(quantity=0),
                name="movement_qty_nonzero",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_movement_type_display()} · {self.product.internal_sku} × {self.quantity}"

    @property
    def signed_quantity(self) -> Decimal:
        """Знаковое количество: приход +, расход -."""
        outgoing = {
            MovementType.WRITE_OFF,
            MovementType.ISSUE,
        }
        if self.movement_type in outgoing:
            return -abs(self.quantity)
        return self.quantity
