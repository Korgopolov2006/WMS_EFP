"""
Тесты пользовательских сценариев в receiving views.

Покрывает POST/AJAX-операции:
 * receiving_create — создание документа приёмки
 * receiving_detail — set_warehouse, change_status (complete), receive_all, фильтры
 * receiving_add_line — добавление строки
 * receiving_update_line_qty — обновление количества
 * receiving_suggest_location — подбор места
 * receiving_next_supplier_doc — генерация номера документа поставщика
 * supplier_create — создание поставщика
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
from receiving.models import Receiving, ReceivingLine, ReceivingStatus, Supplier


User = get_user_model()


class ReceivingViewsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="rcv_admin", email="rcv_a@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.storekeeper = User.objects.create_user(
            username="rcv_stk", email="rcv_s@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        cls.picker = User.objects.create_user(
            username="rcv_pck", email="rcv_p@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )

        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(branch=branch, code="WH1", name="WH1")
        zt, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейка"})
        zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(zone=zone, code="L1", name="L1")

        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="SKU-RCV-1", name="Товар 1",
            oem_number="OEM-RCV-1", brand=brand, category=cat,
            packaging_type=Product.PackagingType.SMALL,
        )

        cls.supplier = Supplier.objects.create(code="ACME", name="ACME Ltd")

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c


# ════════════════════════════════════════════════════════════════════
# receiving_create
# ════════════════════════════════════════════════════════════════════
class ReceivingCreateTests(ReceivingViewsBase):
    def test_get_form(self):
        client = self._client(self.admin)
        response = client.get(reverse("receiving_create"))
        self.assertEqual(response.status_code, 200)

    def test_picker_blocked(self):
        client = self._client(self.picker)
        response = client.get(reverse("receiving_create"))
        self.assertEqual(response.status_code, 403)


# ════════════════════════════════════════════════════════════════════
# supplier_create
# ════════════════════════════════════════════════════════════════════
class SupplierCreateTests(ReceivingViewsBase):
    def test_post_creates_supplier(self):
        client = self._client(self.admin)
        client.post(reverse("supplier_create"), {
            "code": "newsup01",
            "name": "Новый Поставщик",
            "is_active": "on",
        })
        # код нормализуется в верхний регистр
        self.assertTrue(Supplier.objects.filter(name="Новый Поставщик").exists())

    def test_invalid_code_rejected(self):
        client = self._client(self.admin)
        client.post(reverse("supplier_create"), {
            "code": "???",
            "name": "Только символы",
        })
        self.assertFalse(Supplier.objects.filter(name="Только символы").exists())


# ════════════════════════════════════════════════════════════════════
# receiving_list — фильтры
# ════════════════════════════════════════════════════════════════════
class ReceivingListTests(ReceivingViewsBase):
    def test_list_renders(self):
        Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )
        client = self._client(self.admin)
        response = client.get(reverse("receiving_list"))
        self.assertEqual(response.status_code, 200)

    def test_list_filter_by_status(self):
        Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            status=ReceivingStatus.COMPLETED, created_by=self.storekeeper,
        )
        client = self._client(self.admin)
        response = client.get(reverse("receiving_list"), {"status": "COMPLETED"})
        self.assertEqual(response.status_code, 200)

    def test_list_search(self):
        Receiving.objects.create(
            supplier_name="Найдиэтогопоставщика",
            warehouse=self.warehouse, created_by=self.storekeeper,
        )
        client = self._client(self.admin)
        response = client.get(reverse("receiving_list"), {"q": "Найдиэто"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# receiving_detail
# ════════════════════════════════════════════════════════════════════
class ReceivingDetailTests(ReceivingViewsBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )

    def test_get_detail(self):
        client = self._client(self.admin)
        response = client.get(reverse("receiving_detail", args=[self.receiving.pk]))
        self.assertEqual(response.status_code, 200)

    def test_change_status_to_completed_runs_service(self):
        # Добавляем валидную строку
        ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("3"), qty_received=Decimal("3"),
            storage_location=self.location,
        )
        client = self._client(self.admin)
        client.post(
            reverse("receiving_detail", args=[self.receiving.pk]),
            {"change_status": "1", "status": ReceivingStatus.COMPLETED},
        )
        self.receiving.refresh_from_db()
        self.assertEqual(self.receiving.status, ReceivingStatus.COMPLETED)

    def test_completed_without_lines_rolls_back(self):
        client = self._client(self.admin)
        client.post(
            reverse("receiving_detail", args=[self.receiving.pk]),
            {"change_status": "1", "status": ReceivingStatus.COMPLETED},
        )
        # Без строк — ReceivingService отказал, статус откатывается
        self.receiving.refresh_from_db()
        self.assertEqual(self.receiving.status, ReceivingStatus.DRAFT)

    def test_receive_all_fills_qty_received(self):
        line = ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("5"), qty_received=Decimal("0"),
            storage_location=self.location,
        )
        client = self._client(self.admin)
        client.post(
            reverse("receiving_detail", args=[self.receiving.pk]),
            {"receive_all": "1"},
        )
        line.refresh_from_db()
        self.assertEqual(line.qty_received, Decimal("5"))

    def test_set_warehouse(self):
        # Создаём ещё один склад
        wh2 = Warehouse.objects.create(
            branch=self.warehouse.branch, code="WH2", name="WH2",
        )
        client = self._client(self.admin)
        client.post(
            reverse("receiving_detail", args=[self.receiving.pk]),
            {"set_warehouse": "1", "warehouse_id": str(wh2.pk)},
        )
        self.receiving.refresh_from_db()
        self.assertEqual(self.receiving.warehouse_id, wh2.pk)


# ════════════════════════════════════════════════════════════════════
# receiving_add_line
# ════════════════════════════════════════════════════════════════════
class ReceivingAddLineTests(ReceivingViewsBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )

    def test_add_line_post(self):
        client = self._client(self.admin)
        client.post(
            reverse("receiving_add_line", args=[self.receiving.pk]),
            {
                "product": str(self.product.pk),
                "supplier_sku": "ACME-X1",
                "qty_expected": "5",
                "qty_received": "5",
                "storage_location": str(self.location.pk),
            },
        )
        self.assertTrue(
            ReceivingLine.objects.filter(
                receiving=self.receiving, product=self.product,
            ).exists()
        )


# ════════════════════════════════════════════════════════════════════
# receiving_update_line_qty (AJAX)
# ════════════════════════════════════════════════════════════════════
class ReceivingUpdateLineQtyTests(ReceivingViewsBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )
        self.line = ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("5"), qty_received=Decimal("2"),
            storage_location=self.location,
        )

    def test_update_qty_ajax(self):
        client = self._client(self.admin)
        response = client.post(
            reverse("receiving_update_line_qty",
                    args=[self.receiving.pk, self.line.pk]),
            {"qty_received": "4"},
        )
        # 200 (json) или 302 (redirect)
        self.assertIn(response.status_code, (200, 302))
        self.line.refresh_from_db()
        self.assertEqual(self.line.qty_received, Decimal("4"))


# ════════════════════════════════════════════════════════════════════
# receiving_suggest_location / receiving_next_supplier_doc (AJAX)
# ════════════════════════════════════════════════════════════════════
class ReceivingAjaxEndpointsTests(ReceivingViewsBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )

    def test_suggest_location_returns_json(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("receiving_suggest_location", args=[self.receiving.pk]),
            {"product_id": self.product.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_next_supplier_doc_returns_json(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("receiving_next_supplier_doc"),
            {"supplier_id": str(self.supplier.pk)},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("supplier_doc_no", data)

    def test_next_supplier_doc_without_supplier_returns_400(self):
        client = self._client(self.admin)
        response = client.get(reverse("receiving_next_supplier_doc"))
        self.assertEqual(response.status_code, 400)


# ════════════════════════════════════════════════════════════════════
# supplier_list
# ════════════════════════════════════════════════════════════════════
class SupplierListTests(ReceivingViewsBase):
    def test_list_renders(self):
        client = self._client(self.admin)
        response = client.get(reverse("supplier_list"))
        self.assertEqual(response.status_code, 200)

    def test_list_search(self):
        client = self._client(self.admin)
        response = client.get(reverse("supplier_list"), {"q": "ACME"})
        self.assertEqual(response.status_code, 200)
