from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management import BaseCommand
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import (
    Brand,
    Branch,
    Category,
    Product,
    ProductCrossReference,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
)
from inventory.models import Stock
from picking.models import Order, OrderLine, OrderStatus
from receiving.models import Receiving, ReceivingLine, ReceivingStatus


class Command(BaseCommand):
    help = "Заполняет БД данными для отчетов Dead Stock и Аналоги vs Оригиналы"

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Подготовка данных для отчетов..."))

        user, _ = User.objects.get_or_create(
            username="reports_demo",
            defaults={"role": Roles.ADMIN, "is_staff": True, "is_active": True},
        )
        user.set_password("demo123")
        user.save()

        branch, _ = Branch.objects.get_or_create(code="RPT", defaults={"name": "Филиал отчётов", "is_active": True})
        warehouse, _ = Warehouse.objects.get_or_create(
            branch=branch,
            code="RPT-WH",
            defaults={"name": "Склад отчётов", "is_active": True},
        )
        zone_type, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейки", "sort_order": 10})
        zone, _ = StorageZone.objects.get_or_create(warehouse=warehouse, code="RPT-CELL", defaults={"name": "Зона отчётов", "zone_type": zone_type})
        location, _ = StorageLocation.objects.get_or_create(zone=zone, code="RPT-A1", defaults={"name": "Ячейка RPT-A1"})

        brand, _ = Brand.objects.get_or_create(name="ReportBrand")
        category, _ = Category.objects.get_or_create(name="ReportCategory")

        original_1, _ = Product.objects.get_or_create(
            internal_sku="RPT-ORG-001",
            defaults={
                "name": "Оригинал масляного фильтра",
                "brand": brand,
                "category": category,
                "oem_number": "RPT-OEM-001",
                "packaging_type": Product.PackagingType.SMALL,
            },
        )
        analog_1, _ = Product.objects.get_or_create(
            internal_sku="RPT-ANL-001",
            defaults={
                "name": "Аналог масляного фильтра",
                "brand": brand,
                "category": category,
                "oem_number": "RPT-OEM-001A",
                "packaging_type": Product.PackagingType.SMALL,
            },
        )
        original_2, _ = Product.objects.get_or_create(
            internal_sku="RPT-ORG-002",
            defaults={
                "name": "Оригинал тормозных колодок",
                "brand": brand,
                "category": category,
                "oem_number": "RPT-OEM-002",
                "packaging_type": Product.PackagingType.SMALL,
            },
        )
        analog_2, _ = Product.objects.get_or_create(
            internal_sku="RPT-ANL-002",
            defaults={
                "name": "Аналог тормозных колодок",
                "brand": brand,
                "category": category,
                "oem_number": "RPT-OEM-002A",
                "packaging_type": Product.PackagingType.SMALL,
            },
        )
        dead_product, _ = Product.objects.get_or_create(
            internal_sku="RPT-DEAD-001",
            defaults={
                "name": "Товар без движения",
                "brand": brand,
                "category": category,
                "oem_number": "RPT-DEAD-OEM",
                "packaging_type": Product.PackagingType.SMALL,
            },
        )

        ProductCrossReference.objects.get_or_create(
            from_product=original_1,
            to_product=analog_1,
            relation_type=ProductCrossReference.RelationType.ANALOG,
            defaults={"note": "Для отчёта аналогов"},
        )
        ProductCrossReference.objects.get_or_create(
            from_product=original_2,
            to_product=analog_2,
            relation_type=ProductCrossReference.RelationType.ANALOG,
            defaults={"note": "Для отчёта аналогов"},
        )

        receiving_dead, _ = Receiving.objects.get_or_create(
            number="RPT-REC-DEAD-001",
            defaults={
                "supplier_name": "Demo Supplier",
                "status": ReceivingStatus.COMPLETED,
                "created_by": user,
                "completed_at": timezone.now() - timedelta(days=150),
            },
        )
        ReceivingLine.objects.get_or_create(
            receiving=receiving_dead,
            product=dead_product,
            defaults={"qty_expected": Decimal("60.00"), "qty_received": Decimal("60.00"), "storage_location": location},
        )
        stock_dead, _ = Stock.objects.get_or_create(
            product=dead_product,
            storage_location=location,
            batch_no="",
            defaults={"qty_available": Decimal("60.00"), "qty_reserved": Decimal("0.00")},
        )
        if stock_dead.qty_available < Decimal("60.00"):
            stock_dead.qty_available = Decimal("60.00")
            stock_dead.save(update_fields=["qty_available"])

        for idx, shipped_days_ago in enumerate([12, 9, 6, 3], start=1):
            order, _ = Order.objects.get_or_create(
                number=f"RPT-ORD-{idx:03d}",
                defaults={
                    "customer_name": f"Демо клиент {idx}",
                    "status": OrderStatus.SHIPPED,
                    "created_by": user,
                    "confirmed_at": timezone.now() - timedelta(days=shipped_days_ago + 1),
                    "picked_at": timezone.now() - timedelta(days=shipped_days_ago),
                    "shipped_at": timezone.now() - timedelta(days=shipped_days_ago),
                },
            )
            OrderLine.objects.get_or_create(
                order=order,
                product=original_1,
                defaults={"qty_ordered": Decimal("5.00"), "qty_picked": Decimal("5.00"), "price": Decimal("1800.00")},
            )
            OrderLine.objects.get_or_create(
                order=order,
                product=analog_1,
                defaults={"qty_ordered": Decimal("8.00"), "qty_picked": Decimal("8.00"), "price": Decimal("1200.00")},
            )
            OrderLine.objects.get_or_create(
                order=order,
                product=original_2,
                defaults={"qty_ordered": Decimal("3.00"), "qty_picked": Decimal("3.00"), "price": Decimal("3200.00")},
            )
            OrderLine.objects.get_or_create(
                order=order,
                product=analog_2,
                defaults={"qty_ordered": Decimal("6.00"), "qty_picked": Decimal("6.00"), "price": Decimal("2100.00")},
            )

        self.stdout.write(self.style.SUCCESS("Данные для отчетов созданы"))
        self.stdout.write(self.style.SUCCESS("Проверьте: /reports/dead-stock/ и /reports/analogs-vs-originals/"))
