"""
Команда для создания демонстрационных данных.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date, timedelta

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
    VehicleMake,
    VehicleModel,
    Warehouse,
)
from inventory.models import Stock
from picking.models import Order, OrderLine, OrderStatus
from receiving.models import Receiving, ReceivingLine, ReceivingStatus


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные для WMS"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Очистить существующие данные перед созданием",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write(self.style.WARNING("Очистка данных..."))
            # Очистка в правильном порядке (с учётом зависимостей)
            Stock.objects.all().delete()
            OrderLine.objects.all().delete()
            Order.objects.all().delete()
            ReceivingLine.objects.all().delete()
            Receiving.objects.all().delete()
            Product.objects.all().delete()
            StorageLocation.objects.all().delete()
            StorageZone.objects.all().delete()
            StorageZoneType.objects.all().delete()
            Warehouse.objects.all().delete()
            Branch.objects.all().delete()
            Brand.objects.all().delete()
            Category.objects.all().delete()
            VehicleModel.objects.all().delete()
            VehicleMake.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Создание демонстрационных данных..."))

        # 1. Филиалы и склады
        branch1, _ = Branch.objects.get_or_create(
            code="MSK",
            defaults={"name": "Москва", "address": "г. Москва, ул. Складская, 1", "is_active": True}
        )
        branch2, _ = Branch.objects.get_or_create(
            code="SPB",
            defaults={"name": "Санкт-Петербург", "address": "г. СПб, пр. Складской, 10", "is_active": True}
        )

        warehouse1, _ = Warehouse.objects.get_or_create(
            branch=branch1,
            code="WH1",
            defaults={
                "name": "Основной склад Москва",
                "width_m": 50.0,
                "length_m": 80.0,
                "height_m": 10.0,
                "is_active": True,
            }
        )

        # 2. Бренды
        brands = {}
        for brand_name in ["Bosch", "Mann", "Mahle", "Valeo", "Continental"]:
            brand, _ = Brand.objects.get_or_create(name=brand_name)
            brands[brand_name] = brand

        # 3. Категории
        categories = {}
        for cat_name in ["Фильтры", "Тормоза", "Подвеска", "Электрика", "Двигатель"]:
            cat, _ = Category.objects.get_or_create(name=cat_name)
            categories[cat_name] = cat

        # 4. Марки и модели ТС
        makes = {}
        for make_name in ["Toyota", "BMW", "Mercedes", "Audi", "Volkswagen"]:
            make, _ = VehicleMake.objects.get_or_create(name=make_name)
            makes[make_name] = make

        models_dict = {}
        for make_name, model_name in [
            ("Toyota", "Camry"),
            ("Toyota", "Corolla"),
            ("BMW", "3 Series"),
            ("BMW", "5 Series"),
            ("Mercedes", "C-Class"),
        ]:
            model, _ = VehicleModel.objects.get_or_create(
                make=makes[make_name], name=model_name
            )
            models_dict[f"{make_name} {model_name}"] = model

        # 5. Типы зон и зоны
        zone_types = {}
        for code, name in [("CELL", "Ячейки"), ("SHELF", "Полки"), ("FLOOR", "Напольное")]:
            zt, _ = StorageZoneType.objects.get_or_create(
                code=code, defaults={"name": name, "sort_order": 10 if code == "CELL" else 20 if code == "SHELF" else 30}
            )
            zone_types[code] = zt

        zones = {}
        for zone_code, zone_name, zone_type_code in [
            ("CELL-1", "Ячейки мелких деталей", "CELL"),
            ("SHELF-1", "Полки средних деталей", "SHELF"),
            ("FLOOR-1", "Напольное хранение", "FLOOR"),
        ]:
            zone, _ = StorageZone.objects.get_or_create(
                warehouse=warehouse1,
                code=zone_code,
                defaults={
                    "name": zone_name,
                    "zone_type": zone_types[zone_type_code],
                    "description": f"Зона {zone_name} на складе {warehouse1.code}",
                }
            )
            zones[zone_code] = zone

        # 6. Места хранения
        locations = {}
        for zone_code, loc_codes in [
            ("CELL-1", ["C-A1-01", "C-A1-02", "C-A1-03", "C-A2-01", "C-A2-02"]),
            ("SHELF-1", ["S-R1-S1", "S-R1-S2", "S-R2-S1", "S-R2-S2"]),
            ("FLOOR-1", ["F-Z1", "F-Z2", "F-Z3"]),
        ]:
            zone = zones[zone_code]
            for loc_code in loc_codes:
                loc, _ = StorageLocation.objects.get_or_create(
                    zone=zone,
                    code=loc_code,
                    defaults={
                        "name": f"Место {loc_code}",
                        "aisle": loc_code.split("-")[0] if "-" in loc_code else "",
                        "rack": loc_code.split("-")[1] if len(loc_code.split("-")) > 1 else "",
                        "shelf": loc_code.split("-")[2] if len(loc_code.split("-")) > 2 else "",
                        "max_weight_kg": 100.0 if zone_code == "CELL-1" else 500.0 if zone_code == "SHELF-1" else 2000.0,
                    }
                )
                locations[loc_code] = loc

        # 7. Товары
        products = {}
        demo_products = [
            ("FILT-001", "Фильтр масляный Bosch", "Bosch", "Фильтры", "SMALL", "0459144041", 0.5, 10, 10, 8),
            ("FILT-002", "Фильтр воздушный Mann", "Mann", "Фильтры", "SMALL", "HU718X", 0.3, 15, 15, 10),
            ("BRAKE-001", "Колодки тормозные передние", "Bosch", "Тормоза", "LARGE", "0986498151", 2.5, 20, 15, 12),
            ("BRAKE-002", "Диск тормозной", "Mann", "Тормоза", "LARGE", "MD123456", 8.0, 30, 30, 25),
            ("SUSP-001", "Амортизатор передний", "Valeo", "Подвеска", "LARGE", "VS12345", 5.0, 40, 35, 30),
            ("ELEC-001", "Генератор", "Valeo", "Электрика", "LARGE", "VG123456", 12.0, 25, 20, 15),
            ("ENG-001", "Ремень ГРМ", "Continental", "Двигатель", "SMALL", "CT1234", 0.8, 12, 10, 8),
            ("ENG-002", "Свечи зажигания", "Bosch", "Двигатель", "SMALL", "FR7DPP33", 0.1, 8, 8, 6),
        ]

        for sku, name, brand_name, cat_name, pack_type, oem, weight, length, width, height in demo_products:
            product, _ = Product.objects.get_or_create(
                internal_sku=sku,
                defaults={
                    "name": name,
                    "brand": brands[brand_name],
                    "category": categories[cat_name],
                    "packaging_type": pack_type,
                    "oem_number": oem,
                    "weight_kg": weight,
                    "length_cm": length,
                    "width_cm": width,
                    "height_cm": height,
                }
            )
            products[sku] = product

        # 8. Приёмки и остатки
        self.stdout.write("Создание приёмок и остатков...")

        # Создаём пользователя для приёмки
        user, _ = User.objects.get_or_create(
            username="demo_storekeeper",
            defaults={
                "role": Roles.STOREKEEPER,
                "is_staff": True,
                "is_active": True,
            }
        )
        user.set_password("demo123")
        user.save()

        receiving, _ = Receiving.objects.get_or_create(
            number="REC-001",
            defaults={
                "supplier_name": "ООО Поставщик автозапчастей",
                "supplier_doc_no": "INV-2024-001",
                "status": ReceivingStatus.COMPLETED,
                "created_by": user,
                "completed_at": timezone.now() - timedelta(days=5),
            }
        )

        # Создаём строки приёмки и остатки
        stock_data = [
            ("FILT-001", "C-A1-01", 50, None),
            ("FILT-002", "C-A1-02", 30, None),
            ("BRAKE-001", "S-R1-S1", 20, None),
            ("BRAKE-002", "S-R1-S2", 15, None),
            ("SUSP-001", "S-R2-S1", 10, None),
            ("ELEC-001", "S-R2-S2", 8, None),
            ("ENG-001", "C-A2-01", 40, None),
            ("ENG-002", "C-A2-02", 100, date.today() + timedelta(days=30)),  # Срок годности через месяц
        ]

        for sku, loc_code, qty, expiry in stock_data:
            product = products[sku]
            location = locations[loc_code]

            # Строка приёмки
            line, _ = ReceivingLine.objects.get_or_create(
                receiving=receiving,
                product=product,
                defaults={
                    "qty_expected": qty,
                    "qty_received": qty,
                    "storage_location": location,
                }
            )

            # Остаток
            stock, _ = Stock.objects.get_or_create(
                product=product,
                storage_location=location,
                batch_no="",
                defaults={
                    "qty_available": qty,
                    "qty_reserved": Decimal('0.00'),
                    "expiry_date": expiry,
                }
            )

        # 9. Заказы
        self.stdout.write("Создание заказов...")

        customer_user, _ = User.objects.get_or_create(
            username="demo_sales",
            defaults={
                "role": Roles.SALES_MANAGER,
                "is_staff": True,
                "is_active": True,
            }
        )
        customer_user.set_password("demo123")
        customer_user.save()

        order, _ = Order.objects.get_or_create(
            number="ORD-001",
            defaults={
                "customer_name": "Иванов Иван Иванович",
                "customer_phone": "+7 (999) 123-45-67",
                "customer_email": "ivanov@example.com",
                "status": OrderStatus.CONFIRMED,
                "created_by": customer_user,
                "confirmed_at": timezone.now() - timedelta(days=2),
            }
        )

        # Строки заказа
        order_lines_data = [
            ("FILT-001", 10, 10),
            ("BRAKE-001", 5, 5),
            ("ENG-001", 20, 20),
        ]

        for sku, qty_ordered, qty_picked in order_lines_data:
            OrderLine.objects.get_or_create(
                order=order,
                product=products[sku],
                defaults={
                    "qty_ordered": qty_ordered,
                    "qty_picked": qty_picked,
                    "price": Decimal('1500.00'),
                }
            )

        self.stdout.write(self.style.SUCCESS("✅ Демонстрационные данные созданы!"))
        self.stdout.write(f"   - Филиалов: {Branch.objects.count()}")
        self.stdout.write(f"   - Складов: {Warehouse.objects.count()}")
        self.stdout.write(f"   - Товаров: {Product.objects.count()}")
        self.stdout.write(f"   - Мест хранения: {StorageLocation.objects.count()}")
        self.stdout.write(f"   - Остатков: {Stock.objects.count()}")
        self.stdout.write(f"   - Приёмок: {Receiving.objects.count()}")
        self.stdout.write(f"   - Заказов: {Order.objects.count()}")
        self.stdout.write("\nТестовые пользователи:")
        self.stdout.write("   - demo_storekeeper / demo123 (Кладовщик)")
        self.stdout.write("   - demo_sales / demo123 (Менеджер по продажам)")
