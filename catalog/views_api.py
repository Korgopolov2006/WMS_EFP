from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from accounts.constants import Roles
from accounts.permissions import role_required
from catalog.models import Branch, StorageLocation, StorageZone, Warehouse, WarehouseAccess


@require_http_methods(["GET"])
def warehouses_list(request: HttpRequest) -> JsonResponse:
    """Список доступных складов для текущего пользователя."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    accessible_warehouses = request.user.get_accessible_warehouses()

    warehouses_data = []
    for wh in accessible_warehouses:
        access_level = request.user.get_warehouse_access_level(wh)
        warehouses_data.append(
            {
                "id": wh.id,
                "code": wh.code,
                "name": wh.name,
                "branch": {
                    "id": wh.branch.id,
                    "code": wh.branch.code,
                    "name": wh.branch.name,
                },
                "access_level": access_level,
                "width_m": float(wh.width_m),
                "length_m": float(wh.length_m),
                "height_m": float(wh.height_m),
            }
        )

    return JsonResponse({"warehouses": warehouses_data})


@require_http_methods(["GET"])
def warehouse_data_json(request: HttpRequest, warehouse_id: int) -> JsonResponse:
    """Данные склада для 3D-визуализации."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        warehouse = Warehouse.objects.select_related("branch").get(pk=warehouse_id, is_active=True)
    except Warehouse.DoesNotExist:
        return JsonResponse({"error": "Warehouse not found"}, status=404)

    if not request.user.can_access_warehouse(warehouse):
        return JsonResponse({"error": "Access denied"}, status=403)

    zones = StorageZone.objects.filter(warehouse=warehouse).select_related("zone_type").prefetch_related("locations")

    warehouse_objects = []
    for zone in zones:
        zone_type_code = zone.zone_type.code if zone.zone_type else "UNKNOWN"
        for loc in zone.locations.all():
            try:
                aisle_val = float(loc.aisle) if loc.aisle else 0
                rack_val = float(loc.rack) if loc.rack else 0
                shelf_val = float(loc.shelf) if loc.shelf else 0
            except (ValueError, TypeError):
                aisle_val = rack_val = shelf_val = 0

            x = aisle_val * 2.0
            y = rack_val * 1.5
            z = shelf_val * 0.5

            width = 1.0
            depth = 1.0
            height = 0.5

            if zone_type_code == "CELL":
                width, depth, height = 0.8, 0.8, 0.4
            elif zone_type_code == "SHELF":
                width, depth, height = 1.2, 0.6, 0.3
            elif zone_type_code == "FLOOR":
                width, depth, height = 2.0, 1.5, 0.2

            color_map = {
                "CELL": "#60a5fa",
                "SHELF": "#34d399",
                "FLOOR": "#fbbf24",
                "RECEIVING": "#f87171",
            }

            warehouse_objects.append(
                {
                    "id": loc.id,
                    "type": zone_type_code.lower(),
                    "x": x,
                    "y": y,
                    "z": z,
                    "width": width,
                    "depth": depth,
                    "height": height,
                    "color": color_map.get(zone_type_code, "#94a3b8"),
                    "code": loc.code,
                    "zone_code": zone.code,
                    "zone_name": zone.name,
                }
            )

    access_level = request.user.get_warehouse_access_level(warehouse)

    data = {
        "warehouse": {
            "id": warehouse.id,
            "code": warehouse.code,
            "name": warehouse.name,
            "branch": {
                "id": warehouse.branch.id,
                "code": warehouse.branch.code,
                "name": warehouse.branch.name,
            },
            "width": float(warehouse.width_m),
            "length": float(warehouse.length_m),
            "height": float(warehouse.height_m),
        },
        "access_level": access_level,
        "objects": warehouse_objects,
    }
    return JsonResponse(data)


def _check_warehouse_edit_permission(user, warehouse):
    """Проверяет право на редактирование склада."""
    if user.is_admin():
        return True

    access_level = user.get_warehouse_access_level(warehouse)
    return access_level in [WarehouseAccess.AccessLevel.EDIT, WarehouseAccess.AccessLevel.ADMIN]


@require_http_methods(["POST"])
def warehouse_object_create(request: HttpRequest, warehouse_id: int) -> JsonResponse:
    """Создание объекта хранения в складе."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        warehouse = Warehouse.objects.get(pk=warehouse_id, is_active=True)
    except Warehouse.DoesNotExist:
        return JsonResponse({"error": "Warehouse not found"}, status=404)

    if not request.user.can_access_warehouse(warehouse):
        return JsonResponse({"error": "Access denied"}, status=403)

    if not _check_warehouse_edit_permission(request.user, warehouse):
        return JsonResponse({"error": "Edit permission required"}, status=403)

    try:
        import json

        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    required_fields = ["type", "code"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return JsonResponse({"error": f"Missing fields: {', '.join(missing)}"}, status=400)

    zone_type_code = payload.get("type", "CELL")
    try:
        from catalog.models import StorageZoneType

        zone_type = StorageZoneType.objects.get(code=zone_type_code)
        zone = StorageZone.objects.filter(warehouse=warehouse, zone_type=zone_type).first()
        if not zone:
            return JsonResponse({"error": f"Zone with type {zone_type_code} not found in warehouse"}, status=404)
    except StorageZoneType.DoesNotExist:
        return JsonResponse({"error": f"Zone type {zone_type_code} not found"}, status=404)

    try:
        aisle_val = payload.get("aisle", 1)
        rack_val = payload.get("rack", 1)
        shelf_val = payload.get("shelf", 1)
        level_val = payload.get("level", "")

        location = StorageLocation.objects.create(
            zone=zone,
            code=payload["code"],
            aisle=str(int(aisle_val)) if aisle_val and str(aisle_val).strip() else "",
            rack=str(int(rack_val)) if rack_val and str(rack_val).strip() else "",
            shelf=str(int(shelf_val)) if shelf_val and str(shelf_val).strip() else "",
            level=str(int(level_val)) if level_val and str(level_val).strip() else "",
        )
        return JsonResponse({"id": location.id, "code": location.code}, status=201)
    except (ValueError, TypeError) as e:
        return JsonResponse({"error": f"Invalid numeric values: {e}"}, status=400)


@require_http_methods(["DELETE"])
def warehouse_object_delete(request: HttpRequest, warehouse_id: int, pk: int) -> JsonResponse:
    """Удаление объекта хранения."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        warehouse = Warehouse.objects.get(pk=warehouse_id, is_active=True)
    except Warehouse.DoesNotExist:
        return JsonResponse({"error": "Warehouse not found"}, status=404)

    if not request.user.can_access_warehouse(warehouse):
        return JsonResponse({"error": "Access denied"}, status=403)

    if not _check_warehouse_edit_permission(request.user, warehouse):
        return JsonResponse({"error": "Edit permission required"}, status=403)

    try:
        location = StorageLocation.objects.select_related("zone").get(pk=pk, zone__warehouse=warehouse)
        location.delete()
        return JsonResponse({"success": True})
    except StorageLocation.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
