from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.constants import Roles
from accounts.permissions import role_required
from catalog.models import Product
from tasks.models import TaskType

from .forms import OrderForm, OrderLineForm
from .models import Order, OrderLine, OrderPriority, OrderStatus, PickingTask, PickingTaskStatus
from .services import (
    OrderService,
    PickingService,
    get_task_order_lines,
    reserve_stock_for_order_line,
    suggest_stock_for_order_line,
)


def _paginate(request: HttpRequest, items, per_page: int = 10):
    from core.pagination import paginate_legacy
    return paginate_legacy(request, items, per_page=per_page)


def _priority_order():
    return Case(
        When(priority=OrderPriority.URGENT, then=Value(0)),
        When(priority=OrderPriority.HIGH, then=Value(1)),
        When(priority=OrderPriority.NORMAL, then=Value(2)),
        When(priority=OrderPriority.LOW, then=Value(3)),
        default=Value(4),
        output_field=IntegerField(),
    )


def _normalize_oem(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


@role_required(Roles.ADMIN, Roles.SALES_MANAGER, Roles.STOREKEEPER, Roles.LOADER)
def order_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    can_create_order = bool(request.user.is_superuser or request.user.role in [Roles.ADMIN, Roles.SALES_MANAGER])

    qs = Order.objects.select_related("created_by", "picked_by").all()

    if request.user.role == Roles.LOADER and not request.user.is_superuser:
        # Грузчик видит заказы на этапе отгрузки и связанные с его shipping-задачами.
        qs = qs.filter(
            Q(status__in=[OrderStatus.PICKED, OrderStatus.RESERVED, OrderStatus.SHIPPED])
            | Q(tasks__task_type=TaskType.SHIPPING, tasks__assigned_to=request.user)
        ).distinct()

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
    page_obj = _paginate(request, qs, per_page=5)

    return render(
        request,
        "picking/order_list.html",
        {
            "orders": page_obj.object_list,
            "q": q,
            "status": status,
            "statuses": OrderStatus.choices,
            "title": "Заказы",
            "subtitle": "Управление заказами на отгрузку",
            "page_obj": page_obj,
            "can_create_order": can_create_order,
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


@role_required(Roles.ADMIN, Roles.SALES_MANAGER, Roles.STOREKEEPER, Roles.SMALL_PARTS_PICKER, Roles.LOADER)
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    can_manage_order = bool(
        request.user.is_superuser
        or request.user.role in [Roles.ADMIN, Roles.SALES_MANAGER, Roles.STOREKEEPER]
    )
    can_ship_order = bool(
        request.user.is_superuser
        or request.user.role in [Roles.ADMIN, Roles.SALES_MANAGER, Roles.STOREKEEPER, Roles.LOADER]
    )

    order_qs = Order.objects.select_related("created_by", "picked_by")
    if not can_manage_order:
        if request.user.role == Roles.SMALL_PARTS_PICKER:
            order_qs = order_qs.filter(picking_tasks__zone_type_code="CELL")
        elif request.user.role == Roles.LOADER:
            order_qs = order_qs.filter(
                Q(picking_tasks__zone_type_code__in=["SHELF", "FLOOR"])
                | Q(status__in=[OrderStatus.PICKED, OrderStatus.RESERVED, OrderStatus.SHIPPED])
                | Q(tasks__task_type=TaskType.SHIPPING, tasks__assigned_to=request.user)
            )
        order_qs = order_qs.distinct()

    order = get_object_or_404(order_qs, pk=pk)
    lines = order.lines.select_related("product", "product__brand", "product__category").all()
    picking_tasks = order.picking_tasks.select_related("assigned_to").all()
    lines_list = list(lines)
    picking_tasks_list = list(picking_tasks)
    line_form = OrderLineForm()

    if request.method == "POST":
        if "add_line" in request.POST:
            if not can_manage_order:
                messages.error(request, "Для вашей роли недоступно редактирование состава заказа.")
                return redirect("order_detail", pk=pk)
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
                if not can_manage_order:
                    messages.error(request, "Для вашей роли недоступно подтверждение заказа.")
                    return redirect("order_detail", pk=pk)
                success, msg_list = OrderService.confirm_order(order)
            elif new_status == OrderStatus.SHIPPED:
                if not can_ship_order:
                    messages.error(request, "Для вашей роли недоступно подтверждение отгрузки.")
                    return redirect("order_detail", pk=pk)

                confirmation_errors: list[str] = []
                if request.POST.get("ship_check_package") != "1":
                    confirmation_errors.append("Подтвердите проверку комплектности и упаковки.")
                if request.POST.get("ship_check_documents") != "1":
                    confirmation_errors.append("Подтвердите передачу отгрузочных документов.")

                confirm_number = (request.POST.get("ship_confirm_number") or "").strip()
                if confirm_number != order.number:
                    confirmation_errors.append("Номер заказа для подтверждения введён неверно.")

                window_number = (request.POST.get("ship_window_number") or "").strip()
                if not window_number:
                    confirmation_errors.append("Укажите номер окна выдачи.")

                if confirmation_errors:
                    for err in confirmation_errors:
                        messages.error(request, err)
                    return redirect("order_detail", pk=pk)

                updated_fields: list[str] = []
                if order.window_number != window_number:
                    order.window_number = window_number
                    updated_fields.append("window_number")
                if not order.reserved_at_window:
                    order.reserved_at_window = True
                    updated_fields.append("reserved_at_window")
                if updated_fields:
                    order.save(update_fields=updated_fields)

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
    line_page_obj = _paginate(request, line_rows, per_page=5)

    can_add_lines = can_manage_order and order.status == OrderStatus.DRAFT
    can_confirm = can_manage_order and order.status == OrderStatus.DRAFT and total_lines > 0
    can_ship = (
        can_ship_order
        and
        order.status in [OrderStatus.PICKED, OrderStatus.RESERVED]
        and total_qty_ordered > 0
        and total_qty_picked >= total_qty_ordered
    )
    back_url = "order_list" if (can_manage_order or request.user.role == Roles.LOADER) else "picking_task_list"

    context = {
        "order": order,
        "lines": lines_list,
        "line_rows": line_page_obj.object_list,
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
        "can_manage_order": can_manage_order,
        "can_ship_order": can_ship_order,
        "back_url": back_url,
        "title": f"Заказ {order.number}",
        "subtitle": f"Клиент: {order.customer_name}",
        "line_page_obj": line_page_obj,
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
    q = (request.GET.get("q") or "").strip()
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
    if q:
        qs = qs.filter(
            Q(order__number__icontains=q)
            | Q(order__customer_name__icontains=q)
            | Q(zone_type_code__icontains=q)
            | Q(assigned_to__username__icontains=q)
        )

    if request.user.role == Roles.SMALL_PARTS_PICKER:
        qs = qs.filter(zone_type_code="CELL")
    elif request.user.role == Roles.LOADER:
        qs = qs.filter(zone_type_code__in=["SHELF", "FLOOR"])

    from core.sorting import apply_ordering
    qs, sort, order = apply_ordering(qs, request, {
        "id":       "id",
        "order":    "order__number",
        "customer": "order__customer_name",
        "zone":     "zone_type_code",
        "status":   "status",
        "priority": "priority",
        "due":      "due_date",
        "assignee": "assigned_to__username",
        "created":  "created_at",
    }, default="priority", default_order="asc")
    if sort == "priority":
        priority_expr = _priority_order()
        if order == "desc":
            priority_expr = priority_expr.desc()
        qs = qs.order_by(priority_expr, "due_date", "-created_at")

    page_obj = _paginate(request, qs, per_page=5)

    return render(
        request,
        "picking/picking_task_list.html",
        {
            "tasks": page_obj.object_list,
            "q": q,
            "status": status,
            "zone_type": zone_type,
            "statuses": PickingTaskStatus.choices,
            "page_obj": page_obj,
            "sort": sort,
            "order": order,
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
    picking_lines = task.lines.select_related("order_line", "stock", "stock__storage_location").order_by("-id")

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
            normalized_oem = _normalize_oem(oem)

            if not normalized_oem:
                messages.error(request, "Введите OEM номер.")
                return redirect("picking_task_detail", pk=pk)

            order_line = None
            if order_line_id.isdigit():
                order_line = next((line for line in order_lines if line.pk == int(order_line_id)), None)
            else:
                pending_matches = [
                    line
                    for line in order_lines
                    if (line.qty_ordered > line.qty_picked)
                    and _normalize_oem(line.product.oem_number) == normalized_oem
                ]
                if len(pending_matches) == 1:
                    order_line = pending_matches[0]
                elif len(pending_matches) > 1:
                    messages.error(request, "По этому OEM найдено несколько строк. Выберите нужную строку вручную.")
                    return redirect("picking_task_detail", pk=pk)
                else:
                    messages.error(request, "Не удалось автоматически определить строку заказа. Выберите строку вручную.")
                    return redirect("picking_task_detail", pk=pk)

            if not order_line:
                messages.error(request, "Строка заказа не относится к этой задаче подбора.")
                return redirect("picking_task_detail", pk=pk)
            product = order_line.product

            if _normalize_oem(product.oem_number) != normalized_oem:
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

    picking_lines_page_obj = _paginate(request, picking_lines, per_page=5)
    default_pending_line = next((item["line"] for item in order_lines_with_remaining if item["is_pending"]), None)
    context = {
        "task": task,
        "order_lines_with_remaining": order_lines_with_remaining,
        "picking_lines": picking_lines_page_obj.object_list,
        "page_obj": picking_lines_page_obj,
        "default_order_line_id": default_pending_line.pk if default_pending_line else "",
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
