"""
Универсальный хелпер сортировки для list-views.

Использование во view:

    from core.sorting import apply_ordering

    SORT_MAP = {
        "username": "username",
        "email":    "email",
        "joined":   "date_joined",
        "active":   "is_active",
    }

    qs, sort, order = apply_ordering(
        qs, request, SORT_MAP, default="username", default_order="asc",
    )
    # ... передаём в шаблон sort=sort, order=order

В шаблоне:

    {% include "partials/sortable_th.html" with key="username" label="Логин" current=sort order=order %}

URL params: ?sort=<key>&order=asc|desc
"""
from __future__ import annotations


def apply_ordering(
    qs,
    request,
    sort_map: dict[str, str],
    *,
    default: str = "",
    default_order: str = "asc",
) -> tuple:
    """
    qs        — QuerySet
    request   — HttpRequest (читает GET sort/order)
    sort_map  — словарь key (URL) → поле модели (можно с префиксом FK: 'product__name')
    default   — ключ сортировки по умолчанию (когда параметр sort отсутствует)
    default_order — 'asc' | 'desc'
    Возвращает (qs, sort_key, order).
    """
    raw_sort = (request.GET.get("sort") or default or "").strip()
    raw_order = (request.GET.get("order") or default_order or "asc").strip().lower()
    if raw_order not in ("asc", "desc"):
        raw_order = "asc"

    if raw_sort and raw_sort in sort_map:
        field = sort_map[raw_sort]
        prefix = "-" if raw_order == "desc" else ""
        qs = qs.order_by(f"{prefix}{field}")
        return qs, raw_sort, raw_order

    return qs, "", raw_order
