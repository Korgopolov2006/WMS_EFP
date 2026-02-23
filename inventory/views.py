from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.constants import Roles
from accounts.permissions import role_required
from catalog.models import Product, StorageLocation
from inventory.forms import InventoryForm
from inventory.models import Inventory, InventoryLine, Stock
from inventory.services import InventoryService, find_analog_on_stock


def _paginate(request: HttpRequest, items, per_page: int = 5):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get("page"))


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def stock_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    product_id = request.GET.get("product_id", "").strip()
    location_id = request.GET.get("location_id", "").strip()

    qs = Stock.objects.select_related("product", "storage_location", "storage_location__zone").all()

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

    qs = qs.order_by("-qty_available", "product__name")
    page_obj = _paginate(request, qs, per_page=5)

    return render(
        request,
        "inventory/stock_list.html",
        {
            "items": page_obj.object_list,
            "q": q,
            "product_id": product_id,
            "location_id": location_id,
            "page_obj": page_obj,
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

    qs = qs.order_by("-id")
    page_obj = _paginate(request, qs, per_page=5)

    return render(
        request,
        "inventory/inventory_list.html",
        {
            "items": page_obj.object_list,
            "q": q,
            "status": status,
            "page_obj": page_obj,
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
        location_id = request.POST.get("location_id", "").strip()
        qty_actual = request.POST.get("qty_actual", "").strip()

        if product_id.isdigit() and location_id.isdigit() and qty_actual:
            try:
                product = Product.objects.get(pk=int(product_id))
                location = StorageLocation.objects.get(pk=int(location_id))
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
                messages.success(request, "Строка добавлена")
                return redirect("inventory_detail", pk=pk)
            except (Product.DoesNotExist, StorageLocation.DoesNotExist):
                messages.error(request, "Ошибка при добавлении строки")
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
