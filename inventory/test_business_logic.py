"""
Бизнес-тесты для модуля inventory.

Покрывает:
 * InventoryService.start_inventory — создаёт строки по остаткам
 * InventoryService.complete_inventory — обновляет Stock по фактическим данным
 * record_movement — создание записей журнала движений
 * find_analog_on_stock — поиск аналогов с достаточным остатком
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
    ProductCrossReference,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
)

from .models import (
    Inventory,
    InventoryLine,
    InventoryStatus,
    MovementStatus,
    MovementType,
    Stock,
    StockMovement,
)
from .services import (
    InventoryService,
    find_analog_on_stock,
    record_movement,
)


User = get_user_model()


class InventoryFixturesMixin:
    @classmethod
    def make_user(cls, username="storekeeper", role=Roles.STOREKEEPER):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="Pass1!ABCDEFGH",
            role=role,
        )

    @classmethod
    def make_warehouse(cls):
        branch, _ = Branch.objects.get_or_create(code="BR1", defaults={"name": "Главный"})
        return Warehouse.objects.create(branch=branch, code="WH1", name="WH1")

    @classmethod
    def make_zone(cls, warehouse, code="Z1", zone_type_code="CELL"):
        zt, _ = StorageZoneType.objects.get_or_create(
            code=zone_type_code, defaults={"name": zone_type_code}
        )
        return StorageZone.objects.create(
            warehouse=warehouse, code=code, name=f"Зона {code}", zone_type=zt,
        )

    @classmethod
    def make_location(cls, zone, code="L1"):
        return StorageLocation.objects.create(zone=zone, code=code, name=code)

    @classmethod
    def make_product(cls, sku="SKU-INV"):
        brand, _ = Brand.objects.get_or_create(name="DENSO")
        category, _ = Category.objects.get_or_create(name="Generic")
        return Product.objects.create(
            internal_sku=sku, name=f"Товар {sku}",
            oem_number=f"OEM-{sku}", brand=brand, category=category,
        )


# ════════════════════════════════════════════════════════════════════
# record_movement
# ════════════════════════════════════════════════════════════════════
class RecordMovementTests(InventoryFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.product = self.make_product()

    def test_creates_movement_record(self):
        m = record_movement(
            movement_type=MovementType.RECEIPT,
            product=self.product,
            quantity=Decimal("5"),
            user=self.user,
            reason="приёмка от поставщика",
        )
        self.assertEqual(m.movement_type, MovementType.RECEIPT)
        self.assertEqual(m.quantity, Decimal("5"))
        self.assertEqual(m.product, self.product)
        self.assertEqual(m.status, MovementStatus.POSTED)

    def test_rejects_zero_quantity(self):
        with self.assertRaises(ValueError):
            record_movement(
                movement_type=MovementType.RECEIPT,
                product=self.product,
                quantity=Decimal("0"),
            )

    def test_rejects_invalid_movement_type(self):
        with self.assertRaises(ValueError):
            record_movement(
                movement_type="BOGUS",
                product=self.product,
                quantity=Decimal("3"),
            )

    def test_stores_reference_info(self):
        m = record_movement(
            movement_type=MovementType.ISSUE,
            product=self.product,
            quantity=Decimal("2"),
            ref_type="ORDER",
            ref_id=42,
            comment="плановая отгрузка",
        )
        self.assertEqual(m.ref_type, "ORDER")
        self.assertEqual(m.ref_id, "42")
        self.assertEqual(m.comment, "плановая отгрузка")


# ════════════════════════════════════════════════════════════════════
# InventoryService.start_inventory
# ════════════════════════════════════════════════════════════════════
class StartInventoryTests(InventoryFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.zone = self.make_zone(self.warehouse, code="Z-INV", zone_type_code="CELL")
        self.location = self.make_location(self.zone, code="L-1")
        self.product = self.make_product()
        # Создаём остаток в зоне
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("10"),
        )

    def test_start_creates_lines_from_stock(self):
        inv = Inventory.objects.create(number="INV-1", zone=self.zone, created_by=self.user)
        ok, msgs = InventoryService.start_inventory(inv, self.user)

        self.assertTrue(ok, msgs)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InventoryStatus.IN_PROGRESS)
        self.assertIsNotNone(inv.started_at)
        # Создана строка с qty_book = qty_available
        line = InventoryLine.objects.get(inventory=inv, product=self.product)
        self.assertEqual(line.qty_book, Decimal("10"))
        self.assertIsNone(line.qty_actual)

    def test_cannot_start_non_draft_inventory(self):
        inv = Inventory.objects.create(
            number="INV-2", zone=self.zone,
            status=InventoryStatus.COMPLETED, created_by=self.user,
        )
        ok, msgs = InventoryService.start_inventory(inv, self.user)
        self.assertFalse(ok)
        self.assertIn("черновик", msgs[0].lower())

    def test_cannot_start_inventory_with_existing_lines(self):
        inv = Inventory.objects.create(number="INV-3", zone=self.zone, created_by=self.user)
        InventoryLine.objects.create(
            inventory=inv, product=self.product,
            storage_location=self.location, qty_book=Decimal("5"),
        )
        ok, msgs = InventoryService.start_inventory(inv, self.user)
        self.assertFalse(ok)
        self.assertIn("уже созданы", msgs[0].lower())


# ════════════════════════════════════════════════════════════════════
# InventoryService.complete_inventory
# ════════════════════════════════════════════════════════════════════
class CompleteInventoryTests(InventoryFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.zone = self.make_zone(self.warehouse)
        self.location = self.make_location(self.zone)
        self.product = self.make_product()
        self.stock = Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("10"),
        )
        self.inv = Inventory.objects.create(
            number="INV-CMP", zone=self.zone,
            status=InventoryStatus.IN_PROGRESS, created_by=self.user,
        )

    def test_cannot_complete_with_unfilled_lines(self):
        InventoryLine.objects.create(
            inventory=self.inv, product=self.product,
            storage_location=self.location,
            qty_book=Decimal("10"), qty_actual=None,
        )
        ok, msgs = InventoryService.complete_inventory(self.inv, self.user)
        self.assertFalse(ok)
        self.assertTrue(any("не заполнены" in m.lower() for m in msgs))

    def test_cannot_complete_with_fractional_actual_qty(self):
        InventoryLine.objects.create(
            inventory=self.inv, product=self.product,
            storage_location=self.location,
            qty_book=Decimal("10"), qty_actual=Decimal("9.5"),
        )
        ok, msgs = InventoryService.complete_inventory(self.inv, self.user)
        self.assertFalse(ok)
        self.assertTrue(any("целыми" in m.lower() for m in msgs))

    def test_complete_updates_stock_to_actual(self):
        InventoryLine.objects.create(
            inventory=self.inv, product=self.product,
            storage_location=self.location,
            qty_book=Decimal("10"), qty_actual=Decimal("8"),
        )
        ok, msgs = InventoryService.complete_inventory(self.inv, self.user)
        self.assertTrue(ok, msgs)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, InventoryStatus.COMPLETED)
        # Остаток обновился до фактического
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.qty_available, Decimal("8"))

    def test_cannot_complete_non_in_progress(self):
        self.inv.status = InventoryStatus.DRAFT
        self.inv.save()
        ok, msgs = InventoryService.complete_inventory(self.inv, self.user)
        self.assertFalse(ok)


# ════════════════════════════════════════════════════════════════════
# find_analog_on_stock
# ════════════════════════════════════════════════════════════════════
class FindAnalogOnStockTests(InventoryFixturesMixin, TestCase):
    def setUp(self):
        self.warehouse = self.make_warehouse()
        self.zone = self.make_zone(self.warehouse)
        self.location = self.make_location(self.zone)
        self.original = self.make_product(sku="ORIGINAL")
        self.analog = self.make_product(sku="ANALOG")
        # Связываем как аналоги
        ProductCrossReference.objects.create(
            from_product=self.original,
            to_product=self.analog,
            relation_type="ANALOG",
        )

    def test_finds_analog_with_enough_stock(self):
        Stock.objects.create(
            product=self.analog, storage_location=self.location,
            qty_available=Decimal("20"),
        )
        result = find_analog_on_stock(self.original, qty_needed=Decimal("10"))
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["sufficient"])
        self.assertEqual(result[0]["product"], self.analog)

    def test_marks_partial_stock_as_insufficient(self):
        Stock.objects.create(
            product=self.analog, storage_location=self.location,
            qty_available=Decimal("3"),
        )
        result = find_analog_on_stock(self.original, qty_needed=Decimal("10"))
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["sufficient"])

    def test_no_results_when_analog_has_zero_stock(self):
        # Аналог есть, остатка нет
        result = find_analog_on_stock(self.original, qty_needed=Decimal("10"))
        self.assertEqual(result, [])


# ════════════════════════════════════════════════════════════════════
# Model properties / __str__
# ════════════════════════════════════════════════════════════════════
class StockModelTests(InventoryFixturesMixin, TestCase):
    def test_qty_total_is_available_plus_reserved(self):
        wh = self.make_warehouse()
        zone = self.make_zone(wh)
        loc = self.make_location(zone)
        product = self.make_product()
        stock = Stock.objects.create(
            product=product, storage_location=loc,
            qty_available=Decimal("5"), qty_reserved=Decimal("2"),
        )
        self.assertEqual(stock.qty_total, Decimal("7"))
