from django.contrib import admin
from django.db import models
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    Branch,
    Brand,
    Category,
    Product,
    ProductApplicability,
    ProductChangeLog,
    ProductCrossReference,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Tool,
    VehicleMake,
    VehicleModel,
    Warehouse,
    WarehouseAccess,
    Backorder,
)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["code", "name", "address"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Основная информация", {"fields": ("code", "name", "address", "is_active")}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "branch", "width_m", "length_m", "height_m", "is_active"]
    list_filter = ["is_active", "branch", "created_at"]
    search_fields = ["code", "name", "branch__code", "branch__name"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Основная информация", {"fields": ("branch", "code", "name", "is_active")}),
        ("Размеры", {"fields": ("width_m", "length_m", "height_m")}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(WarehouseAccess)
class WarehouseAccessAdmin(admin.ModelAdmin):
    list_display = ["user", "warehouse", "access_level", "created_at"]
    list_filter = ["access_level", "created_at"]
    search_fields = ["user__username", "warehouse__code", "warehouse__name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["user", "warehouse"]


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "created_at"]
    list_filter = ["parent", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["parent"]


@admin.register(VehicleMake)
class VehicleMakeAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(VehicleModel)
class VehicleModelAdmin(admin.ModelAdmin):
    list_display = ["name", "make", "created_at"]
    list_filter = ["make", "created_at"]
    search_fields = ["name", "make__name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["make"]


@admin.register(StorageZoneType)
class StorageZoneTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "sort_order"]
    list_filter = ["sort_order"]
    search_fields = ["code", "name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(StorageZone)
class StorageZoneAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "warehouse", "zone_type", "created_at"]
    list_filter = ["zone_type", "warehouse", "created_at"]
    search_fields = ["code", "name", "warehouse__code"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["warehouse", "zone_type"]


@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "zone", "aisle", "rack", "shelf", "level", "max_weight_kg", "has_stock_display"]
    list_filter = ["zone", "zone__zone_type", "created_at"]
    search_fields = ["code", "name", "zone__code", "aisle", "rack", "shelf"]
    readonly_fields = ["created_at", "updated_at", "has_stock_display"]
    autocomplete_fields = ["zone"]
    fieldsets = (
        ("Основная информация", {"fields": ("zone", "code", "name")}),
        ("Адрес", {"fields": ("aisle", "rack", "shelf", "level")}),
        ("Характеристики", {"fields": ("max_weight_kg", "has_stock_display")}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def has_stock_display(self, obj):
        from inventory.models import Stock
        has_stock = Stock.objects.filter(storage_location=obj, qty_available__gt=0).exists()
        if has_stock:
            qty = Stock.objects.filter(storage_location=obj).aggregate(
                total=models.Sum('qty_available')
            )['total'] or 0
            # format_html передаёт args через conditional_escape (Decimal → SafeString),
            # из-за чего {:.0f} ломается. Форматируем qty ДО передачи в шаблон.
            return format_html(
                '<span style="color: orange;">⚠ Есть товар ({} шт)</span>',
                f"{qty:.0f}",
            )
        # Static markup — используем mark_safe (format_html без args deprecated в Django 6.0)
        return mark_safe('<span style="color: green;">✓ Свободно</span>')
    has_stock_display.short_description = "Статус"

    def delete_model(self, request, obj):
        """Запрещает удаление места хранения, если в нём есть товар."""
        from inventory.models import Stock
        if Stock.objects.filter(storage_location=obj, qty_available__gt=0).exists():
            from django.contrib import messages
            messages.error(request, f"Нельзя удалить место хранения {obj.code}: в нём есть товар")
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Запрещает массовое удаление мест с товаром."""
        from inventory.models import Stock
        from django.contrib import messages

        locations_with_stock = []
        for loc in queryset:
            if Stock.objects.filter(storage_location=loc, qty_available__gt=0).exists():
                locations_with_stock.append(loc.code)

        if locations_with_stock:
            messages.error(
                request,
                f"Нельзя удалить места хранения с товаром: {', '.join(locations_with_stock)}"
            )
            queryset = queryset.exclude(code__in=locations_with_stock)

        super().delete_queryset(request, queryset)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["internal_sku", "name", "oem_number", "brand", "category", "packaging_type", "created_at"]
    list_filter = ["brand", "category", "packaging_type", "created_at"]
    search_fields = ["internal_sku", "name", "oem_number", "analog_number"]
    readonly_fields = ["created_at", "updated_at", "photo_preview", "oem_number_normalized", "analog_number_normalized"]
    fieldsets = (
        ("Основная информация", {"fields": ("internal_sku", "name", "brand", "category")}),
        ("Номера", {"fields": ("oem_number", "analog_number", "oem_number_normalized", "analog_number_normalized")}),
        ("Характеристики", {"fields": ("weight_kg", "length_cm", "width_cm", "height_cm", "packaging_type")}),
        ("Фото", {"fields": ("photo", "photo_preview")}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def photo_preview(self, obj):
        if obj.photo:
            return format_html('<img src="{}" style="max-height: 200px;" />', obj.photo.url)
        return "—"
    photo_preview.short_description = "Превью фото"


@admin.register(ProductApplicability)
class ProductApplicabilityAdmin(admin.ModelAdmin):
    list_display = ["product", "vehicle_model", "created_at"]
    list_filter = ["created_at", "vehicle_model__make"]
    search_fields = ["product__internal_sku", "product__name", "vehicle_model__name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["product", "vehicle_model"]


@admin.register(ProductCrossReference)
class ProductCrossReferenceAdmin(admin.ModelAdmin):
    list_display = ["from_product", "to_product", "relation_type", "created_at"]
    list_filter = ["relation_type", "created_at"]
    search_fields = ["from_product__internal_sku", "to_product__internal_sku", "note"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["from_product", "to_product"]


@admin.register(ProductChangeLog)
class ProductChangeLogAdmin(admin.ModelAdmin):
    list_display = ["product", "action", "changed_by", "source", "created_at"]
    list_filter = ["action", "source", "created_at"]
    search_fields = ["product__internal_sku", "product__name", "changed_by__username", "note"]
    readonly_fields = ["product", "changed_by", "action", "source", "changed_fields", "note", "created_at", "updated_at"]


@admin.register(Backorder)
class BackorderAdmin(admin.ModelAdmin):
    list_display = ["order", "product", "qty_ordered", "qty_fulfilled", "status", "expected_arrival_date", "created_at"]
    list_filter = ["status", "expected_arrival_date", "created_at"]
    search_fields = ["order__number", "product__internal_sku", "product__name"]
    readonly_fields = ["created_at", "updated_at", "qty_remaining_display"]
    autocomplete_fields = ["order", "product", "created_by"]
    fieldsets = (
        ("Основная информация", {"fields": ("order", "product", "created_by")}),
        ("Количество", {"fields": ("qty_ordered", "qty_fulfilled", "qty_remaining_display")}),
        ("Статус", {"fields": ("status", "expected_arrival_date", "fulfilled_at")}),
        ("Примечания", {"fields": ("notes",)}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def qty_remaining_display(self, obj):
        return f"{obj.qty_remaining} шт"
    qty_remaining_display.short_description = "Осталось выполнить"


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "tool_type", "warehouse", "is_available", "current_user", "is_active"]
    list_filter = ["tool_type", "is_available", "is_active", "warehouse", "created_at"]
    search_fields = ["code", "name", "brand", "model"]
    readonly_fields = ["created_at", "updated_at", "is_in_use_display"]
    autocomplete_fields = ["warehouse", "current_user"]
    fieldsets = (
        ("Основная информация", {"fields": ("warehouse", "tool_type", "code", "name", "brand", "model")}),
        ("Статус", {"fields": ("is_available", "is_active", "is_in_use_display")}),
        ("Использование", {"fields": ("current_user", "checked_out_at", "expected_return_at")}),
        ("Техническое обслуживание", {"fields": ("last_maintenance_date", "next_maintenance_date", "maintenance_notes")}),
        ("Примечания", {"fields": ("notes",)}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def is_in_use_display(self, obj):
        # Static markup — mark_safe вместо format_html без args (deprecated в Django 6.0)
        if obj.is_in_use():
            return mark_safe('<span style="color: orange;">В использовании</span>')
        return mark_safe('<span style="color: green;">Свободен</span>')
    is_in_use_display.short_description = "Статус использования"
