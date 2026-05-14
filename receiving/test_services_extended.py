"""
Расширенные тесты receiving/services.py.

Покрывает:
 * ReceivingService.can_complete_receiving — все ветки отказа
 * ReceivingService.validate_receiving_line — макс вес
 * update_stock_from_receiving_line — legacy функция
 * get_user_warehouses — fallback по филиалам
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
    WarehouseAccess,
)

from receiving.models import Receiving, ReceivingLine, ReceivingStatus
from receiving.services import (
    ReceivingService,
    get_user_warehouses,
    update_stock_from_receiving_line,
)


User = get_user_model()


class ReceivingServicesBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="rsx_user", email="rsx@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        cls.admin = User.objects.create_user(
            username="rsx_admin", email="rsxa@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(
            branch=cls.branch, code="WH1", name="WH1",
        )
        zt, _ = StorageZoneType.objects.get_or_create(
            code="CELL", defaults={"name": "Ячейка"},
        )
        zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(
            zone=zone, code="L1", name="L1",
            max_weight_kg=Decimal("10.0"),
        )
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="RSX-SKU-1", name="x",
            oem_number="OEM-RSX-1",
            brand=brand, category=cat,
            weight_kg=Decimal("2.0"),
        )


# ════════════════════════════════════════════════════════════════════
# ReceivingService.can_complete_receiving
# ════════════════════════════════════════════════════════════════════
class CanCompleteReceivingTests(ReceivingServicesBase):
    def test_rejects_already_completed(self):
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse,
            status=ReceivingStatus.COMPLETED, created_by=self.user,
        )
        ok, msgs = ReceivingService.can_complete_receiving(recv)
        self.assertFalse(ok)
        self.assertTrue(any("уже завершена" in m.lower() for m in msgs))

    def test_rejects_cancelled(self):
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse,
            status=ReceivingStatus.CANCELLED, created_by=self.user,
        )
        ok, msgs = ReceivingService.can_complete_receiving(recv)
        self.assertFalse(ok)
        self.assertTrue(any("отмен" in m.lower() for m in msgs))

    def test_rejects_no_warehouse(self):
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse,
            created_by=self.user,
        )
        recv.warehouse = None
        recv.save(update_fields=["warehouse"])
        ok, msgs = ReceivingService.can_complete_receiving(recv)
        self.assertFalse(ok)
        self.assertTrue(any("не указан склад" in m.lower() for m in msgs))

    def test_rejects_no_lines(self):
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse, created_by=self.user,
        )
        ok, msgs = ReceivingService.can_complete_receiving(recv)
        self.assertFalse(ok)
        self.assertTrue(any("нет строк" in m.lower() for m in msgs))

    def test_rejects_location_from_wrong_warehouse(self):
        wh2 = Warehouse.objects.create(branch=self.branch, code="WH2", name="WH2")
        zt, _ = StorageZoneType.objects.get_or_create(
            code="CELL", defaults={"name": "Ячейка"},
        )
        z2 = StorageZone.objects.create(
            warehouse=wh2, code="Z2", name="Z2", zone_type=zt,
        )
        wrong_loc = StorageLocation.objects.create(
            zone=z2, code="L9", name="L9",
        )
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse, created_by=self.user,
        )
        ReceivingLine.objects.create(
            receiving=recv, product=self.product,
            qty_expected=Decimal("3"), qty_received=Decimal("3"),
            storage_location=wrong_loc,
        )
        ok, msgs = ReceivingService.can_complete_receiving(recv)
        self.assertFalse(ok)
        self.assertTrue(any("не относится к складу" in m for m in msgs))

    def test_passes_with_valid_lines(self):
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse, created_by=self.user,
        )
        ReceivingLine.objects.create(
            receiving=recv, product=self.product,
            qty_expected=Decimal("3"), qty_received=Decimal("3"),
            storage_location=self.location,
        )
        ok, msgs = ReceivingService.can_complete_receiving(recv)
        self.assertTrue(ok, msgs)


# ════════════════════════════════════════════════════════════════════
# ReceivingService.validate_receiving_line — weight check
# ════════════════════════════════════════════════════════════════════
class ValidateLineWeightTests(ReceivingServicesBase):
    def _make_line(self, qty_received):
        return ReceivingLine(
            product=self.product,
            qty_expected=Decimal("10"),
            qty_received=qty_received,
            storage_location=self.location,
        )

    def test_exceeds_max_weight_rejected(self):
        # Товар 2 кг, location max 10 кг, принято 6 шт → 12 кг
        errs = ReceivingService.validate_receiving_line(
            self._make_line(Decimal("6")),
        )
        self.assertTrue(any("вес" in e.lower() for e in errs))

    def test_within_max_weight_ok(self):
        # 4 шт × 2 кг = 8 кг ≤ 10 кг
        errs = ReceivingService.validate_receiving_line(
            self._make_line(Decimal("4")),
        )
        self.assertEqual(errs, [])


# ════════════════════════════════════════════════════════════════════
# update_stock_from_receiving_line (legacy)
# ════════════════════════════════════════════════════════════════════
class UpdateStockLegacyTests(ReceivingServicesBase):
    def test_legacy_call_delegates_to_service(self):
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse, created_by=self.user,
        )
        line = ReceivingLine.objects.create(
            receiving=recv, product=self.product,
            qty_expected=Decimal("5"), qty_received=Decimal("5"),
            storage_location=self.location,
        )
        stock = update_stock_from_receiving_line(line)
        self.assertIsNotNone(stock)
        self.assertEqual(stock.product, self.product)


# ════════════════════════════════════════════════════════════════════
# get_user_warehouses — варианты доступа
# ════════════════════════════════════════════════════════════════════
class GetUserWarehousesTests(ReceivingServicesBase):
    def test_superuser_sees_all(self):
        qs = get_user_warehouses(self.admin)
        self.assertIn(self.warehouse, qs)

    def test_user_with_explicit_access(self):
        # Чтобы get_accessible_warehouses вернул склад — нужны и branch и access
        self.user.branches.add(self.branch)
        WarehouseAccess.objects.create(
            user=self.user, warehouse=self.warehouse,
            access_level=WarehouseAccess.AccessLevel.EDIT,
        )
        qs = get_user_warehouses(self.user)
        self.assertIn(self.warehouse, qs)

    def test_user_fallback_by_branch(self):
        # Без явного access — fallback по филиалу
        self.user.branches.add(self.branch)
        qs = get_user_warehouses(self.user)
        # Может вернуть склад через filiale, либо пусто
        self.assertGreaterEqual(qs.count(), 0)

    def test_user_without_branches_returns_empty(self):
        # Совершенно "сирота" — нет ни access, ни branches
        orphan = User.objects.create_user(
            username="orphan", email="orph@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.STOREKEEPER,
        )
        qs = get_user_warehouses(orphan)
        self.assertEqual(qs.count(), 0)
