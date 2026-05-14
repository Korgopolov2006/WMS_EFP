from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import (
    Branch,
    Brand,
    Category,
    Product,
    ProductCrossReference,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
    WarehouseAccess,
)
from inventory.models import Inventory, InventoryLine, InventoryStatus, MovementStatus, MovementType, Stock, StockMovement
from picking.models import (
    Order,
    OrderLine,
    OrderPriority,
    OrderStatus,
    PickingLine,
    PickingTask,
    PickingTaskStatus,
)
from receiving.models import Receiving, ReceivingLine, ReceivingStatus, Supplier
from reports.models import ABCXYZAnalysis, AnalogVsOriginalReport, DeadStockReport, DemandForecast, PickingError
from reports.services import generate_report_snapshots
from tasks.models import Task, TaskPriority, TaskStatus, TaskType


PREFIX = "RDEMO"


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные с реальными названиями автозапчастей для всех отчётов /reports/."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Подготовка демонстрационных данных для отчётов WMS..."))
        with transaction.atomic():
            self._clear_previous_demo()
            users = self._ensure_users()
            warehouse_data = self._ensure_warehouse(users)
            products = self._ensure_products()
            self._ensure_suppliers()
            self._ensure_stock_and_receivings(users, warehouse_data, products)
            orders = self._ensure_sales_orders(users, warehouse_data, products)
            picking_tasks = self._ensure_picking_tasks_and_errors(users, warehouse_data, products, orders)
            self._ensure_staff_activity(users, warehouse_data, orders, picking_tasks)
            summary = generate_report_snapshots(period_days=30, dead_stock_days=90, forecast_days=14, calculated_by=users["analyst"])

        self.stdout.write(self.style.SUCCESS("Демонстрационные данные для отчётов созданы."))
        self.stdout.write(
            "Сформировано: ABC-XYZ — {abc_xyz}; мёртвые остатки — {dead_stock}; "
            "аналоги — {analogs}; прогноз спроса — {demand_forecast}; "
            "ошибки подбора — {picking_errors}; сотрудники — {staff_efficiency}.".format(**summary)
        )
        self.stdout.write(self.style.SUCCESS("Проверьте раздел: http://127.0.0.1:8000/reports/"))

    def _clear_previous_demo(self) -> None:
        product_qs = Product.objects.filter(internal_sku__startswith=f"{PREFIX}-")
        order_qs = Order.objects.filter(number__startswith=f"{PREFIX}-ORD-")

        PickingError.objects.filter(order_line__order__in=order_qs).delete()
        PickingLine.objects.filter(task__order__in=order_qs).delete()
        PickingTask.objects.filter(order__in=order_qs).delete()
        Task.objects.filter(title__startswith=f"{PREFIX}:").delete()
        StockMovement.objects.filter(product__in=product_qs).delete()
        Order.objects.filter(number__startswith=f"{PREFIX}-ORD-").delete()
        Receiving.objects.filter(number__startswith=f"{PREFIX}-RCV-").delete()
        Inventory.objects.filter(number__startswith=f"{PREFIX}-INV-").delete()

        ABCXYZAnalysis.objects.filter(product__in=product_qs).delete()
        DeadStockReport.objects.filter(product__in=product_qs).delete()
        AnalogVsOriginalReport.objects.filter(
            original_product__in=product_qs,
        ).delete()
        AnalogVsOriginalReport.objects.filter(
            analog_product__in=product_qs,
        ).delete()
        DemandForecast.objects.filter(product__in=product_qs).delete()

        ProductCrossReference.objects.filter(from_product__in=product_qs).delete()
        ProductCrossReference.objects.filter(to_product__in=product_qs).delete()
        Stock.objects.filter(product__in=product_qs).delete()
        product_qs.delete()

    def _ensure_users(self) -> dict[str, User]:
        specs = {
            "admin": ("reports_admin", "Артём", "Коргополов", Roles.ADMIN, True),
            "storekeeper": ("kladovshchik_ivankov", "Николай", "Иванков", Roles.STOREKEEPER, False),
            "picker": ("sborshik_smirnov", "Павел", "Смирнов", Roles.SMALL_PARTS_PICKER, False),
            "loader": ("komplektovshik_orlov", "Дмитрий", "Орлов", Roles.LOADER, False),
            "manager": ("manager_kuznetsova", "Анна", "Кузнецова", Roles.SALES_MANAGER, False),
            "analyst": ("analyst_morozov", "Елена", "Морозова", Roles.ANALYST, True),
        }
        result: dict[str, User] = {}
        for key, (username, first_name, last_name, role, is_staff) in specs.items():
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@efp-parts.ru",
                    "role": role,
                    "is_staff": is_staff,
                    "is_active": True,
                },
            )
            user.first_name = first_name
            user.last_name = last_name
            user.email = f"{username}@efp-parts.ru"
            user.role = role
            user.is_staff = is_staff
            user.is_active = True
            if created or not user.has_usable_password():
                user.set_password("Demo12345!")
            user.save()
            result[key] = user
        return result

    def _ensure_warehouse(self, users: dict[str, User]) -> dict[str, object]:
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

        zone_specs = [
            ("CELL", "Ячейки", "Мелкие детали", 10, "A", ["A01-01-01", "A01-01-02", "A01-02-01", "A02-01-01"]),
            ("SHELF", "Стеллажи", "Среднегабаритные детали", 20, "B", ["B01-01-01", "B01-02-01", "B02-01-01"]),
            ("FLOOR", "Напольное хранение", "Крупные детали", 30, "C", ["C01-01-00", "C02-01-00"]),
        ]
        locations: dict[str, StorageLocation] = {}
        for code, name, description, sort_order, zone_code, location_codes in zone_specs:
            zone_type, _ = StorageZoneType.objects.get_or_create(
                code=code,
                defaults={"name": name, "description": description, "sort_order": sort_order},
            )
            zone, _ = StorageZone.objects.get_or_create(
                warehouse=warehouse,
                code=f"{PREFIX}-{zone_code}",
                defaults={"name": f"{name} {zone_code}", "zone_type": zone_type, "description": description},
            )
            for idx, location_code in enumerate(location_codes, start=1):
                location, _ = StorageLocation.objects.get_or_create(
                    zone=zone,
                    code=location_code,
                    defaults={
                        "name": f"Место {location_code}",
                        "aisle": location_code[:1],
                        "rack": str(idx),
                        "shelf": "1",
                        "level": "1",
                    },
                )
                locations[location_code] = location

        for user in users.values():
            user.branches.add(branch)
            WarehouseAccess.objects.update_or_create(
                user=user,
                warehouse=warehouse,
                defaults={"access_level": WarehouseAccess.AccessLevel.ADMIN if user.is_admin() else WarehouseAccess.AccessLevel.EDIT},
            )

        return {"branch": branch, "warehouse": warehouse, "locations": locations}

    def _ensure_suppliers(self) -> None:
        for code, name in [
            ("BOSCH", "Robert Bosch GmbH"),
            ("MANN", "MANN+HUMMEL"),
            ("TRW", "ZF Aftermarket / TRW"),
            ("BREMBO", "Brembo S.p.A."),
            ("NGK", "Niterra / NGK Spark Plug"),
            ("KYB", "KYB Europe"),
        ]:
            Supplier.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})

    def _ensure_products(self) -> dict[str, Product]:
        specs = [
            ("MANN-W71945", "MANN-FILTER W 719/45 Масляный фильтр", "MANN-FILTER", "Фильтры", "W71945", Product.PackagingType.SMALL, "A01-01-01", "980.00"),
            ("MANN-CUK2939", "MANN-FILTER CUK 2939 Фильтр салона", "MANN-FILTER", "Фильтры", "CUK2939", Product.PackagingType.SMALL, "A01-01-02", "1450.00"),
            ("BOSCH-0986494019", "Bosch 0 986 494 019 Колодки тормозные передние", "Bosch", "Тормозная система", "0986494019", Product.PackagingType.SMALL, "B01-01-01", "4200.00"),
            ("BREMBO-P85020", "Brembo P 85 020 Колодки тормозные передние", "Brembo", "Тормозная система", "P85020", Product.PackagingType.SMALL, "B01-01-01", "4600.00"),
            ("NGK-BKR6E11", "NGK BKR6E-11 Свеча зажигания", "NGK", "Электрика", "BKR6E11", Product.PackagingType.SMALL, "A01-02-01", "380.00"),
            ("DENSO-K20TT", "Denso K20TT Свеча зажигания", "Denso", "Электрика", "K20TT", Product.PackagingType.SMALL, "A01-02-01", "420.00"),
            ("SACHS-315087", "Sachs 315 087 Амортизатор подвески", "Sachs", "Подвеска", "315087", Product.PackagingType.LARGE, "C01-01-00", "7600.00"),
            ("KYB-339700", "KYB 339700 Амортизатор передний Excel-G", "KYB", "Подвеска", "339700", Product.PackagingType.LARGE, "C01-01-00", "7100.00"),
            ("SKF-VKBA3644", "SKF VKBA 3644 Комплект ступичного подшипника", "SKF", "Подшипники", "VKBA3644", Product.PackagingType.SMALL, "B01-02-01", "5400.00"),
            ("GATES-K015521XS", "Gates K015521XS Комплект ремня ГРМ", "Gates", "Ремни и ролики", "K015521XS", Product.PackagingType.SMALL, "B02-01-01", "6900.00"),
            ("VALEO-826317", "Valeo 826317 Комплект сцепления", "Valeo", "Сцепление", "826317", Product.PackagingType.LARGE, "C02-01-00", "14200.00"),
            ("MAHLE-OC467", "MAHLE OC 467 Масляный фильтр", "MAHLE", "Фильтры", "OC467", Product.PackagingType.SMALL, "A02-01-01", "820.00"),
            ("TOYOTA-90915YZZE1", "Toyota 90915-YZZE1 Масляный фильтр оригинальный", "Toyota", "Оригинальные запчасти", "90915YZZE1", Product.PackagingType.SMALL, "A02-01-01", "1650.00"),
            ("MANN-W683", "MANN-FILTER W 68/3 Масляный фильтр", "MANN-FILTER", "Фильтры", "W683", Product.PackagingType.SMALL, "A02-01-01", "780.00"),
            ("BMW-34116860017", "BMW 34 11 6 860 017 Колодки тормозные передние оригинальные", "BMW", "Оригинальные запчасти", "34116860017", Product.PackagingType.SMALL, "B01-02-01", "11800.00"),
            ("TRW-GDB1768", "TRW GDB1768 Колодки тормозные передние", "TRW", "Тормозная система", "GDB1768", Product.PackagingType.SMALL, "B01-02-01", "5200.00"),
            ("VAG-06A905115D", "Volkswagen 06A 905 115 D Катушка зажигания оригинальная", "Volkswagen", "Оригинальные запчасти", "06A905115D", Product.PackagingType.SMALL, "A01-02-01", "6200.00"),
            ("BOSCH-0221604115", "Bosch 0 221 604 115 Катушка зажигания", "Bosch", "Электрика", "0221604115", Product.PackagingType.SMALL, "A01-02-01", "3900.00"),
            ("FEBI-24360", "Febi Bilstein 24360 Опора двигателя", "Febi Bilstein", "Двигатель", "24360", Product.PackagingType.SMALL, "B02-01-01", "3100.00"),
            ("LEMFORDER-3475601", "Lemförder 34756 01 Наконечник рулевой тяги", "Lemförder", "Рулевое управление", "3475601", Product.PackagingType.SMALL, "B02-01-01", "2600.00"),
            ("PIERBURG-702551200", "Pierburg 7.02551.20.0 Клапан EGR", "Pierburg", "Двигатель", "702551200", Product.PackagingType.SMALL, "B02-01-01", "9800.00"),
            ("HELLA-8EL012428911", "Hella 8EL 012 428-911 Генератор", "Hella", "Электрика", "8EL012428911", Product.PackagingType.LARGE, "C02-01-00", "23600.00"),
        ]
        result: dict[str, Product] = {}
        for sku, name, brand_name, category_name, oem, packaging_type, location_code, price in specs:
            brand, _ = Brand.objects.get_or_create(name=brand_name)
            category, _ = Category.objects.get_or_create(name=category_name)
            product = Product.objects.create(
                internal_sku=f"{PREFIX}-{sku}",
                name=name,
                brand=brand,
                category=category,
                oem_number=oem,
                packaging_type=packaging_type,
                weight_kg=Decimal("0.250") if packaging_type == Product.PackagingType.SMALL else Decimal("4.500"),
            )
            product._demo_location_code = location_code
            product._demo_price = Decimal(price)
            result[sku] = product

        analog_pairs = [
            ("TOYOTA-90915YZZE1", "MANN-W683", "Аналог масляного фильтра Toyota"),
            ("BMW-34116860017", "TRW-GDB1768", "Аналог передних тормозных колодок BMW"),
            ("VAG-06A905115D", "BOSCH-0221604115", "Аналог катушки зажигания Volkswagen"),
            ("BOSCH-0986494019", "BREMBO-P85020", "Взаимозаменяемые тормозные колодки"),
        ]
        for original_sku, analog_sku, note in analog_pairs:
            ProductCrossReference.objects.get_or_create(
                from_product=result[original_sku],
                to_product=result[analog_sku],
                relation_type=ProductCrossReference.RelationType.ANALOG,
                defaults={"note": note},
            )
        return result

    def _ensure_stock_and_receivings(self, users, warehouse_data, products) -> None:
        now = timezone.now()
        warehouse = warehouse_data["warehouse"]
        locations = warehouse_data["locations"]
        receipt_specs = [
            ("Robert Bosch GmbH", ["BOSCH-0986494019", "BOSCH-0221604115"]),
            ("MANN+HUMMEL", ["MANN-W71945", "MANN-CUK2939", "MANN-W683"]),
            ("Brembo S.p.A.", ["BREMBO-P85020"]),
            ("ZF Aftermarket / TRW", ["TRW-GDB1768"]),
            ("Niterra / NGK Spark Plug", ["NGK-BKR6E11"]),
            ("Denso Europe", ["DENSO-K20TT"]),
            ("KYB Europe", ["KYB-339700"]),
            ("Sachs / ZF Aftermarket", ["SACHS-315087"]),
            ("SKF Group", ["SKF-VKBA3644"]),
            ("Gates Corporation", ["GATES-K015521XS"]),
            ("Valeo Service", ["VALEO-826317"]),
            ("MAHLE Aftermarket", ["MAHLE-OC467"]),
            ("Toyota Genuine Parts", ["TOYOTA-90915YZZE1"]),
            ("BMW Genuine Parts", ["BMW-34116860017"]),
            ("Volkswagen Genuine Parts", ["VAG-06A905115D"]),
            ("Ferdinand Bilstein", ["FEBI-24360"]),
            ("ZF Lemförder", ["LEMFORDER-3475601"]),
        ]
        for idx, (supplier, sku_list) in enumerate(receipt_specs, start=1):
            completed_at = now - timedelta(days=(idx % 18) + 8)
            receiving = Receiving.objects.create(
                number=f"{PREFIX}-RCV-{idx:03d}",
                supplier_name=supplier,
                supplier_doc_no=f"INV-{idx:04d}",
                warehouse=warehouse,
                status=ReceivingStatus.COMPLETED,
                expected_at=completed_at - timedelta(days=2),
                completed_at=completed_at,
                created_by=users["storekeeper"],
            )
            receiving.created_at = completed_at - timedelta(hours=5)
            receiving.save(update_fields=["created_at"])
            for sku in sku_list:
                product = products[sku]
                location = locations[product._demo_location_code]
                qty = Decimal("90.00") if product.packaging_type == Product.PackagingType.SMALL else Decimal("28.00")
                ReceivingLine.objects.create(
                    receiving=receiving,
                    product=product,
                    supplier_sku=product.oem_number,
                    qty_expected=qty,
                    qty_received=qty,
                    storage_location=location,
                )
                Stock.objects.create(
                    product=product,
                    storage_location=location,
                    qty_available=qty,
                    qty_reserved=Decimal("0.00"),
                    batch_no=f"{PREFIX}-{idx:03d}",
                )
                movement = StockMovement.objects.create(
                    movement_type=MovementType.RECEIPT,
                    status=MovementStatus.POSTED,
                    product=product,
                    quantity=qty,
                    to_location=location,
                    batch_no=f"{PREFIX}-{idx:03d}",
                    reason="Поступление от поставщика",
                    ref_type="Receiving",
                    ref_id=receiving.number,
                    user=users["storekeeper"],
                )
                movement.created_at = completed_at
                movement.save(update_fields=["created_at"])

        dead_specs = [
            ("Pierburg Service", "PIERBURG-702551200", Decimal("18.00"), 210),
            ("Hella Aftermarket", "HELLA-8EL012428911", Decimal("7.00"), 260),
        ]
        for idx, (supplier, sku, qty, days_ago) in enumerate(dead_specs, start=1):
            product = products[sku]
            location = locations[product._demo_location_code]
            completed_at = now - timedelta(days=days_ago)
            receiving = Receiving.objects.create(
                number=f"{PREFIX}-RCV-DEAD-{idx:03d}",
                supplier_name=supplier,
                supplier_doc_no=f"OLD-{idx:04d}",
                warehouse=warehouse,
                status=ReceivingStatus.COMPLETED,
                completed_at=completed_at,
                created_by=users["storekeeper"],
            )
            receiving.created_at = completed_at - timedelta(hours=4)
            receiving.save(update_fields=["created_at"])
            ReceivingLine.objects.create(
                receiving=receiving,
                product=product,
                supplier_sku=product.oem_number,
                qty_expected=qty,
                qty_received=qty,
                storage_location=location,
            )
            Stock.objects.create(
                product=product,
                storage_location=location,
                qty_available=qty,
                qty_reserved=Decimal("0.00"),
                batch_no=f"{PREFIX}-OLD-{idx:03d}",
            )

    def _ensure_sales_orders(self, users, warehouse_data, products) -> list[Order]:
        now = timezone.now()
        customers = [
            "Автоцентр Север",
            "СТО Профи",
            "Гараж-Моторс",
            "Автосервис Олимп",
            "МоторЛайн",
            "ТехЦентр Вираж",
            "Автопарк Логистик",
            "Экспресс-Сервис",
        ]
        sales_plan = [
            (2, [("BREMBO-P85020", 7), ("MANN-W71945", 12), ("NGK-BKR6E11", 18), ("TRW-GDB1768", 5)]),
            (4, [("BOSCH-0986494019", 5), ("MANN-CUK2939", 8), ("DENSO-K20TT", 12)]),
            (5, [("MANN-W683", 10), ("TOYOTA-90915YZZE1", 4), ("MAHLE-OC467", 14)]),
            (7, [("TRW-GDB1768", 9), ("BMW-34116860017", 3), ("SKF-VKBA3644", 4)]),
            (9, [("BOSCH-0221604115", 6), ("VAG-06A905115D", 2), ("NGK-BKR6E11", 16)]),
            (11, [("BREMBO-P85020", 6), ("MANN-W71945", 10), ("GATES-K015521XS", 3)]),
            (13, [("KYB-339700", 3), ("SACHS-315087", 2), ("LEMFORDER-3475601", 5)]),
            (15, [("BOSCH-0986494019", 4), ("MANN-CUK2939", 7), ("DENSO-K20TT", 10)]),
            (17, [("MANN-W683", 11), ("TOYOTA-90915YZZE1", 3), ("FEBI-24360", 4)]),
            (19, [("TRW-GDB1768", 8), ("BMW-34116860017", 2), ("SKF-VKBA3644", 3)]),
            (21, [("BOSCH-0221604115", 5), ("VAG-06A905115D", 2), ("VALEO-826317", 1)]),
            (23, [("BREMBO-P85020", 4), ("MANN-W71945", 9), ("NGK-BKR6E11", 12)]),
            (25, [("BOSCH-0986494019", 3), ("MANN-CUK2939", 5), ("GATES-K015521XS", 2)]),
            (27, [("KYB-339700", 2), ("SACHS-315087", 1), ("LEMFORDER-3475601", 4)]),
            (29, [("MAHLE-OC467", 8), ("DENSO-K20TT", 8), ("FEBI-24360", 3)]),
        ]

        orders: list[Order] = []
        for idx, (days_ago, lines) in enumerate(sales_plan, start=1):
            shipped_at = now - timedelta(days=days_ago, hours=idx % 5)
            order = Order.objects.create(
                number=f"{PREFIX}-ORD-{idx:03d}",
                customer_name=customers[idx % len(customers)],
                customer_phone=f"+7 495 10{idx:02d}-{idx:02d}-{idx:02d}",
                customer_email=f"client{idx}@example.ru",
                status=OrderStatus.SHIPPED,
                priority=OrderPriority.HIGH if idx % 4 == 0 else OrderPriority.NORMAL,
                shipping_due_at=shipped_at + timedelta(hours=3),
                source="MANUAL",
                confirmed_at=shipped_at - timedelta(hours=5),
                picked_at=shipped_at - timedelta(hours=2),
                shipped_at=shipped_at,
                created_by=users["manager"],
                picked_by=users["picker"] if idx % 2 else users["loader"],
            )
            order.created_at = shipped_at - timedelta(days=1)
            order.save(update_fields=["created_at"])
            for sku, qty_raw in lines:
                product = products[sku]
                OrderLine.objects.create(
                    order=order,
                    product=product,
                    qty_ordered=Decimal(str(qty_raw)),
                    qty_picked=Decimal(str(qty_raw)),
                    price=product._demo_price,
                )
            orders.append(order)
        return orders

    def _ensure_picking_tasks_and_errors(self, users, warehouse_data, products, orders) -> list[PickingTask]:
        now = timezone.now()
        all_stock = {stock.product_id: stock for stock in Stock.objects.filter(product__in=products.values()).select_related("product")}
        tasks: list[PickingTask] = []
        for idx, order in enumerate(orders[:10], start=1):
            completed_at = order.picked_at or now - timedelta(days=idx)
            task = PickingTask.objects.create(
                order=order,
                status=PickingTaskStatus.COMPLETED,
                priority=order.priority,
                zone_type_code="CELL" if idx % 2 else "SHELF",
                assigned_to=users["picker"] if idx % 2 else users["loader"],
                due_date=completed_at + timedelta(hours=1),
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            task.created_at = completed_at - timedelta(hours=2)
            task.save(update_fields=["created_at"])
            tasks.append(task)
            for line in order.lines.all()[:2]:
                stock = all_stock.get(line.product_id)
                if stock:
                    PickingLine.objects.create(
                        task=task,
                        order_line=line,
                        stock=stock,
                        qty_picked=line.qty_picked,
                        scanned_oem=line.product.oem_number,
                    )

        error_specs = [
            ("WRONG_PRODUCT", orders[0], "BOSCH-0986494019", "BREMBO-P85020", "Отсканирован аналог вместо ожидаемого товара", True, 3),
            ("WRONG_QTY", orders[1], "MANN-CUK2939", None, "Подобрано меньше требуемого количества", True, 5),
            ("WRONG_LOCATION", orders[2], "TOYOTA-90915YZZE1", "MANN-W683", "Товар взят из соседней ячейки", False, 7),
            ("DAMAGED", orders[3], "BMW-34116860017", None, "Повреждена упаковка при подборе", False, 9),
            ("MISSING", orders[4], "VAG-06A905115D", None, "Не найден товар на указанном месте хранения", True, 11),
            ("WRONG_PRODUCT", orders[5], "GATES-K015521XS", "SKF-VKBA3644", "Сборщик взял неверную позицию", False, 13),
            ("WRONG_QTY", orders[6], "KYB-339700", None, "Фактическое количество отличается от задания", True, 15),
        ]
        for idx, (error_type, order, expected_sku, actual_sku, note, resolved, days_ago) in enumerate(error_specs, start=1):
            expected_product = products[expected_sku]
            actual_product = products[actual_sku] if actual_sku else None
            order_line = order.lines.filter(product=expected_product).first()
            if order_line is None:
                order_line = OrderLine.objects.create(
                    order=order,
                    product=expected_product,
                    qty_ordered=Decimal("2.00"),
                    qty_picked=Decimal("0.00"),
                    price=expected_product._demo_price,
                )
            picking_line = None
            task = tasks[(idx - 1) % len(tasks)] if tasks else None
            if task and actual_product:
                stock = all_stock.get(actual_product.id)
                if stock:
                    picking_line, _ = PickingLine.objects.get_or_create(
                        task=task,
                        order_line=order_line,
                        stock=stock,
                        defaults={
                            "qty_picked": Decimal("1.00"),
                            "scanned_oem": actual_product.oem_number,
                        },
                    )
            detected_at = now - timedelta(days=days_ago, hours=idx)
            err = PickingError.objects.create(
                order_line=order_line,
                picking_line=picking_line,
                error_type=error_type,
                expected_product=expected_product,
                actual_product=actual_product,
                expected_qty=order_line.qty_ordered,
                actual_qty=Decimal("1.00") if error_type != "MISSING" else Decimal("0.00"),
                detected_by=users["storekeeper"],
                resolved=resolved,
                resolved_by=users["storekeeper"] if resolved else None,
                resolved_at=detected_at + timedelta(hours=2) if resolved else None,
                notes=note,
            )
            err.detected_at = detected_at
            err.save(update_fields=["detected_at"])
        return tasks

    def _ensure_staff_activity(self, users, warehouse_data, orders, picking_tasks) -> None:
        now = timezone.now()
        zone = next(iter(StorageZone.objects.filter(code=f"{PREFIX}-A")), None)
        location = next(iter(StorageLocation.objects.filter(zone=zone)), None)

        task_specs = [
            ("storekeeper", TaskType.RECEIVING, TaskStatus.COMPLETED, 1.8, "Проверить поставку MANN-FILTER"),
            ("storekeeper", TaskType.INVENTORY, TaskStatus.COMPLETED, 2.4, "Инвентаризация зоны A"),
            ("storekeeper", TaskType.STOCK_MOVEMENT, TaskStatus.COMPLETED, 1.2, "Переместить фильтры в ячейки A01"),
            ("picker", TaskType.PICKING, TaskStatus.COMPLETED, 1.1, "Подбор заказа Автоцентр Север"),
            ("picker", TaskType.PICKING, TaskStatus.COMPLETED, 1.3, "Подбор свечей и фильтров"),
            ("picker", TaskType.PICKING, TaskStatus.IN_PROGRESS, 0, "Подбор тормозных колодок"),
            ("loader", TaskType.SHIPPING, TaskStatus.COMPLETED, 1.5, "Отгрузка заказа СТО Профи"),
            ("loader", TaskType.SHIPPING, TaskStatus.COMPLETED, 1.7, "Передача заказа в зону выдачи"),
            ("loader", TaskType.PICKING, TaskStatus.PENDING, 0, "Подбор крупногабаритных деталей"),
            ("manager", TaskType.OTHER, TaskStatus.COMPLETED, 0.8, "Проверить состав заказа клиента"),
            ("manager", TaskType.OTHER, TaskStatus.COMPLETED, 1.0, "Согласовать замену оригинала аналогом"),
            ("analyst", TaskType.OTHER, TaskStatus.COMPLETED, 2.0, "Подготовить отчёт по мёртвым остаткам"),
            ("analyst", TaskType.OTHER, TaskStatus.IN_PROGRESS, 0, "Проверить прогноз спроса"),
        ]
        for idx, (user_key, task_type, status, duration_hours, title) in enumerate(task_specs, start=1):
            created_at = now - timedelta(days=(idx % 12) + 1, hours=idx)
            task = Task.objects.create(
                task_type=task_type,
                status=status,
                priority=TaskPriority.HIGH if idx % 4 == 0 else TaskPriority.NORMAL,
                title=f"{PREFIX}: {title}",
                description="Демонстрационная задача для отчёта эффективности сотрудников.",
                assigned_to=users[user_key],
                created_by=users["admin"],
                order=orders[idx % len(orders)] if task_type in [TaskType.SHIPPING, TaskType.OTHER] else None,
                picking_task=picking_tasks[idx % len(picking_tasks)] if task_type == TaskType.PICKING and picking_tasks else None,
                due_date=created_at + timedelta(days=1),
            )
            task.created_at = created_at
            if status in [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED]:
                task.started_at = created_at + timedelta(minutes=20)
            if status == TaskStatus.COMPLETED:
                task.completed_at = task.started_at + timedelta(hours=duration_hours)
            task.save(update_fields=["created_at", "started_at", "completed_at"])

        for idx, user_key in enumerate(["storekeeper", "storekeeper", "analyst"], start=1):
            completed_at = now - timedelta(days=idx + 3)
            inv = Inventory.objects.create(
                number=f"{PREFIX}-INV-{idx:03d}",
                zone=zone,
                status=InventoryStatus.COMPLETED,
                started_at=completed_at - timedelta(hours=3),
                completed_at=completed_at,
                created_by=users[user_key],
            )
            inv.created_at = completed_at - timedelta(hours=4)
            inv.save(update_fields=["created_at"])
            if location:
                stock = Stock.objects.filter(storage_location=location).select_related("product").first()
                if stock:
                    InventoryLine.objects.create(
                        inventory=inv,
                        product=stock.product,
                        storage_location=location,
                        qty_book=stock.qty_available,
                        qty_actual=stock.qty_available - Decimal("1.00"),
                    )
