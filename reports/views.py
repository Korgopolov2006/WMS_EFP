from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from math import sqrt

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
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


def _safe_pct(part: float | int, whole: float | int) -> float:
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100, 1)


def _with_share_ranges(items: list[dict]) -> list[dict]:
    cursor = 0.0
    rows = []
    for item in items:
        share = float(item.get("share", 0) or 0)
        next_cursor = min(100.0, round(cursor + share, 1))
        rows.append({**item, "start": round(cursor, 1), "end": next_cursor})
        cursor = next_cursor
    return rows


def _paginate(request: HttpRequest, items, per_page: int = 5):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get("page"))


def _safe_int(value: str | None, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _contains_query(value, query: str) -> bool:
    return query in str(value or "").lower()


def _build_abc_xyz_products(period_start: date, period_end: date) -> list[dict]:
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

    # Для XYZ считаем коэффициент вариации по дневным отгрузкам за период.
    # Чем выше разброс, тем менее предсказуем спрос.
    day_sales = (
        OrderLine.objects.filter(
            order__status=OrderStatus.SHIPPED,
            order__shipped_at__date__gte=period_start,
            order__shipped_at__date__lte=period_end,
        )
        .annotate(day=TruncDate("order__shipped_at"))
        .values("product_id", "day")
        .annotate(day_qty=Sum("qty_picked"))
    )
    qty_by_product_day: dict[int, dict[date, float]] = defaultdict(dict)
    for row in day_sales:
        qty_by_product_day[row["product_id"]][row["day"]] = float(row["day_qty"] or 0)

    period_len = max((period_end - period_start).days + 1, 1)
    for item in products_data:
        product_id = item["product_id"]
        daily_values = [
            qty_by_product_day.get(product_id, {}).get(period_start + timedelta(days=offset), 0.0)
            for offset in range(period_len)
        ]
        mean = sum(daily_values) / period_len
        if mean <= 0:
            item["coefficient_variation"] = 1.0
            continue
        variance = sum((val - mean) ** 2 for val in daily_values) / period_len
        std_dev = sqrt(variance)
        item["coefficient_variation"] = std_dev / mean

    abc_classes = calculate_abc_class(products_data)
    xyz_classes = calculate_xyz_class(products_data)

    for item in products_data:
        item["abc_class"] = abc_classes.get(item["product_id"], "-")
        item["xyz_class"] = xyz_classes.get(item["product_id"], "-")
        item["abc_xyz"] = f"{item['abc_class']}{item['xyz_class']}"

    return products_data


@role_required(Roles.ADMIN, Roles.ANALYST)
def reports_home(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/home.html", {"title": "Отчёты и аналитика"})


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_abc_xyz(request: HttpRequest) -> HttpResponse:
    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    q = (request.GET.get("q") or "").strip()
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    products_data = _build_abc_xyz_products(period_start, period_end)
    if q:
        query = q.lower()
        products_data = [
            item
            for item in products_data
            if _contains_query(item.get("product_sku"), query)
            or _contains_query(item.get("product_name"), query)
            or _contains_query(item.get("abc_class"), query)
            or _contains_query(item.get("xyz_class"), query)
            or _contains_query(item.get("abc_xyz"), query)
        ]
    abc_counts = Counter(item["abc_class"] for item in products_data)
    xyz_counts = Counter(item["xyz_class"] for item in products_data)
    combo_counts = Counter(item["abc_xyz"] for item in products_data)

    combo_descriptions = {
        "AX": "Высокая выручка и стабильный спрос. Держать в приоритете и пополнять регулярно.",
        "AY": "Высокая выручка, но спрос колеблется. Нужен страховой запас и контроль сезонности.",
        "AZ": "Высокая выручка, но спрос нестабилен. Пополнять осторожно, чаще пересматривать прогноз.",
        "BX": "Средняя выручка и стабильный спрос. Поддерживать стандартный уровень запаса.",
        "BY": "Средняя выручка и умеренная вариативность. Нужен регулярный пересмотр нормативов.",
        "BZ": "Средняя выручка и нестабильный спрос. Минимизировать лишние запасы.",
        "CX": "Низкая выручка, но стабильный спрос. Покупать малыми партиями.",
        "CY": "Низкая выручка и умеренная вариативность. Рассматривать под заказ.",
        "CZ": "Низкая выручка и нестабильный спрос. Кандидаты на вывод из запаса.",
    }
    combo_order = ["AX", "AY", "AZ", "BX", "BY", "BZ", "CX", "CY", "CZ"]
    combo_stats = [
        {
            "code": code,
            "count": combo_counts.get(code, 0),
            "description": combo_descriptions[code],
            "share": _safe_pct(combo_counts.get(code, 0), len(products_data)),
        }
        for code in combo_order
    ]

    abc_distribution = _with_share_ranges([
        {"code": "A", "count": abc_counts.get("A", 0), "share": _safe_pct(abc_counts.get("A", 0), len(products_data))},
        {"code": "B", "count": abc_counts.get("B", 0), "share": _safe_pct(abc_counts.get("B", 0), len(products_data))},
        {"code": "C", "count": abc_counts.get("C", 0), "share": _safe_pct(abc_counts.get("C", 0), len(products_data))},
    ])
    xyz_distribution = _with_share_ranges([
        {"code": "X", "count": xyz_counts.get("X", 0), "share": _safe_pct(xyz_counts.get("X", 0), len(products_data))},
        {"code": "Y", "count": xyz_counts.get("Y", 0), "share": _safe_pct(xyz_counts.get("Y", 0), len(products_data))},
        {"code": "Z", "count": xyz_counts.get("Z", 0), "share": _safe_pct(xyz_counts.get("Z", 0), len(products_data))},
    ])
    top_combo_stats = [item for item in combo_stats if item["count"] > 0][:6]
    page_obj = _paginate(request, products_data, per_page=5)

    return render(
        request,
        "reports/abc_xyz.html",
        {
            "title": "ABC-XYZ анализ",
            "products": page_obj.object_list,
            "period_start": period_start,
            "period_end": period_end,
            "period_days": period_days,
            "products_count": len(products_data),
            "total_qty": sum(item["qty"] for item in products_data),
            "total_amount": sum(item["amount"] for item in products_data),
            "abc_counts": {
                "A": abc_counts.get("A", 0),
                "B": abc_counts.get("B", 0),
                "C": abc_counts.get("C", 0),
            },
            "xyz_counts": {
                "X": xyz_counts.get("X", 0),
                "Y": xyz_counts.get("Y", 0),
                "Z": xyz_counts.get("Z", 0),
            },
            "combo_stats": combo_stats,
            "abc_distribution": abc_distribution,
            "xyz_distribution": xyz_distribution,
            "top_combo_stats": top_combo_stats,
            "page_obj": page_obj,
            "q": q,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_dead_stock(request: HttpRequest) -> HttpResponse:
    days_threshold = _safe_int(request.GET.get("days"), 90, min_value=1, max_value=3650)
    q = (request.GET.get("q") or "").strip()
    dead_stocks = find_dead_stock(days_threshold)
    if q:
        query = q.lower()
        filtered = []
        for item in dead_stocks:
            location = getattr(item.get("stock"), "storage_location", None)
            zone = getattr(location, "zone", None)
            if (
                _contains_query(item["product"].internal_sku, query)
                or _contains_query(item["product"].name, query)
                or _contains_query(getattr(location, "code", ""), query)
                or _contains_query(getattr(zone, "name", ""), query)
            ):
                filtered.append(item)
        dead_stocks = filtered

    total_value = sum(item["estimated_value"] or 0 for item in dead_stocks)
    total_qty = sum(item["qty_available"] or 0 for item in dead_stocks)
    items_count = len(dead_stocks)
    avg_days = (
        round(sum(item["days_without_movement"] for item in dead_stocks) / items_count, 1)
        if items_count
        else 0
    )
    critical_items = [item for item in dead_stocks if item["days_without_movement"] >= 180]
    high_items = [item for item in dead_stocks if 90 <= item["days_without_movement"] < 180]
    medium_items = [item for item in dead_stocks if item["days_without_movement"] < 90]
    critical_share = round((len(critical_items) / items_count) * 100, 1) if items_count else 0
    top_value_item = max(dead_stocks, key=lambda x: x["estimated_value"] or 0, default=None)
    top_age_item = max(dead_stocks, key=lambda x: x["days_without_movement"], default=None)
    top_value_items = sorted(dead_stocks, key=lambda x: x["estimated_value"] or 0, reverse=True)[:7]
    top_value_base = top_value_items[0]["estimated_value"] if top_value_items else 0
    for item in top_value_items:
        item["value_share"] = _safe_pct(item["estimated_value"] or 0, top_value_base)

    risk_distribution = _with_share_ranges([
        {"label": "Критический (180+)", "count": len(critical_items), "share": _safe_pct(len(critical_items), items_count)},
        {"label": "Высокий (90-179)", "count": len(high_items), "share": _safe_pct(len(high_items), items_count)},
        {"label": "Средний (<90)", "count": len(medium_items), "share": _safe_pct(len(medium_items), items_count)},
    ])
    page_obj = _paginate(request, dead_stocks, per_page=5)

    return render(
        request,
        "reports/dead_stock.html",
        {
            "title": "Мёртвые остатки",
            "items": page_obj.object_list,
            "days_threshold": days_threshold,
            "total_value": total_value,
            "total_qty": total_qty,
            "items_count": items_count,
            "avg_days": avg_days,
            "critical_count": len(critical_items),
            "critical_share": critical_share,
            "top_value_item": top_value_item,
            "top_age_item": top_age_item,
            "top_value_items": top_value_items,
            "risk_distribution": risk_distribution,
            "page_obj": page_obj,
            "q": q,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_analogs_vs_originals(request: HttpRequest) -> HttpResponse:
    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    q = (request.GET.get("q") or "").strip()
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    analysis_raw = analyze_analogs_vs_originals(period_start, period_end)
    analysis = [
        item
        for item in analysis_raw
        if (item["original_sales_qty"] or 0) > 0 or (item["analog_sales_qty"] or 0) > 0
    ]
    if q:
        query = q.lower()
        analysis = [
            item
            for item in analysis
            if _contains_query(item["original_product"].internal_sku, query)
            or _contains_query(item["original_product"].name, query)
            or _contains_query(item["analog_product"].internal_sku, query)
            or _contains_query(item["analog_product"].name, query)
        ]

    total_original_qty = sum(item["original_sales_qty"] for item in analysis)
    total_analog_qty = sum(item["analog_sales_qty"] for item in analysis)
    total_original_amount = sum(item["original_sales_amount"] for item in analysis)
    total_analog_amount = sum(item["analog_sales_amount"] for item in analysis)

    total_qty = total_original_qty + total_analog_qty
    overall_substitution_rate = float((total_analog_qty / total_qty) * 100) if total_qty else 0

    segment_counts = {
        "high_analog": sum(1 for item in analysis if float(item["substitution_rate"] or 0) >= 60),
        "balanced": sum(
            1 for item in analysis if 40 <= float(item["substitution_rate"] or 0) < 60
        ),
        "original_dominant": sum(1 for item in analysis if float(item["substitution_rate"] or 0) < 40),
    }

    segment_distribution = _with_share_ranges([
        {"label": "Аналог лидер", "count": segment_counts["high_analog"], "share": _safe_pct(segment_counts["high_analog"], len(analysis))},
        {"label": "Баланс", "count": segment_counts["balanced"], "share": _safe_pct(segment_counts["balanced"], len(analysis))},
        {"label": "Оригинал лидер", "count": segment_counts["original_dominant"], "share": _safe_pct(segment_counts["original_dominant"], len(analysis))},
    ])
    top_substitution_pairs = sorted(analysis, key=lambda x: float(x["substitution_rate"] or 0), reverse=True)[:8]
    qty_split = {
        "original_share": _safe_pct(total_original_qty, total_qty),
        "analog_share": _safe_pct(total_analog_qty, total_qty),
    }
    amount_total = total_original_amount + total_analog_amount
    amount_split = {
        "original_share": _safe_pct(total_original_amount, amount_total),
        "analog_share": _safe_pct(total_analog_amount, amount_total),
    }
    page_obj = _paginate(request, analysis, per_page=5)

    return render(
        request,
        "reports/analogs_vs_originals.html",
        {
            "title": "Анализ аналогов vs оригиналов",
            "items": page_obj.object_list,
            "period_start": period_start,
            "period_end": period_end,
            "period_days": period_days,
            "pairs_count": len(analysis),
            "overall_substitution_rate": overall_substitution_rate,
            "total_original_qty": total_original_qty,
            "total_analog_qty": total_analog_qty,
            "total_original_amount": total_original_amount,
            "total_analog_amount": total_analog_amount,
            "segment_counts": segment_counts,
            "segment_distribution": segment_distribution,
            "top_substitution_pairs": top_substitution_pairs,
            "qty_split": qty_split,
            "amount_split": amount_split,
            "page_obj": page_obj,
            "q": q,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST, Roles.STOREKEEPER)
def report_picking_errors(request: HttpRequest) -> HttpResponse:
    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    q = (request.GET.get("q") or "").strip()
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    from reports.models import PickingError

    errors_qs = (
        PickingError.objects.filter(
            detected_at__date__gte=period_start,
            detected_at__date__lte=period_end,
        )
        .select_related("order_line", "expected_product", "actual_product", "detected_by")
        .order_by("-detected_at")
    )
    if q:
        errors_qs = errors_qs.filter(
            Q(order_line__order__number__icontains=q)
            | Q(order_line__product__internal_sku__icontains=q)
            | Q(expected_product__internal_sku__icontains=q)
            | Q(expected_product__name__icontains=q)
            | Q(actual_product__internal_sku__icontains=q)
            | Q(actual_product__name__icontains=q)
            | Q(detected_by__username__icontains=q)
            | Q(error_type__icontains=q)
            | Q(notes__icontains=q)
        )

    total_errors = errors_qs.count()
    resolved_errors = errors_qs.filter(resolved=True).count()
    unresolved_errors = total_errors - resolved_errors
    resolved_rate = round((resolved_errors / total_errors) * 100, 1) if total_errors else 0

    type_labels = dict(PickingError._meta.get_field("error_type").choices)
    errors_by_type = [
        {
            "code": item["error_type"],
            "label": type_labels.get(item["error_type"], item["error_type"]),
            "count": item["count"],
            "share": round((item["count"] / total_errors) * 100, 1) if total_errors else 0,
        }
        for item in errors_qs.values("error_type").annotate(count=Count("id")).order_by("-count")
    ]
    top_products = list(
        errors_qs.values("expected_product__internal_sku", "expected_product__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    top_detectors = list(
        errors_qs.values("detected_by__username")
        .annotate(count=Count("id"))
        .order_by("-count", "detected_by__username")[:5]
    )

    unresolved_old_count = errors_qs.filter(
        resolved=False,
        detected_at__lt=timezone.now() - timedelta(days=2),
    ).count()
    status_distribution = _with_share_ranges([
        {"label": "Исправлено", "count": resolved_errors, "share": _safe_pct(resolved_errors, total_errors)},
        {"label": "Не исправлено", "count": unresolved_errors, "share": _safe_pct(unresolved_errors, total_errors)},
    ])
    page_obj = _paginate(request, errors_qs, per_page=5)

    return render(
        request,
        "reports/picking_errors.html",
        {
            "title": "Ошибки подбора",
            "errors": page_obj.object_list,
            "period_start": period_start,
            "period_end": period_end,
            "period_days": period_days,
            "resolved_rate": resolved_rate,
            "errors_by_type": errors_by_type,
            "top_products": top_products,
            "top_detectors": top_detectors,
            "unresolved_old_count": unresolved_old_count,
            "total_errors": total_errors,
            "resolved_errors": resolved_errors,
            "unresolved_errors": unresolved_errors,
            "status_distribution": status_distribution,
            "page_obj": page_obj,
            "q": q,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_demand_forecast(request: HttpRequest) -> HttpResponse:
    period_days = _safe_int(request.GET.get("period"), 30, min_value=7, max_value=365)
    forecast_days = _safe_int(request.GET.get("forecast_days"), 7, min_value=1, max_value=90)
    q = (request.GET.get("q") or "").strip()
    
    from reports.services import calculate_demand_forecast
    forecasts = calculate_demand_forecast(period_days=period_days, forecast_days=forecast_days)
    if q:
        query = q.lower()
        forecasts = [
            item
            for item in forecasts
            if _contains_query(item.get("product_sku"), query) or _contains_query(item.get("product_name"), query)
        ]
    top_forecasts = forecasts[:10]
    max_forecast = max((item["forecast_qty"] for item in top_forecasts), default=0)
    for item in top_forecasts:
        item["forecast_share"] = _safe_pct(item["forecast_qty"], max_forecast)
        pair_total = item["historical_qty"] + item["forecast_qty"]
        item["history_split_share"] = _safe_pct(item["historical_qty"], pair_total)
        item["forecast_split_share"] = _safe_pct(item["forecast_qty"], pair_total)
    products_count = len(forecasts)
    total_historical_qty = sum(item["historical_qty"] for item in forecasts)
    total_forecast_qty = sum(item["forecast_qty"] for item in forecasts)
    avg_daily_total = sum(item["daily_avg"] for item in forecasts)
    growth_pct = _safe_pct(total_forecast_qty - total_historical_qty, total_historical_qty) if total_historical_qty else 0
    page_obj = _paginate(request, forecasts, per_page=5)
    
    return render(
        request,
        "reports/demand_forecast.html",
        {
            "title": "Прогноз спроса",
            "forecasts": page_obj.object_list,
            "top_forecasts": top_forecasts,
            "products_count": products_count,
            "total_historical_qty": total_historical_qty,
            "total_forecast_qty": total_forecast_qty,
            "avg_daily_total": avg_daily_total,
            "growth_pct": growth_pct,
            "period_days": period_days,
            "forecast_days": forecast_days,
            "page_obj": page_obj,
            "q": q,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_staff_efficiency(request: HttpRequest) -> HttpResponse:
    period_days = _safe_int(request.GET.get("period"), 30, min_value=1, max_value=365)
    selected_role = request.GET.get("role", "")
    q = (request.GET.get("q") or "").strip()

    role_choices = [
        (Roles.ADMIN, "Администратор"),
        (Roles.STOREKEEPER, "Кладовщик"),
        (Roles.SMALL_PARTS_PICKER, "Сборщик"),
        (Roles.LOADER, "Грузчик"),
        (Roles.SALES_MANAGER, "Менеджер"),
        (Roles.ANALYST, "Аналитик"),
    ]

    metrics = calculate_staff_efficiency(period_days=period_days, role=selected_role)
    if q:
        query = q.lower()
        metrics = [
            item
            for item in metrics
            if _contains_query(item["user"].username, query)
            or _contains_query(item["user"].get_full_name(), query)
            or _contains_query(item["role"], query)
        ]

    max_assigned = max((item["assigned_total"] for item in metrics), default=1)
    for item in metrics:
        item["completion_gap"] = max(item["assigned_total"] - item["completed_total"], 0)
        item["workload_share"] = round((item["assigned_total"] / max_assigned) * 100, 1) if max_assigned else 0
        if item["efficiency_score"] >= 80:
            item["score_band"] = "high"
            item["score_label"] = "Стабильно высокий результат"
        elif item["efficiency_score"] >= 60:
            item["score_band"] = "mid"
            item["score_label"] = "Рабочий уровень"
        else:
            item["score_band"] = "low"
            item["score_label"] = "Нужен разбор отклонений"

    summary = {
        "employees": len(metrics),
        "total_assigned_tasks": sum(item["assigned_total"] for item in metrics),
        "total_completed_tasks": sum(item["completed_total"] for item in metrics),
        "avg_score": round(sum(item["efficiency_score"] for item in metrics) / len(metrics), 2) if metrics else 0,
        "avg_completion_rate": round(sum(item["completion_rate"] for item in metrics) / len(metrics), 2) if metrics else 0,
        "avg_task_hours": round(sum(item["avg_task_hours"] for item in metrics) / len(metrics), 2) if metrics else 0,
        "total_picking_completed": sum(item["picking_completed"] for item in metrics),
        "total_orders_shipped": sum(item["orders_shipped"] for item in metrics),
        "total_orders_created": sum(item["orders_created"] for item in metrics),
        "total_receivings_completed": sum(item["receivings_completed"] for item in metrics),
        "total_inventories_completed": sum(item["inventories_completed"] for item in metrics),
    }

    leaders = metrics[:3]
    attention_items = [
        item
        for item in metrics
        if (item["assigned_total"] >= 5 and item["completion_rate"] < 60) or item["avg_task_hours"] >= 10
    ][:5]

    role_accumulator: dict[str, dict] = defaultdict(
        lambda: {
            "role": "",
            "employees": 0,
            "assigned_total": 0,
            "completed_total": 0,
            "score_sum": 0.0,
            "completion_rate_sum": 0.0,
        }
    )

    for item in metrics:
        bucket = role_accumulator[item["role"]]
        bucket["role"] = item["role"]
        bucket["employees"] += 1
        bucket["assigned_total"] += item["assigned_total"]
        bucket["completed_total"] += item["completed_total"]
        bucket["score_sum"] += item["efficiency_score"]
        bucket["completion_rate_sum"] += item["completion_rate"]

    role_summary = []
    for bucket in role_accumulator.values():
        employees_count = bucket["employees"] or 1
        role_summary.append(
            {
                "role": bucket["role"],
                "employees": bucket["employees"],
                "assigned_total": bucket["assigned_total"],
                "completed_total": bucket["completed_total"],
                "avg_score": round(bucket["score_sum"] / employees_count, 2),
                "avg_completion_rate": round(bucket["completion_rate_sum"] / employees_count, 2),
            }
        )
    role_summary.sort(key=lambda item: (item["avg_score"], item["completed_total"]), reverse=True)
    top_performers = metrics[:8]
    role_chart = role_summary[:8]
    max_score = max((item["efficiency_score"] for item in top_performers), default=0)
    max_role_completed = max((item["completed_total"] for item in role_chart), default=0)
    for item in top_performers:
        item["score_share"] = _safe_pct(item["efficiency_score"], max_score)
    for item in role_chart:
        item["completed_share"] = _safe_pct(item["completed_total"], max_role_completed)
    page_obj = _paginate(request, metrics, per_page=5)

    return render(
        request,
        "reports/staff_efficiency.html",
        {
            "title": "Эффективность сотрудников",
            "metrics": page_obj.object_list,
            "period_days": period_days,
            "selected_role": selected_role,
            "q": q,
            "role_choices": role_choices,
            "summary": summary,
            "leaders": leaders,
            "attention_items": attention_items,
            "role_summary": role_summary,
            "top_performers": top_performers,
            "role_chart": role_chart,
            "page_obj": page_obj,
        },
    )


@role_required(Roles.ADMIN, Roles.ANALYST)
def report_data_json(request: HttpRequest, report_type: str) -> JsonResponse:
    period_days = int(request.GET.get("period", 30))
    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=period_days)

    if report_type == "abc_xyz":
        products_data = _build_abc_xyz_products(period_start, period_end)
        for item in products_data:
            item["qty"] = float(item["qty"])
            item["amount"] = float(item["amount"])

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
