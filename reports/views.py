from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.constants import Roles
from accounts.permissions import role_required
from picking.models import OrderLine, OrderStatus
from reports.services import (
    analyze_analogs_vs_originals,
    calculate_staff_efficiency,
    calculate_abc_class,
    calculate_xyz_class,
    find_dead_stock,
    get_picking_errors_summary,
)


@role_required(Roles.ADMIN, Roles.ANALYST)
def reports_home(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/home.html", {"title": "Отчёты и аналитика"})


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_abc_xyz(request: HttpRequest) -> HttpResponse:
    period_days = int(request.GET.get("period", 30))
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    sales_data = (
        OrderLine.objects.filter(
            order__status=OrderStatus.SHIPPED,
            order__shipped_at__date__gte=period_start,
            order__shipped_at__date__lte=period_end,
        )
        .values("product_id", "product__internal_sku", "product__name")
        .annotate(
            total_qty=Sum("qty_picked"),
            total_amount=Sum("qty_picked") * Sum("price"),
        )
        .order_by("-total_amount")
    )

    products_data = []
    for item in sales_data:
        products_data.append(
            {
                "product_id": item["product_id"],
                "product_sku": item["product__internal_sku"],
                "product_name": item["product__name"],
                "qty": item["total_qty"] or 0,
                "amount": item["total_amount"] or 0,
            }
        )

    abc_classes = calculate_abc_class(products_data)
    xyz_classes = calculate_xyz_class(products_data)

    for item in products_data:
        item["abc_class"] = abc_classes.get(item["product_id"], "-")
        item["xyz_class"] = xyz_classes.get(item["product_id"], "-")

    return render(
        request,
        "reports/abc_xyz.html",
        {
            "title": "ABC-XYZ анализ",
            "products": products_data,
            "period_start": period_start,
            "period_end": period_end,
            "period_days": period_days,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_dead_stock(request: HttpRequest) -> HttpResponse:
    days_threshold = int(request.GET.get("days", 90))
    dead_stocks = find_dead_stock(days_threshold)

    total_value = sum(item["estimated_value"] or 0 for item in dead_stocks)

    return render(
        request,
        "reports/dead_stock.html",
        {
            "title": "Мёртвые остатки",
            "items": dead_stocks,
            "days_threshold": days_threshold,
            "total_value": total_value,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_analogs_vs_originals(request: HttpRequest) -> HttpResponse:
    period_days = int(request.GET.get("period", 30))
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    analysis = analyze_analogs_vs_originals(period_start, period_end)

    return render(
        request,
        "reports/analogs_vs_originals.html",
        {
            "title": "Анализ аналогов vs оригиналов",
            "items": analysis,
            "period_start": period_start,
            "period_end": period_end,
            "period_days": period_days,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST, Roles.STOREKEEPER)
def report_picking_errors(request: HttpRequest) -> HttpResponse:
    period_days = int(request.GET.get("period", 30))
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    from reports.models import PickingError

    errors = (
        PickingError.objects.filter(
            detected_at__date__gte=period_start,
            detected_at__date__lte=period_end,
        )
        .select_related("order_line", "expected_product", "actual_product", "detected_by")
        .order_by("-detected_at")
    )

    summary = get_picking_errors_summary(period_start, period_end)

    return render(
        request,
        "reports/picking_errors.html",
        {
            "title": "Ошибки подбора",
            "errors": errors,
            "summary": summary,
            "period_start": period_start,
            "period_end": period_end,
            "period_days": period_days,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_demand_forecast(request: HttpRequest) -> HttpResponse:
    period_days = int(request.GET.get("period", 30))
    forecast_days = int(request.GET.get("forecast_days", 7))
    
    from reports.services import calculate_demand_forecast
    forecasts = calculate_demand_forecast(period_days=period_days, forecast_days=forecast_days)
    
    return render(
        request,
        "reports/demand_forecast.html",
        {
            "title": "Прогноз спроса",
            "forecasts": forecasts,
            "period_days": period_days,
            "forecast_days": forecast_days,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_staff_efficiency(request: HttpRequest) -> HttpResponse:
    period_days = int(request.GET.get("period", 30))
    selected_role = request.GET.get("role", "")

    role_choices = [
        (Roles.ADMIN, "Администратор"),
        (Roles.STOREKEEPER, "Кладовщик"),
        (Roles.SMALL_PARTS_PICKER, "Сборщик"),
        (Roles.LOADER, "Грузчик"),
        (Roles.SALES_MANAGER, "Менеджер"),
        (Roles.ANALYST, "Аналитик"),
    ]

    metrics = calculate_staff_efficiency(period_days=period_days, role=selected_role)

    summary = {
        "employees": len(metrics),
        "total_completed_tasks": sum(item["completed_total"] for item in metrics),
        "avg_score": round(sum(item["efficiency_score"] for item in metrics) / len(metrics), 2) if metrics else 0,
    }

    return render(
        request,
        "reports/staff_efficiency.html",
        {
            "title": "Эффективность сотрудников",
            "metrics": metrics,
            "period_days": period_days,
            "selected_role": selected_role,
            "role_choices": role_choices,
            "summary": summary,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_data_json(request: HttpRequest, report_type: str) -> JsonResponse:
    period_days = int(request.GET.get("period", 30))
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    if report_type == "abc_xyz":
        sales_data = (
            OrderLine.objects.filter(
                order__status=OrderStatus.SHIPPED,
                order__shipped_at__date__gte=period_start,
                order__shipped_at__date__lte=period_end,
            )
            .values("product_id", "product__internal_sku", "product__name")
            .annotate(
                total_qty=Sum("qty_picked"),
                total_amount=Sum("qty_picked") * Sum("price"),
            )
            .order_by("-total_amount")
        )

        products_data = [
            {
                "product_id": item["product_id"],
                "product_sku": item["product__internal_sku"],
                "product_name": item["product__name"],
                "qty": float(item["total_qty"] or 0),
                "amount": float(item["total_amount"] or 0),
            }
            for item in sales_data
        ]

        abc_classes = calculate_abc_class(products_data)
        xyz_classes = calculate_xyz_class(products_data)

        for item in products_data:
            item["abc_class"] = abc_classes.get(item["product_id"], "-")
            item["xyz_class"] = xyz_classes.get(item["product_id"], "-")

        return JsonResponse({"items": products_data})

    elif report_type == "dead_stock":
        days_threshold = int(request.GET.get("days", 90))
        dead_stocks = find_dead_stock(days_threshold)

        data = [
            {
                "product_id": item["product"].id,
                "product_sku": item["product"].internal_sku,
                "product_name": item["product"].name,
                "qty_available": float(item["qty_available"]),
                "days_without_movement": item["days_without_movement"],
                "estimated_value": float(item["estimated_value"] or 0),
            }
            for item in dead_stocks
        ]

        return JsonResponse({"items": data})

    elif report_type == "picking_errors":
        summary = get_picking_errors_summary(period_start, period_end)
        return JsonResponse(summary)

    return JsonResponse({"error": "Unknown report type"}, status=400)
