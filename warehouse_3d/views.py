import io
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from admin_panel.models import AuditLog
from catalog.models import StorageLocation, StorageZone, Warehouse, WarehouseAccess

from .models import StorageObject, WarehouseLayout


# ── Audit helper ────────────────────────────────────────────────


def _log_layout(user, request, action, storage_obj, *, before=None, after=None, extra=None):
    """Запись в AuditLog для операций над 3D-объектами."""
    changes = {}
    if before is not None:
        changes["before"] = before
    if after is not None:
        changes["after"] = after
    if extra:
        changes.update(extra)
    AuditLog.objects.create(
        user=user,
        action=action,
        resource_type="StorageObject",
        resource_id=str(storage_obj.id) if storage_obj and storage_obj.id else "",
        resource_str=str(storage_obj) if storage_obj else "",
        changes=changes or None,
        ip_address=request.META.get("REMOTE_ADDR") if request else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:512]) if request else "",
    )


def _snapshot(obj):
    """Снимок 3D-объекта для audit-журнала."""
    if not obj:
        return None
    return {
        "object_type": obj.object_type,
        "code": obj.code,
        "name": obj.name,
        "position_x": float(obj.position_x or 0),
        "position_y": float(obj.position_y or 0),
        "position_z": float(obj.position_z or 0),
        "width": float(obj.width or 1),
        "depth": float(obj.depth or 1),
        "height": float(obj.height or 1),
        "rotation_y": float(obj.rotation_y or 0),
    }


# ── Helpers ──────────────────────────────────────────────────────


def _can_edit(user, warehouse):
    level = user.get_warehouse_access_level(warehouse)
    return level in (
        WarehouseAccess.AccessLevel.EDIT,
        WarehouseAccess.AccessLevel.ADMIN,
    ) or user.is_admin()


def _capacity_for(obj):
    """
    Эвристика вместимости 3D-объекта в условных единицах:
    объём (W*D*H) с поправкой на тип. Используется для heatmap.
    """
    volume = (obj.width or 1) * (obj.depth or 1) * (obj.height or 1)
    factor = {
        "RACK": 80.0,   # стеллаж — много позиций
        "SHELF": 40.0,
        "CELL": 10.0,
        "FLOOR": 20.0,
    }.get(obj.object_type, 20.0)
    return max(1.0, volume * factor)


def _build_stocks_payload(storage_objects):
    """
    Возвращает (stocks_by_location, fill_by_object, kpi).
    stocks_by_location: {location_id: [{product_sku, product_name, qty}, ...]}
    fill_by_object:     {object_id: {qty, capacity, pct}}
    kpi:                {total_objects, with_stock, empty, fill_pct, total_qty,
                         expired, total_volume}
    """
    from inventory.models import Stock

    stocks_by_location = {}
    location_ids = [obj.storage_location_id for obj in storage_objects if obj.storage_location_id]
    if location_ids:
        stocks = Stock.objects.filter(
            storage_location_id__in=location_ids,
            qty_available__gt=0,
        ).select_related("product", "storage_location")
        for stock in stocks:
            loc_id = stock.storage_location_id
            stocks_by_location.setdefault(loc_id, []).append({
                "stock_id": stock.id,
                "product_sku": stock.product.internal_sku,
                "product_name": stock.product.name,
                "qty": float(stock.qty_available),
                "expiry_date": stock.expiry_date.isoformat() if stock.expiry_date else None,
                "batch_no": stock.batch_no or "",
            })

    fill_by_object = {}
    total_qty = Decimal("0")
    total_capacity = 0.0
    with_stock = 0
    expired_count = 0
    today = timezone.now().date()

    for obj in storage_objects:
        capacity = _capacity_for(obj)
        loc_stocks = stocks_by_location.get(obj.storage_location_id, [])
        qty = sum(Decimal(str(s["qty"])) for s in loc_stocks) if loc_stocks else Decimal("0")
        pct = float(qty) / capacity if capacity else 0.0
        pct = max(0.0, min(1.0, pct))
        if loc_stocks:
            with_stock += 1
            for s in loc_stocks:
                if s.get("expiry_date") and s["expiry_date"] <= today.isoformat():
                    expired_count += 1
        fill_by_object[obj.id] = {
            "qty": float(qty),
            "capacity": round(capacity, 2),
            "pct": round(pct, 4),
            "products": len(loc_stocks),
        }
        total_qty += qty
        total_capacity += capacity

    fill_pct = (float(total_qty) / total_capacity) if total_capacity else 0.0
    fill_pct = max(0.0, min(1.0, fill_pct))

    total_objects = len(storage_objects) if hasattr(storage_objects, "__len__") else storage_objects.count()
    kpi = {
        "total_objects": total_objects,
        "with_stock": with_stock,
        "empty": total_objects - with_stock,
        "fill_pct": round(fill_pct, 4),
        "total_qty": float(total_qty),
        "total_capacity": round(total_capacity, 2),
        "expired": expired_count,
    }
    return stocks_by_location, fill_by_object, kpi


def _serialize_object(obj):
    return {
        "id": obj.id,
        "type": obj.object_type,
        "code": obj.code or "",
        "name": obj.name or "",
        "position": {
            "x": float(obj.position_x or 0),
            "y": float(obj.position_y or 0),
            "z": float(obj.position_z or 0),
        },
        "size": {
            "width": float(obj.width or 1),
            "depth": float(obj.depth or 1),
            "height": float(obj.height or 1),
        },
        "rotation": float(obj.rotation_y or 0),
        "storageLocationId": obj.storage_location_id if obj.storage_location_id else None,
    }


def _storage_locations_payload(warehouse):
    locations = (
        StorageLocation.objects.filter(zone__warehouse=warehouse)
        .select_related("zone", "zone__zone_type")
        .order_by("zone__zone_type__sort_order", "zone__code", "code")
    )
    return [
        {
            "id": loc.id,
            "code": loc.code,
            "label": str(loc),
            "name": loc.name or "",
            "zone": loc.zone.code,
            "zoneName": loc.zone.name,
            "zoneType": loc.zone.zone_type.code if loc.zone.zone_type else "",
        }
        for loc in locations
    ]


# ── Pages ────────────────────────────────────────────────────────


@login_required
def warehouse_3d_index(request):
    """
    Лендинг 3D-склада: выбор склада из доступных.
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
    Отображение 3D-склада с расширенным контекстом
    (товары, заполненность, KPI).
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)

    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    access_level = request.user.get_warehouse_access_level(warehouse)
    can_edit = _can_edit(request.user, warehouse)

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    storage_objects = list(
        StorageObject.objects.filter(warehouse=warehouse, is_active=True)
        .select_related("storage_location")
    )

    stocks_by_location, fill_by_object, kpi = _build_stocks_payload(storage_objects)
    storage_objects_json = [_serialize_object(o) for o in storage_objects]
    zones_payload = _zones_payload(warehouse)
    storage_locations_payload = _storage_locations_payload(warehouse)

    # ?focus=<id> — JS подхватит и сделает fly-to при загрузке
    try:
        focus_id = int(request.GET.get("focus")) if request.GET.get("focus") else None
    except ValueError:
        focus_id = None

    context = {
        "warehouse": warehouse,
        "layout": layout,
        "storage_objects": storage_objects,
        "storage_objects_json": json.dumps(storage_objects_json),
        "can_edit": can_edit,
        "access_level": access_level,
        "stocks_by_location": stocks_by_location,
        "stocks_json": json.dumps(stocks_by_location),
        "fill_by_object_json": json.dumps(fill_by_object),
        "kpi": kpi,
        "kpi_json": json.dumps(kpi),
        "zones_json": json.dumps(zones_payload),
        "storage_locations_json": json.dumps(storage_locations_payload),
        "gate_json": json.dumps({"x": layout.gate_point[0], "z": layout.gate_point[1]}),
        "focus_id": focus_id,
    }
    return render(request, "warehouse_3d/view.html", context)


# ── Layout / Object CRUD ────────────────────────────────────────


@login_required
@require_http_methods(["POST"])
def save_layout(request, warehouse_id):
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    if not _can_edit(request.user, warehouse):
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    data = json.loads(request.body)
    floor_points = data.get("floor_points", [])

    if floor_points and len(floor_points) < 3:
        return JsonResponse({"error": "Недостаточно точек для создания контура"}, status=400)

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    layout.floor_points = floor_points
    layout.is_layout_defined = len(floor_points) >= 3
    layout.save()

    msg = "Геометрия склада сохранена" if layout.is_layout_defined else "Разметка склада очищена"
    return JsonResponse({"success": True, "message": msg})


@login_required
@require_http_methods(["POST"])
def save_storage_object(request, warehouse_id):
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    if not _can_edit(request.user, warehouse):
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    data = json.loads(request.body)
    obj_id = data.get("id")
    is_new = not obj_id
    if obj_id:
        storage_obj = get_object_or_404(StorageObject, id=obj_id, warehouse=warehouse)
        before = _snapshot(storage_obj)
    else:
        storage_obj = StorageObject(warehouse=warehouse)
        before = None

    object_type = data.get("object_type")
    if object_type not in StorageObject.ObjectType.values:
        return JsonResponse({"success": False, "error": "Недопустимый тип объекта"}, status=400)

    storage_location_id = data.get("storage_location_id")
    storage_location = None
    if storage_location_id:
        try:
            storage_location = StorageLocation.objects.get(
                id=int(storage_location_id),
                zone__warehouse=warehouse,
            )
        except (StorageLocation.DoesNotExist, TypeError, ValueError):
            return JsonResponse({"success": False, "error": "Место хранения не найдено"}, status=400)

    storage_obj.object_type = object_type
    storage_obj.code = data.get("code", "")
    storage_obj.name = data.get("name", "")
    storage_obj.position_x = float(data.get("position_x", 0))
    storage_obj.position_z = float(data.get("position_z", 0))
    storage_obj.position_y = float(data.get("position_y", 0))
    storage_obj.width = float(data.get("width", 1))
    storage_obj.depth = float(data.get("depth", 1))
    storage_obj.height = float(data.get("height", 1))
    storage_obj.rotation_y = float(data.get("rotation_y", 0))
    storage_obj.storage_location = storage_location
    storage_obj.save()

    _log_layout(
        request.user, request,
        AuditLog.ActionType.LAYOUT_CREATE if is_new else AuditLog.ActionType.LAYOUT_UPDATE,
        storage_obj, before=before, after=_snapshot(storage_obj),
    )

    return JsonResponse({
        "success": True,
        "id": storage_obj.id,
        "object": _serialize_object(storage_obj),
        "message": "Объект сохранён",
    })


@login_required
@require_http_methods(["POST"])
def delete_storage_object(request, warehouse_id, object_id):
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    if not _can_edit(request.user, warehouse):
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    storage_obj = get_object_or_404(StorageObject, id=object_id, warehouse=warehouse)
    if storage_obj.has_stock():
        stock_count = storage_obj.get_stock_count()
        total_qty = storage_obj.get_total_stock_qty()
        return JsonResponse({
            "success": False,
            "error": (
                f"Невозможно удалить объект: на нём находятся товары "
                f"({stock_count} позиций, всего {total_qty} шт.)"
            ),
            "has_stock": True,
            "stock_count": stock_count,
            "total_qty": float(total_qty),
        }, status=400)

    before = _snapshot(storage_obj)
    storage_obj.is_active = False
    storage_obj.save()
    _log_layout(
        request.user, request,
        AuditLog.ActionType.LAYOUT_DELETE,
        storage_obj, before=before, after=None,
    )
    return JsonResponse({"success": True, "message": "Объект удалён"})


# ═══════════════════════════════════════════════════════════════
#   #1 Авто-генерация стеллажей по сетке
# ═══════════════════════════════════════════════════════════════


@login_required
@require_POST
def bulk_generate_objects(request, warehouse_id):
    """
    Создаёт ряд стеллажей/ячеек по параметрам сетки.
    Body:
      object_type: RACK|SHELF|CELL|FLOOR
      start_x, start_z: float
      direction: 'x' | 'z' (вдоль какой оси расставлять)
      count: int (1..50)
      step: float (расстояние между центрами, м)
      width, depth, height, rotation_y: float
      code_prefix: str (опц.) — префикс для code (генерируем prefix-1, prefix-2, ...)
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    if not _can_edit(request.user, warehouse):
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Некорректный JSON"}, status=400)

    object_type = data.get("object_type") or "RACK"
    if object_type not in StorageObject.ObjectType.values:
        return JsonResponse({"success": False, "error": "Недопустимый тип объекта"}, status=400)

    try:
        count = int(data.get("count", 1))
        step = float(data.get("step", 2.5))
        start_x = float(data.get("start_x", 0))
        start_z = float(data.get("start_z", 0))
        width = float(data.get("width", 2))
        depth = float(data.get("depth", 1))
        height = float(data.get("height", 2.5))
        rotation_y = float(data.get("rotation_y", 0))
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Некорректные параметры"}, status=400)

    if count < 1 or count > 50:
        return JsonResponse({"success": False, "error": "count должен быть в диапазоне 1..50"}, status=400)
    direction = (data.get("direction") or "x").lower()
    if direction not in ("x", "z"):
        return JsonResponse({"success": False, "error": "direction: 'x' или 'z'"}, status=400)

    code_prefix = (data.get("code_prefix") or "").strip()

    created = []
    with transaction.atomic():
        for i in range(count):
            offset = i * step
            pos_x = start_x + (offset if direction == "x" else 0.0)
            pos_z = start_z + (offset if direction == "z" else 0.0)
            code = f"{code_prefix}-{i + 1}" if code_prefix else ""
            obj = StorageObject.objects.create(
                warehouse=warehouse,
                object_type=object_type,
                code=code, name="",
                position_x=pos_x, position_y=0.0, position_z=pos_z,
                width=width, depth=depth, height=height,
                rotation_y=rotation_y,
            )
            created.append(obj)

    _log_layout(
        request.user, request, AuditLog.ActionType.LAYOUT_BULK_CREATE,
        created[0] if created else None,
        before=None,
        after=None,
        extra={
            "count": len(created),
            "object_type": object_type,
            "ids": [o.id for o in created],
            "params": {
                "start_x": start_x, "start_z": start_z,
                "direction": direction, "step": step,
                "width": width, "depth": depth, "height": height,
                "rotation_y": rotation_y, "code_prefix": code_prefix,
            },
        },
    )

    return JsonResponse({
        "success": True,
        "created": len(created),
        "ids": [o.id for o in created],
        "message": f"Создано объектов: {len(created)}",
    })


# ═══════════════════════════════════════════════════════════════
#   #14 Audit-журнал layout: список + откат
# ═══════════════════════════════════════════════════════════════

LAYOUT_AUDIT_ACTIONS = [
    AuditLog.ActionType.LAYOUT_CREATE,
    AuditLog.ActionType.LAYOUT_UPDATE,
    AuditLog.ActionType.LAYOUT_DELETE,
    AuditLog.ActionType.LAYOUT_BULK_CREATE,
    AuditLog.ActionType.LAYOUT_ROLLBACK,
]


@login_required
def layout_audit(request, warehouse_id):
    """
    GET /api/audit/?limit=20
    Возвращает последние записи AuditLog по объектам этого склада.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    try:
        limit = max(1, min(100, int(request.GET.get("limit", 20))))
    except ValueError:
        limit = 20

    object_ids = list(
        StorageObject.objects.filter(warehouse=warehouse).values_list("id", flat=True)
    )
    qs = AuditLog.objects.filter(
        action__in=LAYOUT_AUDIT_ACTIONS,
        resource_type="StorageObject",
    )
    if object_ids:
        qs = qs.filter(resource_id__in=[str(i) for i in object_ids])
    qs = qs.select_related("user").order_by("-timestamp")[:limit]

    items = []
    for log in qs:
        items.append({
            "id": log.id,
            "action": log.action,
            "action_label": log.get_action_display(),
            "resource_id": log.resource_id,
            "resource_str": log.resource_str,
            "user": log.user.username if log.user else "system",
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "changes": log.changes,
            "rollbackable": log.action in (
                AuditLog.ActionType.LAYOUT_UPDATE,
                AuditLog.ActionType.LAYOUT_DELETE,
            ) and bool(log.changes and log.changes.get("before")),
        })
    return JsonResponse({"items": items, "count": len(items)})


@login_required
@require_POST
def layout_audit_rollback(request, warehouse_id, audit_id):
    """
    POST /api/audit/<audit_id>/rollback/
    Откатывает одну запись AuditLog (UPDATE → восстановить before; DELETE → активировать обратно).
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    if not _can_edit(request.user, warehouse):
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    log = get_object_or_404(AuditLog, id=audit_id, resource_type="StorageObject")
    if log.action not in (AuditLog.ActionType.LAYOUT_UPDATE, AuditLog.ActionType.LAYOUT_DELETE):
        return JsonResponse({"success": False, "error": "Эту запись нельзя откатить"}, status=400)

    before = (log.changes or {}).get("before")
    if not before:
        return JsonResponse({"success": False, "error": "Нет данных для отката"}, status=400)

    try:
        obj = StorageObject.objects.get(id=int(log.resource_id), warehouse=warehouse)
    except (StorageObject.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"success": False, "error": "Объект не найден"}, status=404)

    obj.object_type = before.get("object_type", obj.object_type)
    obj.code = before.get("code", obj.code)
    obj.name = before.get("name", obj.name)
    obj.position_x = float(before.get("position_x", obj.position_x))
    obj.position_y = float(before.get("position_y", obj.position_y))
    obj.position_z = float(before.get("position_z", obj.position_z))
    obj.width = float(before.get("width", obj.width))
    obj.depth = float(before.get("depth", obj.depth))
    obj.height = float(before.get("height", obj.height))
    obj.rotation_y = float(before.get("rotation_y", obj.rotation_y))
    if log.action == AuditLog.ActionType.LAYOUT_DELETE:
        obj.is_active = True
    obj.save()

    _log_layout(
        request.user, request, AuditLog.ActionType.LAYOUT_ROLLBACK, obj,
        before=None, after=_snapshot(obj),
        extra={"rolled_back_audit_id": log.id},
    )
    return JsonResponse({"success": True, "message": "Изменение откачено"})


# ═══════════════════════════════════════════════════════════════
#   #13 QR-этикетка: PDF A6 со штрихкодом + код объекта + ?focus=
# ═══════════════════════════════════════════════════════════════


def _load_cyrillic_font():
    """Возвращает имя зарегистрированного шрифта для PDF (поддержка кириллицы)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            pdfmetrics.registerFont(TTFont("WMSFont3D", path))
            return "WMSFont3D"
        except Exception:
            continue
    return "Helvetica"


@login_required
def object_qr_pdf(request, warehouse_id, object_id):
    """
    PDF A6 с QR-кодом и подписями для физической наклейки на стеллаж.
    QR ведёт на 3D с автофокусом: /control/3d/warehouse/<id>/?focus=<obj_id>
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    storage_obj = get_object_or_404(
        StorageObject, id=object_id, warehouse=warehouse, is_active=True,
    )

    import qrcode
    from reportlab.lib.pagesizes import A6
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas

    base_url = request.build_absolute_uri(
        f"/control/3d/warehouse/{warehouse.id}/?focus={storage_obj.id}"
    )
    qr_img = qrcode.make(base_url, box_size=8, border=2)
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_buf.seek(0)

    font = _load_cyrillic_font()
    pdf_buf = io.BytesIO()
    c = pdfcanvas.Canvas(pdf_buf, pagesize=A6)
    page_w, page_h = A6  # 105×148 мм

    # Заголовок
    c.setFont(font, 11)
    c.drawString(8 * mm, page_h - 12 * mm, f"Склад: {warehouse.code}")

    # QR
    from reportlab.lib.utils import ImageReader
    qr_size = 60 * mm
    c.drawImage(
        ImageReader(qr_buf),
        (page_w - qr_size) / 2, page_h - qr_size - 18 * mm,
        width=qr_size, height=qr_size, mask="auto",
    )

    # Код и тип объекта (крупно)
    c.setFont(font, 22)
    label = storage_obj.code or f"#{storage_obj.id}"
    c.drawCentredString(page_w / 2, 30 * mm, label)
    c.setFont(font, 10)
    c.drawCentredString(page_w / 2, 22 * mm, storage_obj.get_object_type_display())
    if storage_obj.name:
        c.setFont(font, 9)
        c.drawCentredString(page_w / 2, 14 * mm, storage_obj.name[:48])

    c.showPage()
    c.save()

    response = HttpResponse(pdf_buf.getvalue(), content_type="application/pdf")
    fname = f"qr_{warehouse.code}_{storage_obj.code or storage_obj.id}.pdf"
    response["Content-Disposition"] = f'inline; filename="{fname}"'
    return response


# ═══════════════════════════════════════════════════════════════
#   #2 Маршрут комплектования (greedy nearest)
# ═══════════════════════════════════════════════════════════════


@login_required
def pick_path(request, warehouse_id):
    """
    GET /api/pickpath/?skus=A,B,C
    Возвращает упорядоченные точки маршрута: ворота → ближайший объект → … → ворота.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    skus_raw = (request.GET.get("skus") or "").strip()
    if not skus_raw:
        return JsonResponse({"path": [], "missing": [], "total_distance": 0.0})
    skus = [s.strip() for s in skus_raw.replace(";", ",").split(",") if s.strip()]
    if not skus:
        return JsonResponse({"path": [], "missing": [], "total_distance": 0.0})

    from inventory.models import Stock

    # Карта: SKU → список (object_id, position) на этом складе
    stocks_qs = (
        Stock.objects
        .filter(
            storage_location__zone__warehouse=warehouse,
            qty_available__gt=0,
            product__internal_sku__in=skus,
        )
        .select_related("product", "storage_location")
    )

    objects_by_loc = {}
    for obj in StorageObject.objects.filter(
        warehouse=warehouse, is_active=True, storage_location_id__isnull=False,
    ):
        objects_by_loc.setdefault(obj.storage_location_id, []).append(obj)

    sku_to_targets = {}
    for s in stocks_qs:
        targets = objects_by_loc.get(s.storage_location_id) or []
        for obj in targets:
            sku_to_targets.setdefault(s.product.internal_sku, []).append({
                "object_id": obj.id,
                "object_code": obj.code,
                "x": float(obj.position_x or 0),
                "z": float(obj.position_z or 0),
                "y": float(obj.position_y or 0),
                "qty_available": float(s.qty_available),
                "location_code": str(s.storage_location),
                "product_sku": s.product.internal_sku,
                "product_name": s.product.name,
            })

    found = {sku: sku_to_targets[sku] for sku in skus if sku in sku_to_targets}
    missing = [sku for sku in skus if sku not in sku_to_targets]

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    gx, gz = layout.gate_point

    # Greedy TSP: каждую точку выбираем как ближайшую из ещё не взятых SKU
    cur_x, cur_z = gx, gz
    remaining = dict(found)  # копия
    ordered = []
    total_dist = 0.0
    while remaining:
        best_sku, best_target, best_dist = None, None, None
        for sku, targets in remaining.items():
            for t in targets:
                d = ((t["x"] - cur_x) ** 2 + (t["z"] - cur_z) ** 2) ** 0.5
                if best_dist is None or d < best_dist:
                    best_dist = d
                    best_sku, best_target = sku, t
        if not best_sku:
            break
        ordered.append({**best_target, "step": len(ordered) + 1})
        total_dist += best_dist
        cur_x, cur_z = best_target["x"], best_target["z"]
        del remaining[best_sku]

    # Возврат к воротам
    total_dist += ((cur_x - gx) ** 2 + (cur_z - gz) ** 2) ** 0.5

    return JsonResponse({
        "gate": {"x": gx, "z": gz},
        "path": ordered,
        "missing": missing,
        "total_distance": round(total_dist, 2),
    })


# ═══════════════════════════════════════════════════════════════
#   #8 Inline-edit товаров на полках
# ═══════════════════════════════════════════════════════════════


@login_required
def object_stocks(request, warehouse_id, object_id):
    """GET /api/object/<id>/stocks/ — список товаров на 3D-объекте."""
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    storage_obj = get_object_or_404(
        StorageObject, id=object_id, warehouse=warehouse, is_active=True,
    )
    if not storage_obj.storage_location_id:
        return JsonResponse({"items": [], "location": None})

    from inventory.models import Stock

    stocks = Stock.objects.filter(
        storage_location_id=storage_obj.storage_location_id,
        qty_available__gt=0,
    ).select_related("product")

    return JsonResponse({
        "location": {
            "id": storage_obj.storage_location_id,
            "code": str(storage_obj.storage_location),
        },
        "items": [{
            "stock_id": s.id,
            "product_id": s.product.id,
            "product_sku": s.product.internal_sku,
            "product_name": s.product.name,
            "qty_available": float(s.qty_available),
            "qty_reserved": float(s.qty_reserved),
            "batch_no": s.batch_no or "",
            "expiry_date": s.expiry_date.isoformat() if s.expiry_date else None,
        } for s in stocks],
    })


@login_required
@require_POST
def stock_action(request, warehouse_id, object_id):
    """
    POST /api/object/<id>/stock-action/
    Body:
      action: 'transfer' | 'write_off' | 'adjust'
      stock_id: int
      qty: float (для write_off / adjust — может быть 0 для adjust)
      target_object_id: int  (только для transfer)
      reason, comment: str
    Создаёт StockMovement через inventory.services.record_movement и обновляет Stock.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    if not _can_edit(request.user, warehouse):
        raise PermissionDenied("У вас нет прав редактировать этот склад.")

    storage_obj = get_object_or_404(
        StorageObject, id=object_id, warehouse=warehouse, is_active=True,
    )
    if not storage_obj.storage_location_id:
        return JsonResponse({"success": False, "error": "Объект не привязан к локации"}, status=400)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Некорректный JSON"}, status=400)

    action = (data.get("action") or "").lower()
    stock_id = data.get("stock_id")
    try:
        qty = Decimal(str(data.get("qty", 0)))
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Некорректное qty"}, status=400)

    from inventory.models import MovementType, Stock
    from inventory.services import record_movement

    try:
        stock = Stock.objects.select_related("product", "storage_location").get(
            id=stock_id,
            storage_location_id=storage_obj.storage_location_id,
        )
    except Stock.DoesNotExist:
        return JsonResponse({"success": False, "error": "Stock не найден"}, status=404)

    reason = (data.get("reason") or "").strip()[:128]
    comment = (data.get("comment") or "").strip()

    with transaction.atomic():
        if action == "transfer":
            target_obj_id = data.get("target_object_id")
            target = get_object_or_404(
                StorageObject, id=target_obj_id, warehouse=warehouse, is_active=True,
            )
            if not target.storage_location_id:
                return JsonResponse({
                    "success": False,
                    "error": "Целевой объект не привязан к локации",
                }, status=400)
            if qty <= 0 or qty > stock.qty_available:
                return JsonResponse({
                    "success": False,
                    "error": "qty должно быть в диапазоне (0, qty_available]",
                }, status=400)

            # Уменьшаем источник, увеличиваем приёмник
            stock.qty_available = stock.qty_available - qty
            stock.save(update_fields=["qty_available"])
            target_stock, _ = Stock.objects.get_or_create(
                product=stock.product,
                storage_location_id=target.storage_location_id,
                batch_no=stock.batch_no or "",
                defaults={"qty_available": Decimal("0"), "qty_reserved": Decimal("0")},
            )
            target_stock.qty_available = target_stock.qty_available + qty
            target_stock.save(update_fields=["qty_available"])

            mv = record_movement(
                movement_type=MovementType.TRANSFER,
                product=stock.product, quantity=qty,
                from_location=stock.storage_location,
                to_location=target.storage_location,
                user=request.user, batch_no=stock.batch_no or "",
                reason=reason or "Перемещение из 3D",
                comment=comment, ref_type="WAREHOUSE_3D",
                ref_id=str(storage_obj.id),
            )
            return JsonResponse({
                "success": True, "movement_id": mv.id,
                "message": f"Перемещено {qty} шт. → {target.code or target.id}",
            })

        if action == "write_off":
            if qty <= 0 or qty > stock.qty_available:
                return JsonResponse({
                    "success": False,
                    "error": "qty должно быть в диапазоне (0, qty_available]",
                }, status=400)
            stock.qty_available = stock.qty_available - qty
            stock.save(update_fields=["qty_available"])
            mv = record_movement(
                movement_type=MovementType.WRITE_OFF,
                product=stock.product, quantity=qty,
                from_location=stock.storage_location,
                user=request.user, batch_no=stock.batch_no or "",
                reason=reason or "Списание из 3D",
                comment=comment, ref_type="WAREHOUSE_3D",
                ref_id=str(storage_obj.id),
            )
            return JsonResponse({
                "success": True, "movement_id": mv.id,
                "message": f"Списано {qty} шт.",
            })

        if action == "adjust":
            # Корректировка: qty — новое значение qty_available
            if qty < 0:
                return JsonResponse({"success": False, "error": "qty не может быть отрицательным"}, status=400)
            delta = qty - stock.qty_available
            if delta == 0:
                return JsonResponse({"success": True, "message": "Без изменений"})
            stock.qty_available = qty
            stock.save(update_fields=["qty_available"])
            mv = record_movement(
                movement_type=MovementType.ADJUSTMENT,
                product=stock.product, quantity=delta,
                from_location=stock.storage_location if delta < 0 else None,
                to_location=stock.storage_location if delta > 0 else None,
                user=request.user, batch_no=stock.batch_no or "",
                reason=reason or "Корректировка из 3D",
                comment=comment, ref_type="WAREHOUSE_3D",
                ref_id=str(storage_obj.id),
            )
            return JsonResponse({
                "success": True, "movement_id": mv.id,
                "message": f"Корректировка: {delta:+} шт.",
            })

    return JsonResponse({"success": False, "error": "Неизвестное действие"}, status=400)


# ═══════════════════════════════════════════════════════════════
#   #9 Long-polling: новые движения после <since>
# ═══════════════════════════════════════════════════════════════


@login_required
def recent_movements(request, warehouse_id):
    """
    GET /api/recent-movements/?since=<id>&limit=50
    Возвращает движения StockMovement, у которых id > since и которые
    затрагивают локации этого склада. Для анимации в 3D.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    try:
        since = int(request.GET.get("since", 0))
    except ValueError:
        since = 0
    try:
        limit = max(1, min(200, int(request.GET.get("limit", 50))))
    except ValueError:
        limit = 50

    from inventory.models import StockMovement

    qs = (
        StockMovement.objects.filter(id__gt=since)
        .filter(
            Q(from_location__zone__warehouse=warehouse)
            | Q(to_location__zone__warehouse=warehouse)
        )
        .select_related("product", "from_location", "to_location")
        .order_by("id")[:limit]
    )

    objects_by_loc = {}
    for obj in StorageObject.objects.filter(
        warehouse=warehouse, is_active=True, storage_location_id__isnull=False,
    ):
        objects_by_loc.setdefault(obj.storage_location_id, []).append(obj)

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    gx, gz = layout.gate_point

    items = []
    last_id = since
    for mv in qs:
        last_id = mv.id

        def _coords(loc):
            if not loc:
                return None
            objs = objects_by_loc.get(loc.id) or []
            if not objs:
                return None
            o = objs[0]
            return {
                "object_id": o.id, "object_code": o.code,
                "x": float(o.position_x or 0),
                "y": float(o.position_y or 0),
                "z": float(o.position_z or 0),
            }

        items.append({
            "id": mv.id,
            "type": mv.movement_type,
            "type_label": mv.get_movement_type_display(),
            "product_sku": mv.product.internal_sku,
            "product_name": mv.product.name,
            "quantity": float(mv.quantity),
            "from": _coords(mv.from_location),
            "to": _coords(mv.to_location),
            "user": mv.user.username if mv.user else "",
            "created_at": mv.created_at.isoformat(),
        })

    return JsonResponse({
        "items": items,
        "last_id": last_id,
        "gate": {"x": gx, "z": gz},
    })


# ═══════════════════════════════════════════════════════════════
#   #10 Зоны: данные для рендера полупрозрачных bbox
# ═══════════════════════════════════════════════════════════════


@login_required
def objects_for_receiving(request, warehouse_id):
    """
    GET /control/3d/api/objects-for-receiving/<warehouse_id>/
    Список 3D-объектов склада с привязанной storage_location и текущей
    заполненностью — для интеграции с модулем приёмки.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    storage_objects = list(
        StorageObject.objects.filter(
            warehouse=warehouse, is_active=True, storage_location_id__isnull=False,
        ).select_related("storage_location")
    )
    _, fill_by_object, _ = _build_stocks_payload(storage_objects)

    items = []
    for obj in storage_objects:
        f = fill_by_object.get(obj.id, {"qty": 0, "capacity": 0, "pct": 0, "products": 0})
        # цвет светофора по pct: 0..0.7 — green, 0.7..0.9 — yellow, >=0.9 — red
        pct = f["pct"]
        status = "ok" if pct < 0.7 else ("warn" if pct < 0.9 else "full")
        items.append({
            "object_id": obj.id,
            "code": obj.code or f"#{obj.id}",
            "name": obj.name or "",
            "type": obj.object_type,
            "type_label": obj.get_object_type_display(),
            "storage_location_id": obj.storage_location_id,
            "storage_location_code": str(obj.storage_location),
            "qty": f["qty"],
            "capacity": f["capacity"],
            "pct": f["pct"],
            "products": f["products"],
            "status": status,
        })
    items.sort(key=lambda x: (x["type"], x["code"]))
    return JsonResponse({"items": items, "count": len(items)})


def _zones_payload(warehouse):
    """
    Для каждой зоны склада возвращает bounding-box по координатам
    StorageObject'ов, привязанных к её локациям.
    """
    zones = list(StorageZone.objects.filter(warehouse=warehouse).select_related("zone_type"))
    if not zones:
        return []

    from catalog.models import StorageLocation

    loc_to_zone = {}
    for zone in zones:
        for loc_id in StorageLocation.objects.filter(zone=zone).values_list("id", flat=True):
            loc_to_zone[loc_id] = zone.id

    bboxes = {}
    for obj in StorageObject.objects.filter(
        warehouse=warehouse, is_active=True, storage_location_id__isnull=False,
    ):
        zid = loc_to_zone.get(obj.storage_location_id)
        if not zid:
            continue
        bb = bboxes.setdefault(zid, {"x_min": None, "x_max": None, "z_min": None, "z_max": None, "h_max": 0.0})
        x = float(obj.position_x or 0)
        z = float(obj.position_z or 0)
        w = float(obj.width or 1) / 2.0
        d = float(obj.depth or 1) / 2.0
        h = float(obj.height or 1)
        bb["x_min"] = x - w if bb["x_min"] is None else min(bb["x_min"], x - w)
        bb["x_max"] = x + w if bb["x_max"] is None else max(bb["x_max"], x + w)
        bb["z_min"] = z - d if bb["z_min"] is None else min(bb["z_min"], z - d)
        bb["z_max"] = z + d if bb["z_max"] is None else max(bb["z_max"], z + d)
        bb["h_max"] = max(bb["h_max"], h)

    out = []
    for zone in zones:
        bb = bboxes.get(zone.id)
        if not bb:
            continue
        # padding 0.4 м для красоты
        out.append({
            "id": zone.id,
            "code": zone.code,
            "name": zone.name,
            "type": zone.zone_type.code if zone.zone_type else "",
            "x_min": bb["x_min"] - 0.4,
            "x_max": bb["x_max"] + 0.4,
            "z_min": bb["z_min"] - 0.4,
            "z_max": bb["z_max"] + 0.4,
            "h_max": max(0.5, bb["h_max"] + 0.2),
        })
    return out


# ── KPI / Search / Heatmap / Import-Export ──────────────────────


@login_required
def kpi_data(request, warehouse_id):
    """JSON со свежими KPI (для авто-обновления панели)."""
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    storage_objects = list(
        StorageObject.objects.filter(warehouse=warehouse, is_active=True)
        .select_related("storage_location")
    )
    _, fill_by_object, kpi = _build_stocks_payload(storage_objects)
    return JsonResponse({"kpi": kpi, "fill_by_object": fill_by_object})


@login_required
def locate_sku(request, warehouse_id):
    """
    Поиск SKU по складу. Возвращает список объектов 3D, на которых лежит товар,
    с координатами для fly-to.
    GET ?q=<sku|name>
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    query = (request.GET.get("q") or "").strip()
    if not query:
        return JsonResponse({"results": []})

    from inventory.models import Stock

    stocks = (
        Stock.objects.filter(
            storage_location__zone__warehouse=warehouse,
            qty_available__gt=0,
        )
        .filter(Q(product__internal_sku__icontains=query) | Q(product__name__icontains=query) | Q(product__oem_number__icontains=query))
        .select_related("product", "storage_location")[:50]
    )

    location_ids = {s.storage_location_id for s in stocks}
    objects_by_loc = {}
    for obj in StorageObject.objects.filter(
        warehouse=warehouse, is_active=True, storage_location_id__in=location_ids
    ):
        objects_by_loc.setdefault(obj.storage_location_id, []).append(obj)

    results = []
    for s in stocks:
        for obj in objects_by_loc.get(s.storage_location_id, []):
            results.append({
                "object_id": obj.id,
                "object_code": obj.code or "",
                "object_type": obj.object_type,
                "position": {
                    "x": float(obj.position_x or 0),
                    "y": float(obj.position_y or 0),
                    "z": float(obj.position_z or 0),
                },
                "product_sku": s.product.internal_sku,
                "product_name": s.product.name,
                "qty": float(s.qty_available),
                "location_code": str(s.storage_location),
            })

    return JsonResponse({"results": results, "count": len(results)})


@login_required
def movement_heatmap(request, warehouse_id):
    """
    Heatmap «активности» по StockMovement за период (по умолчанию 30 дней).
    Возвращает {object_id: count_movements} нормализованный 0..1.
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    try:
        days = max(1, min(365, int(request.GET.get("days", 30))))
    except ValueError:
        days = 30

    since = timezone.now() - timedelta(days=days)

    from inventory.models import StockMovement

    qs = (
        StockMovement.objects
        .filter(
            Q(from_location__zone__warehouse=warehouse) | Q(to_location__zone__warehouse=warehouse),
            created_at__gte=since,
        )
        .values("from_location_id", "to_location_id")
        .annotate(c=Count("id"), q=Sum("quantity"))
    )

    counts_by_loc = {}
    for row in qs:
        for loc_id in (row["from_location_id"], row["to_location_id"]):
            if loc_id:
                counts_by_loc[loc_id] = counts_by_loc.get(loc_id, 0) + (row["c"] or 0)

    objects = StorageObject.objects.filter(
        warehouse=warehouse, is_active=True, storage_location_id__isnull=False
    ).values("id", "storage_location_id")

    counts_by_obj = {o["id"]: counts_by_loc.get(o["storage_location_id"], 0) for o in objects}
    max_count = max(counts_by_obj.values()) if counts_by_obj else 0

    if max_count > 0:
        normalized = {oid: round(c / max_count, 4) for oid, c in counts_by_obj.items()}
    else:
        normalized = dict.fromkeys(counts_by_obj, 0.0)

    return JsonResponse({
        "days": days,
        "since": since.isoformat(),
        "max_count": max_count,
        "by_object": normalized,
        "counts": counts_by_obj,
    })


@login_required
def export_layout(request, warehouse_id):
    """Экспорт layout в JSON-файл."""
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    storage_objects = StorageObject.objects.filter(warehouse=warehouse, is_active=True)

    payload = {
        "warehouse_code": warehouse.code,
        "warehouse_name": warehouse.name,
        "exported_at": timezone.now().isoformat(),
        "floor_points": layout.floor_points,
        "objects": [
            {
                "object_type": o.object_type,
                "code": o.code,
                "name": o.name,
                "position_x": float(o.position_x or 0),
                "position_y": float(o.position_y or 0),
                "position_z": float(o.position_z or 0),
                "width": float(o.width or 1),
                "depth": float(o.depth or 1),
                "height": float(o.height or 1),
                "rotation_y": float(o.rotation_y or 0),
            }
            for o in storage_objects
        ],
    }

    response = HttpResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    fname = f"layout_{warehouse.code}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    return response


@login_required
@require_POST
def import_layout(request, warehouse_id):
    """
    Импорт layout из JSON. Заменяет floor_points и (опционально) объекты.
    Body: { "floor_points": [...], "objects": [...], "replace_objects": bool }
    """
    warehouse = get_object_or_404(Warehouse, id=warehouse_id, is_active=True)
    if not request.user.can_access_warehouse(warehouse):
        raise PermissionDenied("У вас нет доступа к этому складу.")
    if not _can_edit(request.user, warehouse):
        raise PermissionDenied("У вас нет прав на редактирование этого склада.")

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Некорректный JSON"}, status=400)

    floor_points = data.get("floor_points") or []
    objects_in = data.get("objects") or []
    replace_objects = bool(data.get("replace_objects", False))

    if floor_points and len(floor_points) < 3:
        return JsonResponse({"success": False, "error": "Минимум 3 точки контура"}, status=400)

    layout, _ = WarehouseLayout.objects.get_or_create(warehouse=warehouse)
    if floor_points:
        layout.floor_points = floor_points
        layout.is_layout_defined = True
        layout.save()

    created = 0
    if replace_objects:
        active_objects = StorageObject.objects.filter(warehouse=warehouse, is_active=True)
        occupied_count = sum(1 for obj in active_objects if obj.has_stock())
        if occupied_count:
            return JsonResponse({
                "success": False,
                "error": (
                    "Нельзя заменить layout: на "
                    f"{occupied_count} объект(ах) есть товары. "
                    "Сначала переместите или спишите товар."
                ),
            }, status=400)
        # Мягко деактивируем существующие, чтобы не нарушить FK на Stock
        active_objects.update(is_active=False)

    for spec in objects_in:
        try:
            StorageObject.objects.create(
                warehouse=warehouse,
                object_type=spec.get("object_type") or "RACK",
                code=spec.get("code", "") or "",
                name=spec.get("name", "") or "",
                position_x=float(spec.get("position_x", 0) or 0),
                position_y=float(spec.get("position_y", 0) or 0),
                position_z=float(spec.get("position_z", 0) or 0),
                width=float(spec.get("width", 1) or 1),
                depth=float(spec.get("depth", 1) or 1),
                height=float(spec.get("height", 1) or 1),
                rotation_y=float(spec.get("rotation_y", 0) or 0),
            )
            created += 1
        except (ValueError, TypeError):
            continue

    return JsonResponse({
        "success": True,
        "created": created,
        "floor_points_set": bool(floor_points),
        "message": f"Импорт завершён: создано объектов — {created}",
    })
