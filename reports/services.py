from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum, Count, Avg, Max, F, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.constants import Roles
from accounts.models import User
from catalog.models import Product, ProductCrossReference
from inventory.models import InventoryLine, Stock
from picking.models import OrderLine, OrderStatus
from picking.models import Order, PickingTask, PickingTaskStatus
from receiving.models import Receiving, ReceivingStatus
from inventory.models import Inventory, InventoryStatus
from reports.models import PickingError
from tasks.models import Task, TaskStatus


def calculate_abc_class(products_data: list[dict], threshold_a: float = 0.8, threshold_b: float = 0.95) -> dict:
    total_amount = sum(item["amount"] for item in products_data)
    if total_amount == 0:
        return {}

    sorted_data = sorted(products_data, key=lambda x: x["amount"], reverse=True)
    cumulative = Decimal("0.00")
    result = {}

    for item in sorted_data:
        cumulative += item["amount"]
        percentage = float(cumulative / total_amount)

        if percentage <= threshold_a:
            result[item["product_id"]] = "A"
        elif percentage <= threshold_b:
            result[item["product_id"]] = "B"
        else:
            result[item["product_id"]] = "C"

    return result


def calculate_xyz_class(products_data: list[dict], threshold_x: float = 0.2, threshold_y: float = 0.5) -> dict:
    result = {}

    for item in products_data:
        cv = item.get("coefficient_variation", 1.0)

        if cv <= threshold_x:
            result[item["product_id"]] = "X"
        elif cv <= threshold_y:
            result[item["product_id"]] = "Y"
        else:
            result[item["product_id"]] = "Z"

    return result


def find_dead_stock(days_threshold: int = 90) -> list[dict]:
    threshold_date = timezone.localdate() - timedelta(days=days_threshold)
    stocks = Stock.objects.filter(qty_available__gt=0).select_related("product", "storage_location")
    result = []
    for stock in stocks:
        last_receiving = (
            stock.product.receiving_lines.filter(storage_location=stock.storage_location, receiving__status="COMPLETED")
            .aggregate(last_dt=Max("receiving__completed_at"))
            .get("last_dt")
        )
        last_shipping = (
            stock.product.order_lines.filter(order__status=OrderStatus.SHIPPED)
            .aggregate(last_dt=Max("order__shipped_at"))
            .get("last_dt")
        )
        movement_candidates = [dt for dt in [last_receiving, last_shipping] if dt]
        last_movement_dt = max(movement_candidates) if movement_candidates else None
        last_movement = last_movement_dt.date() if last_movement_dt else None
        days_without = (timezone.localdate() - last_movement).days if last_movement else 999

        if last_movement and last_movement >= threshold_date:
            continue

        unit_price = (
            stock.product.order_lines.filter(price__isnull=False)
            .aggregate(avg_price=Avg("price"))
            .get("avg_price")
            or Decimal("0.00")
        )
        estimated_value = stock.qty_available * unit_price
        result.append(
            {
                "product": stock.product,
                "stock": stock,
                "qty_available": stock.qty_available,
                "days_without_movement": days_without,
                "last_movement_date": last_movement,
                "estimated_value": estimated_value,
            }
        )

    return sorted(result, key=lambda x: x["days_without_movement"], reverse=True)


def analyze_analogs_vs_originals(period_start: date, period_end: date) -> list[dict]:
    xrefs = ProductCrossReference.objects.filter(
        relation_type__in=[
            ProductCrossReference.RelationType.ANALOG,
            ProductCrossReference.RelationType.OEM,
        ],
    ).select_related("from_product", "to_product")

    results = []

    for xref in xrefs:
        if xref.relation_type == ProductCrossReference.RelationType.ANALOG:
            original = xref.from_product
            analog = xref.to_product
        else:
            original = xref.to_product
            analog = xref.from_product

        original_sales = (
            OrderLine.objects.filter(
                product=original,
                order__status=OrderStatus.SHIPPED,
                order__shipped_at__date__gte=period_start,
                order__shipped_at__date__lte=period_end,
            )
            .aggregate(
                qty=Coalesce(Sum("qty_picked"), Decimal("0.00")),
                amount=Coalesce(
                    Sum(F("qty_picked") * F("price"), output_field=DecimalField(max_digits=16, decimal_places=2)),
                    Decimal("0.00"),
                ),
            )
        )

        analog_sales = (
            OrderLine.objects.filter(
                product=analog,
                order__status=OrderStatus.SHIPPED,
                order__shipped_at__date__gte=period_start,
                order__shipped_at__date__lte=period_end,
            )
            .aggregate(
                qty=Coalesce(Sum("qty_picked"), Decimal("0.00")),
                amount=Coalesce(
                    Sum(F("qty_picked") * F("price"), output_field=DecimalField(max_digits=16, decimal_places=2)),
                    Decimal("0.00"),
                ),
            )
        )

        total_qty = original_sales["qty"] + analog_sales["qty"]
        substitution_rate = (analog_sales["qty"] / total_qty * 100) if total_qty > 0 else Decimal("0.00")

        results.append(
            {
                "original_product": original,
                "analog_product": analog,
                "original_sales_qty": original_sales["qty"],
                "analog_sales_qty": analog_sales["qty"],
                "original_sales_amount": original_sales["amount"],
                "analog_sales_amount": analog_sales["amount"],
                "substitution_rate": substitution_rate,
            }
        )

    return sorted(results, key=lambda x: x["substitution_rate"], reverse=True)


def get_picking_errors_summary(period_start: date | None = None, period_end: date | None = None) -> dict:
    qs = PickingError.objects.select_related("order_line", "expected_product", "detected_by")

    if period_start:
        qs = qs.filter(detected_at__date__gte=period_start)
    if period_end:
        qs = qs.filter(detected_at__date__lte=period_end)

    total_errors = qs.count()
    resolved_errors = qs.filter(resolved=True).count()
    unresolved_errors = total_errors - resolved_errors

    errors_by_type = qs.values("error_type").annotate(count=Count("id")).order_by("-count")

    top_products = (
        qs.values("expected_product__internal_sku", "expected_product__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    return {
        "total_errors": total_errors,
        "resolved_errors": resolved_errors,
        "unresolved_errors": unresolved_errors,
        "errors_by_type": list(errors_by_type),
        "top_products": list(top_products),
    }


def calculate_demand_forecast(period_days: int = 30, forecast_days: int = 7) -> list[dict]:
    """
    Рассчитывает прогноз спроса на основе истории отгрузок.
    
    Args:
        period_days: Период анализа (дни назад)
        forecast_days: Период прогноза (дни вперёд)
        
    Returns:
        Список словарей с прогнозами для каждого товара
    """
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)
    
    # Получаем историю отгрузок за период
    sales_history = (
        OrderLine.objects.filter(
            order__status=OrderStatus.SHIPPED,
            order__shipped_at__date__gte=period_start,
            order__shipped_at__date__lte=period_end,
            qty_picked__gt=0,
        )
        .values("product_id", "product__internal_sku", "product__name")
        .annotate(
            total_qty=Sum("qty_picked"),
            total_orders=Count("order_id", distinct=True),
            avg_price=Avg("price"),
        )
        .order_by("-total_qty")
    )
    
    result = []
    
    for item in sales_history:
        product_id = item["product_id"]
        total_qty = item["total_qty"] or Decimal("0.00")
        total_orders = item["total_orders"] or 0
        
        # Простой прогноз: среднее количество в день * период прогноза
        # Если было 0 заказов, прогноз = 0
        if total_orders == 0:
            daily_avg = Decimal("0.00")
        else:
            daily_avg = total_qty / Decimal(str(period_days))
        
        forecast_qty = daily_avg * Decimal(str(forecast_days))
        
        # Округляем до целого
        forecast_qty = forecast_qty.quantize(Decimal("1"), rounding="ROUND_HALF_UP")
        
        result.append({
            "product_id": product_id,
            "product_sku": item["product__internal_sku"],
            "product_name": item["product__name"],
            "historical_qty": float(total_qty),
            "historical_orders": total_orders,
            "daily_avg": float(daily_avg),
            "forecast_qty": float(forecast_qty),
            "forecast_period_days": forecast_days,
        })
    
    # Сортируем по прогнозируемому количеству
    result.sort(key=lambda x: x["forecast_qty"], reverse=True)
    
    return result


def calculate_staff_efficiency(period_days: int = 30, role: str = "") -> list[dict]:
    """Метрики эффективности сотрудников по задачам и операциям."""
    since = timezone.now() - timedelta(days=period_days)

    users = User.objects.filter(is_active=True).exclude(role=Roles.INTEGRATION).order_by("role", "username")
    if role:
        users = users.filter(role=role)

    rows: list[dict] = []
    for user in users:
        assigned_qs = Task.objects.filter(assigned_to=user, created_at__gte=since)
        assigned_total = assigned_qs.count()
        completed_qs = Task.objects.filter(
            assigned_to=user,
            status=TaskStatus.COMPLETED,
            completed_at__isnull=False,
            completed_at__gte=since,
        )
        completed_total = completed_qs.count()
        in_progress_total = assigned_qs.filter(status=TaskStatus.IN_PROGRESS).count()
        pending_total = assigned_qs.filter(status=TaskStatus.PENDING).count()

        total_hours = Decimal("0.00")
        for t in completed_qs:
            start_dt = t.started_at or t.created_at
            if not t.completed_at or not start_dt:
                continue
            total_hours += Decimal(str((t.completed_at - start_dt).total_seconds() / 3600))
        avg_task_hours = (total_hours / completed_total) if completed_total else Decimal("0.00")

        picking_completed = PickingTask.objects.filter(
            assigned_to=user,
            status=PickingTaskStatus.COMPLETED,
            completed_at__isnull=False,
            completed_at__gte=since,
        ).count()

        receivings_completed = Receiving.objects.filter(
            created_by=user,
            status=ReceivingStatus.COMPLETED,
            completed_at__isnull=False,
            completed_at__gte=since,
        ).count()

        inventories_completed = Inventory.objects.filter(
            created_by=user,
            status=InventoryStatus.COMPLETED,
            completed_at__isnull=False,
            completed_at__gte=since,
        ).count()

        orders_created = Order.objects.filter(created_by=user, created_at__gte=since).count()
        orders_shipped = Order.objects.filter(
            picked_by=user,
            status=OrderStatus.SHIPPED,
            shipped_at__isnull=False,
            shipped_at__gte=since,
        ).count()

        completion_rate = (Decimal(completed_total) / Decimal(assigned_total) * Decimal("100.00")) if assigned_total else Decimal("0.00")
        score = min(
            Decimal("100.00"),
            completion_rate * Decimal("0.70")
            + Decimal(min(completed_total, 20)) * Decimal("1.50")
            + Decimal(min(picking_completed, 20)) * Decimal("1.00"),
        )

        rows.append(
            {
                "user": user,
                "role": user.get_role_display(),
                "assigned_total": assigned_total,
                "completed_total": completed_total,
                "in_progress_total": in_progress_total,
                "pending_total": pending_total,
                "completion_rate": float(completion_rate.quantize(Decimal("0.01"))),
                "avg_task_hours": float(avg_task_hours.quantize(Decimal("0.01"))),
                "picking_completed": picking_completed,
                "receivings_completed": receivings_completed,
                "inventories_completed": inventories_completed,
                "orders_created": orders_created,
                "orders_shipped": orders_shipped,
                "efficiency_score": float(score.quantize(Decimal("0.01"))),
            }
        )

    rows.sort(key=lambda x: (x["efficiency_score"], x["completed_total"]), reverse=True)
    return rows
