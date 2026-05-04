"""
Шаблонные теги для работы с URL.

Использование:
  {% load url_tags %}
  ?{% querystring_replace request sort='name' order='asc' %}
  → собирает URL-encoded строку из всех текущих GET-параметров,
     заменяя/добавляя указанные.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django import template

register = template.Library()


@register.simple_tag
def querystring_replace(request, **overrides) -> str:
    """
    Возвращает строку URL-параметров, объединяя текущие GET с overrides.
    Удаляет ключ если значение равно "" (пусто).
    Также удаляет параметр page при изменении сортировки/фильтра.
    """
    if request is None:
        return urlencode(overrides, doseq=True)

    base = request.GET.copy()
    if "page" in base and "page" not in overrides:
        del base["page"]
    for k, v in overrides.items():
        if v in (None, ""):
            base.pop(k, None)
        else:
            base[k] = v
    return base.urlencode()
