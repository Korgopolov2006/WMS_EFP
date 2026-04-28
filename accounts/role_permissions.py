"""
Декларативная матрица прав: роль → набор именованных разрешений.

Используется:
  • декоратором @requires(...) для views
  • helper'ом user_can(user, action) в коде
  • шаблонным фильтром {{ user|can:"action" }} в HTML

Подход выбран намеренно простой (вместо Django Groups+Permissions):
  • не требует миграции каждый раз при добавлении действия
  • легко покрыть тестами
  • матрицу можно править одним местом — без изменения SQL-схемы
  • совместим с уже существующим accounts.permissions.role_required
"""
from __future__ import annotations

from collections.abc import Iterable

from .constants import Roles


# ── Каталог разрешений ──────────────────────────────────────
# Имена соответствуют разделам/действиям, отображаемым в UI.
# Принцип: ROLE → set действий, которые доступны.

# Универсальные действия (видимость разделов)
SECTION_DASHBOARD = "section_dashboard"
SECTION_RECEIVING = "section_receiving"
SECTION_STOCK = "section_stock"
SECTION_MOVEMENTS = "section_movements"
SECTION_SCANNER = "section_scanner"
SECTION_ORDERS = "section_orders"
SECTION_PICKING = "section_picking"
SECTION_TASKS = "section_tasks"
SECTION_REPORTS = "section_reports"
SECTION_3D = "section_3d"

# Административные
ADMIN_PANEL = "admin_panel"
MANAGE_USERS = "manage_users"
MANAGE_BACKUPS = "manage_backups"
MANAGE_CATALOG = "manage_catalog"
VIEW_AUDIT = "view_audit"
MANAGE_SETTINGS = "manage_settings"

# Операционные действия
WRITE_RECEIVING = "write_receiving"
WRITE_STOCK = "write_stock"
WRITE_INVENTORY = "write_inventory"
WRITE_ORDER = "write_order"
EXPORT_DATA = "export_data"


# Полный набор для удобства тестов
ALL_ACTIONS: tuple[str, ...] = (
    SECTION_DASHBOARD, SECTION_RECEIVING, SECTION_STOCK, SECTION_MOVEMENTS,
    SECTION_SCANNER, SECTION_ORDERS, SECTION_PICKING, SECTION_TASKS,
    SECTION_REPORTS, SECTION_3D,
    ADMIN_PANEL, MANAGE_USERS, MANAGE_BACKUPS, MANAGE_CATALOG, VIEW_AUDIT, MANAGE_SETTINGS,
    WRITE_RECEIVING, WRITE_STOCK, WRITE_INVENTORY, WRITE_ORDER, EXPORT_DATA,
)


# ── Матрица: роль → разрешения ─────────────────────────────

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Roles.ADMIN: frozenset(ALL_ACTIONS),  # ADMIN видит и может всё

    Roles.STOREKEEPER: frozenset({
        SECTION_DASHBOARD, SECTION_RECEIVING, SECTION_STOCK, SECTION_MOVEMENTS,
        SECTION_SCANNER, SECTION_ORDERS, SECTION_TASKS, SECTION_3D,
        WRITE_RECEIVING, WRITE_STOCK, WRITE_INVENTORY, EXPORT_DATA,
    }),

    Roles.SMALL_PARTS_PICKER: frozenset({
        SECTION_DASHBOARD, SECTION_PICKING, SECTION_TASKS, SECTION_SCANNER,
    }),

    Roles.LOADER: frozenset({
        SECTION_DASHBOARD, SECTION_PICKING, SECTION_ORDERS, SECTION_TASKS, SECTION_SCANNER,
    }),

    Roles.SALES_MANAGER: frozenset({
        SECTION_DASHBOARD, SECTION_ORDERS, EXPORT_DATA, WRITE_ORDER,
    }),

    Roles.ANALYST: frozenset({
        SECTION_DASHBOARD, SECTION_REPORTS, SECTION_3D,
        SECTION_STOCK, SECTION_MOVEMENTS, EXPORT_DATA,
    }),

    Roles.INTEGRATION: frozenset({
        # сервисный аккаунт: ничего в UI, только API
    }),
}


# ── Публичный API ─────────────────────────────────────────

def user_can(user, action: str) -> bool:
    """
    True, если у пользователя есть разрешение `action`.

    Логика:
      • Анонимный → False
      • Суперпользователь → всегда True
      • Иначе по матрице ROLE_PERMISSIONS[user.role]
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", "") or ""
    return action in ROLE_PERMISSIONS.get(role, frozenset())


def user_can_any(user, actions: Iterable[str]) -> bool:
    """True, если у пользователя есть хотя бы одно из действий."""
    return any(user_can(user, a) for a in actions)


def user_can_all(user, actions: Iterable[str]) -> bool:
    """True, если у пользователя есть ВСЕ перечисленные действия."""
    return all(user_can(user, a) for a in actions)


def role_label(role_code: str) -> str:
    """Удобная функция для шаблонов: код роли → русское название."""
    from .constants import ROLE_CHOICES
    return dict(ROLE_CHOICES).get(role_code, role_code)
