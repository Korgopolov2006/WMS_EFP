from __future__ import annotations

from decimal import Decimal

from django.db import models

from accounts.models import User
from catalog.models import Product
from inventory.models import Stock
from picking.models import OrderLine, PickingLine


class ReportType(models.TextChoices):
    ABC_XYZ = "ABC_XYZ", "ABC-XYZ анализ"
    DEAD_STOCK = "DEAD_STOCK", "Мёртвые остатки"
    ANALOGS_VS_ORIGINALS = "ANALOGS_VS_ORIGINALS", "Анализ аналогов vs оригиналов"
    PICKING_ERRORS = "PICKING_ERRORS", "Ошибки подбора"
    DEMAND_FORECAST = "DEMAND_FORECAST", "Прогноз спроса"


class ABCXYZAnalysis(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="abcxyz_analyses",
        verbose_name="Товар",
    )
    period_start = models.DateField("Начало периода")
    period_end = models.DateField("Конец периода")

    total_sales_qty = models.DecimalField("Объём продаж, шт", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_sales_amount = models.DecimalField("Сумма продаж, ₽", max_digits=12, decimal_places=2, default=Decimal("0.00"))

    abc_class = models.CharField("ABC класс", max_length=1, blank=True, help_text="A, B, C")
    xyz_class = models.CharField("XYZ класс", max_length=1, blank=True, help_text="X, Y, Z")

    coefficient_variation = models.DecimalField(
        "Коэффициент вариации",
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "ABC-XYZ анализ"
        verbose_name_plural = "ABC-XYZ анализы"
        indexes = [
            models.Index(fields=["period_start", "period_end"], name="idx_abcxyz_period"),
            models.Index(fields=["abc_class", "xyz_class"], name="idx_abcxyz_class"),
        ]


class DeadStockReport(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="dead_stock_reports",
        verbose_name="Товар",
    )
    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name="dead_stock_reports",
        verbose_name="Остаток",
        null=True,
        blank=True,
    )

    qty_available = models.DecimalField("Количество, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    days_without_movement = models.IntegerField("Дней без движения", default=0)
    last_movement_date = models.DateField("Последнее движение", null=True, blank=True)
    estimated_value = models.DecimalField("Оценочная стоимость, ₽", max_digits=12, decimal_places=2, null=True, blank=True)

    calculated_at = models.DateTimeField("Рассчитано", auto_now_add=True)

    class Meta:
        verbose_name = "Мёртвый остаток"
        verbose_name_plural = "Мёртвые остатки"
        indexes = [
            models.Index(fields=["days_without_movement"], name="idx_dead_stock_days"),
            models.Index(fields=["calculated_at"], name="idx_dead_stock_calculated"),
        ]


class PickingError(models.Model):
    order_line = models.ForeignKey(
        OrderLine,
        on_delete=models.CASCADE,
        related_name="picking_errors",
        verbose_name="Строка заказа",
    )
    picking_line = models.ForeignKey(
        PickingLine,
        on_delete=models.SET_NULL,
        related_name="errors",
        verbose_name="Строка подбора",
        null=True,
        blank=True,
    )

    error_type = models.CharField(
        "Тип ошибки",
        max_length=32,
        choices=[
            ("WRONG_PRODUCT", "Неверный товар"),
            ("WRONG_QTY", "Неверное количество"),
            ("WRONG_LOCATION", "Неверное место"),
            ("DAMAGED", "Повреждённый товар"),
            ("MISSING", "Товар отсутствует"),
        ],
    )

    expected_product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="picking_errors_expected",
        verbose_name="Ожидаемый товар",
    )
    actual_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        related_name="picking_errors_actual",
        verbose_name="Фактический товар",
        null=True,
        blank=True,
    )

    expected_qty = models.DecimalField("Ожидаемое количество", max_digits=10, decimal_places=2)
    actual_qty = models.DecimalField("Фактическое количество", max_digits=10, decimal_places=2, null=True, blank=True)

    detected_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="detected_picking_errors",
        verbose_name="Обнаружил",
    )
    detected_at = models.DateTimeField("Обнаружено", auto_now_add=True)

    resolved = models.BooleanField("Исправлено", default=False)
    resolved_at = models.DateTimeField("Исправлено", null=True, blank=True)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="resolved_picking_errors",
        verbose_name="Исправил",
        null=True,
        blank=True,
    )

    notes = models.TextField("Примечания", blank=True)

    class Meta:
        verbose_name = "Ошибка подбора"
        verbose_name_plural = "Ошибки подбора"
        indexes = [
            models.Index(fields=["error_type"], name="idx_picking_error_type"),
            models.Index(fields=["detected_at"], name="idx_picking_error_detected"),
            models.Index(fields=["resolved"], name="idx_picking_error_resolved"),
        ]


class AnalogVsOriginalReport(models.Model):
    period_start = models.DateField("Начало периода")
    period_end = models.DateField("Конец периода")

    original_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="analog_reports_as_original",
        verbose_name="Оригинальный товар",
    )
    analog_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="analog_reports_as_analog",
        verbose_name="Аналог",
    )

    original_sales_qty = models.DecimalField("Продажи оригинала, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    analog_sales_qty = models.DecimalField("Продажи аналога, шт", max_digits=10, decimal_places=2, default=Decimal("0.00"))

    original_sales_amount = models.DecimalField("Сумма продаж оригинала, ₽", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    analog_sales_amount = models.DecimalField("Сумма продаж аналога, ₽", max_digits=12, decimal_places=2, default=Decimal("0.00"))

    substitution_rate = models.DecimalField(
        "Коэффициент замещения",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Процент замен оригиналов на аналоги",
    )

    calculated_at = models.DateTimeField("Рассчитано", auto_now_add=True)

    class Meta:
        verbose_name = "Отчёт аналоги vs оригиналы"
        verbose_name_plural = "Отчёты аналоги vs оригиналы"
        constraints = [
            models.UniqueConstraint(
                fields=["period_start", "period_end", "original_product", "analog_product"],
                name="uniq_analog_report_period_products",
            ),
        ]


class DemandForecast(models.Model):
    """
    Прогноз спроса на товар с учётом сезонности.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="demand_forecasts",
        verbose_name="Товар",
    )
    forecast_date = models.DateField("Дата прогноза")
    period_start = models.DateField("Начало периода прогноза")
    period_end = models.DateField("Конец периода прогноза")

    forecasted_qty = models.DecimalField(
        "Прогнозируемое количество, шт",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    confidence_level = models.DecimalField(
        "Уровень уверенности",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="От 0 до 100, процент уверенности в прогнозе",
    )

    # Факторы прогноза
    seasonal_factor = models.DecimalField(
        "Сезонный коэффициент",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Коэффициент сезонности (1.0 = норма, >1.0 = сезон, <1.0 = несезон)",
    )
    trend_factor = models.DecimalField(
        "Тренд",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Тренд продаж (положительный/отрицательный)",
    )

    # Исторические данные для расчёта
    historical_sales_qty = models.DecimalField(
        "Исторические продажи, шт",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    historical_period_start = models.DateField("Начало исторического периода", null=True, blank=True)
    historical_period_end = models.DateField("Конец исторического периода", null=True, blank=True)

    calculated_at = models.DateTimeField("Рассчитано", auto_now_add=True)
    calculated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="calculated_forecasts",
        verbose_name="Рассчитал",
        null=True,
        blank=True,
    )

    notes = models.TextField("Примечания", blank=True)

    class Meta:
        verbose_name = "Прогноз спроса"
        verbose_name_plural = "Прогнозы спроса"
        ordering = ["-forecast_date", "product"]
        indexes = [
            models.Index(fields=["product", "forecast_date"], name="idx_forecast_product_date"),
            models.Index(fields=["period_start", "period_end"], name="idx_forecast_period"),
        ]

    def __str__(self) -> str:
        return f"Прогноз для {self.product.internal_sku} на {self.period_start} - {self.period_end}"
