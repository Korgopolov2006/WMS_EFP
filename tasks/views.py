from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.constants import Roles
from accounts.permissions import role_required
from picking.models import Order, OrderStatus, PickingTask, PickingTaskStatus
from .models import Task, TaskStatus, TaskType
from .services import TaskService


@role_required(Roles.ADMIN, Roles.SMALL_PARTS_PICKER, Roles.LOADER, Roles.STOREKEEPER)
def tasks_monitoring(request: HttpRequest) -> HttpResponse:
    return render(request, "tasks/monitoring.html", {"title": "Мониторинг задач"})


@login_required
def tasks_monitoring_api(request: HttpRequest) -> JsonResponse:
    active_orders = Order.objects.filter(
        status__in=[OrderStatus.CONFIRMED, OrderStatus.IN_PICKING, OrderStatus.PICKED]
    ).count()

    pending_tasks = PickingTask.objects.filter(status=PickingTaskStatus.PENDING).count()
    in_progress_tasks = PickingTask.objects.filter(status=PickingTaskStatus.IN_PROGRESS).count()
    completed_tasks_today = PickingTask.objects.filter(
        status=PickingTaskStatus.COMPLETED,
        completed_at__date=timezone.now().date(),
    ).count()

    # Универсальные задачи
    universal_tasks = Task.objects.filter(
        status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
    ).select_related("assigned_to", "created_by")[:20]

    recent_tasks = (
        PickingTask.objects.select_related("order", "assigned_to")
        .filter(status__in=[PickingTaskStatus.PENDING, PickingTaskStatus.IN_PROGRESS])
        .order_by("-id")[:20]
    )

    tasks_data = [
        {
            "id": t.id,
            "order_number": t.order.number,
            "zone_type_code": t.zone_type_code,
            "status": t.status,
            "assigned_to": t.assigned_to.username if t.assigned_to else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in recent_tasks
    ]

    universal_tasks_data = [
        {
            "id": t.id,
            "type": t.task_type,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "assigned_to": t.assigned_to.username if t.assigned_to else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in universal_tasks
    ]

    return JsonResponse(
        {
            "active_orders": active_orders,
            "pending_tasks": pending_tasks,
            "in_progress_tasks": in_progress_tasks,
            "completed_tasks_today": completed_tasks_today,
            "recent_tasks": tasks_data,
            "universal_tasks": universal_tasks_data,
        }
    )


@login_required
@require_http_methods(["GET"])
def task_list(request: HttpRequest) -> HttpResponse:
    """Список задач с фильтрацией по ролям."""
    from .services import TaskService
    
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

    # Только мои задачи (по умолчанию для не-админов)
    if not request.user.is_superuser and request.user.role != Roles.ADMIN:
        if request.GET.get("my_tasks") != "0":  # По умолчанию показываем только свои
            tasks = tasks.filter(assigned_to=request.user)

    tasks = tasks.order_by("-priority", "-created_at")[:50]

    return render(
        request,
        "tasks/list.html",
        {
            "tasks": tasks,
            "task_types": TaskType.choices,
            "task_statuses": TaskStatus.choices,
            "task_type": task_type or "",
            "status": status or "",
            "user_role": request.user.role,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def task_detail(request: HttpRequest, task_id: int) -> HttpResponse:
    """Детальная информация о задаче."""
    from django.contrib import messages
    from django.utils import timezone
    
    task = get_object_or_404(
        Task.objects.select_related("assigned_to", "created_by", "receiving", "inventory", "order", "picking_task"),
        id=task_id,
    )
    
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "start" and task.status == TaskStatus.PENDING:
            from .services import TaskService
            if TaskService.assign_task_to_user(task, request.user):
                messages.success(request, "Задача начата.")
            else:
                messages.error(request, "Не удалось начать задачу.")
            return redirect("task_detail", task_id=task_id)
        
        elif action == "complete" and task.status == TaskStatus.IN_PROGRESS:
            from .services import TaskService
            if TaskService.complete_task(task, request.user):
                messages.success(request, "Задача завершена.")
            else:
                messages.error(request, "Не удалось завершить задачу.")
            return redirect("task_detail", task_id=task_id)
    
    return render(request, "tasks/detail.html", {"task": task})
