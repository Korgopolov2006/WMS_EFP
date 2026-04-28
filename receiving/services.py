"""
Сервисы для модуля receiving.
Бизнес-логика приёмки товаров.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from catalog.models import Product, StorageLocation, Warehouse
from catalog.services import BackorderService
from inventory.models import Stock
from .models import Receiving, ReceivingLine, ReceivingStatus


def get_user_warehouses(user) -> QuerySet[Warehouse]:
    """
    Возвращает склады, в которых пользователь может выполнять операции.

    Приоритет:
    1) Явные доступы через get_accessible_warehouses();
    2) fallback по филиалам пользователя (если доступы не заведены);
    3) для админа - все активные склады.
    """
    if getattr(user, "is_superuser", False) or getattr(user, "is_admin", lambda: False)():
        return Warehouse.objects.filter(is_active=True)

    explicit = user.get_accessible_warehouses()
    if explicit.exists():
        return explicit

    return Warehouse.objects.filter(
        branch__in=user.branches.filter(is_active=True),
        is_active=True,
    ).distinct()


def suggest_storage_location(product: Product, user=None, warehouse: Warehouse | None = None) -> StorageLocation | None:
    """
    Предлагает место хранения для товара на основе его типа упаковки.
    
    Args:
        product: Товар
        user: Пользователь (для ограничения по доступным складам)
        warehouse: Склад документа приёмки
        
    Returns:
        StorageLocation или None
    """
    mapping = {
        Product.PackagingType.SMALL: "CELL",
        Product.PackagingType.LARGE: "SHELF",
        Product.PackagingType.PALLET: "FLOOR",
    }
    preferred_zone_type_code = mapping.get(product.packaging_type)

    base_locations = StorageLocation.objects.select_related("zone", "zone__warehouse", "zone__warehouse__branch").filter(
        zone__warehouse__isnull=False,
        zone__warehouse__is_active=True,
    )
    if user is not None:
        user_warehouses = get_user_warehouses(user)
        base_locations = base_locations.filter(zone__warehouse__in=user_warehouses)
    if warehouse is not None:
        base_locations = base_locations.filter(zone__warehouse=warehouse)

    if preferred_zone_type_code:
        preferred = base_locations.filter(zone__zone_type__code=preferred_zone_type_code).order_by(
            "zone__warehouse__branch__code",
            "zone__warehouse__code",
            "zone__code",
            "code",
            "id",
        ).first()
        if preferred:
            return preferred

    return base_locations.order_by(
        "zone__warehouse__branch__code",
        "zone__warehouse__code",
        "zone__code",
        "code",
        "id",
    ).first()


class ReceivingService:
    """Сервис для управления приёмкой товаров."""

    @staticmethod
    @transaction.atomic
    def complete_receiving(receiving: Receiving) -> tuple[bool, list[str]]:
        """
        Завершает приёмку и создаёт остатки (Stock).
        
        Args:
            receiving: Документ приёмки
            
        Returns:
            (success: bool, messages: list[str])
        """
        errors = []

        if not receiving.warehouse:
            errors.append("Для приёмки не указан склад.")
            return False, errors

        # Валидация: нельзя завершить без строк
        if not receiving.lines.exists():
            errors.append("Нельзя завершить приёмку без строк")
            return False, errors

        # Валидация: проверка количества
        for line in receiving.lines.all():
            if line.qty_received <= 0:
                errors.append(f"Строка {line.product.internal_sku}: количество должно быть больше нуля")
            if line.qty_received > line.qty_expected * Decimal('1.1'):  # Допускаем 10% перебор
                errors.append(f"Строка {line.product.internal_sku}: принято значительно больше ожидаемого")
            if not line.storage_location:
                errors.append(f"Строка {line.product.internal_sku}: не указано место хранения")
            elif line.storage_location.zone.warehouse_id != receiving.warehouse_id:
                errors.append(
                    f"Строка {line.product.internal_sku}: место {line.storage_location} "
                    f"не относится к складу документа ({receiving.warehouse.code})"
                )

        if errors:
            return False, errors

        # Создаём остатки для каждой строки
        created_stocks = []
        for line in receiving.lines.all():
            if line.qty_received > 0:
                stock = ReceivingService._create_stock_from_line(line)
                if stock:
                    created_stocks.append(stock)

                    # Проверяем и выполняем backorder
                    BackorderService.fulfill_backorder_for_product(
                        line.product,
                        line.qty_received,
                        receiving.created_by
                    )

        # Обновляем статус приёмки
        receiving.status = ReceivingStatus.COMPLETED
        receiving.completed_at = timezone.now()
        receiving.save(update_fields=["status", "completed_at"])

        # Завершаем задачу на приёмку, если есть
        from tasks.models import Task, TaskType, TaskStatus
        receiving_task = Task.objects.filter(
            receiving=receiving,
            task_type=TaskType.RECEIVING,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
        ).first()
        if receiving_task:
            receiving_task.status = TaskStatus.COMPLETED
            receiving_task.completed_at = timezone.now()
            receiving_task.save(update_fields=["status", "completed_at"])

        messages = [f"Приёмка завершена. Создано остатков: {len(created_stocks)}"]
        return True, messages

    @staticmethod
    @transaction.atomic
    def _create_stock_from_line(line: ReceivingLine) -> Stock | None:
        """
        Создаёт или обновляет остаток из строки приёмки.
        
        Args:
            line: Строка приёмки
            
        Returns:
            Stock объект
        """
        if line.qty_received <= 0:
            return None

        if not line.storage_location:
            return None

        # Ищем существующий остаток с таким же batch_no (если указан)
        batch_no = line.supplier_sku or ""
        stock, created = Stock.objects.get_or_create(
            product=line.product,
            storage_location=line.storage_location,
            batch_no=batch_no,
            defaults={
                "qty_available": line.qty_received,
                "qty_reserved": Decimal('0.00'),
            }
        )

        if not created:
            # Обновляем существующий остаток
            stock.qty_available += line.qty_received
            stock.save(update_fields=["qty_available"])

        return stock

    @staticmethod
    def validate_receiving_line(line: ReceivingLine) -> list[str]:
        """
        Валидирует строку приёмки.
        
        Returns:
            Список ошибок (пустой, если всё ОК)
        """
        errors = []

        if line.qty_expected <= 0:
            errors.append("Ожидаемое количество должно быть больше нуля")

        if line.qty_expected != line.qty_expected.to_integral_value():
            errors.append("Ожидаемое количество должно быть целым числом (шт)")

        if line.qty_received < 0:
            errors.append("Принятое количество не может быть отрицательным")

        if line.qty_received != line.qty_received.to_integral_value():
            errors.append("Принятое количество должно быть целым числом (шт)")

        if line.qty_received > line.qty_expected * Decimal('1.2'):  # Допускаем 20% перебор
            errors.append("Принятое количество значительно превышает ожидаемое")

        if line.storage_location:
            # Проверяем максимальный вес места хранения
            if line.product.weight_kg and line.storage_location.max_weight_kg:
                total_weight = line.product.weight_kg * line.qty_received
                if total_weight > line.storage_location.max_weight_kg:
                    errors.append(
                        f"Превышен максимальный вес места хранения "
                        f"({total_weight} кг > {line.storage_location.max_weight_kg} кг)"
                    )

        return errors

    @staticmethod
    def can_complete_receiving(receiving: Receiving) -> tuple[bool, list[str]]:
        """
        Проверяет, можно ли завершить приёмку.
        
        Returns:
            (can_complete: bool, reasons: list[str])
        """
        if receiving.status == ReceivingStatus.COMPLETED:
            return False, ["Приёмка уже завершена"]

        if receiving.status == ReceivingStatus.CANCELLED:
            return False, ["Нельзя завершить отменённую приёмку"]

        if not receiving.warehouse:
            return False, ["Для документа не указан склад"]

        if not receiving.lines.exists():
            return False, ["Нет строк приёмки"]

        errors = []
        for line in receiving.lines.all():
            if line.storage_location and line.storage_location.zone.warehouse_id != receiving.warehouse_id:
                errors.append(
                    f"{line.product.internal_sku}: место хранения не относится к складу документа ({receiving.warehouse.code})"
                )
            line_errors = ReceivingService.validate_receiving_line(line)
            errors.extend([f"{line.product.internal_sku}: {e}" for e in line_errors])

        if errors:
            return False, errors

        return True, []


def update_stock_from_receiving_line(line: ReceivingLine) -> Stock | None:
    """
    Устаревшая функция для обратной совместимости.
    Использует ReceivingService.
    """
    return ReceivingService._create_stock_from_line(line)
