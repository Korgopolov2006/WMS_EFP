from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.constants import Roles
from accounts.permissions import role_required
from catalog.models import Product

from .forms import OrderForm, OrderLineForm
from .models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus
from .services import (
    OrderService,
    PickingService,
    get_task_order_lines,
    reserve_stock_for_order_line,
    suggest_stock_for_order_line,
)


@role_required(Roles.ADMIN, Roles.SALES_MANAGER, Roles.STOREKEEPER)
def order_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    qs = Order.objects.select_related("created_by", "picked_by").all()

    if q:
        qs = qs.filter(
            Q(number__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(customer_phone__icontains=q)
            | Q(external_id__icontains=q)
        )
    if status and status in OrderStatus.values:
        qs = qs.filter(status=status)

    qs = qs.order_by("-id")

    return render(
        request,
        "picking/order_list.html",
        {
            "orders": qs,
            "q": q,
            "status": status,
            "statuses": OrderStatus.choices,
            "title": "Заказы",
            "subtitle": "Управление заказами на отгрузку",
        },
    )


@role_required(Roles.ADMIN, Roles.SALES_MANAGER)
def order_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.created_by = request.user
            order.save()
            messages.success(request, f"Заказ создан: {order.number}")
            return redirect("order_detail", pk=order.pk)
    else:
        form = OrderForm()

    return render(request, "picking/order_form.html", {"form": form, "title": "Новый заказ"})


@role_required(Roles.ADMIN, Roles.SALES_MANAGER, Roles.STOREKEEPER)
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order.objects.select_related("created_by", "picked_by"), pk=pk)
    lines = order.lines.select_related("product", "product__brand", "product__category").all()
    picking_tasks = order.picking_tasks.select_related("assigned_to").all()
    lines_list = list(lines)
    picking_tasks_list = list(picking_tasks)
    line_form = OrderLineForm()

    if request.method == "POST":
        if "add_line" in request.POST:
            if order.status != OrderStatus.DRAFT:
                messages.error(request, "Добавлять строки можно только в статусе 'Черновик'.")
                return redirect("order_detail", pk=pk)
            line_form = OrderLineForm(request.POST)
            if line_form.is_valid():
                product = line_form.cleaned_data["product"]
                qty_ordered = line_form.cleaned_data["qty_ordered"]
                price = line_form.cleaned_data.get("price")

                with transaction.atomic():
                    line, created = OrderLine.objects.update_or_create(
                        order=order,
                        product=product,
                        defaults={"qty_ordered": qty_ordered, "price": price},
                    )
                    if created:
                        messages.success(request, f"Строка для товара '{product.name}' добавлена.")
                    else:
                        messages.info(request, f"Строка для товара '{product.name}' обновлена.")
                return redirect("order_detail", pk=pk)

        elif "change_status" in request.POST:
            new_status = request.POST.get("status", "").strip()
            success = False
            msg_list: list[str] = []

            if new_status == OrderStatus.CONFIRMED:
                success, msg_list = OrderService.confirm_order(order)
            elif new_status == OrderStatus.SHIPPED:
                success, msg_list = OrderService.ship_order(order, request.user)
            else:
                msg_list = ["Ручной перевод в этот статус запрещён. Используйте операции подтверждения/отгрузки."]

            if success:
                for msg in msg_list:
                    messages.success(request, msg)
            else:
                for msg in msg_list:
                    messages.error(request, msg)
            return redirect("order_detail", pk=pk)

    total_lines = len(lines_list)
    total_qty_ordered = sum((line.qty_ordered for line in lines_list), Decimal("0.00"))
    total_qty_picked = sum((line.qty_picked for line in lines_list), Decimal("0.00"))
    remaining_qty = max(total_qty_ordered - total_qty_picked, Decimal("0.00"))

    pick_percent = 0
    if total_qty_ordered > 0:
        pick_percent = int(
            ((total_qty_picked / total_qty_ordered) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    total_tasks = len(picking_tasks_list)
    completed_tasks = sum(1 for task in picking_tasks_list if task.status == PickingTaskStatus.COMPLETED)
    in_progress_tasks = sum(1 for task in picking_tasks_list if task.status == PickingTaskStatus.IN_PROGRESS)
    pending_tasks = sum(1 for task in picking_tasks_list if task.status == PickingTaskStatus.PENDING)

    tasks_percent = 0
    if total_tasks > 0:
        tasks_percent = int(round((completed_tasks / total_tasks) * 100))

    status_progress_order = [
        (OrderStatus.DRAFT, "Черновик"),
        (OrderStatus.CONFIRMED, "Подтверждён"),
        (OrderStatus.IN_PICKING, "В подборе"),
        (OrderStatus.PICKED, "Подобран"),
        (OrderStatus.SHIPPED, "Отгружен"),
    ]
    status_index = {
        OrderStatus.DRAFT: 0,
        OrderStatus.CONFIRMED: 1,
        OrderStatus.IN_PICKING: 2,
        OrderStatus.PICKED: 3,
        OrderStatus.RESERVED: 3,
        OrderStatus.SHIPPED: 4,
    }
    current_stage_index = status_index.get(order.status, -1)
    status_steps = [
        {
            "code": code,
            "label": label,
            "is_done": current_stage_index >= idx,
            "is_current": current_stage_index == idx,
        }
        for idx, (code, label) in enumerate(status_progress_order)
    ]

    line_rows = []
    for line in lines_list:
        line_percent = 0
        if line.qty_ordered > 0:
            line_percent = int(
                ((line.qty_picked / line.qty_ordered) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        line_remaining = max(line.qty_ordered - line.qty_picked, Decimal("0.00"))

        if line_remaining == 0:
            line_state = "Готово"
            line_state_tone = "ok"
        elif line.qty_picked > 0:
            line_state = "Частично"
            line_state_tone = "warn"
        else:
            line_state = "Не начат"
            line_state_tone = "muted"

        line_rows.append(
            {
                "line": line,
                "percent": line_percent,
                "remaining": line_remaining,
                "state": line_state,
                "state_tone": line_state_tone,
            }
        )

    can_add_lines = order.status == OrderStatus.DRAFT
    can_confirm = order.status == OrderStatus.DRAFT and total_lines > 0
    can_ship = (
        order.status in [OrderStatus.PICKED, OrderStatus.RESERVED]
        and total_qty_ordered > 0
        and total_qty_picked >= total_qty_ordered
    )

    context = {
        "order": order,
        "lines": lines_list,
        "line_rows": line_rows,
        "line_form": line_form,
        "picking_tasks": picking_tasks_list,
        "status_steps": status_steps,
        "total_lines": total_lines,
        "total_qty_ordered": total_qty_ordered,
        "total_qty_picked": total_qty_picked,
        "remaining_qty": remaining_qty,
        "pick_percent": pick_percent,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "pending_tasks": pending_tasks,
        "tasks_percent": tasks_percent,
        "can_add_lines": can_add_lines,
        "can_confirm": can_confirm,
        "can_ship": can_ship,
        "title": f"Заказ {order.number}",
        "subtitle": f"Клиент: {order.customer_name}",
    }
    return render(request, "picking/order_detail.html", context)


@role_required(Roles.ADMIN, Roles.SALES_MANAGER)
def order_line_delete(request: HttpRequest, pk: int, line_pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk)
    line = get_object_or_404(OrderLine, order=order, pk=line_pk)
    line.delete()
    messages.success(request, f"Строка для товара '{line.product.name}' удалена.")
    return redirect("order_detail", pk=pk)


@role_required(Roles.ADMIN, Roles.SMALL_PARTS_PICKER, Roles.LOADER)
def picking_task_list(request: HttpRequest) -> HttpResponse:
    status = (request.GET.get("status") or "").strip()
    zone_type = (request.GET.get("zone_type") or "").strip()
    order_id = (request.GET.get("order_id") or "").strip()

    qs = PickingTask.objects.select_related("order", "assigned_to").all()

    if status and status in PickingTaskStatus.values:
        qs = qs.filter(status=status)
    if zone_type:
        qs = qs.filter(zone_type_code=zone_type)
    if order_id.isdigit():
        qs = qs.filter(order_id=int(order_id))

    if request.user.role == Roles.SMALL_PARTS_PICKER:
        qs = qs.filter(zone_type_code="CELL")
    elif request.user.role == Roles.LOADER:
        qs = qs.filter(zone_type_code__in=["SHELF", "FLOOR"])

    qs = qs.order_by("-id")

    return render(
        request,
        "picking/picking_task_list.html",
        {
            "tasks": qs,
            "status": status,
            "zone_type": zone_type,
            "statuses": PickingTaskStatus.choices,
        },
    )


@role_required(Roles.ADMIN, Roles.SMALL_PARTS_PICKER, Roles.LOADER)
def picking_task_detail(request: HttpRequest, pk: int) -> HttpResponse:
    task = get_object_or_404(
        PickingTask.objects.select_related("order", "assigned_to", "order__created_by"), pk=pk
    )
    order_lines = list(get_task_order_lines(task))
    order_lines_with_remaining = [
        {
            "line": line,
            "qty_remaining": line.qty_ordered - line.qty_picked,
            "is_pending": line.qty_ordered > line.qty_picked,
        }
        for line in order_lines
    ]
    picking_lines = task.lines.select_related("order_line", "stock", "stock__storage_location").all()

    if request.method == "POST":
        if "assign" in request.POST:
            if task.status != PickingTaskStatus.PENDING:
                messages.info(request, "Задача уже находится в работе или завершена.")
                return redirect("picking_task_detail", pk=pk)
            task.assigned_to = request.user
            task.status = PickingTaskStatus.IN_PROGRESS
            from django.utils import timezone

            task.started_at = timezone.now()
            task.save(update_fields=["assigned_to", "status", "started_at"])
            if task.order.status == OrderStatus.CONFIRMED:
                task.order.status = OrderStatus.IN_PICKING
                task.order.save(update_fields=["status"])
            messages.success(request, "Задача назначена на вас.")
            return redirect("picking_task_detail", pk=pk)

        elif "scan" in request.POST:
            if task.status != PickingTaskStatus.IN_PROGRESS:
                messages.error(request, "Сканирование доступно только для задач в статусе 'В работе'.")
                return redirect("picking_task_detail", pk=pk)
            oem = request.POST.get("oem", "").strip()
            order_line_id = request.POST.get("order_line_id", "").strip()

            if oem and order_line_id.isdigit():
                order_line = next((line for line in order_lines if line.pk == int(order_line_id)), None)
                if not order_line:
                    messages.error(request, "Строка заказа не относится к этой задаче подбора.")
                    return redirect("picking_task_detail", pk=pk)
                product = order_line.product

                if product.oem_number != oem:
                    messages.error(request, f"OEM не совпадает! Ожидается: {product.oem_number}, отсканирован: {oem}")
                    return redirect("picking_task_detail", pk=pk)

                stock = suggest_stock_for_order_line(order_line)
                if not stock:
                    messages.error(request, "Не найдено подходящего остатка для подбора.")
                    return redirect("picking_task_detail", pk=pk)

                qty_needed = order_line.qty_ordered - order_line.qty_picked
                if qty_needed <= 0:
                    messages.warning(request, "Товар уже полностью подобран.")
                    return redirect("picking_task_detail", pk=pk)

                qty_to_pick = min(qty_needed, stock.qty_available)

                if reserve_stock_for_order_line(order_line, stock, qty_to_pick):
                    picking_line, created = task.lines.get_or_create(
                        order_line=order_line,
                        stock=stock,
                        defaults={"qty_picked": qty_to_pick, "scanned_oem": oem},
                    )
                    if not created:
                        picking_line.qty_picked += qty_to_pick
                        picking_line.scanned_oem = oem
                        picking_line.save(update_fields=["qty_picked", "scanned_oem"])
                    messages.success(request, f"Подобрано {qty_to_pick} шт. из {stock.storage_location.code}")
                else:
                    messages.error(request, "Ошибка при резервировании остатка.")

            return redirect("picking_task_detail", pk=pk)

        elif "complete" in request.POST:
            success, msg_list = PickingService.complete_picking_task(task, request.user)
            if success:
                for msg in msg_list:
                    messages.success(request, msg)
            else:
                for msg in msg_list:
                    messages.error(request, msg)
            return redirect("picking_task_detail", pk=pk)

    context = {
        "task": task,
        "order_lines_with_remaining": order_lines_with_remaining,
        "picking_lines": picking_lines,
    }
    return render(request, "picking/picking_task_detail.html", context)


@login_required
def product_search_ajax(request: HttpRequest) -> JsonResponse:
    q = request.GET.get("q", "").strip()
    products = []
    if q:
        products_qs = Product.objects.filter(
            Q(internal_sku__icontains=q) | Q(oem_number__icontains=q) | Q(name__icontains=q)
        )[:10]
        products = [{"id": p.id, "text": str(p), "oem": p.oem_number} for p in products_qs]
    return JsonResponse({"results": products})
