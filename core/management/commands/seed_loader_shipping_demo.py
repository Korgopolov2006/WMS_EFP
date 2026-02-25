from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import Brand, Category, Product
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from tasks.models import Task, TaskPriority, TaskStatus, TaskType


DEMO_PREFIX = "SHIP-DEMO"


class Command(BaseCommand):
    help = "Создаёт реалистичный демо-заказ, готовый к отгрузке, и задачу SHIPPING для роли LOADER."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loader-username",
            default="worker_10",
            help="Логин грузчика, на которого будет назначена задача отгрузки.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        loader_username = (options.get("loader_username") or "").strip()
        if not loader_username:
            raise CommandError("Передайте валидный --loader-username.")

        loader = User.objects.filter(username=loader_username).first()
        if loader is None:
            raise CommandError(f"Пользователь `{loader_username}` не найден.")
        if loader.role != Roles.LOADER:
            loader.role = Roles.LOADER
            loader.save(update_fields=["role"])

        creator = (
            User.objects.filter(role=Roles.ADMIN).order_by("id").first()
            or User.objects.filter(is_superuser=True).order_by("id").first()
            or loader
        )
        picker = User.objects.filter(role=Roles.SMALL_PARTS_PICKER).order_by("id").first() or loader

        token = "".join(ch for ch in loader_username.upper() if ch.isalnum())[:12] or "LOADER"
        order_prefix = f"{DEMO_PREFIX}-{token}-"
        now = timezone.now()

        old_orders = Order.objects.filter(number__startswith=order_prefix)
        deleted_orders = old_orders.count()
        old_orders.delete()

        products = self._ensure_demo_products()
        order = Order.objects.create(
            number=f"{order_prefix}001",
            customer_name='ООО "АвтоЛиния Сервис"',
            customer_phone="+7 (916) 245-77-12",
            customer_email="logistics@autoline-service.ru",
            source="ONLINE",
            external_id="CRM-784512",
            status=OrderStatus.PICKED,
            created_by=creator,
            confirmed_at=now - timedelta(hours=6, minutes=20),
            picked_at=now - timedelta(hours=1, minutes=5),
            picked_by=picker,
        )

        line_specs = [
            (products["ALT"], Decimal("2.00"), Decimal("13450.00")),
            (products["BRAKE"], Decimal("4.00"), Decimal("3670.00")),
            (products["FILTER"], Decimal("12.00"), Decimal("920.00")),
        ]
        created_lines = 0
        for product, qty, price in line_specs:
            OrderLine.objects.create(
                order=order,
                product=product,
                qty_ordered=qty,
                qty_picked=qty,
                price=price,
            )
            created_lines += 1

        zone_tasks = [
            ("CELL", picker, 5),
            ("SHELF", loader, 4),
            ("FLOOR", loader, 3),
        ]
        created_picking_tasks = 0
        for zone_code, assignee, started_h in zone_tasks:
            task = PickingTask.objects.create(
                order=order,
                zone_type_code=zone_code,
                status=PickingTaskStatus.COMPLETED,
                assigned_to=assignee,
            )
            task.started_at = now - timedelta(hours=started_h)
            task.completed_at = now - timedelta(hours=started_h - 1)
            task.save(update_fields=["started_at", "completed_at"])
            created_picking_tasks += 1

        shipping_task = Task.objects.create(
            task_type=TaskType.SHIPPING,
            title=f"Отгрузка заказа {order.number}",
            description=(
                "Проверить комплектность, документы и окно выдачи. "
                "Подтвердить отгрузку с чек-листом."
            ),
            order=order,
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            assigned_to=loader,
            created_by=creator,
            due_date=now + timedelta(hours=2),
            metadata={
                "demo_seed": "loader_shipping",
                "vehicle": "Toyota Camry XV70",
                "urgency": "same_day_pickup",
            },
        )

        self.stdout.write(self.style.SUCCESS("Демо-заказ для отгрузки создан."))
        self.stdout.write(f"loader={loader.username}")
        self.stdout.write(f"order={order.number}")
        self.stdout.write(f"order_status={order.status}")
        self.stdout.write(f"shipping_task_id={shipping_task.id}")
        self.stdout.write(f"deleted_previous_orders={deleted_orders}")
        self.stdout.write(f"created_order_lines={created_lines}")
        self.stdout.write(f"created_picking_tasks={created_picking_tasks}")
        self.stdout.write(self.style.SUCCESS("Проверьте: /tasks/?my_tasks=1 и /picking/orders/?status=PICKED"))

    def _ensure_demo_products(self) -> dict[str, Product]:
        brand, _ = Brand.objects.get_or_create(name="Bosch")
        category, _ = Category.objects.get_or_create(name="Детали для ТО и ходовой")

        specs = [
            {
                "key": "ALT",
                "sku": "BOSCH-ALT-240A",
                "name": "Генератор 14V 240A",
                "oem": "BOSCH-098604Y003",
                "packaging": Product.PackagingType.LARGE,
                "weight": Decimal("7.800"),
            },
            {
                "key": "BRAKE",
                "sku": "BOSCH-BRK-FR-017",
                "name": "Диск тормозной передний 320 мм",
                "oem": "BOSCH-0986479S77",
                "packaging": Product.PackagingType.PALLET,
                "weight": Decimal("9.600"),
            },
            {
                "key": "FILTER",
                "sku": "BOSCH-OIL-FL-461",
                "name": "Фильтр масляный",
                "oem": "BOSCH-0451103461",
                "packaging": Product.PackagingType.SMALL,
                "weight": Decimal("0.320"),
            },
        ]

        result: dict[str, Product] = {}
        for item in specs:
            product, _ = Product.objects.get_or_create(
                internal_sku=item["sku"],
                defaults={
                    "name": item["name"],
                    "oem_number": item["oem"],
                    "analog_number": "",
                    "brand": brand,
                    "category": category,
                    "packaging_type": item["packaging"],
                    "weight_kg": item["weight"],
                    "length_cm": Decimal("20.00"),
                    "width_cm": Decimal("20.00"),
                    "height_cm": Decimal("20.00"),
                },
            )

            changed_fields: list[str] = []
            if product.brand_id != brand.id:
                product.brand = brand
                changed_fields.append("brand")
            if product.category_id != category.id:
                product.category = category
                changed_fields.append("category")
            if product.packaging_type != item["packaging"]:
                product.packaging_type = item["packaging"]
                changed_fields.append("packaging_type")
            if changed_fields:
                product.save(update_fields=changed_fields)

            result[item["key"]] = product

        return result
