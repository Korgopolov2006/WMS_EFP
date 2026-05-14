"""
Расширенные тесты inventory views и admin actions.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from accounts.constants import Roles
from catalog.admin import StorageLocationAdmin
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
    MovementStatus,
    MovementType,
    Stock,
    StockMovement,
)


User = get_user_model()


class InventoryExtendedBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="ix_admin", email="ix_a@t.ru",
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
        cls.zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(
            zone=cls.zone, code="L1", name="L1",
        )
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="IX-SKU-1", name="x", oem_number="OEM-IX-1",
            brand=brand, category=cat,
        )

    def _client(self):
        c = Client()
        c.force_login(self.admin)
        return c


# ════════════════════════════════════════════════════════════════════
# inventory_detail — add_line с зональными ограничениями
# ════════════════════════════════════════════════════════════════════
class InventoryDetailZoneTests(InventoryExtendedBase):
    def setUp(self):
        self.inv = Inventory.objects.create(
            number="INV-Z-1", zone=self.zone,
            status=InventoryStatus.IN_PROGRESS,
            created_by=self.admin,
        )

    def test_add_line_with_location_outside_zone_rejected(self):
        # Создаём место в другой зоне
        zt2, _ = StorageZoneType.objects.get_or_create(
            code="SHELF", defaults={"name": "Полка"},
        )
        other_zone = StorageZone.objects.create(
            warehouse=self.warehouse, code="Z2", name="Z2", zone_type=zt2,
        )
        other_loc = StorageLocation.objects.create(
            zone=other_zone, code="L9", name="L9",
        )
        client = self._client()
        client.post(
            reverse("inventory_detail", args=[self.inv.pk]),
            {
                "add_line": "1",
                "product_id": str(self.product.pk),
                "location_id": str(other_loc.pk),
                "qty_actual": "5",
            },
        )
        # Не создана — место не в зоне инвентаризации
        self.assertFalse(
            InventoryLine.objects.filter(inventory=self.inv).exists()
        )

    def test_add_line_negative_qty_rejected(self):
        client = self._client()
        client.post(
            reverse("inventory_detail", args=[self.inv.pk]),
            {
                "add_line": "1",
                "product_id": str(self.product.pk),
                "location_id": str(self.location.pk),
                "qty_actual": "-1",
            },
        )
        self.assertFalse(
            InventoryLine.objects.filter(inventory=self.inv).exists()
        )

    def test_add_line_multiple_products_in_query_shows_error(self):
        # Несколько товаров с похожими SKU
        Product.objects.create(
            internal_sku="IX-SKU-2", name="x", oem_number="OEM-IX-2",
            brand=self.product.brand, category=self.product.category,
        )
        client = self._client()
        client.post(
            reverse("inventory_detail", args=[self.inv.pk]),
            {
                "add_line": "1",
                "product_query": "IX-SKU",  # частичное — найдёт несколько
                "location_code": "L1",
                "qty_actual": "5",
            },
        )
        # Не создана — нужно уточнить
        self.assertFalse(
            InventoryLine.objects.filter(inventory=self.inv).exists()
        )

    def test_inventory_detail_search_by_q(self):
        InventoryLine.objects.create(
            inventory=self.inv, product=self.product,
            storage_location=self.location,
            qty_book=Decimal("5"), qty_actual=Decimal("5"),
        )
        client = self._client()
        response = client.get(
            reverse("inventory_detail", args=[self.inv.pk]),
            {"q": "IX-SKU"},
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# stock_list — расширенные фильтры
# ════════════════════════════════════════════════════════════════════
class StockListExtTests(InventoryExtendedBase):
    def setUp(self):
        self.stock = Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("10"),
        )

    def test_filter_by_warehouse(self):
        client = self._client()
        response = client.get(
            reverse("stock_list"),
            {"warehouse": str(self.warehouse.pk)},
        )
        self.assertEqual(response.status_code, 200)

    def test_filter_low_stock(self):
        # Создаём низкий остаток
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            batch_no="LOW", qty_available=Decimal("1"),
        )
        client = self._client()
        response = client.get(reverse("stock_list"), {"low_stock": "1"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# movement_list — расширенные фильтры
# ════════════════════════════════════════════════════════════════════
class MovementListExtTests(InventoryExtendedBase):
    def setUp(self):
        StockMovement.objects.create(
            movement_type=MovementType.RECEIPT,
            status=MovementStatus.POSTED,
            product=self.product, quantity=Decimal("5"),
            to_location=self.location, user=self.admin,
        )
        StockMovement.objects.create(
            movement_type=MovementType.WRITE_OFF,
            status=MovementStatus.POSTED,
            product=self.product, quantity=Decimal("-1"),
            from_location=self.location, user=self.admin,
        )

    def test_filter_by_product(self):
        client = self._client()
        response = client.get(
            reverse("movement_list"),
            {"product": str(self.product.pk)},
        )
        self.assertEqual(response.status_code, 200)

    def test_filter_by_status(self):
        client = self._client()
        response = client.get(reverse("movement_list"), {"status": "POSTED"})
        self.assertEqual(response.status_code, 200)

    def test_invalid_date_filter_ignored(self):
        client = self._client()
        response = client.get(
            reverse("movement_list"),
            {"date_from": "not-a-date"},
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# catalog.admin StorageLocationAdmin — delete_model
# ════════════════════════════════════════════════════════════════════
class StorageLocationAdminTests(InventoryExtendedBase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_obj = StorageLocationAdmin(StorageLocation, AdminSite())

    def _request_with_messages(self):
        request = self.factory.post("/admin/")
        request.user = self.admin
        # Подключаем хранилище сообщений
        setattr(request, "session", {})
        setattr(request, "_messages", FallbackStorage(request))
        return request

    def test_delete_blocked_when_stock_exists(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        request = self._request_with_messages()
        self.admin_obj.delete_model(request, self.location)
        # место не удалено
        self.assertTrue(
            StorageLocation.objects.filter(pk=self.location.pk).exists()
        )

    def test_delete_succeeds_when_no_stock(self):
        # Создаём свежее место без остатков
        empty_loc = StorageLocation.objects.create(
            zone=self.zone, code="L-EMPTY", name="empty",
        )
        request = self._request_with_messages()
        self.admin_obj.delete_model(request, empty_loc)
        self.assertFalse(
            StorageLocation.objects.filter(pk=empty_loc.pk).exists()
        )

    def test_delete_queryset_filters_out_locations_with_stock(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("3"),
        )
        empty_loc = StorageLocation.objects.create(
            zone=self.zone, code="L-EMPTY-2", name="empty2",
        )
        request = self._request_with_messages()
        # Передаём queryset
        qs = StorageLocation.objects.filter(pk__in=[self.location.pk, empty_loc.pk])
        self.admin_obj.delete_queryset(request, qs)
        # location с товаром остался, empty_loc удалён
        self.assertTrue(StorageLocation.objects.filter(pk=self.location.pk).exists())
        self.assertFalse(StorageLocation.objects.filter(pk=empty_loc.pk).exists())

    def test_has_stock_display_shows_warning_when_stock(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("3"),
        )
        result = self.admin_obj.has_stock_display(self.location)
        # html содержит "Есть товар" и форматированное количество
        result_str = str(result)
        self.assertIn("Есть товар", result_str)
        self.assertIn("3 шт", result_str)

    def test_has_stock_display_shows_free_when_no_stock(self):
        empty_loc = StorageLocation.objects.create(
            zone=self.zone, code="L-EMPTY-3", name="empty",
        )
        result = self.admin_obj.has_stock_display(empty_loc)
        self.assertIn("Свободно", str(result))
