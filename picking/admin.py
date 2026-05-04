from django.contrib import admin
from django.utils.html import format_html

from .models import Order, OrderLine, OrderStatus, PickingLine, PickingTask, PickingTaskStatus


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "customer_name",
        "status",
        "priority",
        "shipping_due_at",
        "source",
        "confirmed_at",
        "picked_at",
        "shipped_at",
        "created_by",
        "created_at",
    ]
    list_filter = ["status", "priority", "source", "created_at", "shipping_due_at", "confirmed_at", "picked_at", "shipped_at"]
    search_fields = ["number", "customer_name", "customer_phone", "customer_email", "external_id"]
    readonly_fields = ["created_at", "updated_at", "status_display"]
    autocomplete_fields = ["created_by", "picked_by"]
    date_hierarchy = "created_at"
    fieldsets = (
        ("Основная информация", {"fields": ("number", "status", "status_display", "priority", "shipping_due_at", "source", "external_id")}),
        ("Клиент", {"fields": ("customer_name", "customer_phone", "customer_email", "note")}),
        ("Временные метки", {"fields": ("confirmed_at", "picked_at", "shipped_at")}),
        ("Выдача", {"fields": ("reserved_at_window", "window_number")}),
        ("Исполнители", {"fields": ("created_by", "picked_by")}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def status_display(self, obj):
        colors = {
            OrderStatus.DRAFT: "gray",
            OrderStatus.CONFIRMED: "blue",
            OrderStatus.IN_PICKING: "orange",
            OrderStatus.PICKED: "green",
            OrderStatus.RESERVED: "purple",
            OrderStatus.SHIPPED: "darkgreen",
            OrderStatus.CANCELLED: "red",
        }
        color = colors.get(obj.status, "black")
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())
    status_display.short_description = "Статус (визуально)"


@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ["order", "product", "qty_ordered", "qty_picked", "price", "completion_display"]
    list_filter = ["order__status", "order"]
    search_fields = ["order__number", "product__internal_sku", "product__name"]
    readonly_fields = ["completion_display"]
    autocomplete_fields = ["order", "product"]

    def completion_display(self, obj):
        if obj.qty_ordered > 0:
            percent = (obj.qty_picked / obj.qty_ordered) * 100
            color = "green" if percent == 100 else "orange" if percent > 0 else "red"
            return format_html('<span style="color: {};">{:.1f}%</span>', color, percent)
        return "—"
    completion_display.short_description = "Выполнено"


@admin.register(PickingTask)
class PickingTaskAdmin(admin.ModelAdmin):
    list_display = ["order", "zone_type_code", "status", "priority", "due_date", "assigned_to", "started_at", "completed_at", "created_at"]
    list_filter = ["status", "priority", "zone_type_code", "due_date", "created_at", "started_at", "completed_at"]
    search_fields = ["order__number", "assigned_to__username"]
    readonly_fields = ["created_at", "updated_at", "status_display"]
    autocomplete_fields = ["order", "assigned_to"]
    date_hierarchy = "created_at"
    fieldsets = (
        ("Основная информация", {"fields": ("order", "zone_type_code", "status", "status_display", "priority", "due_date")}),
        ("Исполнитель", {"fields": ("assigned_to",)}),
        ("Временные метки", {"fields": ("started_at", "completed_at")}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def status_display(self, obj):
        colors = {
            PickingTaskStatus.PENDING: "gray",
            PickingTaskStatus.IN_PROGRESS: "blue",
            PickingTaskStatus.COMPLETED: "green",
            PickingTaskStatus.CANCELLED: "red",
        }
        color = colors.get(obj.status, "black")
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())
    status_display.short_description = "Статус (визуально)"


@admin.register(PickingLine)
class PickingLineAdmin(admin.ModelAdmin):
    list_display = ["task", "order_line", "stock", "qty_picked", "scanned_oem"]
    list_filter = ["task", "task__status"]
    search_fields = ["task__order__number", "order_line__product__internal_sku", "scanned_oem"]
    autocomplete_fields = ["task", "order_line", "stock"]
