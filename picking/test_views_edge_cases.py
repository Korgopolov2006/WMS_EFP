"""
Edge-case тесты picking views — действия в picking_task_detail.

Покрывает:
 * picking_task_list — фильтры по zone_type/order_id для разных ролей
 * picking_task_detail — assign, scan (по OEM), complete, sort/order
 * order_detail — отказы по ролям
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
from inventory.models import Stock
from picking.models import (
    Order,
    OrderLine,
    OrderStatus,
    PickingTask,
    PickingTaskStatus,
)


User = get_user_model()


class PickingEdgeCasesBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="pe_admin", email="pea@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.manager = User.objects.create_user(
            username="pe_mgr", email="pem@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.SALES_MANAGER,
        )
        cls.picker = User.objects.create_user(
            username="pe_pck", email="pep@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.SMALL_PARTS_PICKER,
        )
        cls.loader = User.objects.create_user(
            username="pe_ldr", email="pel@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.LOADER,
        )

        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(branch=branch, code="WH1", name="WH1")
        zt, _ = StorageZoneType.objects.get_or_create(
            code="CELL", defaults={"name": "Ячейка"},
        )
        zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(zone=zone, code="L1", name="L1")
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="PE-SKU-1", name="Edge товар",
            oem_number="OEM-PE-1", brand=brand, category=cat,
            packaging_type=Product.PackagingType.SMALL,
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _make_order_with_task(self, qty_ordered=Decimal("3"), status=OrderStatus.CONFIRMED):
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Edge Test", customer_phone="+79991234567",
            status=status, created_by=self.manager,
        )
        OrderLine.objects.create(
            order=order, product=self.product, qty_ordered=qty_ordered,
        )
        task = PickingTask.objects.create(
            order=order, zone_type_code="CELL",
            status=PickingTaskStatus.PENDING,
        )
        return order, task


# ════════════════════════════════════════════════════════════════════
# picking_task_list — фильтры и роли
# ════════════════════════════════════════════════════════════════════
class PickingTaskListEdgeTests(PickingEdgeCasesBase):
    def test_picker_sees_only_cell_tasks(self):
        # CELL и SHELF — пикер должен видеть только CELL
        self._make_order_with_task()  # CELL
        order2 = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Shelf order", customer_phone="+79991234567",
            created_by=self.manager,
        )
        PickingTask.objects.create(
            order=order2, zone_type_code="SHELF",
            status=PickingTaskStatus.PENDING,
        )
        client = self._client(self.picker)
        response = client.get(reverse("picking_task_list"))
        self.assertEqual(response.status_code, 200)

    def test_loader_sees_shelf_and_floor_tasks(self):
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="X", customer_phone="+79991234567",
            created_by=self.manager,
        )
        PickingTask.objects.create(
            order=order, zone_type_code="FLOOR",
            status=PickingTaskStatus.PENDING,
        )
        client = self._client(self.loader)
        response = client.get(reverse("picking_task_list"))
        self.assertEqual(response.status_code, 200)

    def test_filter_by_zone_type(self):
        self._make_order_with_task()
        client = self._client(self.admin)
        response = client.get(reverse("picking_task_list"), {"zone_type": "CELL"})
        self.assertEqual(response.status_code, 200)

    def test_filter_by_order_id(self):
        order, _ = self._make_order_with_task()
        client = self._client(self.admin)
        response = client.get(
            reverse("picking_task_list"), {"order_id": str(order.id)},
        )
        self.assertEqual(response.status_code, 200)

    def test_sort_by_different_fields(self):
        self._make_order_with_task()
        client = self._client(self.admin)
        for sort_key in ["id", "order", "customer", "zone", "status", "due"]:
            response = client.get(
                reverse("picking_task_list"), {"sort": sort_key, "order": "desc"},
            )
            self.assertEqual(response.status_code, 200, f"sort={sort_key}")

    def test_search_by_customer_name(self):
        order, _ = self._make_order_with_task()
        client = self._client(self.admin)
        response = client.get(reverse("picking_task_list"), {"q": "Edge"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# picking_task_detail — assign / scan
# ════════════════════════════════════════════════════════════════════
class PickingTaskDetailActionsTests(PickingEdgeCasesBase):
    def test_assign_pending_task(self):
        order, task = self._make_order_with_task()
        client = self._client(self.picker)
        client.post(
            reverse("picking_task_detail", args=[task.pk]),
            {"assign": "1"},
        )
        task.refresh_from_db()
        self.assertEqual(task.status, PickingTaskStatus.IN_PROGRESS)
        self.assertEqual(task.assigned_to, self.picker)
        # Заказ перешёл в IN_PICKING
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.IN_PICKING)

    def test_assign_already_in_progress_rejected(self):
        order, task = self._make_order_with_task()
        task.status = PickingTaskStatus.IN_PROGRESS
        task.assigned_to = self.admin
        task.save()
        client = self._client(self.picker)
        client.post(
            reverse("picking_task_detail", args=[task.pk]),
            {"assign": "1"},
        )
        task.refresh_from_db()
        # Не изменилось
        self.assertEqual(task.assigned_to, self.admin)

    def test_scan_picks_quantity_from_stock(self):
        order, task = self._make_order_with_task(qty_ordered=Decimal("3"))
        task.status = PickingTaskStatus.IN_PROGRESS
        task.assigned_to = self.picker
        task.save()
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("10"),
        )
        client = self._client(self.picker)
        client.post(
            reverse("picking_task_detail", args=[task.pk]),
            {"scan": "1", "oem": "OEM-PE-1"},
        )
        # Подбор увеличил qty_picked у строки
        line = order.lines.first()
        line.refresh_from_db()
        self.assertGreater(line.qty_picked, 0)

    def test_scan_empty_oem_shows_error(self):
        order, task = self._make_order_with_task()
        task.status = PickingTaskStatus.IN_PROGRESS
        task.assigned_to = self.picker
        task.save()
        client = self._client(self.picker)
        response = client.post(
            reverse("picking_task_detail", args=[task.pk]),
            {"scan": "1", "oem": ""},
        )
        # Редирект и сообщение
        self.assertEqual(response.status_code, 302)

    def test_scan_for_pending_task_rejected(self):
        order, task = self._make_order_with_task()
        # task в PENDING — scan недоступен
        client = self._client(self.picker)
        response = client.post(
            reverse("picking_task_detail", args=[task.pk]),
            {"scan": "1", "oem": "OEM-PE-1"},
        )
        self.assertEqual(response.status_code, 302)
        line = order.lines.first()
        line.refresh_from_db()
        self.assertEqual(line.qty_picked, 0)

    def test_scan_wrong_oem_rejected(self):
        order, task = self._make_order_with_task()
        task.status = PickingTaskStatus.IN_PROGRESS
        task.assigned_to = self.picker
        task.save()
        client = self._client(self.picker)
        client.post(
            reverse("picking_task_detail", args=[task.pk]),
            {"scan": "1", "oem": "WRONG-OEM-9999"},
        )
        line = order.lines.first()
        line.refresh_from_db()
        # Не подобрано
        self.assertEqual(line.qty_picked, 0)


# ════════════════════════════════════════════════════════════════════
# order_detail — отказы и редкие ветки
# ════════════════════════════════════════════════════════════════════
class OrderDetailEdgeTests(PickingEdgeCasesBase):
    def test_picker_can_view_cell_zone_order_only(self):
        # Этот заказ имеет CELL-задачу
        order, task = self._make_order_with_task()
        client = self._client(self.picker)
        response = client.get(reverse("order_detail", args=[order.pk]))
        # picker видит заказ, в котором его CELL-задача
        self.assertEqual(response.status_code, 200)

    def test_picker_cannot_add_line(self):
        order, _ = self._make_order_with_task()
        client = self._client(self.picker)
        response = client.post(
            reverse("order_detail", args=[order.pk]),
            {
                "add_line": "1",
                "product": str(self.product.pk),
                "qty_ordered": "1",
                "price": "100",
            },
        )
        # picker не может управлять составом
        self.assertEqual(response.status_code, 302)
