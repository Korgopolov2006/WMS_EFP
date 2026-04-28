import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from catalog.models import Warehouse, WarehouseAccess
from .models import StorageObject, WarehouseLayout


@login_required
def warehouse_3d_index(request):
    """
    Лендинг 3D-склада: выбор склада из доступных.
    Если у пользователя один склад — редирект сразу на него.
    """
    warehouses = list(request.user.get_accessible_warehouses().select_related("branch"))
    if not warehouses:
        messages.warning(request, "У вас нет доступа ни к одному складу.")
        return redirect("dashboard")
    if len(warehouses) == 1:
        return redirect("warehouse_3d:view", warehouse_id=warehouses[0].id)
    return render(request, "warehouse_3d/index.html", {"warehouses": warehouses})


@login_required
def warehouse_3d_view(request, warehouse_id):
    """
    Отображение 3D-склада.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)

    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    access_level = request.user.get_warehouse_access_level(warehouse)
    can_edit = access_level in (
        WarehouseAccess.AccessLevel.EDIT,
        WarehouseAccess.AccessLevel.ADMIN,
    ) or request.user.is_admin()

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    storage_objects = StorageObject.objects.filter(warehouse=warehouse, is_active=True).select_related('storage_location')

    # Получаем информацию о товарах на объектах
    from inventory.models import Stock
    stocks_by_location = {}
    if storage_objects.exists():
        location_ids = [obj.storage_location_id for obj in storage_objects if obj.storage_location_id]
        if location_ids:
            stocks = Stock.objects.filter(
                storage_location_id__in=location_ids,
                qty_available__gt=0
            ).select_related('product', 'storage_location')

            for stock in stocks:
                loc_id = stock.storage_location_id
                if loc_id not in stocks_by_location:
                    stocks_by_location[loc_id] = []
                stocks_by_location[loc_id].append({
                    'product_sku': stock.product.internal_sku,
                    'product_name': stock.product.name,
                    'qty': float(stock.qty_available),
                })

    # Преобразуем в JSON для шаблона
    stocks_json = json.dumps(stocks_by_location)

    # Сериализуем storage_objects в JSON для безопасной передачи в шаблон
    storage_objects_json = []
    for obj in storage_objects:
        storage_objects_json.append({
            'id': obj.id,
            'type': obj.object_type,
            'code': obj.code or '',
            'name': obj.name or '',
            'position': {
                'x': float(obj.position_x or 0),
                'y': float(obj.position_y or 0),
                'z': float(obj.position_z or 0)
            },
            'size': {
                'width': float(obj.width or 1),
                'depth': float(obj.depth or 1),
                'height': float(obj.height or 1)
            },
            'rotation': float(obj.rotation_y or 0),
            'storageLocationId': obj.storage_location_id if obj.storage_location_id else None
        })
    storage_objects_json_str = json.dumps(storage_objects_json)

    context = {
        "warehouse": warehouse,
        "layout": layout,
        "storage_objects": storage_objects,
        "storage_objects_json": storage_objects_json_str,
        "can_edit": can_edit,
        "access_level": access_level,
        "stocks_by_location": stocks_by_location,
        "stocks_json": stocks_json,
    }

    return render(request, "warehouse_3d/view.html", context)


@login_required
@require_http_methods(["POST"])
def save_layout(request, warehouse_id):
    """
    Сохранение геометрии склада (контур пола).
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)

    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    access_level = request.user.get_warehouse_access_level(warehouse)
    can_edit = access_level in (
        WarehouseAccess.AccessLevel.EDIT,
        WarehouseAccess.AccessLevel.ADMIN,
    ) or request.user.is_admin()

    if not can_edit:
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    import json

    data = json.loads(request.body)
    floor_points = data.get("floor_points", [])

    # Allow clearing layout (empty array)
    if floor_points and len(floor_points) < 3:
        return JsonResponse({"error": "Недостаточно точек для создания контура"}, status=400)

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    layout.floor_points = floor_points
    layout.is_layout_defined = len(floor_points) >= 3
    layout.save()

    if layout.is_layout_defined:
        return JsonResponse({"success": True, "message": "Геометрия склада сохранена"})
    else:
        return JsonResponse({"success": True, "message": "Разметка склада очищена"})


@login_required
@require_http_methods(["POST"])
def save_storage_object(request, warehouse_id):
    """
    Сохранение или обновление объекта хранения.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)

    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    access_level = request.user.get_warehouse_access_level(warehouse)
    can_edit = access_level in (
        WarehouseAccess.AccessLevel.EDIT,
        WarehouseAccess.AccessLevel.ADMIN,
    ) or request.user.is_admin()

    if not can_edit:
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    import json

    data = json.loads(request.body)
    obj_id = data.get("id")

    if obj_id:
        storage_obj = get_object_or_404(StorageObject, id=obj_id, warehouse=warehouse)
    else:
        storage_obj = StorageObject(warehouse=warehouse)

    storage_obj.object_type = data.get("object_type")
    storage_obj.code = data.get("code", "")
    storage_obj.name = data.get("name", "")
    storage_obj.position_x = float(data.get("position_x", 0))
    storage_obj.position_z = float(data.get("position_z", 0))
    storage_obj.position_y = float(data.get("position_y", 0))
    storage_obj.width = float(data.get("width", 1))
    storage_obj.depth = float(data.get("depth", 1))
    storage_obj.height = float(data.get("height", 1))
    storage_obj.rotation_y = float(data.get("rotation_y", 0))
    storage_obj.save()

    return JsonResponse(
        {
            "success": True,
            "id": storage_obj.id,
            "message": "Объект сохранён",
        }
    )


@login_required
@require_http_methods(["POST"])
def delete_storage_object(request, warehouse_id, object_id):
    """
    Удаление объекта хранения с проверкой наличия товаров.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)

    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    access_level = request.user.get_warehouse_access_level(warehouse)
    can_edit = access_level in (
        WarehouseAccess.AccessLevel.EDIT,
        WarehouseAccess.AccessLevel.ADMIN,
    ) or request.user.is_admin()

    if not can_edit:
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    storage_obj = get_object_or_404(StorageObject, id=object_id, warehouse=warehouse)

    # Проверка наличия товаров
    if storage_obj.has_stock():
        stock_count = storage_obj.get_stock_count()
        total_qty = storage_obj.get_total_stock_qty()
        return JsonResponse({
            "success": False,
            "error": f"Невозможно удалить объект: на нём находятся товары ({stock_count} позиций, всего {total_qty} шт.)",
            "has_stock": True,
            "stock_count": stock_count,
            "total_qty": float(total_qty)
        }, status=400)

    storage_obj.is_active = False
    storage_obj.save()

    return JsonResponse({"success": True, "message": "Объект удалён"})
