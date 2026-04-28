"""
Сервисы для модуля inventory.
Бизнес-логика инвентаризации.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    Inventory,
    InventoryLine,
    InventoryStatus,
    MovementStatus,
    MovementType,
    Stock,
    StockMovement,
)


def record_movement(
    *,
    movement_type: str,
    product,
    quantity,
    from_location=None,
    to_location=None,
    user=None,
    batch_no: str = "",
    reason: str = "",
    comment: str = "",
    ref_type: str = "",
    ref_id: str = "",
    status: str = MovementStatus.POSTED,
) -> StockMovement:
    """
    Создаёт запись в журнале движений товара.
    Не меняет Stock — только аудит-след.
    Вызывается из сервисов receiving / picking / inventory или вручную.
    """
    qty = Decimal(str(quantity))
    if qty == 0:
        raise ValueError("Количество движения не может быть нулевым.")

    if movement_type not in MovementType.values:
        raise ValueError(f"Неизвестный тип движения: {movement_type}")

    return StockMovement.objects.create(
        movement_type=movement_type,
        status=status,
        product=product,
        quantity=qty,
        from_location=from_location,
        to_location=to_location,
        batch_no=batch_no or "",
        reason=reason or "",
        comment=comment or "",
        ref_type=ref_type or "",
        ref_id=str(ref_id) if ref_id else "",
        user=user,
    )


class InventoryService:
    """Сервис для управления инвентаризацией."""

    @staticmethod
    @transaction.atomic
    def start_inventory(inventory: Inventory, user) -> tuple[bool, list[str]]:
        """
        Начинает инвентаризацию (создаёт строки по остаткам).
        
        Args:
            inventory: Документ инвентаризации
            user: Пользователь
            
        Returns:
            (success: bool, messages: list[str])
        """
        if inventory.status != InventoryStatus.DRAFT:
            return False, ["Можно начинать только черновики"]

        if inventory.lines.exists():
            return False, ["Строки уже созданы"]

        # Создаём строки по остаткам
        if inventory.zone:
            stocks = Stock.objects.filter(
                storage_location__zone=inventory.zone,
                qty_available__gt=0
            ).select_related("product", "storage_location")
        else:
            stocks = Stock.objects.filter(
                qty_available__gt=0
            ).select_related("product", "storage_location")

        created_count = 0
        for stock in stocks:
            InventoryLine.objects.create(
                inventory=inventory,
                product=stock.product,
                storage_location=stock.storage_location,
                qty_book=stock.qty_available,
                qty_actual=None,
            )
            created_count += 1

        inventory.status = InventoryStatus.IN_PROGRESS
        inventory.started_at = timezone.now()
        inventory.save(update_fields=["status", "started_at"])

        return True, [f"Инвентаризация начата. Создано строк: {created_count}."]

    @staticmethod
    @transaction.atomic
    def complete_inventory(inventory: Inventory, user) -> tuple[bool, list[str]]:
        """
        Завершает инвентаризацию (обновляет остатки по фактическим данным).
        
        Args:
            inventory: Документ инвентаризации
            user: Пользователь
            
        Returns:
            (success: bool, messages: list[str])
        """
        if inventory.status != InventoryStatus.IN_PROGRESS:
            return False, ["Можно завершать только инвентаризации в процессе"]

        # Проверяем, что все строки заполнены
        incomplete_lines = inventory.lines.filter(qty_actual__isnull=True)
        if incomplete_lines.exists():
            return False, [
                f"Не заполнены фактические количества для {incomplete_lines.count()} строк"
            ]

        non_integer_lines = [
            line for line in inventory.lines.all()
            if line.qty_actual is not None and line.qty_actual != line.qty_actual.to_integral_value()
        ]
        if non_integer_lines:
            return False, ["Фактические количества должны быть целыми числами (шт)"]

        # Обновляем остатки
        updated_count = 0
        for line in inventory.lines.all():
            stock = Stock.objects.filter(
                product=line.product,
                storage_location=line.storage_location
            ).first()

            if stock:
                # Обновляем остаток
                stock.qty_available = line.qty_actual
                stock.save(update_fields=["qty_available"])
                updated_count += 1

        inventory.status = InventoryStatus.COMPLETED
        inventory.completed_at = timezone.now()
        inventory.save(update_fields=["status", "completed_at"])

        # Завершаем задачу на инвентаризацию, если есть
        from tasks.models import Task, TaskType, TaskStatus
        inventory_task = Task.objects.filter(
            inventory=inventory,
            task_type=TaskType.INVENTORY,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
        ).first()
        if inventory_task:
            inventory_task.status = TaskStatus.COMPLETED
            inventory_task.completed_at = timezone.now()
            inventory_task.save(update_fields=["status", "completed_at"])

        return True, [f"Инвентаризация завершена. Обновлено остатков: {updated_count}."]


def find_analog_on_stock(product, qty_needed):
    """
    Ищет аналоги товара на складе, если оригинала недостаточно.
    
    Args:
        product: Оригинальный товар
        qty_needed: Необходимое количество
        
    Returns:
        Список словарей с информацией об аналогах на складе
    """
    from catalog.models import ProductCrossReference
    from django.db.models import Sum

    # Ищем аналоги через перекрёстные ссылки
    analogs = ProductCrossReference.objects.filter(
        from_product=product,
        relation_type='ANALOG'
    ).select_related('to_product')

    result = []
    for xref in analogs:
        analog_product = xref.to_product
        total_available = Stock.objects.filter(
            product=analog_product,
            qty_available__gt=0
        ).aggregate(total=Sum('qty_available'))['total'] or 0

        if total_available >= qty_needed:
            result.append({
                'product': analog_product,
                'qty_available': total_available,
                'sufficient': True,
            })
        elif total_available > 0:
            result.append({
                'product': analog_product,
                'qty_available': total_available,
                'sufficient': False,
            })

    return result


# Устаревшая функция для обратной совместимости
def update_stock_from_receiving_line(line):
    """
    Устаревшая функция. Использует ReceivingService.
    """
    from receiving.services import ReceivingService
    return ReceivingService._create_stock_from_line(line)
