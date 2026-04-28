from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.constants import Roles

# Create your views here.


def _paginate(request: HttpRequest, items, per_page: int = 5, page_param: str = "page"):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get(page_param))


@login_required
def me(request: HttpRequest) -> HttpResponse:
    user = request.user
    q = (request.GET.get("q") or "").strip()
    warehouses_qs = user.get_accessible_warehouses().select_related("branch").order_by("branch__code", "code")
    branches_qs = user.branches.filter(is_active=True).order_by("code")
    if q:
        warehouses_qs = warehouses_qs.filter(
            Q(code__icontains=q) | Q(name__icontains=q) | Q(branch__code__icontains=q) | Q(branch__name__icontains=q)
        )
        branches_qs = branches_qs.filter(
            Q(code__icontains=q) | Q(name__icontains=q) | Q(address__icontains=q)
        )
    warehouses_page_obj = _paginate(request, warehouses_qs, per_page=5, page_param="wh_page")
    branches_page_obj = _paginate(request, branches_qs, per_page=5, page_param="branch_page")

    role_descriptions = {
        Roles.ADMIN: "Полный доступ ко всем разделам и настройкам системы.",
        Roles.STOREKEEPER: "Операции приёмки, инвентаризации и контроль остатков.",
        Roles.SMALL_PARTS_PICKER: "Выполнение задач подбора по ячейкам и полкам.",
        Roles.LOADER: "Отгрузка и задачи по напольному хранению.",
        Roles.SALES_MANAGER: "Создание и контроль заказов клиентов.",
        Roles.ANALYST: "Отчёты, дашборды и складская аналитика.",
        Roles.INTEGRATION: "Технический доступ для API-интеграций.",
    }

    account_age_days = 0
    if user.date_joined:
        account_age_days = max((timezone.now() - user.date_joined).days, 0)

    quick_links = [
        {"label": "Дашборд", "url": reverse("dashboard"), "variant": "primary"},
        {"label": "Мои задачи", "url": reverse("task_list") + "?my_tasks=1", "variant": "ghost"},
        {"label": "Инструкция", "url": reverse("user_manual"), "variant": "ghost"},
    ]
    if user.role in (Roles.ANALYST, Roles.ADMIN) or user.is_superuser:
        quick_links.append({"label": "Отчёты", "url": reverse("reports_home"), "variant": "ghost"})

    context = {
        "user_obj": user,
        "role_label": user.get_role_display() or user.role,
        "role_description": role_descriptions.get(user.role, "Роль не описана."),
        "accessible_warehouses": warehouses_page_obj.object_list,
        "branches": branches_page_obj.object_list,
        "warehouses_count": warehouses_page_obj.paginator.count,
        "branches_count": branches_page_obj.paginator.count,
        "account_age_days": account_age_days,
        "quick_links": quick_links,
        "q": q,
        "warehouses_page_obj": warehouses_page_obj,
        "branches_page_obj": branches_page_obj,
    }
    return render(request, "accounts/me.html", context)
