"""
Бизнес-тесты для модуля picking.

Покрывает:
 * OrderService.confirm_order — успех, отказ для не-draft, backorder
 * OrderService.ship_order — успех, отказ для неподготовленных
 * PickingService.create_picking_tasks_for_order — задачи разбиваются по зонам
 * PickingService.complete_picking_task — переход статуса заказа
 * suggest_stock_for_order_line / reserve_stock_for_order_line — резервирование
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
from tasks.models import Task, TaskStatus, TaskType

from .models import Order, OrderLine, OrderPriority, OrderStatus, PickingTask, PickingTaskStatus
from .services import (
    OrderService,
    PickingService,
    get_packaging_type_for_zone,
    get_zone_code_for_product,
    reserve_stock_for_order_line,
    suggest_stock_for_order_line,
)


User = get_user_model()


# ════════════════════════════════════════════════════════════════════
# ФАБРИКИ ТЕСТОВЫХ ДАННЫХ
# ════════════════════════════════════════════════════════════════════
class WMSFixturesMixin:
    """Создаёт каркас склада (Branch → Warehouse → Zone → Location)."""

    @classmethod
    def make_user(cls, username="manager", role=Roles.SALES_MANAGER, **extra):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="Pass1!ABCDEFGH",
            role=role,
            **extra,
        )

    @classmethod
    def make_warehouse(cls):
        branch = Branch.objects.create(code="BR1", name="Главный филиал")
        wh = Warehouse.objects.create(branch=branch, code="WH1", name="Основной склад")
        return wh

    @classmethod
    def make_location(cls, warehouse, zone_type_code="CELL", zone_code="Z1", loc_code="L1"):
        zone_type, _ = StorageZoneType.objects.get_or_create(
            code=zone_type_code, defaults={"name": f"Тип {zone_type_code}"}
        )
        zone, _ = StorageZone.objects.get_or_create(
            warehouse=warehouse, code=zone_code,
            defaults={"name": f"Зона {zone_code}", "zone_type": zone_type},
        )
        loc, _ = StorageLocation.objects.get_or_create(
            zone=zone, code=loc_code, defaults={"name": loc_code}
        )
        return loc

    @classmethod
    def make_product(cls, sku="SKU-1", packaging=Product.PackagingType.SMALL):
        brand, _ = Brand.objects.get_or_create(name="DENSO")
        category, _ = Category.objects.get_or_create(name="Generic")
        return Product.objects.create(
            internal_sku=sku,
            name=f"Товар {sku}",
            oem_number=f"OEM-{sku}",
            brand=brand,
            category=category,
            packaging_type=packaging,
        )

    @classmethod
    def make_order(cls, user, **extra):
        defaults = {
            "number": "",  # автогенерация
            "customer_name": "Тест Клиент",
            "customer_phone": "+7 (999) 123-45-67",
            "created_by": user,
        }
        defaults.update(extra)
        if not defaults["number"]:
            defaults["number"] = Order.generate_next_number()
        return Order.objects.create(**defaults)


# ════════════════════════════════════════════════════════════════════
# Helpers (модульные функции сервиса)
# ════════════════════════════════════════════════════════════════════
class ZoneMappingTests(TestCase):
    def test_small_packaging_maps_to_cell(self):
        p = type("P", (), {"packaging_type": Product.PackagingType.SMALL})()
        self.assertEqual(get_zone_code_for_product(p), "CELL")

    def test_large_packaging_maps_to_shelf(self):
        p = type("P", (), {"packaging_type": Product.PackagingType.LARGE})()
        self.assertEqual(get_zone_code_for_product(p), "SHELF")

    def test_pallet_packaging_maps_to_floor(self):
        p = type("P", (), {"packaging_type": Product.PackagingType.PALLET})()
        self.assertEqual(get_zone_code_for_product(p), "FLOOR")

    def test_zone_to_packaging_reversible(self):
        self.assertEqual(get_packaging_type_for_zone("CELL"), Product.PackagingType.SMALL)
        self.assertEqual(get_packaging_type_for_zone("SHELF"), Product.PackagingType.LARGE)
        self.assertEqual(get_packaging_type_for_zone("FLOOR"), Product.PackagingType.PALLET)
        self.assertIsNone(get_packaging_type_for_zone("UNKNOWN"))


# ════════════════════════════════════════════════════════════════════
# OrderService.confirm_order
# ════════════════════════════════════════════════════════════════════
class OrderConfirmTests(WMSFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.location = self.make_location(self.warehouse, zone_type_code="CELL")
        self.product = self.make_product(packaging=Product.PackagingType.SMALL)
        # Остаток есть — достаточно для подтверждения
        self.stock = Stock.objects.create(
            product=self.product,
            storage_location=self.location,
            qty_available=Decimal("10"),
            qty_reserved=Decimal("0"),
        )

    def test_confirm_draft_with_stock_creates_tasks(self):
        order = self.make_order(self.user)
        OrderLine.objects.create(order=order, product=self.product, qty_ordered=Decimal("3"))

        ok, msgs = OrderService.confirm_order(order)

        self.assertTrue(ok, msgs)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        self.assertIsNotNone(order.confirmed_at)
        # Создана задача подбора и задача отгрузки
        self.assertTrue(PickingTask.objects.filter(order=order).exists())
        self.assertTrue(Task.objects.filter(order=order, task_type=TaskType.SHIPPING).exists())

    def test_confirm_rejects_non_draft_order(self):
        order = self.make_order(self.user, status=OrderStatus.CONFIRMED)
        OrderLine.objects.create(order=order, product=self.product, qty_ordered=Decimal("1"))

        ok, msgs = OrderService.confirm_order(order)

        self.assertFalse(ok)
        self.assertIn("черновик", msgs[0].lower())

    def test_confirm_rejects_empty_order(self):
        order = self.make_order(self.user)
        # Нет строк
        ok, msgs = OrderService.confirm_order(order)

        self.assertFalse(ok)
        self.assertIn("без строк", msgs[0].lower())

    def test_confirm_creates_backorder_when_stock_insufficient(self):
        # Уменьшаем остаток ниже потребности
        self.stock.qty_available = Decimal("1")
        self.stock.save()
        order = self.make_order(self.user)
        OrderLine.objects.create(order=order, product=self.product, qty_ordered=Decimal("10"))

        ok, msgs = OrderService.confirm_order(order)

        self.assertFalse(ok)
        # Сообщение про недостаточно
        self.assertTrue(any("недостаточно" in m.lower() for m in msgs))


# ════════════════════════════════════════════════════════════════════
# OrderService.ship_order
# ════════════════════════════════════════════════════════════════════
class OrderShipTests(WMSFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.location = self.make_location(self.warehouse)
        self.product = self.make_product()

    def test_ship_rejects_draft_order(self):
        order = self.make_order(self.user)
        OrderLine.objects.create(order=order, product=self.product, qty_ordered=Decimal("2"))

        ok, msgs = OrderService.ship_order(order, self.user)

        self.assertFalse(ok)
        # Только подтверждённые/подобранные можно отгружать
        self.assertTrue(any("подтверждён" in m.lower() or "подобр" in m.lower() for m in msgs))

    def test_ship_rejects_when_lines_not_fully_picked(self):
        order = self.make_order(self.user, status=OrderStatus.CONFIRMED)
        OrderLine.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("5"), qty_picked=Decimal("2"),
        )

        ok, msgs = OrderService.ship_order(order, self.user)

        self.assertFalse(ok)
        self.assertIn("подобрано", msgs[0].lower())

    def test_ship_decrements_reserved_stock_and_updates_status(self):
        # Подготовка: товар зарезервирован под заказ
        Stock.objects.create(
            product=self.product,
            storage_location=self.location,
            qty_available=Decimal("0"),
            qty_reserved=Decimal("3"),
        )
        order = self.make_order(self.user, status=OrderStatus.PICKED)
        OrderLine.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("3"), qty_picked=Decimal("3"),
        )

        ok, msgs = OrderService.ship_order(order, self.user)

        self.assertTrue(ok, msgs)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.SHIPPED)
        self.assertIsNotNone(order.shipped_at)
        # Зарезервированный остаток списан
        stock = Stock.objects.get(product=self.product, storage_location=self.location)
        self.assertEqual(stock.qty_reserved, Decimal("0"))


# ════════════════════════════════════════════════════════════════════
# PickingService.create_picking_tasks_for_order
# ════════════════════════════════════════════════════════════════════
class CreatePickingTasksTests(WMSFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()

    def test_only_zones_with_lines_get_tasks(self):
        small = self.make_product(sku="SKU-S", packaging=Product.PackagingType.SMALL)
        order = self.make_order(self.user)
        OrderLine.objects.create(order=order, product=small, qty_ordered=Decimal("1"))

        tasks = PickingService.create_picking_tasks_for_order(order)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].zone_type_code, "CELL")

    def test_multi_packaging_creates_multiple_tasks(self):
        small = self.make_product(sku="SKU-S", packaging=Product.PackagingType.SMALL)
        large = self.make_product(sku="SKU-L", packaging=Product.PackagingType.LARGE)
        pallet = self.make_product(sku="SKU-P", packaging=Product.PackagingType.PALLET)
        order = self.make_order(self.user)
        OrderLine.objects.create(order=order, product=small, qty_ordered=Decimal("1"))
        OrderLine.objects.create(order=order, product=large, qty_ordered=Decimal("1"))
        OrderLine.objects.create(order=order, product=pallet, qty_ordered=Decimal("1"))

        tasks = PickingService.create_picking_tasks_for_order(order)

        zones = sorted(t.zone_type_code for t in tasks)
        self.assertEqual(zones, ["CELL", "FLOOR", "SHELF"])

    def test_zero_qty_lines_are_skipped(self):
        small = self.make_product(sku="SKU-S", packaging=Product.PackagingType.SMALL)
        order = self.make_order(self.user)
        OrderLine.objects.create(order=order, product=small, qty_ordered=Decimal("0"))

        tasks = PickingService.create_picking_tasks_for_order(order)
        self.assertEqual(tasks, [])


# ════════════════════════════════════════════════════════════════════
# PickingService.complete_picking_task
# ════════════════════════════════════════════════════════════════════
class CompletePickingTaskTests(WMSFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user(role=Roles.STOREKEEPER)
        self.product = self.make_product(packaging=Product.PackagingType.SMALL)
        self.order = self.make_order(self.user)
        OrderLine.objects.create(
            order=self.order, product=self.product,
            qty_ordered=Decimal("2"), qty_picked=Decimal("2"),
        )

    def test_cannot_complete_pending_task(self):
        task = PickingTask.objects.create(
            order=self.order, zone_type_code="CELL",
            status=PickingTaskStatus.PENDING,
        )
        ok, msgs = PickingService.complete_picking_task(task, self.user)

        self.assertFalse(ok)
        self.assertIn("возьмите", msgs[0].lower())

    def test_cannot_complete_already_completed_task(self):
        task = PickingTask.objects.create(
            order=self.order, zone_type_code="CELL",
            status=PickingTaskStatus.COMPLETED,
        )
        ok, msgs = PickingService.complete_picking_task(task, self.user)
        self.assertFalse(ok)
        self.assertIn("уже завершена", msgs[0].lower())

    def test_complete_task_moves_order_to_picked(self):
        task = PickingTask.objects.create(
            order=self.order, zone_type_code="CELL",
            status=PickingTaskStatus.IN_PROGRESS,
        )
        ok, msgs = PickingService.complete_picking_task(task, self.user)

        self.assertTrue(ok, msgs)
        task.refresh_from_db()
        self.assertEqual(task.status, PickingTaskStatus.COMPLETED)
        self.order.refresh_from_db()
        # У заказа только одна задача и она завершена → статус PICKED
        self.assertEqual(self.order.status, OrderStatus.PICKED)


# ════════════════════════════════════════════════════════════════════
# suggest_stock_for_order_line / reserve_stock_for_order_line
# ════════════════════════════════════════════════════════════════════
class StockReservationTests(WMSFixturesMixin, TestCase):
    def setUp(self):
        self.user = self.make_user()
        self.warehouse = self.make_warehouse()
        self.location = self.make_location(self.warehouse, zone_type_code="CELL")
        self.product = self.make_product(packaging=Product.PackagingType.SMALL)
        self.order = self.make_order(self.user)
        self.line = OrderLine.objects.create(
            order=self.order, product=self.product, qty_ordered=Decimal("3"),
        )

    def test_suggest_returns_first_matching_stock(self):
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        suggested = suggest_stock_for_order_line(self.line)
        self.assertIsNotNone(suggested)
        self.assertEqual(suggested.product_id, self.product.id)

    def test_suggest_returns_none_when_line_fully_picked(self):
        self.line.qty_picked = self.line.qty_ordered
        self.line.save()
        suggested = suggest_stock_for_order_line(self.line)
        self.assertIsNone(suggested)

    def test_reserve_moves_qty_from_available_to_reserved(self):
        stock = Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        ok = reserve_stock_for_order_line(self.line, stock, Decimal("2"))

        self.assertTrue(ok)
        stock.refresh_from_db()
        self.assertEqual(stock.qty_available, Decimal("3"))
        self.assertEqual(stock.qty_reserved, Decimal("2"))
        self.line.refresh_from_db()
        self.assertEqual(self.line.qty_picked, Decimal("2"))

    def test_reserve_rejects_qty_exceeding_available(self):
        stock = Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("1"),
        )
        ok = reserve_stock_for_order_line(self.line, stock, Decimal("5"))
        self.assertFalse(ok)

    def test_reserve_rejects_qty_exceeding_remaining_order_qty(self):
        stock = Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("100"),
        )
        # уже подобрано 2 из 3 — резерв 5 превышает остаток к подбору
        self.line.qty_picked = Decimal("2")
        self.line.save()
        ok = reserve_stock_for_order_line(self.line, stock, Decimal("5"))
        self.assertFalse(ok)

    def test_reserve_rejects_zero_qty(self):
        stock = Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("5"),
        )
        ok = reserve_stock_for_order_line(self.line, stock, Decimal("0"))
        self.assertFalse(ok)
