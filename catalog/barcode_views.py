"""
Эндпоинты для штрихкодов / QR / этикеток / сканера.

Использует существующий каркас base.html и стиль (data-table, breadcrumbs).
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import cache_control

from .barcode_service import (
    find_product_by_code,
    get_product_code,
    render_barcode_png,
    render_qr_png,
)
from .models import Product


@login_required
@cache_control(max_age=3600)
def barcode_image(request: HttpRequest, sku: str) -> HttpResponse:
    """PNG штрихкода для товара (Code128 по умолчанию)."""
    product = get_object_or_404(Product, internal_sku=sku)
    code = get_product_code(product)
    if not code:
        raise Http404("Нет значения для штрихкода.")
    fmt = (request.GET.get("fmt") or "code128").lower()
    if fmt not in ("code128", "ean13"):
        return HttpResponseBadRequest("Поддерживаются форматы: code128, ean13.")
    try:
        png = render_barcode_png(code, fmt=fmt)
    except Exception as exc:
        return HttpResponseBadRequest(f"Ошибка генерации штрихкода: {exc}")
    return HttpResponse(png, content_type="image/png")


@login_required
@cache_control(max_age=3600)
def qr_image(request: HttpRequest, sku: str) -> HttpResponse:
    """PNG QR-кода для товара."""
    product = get_object_or_404(Product, internal_sku=sku)
    code = get_product_code(product)
    if not code:
        raise Http404("Нет значения для QR-кода.")
    try:
        png = render_qr_png(code)
    except Exception as exc:
        return HttpResponseBadRequest(f"Ошибка генерации QR: {exc}")
    return HttpResponse(png, content_type="image/png")


@login_required
def label_view(request: HttpRequest, sku: str) -> HttpResponse:
    """HTML-страница этикетки одного товара (готова к печати)."""
    product = get_object_or_404(
        Product.objects.select_related("brand", "category"),
        internal_sku=sku,
    )
    return render(request, "catalog/label.html", {
        "products": [product],
        "single": True,
    })


@login_required
def labels_bulk_view(request: HttpRequest) -> HttpResponse:
    """
    Массовая печать этикеток.
    Параметр: ?ids=1,2,3 (Product.pk через запятую).
    """
    raw = (request.GET.get("ids") or "").strip()
    pks = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    if not pks:
        return HttpResponseBadRequest("Передайте параметр ids=1,2,3.")
    products = list(
        Product.objects.select_related("brand", "category").filter(pk__in=pks)
    )
    return render(request, "catalog/label.html", {
        "products": products,
        "single": False,
    })


@login_required
def scanner_view(request: HttpRequest) -> HttpResponse:
    """Страница сканера через камеру (html5-qrcode)."""
    return render(request, "catalog/scanner.html", {})


@login_required
def lookup_by_code(request: HttpRequest) -> JsonResponse:
    """
    JSON-эндпоинт для сканера: ищет товар по отсканированному коду.
    Возвращает {found: bool, product: {...}}.
    """
    code = (request.GET.get("code") or "").strip()
    if not code:
        return JsonResponse({"found": False, "error": "Пустой код."})
    product = find_product_by_code(code)
    if not product:
        return JsonResponse({"found": False, "code": code})
    return JsonResponse({
        "found": True,
        "code": code,
        "product": {
            "id": product.pk,
            "internal_sku": product.internal_sku,
            "name": product.name,
            "oem_number": product.oem_number,
            "barcode": product.barcode,
            "brand": product.brand.name if product.brand_id else "",
            "label_url": f"/catalog/codes/label/{product.internal_sku}/",
        },
    })
