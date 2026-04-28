from django.contrib import admin
from django.utils.html import format_html

from .models import Inventory, InventoryLine, InventoryStatus, Stock, StockMovement


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ["product", "storage_location", "qty_available", "qty_reserved", "qty_total_display", "batch_no", "expiry_date"]
    list_filter = ["expiry_date", "storage_location__zone"]
    search_fields = ["product__internal_sku", "product__name", "storage_location__code", "batch_no"]
    readonly_fields = ["qty_total_display"]
    autocomplete_fields = ["product", "storage_location"]
    fieldsets = (
        ("Основная информация", {"fields": ("product", "storage_location", "batch_no")}),
        ("Количество", {"fields": ("qty_available", "qty_reserved", "qty_total_display")}),
        ("Срок годности", {"fields": ("expiry_date",)}),
    )

    def qty_total_display(self, obj):
        return f"{obj.qty_total} шт"
    qty_total_display.short_description = "Всего"


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ["number", "zone", "status", "started_at", "completed_at", "created_by", "created_at"]
    list_filter = ["status", "zone", "created_at", "started_at", "completed_at"]
    search_fields = ["number", "zone__code", "zone__name", "created_by__username"]
    readonly_fields = ["created_at", "updated_at", "status_display"]
    autocomplete_fields = ["zone", "created_by"]
    date_hierarchy = "created_at"
    fieldsets = (
        ("Основная информация", {"fields": ("number", "zone", "status", "status_display")}),
        ("Временные метки", {"fields": ("started_at", "completed_at")}),
        ("Создатель", {"fields": ("created_by",)}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def status_display(self, obj):
        colors = {
            InventoryStatus.DRAFT: "gray",
            InventoryStatus.IN_PROGRESS: "blue",
            InventoryStatus.COMPLETED: "green",
            InventoryStatus.CANCELLED: "red",
        }
        color = colors.get(obj.status, "black")
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())
    status_display.short_description = "Статус (визуально)"


@admin.register(InventoryLine)
class InventoryLineAdmin(admin.ModelAdmin):
    list_display = ["inventory", "product", "storage_location", "qty_book", "qty_actual", "discrepancy"]
    list_filter = ["inventory", "inventory__status"]
    search_fields = ["inventory__number", "product__internal_sku", "storage_location__code"]
    autocomplete_fields = ["inventory", "product", "storage_location"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        "created_at", "movement_type", "status", "product",
        "quantity", "from_location", "to_location", "user",
    ]
    list_filter = ["movement_type", "status", "created_at"]
    search_fields = [
        "product__internal_sku", "product__name", "product__oem_number",
        "reason", "comment", "ref_id",
    ]
    autocomplete_fields = ["product", "from_location", "to_location", "user"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at"]
