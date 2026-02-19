from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.constants import Roles
from accounts.permissions import role_required


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Дашборд с ролевым интерфейсом."""
    from tasks.models import Task, TaskStatus, TaskType
    from tasks.services import TaskService
    from picking.models import PickingTask, PickingTaskStatus
    from receiving.models import Receiving, ReceivingStatus
    from inventory.models import Inventory, InventoryStatus
    from picking.models import Order, OrderStatus

    user = request.user

    role_switch_options = [
        (Roles.STOREKEEPER, "Кладовщик"),
        (Roles.SMALL_PARTS_PICKER, "Сборщик"),
        (Roles.LOADER, "Грузчик"),
        (Roles.SALES_MANAGER, "Менеджер"),
        (Roles.ANALYST, "Аналитик"),
    ]
    role_switch_codes = {code for code, _label in role_switch_options}
    role_label_map = dict(role_switch_options)

    is_admin_mode = user.is_superuser or user.role == Roles.ADMIN
    requested_role = request.GET.get("as_role")
    if is_admin_mode:
        effective_role = requested_role if requested_role in role_switch_codes else Roles.STOREKEEPER
    else:
        effective_role = user.role

    role_task_mapping = {
        Roles.STOREKEEPER: [TaskType.RECEIVING, TaskType.INVENTORY, TaskType.STOCK_MOVEMENT, TaskType.PICKING],
        Roles.SMALL_PARTS_PICKER: [TaskType.PICKING],
        Roles.LOADER: [TaskType.PICKING, TaskType.SHIPPING],
        Roles.SALES_MANAGER: [],
        Roles.ANALYST: [],
    }

    if is_admin_mode:
        dashboard_tasks = Task.objects.filter(task_type__in=role_task_mapping.get(effective_role, []))
    else:
        dashboard_tasks = TaskService.get_tasks_for_user(user)

    pending_tasks = dashboard_tasks.filter(status=TaskStatus.PENDING).count() or 0
    in_progress_tasks = dashboard_tasks.filter(status=TaskStatus.IN_PROGRESS).count() or 0
    total_active_tasks = pending_tasks + in_progress_tasks
    progress_percent = int((in_progress_tasks * 100) / total_active_tasks) if total_active_tasks else 0

    next_action = {
        "title": "Открыть задачи",
        "description": "Перейти к актуальным рабочим задачам.",
        "url": f"{reverse('task_list')}?my_tasks=1",
        "button": "К задачам",
    }

    dashboard_cards = []

    if effective_role == Roles.STOREKEEPER:
        pending_receivings = Receiving.objects.filter(status=ReceivingStatus.DRAFT).count()
        pending_inventories = Inventory.objects.filter(status=InventoryStatus.DRAFT).count()

        dashboard_cards = [
            {
                "title": "Мои задачи",
                "subtitle": "Активные задачи для выполнения",
                "icon": "tasks",
                "metrics": [
                    {"label": "Ожидают выполнения", "value": pending_tasks, "kind": "pending"},
                    {"label": "В работе", "value": in_progress_tasks, "kind": "in_progress"},
                ],
                "progress_percent": progress_percent,
                "actions": [
                    {"label": "Все задачи", "url": f"{reverse('task_list')}?my_tasks=1", "variant": "primary"},
                ],
            },
            {
                "title": "Приёмка",
                "subtitle": "Документы приёмки товара",
                "icon": "receiving",
                "metrics": [
                    {"label": "Ожидают обработки", "value": pending_receivings, "kind": "pending"},
                ],
                "actions": [
                    {"label": "Приёмки", "url": reverse("receiving_list"), "variant": "primary"},
                    {"label": "+ Новая приёмка", "url": reverse("receiving_create"), "variant": "ghost"},
                ],
            },
            {
                "title": "Инвентаризация",
                "subtitle": "Проверка остатков",
                "icon": "inventory",
                "metrics": [
                    {"label": "Ожидают начала", "value": pending_inventories, "kind": "pending"},
                ],
                "actions": [
                    {"label": "Инвентаризации", "url": reverse("inventory_list"), "variant": "primary"},
                    {"label": "+ Новая инвентаризация", "url": reverse("inventory_create"), "variant": "ghost"},
                ],
            },
        ]
        next_action = {
            "title": "Проверить приёмки",
            "description": "Сначала обработайте незакрытые документы приёмки.",
            "url": reverse("receiving_list"),
            "button": "Открыть приёмки",
        }

    if effective_role == Roles.SMALL_PARTS_PICKER:
        pending_picking_tasks = PickingTask.objects.filter(
            status=PickingTaskStatus.PENDING,
            zone_type_code__in=["CELL", "SHELF"],
        ).count()

        dashboard_cards = [
            {
                "title": "Задачи подбора",
                "subtitle": "Мелкие детали: ячейки и полки",
                "icon": "picking",
                "metrics": [
                    {"label": "Ожидают подбора", "value": pending_picking_tasks, "kind": "pending"},
                ],
                "actions": [
                    {"label": "Мои задачи", "url": reverse("picking_task_list"), "variant": "primary"},
                ],
            },
        ]
        next_action = {
            "title": "Начать подбор",
            "description": "Откройте список задач и возьмите первую доступную.",
            "url": reverse("picking_task_list"),
            "button": "К подбору",
        }

    if effective_role == Roles.LOADER:
        pending_shipping_tasks = Task.objects.filter(
            task_type=TaskType.SHIPPING,
            status=TaskStatus.PENDING,
        ).count()
        pending_floor_picking = PickingTask.objects.filter(
            status=PickingTaskStatus.PENDING,
            zone_type_code="FLOOR",
        ).count()

        dashboard_cards = [
            {
                "title": "Отгрузка",
                "subtitle": "Заказы, готовые к выдаче",
                "icon": "shipping",
                "metrics": [
                    {"label": "Ожидают отгрузки", "value": pending_shipping_tasks, "kind": "pending"},
                ],
                "actions": [
                    {"label": "Готовые заказы", "url": f"{reverse('order_list')}?status=PICKED", "variant": "primary"},
                ],
            },
            {
                "title": "Напольное хранение",
                "subtitle": "Паллеты и крупногабарит",
                "icon": "receiving",
                "metrics": [
                    {"label": "Задачи подбора", "value": pending_floor_picking, "kind": "pending"},
                ],
                "actions": [
                    {"label": "Задачи FLOOR", "url": f"{reverse('picking_task_list')}?zone_type=FLOOR", "variant": "primary"},
                ],
            },
        ]
        next_action = {
            "title": "Подготовить отгрузки",
            "description": "Проверьте готовые заказы и начните выдачу.",
            "url": f"{reverse('order_list')}?status=PICKED",
            "button": "К отгрузке",
        }

    if effective_role == Roles.SALES_MANAGER:
        pending_orders = Order.objects.filter(status=OrderStatus.DRAFT).count()
        confirmed_orders = Order.objects.filter(status=OrderStatus.CONFIRMED).count()

        dashboard_cards = [
            {
                "title": "Заказы",
                "subtitle": "Создание и контроль заказов",
                "icon": "orders",
                "metrics": [
                    {"label": "Черновики", "value": pending_orders, "kind": "pending"},
                    {"label": "Подтверждённые", "value": confirmed_orders, "kind": "in_progress"},
                ],
                "actions": [
                    {"label": "Все заказы", "url": reverse("order_list"), "variant": "primary"},
                    {"label": "+ Новый заказ", "url": reverse("order_create"), "variant": "ghost"},
                ],
            },
        ]
        next_action = {
            "title": "Открыть заказы",
            "description": "Обновите статусы и создайте новые заявки.",
            "url": reverse("order_list"),
            "button": "К заказам",
        }

    if effective_role == Roles.ANALYST:
        total_orders_shipped = Order.objects.filter(status=OrderStatus.SHIPPED).count()

        dashboard_cards = [
            {
                "title": "Статистика",
                "subtitle": "Ключевые отчёты и аналитика",
                "icon": "stats",
                "metrics": [
                    {"label": "Отгружено заказов", "value": total_orders_shipped, "kind": "completed"},
                ],
                "actions": [
                    {"label": "Открыть отчёты", "url": reverse("reports_home"), "variant": "primary"},
                ],
            },
        ]
        next_action = {
            "title": "Проверить отчёты",
            "description": "Сверьте динамику остатков и ошибок подбора.",
            "url": reverse("reports_home"),
            "button": "К отчётам",
        }

    first_warehouse = request.user.get_accessible_warehouses().first()
    warehouse_3d_url = reverse("warehouse_3d:view", args=[first_warehouse.id]) if first_warehouse else None

    quick_links = [
        {
            "title": "Справочники",
            "description": "Номенклатура, бренды, категории и зоны.",
            "url": reverse("catalog_admin_home"),
        },
        {
            "title": "Профиль",
            "description": "Настройки пользователя и роль.",
            "url": reverse("me"),
        },
    ]

    if warehouse_3d_url:
        quick_links.insert(
            1,
            {
                "title": "3D склад",
                "description": "Основной модуль 3D-склада для ежедневной работы.",
                "url": warehouse_3d_url,
            },
        )

    if effective_role == Roles.ANALYST:
        quick_links.append(
            {
                "title": "Отчёты",
                "description": "ABC-XYZ, мёртвые остатки, прогноз спроса.",
                "url": reverse("reports_home"),
            }
        )

    context = {
        "title": "Дашборд",
        "user_role": user.role,
        "effective_role": effective_role,
        "effective_role_label": role_label_map.get(effective_role, effective_role),
        "is_admin_mode": is_admin_mode,
        "dashboard_cards": dashboard_cards,
        "quick_links": quick_links,
        "role_switch_options": role_switch_options if is_admin_mode else [],
        "today_summary": {
            "pending_tasks": pending_tasks,
            "in_progress_tasks": in_progress_tasks,
            "progress_percent": progress_percent,
            "next_action": next_action,
        },
    }

    return render(request, "core/dashboard.html", context)


@role_required(Roles.ADMIN)
def integrations(request: HttpRequest) -> HttpResponse:
    return render(request, "core/integrations.html", {"title": "Интеграции"})


@login_required
def user_manual(request: HttpRequest) -> HttpResponse:
    context = _build_manual_context(request)
    return render(request, "core/user_manual.html", context)


@login_required
def user_manual_download(request: HttpRequest) -> HttpResponse:
    context = _build_manual_context(request)

    lines = [
        "WMS: Инструкция по работе",
        f"Дата выгрузки: {timezone.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        "=== Функционал по ролям ===",
    ]

    for role in context["role_cards"]:
        lines.append(f"- {role['role']}: {role['scope']}")
        for action in role["actions"]:
            lines.append(f"  • {action}")
        lines.append("")

    lines.append("=== Сквозной workflow ===")
    for step in context["workflow_steps"]:
        lines.append(f"- {step['title']}: {step['desc']}")
        lines.append(f"  URL: {step['url']}")
    lines.append("")

    lines.append("=== БД и API ===")
    for note in context["architecture_notes"]:
        lines.append(f"- {note}")

    content = "\n".join(lines)
    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="wms_manual_{timezone.now().strftime("%Y%m%d_%H%M")}.txt"'
    return response


def _build_manual_context(request: HttpRequest) -> dict:
    first_warehouse = request.user.get_accessible_warehouses().first()
    warehouse_3d_url = reverse("warehouse_3d:view", args=[first_warehouse.id]) if first_warehouse else None

    role_cards = [
        {
            "role": "Администратор",
            "scope": "Полный доступ ко всем разделам и данным.",
            "actions": [
                "Управление справочниками и ролями",
                "Контроль workflow по всем этапам",
                "Работа с 3D-складом и настройками",
            ],
        },
        {
            "role": "Кладовщик",
            "scope": "Приёмка, инвентаризация, операции по остаткам.",
            "actions": [
                "Создание и завершение приёмки",
                "Запуск и закрытие инвентаризации",
                "Проверка остатков и мест хранения",
            ],
        },
        {
            "role": "Сборщик мелких деталей",
            "scope": "Выполнение задач подбора по ячейкам и полкам.",
            "actions": [
                "Открытие задач подбора",
                "Сканирование/подтверждение подбора",
                "Закрытие выполненных задач",
            ],
        },
        {
            "role": "Грузчик",
            "scope": "Отгрузка и задачи по напольному хранению.",
            "actions": [
                "Подготовка заказов к выдаче",
                "Контроль задач FLOOR-зон",
                "Подтверждение отгрузки",
            ],
        },
        {
            "role": "Менеджер продаж",
            "scope": "Создание и подтверждение заказов.",
            "actions": [
                "Создание заказов и строк",
                "Подтверждение заказов",
                "Контроль статусов выполнения",
            ],
        },
        {
            "role": "Аналитик",
            "scope": "Отчётность и аналитика склада.",
            "actions": [
                "ABC-XYZ анализ",
                "Dead stock и ошибки подбора",
                "Прогноз спроса",
            ],
        },
    ]

    workflow_steps = [
        {
            "title": "1. Приёмка",
            "desc": "Кладовщик создаёт документ приёмки, добавляет строки, завершает приёмку.",
            "url": reverse("receiving_list"),
            "cta": "Открыть приёмку",
        },
        {
            "title": "2. Хранение и инвентаризация",
            "desc": "Остатки размещаются в местах хранения, затем периодически проверяются инвентаризацией.",
            "url": reverse("inventory_list"),
            "cta": "Открыть инвентаризацию",
        },
        {
            "title": "3. Заказы и подбор",
            "desc": "Менеджер подтверждает заказ, система создаёт задачи подбора по зонам.",
            "url": reverse("order_list"),
            "cta": "Открыть заказы",
        },
        {
            "title": "4. Отгрузка",
            "desc": "После завершения подбора заказ отгружается, остатки списываются.",
            "url": reverse("picking_task_list"),
            "cta": "Открыть задачи подбора",
        },
        {
            "title": "5. Аналитика",
            "desc": "Аналитик и администратор проверяют отчёты и ключевые показатели.",
            "url": reverse("reports_home"),
            "cta": "Открыть отчёты",
        },
    ]

    architecture_notes = [
        "Веб-страницы работают через Django Views и Django ORM (прямой серверный доступ к PostgreSQL).",
        "Браузер не подключается к базе данных напрямую.",
        "Для динамических сценариев используются внутренние JSON-эндпоинты (например, мониторинг задач, 3D-операции, EFP/TecDoc и отчётные API).",
        "3D-страница отправляет операции сохранения/удаления через HTTP-запросы к Django endpoint'ам, а уже сервер выполняет ORM-запросы в БД.",
    ]

    quick_links = [
        ("Дашборд", reverse("dashboard")),
        ("Мои задачи", reverse("task_list") + "?my_tasks=1"),
        ("Остатки", reverse("stock_list")),
        ("Справочники", reverse("catalog_admin_home")),
    ]
    if warehouse_3d_url:
        quick_links.append(("3D-склад", warehouse_3d_url))

    return {
        "title": "Инструкция по работе",
        "role_cards": role_cards,
        "workflow_steps": workflow_steps,
        "architecture_notes": architecture_notes,
        "quick_links": quick_links,
    }
