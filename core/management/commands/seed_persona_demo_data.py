from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import (
    Brand,
    Branch,
    Category,
    Product,
    StorageLocation,
    Warehouse,
    WarehouseAccess,
)
from inventory.models import Inventory, InventoryStatus, Stock
from picking.models import Order, OrderLine, OrderStatus, PickingTaskStatus
from picking.services import OrderService, reserve_stock_for_order_line, suggest_stock_for_order_line
from receiving.models import Receiving, ReceivingLine, ReceivingStatus
from tasks.models import Task, TaskPriority, TaskStatus, TaskType
from tasks.services import TaskService


@dataclass(frozen=True)
class PersonaConfig:
    username: str
    password: str
    role: str
    branch_code: str
    warehouse_code: str
    access_level: str
    first_name: str
    last_name: str


PERSONAS: tuple[PersonaConfig, ...] = (
    PersonaConfig(
        username="clad123",
        password="Q1w2e3r4t5y6!",
        role=Roles.STOREKEEPER,
        branch_code="MAIN",
        warehouse_code="WH-01",
        access_level=WarehouseAccess.AccessLevel.EDIT,
        first_name="Игорь",
        last_name="Кладовщиков",
    ),
    PersonaConfig(
        username="sbor123",
        password="Q1w2e3r4t5y6!",
        role=Roles.SMALL_PARTS_PICKER,
        branch_code="MSK",
        warehouse_code="WH1",
        access_level=WarehouseAccess.AccessLevel.EDIT,
        first_name="Олег",
        last_name="Сборщиков",
    ),
    PersonaConfig(
        username="komplect",
        password="Q1w2e3r4t5y6!",
        role=Roles.LOADER,
        branch_code="MSK",
        warehouse_code="WH1",
        access_level=WarehouseAccess.AccessLevel.EDIT,
        first_name="Павел",
        last_name="Комплектовщиков",
    ),
    PersonaConfig(
        username="manager",
        password="Q1w2e3r4t5y6!",
        role=Roles.SALES_MANAGER,
        branch_code="MSK",
        warehouse_code="WH1",
        access_level=WarehouseAccess.AccessLevel.VIEW,
        first_name="Марина",
        last_name="Менеджерова",
    ),
    PersonaConfig(
        username="analatic",
        password="Q1w2e3r4t5y6!",
        role=Roles.ANALYST,
        branch_code="MSK",
        warehouse_code="WH1",
        access_level=WarehouseAccess.AccessLevel.VIEW,
        first_name="Анна",
        last_name="Аналитикова",
    ),
)


class Command(BaseCommand):
    help = "Создаёт реалистичные демо-заказы и задачи для заданных ролевых пользователей."

    def handle(self, *args, **options):
        with transaction.atomic():
            personas = self._ensure_personas()
            warehouses = self._resolve_target_warehouses(personas)
            self._ensure_access(personas, warehouses)
            demo_products = self._ensure_demo_products()
            self._ensure_demo_stock(demo_products, warehouses)
            self._seed_storekeeper_flow(personas["clad123"], warehouses["MAIN"], demo_products)
            self._seed_sales_flow(
                manager=personas["manager"],
                picker=personas["sbor123"],
                loader=personas["komplect"],
                warehouse=warehouses["MSK"],
                products=demo_products,
            )
        self.stdout.write(self.style.SUCCESS("Demo data for personas created/updated successfully."))

    def _ensure_personas(self) -> dict[str, User]:
        result: dict[str, User] = {}
        for cfg in PERSONAS:
            user = User.objects.filter(username=cfg.username).first()
            if user is None:
                raise CommandError(f"Пользователь `{cfg.username}` не найден. Сначала создайте учётную запись.")
            user.role = cfg.role
            user.first_name = cfg.first_name
            user.last_name = cfg.last_name
            user.is_active = True
            user.set_password(cfg.password)
            user.save(update_fields=["role", "first_name", "last_name", "is_active", "password"])
            result[cfg.username] = user
            self.stdout.write(f"  • Пользователь {cfg.username}: роль={cfg.role}, пароль обновлён")
        return result

    def _resolve_target_warehouses(self, personas: dict[str, User]) -> dict[str, Warehouse]:
        all_active = Warehouse.objects.filter(is_active=True).select_related("branch")
        if not all_active.exists():
            raise CommandError("Нет активных складов. Создайте хотя бы один склад перед сидированием.")

        def pick(branch_code: str, warehouse_code: str) -> Warehouse:
            wh = all_active.filter(branch__code=branch_code, code=warehouse_code).first()
            if wh:
                return wh
            branch_wh = all_active.filter(branch__code=branch_code).first()
            if branch_wh:
                return branch_wh
            return all_active.first()

        msk = pick("MSK", "WH1")
        main = pick("MAIN", "WH-01")
        if msk is None or main is None:
            raise CommandError("Не удалось определить склады для демо-данных.")

        self.stdout.write(f"  • Склад MAIN: {main.branch.code}/{main.code}")
        self.stdout.write(f"  • Склад MSK: {msk.branch.code}/{msk.code}")
        return {"MAIN": main, "MSK": msk}

    def _ensure_access(self, personas: dict[str, User], warehouses: dict[str, Warehouse]) -> None:
        cfg_map = {cfg.username: cfg for cfg in PERSONAS}
        for username, user in personas.items():
            cfg = cfg_map[username]
            warehouse = warehouses["MAIN"] if cfg.branch_code == "MAIN" else warehouses["MSK"]

            branch: Branch = warehouse.branch
            user.branches.add(branch)

            access, created = WarehouseAccess.objects.get_or_create(
                user=user,
                warehouse=warehouse,
                defaults={"access_level": cfg.access_level},
            )
            if access.access_level != cfg.access_level:
                access.access_level = cfg.access_level
                access.save(update_fields=["access_level"])

            mode = "создан" if created else "обновлён"
            self.stdout.write(
                f"  • Доступ {username} -> {warehouse.branch.code}/{warehouse.code}: {access.access_level} ({mode})"
            )

    def _ensure_demo_products(self) -> dict[str, Product]:
        brand, _ = Brand.objects.get_or_create(name="Demo Mobility")
        category, _ = Category.objects.get_or_create(name="Демо запчасти")

        specs = (
            {
                "sku": "DMO-SMALL-001",
                "name": "Фильтр масляный M14",
                "oem": "DMO-OEM-51001",
                "packaging": Product.PackagingType.SMALL,
                "weight": Decimal("0.420"),
            },
            {
                "sku": "DMO-SMALL-002",
                "name": "Свеча зажигания иридиевая",
                "oem": "DMO-OEM-51002",
                "packaging": Product.PackagingType.SMALL,
                "weight": Decimal("0.070"),
            },
            {
                "sku": "DMO-LARGE-001",
                "name": "Диск тормозной передний",
                "oem": "DMO-OEM-52001",
                "packaging": Product.PackagingType.LARGE,
                "weight": Decimal("8.500"),
            },
            {
                "sku": "DMO-PALLET-001",
                "name": "Двигатель в сборе 2.0",
                "oem": "DMO-OEM-53001",
                "packaging": Product.PackagingType.PALLET,
                "weight": Decimal("145.000"),
            },
        )

        products: dict[str, Product] = {}
        for item in specs:
            product, created = Product.objects.get_or_create(
                internal_sku=item["sku"],
                defaults={
                    "name": item["name"],
                    "oem_number": item["oem"],
                    "analog_number": "",
                    "brand": brand,
                    "category": category,
                    "packaging_type": item["packaging"],
                    "weight_kg": item["weight"],
                    "length_cm": Decimal("35.00"),
                    "width_cm": Decimal("25.00"),
                    "height_cm": Decimal("20.00"),
                },
            )
            if not created:
                changed = False
                if product.packaging_type != item["packaging"]:
                    product.packaging_type = item["packaging"]
                    changed = True
                if product.brand_id != brand.id:
                    product.brand = brand
                    changed = True
                if product.category_id != category.id:
                    product.category = category
                    changed = True
                if changed:
                    product.save(update_fields=["packaging_type", "brand", "category"])
            products[item["sku"]] = product
        self.stdout.write(f"  • Демо-товаров в контуре: {len(products)}")
        return products

    def _pick_location(self, warehouse: Warehouse, zone_type_code: str) -> StorageLocation:
        location = (
            StorageLocation.objects.select_related("zone", "zone__warehouse")
            .filter(
                zone__warehouse=warehouse,
                zone__zone_type__code=zone_type_code,
            )
            .order_by("code", "id")
            .first()
        )
        if location is None:
            raise CommandError(
                f"На складе {warehouse.branch.code}/{warehouse.code} нет места хранения для зоны {zone_type_code}."
            )
        return location

    def _ensure_demo_stock(self, products: dict[str, Product], warehouses: dict[str, Warehouse]) -> None:
        msk = warehouses["MSK"]
        main = warehouses["MAIN"]

        msk_locations = {
            "SMALL": self._pick_location(msk, "CELL"),
            "LARGE": self._pick_location(msk, "SHELF"),
            "PALLET": self._pick_location(msk, "FLOOR"),
        }
        main_locations = {
            "SMALL": self._pick_location(main, "CELL"),
            "LARGE": self._pick_location(main, "SHELF"),
        }

        stock_plan = (
            (products["DMO-SMALL-001"], msk_locations["SMALL"], Decimal("120.00"), "DEMO-MSK-A"),
            (products["DMO-SMALL-002"], msk_locations["SMALL"], Decimal("200.00"), "DEMO-MSK-B"),
            (products["DMO-LARGE-001"], msk_locations["LARGE"], Decimal("45.00"), "DEMO-MSK-C"),
            (products["DMO-PALLET-001"], msk_locations["PALLET"], Decimal("8.00"), "DEMO-MSK-D"),
            (products["DMO-SMALL-001"], main_locations["SMALL"], Decimal("60.00"), "DEMO-MAIN-A"),
            (products["DMO-LARGE-001"], main_locations["LARGE"], Decimal("18.00"), "DEMO-MAIN-B"),
        )
        for product, location, qty_available, batch_no in stock_plan:
            stock, _ = Stock.objects.get_or_create(
                product=product,
                storage_location=location,
                batch_no=batch_no,
                defaults={"qty_available": qty_available, "qty_reserved": Decimal("0.00")},
            )
            if stock.qty_available < qty_available:
                stock.qty_available = qty_available
                stock.save(update_fields=["qty_available"])

        self.stdout.write("  • Демо-остатки подготовлены")

    def _ensure_order_line(self, order: Order, product: Product, qty: Decimal, price: Decimal) -> None:
        line, created = OrderLine.objects.get_or_create(
            order=order,
            product=product,
            defaults={"qty_ordered": qty, "qty_picked": Decimal("0.00"), "price": price},
        )
        if not created and line.qty_ordered != qty:
            line.qty_ordered = qty
            line.price = price
            line.save(update_fields=["qty_ordered", "price"])

    def _ensure_task(
        self,
        *,
        task_type: str,
        title: str,
        created_by: User,
        assigned_to: User | None = None,
        status: str = TaskStatus.PENDING,
        priority: str = TaskPriority.NORMAL,
        due_date=None,
        receiving: Receiving | None = None,
        inventory: Inventory | None = None,
        order: Order | None = None,
    ) -> Task:
        task = (
            Task.objects.filter(
                task_type=task_type,
                title=title,
                receiving=receiving,
                inventory=inventory,
                order=order,
            )
            .order_by("-id")
            .first()
        )
        if task is None:
            task = Task.objects.create(
                task_type=task_type,
                title=title,
                description="Демо-задача для ролевого сценария",
                created_by=created_by,
                receiving=receiving,
                inventory=inventory,
                order=order,
                assigned_to=assigned_to,
                status=status,
                priority=priority,
                due_date=due_date,
            )
        else:
            update_fields = []
            if task.assigned_to_id != (assigned_to.id if assigned_to else None):
                task.assigned_to = assigned_to
                update_fields.append("assigned_to")
            if task.status != status:
                task.status = status
                update_fields.append("status")
            if task.priority != priority:
                task.priority = priority
                update_fields.append("priority")
            if task.due_date != due_date:
                task.due_date = due_date
                update_fields.append("due_date")
            if update_fields:
                task.save(update_fields=update_fields)
        return task

    def _seed_storekeeper_flow(self, storekeeper: User, warehouse: Warehouse, products: dict[str, Product]) -> None:
        now = timezone.now()
        receiving, _ = Receiving.objects.get_or_create(
            number="RCV-DM-CLAD-01",
            defaults={
                "supplier_name": "ООО АвтоПром Логистик",
                "supplier_doc_no": "UPD-10488",
                "warehouse": warehouse,
                "status": ReceivingStatus.IN_PROGRESS,
                "created_by": storekeeper,
                "expected_at": now,
            },
        )
        if receiving.warehouse_id != warehouse.id:
            receiving.warehouse = warehouse
            receiving.save(update_fields=["warehouse"])

        cell_loc = self._pick_location(warehouse, "CELL")
        shelf_loc = self._pick_location(warehouse, "SHELF")
        ReceivingLine.objects.get_or_create(
            receiving=receiving,
            product=products["DMO-SMALL-001"],
            defaults={
                "supplier_sku": "SUP-FLTR-001",
                "qty_expected": Decimal("30.00"),
                "qty_received": Decimal("12.00"),
                "storage_location": cell_loc,
            },
        )
        ReceivingLine.objects.get_or_create(
            receiving=receiving,
            product=products["DMO-LARGE-001"],
            defaults={
                "supplier_sku": "SUP-BRK-020",
                "qty_expected": Decimal("10.00"),
                "qty_received": Decimal("4.00"),
                "storage_location": shelf_loc,
            },
        )

        self._ensure_task(
            task_type=TaskType.RECEIVING,
            title=f"Приёмка {receiving.number}",
            created_by=storekeeper,
            assigned_to=storekeeper,
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            due_date=now + timedelta(hours=6),
            receiving=receiving,
        )

        inventory, _ = Inventory.objects.get_or_create(
            number="INV-DM-CLAD-01",
            defaults={
                "zone": cell_loc.zone,
                "status": InventoryStatus.DRAFT,
                "created_by": storekeeper,
            },
        )
        self._ensure_task(
            task_type=TaskType.INVENTORY,
            title=f"Инвентаризация {inventory.number}",
            created_by=storekeeper,
            assigned_to=storekeeper,
            status=TaskStatus.PENDING,
            priority=TaskPriority.NORMAL,
            due_date=now + timedelta(days=1),
            inventory=inventory,
        )
        self.stdout.write("  • Сценарий кладовщика готов")

    def _seed_sales_flow(
        self,
        *,
        manager: User,
        picker: User,
        loader: User,
        warehouse: Warehouse,
        products: dict[str, Product],
    ) -> None:
        now = timezone.now()

        draft_order, _ = Order.objects.get_or_create(
            number="ORD-DM-MGR-01",
            defaults={
                "customer_name": "СТО АвтоТех-Сервис",
                "customer_phone": "+7 (903) 510-11-23",
                "customer_email": "sto.avtoteh@example.com",
                "source": "ONLINE",
                "status": OrderStatus.DRAFT,
                "created_by": manager,
            },
        )
        self._ensure_order_line(draft_order, products["DMO-SMALL-002"], Decimal("24.00"), Decimal("890.00"))
        self._ensure_order_line(draft_order, products["DMO-LARGE-001"], Decimal("2.00"), Decimal("6450.00"))

        active_order, _ = Order.objects.get_or_create(
            number="ORD-DM-MGR-02",
            defaults={
                "customer_name": "ООО ТрансЛайн",
                "customer_phone": "+7 (905) 700-88-44",
                "customer_email": "log@transline.example.com",
                "source": "MANUAL",
                "status": OrderStatus.DRAFT,
                "created_by": manager,
            },
        )
        self._ensure_order_line(active_order, products["DMO-SMALL-001"], Decimal("12.00"), Decimal("760.00"))
        self._ensure_order_line(active_order, products["DMO-LARGE-001"], Decimal("4.00"), Decimal("6200.00"))
        self._ensure_order_line(active_order, products["DMO-PALLET-001"], Decimal("1.00"), Decimal("235000.00"))

        if active_order.status == OrderStatus.DRAFT:
            ok, msg = OrderService.confirm_order(active_order)
            if not ok:
                raise CommandError("Не удалось подтвердить ORD-DM-MGR-02: " + "; ".join(msg))

        for line in active_order.lines.select_related("product").all():
            if line.qty_picked > 0:
                continue
            stock = suggest_stock_for_order_line(line)
            if not stock:
                continue
            target_qty = min(line.qty_ordered, Decimal("2.00"))
            reserve_stock_for_order_line(line, stock, target_qty)

        active_order.status = OrderStatus.IN_PICKING
        active_order.save(update_fields=["status"])

        for picking_task in active_order.picking_tasks.all():
            if picking_task.zone_type_code == "CELL":
                picking_task.assigned_to = picker
                picking_task.status = PickingTaskStatus.IN_PROGRESS
                picking_task.started_at = now - timedelta(hours=1, minutes=20)
                picking_task.save(update_fields=["assigned_to", "status", "started_at"])
            else:
                picking_task.assigned_to = loader
                picking_task.status = PickingTaskStatus.PENDING
                picking_task.started_at = None
                picking_task.save(update_fields=["assigned_to", "status", "started_at"])

        picked_order, _ = Order.objects.get_or_create(
            number="ORD-DM-MGR-03",
            defaults={
                "customer_name": "ИП Кузнецов Р.Н.",
                "customer_phone": "+7 (916) 412-09-57",
                "customer_email": "kuznetsov.rn@example.com",
                "source": "POS",
                "status": OrderStatus.DRAFT,
                "created_by": manager,
            },
        )
        self._ensure_order_line(picked_order, products["DMO-SMALL-002"], Decimal("10.00"), Decimal("850.00"))
        self._ensure_order_line(picked_order, products["DMO-LARGE-001"], Decimal("1.00"), Decimal("6300.00"))

        if picked_order.status == OrderStatus.DRAFT:
            ok, msg = OrderService.confirm_order(picked_order)
            if not ok:
                raise CommandError("Не удалось подтвердить ORD-DM-MGR-03: " + "; ".join(msg))

        for line in picked_order.lines.select_related("product").all():
            while line.qty_picked < line.qty_ordered:
                stock = suggest_stock_for_order_line(line)
                if not stock:
                    raise CommandError(f"Недостаточно стока для полного подбора {line.product.internal_sku}.")
                qty_left = line.qty_ordered - line.qty_picked
                qty_to_reserve = min(qty_left, stock.qty_available)
                if qty_to_reserve <= 0:
                    raise CommandError(f"Не удалось зарезервировать количество для {line.product.internal_sku}.")
                reserve_stock_for_order_line(line, stock, qty_to_reserve)
                line.refresh_from_db(fields=["qty_picked", "qty_ordered"])

        for picking_task in picked_order.picking_tasks.all():
            worker = picker if picking_task.zone_type_code == "CELL" else loader
            picking_task.assigned_to = worker
            picking_task.status = PickingTaskStatus.COMPLETED
            picking_task.started_at = now - timedelta(hours=3)
            picking_task.completed_at = now - timedelta(hours=2, minutes=15)
            picking_task.save(update_fields=["assigned_to", "status", "started_at", "completed_at"])

        picked_order.status = OrderStatus.PICKED
        picked_order.picked_by = picker
        picked_order.picked_at = now - timedelta(hours=2, minutes=15)
        picked_order.save(update_fields=["status", "picked_by", "picked_at"])

        shipping_task = (
            Task.objects.filter(order=picked_order, task_type=TaskType.SHIPPING)
            .order_by("-id")
            .first()
        )
        if shipping_task is None:
            shipping_task = TaskService.create_shipping_task(picked_order, manager)
        shipping_task.assigned_to = loader
        shipping_task.status = TaskStatus.IN_PROGRESS
        shipping_task.priority = TaskPriority.HIGH
        shipping_task.started_at = now - timedelta(minutes=35)
        shipping_task.due_date = now + timedelta(hours=2)
        shipping_task.save(
            update_fields=[
                "assigned_to",
                "status",
                "priority",
                "started_at",
                "due_date",
            ]
        )
        self.stdout.write("  • Сценарий заказов/подбора/отгрузки готов")
