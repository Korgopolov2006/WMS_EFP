"""
Контекст-процессоры приложения core.

`pagination_settings` — добавляет в каждый шаблон:
    • per_page         — реально применённое число записей на страницу
                         (читается из ?per_page=N или = DEFAULT_PER_PAGE);
    • per_page_options — кортеж допустимых значений для селектора в UI;
    • per_page_param   — имя GET-параметра.

Это позволяет partials/pagination.html отображать селектор «Показать по: 5/10/25/50/100»
на любой странице без правки каждого view.
"""
from __future__ import annotations

from .pagination import (
    ALLOWED_PER_PAGE,
    DEFAULT_PER_PAGE,
    PER_PAGE_PARAM,
    get_per_page,
)


def pagination_settings(request):
    try:
        per_page = get_per_page(request, default=DEFAULT_PER_PAGE)
    except Exception:
        per_page = DEFAULT_PER_PAGE
    return {
        "per_page": per_page,
        "per_page_options": ALLOWED_PER_PAGE,
        "per_page_param": PER_PAGE_PARAM,
        "per_page_default": DEFAULT_PER_PAGE,
    }
