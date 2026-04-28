from django.contrib import admin

from .models import ABCXYZAnalysis, AnalogVsOriginalReport, DeadStockReport, DemandForecast, PickingError


@admin.register(ABCXYZAnalysis)
class ABCXYZAnalysisAdmin(admin.ModelAdmin):
    list_display = ["product", "period_start", "period_end", "abc_class", "xyz_class", "total_sales_qty", "total_sales_amount"]
    list_filter = ["abc_class", "xyz_class", "period_start", "period_end"]
    search_fields = ["product__internal_sku", "product__name"]
    autocomplete_fields = ["product"]
    date_hierarchy = "period_start"


@admin.register(DeadStockReport)
class DeadStockReportAdmin(admin.ModelAdmin):
    list_display = ["product", "qty_available", "days_without_movement", "last_movement_date", "estimated_value", "calculated_at"]
    list_filter = ["days_without_movement", "calculated_at"]
    search_fields = ["product__internal_sku", "product__name"]
    readonly_fields = ["calculated_at"]
    autocomplete_fields = ["product", "stock"]
    date_hierarchy = "calculated_at"


@admin.register(PickingError)
class PickingErrorAdmin(admin.ModelAdmin):
    list_display = [
        "order_line",
        "error_type",
        "expected_product",
        "actual_product",
        "expected_qty",
        "actual_qty",
        "resolved",
        "detected_at",
    ]
    list_filter = ["error_type", "resolved", "detected_at"]
    search_fields = [
        "order_line__order__number",
        "expected_product__internal_sku",
        "actual_product__internal_sku",
        "notes",
    ]
    readonly_fields = ["detected_at"]
    autocomplete_fields = ["order_line", "picking_line", "expected_product", "actual_product", "detected_by", "resolved_by"]
    date_hierarchy = "detected_at"
    fieldsets = (
        ("Основная информация", {"fields": ("order_line", "picking_line", "error_type")}),
        ("Детали ошибки", {"fields": ("expected_product", "actual_product", "expected_qty", "actual_qty")}),
        ("Обнаружение", {"fields": ("detected_by", "detected_at")}),
        ("Исправление", {"fields": ("resolved", "resolved_at", "resolved_by")}),
        ("Примечания", {"fields": ("notes",)}),
    )


@admin.register(AnalogVsOriginalReport)
class AnalogVsOriginalReportAdmin(admin.ModelAdmin):
    list_display = [
        "original_product",
        "analog_product",
        "period_start",
        "period_end",
        "original_sales_qty",
        "analog_sales_qty",
        "substitution_rate",
        "calculated_at",
    ]
    list_filter = ["period_start", "period_end", "calculated_at"]
    search_fields = ["original_product__internal_sku", "analog_product__internal_sku"]
    readonly_fields = ["calculated_at"]
    autocomplete_fields = ["original_product", "analog_product"]
    date_hierarchy = "period_start"


@admin.register(DemandForecast)
class DemandForecastAdmin(admin.ModelAdmin):
    list_display = [
        "product",
        "forecast_date",
        "period_start",
        "period_end",
        "forecasted_qty",
        "confidence_level",
        "seasonal_factor",
        "calculated_at",
    ]
    list_filter = ["forecast_date", "calculated_at"]
    search_fields = ["product__internal_sku", "product__name", "notes"]
    readonly_fields = ["calculated_at"]
    autocomplete_fields = ["product", "calculated_by"]
    date_hierarchy = "forecast_date"
    fieldsets = (
        ("Основная информация", {"fields": ("product", "forecast_date", "period_start", "period_end")}),
        ("Прогноз", {"fields": ("forecasted_qty", "confidence_level")}),
        ("Факторы", {"fields": ("seasonal_factor", "trend_factor")}),
        ("Исторические данные", {"fields": ("historical_sales_qty", "historical_period_start", "historical_period_end")}),
        ("Дополнительно", {"fields": ("calculated_by", "notes")}),
        ("Системные", {"fields": ("calculated_at",), "classes": ("collapse",)}),
    )
