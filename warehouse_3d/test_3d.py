"""Тесты warehouse_3d: 3D-склад, KPI, поиск SKU, heatmap движений, импорт/экспорт."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import (
    Branch,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
)
from warehouse_3d.models import StorageObject, WarehouseLayout

User = get_user_model()


def _bootstrap_warehouse():
    """Создаёт минимальный набор данных для 3D-тестов."""
    branch, _ = Branch.objects.get_or_create(code="W3D", defaults={"name": "Test Branch"})
    warehouse, _ = Warehouse.objects.get_or_create(
        branch=branch,
        code="MAIN3D",
        defaults={"name": "Test 3D Warehouse"},
    )
    zone_type, _ = StorageZoneType.objects.get_or_create(
        code="SHELF", defaults={"name": "Полки", "sort_order": 1},
    )
    zone, _ = StorageZone.objects.get_or_create(
        warehouse=warehouse,
        code="Z1",
        defaults={"name": "Zone 1", "zone_type": zone_type},
    )
    location, _ = StorageLocation.objects.get_or_create(
        zone=zone,
        code="LOC1",
        defaults={"name": "Loc 1"},
    )
    return warehouse, location


class TestWarehouse3DAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="w3d_admin", email="w3d@t.ru", password="Pass1!ABCDEFGH",
        )
        cls.warehouse, cls.location = _bootstrap_warehouse()
        cls.layout, _ = WarehouseLayout.objects.get_or_create(warehouse=cls.warehouse)
        cls.layout.floor_points = [[0, 0], [10, 0], [10, 10], [0, 10]]
        cls.layout.is_layout_defined = True
        cls.layout.save()

        cls.rack = StorageObject.objects.create(
            warehouse=cls.warehouse,
            object_type=StorageObject.ObjectType.RACK,
            code="R-01",
            position_x=5.0, position_z=5.0, position_y=0.0,
            width=2.0, depth=1.0, height=2.5,
            storage_location=cls.location,
        )
        cls.cell = StorageObject.objects.create(
            warehouse=cls.warehouse,
            object_type=StorageObject.ObjectType.CELL,
            code="C-01",
            position_x=2.0, position_z=2.0, position_y=0.0,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    # ── Главная страница 3D ────────────────────────────────────
    def test_view_3d_renders_with_kpi(self):
        url = reverse("warehouse_3d:view", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # KPI попадает в контекст
        self.assertIn("kpi", resp.context)
        self.assertIn("total_objects", resp.context["kpi"])
        self.assertGreaterEqual(resp.context["kpi"]["total_objects"], 2)

    # ── KPI endpoint ──────────────────────────────────────────
    def test_kpi_endpoint(self):
        url = reverse("warehouse_3d:kpi_data", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("kpi", data)
        self.assertIn("fill_by_object", data)
        # JSON-ключи всегда строки → проверяем оба варианта
        keys = data["fill_by_object"].keys()
        self.assertTrue(self.rack.id in keys or str(self.rack.id) in keys)

    # ── Поиск SKU ─────────────────────────────────────────────
    def test_locate_sku_empty_query(self):
        url = reverse("warehouse_3d:locate_sku", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])

    def test_locate_sku_with_query_returns_200(self):
        url = reverse("warehouse_3d:locate_sku", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.get(url + "?q=NONEXISTENT")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])

    # ── Heatmap движений ──────────────────────────────────────
    def test_movement_heatmap_endpoint(self):
        url = reverse("warehouse_3d:movement_heatmap", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.get(url + "?days=7")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["days"], 7)
        self.assertIn("by_object", data)
        self.assertIn("max_count", data)

    def test_movement_heatmap_clamps_days(self):
        url = reverse("warehouse_3d:movement_heatmap", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.get(url + "?days=99999")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(resp.json()["days"], 365)

    # ── Экспорт layout ────────────────────────────────────────
    def test_export_layout_returns_json_file(self):
        url = reverse("warehouse_3d:export_layout", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        payload = json.loads(resp.content)
        self.assertEqual(payload["warehouse_code"], self.warehouse.code)
        self.assertEqual(payload["floor_points"], [[0, 0], [10, 0], [10, 10], [0, 10]])
        self.assertGreaterEqual(len(payload["objects"]), 2)

    # ── Импорт layout ─────────────────────────────────────────
    def test_import_layout_creates_objects(self):
        url = reverse("warehouse_3d:import_layout", kwargs={"warehouse_id": self.warehouse.id})
        payload = {
            "floor_points": [[0, 0], [20, 0], [20, 20], [0, 20]],
            "objects": [
                {
                    "object_type": "RACK", "code": "IMP-1",
                    "position_x": 1.0, "position_y": 0.0, "position_z": 1.0,
                    "width": 2, "depth": 1, "height": 2.5, "rotation_y": 0,
                },
                {
                    "object_type": "CELL", "code": "IMP-2",
                    "position_x": 3.0, "position_y": 0.0, "position_z": 3.0,
                    "width": 0.5, "depth": 0.5, "height": 0.5, "rotation_y": 90,
                },
            ],
            "replace_objects": False,
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["created"], 2)
        self.assertTrue(StorageObject.objects.filter(warehouse=self.warehouse, code="IMP-1").exists())
        self.assertTrue(StorageObject.objects.filter(warehouse=self.warehouse, code="IMP-2").exists())

    def test_import_layout_rejects_invalid_json(self):
        url = reverse("warehouse_3d:import_layout", kwargs={"warehouse_id": self.warehouse.id})
        resp = self.client.post(url, data="<<not json>>", content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["success"])

    def test_import_layout_rejects_short_floor(self):
        url = reverse("warehouse_3d:import_layout", kwargs={"warehouse_id": self.warehouse.id})
        payload = {"floor_points": [[0, 0], [1, 1]], "objects": []}
        resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_save_storage_object_links_storage_location(self):
        url = reverse("warehouse_3d:save_object", kwargs={"warehouse_id": self.warehouse.id})
        payload = {
            "object_type": "RACK",
            "code": "R-LINK",
            "name": "Linked rack",
            "position_x": 1,
            "position_y": 0,
            "position_z": 1,
            "width": 2,
            "depth": 1,
            "height": 2.5,
            "rotation_y": 0,
            "storage_location_id": self.location.id,
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        obj = StorageObject.objects.get(id=data["id"])
        self.assertEqual(obj.storage_location_id, self.location.id)
        self.assertEqual(data["object"]["storageLocationId"], self.location.id)

    # ── Интеграция с receiving ────────────────────────────────
    def test_objects_for_receiving_endpoint(self):
        url = reverse(
            "warehouse_3d:objects_for_receiving",
            kwargs={"warehouse_id": self.warehouse.id},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertGreaterEqual(data["count"], 1)
        codes = {it["code"] for it in data["items"]}
        self.assertIn("R-01", codes)
        item = next(it for it in data["items"] if it["code"] == "R-01")
        self.assertEqual(item["storage_location_id"], self.location.id)
        self.assertIn(item["status"], ("ok", "warn", "full"))
        self.assertIn("pct", item)
