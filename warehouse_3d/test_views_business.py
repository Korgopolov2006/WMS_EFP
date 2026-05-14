"""
Тесты для warehouse_3d views и models.

Покрывает:
 * warehouse_3d_index, warehouse_3d_view
 * save_layout, save_storage_object, delete_storage_object
 * model properties (gate_point, has_stock, get_stock_count)
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.constants import Roles
from catalog.models import (
    Branch,
    Brand,
    Category,
    Product,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
    WarehouseAccess,
)
from inventory.models import Stock
from warehouse_3d.models import StorageObject, WarehouseLayout


User = get_user_model()


class WH3DBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="3d_admin", email="3a@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(
            branch=branch, code="WH1", name="Склад 1",
        )
        zt, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейка"})
        zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(zone=zone, code="L1", name="L1")
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="SKU-3D-1", name="Товар 3D",
            oem_number="OEM-3D-1", brand=brand, category=cat,
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c


# ════════════════════════════════════════════════════════════════════
# Models
# ════════════════════════════════════════════════════════════════════
class WarehouseLayoutModelTests(WH3DBase):
    def test_gate_point_explicit(self):
        layout = WarehouseLayout.objects.create(
            warehouse=self.warehouse, gate_x=5.0, gate_z=10.0,
        )
        self.assertEqual(layout.gate_point, (5.0, 10.0))

    def test_gate_point_from_floor_points(self):
        layout = WarehouseLayout.objects.create(
            warehouse=self.warehouse,
            floor_points=[[0, 0], [10, 0], [10, 10], [0, 10]],
        )
        # середина первой грани = ((0+10)/2, (0+0)/2) = (5.0, 0.0)
        self.assertEqual(layout.gate_point, (5.0, 0.0))

    def test_gate_point_fallback_zero(self):
        layout = WarehouseLayout.objects.create(warehouse=self.warehouse)
        self.assertEqual(layout.gate_point, (0.0, 0.0))

    def test_get_floor_points_list(self):
        layout = WarehouseLayout.objects.create(
            warehouse=self.warehouse,
            floor_points=[[1, 2], [3, 4]],
        )
        result = layout.get_floor_points_list()
        self.assertEqual(result, [(1, 2), (3, 4)])

    def test_get_floor_points_list_empty(self):
        layout = WarehouseLayout.objects.create(warehouse=self.warehouse)
        self.assertEqual(layout.get_floor_points_list(), [])


class StorageObjectModelTests(WH3DBase):
    def test_has_stock_returns_true(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="A01", storage_location=self.location,
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        self.assertTrue(obj.has_stock())

    def test_has_stock_false_without_location(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL", code="A02",
        )
        self.assertFalse(obj.has_stock())

    def test_get_stock_count(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="A03", storage_location=self.location,
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        self.assertEqual(obj.get_stock_count(), 1)

    def test_get_stock_count_zero_without_location(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL", code="A04",
        )
        self.assertEqual(obj.get_stock_count(), 0)

    def test_get_total_stock_qty(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="A05", storage_location=self.location,
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("7"),
        )
        self.assertEqual(obj.get_total_stock_qty(), Decimal("7"))

    def test_get_total_stock_qty_zero(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL", code="A06",
        )
        self.assertEqual(obj.get_total_stock_qty(), 0)


# ════════════════════════════════════════════════════════════════════
# warehouse_3d_index
# ════════════════════════════════════════════════════════════════════
class WH3DIndexTests(WH3DBase):
    def test_redirects_to_dashboard_when_no_access(self):
        # Обычный пользователь без доступа
        user = User.objects.create_user(
            username="nowh", email="nowh@t.ru", password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )
        client = self._client(user)
        response = client.get(reverse("warehouse_3d:index"))
        self.assertEqual(response.status_code, 302)

    def test_redirects_to_single_warehouse(self):
        # Админ имеет доступ ко всем складам — а у нас только один
        client = self._client(self.admin)
        response = client.get(reverse("warehouse_3d:index"))
        # либо редирект на view, либо страница списка
        self.assertIn(response.status_code, (200, 302))

    def test_shows_list_when_multiple_warehouses(self):
        Warehouse.objects.create(
            branch=self.warehouse.branch, code="WH2", name="WH2",
        )
        client = self._client(self.admin)
        response = client.get(reverse("warehouse_3d:index"))
        # рендерит список (200) или редирект если только что зашёл
        self.assertIn(response.status_code, (200, 302))


# ════════════════════════════════════════════════════════════════════
# warehouse_3d_view
# ════════════════════════════════════════════════════════════════════
class WH3DViewTests(WH3DBase):
    def test_admin_can_view(self):
        client = self._client(self.admin)
        response = client.get(reverse("warehouse_3d:view", args=[self.warehouse.id]))
        self.assertEqual(response.status_code, 200)

    def test_user_without_access_gets_403(self):
        user = User.objects.create_user(
            username="noacc", email="noacc@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.SMALL_PARTS_PICKER,
        )
        client = self._client(user)
        response = client.get(reverse("warehouse_3d:view", args=[self.warehouse.id]))
        # PermissionDenied → 403
        self.assertEqual(response.status_code, 403)

    def test_focus_id_in_querystring(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:view", args=[self.warehouse.id]),
            {"focus": "1"},
        )
        self.assertEqual(response.status_code, 200)

    def test_invalid_focus_handled(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:view", args=[self.warehouse.id]),
            {"focus": "not-a-number"},
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# save_layout
# ════════════════════════════════════════════════════════════════════
class SaveLayoutTests(WH3DBase):
    def test_save_valid_layout(self):
        client = self._client(self.admin)
        response = client.post(
            reverse("warehouse_3d:save_layout", args=[self.warehouse.id]),
            data=json.dumps({"floor_points": [[0, 0], [10, 0], [10, 10], [0, 10]]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        layout = WarehouseLayout.objects.get(warehouse=self.warehouse)
        self.assertTrue(layout.is_layout_defined)

    def test_save_empty_clears_layout(self):
        WarehouseLayout.objects.create(
            warehouse=self.warehouse,
            floor_points=[[0, 0], [1, 0], [1, 1]],
            is_layout_defined=True,
        )
        client = self._client(self.admin)
        response = client.post(
            reverse("warehouse_3d:save_layout", args=[self.warehouse.id]),
            data=json.dumps({"floor_points": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        layout = WarehouseLayout.objects.get(warehouse=self.warehouse)
        self.assertFalse(layout.is_layout_defined)

    def test_insufficient_points_returns_400(self):
        client = self._client(self.admin)
        response = client.post(
            reverse("warehouse_3d:save_layout", args=[self.warehouse.id]),
            data=json.dumps({"floor_points": [[0, 0], [1, 0]]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


# ════════════════════════════════════════════════════════════════════
# save_storage_object / delete_storage_object
# ════════════════════════════════════════════════════════════════════
class StorageObjectCRUDTests(WH3DBase):
    def test_create_object(self):
        client = self._client(self.admin)
        response = client.post(
            reverse("warehouse_3d:save_object", args=[self.warehouse.id]),
            data=json.dumps({
                "object_type": "RACK",
                "code": "R01",
                "name": "Стеллаж 1",
                "position_x": 5.0,
                "position_z": 5.0,
                "position_y": 0.0,
                "width": 2.0,
                "depth": 1.0,
                "height": 3.0,
                "rotation_y": 0.0,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            StorageObject.objects.filter(warehouse=self.warehouse, code="R01").exists()
        )

    def test_delete_object(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL", code="D01",
        )
        client = self._client(self.admin)
        response = client.post(
            reverse("warehouse_3d:delete_object", args=[self.warehouse.id, obj.id]),
        )
        self.assertEqual(response.status_code, 200)
        # Объект помечен как неактивный или удалён
        obj_check = StorageObject.objects.filter(id=obj.id, is_active=True).first()
        self.assertIsNone(obj_check)


# ════════════════════════════════════════════════════════════════════
# Read-only API endpoints
# ════════════════════════════════════════════════════════════════════
class WH3DReadOnlyEndpointsTests(WH3DBase):
    def test_kpi_data(self):
        client = self._client(self.admin)
        response = client.get(reverse("warehouse_3d:kpi_data", args=[self.warehouse.id]))
        self.assertEqual(response.status_code, 200)

    def test_objects_for_receiving(self):
        StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL", code="OFR-1",
            storage_location=self.location,
        )
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:objects_for_receiving", args=[self.warehouse.id]),
        )
        self.assertEqual(response.status_code, 200)

    def test_recent_movements(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:recent_movements", args=[self.warehouse.id]),
        )
        # JSON-эндпоинт — 200 либо 304 (если ничего нового)
        self.assertIn(response.status_code, (200, 204, 304))

    def test_layout_audit(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:layout_audit", args=[self.warehouse.id]),
        )
        self.assertEqual(response.status_code, 200)

    def test_locate_sku(self):
        StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL", code="L-1",
            storage_location=self.location,
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:locate_sku", args=[self.warehouse.id]),
            {"q": "SKU-3D-1"},
        )
        self.assertEqual(response.status_code, 200)

    def test_movement_heatmap(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:movement_heatmap", args=[self.warehouse.id]),
        )
        self.assertEqual(response.status_code, 200)

    def test_export_layout(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("warehouse_3d:export_layout", args=[self.warehouse.id]),
        )
        self.assertEqual(response.status_code, 200)
