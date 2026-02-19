from django.contrib import admin

from .models import StorageObject, WarehouseLayout


@admin.register(WarehouseLayout)
class WarehouseLayoutAdmin(admin.ModelAdmin):
    list_display = ["warehouse", "is_layout_defined", "created_at", "updated_at"]
    list_filter = ["is_layout_defined", "created_at"]
    search_fields = ["warehouse__code", "warehouse__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(StorageObject)
class StorageObjectAdmin(admin.ModelAdmin):
    list_display = [
        "warehouse",
        "object_type",
        "code",
        "name",
        "position_x",
        "position_z",
        "has_stock_display",
        "is_active",
    ]
    list_filter = ["object_type", "is_active", "warehouse"]
    search_fields = ["code", "name", "warehouse__code"]
    readonly_fields = ["created_at", "updated_at", "has_stock_display"]
    
    def has_stock_display(self, obj):
        if obj.has_stock():
            count = obj.get_stock_count()
            qty = obj.get_total_stock_qty()
            return format_html(
                '<span style="color: orange;">⚠ Есть товар ({count} видов, {qty:.0f} шт)</span>',
                count=count,
                qty=qty
            )
        return format_html('<span style="color: green;">✓ Свободно</span>')
    has_stock_display.short_description = "Статус"
    
    def delete_model(self, request, obj):
        """Запрещает удаление объекта, если в нём есть товар."""
        if obj.has_stock():
            from django.contrib import messages
            messages.error(
                request, 
                f"Нельзя удалить объект {obj.code or obj.id}: в нём есть товар"
            )
            return
        super().delete_model(request, obj)
    
    def delete_queryset(self, request, queryset):
        """Запрещает массовое удаление объектов с товаром."""
        from django.contrib import messages
        
        objects_with_stock = []
        for obj in queryset:
            if obj.has_stock():
                objects_with_stock.append(str(obj.code or obj.id))
        
        if objects_with_stock:
            messages.error(
                request,
                f"Нельзя удалить объекты с товаром: {', '.join(objects_with_stock)}"
            )
            queryset = queryset.exclude(id__in=[obj.id for obj in queryset if obj.has_stock()])
        
        super().delete_queryset(request, queryset)
