from __future__ import annotations

from django.db.models import Q, Sum, Avg
from django.http import HttpRequest

from api.auth import ApiAuthError, authenticate_integration
from api.utils import json_error, json_ok, paginate, parse_json
from catalog.models import Brand, Category, Product, ProductCrossReference, VehicleMake, VehicleModel
from inventory.models import Inventory, InventoryLine, Stock
from inventory.services import find_analog_on_stock
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from receiving.models import Receiving, ReceivingLine, ReceivingStatus
from receiving.services import suggest_storage_location
from reports.services import (
    analyze_analogs_vs_originals,
    calculate_abc_class,
    calculate_xyz_class,
    find_dead_stock,
    get_picking_errors_summary,
)


def _require_api_user(request: HttpRequest):
    try:
        user, _token = authenticate_integration(request)
        return user
    except ApiAuthError as e:
        return json_error(str(e), status=401, code="unauthorized")


def health(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp
    return json_ok({"service": "wms-api", "version": "v1"})


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
            p = Product.objects.create(
                internal_sku=payload["internal_sku"],
                name=payload["name"],
                oem_number=payload["oem_number"],
                analog_number=payload.get("analog_number") or "",
                brand_id=payload["brand_id"],
                category_id=payload["category_id"],
            )
        except Exception as e:  # noqa: BLE001
            return json_error(f"Failed to create product: {e}", status=400, code="creation_error")

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

        for field in ["internal_sku", "name", "oem_number", "analog_number"]:
            if field in payload:
                setattr(p, field, payload[field])
        for field in ["brand_id", "category_id"]:
            if field in payload:
                setattr(p, field, payload[field])
        try:
            p.save()
        except Exception as e:  # noqa: BLE001
            return json_error(f"Failed to update product: {e}", status=400, code="update_error")

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

    qs = ProductCrossReference.objects.select_related("to_product").filter(from_product_id=pk).order_by("relation_type")
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
        qs = Receiving.objects.all().order_by("-id")
        if status:
            qs = qs.filter(status=status)
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
        except Exception as e:  # noqa: BLE001
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
        except Exception as e:  # noqa: BLE001
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
            line = ReceivingLine(
                receiving=r,
                product_id=payload["product_id"],
                supplier_sku=payload.get("supplier_sku") or "",
                qty_expected=payload.get("qty_expected") or 0,
                qty_received=payload.get("qty_received") or 0,
            )
            if not line.storage_location and line.product_id:
                loc = suggest_storage_location(line.product)
                if loc:
                    line.storage_location = loc
            line.save()
        except Exception as e:  # noqa: BLE001
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
    qty = payload.get("qty") or 1
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

    qty_needed = float(request.GET.get("qty", "1") or "1")
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

    status = (request.GET.get("status") or "").strip()
    qs = Inventory.objects.select_related("zone", "created_by").all().order_by("-id")
    if status:
        qs = qs.filter(status=status)

    items, page = paginate(request, qs)
    data = [
        {
            "id": inv.id,
            "number": inv.number,
            "zone": inv.zone.name if inv.zone else None,
            "status": inv.status,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in items
    ]
    return json_ok({"items": data, "page": page})


def orders_list_create(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    if request.method == "GET":
        status = (request.GET.get("status") or "").strip()
        qs = Order.objects.select_related("created_by", "picked_by").all().order_by("-id")
        if status:
            qs = qs.filter(status=status)

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
        except Exception as e:  # noqa: BLE001
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


def order_lines_list_create(request: HttpRequest, pk: int):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return json_error("Not found", status=404, code="not_found")

    if request.method == "GET":
        lines = order.lines.select_related("product").all()
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
            product = Product.objects.get(pk=payload["product_id"])
            line, created = OrderLine.objects.update_or_create(
                order=order,
                product=product,
                defaults={
                    "qty_ordered": payload["qty_ordered"],
                    "price": payload.get("price"),
                },
            )
            return json_ok({"id": line.id}, status=201 if created else 200)
        except Product.DoesNotExist:
            return json_error("Product not found", status=404, code="not_found")
        except Exception as e:  # noqa: BLE001
            return json_error(f"Failed to create line: {e}", status=400, code="creation_error")

    return json_error("Method not allowed", status=405, code="method_not_allowed")


def picking_tasks_list(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    status = (request.GET.get("status") or "").strip()
    zone_type = (request.GET.get("zone_type") or "").strip()
    order_id = (request.GET.get("order_id") or "").strip()

    qs = PickingTask.objects.select_related("order", "assigned_to").all()

    if status and status in PickingTaskStatus.values:
        qs = qs.filter(status=status)
    if zone_type:
        qs = qs.filter(zone_type_code=zone_type)
    if order_id.isdigit():
        qs = qs.filter(order_id=int(order_id))

    items, page = paginate(request, qs)
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


def reports_abc_xyz(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    from datetime import timedelta
    from django.utils import timezone

    period_days = int(request.GET.get("period", 30))
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
                "qty": float(item["total_qty"] or 0),
                "amount": float(item["total_amount"] or 0),
            }
        )

    abc_classes = calculate_abc_class(products_data)
    xyz_classes = calculate_xyz_class(products_data)

    for item in products_data:
        item["abc_class"] = abc_classes.get(item["product_id"], "-")
        item["xyz_class"] = xyz_classes.get(item["product_id"], "-")

    return json_ok({"items": products_data, "period_start": str(period_start), "period_end": str(period_end)})


def reports_dead_stock(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    days_threshold = int(request.GET.get("days", 90))
    dead_stocks = find_dead_stock(days_threshold)

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

    return json_ok({"items": data, "days_threshold": days_threshold})


def reports_analogs_vs_originals(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    from datetime import timedelta
    from django.utils import timezone

    period_days = int(request.GET.get("period", 30))
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    analysis = analyze_analogs_vs_originals(period_start, period_end)

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

    return json_ok({"items": data, "period_start": str(period_start), "period_end": str(period_end)})


def reports_picking_errors(request: HttpRequest):
    user_or_resp = _require_api_user(request)
    if not hasattr(user_or_resp, "pk"):
        return user_or_resp

    from datetime import timedelta
    from django.utils import timezone
    from reports.models import PickingError

    period_days = int(request.GET.get("period", 30))
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    summary = get_picking_errors_summary(period_start, period_end)

    errors = (
        PickingError.objects.filter(
            detected_at__date__gte=period_start,
            detected_at__date__lte=period_end,
        )
        .select_related("order_line", "expected_product", "actual_product", "detected_by")
        .order_by("-detected_at")[:100]
    )

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
            "period_start": str(period_start),
            "period_end": str(period_end),
        }
    )

