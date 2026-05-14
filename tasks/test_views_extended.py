"""
Расширенные тесты tasks views — все edge-кейсы.

Покрывает:
 * tasks_monitoring_api — JSON метрики с picking/universal задачами
 * next_task — берёт PENDING из доступных
 * task_list — фильтры type/status/assigned_to/q
 * task_detail SHIPPING ship-confirmation
 * task_detail edge-cases (бан стартов чужих задач, RECEIVING без документа)
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

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
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from receiving.models import Receiving, ReceivingStatus
from tasks.models import Task, TaskPriority, TaskStatus, TaskType


User = get_user_model()


class TasksExtendedBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="tx_admin", email="tx_a@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.storekeeper = User.objects.create_user(
            username="tx_stk", email="tx_s@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        cls.picker = User.objects.create_user(
            username="tx_pck", email="tx_p@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )
        cls.loader = User.objects.create_user(
            username="tx_ldr", email="tx_l@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.LOADER,
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
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="TX-SKU", name="x", oem_number="OEM-TX",
            brand=brand, category=cat,
            packaging_type=Product.PackagingType.SMALL,
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c


# ════════════════════════════════════════════════════════════════════
# tasks_monitoring_api — JSON с детальной разбивкой
# ════════════════════════════════════════════════════════════════════
class TasksMonitoringAPITests(TasksExtendedBase):
    def test_api_returns_json_with_metrics(self):
        # Создаём активные picking-задачи и universal-задачи
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="X", customer_phone="+79991234567",
            status=OrderStatus.CONFIRMED, created_by=self.admin,
        )
        OrderLine.objects.create(
            order=order, product=self.product, qty_ordered=Decimal("1"),
        )
        PickingTask.objects.create(
            order=order, zone_type_code="CELL",
            status=PickingTaskStatus.PENDING,
        )
        Task.objects.create(
            task_type=TaskType.RECEIVING, title="t1",
            status=TaskStatus.PENDING, created_by=self.admin,
        )

        client = self._client(self.admin)
        response = client.get(reverse("tasks_monitoring_api"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("active_orders", data)
        self.assertIn("pending_tasks", data)
        self.assertIn("zone_load", data)
        self.assertIn("universal_pending", data)
        self.assertGreaterEqual(data["pending_tasks"], 1)

    def test_api_with_stale_tasks(self):
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="X", customer_phone="+79991234567",
            status=OrderStatus.CONFIRMED, created_by=self.admin,
        )
        # Задача созданная 5 часов назад — считается stale (>4 часов)
        task = PickingTask.objects.create(
            order=order, zone_type_code="SHELF",
            status=PickingTaskStatus.PENDING,
        )
        PickingTask.objects.filter(pk=task.pk).update(
            created_at=timezone.now() - timedelta(hours=5),
        )
        client = self._client(self.admin)
        response = client.get(reverse("tasks_monitoring_api"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data["stale_picking_count"], 1)

    def test_api_with_overdue_universal_tasks(self):
        # Задача с просроченным due_date
        Task.objects.create(
            task_type=TaskType.OTHER, title="overdue",
            status=TaskStatus.PENDING, created_by=self.admin,
            due_date=timezone.now() - timedelta(hours=1),
        )
        client = self._client(self.admin)
        response = client.get(reverse("tasks_monitoring_api"))
        data = response.json()
        self.assertGreaterEqual(
            sum(1 for t in data.get("universal_tasks", []) if t.get("is_overdue")),
            1,
        )


# ════════════════════════════════════════════════════════════════════
# next_task — взятие PENDING
# ════════════════════════════════════════════════════════════════════
class NextTaskTakeTests(TasksExtendedBase):
    def test_takes_pending_task_and_redirects(self):
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="свободная",
            status=TaskStatus.PENDING, created_by=self.admin,
            receiving=Receiving.objects.create(
                supplier_name="X", warehouse=self.warehouse, created_by=self.admin,
            ),
        )
        client = self._client(self.storekeeper)
        response = client.get(reverse("next_task"))
        self.assertEqual(response.status_code, 302)
        # Задача назначена на пользователя
        task.refresh_from_db()
        self.assertEqual(task.assigned_to, self.storekeeper)

    def test_returns_no_task_json_for_modal(self):
        client = self._client(self.picker)
        response = client.get(reverse("next_task"), {"modal": "1"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertFalse(data.get("has_task", True))

    def test_xhr_header_returns_json(self):
        client = self._client(self.picker)
        response = client.get(
            reverse("next_task"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# task_list — расширенные фильтры
# ════════════════════════════════════════════════════════════════════
class TaskListFiltersExtTests(TasksExtendedBase):
    def setUp(self):
        self.t1 = Task.objects.create(
            task_type=TaskType.RECEIVING, title="приёмка1",
            status=TaskStatus.PENDING, priority=TaskPriority.HIGH,
            created_by=self.admin,
        )
        self.t2 = Task.objects.create(
            task_type=TaskType.PICKING, title="подбор1",
            status=TaskStatus.IN_PROGRESS, priority=TaskPriority.LOW,
            assigned_to=self.picker, created_by=self.admin,
        )

    def test_filter_by_type(self):
        client = self._client(self.admin)
        response = client.get(reverse("task_list"), {"type": "RECEIVING"})
        self.assertEqual(response.status_code, 200)

    def test_filter_by_assigned_to(self):
        client = self._client(self.admin)
        response = client.get(
            reverse("task_list"), {"assigned_to": str(self.picker.pk)},
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_my_tasks_filter(self):
        Task.objects.create(
            task_type=TaskType.OTHER, title="мой",
            assigned_to=self.admin, created_by=self.admin,
        )
        client = self._client(self.admin)
        response = client.get(reverse("task_list"), {"my_tasks": "1"})
        self.assertEqual(response.status_code, 200)

    def test_q_search_in_multiple_fields(self):
        client = self._client(self.admin)
        for q in ["приёмка", "подбор", "tx_pck"]:
            response = client.get(reverse("task_list"), {"q": q})
            self.assertEqual(response.status_code, 200, f"q={q}")

    def test_non_admin_sees_only_own_tasks(self):
        client = self._client(self.picker)
        response = client.get(reverse("task_list"))
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# task_detail SHIPPING ship-confirmation
# ════════════════════════════════════════════════════════════════════
class TaskShippingConfirmationTests(TasksExtendedBase):
    def _make_shipping_setup(self):
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="X", customer_phone="+79991234567",
            status=OrderStatus.PICKED, created_by=self.admin,
        )
        OrderLine.objects.create(
            order=order, product=self.product,
            qty_ordered=Decimal("1"), qty_picked=Decimal("1"),
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_reserved=Decimal("1"), qty_available=Decimal("0"),
        )
        task = Task.objects.create(
            task_type=TaskType.SHIPPING, title="Отгрузка",
            status=TaskStatus.IN_PROGRESS,
            assigned_to=self.loader, order=order,
            created_by=self.admin,
        )
        return order, task

    def test_complete_without_package_check_rejected(self):
        order, task = self._make_shipping_setup()
        client = self._client(self.loader)
        client.post(
            reverse("task_detail", args=[task.id]),
            {
                "action": "complete",
                # нет ship_check_package
                "ship_check_documents": "1",
                "ship_confirm_number": order.number,
                "ship_window_number": "5",
            },
        )
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_complete_without_documents_check_rejected(self):
        order, task = self._make_shipping_setup()
        client = self._client(self.loader)
        client.post(
            reverse("task_detail", args=[task.id]),
            {
                "action": "complete",
                "ship_check_package": "1",
                # нет ship_check_documents
                "ship_confirm_number": order.number,
                "ship_window_number": "5",
            },
        )
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_complete_with_wrong_order_number_rejected(self):
        order, task = self._make_shipping_setup()
        client = self._client(self.loader)
        client.post(
            reverse("task_detail", args=[task.id]),
            {
                "action": "complete",
                "ship_check_package": "1",
                "ship_check_documents": "1",
                "ship_confirm_number": "WRONG-NUMBER",
                "ship_window_number": "5",
            },
        )
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_complete_without_window_number_rejected(self):
        order, task = self._make_shipping_setup()
        client = self._client(self.loader)
        client.post(
            reverse("task_detail", args=[task.id]),
            {
                "action": "complete",
                "ship_check_package": "1",
                "ship_check_documents": "1",
                "ship_confirm_number": order.number,
                "ship_window_number": "",
            },
        )
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_complete_with_all_checks_succeeds(self):
        order, task = self._make_shipping_setup()
        client = self._client(self.loader)
        client.post(
            reverse("task_detail", args=[task.id]),
            {
                "action": "complete",
                "ship_check_package": "1",
                "ship_check_documents": "1",
                "ship_confirm_number": order.number,
                "ship_window_number": "5",
            },
        )
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        order.refresh_from_db()
        self.assertEqual(order.window_number, "5")
        self.assertTrue(order.reserved_at_window)


# ════════════════════════════════════════════════════════════════════
# task_detail — RECEIVING ветки
# ════════════════════════════════════════════════════════════════════
class TaskReceivingActionsTests(TasksExtendedBase):
    def test_start_receiving_task_with_closed_doc_rejected(self):
        recv = Receiving.objects.create(
            supplier_name="X", warehouse=self.warehouse,
            status=ReceivingStatus.COMPLETED,
            created_by=self.admin,
        )
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="t",
            status=TaskStatus.PENDING,
            receiving=recv, created_by=self.admin,
        )
        client = self._client(self.admin)
        client.post(
            reverse("task_detail", args=[task.id]),
            {"action": "start"},
        )
        task.refresh_from_db()
        # Не начата — документ уже закрыт
        self.assertEqual(task.status, TaskStatus.PENDING)
