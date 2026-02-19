from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models

from .constants import ROLE_CHOICES, Roles


class User(AbstractUser):
    """
    Пользователь WMS.

    RBAC-роль хранится явно, чтобы легко использовать в доменной логике и UI.
    Для тонких прав можно дополнительно задействовать Groups/Permissions.
    """

    role = models.CharField(
        "Роль",
        max_length=32,
        choices=ROLE_CHOICES,
        default=Roles.STOREKEEPER,
        db_index=True,
    )
    branches = models.ManyToManyField(
        "catalog.Branch",
        related_name="users",
        verbose_name="Филиалы",
        blank=True,
    )

    def is_admin(self) -> bool:
        return self.role == Roles.ADMIN or self.is_superuser

    def get_accessible_warehouses(self):
        """Возвращает склады, к которым у пользователя есть доступ."""
        from catalog.models import Warehouse, WarehouseAccess

        if self.is_admin():
            return Warehouse.objects.filter(is_active=True).select_related("branch")

        user_branches = self.branches.filter(is_active=True)
        if not user_branches.exists():
            return Warehouse.objects.none()

        accessible_warehouses = Warehouse.objects.filter(
            branch__in=user_branches, is_active=True
        ).select_related("branch")

        access_ids = WarehouseAccess.objects.filter(
            user=self, warehouse__is_active=True
        ).values_list("warehouse_id", flat=True)

        if access_ids.exists():
            return accessible_warehouses.filter(id__in=access_ids).distinct()
        return Warehouse.objects.none()

    def can_access_warehouse(self, warehouse):
        """Проверяет, есть ли у пользователя доступ к складу."""
        if self.is_admin():
            return True

        if not warehouse.is_active:
            return False

        if not self.branches.filter(id=warehouse.branch_id, is_active=True).exists():
            return False

        return WarehouseAccess.objects.filter(user=self, warehouse=warehouse).exists()

    def get_warehouse_access_level(self, warehouse):
        """Возвращает уровень доступа к складу."""
        from catalog.models import WarehouseAccess

        if self.is_admin():
            return WarehouseAccess.AccessLevel.ADMIN

        try:
            access = WarehouseAccess.objects.get(user=self, warehouse=warehouse)
            return access.access_level
        except WarehouseAccess.DoesNotExist:
            return None
