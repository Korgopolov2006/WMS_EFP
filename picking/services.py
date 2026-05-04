"""
Сервисы для модуля picking.
Бизнес-логика комплектации и отгрузки.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from catalog.models import Product
from catalog.services import BackorderService
from inventory.models import Stock
from .models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus


PACKAGING_TO_ZONE = {
    Product.PackagingType.SMALL: "CELL",
    Product.PackagingType.LARGE: "SHELF",
    Product.PackagingType.PALLET: "FLOOR",
}

ZONE_TO_PACKAGING = {zone: packaging for packaging, zone in PACKAGING_TO_ZONE.items()}


def get_zone_code_for_product(product: Product) -> str | None:
    return PACKAGING_TO_ZONE.get(product.packaging_type)


def get_packaging_type_for_zone(zone_type_code: str) -> str | None:
    return ZONE_TO_PACKAGING.get(zone_type_code)


def get_task_order_lines(task: PickingTask):
    packaging_type = get_packaging_type_for_zone(task.zone_type_code)
    if not packaging_type:
        return task.order.lines.none()
    return task.order.lines.filter(product__packaging_type=packaging_type).select_related("product")


class OrderService:
    """Сервис для управления заказами."""

    @staticmethod
    @transaction.atomic
    def confirm_order(order: Order) -> tuple[bool, list[str]]:
        """
        Подтверждает заказ и создаёт задачи на подбор.
        
        Args:
            order: Заказ
            
        Returns:
            (success: bool, messages: list[str])
        """
        if order.status != OrderStatus.DRAFT:
            return False, ["Можно подтверждать только черновики"]

        if not order.lines.exists():
            return False, ["Нельзя подтвердить заказ без строк"]

        # Проверяем наличие товаров
        errors = []
        for line in order.lines.all():
            qty_needed = line.qty_ordered - line.qty_picked
            if qty_needed <= 0:
                continue

            # Ищем доступные остатки
            available_stock = Stock.objects.filter(
                product=line.product,
                qty_available__gt=0
            ).order_by('storage_location__code')

            total_available = sum(s.qty_available for s in available_stock)

            if total_available < qty_needed:
                # Недостаточно товара - создаём backorder
                backorder = BackorderService.create_backorder_from_order(
                    order, line, order.created_by
                )
                if backorder:
                    errors.append(
                        f"Товар {line.product.internal_sku}: недостаточно на складе. "
                        f"Создан backorder на {backorder.qty_ordered} шт."
                    )
                else:
                    errors.append(
                        f"Товар {line.product.internal_sku}: недостаточно на складе"
                    )

        if errors:
            return False, errors

        # Создаём задачи на подбор
        tasks = PickingService.create_picking_tasks_for_order(order)
        if not tasks:
            return False, ["Не удалось сформировать задачи подбора: проверьте типы упаковки товаров"]

        # Обновляем статус заказа
        order.status = OrderStatus.CONFIRMED
        order.confirmed_at = timezone.now()
        order.save(update_fields=["status", "confirmed_at"])

        # Создаём задачу на отгрузку
        from tasks.services import TaskService
        TaskService.create_shipping_task(order, order.created_by)

        return True, [f"Заказ подтверждён. Создано задач подбора: {len(tasks)}."]

    @staticmethod
    @transaction.atomic
    def ship_order(order: Order, user) -> tuple[bool, list[str]]:
        """
        Отгружает заказ (списывает остатки).
        
        Args:
            order: Заказ
            user: Пользователь
            
        Returns:
            (success: bool, messages: list[str])
        """
        if order.status not in [OrderStatus.CONFIRMED, OrderStatus.PICKED, OrderStatus.RESERVED]:
            return False, ["Можно отгружать только подтверждённые/подобранные заказы"]

        # Проверяем, что все строки подобраны
        for line in order.lines.all():
            if line.qty_picked < line.qty_ordered:
                return False, [
                    f"Строка {line.product.internal_sku}: "
                    f"подобрано {line.qty_picked} из {line.qty_ordered}"
                ]

        # Списываем зарезервированные остатки
        for line in order.lines.all():
            # Находим зарезервированные остатки для этого товара
            reserved_stocks = Stock.objects.filter(
                product=line.product,
                qty_reserved__gt=0
            ).order_by('id')

            remaining = line.qty_picked
            for stock in reserved_stocks:
                if remaining <= 0:
                    break

                qty_to_write_off = min(remaining, stock.qty_reserved)
                stock.qty_reserved -= qty_to_write_off
                stock.save(update_fields=["qty_reserved"])
                remaining -= qty_to_write_off

        # Обновляем статус заказа
        order.status = OrderStatus.SHIPPED
        order.shipped_at = timezone.now()
        if not order.picked_by:
            order.picked_by = user
        order.save(update_fields=["status", "shipped_at", "picked_by"])

        # Завершаем задачу на отгрузку, если есть
        from tasks.models import Task, TaskType, TaskStatus
        shipping_task = Task.objects.filter(
            order=order,
            task_type=TaskType.SHIPPING,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
        ).first()
        if shipping_task:
            shipping_task.status = TaskStatus.COMPLETED
            shipping_task.completed_at = timezone.now()
            shipping_task.save(update_fields=["status", "completed_at"])

        return True, ["Заказ отгружен. Остатки списаны."]


class PickingService:
    """Сервис для управления подбором."""

    @staticmethod
    @transaction.atomic
    def create_picking_tasks_for_order(order: Order) -> list[PickingTask]:
        """
        Создаёт задачи на подбор для заказа.
        
        Args:
            order: Заказ
            
        Returns:
            Список созданных задач
        """
        tasks = []
        zone_types = ["CELL", "SHELF", "FLOOR"]
        zone_types_with_items = set()

        for line in order.lines.select_related("product").all():
            if line.qty_ordered <= 0:
                continue
            zone_code = get_zone_code_for_product(line.product)
            if zone_code:
                zone_types_with_items.add(zone_code)

        for zone_type_code in zone_types:
            if zone_type_code not in zone_types_with_items:
                continue
            task = PickingTask.objects.create(
                order=order,
                zone_type_code=zone_type_code,
                status=PickingTaskStatus.PENDING,
                priority=order.priority,
                due_date=order.shipping_due_at,
            )
            tasks.append(task)

        return tasks

    @staticmethod
    @transaction.atomic
    def complete_picking_task(task: PickingTask, user) -> tuple[bool, list[str]]:
        """
        Завершает задачу подбора.
        
        Args:
            task: Задача подбора
            user: Пользователь
            
        Returns:
            (success: bool, messages: list[str])
        """
        if task.status == PickingTaskStatus.COMPLETED:
            return False, ["Задача уже завершена"]
        if task.status == PickingTaskStatus.PENDING:
            return False, ["Сначала возьмите задачу в работу"]

        # Проверяем, что все строки подобраны
        order_lines = get_task_order_lines(task)

        for line in order_lines:
            if line.qty_picked < line.qty_ordered:
                return False, [
                    f"Строка {line.product.internal_sku}: "
                    f"подобрано {line.qty_picked} из {line.qty_ordered}"
                ]

        # Обновляем статус задачи
        task.status = PickingTaskStatus.COMPLETED
        task.completed_at = timezone.now()
        if not task.assigned_to:
            task.assigned_to = user
        task.save(update_fields=["status", "completed_at", "assigned_to"])

        # Завершаем связанную универсальную задачу, если есть
        from tasks.models import Task as UniversalTask, TaskType, TaskStatus
        universal_task = UniversalTask.objects.filter(
            picking_task=task,
            task_type=TaskType.PICKING,
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
        ).first()
        if universal_task:
            universal_task.status = TaskStatus.COMPLETED
            universal_task.completed_at = timezone.now()
            universal_task.save(update_fields=["status", "completed_at"])

        # Проверяем, все ли задачи заказа завершены
        all_tasks_completed = not task.order.picking_tasks.filter(
            status__in=[PickingTaskStatus.PENDING, PickingTaskStatus.IN_PROGRESS]
        ).exists()

        if all_tasks_completed:
            task.order.status = OrderStatus.PICKED
            task.order.picked_at = timezone.now()
            task.order.picked_by = user
            task.order.save(update_fields=["status", "picked_at", "picked_by"])
        elif task.order.status == OrderStatus.CONFIRMED:
            task.order.status = OrderStatus.IN_PICKING
            task.order.save(update_fields=["status"])

        return True, ["Задача подбора завершена."]


# Функции для обратной совместимости
def create_picking_tasks_for_order(order: Order) -> list[PickingTask]:
    """Устаревшая функция. Использует PickingService."""
    return PickingService.create_picking_tasks_for_order(order)


def suggest_stock_for_order_line(order_line: OrderLine) -> Stock | None:
    """
    Предлагает остаток для строки заказа.
    """
    product = order_line.product
    qty_needed = order_line.qty_ordered - order_line.qty_picked

    if qty_needed <= 0:
        return None

    zone_type_code = get_zone_code_for_product(product)

    if not zone_type_code:
        return None

    stock = (
        Stock.objects.filter(
            product=product,
            storage_location__zone__zone_type__code=zone_type_code,
            qty_available__gt=0,
        )
        .select_related("storage_location", "storage_location__zone", "storage_location__zone__zone_type")
        .order_by("storage_location__code")
        .first()
    )

    return stock


def reserve_stock_for_order_line(order_line: OrderLine, stock: Stock, qty: Decimal) -> bool:
    """
    Резервирует остаток для строки заказа.
    """
    if qty <= 0:
        return False
    if stock.qty_available < qty:
        return False
    if order_line.qty_picked + qty > order_line.qty_ordered:
        return False

    stock.qty_available -= qty
    stock.qty_reserved += qty
    stock.save(update_fields=["qty_available", "qty_reserved"])

    order_line.qty_picked += qty
    order_line.save(update_fields=["qty_picked"])

    return True
