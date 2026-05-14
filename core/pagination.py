"""
Единая утилита пагинации для всех представлений WMS.

Позволяет пользователю выбрать количество записей на страницу через
GET-параметр `per_page` (значения 5, 10, 25, 50, 100).

Использование во view::

    from core.pagination import paginate

    page_obj, per_page = paginate(request, queryset, default_per_page=10)

В шаблоне::

    {% include "partials/pagination.html" with per_page=per_page %}
"""
from __future__ import annotations

from django.core.paginator import Paginator
from django.http import HttpRequest

# Допустимые значения для выбора пользователем.
ALLOWED_PER_PAGE: tuple[int, ...] = (5, 10, 25, 50, 100)

# Значение по умолчанию, если параметр не передан.
DEFAULT_PER_PAGE: int = 10

# Имена GET-параметров.
PER_PAGE_PARAM: str = "per_page"
PAGE_PARAM: str = "page"


def get_per_page(
    request: HttpRequest,
    *,
    default: int = DEFAULT_PER_PAGE,
    param: str = PER_PAGE_PARAM,
) -> int:
    """
    Безопасно извлекает per_page из GET-параметров.
    Если значение не входит в ALLOWED_PER_PAGE — возвращает default.
    """
    raw = request.GET.get(param)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value in ALLOWED_PER_PAGE:
        return value
    return default


def paginate(
    request: HttpRequest,
    items,
    *,
    default_per_page: int = DEFAULT_PER_PAGE,
    page_param: str = PAGE_PARAM,
    per_page_param: str = PER_PAGE_PARAM,
) -> tuple:
    """
    Возвращает кортеж (page_obj, per_page).

    Args:
        request: Django-запрос (откуда читаем page и per_page).
        items: QuerySet или список.
        default_per_page: значение по умолчанию (если в GET нет per_page).
        page_param: имя GET-параметра номера страницы.
        per_page_param: имя GET-параметра размера страницы.

    Returns:
        (page_obj, per_page) — Paginator.get_page() и реально применённый размер.
    """
    per_page = get_per_page(request, default=default_per_page, param=per_page_param)
    paginator = Paginator(items, per_page)
    page_obj = paginator.get_page(request.GET.get(page_param))
    return page_obj, per_page


def paginate_legacy(
    request: HttpRequest,
    items,
    per_page: int = DEFAULT_PER_PAGE,
    page_param: str = PAGE_PARAM,
):
    """
    Совместимая обёртка для старого кода (возвращает только page_obj).

    Сохраняет поведение прежней локальной `_paginate` функции, но при этом
    позволяет пользователю переопределить количество записей через ?per_page=N.
    """
    page_obj, _ = paginate(
        request, items,
        default_per_page=per_page,
        page_param=page_param,
    )
    return page_obj
