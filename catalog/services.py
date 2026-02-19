"""
Сервисы для модуля catalog.
Backorder и другие бизнес-процессы.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from inventory.models import Stock
from picking.models import Order, OrderLine, OrderStatus
from .models import Backorder


class BackorderService:
    """Сервис для управления отложенными заказами (Backorder)."""

    @staticmethod
    @transaction.atomic
    def create_backorder_from_order(order: Order, order_line: OrderLine, user) -> Backorder:
        """
        Создаёт Backorder из строки заказа, если товара недостаточно на складе.
        
        Args:
            order: Заказ
            order_line: Строка заказа
            user: Пользователь, создающий backorder
            
        Returns:
            Backorder или None, если товара достаточно
        """
        product = order_line.product
        qty_needed = order_line.qty_ordered - order_line.qty_picked
        
        if qty_needed <= 0:
            return None
        
        # Проверяем доступное количество на всех складах
        total_available = Stock.objects.filter(
            product=product,
            qty_available__gt=0
        ).aggregate(total=models.Sum('qty_available'))['total'] or Decimal('0.00')
        
        if total_available >= qty_needed:
            # Товара достаточно, backorder не нужен
            return None
        
        # Создаём backorder
        backorder = Backorder.objects.create(
            order=order,
            product=product,
            qty_ordered=qty_needed,
            qty_fulfilled=Decimal('0.00'),
            status='PENDING',
            created_by=user,
        )
        
        return backorder

    @staticmethod
    @transaction.atomic
    def fulfill_backorder(backorder: Backorder, qty: Decimal, user) -> bool:
        """
        Выполняет часть или весь backorder при поступлении товара.
        
        Args:
            backorder: Отложенный заказ
            qty: Количество товара, которое поступило
            user: Пользователь, выполняющий backorder
            
        Returns:
            True, если backorder выполнен полностью или частично
        """
        if backorder.status == 'FULFILLED':
            return False
        
        remaining = backorder.qty_remaining
        if qty <= 0 or remaining <= 0:
            return False
        
        # Выполняем backorder
        qty_to_fulfill = min(qty, remaining)
        backorder.qty_fulfilled += qty_to_fulfill
        
        if backorder.qty_fulfilled >= backorder.qty_ordered:
            backorder.status = 'FULFILLED'
            backorder.fulfilled_at = timezone.now()
        elif backorder.qty_fulfilled > 0:
            backorder.status = 'PARTIAL'
        
        backorder.save()
        
        # Обновляем строку заказа
        order_line = backorder.order.lines.filter(product=backorder.product).first()
        if order_line:
            order_line.qty_picked += qty_to_fulfill
            order_line.save()
        
        return True

    @staticmethod
    def get_pending_backorders_for_product(product) -> list[Backorder]:
        """Возвращает список ожидающих backorder для товара."""
        return list(
            Backorder.objects.filter(
                product=product,
                status__in=['PENDING', 'PARTIAL']
            ).order_by('created_at')
        )

    @staticmethod
    @transaction.atomic
    def fulfill_backorder_for_product(product, qty: Decimal, user) -> list[Backorder]:
        """
        Выполняет backorder при поступлении товара.
        
        Args:
            product: Товар
            qty: Количество поступившего товара
            user: Пользователь
            
        Returns:
            Список выполненных backorder
        """
        fulfilled = []
        remaining_qty = qty
        
        # Получаем ожидающие backorder для товара
        pending_backorders = BackorderService.get_pending_backorders_for_product(product)
        
        for backorder in pending_backorders:
            if remaining_qty <= 0:
                break
            
            qty_needed = backorder.qty_remaining
            qty_to_fulfill = min(remaining_qty, qty_needed)
            
            if BackorderService.fulfill_backorder(backorder, qty_to_fulfill, user):
                fulfilled.append(backorder)
                remaining_qty -= qty_to_fulfill
        
        return fulfilled

    @staticmethod
    def get_backorders_by_arrival_date(start_date: date = None, end_date: date = None) -> list[Backorder]:
        """
        Возвращает backorder по ожидаемой дате поступления.
        
        Args:
            start_date: Начало периода (если None, то с сегодня)
            end_date: Конец периода (если None, то +30 дней)
        """
        if start_date is None:
            start_date = date.today()
        if end_date is None:
            end_date = start_date + timedelta(days=30)
        
        return list(
            Backorder.objects.filter(
                expected_arrival_date__gte=start_date,
                expected_arrival_date__lte=end_date,
                status__in=['PENDING', 'PARTIAL']
            ).order_by('expected_arrival_date')
        )


class ExpiryDateService:
    """Сервис для контроля сроков годности товаров."""

    @staticmethod
    def get_expired_stock(days_offset: int = 0) -> list[Stock]:
        """
        Возвращает список остатков с истёкшим сроком годности.
        
        Args:
            days_offset: Смещение в днях (0 = сегодня, -1 = вчера, 1 = завтра)
        """
        cutoff_date = date.today() + timedelta(days=days_offset)
        return list(
            Stock.objects.filter(
                expiry_date__isnull=False,
                expiry_date__lt=cutoff_date,
                qty_available__gt=0
            ).select_related('product', 'storage_location')
        )

    @staticmethod
    def get_expiring_soon_stock(days_ahead: int = 30) -> list[Stock]:
        """
        Возвращает список остатков, срок годности которых истечёт в ближайшие дни.
        
        Args:
            days_ahead: Количество дней вперёд для проверки
        """
        today = date.today()
        future_date = today + timedelta(days=days_ahead)
        
        return list(
            Stock.objects.filter(
                expiry_date__isnull=False,
                expiry_date__gte=today,
                expiry_date__lte=future_date,
                qty_available__gt=0
            ).select_related('product', 'storage_location')
            .order_by('expiry_date')
        )

    @staticmethod
    def get_expiry_summary() -> dict:
        """
        Возвращает сводку по срокам годности.
        
        Returns:
            dict с ключами: expired, expiring_soon_7, expiring_soon_30, total_value
        """
        expired = ExpiryDateService.get_expired_stock()
        expiring_7 = ExpiryDateService.get_expiring_soon_stock(days_ahead=7)
        expiring_30 = ExpiryDateService.get_expiring_soon_stock(days_ahead=30)
        
        # Подсчитываем общую стоимость (упрощённо, можно добавить поле price в Stock)
        total_expired_qty = sum(stock.qty_available for stock in expired)
        total_expiring_7_qty = sum(stock.qty_available for stock in expiring_7)
        total_expiring_30_qty = sum(stock.qty_available for stock in expiring_30)
        
        return {
            "expired": {
                "count": len(expired),
                "total_qty": total_expired_qty,
                "items": expired,
            },
            "expiring_soon_7": {
                "count": len(expiring_7),
                "total_qty": total_expiring_7_qty,
                "items": expiring_7,
            },
            "expiring_soon_30": {
                "count": len(expiring_30),
                "total_qty": total_expiring_30_qty,
                "items": expiring_30,
            },
        }
