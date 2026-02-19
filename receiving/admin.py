from django.contrib import admin
from django.utils.html import format_html

from .models import Receiving, ReceivingLine, ReceivingSerial, ReceivingStatus


@admin.register(Receiving)
class ReceivingAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "supplier_name",
        "status",
        "expected_at",
        "completed_at",
        "created_by",
        "created_at",
    ]
    list_filter = ["status", "created_at", "expected_at", "completed_at"]
    search_fields = ["number", "supplier_name", "supplier_doc_no", "created_by__username"]
    readonly_fields = ["created_at", "updated_at", "status_display"]
    autocomplete_fields = ["created_by"]
    date_hierarchy = "created_at"
    fieldsets = (
        ("Основная информация", {"fields": ("number", "status", "status_display")}),
        ("Поставщик", {"fields": ("supplier_name", "supplier_doc_no")}),
        ("Временные метки", {"fields": ("expected_at", "completed_at")}),
        ("Создатель", {"fields": ("created_by",)}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def status_display(self, obj):
        colors = {
            ReceivingStatus.DRAFT: "gray",
            ReceivingStatus.IN_PROGRESS: "blue",
            ReceivingStatus.COMPLETED: "green",
            ReceivingStatus.CANCELLED: "red",
        }
        color = colors.get(obj.status, "black")
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())
    status_display.short_description = "Статус (визуально)"


@admin.register(ReceivingLine)
class ReceivingLineAdmin(admin.ModelAdmin):
    list_display = ["receiving", "product", "qty_expected", "qty_received", "completion_display", "storage_location"]
    list_filter = ["receiving", "receiving__status", "has_serial_numbers"]
    search_fields = ["receiving__number", "product__internal_sku", "product__name", "supplier_sku"]
    readonly_fields = ["completion_display"]
    autocomplete_fields = ["receiving", "product", "storage_location"]

    def completion_display(self, obj):
        if obj.qty_expected > 0:
            percent = (obj.qty_received / obj.qty_expected) * 100
            color = "green" if percent == 100 else "orange" if percent > 0 else "red"
            return format_html('<span style="color: {};">{:.1f}%</span>', color, percent)
        return "—"
    completion_display.short_description = "Выполнено"


@admin.register(ReceivingSerial)
class ReceivingSerialAdmin(admin.ModelAdmin):
    list_display = ["line", "serial_number"]
    list_filter = ["line__receiving"]
    search_fields = ["serial_number", "line__receiving__number", "line__product__internal_sku"]
    autocomplete_fields = ["line"]
