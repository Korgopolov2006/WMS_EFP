from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import Brand, Branch, Category, Product, StorageLocation, StorageZone, StorageZoneType, Warehouse
from inventory.models import Stock
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from tasks.models import Task, TaskPriority, TaskStatus, TaskType


DEMO_ORDER_PREFIX = "SPP-DEMO"
DEMO_TASK_PREFIX = "SPP_DEMO_TASK"
DEMO_SEED_NAME = "small_parts_picker"


class Command(BaseCommand):
    help = "Создает демо-задачи для пользователя с ролью SMALL_PARTS_PICKER (по умолчанию sbor123)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="sbor123",
            help="Логин пользователя-сборщика, для которого создаются демо-задачи.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        username = (options["username"] or "").strip()
        if not username:
            raise CommandError("Нужно передать валидный --username.")

        picker = User.objects.filter(username=username).first()
        if picker is None:
            raise CommandError(f"Пользователь `{username}` не найден.")

        updated_fields: list[str] = []
        if picker.role != Roles.SMALL_PARTS_PICKER:
            picker.role = Roles.SMALL_PARTS_PICKER
            updated_fields.append("role")
        if not picker.is_active:
            picker.is_active = True
            updated_fields.append("is_active")
        if updated_fields:
            picker.save(update_fields=updated_fields)

        creator = (
            User.objects.filter(role=Roles.ADMIN).order_by("id").first()
            or User.objects.filter(is_superuser=True).order_by("id").first()
            or picker
        )

        safe_token = self._safe_token(username)
        order_prefix = f"{DEMO_ORDER_PREFIX}-{safe_token}-"
        now = timezone.now()

        task_cleanup_qs = Task.objects.filter(title__startswith=f"{DEMO_TASK_PREFIX}:{safe_token}:")
        deleted_tasks = task_cleanup_qs.count()
        task_cleanup_qs.delete()

        order_cleanup_qs = Order.objects.filter(number__startswith=order_prefix)
        deleted_orders = order_cleanup_qs.count()
        order_cleanup_qs.delete()

        location = self._ensure_cell_location()
        product = self._ensure_demo_product(safe_token)
        stock = self._ensure_stock(product, location, safe_token)

        specs = [
            {
                "suffix": "001",
                "title": "Подбор срочного заказа (ожидает старта)",
                "customer": "Демо клиент A",
                "order_status": OrderStatus.CONFIRMED,
                "picking_status": PickingTaskStatus.PENDING,
                "task_status": TaskStatus.PENDING,
                "priority": TaskPriority.HIGH,
                "qty_ordered": Decimal("6.00"),
                "qty_picked": Decimal("0.00"),
                "hours_ago": 1,
                "due_in_hours": 2,
                "assigned_picking": False,
            },
            {
                "suffix": "002",
                "title": "Подбор заказа (в работе)",
                "customer": "Демо клиент B",
                "order_status": OrderStatus.IN_PICKING,
                "picking_status": PickingTaskStatus.IN_PROGRESS,
                "task_status": TaskStatus.IN_PROGRESS,
                "priority": TaskPriority.URGENT,
                "qty_ordered": Decimal("8.00"),
                "qty_picked": Decimal("3.00"),
                "hours_ago": 4,
                "due_in_hours": 1,
                "assigned_picking": True,
            },
            {
                "suffix": "003",
                "title": "Подбор завершенного заказа",
                "customer": "Демо клиент C",
                "order_status": OrderStatus.PICKED,
                "picking_status": PickingTaskStatus.COMPLETED,
                "task_status": TaskStatus.COMPLETED,
                "priority": TaskPriority.NORMAL,
                "qty_ordered": Decimal("5.00"),
                "qty_picked": Decimal("5.00"),
                "hours_ago": 9,
                "due_in_hours": -2,
                "assigned_picking": True,
            },
        ]

        created_orders = 0
        created_picking = 0
        created_universal = 0

        for spec in specs:
            order = Order.objects.create(
                number=f"{order_prefix}{spec['suffix']}",
                customer_name=spec["customer"],
                status=spec["order_status"],
                created_by=creator,
                confirmed_at=now - timedelta(hours=spec["hours_ago"] + 1),
                picked_at=(now - timedelta(hours=max(spec["hours_ago"] - 1, 0)))
                if spec["order_status"] == OrderStatus.PICKED
                else None,
                picked_by=picker if spec["order_status"] == OrderStatus.PICKED else None,
            )
            created_orders += 1

            line = OrderLine.objects.create(
                order=order,
                product=product,
                qty_ordered=spec["qty_ordered"],
                qty_picked=spec["qty_picked"],
                price=Decimal("890.00"),
            )

            picking_task = PickingTask.objects.create(
                order=order,
                zone_type_code="CELL",
                status=spec["picking_status"],
                assigned_to=picker if spec["assigned_picking"] else None,
            )
            created_picking += 1

            picking_task.created_at = now - timedelta(hours=spec["hours_ago"])
            if spec["picking_status"] in {PickingTaskStatus.IN_PROGRESS, PickingTaskStatus.COMPLETED}:
                picking_task.started_at = now - timedelta(hours=spec["hours_ago"] - 0.25)
            if spec["picking_status"] == PickingTaskStatus.COMPLETED:
                picking_task.completed_at = now - timedelta(hours=max(spec["hours_ago"] - 0.1, 0))
            picking_task.save(update_fields=["created_at", "started_at", "completed_at"])

            task = Task.objects.create(
                task_type=TaskType.PICKING,
                title=f"{DEMO_TASK_PREFIX}:{safe_token}: {spec['title']}",
                description=(
                    "Демо-задача для роли SMALL_PARTS_PICKER. "
                    f"Заказ {order.number}, строка {line.product.internal_sku}."
                ),
                status=spec["task_status"],
                priority=spec["priority"],
                order=order,
                picking_task=picking_task,
                assigned_to=picker,
                created_by=creator,
                due_date=now + timedelta(hours=spec["due_in_hours"]),
                metadata={
                    "demo_seed": DEMO_SEED_NAME,
                    "demo_username": username,
                    "zone": "CELL",
                },
            )
            created_universal += 1

            task.created_at = now - timedelta(hours=spec["hours_ago"] + 0.5)
            if spec["task_status"] in {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED}:
                task.started_at = now - timedelta(hours=spec["hours_ago"] - 0.1)
            if spec["task_status"] == TaskStatus.COMPLETED:
                task.completed_at = now - timedelta(hours=max(spec["hours_ago"] - 0.05, 0))
            task.save(update_fields=["created_at", "started_at", "completed_at"])

        self.stdout.write(self.style.SUCCESS("Демо-задачи для роли SMALL_PARTS_PICKER подготовлены."))
        self.stdout.write(f"username={username}")
        self.stdout.write(f"role={picker.role}")
        self.stdout.write(f"deleted_orders={deleted_orders}")
        self.stdout.write(f"deleted_tasks={deleted_tasks}")
        self.stdout.write(f"created_orders={created_orders}")
        self.stdout.write(f"created_picking_tasks={created_picking}")
        self.stdout.write(f"created_universal_tasks={created_universal}")
        self.stdout.write(f"demo_sku={product.internal_sku}")
        self.stdout.write(f"stock_location={stock.storage_location.code}")
        self.stdout.write(f"stock_available={stock.qty_available}")
        self.stdout.write(self.style.SUCCESS("Проверьте: /picking/tasks/ и /tasks/?my_tasks=1"))

    def _safe_token(self, username: str) -> str:
        token = "".join(ch for ch in username.upper() if ch.isalnum())
        return token[:12] or "USER"

    def _ensure_cell_location(self) -> StorageLocation:
        existing = (
            StorageLocation.objects.select_related("zone", "zone__zone_type")
            .filter(zone__zone_type__code="CELL")
            .order_by("id")
            .first()
        )
        if existing is not None:
            return existing

        branch, _ = Branch.objects.get_or_create(
            code="DEMO",
            defaults={"name": "Демо филиал", "address": "г. Демо, ул. Складская, 1", "is_active": True},
        )
        warehouse, _ = Warehouse.objects.get_or_create(
            branch=branch,
            code="WH-DEMO",
            defaults={
                "name": "Демо склад",
                "width_m": Decimal("40.00"),
                "length_m": Decimal("60.00"),
                "height_m": Decimal("8.00"),
                "is_active": True,
            },
        )
        zone_type, _ = StorageZoneType.objects.get_or_create(
            code="CELL",
            defaults={"name": "Ячейки", "sort_order": 10},
        )
        zone, _ = StorageZone.objects.get_or_create(
            warehouse=warehouse,
            code="CELL-1",
            defaults={"name": "Ячейка демо", "zone_type": zone_type},
        )
        location, _ = StorageLocation.objects.get_or_create(
            zone=zone,
            code="C-DEMO-01",
            defaults={"name": "Демо ячейка", "max_weight_kg": Decimal("150.000")},
        )
        return location

    def _ensure_demo_product(self, safe_token: str) -> Product:
        brand, _ = Brand.objects.get_or_create(name="SPP Demo Brand")
        category, _ = Category.objects.get_or_create(name="SPP Demo Category")

        sku = f"SPP-{safe_token}-001"
        product, _ = Product.objects.get_or_create(
            internal_sku=sku,
            defaults={
                "name": "Демо фильтр для сборщика",
                "oem_number": f"SPP-OEM-{safe_token}",
                "analog_number": "",
                "brand": brand,
                "category": category,
                "packaging_type": Product.PackagingType.SMALL,
                "weight_kg": Decimal("0.250"),
                "length_cm": Decimal("12.00"),
                "width_cm": Decimal("8.00"),
                "height_cm": Decimal("8.00"),
            },
        )

        changed_fields: list[str] = []
        if product.brand_id != brand.id:
            product.brand = brand
            changed_fields.append("brand")
        if product.category_id != category.id:
            product.category = category
            changed_fields.append("category")
        if product.packaging_type != Product.PackagingType.SMALL:
            product.packaging_type = Product.PackagingType.SMALL
            changed_fields.append("packaging_type")
        if changed_fields:
            product.save(update_fields=changed_fields)

        return product

    def _ensure_stock(self, product: Product, location: StorageLocation, safe_token: str) -> Stock:
        stock, _ = Stock.objects.get_or_create(
            product=product,
            storage_location=location,
            batch_no=f"SPP-{safe_token}-B1",
            defaults={"qty_available": Decimal("150.00"), "qty_reserved": Decimal("0.00")},
        )
        changed_fields: list[str] = []
        if stock.qty_available < Decimal("50.00"):
            stock.qty_available = Decimal("150.00")
            changed_fields.append("qty_available")
        if stock.qty_reserved < Decimal("0.00"):
            stock.qty_reserved = Decimal("0.00")
            changed_fields.append("qty_reserved")
        if changed_fields:
            stock.save(update_fields=changed_fields)
        return stock
