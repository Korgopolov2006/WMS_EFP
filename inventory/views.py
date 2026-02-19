from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.constants import Roles
from accounts.permissions import role_required
from catalog.models import Product, StorageLocation
from inventory.forms import InventoryForm
from inventory.models import Inventory, InventoryLine, Stock
from inventory.services import InventoryService, find_analog_on_stock


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

    return render(
        request,
        "inventory/stock_list.html",
        {
            "items": qs,
            "q": q,
            "product_id": product_id,
            "location_id": location_id,
        },
    )


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def stock_detail(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=pk)
    stock_items = Stock.objects.filter(product=product).select_related("storage_location").order_by("-qty_available")

    total_available = stock_items.aggregate(Sum("qty_available"))["qty_available__sum"] or 0
    total_reserved = stock_items.aggregate(Sum("qty_reserved"))["qty_reserved__sum"] or 0

    analogs_on_stock = find_analog_on_stock(product, total_available)

    return render(
        request,
        "inventory/stock_detail.html",
        {
            "product": product,
            "stock_items": stock_items,
            "total_available": total_available,
            "total_reserved": total_reserved,
            "analogs_on_stock": analogs_on_stock,
        },
    )


@role_required(Roles.ADMIN, Roles.STOREKEEPER)
def inventory_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "").strip()
    qs = Inventory.objects.select_related("zone", "created_by").all()

    if status:
        qs = qs.filter(status=status)

    qs = qs.order_by("-id")

    return render(
        request,
        "inventory/inventory_list.html",
        {
            "items": qs,
            "status": status,
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
    lines = InventoryLine.objects.filter(inventory=inventory).select_related("product", "storage_location").order_by("product__name")

    if request.method == "POST" and "add_line" in request.POST:
        product_id = request.POST.get("product_id", "").strip()
        location_id = request.POST.get("location_id", "").strip()
        qty_actual = request.POST.get("qty_actual", "").strip()

        if product_id.isdigit() and location_id.isdigit() and qty_actual:
            try:
                product = Product.objects.get(pk=int(product_id))
                location = StorageLocation.objects.get(pk=int(location_id))
                qty_actual_val = float(qty_actual)

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
            except (Product.DoesNotExist, StorageLocation.DoesNotExist, ValueError):
                messages.error(request, "Ошибка при добавлении строки")

    return render(
        request,
        "inventory/inventory_detail.html",
        {
            "inventory": inventory,
            "lines": lines,
        },
    )
