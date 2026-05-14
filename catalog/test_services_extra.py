"""
Тесты для catalog/services.py — BackorderService и ExpiryDateService.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.constants import Roles
from catalog.models import (
    Backorder,
    Branch,
    Brand,
    Category,
    Product,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
)
from catalog.services import BackorderService, ExpiryDateService
from inventory.models import Stock
from picking.models import Order, OrderLine


User = get_user_model()


class CatalogServicesFixturesMixin:
    @classmethod
    def setup_data(cls):
        cls.user = User.objects.create_user(
            username="cat_svc_user", email="cs@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
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
            internal_sku="SKU-BO-1", name="Товар",
            oem_number="OEM-BO-1", brand=brand, category=cat,
        )

    @classmethod
    def make_order_with_line(cls, qty_ordered=Decimal("5")):
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Тест", customer_phone="+79991234567",
            created_by=cls.user,
        )
        line = OrderLine.objects.create(
            order=order, product=cls.product, qty_ordered=qty_ordered,
        )
        return order, line


# ════════════════════════════════════════════════════════════════════
# BackorderService.create_backorder_from_order
# ════════════════════════════════════════════════════════════════════
class CreateBackorderTests(CatalogServicesFixturesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup_data()

    def test_returns_none_when_qty_needed_is_zero(self):
        order, line = self.make_order_with_line(qty_ordered=Decimal("3"))
        line.qty_picked = Decimal("3")
        line.save()
        result = BackorderService.create_backorder_from_order(order, line, self.user)
        self.assertIsNone(result)

    def test_returns_none_when_stock_is_sufficient(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("100"),
        )
        order, line = self.make_order_with_line(qty_ordered=Decimal("5"))
        result = BackorderService.create_backorder_from_order(order, line, self.user)
        self.assertIsNone(result)

    def test_creates_backorder_when_stock_insufficient(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("1"),
        )
        order, line = self.make_order_with_line(qty_ordered=Decimal("5"))
        bo = BackorderService.create_backorder_from_order(order, line, self.user)
        self.assertIsNotNone(bo)
        self.assertEqual(bo.product, self.product)
        self.assertEqual(bo.qty_ordered, Decimal("5"))
        self.assertEqual(bo.status, "PENDING")


# ════════════════════════════════════════════════════════════════════
# BackorderService.fulfill_backorder
# ════════════════════════════════════════════════════════════════════
class FulfillBackorderTests(CatalogServicesFixturesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup_data()

    def test_fulfill_partial_marks_partial_status(self):
        order, line = self.make_order_with_line(qty_ordered=Decimal("10"))
        bo = Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("10"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )
        ok = BackorderService.fulfill_backorder(bo, Decimal("4"), self.user)
        self.assertTrue(ok)
        bo.refresh_from_db()
        self.assertEqual(bo.qty_fulfilled, Decimal("4"))
        self.assertEqual(bo.status, "PARTIAL")

    def test_fulfill_full_marks_fulfilled(self):
        order, line = self.make_order_with_line(qty_ordered=Decimal("10"))
        bo = Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("10"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )
        ok = BackorderService.fulfill_backorder(bo, Decimal("10"), self.user)
        self.assertTrue(ok)
        bo.refresh_from_db()
        self.assertEqual(bo.status, "FULFILLED")
        self.assertIsNotNone(bo.fulfilled_at)

    def test_cannot_fulfill_already_fulfilled(self):
        order, _ = self.make_order_with_line()
        bo = Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("5"), qty_fulfilled=Decimal("5"),
            status="FULFILLED", created_by=self.user,
        )
        ok = BackorderService.fulfill_backorder(bo, Decimal("1"), self.user)
        self.assertFalse(ok)

    def test_fulfill_zero_qty_rejected(self):
        order, _ = self.make_order_with_line()
        bo = Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("5"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )
        ok = BackorderService.fulfill_backorder(bo, Decimal("0"), self.user)
        self.assertFalse(ok)

    def test_fulfill_overshoot_capped_at_remaining(self):
        order, _ = self.make_order_with_line()
        bo = Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )
        # Передаём больше чем нужно
        BackorderService.fulfill_backorder(bo, Decimal("10"), self.user)
        bo.refresh_from_db()
        # Выполнено столько сколько нужно (3), не больше
        self.assertEqual(bo.qty_fulfilled, Decimal("3"))
        self.assertEqual(bo.status, "FULFILLED")

    def test_fulfill_updates_order_line_picked_qty(self):
        order, line = self.make_order_with_line(qty_ordered=Decimal("5"))
        bo = Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("5"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )
        BackorderService.fulfill_backorder(bo, Decimal("3"), self.user)
        line.refresh_from_db()
        self.assertEqual(line.qty_picked, Decimal("3"))


# ════════════════════════════════════════════════════════════════════
# BackorderService.fulfill_backorder_for_product
# ════════════════════════════════════════════════════════════════════
class FulfillForProductTests(CatalogServicesFixturesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup_data()

    def test_fulfills_multiple_backorders_in_order(self):
        order1, _ = self.make_order_with_line(qty_ordered=Decimal("3"))
        order2, _ = self.make_order_with_line(qty_ordered=Decimal("5"))
        bo1 = Backorder.objects.create(
            order=order1, product=self.product,
            qty_ordered=Decimal("3"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )
        bo2 = Backorder.objects.create(
            order=order2, product=self.product,
            qty_ordered=Decimal("5"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )

        fulfilled = BackorderService.fulfill_backorder_for_product(
            self.product, Decimal("10"), self.user,
        )
        # Оба выполнены
        self.assertEqual(len(fulfilled), 2)
        bo1.refresh_from_db()
        bo2.refresh_from_db()
        self.assertEqual(bo1.status, "FULFILLED")
        self.assertEqual(bo2.status, "FULFILLED")

    def test_partial_fulfillment_when_qty_insufficient(self):
        order1, _ = self.make_order_with_line(qty_ordered=Decimal("10"))
        bo1 = Backorder.objects.create(
            order=order1, product=self.product,
            qty_ordered=Decimal("10"), qty_fulfilled=Decimal("0"),
            status="PENDING", created_by=self.user,
        )
        # Поступило только 4 шт
        BackorderService.fulfill_backorder_for_product(
            self.product, Decimal("4"), self.user,
        )
        bo1.refresh_from_db()
        self.assertEqual(bo1.qty_fulfilled, Decimal("4"))
        self.assertEqual(bo1.status, "PARTIAL")


# ════════════════════════════════════════════════════════════════════
# BackorderService.get_pending_backorders_for_product / by_arrival_date
# ════════════════════════════════════════════════════════════════════
class BackorderQueriesTests(CatalogServicesFixturesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup_data()

    def test_get_pending_returns_only_pending_and_partial(self):
        order, _ = self.make_order_with_line()
        Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), status="PENDING", created_by=self.user,
        )
        Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), status="PARTIAL", created_by=self.user,
        )
        Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), status="FULFILLED", created_by=self.user,
        )
        Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), status="CANCELLED", created_by=self.user,
        )
        result = BackorderService.get_pending_backorders_for_product(self.product)
        self.assertEqual(len(result), 2)

    def test_get_by_arrival_date_filters(self):
        order, _ = self.make_order_with_line()
        Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), status="PENDING",
            expected_arrival_date=date.today() + timedelta(days=5),
            created_by=self.user,
        )
        Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), status="PENDING",
            expected_arrival_date=date.today() + timedelta(days=60),
            created_by=self.user,
        )
        # По умолчанию — ближайшие 30 дней
        result = BackorderService.get_backorders_by_arrival_date()
        self.assertEqual(len(result), 1)

    def test_get_by_arrival_date_with_explicit_range(self):
        order, _ = self.make_order_with_line()
        Backorder.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), status="PENDING",
            expected_arrival_date=date(2026, 6, 15),
            created_by=self.user,
        )
        result = BackorderService.get_backorders_by_arrival_date(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
        )
        self.assertEqual(len(result), 1)


# ════════════════════════════════════════════════════════════════════
# ExpiryDateService
# ════════════════════════════════════════════════════════════════════
class ExpiryDateServiceTests(CatalogServicesFixturesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup_data()

    def test_get_expired_returns_stocks_past_today(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("3"),
            expiry_date=date.today() - timedelta(days=5),
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("2"), batch_no="ALT",
            expiry_date=date.today() + timedelta(days=5),
        )
        expired = ExpiryDateService.get_expired_stock()
        self.assertEqual(len(expired), 1)

    def test_get_expiring_soon(self):
        # Истечёт через 3 дня
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("3"),
            expiry_date=date.today() + timedelta(days=3),
        )
        # Истечёт через 60 дней — не в диапазоне 7
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("3"), batch_no="LONG",
            expiry_date=date.today() + timedelta(days=60),
        )
        result = ExpiryDateService.get_expiring_soon_stock(days_ahead=7)
        self.assertEqual(len(result), 1)

    def test_expiry_summary_returns_buckets(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("1"),
            expiry_date=date.today() - timedelta(days=2),
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("1"), batch_no="W",
            expiry_date=date.today() + timedelta(days=5),
        )
        summary = ExpiryDateService.get_expiry_summary()
        self.assertIn("expired", summary)
        self.assertIn("expiring_soon_7", summary)
        self.assertIn("expiring_soon_30", summary)
        self.assertEqual(summary["expired"]["count"], 1)
        self.assertEqual(summary["expiring_soon_7"]["count"], 1)

    def test_stock_without_expiry_excluded(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("10"),
        )
        self.assertEqual(ExpiryDateService.get_expired_stock(), [])
        self.assertEqual(ExpiryDateService.get_expiring_soon_stock(), [])
