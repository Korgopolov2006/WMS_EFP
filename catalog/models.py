from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from .normalization import normalize_part_number


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        abstract = True


class Branch(TimeStampedModel):
    """
    Филиал компании.
    """

    code = models.CharField("Код филиала", max_length=32, unique=True)
    name = models.CharField("Название филиала", max_length=255)
    address = models.TextField("Адрес", blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Warehouse(TimeStampedModel):
    """
    Склад (принадлежит филиалу).
    """

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="warehouses",
        verbose_name="Филиал",
    )
    code = models.CharField("Код склада", max_length=32)
    name = models.CharField("Название склада", max_length=255)
    width_m = models.DecimalField("Ширина, м", max_digits=8, decimal_places=2, default=30.0)
    length_m = models.DecimalField("Длина, м", max_digits=8, decimal_places=2, default=40.0)
    height_m = models.DecimalField("Высота, м", max_digits=8, decimal_places=2, default=8.0)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Склад"
        verbose_name_plural = "Склады"
        ordering = ["branch__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "code"], name="uniq_warehouse_branch_code"),
        ]

    def __str__(self) -> str:
        return f"{self.branch.code}:{self.code} — {self.name}"


class WarehouseAccess(TimeStampedModel):
    """
    Права доступа пользователя к складу.
    """

    class AccessLevel(models.TextChoices):
        VIEW = "VIEW", "Только просмотр"
        EDIT = "EDIT", "Редактирование"
        ADMIN = "ADMIN", "Администратор"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="warehouse_accesses",
        verbose_name="Пользователь",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="accesses",
        verbose_name="Склад",
    )
    access_level = models.CharField(
        "Уровень доступа",
        max_length=16,
        choices=AccessLevel.choices,
        default=AccessLevel.VIEW,
    )

    class Meta:
        verbose_name = "Доступ к складу"
        verbose_name_plural = "Доступы к складам"
        constraints = [
            models.UniqueConstraint(fields=["user", "warehouse"], name="uniq_warehouse_access_user_warehouse"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} → {self.warehouse.code} ({self.get_access_level_display()})"


class Brand(TimeStampedModel):
    name = models.CharField("Бренд", max_length=120, unique=True)

    class Meta:
        verbose_name = "Бренд"
        verbose_name_plural = "Бренды"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Category(TimeStampedModel):
    name = models.CharField("Категория", max_length=120, unique=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Родительская категория",
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class VehicleMake(TimeStampedModel):
    name = models.CharField("Марка", max_length=120, unique=True)

    class Meta:
        verbose_name = "Марка ТС"
        verbose_name_plural = "Марки ТС"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class VehicleModel(TimeStampedModel):
    make = models.ForeignKey(VehicleMake, on_delete=models.PROTECT, related_name="models", verbose_name="Марка")
    name = models.CharField("Модель", max_length=120)

    class Meta:
        verbose_name = "Модель ТС"
        verbose_name_plural = "Модели ТС"
        ordering = ["make__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["make", "name"], name="uniq_vehicle_model_make_name"),
        ]

    def __str__(self) -> str:
        return f"{self.make} {self.name}"


class StorageZoneType(TimeStampedModel):
    """
    Тип складской зоны (справочник).
    """

    code = models.CharField("Код", max_length=32, unique=True)
    name = models.CharField("Название", max_length=120)
    description = models.TextField("Описание", blank=True)
    sort_order = models.PositiveIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Тип складской зоны"
        verbose_name_plural = "Типы складских зон"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class StorageZone(TimeStampedModel):
    """
    Конкретная зона склада (например: ЯЧЕЕЧНЫЙ-1, ПОЛКИ-2, НАПОЛЬНАЯ-1).
    """

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="zones",
        verbose_name="Склад",
        null=True,
        blank=True,
    )
    code = models.CharField("Код зоны", max_length=32)
    name = models.CharField("Название зоны", max_length=120)
    zone_type = models.ForeignKey(
        StorageZoneType,
        on_delete=models.PROTECT,
        related_name="zones",
        verbose_name="Тип зоны",
    )
    description = models.TextField("Описание", blank=True)

    class Meta:
        verbose_name = "Зона хранения"
        verbose_name_plural = "Зоны хранения"
        ordering = ["warehouse__code", "zone_type__sort_order", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "code"],
                name="uniq_zone_warehouse_code",
                condition=models.Q(warehouse__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        if self.warehouse:
            return f"{self.warehouse.code}:{self.code} — {self.name}"
        return f"{self.code} — {self.name}"


class StorageLocation(TimeStampedModel):
    """
    Место хранения (ячейка, полка, место на полу).
    """

    zone = models.ForeignKey(
        StorageZone,
        on_delete=models.PROTECT,
        related_name="locations",
        verbose_name="Зона",
    )
    code = models.CharField("Код места", max_length=32)
    name = models.CharField("Наименование места", max_length=120, blank=True)

    aisle = models.CharField("Ряд", max_length=16, blank=True)
    rack = models.CharField("Стеллаж", max_length=16, blank=True)
    shelf = models.CharField("Полка", max_length=16, blank=True)
    level = models.CharField("Уровень", max_length=16, blank=True)

    max_weight_kg = models.DecimalField(
        "Максимальный вес, кг",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        verbose_name = "Место хранения"
        verbose_name_plural = "Места хранения"
        ordering = ["zone__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["zone", "code"], name="uniq_location_zone_code"),
        ]

    def __str__(self) -> str:
        return f"{self.zone.code}:{self.code}"


class Product(TimeStampedModel):
    class PackagingType(models.TextChoices):
        SMALL = "SMALL", "Мелкий"
        LARGE = "LARGE", "Крупный"
        PALLET = "PALLET", "Паллетный"

    internal_sku = models.CharField("Внутренний артикул", max_length=64, unique=True)
    name = models.CharField("Наименование", max_length=255)

    oem_number = models.CharField("OEM номер", max_length=64, db_index=True)
    analog_number = models.CharField("Номер аналога", max_length=64, blank=True, db_index=True)
    barcode = models.CharField(
        "Штрихкод",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="EAN-13 / UPC / любой буквенно-цифровой код. Если пусто — используется внутренний артикул.",
    )
    oem_number_normalized = models.CharField(max_length=64, blank=True, default="", editable=False, db_index=True)
    analog_number_normalized = models.CharField(max_length=64, blank=True, default="", editable=False, db_index=True)

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products", verbose_name="Бренд")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products", verbose_name="Категория")

    weight_kg = models.DecimalField(
        "Вес, кг",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    length_cm = models.DecimalField(
        "Длина, см",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    width_cm = models.DecimalField(
        "Ширина, см",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    height_cm = models.DecimalField(
        "Высота, см",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    packaging_type = models.CharField(
        "Тип упаковки",
        max_length=16,
        choices=PackagingType.choices,
        default=PackagingType.SMALL,
        db_index=True,
    )

    photo = models.ImageField("Фото детали", upload_to="products/", null=True, blank=True)

    applicability = models.ManyToManyField(
        VehicleModel,
        through="ProductApplicability",
        related_name="products",
        verbose_name="Применимость",
        blank=True,
    )

    class Meta:
        verbose_name = "Номенклатура (товар)"
        verbose_name_plural = "Номенклатура (товары)"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["oem_number"], name="idx_product_oem"),
            models.Index(fields=["analog_number"], name="idx_product_analog"),
            models.Index(fields=["brand", "category"], name="idx_product_brand_cat"),
            models.Index(fields=["barcode"], name="idx_product_barcode"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["barcode"],
                condition=~models.Q(barcode=""),
                name="uniq_product_barcode_nonempty",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.internal_sku} — {self.name}"

    def save(self, *args, **kwargs):
        self.oem_number_normalized = normalize_part_number(self.oem_number)
        self.analog_number_normalized = normalize_part_number(self.analog_number)
        from .product_validation import validate_product_numbers_uniqueness

        validate_product_numbers_uniqueness(
            oem_number=self.oem_number,
            analog_number=self.analog_number,
            exclude_id=self.pk,
        )
        super().save(*args, **kwargs)


class ProductApplicability(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="fitments", verbose_name="Товар")
    vehicle_model = models.ForeignKey(
        VehicleModel, on_delete=models.PROTECT, related_name="fitments", verbose_name="Модель ТС"
    )

    class Meta:
        verbose_name = "Применимость товара"
        verbose_name_plural = "Применимость товаров"
        constraints = [
            models.UniqueConstraint(fields=["product", "vehicle_model"], name="uniq_product_vehicle_model"),
        ]

    def __str__(self) -> str:
        return f"{self.product} → {self.vehicle_model}"


class ProductCrossReference(TimeStampedModel):
    """
    Перекрёстные ссылки OEM ↔ аналоги.

    Храним именно связи между карточками товара, чтобы:
    - корректно искать замену (аналог)
    - строить отчёты "аналог vs оригинал"
    """

    class RelationType(models.TextChoices):
        ANALOG = "ANALOG", "Аналог"
        OEM = "OEM", "Оригинал (OEM)"
        REPLACED_BY = "REPLACED_BY", "Заменён на"

    from_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="xref_from",
        verbose_name="Из товара",
    )
    to_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="xref_to",
        verbose_name="В товар",
    )
    relation_type = models.CharField("Тип связи", max_length=16, choices=RelationType.choices, db_index=True)
    note = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Перекрёстная ссылка"
        verbose_name_plural = "Перекрёстные ссылки"
        constraints = [
            models.CheckConstraint(condition=~models.Q(from_product=models.F("to_product")), name="chk_xref_not_self"),
            models.UniqueConstraint(
                fields=["from_product", "to_product", "relation_type"], name="uniq_xref_from_to_type"
            ),
        ]
        indexes = [
            models.Index(fields=["from_product", "relation_type"], name="idx_xref_from_type"),
        ]

    def __str__(self) -> str:
        return f"{self.from_product} → {self.to_product} ({self.relation_type})"


class ProductChangeLog(TimeStampedModel):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Создание"
        UPDATE = "UPDATE", "Изменение"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="change_logs",
        verbose_name="Товар",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_change_logs",
        verbose_name="Пользователь",
    )
    action = models.CharField("Действие", max_length=16, choices=Action.choices, db_index=True)
    source = models.CharField("Источник", max_length=32, default="ui")
    changed_fields = models.JSONField("Изменения", default=dict, blank=True)
    note = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Журнал изменения товара"
        verbose_name_plural = "Журнал изменений товаров"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "created_at"], name="idx_prod_chlog_product_created"),
            models.Index(fields=["action", "created_at"], name="idx_prod_chlog_action_created"),
        ]

    def __str__(self) -> str:
        return f"{self.product.internal_sku}: {self.get_action_display()} ({self.created_at:%d.%m.%Y %H:%M})"


class Backorder(TimeStampedModel):
    """
    Отложенный заказ (товар отсутствует на складе, заказ будет выполнен при поступлении).
    """

    order = models.ForeignKey(
        "picking.Order",
        on_delete=models.CASCADE,
        related_name="backorders",
        verbose_name="Заказ",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="backorders",
        verbose_name="Товар",
    )
    qty_ordered = models.DecimalField(
        "Заказано, шт",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    qty_fulfilled = models.DecimalField(
        "Выполнено, шт",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    status = models.CharField(
        "Статус",
        max_length=16,
        choices=[
            ("PENDING", "Ожидает"),
            ("PARTIAL", "Частично выполнен"),
            ("FULFILLED", "Выполнен"),
            ("CANCELLED", "Отменён"),
        ],
        default="PENDING",
        db_index=True,
    )

    expected_arrival_date = models.DateField("Ожидаемая дата поступления", null=True, blank=True)
    fulfilled_at = models.DateTimeField("Выполнено", null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_backorders",
        verbose_name="Создал",
    )

    notes = models.TextField("Примечания", blank=True)

    class Meta:
        verbose_name = "Отложенный заказ"
        verbose_name_plural = "Отложенные заказы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="idx_backorder_status"),
            models.Index(fields=["expected_arrival_date"], name="idx_backorder_arrival"),
        ]

    def __str__(self) -> str:
        return f"Backorder: {self.order.number} — {self.product.internal_sku} ({self.qty_ordered} шт)"

    @property
    def qty_remaining(self):
        """Осталось выполнить."""
        return self.qty_ordered - self.qty_fulfilled


class Tool(TimeStampedModel):
    """
    Инструмент на складе (штабелёры, тележки, сканеры и т.д.).
    """

    class ToolType(models.TextChoices):
        FORKLIFT = "FORKLIFT", "Штабелёр"
        HAND_TRUCK = "HAND_TRUCK", "Ручная тележка"
        SCANNER = "SCANNER", "Сканер штрихкодов"
        PRINTER = "PRINTER", "Принтер этикеток"
        OTHER = "OTHER", "Прочее"

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="tools",
        verbose_name="Склад",
        null=True,
        blank=True,
    )

    tool_type = models.CharField(
        "Тип инструмента",
        max_length=32,
        choices=ToolType.choices,
        db_index=True,
    )
    code = models.CharField("Код/Инвентарный номер", max_length=64, unique=True)
    name = models.CharField("Название", max_length=255)
    brand = models.CharField("Бренд/Производитель", max_length=120, blank=True)
    model = models.CharField("Модель", max_length=120, blank=True)

    is_available = models.BooleanField("Доступен", default=True)
    is_active = models.BooleanField("Активен", default=True)

    # Текущее использование
    current_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="tools_in_use",
        verbose_name="Текущий пользователь",
        null=True,
        blank=True,
    )
    checked_out_at = models.DateTimeField("Выдан", null=True, blank=True)
    expected_return_at = models.DateTimeField("Ожидаемое возвращение", null=True, blank=True)

    # Техническое обслуживание
    last_maintenance_date = models.DateField("Последнее ТО", null=True, blank=True)
    next_maintenance_date = models.DateField("Следующее ТО", null=True, blank=True)
    maintenance_notes = models.TextField("Примечания по ТО", blank=True)

    notes = models.TextField("Примечания", blank=True)

    class Meta:
        verbose_name = "Инструмент"
        verbose_name_plural = "Инструменты"
        ordering = ["warehouse", "tool_type", "code"]
        indexes = [
            models.Index(fields=["warehouse", "is_available"], name="idx_tool_warehouse_available"),
            models.Index(fields=["tool_type"], name="idx_tool_type"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name} ({self.get_tool_type_display()})"

    def is_in_use(self) -> bool:
        """Проверяет, используется ли инструмент сейчас."""
        return self.current_user is not None and self.is_available
