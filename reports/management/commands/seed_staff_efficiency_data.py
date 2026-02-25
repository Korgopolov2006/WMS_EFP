from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from inventory.models import Inventory, InventoryStatus
from picking.models import Order, OrderStatus, PickingTask, PickingTaskStatus
from receiving.models import Receiving, ReceivingStatus
from tasks.models import Task, TaskPriority, TaskStatus, TaskType


USER_PREFIX = "seff_"
TASK_PREFIX = "SEFF_TASK"
ORDER_PREFIX = "SEFF-ORD-"
RECEIVING_PREFIX = "SEFF-RCV-"
INVENTORY_PREFIX = "SEFF-INV-"


class Command(BaseCommand):
    help = "Заполняет БД тестовыми данными для отчета /reports/staff-efficiency/"

    def handle(self, *args, **options):
        now = timezone.now()
        self.stdout.write(self.style.WARNING("Подготовка тестовых данных для отчета эффективности сотрудников..."))

        with transaction.atomic():
            users = self._ensure_users()

            deleted_tasks, _ = Task.objects.filter(title__startswith=TASK_PREFIX).delete()
            deleted_orders, _ = Order.objects.filter(number__startswith=ORDER_PREFIX).delete()
            deleted_receivings, _ = Receiving.objects.filter(number__startswith=RECEIVING_PREFIX).delete()
            deleted_inventories, _ = Inventory.objects.filter(number__startswith=INVENTORY_PREFIX).delete()

            orders = self._create_orders(users, now)
            picking_tasks = self._create_picking_tasks(users, orders, now)
            universal_tasks = self._create_universal_tasks(users, orders, picking_tasks, now)
            receivings = self._create_receivings(users, now)
            inventories = self._create_inventories(users, now)

        since = now - timedelta(days=30)
        active_users = User.objects.filter(username__startswith=USER_PREFIX, is_active=True).count()
        task_total = Task.objects.filter(title__startswith=TASK_PREFIX).count()
        task_completed = Task.objects.filter(
            title__startswith=TASK_PREFIX,
            status=TaskStatus.COMPLETED,
            completed_at__gte=since,
        ).count()
        picking_completed = PickingTask.objects.filter(
            order__number__startswith=ORDER_PREFIX,
            status=PickingTaskStatus.COMPLETED,
            completed_at__gte=since,
        ).count()
        orders_shipped = Order.objects.filter(
            number__startswith=ORDER_PREFIX,
            status=OrderStatus.SHIPPED,
            shipped_at__gte=since,
        ).count()

        self.stdout.write(self.style.SUCCESS("Тестовые данные staff-efficiency созданы."))
        self.stdout.write(f"deleted_demo_tasks={deleted_tasks}")
        self.stdout.write(f"deleted_demo_orders={deleted_orders}")
        self.stdout.write(f"deleted_demo_receivings={deleted_receivings}")
        self.stdout.write(f"deleted_demo_inventories={deleted_inventories}")
        self.stdout.write(f"demo_users={active_users}")
        self.stdout.write(f"created_demo_orders={len(orders)}")
        self.stdout.write(f"created_demo_picking_tasks={len(picking_tasks)}")
        self.stdout.write(f"created_demo_universal_tasks={len(universal_tasks)}")
        self.stdout.write(f"created_demo_receivings={len(receivings)}")
        self.stdout.write(f"created_demo_inventories={len(inventories)}")
        self.stdout.write(f"demo_tasks_completed_30d={task_completed}/{task_total}")
        self.stdout.write(f"demo_picking_completed_30d={picking_completed}")
        self.stdout.write(f"demo_orders_shipped_30d={orders_shipped}")
        self.stdout.write(self.style.SUCCESS("Проверьте: /reports/staff-efficiency/"))

    def _ensure_users(self) -> dict[str, User]:
        user_specs = [
            ("admin", Roles.ADMIN),
            ("storekeeper", Roles.STOREKEEPER),
            ("picker", Roles.SMALL_PARTS_PICKER),
            ("loader", Roles.LOADER),
            ("manager", Roles.SALES_MANAGER),
            ("analyst", Roles.ANALYST),
        ]
        users: dict[str, User] = {}

        for suffix, role in user_specs:
            username = f"{USER_PREFIX}{suffix}"
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "role": role,
                    "is_staff": role in (Roles.ADMIN, Roles.ANALYST),
                    "is_active": True,
                },
            )
            changed_fields: list[str] = []
            if user.role != role:
                user.role = role
                changed_fields.append("role")
            if not user.is_active:
                user.is_active = True
                changed_fields.append("is_active")
            target_is_staff = role in (Roles.ADMIN, Roles.ANALYST)
            if user.is_staff != target_is_staff:
                user.is_staff = target_is_staff
                changed_fields.append("is_staff")
            if changed_fields:
                user.save(update_fields=changed_fields)
            users[suffix] = user

        return users

    def _create_orders(self, users: dict[str, User], now):
        plan = [
            ("manager", OrderStatus.SHIPPED, "picker", 2),
            ("manager", OrderStatus.SHIPPED, "loader", 3),
            ("manager", OrderStatus.PICKED, None, 1),
            ("manager", OrderStatus.IN_PICKING, None, 1),
            ("manager", OrderStatus.CONFIRMED, None, 0),
            ("admin", OrderStatus.SHIPPED, "storekeeper", 4),
            ("admin", OrderStatus.SHIPPED, "picker", 5),
            ("admin", OrderStatus.CONFIRMED, None, 2),
            ("storekeeper", OrderStatus.SHIPPED, "loader", 6),
            ("storekeeper", OrderStatus.PICKED, None, 3),
            ("storekeeper", OrderStatus.CONFIRMED, None, 3),
            ("picker", OrderStatus.SHIPPED, "picker", 2),
            ("picker", OrderStatus.PICKED, None, 1),
            ("loader", OrderStatus.SHIPPED, "loader", 2),
            ("loader", OrderStatus.IN_PICKING, None, 1),
            ("analyst", OrderStatus.CONFIRMED, None, 1),
            ("manager", OrderStatus.CANCELLED, None, 3),
            ("admin", OrderStatus.CANCELLED, None, 7),
        ]

        orders: list[Order] = []
        for idx, (creator_key, status, picked_key, days_ago) in enumerate(plan, start=1):
            dt_base = now - timedelta(days=days_ago, hours=(idx % 7) + 1)
            order = Order.objects.create(
                number=f"{ORDER_PREFIX}{idx:03d}",
                customer_name=f"Демо клиент эффективности {idx}",
                status=status,
                created_by=users[creator_key],
                picked_by=users[picked_key] if picked_key else None,
                confirmed_at=dt_base if status != OrderStatus.DRAFT else None,
                picked_at=dt_base + timedelta(hours=1) if status in [OrderStatus.PICKED, OrderStatus.SHIPPED] else None,
                shipped_at=dt_base + timedelta(hours=2) if status == OrderStatus.SHIPPED else None,
            )
            order.created_at = dt_base
            order.save(update_fields=["created_at"])
            orders.append(order)
        return orders

    def _create_picking_tasks(self, users: dict[str, User], orders: list[Order], now):
        plan = [
            ("picker", 10, PickingTaskStatus.COMPLETED, "CELL"),
            ("picker", 2, PickingTaskStatus.IN_PROGRESS, "CELL"),
            ("picker", 1, PickingTaskStatus.PENDING, "SHELF"),
            ("loader", 6, PickingTaskStatus.COMPLETED, "FLOOR"),
            ("loader", 2, PickingTaskStatus.IN_PROGRESS, "FLOOR"),
            ("loader", 1, PickingTaskStatus.PENDING, "BULK"),
            ("storekeeper", 3, PickingTaskStatus.COMPLETED, "SHELF"),
            ("storekeeper", 1, PickingTaskStatus.PENDING, "CELL"),
            ("admin", 1, PickingTaskStatus.COMPLETED, "CELL"),
        ]

        tasks: list[PickingTask] = []
        order_idx = 0
        for assignee_key, count, status, zone_code in plan:
            for i in range(count):
                created_dt = now - timedelta(days=(i % 9) + 1, hours=(i % 6) + 1)
                order = orders[order_idx % len(orders)]
                order_idx += 1

                task = PickingTask.objects.create(
                    order=order,
                    status=status,
                    zone_type_code=zone_code,
                    assigned_to=users[assignee_key],
                )
                task.created_at = created_dt
                if status == PickingTaskStatus.IN_PROGRESS:
                    task.started_at = created_dt + timedelta(minutes=25)
                elif status == PickingTaskStatus.COMPLETED:
                    task.started_at = created_dt + timedelta(minutes=15)
                    task.completed_at = created_dt + timedelta(hours=2, minutes=10)
                task.save(update_fields=["created_at", "started_at", "completed_at"])
                tasks.append(task)
        return tasks

    def _create_universal_tasks(self, users: dict[str, User], orders: list[Order], picking_tasks: list[PickingTask], now):
        profiles = {
            "admin": {"total": 8, "completed": 6, "in_progress": 1, "pending": 1, "base_hours": 2.5},
            "storekeeper": {"total": 12, "completed": 9, "in_progress": 2, "pending": 1, "base_hours": 3.6},
            "picker": {"total": 15, "completed": 12, "in_progress": 2, "pending": 1, "base_hours": 1.4},
            "loader": {"total": 10, "completed": 7, "in_progress": 2, "pending": 1, "base_hours": 2.2},
            "manager": {"total": 6, "completed": 3, "in_progress": 1, "pending": 2, "base_hours": 4.8},
            "analyst": {"total": 5, "completed": 3, "in_progress": 1, "pending": 1, "base_hours": 4.2},
        }
        type_cycle = [
            TaskType.PICKING,
            TaskType.SHIPPING,
            TaskType.RECEIVING,
            TaskType.INVENTORY,
            TaskType.STOCK_MOVEMENT,
            TaskType.OTHER,
        ]
        priority_cycle = [
            TaskPriority.NORMAL,
            TaskPriority.HIGH,
            TaskPriority.NORMAL,
            TaskPriority.URGENT,
            TaskPriority.LOW,
        ]

        tasks: list[Task] = []
        order_idx = 0
        pick_idx = 0
        counter = 1

        for user_key, profile in profiles.items():
            assigned_to = users[user_key]
            completed_count = profile["completed"]
            in_progress_count = profile["in_progress"]
            total = profile["total"]
            base_hours = profile["base_hours"]

            for i in range(total):
                if i < completed_count:
                    status = TaskStatus.COMPLETED
                elif i < completed_count + in_progress_count:
                    status = TaskStatus.IN_PROGRESS
                else:
                    status = TaskStatus.PENDING

                created_dt = now - timedelta(days=(i % 14) + 1, hours=(i % 8) + 1)
                task_type = type_cycle[(counter - 1) % len(type_cycle)]
                priority = priority_cycle[(counter - 1) % len(priority_cycle)]

                linked_order = orders[order_idx % len(orders)] if task_type in [TaskType.SHIPPING, TaskType.OTHER] else None
                linked_picking = picking_tasks[pick_idx % len(picking_tasks)] if task_type == TaskType.PICKING else None
                if linked_order:
                    order_idx += 1
                if linked_picking:
                    pick_idx += 1

                task = Task.objects.create(
                    task_type=task_type,
                    status=status,
                    priority=priority,
                    title=f"{TASK_PREFIX} #{counter:03d}: {assigned_to.username}",
                    description="Демо-данные для аналитики эффективности сотрудников.",
                    assigned_to=assigned_to,
                    created_by=users["admin"],
                    order=linked_order,
                    picking_task=linked_picking,
                )
                task.created_at = created_dt
                if status in [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED]:
                    task.started_at = created_dt + timedelta(minutes=20)
                if status == TaskStatus.COMPLETED:
                    duration_hours = base_hours + ((i % 3) * 0.35)
                    task.completed_at = task.started_at + timedelta(hours=duration_hours)
                task.save(update_fields=["created_at", "started_at", "completed_at"])
                tasks.append(task)
                counter += 1

        return tasks

    def _create_receivings(self, users: dict[str, User], now):
        plan = [
            ("storekeeper", 4),
            ("admin", 1),
            ("loader", 1),
            ("manager", 1),
        ]
        receivings: list[Receiving] = []
        counter = 1
        for user_key, count in plan:
            for i in range(count):
                completed_dt = now - timedelta(days=(i % 10) + 1, hours=(i % 5) + 2)
                receiving = Receiving.objects.create(
                    number=f"{RECEIVING_PREFIX}{counter:03d}",
                    supplier_name="Demo Supplier",
                    status=ReceivingStatus.COMPLETED,
                    created_by=users[user_key],
                    completed_at=completed_dt,
                )
                receiving.created_at = completed_dt - timedelta(hours=4)
                receiving.save(update_fields=["created_at"])
                receivings.append(receiving)
                counter += 1
        return receivings

    def _create_inventories(self, users: dict[str, User], now):
        plan = [
            ("storekeeper", 2),
            ("admin", 1),
            ("analyst", 1),
        ]
        inventories: list[Inventory] = []
        counter = 1
        for user_key, count in plan:
            for i in range(count):
                completed_dt = now - timedelta(days=(i % 9) + 2, hours=(i % 4) + 1)
                inventory = Inventory.objects.create(
                    number=f"{INVENTORY_PREFIX}{counter:03d}",
                    status=InventoryStatus.COMPLETED,
                    created_by=users[user_key],
                    completed_at=completed_dt,
                    started_at=completed_dt - timedelta(hours=3),
                )
                inventory.created_at = completed_dt - timedelta(hours=5)
                inventory.save(update_fields=["created_at"])
                inventories.append(inventory)
                counter += 1
        return inventories
