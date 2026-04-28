from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from api.auth import ApiAuthError, authenticate_integration
from api.utils import json_error, json_ok, paginate, parse_json
from accounts.constants import Roles
from accounts.models import User
from catalog.audit import build_product_changes, log_product_change
from catalog.models import Brand, Category, Product, ProductCrossReference, VehicleMake, VehicleModel
from catalog.models import StorageLocation, StorageZone, Warehouse
from catalog.models import ProductChangeLog
from catalog.product_validation import validate_product_numbers_uniqueness
from inventory.models import Inventory, InventoryLine, InventoryStatus, Stock
from inventory.services import InventoryService, find_analog_on_stock
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from picking.models import PickingLine
from picking.services import OrderService, PickingService
from receiving.models import Receiving, ReceivingLine, ReceivingStatus
from receiving.services import suggest_storage_location
from receiving.services import ReceivingService
from reports.services import (
    analyze_analogs_vs_originals,
    calculate_abc_class,
    calculate_demand_forecast,
    calculate_staff_efficiency,
    calculate_xyz_class,
    find_dead_stock,
)
from tasks.models import Task, TaskComment, TaskPriority, TaskStatus, TaskType
from tasks.services import TaskService
from warehouse_3d.models import StorageObject


def _require_api_user(request: HttpRequest):
    try:
        user, _token = authenticate_integration(request)
        return user
    except ApiAuthError as e:
        return json_error(str(e), status=401, code="unauthorized")


def _parse_piece_qty(value, field_name: str, *, allow_zero: bool) -> Decimal:
    if value in (None, ""):
        raise ValueError(f"Field {field_name} is required")
    try:
        qty = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Field {field_name} must be a valid number")
    if qty != qty.to_integral_value():
        raise ValueError(f"Field {field_name} must be an integer quantity (pieces)")
    if allow_zero:
        if qty < 0:
            raise ValueError(f"Field {field_name} cannot be negative")
    elif qty <= 0:
        raise ValueError(f"Field {field_name} must be greater than zero")
    return qty


def _safe_int(value, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _paginate_list(request: HttpRequest, items: list):
    limit = _safe_int(request.GET.get("limit"), 50, min_value=1, max_value=200)
    offset = _safe_int(request.GET.get("offset"), 0, min_value=0)
    total = len(items)
    return items[offset : offset + limit], {"limit": limit, "offset": offset, "total": total}


def _serialize_task(task: Task):
    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "priority": task.priority,
        "title": task.title,
        "description": task.description,
        "assigned_to": (
            {"id": task.assigned_to_id, "username": task.assigned_to.username}
            if task.assigned_to_id and getattr(task, "assigned_to", None)
            else None
        ),
        "created_by": (
            {"id": task.created_by_id, "username": task.created_by.username}
            if task.created_by_id and getattr(task, "created_by", None)
            else None
        ),
        "receiving_id": task.receiving_id,
        "inventory_id": task.inventory_id,
        "order_id": task.order_id,
        "picking_task_id": task.picking_task_id,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def health(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    return json_ok({"service": "wms-api", "version": "v1"})


def me(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    user = user_or_resp
    warehouses_qs = Warehouse.objects.filter(is_active=True).select_related("branch")
    if not (user.is_superuser or user.role == Roles.INTEGRATION):
        warehouses_qs = user.get_accessible_warehouses()

    warehouses = [
        {
            "id": wh.id,
            "code": wh.code,
            "name": wh.name,
            "branch": {"id": wh.branch_id, "code": wh.branch.code, "name": wh.branch.name},
            "access_level": user.get_warehouse_access_level(wh),
        }
        for wh in warehouses_qs
    ]
    branches = list(user.branches.filter(is_active=True).values("id", "code", "name", "address"))
    return json_ok(
        {
            "id": user.id,
            "username": user.username,
            "full_name": user.get_full_name(),
            "email": user.email,
            "role": user.role,
            "role_label": user.get_role_display(),
            "is_superuser": user.is_superuser,
            "is_staff": user.is_staff,
            "warehouses": warehouses,
            "branches": branches,
        }
    )


def dashboard_summary_api(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    pending_tasks = Task.objects.filter(status=TaskStatus.PENDING).count()
    in_progress_tasks = Task.objects.filter(status=TaskStatus.IN_PROGRESS).count()
    pending_receivings = Receiving.objects.filter(status=ReceivingStatus.DRAFT).count()
    pending_inventories = Inventory.objects.filter(status=InventoryStatus.DRAFT).count()
    pending_orders = Order.objects.filter(status=OrderStatus.DRAFT).count()
    picking_pending = PickingTask.objects.filter(status=PickingTaskStatus.PENDING).count()

    return json_ok(
        {
            "generated_at": timezone.now().isoformat(),
            "tasks": {"pending": pending_tasks, "in_progress": in_progress_tasks},
            "receivings": {"draft": pending_receivings},
            "inventories": {"draft": pending_inventories},
            "orders": {"draft": pending_orders},
            "picking_tasks": {"pending": picking_pending},
        }
    )


def manual_api(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    user = user_or_resp
    first_warehouse = Warehouse.objects.filter(is_active=True).order_by("id").first()
    warehouse_3d_url = reverse("warehouse_3d:view", args=[first_warehouse.id]) if first_warehouse else None
    return json_ok(
        {
            "title": "WMS Manual",
            "sections": [
                {"key": "receiving", "title": "Приемка", "url": reverse("receiving_list")},
                {"key": "inventory", "title": "Инвентаризация", "url": reverse("inventory_list")},
                {"key": "picking", "title": "Подбор", "url": reverse("picking_task_list")},
                {"key": "orders", "title": "Заказы", "url": reverse("order_list")},
                {"key": "reports", "title": "Отчеты", "url": reverse("reports_home")},
                {"key": "profile", "title": "Профиль", "url": reverse("me")},
            ],
            "quick_links": {
                "dashboard": reverse("dashboard"),
                "tasks": reverse("task_list"),
                "warehouse_3d": warehouse_3d_url,
            },
            "role": user.role,
            "role_label": user.get_role_display(),
        }
    )


def brands_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    q = (request.GET.get("q") or "").strip()
    qs = Brand.objects.all().order_by("name")
    if q:
        qs = qs.filter(name__icontains=q)

    items, page = paginate(request, qs)
    data = [{"id": b.id, "name": b.name} for b in items]
    return json_ok({"items": data, "page": page})


def categories_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    q = (request.GET.get("q") or "").strip()
    qs = Category.objects.select_related("parent").all().order_by("name")
    if q:
        qs = qs.filter(name__icontains=q)

    items, page = paginate(request, qs)
    data = [
        {"id": c.id, "name": c.name, "parent_id": c.parent_id, "parent_name": (c.parent.name if c.parent else None)}
        for c in items
    ]
    return json_ok({"items": data, "page": page})


def vehicle_makes_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    q = (request.GET.get("q") or "").strip()
    qs = VehicleMake.objects.all().order_by("name")
    if q:
        qs = qs.filter(name__icontains=q)

    items, page = paginate(request, qs)
    data = [{"id": m.id, "name": m.name} for m in items]
    return json_ok({"items": data, "page": page})


def vehicle_models_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    q = (request.GET.get("q") or "").strip()
    make_id = (request.GET.get("make_id") or "").strip()
    qs = VehicleModel.objects.select_related("make").all().order_by("make__name", "name")
    if make_id.isdigit():
        qs = qs.filter(make_id=int(make_id))
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(make__name__icontains=q))

    items, page = paginate(request, qs)
    data = [{"id": vm.id, "make_id": vm.make_id, "make_name": vm.make.name, "name": vm.name} for vm in items]
    return json_ok({"items": data, "page": page})


def products_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        oem = (request.GET.get("oem") or "").strip()
        sku = (request.GET.get("sku") or "").strip()
        brand_id = (request.GET.get("brand_id") or "").strip()
        category_id = (request.GET.get("category_id") or "").strip()

        qs = Product.objects.select_related("brand", "category").all().order_by("name")
        if sku:
            qs = qs.filter(internal_sku__icontains=sku)
        if oem:
            qs = qs.filter(oem_number__icontains=oem)
        if brand_id.isdigit():
            qs = qs.filter(brand_id=int(brand_id))
        if category_id.isdigit():
            qs = qs.filter(category_id=int(category_id))
        if q:
            qs = qs.filter(
                Q(internal_sku__icontains=q)
                | Q(name__icontains=q)
                | Q(oem_number__icontains=q)
                | Q(analog_number__icontains=q)
                | Q(brand__name__icontains=q)
            )

        items, page = paginate(request, qs)
        data = [
            {
                "id": p.id,
                "internal_sku": p.internal_sku,
                "name": p.name,
                "oem_number": p.oem_number,
                "analog_number": p.analog_number,
                "brand": {"id": p.brand_id, "name": p.brand.name},
                "category": {"id": p.category_id, "name": p.category.name},
                "packaging_type": p.packaging_type,
                "weight_kg": str(p.weight_kg) if p.weight_kg is not None else None,
                "length_cm": str(p.length_cm) if p.length_cm is not None else None,
                "width_cm": str(p.width_cm) if p.width_cm is not None else None,
                "height_cm": str(p.height_cm) if p.height_cm is not None else None,
            }
            for p in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        required = ["internal_sku", "name", "oem_number", "brand_id", "category_id"]
        missing = [f for f in required if not payload.get(f)]
        if missing:
            return json_error(f"Missing fields: {', '.join(missing)}", status=400, code="validation_error")

        try:
            validate_product_numbers_uniqueness(
                oem_number=payload.get("oem_number"),
                analog_number=payload.get("analog_number"),
                exclude_id=None,
            )
        except ValidationError as e:
            return json_error(str(e), status=400, code="validation_error")

        try:
            p = Product.objects.create(
                internal_sku=payload["internal_sku"],
                name=payload["name"],
                oem_number=payload["oem_number"],
                analog_number=payload.get("analog_number") or "",
                brand_id=payload["brand_id"],
                category_id=payload["category_id"],
            )
        except Exception as e:
            return json_error(f"Failed to create product: {e}", status=400, code="creation_error")

        fresh = (
            Product.objects.select_related("brand", "category")
            .prefetch_related("applicability__make")
            .get(pk=p.pk)
        )
        changes = build_product_changes(
            before=None,
            after=fresh,
            action=ProductChangeLog.Action.CREATE,
        )
        log_product_change(
            product=fresh,
            user=user_or_resp,
            action=ProductChangeLog.Action.CREATE,
            changes=changes,
            source="api",
        )

        return json_ok({"id": p.id}, status=201)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def product_detail(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        p = (
            Product.objects.select_related("brand", "category")
            .prefetch_related("applicability__make")
            .get(pk=pk)
        )
    except Product.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        applicability = [{"id": vm.id, "make": vm.make.name, "model": vm.name} for vm in p.applicability.all()]
        data = {
            "id": p.id,
            "internal_sku": p.internal_sku,
            "name": p.name,
            "oem_number": p.oem_number,
            "analog_number": p.analog_number,
            "brand": {"id": p.brand_id, "name": p.brand.name},
            "category": {"id": p.category_id, "name": p.category.name},
            "packaging_type": p.packaging_type,
            "photo_url": p.photo.url if p.photo else None,
            "applicability": applicability,
        }
        return json_ok(data)

    if request.method in ("PUT", "PATCH"):
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        before = (
            Product.objects.select_related("brand", "category")
            .prefetch_related("applicability__make")
            .get(pk=p.pk)
        )
        changed_data: list[str] = []
        for field in ["internal_sku", "name", "oem_number", "analog_number"]:
            if field in payload:
                setattr(p, field, payload[field])
                changed_data.append(field)
        for field in ["brand_id", "category_id"]:
            if field in payload:
                setattr(p, field, payload[field])
                changed_data.append("brand" if field == "brand_id" else "category")
        try:
            validate_product_numbers_uniqueness(
                oem_number=p.oem_number,
                analog_number=p.analog_number,
                exclude_id=p.pk,
            )
        except ValidationError as e:
            return json_error(str(e), status=400, code="validation_error")
        try:
            p.save()
        except Exception as e:
            return json_error(f"Failed to update product: {e}", status=400, code="update_error")

        after = (
            Product.objects.select_related("brand", "category")
            .prefetch_related("applicability__make")
            .get(pk=p.pk)
        )
        changes = build_product_changes(
            before=before,
            after=after,
            action=ProductChangeLog.Action.UPDATE,
            changed_data=changed_data,
        )
        log_product_change(
            product=after,
            user=user_or_resp,
            action=ProductChangeLog.Action.UPDATE,
            changes=changes,
            source="api",
        )

        return json_ok({"id": p.id})

    if request.method == "DELETE":
        p.delete()
        return json_ok({"deleted": True})

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def product_xrefs_list(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    # ensure product exists
    if not Product.objects.filter(pk=pk).exists():
        return json_error("Not found", status=404, code="not_found")

    q = (request.GET.get("q") or "").strip()
    qs = ProductCrossReference.objects.select_related("to_product").filter(from_product_id=pk)
    if q:
        qs = qs.filter(
            Q(to_product__internal_sku__icontains=q)
            | Q(to_product__name__icontains=q)
            | Q(relation_type__icontains=q)
            | Q(note__icontains=q)
        )
    qs = qs.order_by("relation_type", "to_product__name")
    items, page = paginate(request, qs)
    data = [
        {
            "id": x.id,
            "relation_type": x.relation_type,
            "note": x.note,
            "to_product": {"id": x.to_product_id, "internal_sku": x.to_product.internal_sku, "name": x.to_product.name},
        }
        for x in items
    ]
    return json_ok({"items": data, "page": page})


def receivings_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    if request.method == "GET":
        status = (request.GET.get("status") or "").strip()
        q = (request.GET.get("q") or "").strip()
        qs = Receiving.objects.all().order_by("-id")
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(supplier_name__icontains=q)
                | Q(supplier_doc_no__icontains=q)
                | Q(created_by__username__icontains=q)
            )
        items, page = paginate(request, qs)
        data = [
            {
                "id": r.id,
                "number": r.number,
                "supplier_name": r.supplier_name,
                "supplier_doc_no": r.supplier_doc_no,
                "status": r.status,
            }
            for r in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        for field in ["number", "supplier_name"]:
            if not payload.get(field):
                return json_error(f"Missing field {field}", status=400, code="validation_error")

        try:
            r = Receiving.objects.create(
                number=payload["number"],
                supplier_name=payload["supplier_name"],
                supplier_doc_no=payload.get("supplier_doc_no") or "",
                created_by=user_or_resp,
            )
        except Exception as e:
            return json_error(f"Failed to create receiving: {e}", status=400, code="creation_error")

        return json_ok({"id": r.id}, status=201)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def receiving_detail_api(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        r = Receiving.objects.get(pk=pk)
    except Receiving.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        data = {
            "id": r.id,
            "number": r.number,
            "supplier_name": r.supplier_name,
            "supplier_doc_no": r.supplier_doc_no,
            "status": r.status,
        }
        return json_ok(data)

    if request.method in ("PUT", "PATCH"):
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        if "status" in payload and payload["status"] in ReceivingStatus.values:
            r.status = payload["status"]
        if "supplier_doc_no" in payload:
            r.supplier_doc_no = payload["supplier_doc_no"] or ""
        try:
            r.save()
        except Exception as e:
            return json_error(f"Failed to update receiving: {e}", status=400, code="update_error")
        return json_ok({"id": r.id})

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def receiving_lines_list_create(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        r = Receiving.objects.get(pk=pk)
    except Receiving.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        qs = ReceivingLine.objects.select_related("product", "storage_location").filter(receiving=r)
        q = (request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(product__internal_sku__icontains=q)
                | Q(product__name__icontains=q)
                | Q(product__oem_number__icontains=q)
                | Q(storage_location__code__icontains=q)
                | Q(supplier_sku__icontains=q)
            )
        items, page = paginate(request, qs)
        data = [
            {
                "id": line.id,
                "product": {
                    "id": line.product_id,
                    "internal_sku": line.product.internal_sku,
                    "name": line.product.name,
                    "oem_number": line.product.oem_number,
                },
                "supplier_sku": line.supplier_sku,
                "qty_expected": str(line.qty_expected),
                "qty_received": str(line.qty_received),
                "storage_location": str(line.storage_location) if line.storage_location else None,
                "has_serial_numbers": line.has_serial_numbers,
            }
            for line in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        required = ["product_id", "qty_expected", "supplier_sku"]
        missing = [f for f in required if not payload.get(f)]
        if missing:
            return json_error(f"Missing fields: {', '.join(missing)}", status=400, code="validation_error")

        try:
            qty_expected = _parse_piece_qty(payload.get("qty_expected"), "qty_expected", allow_zero=False)
            qty_received = _parse_piece_qty(payload.get("qty_received", 0), "qty_received", allow_zero=True)
        except ValueError as e:
            return json_error(str(e), status=400, code="validation_error")

        try:
            line = ReceivingLine(
                receiving=r,
                product_id=payload["product_id"],
                supplier_sku=payload.get("supplier_sku") or "",
                qty_expected=qty_expected,
                qty_received=qty_received,
            )
            if not line.storage_location and line.product_id:
                loc = suggest_storage_location(line.product)
                if loc:
                    line.storage_location = loc
            line.save()
        except Exception as e:
            return json_error(f"Failed to create line: {e}", status=400, code="creation_error")

        return json_ok({"id": line.id}, status=201)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def receiving_scan(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        r = Receiving.objects.get(pk=pk)
    except Receiving.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method != "POST":
        return json_error("Method not allowed", status=405, code="method_not_allowed")

    try:
        payload = parse_json(request)
    except ValueError as e:
        return json_error(str(e), status=400)

    barcode = (payload.get("barcode") or "").strip()
    try:
        qty = _parse_piece_qty(payload.get("qty", 1), "qty", allow_zero=False)
    except ValueError as e:
        return json_error(str(e), status=400, code="validation_error")
    if not barcode:
        return json_error("Missing field barcode", status=400, code="validation_error")

    prod_qs = Product.objects.filter(
        Q(oem_number=barcode) | Q(internal_sku=barcode) | Q(analog_number=barcode)
    )
    count = prod_qs.count()
    if count == 0:
        return json_error("Product not found for barcode", status=404, code="not_found")
    if count > 1:
        return json_error("Barcode is ambiguous, multiple products found", status=400, code="ambiguous_barcode")

    product = prod_qs.first()

    line, _created = ReceivingLine.objects.get_or_create(
        receiving=r,
        product=product,
        supplier_sku=barcode,
        defaults={"qty_expected": 0, "qty_received": 0},
    )
    line.qty_expected = (line.qty_expected or 0) + qty
    line.qty_received = (line.qty_received or 0) + qty
    if not line.storage_location:
        loc = suggest_storage_location(product)
        if loc:
            line.storage_location = loc
    line.save()

    return json_ok(
        {
            "id": line.id,
            "product": {
                "id": product.id,
                "internal_sku": product.internal_sku,
                "name": product.name,
                "oem_number": product.oem_number,
            },
            "qty_expected": str(line.qty_expected),
            "qty_received": str(line.qty_received),
            "storage_location": str(line.storage_location) if line.storage_location else None,
        }
    )


def receiving_action(request: HttpRequest, pk: int, action: str):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    if request.method != "POST":
        return json_error("Method not allowed", status=405, code="method_not_allowed")
    try:
        receiving = Receiving.objects.get(pk=pk)
    except Receiving.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if action == "start":
        if receiving.status == ReceivingStatus.DRAFT:
            receiving.status = ReceivingStatus.IN_PROGRESS
            receiving.save(update_fields=["status"])
            return json_ok({"success": True, "status": receiving.status})
        return json_error("Receiving cannot be started", status=400, code="validation_error")

    if action == "complete":
        ok, messages = ReceivingService.complete_receiving(receiving)
        if not ok:
            return json_error("; ".join(messages), status=400, code="validation_error")
        return json_ok({"success": True, "messages": messages, "status": receiving.status})

    return json_error("Unknown action", status=400, code="validation_error")


def stock_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    q = (request.GET.get("q") or "").strip()
    product_id = (request.GET.get("product_id") or "").strip()
    location_id = (request.GET.get("location_id") or "").strip()

    qs = Stock.objects.select_related("product", "storage_location").all()

    if product_id.isdigit():
        qs = qs.filter(product_id=int(product_id))
    if location_id.isdigit():
        qs = qs.filter(storage_location_id=int(location_id))
    if q:
        qs = qs.filter(
            Q(product__internal_sku__icontains=q)
            | Q(product__name__icontains=q)
            | Q(product__oem_number__icontains=q)
            | Q(storage_location__code__icontains=q)
        )

    items, page = paginate(request, qs)
    data = [
        {
            "id": s.id,
            "product": {
                "id": s.product_id,
                "internal_sku": s.product.internal_sku,
                "name": s.product.name,
                "oem_number": s.product.oem_number,
            },
            "storage_location": {
                "id": s.storage_location_id,
                "code": s.storage_location.code,
                "zone": s.storage_location.zone.name if s.storage_location.zone else None,
            },
            "qty_available": str(s.qty_available),
            "qty_reserved": str(s.qty_reserved),
            "batch_no": s.batch_no,
        }
        for s in items
    ]
    return json_ok({"items": data, "page": page})


def stock_analogs(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        product = Product.objects.get(pk=pk)
    except Product.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    try:
        qty_needed = _parse_piece_qty(request.GET.get("qty", "1") or "1", "qty", allow_zero=False)
    except ValueError as e:
        return json_error(str(e), status=400, code="validation_error")
    analogs = find_analog_on_stock(product, qty_needed)

    data = [
        {
            "product": {
                "id": ap.id,
                "internal_sku": ap.internal_sku,
                "name": ap.name,
                "oem_number": ap.oem_number,
            },
            "stock": {
                "id": st.id,
                "storage_location": st.storage_location.code,
                "qty_available": str(st.qty_available),
            },
            "qty_available": str(qty),
        }
        for ap, st, qty in analogs
    ]
    return json_ok({"items": data})


def inventories_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    if request.method == "GET":
        status = (request.GET.get("status") or "").strip()
        q = (request.GET.get("q") or "").strip()
        qs = Inventory.objects.select_related("zone", "created_by").all().order_by("-id")
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(zone__name__icontains=q)
                | Q(created_by__username__icontains=q)
            )

        items, page = paginate(request, qs)
        data = [
            {
                "id": inv.id,
                "number": inv.number,
                "zone": inv.zone.name if inv.zone else None,
                "zone_id": inv.zone_id,
                "status": inv.status,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        number = (payload.get("number") or "").strip()
        if not number:
            return json_error("Missing field number", status=400, code="validation_error")
        zone_id = payload.get("zone_id")
        zone = None
        if zone_id not in (None, ""):
            try:
                zone = StorageZone.objects.get(pk=int(zone_id))
            except (StorageZone.DoesNotExist, TypeError, ValueError):
                return json_error("Zone not found", status=404, code="not_found")
        try:
            inv = Inventory.objects.create(number=number, zone=zone, created_by=user_or_resp)
            TaskService.create_inventory_task(inv, user_or_resp)
        except Exception as e:
            return json_error(f"Failed to create inventory: {e}", status=400, code="creation_error")
        return json_ok({"id": inv.id}, status=201)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def inventory_detail_api(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        inv = Inventory.objects.select_related("zone", "created_by").get(pk=pk)
    except Inventory.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        data = {
            "id": inv.id,
            "number": inv.number,
            "zone": (
                {"id": inv.zone_id, "code": inv.zone.code, "name": inv.zone.name}
                if inv.zone_id and inv.zone
                else None
            ),
            "status": inv.status,
            "started_at": inv.started_at.isoformat() if inv.started_at else None,
            "completed_at": inv.completed_at.isoformat() if inv.completed_at else None,
            "created_by": {"id": inv.created_by_id, "username": inv.created_by.username},
        }
        return json_ok(data)

    if request.method in ("PUT", "PATCH"):
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)
        if "status" in payload:
            status = str(payload.get("status") or "").strip()
            if status in dict(Inventory._meta.get_field("status").choices):
                inv.status = status
            else:
                return json_error("Invalid status", status=400, code="validation_error")
        if "number" in payload and payload.get("number"):
            inv.number = str(payload["number"]).strip()
        try:
            inv.save()
        except Exception as e:
            return json_error(f"Failed to update inventory: {e}", status=400, code="update_error")
        return json_ok({"id": inv.id})

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def inventory_lines_list_create(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        inv = Inventory.objects.get(pk=pk)
    except Inventory.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        lines = inv.lines.select_related("product", "storage_location").all().order_by("id")
        if q:
            lines = lines.filter(
                Q(product__internal_sku__icontains=q)
                | Q(product__name__icontains=q)
                | Q(storage_location__code__icontains=q)
            )
        items, page = paginate(request, lines)
        data = [
            {
                "id": line.id,
                "product": {
                    "id": line.product_id,
                    "internal_sku": line.product.internal_sku,
                    "name": line.product.name,
                },
                "storage_location": {
                    "id": line.storage_location_id,
                    "code": line.storage_location.code,
                },
                "qty_book": str(line.qty_book),
                "qty_actual": str(line.qty_actual) if line.qty_actual is not None else None,
                "discrepancy": str(line.discrepancy),
            }
            for line in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        required = ["product_id", "location_id", "qty_actual"]
        missing = [f for f in required if payload.get(f) in (None, "")]
        if missing:
            return json_error(f"Missing fields: {', '.join(missing)}", status=400, code="validation_error")
        try:
            qty_actual = _parse_piece_qty(payload.get("qty_actual"), "qty_actual", allow_zero=True)
            product = Product.objects.get(pk=int(payload["product_id"]))
            location = StorageLocation.objects.get(pk=int(payload["location_id"]))
        except ValueError as e:
            return json_error(str(e), status=400, code="validation_error")
        except (Product.DoesNotExist, StorageLocation.DoesNotExist):
            return json_error("Product or location not found", status=404, code="not_found")

        stock = Stock.objects.filter(product=product, storage_location=location).first()
        qty_book = stock.qty_available if stock else Decimal("0")
        line, created = InventoryLine.objects.update_or_create(
            inventory=inv,
            product=product,
            storage_location=location,
            defaults={"qty_book": qty_book, "qty_actual": qty_actual},
        )
        return json_ok({"id": line.id}, status=201 if created else 200)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def inventory_action(request: HttpRequest, pk: int, action: str):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    if request.method != "POST":
        return json_error("Method not allowed", status=405, code="method_not_allowed")
    try:
        inv = Inventory.objects.get(pk=pk)
    except Inventory.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if action == "start":
        ok, messages = InventoryService.start_inventory(inv, user_or_resp)
    elif action == "complete":
        ok, messages = InventoryService.complete_inventory(inv, user_or_resp)
    else:
        return json_error("Unknown action", status=400, code="validation_error")
    if not ok:
        return json_error("; ".join(messages), status=400, code="validation_error")
    return json_ok({"success": True, "messages": messages, "status": inv.status})


def orders_list_create(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    if request.method == "GET":
        status = (request.GET.get("status") or "").strip()
        q = (request.GET.get("q") or "").strip()
        qs = Order.objects.select_related("created_by", "picked_by").all().order_by("-id")
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(customer_name__icontains=q)
                | Q(customer_phone__icontains=q)
                | Q(customer_email__icontains=q)
                | Q(external_id__icontains=q)
            )

        items, page = paginate(request, qs)
        data = [
            {
                "id": o.id,
                "number": o.number,
                "customer_name": o.customer_name,
                "customer_phone": o.customer_phone,
                "customer_email": o.customer_email,
                "status": o.status,
                "source": o.source,
                "external_id": o.external_id,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        required = ["number", "customer_name"]
        missing = [f for f in required if not payload.get(f)]
        if missing:
            return json_error(f"Missing fields: {', '.join(missing)}", status=400, code="validation_error")

        try:
            order = Order.objects.create(
                number=payload["number"],
                customer_name=payload["customer_name"],
                customer_phone=payload.get("customer_phone") or "",
                customer_email=payload.get("customer_email") or "",
                source=payload.get("source") or "API",
                external_id=payload.get("external_id") or "",
                created_by=user_or_resp,
            )
            return json_ok({"id": order.id}, status=201)
        except Exception as e:
            return json_error(f"Failed to create order: {e}", status=400, code="creation_error")

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def order_detail_update(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        lines = order.lines.select_related("product").all()
        data = {
            "id": order.id,
            "number": order.number,
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "customer_email": order.customer_email,
            "status": order.status,
            "source": order.source,
            "external_id": order.external_id,
            "lines": [
                {
                    "id": line.id,
                    "product": {
                        "id": line.product_id,
                        "internal_sku": line.product.internal_sku,
                        "name": line.product.name,
                        "oem_number": line.product.oem_number,
                    },
                    "qty_ordered": str(line.qty_ordered),
                    "qty_picked": str(line.qty_picked),
                    "price": str(line.price) if line.price else None,
                }
                for line in lines
            ],
        }
        return json_ok(data)

    if request.method in ("PUT", "PATCH"):
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        if "status" in payload:
            if payload["status"] in OrderStatus.values:
                order.status = payload["status"]
                order.save(update_fields=["status"])

        return json_ok({"id": order.id})

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def order_action(request: HttpRequest, pk: int, action: str):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    if request.method != "POST":
        return json_error("Method not allowed", status=405, code="method_not_allowed")
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if action == "confirm":
        ok, messages = OrderService.confirm_order(order)
        if not ok:
            return json_error("; ".join(messages), status=400, code="validation_error")
        return json_ok({"success": True, "messages": messages, "status": order.status})

    if action == "ship":
        ok, messages = OrderService.ship_order(order, user_or_resp)
        if not ok:
            return json_error("; ".join(messages), status=400, code="validation_error")
        return json_ok({"success": True, "messages": messages, "status": order.status})

    return json_error("Unknown action", status=400, code="validation_error")


def order_lines_list_create(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        lines = order.lines.select_related("product").all()
        if q:
            lines = lines.filter(
                Q(product__internal_sku__icontains=q)
                | Q(product__name__icontains=q)
                | Q(product__oem_number__icontains=q)
            )
        items, page = paginate(request, lines)
        data = [
            {
                "id": line.id,
                "product": {
                    "id": line.product_id,
                    "internal_sku": line.product.internal_sku,
                    "name": line.product.name,
                    "oem_number": line.product.oem_number,
                },
                "qty_ordered": str(line.qty_ordered),
                "qty_picked": str(line.qty_picked),
                "price": str(line.price) if line.price else None,
            }
            for line in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        required = ["product_id", "qty_ordered"]
        missing = [f for f in required if not payload.get(f)]
        if missing:
            return json_error(f"Missing fields: {', '.join(missing)}", status=400, code="validation_error")

        try:
            qty_ordered = _parse_piece_qty(payload.get("qty_ordered"), "qty_ordered", allow_zero=False)
        except ValueError as e:
            return json_error(str(e), status=400, code="validation_error")

        try:
            product = Product.objects.get(pk=payload["product_id"])
            line, created = OrderLine.objects.update_or_create(
                order=order,
                product=product,
                defaults={
                    "qty_ordered": qty_ordered,
                    "price": payload.get("price"),
                },
            )
            return json_ok({"id": line.id}, status=201 if created else 200)
        except Product.DoesNotExist:
            return json_error("Product not found", status=404, code="not_found")
        except Exception as e:
            return json_error(f"Failed to create line: {e}", status=400, code="creation_error")

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def picking_tasks_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    status = (request.GET.get("status") or "").strip()
    zone_type = (request.GET.get("zone_type") or "").strip()
    order_id = (request.GET.get("order_id") or "").strip()
    q = (request.GET.get("q") or "").strip()

    qs = PickingTask.objects.select_related("order", "assigned_to").all()

    if status and status in PickingTaskStatus.values:
        qs = qs.filter(status=status)
    if zone_type:
        qs = qs.filter(zone_type_code=zone_type)
    if order_id.isdigit():
        qs = qs.filter(order_id=int(order_id))
    if q:
        qs = qs.filter(
            Q(order__number__icontains=q)
            | Q(order__customer_name__icontains=q)
            | Q(zone_type_code__icontains=q)
            | Q(assigned_to__username__icontains=q)
        )

    items, page = paginate(request, qs.order_by("-id"))
    data = [
        {
            "id": t.id,
            "order": {"id": t.order_id, "number": t.order.number},
            "zone_type_code": t.zone_type_code,
            "status": t.status,
            "assigned_to": t.assigned_to.username if t.assigned_to else None,
        }
        for t in items
    ]
    return json_ok({"items": data, "page": page})


def picking_task_detail_api(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    try:
        task = PickingTask.objects.select_related("order", "assigned_to").get(pk=pk)
    except PickingTask.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        data = {
            "id": task.id,
            "order": {
                "id": task.order_id,
                "number": task.order.number,
                "status": task.order.status,
            },
            "zone_type_code": task.zone_type_code,
            "status": task.status,
            "assigned_to": (
                {"id": task.assigned_to_id, "username": task.assigned_to.username}
                if task.assigned_to_id and task.assigned_to
                else None
            ),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
        return json_ok(data)

    if request.method in ("PUT", "PATCH"):
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)
        if "assigned_to_id" in payload:
            assigned_to_id = payload.get("assigned_to_id")
            if assigned_to_id in (None, ""):
                task.assigned_to = None
            else:
                try:
                    task.assigned_to = User.objects.get(pk=int(assigned_to_id))
                except (User.DoesNotExist, TypeError, ValueError):
                    return json_error("User not found", status=404, code="not_found")
        if "status" in payload:
            status = str(payload.get("status") or "").strip()
            if status in PickingTaskStatus.values:
                task.status = status
                if status == PickingTaskStatus.IN_PROGRESS and not task.started_at:
                    task.started_at = timezone.now()
                if status == PickingTaskStatus.COMPLETED and not task.completed_at:
                    task.completed_at = timezone.now()
        task.save()
        return json_ok({"id": task.id})

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def picking_task_lines_list_create(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    try:
        task = PickingTask.objects.select_related("order").get(pk=pk)
    except PickingTask.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        qs = task.lines.select_related("order_line", "order_line__product", "stock", "stock__storage_location")
        if q:
            qs = qs.filter(
                Q(order_line__product__internal_sku__icontains=q)
                | Q(order_line__product__name__icontains=q)
                | Q(order_line__product__oem_number__icontains=q)
                | Q(stock__storage_location__code__icontains=q)
            )
        items, page = paginate(request, qs.order_by("-id"))
        data = [
            {
                "id": line.id,
                "order_line_id": line.order_line_id,
                "product": {
                    "id": line.order_line.product_id,
                    "internal_sku": line.order_line.product.internal_sku,
                    "name": line.order_line.product.name,
                },
                "stock_id": line.stock_id,
                "storage_location": line.stock.storage_location.code,
                "qty_picked": str(line.qty_picked),
                "scanned_oem": line.scanned_oem,
            }
            for line in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)
        required = ["order_line_id", "stock_id", "qty_picked"]
        missing = [f for f in required if payload.get(f) in (None, "")]
        if missing:
            return json_error(f"Missing fields: {', '.join(missing)}", status=400, code="validation_error")
        try:
            qty_picked = _parse_piece_qty(payload.get("qty_picked"), "qty_picked", allow_zero=False)
            order_line = OrderLine.objects.select_related("product").get(pk=int(payload["order_line_id"]), order=task.order)
            stock = Stock.objects.select_related("product").get(pk=int(payload["stock_id"]))
        except ValueError as e:
            return json_error(str(e), status=400, code="validation_error")
        except (OrderLine.DoesNotExist, Stock.DoesNotExist):
            return json_error("Order line or stock not found", status=404, code="not_found")

        if stock.product_id != order_line.product_id:
            return json_error("Stock product does not match order line product", status=400, code="validation_error")

        line, created = PickingLine.objects.update_or_create(
            task=task,
            order_line=order_line,
            stock=stock,
            defaults={
                "qty_picked": qty_picked,
                "scanned_oem": (payload.get("scanned_oem") or "").strip(),
            },
        )
        order_line.qty_picked = sum(task_line.qty_picked for task_line in order_line.picking_lines.filter(task=task))
        order_line.save(update_fields=["qty_picked"])
        return json_ok({"id": line.id}, status=201 if created else 200)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def picking_task_action(request: HttpRequest, pk: int, action: str):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    if request.method != "POST":
        return json_error("Method not allowed", status=405, code="method_not_allowed")

    try:
        task = PickingTask.objects.get(pk=pk)
    except PickingTask.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if action == "start":
        if task.status == PickingTaskStatus.PENDING:
            task.status = PickingTaskStatus.IN_PROGRESS
            task.started_at = timezone.now()
            if not task.assigned_to:
                task.assigned_to = user_or_resp
            task.save(update_fields=["status", "started_at", "assigned_to"])
            return json_ok({"success": True, "status": task.status})
        return json_error("Task cannot be started", status=400, code="validation_error")

    if action == "complete":
        ok, messages = PickingService.complete_picking_task(task, user_or_resp)
        if not ok:
            return json_error("; ".join(messages), status=400, code="validation_error")
        return json_ok({"success": True, "messages": messages, "status": task.status})

    return json_error("Unknown action", status=400, code="validation_error")


def tasks_list_create(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        task_type = (request.GET.get("type") or "").strip()
        status = (request.GET.get("status") or "").strip()
        priority = (request.GET.get("priority") or "").strip()
        assigned_to = (request.GET.get("assigned_to") or "").strip()

        tasks = TaskService.get_tasks_for_user(user_or_resp).select_related(
            "assigned_to", "created_by", "receiving", "inventory", "order", "picking_task"
        )
        if task_type and task_type in TaskType.values:
            tasks = tasks.filter(task_type=task_type)
        if status and status in TaskStatus.values:
            tasks = tasks.filter(status=status)
        if priority and priority in TaskPriority.values:
            tasks = tasks.filter(priority=priority)
        if assigned_to.isdigit():
            tasks = tasks.filter(assigned_to_id=int(assigned_to))
        if q:
            tasks = tasks.filter(
                Q(title__icontains=q)
                | Q(description__icontains=q)
                | Q(created_by__username__icontains=q)
                | Q(assigned_to__username__icontains=q)
                | Q(order__number__icontains=q)
                | Q(receiving__number__icontains=q)
                | Q(inventory__number__icontains=q)
            )
        items, page = paginate(request, tasks.order_by("-priority", "-created_at"))
        return json_ok({"items": [_serialize_task(task) for task in items], "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)
        required = ["task_type", "title"]
        missing = [f for f in required if not payload.get(f)]
        if missing:
            return json_error(f"Missing fields: {', '.join(missing)}", status=400, code="validation_error")
        task_type = str(payload["task_type"])
        if task_type not in TaskType.values:
            return json_error("Invalid task_type", status=400, code="validation_error")
        priority = str(payload.get("priority") or TaskPriority.NORMAL)
        if priority not in TaskPriority.values:
            priority = TaskPriority.NORMAL
        assigned_to_id = payload.get("assigned_to_id") or None
        if assigned_to_id not in (None, ""):
            try:
                User.objects.get(pk=int(assigned_to_id))
            except (User.DoesNotExist, TypeError, ValueError):
                return json_error("assigned_to_id user not found", status=404, code="not_found")
        try:
            task = Task.objects.create(
                task_type=task_type,
                title=str(payload["title"]).strip(),
                description=str(payload.get("description") or "").strip(),
                status=TaskStatus.PENDING,
                priority=priority,
                receiving_id=payload.get("receiving_id") or None,
                inventory_id=payload.get("inventory_id") or None,
                order_id=payload.get("order_id") or None,
                picking_task_id=payload.get("picking_task_id") or None,
                created_by=user_or_resp,
                assigned_to_id=assigned_to_id,
            )
        except Exception as e:
            return json_error(f"Failed to create task: {e}", status=400, code="creation_error")
        return json_ok({"id": task.id}, status=201)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def task_detail_api(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    try:
        task = Task.objects.select_related(
            "assigned_to", "created_by", "receiving", "inventory", "order", "picking_task"
        ).get(pk=pk)
    except Task.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        return json_ok(_serialize_task(task))

    if request.method in ("PUT", "PATCH"):
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)

        if "title" in payload:
            task.title = str(payload["title"] or "").strip()
        if "description" in payload:
            task.description = str(payload["description"] or "").strip()
        if "status" in payload and payload["status"] in TaskStatus.values:
            task.status = payload["status"]
            if task.status == TaskStatus.IN_PROGRESS and not task.started_at:
                task.started_at = timezone.now()
            if task.status == TaskStatus.COMPLETED and not task.completed_at:
                task.completed_at = timezone.now()
        if "priority" in payload and payload["priority"] in TaskPriority.values:
            task.priority = payload["priority"]
        if "assigned_to_id" in payload:
            assigned_to_id = payload.get("assigned_to_id")
            if assigned_to_id in (None, ""):
                task.assigned_to_id = None
            else:
                try:
                    task.assigned_to = User.objects.get(pk=int(assigned_to_id))
                except (User.DoesNotExist, TypeError, ValueError):
                    return json_error("assigned_to_id user not found", status=404, code="not_found")
        task.save()
        return json_ok({"id": task.id})

    if request.method == "DELETE":
        task.delete()
        return json_ok({"deleted": True})

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def task_action(request: HttpRequest, pk: int, action: str):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    if request.method != "POST":
        return json_error("Method not allowed", status=405, code="method_not_allowed")
    try:
        task = Task.objects.select_related("assigned_to").get(pk=pk)
    except Task.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if action == "start":
        ok = TaskService.assign_task_to_user(task, user_or_resp)
        if not ok:
            return json_error("Cannot start task", status=400, code="validation_error")
        return json_ok({"success": True, "status": task.status})

    if action == "complete":
        ok = TaskService.complete_task(task, user_or_resp)
        if not ok:
            return json_error("Cannot complete task", status=400, code="validation_error")
        return json_ok({"success": True, "status": task.status})

    if action == "cancel":
        task.status = TaskStatus.CANCELLED
        task.save(update_fields=["status"])
        return json_ok({"success": True, "status": task.status})

    return json_error("Unknown action", status=400, code="validation_error")


def task_comments_list_create(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    try:
        task = Task.objects.get(pk=pk)
    except Task.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        comments = task.comments.select_related("author").all().order_by("-created_at")
        items, page = paginate(request, comments)
        data = [
            {
                "id": comment.id,
                "text": comment.text,
                "author": {"id": comment.author_id, "username": comment.author.username},
                "created_at": comment.created_at.isoformat() if comment.created_at else None,
            }
            for comment in items
        ]
        return json_ok({"items": data, "page": page})

    if request.method == "POST":
        try:
            payload = parse_json(request)
        except ValueError as e:
            return json_error(str(e), status=400)
        text = str(payload.get("text") or "").strip()
        if not text:
            return json_error("Missing field text", status=400, code="validation_error")
        comment = TaskComment.objects.create(task=task, author=user_or_resp, text=text)
        return json_ok({"id": comment.id}, status=201)

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def tasks_monitoring_summary(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    now = timezone.now()
    active_orders = Order.objects.filter(
        status__in=[OrderStatus.CONFIRMED, OrderStatus.IN_PICKING, OrderStatus.PICKED]
    ).count()
    pending_picking = PickingTask.objects.filter(status=PickingTaskStatus.PENDING).count()
    in_progress_picking = PickingTask.objects.filter(status=PickingTaskStatus.IN_PROGRESS).count()
    completed_today = PickingTask.objects.filter(
        status=PickingTaskStatus.COMPLETED, completed_at__date=now.date()
    ).count()
    universal_qs = Task.objects.filter(status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
    by_type = list(universal_qs.values("task_type").annotate(count=Count("id")).order_by("-count"))
    by_priority = list(universal_qs.values("priority").annotate(count=Count("id")).order_by("-count"))

    return json_ok(
        {
            "generated_at": now.isoformat(),
            "active_orders": active_orders,
            "pending_picking_tasks": pending_picking,
            "in_progress_picking_tasks": in_progress_picking,
            "completed_picking_tasks_today": completed_today,
            "universal_pending": universal_qs.filter(status=TaskStatus.PENDING).count(),
            "universal_in_progress": universal_qs.filter(status=TaskStatus.IN_PROGRESS).count(),
            "universal_by_type": by_type,
            "universal_by_priority": by_priority,
        }
    )


def warehouses_list_api(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    q = (request.GET.get("q") or "").strip()
    user = user_or_resp
    qs = Warehouse.objects.filter(is_active=True).select_related("branch")
    if not (user.is_superuser or user.role == Roles.INTEGRATION):
        qs = user.get_accessible_warehouses()
    if q:
        qs = qs.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
            | Q(branch__code__icontains=q)
            | Q(branch__name__icontains=q)
        )
    items, page = paginate(request, qs.order_by("branch__code", "code"))
    data = [
        {
            "id": wh.id,
            "code": wh.code,
            "name": wh.name,
            "branch": {"id": wh.branch_id, "code": wh.branch.code, "name": wh.branch.name},
            "access_level": user.get_warehouse_access_level(wh),
            "width_m": float(wh.width_m),
            "length_m": float(wh.length_m),
            "height_m": float(wh.height_m),
        }
        for wh in items
    ]
    return json_ok({"items": data, "page": page})


def warehouse_map_api(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    try:
        warehouse = Warehouse.objects.select_related("branch").get(pk=pk, is_active=True)
    except Warehouse.DoesNotExist:
        return json_error("Warehouse not found", status=404, code="not_found")
    user = user_or_resp
    if not (user.is_superuser or user.role == Roles.INTEGRATION or user.can_access_warehouse(warehouse)):
        return json_error("Access denied", status=403, code="forbidden")

    q = (request.GET.get("q") or "").strip()
    zones = StorageZone.objects.filter(warehouse=warehouse).select_related("zone_type").prefetch_related("locations")
    if q:
        zones = zones.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
            | Q(zone_type__name__icontains=q)
            | Q(locations__code__icontains=q)
        ).distinct()
    zone_items, zone_page = paginate(request, zones.order_by("zone_type__sort_order", "code"))
    zone_ids = [zone.id for zone in zone_items]
    locations = StorageLocation.objects.filter(zone_id__in=zone_ids).select_related("zone")
    by_zone = {}
    for loc in locations:
        by_zone.setdefault(loc.zone_id, []).append(
            {
                "id": loc.id,
                "code": loc.code,
                "name": loc.name,
                "aisle": loc.aisle,
                "rack": loc.rack,
                "shelf": loc.shelf,
                "level": loc.level,
            }
        )
    zones_data = [
        {
            "id": zone.id,
            "code": zone.code,
            "name": zone.name,
            "zone_type": {
                "id": zone.zone_type_id,
                "code": zone.zone_type.code,
                "name": zone.zone_type.name,
            },
            "locations": by_zone.get(zone.id, []),
        }
        for zone in zone_items
    ]
    return json_ok(
        {
            "warehouse": {
                "id": warehouse.id,
                "code": warehouse.code,
                "name": warehouse.name,
                "branch": {"id": warehouse.branch_id, "code": warehouse.branch.code, "name": warehouse.branch.name},
            },
            "zones": zones_data,
            "page": zone_page,
        }
    )


def warehouse_objects_api(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    try:
        warehouse = Warehouse.objects.get(pk=pk, is_active=True)
    except Warehouse.DoesNotExist:
        return json_error("Warehouse not found", status=404, code="not_found")
    user = user_or_resp
    can_access = user.is_superuser or user.role == Roles.INTEGRATION or user.can_access_warehouse(warehouse)
    if not can_access:
        return json_error("Access denied", status=403, code="forbidden")

    if request.method == "GET":
        q = (request.GET.get("q") or "").strip()
        qs = StorageObject.objects.filter(warehouse=warehouse, is_active=True).select_related("storage_location")
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(name__icontains=q)
                | Q(object_type__icontains=q)
                | Q(storage_location__code__icontains=q)
            )
        items, page = paginate(request, qs.order_by("object_type", "code", "id"))
        data = [
            {
                "id": obj.id,
                "object_type": obj.object_type,
                "code": obj.code,
                "name": obj.name,
                "position_x": obj.position_x,
                "position_y": obj.position_y,
                "position_z": obj.position_z,
                "width": obj.width,
                "depth": obj.depth,
                "height": obj.height,
                "rotation_y": obj.rotation_y,
                "storage_location_id": obj.storage_location_id,
            }
            for obj in items
        ]
        return json_ok({"items": data, "page": page})

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def reports_abc_xyz(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    from datetime import timedelta
    from django.utils import timezone

    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    q = (request.GET.get("q") or "").strip()
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    sales_data = (
        OrderLine.objects.filter(
            order__status=OrderStatus.SHIPPED,
            order__shipped_at__date__gte=period_start,
            order__shipped_at__date__lte=period_end,
        )
        .values("product_id", "product__internal_sku", "product__name")
        .annotate(
            total_qty=Sum("qty_picked"),
            total_amount=Sum("qty_picked") * Avg("price"),
        )
        .order_by("-total_amount")
    )

    products_data = []
    for item in sales_data:
        products_data.append(
            {
                "product_id": item["product_id"],
                "product_sku": item["product__internal_sku"],
                "product_name": item["product__name"],
                "qty": Decimal(item["total_qty"] or 0),
                "amount": Decimal(item["total_amount"] or 0),
            }
        )

    abc_classes = calculate_abc_class(products_data)
    xyz_classes = calculate_xyz_class(products_data)

    for item in products_data:
        item["abc_class"] = abc_classes.get(item["product_id"], "-")
        item["xyz_class"] = xyz_classes.get(item["product_id"], "-")
        item["abc_xyz"] = f"{item['abc_class']}{item['xyz_class']}"

    if q:
        query = q.lower()
        products_data = [
            item
            for item in products_data
            if query in (item["product_sku"] or "").lower()
            or query in (item["product_name"] or "").lower()
            or query in (item["abc_class"] or "").lower()
            or query in (item["xyz_class"] or "").lower()
            or query in (item["abc_xyz"] or "").lower()
        ]

    for item in products_data:
        item["qty"] = float(item["qty"] or 0)
        item["amount"] = float(item["amount"] or 0)

    items, page = _paginate_list(request, products_data)
    return json_ok({"items": items, "page": page, "period_start": str(period_start), "period_end": str(period_end)})


def reports_dead_stock(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    days_threshold = _safe_int(request.GET.get("days"), 90, min_value=1, max_value=3650)
    q = (request.GET.get("q") or "").strip()
    dead_stocks = find_dead_stock(days_threshold)
    if q:
        query = q.lower()
        filtered = []
        for item in dead_stocks:
            location = getattr(item.get("stock"), "storage_location", None)
            zone = getattr(location, "zone", None)
            if (
                query in (item["product"].internal_sku or "").lower()
                or query in (item["product"].name or "").lower()
                or query in (getattr(location, "code", "") or "").lower()
                or query in (getattr(zone, "name", "") or "").lower()
            ):
                filtered.append(item)
        dead_stocks = filtered

    data = [
        {
            "product_id": item["product"].id,
            "product_sku": item["product"].internal_sku,
            "product_name": item["product"].name,
            "stock_id": item["stock"].id,
            "location_code": item["stock"].storage_location.code,
            "qty_available": float(item["qty_available"]),
            "days_without_movement": item["days_without_movement"],
            "estimated_value": float(item["estimated_value"] or 0),
        }
        for item in dead_stocks
    ]
    items, page = _paginate_list(request, data)
    return json_ok({"items": items, "page": page, "days_threshold": days_threshold})


def reports_analogs_vs_originals(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    from datetime import timedelta
    from django.utils import timezone

    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    q = (request.GET.get("q") or "").strip()
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    analysis = analyze_analogs_vs_originals(period_start, period_end)
    if q:
        query = q.lower()
        analysis = [
            item
            for item in analysis
            if query in (item["original_product"].internal_sku or "").lower()
            or query in (item["original_product"].name or "").lower()
            or query in (item["analog_product"].internal_sku or "").lower()
            or query in (item["analog_product"].name or "").lower()
        ]

    data = [
        {
            "original_product": {
                "id": item["original_product"].id,
                "internal_sku": item["original_product"].internal_sku,
                "name": item["original_product"].name,
            },
            "analog_product": {
                "id": item["analog_product"].id,
                "internal_sku": item["analog_product"].internal_sku,
                "name": item["analog_product"].name,
            },
            "original_sales_qty": float(item["original_sales_qty"]),
            "analog_sales_qty": float(item["analog_sales_qty"]),
            "original_sales_amount": float(item["original_sales_amount"]),
            "analog_sales_amount": float(item["analog_sales_amount"]),
            "substitution_rate": float(item["substitution_rate"]),
        }
        for item in analysis
    ]
    items, page = _paginate_list(request, data)
    return json_ok({"items": items, "page": page, "period_start": str(period_start), "period_end": str(period_end)})


def reports_picking_errors(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    from datetime import timedelta
    from django.utils import timezone
    from reports.models import PickingError

    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    q = (request.GET.get("q") or "").strip()
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    errors_qs = PickingError.objects.filter(
        detected_at__date__gte=period_start,
        detected_at__date__lte=period_end,
    ).select_related("order_line", "expected_product", "actual_product", "detected_by")
    if q:
        errors_qs = errors_qs.filter(
            Q(order_line__order__number__icontains=q)
            | Q(order_line__product__internal_sku__icontains=q)
            | Q(expected_product__internal_sku__icontains=q)
            | Q(expected_product__name__icontains=q)
            | Q(actual_product__internal_sku__icontains=q)
            | Q(actual_product__name__icontains=q)
            | Q(detected_by__username__icontains=q)
            | Q(error_type__icontains=q)
            | Q(notes__icontains=q)
        )
    summary = {
        "total_errors": errors_qs.count(),
        "resolved_errors": errors_qs.filter(resolved=True).count(),
    }
    summary["unresolved_errors"] = summary["total_errors"] - summary["resolved_errors"]
    summary["errors_by_type"] = list(errors_qs.values("error_type").annotate(count=Count("id")).order_by("-count"))

    errors, page = paginate(request, errors_qs.order_by("-detected_at"))

    errors_data = [
        {
            "id": e.id,
            "error_type": e.error_type,
            "expected_product": {
                "id": e.expected_product.id,
                "internal_sku": e.expected_product.internal_sku,
                "name": e.expected_product.name,
            },
            "actual_product": {
                "id": e.actual_product.id,
                "internal_sku": e.actual_product.internal_sku,
                "name": e.actual_product.name,
            }
            if e.actual_product
            else None,
            "expected_qty": str(e.expected_qty),
            "actual_qty": str(e.actual_qty) if e.actual_qty else None,
            "detected_at": e.detected_at.isoformat() if e.detected_at else None,
            "detected_by": e.detected_by.username if e.detected_by else None,
            "resolved": e.resolved,
        }
        for e in errors
    ]

    return json_ok(
        {
            "total_errors": summary.get("total_errors", 0),
            "resolved_errors": summary.get("resolved_errors", 0),
            "unresolved_errors": summary.get("unresolved_errors", 0),
            "error_types_count": {item["error_type"]: item["count"] for item in summary.get("errors_by_type", [])},
            "recent_errors": errors_data,
            "page": page,
            "period_start": str(period_start),
            "period_end": str(period_end),
        }
    )


def reports_demand_forecast(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    period_days = _safe_int(request.GET.get("period"), 30, min_value=7, max_value=365)
    forecast_days = _safe_int(request.GET.get("forecast_days"), 7, min_value=1, max_value=90)
    q = (request.GET.get("q") or "").strip()
    forecasts = calculate_demand_forecast(period_days=period_days, forecast_days=forecast_days)
    if q:
        query = q.lower()
        forecasts = [
            item
            for item in forecasts
            if query in (item.get("product_sku") or "").lower()
            or query in (item.get("product_name") or "").lower()
        ]
    items, page = _paginate_list(request, forecasts)
    return json_ok(
        {
            "items": items,
            "page": page,
            "period_days": period_days,
            "forecast_days": forecast_days,
        }
    )


def reports_staff_efficiency(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    role = (request.GET.get("role") or "").strip()
    q = (request.GET.get("q") or "").strip()
    metrics = calculate_staff_efficiency(period_days=period_days, role=role)
    if q:
        query = q.lower()
        metrics = [
            item
            for item in metrics
            if query in (item["user"].username or "").lower()
            or query in (item["user"].get_full_name() or "").lower()
            or query in (item["role"] or "").lower()
        ]

    payload = []
    for item in metrics:
        payload.append(
            {
                "user": {"id": item["user"].id, "username": item["user"].username},
                "role": item["role"],
                "assigned_total": item["assigned_total"],
                "completed_total": item["completed_total"],
                "in_progress_total": item["in_progress_total"],
                "pending_total": item["pending_total"],
                "completion_rate": item["completion_rate"],
                "avg_task_hours": item["avg_task_hours"],
                "picking_completed": item["picking_completed"],
                "receivings_completed": item["receivings_completed"],
                "inventories_completed": item["inventories_completed"],
                "orders_created": item["orders_created"],
                "orders_shipped": item["orders_shipped"],
                "efficiency_score": item["efficiency_score"],
            }
        )

    items, page = _paginate_list(request, payload)
    return json_ok({"items": items, "page": page, "period_days": period_days, "role": role or None})
