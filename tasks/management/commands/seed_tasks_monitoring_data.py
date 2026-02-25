from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import Brand, Category, Product
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from tasks.models import Task, TaskPriority, TaskStatus, TaskType


DEMO_ORDER_PREFIX = "TMON-ORD-"
DEMO_TASK_PREFIX = "TMON_TASK"


class Command(BaseCommand):
    help = "Создает тестовые данные для страницы /tasks/monitoring/"

    def handle(self, *args, **options):
        now = timezone.now()
        self.stdout.write(self.style.WARNING("Подготовка тестовых данных для мониторинга задач..."))

        with transaction.atomic():
            users = self._ensure_demo_users()
            products = self._ensure_demo_products()

            deleted_universal, _ = Task.objects.filter(title__startswith=DEMO_TASK_PREFIX).delete()
            deleted_orders, _ = Order.objects.filter(number__startswith=DEMO_ORDER_PREFIX).delete()

            created_orders = self._create_demo_orders(users["admin"], products, now)
            created_picking = self._create_demo_picking_tasks(created_orders, users, now)
            created_universal = self._create_demo_universal_tasks(created_orders, created_picking, users, now)

        active_orders = Order.objects.filter(
            status__in=[OrderStatus.CONFIRMED, OrderStatus.IN_PICKING, OrderStatus.PICKED]
        ).count()
        pending_tasks = PickingTask.objects.filter(status=PickingTaskStatus.PENDING).count()
        in_progress_tasks = PickingTask.objects.filter(status=PickingTaskStatus.IN_PROGRESS).count()
        completed_today = PickingTask.objects.filter(
            status=PickingTaskStatus.COMPLETED,
            completed_at__date=now.date(),
        ).count()
        universal_open = Task.objects.filter(status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]).count()
        universal_overdue = Task.objects.filter(
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
            due_date__isnull=False,
            due_date__lt=now,
        ).count()

        self.stdout.write(self.style.SUCCESS("Тестовые данные мониторинга созданы."))
        self.stdout.write(f"deleted_demo_universal={deleted_universal}")
        self.stdout.write(f"deleted_demo_orders={deleted_orders}")
        self.stdout.write(f"created_demo_orders={len(created_orders)}")
        self.stdout.write(f"created_demo_picking_tasks={len(created_picking)}")
        self.stdout.write(f"created_demo_universal_tasks={len(created_universal)}")
        self.stdout.write(f"active_orders_total={active_orders}")
        self.stdout.write(f"picking_pending_total={pending_tasks}")
        self.stdout.write(f"picking_in_progress_total={in_progress_tasks}")
        self.stdout.write(f"picking_completed_today_total={completed_today}")
        self.stdout.write(f"universal_open_total={universal_open}")
        self.stdout.write(f"universal_overdue_total={universal_overdue}")
        self.stdout.write(self.style.SUCCESS("Проверьте: /tasks/monitoring/"))

    def _ensure_demo_users(self) -> dict[str, User]:
        user_specs = [
            ("tasks_demo_admin", Roles.ADMIN, True),
            ("tasks_demo_picker", Roles.SMALL_PARTS_PICKER, False),
            ("tasks_demo_loader", Roles.LOADER, False),
            ("tasks_demo_storekeeper", Roles.STOREKEEPER, False),
        ]
        users: dict[str, User] = {}

        for username, role, is_staff in user_specs:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "role": role,
                    "is_staff": is_staff,
                    "is_active": True,
                },
            )
            changed_fields: list[str] = []
            if user.role != role:
                user.role = role
                changed_fields.append("role")
            if user.is_staff != is_staff:
                user.is_staff = is_staff
                changed_fields.append("is_staff")
            if not user.is_active:
                user.is_active = True
                changed_fields.append("is_active")
            if changed_fields:
                user.save(update_fields=changed_fields)
            users[role.lower()] = user

        users["admin"] = users[Roles.ADMIN.lower()]
        users["picker"] = users[Roles.SMALL_PARTS_PICKER.lower()]
        users["loader"] = users[Roles.LOADER.lower()]
        users["storekeeper"] = users[Roles.STOREKEEPER.lower()]
        return users

    def _ensure_demo_products(self) -> list[Product]:
        brand, _ = Brand.objects.get_or_create(name="Task Demo Brand")
        category, _ = Category.objects.get_or_create(name="Task Demo Category")

        specs = [
            ("TMON-SKU-001", "Фильтр масляный TMON", "TMON-OEM-001"),
            ("TMON-SKU-002", "Колодки тормозные TMON", "TMON-OEM-002"),
            ("TMON-SKU-003", "Свеча зажигания TMON", "TMON-OEM-003"),
            ("TMON-SKU-004", "Ремень приводной TMON", "TMON-OEM-004"),
        ]

        products: list[Product] = []
        for sku, name, oem in specs:
            product, _ = Product.objects.get_or_create(
                internal_sku=sku,
                defaults={
                    "name": name,
                    "oem_number": oem,
                    "brand": brand,
                    "category": category,
                    "packaging_type": Product.PackagingType.SMALL,
                },
            )
            products.append(product)
        return products

    def _create_demo_orders(self, admin_user: User, products: list[Product], now):
        status_plan = [
            OrderStatus.CONFIRMED,
            OrderStatus.CONFIRMED,
            OrderStatus.IN_PICKING,
            OrderStatus.IN_PICKING,
            OrderStatus.PICKED,
            OrderStatus.PICKED,
            OrderStatus.SHIPPED,
            OrderStatus.CANCELLED,
        ]
        orders: list[Order] = []

        for idx, status in enumerate(status_plan, start=1):
            order = Order.objects.create(
                number=f"{DEMO_ORDER_PREFIX}{idx:03d}",
                customer_name=f"Демо клиент {idx}",
                status=status,
                created_by=admin_user,
                confirmed_at=now - timedelta(days=idx, hours=2),
                picked_at=(now - timedelta(days=idx, hours=1))
                if status in [OrderStatus.PICKED, OrderStatus.SHIPPED]
                else None,
                shipped_at=(now - timedelta(days=idx))
                if status == OrderStatus.SHIPPED
                else None,
            )
            orders.append(order)

            product = products[(idx - 1) % len(products)]
            OrderLine.objects.create(
                order=order,
                product=product,
                qty_ordered=Decimal(str(2 + idx)),
                qty_picked=Decimal(str(2 + idx if status in [OrderStatus.PICKED, OrderStatus.SHIPPED] else 0)),
                price=Decimal("1500.00") + Decimal(str(idx * 100)),
            )

        return orders

    def _create_demo_picking_tasks(self, orders, users: dict[str, User], now):
        specs = [
            {"order_index": 0, "status": PickingTaskStatus.PENDING, "zone": "CELL", "assigned": None, "created_h": 1},
            {"order_index": 1, "status": PickingTaskStatus.PENDING, "zone": "CELL", "assigned": None, "created_h": 6},
            {"order_index": 2, "status": PickingTaskStatus.IN_PROGRESS, "zone": "SHELF", "assigned": "picker", "created_h": 3},
            {"order_index": 2, "status": PickingTaskStatus.IN_PROGRESS, "zone": "FLOOR", "assigned": "loader", "created_h": 7},
            {"order_index": 3, "status": PickingTaskStatus.PENDING, "zone": "FLOOR", "assigned": None, "created_h": 5},
            {"order_index": 4, "status": PickingTaskStatus.IN_PROGRESS, "zone": "CELL", "assigned": "picker", "created_h": 2},
            {"order_index": 5, "status": PickingTaskStatus.PENDING, "zone": "BULK", "assigned": None, "created_h": 10},
            {"order_index": 4, "status": PickingTaskStatus.COMPLETED, "zone": "SHELF", "assigned": "picker", "created_h": 12, "completed_h": 2},
            {"order_index": 5, "status": PickingTaskStatus.COMPLETED, "zone": "CELL", "assigned": "loader", "created_h": 9, "completed_h": 3},
            {"order_index": 3, "status": PickingTaskStatus.COMPLETED, "zone": "FLOOR", "assigned": "picker", "created_h": 8, "completed_h": 1},
        ]

        created_tasks: list[PickingTask] = []
        for spec in specs:
            assigned_to = users.get(spec["assigned"]) if spec.get("assigned") else None
            task = PickingTask.objects.create(
                order=orders[spec["order_index"]],
                status=spec["status"],
                zone_type_code=spec["zone"],
                assigned_to=assigned_to,
            )
            created_at = now - timedelta(hours=spec["created_h"])
            task.created_at = created_at
            if task.status == PickingTaskStatus.IN_PROGRESS:
                task.started_at = created_at + timedelta(minutes=20)
            if task.status == PickingTaskStatus.COMPLETED:
                completed_h = spec.get("completed_h", 1)
                task.started_at = created_at + timedelta(minutes=15)
                task.completed_at = now - timedelta(hours=completed_h)
            task.save(update_fields=["created_at", "started_at", "completed_at"])
            created_tasks.append(task)
        return created_tasks

    def _create_demo_universal_tasks(self, orders, picking_tasks, users: dict[str, User], now):
        specs = [
            {
                "title": "Приемка срочной поставки фильтров",
                "task_type": TaskType.RECEIVING,
                "status": TaskStatus.PENDING,
                "priority": TaskPriority.URGENT,
                "assigned": "storekeeper",
                "due_in_h": -3,
                "created_h": 6,
                "order_index": None,
                "picking_ref": None,
            },
            {
                "title": "Проверить остатки зоны CELL",
                "task_type": TaskType.INVENTORY,
                "status": TaskStatus.IN_PROGRESS,
                "priority": TaskPriority.HIGH,
                "assigned": "storekeeper",
                "due_in_h": 5,
                "created_h": 8,
                "order_index": None,
                "picking_ref": None,
            },
            {
                "title": "Подтвердить отгрузку заказа",
                "task_type": TaskType.SHIPPING,
                "status": TaskStatus.PENDING,
                "priority": TaskPriority.HIGH,
                "assigned": "loader",
                "due_in_h": 2,
                "created_h": 2,
                "order_index": 4,
                "picking_ref": None,
            },
            {
                "title": "Перемещение товара в резервную зону",
                "task_type": TaskType.STOCK_MOVEMENT,
                "status": TaskStatus.PENDING,
                "priority": TaskPriority.NORMAL,
                "assigned": "storekeeper",
                "due_in_h": -1,
                "created_h": 7,
                "order_index": None,
                "picking_ref": None,
            },
            {
                "title": "Контрольный пересчет мелких деталей",
                "task_type": TaskType.INVENTORY,
                "status": TaskStatus.PENDING,
                "priority": TaskPriority.LOW,
                "assigned": "storekeeper",
                "due_in_h": 18,
                "created_h": 3,
                "order_index": None,
                "picking_ref": None,
            },
            {
                "title": "Подбор заказа с ограниченным сроком",
                "task_type": TaskType.PICKING,
                "status": TaskStatus.IN_PROGRESS,
                "priority": TaskPriority.URGENT,
                "assigned": "picker",
                "due_in_h": -2,
                "created_h": 5,
                "order_index": 2,
                "picking_ref": 2,
            },
            {
                "title": "Подготовка упаковки к выдаче",
                "task_type": TaskType.SHIPPING,
                "status": TaskStatus.IN_PROGRESS,
                "priority": TaskPriority.NORMAL,
                "assigned": "loader",
                "due_in_h": 4,
                "created_h": 4,
                "order_index": 3,
                "picking_ref": None,
            },
            {
                "title": "Аудит отмененных заказов",
                "task_type": TaskType.OTHER,
                "status": TaskStatus.PENDING,
                "priority": TaskPriority.LOW,
                "assigned": "admin",
                "due_in_h": None,
                "created_h": 1,
                "order_index": 7,
                "picking_ref": None,
            },
            {
                "title": "Ручная проверка задач подбора",
                "task_type": TaskType.PICKING,
                "status": TaskStatus.PENDING,
                "priority": TaskPriority.HIGH,
                "assigned": "picker",
                "due_in_h": 1,
                "created_h": 2,
                "order_index": 1,
                "picking_ref": 0,
            },
        ]

        created_tasks: list[Task] = []
        for spec in specs:
            created_at = now - timedelta(hours=spec["created_h"])
            due_date = now + timedelta(hours=spec["due_in_h"]) if spec["due_in_h"] is not None else None
            assigned_to = users[spec["assigned"]] if spec.get("assigned") else None
            order = orders[spec["order_index"]] if spec["order_index"] is not None else None
            picking_task = picking_tasks[spec["picking_ref"]] if spec["picking_ref"] is not None else None

            task = Task.objects.create(
                task_type=spec["task_type"],
                status=spec["status"],
                priority=spec["priority"],
                title=f"{DEMO_TASK_PREFIX}: {spec['title']}",
                description="Сгенерировано для демонстрации мониторинга.",
                order=order,
                picking_task=picking_task,
                assigned_to=assigned_to,
                created_by=users["admin"],
                due_date=due_date,
            )
            task.created_at = created_at
            if spec["status"] == TaskStatus.IN_PROGRESS:
                task.started_at = created_at + timedelta(minutes=30)
            task.save(update_fields=["created_at", "started_at"])
            created_tasks.append(task)

        return created_tasks
