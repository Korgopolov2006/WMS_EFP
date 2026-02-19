"""
Миксины для Django Admin с разграничением доступа по ролям.
"""

from django.contrib import admin
from django.core.exceptions import PermissionDenied

from accounts.constants import Roles


class RoleBasedAdminMixin:
    """Миксин для разграничения доступа в админке по ролям."""

    # Роли, которым разрешён доступ (по умолчанию только ADMIN)
    allowed_roles = [Roles.ADMIN]

    def has_view_permission(self, request, obj=None):
        """Проверка права на просмотр."""
        if request.user.is_superuser:
            return True
        return request.user.role in self.allowed_roles

    def has_add_permission(self, request):
        """Проверка права на добавление."""
        if request.user.is_superuser:
            return True
        return request.user.role in self.allowed_roles

    def has_change_permission(self, request, obj=None):
        """Проверка права на изменение."""
        if request.user.is_superuser:
            return True
        return request.user.role in self.allowed_roles

    def has_delete_permission(self, request, obj=None):
        """Проверка права на удаление."""
        if request.user.is_superuser:
            return True
        return request.user.role in self.allowed_roles


class ReceivingAdminMixin(RoleBasedAdminMixin):
    """Миксин для админки приёмки."""
    allowed_roles = [Roles.ADMIN, Roles.STOREKEEPER]


class PickingAdminMixin(RoleBasedAdminMixin):
    """Миксин для админки комплектации."""
    allowed_roles = [Roles.ADMIN, Roles.STOREKEEPER, Roles.SMALL_PARTS_PICKER, Roles.LOADER]


class InventoryAdminMixin(RoleBasedAdminMixin):
    """Миксин для админки инвентаризации."""
    allowed_roles = [Roles.ADMIN, Roles.STOREKEEPER]


class ReportsAdminMixin(RoleBasedAdminMixin):
    """Миксин для админки отчётов."""
    allowed_roles = [Roles.ADMIN, Roles.ANALYST]
