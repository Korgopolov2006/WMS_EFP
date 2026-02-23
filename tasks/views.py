from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.constants import Roles
from accounts.permissions import role_required
from picking.models import Order, OrderStatus, PickingTask, PickingTaskStatus
from receiving.models import ReceivingStatus
from .models import Task, TaskStatus, TaskType
from .services import TaskService


def _paginate(request: HttpRequest, items, per_page: int = 5):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get("page"))


def _is_admin_user(user) -> bool:
    return bool(user.is_superuser or user.role == Roles.ADMIN)


def _can_start_task(task: Task, user) -> bool:
    if task.status != TaskStatus.PENDING:
        return False

    if task.task_type == TaskType.RECEIVING:
        if not task.receiving:
            return False
        if task.receiving.status in [ReceivingStatus.COMPLETED, ReceivingStatus.CANCELLED]:
            return False

    if not task.can_be_assigned_to(user):
        return False
    if task.assigned_to_id is None:
        return True
    if task.assigned_to_id == user.id:
        return True
    return _is_admin_user(user)


def _can_complete_task(task: Task, user) -> bool:
    if task.status != TaskStatus.IN_PROGRESS:
        return False

    if task.task_type == TaskType.RECEIVING:
        if not task.receiving:
            return False
        if task.receiving.status != ReceivingStatus.COMPLETED:
            return False

    if task.assigned_to_id == user.id:
        return True
    return _is_admin_user(user)


@role_required(Roles.ADMIN, Roles.SMALL_PARTS_PICKER, Roles.LOADER, Roles.STOREKEEPER)
def tasks_monitoring(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "tasks/monitoring.html",
        {
            "title": "Мониторинг задач",
            "refresh_interval_sec": 8,
        },
    )


@login_required
def tasks_monitoring_api(request: HttpRequest) -> JsonResponse:
    now = timezone.now()
    active_orders_qs = Order.objects.filter(
        status__in=[OrderStatus.CONFIRMED, OrderStatus.IN_PICKING, OrderStatus.PICKED]
    )
    active_orders = active_orders_qs.count()

    pending_tasks = PickingTask.objects.filter(status=PickingTaskStatus.PENDING).count()
    in_progress_tasks = PickingTask.objects.filter(status=PickingTaskStatus.IN_PROGRESS).count()
    completed_tasks_today = PickingTask.objects.filter(
        status=PickingTaskStatus.COMPLETED,
        completed_at__date=now.date(),
    ).count()

    active_picking_tasks = (
        PickingTask.objects.select_related("order", "assigned_to")
        .filter(status__in=[PickingTaskStatus.PENDING, PickingTaskStatus.IN_PROGRESS])
        .order_by("-id")[:20]
    )

    active_picking_created = list(
        PickingTask.objects.filter(status__in=[PickingTaskStatus.PENDING, PickingTaskStatus.IN_PROGRESS])
        .values_list("created_at", flat=True)
    )
    avg_open_age_hours = (
        round(
            sum((now - created_at).total_seconds() for created_at in active_picking_created)
            / len(active_picking_created)
            / 3600,
            1,
        )
        if active_picking_created
        else 0
    )
    stale_picking_count = PickingTask.objects.filter(
        status__in=[PickingTaskStatus.PENDING, PickingTaskStatus.IN_PROGRESS],
        created_at__lt=now - timedelta(hours=4),
    ).count()

    zone_load = list(
        PickingTask.objects.filter(status__in=[PickingTaskStatus.PENDING, PickingTaskStatus.IN_PROGRESS])
        .values("zone_type_code")
        .annotate(count=Count("id"))
        .order_by("-count", "zone_type_code")
    )

    universal_tasks = (
        Task.objects.filter(status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
        .select_related("assigned_to", "created_by", "order", "receiving", "inventory", "picking_task")
        .order_by("due_date", "-created_at")[:20]
    )
    universal_tasks_qs = Task.objects.filter(status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
    universal_pending = universal_tasks_qs.filter(status=TaskStatus.PENDING).count()
    universal_in_progress = universal_tasks_qs.filter(status=TaskStatus.IN_PROGRESS).count()
    overdue_universal = universal_tasks_qs.filter(due_date__isnull=False, due_date__lt=now).count()

    task_type_labels = dict(TaskType.choices)
    task_status_labels = dict(TaskStatus.choices)
    priority_labels = dict(Task._meta.get_field("priority").choices)

    universal_by_type = [
        {
            "code": item["task_type"],
            "label": task_type_labels.get(item["task_type"], item["task_type"]),
            "count": item["count"],
        }
        for item in universal_tasks_qs.values("task_type").annotate(count=Count("id")).order_by("-count", "task_type")
    ]
    universal_by_priority = [
        {
            "code": item["priority"],
            "label": priority_labels.get(item["priority"], item["priority"]),
            "count": item["count"],
        }
        for item in universal_tasks_qs.values("priority").annotate(count=Count("id")).order_by("-count", "priority")
    ]

    tasks_data = [
        {
            "id": t.id,
            "order_id": t.order_id,
            "order_number": t.order.number,
            "zone_type_code": t.zone_type_code,
            "status": t.status,
            "assigned_to": t.assigned_to.username if t.assigned_to else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "started_at": t.started_at.isoformat() if t.started_at else None,
        }
        for t in active_picking_tasks
    ]

    def _task_reference(task: Task) -> str:
        if task.order:
            return f"Заказ {task.order.number}"
        if task.receiving:
            return f"Приемка {task.receiving.number}"
        if task.inventory:
            return f"Инвентаризация {task.inventory.number}"
        if task.picking_task:
            return f"Подбор #{task.picking_task_id}"
        return "Без связанного документа"

    universal_tasks_data = [
        {
            "id": t.id,
            "type": t.task_type,
            "type_label": task_type_labels.get(t.task_type, t.task_type),
            "title": t.title,
            "status": t.status,
            "status_label": task_status_labels.get(t.status, t.status),
            "priority": t.priority,
            "priority_label": priority_labels.get(t.priority, t.priority),
            "assigned_to": t.assigned_to.username if t.assigned_to else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "is_overdue": bool(t.due_date and t.due_date < now),
            "reference": _task_reference(t),
        }
        for t in universal_tasks
    ]

    return JsonResponse(
        {
            "generated_at": now.isoformat(),
            "active_orders": active_orders,
            "pending_tasks": pending_tasks,
            "in_progress_tasks": in_progress_tasks,
            "completed_tasks_today": completed_tasks_today,
            "avg_open_age_hours": avg_open_age_hours,
            "stale_picking_count": stale_picking_count,
            "zone_load": zone_load,
            "universal_pending": universal_pending,
            "universal_in_progress": universal_in_progress,
            "universal_overdue": overdue_universal,
            "universal_by_type": universal_by_type,
            "universal_by_priority": universal_by_priority,
            "recent_tasks": tasks_data,
            "universal_tasks": universal_tasks_data,
        }
    )


@login_required
@require_http_methods(["GET"])
def task_list(request: HttpRequest) -> HttpResponse:
    """Список задач с фильтрацией по ролям."""
    # Получаем задачи, доступные пользователю
    tasks = TaskService.get_tasks_for_user(request.user)
    tasks = tasks.select_related("assigned_to", "created_by", "receiving", "inventory", "order", "picking_task")

    # Фильтры
    task_type = request.GET.get("type")
    if task_type:
        tasks = tasks.filter(task_type=task_type)

    status = request.GET.get("status")
    if status:
        tasks = tasks.filter(status=status)

    assigned_to = request.GET.get("assigned_to")
    if assigned_to:
        tasks = tasks.filter(assigned_to_id=assigned_to)

    q = (request.GET.get("q") or "").strip()
    if q:
        tasks = tasks.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(created_by__username__icontains=q)
            | Q(assigned_to__username__icontains=q)
            | Q(order__number__icontains=q)
            | Q(receiving__number__icontains=q)
            | Q(inventory__number__icontains=q)
        )

    is_admin_user = _is_admin_user(request.user)
    my_tasks = request.GET.get("my_tasks") == "1"

    # Для обычных ролей всегда показываем только назначенные им задачи.
    if not is_admin_user:
        tasks = tasks.filter(assigned_to=request.user)
    elif my_tasks:
        # Для админа чекбокс "Только мои" включает фильтр по исполнителю.
        tasks = tasks.filter(assigned_to=request.user)

    tasks = tasks.order_by("-priority", "-created_at")
    page_obj = _paginate(request, tasks, per_page=5)
    page_tasks = list(page_obj.object_list)
    startable_task_ids = [task.id for task in page_tasks if _can_start_task(task, request.user)]
    completable_task_ids = [task.id for task in page_tasks if _can_complete_task(task, request.user)]

    return render(
        request,
        "tasks/list.html",
        {
            "tasks": page_tasks,
            "task_types": TaskType.choices,
            "task_statuses": TaskStatus.choices,
            "task_type": task_type or "",
            "status": status or "",
            "q": q,
            "user_role": request.user.role,
            "my_tasks": my_tasks,
            "startable_task_ids": startable_task_ids,
            "completable_task_ids": completable_task_ids,
            "page_obj": page_obj,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def task_detail(request: HttpRequest, task_id: int) -> HttpResponse:
    """Детальная информация о задаче."""
    from django.contrib import messages

    is_admin_user = _is_admin_user(request.user)
    user_tasks = TaskService.get_tasks_for_user(request.user)
    if not is_admin_user:
        user_tasks = user_tasks.filter(assigned_to=request.user)

    task = get_object_or_404(
        user_tasks.select_related("assigned_to", "created_by", "receiving", "inventory", "order", "picking_task"),
        id=task_id,
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "start":
            if not _can_start_task(task, request.user):
                if task.task_type == TaskType.RECEIVING:
                    messages.error(request, "Нельзя начать задачу: документ приёмки уже закрыт или отменён.")
                else:
                    messages.error(request, "Нельзя начать эту задачу.")
                return redirect("task_detail", task_id=task_id)

            if TaskService.assign_task_to_user(task, request.user):
                messages.success(request, "Задача начата.")
            else:
                messages.error(request, "Не удалось начать задачу.")
            return redirect("task_detail", task_id=task_id)

        elif action == "complete":
            if not _can_complete_task(task, request.user):
                if task.task_type == TaskType.RECEIVING:
                    messages.error(request, "Сначала завершите документ приёмки, затем закройте задачу.")
                else:
                    messages.error(request, "Нельзя завершить эту задачу.")
                return redirect("task_detail", task_id=task_id)

            if TaskService.complete_task(task, request.user):
                messages.success(request, "Задача завершена.")
            else:
                messages.error(request, "Не удалось завершить задачу.")
            return redirect("task_detail", task_id=task_id)

    return render(
        request,
        "tasks/detail.html",
        {
            "task": task,
            "can_start": _can_start_task(task, request.user),
            "can_complete": _can_complete_task(task, request.user),
        },
    )
