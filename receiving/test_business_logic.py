"""
Бизнес-тесты для модуля receiving.

Покрывает:
 * ReceivingService.complete_receiving — успех, отказ без склада/строк
 * ReceivingService.validate_receiving_line — ограничения количества и веса
 * ReceivingService._create_stock_from_line — создание/слияние остатков
 * suggest_storage_location — подбор места хранения по типу упаковки
 * get_user_warehouses — фильтрация по правам пользователя
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

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
from inventory.models import Stock

from .models import Receiving, ReceivingLine, ReceivingStatus, Supplier
from .services import (
    ReceivingService,
    get_user_warehouses,
    suggest_storage_location,
)


User = get_user_model()


class ReceivingFixturesMixin:
    @classmethod
    def make_user(cls, username="storekeeper", role=Roles.STOREKEEPER, **extra):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="Pass1!ABCDEFGH",
            role=role,
            **extra,
        )

    @classmethod
    def make_warehouse(cls, code="WH1"):
        branch, _ = Branch.objects.get_or_create(code="BR1", defaults={"name": "Главный"})
        return Warehouse.objects.create(branch=branch, code=code, name=f"Склад {code}")

    @classmethod
    def make_location(cls, warehouse, zone_type_code="CELL", zone_code="Z1", loc_code="L1"):
        zt, _ = StorageZoneType.objects.get_or_create(
            code=zone_type_code, defaults={"name": zone_type_code}
        )
        zone, _ = StorageZone.objects.get_or_create(
            warehouse=warehouse, code=zone_code,
            defaults={"name": f"Зона {zone_code}", "zone_type": zt},
        )
        return StorageLocation.objects.create(zone=zone, code=loc_code, name=loc_code)

    @classmethod
    def make_product(cls, sku="SKU-R", packaging=Product.PackagingType.SMALL, **extra):
        brand, _ = Brand.objects.get_or_create(name="DENSO")
        category, _ = Category.objects.get_or_create(name="Generic")
        return Product.objects.create(
            internal_sku=sku, name=f"Товар {sku}",
            oem_number=f"OEM-{sku}", brand=brand, category=category,
            packaging_type=packaging, **extra,
        )


# ════════════════════════════════════════════════════════════════════
# SupplierForm дополнительно
# ════════════════════════════════════════════════════════════════════
class SupplierModelTests(TestCase):
    def test_supplier_str_includes_code_and_name(self):
        s = Supplier.objects.create(code="ACME", name="ACME Ltd")
        self.assertIn("ACME", str(s))
        self.assertIn("Ltd", str(s))


# ════════════════════════════════════════════════════════════════════
# Receiving.generate_next_number / generate_next_supplier_doc_number
# ════════════════════════════════════════════════════════════════════
class ReceivingNumberGenerationTests(ReceivingFixturesMixin, TestCase):
    def test_number_generated_on_save(self):
        user = self.make_user()
        warehouse = self.make_warehouse()
        receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=warehouse, created_by=user,
        )
        self.assertTrue(receiving.number.startswith("RCV-"))
        # формат RCV-YYYYMMDD-NNNN
        parts = receiving.number.split("-")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[2]), 4)

    def test_supplier_doc_number_generated_with_supplier_code(self):
        user = self.make_user()
        warehouse = self.make_warehouse()
        receiving = Receiving.objects.create(
            supplier_name="acme!!!", warehouse=warehouse, created_by=user,
        )
        # Спец-символы выбрасываются, остаётся "ACME"
        self.assertIn("ACME", receiving.supplier_doc_no.upper())


# ════════════════════════════════════════════════════════════════════
# ReceivingService.complete_receiving
# ════════════════════════════════════════════════════════════════════
class CompleteReceivingTests(ReceivingFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.location = self.make_location(self.warehouse, zone_type_code="CELL")
        self.product = self.make_product()
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse, created_by=self.user,
        )

    def test_rejects_receiving_without_warehouse(self):
        rcv = Receiving.objects.create(supplier_name="X", created_by=self.user)
        rcv.warehouse = None
        rcv.save(update_fields=["warehouse"])
        ok, msgs = ReceivingService.complete_receiving(rcv)
        self.assertFalse(ok)
        self.assertIn("склад", msgs[0].lower())

    def test_rejects_receiving_without_lines(self):
        ok, msgs = ReceivingService.complete_receiving(self.receiving)
        self.assertFalse(ok)
        self.assertIn("без строк", msgs[0].lower())

    def test_rejects_line_with_zero_qty(self):
        ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("5"), qty_received=Decimal("0"),
            storage_location=self.location,
        )
        ok, msgs = ReceivingService.complete_receiving(self.receiving)
        self.assertFalse(ok)
        self.assertTrue(any("больше нуля" in m for m in msgs))

    def test_rejects_line_without_location(self):
        ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("5"), qty_received=Decimal("5"),
        )
        ok, msgs = ReceivingService.complete_receiving(self.receiving)
        self.assertFalse(ok)
        self.assertTrue(any("место хранения" in m for m in msgs))

    def test_rejects_line_with_significant_overflow(self):
        ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("5"),
            qty_received=Decimal("10"),  # 200% — больше допуска 110%
            storage_location=self.location,
        )
        ok, msgs = ReceivingService.complete_receiving(self.receiving)
        self.assertFalse(ok)
        self.assertTrue(any("значительно больше" in m for m in msgs))

    def test_rejects_location_from_wrong_warehouse(self):
        other_warehouse = self.make_warehouse(code="WH2")
        other_loc = self.make_location(other_warehouse, zone_code="Z9", loc_code="L9")
        ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("3"), qty_received=Decimal("3"),
            storage_location=other_loc,
        )
        ok, msgs = ReceivingService.complete_receiving(self.receiving)
        self.assertFalse(ok)
        self.assertTrue(any("не относится к складу" in m for m in msgs))

    def test_complete_creates_stock_and_changes_status(self):
        ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("5"), qty_received=Decimal("5"),
            storage_location=self.location,
        )
        ok, msgs = ReceivingService.complete_receiving(self.receiving)

        self.assertTrue(ok, msgs)
        self.receiving.refresh_from_db()
        self.assertEqual(self.receiving.status, ReceivingStatus.COMPLETED)
        self.assertIsNotNone(self.receiving.completed_at)
        # Создан остаток
        stock = Stock.objects.get(product=self.product, storage_location=self.location)
        self.assertEqual(stock.qty_available, Decimal("5"))

    def test_complete_merges_stock_with_existing_batch(self):
        # Уже есть остаток того же товара/места/партии
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("3"), batch_no="BATCH-A",
        )
        ReceivingLine.objects.create(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("4"), qty_received=Decimal("4"),
            storage_location=self.location, supplier_sku="BATCH-A",
        )
        ok, msgs = ReceivingService.complete_receiving(self.receiving)
        self.assertTrue(ok, msgs)
        stock = Stock.objects.get(
            product=self.product, storage_location=self.location, batch_no="BATCH-A",
        )
        self.assertEqual(stock.qty_available, Decimal("7"))


# ════════════════════════════════════════════════════════════════════
# ReceivingService.validate_receiving_line
# ════════════════════════════════════════════════════════════════════
class ValidateReceivingLineTests(ReceivingFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.location = self.make_location(self.warehouse)
        self.product = self.make_product()
        self.receiving = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse, created_by=self.user,
        )

    def _line(self, **kw):
        defaults = dict(
            receiving=self.receiving, product=self.product,
            qty_expected=Decimal("5"), qty_received=Decimal("5"),
            storage_location=self.location,
        )
        defaults.update(kw)
        return ReceivingLine(**defaults)

    def test_qty_expected_zero_rejected(self):
        errs = ReceivingService.validate_receiving_line(self._line(qty_expected=Decimal("0")))
        self.assertTrue(any("больше нуля" in e.lower() for e in errs))

    def test_qty_received_fractional_rejected(self):
        errs = ReceivingService.validate_receiving_line(
            self._line(qty_received=Decimal("3.5"))
        )
        self.assertTrue(any("целым" in e.lower() for e in errs))

    def test_qty_received_negative_rejected(self):
        errs = ReceivingService.validate_receiving_line(
            self._line(qty_received=Decimal("-1"))
        )
        self.assertTrue(any("отрицательным" in e.lower() for e in errs))

    def test_qty_received_overflow_rejected(self):
        # Превышение 120% — отклоняем
        errs = ReceivingService.validate_receiving_line(
            self._line(qty_expected=Decimal("5"), qty_received=Decimal("10"))
        )
        self.assertTrue(any("значительно превышает" in e.lower() for e in errs))

    def test_valid_line_returns_empty_errors(self):
        errs = ReceivingService.validate_receiving_line(self._line())
        self.assertEqual(errs, [])


# ════════════════════════════════════════════════════════════════════
# suggest_storage_location
# ════════════════════════════════════════════════════════════════════
class SuggestLocationTests(ReceivingFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.cell = self.make_location(self.warehouse, zone_type_code="CELL", zone_code="ZC", loc_code="LC")
        self.shelf = self.make_location(self.warehouse, zone_type_code="SHELF", zone_code="ZS", loc_code="LS")
        self.floor = self.make_location(self.warehouse, zone_type_code="FLOOR", zone_code="ZF", loc_code="LF")

    def test_small_product_suggested_cell(self):
        prod = self.make_product(sku="SKU-SMALL", packaging=Product.PackagingType.SMALL)
        loc = suggest_storage_location(prod, warehouse=self.warehouse)
        self.assertEqual(loc.zone.zone_type.code, "CELL")

    def test_large_product_suggested_shelf(self):
        prod = self.make_product(sku="SKU-LARGE", packaging=Product.PackagingType.LARGE)
        loc = suggest_storage_location(prod, warehouse=self.warehouse)
        self.assertEqual(loc.zone.zone_type.code, "SHELF")

    def test_pallet_product_suggested_floor(self):
        prod = self.make_product(sku="SKU-PALLET", packaging=Product.PackagingType.PALLET)
        loc = suggest_storage_location(prod, warehouse=self.warehouse)
        self.assertEqual(loc.zone.zone_type.code, "FLOOR")


# ════════════════════════════════════════════════════════════════════
# get_user_warehouses
# ════════════════════════════════════════════════════════════════════
class UserWarehousesTests(ReceivingFixturesMixin, TestCase):
    def test_superuser_sees_all_active_warehouses(self):
        admin = self.make_user(username="admin1", role=Roles.ADMIN, is_superuser=True)
        self.make_warehouse(code="A1")
        self.make_warehouse(code="A2")
        qs = get_user_warehouses(admin)
        self.assertEqual(qs.count(), 2)
