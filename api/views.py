"""
API views для внешних интеграций.
"""

from __future__ import annotations

from django.db import models
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from catalog.models import Product


@require_http_methods(["GET"])
def product_search(request: HttpRequest) -> JsonResponse:
    """
    Поиск товаров для интерфейса выбора.
    
    Параметры:
    - q: поисковый запрос (артикул, OEM, название, бренд)
    - limit: максимальное количество результатов (по умолчанию 20)
    """
    query = request.GET.get("q", "").strip()
    limit = int(request.GET.get("limit", 20))

    if not query or len(query) < 2:
        return JsonResponse({"results": []})

    # Поиск по артикулу, OEM, названию, бренду
    products = Product.objects.select_related("brand", "category").filter(
        models.Q(internal_sku__icontains=query) |
        models.Q(oem_number__icontains=query) |
        models.Q(name__icontains=query) |
        models.Q(brand__name__icontains=query)
    )[:limit]

    results = []
    for product in products:
        results.append({
            "id": product.id,
            "internal_sku": product.internal_sku,
            "oem_number": product.oem_number or "",
            "name": product.name,
            "brand": product.brand.name if product.brand else "",
            "category": product.category.name if product.category else "",
            "packaging_type": product.get_packaging_type_display() if product.packaging_type else "",
            "weight_kg": float(product.weight_kg) if product.weight_kg else None,
            "photo": product.photo.url if product.photo else None,
        })

    return JsonResponse({"results": results})
