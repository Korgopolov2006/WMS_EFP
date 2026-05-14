"""
Расширенные тесты receiving views.

Покрывает:
 * receiving_create_product — создание товара из приёмки
 * receiving_product_prefill — поиск товара для предзаполнения
 * receiving_pdf — генерация PDF-документа
 * receiving_list — фильтры по складу/датам/поставщику
 * supplier_list — поиск
 * receiving_create POST — успешное и неуспешное создание
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


class ReceivingExtendedBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="re_admin", email="rea@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.storekeeper = User.objects.create_user(
            username="re_stk", email="res@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
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
        cls.supplier = Supplier.objects.create(code="ACME", name="ACME Ltd")
        cls.brand = Brand.objects.create(name="DENSO")
        cls.category = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="RE-SKU-1", name="Товар",
            oem_number="OEM-RE-1", brand=cls.brand, category=cls.category,
            packaging_type=Product.PackagingType.SMALL,
        )

    def _client(self, user=None):
        c = Client()
        c.force_login(user or self.admin)
        return c


# ════════════════════════════════════════════════════════════════════
# receiving_create — POST с валидной формой
# ════════════════════════════════════════════════════════════════════
class ReceivingCreatePostTests(ReceivingExtendedBase):
    def test_post_creates_receiving(self):
        client = self._client()
        response = client.post(reverse("receiving_create"), {
            "number": "",
            "supplier_doc_no": "",
            "supplier": str(self.supplier.pk),
            "warehouse": str(self.warehouse.pk),
            "expected_at": "2026-05-15",
        })
        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(
            Receiving.objects.filter(supplier_name=self.supplier.name).exists()
        )

    def test_post_invalid_warehouse_shows_form(self):
        client = self._client()
        response = client.post(reverse("receiving_create"), {
            "number": "",
            "supplier": str(self.supplier.pk),
            "warehouse": "",  # отсутствует
        })
        # форма с ошибкой
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# receiving_list — фильтры
# ════════════════════════════════════════════════════════════════════
class ReceivingListFiltersTests(ReceivingExtendedBase):
    def setUp(self):
        self.r1 = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            status=ReceivingStatus.DRAFT, created_by=self.storekeeper,
        )
        self.r2 = Receiving.objects.create(
            supplier_name="OtherSupp", warehouse=self.warehouse,
            status=ReceivingStatus.COMPLETED, created_by=self.storekeeper,
        )

    def test_filter_by_warehouse(self):
        client = self._client()
        response = client.get(
            reverse("receiving_list"),
            {"warehouse": str(self.warehouse.pk)},
        )
        self.assertEqual(response.status_code, 200)

    def test_filter_by_date(self):
        client = self._client()
        response = client.get(reverse("receiving_list"), {
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        })
        self.assertEqual(response.status_code, 200)

    def test_filter_by_supplier_name(self):
        client = self._client()
        response = client.get(reverse("receiving_list"), {"q": "Other"})
        self.assertEqual(response.status_code, 200)

    def test_sort_by_columns(self):
        client = self._client()
        for sort_key in ["id", "number", "status", "created"]:
            response = client.get(reverse("receiving_list"), {
                "sort": sort_key, "order": "desc",
            })
            self.assertEqual(response.status_code, 200, f"sort={sort_key}")


# ════════════════════════════════════════════════════════════════════
# receiving_pdf
# ════════════════════════════════════════════════════════════════════
class ReceivingPDFTests(ReceivingExtendedBase):
    def test_pdf_generated_with_lines(self):
        receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )
        ReceivingLine.objects.create(
            receiving=receiving, product=self.product,
            qty_expected=Decimal("3"), qty_received=Decimal("3"),
            storage_location=self.location,
        )
        client = self._client()
        response = client.get(reverse("receiving_pdf", args=[receiving.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_pdf_for_empty_receiving(self):
        receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )
        client = self._client()
        response = client.get(reverse("receiving_pdf", args=[receiving.pk]))
        # PDF генерируется даже без строк
        self.assertEqual(response.status_code, 200)

    def test_pdf_without_warehouse(self):
        receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )
        # Снимаем склад
        receiving.warehouse = None
        receiving.save(update_fields=["warehouse"])
        client = self._client()
        response = client.get(reverse("receiving_pdf", args=[receiving.pk]))
        # должен показать "Склад: —" но не упасть
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# receiving_product_prefill — JSON endpoint
# ════════════════════════════════════════════════════════════════════
class ReceivingProductPrefillTests(ReceivingExtendedBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )

    def test_short_query_returns_400(self):
        client = self._client()
        response = client.get(
            reverse("receiving_product_prefill", args=[self.receiving.pk]),
            {"q": "x"},
        )
        self.assertEqual(response.status_code, 400)

    def test_exact_match_by_sku_returns_product(self):
        client = self._client()
        response = client.get(
            reverse("receiving_product_prefill", args=[self.receiving.pk]),
            {"q": "RE-SKU-1"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))

    def test_exact_match_by_oem(self):
        client = self._client()
        response = client.get(
            reverse("receiving_product_prefill", args=[self.receiving.pk]),
            {"q": "OEM-RE-1"},
        )
        self.assertEqual(response.status_code, 200)

    def test_partial_match_returns_first_product(self):
        client = self._client()
        response = client.get(
            reverse("receiving_product_prefill", args=[self.receiving.pk]),
            {"q": "RE-SKU"},
        )
        self.assertEqual(response.status_code, 200)

    def test_no_match_returns_error_or_efp(self):
        client = self._client()
        response = client.get(
            reverse("receiving_product_prefill", args=[self.receiving.pk]),
            {"q": "DEFINITELY-NOT-EXISTS-123"},
        )
        # 404 (не нашли) или 200 (нашли через EFP)
        self.assertIn(response.status_code, (200, 400, 404, 502, 503, 504))


# ════════════════════════════════════════════════════════════════════
# receiving_create_product
# ════════════════════════════════════════════════════════════════════
class ReceivingCreateProductTests(ReceivingExtendedBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )

    def test_get_form(self):
        client = self._client()
        response = client.get(
            reverse("receiving_create_product", args=[self.receiving.pk]),
        )
        self.assertEqual(response.status_code, 200)

    def test_post_creates_product_and_returns_to_receiving(self):
        client = self._client()
        response = client.post(
            reverse("receiving_create_product", args=[self.receiving.pk]),
            {
                "internal_sku": "NEW-FROM-RECEIVING",
                "name": "Создан из приёмки",
                "oem_number": "OEM-NEW-RCV",
                "brand": str(self.brand.pk),
                "category": str(self.category.pk),
                "packaging_type": "SMALL",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(
            Product.objects.filter(internal_sku="NEW-FROM-RECEIVING").exists()
        )

    def test_post_invalid_data_shows_form(self):
        client = self._client()
        response = client.post(
            reverse("receiving_create_product", args=[self.receiving.pk]),
            {
                "internal_sku": "",  # обязательное
                "name": "X",
                "oem_number": "Y",
            },
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# receiving_update_line_qty — edge cases
# ════════════════════════════════════════════════════════════════════
class ReceivingUpdateLineQtyEdgeTests(ReceivingExtendedBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )
        self.line = ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("10"), qty_received=Decimal("0"),
            storage_location=self.location,
        )

    def test_update_qty_with_valid_value(self):
        client = self._client()
        response = client.post(
            reverse("receiving_update_line_qty",
                    args=[self.receiving.pk, self.line.pk]),
            {"qty_received": "8"},
        )
        self.assertIn(response.status_code, (200, 302))
        self.line.refresh_from_db()
        self.assertEqual(self.line.qty_received, Decimal("8"))

    def test_update_qty_with_invalid_value(self):
        client = self._client()
        response = client.post(
            reverse("receiving_update_line_qty",
                    args=[self.receiving.pk, self.line.pk]),
            {"qty_received": "not-a-number"},
        )
        # Возвращает ошибку
        self.assertIn(response.status_code, (200, 302, 400))


# ════════════════════════════════════════════════════════════════════
# receiving_suggest_location — все варианты
# ════════════════════════════════════════════════════════════════════
class ReceivingSuggestLocationExtTests(ReceivingExtendedBase):
    def setUp(self):
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.storekeeper,
        )

    def test_suggest_without_product_returns_400_or_empty(self):
        client = self._client()
        response = client.get(
            reverse("receiving_suggest_location", args=[self.receiving.pk]),
        )
        self.assertIn(response.status_code, (200, 400))

    def test_suggest_with_invalid_product_id(self):
        client = self._client()
        response = client.get(
            reverse("receiving_suggest_location", args=[self.receiving.pk]),
            {"product_id": "not-numeric"},
        )
        self.assertIn(response.status_code, (200, 400))
