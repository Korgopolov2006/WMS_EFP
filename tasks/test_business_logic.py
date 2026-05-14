"""
Бизнес-тесты для модуля tasks.

Покрывает:
 * TaskService.get_tasks_for_user — фильтр задач по роли
 * TaskService.assign_task_to_user — назначение и блокировки
 * TaskService.complete_task — особенности по типам (приёмка/отгрузка)
 * TaskService.create_receiving_task / create_inventory_task / create_shipping_task
 * Task.can_be_assigned_to — матрица ролей
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.constants import Roles
from catalog.models import Branch, Brand, Category, Product, Warehouse
from inventory.models import Inventory, InventoryStatus
from picking.models import Order, OrderLine, OrderStatus
from receiving.models import Receiving, ReceivingStatus

from .models import Task, TaskPriority, TaskStatus, TaskType
from .services import TaskService


User = get_user_model()


class TasksFixturesMixin:
    @classmethod
    def make_user(cls, username, role, **extra):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="Pass1!ABCDEFGH",
            role=role, **extra,
        )

    @classmethod
    def make_warehouse(cls):
        b, _ = Branch.objects.get_or_create(code="BR1", defaults={"name": "Главный"})
        return Warehouse.objects.create(branch=b, code="WH1", name="WH1")

    @classmethod
    def make_receiving(cls, user, warehouse=None):
        return Receiving.objects.create(
            supplier_name="ACME",
            warehouse=warehouse or cls.make_warehouse(),
            created_by=user,
        )

    @classmethod
    def make_order(cls, user, **kwargs):
        defaults = dict(
            customer_name="Тест", customer_phone="+79991234567",
            created_by=user,
        )
        defaults.update(kwargs)
        defaults["number"] = defaults.get("number") or Order.generate_next_number()
        return Order.objects.create(**defaults)


# ════════════════════════════════════════════════════════════════════
# TaskService.get_tasks_for_user
# ════════════════════════════════════════════════════════════════════
class GetTasksForUserTests(TasksFixturesMixin, TestCase):
    def setUp(self):
        self.admin = self.make_user("admin", Roles.ADMIN, is_superuser=True)
        self.creator = self.make_user("creator", Roles.ADMIN, is_superuser=True)
        # Создаём задачи разных типов
        self.recv_task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="recv", created_by=self.creator,
        )
        self.pick_task = Task.objects.create(
            task_type=TaskType.PICKING, title="pick", created_by=self.creator,
        )
        self.ship_task = Task.objects.create(
            task_type=TaskType.SHIPPING, title="ship", created_by=self.creator,
        )

    def test_admin_sees_all_tasks(self):
        result = list(TaskService.get_tasks_for_user(self.admin))
        self.assertEqual(len(result), 3)

    def test_storekeeper_sees_receiving_and_picking(self):
        stk = self.make_user("stk", Roles.STOREKEEPER)
        types = {t.task_type for t in TaskService.get_tasks_for_user(stk)}
        self.assertIn(TaskType.RECEIVING, types)
        self.assertIn(TaskType.PICKING, types)
        self.assertNotIn(TaskType.SHIPPING, types)

    def test_small_parts_picker_sees_only_picking(self):
        spp = self.make_user("spp", Roles.SMALL_PARTS_PICKER)
        types = {t.task_type for t in TaskService.get_tasks_for_user(spp)}
        self.assertEqual(types, {TaskType.PICKING})

    def test_loader_sees_picking_and_shipping(self):
        ld = self.make_user("ld", Roles.LOADER)
        types = {t.task_type for t in TaskService.get_tasks_for_user(ld)}
        self.assertEqual(types, {TaskType.PICKING, TaskType.SHIPPING})

    def test_analyst_sees_nothing(self):
        an = self.make_user("an", Roles.ANALYST)
        result = list(TaskService.get_tasks_for_user(an))
        self.assertEqual(result, [])


# ════════════════════════════════════════════════════════════════════
# TaskService.assign_task_to_user
# ════════════════════════════════════════════════════════════════════
class AssignTaskTests(TasksFixturesMixin, TestCase):
    def setUp(self):
        self.admin = self.make_user("admin", Roles.ADMIN, is_superuser=True)

    def test_picker_assigns_picking_task(self):
        picker = self.make_user("p1", Roles.SMALL_PARTS_PICKER)
        task = Task.objects.create(
            task_type=TaskType.PICKING, title="t", created_by=self.admin,
        )
        ok = TaskService.assign_task_to_user(task, picker)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.assigned_to, picker)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertIsNotNone(task.started_at)

    def test_cannot_grab_task_already_assigned_to_another(self):
        p1 = self.make_user("p1", Roles.SMALL_PARTS_PICKER)
        p2 = self.make_user("p2", Roles.SMALL_PARTS_PICKER)
        task = Task.objects.create(
            task_type=TaskType.PICKING, title="t",
            assigned_to=p1, created_by=self.admin,
        )
        ok = TaskService.assign_task_to_user(task, p2)
        self.assertFalse(ok)

    def test_cannot_assign_non_pending_task(self):
        picker = self.make_user("p1", Roles.SMALL_PARTS_PICKER)
        task = Task.objects.create(
            task_type=TaskType.PICKING, title="t",
            status=TaskStatus.COMPLETED, created_by=self.admin,
        )
        ok = TaskService.assign_task_to_user(task, picker)
        self.assertFalse(ok)

    def test_role_mismatch_rejected(self):
        analyst = self.make_user("an", Roles.ANALYST)
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="t", created_by=self.admin,
        )
        ok = TaskService.assign_task_to_user(task, analyst)
        self.assertFalse(ok)

    def test_starting_receiving_task_changes_document_status(self):
        stk = self.make_user("stk", Roles.STOREKEEPER)
        receiving = self.make_receiving(self.admin)
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="recv",
            receiving=receiving, created_by=self.admin,
        )
        ok = TaskService.assign_task_to_user(task, stk)
        self.assertTrue(ok)
        receiving.refresh_from_db()
        self.assertEqual(receiving.status, ReceivingStatus.IN_PROGRESS)

    def test_cannot_assign_receiving_task_for_closed_document(self):
        stk = self.make_user("stk", Roles.STOREKEEPER)
        receiving = self.make_receiving(self.admin)
        receiving.status = ReceivingStatus.COMPLETED
        receiving.save()
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="recv",
            receiving=receiving, created_by=self.admin,
        )
        ok = TaskService.assign_task_to_user(task, stk)
        self.assertFalse(ok)


# ════════════════════════════════════════════════════════════════════
# TaskService.complete_task
# ════════════════════════════════════════════════════════════════════
class CompleteTaskTests(TasksFixturesMixin, TestCase):
    def setUp(self):
        self.admin = self.make_user("admin", Roles.ADMIN, is_superuser=True)
        self.stk = self.make_user("stk", Roles.STOREKEEPER)

    def test_only_in_progress_task_can_be_completed(self):
        task = Task.objects.create(
            task_type=TaskType.OTHER, title="t",
            status=TaskStatus.PENDING, assigned_to=self.stk,
            created_by=self.admin,
        )
        self.assertFalse(TaskService.complete_task(task, self.stk))

    def test_only_assignee_can_complete(self):
        other = self.make_user("other", Roles.STOREKEEPER)
        task = Task.objects.create(
            task_type=TaskType.OTHER, title="t",
            status=TaskStatus.IN_PROGRESS, assigned_to=self.stk,
            created_by=self.admin,
        )
        self.assertFalse(TaskService.complete_task(task, other))

    def test_receiving_task_can_close_only_after_doc_completed(self):
        receiving = self.make_receiving(self.admin)
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="recv",
            status=TaskStatus.IN_PROGRESS, assigned_to=self.stk,
            receiving=receiving, created_by=self.admin,
        )
        # Документ ещё не завершён
        self.assertFalse(TaskService.complete_task(task, self.stk))
        # Завершаем документ — теперь можно
        receiving.status = ReceivingStatus.COMPLETED
        receiving.save()
        self.assertTrue(TaskService.complete_task(task, self.stk))
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_generic_task_completes_directly(self):
        task = Task.objects.create(
            task_type=TaskType.OTHER, title="t",
            status=TaskStatus.IN_PROGRESS, assigned_to=self.stk,
            created_by=self.admin,
        )
        ok = TaskService.complete_task(task, self.stk)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)


# ════════════════════════════════════════════════════════════════════
# Factory методы создания задач
# ════════════════════════════════════════════════════════════════════
class CreateTaskFactoryMethodTests(TasksFixturesMixin, TestCase):
    def test_create_receiving_task_fields(self):
        admin = self.make_user("admin", Roles.ADMIN, is_superuser=True)
        recv = self.make_receiving(admin)
        task = TaskService.create_receiving_task(recv, admin)
        self.assertEqual(task.task_type, TaskType.RECEIVING)
        self.assertEqual(task.receiving, recv)
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIn(recv.number, task.title)

    def test_create_shipping_task_inherits_priority(self):
        admin = self.make_user("admin", Roles.ADMIN, is_superuser=True)
        order = self.make_order(admin, priority="URGENT")
        task = TaskService.create_shipping_task(order, admin)
        self.assertEqual(task.task_type, TaskType.SHIPPING)
        self.assertEqual(task.order, order)
        self.assertEqual(task.priority, "URGENT")

    def test_create_inventory_task_with_zone(self):
        admin = self.make_user("admin", Roles.ADMIN, is_superuser=True)
        inv = Inventory.objects.create(number="INV-T1", created_by=admin)
        task = TaskService.create_inventory_task(inv, admin)
        self.assertEqual(task.task_type, TaskType.INVENTORY)
        self.assertEqual(task.inventory, inv)
        self.assertIn("INV-T1", task.title)
