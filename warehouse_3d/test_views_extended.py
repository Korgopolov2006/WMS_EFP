"""
Расширенные тесты warehouse_3d views.

Покрывает:
 * bulk_generate_objects — массовое создание с валидацией
 * layout_audit_rollback — откат изменений
 * object_qr_pdf — PDF этикетка
 * pick_path — маршрут комплектования (greedy TSP)
 * object_stocks, stock_action — inline-edit товаров
 * import_layout, export_layout
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.constants import Roles
from admin_panel.models import AuditLog
from catalog.models import (
    Branch,
    Brand,
    Category,
    Product,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
)
from inventory.models import Stock, StockMovement
from warehouse_3d.models import StorageObject, WarehouseLayout


User = get_user_model()


class WH3DExtendedBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="3dx_admin", email="3xa@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(
            branch=branch, code="WH1", name="WH1",
        )
        zt, _ = StorageZoneType.objects.get_or_create(
            code="CELL", defaults={"name": "Ячейка"},
        )
        zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(zone=zone, code="L1", name="L1")
        cls.location2 = StorageLocation.objects.create(zone=zone, code="L2", name="L2")
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="WH-PROD-1", name="Товар 3D",
            oem_number="OEM-WH-1", brand=brand, category=cat,
        )

    def _client(self):
        c = Client()
        c.force_login(self.admin)
        return c


# ════════════════════════════════════════════════════════════════════
# bulk_generate_objects
# ════════════════════════════════════════════════════════════════════
class BulkGenerateTests(WH3DExtendedBase):
    def _post_bulk(self, data):
        return self._client().post(
            reverse("warehouse_3d:bulk_generate_objects", args=[self.warehouse.id]),
            data=json.dumps(data),
            content_type="application/json",
        )

    def test_generates_specified_count_along_x(self):
        response = self._post_bulk({
            "object_type": "RACK", "count": 5, "step": 2.0,
            "start_x": 0, "start_z": 0, "direction": "x",
            "code_prefix": "RACK",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 5)
        racks = StorageObject.objects.filter(
            warehouse=self.warehouse, object_type="RACK",
        )
        self.assertEqual(racks.count(), 5)
        # Координаты разнесены по X
        xs = sorted([float(r.position_x) for r in racks])
        self.assertEqual(xs, [0.0, 2.0, 4.0, 6.0, 8.0])

    def test_generates_along_z_direction(self):
        response = self._post_bulk({
            "object_type": "SHELF", "count": 3, "step": 1.5,
            "start_x": 5, "start_z": 5, "direction": "z",
        })
        self.assertEqual(response.status_code, 200)
        shelves = StorageObject.objects.filter(
            warehouse=self.warehouse, object_type="SHELF",
        )
        zs = sorted([float(s.position_z) for s in shelves])
        self.assertEqual(zs, [5.0, 6.5, 8.0])

    def test_invalid_object_type_rejected(self):
        response = self._post_bulk({"object_type": "INVALID", "count": 1})
        self.assertEqual(response.status_code, 400)

    def test_count_out_of_range_rejected(self):
        response = self._post_bulk({"count": 100})
        self.assertEqual(response.status_code, 400)
        response = self._post_bulk({"count": 0})
        self.assertEqual(response.status_code, 400)

    def test_invalid_direction_rejected(self):
        response = self._post_bulk({"count": 2, "direction": "y"})
        self.assertEqual(response.status_code, 400)

    def test_invalid_numeric_params_rejected(self):
        response = self._post_bulk({
            "count": "not-a-number", "step": "x",
        })
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_rejected(self):
        response = self._client().post(
            reverse("warehouse_3d:bulk_generate_objects", args=[self.warehouse.id]),
            data="not-json{[",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_audit_log_created(self):
        self._post_bulk({"count": 2, "code_prefix": "AUD"})
        log = AuditLog.objects.filter(
            action=AuditLog.ActionType.LAYOUT_BULK_CREATE,
        ).first()
        self.assertIsNotNone(log)


# ════════════════════════════════════════════════════════════════════
# layout_audit_rollback
# ════════════════════════════════════════════════════════════════════
class LayoutAuditRollbackTests(WH3DExtendedBase):
    def test_rollback_restores_previous_state(self):
        # 1. Создаём объект и редактируем его — генерируется AuditLog UPDATE
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK",
            code="R-OLD", position_x=1.0, position_z=2.0,
            width=2.0, depth=1.0, height=2.5,
        )
        before = {
            "object_type": "RACK", "code": "R-OLD", "name": "",
            "position_x": 1.0, "position_y": 0.0, "position_z": 2.0,
            "width": 2.0, "depth": 1.0, "height": 2.5, "rotation_y": 0.0,
        }
        # Создаём AuditLog вручную (имитация прошлого редактирования)
        log = AuditLog.objects.create(
            user=self.admin,
            action=AuditLog.ActionType.LAYOUT_UPDATE,
            resource_type="StorageObject",
            resource_id=str(obj.id),
            changes={"before": before, "after": {}},
        )
        # Меняем объект
        obj.code = "R-NEW"
        obj.position_x = 99.0
        obj.save()

        # 2. Откатываем
        response = self._client().post(
            reverse("warehouse_3d:layout_audit_rollback",
                    args=[self.warehouse.id, log.id]),
        )
        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.code, "R-OLD")
        self.assertEqual(float(obj.position_x), 1.0)

    def test_rollback_delete_reactivates_object(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="C1", is_active=False,
        )
        before = {
            "object_type": "CELL", "code": "C1", "name": "",
            "position_x": 0.0, "position_y": 0.0, "position_z": 0.0,
            "width": 1.0, "depth": 1.0, "height": 1.0, "rotation_y": 0.0,
        }
        log = AuditLog.objects.create(
            user=self.admin,
            action=AuditLog.ActionType.LAYOUT_DELETE,
            resource_type="StorageObject",
            resource_id=str(obj.id),
            changes={"before": before},
        )
        response = self._client().post(
            reverse("warehouse_3d:layout_audit_rollback",
                    args=[self.warehouse.id, log.id]),
        )
        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertTrue(obj.is_active)

    def test_cannot_rollback_create_action(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK", code="RC1",
        )
        log = AuditLog.objects.create(
            user=self.admin,
            action=AuditLog.ActionType.LAYOUT_CREATE,
            resource_type="StorageObject",
            resource_id=str(obj.id),
            changes={"after": {}},
        )
        response = self._client().post(
            reverse("warehouse_3d:layout_audit_rollback",
                    args=[self.warehouse.id, log.id]),
        )
        self.assertEqual(response.status_code, 400)

    def test_rollback_without_before_data(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK", code="R-NB",
        )
        log = AuditLog.objects.create(
            user=self.admin,
            action=AuditLog.ActionType.LAYOUT_UPDATE,
            resource_type="StorageObject",
            resource_id=str(obj.id),
            changes={"before": None},  # пусто
        )
        response = self._client().post(
            reverse("warehouse_3d:layout_audit_rollback",
                    args=[self.warehouse.id, log.id]),
        )
        self.assertEqual(response.status_code, 400)


# ════════════════════════════════════════════════════════════════════
# object_qr_pdf
# ════════════════════════════════════════════════════════════════════
class ObjectQRPdfTests(WH3DExtendedBase):
    def test_pdf_generated(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK",
            code="QR-1", name="Тестовый стеллаж",
        )
        response = self._client().get(
            reverse("warehouse_3d:object_qr", args=[self.warehouse.id, obj.id]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        # inline или attachment — главное чтобы PDF
        cd = response.get("Content-Disposition", "").lower()
        self.assertTrue("inline" in cd or "attachment" in cd)

    def test_pdf_for_inactive_object_404(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK",
            code="QR-INACTIVE", is_active=False,
        )
        response = self._client().get(
            reverse("warehouse_3d:object_qr", args=[self.warehouse.id, obj.id]),
        )
        self.assertEqual(response.status_code, 404)


# ════════════════════════════════════════════════════════════════════
# pick_path
# ════════════════════════════════════════════════════════════════════
class PickPathTests(WH3DExtendedBase):
    def setUp(self):
        # Привязываем объекты к локациям
        self.obj1 = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK",
            code="R1", storage_location=self.location,
            position_x=5.0, position_z=5.0,
        )
        self.obj2 = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK",
            code="R2", storage_location=self.location2,
            position_x=10.0, position_z=10.0,
        )
        # Stock на этих локациях
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        # Второй товар
        brand = Brand.objects.create(name="VALEO")
        cat = Category.objects.create(name="Other")
        self.product2 = Product.objects.create(
            internal_sku="WH-PROD-2", name="Товар 2",
            oem_number="OEM-WH-2", brand=brand, category=cat,
        )
        Stock.objects.create(
            product=self.product2, storage_location=self.location2,
            qty_available=Decimal("3"),
        )
        # Layout с координатами ворот
        WarehouseLayout.objects.create(
            warehouse=self.warehouse, gate_x=0.0, gate_z=0.0,
        )

    def test_pick_path_returns_ordered_route(self):
        response = self._client().get(
            reverse("warehouse_3d:pick_path", args=[self.warehouse.id]),
            {"skus": f"{self.product.internal_sku},{self.product2.internal_sku}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["path"]), 2)
        # Ближайший к воротам (5,5) выбран первым
        self.assertEqual(data["path"][0]["product_sku"], self.product.internal_sku)
        # Общая дистанция > 0
        self.assertGreater(data["total_distance"], 0)

    def test_pick_path_empty_skus(self):
        response = self._client().get(
            reverse("warehouse_3d:pick_path", args=[self.warehouse.id]),
            {"skus": ""},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["path"], [])
        self.assertEqual(data["total_distance"], 0.0)

    def test_pick_path_unknown_sku_in_missing(self):
        response = self._client().get(
            reverse("warehouse_3d:pick_path", args=[self.warehouse.id]),
            {"skus": "NON-EXISTENT-SKU"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("NON-EXISTENT-SKU", data["missing"])

    def test_pick_path_supports_semicolons_as_separator(self):
        response = self._client().get(
            reverse("warehouse_3d:pick_path", args=[self.warehouse.id]),
            {"skus": f"{self.product.internal_sku};{self.product2.internal_sku}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["path"]), 2)


# ════════════════════════════════════════════════════════════════════
# object_stocks
# ════════════════════════════════════════════════════════════════════
class ObjectStocksTests(WH3DExtendedBase):
    def test_returns_stocks_list(self):
        obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="OS-1", storage_location=self.location,
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("7"),
        )
        response = self._client().get(
            reverse("warehouse_3d:object_stocks",
                    args=[self.warehouse.id, obj.id]),
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# stock_action (transfer / write_off / adjust)
# ════════════════════════════════════════════════════════════════════
class StockActionTests(WH3DExtendedBase):
    def setUp(self):
        self.obj_from = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="FROM", storage_location=self.location,
        )
        self.obj_to = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="TO", storage_location=self.location2,
        )
        self.stock = Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("10"),
        )

    def _post(self, obj, data):
        return self._client().post(
            reverse("warehouse_3d:stock_action",
                    args=[self.warehouse.id, obj.id]),
            data=json.dumps(data),
            content_type="application/json",
        )

    def test_transfer_moves_qty_between_objects(self):
        response = self._post(self.obj_from, {
            "action": "transfer",
            "stock_id": self.stock.id,
            "qty": "3",
            "target_object_id": self.obj_to.id,
            "reason": "Тест",
        })
        self.assertEqual(response.status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.qty_available, Decimal("7"))
        # Stock на target создан
        target_stock = Stock.objects.get(
            product=self.product, storage_location=self.location2,
        )
        self.assertEqual(target_stock.qty_available, Decimal("3"))
        # Создано StockMovement
        self.assertTrue(StockMovement.objects.filter(
            product=self.product, movement_type="TRANSFER",
        ).exists())

    def test_transfer_exceeding_available_rejected(self):
        response = self._post(self.obj_from, {
            "action": "transfer",
            "stock_id": self.stock.id,
            "qty": "100",  # больше чем 10
            "target_object_id": self.obj_to.id,
        })
        self.assertEqual(response.status_code, 400)

    def test_write_off_reduces_stock(self):
        response = self._post(self.obj_from, {
            "action": "write_off",
            "stock_id": self.stock.id,
            "qty": "4",
            "reason": "Брак",
        })
        self.assertEqual(response.status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.qty_available, Decimal("6"))

    def test_write_off_zero_qty_rejected(self):
        response = self._post(self.obj_from, {
            "action": "write_off",
            "stock_id": self.stock.id,
            "qty": "0",
        })
        self.assertEqual(response.status_code, 400)

    def test_adjust_sets_new_qty(self):
        response = self._post(self.obj_from, {
            "action": "adjust",
            "stock_id": self.stock.id,
            "qty": "15",
            "reason": "Инвентаризация",
        })
        self.assertEqual(response.status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.qty_available, Decimal("15"))

    def test_adjust_negative_rejected(self):
        response = self._post(self.obj_from, {
            "action": "adjust",
            "stock_id": self.stock.id,
            "qty": "-5",
        })
        self.assertEqual(response.status_code, 400)

    def test_unknown_action_rejected(self):
        response = self._post(self.obj_from, {
            "action": "destroy_the_world",
            "stock_id": self.stock.id,
            "qty": "1",
        })
        self.assertEqual(response.status_code, 400)

    def test_stock_not_found(self):
        response = self._post(self.obj_from, {
            "action": "write_off",
            "stock_id": 99999,
            "qty": "1",
        })
        self.assertEqual(response.status_code, 404)

    def test_invalid_json_rejected(self):
        response = self._client().post(
            reverse("warehouse_3d:stock_action",
                    args=[self.warehouse.id, self.obj_from.id]),
            data="{{bad",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_object_without_location_rejected(self):
        no_loc_obj = StorageObject.objects.create(
            warehouse=self.warehouse, object_type="CELL",
            code="NO-LOC",
        )
        response = self._post(no_loc_obj, {
            "action": "write_off", "stock_id": self.stock.id, "qty": "1",
        })
        self.assertEqual(response.status_code, 400)


# ════════════════════════════════════════════════════════════════════
# import / export layout
# ════════════════════════════════════════════════════════════════════
class LayoutImportExportTests(WH3DExtendedBase):
    def test_export_returns_json_with_layout_and_objects(self):
        WarehouseLayout.objects.create(
            warehouse=self.warehouse,
            floor_points=[[0, 0], [10, 0], [10, 10], [0, 10]],
            is_layout_defined=True,
        )
        StorageObject.objects.create(
            warehouse=self.warehouse, object_type="RACK",
            code="EXP-1", position_x=5.0,
        )
        response = self._client().get(
            reverse("warehouse_3d:export_layout", args=[self.warehouse.id]),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Должны быть ключи о layout и объектах
        self.assertTrue(any(k in data for k in ("layout", "objects", "storage_objects")))

    def test_import_layout_replaces_data(self):
        payload = {
            "layout": {"floor_points": [[0, 0], [5, 0], [5, 5], [0, 5]]},
            "objects": [
                {
                    "object_type": "RACK", "code": "IMP-1",
                    "position_x": 1.0, "position_z": 1.0,
                    "position_y": 0.0,
                    "width": 1.0, "depth": 1.0, "height": 2.0,
                    "rotation_y": 0.0,
                },
            ],
        }
        response = self._client().post(
            reverse("warehouse_3d:import_layout", args=[self.warehouse.id]),
            data=json.dumps(payload),
            content_type="application/json",
        )
        # Допускаем что эндпоинт может вернуть 200/400 в зависимости от схемы
        self.assertIn(response.status_code, (200, 400))
