from __future__ import annotations

from django.core.validators import MinValueValidator
from django.db import models

from catalog.models import TimeStampedModel, Warehouse


class WarehouseLayout(TimeStampedModel):
    """
    Геометрия склада: контур, стены, активная зона.
    """

    warehouse = models.OneToOneField(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="layout",
        verbose_name="Склад",
    )
    floor_points = models.JSONField(
        "Точки контура пола",
        default=list,
        help_text="Массив точек [[x, z], ...] для построения контура склада",
    )
    is_layout_defined = models.BooleanField(
        "Разметка выполнена",
        default=False,
        help_text="True, если контур склада уже нарисован",
    )

    # ── Точка «ворот» (нужна для анимации движений в 3D) ──
    gate_x = models.FloatField(
        "Координата ворот X",
        null=True, blank=True,
        help_text="Если не задано — берётся середина первой грани контура",
    )
    gate_z = models.FloatField("Координата ворот Z", null=True, blank=True)

    @property
    def gate_point(self):
        """Возвращает (x, z) для точки ворот: явное значение или середина первой грани."""
        if self.gate_x is not None and self.gate_z is not None:
            return (float(self.gate_x), float(self.gate_z))
        if self.floor_points and len(self.floor_points) >= 2:
            (x1, z1), (x2, z2) = self.floor_points[0], self.floor_points[1]
            return ((x1 + x2) / 2.0, (z1 + z2) / 2.0)
        return (0.0, 0.0)

    class Meta:
        verbose_name = "Геометрия склада"
        verbose_name_plural = "Геометрии складов"

    def __str__(self) -> str:
        return f"Layout: {self.warehouse.code}"

    def get_floor_points_list(self):
        """Возвращает список точек как список кортежей [(x, z), ...]."""
        if not self.floor_points:
            return []
        return [tuple(point) for point in self.floor_points]


class StorageObject(TimeStampedModel):
    """
    3D-объект хранения на складе: стеллаж, полка, ячейка, напольная зона.
    """

    class ObjectType(models.TextChoices):
        RACK = "RACK", "Стеллаж"
        SHELF = "SHELF", "Полка"
        CELL = "CELL", "Ячейка"
        FLOOR = "FLOOR", "Напольное место"

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="storage_objects",
        verbose_name="Склад",
    )
    object_type = models.CharField(
        "Тип объекта",
        max_length=16,
        choices=ObjectType.choices,
        db_index=True,
    )
    code = models.CharField("Код объекта", max_length=64, blank=True)
    name = models.CharField("Название", max_length=255, blank=True)

    # Позиция и размеры в 3D-пространстве
    position_x = models.FloatField("Позиция X", default=0.0)
    position_z = models.FloatField("Позиция Z", default=0.0)
    position_y = models.FloatField("Позиция Y (высота)", default=0.0)

    width = models.FloatField(
        "Ширина",
        default=1.0,
        validators=[MinValueValidator(0.1)],
    )
    depth = models.FloatField(
        "Глубина",
        default=1.0,
        validators=[MinValueValidator(0.1)],
    )
    height = models.FloatField(
        "Высота",
        default=1.0,
        validators=[MinValueValidator(0.1)],
    )

    rotation_y = models.FloatField(
        "Поворот вокруг Y (градусы)",
        default=0.0,
        help_text="Поворот объекта вокруг вертикальной оси",
    )

    is_active = models.BooleanField("Активен", default=True)

    # Связь с логическими местами хранения (опционально)
    storage_location = models.ForeignKey(
        "catalog.StorageLocation",
        on_delete=models.SET_NULL,
        related_name="storage_objects_3d",
        verbose_name="Место хранения",
        null=True,
        blank=True,
        help_text="Связь с логическим местом хранения из каталога",
    )

    class Meta:
        verbose_name = "Объект хранения"
        verbose_name_plural = "Объекты хранения"
        ordering = ["warehouse", "object_type", "code"]
        indexes = [
            models.Index(fields=["warehouse", "object_type"], name="idx_storage_obj_wh_type"),
        ]

    def __str__(self) -> str:
        if self.code:
            return f"{self.warehouse.code}:{self.code} ({self.get_object_type_display()})"
        return f"{self.warehouse.code}:{self.get_object_type_display()} #{self.id}"

    def has_stock(self):
        """Проверяет, есть ли товары на этом объекте хранения."""
        if not self.storage_location:
            return False
        from inventory.models import Stock
        return Stock.objects.filter(
            storage_location=self.storage_location,
            qty_available__gt=0
        ).exists()

    def get_stock_count(self):
        """Возвращает количество различных товаров на объекте."""
        if not self.storage_location:
            return 0
        from inventory.models import Stock
        return Stock.objects.filter(
            storage_location=self.storage_location,
            qty_available__gt=0
        ).count()

    def get_total_stock_qty(self):
        """Возвращает общее количество товаров на объекте."""
        if not self.storage_location:
            return 0
        from inventory.models import Stock
        from django.db.models import Sum
        result = Stock.objects.filter(
            storage_location=self.storage_location
        ).aggregate(total=Sum('qty_available'))
        return result['total'] or 0
