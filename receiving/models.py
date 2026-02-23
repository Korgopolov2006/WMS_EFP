from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from catalog.models import Product, StorageLocation, Warehouse


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        abstract = True


class ReceivingStatus(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    IN_PROGRESS = "IN_PROGRESS", "В процессе"
    COMPLETED = "COMPLETED", "Завершена"
    CANCELLED = "CANCELLED", "Отменена"


class Supplier(TimeStampedModel):
    """Справочник поставщиков для документов приёмки."""

    code = models.CharField("Код поставщика", max_length=24, unique=True)
    name = models.CharField("Название поставщика", max_length=255, unique=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Receiving(TimeStampedModel):
    """
    Документ приёмки поставки.
    """

    number = models.CharField("Номер приёмки", max_length=32, unique=True)
    supplier_name = models.CharField("Поставщик", max_length=255)
    supplier_doc_no = models.CharField("Номер документа поставщика", max_length=64, blank=True)
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="receivings",
        verbose_name="Склад",
        null=True,
        blank=True,
    )

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=ReceivingStatus.choices,
        default=ReceivingStatus.DRAFT,
        db_index=True,
    )

    expected_at = models.DateTimeField("Плановая дата поставки", null=True, blank=True)
    completed_at = models.DateTimeField("Дата завершения", null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="receivings_created",
        verbose_name="Создал",
    )

    class Meta:
        verbose_name = "Приёмка"
        verbose_name_plural = "Приёмки"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.number} — {self.supplier_name}"

    @classmethod
    def generate_next_number(cls, for_date=None) -> str:
        target_date = for_date or timezone.localdate()
        prefix = f"RCV-{target_date:%Y%m%d}-"
        last_number = (
            cls.objects.filter(number__startswith=prefix)
            .order_by("-number")
            .values_list("number", flat=True)
            .first()
        )

        seq = 1
        if last_number:
            try:
                seq = int(last_number.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"{prefix}{seq:04d}"

    @staticmethod
    def _normalize_supplier_code(raw_code: str | None) -> str:
        if not raw_code:
            return "SUP"
        cleaned = "".join(ch for ch in str(raw_code).upper() if ch.isascii() and ch.isalnum())
        return cleaned[:12] if cleaned else "SUP"

    @classmethod
    def generate_next_supplier_doc_number(cls, supplier_code: str | None = None, for_date=None) -> str:
        """
        Генерирует номер документа поставщика.
        Формат: SDOC-<SUPPLIER>-YYYYMMDD-XXXX
        """
        target_date = for_date or timezone.localdate()
        norm_code = cls._normalize_supplier_code(supplier_code)
        prefix = f"SDOC-{norm_code}-{target_date:%Y%m%d}-"
        last_number = (
            cls.objects.filter(supplier_doc_no__startswith=prefix)
            .order_by("-supplier_doc_no")
            .values_list("supplier_doc_no", flat=True)
            .first()
        )

        seq = 1
        if last_number:
            try:
                seq = int(last_number.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_next_number()
        if not self.supplier_doc_no:
            self.supplier_doc_no = self.generate_next_supplier_doc_number(
                supplier_code=self.supplier_name,
                for_date=timezone.localdate(),
            )
        super().save(*args, **kwargs)


class ReceivingLine(models.Model):
    """
    Строка приёмки (позиция товара).
    """

    receiving = models.ForeignKey(
        Receiving,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Приёмка",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="receiving_lines",
        verbose_name="Товар",
    )
    supplier_sku = models.CharField("Артикул поставщика/штрихкод", max_length=64, blank=True)

    qty_expected = models.DecimalField("Ожидаемо, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    qty_received = models.DecimalField("Принято, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))

    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="receiving_lines",
        verbose_name="Место хранения",
        null=True,
        blank=True,
    )

    has_serial_numbers = models.BooleanField("Есть серийные номера", default=False)

    class Meta:
        verbose_name = "Строка приёмки"
        verbose_name_plural = "Строки приёмки"
        ordering = ["receiving_id", "id"]

    def __str__(self) -> str:
        return f"{self.receiving.number} / {self.product.internal_sku}"


class ReceivingSerial(models.Model):
    """
    Учёт серийных номеров (генераторы, стартеры и т.п.).
    """

    line = models.ForeignKey(
        ReceivingLine,
        on_delete=models.CASCADE,
        related_name="serials",
        verbose_name="Строка приёмки",
    )
    serial_number = models.CharField("Серийный номер", max_length=128)

    class Meta:
        verbose_name = "Серийный номер приёмки"
        verbose_name_plural = "Серийные номера приёмки"
        unique_together = ("line", "serial_number")

    def __str__(self) -> str:
        return self.serial_number
