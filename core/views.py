import os
from html import escape
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from accounts.constants import ROLE_CHOICES, Roles
from accounts.permissions import role_required


@login_required
def role_redirect(request: HttpRequest) -> HttpResponse:
    """
    Smart redirect после логина:
    - Администратор → /control/ (кастомная админ-панель)
    - Все остальные → /         (рабочий дашборд)
    """
    user = request.user
    if user.is_superuser or getattr(user, "role", None) == Roles.ADMIN:
        return redirect("admin_panel:dashboard")
    return redirect("dashboard")


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

    # ----- KPI для верхнего ряда дашборда -----
    from django.db.models import Sum
    from inventory.models import Stock
    from receiving.models import ReceivingLine

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    kpi_received_today = (
        ReceivingLine.objects
        .filter(receiving__status=ReceivingStatus.COMPLETED, receiving__completed_at__gte=today_start)
        .aggregate(total=Sum("qty_received"))
        .get("total")
        or 0
    )
    kpi_total_sku = Stock.objects.values("product_id").distinct().count()
    kpi_errors = Stock.objects.filter(qty_available__lte=0).count()

    # Базовый next_action — берём следующую доступную задачу одним кликом
    next_action = {
        "title": "Взять следующую задачу",
        "description": "Открывает уже начатую вами задачу либо назначает первую свободную из очереди.",
        "url": reverse("next_task"),
        "button": "Взять задачу",
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
            "title": "Взять следующую задачу",
            "description": "Берёт следующую задачу по приоритету и открывает её страницу.",
            "url": reverse("next_task"),
            "button": "Взять задачу",
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
            "title": "Взять следующую задачу",
            "description": "Назначает на вас первую свободную задачу подбора и открывает её.",
            "url": reverse("next_task"),
            "button": "Взять задачу",
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
            "title": "Взять следующую задачу",
            "description": "Берёт ближайшую задачу подбора или отгрузки.",
            "url": reverse("next_task"),
            "button": "Взять задачу",
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
            "title": "Профиль",
            "description": "Настройки пользователя и роль.",
            "url": reverse("me"),
        },
    ]

    if is_admin_mode:
        quick_links.insert(
            0,
            {
                "title": "Справочники",
                "description": "Номенклатура, бренды, категории и зоны.",
                "url": reverse("catalog_admin_home"),
            },
        )

    if warehouse_3d_url:
        quick_links.insert(
            1 if is_admin_mode else 0,
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
        "kpi_received_today": kpi_received_today,
        "kpi_total_sku": kpi_total_sku,
        "kpi_errors": kpi_errors,
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
    role_map = {item["code"]: item for item in context["role_cards"]}

    requested_role = (request.GET.get("role") or "").strip().upper()
    user_role = getattr(request.user, "role", "")
    if requested_role in role_map:
        selected_role_code = requested_role
    elif user_role in role_map:
        selected_role_code = user_role
    else:
        selected_role_code = next(iter(role_map.keys()))

    selected_role = role_map[selected_role_code]
    pdf_content = _build_manual_pdf(
        role=selected_role,
        workflow_steps=context["workflow_steps"],
        work_principles=context["work_principles"],
    )

    response = HttpResponse(pdf_content, content_type="application/pdf")
    filename = f"wms_manual_{selected_role_code.lower()}_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _build_manual_context(request: HttpRequest) -> dict:
    first_warehouse = request.user.get_accessible_warehouses().first()
    warehouse_3d_url = reverse("warehouse_3d:view", args=[first_warehouse.id]) if first_warehouse else None

    all_role_cards = _get_manual_role_cards(warehouse_3d_url)
    user_role = getattr(request.user, "role", "")
    is_admin_mode = bool(request.user.is_superuser or user_role == Roles.ADMIN)

    if is_admin_mode:
        role_cards = all_role_cards
    else:
        role_cards = [card for card in all_role_cards if card["code"] == user_role]
        if not role_cards:
            # Безопасный fallback, если роль отсутствует в справочнике.
            role_cards = [card for card in all_role_cards if card["code"] == Roles.STOREKEEPER]

    workflow_steps = [
        {
            "title": "1. Начните смену с задач",
            "desc": "Откройте список задач, возьмите приоритетные и проверьте сроки выполнения.",
            "url": reverse("task_list") + "?my_tasks=1",
            "cta": "Открыть мои задачи",
        },
        {
            "title": "2. Выполняйте операции по своему этапу",
            "desc": "Работайте в роли: приёмка, инвентаризация, подбор, отгрузка или контроль заказов.",
            "url": reverse("dashboard"),
            "cta": "Открыть дашборд",
        },
        {
            "title": "3. Фиксируйте фактический результат",
            "desc": "Вносите реальные количества, места хранения и статусы без пропусков и допущений.",
            "url": reverse("task_list") + "?my_tasks=1",
            "cta": "Вернуться к задачам",
        },
        {
            "title": "4. Завершайте этап и передавайте дальше",
            "desc": "Закрывайте документ только после проверки, затем передавайте работу следующей роли.",
            "url": reverse("task_list") + "?my_tasks=1",
            "cta": "Проверить статус задач",
        },
    ]

    work_principles = [
        "Работайте только в рамках своей роли и назначенных задач.",
        "Перед началом операции проверяйте исходные данные документа и статус.",
        "Фиксируйте только фактические значения: количество, место, результат выполнения.",
        "При расхождениях оформляйте комментарий и не закрывайте этап без проверки.",
        "В конце смены проверьте, что незавершённые задачи переведены в корректный статус.",
    ]

    quick_links = [("Дашборд", reverse("dashboard"))]
    if is_admin_mode or user_role in {Roles.STOREKEEPER, Roles.SMALL_PARTS_PICKER, Roles.LOADER}:
        quick_links.append(("Мои задачи", reverse("task_list") + "?my_tasks=1"))
    if is_admin_mode or user_role == Roles.STOREKEEPER:
        quick_links.append(("Приёмка", reverse("receiving_list")))
        quick_links.append(("Инвентаризация", reverse("inventory_list")))
        quick_links.append(("Остатки", reverse("stock_list")))
    if is_admin_mode or user_role == Roles.SALES_MANAGER:
        quick_links.append(("Заказы", reverse("order_list")))
    if is_admin_mode or user_role in {Roles.SMALL_PARTS_PICKER, Roles.LOADER}:
        quick_links.append(("Задачи подбора", reverse("picking_task_list")))
    if is_admin_mode or user_role == Roles.ANALYST:
        quick_links.append(("Отчёты", reverse("reports_home")))
    if is_admin_mode:
        quick_links.append(("Справочники", reverse("catalog_admin_home")))

    if warehouse_3d_url:
        quick_links.append(("3D-склад", warehouse_3d_url))

    role_choices = [
        {
            "code": card["code"],
            "label": card["role"],
            "scope": card["scope"],
        }
        for card in role_cards
    ]

    return {
        "title": "Инструкция по работе",
        "role_cards": role_cards,
        "role_choices": role_choices,
        "allow_role_switch": is_admin_mode,
        "workflow_steps": workflow_steps,
        "work_principles": work_principles,
        "quick_links": quick_links,
    }


def _get_manual_role_cards(warehouse_3d_url: str | None) -> list[dict]:
    cards_by_role = {
        Roles.ADMIN: {
            "scope": "Полный доступ ко всем разделам и данным.",
            "actions": [
                "Управление справочниками, ролями и филиалами",
                "Контроль workflow: приёмка, подбор, отгрузка, инвентаризация",
                "Настройка интеграций, API и фоновых процессов",
            ],
            "daily_flow": [
                "Проверить дашборд и узкие места по задачам.",
                "Проконтролировать критические документы приёмки и отгрузки.",
                "Проверить ошибки подбора, отчёты и корректность данных.",
            ],
            "key_pages": [
                ("Дашборд", reverse("dashboard")),
                ("Справочники", reverse("catalog_admin_home")),
                ("Отчёты", reverse("reports_home")),
                ("Интеграции", reverse("integrations")),
            ],
        },
        Roles.STOREKEEPER: {
            "scope": "Приёмка, инвентаризация и операции по остаткам.",
            "actions": [
                "Создание и заполнение приёмки товара",
                "Добавление строк и размещение товара по местам хранения",
                "Запуск и закрытие инвентаризаций",
            ],
            "daily_flow": [
                "Открыть список приёмок и взять документ в работу.",
                "Проверить поставщика, добавить товары, подтвердить фактическое количество.",
                "Завершить приёмку и убедиться, что остатки обновились.",
            ],
            "key_pages": [
                ("Мои задачи", reverse("task_list") + "?my_tasks=1"),
                ("Приёмка", reverse("receiving_list")),
                ("Инвентаризация", reverse("inventory_list")),
                ("Остатки", reverse("stock_list")),
            ],
        },
        Roles.SMALL_PARTS_PICKER: {
            "scope": "Подбор по ячейкам и полкам (CELL/SHELF).",
            "actions": [
                "Открытие задач подбора и принятие в работу",
                "Подтверждение подбора деталей по строкам",
                "Фиксация результатов и закрытие задач",
            ],
            "daily_flow": [
                "Открыть список задач подбора и выбрать приоритетные.",
                "Сканировать/подтверждать позиции по маршруту.",
                "Передать выполненный заказ на этап отгрузки.",
            ],
            "key_pages": [
                ("Мои задачи", reverse("task_list") + "?my_tasks=1"),
                ("Задачи подбора", reverse("picking_task_list")),
                ("Заказы", reverse("order_list")),
            ],
        },
        Roles.LOADER: {
            "scope": "Отгрузка и обработка напольных зон (FLOOR).",
            "actions": [
                "Подготовка заказов к выдаче клиенту",
                "Работа с крупногабаритными позициями и FLOOR-задачами",
                "Подтверждение отгрузки по задаче SHIPPING или из карточки заказа",
            ],
            "daily_flow": [
                "Открыть 'Мои задачи' и взять в работу задачу типа 'Отгрузка'.",
                "Собрать и перепроверить комплектность для отгрузки.",
                "Подтвердить отгрузку и убедиться, что заказ перешёл в статус 'Отгружен'.",
            ],
            "key_pages": [
                ("Заказы (готовые)", reverse("order_list") + "?status=PICKED"),
                ("Задачи FLOOR", reverse("picking_task_list") + "?zone_type=FLOOR"),
                ("Мои задачи", reverse("task_list") + "?my_tasks=1"),
            ],
        },
        Roles.SALES_MANAGER: {
            "scope": "Создание, проверка и подтверждение заказов.",
            "actions": [
                "Создание заказа и добавление строк",
                "Проверка доступности и статусов выполнения",
                "Подтверждение и передача в складской workflow",
            ],
            "daily_flow": [
                "Создать/обновить заказы клиентов.",
                "Проверить статус подбора и согласовать изменения.",
                "Контролировать прохождение до отгрузки.",
            ],
            "key_pages": [
                ("Заказы", reverse("order_list")),
                ("Создать заказ", reverse("order_create")),
                ("Мои задачи", reverse("task_list") + "?my_tasks=1"),
            ],
        },
        Roles.ANALYST: {
            "scope": "Отчётность, KPI и контроль качества процессов.",
            "actions": [
                "ABC/XYZ анализ и контроль оборачиваемости",
                "Анализ ошибок подбора и узких мест",
                "Построение прогноза спроса",
            ],
            "daily_flow": [
                "Открыть отчёты и проверить ключевые метрики.",
                "Выявить отклонения по остаткам и ошибкам подбора.",
                "Сформировать рекомендации для команды.",
            ],
            "key_pages": [
                ("Отчёты", reverse("reports_home")),
                ("ABC/XYZ", reverse("report_abc_xyz")),
                ("Ошибки подбора", reverse("report_picking_errors")),
            ],
        },
        Roles.INTEGRATION: {
            "scope": "Техническая роль для API и фоновых сервисов.",
            "actions": [
                "Поддержка интеграций с внешними сервисами",
                "Мониторинг очередей и фоновых задач",
                "Проверка корректности обмена данными",
            ],
            "daily_flow": [
                "Проверить доступность API и очередь задач.",
                "Проконтролировать ошибки интеграций и повторные попытки.",
                "Подтвердить целостность данных после обмена.",
            ],
            "key_pages": [
                ("Интеграции", reverse("integrations")),
                ("API документация", reverse("api_v1_docs")),
            ],
        },
    }

    if warehouse_3d_url:
        role_cards_3d = [Roles.ADMIN, Roles.STOREKEEPER, Roles.LOADER]
        for role_code in role_cards_3d:
            role = cards_by_role.get(role_code)
            if role is not None:
                role["key_pages"].append(("3D-склад", warehouse_3d_url))

    cards: list[dict] = []
    for role_code, role_label in ROLE_CHOICES:
        payload = cards_by_role.get(role_code)
        if payload is None:
            continue
        cards.append(
            {
                "code": role_code,
                "role": role_label,
                "scope": payload["scope"],
                "actions": payload["actions"],
                "daily_flow": payload["daily_flow"],
                "key_pages": payload["key_pages"],
            }
        )
    return cards


def _build_manual_pdf(*, role: dict, workflow_steps: list[dict], work_principles: list[str]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"WMS Manual - {role['role']}",
    )

    font_name = _resolve_pdf_font_name()
    styles = {
        "title": ParagraphStyle(
            "title",
            fontName=font_name,
            fontSize=15,
            leading=20,
            spaceAfter=8,
        ),
        "meta": ParagraphStyle(
            "meta",
            fontName=font_name,
            fontSize=9,
            textColor="#5f697f",
            leading=12,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName=font_name,
            fontSize=12,
            leading=16,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "text": ParagraphStyle(
            "text",
            fontName=font_name,
            fontSize=10,
            leading=14,
            spaceAfter=2,
        ),
    }

    story = [
        Paragraph("WMS: Инструкция по работе", styles["title"]),
        Paragraph(f"Роль: {escape(role['role'])}", styles["text"]),
        Paragraph(f"Дата выгрузки: {timezone.now().strftime('%d.%m.%Y %H:%M')}", styles["meta"]),
        Paragraph("Зона ответственности", styles["h2"]),
        Paragraph(escape(role["scope"]), styles["text"]),
        Paragraph("Основные действия", styles["h2"]),
    ]

    for action in role["actions"]:
        story.append(Paragraph(f"• {escape(action)}", styles["text"]))

    story.append(Paragraph("Ежедневный сценарий", styles["h2"]))
    for idx, step in enumerate(role["daily_flow"], start=1):
        story.append(Paragraph(f"{idx}. {escape(step)}", styles["text"]))

    story.append(Paragraph("Ключевые страницы", styles["h2"]))
    for label, url in role["key_pages"]:
        story.append(Paragraph(f"• {escape(label)}: {escape(url)}", styles["text"]))

    story.append(Spacer(1, 6))
    story.append(Paragraph("Пошаговая работа сотрудника", styles["h2"]))
    for step in workflow_steps:
        story.append(Paragraph(f"• {escape(step['title'])}: {escape(step['desc'])}", styles["text"]))
        story.append(Paragraph(f"URL: {escape(step['url'])}", styles["meta"]))

    story.append(Paragraph("Правила работы в программе", styles["h2"]))
    for note in work_principles:
        story.append(Paragraph(f"• {escape(note)}", styles["text"]))

    doc.build(story)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data


def _resolve_pdf_font_name() -> str:
    font_name = "WMSManualFont"
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name

    candidates = [
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "calibri.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for font_path in candidates:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            return font_name
    return "Helvetica"


def permission_denied_view(request: HttpRequest, exception=None) -> HttpResponse:
    message = "У вас нет доступа к этой странице."
    if exception:
        message = str(exception)
    return render(
        request,
        "errors/403.html",
        {
            "title": "Нет доступа",
            "error_message": message,
        },
        status=403,
    )
