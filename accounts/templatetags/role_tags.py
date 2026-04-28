"""
Шаблонные теги/фильтры для проверки прав в HTML.

Использование:
  {% load role_tags %}
  {% if request.user|can:"manage_users" %}<a href="...">Пользователи</a>{% endif %}

  {% if request.user|can_any:"manage_users,view_audit" %}...{% endif %}
"""
from __future__ import annotations

from django import template

from accounts.role_permissions import user_can, user_can_all, user_can_any

register = template.Library()


@register.filter(name="can")
def can(user, action: str) -> bool:
    """{{ user|can:"action_name" }} → True/False."""
    return user_can(user, action)


@register.filter(name="can_any")
def can_any(user, actions: str) -> bool:
    """{{ user|can_any:"a,b,c" }} → True если есть хотя бы одно."""
    items = [a.strip() for a in (actions or "").split(",") if a.strip()]
    return user_can_any(user, items)


@register.filter(name="can_all")
def can_all(user, actions: str) -> bool:
    """{{ user|can_all:"a,b,c" }} → True если есть все."""
    items = [a.strip() for a in (actions or "").split(",") if a.strip()]
    return user_can_all(user, items)
