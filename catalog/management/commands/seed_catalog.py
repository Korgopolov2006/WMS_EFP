from __future__ import annotations

from django.core.management import BaseCommand
from django.db import transaction

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


class Command(BaseCommand):
    help = "Первичное наполнение справочников каталога (типы зон, базовые категории)."

    @transaction.atomic
    def handle(self, *args, **options):
        zone_types = [
            ("CELL", "Ячеечный склад", "Мелкие позиции, хранение по адресам ячеек", 10),
            ("SHELF", "Полки", "Средние позиции, хранение на стеллажах/полках", 20),
            ("FLOOR", "Напольное хранение", "Крупные позиции, хранение на полу/в выделенной зоне", 30),
            ("HEAVY", "Зона тяжеловесов", "Тяжёлые/габаритные товары", 40),
        ]

        for code, name, description, sort_order in zone_types:
            StorageZoneType.objects.update_or_create(
                code=code,
                defaults={"name": name, "description": description, "sort_order": sort_order},
            )

        categories = [
            "Электроника",
            "Ходовая часть",
            "Тормозная система",
            "Двигатель",
            "Трансмиссия",
            "Фильтры и расходники",
            "Кузовные детали",
            "Химия и автоаксессуары",
        ]
        for name in categories:
            Category.objects.get_or_create(name=name)

        electronics, _ = Category.objects.get_or_create(name="Электроника")
        brakes, _ = Category.objects.get_or_create(name="Тормозная система")
        chassis, _ = Category.objects.get_or_create(name="Ходовая часть")

        brands = ["Bosch", "Sachs", "Lemforder", "NGK", "TRW"]
        brand_objs = {}
        for b in brands:
            brand_objs[b], _ = Brand.objects.get_or_create(name=b)

        demo_products = [
            ("BOSCH-ALT-001", "Генератор Bosch 120A", "0124325001", "", "Bosch", electronics, Product.PackagingType.LARGE),
            ("BOSCH-START-002", "Стартер Bosch 2.0kW", "0001107426", "", "Bosch", electronics, Product.PackagingType.LARGE),
            ("SACHS-CL-001", "Амортизатор Sachs передний", "314036", "", "Sachs", chassis, Product.PackagingType.LARGE),
            ("TRW-BRK-001", "Комплект тормозных колодок TRW", "GDB1330", "", "TRW", brakes, Product.PackagingType.SMALL),
            ("NGK-SP-001", "Свеча зажигания NGK", "BKR6E", "", "NGK", electronics, Product.PackagingType.SMALL),
        ]
        for sku, name, oem, analog, brand_name, cat, pack in demo_products:
            Product.objects.get_or_create(
                internal_sku=sku,
                defaults={
                    "name": name,
                    "oem_number": oem,
                    "analog_number": analog,
                    "brand": brand_objs[brand_name],
                    "category": cat,
                    "packaging_type": pack,
                },
            )

        branch_main, _ = Branch.objects.get_or_create(
            code="MAIN",
            defaults={"name": "Главный филиал", "address": "г. Москва, ул. Примерная, д. 1"},
        )

        warehouse_main, _ = Warehouse.objects.get_or_create(
            branch=branch_main,
            code="WH-01",
            defaults={"name": "Основной склад", "width_m": 30.0, "length_m": 40.0, "height_m": 8.0},
        )

        cell_zone, _ = StorageZone.objects.get_or_create(
            warehouse=warehouse_main,
            code="CELL-01",
            defaults={"name": "Ячеечная зона 1", "zone_type": StorageZoneType.objects.get(code="CELL")},
        )
        shelf_zone, _ = StorageZone.objects.get_or_create(
            warehouse=warehouse_main,
            code="SHELF-01",
            defaults={"name": "Зона полок 1", "zone_type": StorageZoneType.objects.get(code="SHELF")},
        )
        floor_zone, _ = StorageZone.objects.get_or_create(
            warehouse=warehouse_main,
            code="FLOOR-01",
            defaults={"name": "Напольная зона 1", "zone_type": StorageZoneType.objects.get(code="FLOOR")},
        )

        for i in range(1, 13):
            StorageLocation.objects.get_or_create(zone=cell_zone, code=f"A{i:02d}")
        for i in range(1, 7):
            StorageLocation.objects.get_or_create(zone=shelf_zone, code=f"S{i:02d}")
        StorageLocation.objects.get_or_create(zone=floor_zone, code="FLOOR-01")

        self.stdout.write(self.style.SUCCESS("Справочники и демо-данные заполнены (seed_catalog)."))

