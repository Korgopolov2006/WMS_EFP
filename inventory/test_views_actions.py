"""
Тесты пользовательских сценариев в inventory views.

Покрывает:
 * stock_list / stock_detail / movement_list — рендеринг с фильтрами
 * inventory_list — фильтр по статусу
 * inventory_create — POST создание
 * inventory_detail — add_line с валидацией
 * inventory_product_hint (AJAX)
"""
from __future__ import annotations

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
)
from inventory.models import (
    Inventory,
    InventoryLine,
    InventoryStatus,
    MovementType,
    Stock,
    StockMovement,
)


User = get_user_model()


class InventoryViewsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="inv_admin", email="inv_a@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.storekeeper = User.objects.create_user(
            username="inv_stk", email="inv_s@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        cls.picker = User.objects.create_user(
            username="inv_pck", email="inv_p@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )

        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(branch=branch, code="WH1", name="WH1")
        zt, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейка"})
        cls.zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Зона 1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(zone=cls.zone, code="A01", name="A01")

        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="SKU-INV-1", name="Товар инв",
            oem_number="OEM-INV-1", brand=brand, category=cat,
        )

        cls.stock = Stock.objects.create(
            product=cls.product, storage_location=cls.location,
            qty_available=Decimal("10"),
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c


# ════════════════════════════════════════════════════════════════════
# stock_list / stock_detail
# ════════════════════════════════════════════════════════════════════
class StockListTests(InventoryViewsBase):
    def test_list_renders(self):
        client = self._client(self.admin)
        response = client.get(reverse("stock_list"))
        self.assertEqual(response.status_code, 200)

    def test_list_filter_by_zone(self):
        client = self._client(self.admin)
        response = client.get(reverse("stock_list"), {"zone": self.zone.pk})
        self.assertEqual(response.status_code, 200)

    def test_list_search_by_product(self):
        client = self._client(self.admin)
        response = client.get(reverse("stock_list"), {"q": "SKU-INV"})
        self.assertEqual(response.status_code, 200)

    def test_stock_detail_renders(self):
        # ВАЖНО: stock_detail принимает Product.pk, не Stock.pk
        client = self._client(self.admin)
        response = client.get(reverse("stock_detail", args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)

    def test_picker_blocked_from_stock_list(self):
        client = self._client(self.picker)
        response = client.get(reverse("stock_list"))
        self.assertEqual(response.status_code, 403)


# ════════════════════════════════════════════════════════════════════
# inventory_list
# ════════════════════════════════════════════════════════════════════
class InventoryListTests(InventoryViewsBase):
    def test_list_renders(self):
        Inventory.objects.create(
            number="INV-LIST-1", zone=self.zone, created_by=self.storekeeper,
        )
        client = self._client(self.admin)
        response = client.get(reverse("inventory_list"))
        self.assertEqual(response.status_code, 200)

    def test_list_filter_by_status(self):
        client = self._client(self.admin)
        response = client.get(reverse("inventory_list"), {"status": "DRAFT"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# inventory_create
# ════════════════════════════════════════════════════════════════════
class InventoryCreateTests(InventoryViewsBase):
    def test_get_form(self):
        client = self._client(self.admin)
        response = client.get(reverse("inventory_create"))
        self.assertEqual(response.status_code, 200)

    def test_post_creates_inventory(self):
        client = self._client(self.admin)
        response = client.post(reverse("inventory_create"), {
            "number": "INV-NEW-1",
            "zone": str(self.zone.pk),
        })
        self.assertIn(response.status_code, (200, 302))
        inv = Inventory.objects.filter(number="INV-NEW-1").first()
        self.assertIsNotNone(inv)
        # Создатель проставлен
        self.assertEqual(inv.created_by, self.admin)


# ════════════════════════════════════════════════════════════════════
# inventory_detail — add_line
# ════════════════════════════════════════════════════════════════════
class InventoryDetailAddLineTests(InventoryViewsBase):
    def setUp(self):
        self.inv = Inventory.objects.create(
            number="INV-D-1", zone=self.zone,
            status=InventoryStatus.IN_PROGRESS, created_by=self.storekeeper,
        )

    def test_get_detail(self):
        client = self._client(self.admin)
        response = client.get(reverse("inventory_detail", args=[self.inv.pk]))
        self.assertEqual(response.status_code, 200)

    def test_add_line_by_product_and_location_ids(self):
        client = self._client(self.admin)
        client.post(
            reverse("inventory_detail", args=[self.inv.pk]),
            {
                "add_line": "1",
                "product_id": str(self.product.pk),
                "location_id": str(self.location.pk),
                "qty_actual": "10",
            },
        )
        self.assertTrue(
            InventoryLine.objects.filter(
                inventory=self.inv, product=self.product,
                storage_location=self.location,
            ).exists()
        )

    def test_add_line_with_fractional_qty_rejected(self):
        client = self._client(self.admin)
        client.post(
            reverse("inventory_detail", args=[self.inv.pk]),
            {
                "add_line": "1",
                "product_id": str(self.product.pk),
                "location_id": str(self.location.pk),
                "qty_actual": "1.5",
            },
        )
        # строка не создана
        self.assertFalse(
            InventoryLine.objects.filter(
                inventory=self.inv, product=self.product,
            ).exists()
        )

    def test_add_line_search_by_sku(self):
        client = self._client(self.admin)
        client.post(
            reverse("inventory_detail", args=[self.inv.pk]),
            {
                "add_line": "1",
                "product_query": "SKU-INV-1",
                "location_code": "A01",
                "qty_actual": "5",
            },
        )
        line = InventoryLine.objects.filter(
            inventory=self.inv, product=self.product,
        ).first()
        self.assertIsNotNone(line)
        self.assertEqual(line.qty_actual, Decimal("5"))

    def test_add_line_unknown_product_shows_error(self):
        client = self._client(self.admin)
        response = client.post(
            reverse("inventory_detail", args=[self.inv.pk]),
            {
                "add_line": "1",
                "product_query": "НесуществующийТовар",
                "location_code": "A01",
                "qty_actual": "5",
            },
            follow=True,
        )
        # Сообщение об ошибке показано
        self.assertEqual(response.status_code, 200)
        self.assertFalse(InventoryLine.objects.filter(inventory=self.inv).exists())


# ════════════════════════════════════════════════════════════════════
# inventory_product_hint (AJAX)
# ════════════════════════════════════════════════════════════════════
class InventoryProductHintTests(InventoryViewsBase):
    def setUp(self):
        self.inv = Inventory.objects.create(
            number="INV-H-1", zone=self.zone,
            status=InventoryStatus.IN_PROGRESS, created_by=self.storekeeper,
        )

    def test_returns_json(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("inventory_product_hint", args=[self.inv.pk]),
            {"q": "SKU-INV"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")


# ════════════════════════════════════════════════════════════════════
# movement_list
# ════════════════════════════════════════════════════════════════════
class MovementListTests(InventoryViewsBase):
    def test_list_renders(self):
        StockMovement.objects.create(
            movement_type=MovementType.RECEIPT,
            product=self.product, quantity=Decimal("5"),
            to_location=self.location, user=self.admin,
        )
        client = self._client(self.admin)
        response = client.get(reverse("movement_list"))
        self.assertEqual(response.status_code, 200)

    def test_list_filter_by_type(self):
        client = self._client(self.admin)
        response = client.get(reverse("movement_list"), {"type": "RECEIPT"})
        self.assertEqual(response.status_code, 200)

    def test_list_filter_by_date_range(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("movement_list"),
            {"date_from": "2026-01-01", "date_to": "2026-12-31"},
        )
        self.assertEqual(response.status_code, 200)
