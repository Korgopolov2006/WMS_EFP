from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.constants import Roles
from accounts.permissions import role_required
from catalog.models import Product, StorageLocation
from core.export import ExportColumn, dispatch_export
from inventory.forms import InventoryForm
from inventory.models import (
    Inventory,
    InventoryLine,
    MovementType,
    Stock,
    StockMovement,
)
from inventory.services import find_analog_on_stock


def _paginate(request: HttpRequest, items, per_page: int = 10):
    from core.pagination import paginate_legacy
    return paginate_legacy(request, items, per_page=per_page)


def _format_decimal(value) -> str:
    value = value or Decimal("0")
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return str(value.normalize())


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def stock_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    product_query = (request.GET.get("product") or request.GET.get("product_query") or "").strip()
    location_query = (request.GET.get("location") or request.GET.get("location_query") or "").strip()
    product_id = request.GET.get("product_id", "").strip()
    location_id = request.GET.get("location_id", "").strip()

    qs = Stock.objects.select_related("product", "storage_location", "storage_location__zone").all()

    # Старые ID-параметры оставляем для совместимости со ссылками/интеграциями,
    # но в интерфейсе показываем понятные фильтры по товару и месту.
    if product_id.isdigit():
        qs = qs.filter(product_id=int(product_id))
    if location_id.isdigit():
        qs = qs.filter(storage_location_id=int(location_id))
    if product_query:
        qs = qs.filter(
            Q(product__internal_sku__icontains=product_query)
            | Q(product__name__icontains=product_query)
            | Q(product__oem_number__icontains=product_query)
            | Q(product__barcode__icontains=product_query)
        )
    if location_query:
        qs = qs.filter(
            Q(storage_location__code__icontains=location_query)
            | Q(storage_location__name__icontains=location_query)
            | Q(storage_location__zone__code__icontains=location_query)
            | Q(storage_location__zone__name__icontains=location_query)
        )
    if q:
        qs = qs.filter(
            Q(product__internal_sku__icontains=q)
            | Q(product__name__icontains=q)
            | Q(product__oem_number__icontains=q)
            | Q(product__barcode__icontains=q)
            | Q(storage_location__code__icontains=q)
        )

    from core.sorting import apply_ordering
    qs, sort, order = apply_ordering(qs, request, {
        "sku":      "product__internal_sku",
        "name":     "product__name",
        "oem":      "product__oem_number",
        "location": "storage_location__code",
        "zone":     "storage_location__zone__name",
        "qty":      "qty_available",
        "reserved": "qty_reserved",
        "batch":    "batch_no",
    }, default="qty", default_order="desc")

    export_resp = dispatch_export(
        request, qs, _STOCK_EXPORT_COLUMNS,
        filename="stock", title="Складские остатки",
    )
    if export_resp is not None:
        return export_resp

    page_obj = _paginate(request, qs, per_page=5)

    return render(
        request,
        "inventory/stock_list.html",
        {
            "items": page_obj.object_list,
            "q": q,
            "product_query": product_query,
            "location_query": location_query,
            "product_id": product_id,
            "location_id": location_id,
            "page_obj": page_obj,
            "sort": sort,
            "order": order,
        },
    )


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def stock_detail(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=pk)
    q = (request.GET.get("q") or "").strip()
    stock_items_all = Stock.objects.filter(product=product).select_related("storage_location", "storage_location__zone")
    stock_items = stock_items_all
    if q:
        stock_items = stock_items.filter(
            Q(storage_location__code__icontains=q)
            | Q(storage_location__zone__name__icontains=q)
            | Q(batch_no__icontains=q)
        )
    stock_items = stock_items.order_by("-qty_available")

    total_available = stock_items_all.aggregate(Sum("qty_available"))["qty_available__sum"] or 0
    total_reserved = stock_items_all.aggregate(Sum("qty_reserved"))["qty_reserved__sum"] or 0

    analogs_on_stock = find_analog_on_stock(product, total_available)
    page_obj = _paginate(request, stock_items, per_page=5)

    return render(
        request,
        "inventory/stock_detail.html",
        {
            "product": product,
            "stock_items": page_obj.object_list,
            "total_available": total_available,
            "total_reserved": total_reserved,
            "analogs_on_stock": analogs_on_stock,
            "q": q,
            "page_obj": page_obj,
        },
    )


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def inventory_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    status = request.GET.get("status", "").strip()
    qs = Inventory.objects.select_related("zone", "created_by").all()

    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(number__icontains=q)
            | Q(zone__name__icontains=q)
            | Q(created_by__username__icontains=q)
        )

    from core.sorting import apply_ordering
    qs, sort, order = apply_ordering(qs, request, {
        "number":   "number",
        "zone":     "zone__name",
        "status":   "status",
        "creator":  "created_by__username",
        "created":  "created_at",
        "started":  "started_at",
        "completed": "completed_at",
    }, default="created", default_order="desc")

    page_obj = _paginate(request, qs, per_page=5)

    return render(
        request,
        "inventory/inventory_list.html",
        {
            "items": page_obj.object_list,
            "q": q,
            "status": status,
            "page_obj": page_obj,
            "sort": sort,
            "order": order,
        },
    )


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def inventory_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = InventoryForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()

            # Создаём задачу на инвентаризацию
            from tasks.services import TaskService
            TaskService.create_inventory_task(obj, request.user)

            messages.success(request, f"Инвентаризация создана: {obj.number}")
            return redirect("inventory_detail", pk=obj.pk)
    else:
        form = InventoryForm()

    return render(request, "inventory/inventory_form.html", {"form": form, "title": "Новая инвентаризация"})


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def inventory_detail(request: HttpRequest, pk: int) -> HttpResponse:
    inventory = get_object_or_404(Inventory.objects.select_related("zone", "created_by"), pk=pk)
    q = (request.GET.get("q") or "").strip()
    lines = InventoryLine.objects.filter(inventory=inventory).select_related("product", "storage_location").order_by("product__name")

    if request.method == "POST" and "add_line" in request.POST:
        product_id = request.POST.get("product_id", "").strip()
        product_query = request.POST.get("product_query", "").strip()
        location_id = request.POST.get("location_id", "").strip()
        location_code = request.POST.get("location_code", "").strip()
        qty_actual = request.POST.get("qty_actual", "").strip()

        if qty_actual:
            try:
                product = None
                if product_id.isdigit():
                    product = Product.objects.filter(pk=int(product_id)).first()
                elif product_query:
                    exact_product = Product.objects.filter(
                        Q(internal_sku__iexact=product_query)
                        | Q(oem_number__iexact=product_query)
                        | Q(name__iexact=product_query)
                    ).first()
                    if exact_product:
                        product = exact_product
                    else:
                        product_qs = Product.objects.filter(
                            Q(internal_sku__icontains=product_query)
                            | Q(oem_number__icontains=product_query)
                            | Q(name__icontains=product_query)
                        ).order_by("name")
                        product_matches = list(product_qs[:6])
                        if not product_matches:
                            raise ValueError("Товар не найден. Уточните SKU/OEM/название.")
                        if len(product_matches) > 1:
                            suggestions = ", ".join(f"{p.internal_sku} — {p.name}" for p in product_matches[:3])
                            raise ValueError(f"Найдено несколько товаров. Уточните запрос: {suggestions}")
                        product = product_matches[0]

                if not product:
                    raise ValueError("Укажите товар (поиск по SKU/OEM/названию).")

                location = None
                if location_id.isdigit():
                    location = StorageLocation.objects.filter(pk=int(location_id)).first()
                elif location_code:
                    location_qs = StorageLocation.objects.filter(code__iexact=location_code)
                    if inventory.zone_id:
                        location_qs = location_qs.filter(zone=inventory.zone)
                    location = location_qs.select_related("zone").first()
                    if not location:
                        fuzzy_locations = StorageLocation.objects.filter(code__icontains=location_code)
                        if inventory.zone_id:
                            fuzzy_locations = fuzzy_locations.filter(zone=inventory.zone)
                        location_matches = list(fuzzy_locations.select_related("zone")[:6])
                        if not location_matches:
                            raise ValueError("Место хранения не найдено. Укажите код места (например A01).")
                        if len(location_matches) > 1:
                            suggestions = ", ".join(loc.code for loc in location_matches[:4])
                            raise ValueError(f"Найдено несколько мест. Уточните код: {suggestions}")
                        location = location_matches[0]

                if not location:
                    raise ValueError("Укажите место хранения (по коду).")
                if inventory.zone_id and location.zone_id != inventory.zone_id:
                    raise ValueError("Место хранения должно относиться к зоне инвентаризации.")

                qty_actual_val = Decimal(qty_actual)
                if qty_actual_val != qty_actual_val.to_integral_value():
                    raise ValueError("Фактическое количество должно быть целым числом (шт).")
                if qty_actual_val < 0:
                    raise ValueError("Фактическое количество не может быть отрицательным.")

                stock = Stock.objects.filter(product=product, storage_location=location).first()
                qty_book = stock.qty_available if stock else 0

                InventoryLine.objects.update_or_create(
                    inventory=inventory,
                    product=product,
                    storage_location=location,
                    defaults={"qty_book": qty_book, "qty_actual": qty_actual_val},
                )
                messages.success(request, "Строка инвентаризации сохранена.")
                return redirect("inventory_detail", pk=pk)
            except (InvalidOperation, ValueError) as exc:
                messages.error(request, str(exc))

    if q:
        lines = lines.filter(
            Q(product__internal_sku__icontains=q)
            | Q(product__name__icontains=q)
            | Q(storage_location__code__icontains=q)
        )
    page_obj = _paginate(request, lines, per_page=5)

    return render(
        request,
        "inventory/inventory_detail.html",
        {
            "inventory": inventory,
            "lines": page_obj.object_list,
            "q": q,
            "page_obj": page_obj,
        },
    )


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def inventory_product_hint(request: HttpRequest, pk: int) -> JsonResponse:
    inventory = get_object_or_404(Inventory.objects.select_related("zone"), pk=pk)
    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return JsonResponse({"products": []})

    products = (
        Product.objects.select_related("brand", "category")
        .filter(
            Q(internal_sku__icontains=query)
            | Q(oem_number__icontains=query)
            | Q(barcode__icontains=query)
            | Q(name__icontains=query)
        )
        .order_by("internal_sku")[:8]
    )

    items = []
    for product in products:
        stock_qs = Stock.objects.select_related("storage_location", "storage_location__zone").filter(product=product)
        if inventory.zone_id:
            stock_qs = stock_qs.filter(storage_location__zone=inventory.zone)
        stocks = list(stock_qs.order_by("-qty_available", "storage_location__code")[:8])
        total_qty = sum((stock.qty_available for stock in stocks), Decimal("0"))
        locations = [
            {
                "id": stock.storage_location_id,
                "code": stock.storage_location.code,
                "name": stock.storage_location.name,
                "zone": stock.storage_location.zone.code,
                "qty_book": _format_decimal(stock.qty_available),
            }
            for stock in stocks
        ]
        primary_location = locations[0] if locations else None

        items.append(
            {
                "id": product.pk,
                "sku": product.internal_sku,
                "name": product.name,
                "oem": product.oem_number,
                "barcode": product.barcode or product.internal_sku,
                "brand": product.brand.name if product.brand_id else "",
                "category": product.category.name if product.category_id else "",
                "total_qty": _format_decimal(total_qty),
                "primary_location": primary_location,
                "locations": locations,
                "barcode_url": reverse("catalog_barcode_image", args=[product.internal_sku]),
                "qr_url": reverse("catalog_qr_image", args=[product.internal_sku]),
                "label_url": reverse("catalog_label", args=[product.internal_sku]),
            }
        )

    return JsonResponse({"products": items})


def _parse_date(value: str):
    """YYYY-MM-DD → datetime в локальной TZ или None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    return timezone.make_aware(datetime.combine(d, time.min))


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def movement_list(request: HttpRequest) -> HttpResponse:
    """Журнал движений товара с фильтрами и CSV-экспортом."""
    q = (request.GET.get("q") or "").strip()
    mtype = (request.GET.get("type") or "").strip()
    date_from = _parse_date(request.GET.get("date_from", ""))
    date_to = _parse_date(request.GET.get("date_to", ""))
    location_id = (request.GET.get("location_id") or "").strip()
    user_id = (request.GET.get("user_id") or "").strip()

    qs = StockMovement.objects.select_related(
        "product", "from_location", "to_location", "user"
    ).all()

    if mtype and mtype in MovementType.values:
        qs = qs.filter(movement_type=mtype)
    if date_from:
        qs = qs.filter(created_at__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__lt=date_to + timedelta(days=1))
    if location_id.isdigit():
        loc_id = int(location_id)
        qs = qs.filter(Q(from_location_id=loc_id) | Q(to_location_id=loc_id))
    if user_id.isdigit():
        qs = qs.filter(user_id=int(user_id))
    if q:
        qs = qs.filter(
            Q(product__internal_sku__icontains=q)
            | Q(product__name__icontains=q)
            | Q(product__oem_number__icontains=q)
            | Q(reason__icontains=q)
            | Q(comment__icontains=q)
            | Q(ref_id__icontains=q)
        )

    from core.sorting import apply_ordering
    qs, sort, order = apply_ordering(qs, request, {
        "date":     "created_at",
        "type":     "movement_type",
        "status":   "status",
        "sku":      "product__internal_sku",
        "name":     "product__name",
        "qty":      "quantity",
        "user":     "user__username",
    }, default="date", default_order="desc")

    export_resp = dispatch_export(
        request, qs, _MOVEMENT_EXPORT_COLUMNS,
        filename="movements", title="Журнал движений товара",
    )
    if export_resp is not None:
        return export_resp

    page_obj = _paginate(request, qs, per_page=25)

    return render(
        request,
        "inventory/movement_list.html",
        {
            "items": page_obj.object_list,
            "page_obj": page_obj,
            "q": q,
            "type": mtype,
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "location_id": location_id,
            "user_id": user_id,
            "movement_types": MovementType.choices,
            "sort": sort,
            "order": order,
        },
    )


_STOCK_EXPORT_COLUMNS = [
    ExportColumn("SKU", lambda s: s.product.internal_sku),
    ExportColumn("Товар", lambda s: s.product.name),
    ExportColumn("OEM", lambda s: s.product.oem_number),
    ExportColumn("Бренд", lambda s: s.product.brand.name if s.product.brand_id else ""),
    ExportColumn("Место", lambda s: s.storage_location.code),
    ExportColumn("Зона", lambda s: s.storage_location.zone.name if s.storage_location.zone_id else ""),
    ExportColumn("Доступно", lambda s: s.qty_available),
    ExportColumn("Резерв", lambda s: s.qty_reserved),
    ExportColumn("Партия", lambda s: s.batch_no),
    ExportColumn("Срок годности", lambda s: s.expiry_date.strftime("%Y-%m-%d") if s.expiry_date else ""),
]


_MOVEMENT_EXPORT_COLUMNS = [
    ExportColumn("Дата", lambda m: timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M:%S")),
    ExportColumn("Тип", lambda m: m.get_movement_type_display()),
    ExportColumn("Статус", lambda m: m.get_status_display()),
    ExportColumn("SKU", lambda m: m.product.internal_sku),
    ExportColumn("Товар", lambda m: m.product.name),
    ExportColumn("Кол-во", lambda m: m.quantity),
    ExportColumn("Откуда", lambda m: m.from_location.code if m.from_location else ""),
    ExportColumn("Куда", lambda m: m.to_location.code if m.to_location else ""),
    ExportColumn("Партия", lambda m: m.batch_no),
    ExportColumn("Причина", lambda m: m.reason),
    ExportColumn("Документ", lambda m: f"{m.ref_type}:{m.ref_id}" if m.ref_type or m.ref_id else ""),
    ExportColumn("Пользователь", lambda m: m.user.username if m.user else ""),
    ExportColumn("Комментарий", lambda m: m.comment),
]
