"""
Команда для создания демонстрационного workflow с полным циклом операций.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management import BaseCommand
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
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
from inventory.models import Inventory, InventoryStatus, Stock
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from receiving.models import Receiving, ReceivingLine, ReceivingStatus
from tasks.models import Task
from tasks.services import TaskService


class Command(BaseCommand):
    help = "Создаёт демонстрационный workflow: приёмка → хранение → подбор → отгрузка"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Очистить существующие данные перед созданием",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write(self.style.WARNING("Очистка данных..."))
            # Очистка в правильном порядке
            Task.objects.all().delete()
            PickingTask.objects.all().delete()
            OrderLine.objects.all().delete()
            Order.objects.all().delete()
            Stock.objects.all().delete()
            ReceivingLine.objects.all().delete()
            Receiving.objects.all().delete()
            Inventory.objects.all().delete()
            Product.objects.all().delete()
            StorageLocation.objects.all().delete()
            StorageZone.objects.all().delete()
            StorageZoneType.objects.all().delete()
            Warehouse.objects.all().delete()
            Branch.objects.all().delete()
            Brand.objects.all().delete()
            Category.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Создание демонстрационного workflow..."))

        # 1. Создаём пользователей с разными ролями
        self.stdout.write("Создание пользователей...")

        admin_user, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "role": Roles.ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            }
        )
        admin_user.set_password("admin123")
        admin_user.save()

        storekeeper, _ = User.objects.get_or_create(
            username="storekeeper",
            defaults={
                "role": Roles.STOREKEEPER,
                "is_staff": True,
                "is_active": True,
            }
        )
        storekeeper.set_password("storekeeper123")
        storekeeper.save()

        picker, _ = User.objects.get_or_create(
            username="picker",
            defaults={
                "role": Roles.SMALL_PARTS_PICKER,
                "is_staff": True,
                "is_active": True,
            }
        )
        picker.set_password("picker123")
        picker.save()

        loader, _ = User.objects.get_or_create(
            username="loader",
            defaults={
                "role": Roles.LOADER,
                "is_staff": True,
                "is_active": True,
            }
        )
        loader.set_password("loader123")
        loader.save()

        sales_manager, _ = User.objects.get_or_create(
            username="sales",
            defaults={
                "role": Roles.SALES_MANAGER,
                "is_staff": True,
                "is_active": True,
            }
        )
        sales_manager.set_password("sales123")
        sales_manager.save()

        analyst, _ = User.objects.get_or_create(
            username="analyst",
            defaults={
                "role": Roles.ANALYST,
                "is_staff": True,
                "is_active": True,
            }
        )
        analyst.set_password("analyst123")
        analyst.save()

        # 2. Создаём структуру склада
        self.stdout.write("Создание структуры склада...")

        branch, _ = Branch.objects.get_or_create(
            code="DEMO",
            defaults={"name": "Демо-филиал", "address": "г. Демо, ул. Складская, 1", "is_active": True}
        )

        warehouse, _ = Warehouse.objects.get_or_create(
            branch=branch,
            code="WH-DEMO",
            defaults={
                "name": "Демо-склад",
                "width_m": 50.0,
                "length_m": 80.0,
                "height_m": 10.0,
                "is_active": True,
            }
        )

        # Типы зон
        zone_types = {}
        for code, name in [("CELL", "Ячейки"), ("SHELF", "Полки"), ("FLOOR", "Напольное")]:
            zt, _ = StorageZoneType.objects.get_or_create(
                code=code, defaults={"name": name, "sort_order": 10 if code == "CELL" else 20 if code == "SHELF" else 30}
            )
            zone_types[code] = zt

        # Зоны
        zones = {}
        for zone_code, zone_name, zone_type_code in [
            ("CELL-1", "Ячейки мелких деталей", "CELL"),
            ("SHELF-1", "Полки средних деталей", "SHELF"),
            ("FLOOR-1", "Напольное хранение", "FLOOR"),
        ]:
            zone, _ = StorageZone.objects.get_or_create(
                warehouse=warehouse,
                code=zone_code,
                defaults={
                    "name": zone_name,
                    "zone_type": zone_types[zone_type_code],
                    "description": f"Зона {zone_name}",
                }
            )
            zones[zone_code] = zone

        # Места хранения
        locations = {}
        for zone_code, loc_codes in [
            ("CELL-1", ["C-A1-01", "C-A1-02", "C-A2-01"]),
            ("SHELF-1", ["S-R1-S1", "S-R2-S1"]),
            ("FLOOR-1", ["F-Z1", "F-Z2"]),
        ]:
            zone = zones[zone_code]
            for loc_code in loc_codes:
                loc, _ = StorageLocation.objects.get_or_create(
                    zone=zone,
                    code=loc_code,
                    defaults={
                        "name": f"Место {loc_code}",
                        "max_weight_kg": 100.0 if zone_code == "CELL-1" else 500.0 if zone_code == "SHELF-1" else 2000.0,
                    }
                )
                locations[loc_code] = loc

        # 3. Создаём товары
        self.stdout.write("Создание товаров...")

        brand, _ = Brand.objects.get_or_create(name="Demo Brand")
        category, _ = Category.objects.get_or_create(name="Демо-категория")

        products = {}
        demo_products = [
            ("FILT-001", "Фильтр масляный", "SMALL", "C-A1-01", 50),
            ("FILT-002", "Фильтр воздушный", "SMALL", "C-A1-02", 30),
            ("BRAKE-001", "Колодки тормозные", "LARGE", "S-R1-S1", 20),
            ("BRAKE-002", "Диск тормозной", "LARGE", "S-R2-S1", 15),
            ("ENG-001", "Ремень ГРМ", "SMALL", "C-A2-01", 40),
            ("SUSP-001", "Амортизатор", "LARGE", "F-Z1", 10),
        ]

        for sku, name, pack_type, loc_code, qty in demo_products:
            product, _ = Product.objects.get_or_create(
                internal_sku=sku,
                defaults={
                    "name": name,
                    "brand": brand,
                    "category": category,
                    "packaging_type": pack_type,
                    "oem_number": f"OEM-{sku}",
                    "weight_kg": 1.0,
                    "length_cm": 10,
                    "width_cm": 10,
                    "height_cm": 10,
                }
            )
            products[sku] = product

        # 4. Создаём приёмку (STOREKEEPER)
        self.stdout.write("Создание приёмки...")

        receiving, _ = Receiving.objects.get_or_create(
            number="REC-DEMO-001",
            defaults={
                "supplier_name": "ООО Поставщик",
                "supplier_doc_no": "INV-DEMO-001",
                "status": ReceivingStatus.DRAFT,
                "created_by": storekeeper,
            }
        )

        # Строки приёмки
        for sku, loc_code, qty in [
            ("FILT-001", "C-A1-01", 50),
            ("FILT-002", "C-A1-02", 30),
            ("BRAKE-001", "S-R1-S1", 20),
            ("BRAKE-002", "S-R2-S1", 15),
            ("ENG-001", "C-A2-01", 40),
            ("SUSP-001", "F-Z1", 10),
        ]:
            ReceivingLine.objects.get_or_create(
                receiving=receiving,
                product=products[sku],
                defaults={
                    "qty_expected": qty,
                    "qty_received": qty,
                    "storage_location": locations[loc_code],
                }
            )

        # Создаём задачу на приёмку
        receiving_task = TaskService.create_receiving_task(receiving, storekeeper)
        self.stdout.write(f"  ✓ Создана задача: {receiving_task.title}")

        # Завершаем приёмку (автоматически создаются остатки)
        from receiving.services import ReceivingService
        success, messages = ReceivingService.complete_receiving(receiving)
        if success:
            self.stdout.write(f"  ✓ Приёмка завершена: {messages[0]}")
            # Задача автоматически закрывается

        # 5. Создаём заказ (SALES_MANAGER)
        self.stdout.write("Создание заказа...")

        order, _ = Order.objects.get_or_create(
            number="ORD-DEMO-001",
            defaults={
                "customer_name": "Иванов Иван",
                "customer_phone": "+7 (999) 123-45-67",
                "status": OrderStatus.DRAFT,
                "created_by": sales_manager,
            }
        )

        # Строки заказа
        order_lines_data = [
            ("FILT-001", 10),
            ("BRAKE-001", 5),
            ("ENG-001", 20),
        ]

        for sku, qty in order_lines_data:
            OrderLine.objects.get_or_create(
                order=order,
                product=products[sku],
                defaults={
                    "qty_ordered": qty,
                    "qty_picked": 0,
                    "price": Decimal('1500.00'),
                }
            )

        # Подтверждаем заказ (автоматически создаются PickingTask и задача SHIPPING)
        from picking.services import OrderService
        success, messages = OrderService.confirm_order(order)
        if success:
            self.stdout.write(f"  ✓ Заказ подтверждён: {messages[0]}")
            # Автоматически созданы PickingTask и задача SHIPPING

        # 6. Выполняем подбор (SMALL_PARTS_PICKER)
        self.stdout.write("Выполнение подбора...")

        # Находим задачи подбора для мелких зон
        picking_tasks = PickingTask.objects.filter(
            order=order,
            zone_type_code__in=["CELL", "SHELF"],
            status=PickingTaskStatus.PENDING
        )

        for task in picking_tasks:
            # Назначаем задачу
            task.assigned_to = picker
            task.status = PickingTaskStatus.IN_PROGRESS
            task.started_at = timezone.now()
            task.save()

            # Резервируем товары (симуляция подбора)
            for line in order.lines.all():
                if line.qty_picked < line.qty_ordered:
                    from picking.services import suggest_stock_for_order_line, reserve_stock_for_order_line
                    stock = suggest_stock_for_order_line(line)
                    if stock:
                        qty_needed = line.qty_ordered - line.qty_picked
                        qty_to_reserve = min(qty_needed, stock.qty_available)
                        reserve_stock_for_order_line(line, stock, qty_to_reserve)

            # Завершаем задачу
            from picking.services import PickingService
            success, messages = PickingService.complete_picking_task(task, picker)
            if success:
                self.stdout.write(f"  ✓ Задача подбора завершена: {task.zone_type_code}")

        # 7. Выполняем отгрузку (LOADER)
        self.stdout.write("Выполнение отгрузки...")

        # Проверяем, что заказ подобран
        if order.status == OrderStatus.PICKED:
            success, messages = OrderService.ship_order(order, loader)
            if success:
                self.stdout.write(f"  ✓ Заказ отгружен: {messages[0]}")
                # Задача SHIPPING автоматически закрывается

        # 8. Создаём инвентаризацию (STOREKEEPER)
        self.stdout.write("Создание инвентаризации...")

        inventory, _ = Inventory.objects.get_or_create(
            number="INV-DEMO-001",
            defaults={
                "zone": zones["CELL-1"],
                "status": InventoryStatus.DRAFT,
                "created_by": storekeeper,
            }
        )

        # Создаём задачу на инвентаризацию
        inventory_task = TaskService.create_inventory_task(inventory, storekeeper)
        self.stdout.write(f"  ✓ Создана задача: {inventory_task.title}")

        # Начинаем инвентаризацию
        from inventory.services import InventoryService
        success, messages = InventoryService.start_inventory(inventory, storekeeper)
        if success:
            self.stdout.write(f"  ✓ Инвентаризация начата: {messages[0]}")

        # Завершаем инвентаризацию (симуляция - оставляем фактические = учётным)
        for line in inventory.lines.all():
            line.qty_actual = line.qty_book
            line.save()

        success, messages = InventoryService.complete_inventory(inventory, storekeeper)
        if success:
            self.stdout.write(f"  ✓ Инвентаризация завершена: {messages[0]}")
            # Задача автоматически закрывается

        self.stdout.write(self.style.SUCCESS("\n✅ Демонстрационный workflow создан!"))
        self.stdout.write("\nПользователи для демонстрации:")
        self.stdout.write("  - admin / admin123 (Администратор)")
        self.stdout.write("  - storekeeper / storekeeper123 (Кладовщик)")
        self.stdout.write("  - picker / picker123 (Сборщик мелких деталей)")
        self.stdout.write("  - loader / loader123 (Грузчик)")
        self.stdout.write("  - sales / sales123 (Менеджер по продажам)")
        self.stdout.write("  - analyst / analyst123 (Аналитик)")
        self.stdout.write("\nСозданные данные:")
        self.stdout.write(f"  - Приёмка: {receiving.number} (завершена)")
        self.stdout.write(f"  - Заказ: {order.number} (отгружен)")
        self.stdout.write(f"  - Инвентаризация: {inventory.number} (завершена)")
        self.stdout.write(f"  - Задач создано: {Task.objects.count()}")
        self.stdout.write(f"  - Остатков: {Stock.objects.count()}")
