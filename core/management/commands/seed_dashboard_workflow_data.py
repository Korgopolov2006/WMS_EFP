from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import Branch, Brand, Category, Product, StorageLocation, StorageZone, StorageZoneType, Warehouse, WarehouseAccess
from inventory.models import Inventory, InventoryLine, InventoryStatus, MovementStatus, MovementType, Stock, StockMovement
from picking.models import Order, OrderLine, OrderPriority, OrderStatus, PickingTask, PickingTaskStatus
from receiving.models import Receiving, ReceivingLine, ReceivingStatus, Supplier
from tasks.models import Task, TaskPriority, TaskStatus, TaskType


SEED = "dashboard_workflow"


class Command(BaseCommand):
    help = "Создаёт рабочие данные для дашбордов сотрудников без демонстрационных названий."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Создание рабочих данных для дашбордов сотрудников..."))
        with transaction.atomic():
            self._clear_previous()
            warehouse_data = self._ensure_warehouse()
            products = self._ensure_products()
            self._ensure_suppliers()
            self._ensure_accesses(warehouse_data["branch"], warehouse_data["warehouse"])
            self._create_today_receiving(warehouse_data, products)
            orders = self._create_orders(products)
            picking_tasks = self._create_picking_tasks(orders)
            self._create_staff_tasks(orders, picking_tasks)
            self._create_inventory(warehouse_data, products)
            self._create_stock_movements(warehouse_data, products)

        self.stdout.write(self.style.SUCCESS("Рабочие данные для дашбордов созданы."))
        self.stdout.write("Проверьте дашборды под ролями: менеджер, кладовщик, сборщик, комплектовщик/грузчик, аналитик.")

    def _clear_previous(self) -> None:
        now = timezone.now()
        order_qs = Order.objects.filter(
            Q(source=SEED) | Q(external_id__startswith="DASH-") | Q(external_id__startswith="WORKFLOW-")
        )
        Task.objects.filter(metadata__seed=SEED).delete()
        PickingTask.objects.filter(order__in=order_qs).delete()
        order_qs.delete()
        Receiving.objects.filter(
            Q(supplier_doc_no__startswith="DASH-") | Q(number__startswith=f"RCV-{now:%Y%m%d}-92")
        ).delete()
        Inventory.objects.filter(
            Q(number__startswith="INV-DASH-") | Q(number__startswith=f"INV-{now:%Y%m%d}-92")
        ).delete()
        StockMovement.objects.filter(ref_type=SEED).delete()
        Stock.objects.filter(Q(batch_no__startswith="DASH-") | Q(batch_no__startswith=f"BATCH-{now:%Y%m%d}-")).delete()

    def _ensure_warehouse(self) -> dict[str, object]:
        branch, _ = Branch.objects.get_or_create(
            code="EFP-MSK",
            defaults={"name": "ООО «ЕФП-ПАРТС»", "address": "г. Москва, склад автозапчастей", "is_active": True},
        )
        warehouse, _ = Warehouse.objects.get_or_create(
            branch=branch,
            code="MAIN",
            defaults={
                "name": "Основной склад автозапчастей",
                "width_m": Decimal("36.00"),
                "length_m": Decimal("54.00"),
                "height_m": Decimal("8.00"),
                "is_active": True,
            },
        )
        zone_types = {
            "CELL": ("Ячейки", "Мелкие детали", 10),
            "SHELF": ("Стеллажи", "Среднегабаритные детали", 20),
            "FLOOR": ("Напольное хранение", "Крупногабаритные детали", 30),
        }
        locations: dict[str, StorageLocation] = {}
        for code, (name, description, order) in zone_types.items():
            zone_type, _ = StorageZoneType.objects.get_or_create(
                code=code,
                defaults={"name": name, "description": description, "sort_order": order},
            )
            zone, _ = StorageZone.objects.get_or_create(
                warehouse=warehouse,
                code={"CELL": "A-CELL", "SHELF": "B-SHELF", "FLOOR": "C-FLOOR"}[code],
                defaults={"name": f"{name} текущей смены", "zone_type": zone_type, "description": description},
            )
            for idx in range(1, 4):
                loc_code = f"{code[0]}{idx:02d}-01-01"
                location, _ = StorageLocation.objects.get_or_create(
                    zone=zone,
                    code=loc_code,
                    defaults={"name": f"Место {loc_code}", "aisle": code[0], "rack": str(idx), "shelf": "1", "level": "1"},
                )
                locations[loc_code] = location
        return {"branch": branch, "warehouse": warehouse, "locations": locations}

    def _ensure_accesses(self, branch: Branch, warehouse: Warehouse) -> None:
        for user in User.objects.filter(is_active=True).exclude(role=Roles.INTEGRATION):
            user.branches.add(branch)
            WarehouseAccess.objects.update_or_create(
                user=user,
                warehouse=warehouse,
                defaults={
                    "access_level": WarehouseAccess.AccessLevel.ADMIN
                    if user.role == Roles.ADMIN or user.is_superuser
                    else WarehouseAccess.AccessLevel.EDIT
                },
            )

    def _ensure_suppliers(self) -> None:
        for code, name in [
            ("ATE", "Continental Aftermarket & Services"),
            ("FILTRON", "Filtron"),
            ("OSRAM", "OSRAM Automotive"),
            ("ELRING", "ElringKlinger AG"),
        ]:
            Supplier.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})

    def _ensure_products(self) -> dict[str, Product]:
        specs = [
            ("ATE-13046071172", "ATE 13.0460-7117.2 Колодки тормозные передние", "ATE", "Тормозная система", "13046071172", "SHELF", "4200.00"),
            ("FILTRON-OP526", "Filtron OP 526 Масляный фильтр", "Filtron", "Фильтры", "OP526", "CELL", "690.00"),
            ("OSRAM-64210NL", "OSRAM Night Breaker Laser H7 64210NL", "OSRAM", "Электрика", "64210NL", "CELL", "980.00"),
            ("ELRING-036163", "Elring 036.163 Прокладка клапанной крышки", "Elring", "Двигатель", "036163", "CELL", "1350.00"),
            ("LUK-600001600", "LuK 600 0016 00 Комплект сцепления RepSet", "LuK", "Сцепление", "600001600", "FLOOR", "17300.00"),
            ("MONROE-G7322", "Monroe G7322 Амортизатор передний", "Monroe", "Подвеска", "G7322", "FLOOR", "6400.00"),
        ]
        result = {}
        for sku, name, brand_name, category_name, oem, zone_kind, price in specs:
            brand, _ = Brand.objects.get_or_create(name=brand_name)
            category, _ = Category.objects.get_or_create(name=category_name)
            product, _ = Product.objects.get_or_create(
                internal_sku=sku,
                defaults={
                    "name": name,
                    "brand": brand,
                    "category": category,
                    "oem_number": oem,
                    "packaging_type": Product.PackagingType.LARGE if zone_kind == "FLOOR" else Product.PackagingType.SMALL,
                    "weight_kg": Decimal("4.500") if zone_kind == "FLOOR" else Decimal("0.350"),
                },
            )
            product._dash_zone_kind = zone_kind
            product._dash_price = Decimal(price)
            result[sku] = product
        return result

    def _get_user_by_role(self, role: str) -> User | None:
        return User.objects.filter(role=role, is_active=True).order_by("id").first()

    def _create_today_receiving(self, warehouse_data: dict[str, object], products: dict[str, Product]) -> None:
        now = timezone.now()
        warehouse = warehouse_data["warehouse"]
        locations = warehouse_data["locations"]
        storekeeper = self._get_user_by_role(Roles.STOREKEEPER) or User.objects.filter(is_active=True).first()
        receiving = Receiving.objects.create(
            number=f"RCV-{now:%Y%m%d}-9201",
            supplier_name="Continental Aftermarket & Services",
            supplier_doc_no=f"SDOC-ATE-{now:%Y%m%d}-9201",
            warehouse=warehouse,
            status=ReceivingStatus.COMPLETED,
            expected_at=now - timedelta(hours=2),
            completed_at=now - timedelta(minutes=25),
            created_by=storekeeper,
        )
        lines = [
            ("ATE-13046071172", Decimal("18.00"), "S01-01-01"),
            ("FILTRON-OP526", Decimal("36.00"), "C01-01-01"),
            ("OSRAM-64210NL", Decimal("24.00"), "C02-01-01"),
        ]
        for sku, qty, location_code in lines:
            product = products[sku]
            location = locations[location_code]
            ReceivingLine.objects.create(
                receiving=receiving,
                product=product,
                supplier_sku=product.oem_number,
                qty_expected=qty,
                qty_received=qty,
                storage_location=location,
            )
            stock = Stock.objects.create(
                product=product,
                storage_location=location,
                qty_available=qty,
                qty_reserved=Decimal("0.00"),
                batch_no=f"BATCH-{now:%Y%m%d}-{sku.split('-', 1)[0]}",
            )
            StockMovement.objects.create(
                movement_type=MovementType.RECEIPT,
                status=MovementStatus.POSTED,
                product=product,
                quantity=qty,
                to_location=location,
                batch_no=stock.batch_no,
                reason="Поступление текущей смены",
                comment="Товар принят и размещён по местам хранения.",
                ref_type=SEED,
                ref_id=receiving.number,
                user=storekeeper,
            )

        shortage_product = products["MONROE-G7322"]
        Stock.objects.create(
            product=shortage_product,
            storage_location=locations["F01-01-01"],
            qty_available=Decimal("0.00"),
            qty_reserved=Decimal("0.00"),
            batch_no=f"BATCH-{now:%Y%m%d}-SHORT-MONROE",
        )

    def _create_orders(self, products: dict[str, Product]) -> list[Order]:
        now = timezone.now()
        manager = self._get_user_by_role(Roles.SALES_MANAGER) or User.objects.filter(is_active=True).first()
        picker = self._get_user_by_role(Roles.SMALL_PARTS_PICKER)
        plan = [
            ("СТО Северный мост", OrderStatus.DRAFT, [("ATE-13046071172", 2), ("FILTRON-OP526", 4)]),
            ("Автосервис ПрофиМотор", OrderStatus.DRAFT, [("OSRAM-64210NL", 6), ("ELRING-036163", 2)]),
            ("Техцентр Восток", OrderStatus.CONFIRMED, [("ATE-13046071172", 3), ("FILTRON-OP526", 8)]),
            ("АвтоЛига Запад", OrderStatus.CONFIRMED, [("LUK-600001600", 1), ("MONROE-G7322", 2)]),
            ("Гараж-Моторс", OrderStatus.IN_PICKING, [("OSRAM-64210NL", 4), ("ELRING-036163", 1)]),
            ("Автопарк Логистик", OrderStatus.PICKED, [("ATE-13046071172", 2), ("FILTRON-OP526", 3)]),
        ]
        orders = []
        for idx, (customer, status, lines) in enumerate(plan, start=1):
            order = Order.objects.create(
                number=f"ORD-{now:%Y%m%d}-92{idx:02d}",
                customer_name=customer,
                customer_phone=f"+7 495 92{idx:02d}-{idx:02d}-{idx:02d}",
                customer_email=f"order{idx}@service-auto.ru",
                status=status,
                priority=OrderPriority.HIGH if idx in (3, 5) else OrderPriority.NORMAL,
                shipping_due_at=now + timedelta(hours=idx + 2),
                source="MANUAL",
                external_id=f"WORKFLOW-{idx:03d}",
                confirmed_at=now - timedelta(hours=2) if status != OrderStatus.DRAFT else None,
                picked_at=now - timedelta(minutes=40) if status == OrderStatus.PICKED else None,
                created_by=manager,
                picked_by=picker if status in (OrderStatus.PICKED, OrderStatus.IN_PICKING) and picker else None,
            )
            for sku, qty_raw in lines:
                product = products[sku]
                OrderLine.objects.create(
                    order=order,
                    product=product,
                    qty_ordered=Decimal(str(qty_raw)),
                    qty_picked=Decimal(str(qty_raw if status == OrderStatus.PICKED else 0)),
                    price=product._dash_price,
                )
            orders.append(order)
        return orders

    def _create_picking_tasks(self, orders: list[Order]) -> list[PickingTask]:
        picker = self._get_user_by_role(Roles.SMALL_PARTS_PICKER)
        loader = self._get_user_by_role(Roles.LOADER)
        tasks = []
        for idx, order in enumerate(orders[2:], start=1):
            status = PickingTaskStatus.PENDING if idx in (1, 2, 4) else PickingTaskStatus.IN_PROGRESS
            zone_type = "FLOOR" if idx == 2 else ("SHELF" if idx % 2 else "CELL")
            task = PickingTask.objects.create(
                order=order,
                status=status,
                priority=order.priority,
                due_date=timezone.now() + timedelta(hours=idx + 1),
                zone_type_code=zone_type,
                assigned_to=None if status == PickingTaskStatus.PENDING else (loader if zone_type == "FLOOR" else picker),
                started_at=timezone.now() - timedelta(minutes=30) if status == PickingTaskStatus.IN_PROGRESS else None,
            )
            tasks.append(task)
        return tasks

    def _create_staff_tasks(self, orders: list[Order], picking_tasks: list[PickingTask]) -> None:
        now = timezone.now()
        role_tasks = {
            Roles.STOREKEEPER: [
                (TaskType.RECEIVING, TaskStatus.IN_PROGRESS, "Разместить поступление Continental по ячейкам"),
                (TaskType.INVENTORY, TaskStatus.PENDING, "Проверить остатки фильтров в зоне C"),
            ],
            Roles.SMALL_PARTS_PICKER: [
                (TaskType.PICKING, TaskStatus.IN_PROGRESS, "Подобрать лампы OSRAM и фильтры Filtron"),
                (TaskType.PICKING, TaskStatus.PENDING, "Проверить ячейки мелких деталей перед отгрузкой"),
            ],
            Roles.LOADER: [
                (TaskType.SHIPPING, TaskStatus.IN_PROGRESS, "Передать заказ Автопарк Логистик к окну выдачи"),
                (TaskType.PICKING, TaskStatus.PENDING, "Подготовить крупногабаритные позиции LuK и Monroe"),
            ],
            Roles.SALES_MANAGER: [
                (TaskType.OTHER, TaskStatus.IN_PROGRESS, "Согласовать заказ СТО Северный мост"),
                (TaskType.OTHER, TaskStatus.PENDING, "Проверить резерв по заказу АвтоЛига Запад"),
            ],
            Roles.ANALYST: [
                (TaskType.OTHER, TaskStatus.IN_PROGRESS, "Проверить прогноз спроса по фильтрам и колодкам"),
                (TaskType.OTHER, TaskStatus.PENDING, "Подготовить выводы по мёртвым остаткам"),
            ],
        }
        for role, specs in role_tasks.items():
            for user in User.objects.filter(role=role, is_active=True):
                for idx, (task_type, status, title) in enumerate(specs, start=1):
                    task = Task.objects.create(
                        task_type=task_type,
                        status=status,
                        priority=TaskPriority.HIGH if status == TaskStatus.IN_PROGRESS else TaskPriority.NORMAL,
                        title=title,
                        description="Рабочая задача текущей смены.",
                        assigned_to=user,
                        created_by=self._get_user_by_role(Roles.ADMIN) or user,
                        order=orders[(user.id + idx) % len(orders)] if task_type in (TaskType.SHIPPING, TaskType.OTHER) else None,
                        picking_task=picking_tasks[(user.id + idx) % len(picking_tasks)] if task_type == TaskType.PICKING and picking_tasks else None,
                        due_date=now + timedelta(hours=idx + 2),
                        metadata={"seed": SEED},
                    )
                    task.created_at = now - timedelta(minutes=40 + idx)
                    if status == TaskStatus.IN_PROGRESS:
                        task.started_at = now - timedelta(minutes=20)
                    task.save(update_fields=["created_at", "started_at"])

        admin = self._get_user_by_role(Roles.ADMIN)
        if admin:
            Task.objects.create(
                task_type=TaskType.SHIPPING,
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                title="Проконтролировать отгрузку срочного заказа",
                description="Задача доступна комплектовщику/грузчику.",
                assigned_to=None,
                created_by=admin,
                order=orders[-1],
                due_date=now + timedelta(hours=3),
                metadata={"seed": SEED},
            )

    def _create_inventory(self, warehouse_data: dict[str, object], products: dict[str, Product]) -> None:
        now = timezone.now()
        storekeeper = self._get_user_by_role(Roles.STOREKEEPER) or User.objects.filter(is_active=True).first()
        zone = StorageZone.objects.filter(code="DASH-CELL").first()
        draft = Inventory.objects.create(
            number=f"INV-{now:%Y%m%d}-9201",
            zone=zone or StorageZone.objects.filter(code="A-CELL").first(),
            status=InventoryStatus.DRAFT,
            started_at=None,
            completed_at=None,
            created_by=storekeeper,
        )
        location = warehouse_data["locations"]["C01-01-01"]
        InventoryLine.objects.create(
            inventory=draft,
            product=products["FILTRON-OP526"],
            storage_location=location,
            qty_book=Decimal("36.00"),
            qty_actual=None,
        )

    def _create_stock_movements(self, warehouse_data: dict[str, object], products: dict[str, Product]) -> None:
        user = self._get_user_by_role(Roles.STOREKEEPER) or User.objects.filter(is_active=True).first()
        locations = warehouse_data["locations"]
        StockMovement.objects.create(
            movement_type=MovementType.TRANSFER,
            status=MovementStatus.POSTED,
            product=products["FILTRON-OP526"],
            quantity=Decimal("6.00"),
            from_location=locations["C01-01-01"],
            to_location=locations["C02-01-01"],
            batch_no=f"BATCH-{timezone.now():%Y%m%d}-TRANSFER",
            reason="Выравнивание остатков текущей смены",
            comment="Часть фильтров перенесена ближе к зоне выдачи.",
            ref_type=SEED,
            ref_id=f"MOVE-{timezone.now():%Y%m%d}-9201",
            user=user,
        )
