from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.constants import Roles
from accounts.permissions import role_required

from .forms import (
    BrandForm,
    CategoryForm,
    ProductForm,
    ProductCrossReferenceForm,
    StorageZoneForm,
    StorageLocationForm,
    StorageZoneTypeForm,
    VehicleMakeForm,
    VehicleModelForm,
)
from .models import (
    Brand,
    Category,
    Product,
    ProductCrossReference,
    StorageZone,
    StorageLocation,
    StorageZoneType,
    VehicleMake,
    VehicleModel,
)


@role_required(Roles.ADMIN)
def admin_home(request: HttpRequest) -> HttpResponse:
    return render(request, "catalog/admin/home.html")


def _apply_qs_search(qs: QuerySet, q: str, *fields: str) -> QuerySet:
    if not q:
        return qs
    from django.db.models import Q

    query = Q()
    for f in fields:
        query |= Q(**{f"{f}__icontains": q})
    return qs.filter(query)


@role_required(Roles.ADMIN)
def brand_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    items = _apply_qs_search(Brand.objects.all(), q, "name")
    return render(
        request,
        "catalog/admin/brand_list.html",
        {"items": items, "q": q, "title": "Бренды", "subtitle": "Справочник производителей", "create_url": "catalog_brand_create"},
    )


@role_required(Roles.ADMIN)
def brand_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = BrandForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Бренд создан: {obj}")
            return redirect("catalog_brand_list")
    else:
        form = BrandForm()
    return render(request, "catalog/admin/form.html", {"form": form, "title": "Новый бренд"})


@role_required(Roles.ADMIN)
def brand_update(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(Brand, pk=pk)
    if request.method == "POST":
        form = BrandForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Бренд обновлён: {obj}")
            return redirect("catalog_brand_list")
    else:
        form = BrandForm(instance=obj)
    return render(request, "catalog/admin/form.html", {"form": form, "title": f"Редактирование: {obj}"})


@role_required(Roles.ADMIN)
def category_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    items = _apply_qs_search(Category.objects.select_related("parent").all(), q, "name")
    return render(
        request,
        "catalog/admin/category_list.html",
        {"items": items, "q": q, "title": "Категории", "subtitle": "Классификация номенклатуры", "create_url": "catalog_category_create"},
    )


@role_required(Roles.ADMIN)
def category_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Категория создана: {obj}")
            return redirect("catalog_category_list")
    else:
        form = CategoryForm()
    return render(request, "catalog/admin/form.html", {"form": form, "title": "Новая категория"})


@role_required(Roles.ADMIN)
def category_update(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Категория обновлена: {obj}")
            return redirect("catalog_category_list")
    else:
        form = CategoryForm(instance=obj)
    return render(request, "catalog/admin/form.html", {"form": form, "title": f"Редактирование: {obj}"})


@role_required(Roles.ADMIN)
def vehicle_make_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    items = _apply_qs_search(VehicleMake.objects.all(), q, "name")
    return render(
        request,
        "catalog/admin/vehicle_make_list.html",
        {"items": items, "q": q, "title": "Марки ТС", "subtitle": "适用 — применимость (марка/модель ТС)", "create_url": "catalog_vehicle_make_create"},
    )


@role_required(Roles.ADMIN)
def vehicle_make_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = VehicleMakeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Марка создана: {obj}")
            return redirect("catalog_vehicle_make_list")
    else:
        form = VehicleMakeForm()
    return render(request, "catalog/admin/form.html", {"form": form, "title": "Новая марка ТС"})


@role_required(Roles.ADMIN)
def vehicle_make_update(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(VehicleMake, pk=pk)
    if request.method == "POST":
        form = VehicleMakeForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Марка обновлена: {obj}")
            return redirect("catalog_vehicle_make_list")
    else:
        form = VehicleMakeForm(instance=obj)
    return render(request, "catalog/admin/form.html", {"form": form, "title": f"Редактирование: {obj}"})


@role_required(Roles.ADMIN)
def vehicle_model_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    items = VehicleModel.objects.select_related("make").all()
    if q:
        items = _apply_qs_search(items, q, "name", "make__name")
    return render(
        request,
        "catalog/admin/vehicle_model_list.html",
        {"items": items, "q": q, "title": "Модели ТС", "subtitle": "适用 — применимость (марка/модель ТС)", "create_url": "catalog_vehicle_model_create"},
    )


@role_required(Roles.ADMIN)
def vehicle_model_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = VehicleModelForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Модель создана: {obj}")
            return redirect("catalog_vehicle_model_list")
    else:
        form = VehicleModelForm()
    return render(request, "catalog/admin/form.html", {"form": form, "title": "Новая модель ТС"})


@role_required(Roles.ADMIN)
def vehicle_model_update(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(VehicleModel, pk=pk)
    if request.method == "POST":
        form = VehicleModelForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Модель обновлена: {obj}")
            return redirect("catalog_vehicle_model_list")
    else:
        form = VehicleModelForm(instance=obj)
    return render(request, "catalog/admin/form.html", {"form": form, "title": f"Редактирование: {obj}"})


@role_required(Roles.ADMIN)
def zone_type_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    items = StorageZoneType.objects.all()
    items = _apply_qs_search(items, q, "name", "code")
    return render(
        request,
        "catalog/admin/zone_type_list.html",
        {"items": items, "q": q, "title": "Типы складских зон", "subtitle": "Ячеечный/полки/напольное/тяжеловесы", "create_url": "catalog_zone_type_create"},
    )


@role_required(Roles.ADMIN)
def zone_type_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StorageZoneTypeForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Тип зоны создан: {obj}")
            return redirect("catalog_zone_type_list")
    else:
        form = StorageZoneTypeForm()
    return render(request, "catalog/admin/form.html", {"form": form, "title": "Новый тип складской зоны"})


@role_required(Roles.ADMIN)
def zone_type_update(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(StorageZoneType, pk=pk)
    if request.method == "POST":
        form = StorageZoneTypeForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Тип зоны обновлён: {obj}")
            return redirect("catalog_zone_type_list")
    else:
        form = StorageZoneTypeForm(instance=obj)
    return render(request, "catalog/admin/form.html", {"form": form, "title": f"Редактирование: {obj}"})


@login_required
def storage_map(request: HttpRequest) -> HttpResponse:
    from catalog.models import Warehouse

    view_mode = request.GET.get("view", "table")
    warehouse_id = request.GET.get("warehouse_id")

    accessible_warehouses = request.user.get_accessible_warehouses()

    current_warehouse = None
    zones = StorageZone.objects.none()

    if warehouse_id:
        try:
            warehouse_id_int = int(warehouse_id)
            current_warehouse = accessible_warehouses.filter(pk=warehouse_id_int).first()
            if current_warehouse:
                zones = StorageZone.objects.filter(warehouse=current_warehouse).select_related("zone_type", "warehouse", "warehouse__branch").prefetch_related("locations")
        except (ValueError, Warehouse.DoesNotExist):
            pass

    if not current_warehouse:
        current_warehouse = accessible_warehouses.first()
        if current_warehouse:
            zones = StorageZone.objects.filter(warehouse=current_warehouse).select_related("zone_type", "warehouse", "warehouse__branch").prefetch_related("locations")

    access_level = None
    if current_warehouse:
        access_level = request.user.get_warehouse_access_level(current_warehouse)
        if view_mode == "3d":
            return redirect("warehouse_3d:view", warehouse_id=current_warehouse.id)

    return render(
        request,
        "catalog/admin/storage_map.html",
        {
            "zones": zones,
            "view_mode": view_mode,
            "warehouses": accessible_warehouses,
            "current_warehouse": current_warehouse,
            "access_level": access_level,
        },
    )


@role_required(Roles.ADMIN)
def product_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    items = Product.objects.select_related("brand", "category").all()
    if q:
        items = _apply_qs_search(items, q, "internal_sku", "name", "oem_number", "analog_number", "brand__name")
    return render(
        request,
        "catalog/admin/product_list.html",
        {"items": items, "q": q, "title": "Номенклатура", "subtitle": "Карточки товаров (OEM/аналоги/размеры/упаковка)", "create_url": "catalog_product_create"},
    )


@role_required(Roles.ADMIN)
def product_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Товар создан: {obj}")
            return redirect("catalog_product_list")
    else:
        form = ProductForm()
    return render(request, "catalog/admin/form.html", {"form": form, "title": "Новый товар"})


@role_required(Roles.ADMIN)
def product_update(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Товар обновлён: {obj}")
            return redirect("catalog_product_list")
    else:
        form = ProductForm(instance=obj)
    return render(request, "catalog/admin/product_edit.html", {"form": form, "title": f"Редактирование: {obj}", "product": obj})


@role_required(Roles.ADMIN)
def product_xref(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=pk)
    items = (
        ProductCrossReference.objects.select_related("from_product", "to_product")
        .filter(from_product=product)
        .order_by("relation_type", "to_product__name")
    )

    if request.method == "POST":
        form = ProductCrossReferenceForm(request.POST)
        if form.is_valid():
            xref: ProductCrossReference = form.save(commit=False)
            xref.from_product = product
            xref.save()
            messages.success(request, "Связь добавлена.")
            return redirect("catalog_product_xref", pk=product.pk)
    else:
        form = ProductCrossReferenceForm()

    return render(
        request,
        "catalog/admin/product_xref.html",
        {"product": product, "items": items, "form": form},
    )


@role_required(Roles.ADMIN)
def product_xref_delete(request: HttpRequest, pk: int, xref_id: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=pk)
    xref = get_object_or_404(ProductCrossReference, pk=xref_id, from_product=product)
    if request.method == "POST":
        xref.delete()
        messages.success(request, "Связь удалена.")
    return redirect("catalog_product_xref", pk=product.pk)
